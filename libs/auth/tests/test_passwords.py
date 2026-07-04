"""Argon2id password hashing (no I/O)."""

from __future__ import annotations

from auth import passwords


def test_hash_is_argon2id_and_not_plaintext():
    hashed = passwords.hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert "correct horse battery staple" not in hashed


def test_verify_accepts_correct_and_rejects_wrong():
    hashed = passwords.hash_password("s3cret-passphrase!")
    assert passwords.verify_password(hashed, "s3cret-passphrase!") is True
    assert passwords.verify_password(hashed, "not-the-password") is False


def test_verify_on_malformed_hash_returns_false():
    assert passwords.verify_password("not-a-real-hash", "whatever") is False


def test_two_hashes_of_same_password_differ_by_salt():
    a = passwords.hash_password("same-input-here")
    b = passwords.hash_password("same-input-here")
    assert a != b  # random per-hash salt


def test_dummy_hash_verifies_false_for_arbitrary_input():
    # The enumeration-defense hash must never accidentally match a real password.
    assert passwords.verify_password(passwords.DUMMY_HASH, "anything") is False


def test_needs_rehash_false_for_current_params():
    assert passwords.needs_rehash(passwords.hash_password("current-params-pw")) is False
