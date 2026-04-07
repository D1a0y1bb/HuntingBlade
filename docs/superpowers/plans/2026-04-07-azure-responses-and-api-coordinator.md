# Azure Responses Solver 与 `.env` API 总控 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `azure/...` solver 切到 Responses API，并新增只依赖 `.env` 的 `--coordinator azure` 总控后端。

**Architecture:** 模型解析层只升级 `azure` provider，不扩大到其他 provider；协调器层新增一个基于 Pydantic AI 的 API coordinator，并继续复用共享 `coordinator_loop` / `coordinator_core`。CLI 只负责路由与参数归一化，README 负责把 `.env only` 用法讲清楚。

**Tech Stack:** Python 3.14, click, asyncio, pydantic-ai, pytest, rich

---

### Task 1: 先用测试锁定 Azure Responses 解析行为

**Files:**
- Create: `tests/test_models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 为 `azure/...` 新增 model 类型测试**

```python
def test_resolve_model_uses_openai_responses_for_azure() -> None:
    settings = Settings(
        azure_openai_endpoint="https://api.example.com/v1",
        azure_openai_api_key="test-key",
    )

    model = resolve_model("azure/gpt-5.4", settings)

    assert isinstance(model, OpenAIResponsesModel)
```

- [ ] **Step 2: 为 Azure model settings 新增关键参数断言**

```python
def test_resolve_model_settings_uses_responses_defaults_for_azure() -> None:
    settings = resolve_model_settings("azure/gpt-5.4")

    assert settings["max_tokens"] == 128_000
    assert settings["openai_reasoning_effort"] == "medium"
    assert settings["openai_reasoning_summary"] == "auto"
    assert settings["openai_truncation"] == "auto"
    assert "openai_previous_response_id" not in settings
```

- [ ] **Step 3: 运行测试确认先失败**

Run: `uv run pytest tests/test_models.py -q`  
Expected: FAIL because `resolve_model()` still returns `OpenAIModel`

### Task 2: 先用测试锁定 Azure coordinator 入口

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `tests/test_coordinator_platform_flow.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_coordinator_platform_flow.py`

- [ ] **Step 1: 扩展 CLI help 与参数测试**

```python
def test_main_help_uses_english_options_with_chinese_help() -> None:
    result = CliRunner().invoke(cli.main, ["--help"])
    assert "azure" in result.output
```

```python
def test_main_accepts_azure_coordinator(monkeypatch, tmp_path: Path) -> None:
    ...
    result = CliRunner().invoke(
        cli.main,
        [
            "--platform", "lingxu-event-ctf",
            "--platform-url", "https://lx.example.com",
            "--lingxu-event-id", "42",
            "--lingxu-cookie-file", str(cookie_file),
            "--coordinator", "azure",
        ],
    )
    assert result.exit_code == 0
    assert captured["coordinator_backend"] == "azure"
```

- [ ] **Step 2: 为 Azure coordinator 共享事件循环接线新增测试**

```python
@pytest.mark.asyncio
async def test_run_azure_coordinator_uses_shared_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.agents.azure_coordinator import run_azure_coordinator
    ...
    result = await run_azure_coordinator(
        settings=make_settings(platform="lingxu-event-ctf"),
        model_specs=["azure/gpt-5.4-mini"],
        challenges_root="challenges",
        no_submit=True,
        msg_port=9701,
        platform=platform,
    )
    assert result["results"] == {}
```

- [ ] **Step 3: 为 Azure 总控模型归一化新增测试**

```python
def test_normalize_azure_coordinator_model_accepts_bare_model_name() -> None:
    assert _normalize_azure_coordinator_model("gpt-5.4") == "azure/gpt-5.4"
```

```python
def test_normalize_azure_coordinator_model_rejects_non_azure_spec() -> None:
    with pytest.raises(ValueError):
        _normalize_azure_coordinator_model("google/gemini-3-flash-preview")
```

- [ ] **Step 4: 运行测试确认先失败**

Run: `uv run pytest tests/test_cli.py tests/test_coordinator_platform_flow.py -q`  
Expected: FAIL because `azure` coordinator 分支与模块尚不存在

### Task 3: 实现 Azure Responses model 解析

**Files:**
- Modify: `backend/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 切换 Azure model 到 Responses API**

```python
from pydantic_ai.models.openai import (
    OpenAIModel,
    OpenAIModelSettings,
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
)
```

```python
        case "azure":
            return OpenAIResponsesModel(
                model_id,
                provider=OpenAIProvider(
                    base_url=settings.azure_openai_endpoint,
                    api_key=settings.azure_openai_api_key,
                ),
            )
```

- [ ] **Step 2: 切换 Azure settings 到 Responses 参数**

```python
        case "azure":
            return OpenAIResponsesModelSettings(
                max_tokens=128_000,
                openai_reasoning_effort="medium",
                openai_reasoning_summary="auto",
                openai_truncation="auto",
            )
```

- [ ] **Step 3: 保持 `zen` 现状不变**

```python
        case "zen":
            return OpenAIModelSettings(
                max_tokens=128_000,
            )
```

- [ ] **Step 4: 运行定向测试**

Run: `uv run pytest tests/test_models.py -q`  
Expected: PASS

### Task 4: 实现 `.env` only 的 Azure coordinator

**Files:**
- Create: `backend/agents/azure_coordinator.py`
- Modify: `backend/cli.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_coordinator_platform_flow.py`

- [ ] **Step 1: 新增 Azure coordinator 工具封装与 agent**

```python
async def fetch_challenges(ctx: RunContext[CoordinatorDeps]) -> str:
    return await do_fetch_challenges(ctx.deps)
```

```python
agent = Agent(
    resolve_model(model_spec, settings),
    deps_type=CoordinatorDeps,
    system_prompt=COORDINATOR_PROMPT,
    model_settings=resolve_model_settings(model_spec),
    tools=[fetch_challenges, get_solve_status, spawn_swarm, ...],
)
```

- [ ] **Step 2: 实现 coordinator model 归一化**

```python
def _normalize_azure_coordinator_model(spec: str | None) -> str:
    if not spec:
        return "azure/gpt-5.4"
    if "/" not in spec:
        return f"azure/{spec}"
    if not spec.startswith("azure/"):
        raise ValueError("azure coordinator 只能使用 azure/<model> 或裸模型名")
    return spec
```

- [ ] **Step 3: 在 `run_azure_coordinator()` 中复用共享事件循环**

```python
async def turn_fn(message: str) -> None:
    result = await agent.run(
        message,
        deps=deps,
        message_history=message_history or None,
    )
    message_history = result.all_messages()
```

- [ ] **Step 4: CLI 接入 `azure` 分支**

```python
@click.option(
    "--coordinator",
    default="claude",
    type=click.Choice(["claude", "codex", "azure", "none"]),
    help="协调器后端；azure 表示只走 .env 的 API 总控，none 表示无总控整场模式",
)
```

```python
    elif coordinator_backend == "azure":
        from backend.agents.azure_coordinator import run_azure_coordinator
        results = await run_azure_coordinator(...)
```

- [ ] **Step 5: 运行定向测试**

Run: `uv run pytest tests/test_cli.py tests/test_coordinator_platform_flow.py -q`  
Expected: PASS

### Task 5: 更新 README 并做整体验证

**Files:**
- Modify: `README.md`
- Test: `README.md`

- [ ] **Step 1: README 补充 Azure coordinator 与 `.env only` 说明**

```md
| 协调模式 | 已支持 | `claude`、`codex`、`azure`、`none` |
```

```md
- 如果你不想依赖本机 Codex/Claude，请使用 `--coordinator azure` 或 `--coordinator none`。
- `--coordinator azure` 与 `--models azure/...` 一样，都只读取 `.env` 中的 Azure 配置。
```

- [ ] **Step 2: 更新推荐命令**

```bash
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

- [ ] **Step 3: 运行完整验证**

Run: `uv run pytest -q`  
Expected: PASS

Run: `uv run ctf-solve --help`  
Expected: help 文案中包含 `azure`
