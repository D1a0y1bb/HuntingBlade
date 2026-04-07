from backend.control.actions import BroadcastKnowledge, BumpSolver, SpawnSwarm
from backend.control.knowledge_store import KnowledgeStore
from backend.control.policy_engine import PolicyEngine
from backend.control.state import ChallengeState, CompetitionState, SwarmState
from backend.control.working_memory import WorkingMemoryStore


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
