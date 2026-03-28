"""Simple local authentication — optional, single user, session-based."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time

import bcrypt

from backend.core.database import Database

logger = logging.getLogger("ipmilink.auth")

SESSION_EXPIRY_SECONDS = 86400  # 24h default


class AuthManager:
    def __init__(self, db: Database):
        self.db = db
        self._secret: str = ""

    async def initialize(self) -> None:
        """Load or generate app secret for session signing."""
        secret = await self.db.get_config("app_secret")
        if not secret:
            secret = secrets.token_hex(32)
            await self.db.set_config("app_secret", secret)
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

    def create_session_token(self, username: str) -> str:
        payload = {
            "sub": username,
            "iat": int(time.time()),
            "exp": int(time.time()) + SESSION_EXPIRY_SECONDS,
        }
        data = json.dumps(payload, separators=(",", ":"))
        sig = hmac.new(self._secret.encode(), data.encode(), hashlib.sha256).hexdigest()
        return f"{data}.{sig}"

    def verify_session_token(self, token: str) -> str | None:
        """Returns username if valid, None otherwise."""
        try:
            data_part, sig_part = token.rsplit(".", 1)
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
        """Derive encryption key for BMC credentials from app secret."""
        return hashlib.pbkdf2_hmac(
            "sha256", self._secret.encode(), b"ipmilink-cred-enc", 100000, dklen=32
        )
