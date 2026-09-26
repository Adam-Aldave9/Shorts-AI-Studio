"""No-network classification of provider failures into ErrorCodes."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from schema import ErrorCode

from adapters import registry
from adapters.base import ProviderError
from adapters.elevenlabs import _ELEVENLABS_CODES
from adapters.errors import http_error
from adapters.fal import _FAL_TYPE_CODES, FalAdapter
from adapters.mock import MockAdapter

LONG_PROMPT = "Animated. Establishing wide shot. " * 70

TOO_LONG_BODY = {
    "detail": [
        {
            "loc": ["body", "prompt"],
            "msg": "The prompt is 2069 UTF-8 encoded bytes, which exceeds the maximum of 2048.",
            "type": "sequence_too_long",
            "url": "https://docs.fal.ai/errors#sequence_too_long",
            "ctx": {"max_length": 2048},
            "input": LONG_PROMPT,
        }
    ]
}

CONTENT_POLICY_BODY = {
    "detail": [
        {
            "loc": ["body"],
            "msg": "The content could not be processed because it contained material flagged "
            "by a content checker.",
            "type": "content_policy_violation",
            "url": "https://docs.fal.ai/errors#content_policy_violation",
            "input": {"prompt": LONG_PROMPT, "image_url": "https://v3b.fal.media/files/b/x/ref.jpg"},
        }
    ]
}


def _fal(status: int, body=None, *, text: str | None = None, headers=None) -> ProviderError:
    if text is not None:
        resp = httpx.Response(status, text=text, headers=headers)
    else:
        resp = httpx.Response(status, json=body, headers=headers)
    return http_error("fal", "fetch", resp, _FAL_TYPE_CODES)


def test_incident_prompt_too_long():
    err = _fal(422, TOO_LONG_BODY)
    assert err.code is ErrorCode.PROMPT_TOO_LONG
    assert err.transient is False
    assert str(err).startswith("The prompt is 2069 UTF-8 encoded bytes")
    assert err.detail.startswith("fal fetch HTTP 422: ")
    assert "sequence_too_long" in err.detail and "max_length" in err.detail


def test_incident_content_policy():
    err = _fal(422, CONTENT_POLICY_BODY)
    assert err.code is ErrorCode.CONTENT_POLICY
    assert err.transient is False
    assert "flagged by a content checker" in str(err)


def test_input_is_stripped_from_detail():
    for body in (TOO_LONG_BODY, CONTENT_POLICY_BODY):
        err = _fal(422, body)
        assert "Establishing wide shot" not in err.detail
        assert '"input"' not in err.detail
        assert "ref.jpg" not in err.detail


def test_sequence_too_long_elsewhere_is_invalid_input():
    body = {"detail": [{"loc": ["body", "image_urls"], "msg": "too many", "type": "sequence_too_long"}]}
    assert _fal(422, body).code is ErrorCode.INVALID_INPUT


def test_file_download_error_is_input_image():
    body = {"detail": [{"loc": ["body", "image_url"], "msg": "could not download", "type": "file_download_error"}]}
    assert _fal(422, body).code is ErrorCode.INPUT_IMAGE


def test_runner_types_are_transient():
    body = {"detail": [{"loc": ["body"], "msg": "runner died", "type": "runner_disconnected"}]}
    err = _fal(422, body)
    assert err.code is ErrorCode.PROVIDER_UNAVAILABLE and err.transient is True


def test_top_level_error_type():
    err = _fal(500, {"error": "timed out", "error_type": "generation_timeout"})
    assert err.code is ErrorCode.PROVIDER_UNAVAILABLE
    assert str(err) == "timed out"


def test_status_defaults():
    assert _fal(401, {"detail": "Invalid key"}).code is ErrorCode.AUTH
    exhausted = _fal(403, {"detail": "User is locked. Reason: Exhausted balance."})
    assert exhausted.code is ErrorCode.QUOTA and exhausted.transient is False
    limited = _fal(429, {"detail": "slow down"})
    assert limited.code is ErrorCode.RATE_LIMITED and limited.transient is True
    unavailable = _fal(503, {"detail": "unavailable"})
    assert unavailable.code is ErrorCode.PROVIDER_UNAVAILABLE and unavailable.transient is True
    assert _fal(404, {"detail": "nope"}).code is ErrorCode.INVALID_INPUT


def test_non_json_body():
    err = _fal(500, text="<html>Bad gateway</html>")
    assert err.code is ErrorCode.PROVIDER_UNAVAILABLE
    assert str(err) == "HTTP 500"
    assert err.detail == "fal fetch HTTP 500: <html>Bad gateway</html>"


def test_needs_retry_header_is_recorded():
    err = _fal(503, {"detail": "busy"}, headers={"X-Fal-Needs-Retry": "1"})
    assert err.detail.endswith("[X-Fal-Needs-Retry: 1]")


def test_elevenlabs_status_overrides_http_status():
    resp = httpx.Response(
        401, json={"detail": {"status": "quota_exceeded", "message": "You have 0 credits left."}}
    )
    err = http_error("elevenlabs", "submit", resp, _ELEVENLABS_CODES)
    assert err.code is ErrorCode.QUOTA
    assert str(err) == "You have 0 credits left."
    voice = httpx.Response(
        400, json={"detail": {"status": "voice_not_found", "message": "Voice not found."}}
    )
    assert http_error("elevenlabs", "submit", voice, _ELEVENLABS_CODES).code is ErrorCode.INVALID_INPUT


def test_flux_safety_flag_is_a_billed_content_policy_failure():
    data = {
        "images": [{"url": "https://v3b.fal.media/files/b/example/black.jpg"}],
        "has_nsfw_concepts": [True],
    }
    with pytest.raises(ProviderError) as ei:
        FalAdapter._parse_result(data, {"model": "flux-schnell", "kind": "image"})
    assert ei.value.code is ErrorCode.CONTENT_POLICY
    assert ei.value.transient is False
    assert ei.value.cost_usd == 0.03


def test_flux_clean_result_parses():
    data = {"images": [{"url": "https://x/ok.jpg"}], "has_nsfw_concepts": [False]}
    result = FalAdapter._parse_result(data, {"model": "flux-schnell", "kind": "image"})
    assert result.asset_url == "https://x/ok.jpg" and result.cost_usd == 0.03


def test_missing_result_url_is_permanent_unknown():
    with pytest.raises(ProviderError) as ei:
        FalAdapter._parse_result({"video": {}}, {"model": "pixverse-v6-i2v", "kind": "video"})
    assert ei.value.code is ErrorCode.UNKNOWN and ei.value.transient is False


def test_transient_defaults_from_code():
    assert ProviderError("x", code=ErrorCode.RATE_LIMITED).transient is True
    assert ProviderError("x", code=ErrorCode.CONTENT_POLICY).transient is False
    assert ProviderError("x").transient is False
    assert ProviderError("x", code=ErrorCode.CONTENT_POLICY, transient=True).transient is True


@pytest.mark.parametrize(
    ("token", "code", "transient"),
    [
        ("content_policy", ErrorCode.CONTENT_POLICY, False),
        ("provider_unavailable", ErrorCode.PROVIDER_UNAVAILABLE, True),
        ("bogus", ErrorCode.UNKNOWN, False),
    ],
)
def test_mock_failure_token(token, code, transient):
    payload = {"asset_type": "video", "prompt": f"a shot [mock-fail:{token}]"}
    with pytest.raises(ProviderError) as ei:
        asyncio.run(MockAdapter("fal").submit("pixverse-v6-i2v", payload))
    assert ei.value.code is code
    assert ei.value.transient is transient


def test_mock_failure_token_in_narration():
    payload = {"asset_type": "voiceover", "text": "Hello [mock-fail:quota]"}
    with pytest.raises(ProviderError) as ei:
        asyncio.run(MockAdapter("elevenlabs").submit("flash-v2.5", payload))
    assert ei.value.code is ErrorCode.QUOTA


def test_unknown_provider_is_permanent_invalid_input():
    with pytest.raises(ProviderError) as ei:
        registry.get_adapter("runway:gen3")
    assert ei.value.code is ErrorCode.INVALID_INPUT
    assert ei.value.transient is False
