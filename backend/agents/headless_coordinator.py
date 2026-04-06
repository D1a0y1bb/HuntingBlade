"""Headless coordinator — shared event loop without a top-level LLM coordinator."""

from __future__ import annotations

import logging
from typing import Any

from backend.agents.coordinator_loop import build_deps, run_event_loop
from backend.config import Settings
from backend.platforms.base import CompetitionPlatformClient

logger = logging.getLogger(__name__)


async def run_headless_coordinator(
    settings: Settings,
    model_specs: list[str] | None = None,
    challenges_root: str = "challenges",
    no_submit: bool = False,
    msg_port: int = 0,
    platform: CompetitionPlatformClient | None = None,
) -> dict[str, Any]:
    """Run the shared competition loop without a top-level LLM coordinator."""
    ctfd, cost_tracker, deps = build_deps(
        settings=settings,
        model_specs=model_specs,
        challenges_root=challenges_root,
        no_submit=no_submit,
        platform=platform,
    )
    deps.msg_port = msg_port

    async def turn_fn(message: str) -> None:
        logger.info("Headless event: %s", message[:400])

    return await run_event_loop(deps, ctfd, cost_tracker, turn_fn)
