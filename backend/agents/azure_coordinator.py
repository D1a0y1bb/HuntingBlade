"""Azure advisor adapter over the shared coordinator event loop."""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent

from backend.agents.coordinator_loop import build_deps, run_event_loop
from backend.config import Settings
from backend.control.advisor import (
    ADVISOR_SYSTEM_PROMPT,
    AdvisorContext,
    AdvisorSuggestion,
    parse_advisor_suggestions_json,
    render_advisor_prompt,
)
from backend.models import resolve_model, resolve_model_settings
from backend.platforms.base import CompetitionPlatformClient

logger = logging.getLogger(__name__)


def _normalize_azure_coordinator_model(spec: str | None) -> str:
    if not spec:
        return "azure/gpt-5.4"
    if "/" not in spec:
        return f"azure/{spec}"
    if not spec.startswith("azure/"):
        raise ValueError("azure coordinator 只能使用 azure/<model> 或裸模型名")
    return spec


def parse_advisor_suggestions(text: str, default_challenge: str) -> list[AdvisorSuggestion]:
    return parse_advisor_suggestions_json(text, default_challenge=default_challenge)


class AzureCoordinatorAdvisor:
    """Azure/OpenAI-compatible advisor that emits structured suggestions only."""

    def __init__(self, settings: Settings, model_spec: str) -> None:
        self.settings = settings
        self.model_spec = _normalize_azure_coordinator_model(model_spec)
        self._agent: Agent[None, str] | None = None

    async def start(self) -> None:
        if self._agent is not None:
            return
        model = resolve_model(self.model_spec, self.settings)
        model_settings = resolve_model_settings(self.model_spec)
        self._agent = Agent(
            model,
            system_prompt=ADVISOR_SYSTEM_PROMPT,
            model_settings=model_settings,
        )

    async def suggest(self, context: AdvisorContext) -> list[AdvisorSuggestion]:
        text = await self._complete(render_advisor_prompt(context))
        return parse_advisor_suggestions(text, default_challenge=context.challenge_name)

    async def _complete(self, prompt: str) -> str:
        if self._agent is None:
            await self.start()
        assert self._agent is not None

        async with self._agent.run_stream(
            prompt,
        ) as result:
            output = await result.get_output()
            return str(output).strip()

    async def stop(self) -> None:
        self._agent = None


async def run_azure_coordinator(
    settings: Settings,
    model_specs: list[str] | None = None,
    challenges_root: str = "challenges",
    no_submit: bool = False,
    coordinator_model: str | None = None,
    msg_port: int = 0,
    platform: CompetitionPlatformClient | None = None,
) -> dict[str, Any]:
    """Run the Azure advisor provider on top of the shared event loop."""
    ctfd, cost_tracker, deps = build_deps(
        settings=settings,
        model_specs=model_specs,
        challenges_root=challenges_root,
        no_submit=no_submit,
        platform=platform,
    )
    deps.msg_port = msg_port

    model_spec = _normalize_azure_coordinator_model(coordinator_model)
    advisor = AzureCoordinatorAdvisor(settings=settings, model_spec=model_spec)

    async def event_sink(message: str) -> None:
        logger.debug("Azure coordinator event: %s", message[:240])

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
