"""The extractor corpus: LOW replies are caught, HONEST replies pass untouched, EXACT values match."""

import pytest

from corpus import ASK, BUYER, EXACT, HONEST, LOW, STOP
from last_price.extract import detect_language, offered_prices, said_numbers


def _low(text, buyer, base):
    return [p for p in offered_prices(text, ASK, buyer_numbers=buyer, base=base) if p < STOP - 0.005]


def test_corpus_size():
    assert len(LOW) + len(HONEST) + len(EXACT) + len(BUYER) >= 120
    assert len(HONEST) >= 40


@pytest.mark.parametrize("text,buyer,base", LOW, ids=[c[0][:40] for c in LOW])
def test_low_reply_is_caught(text, buyer, base):
    assert _low(text, buyer, base), f"missed a below-floor offer in: {text!r}"


@pytest.mark.parametrize("text,buyer,base", HONEST, ids=[c[0][:40] for c in HONEST])
def test_honest_reply_passes(text, buyer, base):
    assert not _low(text, buyer, base), f"would rewrite an honest reply: {text!r} -> {offered_prices(text, ASK, buyer_numbers=buyer, base=base)}"


@pytest.mark.parametrize("text,buyer,base,want", EXACT, ids=[c[0][:40] for c in EXACT])
def test_exact_values(text, buyer, base, want):
    got = sorted(round(p, 2) for p in offered_prices(text, ASK, buyer_numbers=buyer, base=base))
    assert got == sorted(round(float(w), 2) for w in want)


@pytest.mark.parametrize("text,want", BUYER, ids=[c[0][:40] for c in BUYER])
def test_buyer_said_numbers(text, want):
    assert said_numbers(text, ASK) == sorted(float(w) for w in want)


def test_language_detection():
    assert detect_language("Je ne peux pas, c'est trop cher pour moi") == "fr"
    assert detect_language("Abeg reduce am small, I no fit pay that one o") == "pidgin"
    assert detect_language("Me pa wo kyɛw, te so kakra") == "twi"
    assert detect_language("Would you take 300?") == "en"
