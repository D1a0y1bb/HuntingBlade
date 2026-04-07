from backend.control.state import ChallengeState, SwarmState
from backend.control.working_memory import ChallengeWorkingMemory
from backend.control.strategy_reducer import reduce_strategy_state


def test_reduce_strategy_state_marks_exploit_for_actionable_hypothesis() -> None:
    challenge = ChallengeState(challenge_name="echo", status="running", category="pwn")
    swarm = SwarmState(
        challenge_name="echo",
        status="running",
        running_models=["azure/gpt-5.4"],
        last_progress_at=95.0,
        last_bump_at=0.0,
        bump_count=1,
    )
    memory = ChallengeWorkingMemory(challenge_name="echo")
    memory.open_hypotheses.append("Try format string offset 7")
    memory.verified_findings.append("exploit pattern: printf reaches user-controlled input")

    strategy = reduce_strategy_state(
        challenge=challenge,
        swarm=swarm,
        memory=memory,
        result_record=None,
        now=100.0,
        stall_seconds=60,
        bump_cooldown_seconds=30,
    )

    assert strategy.stage == "exploit"
    assert strategy.active_hypothesis == "Try format string offset 7"
    assert "format string" in strategy.goal


def test_reduce_strategy_state_marks_blocked_for_stalled_swarm_without_new_evidence() -> None:
    challenge = ChallengeState(challenge_name="rsa", status="running", category="crypto")
    swarm = SwarmState(
        challenge_name="rsa",
        status="running",
        running_models=["azure/gpt-5.4"],
        last_progress_at=0.0,
        last_bump_at=20.0,
        bump_count=3,
    )
    memory = ChallengeWorkingMemory(challenge_name="rsa")
    memory.open_hypotheses.append("Try common modulus attack")

    strategy = reduce_strategy_state(
        challenge=challenge,
        swarm=swarm,
        memory=memory,
        result_record=None,
        now=300.0,
        stall_seconds=60,
        bump_cooldown_seconds=30,
    )

    assert strategy.stage == "blocked"
    assert strategy.blocked_reasons
    assert strategy.confidence < 0.5
