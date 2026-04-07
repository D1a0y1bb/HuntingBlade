from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


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
