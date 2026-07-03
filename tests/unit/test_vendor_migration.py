"""Vendor vocabulary normalization migration tests (08-01, D-02 / SC-1).

`Database.connect()` runs a one-shot, idempotent DATA migration that normalizes the
`servers.vendor` column onto the canonical six-value enum
(`dell | supermicro | hpe | lenovo | ibm | generic`):

  * lowercase any mixed-case value      ('HP' -> 'hp', 'Dell' -> 'dell')
  * retire the legacy value             ('hp' -> 'hpe')
  * sweep any remaining non-enum value  ('acme' -> 'generic')

NULL / '' rows are LEFT UNTOUCHED on purpose, so the runtime default 'dell'
(Phase-4 "Decision G") still applies to them elsewhere.

Uses the repo throwaway-DB pattern (`Database(tmp_path/...)` + `await connect()`); the
project's `asyncio_mode = "auto"` means async test functions need no decorator. Only
RFC5737 documentation hosts (192.0.2.x) and synthetic credentials appear here — never
real hosts or real credentials (CLAUDE.md public-repo rule).
"""

from __future__ import annotations

from backend.core.database import Database

# (id, seeded vendor) spanning every normalization case; None => SQL NULL, "" => empty.
_SEED = [
    ("s_hp", "hp"),      # legacy value              -> hpe
    ("s_HP", "HP"),      # mixed-case legacy         -> hpe
    ("s_Dell", "Dell"),  # mixed-case but valid      -> dell
    ("s_acme", "acme"),  # non-enum garbage          -> generic
    ("s_dell", "dell"),  # already canonical         -> unchanged
    ("s_null", None),    # NULL                      -> untouched (stays NULL)
    ("s_empty", ""),     # empty string              -> untouched (stays '')
]

# The expected post-migration vendor for each seeded id.
_EXPECTED = {
    "s_hp": "hpe",
    "s_HP": "hpe",
    "s_Dell": "dell",
    "s_acme": "generic",
    "s_dell": "dell",
    "s_null": None,
    "s_empty": "",
}


async def _insert_server(db: Database, sid: str, vendor: str | None) -> None:
    """INSERT a minimal server row with an explicit vendor (may be NULL); fill all NOT NULL cols.

    Passing vendor=None inserts SQL NULL, overriding the column DEFAULT 'dell' — that is
    exactly the row we need to prove the migration leaves NULL untouched.
    """
    await db.execute(
        "INSERT INTO servers (id, name, host, username_enc, password_enc, vendor) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (sid, f"srv-{sid}", "192.0.2.10", "x", "x", vendor),
    )
    await db.commit()


async def _vendor_of(db: Database, sid: str) -> str | None:
    row = await db.fetchone("SELECT vendor FROM servers WHERE id = ?", (sid,))
    assert row is not None
    return row["vendor"]


async def _seed_all(db: Database) -> None:
    for sid, vendor in _SEED:
        await _insert_server(db, sid, vendor)


async def _assert_all_expected(db: Database) -> None:
    for sid, expected in _EXPECTED.items():
        assert await _vendor_of(db, sid) == expected, sid


async def test_vendor_migration_normalizes_existing_rows(tmp_path):
    """Seed one row per case, then re-run connect() and assert each row is normalized.

    hp->hpe, HP->hpe, Dell->dell, acme->generic, dell unchanged, NULL untouched, '' untouched.
    """
    db_path = str(tmp_path / "vendor.db")

    # First connect() creates the schema; the migration runs over an EMPTY table (no-op).
    db = Database(db_path)
    await db.connect()
    await _seed_all(db)
    await db.close()

    # Re-open + connect() to RUN the normalization over the seeded rows.
    db = Database(db_path)
    await db.connect()
    await _assert_all_expected(db)
    await db.close()


async def test_vendor_migration_is_idempotent(tmp_path):
    """Running the normalization a SECOND time changes nothing (idempotent)."""
    db_path = str(tmp_path / "vendor_idem.db")

    db = Database(db_path)
    await db.connect()
    await _seed_all(db)
    await db.close()

    # First normalization pass.
    db = Database(db_path)
    await db.connect()
    await _assert_all_expected(db)
    await db.close()

    # Second normalization pass — values must be identical (no double-transform, no re-sweep).
    db = Database(db_path)
    await db.connect()
    await _assert_all_expected(db)
    await db.close()
