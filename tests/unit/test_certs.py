"""Self-signed certificate generation and the TLS resolution that drives it."""

from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from backend.core.certs import generate_self_signed, resolve_tls_files
from backend.core.config import AppConfig, DataConfig, ServerConfig


def _load(cert_path: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(cert_path.read_bytes())


def _config(tmp_path: Path, **server) -> AppConfig:
    cfg = AppConfig()
    cfg.server = ServerConfig(**server)
    cfg.data = DataConfig(db_path=str(tmp_path / "ipmideck.db"))
    return cfg


def test_generated_pair_is_a_usable_certificate_and_key(tmp_path):
    cert_path, key_path = generate_self_signed(tmp_path / "certs")
    assert cert_path.is_file() and key_path.is_file()
    cert = _load(cert_path)
    assert cert.not_valid_after_utc > cert.not_valid_before_utc
    # Browsers refuse leaf certificates valid for more than 825 days.
    assert (cert.not_valid_after_utc - cert.not_valid_before_utc).days <= 825
    assert load_pem_private_key(key_path.read_bytes(), password=None).key_size == 2048


def test_certificate_covers_loopback_and_this_machine(tmp_path):
    """A certificate that only covers localhost fails with a name mismatch on a LAN."""
    cert_path, _ = generate_self_signed(tmp_path / "certs")
    san = _load(cert_path).extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value
    names = set(san.get_values_for_type(x509.DNSName))
    addresses = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}

    assert "localhost" in names
    assert "127.0.0.1" in addresses
    assert socket.gethostname() in names


def test_certificate_can_be_added_to_a_trust_store(tmp_path):
    """Without these, the browser warning cannot be removed by importing the file."""
    cert_path, _ = generate_self_signed(tmp_path / "certs")
    exts = _load(cert_path).extensions
    assert exts.get_extension_for_class(x509.BasicConstraints).value.ca is True
    assert exts.get_extension_for_class(x509.KeyUsage).value.key_cert_sign is True
    eku = exts.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert x509.oid.ExtendedKeyUsageOID.SERVER_AUTH in eku


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_private_key_is_owner_only(tmp_path):
    _, key_path = generate_self_signed(tmp_path / "certs")
    assert oct(key_path.stat().st_mode)[-3:] == "600"


def test_generating_twice_overwrites_cleanly(tmp_path):
    first_cert, _ = generate_self_signed(tmp_path / "certs")
    first_serial = _load(first_cert).serial_number
    second_cert, _ = generate_self_signed(tmp_path / "certs")
    assert second_cert == first_cert
    assert _load(second_cert).serial_number != first_serial


def test_plain_http_stays_the_explicit_default(tmp_path):
    assert resolve_tls_files(_config(tmp_path)) is None
    assert not (tmp_path / "certs").exists()


def test_enabling_https_without_a_certificate_creates_one(tmp_path):
    resolved = resolve_tls_files(_config(tmp_path, https=True))
    assert resolved is not None
    cert_file, key_file = resolved
    assert Path(cert_file) == tmp_path / "certs" / "server.crt"
    assert Path(key_file).is_file()


def test_an_existing_certificate_is_never_regenerated(tmp_path):
    cfg = _config(tmp_path, https=True)
    cert_file, _ = resolve_tls_files(cfg)
    serial = _load(Path(cert_file)).serial_number
    again_cert, _ = resolve_tls_files(cfg)
    assert _load(Path(again_cert)).serial_number == serial


def test_a_configured_certificate_is_used_as_given(tmp_path):
    custom = tmp_path / "mine"
    cert_path, key_path = generate_self_signed(custom)
    resolved = resolve_tls_files(
        _config(tmp_path, https=True, cert_file=str(cert_path), key_file=str(key_path))
    )
    assert resolved == (str(cert_path), str(key_path))
    # The default location must not have been touched.
    assert not (tmp_path / "certs").exists()


def test_a_configured_path_that_does_not_exist_falls_back_to_generating(tmp_path):
    """Pointing at a missing file must not leave the operator with no dashboard at all."""
    resolved = resolve_tls_files(
        _config(tmp_path, https=True, cert_file="/nonexistent/a.crt", key_file="/nonexistent/a.key")
    )
    assert resolved is not None
    assert Path(resolved[0]) == tmp_path / "certs" / "server.crt"


def test_generation_failure_falls_back_to_plain_http(tmp_path, monkeypatch):
    """A certificate problem must never be the reason the dashboard is unreachable."""
    monkeypatch.setattr(
        "backend.core.certs.generate_self_signed",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("read-only")),
    )
    assert resolve_tls_files(_config(tmp_path, https=True)) is None


def test_a_broken_hostname_lookup_still_yields_a_certificate(tmp_path, monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("no DNS")

    monkeypatch.setattr(socket, "gethostname", _boom)
    cert_path, _ = generate_self_signed(tmp_path / "certs")
    san = _load(cert_path).extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value
    assert "localhost" in set(san.get_values_for_type(x509.DNSName))
    assert ipaddress.ip_address("127.0.0.1") in san.get_values_for_type(x509.IPAddress)
