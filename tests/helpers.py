"""Test doubles: an in-memory Hermes-like context and a JSON round-tripping state."""

import json
import random

from last_price.runtime import Runtime
from last_price.state import MemoryState


class JsonState(MemoryState):
    """ctx.state's contract with PluginState's JSON round trip on every write."""

    def set(self, key, value):
        self.data[key] = json.loads(json.dumps(value))


class FakeLlm:
    def __init__(self, reply="I can do $395, and I'll include a case.", fail=False):
        self.reply, self.fail, self.calls = reply, fail, []

    def complete(self, messages, **kw):
        self.calls.append({"messages": messages, **kw})
        if self.fail:
            raise TimeoutError("model timed out")

        class R:
            text = self.reply
            usage = None
        return R()


def make_rt(tmp_path, *, floor=361.0, ask=420.0, llm=None, extras=("a case",), titles=None, seed=7):
    state = JsonState()
    rt = Runtime(state, data_dir=tmp_path, llm=llm or FakeLlm(),
                 title_lookup=lambda sid: ((titles or {}).get(sid), "user"))
    item = rt.store.sell("iPhone 13, 128GB", ask, floor, extras=list(extras), rng=random.Random(seed))
    return rt, item


def first_turn(rt, sid):
    """Hermes's ``is_first_turn`` for a chat test: True the first time ``sid`` takes a turn (Hermes passes
    True when the session has no history yet; a held turn still leaves its withheld row)."""
    seen = rt.__dict__.setdefault("_test_turns", set())
    first = sid not in seen
    seen.add(sid)
    return first


def open_duel(rt, item, arm="lp", sid="local-abc"):
    rec = rt.store.new_duel(item.key, ["stock", "lp"])
    rt.title_lookup = lambda s: ({sid: rec["arms"][arm]["title"]}.get(s), "user")
    return rec
