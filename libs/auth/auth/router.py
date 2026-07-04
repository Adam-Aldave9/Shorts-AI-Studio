"""The ``/auth`` HTTP surface: register, login, logout, me, csrf.

Cookie contract (set on login/register, cleared on logout):
  * ``afp_session`` — the opaque session id. ``HttpOnly`` (JS can't read it),
    ``Secure`` in prod, ``SameSite=Lax``, ``Path=/``, host-only.
  * ``afp_csrf`` — the signed CSRF token. **Readable** by JS (the SPA echoes it in
    ``X-CSRF-Token``), same flags otherwise but not ``HttpOnly``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from auth import csrf, sessions, users
from auth.config import (
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    CSRF_COOKIE_NAME,
    SESSION_ABSOLUTE_TTL,
    SESSION_COOKIE_NAME,
)
from auth.models import LoginRequest, RegisterRequest, UserOut
from auth.ratelimit import allow_login, allow_register

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    """Best-effort client IP for rate-limiting. Behind the reverse proxy the real
    client is the first hop in ``X-Forwarded-For``; fall back to the socket peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_session_cookies(response: Response, sid: str, csrf_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        sid,
        max_age=SESSION_ABSOLUTE_TTL,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf.issue_cookie_value(csrf_token),
        max_age=SESSION_ABSOLUTE_TTL,
        httponly=False,  # the SPA must read this to echo it back
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


async def _start_session(response: Response, user_id: str) -> None:
    sid, csrf_token = await sessions.create_session(user_id)
    _set_session_cookies(response, sid, csrf_token)


@router.post("/register", status_code=201, response_model=UserOut)
async def register(body: RegisterRequest, request: Request, response: Response) -> UserOut:
    """Open self-service sign-up (rate-limited per IP). On success the new account is
    also logged in (session cookies set), so the SPA lands authenticated."""
    if not await allow_register(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many attempts, try again later")
    try:
        user = await users.register_user(body.username, body.password)
    except users.UserExistsError:
        raise HTTPException(status_code=409, detail="username is taken")
    await _start_session(response, user.user_id)
    return user


@router.post("/login", response_model=UserOut)
async def login(body: LoginRequest, request: Request, response: Response) -> UserOut:
    """Verify credentials and start a fresh session. Generic 401 on any failure (no
    user enumeration); 429 when throttled."""
    if not await allow_login(body.username.lower(), _client_ip(request)):
        raise HTTPException(status_code=429, detail="too many attempts, try again later")
    try:
        user = await users.authenticate(body.username, body.password)
    except users.InvalidCredentials:
        raise HTTPException(status_code=401, detail="invalid username or password")
    await _start_session(response, user.user_id)
    return user


@router.post("/logout", status_code=204)
async def logout(request: Request) -> Response:
    """Revoke the current session server-side and clear both cookies. Requires a
    valid session + CSRF token (enforced by the middleware before this runs)."""
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if sid:
        await sessions.destroy_session(sid)
    response = Response(status_code=204)
    _clear_session_cookies(response)
    return response


@router.get("/me", response_model=UserOut)
async def me(request: Request) -> UserOut:
    """The current account — the SPA bootstraps its auth state from this. Requires a
    session (the middleware 401s otherwise), so ``request.state.user_id`` is set."""
    user = await users.get_user(request.state.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


@router.get("/csrf")
async def issue_csrf(request: Request, response: Response) -> dict[str, str | None]:
    """(Re)issue the readable ``afp_csrf`` cookie for the current session so the SPA
    can make its first unsafe request after a reload. Public: harmless without a
    session (returns ``null`` and sets nothing)."""
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    session = await sessions.get_session(sid) if sid else None
    if not session:
        return {"csrf": None}
    token = session["csrf"]
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf.issue_cookie_value(token),
        max_age=SESSION_ABSOLUTE_TTL,
        httponly=False,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )
    return {"csrf": csrf.issue_cookie_value(token)}
