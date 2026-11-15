"""A newer version found by the unattended check is announced once, with the command to install it.

Before, the only trace was an INFO record, which the console hides at its WARNING verbosity, so an
operator who never pressed [g] or opened the web UI never heard about a release.
"""

from __future__ import annotations

import logging
import sys

import pytest

from backend.core import updates
from backend.core.update_service import UpdateService, UpdateStatus


def _found(version="99.0.0", method="pip", **fields) -> UpdateStatus:
    return UpdateStatus(
        latest_version=version, update_available=True, install_method=method, **fields
    )


# === The command ===


def test_docker_is_upgraded_from_outside_the_container():
    assert updates.upgrade_command("docker", "9.9.9") == "docker compose pull && docker compose up -d"


def test_a_checkout_moves_to_the_release_tag():
    assert updates.upgrade_command("git", "9.9.9") == "git fetch --tags && git checkout v9.9.9"


def test_a_package_install_upgrades_the_interpreter_that_is_running(monkeypatch):
    monkeypatch.setattr(sys, "executable", "/opt/ipmideck/bin/python")
    assert (
        updates.upgrade_command("pip", "9.9.9")
        == "/opt/ipmideck/bin/python -m pip install --upgrade ipmideck==9.9.9"
    )


def test_an_interpreter_path_with_spaces_is_quoted(monkeypatch):
    monkeypatch.setattr(sys, "executable", "C:/Program Files/Python/python.exe")
    assert updates.upgrade_command("pip", "9.9.9").startswith('"C:/Program Files/Python/python.exe"')


def test_an_unknown_install_gets_no_invented_command():
    assert updates.upgrade_command("unknown", "9.9.9") is None


# === The announcement ===


def test_the_console_hears_about_a_version_once():
    service = UpdateService(None, None)
    heard = []
    service.announce = heard.append
    for _ in range(3):
        service._announce_once(_found())
    assert [s.latest_version for s in heard] == ["99.0.0"]


def test_a_later_version_is_announced_again():
    service = UpdateService(None, None)
    heard = []
    service.announce = heard.append
    service._announce_once(_found("99.0.0"))
    service._announce_once(_found("99.1.0"))
    assert [s.latest_version for s in heard] == ["99.0.0", "99.1.0"]


@pytest.mark.parametrize(
    "status",
    [UpdateStatus(), UpdateStatus(latest_version="1.0.0", update_available=False)],
    ids=["nothing-known", "up-to-date"],
)
def test_nothing_is_announced_without_a_newer_version(status):
    service = UpdateService(None, None)
    heard = []
    service.announce = heard.append
    service._announce_once(status)
    assert heard == []


def test_without_a_console_the_log_carries_it_above_the_default_verbosity(caplog, monkeypatch):
    monkeypatch.setattr(sys, "executable", "/opt/ipmideck/bin/python")
    service = UpdateService(None, None)
    with caplog.at_level(logging.WARNING, logger="ipmideck.updates"):
        service._announce_once(_found(is_security=True))
        service._announce_once(_found(is_security=True))
    records = [r.getMessage() for r in caplog.records]
    assert len(records) == 1
    assert "99.0.0" in records[0] and "security release" in records[0]
    assert "pip install --upgrade ipmideck==99.0.0" in records[0]


def test_a_failing_console_does_not_break_the_check():
    service = UpdateService(None, None)

    def broken(status):
        raise RuntimeError("console gone")

    service.announce = broken
    service._announce_once(_found())  # must not raise


def test_the_console_line_includes_the_command(monkeypatch):
    from backend.main import _report_update_status

    monkeypatch.setattr(sys, "executable", "/opt/ipmideck/bin/python")
    shown = []
    _report_update_status(_found(method="docker"), lambda line, style="": shown.append(line))
    assert "Upgrade with: docker compose pull && docker compose up -d" in shown
