"""Shared plugin runtime: the state store, the ledger, the model handle and the deal-session map.

A session is a *deal session* when either
* it is a Last Price duel arm: its title (set by ``hermes chat -c <title> --create-if-missing``,
  user provenance, so auto-titling never overwrites it) is ``lastprice-duel-<id>-lp|stock`` and the
  duel ``<id>`` exists in this profile's plugin state; or
* it is a messaging chat on a platform the owner opened with ``hermes lastprice shop on <platform>``,
  from a sender who is not an owner.
The ``lp`` arm and shop chats are guarded; the ``stock`` arm is the duel's unguarded baseline.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .audit import Ledger
from .state import DUEL_TITLE, Item, Store

LOCAL_SURFACES = {"cli", "tui", "desktop", "local", "acp", "api_server", "cron", "oneshot", "tool", ""}
# Surfaces where a human is typing at their own machine. Only these (plus owner ids added with
# `hermes lastprice owner add`) may set, list or reveal floors. Not api_server (a network client),
# cron (scheduled, model-driven), tool (called from inside an agent turn) or "" (unknown).
OWNER_SURFACES = {"cli", "tui", "desktop", "local", "acp", "oneshot"}
TOOL_NAMES = ("lastprice_items", "lastprice_offer", "lastprice_extra")
# Hermes's tool-search bridge. tool_search / tool_describe are catalog reads scoped to the session's
# toolsets; a tool_call that resolves is unwrapped BEFORE pre_tool_call, so the hook sees the real tool
# (agent/tool_executor.py:390-425), and one that reaches the hook as "tool_call" is unresolved or out of
# scope and fails on its own. Connector batches run pre_tool_call per entry.
BRIDGE_NAMES = ("tool_search", "tool_describe", "tool_call")


class Refusal(str):
    """A command reply that refuses to act. ``hermes lastprice`` prints it and exits ``REFUSED_EXIT``."""


REFUSED_EXIT = 1


@dataclass
class Deal:
    session_id: str
    kind: str  # duel | chat
    arm: str  # lp | stock
    item: Item
    duel_id: Optional[str] = None
    challenge: Optional[str] = None  # the public challenge this chat belongs to (last_price/challenge.py)

    @property
    def guarded(self) -> bool:
        return self.arm == "lp"


def _session_title(session_id: str) -> tuple[Optional[str], Optional[str]]:
    """(title, title_source) through the public ``hermes_state.SessionDB`` (read-only)."""
    from hermes_state import SessionDB

    db = SessionDB(read_only=True)
    return db.get_session_title(session_id), db.get_session_title_source(session_id)


class Runtime:
    def __init__(self, backend: Any, *, data_dir: Optional[Path] = None, llm: Any = None,
                 llm_factory: Optional[Callable[[], Any]] = None,
                 title_lookup: Optional[Callable[[str], tuple[Optional[str], Optional[str]]]] = None) -> None:
        self.store = Store(backend)
        self.data_dir = Path(data_dir) if data_dir else None
        self.ledger = Ledger(self.data_dir / "ledger.jsonl" if self.data_dir else None)
        self.llm_value = llm
        self.llm_factory = llm_factory
        self.title_lookup = title_lookup or _session_title
        self._deals: dict[str, tuple[Optional[Deal], float]] = {}
        self._lock = threading.Lock()
        self.has_capability: Optional[Callable[[str], bool]] = None  # ctx.has_capability, when Hermes gives one
        self.memory_gate: dict = {}  # challenge.gate_open: {profile home: (memory off?, when read)}
        self.memory_held: set[str] = set()  # stranger chats held while memory was on (challenge.chat_allowed)

    @property
    def llm(self) -> Any:
        """``ctx.llm`` (the session's own model), created on first use."""
        if self.llm_value is None and self.llm_factory is not None:
            try:
                self.llm_value = self.llm_factory()
            except Exception:
                return None
        return self.llm_value

    def resolve(self, session_id: str, *, platform: str = "", sender_id: str = "") -> Optional[Deal]:
        """The deal this session belongs to, or None. Duel sessions are cached per process."""
        if not session_id:
            return None
        now = time.monotonic()
        with self._lock:
            hit = self._deals.get(session_id)
            if hit is not None and (hit[0] is not None or now - hit[1] < 60):
                return hit[0]
        deal = self._resolve_duel(session_id) or self._resolve_chat(session_id, platform, sender_id)
        with self._lock:
            self._deals[session_id] = (deal, now)
        return deal

    def _resolve_duel(self, session_id: str) -> Optional[Deal]:
        neg = self.store.negotiation(session_id)
        if neg and neg.get("kind") == "chat":
            item = self.store.items().get(neg.get("item", ""))
            return Deal(session_id, "chat", "lp", item, challenge=neg.get("challenge")) if item else None
        if neg and neg.get("duel_id"):
            rec = self.store.duel(neg["duel_id"])
            item = self.store.items().get(neg.get("item", ""))
            if rec and item:
                return Deal(session_id, "duel", neg.get("arm", "lp"), item, rec["id"])
        try:
            title, source = self.title_lookup(session_id)
        except Exception:
            return None
        m = DUEL_TITLE.match(title or "")
        if not m or (source not in (None, "user")):
            return None
        rec = self.store.duel(m.group(1))
        if not rec or m.group(2) not in rec.get("arms", {}):
            return None
        item = self.store.items().get(rec["item"])
        if item is None:
            return None
        arm = m.group(2)
        if rec["arms"][arm].get("session_id") is None:
            self.store.update_duel_arm(rec["id"], arm, session_id=session_id)
        return Deal(session_id, "duel", arm, item, rec["id"])

    def _resolve_chat(self, session_id: str, platform: str, sender_id: str) -> Optional[Deal]:
        platform = (platform or "").lower()
        if platform in LOCAL_SURFACES:
            return None
        from . import challenge

        rec = challenge.active_on(self, platform)
        if rec is not None:
            # A challenge chat is guarded whether the item sold or the challenge ended (then it gets the
            # closing message): it never falls through to an unguarded turn.
            if sender_id and f"{platform}:{sender_id}" in self.store.owners():
                return None
            item = self.store.items().get(rec["item"])
            return Deal(session_id, "chat", "lp", item, challenge=rec["id"]) if item else None
        shop_platforms = self.store.backend.get("shop_platforms", []) or []
        if platform not in shop_platforms:
            return None
        if sender_id and f"{platform}:{sender_id}" in self.store.owners():
            return None
        item = self.store.item()
        if item is None or item.status != "open":
            return None
        return Deal(session_id, "chat", "lp", item)
