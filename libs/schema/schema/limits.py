"""Provider input limits a package must satisfy to be renderable."""

PROMPT_MAX_BYTES: dict[str, int] = {
    "fal:pixverse-v6-i2v": 2048,
}


def utf8_len(text: str | None) -> int:
    return len((text or "").encode("utf-8"))


def prompt_max_bytes(provider_hint: str | None) -> int | None:
    return PROMPT_MAX_BYTES.get(provider_hint or "")
