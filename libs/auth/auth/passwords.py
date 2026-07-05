"""Password hashing — Argon2id via ``argon2-cffi`` (OWASP-recommended params).

The pipeline never stores plaintext: registration hashes, login verifies, and when
the tuning parameters change we transparently rehash on the next successful login.
A module-level ``DUMMY_HASH`` lets the login path spend the same CPU verifying a
*non-existent* user as a real one, so response timing does not leak which usernames
exist (user-enumeration defense).
"""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# OWASP Argon2id minimums (memory in KiB, iterations, lanes). argon2-cffi defaults are
# already at/above these; we pin them so the cost is explicit and stable across envs.
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

# A precomputed hash of a random string. Verifying against it burns a full Argon2
# check for unknown users, matching the timing of a real (failed) verify.
DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    """Return an Argon2id hash (embeds algorithm + params + salt)."""
    return _HASHER.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Constant-ish-time verify. Returns False on mismatch or a malformed stored hash
    rather than raising, so callers branch on a plain bool."""
    try:
        return _HASHER.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when ``stored_hash`` was made with older/weaker params than current — the
    caller rehashes with :func:`hash_password` after a successful verify."""
    try:
        return _HASHER.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return False
