"""Azure API coordinator — shared event loop plus Pydantic AI over `.env` settings only."""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic_ai import Agent, RunContext

from backend.agents.claude_coordinator import COORDINATOR_PROMPT
from backend.agents.coordinator_core import (
    do_broadcast,
    do_bump_agent,
    do_check_swarm_status,
    do_fetch_challenges,
    do_get_solve_status,
    do_kill_swarm,
    do_read_solver_trace,
    do_spawn_swarm,
    do_submit_flag,
)
from backend.agents.coordinator_loop import build_deps, run_event_loop
from backend.config import Settings
from backend.deps import CoordinatorDeps
from backend.models import (
    model_id_from_spec,
    provider_from_spec,
    resolve_model,
    resolve_model_settings,
)
from backend.platforms.base import CompetitionPlatformClient

logger = logging.getLogger(__name__)


async def fetch_challenges(ctx: RunContext[CoordinatorDeps]) -> str:
    """List all challenges with category, points, solve count, and status."""
    return await do_fetch_challenges(ctx.deps)


async def get_solve_status(ctx: RunContext[CoordinatorDeps]) -> str:
    """Check which challenges are solved and which swarms are running."""
    return await do_get_solve_status(ctx.deps)


async def spawn_swarm(ctx: RunContext[CoordinatorDeps], challenge_name: str) -> str:
    """Launch all solver models on a challenge."""
    return await do_spawn_swarm(ctx.deps, challenge_name)


async def check_swarm_status(ctx: RunContext[CoordinatorDeps], challenge_name: str) -> str:
    """Get per-agent progress for a swarm."""
    return await do_check_swarm_status(ctx.deps, challenge_name)


async def submit_flag(ctx: RunContext[CoordinatorDeps], challenge_name: str, flag: str) -> str:
    """Submit a flag to the platform."""
    return await do_submit_flag(ctx.deps, challenge_name, flag)


async def kill_swarm(ctx: RunContext[CoordinatorDeps], challenge_name: str) -> str:
    """Cancel all agents for a challenge."""
    return await do_kill_swarm(ctx.deps, challenge_name)


async def bump_agent(
    ctx: RunContext[CoordinatorDeps], challenge_name: str, model_spec: str, insights: str
) -> str:
    """Send targeted technical guidance to a solver."""
    return await do_bump_agent(ctx.deps, challenge_name, model_spec, insights)


async def broadcast(ctx: RunContext[CoordinatorDeps], challenge_name: str, message: str) -> str:
    """Broadcast a strategic hint to all solvers on a challenge."""
    return await do_broadcast(ctx.deps, challenge_name, message)


async def read_solver_trace(
    ctx: RunContext[CoordinatorDeps], challenge_name: str, model_spec: str, last_n: int = 20
) -> str:
    """Read recent trace events from a specific solver."""
    return await do_read_solver_trace(ctx.deps, challenge_name, model_spec, last_n)


def _normalize_azure_coordinator_model(spec: str | None) -> str:
    if not spec:
        return "azure/gpt-5.4"
    if "/" not in spec:
        return f"azure/{spec}"
    if not spec.startswith("azure/"):
        raise ValueError("azure coordinator 只能使用 azure/<model> 或裸模型名")
    return spec


class AzureCoordinator:
    """Coordinator backed by the Azure/OpenAI-compatible `.env` channel."""

    def __init__(self, deps: CoordinatorDeps, settings: Settings, model_spec: str) -> None:
        self.deps = deps
        self.settings = settings
        self.model_spec = model_spec
        self.model_id = model_id_from_spec(model_spec)
        self.agent_name = f"coordinator/{self.model_id}"
        self._agent: Agent[CoordinatorDeps, str] | None = None
        self._messages: list[Any] = []

    async def start(self) -> None:
        model = resolve_model(self.model_spec, self.settings)
        model_settings = resolve_model_settings(self.model_spec)
        self._agent = Agent(
            model,
            deps_type=CoordinatorDeps,
            system_prompt=COORDINATOR_PROMPT,
            model_settings=model_settings,
            tools=[
                fetch_challenges,
                get_solve_status,
                spawn_swarm,
                check_swarm_status,
                submit_flag,
                kill_swarm,
                bump_agent,
                broadcast,
                read_solver_trace,
            ],
        )
        logger.info(
            "Azure coordinator started (model_spec=%s, model_id=%s)",
            self.model_spec,
            self.model_id,
        )

    async def turn(self, message: str) -> None:
        if self._agent is None:
            await self.start()
        assert self._agent is not None

        t0 = time.monotonic()
        try:
            async with self._agent.run_stream(
                message,
                deps=self.deps,
                message_history=self._messages or None,
            ) as result:
                output = await result.get_output()
                usage = result.usage()
                self._messages = result.all_messages()
        except Exception:
            logger.warning("Azure coordinator turn failed", exc_info=True)
            return

        duration = time.monotonic() - t0
        self.deps.cost_tracker.record(
            self.agent_name,
            usage,
            self.model_id,
            provider_spec=provider_from_spec(self.model_spec),
            duration_seconds=duration,
        )

        output = output.strip()
        if output:
            logger.info("Azure coordinator turn done: %s", output[:400])
        else:
            logger.info("Azure coordinator turn done with tool-only output")

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
    """Run the Azure API coordinator with the shared event loop."""
    ctfd, cost_tracker, deps = build_deps(
        settings=settings,
        model_specs=model_specs,
        challenges_root=challenges_root,
        no_submit=no_submit,
        platform=platform,
    )
    deps.msg_port = msg_port

    model_spec = _normalize_azure_coordinator_model(coordinator_model)
    coordinator = AzureCoordinator(deps, settings=settings, model_spec=model_spec)
    await coordinator.start()

    async def turn_fn(message: str) -> None:
        await coordinator.turn(message)

    try:
        return await run_event_loop(deps, ctfd, cost_tracker, turn_fn)
    finally:
        await coordinator.stop()
