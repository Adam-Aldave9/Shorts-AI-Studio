"""Request/response models for the auth endpoints.

Validation is the first security gate: usernames are constrained to a small charset
and normalized to lowercase (so ``Alice`` and ``alice`` are the same account), and
passwords have a floor (entropy) and a ceiling (to bound Argon2 hashing cost — an
unbounded password is a cheap DoS). ``UserOut`` is deliberately minimal: it never
carries the password hash.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator

USERNAME_MIN = 3
USERNAME_MAX = 32
PASSWORD_MIN = 12
PASSWORD_MAX = 128

# Letters, digits, and a few separators — no whitespace/control/markup.
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")


def normalize_username(username: str) -> str:
    """The canonical stored form: trimmed + lowercased (case-insensitive identity)."""
    return username.strip().lower()


class RegisterRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        candidate = value.strip()
        if not (USERNAME_MIN <= len(candidate) <= USERNAME_MAX):
            raise ValueError(
                f"username must be {USERNAME_MIN}-{USERNAME_MAX} characters"
            )
        if not _USERNAME_RE.match(candidate):
            raise ValueError(
                "username may contain only letters, digits, '.', '_' and '-'"
            )
        return candidate

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        if not (PASSWORD_MIN <= len(value) <= PASSWORD_MAX):
            raise ValueError(
                f"password must be {PASSWORD_MIN}-{PASSWORD_MAX} characters"
            )
        return value


class LoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _trim_username(cls, value: str) -> str:
        # Login is lenient on format (the register gate already ran); it only needs a
        # length ceiling so an absurd input cannot force wasted work.
        candidate = value.strip()
        if not candidate or len(candidate) > USERNAME_MAX:
            raise ValueError("invalid username")
        return candidate

    @field_validator("password")
    @classmethod
    def _cap_password(cls, value: str) -> str:
        if not value or len(value) > PASSWORD_MAX:
            raise ValueError("invalid password")
        return value


class UserOut(BaseModel):
    """The safe public view of an account (never includes the password hash)."""

    user_id: str
    username: str
