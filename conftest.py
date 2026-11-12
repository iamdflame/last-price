import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

# What real `hermes config get <key> --json` prints (Hermes 0.23.1): the value with Hermes's defaults merged,
# as one line of JSON, exit 0. Only a key with no default exits 1 with "Config key not set: <key>" on stderr.
# An absent memory flag prints its default, `true`; an absent memory.provider prints `""`.
HERMES_DEFAULTS = {"memory.memory_enabled": "true", "memory.user_profile_enabled": "true", "memory.provider": '""'}
# A dedicated shop profile with memory off (README, "The public challenge").
SHOP_PROFILE = {"memory.memory_enabled": "false", "memory.user_profile_enabled": "false", "memory.provider": '""'}


def hermes_config_get(answers):
    """A fake `hermes config get <key> --json` for a profile whose config.yaml sets ``answers``."""
    def get(key, timeout=None):
        if key in answers:
            return 0, answers[key] + "\n", ""
        if key in HERMES_DEFAULTS:
            return 0, HERMES_DEFAULTS[key] + "\n", ""
        return 1, "", f"Config key not set: {key}\n"
    return get


shop_profile_get = hermes_config_get(SHOP_PROFILE)


@pytest.fixture(autouse=True)
def _no_hermes_config(monkeypatch):
    """No test runs the real `hermes`: by default it answers as a dedicated shop profile (the CLI reads,
    the in-process chat gate, the raw config.yaml with no ${VAR} reference, and no bot token); tests that
    need another answer pass their own getter or patch these."""
    from last_price import challenge

    monkeypatch.setattr(challenge, "hermes_get", shop_profile_get)
    monkeypatch.setattr(challenge, "chat_get", shop_profile_get)
    monkeypatch.setattr(challenge, "raw_config", lambda: {})
    monkeypatch.setattr(challenge, "hermes_exit_code", lambda key: 1)
