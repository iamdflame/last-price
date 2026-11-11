"""The counter policy: Boulware concession, never below the stop, no floor recovery."""

import random

from last_price import policy


def test_stop_is_inside_the_band():
    rng = random.Random(1)
    for _ in range(500):
        s = policy.draw_stop(420, 360, rng)
        assert 360 + 0.05 * 60 - 1e-9 <= s <= 360 + 0.15 * 60 + 1e-9


def test_counter_moves_only_when_the_buyer_moves_and_never_below_stop():
    stop = 366.4
    neg = policy.start(420)
    seq = [300, 300, 300, 310, 305, 320, 340, 340, 350, 355, 360, 365]
    counters = []
    for b in seq:
        before = neg.counter
        best_before = neg.best_buyer
        policy.on_buyer_message(neg, [b], stop)
        if b <= best_before:
            assert neg.counter == before, "the counter moved without the buyer moving"
        counters.append(neg.counter)
    assert all(a >= b for a, b in zip(counters, counters[1:])), "the counter rose"
    assert min(counters) >= policy.round_up(stop, 5)
    assert all(c % 5 == 0 for c in counters)


def test_concession_is_slow_then_faster():
    neg = policy.start(420)
    steps = []
    for b in (300, 310, 320, 330, 340):
        c0 = neg.counter
        policy.on_buyer_message(neg, [b], 366.0)
        steps.append(c0 - neg.counter)
    assert steps[0] <= steps[-2], steps


def test_offer_decisions():
    stop = 366.4
    neg = policy.start(420)
    policy.on_buyer_message(neg, [300], stop)
    ok, counter = policy.decide_offer(neg, 300, stop)
    assert not ok and counter >= 370
    # a price at or above the counter is accepted at the buyer's number
    neg2 = policy.start(420)
    policy.on_buyer_message(neg2, [415], stop)
    assert policy.decide_offer(neg2, 415, stop) == (True, 415.0)
    # never below the stop, even on the last allowed offer
    neg3 = policy.start(420)
    for _ in range(policy.MAX_OFFERS):
        ok, _c = policy.decide_offer(neg3, 365, stop)
        assert not ok
    # on the last offer, at or above the stop closes
    neg4 = policy.start(420)
    neg4.offers_used = policy.MAX_OFFERS - 1
    assert policy.decide_offer(neg4, 367, stop)[0]


def test_a_price_already_offered_is_honoured():
    stop = 366.4
    neg = policy.start(420)
    policy.note_sent(neg, [380], stop)
    neg.counter = 395
    assert policy.decide_offer(neg, 380, stop) == (True, 380.0)
    policy.note_sent(neg, [300], stop)  # a below-stop price can never become "offered"
    assert neg.lowest_sent == 380


def _probe(floor, seed):
    """A patient buyer: creeps up, then binary-searches with every allowed offer."""
    rng = random.Random(seed)
    stop = policy.draw_stop(420, floor, rng)
    neg = policy.start(420)
    seen = []
    for b in range(250, 420, 10):
        policy.on_buyer_message(neg, [b], stop)
        seen.append(neg.counter)
    return seen, stop


def test_no_floor_recovery_from_counters():
    """Different floors give the SAME counter sequence: the counters cannot tell them apart."""
    by_seq = {}
    for floor in range(340, 381):
        for seed in range(40):
            seq, _stop = _probe(float(floor), seed)
            by_seq.setdefault(tuple(seq), set()).add(floor)
    widths = [max(fl) - min(fl) for fl in by_seq.values() if len(fl) > 1]
    assert widths, "every counter sequence pinned down a single floor"
    # the most common outcome is consistent with a spread of floors several dollars wide
    biggest = max(by_seq.values(), key=len)
    assert max(biggest) - min(biggest) >= 5
    # and no counter ever equals the floor
    for floor in (340, 355, 360, 372):
        for seed in range(30):
            seq, _ = _probe(float(floor), seed)
            assert min(seq) > floor
