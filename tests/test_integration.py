"""Against the installed Hermes (opt-in): LASTPRICE_HERMES_IT=1 python -m pytest tests/test_integration.py

Run it with the Python that runs Hermes (its venv), so ``hermes_cli`` imports.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.environ.get("LASTPRICE_HERMES_IT") != "1", reason="set LASTPRICE_HERMES_IT=1")


def _hermes():
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
    exe = Path(_hermes())
    py = next((p for p in (exe.parent / "python.exe", exe.parent / "python") if p.exists()), None)
    if py is None:
        pytest.skip("Hermes's interpreter not found beside the hermes launcher")
    code = ("import sys; sys.path.insert(0, '.'); from last_price.runtime import Runtime; "
            "from last_price.state import MemoryState; rt = Runtime(MemoryState()); "
            "print('deal:', rt.resolve('local-does-not-exist'))")
    env = {**os.environ, "HERMES_HOME": str(tmp_path)}
    out = subprocess.run([str(py), "-c", code], cwd=ROOT, capture_output=True, text=True, env=env, timeout=120)
    assert "deal: None" in out.stdout, out.stderr[-1500:]
