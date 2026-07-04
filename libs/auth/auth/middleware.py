"""Pure-ASGI auth + CSRF enforcement.

Deliberately **not** a ``BaseHTTPMiddleware``: that class buffers the entire
response before forwarding it, which would break the scheduler's long-lived SSE
status stream. A pure-ASGI middleware inspects the request and then hands the
original ``(scope, receive, send)`` straight through, so streaming bodies flow
untouched.

Per request it: lets OPTIONS (CORS preflight) and the public allow-list through;
otherwise requires a valid session cookie (401 if absent/expired), and on unsafe
methods also requires a valid CSRF token + allowed Origin (403). On success it
stamps ``request.state.user_id`` for downstream handlers/dependencies.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from auth import csrf, sessions
from auth.config import SESSION_COOKIE_NAME

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Always public regardless of caller config: liveness + the OpenAPI surface the
# frontend's `npm run gen:api` reads. These leak no user data.
_DEFAULT_PUBLIC = {
    "/health",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}


class AuthMiddleware:
    def __init__(self, app: ASGIApp, public_paths: set[str] | None = None) -> None:
        self.app = app
        self.public = set(public_paths or ()) | _DEFAULT_PUBLIC

    def _is_public(self, path: str) -> bool:
        return path in self.public

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method: str = scope["method"]
        path: str = scope["path"]
        if method == "OPTIONS" or self._is_public(path):
            await self.app(scope, receive, send)
            return

        # Parsing headers/cookies does not consume the request body, so the wrapped
        # app still receives an intact stream.
        request = Request(scope, receive)
        sid = request.cookies.get(SESSION_COOKIE_NAME)
        session = await sessions.touch_session(sid) if sid else None
        if session is None:
            await self._deny(scope, receive, send, 401, "authentication required")
            return

        if method in _UNSAFE_METHODS:
            header_token = request.headers.get("x-csrf-token")
            if not csrf.verify_csrf(session.get("csrf", ""), header_token):
                await self._deny(scope, receive, send, 403, "invalid or missing CSRF token")
                return
            if not csrf.check_origin(
                request.headers.get("origin"), request.headers.get("referer")
            ):
                await self._deny(scope, receive, send, 403, "origin not allowed")
                return

        # Downstream Request.state reads from scope["state"]; merge, don't clobber.
        scope.setdefault("state", {})
        scope["state"]["user_id"] = session["user_id"]
        scope["state"]["session_id"] = sid
        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(
        scope: Scope, receive: Receive, send: Send, status: int, detail: str
    ) -> None:
        await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)


def install_auth(app: ASGIApp, public_paths: set[str] | None = None) -> None:
    """Install the auth+CSRF middleware on a FastAPI/Starlette app.

    ``public_paths`` are the app-local paths reachable without a session (e.g.
    ``/auth/login``). Health + OpenAPI paths are always public. Note the paths are
    app-local: behind the reverse proxy nginx strips the ``/api/<svc>`` prefix, so
    the app sees ``/auth/login``, not ``/api/scheduler/auth/login``."""
    app.add_middleware(AuthMiddleware, public_paths=public_paths)
