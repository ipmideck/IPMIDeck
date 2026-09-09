"""The configuration file only advertises keys the code actually reads."""

from __future__ import annotations

from pathlib import Path

import yaml

from backend.core.config import AuthConfig, load_config, save_default_config

REPO_ROOT = Path(__file__).resolve().parents[2]

# Keys that used to be advertised but were never read. A working `enabled` key would be a
# second, weaker switch for a security control: anyone able to edit the file could turn the
# login off. It is therefore removed rather than implemented, and must not come back.
REMOVED_AUTH_KEYS = ("enabled", "max_login_attempts", "lockout_duration")


def test_auth_config_exposes_only_the_setting_that_works():
    assert set(AuthConfig.__dataclass_fields__) == {"session_expiry"}


def test_example_config_has_no_inert_auth_keys():
    raw = yaml.safe_load((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    assert "session_expiry" in raw["auth"], "the one working key must stay documented"
    for key in REMOVED_AUTH_KEYS:
        assert key not in raw["auth"], f"{key} does nothing and must not be advertised"


def test_example_config_loads():
    config = load_config(str(REPO_ROOT / "config.example.yaml"))
    assert config.auth.session_expiry == "24h"


def test_example_poll_intervals_match_the_code_defaults():
    """A shipped example that disagrees with the defaults is a documentation bug.

    command_timeout in particular was advertised as 10s while the real default is 30s,
    which exists because a real BMC's sensor listing can take around 16 seconds.
    """
    raw = yaml.safe_load((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    config = load_config(str(REPO_ROOT / "config.example.yaml"))
    assert raw["ipmi"]["poll_interval"] == config.ipmi.poll_interval == 30
    assert raw["ipmi"]["power_poll_interval"] == config.ipmi.power_poll_interval == 30
    assert raw["ipmi"]["command_timeout"] == config.ipmi.command_timeout == 30


def test_first_run_does_not_regenerate_the_removed_keys(tmp_path):
    """First run writes the file, so missing it here would reintroduce the dead keys."""
    path = tmp_path / "config.yaml"
    save_default_config(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["auth"] == {"session_expiry": "24h"}


def test_existing_config_with_removed_keys_still_loads(tmp_path):
    """An already-deployed file keeps working: unknown keys are ignored, not fatal."""
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump(
            {
                "auth": {
                    "enabled": False,
                    "session_expiry": "2h",
                    "max_login_attempts": 9,
                    "lockout_duration": "5m",
                }
            }
        ),
        encoding="utf-8",
    )
    config = load_config(str(path))
    assert config.auth.session_expiry == "2h"
