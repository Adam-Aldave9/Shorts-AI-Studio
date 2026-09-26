"""Revise agent: rewrite one image-to-video prompt a provider rejected.

Used by the Status page's "Suggest fix". It only proposes a rewrite; the user reviews
it and saves through the scheduler, so approved content never changes unseen.
"""

from __future__ import annotations

from schema import ErrorCode

from planning.llm import MODEL_PROMPTS, Messages, call_structured
from planning.models import PromptRevision

SYSTEM = (
    "You fix one image-to-video prompt that a video provider rejected. Preserve the "
    "shot's camera, story beat, the characters' identities and the closing style "
    "sentence. Return the full rewritten prompt and one sentence on what you changed."
)

_CONTENT_POLICY = (
    "An automated content filter rejected it; depict the same moment so a strict filter "
    "accepts it: tension, motion and expression; no graphic violence, injuries, blood, or "
    "weapons aimed or fired at people."
)
_GENERIC = "Make it a clear, self-contained description of the camera move and action."


def _guidance(code: ErrorCode | None, max_bytes: int | None) -> str:
    if code is ErrorCode.PROMPT_TOO_LONG:
        target = f"at most {max_bytes} bytes" if max_bytes else "substantially"
        return (
            f"It was too long for the model. Shorten it to {target}: describe the setting "
            "in one clause, keep the focal character's description, and condense the "
            "others to their name plus two or three distinctive visual traits."
        )
    if code is ErrorCode.CONTENT_POLICY:
        return _CONTENT_POLICY
    return _GENERIC


def build_prompt(
    prompt: str, code: ErrorCode | None, *, max_bytes: int | None, style: str
) -> Messages:
    """Pure: rejected prompt + failure code -> chat messages."""
    limits = "Use plain ASCII punctuation (no em dashes or curly quotes)."
    if max_bytes:
        limits = f"Stay under {max_bytes} UTF-8 bytes. " + limits
    human = (
        f"The film's visual style: {style}.\n\n"
        f"Rejected prompt:\n{prompt}\n\n"
        f"{_guidance(code, max_bytes)}\n{limits}"
    )
    return [("system", SYSTEM), ("human", human)]


def parse(result: PromptRevision | dict) -> PromptRevision:
    return result if isinstance(result, PromptRevision) else PromptRevision.model_validate(result)


def run(
    prompt: str,
    code: ErrorCode | None,
    *,
    max_bytes: int | None,
    style: str,
    call=call_structured,
) -> PromptRevision:
    raw = call(
        model=MODEL_PROMPTS,
        messages=build_prompt(prompt, code, max_bytes=max_bytes, style=style),
        schema=PromptRevision,
        temperature=0.3,
    )
    return parse(raw)
