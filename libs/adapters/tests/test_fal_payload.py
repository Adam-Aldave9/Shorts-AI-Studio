"""No-network sanity checks for the fal adapter's payload builder + tables."""

from __future__ import annotations

import pytest

from adapters.base import ProviderError
from adapters.fal import _MODEL_SLUGS, _PRICES, FalAdapter


def test_flux_input_includes_image_size():
    body = FalAdapter._build_input("flux-schnell", {"prompt": "a frog", "width": 1024, "height": 576})
    assert body["prompt"] == "a frog"
    assert body["image_size"] == {"width": 1024, "height": 576}


def test_flux_input_without_dims_omits_image_size():
    body = FalAdapter._build_input("flux-schnell", {"prompt": "x"})
    assert "image_size" not in body


def test_pixverse_requires_image_url():
    with pytest.raises(ProviderError) as ei:
        FalAdapter._build_input("pixverse-v6-i2v", {"prompt": "pan", "image_url": None})
    assert ei.value.transient is False


def test_pixverse_builds_body_with_int_duration():
    body = FalAdapter._build_input(
        "pixverse-v6-i2v", {"prompt": "pan", "image_url": "https://x/y.png", "duration": 3.0}
    )
    assert body == {"prompt": "pan", "image_url": "https://x/y.png", "duration": 3}


def test_unknown_model_is_permanent_error():
    with pytest.raises(ProviderError) as ei:
        FalAdapter._build_input("nope", {})
    assert ei.value.transient is False


def test_priced_models_all_have_slugs():
    assert set(_PRICES) <= set(_MODEL_SLUGS)
