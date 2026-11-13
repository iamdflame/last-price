"""Against the installed Hermes (opt-in): LASTPRICE_HERMES_IT=1 python -m pytest tests/test_integration.py

Run pytest with your own Python and append Hermes's venv (``Scripts`` on Windows, ``bin`` elsewhere) to
the END of PATH (README, "More"). The tests use the ``hermes`` in the first PATH folder that also holds
Hermes's Python (so a ``hermes`` launcher earlier on PATH does not hide the venv), and run the
deal-session lookup in that Python, where ``hermes_state`` imports.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.environ.get("LASTPRICE_HERMES_IT") != "1", reason="set LASTPRICE_HERMES_IT=1")


def _beside(exe):
    """Hermes's Python beside a ``hermes`` launcher (its venv), or None."""
    folder = Path(exe).parent
    return next((p for p in (folder / "python.exe", folder / "python") if p.exists()), None)


def _hermes():
    """The ``hermes`` of a venv on PATH (one with its Python beside it), else the first ``hermes``."""
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        exe = shutil.which("hermes", path=folder) if folder else None
        if exe and _beside(exe):
            return exe
    exe = shutil.which("hermes")
    if not exe:
        pytest.skip("hermes is not on PATH")
    return exe


def test_validate_passes_without_private_imports():
    out = subprocess.run([_hermes(), "plugins", "validate", str(ROOT)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300)
    text = out.stdout + out.stderr
    assert "Validation passed" in text, text[-2000:]
    assert "private core" not in text


def test_runtime_reads_titles_through_public_hermes_state(tmp_path):
    """In Hermes's own interpreter: the deal-session lookup uses hermes_state.SessionDB (public) and a
    session that is not a duel resolves to no deal."""
    py = _beside(_hermes())
    if py is None:
        pytest.skip("Hermes's interpreter not found beside the hermes launcher")
    code = ("import sys; sys.path.insert(0, '.'); from last_price.runtime import Runtime; "
            "from last_price.state import MemoryState; rt = Runtime(MemoryState()); "
            "print('deal:', rt.resolve('local-does-not-exist'))")
    env = {**os.environ, "HERMES_HOME": str(tmp_path)}
    out = subprocess.run([str(py), "-c", code], cwd=ROOT, capture_output=True, text=True, env=env, timeout=120)
    assert "deal: None" in out.stdout, out.stderr[-1500:]


def _free_port():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_held_chat_stays_held_across_a_restart_until_release(tmp_path):
    """Review 3 #1 against Hermes's own AIAgent: a telegram-sourced stranger chat, a local fake OpenAI-compatible
    endpoint (tests/it_fake_llm.py), each turn in a new process (tests/it_turn.py), as a restarted gateway would.
    The chat starts while memory is on (held; Hermes saves its prompt with MEMORY.md in it); with memory off and a
    new process it stays held (0.1.5 sent that prompt to the model); after `shop release` (which runs `hermes
    sessions refresh-prompts`) the next turn reaches the model with no memory in the system message."""
    import json
    import shutil as _sh
    import sys

    hermes = _hermes()
    py = _beside(hermes)
    if py is None:
        pytest.skip("Hermes's interpreter not found beside the hermes launcher")
    home = tmp_path / "h"
    (home / "memories").mkdir(parents=True)
    plug = home / "plugins" / "last-price"
    plug.mkdir(parents=True)
    _sh.copytree(ROOT / "last_price", plug / "last_price", ignore=_sh.ignore_patterns("__pycache__"))
    for name in ("__init__.py", "plugin.yaml"):
        _sh.copy(ROOT / name, plug / name)
    port, log = _free_port(), tmp_path / "requests.jsonl"
    (home / "config.yaml").write_text(
        f"model:\n  default: fake-model\n  provider: custom\n  base_url: http://127.0.0.1:{port}/v1\n"
        "memory:\n  memory_enabled: false\n  user_profile_enabled: false\nplugins:\n  enabled:\n  - last-price\n",
        encoding="utf-8")
    (home / "memories" / "MEMORY.md").write_text("OWNER-MEMORY-MARKER: the owner's private note.\n", encoding="utf-8")
    env = {**os.environ, "HERMES_HOME": str(home), "HERMES_DISABLE_LAZY_INSTALLS": "1", "PYTHONIOENCODING": "utf-8",
           "PATH": str(Path(hermes).parent) + os.pathsep + os.environ.get("PATH", "")}
    fake = subprocess.Popen([sys.executable, str(ROOT / "tests" / "it_fake_llm.py"), str(port), str(log)])

    def run(*args):
        out = subprocess.run([hermes, *args], env=env, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=300)
        return out.returncode, out.stdout + out.stderr

    def chat_requests():
        rows = [json.loads(ln)["messages"] for ln in (log.read_text(encoding="utf-8").splitlines() if log.exists() else [])]
        return [m for m in rows if not any("You name chat sessions" in str(x.get("content")) for x in m
                                           if x.get("role") == "system")]

    def turn(sid, text):
        before = len(chat_requests())
        out = subprocess.run([str(py), str(ROOT / "tests" / "it_turn.py"), sid, text, str(port)], env=env,
                             cwd=str(Path(py).parents[2]), capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=300)
        line = next((ln for ln in out.stdout.splitlines() if ln.startswith("VERDICT ")), None)
        assert line, out.stderr[-2000:]
        new = chat_requests()[before:]
        memory = any("OWNER-MEMORY-MARKER" in str(x.get("content")) for m in new for x in m if x.get("role") == "system")
        return json.loads(line[8:]), len(new), memory

    try:
        assert run("lastprice", "sell", "Pixel 7", "ask", "420", "floor", "360")[0] == 0
        assert run("lastprice", "shop", "on", "telegram")[0] == 0
        assert run("config", "set", "memory.memory_enabled", "true")[0] == 0
        verdict, calls, _mem = turn("tg-it", "Hi, would you take 300?")  # 1. memory on: held
        assert calls == 0 and verdict["stored_prompt_has_marker"] is True
        assert run("config", "set", "memory.memory_enabled", "false")[0] == 0
        verdict, calls, _mem = turn("tg-it", "OK, 350 then?")  # 2. memory off, a new process: still held
        assert calls == 0, "a held chat reached the model after memory off and a restart"
        assert "held stranger chats: 1" in run("lastprice", "doctor")[1]
        code, text = run("lastprice", "shop", "release")  # 3. memory off, no gateway: refresh, then release
        assert code == 0 and text.startswith("Released 1 chat(s)"), text[-1500:]
        verdict, calls, memory = turn("tg-it", "Fine, 360?")  # 4. the next turn: no memory in the system message
        assert calls == 1 and memory is False and verdict["stored_prompt_has_marker"] is False
    finally:
        fake.kill()
