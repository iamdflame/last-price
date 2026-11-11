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
