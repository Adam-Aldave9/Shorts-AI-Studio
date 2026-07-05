"""FastAPI dependencies for protected handlers.

The ASGI middleware has already authenticated the request and stamped
``request.state.user_id`` before any handler runs, so these dependencies are cheap
reads of that state plus (for ownership) one persistence lookup. They exist so
individual handlers can declare *ownership* requirements the middleware can't express
generically (it doesn't know a path's ``project_id`` semantics).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

import state

from auth import users
from auth.models import UserOut


def current_user_id(request: Request) -> str:
    """The authenticated user's id, from middleware-populated request state.

    A protected route only runs after the middleware allowed it, so this is
    normally set; the 401 guards the misconfiguration where a dependency is attached
    to a path the middleware treats as public."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="authentication required")
    return user_id


async def current_user(request: Request) -> UserOut:
    """The full public view of the authenticated account (loads from persistence)."""
    user = await users.get_user(current_user_id(request))
    if user is None:
        # Session referenced a user that no longer exists — treat as unauthenticated.
        raise HTTPException(status_code=401, detail="authentication required")
    return user


async def owned_package(project_id: str, request: Request) -> str:
    """Guard a per-package route: the caller must own ``project_id``.

    Returns **404** (not 403) for a package the caller doesn't own — or one that
    doesn't exist, or a legacy unowned one — so the response never reveals which
    project ids exist to a non-owner."""
    user_id = current_user_id(request)
    owner = await state.get_project_owner(project_id)
    if owner is None or owner != user_id:
        raise HTTPException(status_code=404, detail="package not found")
    return project_id


# A ready-to-use dependency object for `= Depends(...)` defaults.
OwnedPackage = Depends(owned_package)
