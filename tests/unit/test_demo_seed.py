"""Demo-seed idempotency + public-repo hygiene unit tests (08-04, D-16 / SC-6).

`backend.main._seed_demo_servers(db, auth)` seeds ONE synthetic server per canonical vendor
(dell, supermicro, hpe, lenovo, ibm, generic — 6 total) when demo mode is active, so the
per-vendor journeys (tier badges, monitoring-only warnings, loop-skip, argv routing) are
visible + Playwright-testable WITHOUT hardware. It is idempotent: re-seeding on every restart
(INSERT OR IGNORE on deterministic `demo-<vendor>` ids) adds NO duplicate rows.

Uses the conftest `auth_manager` fixture (Strategy C — yields an initialized (am, db) on a
tmp_path on-disk DB) so encrypt() has a real key. Only RFC5737 documentation hosts
(192.0.2.x / 198.51.100.x / 203.0.113.x) and synthetic throwaway credentials appear here —
never a real host, serial, or credential (CLAUDE.md public-repo rule). The project's
`asyncio_mode = "auto"` means async test functions need no decorator.
"""

from __future__ import annotations

import ipaddress

from backend.main import _seed_demo_servers

# The canonical six-value vendor enum (server_routes.Vendor) — one demo server per vendor.
_EXPECTED_VENDORS = {"dell", "supermicro", "hpe", "lenovo", "ibm", "generic"}

# RFC5737 documentation ranges — the ONLY host space allowed in a public repo (CLAUDE.md).
_RFC5737_NETS = [
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
]

# Real LAN ranges — a seeded host landing here would mean a real-host leak (must NOT happen).
_LAN_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]


def _is_rfc5737(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in _RFC5737_NETS)


async def _servers(db) -> list[dict]:
    return await db.fetchall("SELECT id, host, vendor FROM servers")


async def test_seed_creates_exactly_six_vendor_servers(auth_manager):
    """A fresh DB seeded once holds exactly 6 rows, one per canonical vendor, RFC5737 hosts."""
    am, db = auth_manager

    await _seed_demo_servers(db, am)

    rows = await _servers(db)
    assert len(rows) == 6
    assert {r["vendor"] for r in rows} == _EXPECTED_VENDORS
    for r in rows:
        assert _is_rfc5737(r["host"]), r["host"]


async def test_seed_is_idempotent(auth_manager):
    """Seeding a SECOND time adds NO duplicate rows (still exactly 6 — INSERT OR IGNORE)."""
    am, db = auth_manager

    await _seed_demo_servers(db, am)
    await _seed_demo_servers(db, am)

    rows = await _servers(db)
    assert len(rows) == 6
    # One row per vendor even after re-seeding (no duplicates), all with distinct deterministic ids.
    assert sorted(r["vendor"] for r in rows) == sorted(_EXPECTED_VENDORS)
    assert len({r["id"] for r in rows}) == 6


async def test_seed_hosts_are_not_real_lan_addresses(auth_manager):
    """Public-repo hygiene: no seeded host is in a real LAN range (10/8, 172.16/12, 192.168/16)."""
    am, db = auth_manager

    await _seed_demo_servers(db, am)

    for r in await _servers(db):
        addr = ipaddress.ip_address(r["host"])
        assert not any(addr in net for net in _LAN_NETS), r["host"]
        assert _is_rfc5737(r["host"]), r["host"]
