"""State round trip and the commitment."""

import json
import random

from helpers import JsonState
from last_price.state import Store, commitment


class Frozen:
    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


def test_round_trip_through_json():
    st = JsonState()
    store = Store(st)
    it = store.sell("iPhone 13, 128GB", 420, 360, extras=["a case"], rng=random.Random(3))
    again = Store(Frozen(json.loads(json.dumps(st.data)))).item("iphone-13-128gb")
    assert again == it
    assert again.commit == commitment(360, again.salt)
    assert 363 <= again.stop <= 369
    assert again.public() == {"item": "iphone-13-128gb", "name": "iPhone 13, 128GB", "ask": 420.0, "currency": "USD",
                              "extras": ["a case"], "status": "open"}


def test_refuses_bad_listings():
    store = Store(JsonState())
    for ask, floor in ((420, 500), (0, 10), (10, 0)):
        try:
            store.sell("x", ask, floor)
        except ValueError:
            continue
        raise AssertionError("accepted a bad listing")


def test_duel_records_and_expiry():
    store = Store(JsonState())
    it = store.sell("x", 100, 80)
    rec = store.new_duel(it.key, ["stock", "lp"])
    assert store.duel(rec["id"])["arms"]["lp"]["title"] == f"lastprice-duel-{rec['id']}-lp"
    rec["expires"] = 0
    store.save_duel(rec)
    assert store.duel(rec["id"]) is None
