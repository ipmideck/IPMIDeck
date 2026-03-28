"""Authentication routes — simplified local auth."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Request, Response
from pydantic import BaseModel

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str
    password: str


@router.get("/me")
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
    from backend.main import auth
    if not await auth.is_auth_enabled():
        return {"success": True, "message": "Auth disabled"}

    if not await auth.verify_password(body.username, body.password):
        return {"success": False, "error": "Invalid credentials"}

    token = auth.create_session_token(body.username)
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400,
    )
    return {"success": True, "username": body.username}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("session")
    return {"success": True}


@router.post("/setup")
async def setup(body: SetupRequest):
    from backend.main import auth
    if await auth.has_user():
        return {"success": False, "error": "User already exists"}
    await auth.create_user(body.username, body.password)
    return {"success": True}


@router.get("/status")
async def auth_status():
    from backend.main import auth
    return {
        "auth_enabled": await auth.is_auth_enabled(),
        "has_user": await auth.has_user(),
    }


@router.post("/toggle")
async def toggle_auth(request: Request):
    from backend.main import auth
    body = await request.json()
    enabled = body.get("enabled", True)
    await auth.set_auth_enabled(enabled)
    return {"success": True, "auth_enabled": enabled}
