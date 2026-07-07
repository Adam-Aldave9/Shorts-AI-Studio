"""The planning agents (spec §4.1).

Each agent is a pure ``build_prompt(...) -> messages`` + ``parse(result) -> model``
pair plus a thin ``run(...)`` that hands the messages to a swappable LLM ``call``.
That split keeps every agent unit-testable with no network: tests exercise
``build_prompt`` / ``parse`` directly against canned responses (spec §14.4
verification), and inject a fake ``call`` into ``run``.
"""

from planning.agents import breakdown, prompts, script, world

__all__ = ["world", "script", "breakdown", "prompts"]
