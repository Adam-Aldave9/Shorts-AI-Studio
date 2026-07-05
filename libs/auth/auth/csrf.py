"""CSRF defense — a per-session synchronizer token, plus an Origin/Referer check.

Layered defenses (any one of which stops a cross-site write):

1. **Synchronizer token bound to the session.** A random token is minted with the
   session and stored in its server-side record. It is surfaced to the SPA in a
   *readable* ``afp_csrf`` cookie, HMAC-signed with ``SECRET_KEY`` so only this
   server can mint a valid one. The client echoes it in the ``X-CSRF-Token`` header
   on every unsafe method; the server verifies the signature and then does a
   **constant-time** compare against the session's stored token. A cross-site page
   cannot read the cookie (it's a different origin) so it cannot populate the header.
2. **Origin/Referer allow-list.** Unsafe requests must carry an ``Origin`` (or, as a
   fallback, ``Referer``) whose origin is in the configured allow-list.
3. ``SameSite=Lax`` on the session cookie (set at the cookie layer) as a third net.
"""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlsplit

from auth.config import AUTH_ALLOWED_ORIGINS, SECRET_KEY

_SEP = "."


def _sign(token: str) -> str:
    digest = hmac.new(SECRET_KEY.encode(), token.encode(), hashlib.sha256).hexdigest()
    return f"{token}{_SEP}{digest}"


def issue_cookie_value(token: str) -> str:
    """The signed value to place in the readable ``afp_csrf`` cookie."""
    return _sign(token)


def unsign(value: str) -> str | None:
    """Recover the token from a signed cookie/header value, or ``None`` if the
    signature is absent or invalid (constant-time comparison)."""
    if not value or _SEP not in value:
        return None
    token, _, digest = value.rpartition(_SEP)
    expected = hmac.new(SECRET_KEY.encode(), token.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, expected):
        return None
    return token


def verify_csrf(session_token: str, header_value: str | None) -> bool:
    """True iff the ``X-CSRF-Token`` header carries a validly-signed token that
    matches this session's stored token. Constant-time throughout."""
    if not header_value or not session_token:
        return False
    token = unsign(header_value)
    if token is None:
        return False
    return hmac.compare_digest(token, session_token)


def _origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def check_origin(origin: str | None, referer: str | None) -> bool:
    """Allow the request only if its Origin (preferred) or Referer resolves to an
    allowed origin. A missing *and* unparseable pair is rejected on unsafe methods."""
    candidate = origin or referer
    if not candidate:
        return False
    resolved = _origin_of(candidate)
    if resolved is None:
        return False
    return resolved in AUTH_ALLOWED_ORIGINS
