"""The counter policy: Boulware concession, never below the stop, no floor recovery."""

import random

from last_price import policy


def test_stop_is_inside_the_band():
    rng = random.Random(1)
    for _ in range(500):
        s = policy.draw_stop(420, 360, rng)
        assert 360 + 0.05 * 60 - 1e-9 <= s <= 360 + 0.15 * 60 + 1e-9


def test_counter_never_rises_never_below_the_stop_line_and_stays_on_the_step():
    stop = 366.4
    neg = policy.start(420)
    seq = [300, 300, 300, 310, 305, 320, 340, 340, 350, 355, 360, 365]
    counters = []
    for b in seq:
        policy.on_buyer_message(neg, [b], stop)
        counters.append(neg.counter)
    assert all(a >= b for a, b in zip(counters, counters[1:])), "the counter rose"
    assert min(counters) >= policy.round_up(stop, 5)
    assert all(c % 5 == 0 for c in counters)


def test_early_holds_do_not_move_the_counter_later_holds_move_it_a_little():
    stop = 366.4
    neg = policy.start(420)
    policy.on_buyer_message(neg, [300], stop)  # message 1: the buyer's first offer moves it
    first = neg.counter
    policy.on_buyer_message(neg, [300], stop)  # message 2: a hold, too early to move
    assert neg.counter == first
    policy.on_buyer_message(neg, [], stop)  # message 3: still holding: a small time concession
    assert first - 15 <= neg.counter < first
    for _ in range(20):  # a buyer who never moves cannot push it below the stop line
        policy.on_buyer_message(neg, [300], stop)
    assert neg.counter == policy.round_up(stop, 5)


def test_a_climbing_buyer_reaches_the_stop_line_within_five_messages():
    neg = policy.start(420)
    steps = []
    for b in (300, 320, 340, 350, 355):
        c0 = neg.counter
        policy.on_buyer_message(neg, [b], 366.4)
        steps.append(c0 - neg.counter)
    assert neg.counter == 370, (neg.counter, steps)
    assert steps[0] <= 15  # the first concession is a small one


def test_a_buyer_above_the_stop_line_and_close_to_the_counter_is_met():
    stop = 366.4
    neg = policy.start(420)
    for b in (350, 375):
        policy.on_buyer_message(neg, [b], stop)
    assert neg.counter == 390
    policy.on_buyer_message(neg, [380], stop)
    assert neg.counter == 380
    assert policy.decide_offer(neg, 380, stop) == (True, 380.0)
    # but a buyer below the stop line is never met
    neg2 = policy.start(420)
    for b in (350, 360, 365, 365, 365, 365, 365, 365):
        policy.on_buyer_message(neg2, [b], stop)
    assert neg2.counter == 370
    assert not policy.decide_offer(neg2, 365, stop)[0]


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


def test_an_amount_above_the_ask_is_not_a_price_for_this_item():
    """A live bench duel: 'two phones for $650' was accepted as a $650 sale of one phone."""
    neg = policy.start(420)
    policy.on_buyer_message(neg, [650], 366.4)
    assert policy.decide_offer(neg, 650, 366.4) == (False, 410.0)  # the opening anchor, not a sale
    assert neg.offers_used == 0 and neg.sold_at is None


def test_the_buyer_quoting_the_counter_does_not_freeze_it():
    """A live bench duel (French): "$405 c'est encore un peu élevé" was read as a $405 offer, and the
    counter stayed at $405 while the buyer climbed 350, 360, 375, 390, 400."""
    neg = policy.start(420)
    policy.on_buyer_message(neg, [350], 366.4)
    assert neg.counter == 405
    policy.on_buyer_message(neg, [360, 405], 366.4)  # "$405 is still high for me. I can go to $360."
    assert neg.best_buyer == 360 and neg.counter < 405
    policy.on_buyer_message(neg, [375], 366.4)
    assert neg.counter == 380
    policy.on_buyer_message(neg, [390], 366.4)  # above the counter: the offer tool says yes at 390
    assert policy.decide_offer(neg, 390, 366.4) == (True, 390.0)


def test_asking_for_lower_is_not_agreeing():
    assert policy.asks_for_lower("Based on that, $405 would be around GH₵ 4,860. Would you consider lowering the price?")
    assert policy.asks_for_lower("$390 is still too high for me")
    assert not policy.asks_for_lower("Would you take $365?")
    assert not policy.asks_for_lower("OK, $390 works. ACCEPT $390")
    assert not policy.asks_for_lower("I can't go lower than $380, deal?")


# ---- the opening anchor (0.1.2): a first message with no number no longer gets the full ask back ----

def test_a_first_message_with_no_number_opens_below_the_ask():
    neg = policy.start(420)
    policy.on_buyer_message(neg, [], 366.4)  # "Hi, is the iPhone still available?"
    assert neg.counter == 410 == policy.opening_price(420)
    policy.on_buyer_message(neg, [], 366.4)  # message 2, still no number: too early to move again
    assert neg.counter == 410


def test_the_opening_reads_neither_the_floor_nor_the_stop():
    # every stop a $420 item can draw (floors 300-380, 5-15% margins) opens at the same price
    rng = random.Random(3)
    openings = set()
    for _ in range(300):
        floor = rng.uniform(300, 380)
        neg = policy.start(420)
        policy.on_buyer_message(neg, [], policy.draw_stop(420, floor, rng))
        openings.add(neg.counter)
    assert openings == {410.0}


def test_the_opening_never_goes_below_the_stop_line():
    neg = policy.start(100)  # floor 99: the stop line is 100, above the $97 opening
    stop = policy.draw_stop(100, 99, random.Random(1))
    policy.on_buyer_message(neg, [], stop)
    assert neg.counter >= policy.round_up(stop, policy.step_of(100))


def test_a_first_offer_still_concedes_with_the_buyer_never_below_their_offer():
    stop = 366.4
    a, b = policy.start(420), policy.start(420)
    policy.on_buyer_message(a, [300], stop)  # a first offer: the usual 25% of the gap
    policy.on_buyer_message(b, [415], stop)  # a first offer just under the ask: met at the buyer's price, never below it
    assert a.counter == 405
    assert b.counter == 415


def test_the_opening_scales_with_the_ask_and_stays_on_the_step():
    for ask in (40, 99, 420, 1200, 4500, 12000):
        o = policy.opening_price(ask)
        step = policy.step_of(ask)
        assert o < ask and o % step == 0 and ask - o <= max(step, ask * policy.OPENING_SHARE) + step
