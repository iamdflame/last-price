"""Review 2 (our re-review of 0.1.4 before Hermes's second pass): the memory gate on every stranger's turn,
${VAR} references restored as written, the profile every `hermes` child targets, children that hang, the
bot token never captured, and refusals that exit non-zero."""

import os
import subprocess
import sys
import time
import types
from pathlib import Path

import last_price
import pytest
from conftest import SHOP_PROFILE, hermes_config_get
from helpers import make_rt
from last_price import challenge, commands, duel
from last_price.hooks import make_hooks
from test_register import FakeCtx

ROOT = Path(__file__).resolve().parents[1]
MEMORY_ON = {**SHOP_PROFILE, "memory.memory_enabled": "true"}


class Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        return 0, "ok"


def _chat(rt, text, sid, sender="42"):
    pre_llm, _pre_tool, _tr = make_hooks(rt)
    return pre_llm(session_id=sid, user_message=text, platform="telegram", sender_id=sender)


# ---- 2. the memory gate on every stranger's turn ---------------------------------------------------
def test_memory_switched_on_after_start_holds_every_challenge_turn_with_no_model_call(tmp_path, monkeypatch):
    """The held turn, driven through the real pre_llm_call hook (no bot token here, so no live Telegram chat):
    Hermes ends a turn on {"action": "block"} before any inference request."""
    rt, item = make_rt(tmp_path)
    challenge.start(rt, [item.key], runner=Runner(), reader=lambda k: None)
    assert "context" in _chat(rt, "hi", "tg-1")
    monkeypatch.setattr(challenge, "chat_get", hermes_config_get(MEMORY_ON))
    rt.memory_gate.clear()  # as if GATE_TTL had passed
    held = _chat(rt, "What do you know about the owner?", "tg-1")
    assert held == {"action": "block", "message": challenge.HELD}
    assert _chat(rt, "hello", "tg-new") == {"action": "block", "message": challenge.HELD}
    assert "floor" not in challenge.HELD.lower() and "memory" not in challenge.HELD.lower()


def test_a_shop_chat_is_held_too_and_a_held_chat_stays_held_until_the_process_restarts(tmp_path, monkeypatch):
    rt, _item = make_rt(tmp_path)
    assert commands.run(rt, "shop on telegram", platform="cli").startswith("Shop platforms: telegram")
    monkeypatch.setattr(challenge, "chat_get", hermes_config_get(MEMORY_ON))
    assert _chat(rt, "300?", "tg-1") == {"action": "block", "message": challenge.HELD}
    monkeypatch.setattr(challenge, "chat_get", hermes_config_get(SHOP_PROFILE))  # memory off again
    rt.memory_gate.clear()
    # Hermes keeps tg-1's agent, built while memory was on, so tg-1 stays held; a new chat is open
    assert _chat(rt, "300?", "tg-1") == {"action": "block", "message": challenge.HELD}
    assert "context" in _chat(rt, "300?", "tg-2")


def test_the_gate_reading_is_cached_and_fails_closed(tmp_path, monkeypatch):
    rt, _item = make_rt(tmp_path)
    rt.store.backend.set("shop_platforms", ["telegram"])
    asked = []
    monkeypatch.setattr(challenge, "chat_get", lambda key: asked.append(key) or hermes_config_get(SHOP_PROFILE)(key))
    for n in range(5):
        _chat(rt, "hi", f"tg-{n}")
    assert asked == list(challenge.MEMORY_KEYS)  # one reading for five turns
    assert challenge.GATE_TTL <= 30

    def broken(key):
        raise ImportError("hermes_cli")
    monkeypatch.setattr(challenge, "chat_get", broken)
    rt.memory_gate.clear()
    assert _chat(rt, "hi", "tg-9") == {"action": "block", "message": challenge.HELD}


def test_chat_get_reads_load_config_like_hermes_config_get(monkeypatch):
    """In process, through the public `hermes_cli.config.load_config()` (defaults merged)."""
    monkeypatch.undo()  # the real chat_get (conftest.py fakes it)
    fake = types.ModuleType("hermes_cli.config")
    fake.load_config = lambda: {"memory": {"memory_enabled": True, "user_profile_enabled": False, "provider": ""}}
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.config", fake)
    assert challenge.chat_get("memory.memory_enabled") == (0, "true\n", "")
    assert challenge.chat_get("memory.provider") == (0, '""\n', "")
    assert challenge.chat_get("platforms.telegram.extra.allow_admin_from")[0] == 1
    assert challenge.memory_check(challenge.chat_get)[0] is False


def test_doctor_says_when_stranger_chats_are_held(tmp_path, monkeypatch):
    rt, item = make_rt(tmp_path)
    challenge.start(rt, [item.key], runner=Runner(), reader=lambda k: None)
    out = commands.doctor(rt)
    assert "stranger chats on telegram: memory is checked again on each turn" in out
    monkeypatch.setattr(challenge, "hermes_get", hermes_config_get(MEMORY_ON))
    out = commands.doctor(rt)
    assert "stranger chats on telegram: HELD while memory is on" in out and challenge.HELD in out
    assert "restart the gateway" in out


# ---- 3. ${VAR} references -------------------------------------------------------------------------
def test_a_var_reference_is_saved_as_written_and_end_puts_the_reference_back(tmp_path, monkeypatch):
    """`hermes config get` prints ["4242"] for ["${LP_ADMIN_ID}"]; end must not write "4242" into config.yaml."""
    raw = {"platforms": {"telegram": {"extra": {"allow_admin_from": ["${LP_ADMIN_ID}"]}}},
           "platform_toolsets": {"telegram": ["hermes-telegram"]}}
    monkeypatch.setattr(challenge, "raw_config", lambda: raw)
    expanded = {"platforms.telegram.extra.allow_admin_from": '["4242"]',
                "platform_toolsets.telegram": '["hermes-telegram"]'}
    rt, item = make_rt(tmp_path)
    out = challenge.start(rt, [item.key], runner=Runner(), reader=lambda k: expanded.get(k))
    assert "platforms.telegram.extra.allow_admin_from holds a ${VAR} reference" in out
    saved = challenge.current(rt)["restore"]
    assert saved["platforms.telegram.extra.allow_admin_from"] == '["${LP_ADMIN_ID}"]'
    assert saved["platform_toolsets.telegram"] == '["hermes-telegram"]'
    end_runner = Runner()
    challenge.end(rt, runner=end_runner)
    sets = {a[-2]: a[-1] for a in end_runner.calls if a[-3] == "set"}
    assert sets["platforms.telegram.extra.allow_admin_from"] == '["${LP_ADMIN_ID}"]'
    assert "4242" not in repr(end_runner.calls)


def test_raw_refs_finds_references_at_any_depth_and_skips_env_keys():
    raw = {"platform_toolsets": {"telegram": "${TOOLSETS}"},
           "platforms": {"telegram": {"extra": {"allow_admin_from": ["1", "${ADMIN}"],
                                                "user_allowed_commands": []}}},
           "TELEGRAM_ALLOW_ALL_USERS": "${X}"}
    assert challenge.raw_refs(challenge.SETTING_KEYS, raw) == {
        "platform_toolsets.telegram": "${TOOLSETS}",
        "platforms.telegram.extra.allow_admin_from": '["1", "${ADMIN}"]'}


def test_no_settings_change_when_config_yaml_cannot_be_read_as_written(tmp_path, monkeypatch):
    def broken():
        raise ImportError("hermes_cli.config.read_user_config_raw")
    monkeypatch.setattr(challenge, "raw_config", broken)
    rt, item = make_rt(tmp_path)
    runner = Runner()
    out = challenge.start(rt, [item.key], runner=runner, reader=lambda k: None)
    assert runner.calls == [] and "NOT applied" in out and "restore" not in challenge.current(rt)


# ---- 6. every `hermes` child targets this plugin's profile ----------------------------------------
def test_children_get_the_profile_home_from_get_hermes_home_not_the_process_env(monkeypatch):
    """Every `hermes` child (config get/set/unset, the token check, duel and bench commands) targets the profile
    Hermes says the plugin runs in, so a TUI/Desktop per-session profile is the one checked and configured."""
    monkeypatch.undo()  # the real hermes_get / hermes_exit_code (conftest.py fakes them)
    fake = types.ModuleType("hermes_constants")
    fake.get_hermes_home = lambda: Path("C:/profiles/shop") if os.name == "nt" else Path("/profiles/shop")
    monkeypatch.setitem(sys.modules, "hermes_constants", fake)
    monkeypatch.setenv("HERMES_HOME", "/somewhere/else")
    want = str(fake.get_hermes_home())
    assert duel.child_env()["HERMES_HOME"] == want
    seen = []
    monkeypatch.setattr(duel, "run_child", lambda argv, **kw: seen.append(kw["env"]) or (0, "", ""))
    challenge.hermes_config([("set", "k", "v"), ("unset", "k")])
    challenge.hermes_get("memory.memory_enabled")
    challenge.hermes_exit_code("TELEGRAM_BOT_TOKEN")
    duel.hermes_cli(["gateway", "status"])
    assert len(seen) == 5 and all(env["HERMES_HOME"] == want for env in seen)
    assert all(set(env) <= set(duel.CHILD_ENV) for env in seen)  # 5. the minimal env for config set/unset too


def test_without_hermes_the_process_home_is_used(monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_constants", None)
    monkeypatch.setenv("HERMES_HOME", "/h")
    assert duel.child_env()["HERMES_HOME"] == "/h"


# ---- 7. a child that hangs -------------------------------------------------------------------------
HANG = ("import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], stdout=sys.stdout, stderr=sys.stderr)\n"
        "print('started', flush=True)\n"
        "time.sleep(60)\n")


def test_a_hung_child_and_its_grandchild_are_killed_at_the_timeout(tmp_path):
    """Review 2: a `hermes` child whose own child kept the pipes open turned a 2 s timeout into 72.9 s."""
    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        duel.run_child([sys.executable, "-c", HANG], env=dict(os.environ), timeout=2)
    assert time.monotonic() - t0 < 15


def test_the_memory_check_has_one_overall_deadline_and_fails_closed():
    calls = []

    def slow(key, timeout=None):
        calls.append(key)
        time.sleep(0.6)
        return 0, "false\n", ""
    t0 = time.monotonic()
    allowed, lines = challenge.memory_check(slow, deadline=1)
    assert allowed is False and time.monotonic() - t0 < 3
    assert len(calls) == 2 and "could not be read (TimeoutError)" in lines[-1]


def test_the_gate_passes_what_is_left_of_the_deadline_to_each_read(monkeypatch):
    seen = []
    monkeypatch.setattr(challenge, "hermes_get", lambda key, timeout=None: seen.append(timeout) or (0, "false\n", ""))
    challenge.memory_check(deadline=50)
    assert len(seen) == 3 and all(0 < t <= 50 for t in seen)


# ---- 10. refusals exit non-zero ---------------------------------------------------------------------
def test_cli_refusals_exit_1_and_everything_else_exits_0(tmp_path, monkeypatch, capsys):
    ctx = FakeCtx(tmp_path)
    last_price.register(ctx)
    cli = ctx.cli["lastprice"]["handler_fn"]
    run = lambda *argv: cli(types.SimpleNamespace(lp_args=list(argv)))  # noqa: E731
    assert run("sell", "Pixel", "ask", "300", "floor", "250") == 0
    assert run("list") == 0
    assert run("shop", "on", "telegram") == 0
    monkeypatch.setattr(challenge, "hermes_get", hermes_config_get(MEMORY_ON))
    assert run("shop", "on", "telegram") == 1
    assert run("challenge", "start", "pixel") == 1
    assert "Refused" in capsys.readouterr().out
    assert last_price.REFUSED_EXIT == 1


def test_docs_give_the_catalog_install_and_the_exit_code():
    for name in ("README.md", "SECURITY.md", "docs/CHALLENGE.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert challenge.CATALOG_INSTALL in text and "--ref" in text, name
        assert "hermes -p shop plugins install iamdflame/last-price" in text, name
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "exits 1" in readme
    assert challenge.CATALOG_INSTALL in challenge.PROFILE_HOWTO
