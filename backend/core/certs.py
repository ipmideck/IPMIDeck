"""Self-signed TLS certificate generation (04-W4-03).

Uses the already-installed `cryptography` library's x509 CertificateBuilder — no openssl
subprocess, no system OpenSSL dependency, cross-platform. The generated key gets the same
owner-only file permissions as the at-rest encryption key (_set_secure_permissions).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from backend.core.crypto import _set_secure_permissions


def generate_self_signed(cert_dir: Path) -> tuple[Path, Path]:
    """Generate a 2048-bit self-signed cert+key pair. Returns (cert_path, key_path)."""
    cert_dir = Path(cert_dir)
    cert_dir.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ipmilink.local")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        # 825 days is the browser-accepted maximum for leaf certs.
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName("ipmilink.local"),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = cert_dir / "server.crt"
    key_path = cert_dir / "server.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    _set_secure_permissions(key_path)
    return cert_path, key_path
