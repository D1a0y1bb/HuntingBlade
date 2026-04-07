from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

StrategyStage = Literal["recon", "exploit", "verify", "finalize", "blocked"]


@dataclass(slots=True)
class ChallengeStrategyState:
    challenge_name: str
    stage: StrategyStage = "recon"
    goal: str = ""
    active_hypothesis: str = ""
    supporting_evidence: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    last_transition_reason: str = ""

    def to_summary(self) -> str:
        return "\n".join(
            [
                f"stage={self.stage}",
                f"goal={self.goal}",
                f"active_hypothesis={self.active_hypothesis}",
                f"supporting_evidence={self.supporting_evidence[:3]}",
                f"blocked_reasons={self.blocked_reasons[:3]}",
                f"next_actions={self.next_actions[:3]}",
                f"confidence={self.confidence:.2f}",
                f"last_transition_reason={self.last_transition_reason}",
            ]
        )


def fallback_strategy_state(challenge_name: str, *, reason: str = "") -> ChallengeStrategyState:
    return ChallengeStrategyState(
        challenge_name=challenge_name,
        stage="recon",
        confidence=0.0,
        last_transition_reason=reason or "fallback to recon",
    )
