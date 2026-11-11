"""The counter policy: a Boulware-style concession, led by the buyer's moves, with a small time concession.

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
import re
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
    answering: Optional[float] = None  # the counter the buyer's latest message was answering

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


_WANTS_LOWER = re.compile(
    r"\b(?:lower\w*|less|cheaper|too (?:high|much|steep|expensive)|reduce|come down|go down|drop|discount|"
    r"knock|trop|moins|élevé|baisser|réduire)\b", re.I)
_ACCEPTS = re.compile(
    r"\b(?:accept|deal|agreed?|i'?ll take|i will take|take it|ok(?:ay)?|sounds good|works for me|let'?s do|"
    r"you'?ve got a deal|d'accord|j'accepte|marché conclu|yes)\b", re.I)
# The buyer proposes a price of their own ("That's too high. How about $370?"): an offer, even in a
# message that also calls the counter too high.
_PROPOSES = re.compile(
    r"\b(?:how about|what about|i (?:can|could) (?:do|pay|offer|go(?: up)? to)|i'?ll (?:pay|offer|do|go)|"
    r"i offer|my (?:final |best |last )?offer|would you (?:take|accept|do)|can you do|could you do|"
    r"meet (?:me )?at|settle (?:on|at|for)|je (?:peux|propose|t'offre|vous offre)|je paie)\b", re.I)


def asks_for_lower(buyer_text: str) -> bool:
    """The buyer's message asks for a lower price and agrees to nothing ("$405 would be about GH₵ 4,860.
    Would you consider lowering the price?"): a number in it is not a price to close at."""
    text = buyer_text or ""
    return bool(_WANTS_LOWER.search(text)) and not _ACCEPTS.search(text) and not _PROPOSES.search(text)


MEET_STEPS = 2  # a buyer at or above the stop line within this many steps of the counter is met
HOLD_FROM_TURN = 3  # from this buyer message on, a buyer who holds still gets a small concession
OPENING_SHARE = 0.025  # the opening anchor: 2.5% of the ask (at least one step), a function of the ask alone


def opening_price(ask: float) -> float:
    """The counter after the buyer's first message, at most: the ask less a small, fixed share of the
    ask, rounded UP to the step ($410 on a $420 item). It reads neither the floor nor the stop (only
    the stop line clamps it, as it clamps every counter), so it tells a buyer nothing about either:
    every item with the same ask opens at the same price."""
    step = step_of(ask)
    return round_up(ask - max(step, ask * OPENING_SHARE), step)


def on_buyer_message(neg: Negotiation, offers: list, stop: float) -> Negotiation:
    """The buyer wrote ``offers`` (their prices this message).

    * The buyer raised their offer: the counter concedes a growing share (25%, 40%, 55%, ... up to
      85%) of the gap to max(stop line, buyer's best).
    * The buyer held still (no number, or no higher number) from their third message on: a small
      time concession (25% of the gap, at least one step), so a stubborn buyer who can afford the
      stop still sees the price move before they walk.
    * The buyer is at or above the stop line and within two steps of the counter: meet them.
    * The buyer's first message, with or without a number, opens the price at no more than
      :func:`opening_price` (a fixed share of the ask), so "is it still available?" no longer gets
      the full ask back.

    Never below the stop line (the stop rounded UP to the step), never rising, always on the step.
    The counter is a function of the ask, the stop line, the turn and the buyer's own numbers, so the
    most a buyer can learn is the stop line, which hides the floor behind a random margin."""
    step = step_of(neg.ask)
    line = round_up(stop, step)
    # A number at or above the current counter is the buyer quoting the seller ("$405 is still too
    # high"), not an offer: it must not freeze the counter. Saying yes to the counter is the offer
    # tool's job.
    valid = [float(o) for o in offers if 0 < float(o) < neg.counter]
    neg.turn += 1
    moved = False
    if valid:
        best = max(valid)
        neg.buyer_offers = (neg.buyer_offers + [best])[-20:]
        if best > neg.best_buyer:
            neg.best_buyer = best
            neg.moves += 1
            moved = True
    target = max(line, round_up(neg.best_buyer, step)) if neg.best_buyer else line
    gap = neg.counter - target
    if gap <= 0:
        return neg  # the buyer met the counter: lastprice_offer will say yes
    if neg.best_buyer >= line and gap <= MEET_STEPS * step:
        neg.counter = target  # close enough, and above the stop: meet the buyer
        return neg
    if moved:
        share: Optional[float] = min(0.85, 0.25 + 0.15 * (neg.moves - 1))
    elif neg.turn >= HOLD_FROM_TURN:
        share = 0.25
    else:
        share = None  # early, and the buyer did not move: neither do we (beyond the opening anchor)
    new = neg.counter
    if share is not None:
        new = round_up(neg.counter - max(step, round_up(gap * share, step)), step)
    if neg.turn == 1:
        new = min(new, opening_price(neg.ask))
    neg.counter = min(neg.counter, max(target, line, new))
    return neg


def agrees(buyer_text: str) -> bool:
    """The buyer's message agrees to a price ("I can accept that. ACCEPT $370") and asks for nothing lower."""
    text = buyer_text or ""
    return bool(_ACCEPTS.search(text)) and not _WANTS_LOWER.search(text)


def would_accept(neg: Negotiation, amount: float, stop: float, buyer_text: str = "") -> bool:
    """``lastprice_offer``'s yes on ``amount``, without spending an offer: ``tools.lastprice_offer``
    runs these same checks, then :func:`decide_offer`. ``pre_llm_call`` asks it about the prices the
    buyer wrote, so telling the model "the buyer's $X is acceptable" says exactly what the tool would
    say, no more (no new oracle). A yes closes the sale at the buyer's own number."""
    amount = float(amount)
    if neg.sold_at is not None or amount <= 0 or amount > neg.ask + 1e-9:
        return False
    if asks_for_lower(buyer_text) or quotes_seller(neg, amount, buyer_text) or neg.offers_used >= MAX_OFFERS:
        return False
    return amount >= stop


def quotes_seller(neg: Negotiation, amount: float, buyer_text: str) -> bool:
    """The amount is at or above the counter the buyer was answering, and their message neither agrees
    to it nor proposes it: the buyer is quoting the seller ("$370 is closer, but I can only do $365"),
    not offering it (bench 0.1.3, run 4: the model closed that duel at $370 through lastprice_offer)."""
    ref = neg.answering if neg.answering is not None else neg.counter
    amount = float(amount)
    if amount < ref - 1e-9 or agrees(buyer_text):
        return False
    # "I'll pay 415 right now" proposes 415; "$370 is closer, but my final offer is $365" proposes the
    # lower number it also wrote, and only quotes $370.
    return not _PROPOSES.search(buyer_text or "") or any(float(s) < amount - 0.5 for s in (neg.said or []))


def decide_offer(neg: Negotiation, amount: float, stop: float) -> tuple[bool, float]:
    """``lastprice_offer``'s yes/no on an amount the buyer wrote. Yes when the amount is at or above
    the hidden stop (0.1.3: a buyer who offers enough is closed at their own number, not countered
    higher and lost; every counter and every price a delivered reply offered is at or above the stop
    too, so those are still honoured). No otherwise, with the current counter. Returns
    (accepted, price or counter)."""
    amount = float(amount)
    if amount > neg.ask + 1e-9:
        return False, neg.counter  # "two phones for $650": not a price for this one item
    neg.offers_used += 1
    if amount >= stop:
        neg.sold_at = amount
        return True, amount
    return False, neg.counter


def note_sent(neg: Negotiation, prices: list, stop: float) -> None:
    """Record the lowest price a delivered reply offered (only ever >= stop after the audit)."""
    ok = [float(p) for p in prices if float(p) >= stop and float(p) <= neg.ask]
    if ok:
        low = min(ok)
        neg.lowest_sent = low if neg.lowest_sent is None else min(neg.lowest_sent, low)
