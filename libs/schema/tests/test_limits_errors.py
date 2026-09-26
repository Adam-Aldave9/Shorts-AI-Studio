from schema import (
    TRANSIENT_CODES,
    ErrorCode,
    mock_failure_code,
    prompt_max_bytes,
    strip_mock_failure,
    utf8_len,
)


def test_utf8_len_counts_bytes_not_chars():
    assert utf8_len("\u2014") == 3
    assert utf8_len("abc") == 3
    assert utf8_len(None) == 0


def test_prompt_max_bytes_lookup():
    assert prompt_max_bytes("fal:pixverse-v6-i2v") == 2048
    assert prompt_max_bytes("fal:flux-schnell") is None
    assert prompt_max_bytes(None) is None


def test_error_code_renders_as_value():
    assert f"{ErrorCode.CONTENT_POLICY}" == "content_policy"
    assert ErrorCode.RATE_LIMITED in TRANSIENT_CODES
    assert ErrorCode.CONTENT_POLICY not in TRANSIENT_CODES


def test_mock_failure_code_parse():
    assert mock_failure_code("a shot [mock-fail:content_policy] here") is ErrorCode.CONTENT_POLICY
    assert mock_failure_code("[mock-fail:provider_unavailable]") is ErrorCode.PROVIDER_UNAVAILABLE
    assert mock_failure_code("[mock-fail:nonsense]") is ErrorCode.UNKNOWN
    assert mock_failure_code("clean prompt") is None
    assert mock_failure_code(None) is None


def test_strip_mock_failure():
    assert strip_mock_failure("A  shot [mock-fail:content_policy] of a river.") == "A shot of a river."
    assert strip_mock_failure("[mock-fail:timeout] x [mock-fail:auth]") == "x"
