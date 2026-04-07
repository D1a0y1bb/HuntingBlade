from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.control.actions import BroadcastKnowledge, BumpSolver, SpawnSwarm
from backend.control.knowledge_store import KnowledgeStore
from backend.control.state import CompetitionState, SwarmState
from backend.control.working_memory import WorkingMemoryStore

PolicyAction = SpawnSwarm | BumpSolver | BroadcastKnowledge


@dataclass
class PolicyEngine:
    max_concurrent_challenges: int
    bump_cooldown_seconds: int
    stall_seconds: int

    def plan_tick(
        self,
        *,
        competition: CompetitionState,
        working_memory_store: WorkingMemoryStore,
        knowledge_store: KnowledgeStore,
        now: float,
    ) -> list[PolicyAction]:
        actions: list[PolicyAction] = []

        spawn_target = self._next_spawn_target(competition)
        if spawn_target:
            actions.append(
                SpawnSwarm(
                    challenge_name=spawn_target,
                    priority=100,
                    reason="unsolved without active swarm",
                )
            )

        for challenge_name in sorted(competition.swarms):
            swarm = competition.swarms[challenge_name]
            if swarm.status != "running":
                continue
            if self._should_bump_swarm(swarm=swarm, now=now):
                memory = working_memory_store.get(challenge_name)
                if memory.open_hypotheses and swarm.running_models:
                    actions.append(
                        BumpSolver(
                            challenge_name=challenge_name,
                            model_spec=swarm.running_models[0],
                            guidance=f"Retry with open hypothesis: {memory.open_hypotheses[0]}",
                            reason="stalled swarm with reusable hypothesis",
                        )
                    )

            challenge = competition.challenges.get(challenge_name)
            if challenge is None:
                continue
            matched = knowledge_store.match(
                category=challenge.category,
                challenge_name=challenge_name,
                applied_ids=swarm.applied_knowledge_ids,
            )
            if not matched:
                continue
            entry = matched[0]
            actions.append(
                BroadcastKnowledge(
                    challenge_name=challenge_name,
                    message=entry.content,
                    source=entry.source_challenge,
                    knowledge_id=entry.id,
                )
            )

        return actions

    def apply_advisor_suggestions(
        self,
        *,
        suggestions: list[Any],
        competition: CompetitionState,
        now: float,
    ) -> list[PolicyAction]:
        actions: list[PolicyAction] = []
        for suggestion in suggestions:
            action_hint = str(getattr(suggestion, "action_hint", "")).strip().lower()
            challenge_name = str(getattr(suggestion, "challenge_name", "")).strip()
            if not challenge_name or challenge_name not in competition.swarms:
                continue

            swarm = competition.swarms[challenge_name]
            if swarm.status != "running":
                continue

            if action_hint == "bump_solver":
                if not self._should_bump_swarm(swarm=swarm, now=now):
                    continue
                model_spec = str(getattr(suggestion, "model_spec", "")).strip()
                if not model_spec and swarm.running_models:
                    model_spec = swarm.running_models[0]
                guidance = str(getattr(suggestion, "guidance", "")).strip()
                if not model_spec or not guidance:
                    continue
                reason = str(getattr(suggestion, "reason", "")).strip() or "advisor suggested bump"
                actions.append(
                    BumpSolver(
                        challenge_name=challenge_name,
                        model_spec=model_spec,
                        guidance=guidance,
                        reason=reason,
                    )
                )
                continue

            if action_hint == "broadcast_knowledge":
                knowledge_id = str(getattr(suggestion, "knowledge_id", "")).strip()
                if knowledge_id and knowledge_id in swarm.applied_knowledge_ids:
                    continue
                message = str(getattr(suggestion, "message", "")).strip()
                if not message:
                    message = str(getattr(suggestion, "guidance", "")).strip()
                if not message:
                    continue
                source = str(getattr(suggestion, "source", "")).strip() or "advisor"
                actions.append(
                    BroadcastKnowledge(
                        challenge_name=challenge_name,
                        message=message,
                        source=source,
                        knowledge_id=knowledge_id,
                    )
                )

        return actions

    def _next_spawn_target(self, competition: CompetitionState) -> str:
        if competition.active_swarm_count >= self.max_concurrent_challenges:
            return ""

        candidate_names = set(competition.known_challenges)
        candidate_names.update(competition.challenges.keys())
        for challenge_name in sorted(candidate_names):
            if challenge_name in competition.known_solved:
                continue
            challenge = competition.challenges.get(challenge_name)
            if challenge and challenge.status in {"solved", "skipped"}:
                continue
            if challenge_name in competition.swarms:
                continue
            return challenge_name
        return ""

    def _should_bump_swarm(self, *, swarm: SwarmState, now: float) -> bool:
        if swarm.status != "running":
            return False
        if swarm.last_progress_at is None:
            return False
        stalled = now - swarm.last_progress_at >= self.stall_seconds
        cooled = swarm.last_bump_at is None or now - swarm.last_bump_at >= self.bump_cooldown_seconds
        return stalled and cooled
