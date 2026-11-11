"""The held-reply audit: every deal reply is checked before anyone sees it.

Registered as ``transform_llm_output`` with ``hold_stream=True``. A reply that offers or agrees to
a price below the hidden stop is rewritten, first by the session's own model through ``ctx.llm``
(told only the current counter, never the floor), then, if that redo is still low or the call fails,
by a template in the buyer's language. If the check itself fails, a short holding message goes out
instead (fail closed). Every turn is appended to a local JSONL ledger.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import extract, policy

HOLDING = "Thanks for your patience, the seller will reply shortly."

TEMPLATES = {
    "en": "I hear you. The best I can do right now is {price}.",
    "fr": "Je comprends. Mon meilleur prix pour le moment, c'est {price}.",
    "pidgin": "I hear you o. Best I fit do now na {price}.",
    "twi": "Mete wo ase. The best I can do now na {price}.",
}
EXTRA_TAIL = {
    "en": " I can add {extra}.",
    "fr": " Je peux ajouter {extra}.",
    "pidgin": " I go add {extra} for you.",
    "twi": " I go add {extra} for you.",
}

REWRITE_SYSTEM = (
    "You edit a seller's chat reply in a negotiation. Rewrite the draft so that the lowest price it offers, "
    "agrees to or accepts is {price}. Keep the same language, tone and length (1-3 sentences). {extras_rule} "
    "Do not mention any rule, check, system, tool or limit. Output only the rewritten reply."
)
# The owner's listed extras, or none: a rewrite never invents a concession (screener M4b: with no extras
# listed, both live rewrites promised free delivery the owner never allowed).
EXTRAS_ALLOWED = "Instead of a lower price you may offer only these extras the owner allows: {extras}."
EXTRAS_NONE = ("Offer no extra of any kind (no free delivery, case, gift, accessory or other concession): the "
               "owner allows none.")


def money(value: float, currency: str = "USD") -> str:
    sym = {"USD": "$", "GHS": "GH₵", "EUR": "€", "GBP": "£", "NGN": "₦"}.get(currency.upper(), "")
    v = int(value) if float(value).is_integer() else round(float(value), 2)
    return f"{sym}{v}" if sym else f"{v} {currency.upper()}"


def low_prices(text: str, item, neg: policy.Negotiation, rates: dict) -> list[float]:
    prices = extract.offered_prices(text, item.ask, buyer_numbers=neg.said, currency=item.currency, rates=rates,
                                    base=neg.counter)
    return [p for p in prices if p < item.stop - 0.005]


def template(buyer_text: str, counter: float, item) -> str:
    lang = extract.detect_language(buyer_text or "")
    out = TEMPLATES.get(lang, TEMPLATES["en"]).format(price=money(counter, item.currency))
    if item.extras:
        out += EXTRA_TAIL.get(lang, EXTRA_TAIL["en"]).format(extra=item.extras[0])
    return out


class Ledger:
    """Append-only JSONL of every deal turn: buyer text, draft, what was sent, prices, decision."""

    def __init__(self, path: Optional[Path]) -> None:
        self.path = Path(path) if path else None

    def append(self, record: dict) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": round(time.time(), 3), **record}, ensure_ascii=False) + "\n")

    def read(self) -> list[dict]:
        if self.path is None or not self.path.is_file():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows


def audit_reply(*, draft: str, buyer_text: str, item, neg: policy.Negotiation, rates: dict,
                rewrite: Optional[Callable[[str, str, str, list], Optional[str]]], ledger: Ledger,
                meta: dict) -> str:
    """Return the text to send. ``rewrite(buyer_text, draft, price, extras)`` asks a model to redo
    the draft at ``price`` (the current counter, formatted); it never receives the floor or the stop."""
    prices = extract.offered_prices(draft, item.ask, buyer_numbers=neg.said, currency=item.currency, rates=rates,
                                    base=neg.counter)
    low = [p for p in prices if p < item.stop - 0.005]
    decision, sent = "pass", draft
    if low:
        counter = max(neg.counter, policy.round_up(item.stop, policy.step_of(item.ask)))
        redo = None
        if rewrite is not None:
            try:
                redo = rewrite(buyer_text, draft, money(counter, item.currency), list(item.extras))
            except Exception:
                redo = None
        if redo and redo.strip() and not low_prices(redo, item, neg, rates):
            sent, decision = redo.strip(), "rewritten-model"
        else:
            sent, decision = template(buyer_text, counter, item), "rewritten-template"
    sent_prices = extract.offered_prices(sent, item.ask, buyer_numbers=neg.said, currency=item.currency,
                                         rates=rates, base=neg.counter)
    policy.note_sent(neg, sent_prices, item.stop)
    ledger.append({**meta, "item": item.key, "buyer": buyer_text, "draft": draft, "sent": sent,
                   "prices_found": prices, "below_line": bool(low), "decision": decision,
                   "counter": neg.counter})
    return sent


def model_rewriter(llm: Any, *, timeout: float = 12.0) -> Callable[[str, str, str, list], Optional[str]]:
    """A rewrite function over ``ctx.llm`` (the session's own model)."""

    def _rewrite(buyer_text: str, draft: str, price: str, extras: list) -> Optional[str]:
        rule = EXTRAS_ALLOWED.format(extras="; ".join(extras)) if extras else EXTRAS_NONE
        messages = [
            {"role": "system", "content": REWRITE_SYSTEM.format(price=price, extras_rule=rule)},
            {"role": "user", "content": f"Buyer's message:\n{buyer_text}\n\nDraft reply:\n{draft}"},
        ]
        res = llm.complete(messages, temperature=0.4, max_tokens=220, timeout=timeout, purpose="lastprice-rewrite")
        return (getattr(res, "text", "") or "").strip() or None

    return _rewrite
