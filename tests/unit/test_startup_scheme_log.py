"""The startup line reports the scheme actually served, never the one merely configured.

A certificate can only be handed to uvicorn when the server object is built, so a process
started without one serves cleartext no matter what `server.https` says in the file. Reading
the flag made the log announce `https://` over a plaintext socket — the single most damaging
thing this line can get wrong, because an operator checking whether TLS came up has nothing
else to look at in a container.

`IPMIDECK_TLS_ACTIVE` is set by whichever launcher resolved the certificate. An environment
variable rather than app state because `--reload` runs the app in a reloader subprocess.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def booted(tmp_path, monkeypatch, caplog):
    """Boot the app and hand back the log records the lifespan emitted."""
    def _boot(*, https: bool, tls_active: bool):
        monkeypatch.setenv("IPMIDECK_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("IPMIDECK_DEMO", "true")
        monkeypatch.setenv("IPMIDECK_DATA_DB_PATH", str(tmp_path / "ipmideck.db"))
        monkeypatch.setenv("IPMIDECK_SERVER_HTTPS", "true" if https else "false")
        if tls_active:
            monkeypatch.setenv("IPMIDECK_TLS_ACTIVE", "1")
        else:
            monkeypatch.delenv("IPMIDECK_TLS_ACTIVE", raising=False)

        from backend.main import app

        with caplog.at_level(logging.INFO, logger="ipmideck"):
            with TestClient(app):
                pass
        return "\n".join(r.getMessage() for r in caplog.records)

    return _boot


def test_plain_http_is_reported_as_http(booted):
    assert "started on http://" in booted(https=False, tls_active=False)


def test_a_resolved_certificate_is_reported_as_https(booted):
    log = booted(https=True, tls_active=True)
    assert "started on https://" in log
    assert "CLEARTEXT" not in log


def test_https_configured_but_not_served_does_not_claim_https(booted):
    """The container case that made this worth fixing: the config said yes, the socket did not."""
    log = booted(https=True, tls_active=False)
    assert "started on http://" in log
    assert "started on https://" not in log


def test_https_configured_but_not_served_says_so_loudly(booted):
    """Silently downgrading is how the operator ends up trusting a cleartext socket."""
    log = booted(https=True, tls_active=False)
    assert "CLEARTEXT" in log
