"""Review 3 (our delta review of 0.1.5): a held stranger chat stays held across restarts until `shop release`
rebuilds its saved prompt without memory; memory is read on every turn; Ctrl+C kills the live children."""

import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import last_price
import pytest
from conftest import SHOP_PROFILE, hermes_config_get
from helpers import first_turn, make_rt, open_duel
from last_price import challenge, commands, duel
from last_price.hooks import make_hooks
from last_price.runtime import Refusal, Runtime
from test_register import FakeCtx

ROOT = Path(__file__).resolve().parents[1]
MEMORY_ON = {**SHOP_PROFILE, "memory.memory_enabled": "true"}
HELD = {"action": "block", "message": challenge.HELD}


def _chat(rt, text, sid, sender="42", platform="telegram"):
    pre_llm, _pre_tool, _tr = make_hooks(rt)
    return pre_llm(session_id=sid, user_message=text, platform=platform, sender_id=sender,
                   is_first_turn=first_turn(rt, sid))


def _restart(rt):
    """A new gateway process: a new Runtime on the same plugin state (ctx.state is a file in Hermes)."""
    new = Runtime(rt.store.backend, data_dir=rt.data_dir, llm=rt.llm_value, title_lookup=rt.title_lookup)
    new._test_turns = rt.__dict__.get("_test_turns", set())
    return new


def _memory(monkeypatch, on):
    getter = hermes_config_get(MEMORY_ON if on else SHOP_PROFILE)
    monkeypatch.setattr(challenge, "chat_get", getter)  # the in-process gate
    monkeypatch.setattr(challenge, "hermes_get", getter)  # `hermes config get` (release, doctor)


class Hermes:
    """The two public CLI calls `shop release` makes: `hermes gateway status`, `hermes sessions refresh-prompts`."""

    def __init__(self, gateway=False, refresh_code=0):
        self.gateway, self.refresh_code, self.calls = gateway, refresh_code, []

    def install(self, monkeypatch):
        monkeypatch.setattr(duel, "gateway_running", lambda: self.gateway)
        monkeypatch.setattr(duel, "hermes_cli", self)
        return self

    def __call__(self, args, timeout=120):
        self.calls.append(args)
        return self.refresh_code, "Requested a system prompt refresh for every session in this profile"


def _shop(tmp_path):
    rt, item = make_rt(tmp_path)
    assert commands.run(rt, "shop on telegram", platform="cli").startswith("Shop platforms: telegram")
    return rt, item


# ---- 1. the hold survives a restart ---------------------------------------------------------------
def test_a_chat_held_while_memory_was_on_stays_held_after_memory_off_and_a_restart(tmp_path, monkeypatch):
    """Review 3 #1, the reviewer's sequence: Hermes saved this chat's prompt while memory was on and replays it
    after a restart, so the new process must still hold it (0.1.5 forgot the hold on restart)."""
    rt, _item = _shop(tmp_path)
    _memory(monkeypatch, on=True)
    assert _chat(rt, "Hi, would you take 300?", "tg-1") == HELD
    _memory(monkeypatch, on=False)
    rt2 = _restart(rt)
    assert _chat(rt2, "OK, 350 then?", "tg-1") == HELD
    assert _chat(_restart(rt2), "350?", "tg-1") == HELD
    assert "context" in _chat(rt2, "hello", "tg-2")  # a chat that starts with memory off runs
    assert sorted(challenge.holds(rt2)["held"]) == ["tg-1"]


def test_a_chat_first_seen_past_its_first_turn_is_held(tmp_path):
    """Begun under an earlier version (or as an ordinary chat): its saved prompt was built before any check."""
    rt, _item = _shop(tmp_path)
    pre_llm, _t, _tr = make_hooks(rt)
    assert pre_llm(session_id="tg-old", user_message="350?", platform="telegram", sender_id="42",
                   is_first_turn=False) == HELD
    assert "tg-old" in challenge.holds(rt)["held"]


def test_owners_and_non_deal_chats_are_never_held(tmp_path, monkeypatch):
    rt, item = _shop(tmp_path)
    rt.store.add_owner("telegram:7")
    _memory(monkeypatch, on=True)
    assert _chat(rt, "hi", "tg-owner", sender="7") is None  # the owner's own chat: not a deal chat
    assert _chat(rt, "hi", "dc-1", platform="discord") is None  # a platform the shop is not on
    assert _chat(rt, "hi", "cli-1", platform="cli") is None  # the owner's terminal
    open_duel(rt, item, arm="lp", sid="local-duel")
    pre_llm, _t, _tr = make_hooks(rt)
    assert "context" in pre_llm(session_id="local-duel", user_message="300?", platform="cli")  # a duel arm
    assert challenge.holds(rt)["held"] == {}


# ---- 2. release ------------------------------------------------------------------------------------
def test_release_runs_refresh_prompts_and_then_the_chat_runs(tmp_path, monkeypatch):
    rt, _item = _shop(tmp_path)
    _memory(monkeypatch, on=True)
    assert _chat(rt, "hi", "tg-1") == HELD
    _memory(monkeypatch, on=False)
    hermes = Hermes().install(monkeypatch)
    out = commands.run(rt, "shop release", platform="cli")
    assert not isinstance(out, Refusal) and out.startswith("Released 1 chat(s)")
    assert hermes.calls == [["sessions", "refresh-prompts"]]
    rt2 = _restart(rt)
    assert "context" in _chat(rt2, "350?", "tg-1")
    assert commands.run(rt2, "shop release", platform="cli") == "No stranger chat is held."


@pytest.mark.parametrize("case", ["memory on", "gateway running", "gateway unknown", "refresh fails", "remote"])
def test_release_refuses_and_releases_nothing(tmp_path, monkeypatch, case):
    rt, _item = _shop(tmp_path)
    _memory(monkeypatch, on=True)
    assert _chat(rt, "hi", "tg-1") == HELD
    _memory(monkeypatch, on=case == "memory on")
    hermes = Hermes(gateway={"gateway running": True, "gateway unknown": None}.get(case, False),
                    refresh_code=1 if case == "refresh fails" else 0).install(monkeypatch)
    if case == "remote":
        rt.store.add_owner("telegram:7")
        out = commands.run(rt, "shop release", platform="telegram", source=types.SimpleNamespace(user_id="7"))
    else:
        out = commands.run(rt, "shop release", platform="cli")
    assert isinstance(out, Refusal), out
    if case in ("memory on", "gateway running", "gateway unknown", "remote"):
        assert hermes.calls == []  # no refresh requested
    assert "tg-1" in challenge.holds(rt)["held"]
    assert _chat(_restart(rt), "350?", "tg-1") == HELD


def test_held_chats_never_get_a_model_turn_in_any_order_of_events(tmp_path, monkeypatch):
    """Memory on/off, restart, release (refresh inside it) in every order the owner can produce: the chat runs
    only after a release made with memory off, and only while memory stays off."""
    rt, _item = _shop(tmp_path)
    hermes = Hermes().install(monkeypatch)
    _memory(monkeypatch, on=True)
    assert _chat(rt, "1", "tg-1") == HELD
    assert isinstance(commands.run(rt, "shop release", platform="cli"), Refusal)  # release while memory on
    rt = _restart(rt)
    assert _chat(rt, "2", "tg-1") == HELD  # restart while memory on
    _memory(monkeypatch, on=False)
    assert _chat(rt, "3", "tg-1") == HELD  # memory off, no restart
    rt = _restart(rt)
    assert _chat(rt, "4", "tg-1") == HELD  # memory off, restart
    hermes.gateway = True
    assert isinstance(commands.run(rt, "shop release", platform="cli"), Refusal)  # gateway still running
    assert _chat(rt, "5", "tg-1") == HELD
    hermes.gateway = False
    assert commands.run(rt, "shop release", platform="cli").startswith("Released")
    rt = _restart(rt)
    assert "context" in _chat(rt, "6", "tg-1")
    _memory(monkeypatch, on=True)
    assert _chat(rt, "7", "tg-1") == HELD  # memory on again: held at once, no window
    _memory(monkeypatch, on=False)
    assert _chat(_restart(rt), "8", "tg-1") == HELD  # and held again until the next release


def test_doctor_counts_held_chats_and_gives_the_release_steps(tmp_path, monkeypatch):
    rt, _item = _shop(tmp_path)
    _memory(monkeypatch, on=True)
    _chat(rt, "hi", "tg-1")
    _memory(monkeypatch, on=False)
    out = commands.doctor(_restart(rt))
    assert "held stranger chats: 1." in out
    for step in challenge.RELEASE_STEPS:
        assert step in out
    assert "restart the gateway" not in out and "10 s" not in out


def test_cli_release_refusal_exits_1(tmp_path, monkeypatch):
    ctx = FakeCtx(tmp_path)
    last_price.register(ctx)
    cli = ctx.cli["lastprice"]["handler_fn"]
    run = lambda *argv: cli(types.SimpleNamespace(lp_args=list(argv)))  # noqa: E731
    assert run("shop", "release") == 0  # nothing held
    challenge._mark(Runtime(ctx.state), ["tg-1"], "held")
    Hermes(gateway=True).install(monkeypatch)
    assert run("shop", "release") == 1
    Hermes(gateway=False).install(monkeypatch)
    assert run("shop", "release") == 0


# ---- 3. memory is read on every turn ----------------------------------------------------------------
def test_memory_switched_on_holds_the_very_next_turn(tmp_path, monkeypatch):
    """0.1.5 reused a reading for up to 10 s; now each turn reads config.yaml as it is."""
    rt, _item = _shop(tmp_path)
    assert "context" in _chat(rt, "hi", "tg-1")
    _memory(monkeypatch, on=True)
    assert _chat(rt, "300?", "tg-1") == HELD


def test_chat_get_follows_a_config_change_with_no_wait(monkeypatch):
    """The real chat_get over a load_config that, like Hermes's, re-reads when config.yaml's signature changes."""
    monkeypatch.undo()
    cfg = {"memory": {"memory_enabled": False, "user_profile_enabled": False, "provider": ""}}
    fake = types.ModuleType("hermes_cli.config")
    fake.load_config = lambda: {"memory": dict(cfg["memory"])}
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.config", fake)
    rt, _item = make_rt(Path("."))
    assert challenge.gate_open(rt) is True
    cfg["memory"]["memory_enabled"] = True
    assert challenge.gate_open(rt) is False


# ---- 4. Ctrl+C kills the live children --------------------------------------------------------------
SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]


@pytest.fixture
def fresh_stop():
    duel._STOPPED.clear()
    yield
    duel._STOPPED.clear()


def test_ctrl_c_while_waiting_kills_the_child(monkeypatch, fresh_stop):
    """KeyboardInterrupt in the waiting thread: the child (its own session on POSIX) is killed in run_child's finally."""
    started = []
    real_popen = subprocess.Popen

    class Popen(real_popen):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            started.append(self)

        def communicate(self, *a, **kw):
            if self is started[0]:
                raise KeyboardInterrupt  # Ctrl+C while run_child waits on its child
            return super().communicate(*a, **kw)

    monkeypatch.setattr(duel.subprocess, "Popen", Popen)
    with pytest.raises(KeyboardInterrupt):
        duel.run_child(SLEEP, env=dict(os.environ), timeout=30)
    proc = started[0]
    real_popen.communicate(proc, timeout=15)  # returns only once the child is gone
    assert proc.poll() is not None and not duel._LIVE


def test_ctrl_c_in_the_main_thread_kills_children_running_in_worker_threads(fresh_stop):
    """Duel arms and bench duels run children from worker threads; stop_children (the main thread's except) kills
    them and no new child starts."""
    result = {}

    def worker():
        t0 = time.monotonic()
        try:
            duel.run_child(SLEEP, env=dict(os.environ), timeout=60)
        except Exception as exc:
            result["exc"] = exc
        result["seconds"] = time.monotonic() - t0

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    deadline = time.monotonic() + 15
    while not duel._LIVE and time.monotonic() < deadline:
        time.sleep(0.05)
    assert duel._LIVE
    duel.stop_children()
    t.join(20)
    assert not t.is_alive() and result["seconds"] < 25 and not duel._LIVE
    with pytest.raises(ChildProcessError):
        duel.run_child(SLEEP, env=dict(os.environ), timeout=60)


# ---- 5. docs ------------------------------------------------------------------------------------------
def test_docs_give_the_release_steps_and_say_formatting_only():
    for name in ("README.md", "SECURITY.md", "docs/CHALLENGE.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "restart the gateway" not in text and "until the gateway restarts" not in text, name
        assert "at most 10 s old" not in text, name
        assert "hermes -p shop lastprice shop release" in text and "refresh-prompts" in text, name
    for name in ("README.md", "docs/CHALLENGE.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "line endings only" not in text and "formatting only (line endings, quoting)" in text, name


# ---- 6. a compressed chat keeps its state --------------------------------------------------------------
def test_a_compression_continuation_inherits_its_parents_state(tmp_path, monkeypatch):
    """Hermes continues a compressed chat under a new session id whose parent is the old one: a running chat must
    not be held by it, and a held chat must not escape through it."""
    rt, _item = _shop(tmp_path)
    parents = {"tg-1b": "tg-1", "tg-1c": "tg-1b", "tg-2b": "tg-2", "tg-9b": "tg-9"}
    rt.parent_lookup = parents.get
    assert "context" in _chat(rt, "hi", "tg-1")
    pre_llm, _t, _tr = make_hooks(rt)
    turn = lambda sid: pre_llm(session_id=sid, user_message="350?", platform="telegram", sender_id="42",  # noqa
                               is_first_turn=False)
    assert "context" in turn("tg-1c")  # two compressions down from a running chat
    _memory(monkeypatch, on=True)
    assert _chat(rt, "hi", "tg-2") == HELD
    _memory(monkeypatch, on=False)
    assert turn("tg-2b") == HELD  # a held chat's continuation stays held
    assert turn("tg-9b") == HELD  # no recorded ancestor: held

    def broken(sid):
        raise RuntimeError("state.db")
    rt.parent_lookup = broken
    assert turn("tg-x") == HELD
