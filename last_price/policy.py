"""The counter policy: a slow (Boulware-style) concession that moves only when the buyer moves.

The policy never reads the floor. It works from the ask and a hidden *stop*: the floor plus a
random 5-15% of the ask-floor gap, drawn once per item (:func:`draw_stop`). Every counter is
rounded UP to the item's step ($5 by default), never goes below the stop, and never rises.

Why no two counters solve for the floor: a counter is a function of the ask, the stop and the
buyer's own numbers. The stop already hides the floor behind a random margin, and the rounding
hides the stop inside a step-sized band. The most a patient buyer can learn is "the counters stop
falling around here", which bounds the floor only to a range (docs/THREAT_MODEL.md, "probing").
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

MAX_OFFERS = 5  # lastprice_offer calls per buyer per item


def draw_stop(ask: float, floor: float, rng: Optional[random.Random] = None) -> float:
    """floor + U(0.05, 0.15) x (ask - floor), drawn once and stored."""
    rng = rng or random.SystemRandom()
    return round(floor + rng.uniform(0.05, 0.15) * (ask - floor), 2)


def round_up(value: float, step: float) -> float:
    return float(math.ceil(value / step - 1e-9) * step)


@dataclass
class Negotiation:
    """One buyer haggling over one item (stored per session)."""

    ask: float
    counter: float  # the lowest price the seller may state now
    best_buyer: float = 0.0  # the buyer's highest offer so far
    moves: int = 0  # how many times the buyer raised their offer
    offers_used: int = 0  # lastprice_offer calls
    lowest_sent: Optional[float] = None  # lowest price a DELIVERED reply offered (binding)
    buyer_offers: list = field(default_factory=list)
    said: list = field(default_factory=list)  # numbers the buyer wrote in the latest message
    turn: int = 0
    sold_at: Optional[float] = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Negotiation":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


def start(ask: float) -> Negotiation:
    return Negotiation(ask=float(ask), counter=float(ask))


def step_of(ask: float) -> float:
    """$5 on a $420 item; 1% of the ask, at least 1, rounded to a friendly step."""
    raw = max(1.0, ask * 0.01)
    for s in (1, 2, 5, 10, 20, 25, 50, 100, 250, 500, 1000):
        if raw <= s:
            return float(s)
    return float(round(raw, -3))


def on_buyer_message(neg: Negotiation, offers: list, stop: float) -> Negotiation:
    """The buyer wrote ``offers`` (their prices this message). The counter moves only if the
    buyer's best offer went UP; then it concedes a growing share of the gap to
    max(stop, buyer's best), never below the stop, rounded up to the step."""
    step = step_of(neg.ask)
    floor_line = round_up(stop, step)
    valid = [float(o) for o in offers if 0 < float(o) <= neg.ask]
    neg.turn += 1
    if not valid:
        return neg
    best = max(valid)
    neg.buyer_offers = (neg.buyer_offers + [best])[-20:]
    if best <= neg.best_buyer:
        return neg  # the buyer did not move: neither do we
    first = neg.best_buyer == 0.0
    neg.best_buyer = best
    neg.moves += 1
    target = max(floor_line, round_up(best, step))
    gap = neg.counter - target
    if gap <= 0:
        return neg  # the buyer met the counter: lastprice_offer will say yes
    share = 0.12 if first else min(0.8, 0.2 + 0.15 * (neg.moves - 1))
    concession = max(step, round_up(gap * share, step))
    neg.counter = max(target, floor_line, round_up(neg.counter - concession, step))
    return neg


def decide_offer(neg: Negotiation, amount: float, stop: float) -> tuple[bool, float]:
    """``lastprice_offer``'s yes/no on an amount the buyer wrote. Yes when the amount meets the
    current counter, or a price a delivered reply already offered (an offer made is kept), or, on
    the buyer's last allowed offer, the stop. Returns (accepted, counter)."""
    neg.offers_used += 1
    amount = float(amount)
    honoured = min(neg.counter, neg.lowest_sent) if neg.lowest_sent is not None else neg.counter
    if amount >= honoured - 1e-9 and amount >= stop:
        neg.sold_at = amount
        return True, amount
    if neg.offers_used >= MAX_OFFERS and amount >= stop:
        neg.sold_at = amount
        return True, amount
    return False, neg.counter


def note_sent(neg: Negotiation, prices: list, stop: float) -> None:
    """Record the lowest price a delivered reply offered (only ever >= stop after the audit)."""
    ok = [float(p) for p in prices if float(p) >= stop and float(p) <= neg.ask]
    if ok:
        low = min(ok)
        neg.lowest_sent = low if neg.lowest_sent is None else min(neg.lowest_sent, low)
