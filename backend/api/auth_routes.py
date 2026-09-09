"""Authentication routes — simplified local auth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.core.auth import require_auth
from backend.core.i18n import get_lang, t

router = APIRouter()


def _set_session_cookie(response: Response, request: Request, token: str, max_age: int) -> None:
    """Issue the session cookie, setting secure=True when the request arrived over HTTPS.

    Decision R (04-W4-03): all three cookie issuers (login / setup / configure) route through
    this single helper so the secure flag is set consistently. Detection uses
    request.url.scheme == "https" — true when uvicorn terminates TLS (config.server.https on)
    or a TLS-terminating reverse proxy forwards the scheme. On plain HTTP it stays False so
    LAN-only HTTP deployments keep working.

    SX0-A: ``max_age`` is the configured session lifetime in seconds
    (auth.session_expiry_seconds), so the cookie Max-Age matches the token exp instead of a
    hardcoded 24h.
    """
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="strict",
        max_age=max_age,
        secure=request.url.scheme == "https",
    )


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str
    password: str


class ConfigureRequest(BaseModel):
    username: str
    password: str
    # SEC-05 (F6/F10): required whenever an account already exists — including on an
    # auth-DISABLED instance, which is the F10 window. Optional only at genuine first
    # run (no account), where there is no password to prove knowledge of.
    current_password: str | None = None


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
        if not token or not await auth.verify_session_token_async(token):
            raise HTTPException(status_code=401, detail={"error": "unauthorized"})


@router.get("/me")
async def get_me(request: Request):
    from backend.main import auth
    has_user = await auth.has_user()
    if not await auth.is_auth_enabled():
        return {"authenticated": True, "username": "local", "auth_enabled": False, "has_user": has_user}
    token = request.cookies.get("session")
    username = await auth.verify_session_token_async(token) if token else None
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
async def login(body: LoginRequest, request: Request, response: Response, lang: str = Depends(get_lang)):
    """Authenticate and issue session cookie.

    The password is verified FIRST and the lockout is consulted only on the failure
    path. Checking the lockout before verifying would let anyone lock the operator
    out of their own instance: the counter is keyed on a username supplied by the
    caller, so burning a handful of attempts on a guessed name was enough to have
    the CORRECT password refused for the whole lockout window. Verifying first costs
    the attacker a bcrypt comparison per attempt (the actual throttle) while a valid
    credential is never rejected.

    A failed attempt answers HTTP 401 rather than 200, so caches, proxies and
    scripted clients can tell an authentication failure from a success without
    parsing the body. JSONResponse is used instead of HTTPException to keep the body
    shape (`{"success": false, "error": ...}`) that existing callers already read.

    Error messages must not reveal whether the username exists or when the lockout
    expires.
    """
    from backend.main import auth

    if not await auth.is_auth_enabled():
        return {"success": True, "message": "Auth disabled"}

    if not await auth.verify_password(body.username, body.password):
        await auth.record_failure(body.username)
        # A failure that crosses the threshold must not be announced as the trigger:
        # the generic lockout text is identical to the one a later attempt receives.
        error = (
            t("too_many_attempts", lang)
            if await auth.check_lockout(body.username)
            else t("invalid_credentials", lang)
        )
        return JSONResponse(status_code=401, content={"success": False, "error": error})

    # Success: clear any prior failure counter, issue session.
    await auth.reset_failures(body.username)
    token = await auth.create_session_token_async(body.username)
    _set_session_cookie(response, request, token, auth.session_expiry_seconds)
    return {"success": True, "username": body.username}


@router.post("/logout", dependencies=[Depends(require_auth)])
async def logout(response: Response):
    response.delete_cookie("session")
    return {"success": True}


@router.post("/setup")
async def setup(body: SetupRequest, request: Request, response: Response, lang: str = Depends(get_lang)):
    """First-run account creation. Always leaves authentication ENABLED.

    SEC-04 clause 2 (F5): an anonymous caller can disable auth on a
    not-yet-configured instance (that clause is deferred onto SEC-06), and
    `setup` used to create the account without
    touching the flag. The instance therefore stayed open forever, with no UI
    symptom, even after the real operator finished first run.

    Re-enabling unconditionally removes the DURABILITY and the SILENCE of that
    attack: whatever the flag was beforehand, completing first run closes the
    instance and the login page is enforced from then on.
    """
    from backend.main import auth
    if await auth.has_user():
        return {"success": False, "error": t("user_already_exists", lang)}
    try:
        await auth.create_user(body.username, body.password)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    await auth.set_auth_enabled(True)
    token = await auth.create_session_token_async(body.username)
    _set_session_cookie(response, request, token, auth.session_expiry_seconds)
    return {"success": True, "username": body.username}


@router.post("/configure")
async def configure_auth(body: ConfigureRequest, request: Request, response: Response):
    """D-09/D-13: set fresh credentials AND enable auth atomically (overwrite-on-enable).

    REVIEWS #1: callable without a session only at bootstrap (auth disabled OR no user
    yet). Once auth is active for a real account, a valid session is required — this
    endpoint is NOT an unauthenticated credential-takeover path. Issues a fresh session
    cookie for the new username so the operator stays logged in (and the new cookie
    passes the require_auth current-user check while any old-username cookie is rejected).

    SEC-05 (F6, and F10 as a side effect): a valid-looking session was the ONLY thing
    standing between a caller and a rewrite of the sole account — the exact action an
    incident responder takes to evict an attacker. Proving knowledge of the CURRENT
    password is now required whenever an account exists.

    The gate keys on `has_user()`, NOT on `auth_enabled`. That keying is load-bearing:
    keying on `auth_enabled` would leave the F10 window wide open, because an
    auth-disabled instance with an existing account could be seized with no cookie at
    all — and the frontend only shows this form when auth is OFF, so an `auth_enabled`
    condition would never fire from the UI.

    With no account present nothing is required: that is genuine first run.
    """
    from backend.main import auth
    await _require_session_if_active(request, auth)

    if await auth.has_user():
        if not body.current_password:
            return {"success": False, "error": "Current password is required"}
        # On an auth-disabled instance there is no session to name the current user,
        # so fall back to the single stored account row (the users table is single-user).
        token = request.cookies.get("session")
        current_username = await auth.verify_session_token_async(token) if token else None
        if not current_username:
            row = await auth.db.fetchone("SELECT username FROM users LIMIT 1")
            current_username = row["username"] if row else None
        if not current_username or not await auth.verify_password(
            current_username, body.current_password
        ):
            return {"success": False, "error": "Incorrect password"}

    try:
        await auth.replace_user(body.username, body.password)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    await auth.set_auth_enabled(True)
    token = await auth.create_session_token_async(body.username)
    _set_session_cookie(response, request, token, auth.session_expiry_seconds)
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
        username = await auth.verify_session_token_async(token) if token else None
        if not username or not await auth.verify_password(username, body.current_password):
            return {"success": False, "error": "Incorrect password"}

    await auth.set_auth_enabled(False)
    return {"success": True, "auth_enabled": False}
