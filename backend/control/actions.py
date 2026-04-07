from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpawnSwarm:
    challenge_name: str
    priority: int
    reason: str
    kind: str = field(init=False, default="spawn_swarm")


@dataclass(frozen=True)
class BumpSolver:
    challenge_name: str
    model_spec: str
    guidance: str
    reason: str
    kind: str = field(init=False, default="bump_solver")


@dataclass(frozen=True)
class BroadcastKnowledge:
    challenge_name: str
    message: str
    source: str
    knowledge_id: str = ""
    kind: str = field(init=False, default="broadcast_knowledge")


@dataclass(frozen=True)
class HoldChallenge:
    challenge_name: str
    reason: str
    retry_after_seconds: int
    kind: str = field(init=False, default="hold_challenge")


@dataclass(frozen=True)
class RetryChallenge:
    challenge_name: str
    reason: str
    kind: str = field(init=False, default="retry_challenge")


@dataclass(frozen=True)
class MarkChallengeSkipped:
    challenge_name: str
    reason: str
    kind: str = field(init=False, default="mark_challenge_skipped")
