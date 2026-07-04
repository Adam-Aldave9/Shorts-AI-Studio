"""Auth configuration — env-derived module constants (repo convention: no settings
class, read once at import).

The app **fails fast** if ``SECRET_KEY`` is missing: a browser-facing service must
never boot without the secret that signs the CSRF cookie. Everything else has a safe
default so local dev works with a single ``SECRET_KEY`` set.
"""

from __future__ import annotations

import os


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is required for authentication but is unset. Generate one with "
            "`python -c \"import secrets; print(secrets.token_urlsafe(64))\"` and set it "
            "in the environment (see .env.example)."
        )
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Signs the readable CSRF cookie (double-submit). Required — no default.
SECRET_KEY: str = _require("SECRET_KEY")

# Cookie names. ``afp_session`` is the HttpOnly opaque session id; ``afp_csrf`` is the
# JS-readable double-submit token the SPA echoes back in the X-CSRF-Token header.
SESSION_COOKIE_NAME: str = os.environ.get("SESSION_COOKIE_NAME", "afp_session")
CSRF_COOKIE_NAME: str = os.environ.get("CSRF_COOKIE_NAME", "afp_csrf")

# Cookie flags. ``COOKIE_SECURE`` must be true in prod (HTTPS); local dev over http
# sets it false. ``SameSite=Lax`` is the CSRF baseline for first-party cookies.
COOKIE_SECURE: bool = _bool("COOKIE_SECURE", False)
COOKIE_SAMESITE: str = os.environ.get("COOKIE_SAMESITE", "lax")

# Session TTLs (seconds): a 30-min sliding idle window and a 12-hour absolute cap.
SESSION_IDLE_TTL: int = _int("SESSION_IDLE_TTL", 1800)
SESSION_ABSOLUTE_TTL: int = _int("SESSION_ABSOLUTE_TTL", 43200)


def allowed_origins() -> list[str]:
    """Origins accepted by the CSRF Origin/Referer allow-list (and CORS). Comma or
    whitespace separated; defaults to the local Vite dev origin."""
    raw = os.environ.get("AUTH_ALLOWED_ORIGINS", "http://localhost:5173")
    parts = [p.strip().rstrip("/") for p in raw.replace(",", " ").split()]
    return [p for p in parts if p]


AUTH_ALLOWED_ORIGINS: list[str] = allowed_origins()
