from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

ALLOWED_ADVISOR_ACTION_HINTS = {
    "none",
    "spawn_swarm",
    "bump_solver",
    "broadcast_knowledge",
}

ADVISOR_SYSTEM_PROMPT = """\
You are a provider-neutral CTF coordinator advisor.
You do not have tools. You cannot execute actions yourself.
Review one challenge at a time and return only structured suggestions for the coordinator policy layer.

Allowed action_hint values:
- none
- spawn_swarm
- bump_solver
- broadcast_knowledge

Return ONLY JSON. Use either:
- a JSON array of suggestion objects, or
- an object with a "suggestions" array.

Each suggestion object may contain:
- action_hint
- challenge_name
- model_spec
- guidance
- reason
- message
- source
- knowledge_id

Contract rules:
- For broadcast_knowledge, you MUST copy back a knowledge_id from knowledge_summary.
- Do not emit broadcast_knowledge if no reusable knowledge candidate includes a knowledge_id.
- Keep each suggestion scoped to the provided challenge_name only.
- If you include challenge_name, it must exactly match the provided challenge_name.

Keep suggestions concise and execution-free. Do not describe tool calls.
"""


@dataclass(slots=True)
class AdvisorContext:
    competition_summary: str
    challenge_name: str
    memory_summary: str
    knowledge_summary: str
    strategy_summary: str = ""


@dataclass(slots=True)
class AdvisorSuggestion:
    action_hint: str
    challenge_name: str
    model_spec: str = ""
    guidance: str = ""
    reason: str = ""
    message: str = ""
    source: str = ""
    knowledge_id: str = ""


@runtime_checkable
class CoordinatorAdvisor(Protocol):
    async def suggest(self, context: AdvisorContext) -> list[AdvisorSuggestion]:
        """Return structured suggestions for a single challenge."""


def render_advisor_prompt(context: AdvisorContext) -> str:
    return (
        "Provide advisor suggestions for the following challenge context.\n\n"
        f"competition_summary: {context.competition_summary}\n"
        f"challenge_name: {context.challenge_name}\n"
        f"memory_summary: {context.memory_summary}\n"
        f"knowledge_summary: {context.knowledge_summary}\n"
        f"strategy_summary: {context.strategy_summary}\n"
    )


def parse_advisor_suggestions_json(
    text: str,
    *,
    default_challenge: str,
) -> list[AdvisorSuggestion]:
    normalized = _strip_json_fence(text)
    if not normalized:
        return []

    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        raw_items = payload.get("suggestions", [])
    elif isinstance(payload, list):
        raw_items = payload
    else:
        return []

    suggestions: list[AdvisorSuggestion] = []
    for item in raw_items:
        suggestion = _coerce_suggestion(item, default_challenge=default_challenge)
        if suggestion is not None:
            suggestions.append(suggestion)
    return suggestions


def _coerce_suggestion(item: Any, *, default_challenge: str) -> AdvisorSuggestion | None:
    if not isinstance(item, dict):
        return None

    action_hint = str(item.get("action_hint", "")).strip().lower()
    if not action_hint:
        action_hint = "none"
    if action_hint not in ALLOWED_ADVISOR_ACTION_HINTS:
        return None

    raw_challenge_name = str(item.get("challenge_name", "")).strip()
    if raw_challenge_name and raw_challenge_name != default_challenge:
        return None

    challenge_name = raw_challenge_name or default_challenge
    if not challenge_name:
        return None

    knowledge_id = str(item.get("knowledge_id", "")).strip()
    if action_hint == "broadcast_knowledge" and not knowledge_id:
        return None

    return AdvisorSuggestion(
        action_hint=action_hint,
        challenge_name=challenge_name,
        model_spec=str(item.get("model_spec", "")).strip(),
        guidance=str(item.get("guidance", "")).strip(),
        reason=str(item.get("reason", "")).strip(),
        message=str(item.get("message", "")).strip(),
        source=str(item.get("source", "")).strip(),
        knowledge_id=knowledge_id,
    )


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if not lines:
        return ""
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
