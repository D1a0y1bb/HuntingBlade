from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from backend.deps import CoordinatorDeps
    from backend.poller import CompetitionPoller


@dataclass
class ChallengeState:
    challenge_name: str
    status: Literal["unknown", "pending", "running", "solved", "skipped", "error"] = "unknown"
    category: str = ""
    value: float = 0.0
    requires_env_start: bool = False
    unsupported_reason: str = ""
    last_materialized_at: float | None = None


@dataclass
class SwarmState:
    challenge_name: str
    status: Literal["idle", "running", "finished", "cancelled", "error"] = "idle"
    running_models: list[str] = field(default_factory=list)
    last_bump_at: float | None = None
    bump_count: int = 0
    last_progress_at: float | None = None
    last_error: str = ""
    step_count: int = 0
    cost_usd: float = 0.0
    winner_model: str = ""
    applied_knowledge_ids: set[str] = field(default_factory=set)


@dataclass
class CompetitionState:
    known_challenges: set[str] = field(default_factory=set)
    known_solved: set[str] = field(default_factory=set)
    challenges: dict[str, ChallengeState] = field(default_factory=dict)
    swarms: dict[str, SwarmState] = field(default_factory=dict)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    global_cost_usd: float = 0.0
    last_poll_at: float | None = None
    operator_messages: list[str] = field(default_factory=list)

    @property
    def active_swarm_count(self) -> int:
        return sum(1 for swarm in self.swarms.values() if swarm.status == "running")


def _solver_step_count(solver: Any) -> int:
    step_count = getattr(solver, "_step_count", None)
    if step_count is None:
        step_count = getattr(solver, "step_count", 0)
    if isinstance(step_count, list):
        return int(step_count[0]) if step_count else 0
    if isinstance(step_count, tuple):
        return int(step_count[0]) if step_count else 0
    try:
        return int(step_count)
    except (TypeError, ValueError):
        return 0


def _solver_cost_usd(solver: Any, deps: CoordinatorDeps) -> float:
    agent_name = getattr(solver, "agent_name", "")
    if agent_name:
        usage = deps.cost_tracker.by_agent.get(agent_name)
        if usage:
            return float(usage.cost_usd)
    return 0.0


def _status_from_result(record: dict[str, Any] | None) -> str | None:
    if not record:
        return None
    solve_status = str(record.get("solve_status", "")).lower()
    if solve_status in {"cancelled"}:
        return "cancelled"
    if solve_status in {"error", "quota_error"}:
        return "error"
    if solve_status in {"flag_found", "gave_up", "no_result", "skipped"}:
        return "finished"
    return None


def build_runtime_state_snapshot(
    deps: CoordinatorDeps,
    poller: CompetitionPoller,
    now: float,
) -> CompetitionState:
    previous = deps.runtime_state.swarms if deps.runtime_state else {}
    terminal_names: set[str] = {
        name for name, swarm in previous.items() if swarm.status in {"finished", "cancelled", "error"}
    }
    terminal_names.update(
        {
            name
            for name, record in deps.results.items()
            if _status_from_result(record) in {"finished", "cancelled", "error"}
        }
    )
    swarm_names = set(deps.swarms)
    swarm_names.update(terminal_names)

    swarms: dict[str, SwarmState] = {}
    for name in swarm_names:
        swarm = deps.swarms.get(name)
        result_status = _status_from_result(deps.results.get(name))
        prior_state = previous.get(name)
        status = prior_state.status if prior_state else "idle"

        if swarm is not None:
            task = deps.swarm_tasks.get(name)
            if task is not None:
                status = result_status or ("finished" if task.done() else "running")
            else:
                if swarm.cancel_event.is_set():
                    if result_status:
                        status = result_status
                    elif prior_state and prior_state.status in {"finished", "cancelled", "error"}:
                        status = prior_state.status
                    else:
                        status = "cancelled"
                else:
                    status = result_status or "running"
        else:
            if result_status:
                status = result_status
            elif prior_state and prior_state.status in {"finished", "cancelled", "error"}:
                status = prior_state.status
            else:
                continue

        if swarm is not None:
            step_count = 0
            cost_usd = 0.0
            for solver in swarm.solvers.values():
                step_count += _solver_step_count(solver)
                cost_usd += _solver_cost_usd(solver, deps)
            running_models = sorted(swarm.solvers.keys()) if status == "running" else []
        elif prior_state:
            step_count = prior_state.step_count
            cost_usd = prior_state.cost_usd
            running_models = [] if status != "running" else list(prior_state.running_models)
        else:
            step_count = 0
            cost_usd = 0.0
            running_models = []

        swarms[name] = SwarmState(
            challenge_name=name,
            status=status,
            running_models=running_models,
            step_count=step_count,
            cost_usd=cost_usd,
        )

    return CompetitionState(
        known_challenges=set(poller.known_challenges),
        known_solved=set(poller.known_solved),
        swarms=swarms,
        results=dict(deps.results),
        global_cost_usd=deps.cost_tracker.total_cost_usd,
        last_poll_at=now,
    )
