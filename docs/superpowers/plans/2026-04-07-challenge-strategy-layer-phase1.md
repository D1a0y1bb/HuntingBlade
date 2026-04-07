# Challenge Strategy Layer Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有显式控制面上新增 `Challenge Strategy Layer`，让共享控制链路从 `Working Memory -> Policy` 升级为 `Working Memory -> Strategy State -> Policy`，并把 `strategy_summary` 接入 advisor。

**Architecture:** 第一阶段只新增两个纯逻辑模块：`strategy_state.py` 与 `strategy_reducer.py`，由 reducer 依据 runtime state、working memory 与结果状态归纳单题策略状态。第二阶段把 `CoordinatorDeps` 与 `coordinator_loop` 接线成“刷新策略状态 -> 生成策略摘要 -> policy/advisor 消费”；第三阶段让 `PolicyEngine` 和 advisor prompt 都优先依赖 strategy 层，而不是直接依赖零散 memory 字符串。

**Tech Stack:** Python 3.14, dataclasses, asyncio, pytest, Ruff

## 执行状态

- `Task 1` 已完成：新增 `backend/control/strategy_state.py` 与 `backend/control/strategy_reducer.py`，并补 `tests/test_strategy_reducer.py`。
- `Task 2` 已完成：`CoordinatorDeps` 已新增 `strategy_states`，`coordinator_loop` 已接入 `_refresh_strategy_states()` 与 `_summarize_strategy()`。
- `Task 3` 已完成：`PolicyEngine.plan_tick()` 已优先消费 `strategy_states`，可用 `active_hypothesis` 驱动 bump，并在低置信度 `blocked` 状态下抑制 bump。
- `Task 4` 已完成：`AdvisorContext` 与 prompt 已接入 `strategy_summary`，`README` 已补 `Strategy Layer` 架构说明。
- `Task 5` 已完成：已跑 `uv run pytest -q` 与 `uv run ruff check backend tests`；当前工作区除用户原有未跟踪目录 `writeups/` 外，不包含额外无关改动。

---

## File Structure

- `backend/control/strategy_state.py`
  责任：定义 `ChallengeStrategyState`、稳定的 `to_summary()`、以及 fallback/factory 帮助函数。
- `backend/control/strategy_reducer.py`
  责任：根据 `ChallengeState / SwarmState / ChallengeWorkingMemory / result` 归纳出结构化策略状态。
- `backend/control/__init__.py`
  责任：导出 `ChallengeStrategyState` 供控制面其他模块稳定引用。
- `backend/deps.py`
  责任：为 coordinator runtime 增加 `strategy_states` 存储。
- `backend/control/policy_engine.py`
  责任：从“直接读 memory”升级为“优先读 strategy state，再决定 bump / broadcast”。
- `backend/control/advisor.py`
  责任：给 `AdvisorContext` 增加 `strategy_summary` 并接入 prompt 渲染。
- `backend/agents/coordinator_loop.py`
  责任：刷新 `strategy_states`、提供 `_summarize_strategy()`、把 summary 传给 advisor，并在 `plan_tick()` 中传入 strategy 状态。
- `tests/test_strategy_reducer.py`
  责任：验证 reducer 与 `ChallengeStrategyState` 的阶段归纳和摘要输出。
- `tests/test_policy_engine.py`
  责任：验证 policy 使用 strategy 状态而非直接依赖 `open_hypotheses[0]`。
- `tests/test_coordinator_platform_flow.py`
  责任：验证 coordinator loop 能刷新 strategy 状态并把 `strategy_summary` 传给 advisor。
- `README.md`
  责任：在实现完成后补一小段架构说明，把 `Strategy Layer` 加到控制链路里。

---

### Task 1: 新增 `ChallengeStrategyState` 与 `StrategyReducer`

**Files:**
- Create: `backend/control/strategy_state.py`
- Create: `backend/control/strategy_reducer.py`
- Modify: `backend/control/__init__.py`
- Create: `tests/test_strategy_reducer.py`

- [ ] **Step 1: 先写 reducer 的失败测试**

```python
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
```

- [ ] **Step 2: 跑测试，确认新模块尚不存在**

Run: `uv run pytest tests/test_strategy_reducer.py -q`  
Expected: FAIL with `ModuleNotFoundError` for `backend.control.strategy_reducer`

- [ ] **Step 3: 写最小实现，落 `ChallengeStrategyState` 和 reducer**

```python
# backend/control/strategy_state.py
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
```

```python
# backend/control/strategy_reducer.py
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
    if challenge.status == "solved":
        return ChallengeStrategyState(
            challenge_name=challenge.challenge_name,
            stage="finalize",
            goal="完成收尾并保留题解结果",
            confidence=1.0,
            last_transition_reason="challenge solved",
        )

    if swarm and swarm.status == "running":
        stalled = (
            swarm.last_progress_at is not None and now - swarm.last_progress_at >= stall_seconds
        )
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
```

```python
# backend/control/__init__.py
from .strategy_state import ChallengeStrategyState

__all__ = [
    ...,
    "ChallengeStrategyState",
]
```

- [ ] **Step 4: 运行 reducer 测试，确认新对象通过**

Run: `uv run pytest tests/test_strategy_reducer.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/control/__init__.py backend/control/strategy_state.py backend/control/strategy_reducer.py tests/test_strategy_reducer.py
git commit -m "feat: 增加单题策略状态归纳器"
```

### Task 2: 把 `strategy_states` 接入 `deps` 与 `coordinator_loop`

**Files:**
- Modify: `backend/deps.py`
- Modify: `backend/agents/coordinator_loop.py`
- Modify: `tests/test_coordinator_platform_flow.py`

- [ ] **Step 1: 先写 loop 接线的失败测试**

```python
def test_refresh_strategy_states_populates_strategy_summary_for_running_challenge() -> None:
    from backend.control.strategy_state import ChallengeStrategyState

    deps = CoordinatorDeps(
        ctfd=FakePlatform(),
        cost_tracker=CostTracker(),
        settings=make_settings(),
        model_specs=["azure/gpt-5.4"],
    )
    deps.runtime_state = CompetitionState(
        challenges={
            "echo": ChallengeState(challenge_name="echo", status="running", category="pwn")
        },
        swarms={
            "echo": SwarmState(
                challenge_name="echo",
                status="running",
                running_models=["azure/gpt-5.4"],
                last_progress_at=0.0,
            )
        },
    )
    deps.working_memory_store.get("echo").open_hypotheses.append("Try format string offset 7")

    coordinator_loop._refresh_strategy_states(deps, now=120.0)

    assert deps.strategy_states["echo"].stage == "exploit"
    assert "offset 7" in coordinator_loop._summarize_strategy(deps, "echo")
```

- [ ] **Step 2: 运行测试，确认当前没有 strategy 刷新链路**

Run: `uv run pytest tests/test_coordinator_platform_flow.py -q -k "refresh_strategy_states_populates_strategy_summary"`  
Expected: FAIL with `AttributeError` for `_refresh_strategy_states` or missing `strategy_states`

- [ ] **Step 3: 在 `CoordinatorDeps` 中加入策略状态存储**

```python
# backend/deps.py
from backend.control.strategy_state import ChallengeStrategyState


@dataclass
class CoordinatorDeps:
    ...
    strategy_states: dict[str, ChallengeStrategyState] = field(default_factory=dict)
```

- [ ] **Step 4: 在 loop 中实现刷新与摘要 helper**

```python
# backend/agents/coordinator_loop.py
from backend.control.strategy_reducer import reduce_strategy_state
from backend.control.strategy_state import fallback_strategy_state


def _refresh_strategy_states(deps: CoordinatorDeps, now: float) -> None:
    strategy_states = {}
    for challenge_name, challenge in deps.runtime_state.challenges.items():
        swarm = deps.runtime_state.swarms.get(challenge_name)
        memory = deps.working_memory_store.get(challenge_name)
        try:
            strategy_states[challenge_name] = reduce_strategy_state(
                challenge=challenge,
                swarm=swarm,
                memory=memory,
                result_record=deps.results.get(challenge_name),
                now=now,
                stall_seconds=deps.policy_engine.stall_seconds if deps.policy_engine else 180,
                bump_cooldown_seconds=(
                    deps.policy_engine.bump_cooldown_seconds if deps.policy_engine else 60
                ),
            )
        except Exception:
            logger.exception("Strategy reduction failed for %s", challenge_name)
            strategy_states[challenge_name] = fallback_strategy_state(
                challenge_name,
                reason="strategy reducer failed",
            )
    deps.strategy_states = strategy_states


def _summarize_strategy(deps: CoordinatorDeps, challenge_name: str) -> str:
    strategy = deps.strategy_states.get(challenge_name)
    if strategy is None:
        return "No strategy state available."
    return strategy.to_summary()
```

- [ ] **Step 5: 在主循环刷新 runtime state 后同步刷新 strategy state**

```python
# backend/agents/coordinator_loop.py
deps.runtime_state = build_runtime_state_snapshot(deps, poller, now)
_refresh_strategy_states(deps, now)
```

把这句接到：

- 初始 snapshot 完成后
- 每次 trace 增量更新后
- 每次 action 执行完、runtime state 重建后

- [ ] **Step 6: 运行定向测试确认 loop 已接线**

Run: `uv run pytest tests/test_coordinator_platform_flow.py -q -k "refresh_strategy_states_populates_strategy_summary"`  
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/deps.py backend/agents/coordinator_loop.py tests/test_coordinator_platform_flow.py
git commit -m "refactor: 接入单题策略状态刷新链路"
```

### Task 3: 让 `PolicyEngine` 消费 strategy state

**Files:**
- Modify: `backend/control/policy_engine.py`
- Modify: `backend/agents/coordinator_loop.py`
- Modify: `tests/test_policy_engine.py`

- [ ] **Step 1: 先写失败测试，锁定 strategy 优先级**

```python
from backend.control.strategy_state import ChallengeStrategyState


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
```

- [ ] **Step 2: 跑测试，确认当前 `plan_tick()` 还不接受 strategy 输入**

Run: `uv run pytest tests/test_policy_engine.py -q -k "prefers_strategy_active_hypothesis or skips_bump_for_low_confidence_blocked_strategy"`  
Expected: FAIL with unexpected keyword `strategy_states` or wrong guidance

- [ ] **Step 3: 扩展 `PolicyEngine.plan_tick()` 签名并优先读 strategy**

```python
# backend/control/policy_engine.py
from backend.control.strategy_state import ChallengeStrategyState


def plan_tick(
    self,
    *,
    competition: CompetitionState,
    working_memory_store: WorkingMemoryStore,
    knowledge_store: KnowledgeStore,
    strategy_states: dict[str, ChallengeStrategyState] | None = None,
    now: float,
) -> list[PolicyAction]:
    strategies = strategy_states or {}
    ...
    strategy = strategies.get(challenge_name)
    if self._should_bump_swarm(swarm=swarm, now=now):
        active_hypothesis = strategy.active_hypothesis if strategy else ""
        if not active_hypothesis:
            memory = working_memory_store.get(challenge_name)
            active_hypothesis = memory.open_hypotheses[0] if memory.open_hypotheses else ""
        if (
            strategy
            and strategy.stage == "blocked"
            and strategy.confidence < 0.5
        ):
            active_hypothesis = ""
        if active_hypothesis and swarm.running_models:
            actions.append(
                BumpSolver(
                    challenge_name=challenge_name,
                    model_spec=swarm.running_models[0],
                    guidance=f"Retry with open hypothesis: {active_hypothesis}",
                    reason="stalled swarm with reusable hypothesis",
                )
            )
```

- [ ] **Step 4: 在 loop 里把 `deps.strategy_states` 传给 `plan_tick()`**

```python
actions = deps.policy_engine.plan_tick(
    competition=deps.runtime_state,
    working_memory_store=deps.working_memory_store,
    knowledge_store=deps.knowledge_store,
    strategy_states=deps.strategy_states,
    now=now,
)
```

- [ ] **Step 5: 跑 policy 定向测试确认行为切换成功**

Run: `uv run pytest tests/test_policy_engine.py -q`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/control/policy_engine.py backend/agents/coordinator_loop.py tests/test_policy_engine.py
git commit -m "feat: 让策略层驱动 policy 决策"
```

### Task 4: 把 `strategy_summary` 接到 advisor，并补 README

**Files:**
- Modify: `backend/control/advisor.py`
- Modify: `backend/agents/coordinator_loop.py`
- Modify: `tests/test_coordinator_platform_flow.py`
- Modify: `README.md`

- [ ] **Step 1: 先写 advisor 输入面的失败测试**

```python
async def test_run_event_loop_passes_strategy_summary_to_advisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.control.advisor import AdvisorContext
    from backend.control.strategy_state import ChallengeStrategyState

    ...
    deps.strategy_states["rsa"] = ChallengeStrategyState(
        challenge_name="rsa",
        stage="exploit",
        goal="Try common modulus attack",
        active_hypothesis="Try common modulus attack",
        confidence=0.8,
    )

    captured_contexts: list[AdvisorContext] = []

    class FakeAdvisor:
        async def suggest(self, context: AdvisorContext) -> list[Any]:
            captured_contexts.append(context)
            return []

    ...

    assert "stage=exploit" in captured_contexts[0].strategy_summary
    assert "common modulus" in captured_contexts[0].strategy_summary
```

- [ ] **Step 2: 跑测试，确认当前 `AdvisorContext` 尚无 `strategy_summary`**

Run: `uv run pytest tests/test_coordinator_platform_flow.py -q -k "passes_strategy_summary_to_advisor"`  
Expected: FAIL with missing field or missing summary content

- [ ] **Step 3: 扩展 `AdvisorContext` 与 prompt 渲染**

```python
# backend/control/advisor.py
@dataclass(slots=True)
class AdvisorContext:
    competition_summary: str
    challenge_name: str
    memory_summary: str
    knowledge_summary: str
    strategy_summary: str


def render_advisor_prompt(context: AdvisorContext) -> str:
    return (
        "Provide advisor suggestions for the following challenge context.\n\n"
        f"competition_summary: {context.competition_summary}\n"
        f"challenge_name: {context.challenge_name}\n"
        f"memory_summary: {context.memory_summary}\n"
        f"knowledge_summary: {context.knowledge_summary}\n"
        f"strategy_summary: {context.strategy_summary}\n"
    )
```

- [ ] **Step 4: 在 loop 的 advisor tick 中传入 `_summarize_strategy()`**

```python
context = AdvisorContext(
    competition_summary=competition_summary,
    challenge_name=challenge_name,
    memory_summary=_summarize_memory(deps, challenge_name),
    knowledge_summary=_summarize_knowledge(deps, challenge_name),
    strategy_summary=_summarize_strategy(deps, challenge_name),
)
```

- [ ] **Step 5: README 补一小段 Phase 1 架构链路**

```markdown
- `Strategy Layer`：单题策略解释层，负责把 runtime state 与 working memory 归纳为 `stage / goal / active_hypothesis / next_actions`
- 当前控制链路已从 `Working Memory -> Policy` 升级为 `Working Memory -> Strategy -> Policy`
```

- [ ] **Step 6: 跑定向集成测试确认 advisor 已读到 strategy summary**

Run: `uv run pytest tests/test_coordinator_platform_flow.py -q -k "passes_strategy_summary_to_advisor or applies_advisor_suggestions_via_policy_engine"`  
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/control/advisor.py backend/agents/coordinator_loop.py tests/test_coordinator_platform_flow.py README.md
git commit -m "feat: 向 advisor 暴露单题策略摘要"
```

### Task 5: 全量回归与收尾

**Files:**
- Modify: `docs/superpowers/plans/2026-04-07-challenge-strategy-layer-phase1.md`

- [ ] **Step 1: 跑全量测试**

Run: `uv run pytest -q`  
Expected: PASS

- [ ] **Step 2: 跑 lint**

Run: `uv run ruff check backend tests`  
Expected: PASS

- [ ] **Step 3: 检查工作区，确认不碰 `writeups/`**

Run: `git status --short`  
Expected: 只包含本计划涉及文件；若仍有 `?? writeups/`，不要 stage 它

- [ ] **Step 4: 回写计划执行状态并提交**

```bash
git add docs/superpowers/plans/2026-04-07-challenge-strategy-layer-phase1.md
git commit -m "docs: 更新 strategy layer 第一阶段计划状态"
```
