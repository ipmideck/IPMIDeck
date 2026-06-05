"""Authentication routes — simplified local auth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from backend.core.auth import require_auth
from backend.core.i18n import get_lang, t

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str
    password: str


class ConfigureRequest(BaseModel):
    username: str
    password: str


class ToggleRequest(BaseModel):
    enabled: bool = True
    # Required when disabling an ACTIVE login (auth_enabled AND has_user). Used as a
    # second-factor intent confirmation — see /toggle. Optional during first-run
    # skip-at-setup (no user yet) and ignored for enable (which is refused here
    # anyway; enable goes through /configure with fresh credentials).
    current_password: str | None = None


async def _require_session_if_active(request: Request, auth) -> None:
    """REVIEWS #1: require a valid session ONLY when auth is active for a real account.

    Bootstrap (auth disabled OR no user yet) is callable with no session — that is the
    first-run / re-enable-from-disabled path. Once `auth_enabled AND has_user`, a valid
    session cookie is mandatory (else 401). Shared by /configure and /toggle so both
    endpoints enforce ONE consistent first-run-aware rule.
    """
    if await auth.is_auth_enabled() and await auth.has_user():
        token = request.cookies.get("session")
        if not token or not auth.verify_session_token(token):
            raise HTTPException(status_code=401, detail={"error": "unauthorized"})


@router.get("/me")
async def get_me(request: Request):
    from backend.main import auth
    has_user = await auth.has_user()
    if not await auth.is_auth_enabled():
        return {"authenticated": True, "username": "local", "auth_enabled": False, "has_user": has_user}
    token = request.cookies.get("session")
    username = auth.verify_session_token(token) if token else None
    # REVIEWS #7: mirror require_auth — a token whose subject is no longer the current
    # stored user (e.g. after a credential replace) is NOT authenticated. Keeps /me
    # consistent with protected routes so the frontend boot routing sees the same state.
    if username and not await auth.db.fetchone(
        "SELECT 1 FROM users WHERE username = ? LIMIT 1", (username,)
    ):
        username = None
    if not username:
        return {"authenticated": False, "auth_enabled": True, "has_user": has_user}
    return {"authenticated": True, "username": username, "auth_enabled": True, "has_user": has_user}


@router.post("/login")
async def login(body: LoginRequest, response: Response, lang: str = Depends(get_lang)):
    """Authenticate and issue session cookie.

    SEC-03 lockout flow (D-03):
    1. Pre-check: if user is currently locked out → return generic message (D-04).
    2. verify_password → if False → record_failure → if NOW locked, return generic
       message; otherwise return 'Invalid credentials'.
    3. Success → reset_failures, then issue session cookie.

    D-04: error messages MUST NOT reveal whether the username exists or when the
    lockout expires.
    """
    from backend.main import auth

    if not await auth.is_auth_enabled():
        return {"success": True, "message": "Auth disabled"}

    # 1. Pre-check lockout BEFORE attempting password verify (avoids leaking timing).
    if await auth.check_lockout(body.username):
        return {"success": False, "error": t("too_many_attempts", lang)}

    # 2. Verify password.
    if not await auth.verify_password(body.username, body.password):
        await auth.record_failure(body.username)
        # If this failure pushed us into lockout, return the generic message
        # (Pitfall #3: must not leak that this specific attempt was the trigger).
        if await auth.check_lockout(body.username):
            return {"success": False, "error": t("too_many_attempts", lang)}
        return {"success": False, "error": t("invalid_credentials", lang)}

    # 3. Success: clear any prior failure counter, issue session.
    await auth.reset_failures(body.username)
    token = auth.create_session_token(body.username)
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400,
    )
    return {"success": True, "username": body.username}


@router.post("/logout", dependencies=[Depends(require_auth)])
async def logout(response: Response):
    response.delete_cookie("session")
    return {"success": True}


@router.post("/setup")
async def setup(body: SetupRequest, response: Response, lang: str = Depends(get_lang)):
    from backend.main import auth
    if await auth.has_user():
        return {"success": False, "error": t("user_already_exists", lang)}
    await auth.create_user(body.username, body.password)
    token = auth.create_session_token(body.username)
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400,
    )
    return {"success": True, "username": body.username}


@router.post("/configure")
async def configure_auth(body: ConfigureRequest, request: Request, response: Response):
    """D-09/D-13: set fresh credentials AND enable auth atomically (overwrite-on-enable).

    REVIEWS #1: callable without a session only at bootstrap (auth disabled OR no user
    yet). Once auth is active for a real account, a valid session is required — this
    endpoint is NOT an unauthenticated credential-takeover path. Issues a fresh session
    cookie for the new username so the operator stays logged in (and the new cookie
    passes the require_auth current-user check while any old-username cookie is rejected).
    """
    from backend.main import auth
    await _require_session_if_active(request, auth)
    try:
        await auth.replace_user(body.username, body.password)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    await auth.set_auth_enabled(True)
    token = auth.create_session_token(body.username)
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400,
    )
    return {"success": True, "username": body.username}


@router.get("/status")
async def auth_status():
    from backend.main import auth
    return {
        "auth_enabled": await auth.is_auth_enabled(),
        "has_user": await auth.has_user(),
    }


@router.post("/toggle")
async def toggle_auth(body: ToggleRequest, request: Request, lang: str = Depends(get_lang)):
    """Disable auth (enabled:false). Enabling is REJECTED — use /configure.

    REVIEWS #2: enabling auth always requires setting fresh credentials (D-09), so
    /toggle {enabled:true} is refused here. This supersedes Phase 1 D-08's password-less
    toggle-ON: stale stored credentials can no longer silently re-enable auth, and auth
    can never be enabled with no user. For {enabled:false} we use the shared first-run-aware
    helper: skip-at-setup (no user / auth off) works with no cookie (D-02); disabling an
    active login (auth_enabled AND has_user) still requires a valid session (Phase 1 D-08).

    SECURITY: when disabling an ACTIVE login (has_user is true), the request MUST
    include the operator's current password — intent confirmation and typo-prevention
    against a hijacked session or a stray click on the disable button. The skip-at-
    setup path (no user yet) is unaffected since there's no password to verify.
    """
    from backend.main import auth
    if body.enabled:
        return {
            "success": False,
            "error": t("use_configure_to_enable", lang),
        }
    await _require_session_if_active(request, auth)

    if await auth.has_user():
        if not body.current_password:
            return {
                "success": False,
                "error": "Current password is required to disable authentication",
            }
        token = request.cookies.get("session")
        username = auth.verify_session_token(token) if token else None
        if not username or not await auth.verify_password(username, body.current_password):
            return {"success": False, "error": "Incorrect password"}

    await auth.set_auth_enabled(False)
    return {"success": True, "auth_enabled": False}
