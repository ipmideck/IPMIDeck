"""The container health check probes the port the server was actually started on.

A command-line port wins over IPMIDECK_SERVER_PORT and config.yaml, and under host networking
overriding the command is the only way to move the port, so the check reads it from there.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "docker_healthcheck", Path(__file__).resolve().parents[2] / "docker-healthcheck.py"
)
healthcheck = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(healthcheck)


@pytest.mark.parametrize(
    "argv, port",
    [
        (["/usr/local/bin/python", "/usr/local/bin/ipmideck", "--host", "0.0.0.0",
          "--port", "3000", "start"], 3000),
        (["/usr/local/bin/python", "/usr/local/bin/ipmideck", "--port", "8080", "start"], 8080),
        (["python", "-m", "backend.main", "--port=9443", "start"], 9443),
        (["/usr/local/bin/python", "/usr/local/bin/ipmideck", "start"], None),
        (["python", "/usr/local/bin/docker-healthcheck.py"], None),
        (["nginx", "--port", "80"], None),
        (["/usr/local/bin/ipmideck", "--port", "not-a-number"], None),
    ],
)
def test_port_is_read_from_an_ipmideck_command_line(argv, port):
    assert healthcheck.port_from_argv(argv) == port


def test_falls_back_to_the_variable_then_the_default(monkeypatch, tmp_path):
    monkeypatch.setattr(healthcheck, "Path", lambda _p: tmp_path)  # no processes to read
    monkeypatch.setenv("IPMIDECK_SERVER_PORT", "8181")
    assert healthcheck.served_port() == 8181
    monkeypatch.delenv("IPMIDECK_SERVER_PORT")
    assert healthcheck.served_port() == 3000
