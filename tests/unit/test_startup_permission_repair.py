"""An already-deployed config.yaml is tightened on start, not only when it is written back.

The release notes promise that existing installations are repaired automatically on the next
start. That was true of the database, which re-applies the mode on every `connect()`, but not
of config.yaml: it was only tightened when something wrote it back, so an install whose
operator never changed a network setting kept a world-readable file holding the session secret
for as long as it ran.

The wiring test runs everywhere; the mode assertion is POSIX-only, because on Windows
`_set_secure_permissions` rewrites the NTFS ACL rather than the mode bits.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.core.config import save_default_config


def _boot(tmp_path, monkeypatch) -> Path:
    """Boot the app against a tmp data dir holding a config left loose by an older version."""
    monkeypatch.setenv("IPMIDECK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPMIDECK_DEMO", "true")
    monkeypatch.setenv("IPMIDECK_DATA_DB_PATH", str(tmp_path / "ipmideck.db"))

    path = tmp_path / "config.yaml"
    save_default_config(path)
    if os.name != "nt":
        os.chmod(path, 0o644)
    return path


def test_startup_tightens_an_existing_config(tmp_path, monkeypatch):
    """Proves the call is wired into the startup path on every platform."""
    path = _boot(tmp_path, monkeypatch)

    import backend.main as bm

    seen: list[Path] = []
    real = bm._set_secure_permissions
    monkeypatch.setattr(bm, "_set_secure_permissions", lambda p: (seen.append(Path(p)), real(p))[1])

    with TestClient(bm.app):
        pass

    assert path in seen, seen


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits; Windows takes the ACL path instead")
def test_startup_leaves_the_config_owner_only(tmp_path, monkeypatch):
    path = _boot(tmp_path, monkeypatch)

    from backend.main import app

    with TestClient(app):
        pass

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_startup_does_not_fail_when_there_is_no_config(tmp_path, monkeypatch):
    """A first run has nothing to repair; the guard must not turn that into a crash."""
    monkeypatch.setenv("IPMIDECK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPMIDECK_DEMO", "true")
    monkeypatch.setenv("IPMIDECK_DATA_DB_PATH", str(tmp_path / "ipmideck.db"))

    from backend.main import app

    with TestClient(app):
        pass

    assert (tmp_path / "config.yaml").exists()  # written by save_default_config instead
