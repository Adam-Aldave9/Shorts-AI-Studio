"""Full HTTP round-trip through the router + ASGI middleware (Starlette TestClient).

Asserts the whole cookie/CSRF handshake end to end: registration/login set an
HttpOnly session cookie + a readable CSRF cookie, protected routes 401 without a
session, unsafe methods 403 without the CSRF header, and logout revokes. fakeredis is
injected via ``state.use_client`` and shared with the session/user stores.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, Request
from starlette.testclient import TestClient

import state
from auth import auth_router, current_user_id, install_auth, owned_package
from auth.config import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover
    fakeredis_aio = None

_ORIGIN = {"Origin": "http://localhost:5173"}
_PW = "a-strong-password-123"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)

    @app.get("/protected")
    def protected(request: Request) -> dict:
        return {"user_id": current_user_id(request)}

    @app.post("/things")
    def create_thing(request: Request) -> dict:
        return {"user_id": current_user_id(request)}

    @app.get("/packages/{project_id}")
    async def read_pkg(project_id: str, _owned: str = Depends(owned_package)) -> dict:
        return {"project_id": project_id}

    install_auth(app, public_paths={"/auth/login", "/auth/register", "/auth/csrf"})
    return app


@pytest.fixture
def client():
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")
    state.use_client(fakeredis_aio.FakeRedis(decode_responses=True))
    with TestClient(_build_app(), base_url="http://localhost:5173") as c:
        yield c
    state.use_client(None)


def _set_cookie_headers(response) -> list[str]:
    return [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]


def test_register_sets_httponly_session_and_readable_csrf(client):
    resp = client.post("/auth/register", json={"username": "Alice", "password": _PW}, headers=_ORIGIN)
    assert resp.status_code == 201
    assert resp.json() == {"user_id": resp.json()["user_id"], "username": "Alice"}

    cookies = _set_cookie_headers(resp)
    session_cookie = next(c for c in cookies if c.startswith(f"{SESSION_COOKIE_NAME}="))
    csrf_cookie = next(c for c in cookies if c.startswith(f"{CSRF_COOKIE_NAME}="))
    assert "httponly" in session_cookie.lower()
    assert "samesite=lax" in session_cookie.lower()
    assert "httponly" not in csrf_cookie.lower()  # SPA must read it


def test_duplicate_register_conflicts(client):
    client.post("/auth/register", json={"username": "bob", "password": _PW}, headers=_ORIGIN)
    dup = client.post("/auth/register", json={"username": "bob", "password": _PW}, headers=_ORIGIN)
    assert dup.status_code == 409


def test_protected_requires_session(client):
    assert client.get("/protected").status_code == 401


def test_login_wrong_password_is_generic_401(client):
    client.post("/auth/register", json={"username": "carol", "password": _PW}, headers=_ORIGIN)
    client.cookies.clear()
    bad = client.post(
        "/auth/login", json={"username": "carol", "password": "wrong-password"}, headers=_ORIGIN
    )
    assert bad.status_code == 401
    assert bad.json()["detail"] == "invalid username or password"


def test_full_login_me_csrf_logout_flow(client):
    client.post("/auth/register", json={"username": "dave", "password": _PW}, headers=_ORIGIN)
    client.cookies.clear()  # drop the auto-login session; log in fresh

    login = client.post("/auth/login", json={"username": "dave", "password": _PW}, headers=_ORIGIN)
    assert login.status_code == 200
    assert login.json()["username"] == "dave"

    me = client.get("/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "dave"

    # unsafe method without the CSRF header -> 403
    assert client.post("/things", headers=_ORIGIN).status_code == 403

    # echo the readable CSRF cookie in the header -> allowed
    csrf_value = client.cookies.get(CSRF_COOKIE_NAME)
    ok = client.post("/things", headers={**_ORIGIN, "X-CSRF-Token": csrf_value})
    assert ok.status_code == 200 and ok.json()["user_id"]

    # bad Origin is rejected even with a valid token
    bad_origin = client.post(
        "/things", headers={"Origin": "http://evil.example", "X-CSRF-Token": csrf_value}
    )
    assert bad_origin.status_code == 403

    # logout needs the CSRF token too; then the session is gone
    logout = client.post("/auth/logout", headers={**_ORIGIN, "X-CSRF-Token": csrf_value})
    assert logout.status_code == 204
    assert client.get("/protected").status_code == 401


def test_foreign_package_returns_404(client):
    import asyncio

    # userA registers and owns p_a (stamp ownership straight into the shared fake
    # store; the guard only needs the owner index, not a full package body).
    reg = client.post("/auth/register", json={"username": "ann", "password": _PW}, headers=_ORIGIN)
    user_a = reg.json()["user_id"]
    asyncio.new_event_loop().run_until_complete(
        state.store._redis().set("project:p_a:owner", user_a)
    )

    # userA can read their own package
    assert client.get("/packages/p_a").status_code == 200

    # userB registers -> different session -> 404 on p_a (no existence leak)
    client.cookies.clear()
    client.post("/auth/register", json={"username": "bill", "password": _PW}, headers=_ORIGIN)
    assert client.get("/packages/p_a").status_code == 404
