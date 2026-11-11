"""Items, owners, negotiations and duels in Hermes's profile-scoped plugin state (``ctx.state``).

Only this module reads a floor or a stop, and only two callers ask for them: the policy and the
audit (``stop``), and ``reveal`` (the floor, for the owner). Nothing here formats either into a
string that reaches a model, a tool result, a log line or the ledger (tests/test_secrecy.py).
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from . import policy

SCHEMA = 1


class MemoryState:
    """``ctx.state``'s get/set contract in memory (tests, and the CLI fallback)."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value


def commitment(floor: float, salt: str) -> str:
    """sha256("<floor>:<salt>"), the floor's public commitment."""
    return hashlib.sha256(f"{_num(floor)}:{salt}".encode("utf-8")).hexdigest()


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{float(x):.2f}"


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return (s or "item")[:48]


def _key(prefix: str, ident: str) -> str:
    ident = str(ident)
    if len(prefix) + 1 + len(ident) > 120 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", ident):
        ident = hashlib.sha256(ident.encode("utf-8")).hexdigest()[:40]
    return f"{prefix}:{ident}"


@dataclass
class Item:
    key: str
    name: str
    ask: float
    floor: float
    stop: float
    salt: str
    commit: str
    currency: str = "USD"
    extras: list = field(default_factory=list)
    status: str = "open"  # open | reserved | sold
    created: float = 0.0

    def public(self) -> dict:
        """What a model, a tool result or a log may see: never the floor, the stop or the salt."""
        return {"item": self.key, "name": self.name, "ask": self.ask, "currency": self.currency,
                "extras": list(self.extras), "status": self.status}


class Store:
    """Typed access over a ``get``/``set`` state object (``ctx.state`` in Hermes)."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend

    # ---- items ------------------------------------------------------------------------------
    def items(self) -> dict[str, Item]:
        raw = self.backend.get("items", {}) or {}
        return {k: Item(**v) for k, v in raw.items()}

    def item(self, key_or_name: Optional[str] = None) -> Optional[Item]:
        items = self.items()
        if not items:
            return None
        if not key_or_name:
            open_items = [i for i in items.values() if i.status == "open"] or list(items.values())
            return max(open_items, key=lambda i: i.created)
        k = slug(key_or_name)
        if k in items:
            return items[k]
        hits = [i for i in items.values() if k in i.key or i.key in k]
        return hits[0] if len(hits) == 1 else None

    def sell(self, name: str, ask: float, floor: float, *, currency: str = "USD", extras: Optional[list] = None,
             rng=None) -> Item:
        if not (ask > 0 and floor > 0):
            raise ValueError("ask and floor must be positive numbers")
        if floor > ask:
            raise ValueError("the floor must not be above the ask")
        salt = secrets.token_hex(16)
        stop = policy.draw_stop(ask, floor, rng)
        it = Item(key=slug(name), name=name.strip(), ask=float(ask), floor=float(floor), stop=stop, salt=salt,
                  commit=commitment(floor, salt), currency=currency.upper(), extras=list(extras or []),
                  created=time.time())
        raw = self.backend.get("items", {}) or {}
        raw[it.key] = dict(it.__dict__)
        self.backend.set("items", raw)
        return it

    def set_status(self, key: str, status: str) -> None:
        raw = self.backend.get("items", {}) or {}
        if key in raw:
            raw[key]["status"] = status
            self.backend.set("items", raw)

    # ---- shop, owners, rates ----------------------------------------------------------------
    def shop_open(self) -> bool:
        return bool((self.backend.get("shop", {}) or {}).get("open", True))

    def set_shop_open(self, value: bool) -> None:
        self.backend.set("shop", {"open": bool(value)})

    def owners(self) -> list[str]:
        return list(self.backend.get("owners", []) or [])

    def add_owner(self, ident: str) -> None:
        owners = self.owners()
        if ident not in owners:
            owners.append(ident)
        self.backend.set("owners", owners)

    def rates(self) -> dict:
        return dict(self.backend.get("rates", {}) or {})

    # ---- negotiations (one per session) -----------------------------------------------------
    def negotiation(self, session_id: str) -> Optional[dict]:
        return self.backend.get(_key("neg", session_id))

    def save_negotiation(self, session_id: str, record: dict) -> None:
        self.backend.set(_key("neg", session_id), record)

    # ---- duels ------------------------------------------------------------------------------
    def new_duel(self, item_key: str, arms: list[str]) -> dict:
        duel_id = secrets.token_hex(6)
        rec = {"id": duel_id, "item": item_key, "created": time.time(), "expires": time.time() + 6 * 3600,
               "arms": {arm: {"title": f"lastprice-duel-{duel_id}-{arm}", "sale": None, "session_id": None}
                        for arm in arms}}
        self.backend.set(_key("duel", duel_id), rec)
        return rec

    def duel(self, duel_id: str) -> Optional[dict]:
        """The duel record, with each arm's own record (session, sale) merged in."""
        rec = self.backend.get(_key("duel", duel_id))
        if rec and rec.get("expires", 0) < time.time():
            return None
        if rec:
            for arm, fields in (rec.get("arms") or {}).items():
                fields.update(self.backend.get(_key("arm", f"{duel_id}-{arm}")) or {})
        return rec

    def update_duel_arm(self, duel_id: str, arm: str, **fields: Any) -> None:
        """One arm's session binding and sale live under their own key, so the two arms of a duel,
        playing at the same time in Hermes, never overwrite each other's writes."""
        key = _key("arm", f"{duel_id}-{arm}")
        cur = self.backend.get(key) or {}
        cur.update(fields)
        self.backend.set(key, cur)

    def save_duel(self, rec: dict) -> None:
        self.backend.set(_key("duel", rec["id"]), rec)


DUEL_TITLE = re.compile(r"^lastprice-duel-([0-9a-f]{12})-(lp|stock)$")
