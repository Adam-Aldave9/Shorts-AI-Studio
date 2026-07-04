"""CSRF token signing/verification + Origin allow-list (no I/O)."""

from __future__ import annotations

from auth import csrf


def test_sign_unsign_roundtrip():
    signed = csrf.issue_cookie_value("token-abc")
    assert signed != "token-abc"  # carries an HMAC suffix
    assert csrf.unsign(signed) == "token-abc"


def test_unsign_rejects_tampered_value():
    signed = csrf.issue_cookie_value("token-abc")
    tampered = signed[:-1] + ("0" if signed[-1] != "0" else "1")
    assert csrf.unsign(tampered) is None
    assert csrf.unsign("no-separator") is None
    assert csrf.unsign("") is None


def test_verify_csrf_matches_session_token():
    session_token = "sess-token-xyz"
    header = csrf.issue_cookie_value(session_token)
    assert csrf.verify_csrf(session_token, header) is True
    # a validly-signed but different token must not pass
    assert csrf.verify_csrf(session_token, csrf.issue_cookie_value("other")) is False
    assert csrf.verify_csrf(session_token, None) is False
    assert csrf.verify_csrf("", header) is False


def test_check_origin_allow_list():
    assert csrf.check_origin("http://localhost:5173", None) is True
    assert csrf.check_origin(None, "http://localhost:5173/checkpoint/x") is True
    assert csrf.check_origin("http://evil.example", None) is False
    assert csrf.check_origin(None, None) is False
    assert csrf.check_origin("garbage", None) is False
