from __future__ import annotations

from typing import Any

from backend.control.state import ChallengeState, SwarmState
from backend.control.strategy_state import ChallengeStrategyState
from backend.control.working_memory import ChallengeWorkingMemory


def reduce_strategy_state(
    *,
    challenge: ChallengeState,
    swarm: SwarmState | None,
    memory: ChallengeWorkingMemory,
    result_record: dict[str, Any] | None,
    now: float,
    stall_seconds: int,
    bump_cooldown_seconds: int,
) -> ChallengeStrategyState:
    del result_record, bump_cooldown_seconds

    if challenge.status == "solved":
        return ChallengeStrategyState(
            challenge_name=challenge.challenge_name,
            stage="finalize",
            goal="完成收尾并保留题解结果",
            confidence=1.0,
            last_transition_reason="challenge solved",
        )

    if swarm and swarm.status == "running":
        stalled = swarm.last_progress_at is not None and now - swarm.last_progress_at >= stall_seconds
        if stalled and swarm.bump_count >= 3 and not memory.verified_findings:
            return ChallengeStrategyState(
                challenge_name=challenge.challenge_name,
                stage="blocked",
                goal="停止重复 bump，等待新证据",
                active_hypothesis=memory.open_hypotheses[0] if memory.open_hypotheses else "",
                blocked_reasons=["stalled after repeated bumps without new evidence"],
                next_actions=["wait_for_new_evidence"],
                confidence=0.2,
                last_transition_reason="stalled with repeated bumps",
            )

    if memory.open_hypotheses:
        active = memory.open_hypotheses[0]
        evidence = list(memory.verified_findings[:2]) or list(memory.useful_artifacts[:2])
        return ChallengeStrategyState(
            challenge_name=challenge.challenge_name,
            stage="exploit",
            goal=active,
            active_hypothesis=active,
            supporting_evidence=evidence,
            next_actions=[active],
            confidence=0.75,
            last_transition_reason="actionable hypothesis available",
        )

    return ChallengeStrategyState(
        challenge_name=challenge.challenge_name,
        stage="recon",
        goal="确认攻击面与利用入口",
        supporting_evidence=list(memory.useful_artifacts[:2]),
        next_actions=["collect_more_evidence"],
        confidence=0.4,
        last_transition_reason="insufficient actionable evidence",
    )
