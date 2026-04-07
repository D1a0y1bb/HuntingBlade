from backend.control.working_memory import WorkingMemoryStore, _is_failed_submit_result


def test_working_memory_dedupes_repeated_failed_hypothesis() -> None:
    store = WorkingMemoryStore()
    store.apply_trace_events(
        challenge_name="echo",
        events=[
            {"type": "tool_result", "tool": "submit_flag", "result": "INCORRECT"},
            {"type": "tool_result", "tool": "submit_flag", "result": "INCORRECT"},
            {"type": "bump", "insights": "Try format string offset 6"},
            {"type": "bump", "insights": "Try format string offset 6"},
            {"type": "bump", "insights": "platform rule: keep this as verified finding, not hypothesis"},
        ],
    )

    memory = store.get("echo")

    assert memory.failed_hypotheses == ["submit_flag returned INCORRECT"]
    assert memory.last_guidance == [
        "Try format string offset 6",
        "platform rule: keep this as verified finding, not hypothesis",
    ]
    assert memory.open_hypotheses == ["Try format string offset 6"]


def test_working_memory_keeps_verified_findings_and_artifacts() -> None:
    store = WorkingMemoryStore()
    store.apply_trace_events(
        challenge_name="rsa",
        events=[
            {"type": "tool_result", "tool": "read_file", "result": "/challenge/distfiles/pub.pem"},
            {"type": "tool_result", "tool": "bash", "result": "platform rule: Lingxu env题需要先 begin/run/addr"},
            {"type": "flag_confirmed", "tool": "submit_flag"},
        ],
    )

    memory = store.get("rsa")

    assert "/challenge/distfiles/pub.pem" in memory.useful_artifacts
    assert "platform rule: Lingxu env题需要先 begin/run/addr" in memory.verified_findings


def test_working_memory_extracts_open_hypotheses_from_trace_candidates() -> None:
    store = WorkingMemoryStore()
    store.apply_trace_events(
        challenge_name="heapnote",
        events=[
            {
                "type": "bump",
                "insights": "Candidate finding: libc leak from unsorted bin\nnext step: try __free_hook overwrite",
            },
            {
                "type": "tool_result",
                "tool": "bash",
                "result": "candidate finding: tcache poison primitive seems controllable",
            },
            {
                "type": "tool_result",
                "tool": "bash",
                "result": "next step: craft double-free sequence and re-run",
            },
            {
                "type": "tool_result",
                "tool": "bash",
                "result": "platform rule: Lingxu env题需要先 begin/run/addr",
            },
        ],
    )

    memory = store.get("heapnote")

    assert memory.open_hypotheses == [
        "Candidate finding: libc leak from unsorted bin",
        "next step: try __free_hook overwrite",
        "candidate finding: tcache poison primitive seems controllable",
        "next step: craft double-free sequence and re-run",
    ]
    assert "platform rule: Lingxu env题需要先 begin/run/addr" not in memory.open_hypotheses
    assert "platform rule: Lingxu env题需要先 begin/run/addr" in memory.verified_findings


def test_working_memory_filters_unprefixed_bump_meta_guidance() -> None:
    store = WorkingMemoryStore()
    store.apply_trace_events(
        challenge_name="legacy-smoke",
        events=[
            {"type": "bump", "insights": "No sibling insights available yet."},
            {
                "type": "bump",
                "insights": "Retry with open hypothesis: candidate finding: heap metadata corruption",
            },
            {"type": "bump", "insights": "Try format string offset 6"},
            {"type": "bump", "insights": "Check argv parsing"},
            {"type": "bump", "insights": "candidate finding: can leak stack canary"},
            {"type": "bump", "insights": "next step: brute-force low 12 bits"},
            {"type": "bump", "insights": "platform rule: keep this as verified finding, not hypothesis"},
            {"type": "bump", "insights": "category rule: heap challenge prefers uaf pivot"},
            {"type": "bump", "insights": "exploit pattern: unlink-once then overlap chunks"},
        ],
    )

    memory = store.get("legacy-smoke")

    assert "No sibling insights available yet." not in memory.open_hypotheses
    assert (
        "Retry with open hypothesis: candidate finding: heap metadata corruption"
        not in memory.open_hypotheses
    )
    assert "Try format string offset 6" in memory.open_hypotheses
    assert "Check argv parsing" in memory.open_hypotheses
    assert "candidate finding: can leak stack canary" in memory.open_hypotheses
    assert "next step: brute-force low 12 bits" in memory.open_hypotheses
    assert "platform rule: keep this as verified finding, not hypothesis" not in memory.open_hypotheses
    assert "category rule: heap challenge prefers uaf pivot" not in memory.open_hypotheses
    assert "exploit pattern: unlink-once then overlap chunks" not in memory.open_hypotheses


def test_working_memory_ignores_successful_submit_flag_results() -> None:
    store = WorkingMemoryStore()
    store.apply_trace_events(
        challenge_name="web",
        events=[
            {"type": "tool_result", "tool": "submit_flag", "result": "INCORRECT"},
            {"type": "tool_result", "tool": "submit_flag", "result": "CORRECT"},
            {"type": "tool_result", "tool": "submit_flag", "result": "accepted"},
        ],
    )

    memory = store.get("web")

    assert memory.failed_hypotheses == ["submit_flag returned INCORRECT"]


def test_working_memory_ignores_invalid_event_shapes() -> None:
    store = WorkingMemoryStore()
    store.apply_trace_events(
        challenge_name="misc",
        events=[
            {"type": "tool_result", "tool": "submit_flag", "result": "INCORRECT"},
            "bad-line",
            123,
            None,
            {"type": "bump", "insights": "Check argv parsing"},
        ],
    )

    memory = store.get("misc")
    assert memory.failed_hypotheses == ["submit_flag returned INCORRECT"]
    assert memory.last_guidance == ["Check argv parsing"]


def test_is_failed_submit_result_ignores_failure_words_inside_successful_flag_display() -> None:
    assert _is_failed_submit_result('CORRECT — "flag{wrong_turn}" accepted.') is False
    assert (
        _is_failed_submit_result(
            'ALREADY SOLVED — "flag{invalid-but-real}" accepted. 您已提交了正确的Flag'
        )
        is False
    )
    assert _is_failed_submit_result('CORRECT — "flag{failed_once_before}" accepted.') is False
    assert _is_failed_submit_result('INCORRECT — "flag{bad}" rejected.') is True
