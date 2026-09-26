"""Deterministic fitting of provider prompts into their byte limits."""

from __future__ import annotations

import re

from schema import utf8_len

_ASCII_PUNCTUATION = str.maketrans(
    {
        "\u2014": "-",
        "\u2013": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u00a0": " ",
    }
)

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def normalize_punctuation(text: str) -> str:
    return text.translate(_ASCII_PUNCTUATION)


def _cut_bytes(text: str, max_bytes: int) -> str:
    cut = text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
    if cut != text and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip()


def fit_to_bytes(text: str, max_bytes: int | None) -> str:
    """Drop middle sentences (never the opening shot/camera sentence or the closing
    style sentence) until ``text`` fits; cut bytes only as a last resort."""
    if max_bytes is None or utf8_len(text) <= max_bytes:
        return text
    sentences = _SENTENCE_BREAK.split(text.strip())
    if len(sentences) > 2:
        first, middle, last = sentences[0], sentences[1:-1], sentences[-1]
        while middle:
            middle.pop()
            candidate = " ".join([first, *middle, last])
            if utf8_len(candidate) <= max_bytes:
                return candidate
        text = f"{first} {last}"
        if utf8_len(text) <= max_bytes:
            return text
    return _cut_bytes(text, max_bytes)
