"""Claude advisor adapter over the shared coordinator event loop."""

from __future__ import annotations

import logging
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage

from backend.agents.coordinator_loop import build_deps, run_event_loop
from backend.config import Settings
from backend.control.advisor import (
    ADVISOR_SYSTEM_PROMPT,
    AdvisorContext,
    AdvisorSuggestion,
    parse_advisor_suggestions_json,
    render_advisor_prompt,
)

logger = logging.getLogger(__name__)


class ClaudeCoordinatorAdvisor:
    """Claude SDK advisor adapter that returns structured suggestions only."""

    def __init__(self, model: str) -> None:
        self.model = model

    async def start(self) -> None:
        return None

    async def suggest(self, context: AdvisorContext) -> list[AdvisorSuggestion]:
        prompt = render_advisor_prompt(context)
        text = ""
        options = ClaudeAgentOptions(
            model=self.model,
            system_prompt=ADVISOR_SYSTEM_PROMPT,
            env={"CLAUDECODE": ""},
            allowed_tools=[],
            permission_mode="bypassPermissions",
        )
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for message in client.receive_response():
                if isinstance(message, ResultMessage) and message.result:
                    text = str(message.result).strip()
        return parse_advisor_suggestions_json(text, default_challenge=context.challenge_name)

    async def stop(self) -> None:
        return None


async def run_claude_coordinator(
    settings: Settings,
    model_specs: list[str] | None = None,
    challenges_root: str = "challenges",
    no_submit: bool = False,
    coordinator_model: str | None = None,
    msg_port: int = 0,
) -> dict[str, Any]:
    """Run the Claude advisor provider on top of the shared event loop."""
    ctfd, cost_tracker, deps = build_deps(
        settings, model_specs, challenges_root, no_submit,
    )
    deps.msg_port = msg_port

    resolved_model = coordinator_model or "claude-opus-4-6"
    advisor = ClaudeCoordinatorAdvisor(model=resolved_model)

    async def event_sink(message: str) -> None:
        logger.debug("Claude coordinator event: %s", message[:240])

    try:
        await advisor.start()
        return await run_event_loop(
            deps,
            ctfd,
            cost_tracker,
            event_sink=event_sink,
            advisor=advisor,
        )
    finally:
        await advisor.stop()
