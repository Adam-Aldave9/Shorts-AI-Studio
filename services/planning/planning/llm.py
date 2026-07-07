"""The one place the planning tier talks to an LLM (spec §2.1, §4.4).

This is the *thin, swappable* half of the pure-fn + thin-wrapper split the worker
and compositor use: the agents build prompts and parse results with no network in
sight, and hand the actual call here. Tests inject a fake ``call`` and never reach
this module; the real path lazily imports ``langchain-anthropic`` so importing the
planning package (and running the MOCK chain) needs no LLM stack installed.

Per-agent model routing (spec §4.4, pulled forward from v2): the script agent runs
on a stronger model because that creative step is where quality pays off; the
breakdown and prompts agents — run more often during tuning — run on a cheaper one.
Structured output via ``with_structured_output`` so each agent gets schema-shaped
JSON back, not free text.
"""

from __future__ import annotations

from typing import Sequence

from pydantic import BaseModel

# Per-agent model routing. Opus for the open-ended creative steps (world-building
# and scripting), Sonnet for the two cheaper, more mechanical ones.
MODEL_WORLD = "claude-opus-4-8"
MODEL_SCRIPT = "claude-opus-4-8"
MODEL_BREAKDOWN = "claude-sonnet-4-6"
MODEL_PROMPTS = "claude-sonnet-4-6"

# Newer Claude models deprecate the ``temperature`` parameter and reject requests
# that set it (400 invalid_request_error). The agents still express an intended
# temperature for readability/older models, so we accept it in the signature but
# only forward it to models that still support it.
_NO_TEMPERATURE_MODELS = {"claude-opus-4-8"}

# A message is a (role, content) tuple — ``langchain`` accepts these directly, so
# the agents' ``build_prompt`` functions stay free of any langchain import.
Messages = Sequence[tuple[str, str]]


def call_structured(
    *,
    model: str,
    messages: Messages,
    schema: type[BaseModel],
    temperature: float = 0.7,
    max_tokens: int = 8192,
) -> BaseModel:
    """Invoke ``model`` and return an instance of ``schema`` (tool-calling JSON).

    ``langchain_anthropic`` is imported lazily so this dependency is only required
    on a real, keyed run — never for the mock chain or the unit tests, which pass a
    stand-in ``call`` to the agents instead.
    """
    from langchain_anthropic import ChatAnthropic

    kwargs: dict = {"model": model, "max_tokens": max_tokens}
    if model not in _NO_TEMPERATURE_MODELS:
        kwargs["temperature"] = temperature

    llm = ChatAnthropic(**kwargs)
    return llm.with_structured_output(schema).invoke(list(messages))
