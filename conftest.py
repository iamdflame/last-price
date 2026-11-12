import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

# What `hermes config get <key> --json` prints in a dedicated shop profile with memory off
# (README, "The public challenge"); every other key: not set.
SHOP_PROFILE = {"memory.memory_enabled": "false", "memory.user_profile_enabled": "false", "memory.provider": '""'}


def shop_profile_get(key):
    if key in SHOP_PROFILE:
        return 0, SHOP_PROFILE[key] + "\n", ""
    return 1, "", f"Config key not set: {key}\n"


@pytest.fixture(autouse=True)
def _no_hermes_config(monkeypatch):
    """No test runs the real `hermes config get`: by default it answers as a dedicated shop profile;
    tests that need another answer pass their own getter or patch `challenge.hermes_get`."""
    from last_price import challenge

    monkeypatch.setattr(challenge, "hermes_get", shop_profile_get)
