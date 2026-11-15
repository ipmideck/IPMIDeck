"""Environment overrides for the transport settings."""

from __future__ import annotations

from backend.core.config import load_config


def _isolate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IPMIDECK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPMIDECK_CONFIG_PATH", str(tmp_path / "config.yaml"))


def test_https_can_be_turned_on_from_the_environment(tmp_path, monkeypatch):
    """A container never runs the CLI, so this is its only way to enable TLS."""
    _isolate(tmp_path, monkeypatch)
    assert load_config().server.https is False
    monkeypatch.setenv("IPMIDECK_SERVER_HTTPS", "true")
    assert load_config().server.https is True


def test_https_env_accepts_the_same_spellings_as_the_other_flags(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    for value in ("true", "1", "yes", "TRUE"):
        monkeypatch.setenv("IPMIDECK_SERVER_HTTPS", value)
        assert load_config().server.https is True, value
    for value in ("false", "0", "no", ""):
        monkeypatch.setenv("IPMIDECK_SERVER_HTTPS", value)
        assert load_config().server.https is False, value


def test_certificate_paths_can_come_from_the_environment(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("IPMIDECK_SERVER_CERT_FILE", "/etc/tls/site.crt")
    monkeypatch.setenv("IPMIDECK_SERVER_KEY_FILE", "/etc/tls/site.key")
    cfg = load_config()
    assert cfg.server.cert_file == "/etc/tls/site.crt"
    assert cfg.server.key_file == "/etc/tls/site.key"
