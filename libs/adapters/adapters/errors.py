"""Classify a provider's failed HTTP response into a ``ProviderError`` with an ``ErrorCode``."""

from __future__ import annotations

import json
from typing import Any

import httpx
from schema import ErrorCode

from adapters.base import ProviderError

_DETAIL_MAX_CHARS = 1500
_PROMPT_FIELDS = {"prompt", "negative_prompt"}
_QUOTA_WORDS = ("balance", "credit", "quota")


def _status_default(status: int, message: str) -> ErrorCode:
    if status in (401, 403):
        lowered = message.lower()
        return ErrorCode.QUOTA if any(w in lowered for w in _QUOTA_WORDS) else ErrorCode.AUTH
    if status == 402:
        return ErrorCode.QUOTA
    if status == 429:
        return ErrorCode.RATE_LIMITED
    if status in (408, 504) or status >= 500:
        return ErrorCode.PROVIDER_UNAVAILABLE
    return ErrorCode.INVALID_INPUT


def _without_input(value: Any) -> Any:
    # fal echoes the whole request input back; it would crowd out the useful part.
    if isinstance(value, dict):
        return {k: _without_input(v) for k, v in value.items() if k != "input"}
    if isinstance(value, list):
        return [_without_input(v) for v in value]
    return value


def _parse_body(body: Any) -> tuple[str | None, str | None, list[Any]]:
    """Best-effort ``(type, message, loc)`` from the provider's error body."""
    if not isinstance(body, dict):
        return None, None, []
    detail = body.get("detail")
    if isinstance(detail, list) and detail and isinstance(detail[0], dict):
        first = detail[0]
        loc = first.get("loc")
        kind = first.get("type") or body.get("error_type")
        return kind, first.get("msg"), loc if isinstance(loc, list) else []
    if isinstance(detail, dict):
        return detail.get("status"), detail.get("message"), []
    if isinstance(detail, str):
        return body.get("error_type"), detail, []
    error = body.get("error")
    return body.get("error_type"), error if isinstance(error, str) else None, []


def _classify(kind: str | None, loc: list[Any], type_codes: dict[str, ErrorCode]) -> ErrorCode | None:
    if not kind:
        return None
    if kind == "sequence_too_long" and loc and loc[-1] in _PROMPT_FIELDS:
        return ErrorCode.PROMPT_TOO_LONG
    if kind.startswith("runner_"):
        return ErrorCode.PROVIDER_UNAVAILABLE
    return type_codes.get(kind)


def http_error(
    provider: str, verb: str, resp: httpx.Response, type_codes: dict[str, ErrorCode]
) -> ProviderError:
    status = resp.status_code
    try:
        body = resp.json()
    except ValueError:
        body = None

    kind, message, loc = _parse_body(body)
    message = message or f"HTTP {status}"
    code = _classify(kind, loc, type_codes) or _status_default(status, message)

    prefix = f"{provider} {verb} HTTP {status}: "
    if body is None:
        detail = prefix + resp.text[:500]
    else:
        compact = json.dumps(_without_input(body), separators=(",", ":"), ensure_ascii=False)
        detail = (prefix + compact)[:_DETAIL_MAX_CHARS]
    needs_retry = resp.headers.get("X-Fal-Needs-Retry")
    if needs_retry is not None:
        detail += f" [X-Fal-Needs-Retry: {needs_retry}]"

    return ProviderError(message, code=code, detail=detail)
