"""Self-signed TLS certificate generation.

Uses the already-installed `cryptography` library's x509 CertificateBuilder — no openssl
subprocess, no system OpenSSL dependency, cross-platform. The generated key gets the same
owner-only file permissions as the at-rest encryption key (_set_secure_permissions).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from backend.core.crypto import _set_secure_permissions

logger = logging.getLogger("ipmideck.certs")

# Names every generated certificate covers regardless of how the machine is configured.
_BASE_DNS_NAMES = ("localhost", "ipmideck.local")
_BASE_IPS = ("127.0.0.1", "::1")


def _local_identities() -> tuple[list[str], list[str]]:
    """Best-effort list of the names and addresses this machine answers to.

    A dashboard is reached at whatever the operator typed — a LAN address, a short
    hostname, a `.local` name. A certificate that covers only loopback fails with a name
    mismatch, which browsers do NOT let you click through the way they do an unknown
    issuer. Resolution is wrapped because a box with broken DNS must still get a
    certificate rather than fail to start.
    """
    names: list[str] = []
    addresses: list[str] = []
    try:
        hostname = socket.gethostname()
        if hostname:
            names.append(hostname)
            try:
                fqdn = socket.getfqdn(hostname)
                if fqdn and fqdn != hostname:
                    names.append(fqdn)
            except OSError:
                pass
            try:
                for info in socket.getaddrinfo(hostname, None):
                    addresses.append(str(info[4][0]))
            except OSError:
                pass
    except OSError:
        logger.debug("Could not determine local host identity", exc_info=True)
    return names, addresses


def _subject_alt_names() -> x509.SubjectAlternativeName:
    dns_names, addresses = _local_identities()
    entries: list[x509.GeneralName] = []
    seen_names: set[str] = set()
    for name in (*_BASE_DNS_NAMES, *dns_names):
        lowered = name.lower()
        if lowered in seen_names:
            continue
        seen_names.add(lowered)
        try:
            entries.append(x509.DNSName(name))
        except ValueError:
            continue
    seen_ips: set[str] = set()
    for raw in (*_BASE_IPS, *addresses):
        # A scoped IPv6 literal ("fe80::1%eth0") is not a valid certificate entry.
        candidate = raw.split("%", 1)[0]
        if candidate in seen_ips:
            continue
        seen_ips.add(candidate)
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(candidate)))
        except ValueError:
            continue
    return x509.SubjectAlternativeName(entries)


def generate_self_signed(cert_dir: Path) -> tuple[Path, Path]:
    """Generate a 2048-bit self-signed cert+key pair. Returns (cert_path, key_path)."""
    cert_dir = Path(cert_dir)
    cert_dir.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ipmideck.local")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        # 825 days is the browser-accepted maximum for leaf certs.
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=825))
        .add_extension(_subject_alt_names(), critical=False)
        # Marking it a CA is what lets the operator add this file to the system trust
        # store and have it accepted there: macOS and Windows will not anchor trust on a
        # plain end-entity certificate, so without this the warning cannot be removed.
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_cert_sign=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
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


def resolve_tls_files(config) -> tuple[str, str] | None:
    """Return the cert/key pair to serve with, generating one if needed.

    Returns None when TLS is off or cannot be set up, in which case the caller serves
    plain HTTP. Falling back is deliberate: locking an operator out of their own
    dashboard over a certificate problem is worse than plaintext on a trusted LAN, which
    is what they had a moment ago anyway. The fallback is always logged.
    """
    if not config.server.https:
        return None

    cert_file = config.server.cert_file
    key_file = config.server.key_file
    if cert_file and key_file and Path(cert_file).is_file() and Path(key_file).is_file():
        return str(cert_file), str(key_file)

    cert_dir = Path(config.data.db_path).parent / "certs"
    default_cert = cert_dir / "server.crt"
    default_key = cert_dir / "server.key"
    if default_cert.is_file() and default_key.is_file():
        return str(default_cert), str(default_key)

    try:
        cert_path, key_path = generate_self_signed(cert_dir)
    except Exception:
        logger.exception("Could not create a certificate — starting over plain HTTP instead")
        return None

    logger.warning(
        "No certificate found, so a self-signed one was created at %s. Browsers will warn "
        "that the issuer is unknown: the connection is still encrypted, only the identity "
        "is unverified. Import the certificate or point server.cert_file/key_file at your "
        "own to remove the warning.",
        cert_path,
    )
    return str(cert_path), str(key_path)
