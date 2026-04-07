# Auto Bump 闭环、Coordinator 去 Legacy 与 Smoke 回归脚本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让共享控制面真正完成“trace -> memory -> policy -> bump”的自动闭环，移除 provider coordinator 的 legacy 直控路径，并把线上 smoke 固化成可重复执行的回归脚本。

**Architecture:** 继续以 `backend/agents/coordinator_loop.py` 作为唯一赛事控制主循环，把 provider 端收缩成 advisor-only 适配层，所有顶层动作都经由共享 `PolicyEngine + coordinator_core` 执行。自动 bump 不再依赖人工预填 `open_hypotheses`，而是由 trace 增量提炼出可复用假设；外部长跑验证改为脚本化、带断言标记的 smoke harness。

**Tech Stack:** Python 3.14, pytest, pydantic-ai, Claude Agent SDK, Codex app-server, shell smoke harness, Ruff

## 执行状态

- `Task 1` 已完成：`trace -> working memory -> policy -> bump` 自动闭环已打通，并补了 working memory / platform flow 回归测试。
- `Task 2` 已完成：共享 `coordinator_loop` 现在以 `event_sink` 作为统一事件出口，`headless` 与 provider coordinator 都走同一主循环。
- `Task 3` 已完成：`azure` / `codex` / `claude` provider 入口已收缩为 advisor-only 适配层；README 同步收紧为当前真实语义。
- `Task 4` 已完成：新增 `scripts/run_coordinator_smoke.py`，支持默认 Azure smoke 预设、自定义透传命令、marker 断言和受控终止；README 已补使用说明。
- `Task 5` 已完成：已跑全量 `pytest`、`ruff check backend tests scripts`、smoke `--help`、最小自检，以及一轮安全的 live smoke（临时 `challenges-dir` / `writeup-dir` + `--no-submit`，避免触碰仓库内 `writeups/`）。

## 说明

- 原计划里的分任务 commit 步骤未逐条执行；本轮改动保留在同一开发分支上，统一做最终提交与推送。

---

### Task 1: 打通自动 bump 真闭环

**Files:**
- Modify: `backend/control/working_memory.py`
- Modify: `backend/control/policy_engine.py`
- Modify: `tests/test_working_memory.py`
- Modify: `tests/test_policy_engine.py`
- Modify: `tests/test_coordinator_platform_flow.py`

- [ ] **Step 1: 先用失败测试锁定 trace 到 open hypotheses 的提炼行为**

```python
def test_working_memory_promotes_bump_guidance_and_unverified_findings_to_open_hypotheses() -> None:
    store = WorkingMemoryStore()
    store.apply_trace_events(
        challenge_name="echo",
        events=[
            {"type": "bump", "insights": "Try format string offset 6"},
            {
                "type": "tool_result",
                "tool": "bash",
                "result": "Candidate finding: stack canary leak is visible via printf output",
            },
        ],
    )

    memory = store.get("echo")

    assert "Try format string offset 6" in memory.open_hypotheses
    assert "stack canary leak is visible via printf output" in memory.open_hypotheses
```

- [ ] **Step 2: 再用失败测试锁定 event loop 自动触发 bump**

```python
@pytest.mark.asyncio
async def test_run_event_loop_turns_trace_hypothesis_into_policy_bump(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        json.dumps({"type": "bump", "insights": "Try common modulus attack"}) + "\n",
        encoding="utf-8",
    )

    executed: list[BumpSolver] = []

    async def fake_execute_action(deps: CoordinatorDeps, action: Any) -> str:
        if isinstance(action, BumpSolver):
            executed.append(action)
        return "ok"

    ...

    assert executed == [
        BumpSolver(
            challenge_name="rsa",
            model_spec="azure/gpt-5.4",
            guidance="Retry with open hypothesis: Try common modulus attack",
            reason="stalled swarm with reusable hypothesis",
        )
    ]
```

- [ ] **Step 3: 跑测试确认当前确实失败**

Run: `uv run pytest tests/test_working_memory.py tests/test_policy_engine.py tests/test_coordinator_platform_flow.py -q`  
Expected: FAIL，因为当前 `apply_trace_events()` 不会填充 `open_hypotheses`，event loop 也无法通过真实 trace 触发 `BumpSolver`

- [ ] **Step 4: 在 `WorkingMemoryStore` 中实现“可复用假设”提炼**

```python
def apply_trace_events(self, challenge_name: str, events: list[Any]) -> ChallengeWorkingMemory:
    memory = self.get(challenge_name)
    for event in events:
        ...
        if event_type == "bump":
            insight = str(event.get("insights", "")).strip()
            if insight and insight not in memory.last_guidance:
                memory.last_guidance.append(insight)
            if insight and insight not in memory.open_hypotheses:
                memory.open_hypotheses.append(insight)

        if event_type == "tool_result":
            hypothesis = _extract_open_hypothesis(str(event.get("result", "")))
            if hypothesis and hypothesis not in memory.open_hypotheses:
                memory.open_hypotheses.append(hypothesis)
```

- [ ] **Step 5: 给开放假设提炼补最小辅助函数和去噪规则**

```python
def _extract_open_hypothesis(result: str) -> str:
    finding = result.strip()
    if not finding:
        return ""
    lowered = finding.lower()
    if lowered.startswith(("platform rule:", "category rule:", "exploit pattern:")):
        return ""
    if "candidate finding:" in lowered:
        return finding.split(":", 1)[1].strip()
    if "next step:" in lowered:
        return finding.split(":", 1)[1].strip()
    return ""
```

- [ ] **Step 6: 保持 policy 行为简单，只消费 `open_hypotheses` 的首项**

```python
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
```

- [ ] **Step 7: 跑定向测试确认闭环通过**

Run: `uv run pytest tests/test_working_memory.py tests/test_policy_engine.py tests/test_coordinator_platform_flow.py -q`  
Expected: PASS，且新增用例证明 trace 可直接驱动自动 bump

- [ ] **Step 8: Commit**

```bash
git add backend/control/working_memory.py backend/control/policy_engine.py tests/test_working_memory.py tests/test_policy_engine.py tests/test_coordinator_platform_flow.py
git commit -m "feat: 打通自动 bump 闭环"
```

### Task 2: 让共享 coordinator loop 成为唯一控制主循环

**Files:**
- Modify: `backend/agents/coordinator_loop.py`
- Modify: `backend/agents/headless_coordinator.py`
- Modify: `tests/test_coordinator_platform_flow.py`

- [ ] **Step 1: 先写失败测试，锁定“没有顶层 turn 也能跑 loop”**

```python
@pytest.mark.asyncio
async def test_run_event_loop_supports_headless_event_sink_without_llm_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform = FakePlatform(
        stub_snapshots=[[{"name": "warmup"}]],
        solved_snapshots=[{"warmup"}],
    )
    deps = CoordinatorDeps(
        ctfd=platform,
        cost_tracker=CostTracker(),
        settings=make_settings(all_solved_policy="exit"),
        model_specs=[],
    )
    seen: list[str] = []

    async def event_sink(message: str) -> None:
        seen.append(message)

    result = await coordinator_loop.run_event_loop(
        deps=deps,
        ctfd=platform,
        cost_tracker=deps.cost_tracker,
        event_sink=event_sink,
        advisor=None,
    )

    assert result["results"] == {}
    assert any("CTF is LIVE" in item for item in seen)
```

- [ ] **Step 2: 跑测试确认当前接口不支持**

Run: `uv run pytest tests/test_coordinator_platform_flow.py -q`  
Expected: FAIL，因为当前 `run_event_loop()` 必须传 `turn_fn`

- [ ] **Step 3: 把 `turn_fn` 抽象成可选的 `event_sink`**

```python
EventSink = Callable[[str], Coroutine[Any, Any, None]]

async def run_event_loop(
    deps: CoordinatorDeps,
    ctfd: CompetitionPlatformClient,
    cost_tracker: CostTracker,
    event_sink: EventSink | None = None,
    advisor: CoordinatorAdvisor | None = None,
    status_interval: int = 60,
) -> dict[str, Any]:
    ...
    if event_sink is not None:
        await event_sink(initial_msg)
    else:
        logger.info("Headless event: %s", initial_msg[:400])
```

- [ ] **Step 4: 所有事件推送点都统一走 helper，避免散落判断**

```python
async def _emit_event(event_sink: EventSink | None, message: str) -> None:
    if not message:
        return
    if event_sink is None:
        logger.info("Headless event: %s", message[:400])
        return
    await event_sink(message)
```

- [ ] **Step 5: 更新 headless coordinator，直接显式传 `event_sink`**

```python
async def event_sink(message: str) -> None:
    logger.info("Headless event: %s", message[:400])

return await run_event_loop(
    deps,
    ctfd,
    cost_tracker,
    event_sink=event_sink,
)
```

- [ ] **Step 6: 跑共享 loop 回归**

Run: `uv run pytest tests/test_coordinator_platform_flow.py -q`  
Expected: PASS，且现有 headless 与 advisor 相关测试不回退

- [ ] **Step 7: Commit**

```bash
git add backend/agents/coordinator_loop.py backend/agents/headless_coordinator.py tests/test_coordinator_platform_flow.py
git commit -m "refactor: 统一 coordinator 事件主循环"
```

### Task 3: 把 provider coordinator 收缩成 advisor-only 壳层

**Files:**
- Modify: `backend/agents/azure_coordinator.py`
- Modify: `backend/agents/codex_coordinator.py`
- Modify: `backend/agents/claude_coordinator.py`
- Modify: `tests/test_coordinator_platform_flow.py`
- Modify: `README.md`

- [ ] **Step 1: 先写失败测试，锁定 provider 入口不再需要 legacy coordinator turn**

```python
@pytest.mark.asyncio
async def test_run_azure_coordinator_uses_event_sink_and_advisor_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_event_loop(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["event_sink"] = kwargs.get("event_sink")
        captured["advisor"] = kwargs.get("advisor")
        return {"results": {}, "total_cost_usd": 0.0, "total_tokens": 0}

    monkeypatch.setattr("backend.agents.azure_coordinator.run_event_loop", fake_run_event_loop)

    result = await run_azure_coordinator(...)

    assert callable(captured["event_sink"])
    assert captured["advisor"] is not None
```

- [ ] **Step 2: 跑 provider 相关测试确认当前实现仍依赖 legacy 类**

Run: `uv run pytest tests/test_coordinator_platform_flow.py -q`  
Expected: FAIL，因为当前 Azure/Codex 仍会创建 `AzureCoordinator` / `CodexCoordinator` 并把 `turn_fn` 传入共享 loop

- [ ] **Step 3: 删除 Azure 的 direct coordinator 类，只保留 advisor 与简单 event sink**

```python
async def run_azure_coordinator(...):
    ...
    advisor = AzureCoordinatorAdvisor(settings=settings, model_spec=model_spec)
    await advisor.start()

    async def event_sink(message: str) -> None:
        logger.info("Azure coordinator event: %s", message[:400])

    try:
        return await run_event_loop(
            deps,
            ctfd,
            cost_tracker,
            event_sink=event_sink,
            advisor=advisor,
        )
    finally:
        await advisor.stop()
```

- [ ] **Step 4: Codex 与 Claude 也改成 advisor-only 入口**

```python
async def run_codex_coordinator(...):
    ...
    advisor = CodexCoordinatorAdvisor(model=resolved_model)
    await advisor.start()

    async def event_sink(msg: str) -> None:
        logger.info("Codex coordinator event: %s", msg[:400])

    try:
        return await run_event_loop(
            deps,
            ctfd,
            cost_tracker,
            event_sink=event_sink,
            advisor=advisor,
        )
    finally:
        await advisor.stop()
```

- [ ] **Step 5: 清理 provider 文件中的 legacy prompt / tool / thread 管理残留**

```python
# 删除内容示意：
- class AzureCoordinator
- class CodexCoordinator
- COORDINATOR_PROMPT
- COORDINATOR_TOOLS
- _build_coordinator_mcp(...)
```

- [ ] **Step 6: 补 README，明确当前 coordinator provider 语义已经是“advisor backend”**

```markdown
- `--coordinator azure|codex|claude` 现在只决定“顶层 advisor 使用哪个 provider”。
- 真正的 spawn / bump / broadcast 一律由共享 `coordinator_loop + policy_engine + coordinator_core` 执行。
- `--coordinator none` 表示没有 advisor，只保留共享控制闭环。
```

- [ ] **Step 7: 跑 provider 与文档相关回归**

Run: `uv run pytest tests/test_coordinator_platform_flow.py tests/test_cli.py -q`  
Expected: PASS

Run: `uv run ruff check backend/agents/azure_coordinator.py backend/agents/codex_coordinator.py backend/agents/claude_coordinator.py backend/agents/coordinator_loop.py tests/test_coordinator_platform_flow.py README.md`  
Expected: PASS（README 若不在 Ruff 范围，保留 Python 文件通过即可）

- [ ] **Step 8: Commit**

```bash
git add backend/agents/azure_coordinator.py backend/agents/codex_coordinator.py backend/agents/claude_coordinator.py backend/agents/coordinator_loop.py tests/test_coordinator_platform_flow.py tests/test_cli.py README.md
git commit -m "refactor: 去除 provider coordinator legacy 直控"
```

### Task 4: 把长跑 smoke 固化成可重复执行的回归脚本

**Files:**
- Create: `scripts/run_coordinator_smoke.py`
- Modify: `README.md`

- [ ] **Step 1: 先写脚本设计约束到 README 草案里，明确成功判定**

```markdown
Smoke 成功条件：
- 子进程成功启动 `ctf-solve`
- 日志中出现 `Coordinator starting:`
- 日志中出现 `Policy action executed:` 或 `Headless event:` / provider event
- 日志中出现 Azure `/responses` 200 或至少出现一次 solver/coordinator 正常事件循环
- 达到设定时长后脚本能优雅终止并返回 0
```

- [ ] **Step 2: 新增 Python 脚本，把命令、超时、关键日志断言封装起来**

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=90)
    parser.add_argument("--log-file", default="")
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    ...
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        matched = _stream_until_deadline(proc, deadline, markers)
    finally:
        _terminate_process(proc)

    missing = [marker for marker, seen in matched.items() if not seen]
    if missing:
        print(f"Smoke failed, missing markers: {missing}", file=sys.stderr)
        return 1
    return 0
```

- [ ] **Step 3: 默认内置一条与你当前线上命令一致的 Azure coordinator smoke 模板**

```python
DEFAULT_SMOKE_CMD = [
    "uv",
    "run",
    "ctf-solve",
    "--platform",
    "lingxu-event-ctf",
    "--coordinator",
    "azure",
    "--all-solved-policy",
    "exit",
    ...
]
```

- [ ] **Step 4: README 补运行方式与注意事项**

```markdown
python scripts/run_coordinator_smoke.py --duration-seconds 90 -- \
  uv run ctf-solve \
  --platform lingxu-event-ctf \
  --platform-url https://ctf.yunyansec.com \
  --lingxu-event-id 198 \
  --coordinator azure \
  --models azure/gpt-5.4 \
  --models azure/gpt-5.4-mini \
  --max-challenges 3 \
  --all-solved-policy exit \
  --writeup-mode confirmed \
  --writeup-dir writeups \
  --msg-port 9400 \
  -v
```

- [ ] **Step 5: 对脚本跑一次 `--help` 和一次最小自检**

Run: `uv run python scripts/run_coordinator_smoke.py --help`  
Expected: PASS，显示参数说明

Run: `uv run python scripts/run_coordinator_smoke.py --duration-seconds 5 -- python -c "import time; print('Coordinator starting: ok'); print('Policy action executed: ok'); time.sleep(1)"`  
Expected: PASS，脚本正确匹配 marker 并返回 0

- [ ] **Step 6: 在真实环境跑 Azure coordinator smoke**

Run:

```bash
uv run python scripts/run_coordinator_smoke.py --duration-seconds 90 -- \
  uv run ctf-solve \
    --platform lingxu-event-ctf \
    --platform-url https://ctf.yunyansec.com \
    --lingxu-event-id 198 \
    --coordinator azure \
    --models azure/gpt-5.4 \
    --models azure/gpt-5.4-mini \
    --max-challenges 3 \
    --all-solved-policy exit \
    --writeup-mode confirmed \
    --writeup-dir writeups \
    --msg-port 9400 \
    -v
```

Expected: PASS，脚本在 90 秒内观测到启动与控制面 marker，结束后返回 0

- [ ] **Step 7: Commit**

```bash
git add scripts/run_coordinator_smoke.py README.md
git commit -m "feat: 固化 coordinator smoke 回归脚本"
```

### Task 5: 最终总回归与交付

**Files:**
- Modify: `docs/superpowers/plans/2026-04-07-auto-bump-legacy-smoke-regression.md`

- [ ] **Step 1: 跑完整测试集**

Run: `uv run pytest -q`  
Expected: PASS

- [ ] **Step 2: 跑关键 lint**

Run: `uv run ruff check backend tests scripts`  
Expected: PASS

- [ ] **Step 3: 检查工作区只包含本次相关改动**

Run: `git status --short`  
Expected: 仅出现本计划涉及文件；不包含 `writeups/`

- [ ] **Step 4: 更新计划勾选并提交**

```bash
git add docs/superpowers/plans/2026-04-07-auto-bump-legacy-smoke-regression.md
git commit -m "docs: 更新 auto bump 与 coordinator 回归计划状态"
```
