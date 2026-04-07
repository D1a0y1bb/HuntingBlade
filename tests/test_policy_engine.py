from types import SimpleNamespace

from backend.control.actions import BroadcastKnowledge, BumpSolver, SpawnSwarm
from backend.control.knowledge_store import KnowledgeStore
from backend.control.policy_engine import PolicyEngine
from backend.control.state import ChallengeState, CompetitionState, SwarmState
from backend.control.strategy_state import ChallengeStrategyState
from backend.control.working_memory import WorkingMemoryStore
from backend.cost_tracker import CostTracker
from backend.deps import CoordinatorDeps


def test_policy_engine_spawns_unsolved_challenge_when_capacity_available() -> None:
    state = CompetitionState(
        known_challenges={"echo"},
        known_solved=set(),
        challenges={"echo": ChallengeState(challenge_name="echo", status="pending", category="pwn")},
        swarms={},
    )

    engine = PolicyEngine(max_concurrent_challenges=3, bump_cooldown_seconds=60, stall_seconds=120)
    actions = engine.plan_tick(
        competition=state,
        working_memory_store=WorkingMemoryStore(),
        knowledge_store=KnowledgeStore(),
        now=100.0,
    )

    assert actions == [SpawnSwarm(challenge_name="echo", priority=100, reason="unsolved without active swarm")]


def test_policy_engine_bumps_stalled_swarm_once_cooldown_expires() -> None:
    state = CompetitionState(
        challenges={"rsa": ChallengeState(challenge_name="rsa", status="running", category="crypto")},
        swarms={
            "rsa": SwarmState(
                challenge_name="rsa",
                status="running",
                running_models=["azure/gpt-5.4"],
                last_bump_at=0.0,
                last_progress_at=0.0,
            )
        },
    )
    memories = WorkingMemoryStore()
    memories.get("rsa").open_hypotheses.append("Try common modulus attack")

    engine = PolicyEngine(max_concurrent_challenges=3, bump_cooldown_seconds=30, stall_seconds=60)
    actions = engine.plan_tick(
        competition=state,
        working_memory_store=memories,
        knowledge_store=KnowledgeStore(),
        now=100.0,
    )

    assert actions == [
        BumpSolver(
            challenge_name="rsa",
            model_spec="azure/gpt-5.4",
            guidance="Retry with open hypothesis: Try common modulus attack",
            reason="stalled swarm with reusable hypothesis",
        )
    ]


def test_policy_engine_broadcasts_matched_knowledge_once_per_swarm() -> None:
    state = CompetitionState(
        known_challenges={"hatephp"},
        challenges={"hatephp": ChallengeState(challenge_name="hatephp", status="running", category="web")},
        swarms={
            "hatephp": SwarmState(
                challenge_name="hatephp",
                status="running",
                running_models=["azure/gpt-5.4"],
                applied_knowledge_ids=set(),
            )
        },
    )
    store = KnowledgeStore()
    entry = store.upsert(
        scope="category",
        kind="exploit_pattern",
        content="category rule: php phar deserialization first",
        evidence="confirmed in prior web challenge",
        confidence=0.9,
        source_challenge="older-web",
        applicability={"category": "web"},
    )

    engine = PolicyEngine(max_concurrent_challenges=3, bump_cooldown_seconds=60, stall_seconds=120)
    actions = engine.plan_tick(
        competition=state,
        working_memory_store=WorkingMemoryStore(),
        knowledge_store=store,
        now=100.0,
    )

    assert actions == [
        BroadcastKnowledge(
            challenge_name="hatephp",
            message="category rule: php phar deserialization first",
            source="older-web",
            knowledge_id=entry.id,
        )
    ]


def test_policy_engine_prefers_strategy_active_hypothesis_over_raw_memory() -> None:
    state = CompetitionState(
        challenges={"rsa": ChallengeState(challenge_name="rsa", status="running", category="crypto")},
        swarms={
            "rsa": SwarmState(
                challenge_name="rsa",
                status="running",
                running_models=["azure/gpt-5.4"],
                last_bump_at=0.0,
                last_progress_at=0.0,
            )
        },
    )
    memories = WorkingMemoryStore()
    memories.get("rsa").open_hypotheses.append("Try wrong path first")
    strategies = {
        "rsa": ChallengeStrategyState(
            challenge_name="rsa",
            stage="exploit",
            active_hypothesis="Try common modulus attack",
            goal="Try common modulus attack",
            confidence=0.8,
        )
    }

    engine = PolicyEngine(max_concurrent_challenges=3, bump_cooldown_seconds=30, stall_seconds=60)
    actions = engine.plan_tick(
        competition=state,
        working_memory_store=memories,
        knowledge_store=KnowledgeStore(),
        strategy_states=strategies,
        now=100.0,
    )

    assert actions[0].guidance == "Retry with open hypothesis: Try common modulus attack"


def test_policy_engine_skips_bump_for_low_confidence_blocked_strategy() -> None:
    state = CompetitionState(
        challenges={"rsa": ChallengeState(challenge_name="rsa", status="running", category="crypto")},
        swarms={
            "rsa": SwarmState(
                challenge_name="rsa",
                status="running",
                running_models=["azure/gpt-5.4"],
                last_bump_at=0.0,
                last_progress_at=0.0,
            )
        },
    )
    strategies = {
        "rsa": ChallengeStrategyState(
            challenge_name="rsa",
            stage="blocked",
            active_hypothesis="Try common modulus attack",
            goal="Stop retrying without new evidence",
            confidence=0.2,
            blocked_reasons=["stalled after repeated bumps"],
        )
    }

    engine = PolicyEngine(max_concurrent_challenges=3, bump_cooldown_seconds=30, stall_seconds=60)
    actions = engine.plan_tick(
        competition=state,
        working_memory_store=WorkingMemoryStore(),
        knowledge_store=KnowledgeStore(),
        strategy_states=strategies,
        now=100.0,
    )

    assert actions == []


def test_policy_engine_does_not_broadcast_knowledge_for_non_running_swarm() -> None:
    store = KnowledgeStore()
    store.upsert(
        scope="category",
        kind="exploit_pattern",
        content="category rule: web: try phar first",
        evidence="confirmed in prior web challenge",
        confidence=0.8,
        source_challenge="older-web",
        applicability={"category": "web"},
    )
    engine = PolicyEngine(max_concurrent_challenges=3, bump_cooldown_seconds=60, stall_seconds=120)

    for swarm_status in ("finished", "cancelled"):
        state = CompetitionState(
            known_challenges={"hatephp"},
            known_solved=set(),
            challenges={"hatephp": ChallengeState(challenge_name="hatephp", status="pending", category="web")},
            swarms={
                "hatephp": SwarmState(
                    challenge_name="hatephp",
                    status=swarm_status,
                    running_models=[],
                    applied_knowledge_ids=set(),
                )
            },
        )
        actions = engine.plan_tick(
            competition=state,
            working_memory_store=WorkingMemoryStore(),
            knowledge_store=store,
            now=100.0,
        )

        assert actions == []


def test_policy_engine_does_not_spawn_when_terminal_swarm_already_exists() -> None:
    for terminal_status in ("finished", "cancelled", "error"):
        state = CompetitionState(
            known_challenges={"echo"},
            known_solved=set(),
            challenges={"echo": ChallengeState(challenge_name="echo", status="pending", category="pwn")},
            swarms={
                "echo": SwarmState(
                    challenge_name="echo",
                    status=terminal_status,
                )
            },
        )
        engine = PolicyEngine(max_concurrent_challenges=3, bump_cooldown_seconds=60, stall_seconds=120)

        actions = engine.plan_tick(
            competition=state,
            working_memory_store=WorkingMemoryStore(),
            knowledge_store=KnowledgeStore(),
            now=100.0,
        )

        assert actions == []


def test_policy_engine_advisor_bump_requires_running_stalled_and_cooled_swarm() -> None:
    engine = PolicyEngine(max_concurrent_challenges=3, bump_cooldown_seconds=30, stall_seconds=60)
    suggestions = [
        SimpleNamespace(
            action_hint="bump_solver",
            challenge_name="rsa-running-not-stalled",
            model_spec="azure/gpt-5.4",
            guidance="Try gcd on shared modulus",
            reason="advisor bump",
        ),
        SimpleNamespace(
            action_hint="bump_solver",
            challenge_name="rsa-finished",
            model_spec="azure/gpt-5.4",
            guidance="Try gcd on shared modulus",
            reason="advisor bump",
        ),
        SimpleNamespace(
            action_hint="bump_solver",
            challenge_name="rsa-running-stalled",
            model_spec="azure/gpt-5.4",
            guidance="Try common modulus attack",
            reason="advisor bump",
        ),
    ]
    competition = CompetitionState(
        swarms={
            "rsa-running-not-stalled": SwarmState(
                challenge_name="rsa-running-not-stalled",
                status="running",
                running_models=["azure/gpt-5.4"],
                last_bump_at=0.0,
                last_progress_at=90.0,
            ),
            "rsa-finished": SwarmState(
                challenge_name="rsa-finished",
                status="finished",
                running_models=["azure/gpt-5.4"],
                last_bump_at=0.0,
                last_progress_at=0.0,
            ),
            "rsa-running-stalled": SwarmState(
                challenge_name="rsa-running-stalled",
                status="running",
                running_models=["azure/gpt-5.4"],
                last_bump_at=0.0,
                last_progress_at=0.0,
            ),
        }
    )

    actions = engine.apply_advisor_suggestions(
        suggestions=suggestions,
        competition=competition,
        now=100.0,
    )

    assert actions == [
        BumpSolver(
            challenge_name="rsa-running-stalled",
            model_spec="azure/gpt-5.4",
            guidance="Try common modulus attack",
            reason="advisor bump",
        )
    ]


def test_policy_engine_advisor_broadcast_skips_non_running_and_applied_knowledge() -> None:
    engine = PolicyEngine(max_concurrent_challenges=3, bump_cooldown_seconds=30, stall_seconds=60)
    suggestions = [
        SimpleNamespace(
            action_hint="broadcast_knowledge",
            challenge_name="web-finished",
            message="use php filters first",
            source="advisor",
            knowledge_id="k-finished",
        ),
        SimpleNamespace(
            action_hint="broadcast_knowledge",
            challenge_name="web-running",
            message="repeat old knowledge",
            source="advisor",
            knowledge_id="k-used",
        ),
        SimpleNamespace(
            action_hint="broadcast_knowledge",
            challenge_name="web-running",
            message="fresh knowledge",
            source="advisor",
            knowledge_id="k-fresh",
        ),
    ]
    competition = CompetitionState(
        swarms={
            "web-finished": SwarmState(
                challenge_name="web-finished",
                status="finished",
                running_models=[],
                applied_knowledge_ids=set(),
            ),
            "web-running": SwarmState(
                challenge_name="web-running",
                status="running",
                running_models=["azure/gpt-5.4"],
                applied_knowledge_ids={"k-used"},
            ),
        }
    )

    actions = engine.apply_advisor_suggestions(
        suggestions=suggestions,
        competition=competition,
        now=100.0,
    )

    assert actions == [
        BroadcastKnowledge(
            challenge_name="web-running",
            message="fresh knowledge",
            source="advisor",
            knowledge_id="k-fresh",
        )
    ]


def test_coordinator_deps_syncs_policy_engine_concurrency_with_override() -> None:
    deps = CoordinatorDeps(
        ctfd=SimpleNamespace(),
        cost_tracker=CostTracker(),
        settings=SimpleNamespace(),
        max_concurrent_challenges=4,
    )

    assert deps.max_concurrent_challenges == 4
    assert deps.policy_engine.max_concurrent_challenges == 4


def test_coordinator_deps_respects_explicit_policy_engine_instance() -> None:
    explicit_engine = PolicyEngine(max_concurrent_challenges=99, bump_cooldown_seconds=15, stall_seconds=45)

    deps = CoordinatorDeps(
        ctfd=SimpleNamespace(),
        cost_tracker=CostTracker(),
        settings=SimpleNamespace(),
        max_concurrent_challenges=4,
        policy_engine=explicit_engine,
    )

    assert deps.policy_engine is explicit_engine
    assert deps.policy_engine.max_concurrent_challenges == 99
