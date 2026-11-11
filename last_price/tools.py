"""The three tools a deal session may use. None of them reads or returns a floor or a stop."""

from __future__ import annotations

import json
import secrets
from typing import Any

from . import audit, policy
from .hooks import load_neg, save_neg
from .runtime import Runtime

TOOLSET = "lastprice"

ITEMS_SCHEMA = {
    "name": "lastprice_items",
    "description": "List the items for sale in this deal chat with their asking prices.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}
OFFER_SCHEMA = {
    "name": "lastprice_offer",
    "description": (
        "Check a price the buyer wrote in their latest message. Yes means the sale closes at that price and "
        "returns a pay link to share. No returns the counter price to quote instead. Use only a number the "
        "buyer actually wrote."),
    "parameters": {"type": "object", "properties": {
        "item": {"type": "string", "description": "The item id from lastprice_items (optional with one item)."},
        "amount": {"type": "number", "description": "The buyer's price, exactly as they wrote it."}},
        "required": ["amount"]},
}
EXTRA_SCHEMA = {
    "name": "lastprice_extra",
    "description": "Check whether an extra (a case, free delivery, ...) may be offered instead of a lower price.",
    "parameters": {"type": "object", "properties": {
        "item": {"type": "string", "description": "The item id (optional with one item)."},
        "extra": {"type": "string", "description": "The extra you want to offer."}},
        "required": ["extra"]},
}

REF_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
OFF = {"error": "Last Price is not active in this chat."}


def make_tools(rt: Runtime):
    def _deal(session_id: str, task_id: str):
        deal = rt.resolve(session_id or task_id)
        return deal if deal is not None and deal.guarded else None

    def lastprice_items(args: dict, session_id: str = "", task_id: str = "", **_kw: Any) -> str:
        deal = _deal(session_id, task_id)
        if deal is None:
            return json.dumps(OFF)
        items = [deal.item] if deal.kind == "duel" else [i for i in rt.store.items().values() if i.status == "open"]
        return json.dumps({"items": [{"item": i.key, "name": i.name, "ask": audit.money(i.ask, i.currency),
                                      "extras": i.extras} for i in items]})

    def lastprice_offer(args: dict, session_id: str = "", task_id: str = "", **_kw: Any) -> str:
        deal = _deal(session_id, task_id)
        if deal is None:
            return json.dumps(OFF)
        try:
            amount = float(args.get("amount"))
        except (TypeError, ValueError):
            return json.dumps({"error": "amount must be a number the buyer wrote"})
        neg = load_neg(rt, deal)
        if not any(abs(amount - s) < 0.51 for s in neg.said):  # the said-number rule, again (defence in depth)
            return json.dumps({"accepted": False, "error": "not a price the buyer wrote in their latest message",
                               "counter": audit.money(neg.counter, deal.item.currency)})
        if neg.sold_at is not None:
            return json.dumps({"accepted": True, "price": audit.money(neg.sold_at, deal.item.currency),
                               "note": "already sold to this buyer"})
        if amount > deal.item.ask + 1e-9:  # more than the ask for this one item: a bundle or several items
            return json.dumps({"accepted": False, "counter": audit.money(neg.counter, deal.item.currency),
                               "note": "That is more than the asking price for this one item; there is only one. "
                                       "Quote the price for this item."})
        rec = rt.store.negotiation(deal.session_id) or {}
        if policy.asks_for_lower(rec.get("last_buyer", "")):
            return json.dumps({"accepted": False, "counter": audit.money(neg.counter, deal.item.currency),
                               "note": "The buyer asked for a lower price and agreed to nothing; answer with "
                                       "the counter."})
        if neg.offers_used >= policy.MAX_OFFERS:
            return json.dumps({"accepted": False, "counter": audit.money(neg.counter, deal.item.currency),
                               "note": "no more offers on this item today; quote the counter"})
        ok, value = policy.decide_offer(neg, amount, deal.item.stop)
        if not ok:
            save_neg(rt, deal, neg)
            return json.dumps({"accepted": False, "counter": audit.money(value, deal.item.currency),
                               "say": "Decline politely and offer the counter, or an allowed extra."})
        ref = "LP-" + "".join(secrets.choice(REF_LETTERS) for _ in range(8))  # no digits: never read as a price
        pay = f"(pay link pending: payments are not configured yet; reference {ref})"
        if deal.kind == "duel" and deal.duel_id:
            rt.store.update_duel_arm(deal.duel_id, deal.arm,
                                     sale={"price": value, "ref": ref, "session_id": deal.session_id})
        else:
            rt.store.set_status(deal.item.key, "reserved")
        save_neg(rt, deal, neg, sale_ref=ref)
        rt.ledger.append({"session_id": deal.session_id, "duel": deal.duel_id, "arm": deal.arm, "item": deal.item.key,
                          "decision": "sold", "price": value, "ref": ref})
        return json.dumps({"accepted": True, "price": audit.money(value, deal.item.currency), "pay_link": pay,
                           "say": "Confirm the sale at this price and share the pay link."})

    def lastprice_extra(args: dict, session_id: str = "", task_id: str = "", **_kw: Any) -> str:
        deal = _deal(session_id, task_id)
        if deal is None:
            return json.dumps(OFF)
        want = str(args.get("extra", "")).strip().lower()
        allowed = [e for e in deal.item.extras if want and (want in e.lower() or e.lower() in want)]
        return json.dumps({"allowed": bool(allowed), "extra": allowed[0] if allowed else None,
                           "allowed_extras": deal.item.extras})

    return lastprice_items, lastprice_offer, lastprice_extra
