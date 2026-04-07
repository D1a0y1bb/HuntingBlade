from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChallengeWorkingMemory:
    challenge_name: str
    attempted_actions: list[str] = field(default_factory=list)
    failed_hypotheses: list[str] = field(default_factory=list)
    open_hypotheses: list[str] = field(default_factory=list)
    verified_findings: list[str] = field(default_factory=list)
    useful_artifacts: list[str] = field(default_factory=list)
    last_guidance: list[str] = field(default_factory=list)

    def to_summary(self) -> str:
        return "\n".join(
            [
                f"failed_hypotheses={self.failed_hypotheses[:3]}",
                f"open_hypotheses={self.open_hypotheses[:3]}",
                f"verified_findings={self.verified_findings[:3]}",
                f"useful_artifacts={self.useful_artifacts[:3]}",
                f"last_guidance={self.last_guidance[-2:]}",
            ]
        )

    def verified_findings_for_promotion(self) -> list[str]:
        return [finding.strip() for finding in self.verified_findings if finding.strip()]


class WorkingMemoryStore:
    def __init__(self) -> None:
        self._memories: dict[str, ChallengeWorkingMemory] = {}

    def get(self, challenge_name: str) -> ChallengeWorkingMemory:
        return self._memories.setdefault(challenge_name, ChallengeWorkingMemory(challenge_name))

    def apply_trace_events(self, challenge_name: str, events: list[Any]) -> ChallengeWorkingMemory:
        memory = self.get(challenge_name)
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "bump":
                insight = str(event.get("insights", "")).strip()
                if insight and insight not in memory.last_guidance:
                    memory.last_guidance.append(insight)
                for hypothesis in _extract_open_hypotheses(insight, allow_unprefixed=True):
                    if hypothesis not in memory.open_hypotheses:
                        memory.open_hypotheses.append(hypothesis)
            if event_type == "tool_result" and event.get("tool") == "submit_flag":
                tool = str(event.get("tool", "")).strip()
                result = str(event.get("result", "")).strip()
                if tool and result and _is_failed_submit_result(result):
                    summary = f"{tool} returned {result}"
                    if summary not in memory.failed_hypotheses:
                        memory.failed_hypotheses.append(summary)
            if event_type == "tool_result" and "/challenge/" in str(event.get("result", "")):
                artifact = str(event.get("result", "")).strip()
                if artifact and artifact not in memory.useful_artifacts:
                    memory.useful_artifacts.append(artifact)
            if event_type == "tool_result":
                result = str(event.get("result", ""))
                finding = _extract_verified_finding(result)
                if finding and finding not in memory.verified_findings:
                    memory.verified_findings.append(finding)
                for hypothesis in _extract_open_hypotheses(result):
                    if hypothesis not in memory.open_hypotheses:
                        memory.open_hypotheses.append(hypothesis)
        return memory


def _is_failed_submit_result(result: str) -> bool:
    normalized = result.strip().lower()
    if not normalized:
        return False

    # Ignore user-provided flag text when classifying result status.
    outside_quotes = re.sub(r'"[^"]*"', '""', normalized)

    failure_markers = (
        "incorrect",
        "rejected",
        "reject",
        "denied",
        "wrong answer",
        "not correct",
        "bad flag",
        "invalid flag",
        "submit failed",
        "submission failed",
    )
    if any(marker in outside_quotes for marker in failure_markers):
        return True

    if (
        re.search(r"\bcorrect\b", outside_quotes) is not None
        or "already solved" in outside_quotes
        or "accepted" in outside_quotes
        or "success" in outside_quotes
        or "confirmed" in outside_quotes
        or "您已提交了正确的flag" in normalized
        or "已提交了正确的flag" in normalized
    ):
        return False
    return False


def _extract_verified_finding(result: str) -> str:
    finding = result.strip()
    if not finding:
        return ""
    lowered = finding.lower()
    prefixes = ("platform rule:", "category rule:", "exploit pattern:")
    if any(marker in lowered for marker in prefixes):
        return finding
    return ""


def _extract_open_hypotheses(text: str, *, allow_unprefixed: bool = False) -> list[str]:
    if not text.strip():
        return []
    extracted: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-*").strip()
        if not line:
            continue
        normalized = re.sub(r"\s+", " ", line).strip()
        lowered = normalized.lower()
        if _extract_verified_finding(normalized):
            continue
        if lowered.startswith("candidate finding:") or lowered.startswith("next step:"):
            extracted.append(normalized)
            continue
        if allow_unprefixed and _is_plain_hypothesis_candidate(normalized):
            extracted.append(normalized)
    return extracted


def _is_plain_hypothesis_candidate(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 8:
        return False
    lowered = stripped.lower()
    if lowered in {"ok", "done", "continue", "retry", "none", "n/a"}:
        return False
    meta_prefixes = (
        "no sibling insights available",
        "retry with open hypothesis:",
    )
    if any(lowered.startswith(prefix) for prefix in meta_prefixes):
        return False
    actionable_prefixes = (
        "try ",
        "check ",
        "use ",
        "run ",
        "inspect ",
        "verify ",
        "test ",
        "probe ",
        "attempt ",
        "trace ",
        "dump ",
        "read ",
        "enumerate ",
    )
    if not any(lowered.startswith(prefix) for prefix in actionable_prefixes):
        return False
    return not re.fullmatch(r"[\W_]+", stripped)
