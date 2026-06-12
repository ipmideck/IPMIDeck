"""Simple local authentication — optional, single user, session-based."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from pathlib import Path

import bcrypt

from fastapi import HTTPException, Request

from backend.core.crypto import _set_secure_permissions, decrypt, encrypt
from backend.core.database import Database

logger = logging.getLogger("ipmilink.auth")

SESSION_EXPIRY_SECONDS = 86400  # 24h default


class AuthManager:
    def __init__(self, db: Database):
        self.db = db
        # Session-token HMAC signing secret (kept in memory after initialize()).
        # Persisted separately under app_config['session_secret'] — distinct from the
        # at-rest credential encryption key, which lives in data/encryption.key.
        self._secret: str = ""
        # 04-W4-04 (Decision I): at-rest credential encryption key, loaded from
        # data/encryption.key (or generated/migrated by initialize()). The single
        # source for get_encryption_key(); no longer derived from _secret.
        self._file_key: bytes = b""
        # SEC-03 brute-force lockout state (D-01, D-02): per-username, in-memory.
        # Resets on server restart per D-02 (acceptable for LAN single-process).
        # Format: {username: {"count": int, "last_failure": float, "locked_until": float}}
        # Times are time.monotonic() seconds — do NOT mix with time.time().
        self._fail_state: dict[str, dict] = {}
        self._fail_lock = asyncio.Lock()

    @staticmethod
    def _derive_old_key(db_secret: str) -> bytes:
        """The pre-04-W4-04 credential key: PBKDF2 over the in-DB app_secret.

        Identical to the old get_encryption_key() derivation, so it can decrypt
        credentials that were encrypted before the file-key migration.
        """
        return hashlib.pbkdf2_hmac(
            "sha256", db_secret.encode(), b"ipmilink-cred-enc", 100000, dklen=32
        )

    async def initialize(self) -> None:
        """Load or CRASH-SAFE-migrate the at-rest credential encryption key.

        Decision H: data_dir is derived from ``Path(self.db.db_path).parent`` —
        AuthManager only holds a Database, it has NO ``.config`` attribute.

        Decision I: the migration from the in-DB ``app_secret`` (PBKDF2-derived key)
        to a file-based ``data/encryption.key`` is crash-safe. The hard rule is that
        the in-DB ``app_secret`` is the ONLY canonical key holder until the file key is
        proven to decrypt the existing rows; it is deleted LAST, after the key file is
        durably in place. Four cases:

        CASE 1 — BOTH ``encryption.key`` AND ``app_secret`` exist (crash recovery):
          a partial migration left both behind. Verify the FILE key can decrypt a real
          credential row. If yes → the DB rows are already re-encrypted with the file
          key, so finish by deleting ``app_secret``. If NO → the file key is wrong (the
          re-encrypt transaction never committed); keep ``app_secret`` as canonical,
          fall back to the PBKDF2 key, and abort the migration WITHOUT corrupting data.

        CASE 2 — ``encryption.key`` only → steady state; the file is authoritative.

        CASE 3 — ``app_secret`` only, no file key → run the migration:
          (a) decrypt every ``*_enc`` row in memory with the old key (fails here leaves
              everything untouched);
          (b) write the new key to ``encryption.key.tmp`` + secure perms;
          (c) re-encrypt the rows inside a DB transaction and COMMIT;
          (d) atomic ``os.replace(.tmp -> encryption.key)``;
          (e) ONLY THEN delete ``app_secret``.
          A crash between (c) and (d) leaves the .tmp + the re-encrypted rows + the
          ``app_secret`` row → next boot lands in CASE 1 and finishes cleanly.

        CASE 4 — neither exists → first-run greenfield; generate a fresh file key.

        The session-signing secret is migrated/preserved separately (CASE 1/3 copy the
        old app_secret value into ``session_secret`` BEFORE deleting it, so existing
        session cookies stay valid across the upgrade) via ``_setup_session_secret()``.
        """
        # Decision H: data_dir from db.db_path (AuthManager has no AppConfig attribute).
        data_dir = Path(self.db.db_path).parent
        key_path = data_dir / "encryption.key"
        tmp_path = key_path.with_suffix(".tmp")
        db_secret = await self.db.get_config("app_secret")

        # CASE 1 — both exist: a partial migration. Verify before deleting anything.
        if key_path.exists() and db_secret:
            file_key = key_path.read_bytes()
            if len(file_key) != 32:
                raise RuntimeError(
                    f"Invalid encryption.key length: expected 32, got {len(file_key)}"
                )
            sample = await self.db.fetchone(
                "SELECT username_enc FROM servers WHERE username_enc IS NOT NULL LIMIT 1"
            )
            file_key_ok: bool
            if sample is None:
                # No credential rows to verify against — accept the file key as
                # canonical (nothing to corrupt) and drop the obsolete app_secret.
                file_key_ok = True
            else:
                try:
                    decrypt(sample["username_enc"], file_key)
                    file_key_ok = True
                except Exception:
                    file_key_ok = False

            if file_key_ok:
                # File key works → the re-encrypt transaction committed. Preserve the
                # session secret, then delete app_secret to finish the migration.
                await self._migrate_session_secret(db_secret)
                await self.db.execute("DELETE FROM app_config WHERE key=?", ("app_secret",))
                await self.db.commit()
                self._file_key = file_key
                await self._setup_session_secret()
                logger.info("encryption.key recovery: file key verified; app_secret removed")
                return
            # File key does NOT decrypt — the re-encrypt never committed. Keep
            # app_secret as canonical, revert to the PBKDF2 key, abort migration.
            logger.warning(
                "Both encryption.key and app_secret exist but the file key does not "
                "decrypt existing credentials — keeping app_secret as the canonical key "
                "and aborting the migration. Remove data/encryption.key to retry, or "
                "investigate a corrupted key file."
            )
            self._file_key = self._derive_old_key(db_secret)
            await self._setup_session_secret()
            return

        # CASE 2 — file key only: steady state.
        if key_path.exists():
            file_key = key_path.read_bytes()
            if len(file_key) != 32:
                raise RuntimeError(
                    f"Invalid encryption.key length: expected 32, got {len(file_key)}"
                )
            self._file_key = file_key
            await self._setup_session_secret()
            return

        # CASE 3 — migration: app_secret exists, no file key yet.
        if db_secret:
            old_key = self._derive_old_key(db_secret)
            new_key = secrets.token_bytes(32)
            servers = await self.db.fetchall(
                "SELECT id, username_enc, password_enc FROM servers"
            )
            # (a) decrypt + re-encrypt in memory FIRST — fails before any disk writes,
            #     leaving app_secret + the original *_enc rows fully intact.
            new_rows: list[tuple] = []
            try:
                for s in servers:
                    u_new = (
                        encrypt(decrypt(s["username_enc"], old_key), new_key)
                        if s["username_enc"] else s["username_enc"]
                    )
                    p_new = (
                        encrypt(decrypt(s["password_enc"], old_key), new_key)
                        if s["password_enc"] else s["password_enc"]
                    )
                    new_rows.append((s["id"], u_new, p_new))
            except Exception:
                logger.exception(
                    "Crypto migration aborted in the decrypt phase — app_secret and the "
                    "*_enc rows are untouched."
                )
                raise

            # (b) write the new key to .tmp first, so a committed DB never lacks a file.
            data_dir.mkdir(parents=True, exist_ok=True)
            try:
                tmp_path.write_bytes(new_key)
                _set_secure_permissions(tmp_path)
            except Exception:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                raise

            # (c) DB transaction: re-encrypt rows + preserve the session secret, commit.
            try:
                await self.db.execute("BEGIN")
                for sid, u_new, p_new in new_rows:
                    await self.db.execute(
                        "UPDATE servers SET username_enc=?, password_enc=? WHERE id=?",
                        (u_new, p_new, sid),
                    )
                # Copy app_secret -> session_secret in the SAME transaction so session
                # cookies keep verifying after app_secret is later deleted.
                await self.db.execute(
                    "INSERT INTO app_config (key, value, updated_at) "
                    "VALUES ('session_secret', ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO NOTHING",
                    (db_secret,),
                )
                await self.db.commit()
            except Exception:
                try:
                    await self.db.rollback()
                except Exception:
                    pass
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                logger.exception(
                    "Crypto migration aborted during the re-encrypt transaction — rolled "
                    "back; .tmp removed; app_secret remains canonical."
                )
                raise

            # (d) atomic rename. A crash before this leaves .tmp + committed rows +
            #     app_secret → next boot lands in CASE 1 and finishes the migration.
            try:
                tmp_path.replace(key_path)
            except Exception:
                logger.exception(
                    "Crypto migration: atomic rename failed AFTER the DB commit. The DB "
                    "rows are re-encrypted with the new key and encryption.key.tmp still "
                    "holds it — on the next boot the dual-exist recovery branch will "
                    "verify and complete the migration, or you can rename the .tmp to "
                    "encryption.key manually. app_secret is intentionally still present."
                )
                raise

            # (e) ONLY NOW delete app_secret — the file key is durably in place.
            await self.db.execute("DELETE FROM app_config WHERE key=?", ("app_secret",))
            await self.db.commit()
            self._file_key = new_key
            await self._setup_session_secret()
            logger.info(
                "Migrated at-rest credential key to data/encryption.key (%d rows re-encrypted); "
                "app_secret removed from the DB.", len(new_rows),
            )
            return

        # CASE 4 — first-run greenfield: generate a fresh file key.
        new_key = secrets.token_bytes(32)
        data_dir.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(new_key)
        _set_secure_permissions(key_path)
        self._file_key = new_key
        await self._setup_session_secret()
        logger.info("Generated new at-rest credential key at data/encryption.key (first run)")

    async def _migrate_session_secret(self, db_secret: str) -> None:
        """Best-effort: persist the old app_secret as session_secret if not present.

        Used by the CASE-1 recovery path (where the re-encrypt transaction may have
        committed without yet copying the session secret). Idempotent.
        """
        existing = await self.db.get_config("session_secret")
        if existing is None:
            await self.db.set_config("session_secret", db_secret)

    async def _setup_session_secret(self) -> None:
        """Load (or generate) the session-token HMAC signing secret.

        Stored separately from the credential key under app_config['session_secret'].
        On a migrated install this row holds the old app_secret value, so previously
        issued session cookies remain valid. On a greenfield install it is freshly
        generated.
        """
        secret = await self.db.get_config("session_secret")
        if not secret:
            secret = secrets.token_hex(32)
            await self.db.set_config("session_secret", secret)
        self._secret = secret

    async def is_auth_enabled(self) -> bool:
        val = await self.db.get_config("auth_enabled", "true")
        return val.lower() in ("true", "1", "yes")

    async def set_auth_enabled(self, enabled: bool) -> None:
        await self.db.set_config("auth_enabled", str(enabled).lower())

    async def has_user(self) -> bool:
        row = await self.db.fetchone("SELECT 1 FROM users LIMIT 1")
        return row is not None

    async def create_user(self, username: str, password: str) -> None:
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        await self.db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, pw_hash),
        )
        await self.db.commit()
        logger.info("User created: %s", username)

    async def verify_password(self, username: str, password: str) -> bool:
        row = await self.db.fetchone(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        )
        if not row:
            return False
        return bcrypt.checkpw(password.encode(), row["password_hash"].encode())

    async def update_password(self, username: str, new_password: str) -> None:
        pw_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        await self.db.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (pw_hash, username),
        )
        await self.db.commit()

    async def replace_user(self, username: str, password: str) -> None:
        """Single-user create-or-replace: clear the users table and insert one row.

        The users table is single-user (LAN). The new username may differ from any
        existing row, so we DELETE-then-INSERT rather than UPDATE (which would miss
        a renamed user) or INSERT (which could leave two rows / hit UNIQUE).

        REVIEWS #8: validate trimmed credentials and apply DELETE+INSERT atomically —
        on any failure we do NOT commit (rollback), so a failed INSERT never leaves a
        committed empty users table.
        """
        username = username.strip()
        if not username or not password.strip():
            raise ValueError("Username and password are required")
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        try:
            await self.db.execute("DELETE FROM users")
            await self.db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, pw_hash),
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        logger.info("User credentials replaced: %s", username)

    # === SEC-03: Brute-force lockout (per-username, in-memory) ===

    async def check_lockout(self, username: str) -> bool:
        """Return True iff this username is currently locked out.

        Per D-03: counter resets if last failure is > 1h ago.
        Lock is held only for the dict R/M/W (no awaits inside) per RESEARCH lines 199-209.
        """
        async with self._fail_lock:
            state = self._fail_state.get(username)
            if not state:
                return False
            now = time.monotonic()
            # Reset stale entries (> 1h since last failure)
            if now - state["last_failure"] > 3600:
                self._fail_state.pop(username, None)
                return False
            return state["locked_until"] > now

    async def record_failure(self, username: str) -> None:
        """Record a failed login attempt and apply exponential backoff if past threshold.

        Per D-03: first 5 failures are silent (counter only). From the 6th failure onward,
        lock for `min(60 * 2**(count-6), 3600)` seconds.
        """
        async with self._fail_lock:
            now = time.monotonic()
            state = self._fail_state.setdefault(
                username, {"count": 0, "last_failure": 0.0, "locked_until": 0.0}
            )
            state["count"] += 1
            state["last_failure"] = now
            if state["count"] >= 6:
                exponent = state["count"] - 6  # 0 on first lockout (count=6)
                duration = min(60 * (2 ** exponent), 3600)
                state["locked_until"] = now + duration
                logger.warning(
                    "Account '%s' locked for %ds after %d failures",
                    username, duration, state["count"],
                )

    async def reset_failures(self, username: str) -> None:
        """Clear failure state for a username (called after successful login)."""
        async with self._fail_lock:
            self._fail_state.pop(username, None)

    def create_session_token(self, username: str) -> str:
        payload = {
            "sub": username,
            "iat": int(time.time()),
            "exp": int(time.time()) + SESSION_EXPIRY_SECONDS,
        }
        data = json.dumps(payload, separators=(",", ":"))
        sig = hmac.new(self._secret.encode(), data.encode(), hashlib.sha256).hexdigest()
        # base64url-encode the data part so the cookie value is RFC 6265-safe
        # (raw JSON contains { } , " which browsers reject/truncate). Sign the raw
        # JSON; encode only for transport.
        b64 = base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")
        return f"{b64}.{sig}"

    def verify_session_token(self, token: str) -> str | None:
        """Returns username if valid, None otherwise."""
        try:
            b64_part, sig_part = token.rsplit(".", 1)
            # Re-pad and decode the base64url data part back to the raw JSON that was signed.
            data_part = base64.urlsafe_b64decode(
                b64_part + "=" * (-len(b64_part) % 4)
            ).decode()
            expected_sig = hmac.new(
                self._secret.encode(), data_part.encode(), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(sig_part, expected_sig):
                return None
            payload = json.loads(data_part)
            if payload.get("exp", 0) < time.time():
                return None
            return payload.get("sub")
        except Exception:
            return None

    def get_encryption_key(self) -> bytes:
        """Return the at-rest BMC-credential encryption key.

        The single read path used everywhere (server_routes, sel/routes, fanpilot/tasks,
        power/routes, fru/routes, etc.). After 04-W4-04 this returns the file-based key
        (self._file_key) loaded/migrated by initialize() — no longer a PBKDF2 derivation
        of the session secret. Callers are unchanged; only the source of the bytes moved.
        """
        if not self._file_key:
            raise RuntimeError("AuthManager not initialized — encryption key unavailable")
        return self._file_key


async def require_auth(request: Request) -> str:
    """FastAPI dependency: validate session cookie. Returns username or raises 401.

    - If auth is DISABLED globally, returns "local" (no-op pass-through). This is critical
      per Pitfall #2: when admin toggles auth off, every request must still succeed.
    - If auth is ENABLED, requires a valid session cookie. Missing/invalid → HTTP 401
      with JSON body {"error": "unauthorized"} per D-07.
    - NO WWW-Authenticate header (avoids native browser popup in SPA).

    Used as a router-level dep on protected routers and per-endpoint on mixed routers.
    """
    # Late import to avoid circular dep — same pattern used by route handlers.
    from backend.main import auth as _auth

    if not await _auth.is_auth_enabled():
        return "local"

    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})

    username = _auth.verify_session_token(token)
    if not username:
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})

    # REVIEWS #7: a signed token for an OLD username (pre credential-replace) must
    # not stay valid. Confirm the token subject is the CURRENT single stored user.
    row = await _auth.db.fetchone(
        "SELECT 1 FROM users WHERE username = ? LIMIT 1", (username,)
    )
    if row is None:
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})
    return username
