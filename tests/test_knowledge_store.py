from backend.control.knowledge_store import KnowledgeStore
from backend.control.working_memory import ChallengeWorkingMemory


def test_promote_verified_platform_rule_from_memory() -> None:
    store = KnowledgeStore()
    memory = ChallengeWorkingMemory(
        challenge_name="hatephp",
        verified_findings=["platform rule: Lingxu env题需要先 begin/run/addr"],
    )

    promoted = store.promote_from_memory(
        challenge_name="hatephp",
        category="web",
        memory=memory,
    )

    assert len(promoted) == 1
    assert promoted[0].scope == "platform"
    assert promoted[0].kind == "platform_rule"


def test_match_returns_category_knowledge_and_skips_applied_entry() -> None:
    store = KnowledgeStore()
    entry = store.upsert(
        scope="category",
        kind="exploit_pattern",
        content="php phar deserialization first",
        evidence="confirmed in two PHP challenges",
        confidence=0.9,
        source_challenge="hatephp",
        applicability={"category": "web"},
    )

    matched = store.match(
        category="web",
        challenge_name="web2",
        applied_ids={entry.id},
    )

    assert matched == []
