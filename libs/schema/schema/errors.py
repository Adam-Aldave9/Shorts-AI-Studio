"""The provider-failure vocabulary shared by adapters, worker, scheduler and UI."""

import re
from enum import StrEnum


class ErrorCode(StrEnum):
    PROMPT_TOO_LONG = "prompt_too_long"
    CONTENT_POLICY = "content_policy"
    INPUT_IMAGE = "input_image"
    INVALID_INPUT = "invalid_input"
    TIMEOUT = "timeout"
    AUTH = "auth"
    QUOTA = "quota"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


TRANSIENT_CODES: frozenset[ErrorCode] = frozenset(
    {ErrorCode.RATE_LIMITED, ErrorCode.PROVIDER_UNAVAILABLE}
)

_MOCK_FAIL = re.compile(r"\[mock-fail:([a-z_]+)\]")


def mock_failure_code(text: str | None) -> ErrorCode | None:
    match = _MOCK_FAIL.search(text or "")
    if match is None:
        return None
    try:
        return ErrorCode(match.group(1))
    except ValueError:
        return ErrorCode.UNKNOWN


def strip_mock_failure(text: str) -> str:
    return " ".join(_MOCK_FAIL.sub(" ", text).split())
