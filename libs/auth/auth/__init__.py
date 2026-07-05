"""Shared session-based authentication for the AI Film Pipeline.

Both browser-facing services (``planning``, ``scheduler``) install the same layer:

    from auth import auth_router, install_auth, current_user_id, owned_package

    app.include_router(auth_router)
    install_auth(app, public_paths={"/auth/login", "/auth/register", "/auth/csrf"})

Auth model: opaque server-side sessions in Redis (HttpOnly cookie), Argon2id password
hashing, and a per-session CSRF synchronizer token. See the module docstrings for the
security rationale of each piece.
"""

from auth.deps import OwnedPackage, current_user, current_user_id, owned_package
from auth.middleware import AuthMiddleware, install_auth
from auth.router import router as auth_router

__all__ = [
    "auth_router",
    "install_auth",
    "AuthMiddleware",
    "current_user",
    "current_user_id",
    "owned_package",
    "OwnedPackage",
]
