"""Authentication routes — simplified local auth."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel

from backend.core.auth import require_auth

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str
    password: str


@router.get("/me", dependencies=[Depends(require_auth)])
async def get_me(request: Request):
    from backend.main import auth
    if not await auth.is_auth_enabled():
        return {"authenticated": True, "username": "local", "auth_enabled": False}

    token = request.cookies.get("session")
    if not token:
        return {"authenticated": False}

    username = auth.verify_session_token(token)
    if not username:
        return {"authenticated": False}
    return {"authenticated": True, "username": username, "auth_enabled": True}


@router.post("/login")
async def login(body: LoginRequest, response: Response):
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
        return {"success": False, "error": "Too many failed attempts. Try again later."}

    # 2. Verify password.
    if not await auth.verify_password(body.username, body.password):
        await auth.record_failure(body.username)
        # If this failure pushed us into lockout, return the generic message
        # (Pitfall #3: must not leak that this specific attempt was the trigger).
        if await auth.check_lockout(body.username):
            return {"success": False, "error": "Too many failed attempts. Try again later."}
        return {"success": False, "error": "Invalid credentials"}

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
async def setup(body: SetupRequest, response: Response):
    from backend.main import auth
    if await auth.has_user():
        return {"success": False, "error": "User already exists"}
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


@router.get("/status")
async def auth_status():
    from backend.main import auth
    return {
        "auth_enabled": await auth.is_auth_enabled(),
        "has_user": await auth.has_user(),
    }


@router.post("/toggle")
async def toggle_auth(request: Request):
    """Toggle auth on/off.

    Per D-08 (SEC-02): when auth is currently ENABLED, require a valid session.
    When auth is DISABLED, anyone may re-enable it (bootstrap path; no users yet
    means no one can authenticate).
    """
    from backend.main import auth
    if await auth.is_auth_enabled():
        token = request.cookies.get("session")
        if not token or not auth.verify_session_token(token):
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail={"error": "unauthorized"})
    body = await request.json()
    enabled = body.get("enabled", True)
    await auth.set_auth_enabled(enabled)
    return {"success": True, "auth_enabled": enabled}
