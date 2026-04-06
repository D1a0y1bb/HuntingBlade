# 自动收尾、环境释放与 Writeup 输出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 HuntingBlade 的整场自动解题补齐三项运行期闭环能力：全解后按策略退出、环境题提交成功后自动释放环境、可选输出统一中文 writeup 草稿。

**Architecture:** 继续复用共享的 `backend/agents/coordinator_loop.py` 事件循环做“何时退出”的统一决策，不分裂出第二套生命周期逻辑。平台相关动作通过 `CompetitionPlatformClient.release_challenge_env()` 下沉到平台适配层，题目结果汇总与 writeup 输出由独立 helper 统一生成，避免把状态散落在 swarm、coordinator 和 README 三处。

**Tech Stack:** Python 3.14, click, asyncio, httpx, pydantic-settings, pytest, PyYAML, rich

---

## File Structure

- `backend/config.py`
  负责新增运行期开关默认值：`all_solved_policy`、`all_solved_idle_seconds`、`writeup_mode`、`writeup_dir`。
- `backend/cli.py`
  负责暴露新的 CLI 选项、参数校验、把生命周期配置写入 `Settings`，并在启动摘要中展示当前策略。
- `backend/solver_base.py`
  给 `SolverResult` 增加 `model_spec`，让结果记录能落下 `winner_model`。
- `backend/agents/solver.py`
  为 Pydantic AI solver 返回补齐 `model_spec`。
- `backend/agents/codex_solver.py`
  为 Codex solver 返回补齐 `model_spec`。
- `backend/agents/claude_solver.py`
  为 Claude solver 返回补齐 `model_spec`。
- `backend/agents/swarm.py`
  负责记录确认提交后的 `submit_status` / `submit_display` / `submit_message`，供收尾逻辑使用。
- `backend/deps.py`
  为 `CoordinatorDeps` 增加运行期去重状态，例如 `released_envs`。
- `backend/solve_lifecycle.py`
  新增统一结果结构与收尾 helper，例如 `ChallengeResultRecord`、`build_result_record()`、`finalize_swarm_result()`、`should_generate_writeup()`。
- `backend/writeups.py`
  新增中文 Markdown writeup 渲染与落盘逻辑，并从 trace JSONL 保守提取关键步骤摘要。
- `backend/platforms/base.py`
  为平台协议增加 `release_challenge_env(challenge_ref)` 能力。
- `backend/ctfd.py`
  提供 `release_challenge_env()` no-op 实现，保证旧平台不受影响。
- `backend/platforms/lingxu_event_ctf.py`
  对接凌虚 `/event/{event_id}/ctf/{challenge_id}/release/` 释放接口。
- `backend/agents/coordinator_core.py`
  在 swarm 完成后统一记录结果、尝试环境释放、尝试 writeup 生成。
- `backend/agents/coordinator_loop.py`
  在共享事件循环中实现 `wait|exit|idle` 三种全解后策略。
- `tests/test_cli.py`
  覆盖新 CLI 选项可见性、中文 help、配置对象传递和 `idle` 参数校验。
- `tests/test_writeups.py`
  覆盖统一结果结构、writeup 目录与中文章节、trace 摘要、生成策略。
- `tests/test_lingxu_event_ctf_client.py`
  覆盖凌虚环境释放接口和 CSRF 行为。
- `tests/test_coordinator_platform_flow.py`
  覆盖收尾逻辑、环境释放触发条件、dry-run 行为、全解后退出策略。
- `README.md`
  补全中文使用说明、退出策略、环境释放规则与 writeup 示例命令。

### Task 1: 先固定 CLI 与配置契约

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `backend/config.py`
- Modify: `backend/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 在 CLI 测试里补上生命周期选项的 help 与配置断言**

```python
def test_main_help_shows_lifecycle_options() -> None:
    result = CliRunner().invoke(cli.main, ["--help"])

    assert result.exit_code == 0
    assert "--all-solved-policy" in result.output
    assert "wait|exit|idle" in result.output
    assert "--all-solved-idle-seconds" in result.output
    assert "--writeup-mode" in result.output
    assert "off|confirmed|solved" in result.output
    assert "--writeup-dir" in result.output


def test_main_passes_lifecycle_options_into_settings(monkeypatch, tmp_path: Path) -> None:
    cookie_file = tmp_path / "lingxu.cookie"
    cookie_file.write_text("sessionid=sid123", encoding="utf-8")
    captured: dict[str, object] = {}

    async def fake_run_coordinator(
        settings,
        model_specs,
        challenges_dir,
        no_submit,
        coordinator_model,
        coordinator_backend,
        max_challenges,
        msg_port=0,
    ) -> None:
        captured["settings"] = settings

    monkeypatch.setattr(cli, "_run_coordinator", fake_run_coordinator)

    result = CliRunner().invoke(
        cli.main,
        [
            "--platform", "lingxu-event-ctf",
            "--platform-url", "https://lx.example.com",
            "--lingxu-event-id", "42",
            "--lingxu-cookie-file", str(cookie_file),
            "--all-solved-policy", "idle",
            "--all-solved-idle-seconds", "180",
            "--writeup-mode", "solved",
            "--writeup-dir", str(tmp_path / "writeups"),
        ],
    )

    assert result.exit_code == 0
    settings = captured["settings"]
    assert settings.all_solved_policy == "idle"
    assert settings.all_solved_idle_seconds == 180
    assert settings.writeup_mode == "solved"
    assert settings.writeup_dir == str(tmp_path / "writeups")


def test_main_rejects_nonpositive_idle_seconds(tmp_path: Path) -> None:
    cookie_file = tmp_path / "lingxu.cookie"
    cookie_file.write_text("sessionid=sid123", encoding="utf-8")

    result = CliRunner().invoke(
        cli.main,
        [
            "--platform", "lingxu-event-ctf",
            "--platform-url", "https://lx.example.com",
            "--lingxu-event-id", "42",
            "--lingxu-cookie-file", str(cookie_file),
            "--all-solved-policy", "idle",
            "--all-solved-idle-seconds", "0",
        ],
    )

    assert result.exit_code != 0
    assert "必须大于 0" in result.output
```

- [ ] **Step 2: 运行测试，确认现状还不支持这些选项**

Run: `uv run pytest tests/test_cli.py -q`  
Expected: FAIL because `main()` still没有 `--all-solved-policy` / `--writeup-mode` / `--writeup-dir`，也没有 `idle` 秒数校验

- [ ] **Step 3: 在 `Settings` 里补上默认配置字段**

```python
class Settings(BaseSettings):
    # Lifecycle
    all_solved_policy: str = "wait"
    all_solved_idle_seconds: int = 300
    writeup_mode: str = "off"
    writeup_dir: str = "writeups"
```

- [ ] **Step 4: 在 CLI 中接入新选项、校验与启动摘要**

```python
@click.option(
    "--all-solved-policy",
    default="wait",
    type=click.Choice(["wait", "exit", "idle"]),
    help="全部题目解出后的行为：wait 持续等待，exit 立即退出，idle 空闲后退出",
)
@click.option(
    "--all-solved-idle-seconds",
    default=300,
    type=int,
    help="当 --all-solved-policy=idle 时，全部已解后继续观察的秒数",
)
@click.option(
    "--writeup-mode",
    default="off",
    type=click.Choice(["off", "confirmed", "solved"]),
    help="是否自动输出中文 writeup 草稿",
)
@click.option(
    "--writeup-dir",
    default="writeups",
    type=click.Path(file_okay=False, path_type=Path),
    help="writeup 输出目录根路径",
)
def main(
    platform: str | None,
    platform_url: str | None,
    lingxu_event_id: int | None,
    lingxu_cookie: str | None,
    lingxu_cookie_file: Path | None,
    ctfd_url: str | None,
    ctfd_token: str | None,
    image: str,
    models: tuple[str, ...],
    challenge: str | None,
    challenges_dir: str,
    no_submit: bool,
    coordinator_model: str | None,
    coordinator: str,
    max_challenges: int,
    msg_port: int,
    verbose: bool,
    all_solved_policy: str,
    all_solved_idle_seconds: int,
    writeup_mode: str,
    writeup_dir: Path,
) -> None:
    if all_solved_policy == "idle" and all_solved_idle_seconds <= 0:
        raise click.ClickException("--all-solved-idle-seconds 必须大于 0")

    settings.all_solved_policy = all_solved_policy
    settings.all_solved_idle_seconds = all_solved_idle_seconds
    settings.writeup_mode = writeup_mode
    settings.writeup_dir = str(writeup_dir)

    console.print(f"  All-solved policy: {settings.all_solved_policy}")
    if settings.all_solved_policy == "idle":
        console.print(f"  Idle timeout: {settings.all_solved_idle_seconds}s")
    console.print(f"  Writeup mode: {settings.writeup_mode}")
    if settings.writeup_mode != "off":
        console.print(f"  Writeup dir: {settings.writeup_dir}")
```

- [ ] **Step 5: 重新运行 CLI 测试，确认契约生效**

Run: `uv run pytest tests/test_cli.py -q`  
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add tests/test_cli.py backend/config.py backend/cli.py
git commit -m "feat: 增加自动收尾与 writeup CLI 选项"
```

### Task 2: 用统一结果结构和 writeup 渲染器固定输出语义

**Files:**
- Create: `tests/test_writeups.py`
- Modify: `backend/solver_base.py`
- Modify: `backend/agents/solver.py`
- Modify: `backend/agents/codex_solver.py`
- Modify: `backend/agents/claude_solver.py`
- Create: `backend/solve_lifecycle.py`
- Create: `backend/writeups.py`
- Test: `tests/test_writeups.py`

- [ ] **Step 1: 先写结果结构与中文 writeup 的测试**

```python
def test_build_result_record_preserves_submit_and_cleanup_fields() -> None:
    result = SolverResult(
        flag="flag{demo}",
        status=FLAG_FOUND,
        findings_summary="通过格式化字符串泄露 GOT 后完成任意写。",
        step_count=9,
        cost_usd=0.37,
        log_path="/tmp/trace.jsonl",
        model_spec="codex/gpt-5.4",
    )

    record = build_result_record(
        result=result,
        confirmed=True,
        submit_status="correct",
        submit_display='CORRECT — "flag{demo}" accepted.',
        env_cleanup_status="released",
        env_cleanup_error="",
    )

    assert record["flag"] == "flag{demo}"
    assert record["solve_status"] == FLAG_FOUND
    assert record["confirmed"] is True
    assert record["winner_model"] == "codex/gpt-5.4"
    assert record["submit_status"] == "correct"
    assert record["env_cleanup_status"] == "released"
    assert record["writeup_status"] == "pending"


def test_write_writeup_generates_chinese_markdown_under_platform_run_dir(tmp_path: Path) -> None:
    challenge_dir = tmp_path / "echo-2483"
    dist_dir = challenge_dir / "distfiles"
    dist_dir.mkdir(parents=True)
    (dist_dir / "echo.zip").write_text("zip placeholder", encoding="utf-8")

    trace_path = tmp_path / "trace-echo.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps({"type": "tool_call", "step": 2, "tool": "bash", "args": "file /challenge/distfiles/echo"}),
                json.dumps({"type": "tool_result", "step": 2, "tool": "bash", "result": "ELF 32-bit"}),
            ]
        ),
        encoding="utf-8",
    )

    meta = ChallengeMeta(
        name="echo",
        category="Pwn",
        value=200,
        platform="lingxu-event-ctf",
        platform_url="https://ctf.yunyansec.com",
        event_id=198,
        platform_challenge_id=2483,
        connection_info="nc gamebox.yunyansec.com 36445",
        requires_env_start=True,
        description="flag格式为flag{xxxxxx}",
    )
    record = {
        "flag": "flag{demo}",
        "solve_status": FLAG_FOUND,
        "submit_status": "correct",
        "submit_display": 'CORRECT — "flag{demo}" accepted.',
        "confirmed": True,
        "winner_model": "codex/gpt-5.4",
        "findings_summary": "定位到格式化字符串，泄露地址后覆写 GOT。",
        "log_path": str(trace_path),
        "env_cleanup_status": "released",
        "env_cleanup_error": "",
        "writeup_path": "",
        "writeup_status": "pending",
        "writeup_error": "",
    }

    output = write_writeup(
        meta=meta,
        challenge_dir=str(challenge_dir),
        record=record,
        base_dir=str(tmp_path / "writeups"),
    )

    text = Path(output).read_text(encoding="utf-8")
    assert output.endswith("writeups/lingxu-event-ctf-198/echo.md")
    assert "# echo" in text
    assert "## 题目基本信息" in text
    assert "## 附件与环境信息" in text
    assert "## 最终结果" in text
    assert "## 解题思路摘要" in text
    assert "## 关键步骤与命令" in text
    assert "echo.zip" in text
    assert "nc gamebox.yunyansec.com 36445" in text
    assert "file /challenge/distfiles/echo" in text


def test_should_generate_writeup_respects_confirmed_and_solved_modes() -> None:
    confirmed_record = {"solve_status": FLAG_FOUND, "confirmed": True}
    dry_run_record = {"solve_status": FLAG_FOUND, "confirmed": False}

    assert should_generate_writeup("off", confirmed_record) is False
    assert should_generate_writeup("confirmed", confirmed_record) is True
    assert should_generate_writeup("confirmed", dry_run_record) is False
    assert should_generate_writeup("solved", dry_run_record) is True
```

- [ ] **Step 2: 运行测试，确认辅助模块尚不存在**

Run: `uv run pytest tests/test_writeups.py -q`  
Expected: FAIL because `backend.solve_lifecycle` / `backend.writeups` 尚不存在，且 `SolverResult` 还没有 `model_spec`

- [ ] **Step 3: 给 `SolverResult` 增加 `model_spec`，并在三个 solver 中填充**

```python
@dataclass
class SolverResult:
    flag: str | None
    status: str
    findings_summary: str
    step_count: int
    cost_usd: float
    log_path: str
    model_spec: str = ""
```

```python
return SolverResult(
    flag=self._flag,
    status=status,
    findings_summary=self._findings[:2000],
    step_count=run_steps if run_steps is not None else self._step_count,
    cost_usd=run_cost if run_cost is not None else self._cost_usd,
    log_path=self.tracer.path,
    model_spec=self.model_spec,
)
```

```python
return SolverResult(
    flag=self._flag,
    status=status,
    findings_summary=self._findings[:2000],
    step_count=self._step_count,
    cost_usd=self._cost_usd,
    log_path=self.tracer.path,
    model_spec=self.model_spec,
)
```

```python
return SolverResult(
    flag=self._flag,
    status=status,
    findings_summary=self._findings[:2000],
    step_count=run_steps if run_steps is not None else self._step_count[0],
    cost_usd=run_cost if run_cost is not None else cost,
    log_path=self.tracer.path,
    model_spec=self.model_spec,
)
```

- [ ] **Step 4: 新增统一结果 helper 与中文 writeup 渲染器**

```python
class ChallengeResultRecord(TypedDict):
    flag: str | None
    solve_status: str
    submit_status: str
    submit_display: str
    confirmed: bool
    winner_model: str
    findings_summary: str
    log_path: str
    writeup_path: str
    writeup_status: str
    writeup_error: str
    env_cleanup_status: str
    env_cleanup_error: str


def build_result_record(
    *,
    result: SolverResult,
    confirmed: bool,
    submit_status: str,
    submit_display: str,
    env_cleanup_status: str,
    env_cleanup_error: str,
) -> ChallengeResultRecord:
    return {
        "flag": result.flag,
        "solve_status": result.status,
        "submit_status": submit_status,
        "submit_display": submit_display,
        "confirmed": confirmed,
        "winner_model": result.model_spec,
        "findings_summary": result.findings_summary,
        "log_path": result.log_path,
        "writeup_path": "",
        "writeup_status": "pending",
        "writeup_error": "",
        "env_cleanup_status": env_cleanup_status,
        "env_cleanup_error": env_cleanup_error,
    }


def should_generate_writeup(mode: str, record: ChallengeResultRecord) -> bool:
    if mode == "off":
        return False
    if mode == "confirmed":
        return bool(record["confirmed"])
    return record["solve_status"] == FLAG_FOUND
```

```python
def _slugify(name: str) -> str:
    slug = re.sub(r'[<>:"/\\\\|?*.\\x00-\\x1f]', "", name.lower().strip())
    slug = re.sub(r"[\\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "challenge"


def _run_dir_name(meta: ChallengeMeta) -> str:
    platform = meta.platform or "ctfd"
    event_ref = meta.event_id if meta.event_id is not None else "local"
    return f"{platform}-{event_ref}"


def read_trace_excerpt(log_path: str, limit: int = 8) -> list[str]:
    path = Path(log_path)
    if not log_path or not path.exists():
        return []

    excerpt: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines()[-40:]:
        if not raw.strip():
            continue
        event = json.loads(raw)
        if event.get("type") == "tool_call":
            excerpt.append(
                f"- Step {event.get('step', '?')} 调用 `{event.get('tool', '?')}`：`{str(event.get('args', ''))[:120]}`"
            )
        elif event.get("type") == "tool_result":
            excerpt.append(
                f"- Step {event.get('step', '?')} 返回：`{str(event.get('result', ''))[:120]}`"
            )
        if len(excerpt) >= limit:
            break
    return excerpt


def write_writeup(meta: ChallengeMeta, challenge_dir: str, record: ChallengeResultRecord, base_dir: str) -> str:
    output_dir = Path(base_dir) / _run_dir_name(meta)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_slugify(meta.name)}.md"

    trace_excerpt = read_trace_excerpt(record["log_path"])
    distfiles = list_distfiles(challenge_dir)
    reproduction_note = "未自动提交，需人工确认。" if not record["confirmed"] else "平台已确认该 flag。"
    if record["env_cleanup_status"] == "failed":
        reproduction_note += "\n平台环境可能仍处于占用状态。"

    body = "\n".join(
        [
            f"# {meta.name}",
            "",
            "## 题目基本信息",
            f"- 分类：{meta.category or 'Unknown'}",
            f"- 分值：{meta.value or 0}",
            f"- 平台：{meta.platform or 'local'}",
            f"- 赛事 ID：{meta.event_id or 'local'}",
            f"- 平台题目 ID：{meta.platform_challenge_id or 'n/a'}",
            "",
            "## 附件与环境信息",
            f"- 本地题目目录：`{challenge_dir}`",
            f"- 附件目录：`{Path(challenge_dir) / 'distfiles'}`",
            f"- Connection：`{meta.connection_info or '无'}`",
            f"- 需要启动环境：{'是' if meta.requires_env_start else '否'}",
            f"- 附件清单：{', '.join(distfiles) if distfiles else '无'}",
            "",
            "## 最终结果",
            f"- 确认解出：{'是' if record['confirmed'] else '否'}",
            f"- Flag：`{record['flag'] or '未记录'}`",
            f"- 提交结果：{record['submit_display'] or record['submit_status']}",
            f"- 环境释放：{record['env_cleanup_status']}",
            "",
            "## 解题思路摘要",
            record["findings_summary"] or "本次运行未留下可用摘要，需结合 trace 人工补全。",
            "",
            "## 关键步骤与命令",
            *(trace_excerpt or ["- 未提取到关键 trace，请人工查看原始日志。"]),
            "",
            "## 复现备注",
            reproduction_note,
            "",
        ]
    )

    output_path.write_text(body, encoding="utf-8")
    return str(output_path)
```

- [ ] **Step 5: 运行 writeup 测试，确认输出结构稳定**

Run: `uv run pytest tests/test_writeups.py -q`  
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add tests/test_writeups.py backend/solver_base.py backend/agents/solver.py backend/agents/codex_solver.py backend/agents/claude_solver.py backend/solve_lifecycle.py backend/writeups.py
git commit -m "feat: 增加统一结果结构与中文 writeup 生成器"
```

### Task 3: 给平台协议补上环境释放能力

**Files:**
- Modify: `tests/test_lingxu_event_ctf_client.py`
- Modify: `backend/platforms/base.py`
- Modify: `backend/ctfd.py`
- Modify: `backend/platforms/lingxu_event_ctf.py`
- Test: `tests/test_lingxu_event_ctf_client.py`

- [ ] **Step 1: 先写凌虚环境释放接口测试**

```python
@pytest.mark.asyncio
async def test_release_challenge_env_posts_release_endpoint_with_csrf() -> None:
    seen_requests: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append((request.method, request.url.path, request.headers.get("x-csrftoken")))
        assert request.content == b""
        return httpx.Response(200, json={"status": 1, "msg": "释放成功"})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )
    meta = ChallengeMeta(
        name="Warmup Task",
        platform="lingxu-event-ctf",
        event_id=42,
        platform_challenge_id=137,
    )

    try:
        await client.release_challenge_env(meta)
    finally:
        await client.close()

    assert seen_requests == [("POST", "/event/42/ctf/137/release/", "csrf456")]


@pytest.mark.asyncio
async def test_release_challenge_env_omits_csrf_when_cookie_has_no_token() -> None:
    seen_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("x-csrftoken"))
        return httpx.Response(200, json={"status": 1, "msg": "释放成功"})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123",
        transport=httpx.MockTransport(handler),
    )

    try:
        await client.release_challenge_env({"platform_challenge_id": 137})
    finally:
        await client.close()

    assert seen_headers == [None]
```

- [ ] **Step 2: 运行测试，确认协议还没有释放方法**

Run: `uv run pytest tests/test_lingxu_event_ctf_client.py -q`  
Expected: FAIL because `CompetitionPlatformClient` / `LingxuEventCTFClient` 还没有 `release_challenge_env()`

- [ ] **Step 3: 在平台协议与两个平台实现中补齐释放接口**

```python
@runtime_checkable
class CompetitionPlatformClient(Protocol):
    async def validate_access(self) -> None:
        pass

    async def fetch_challenge_stubs(self) -> list[dict[str, Any]]:
        pass

    async def fetch_all_challenges(self) -> list[dict[str, Any]]:
        pass

    async def fetch_solved_names(self) -> set[str]:
        pass

    async def pull_challenge(self, challenge: dict[str, Any], output_dir: str) -> str:
        pass

    async def prepare_challenge(self, challenge_dir: str) -> None:
        pass

    async def submit_flag(self, challenge_ref: Any, flag: str) -> Any:
        pass

    async def release_challenge_env(self, challenge_ref: Any) -> None:
        pass

    async def close(self) -> None:
        pass
```

```python
async def release_challenge_env(self, challenge_ref: Any) -> None:
    return None
```

```python
async def release_challenge_env(self, challenge_ref: Any) -> None:
    challenge_id = self._platform_challenge_id_from_ref(challenge_ref)
    event_id = self._event_id_from_ref(challenge_ref)

    response, payload = await self._post(f"/event/{event_id}/ctf/{challenge_id}/release/")
    message = self._extract_message(payload)
    if response.status_code >= 400:
        raise RuntimeError(message or f"release failed with HTTP {response.status_code}")
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(message or "release failed")
```

- [ ] **Step 4: 重新运行凌虚客户端测试**

Run: `uv run pytest tests/test_lingxu_event_ctf_client.py -q`  
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tests/test_lingxu_event_ctf_client.py backend/platforms/base.py backend/ctfd.py backend/platforms/lingxu_event_ctf.py
git commit -m "feat: 增加平台环境释放能力"
```

### Task 4: 把收尾逻辑串进 swarm 完成路径

**Files:**
- Modify: `tests/test_coordinator_platform_flow.py`
- Modify: `backend/deps.py`
- Modify: `backend/agents/swarm.py`
- Modify: `backend/solve_lifecycle.py`
- Modify: `backend/agents/coordinator_core.py`
- Test: `tests/test_coordinator_platform_flow.py`
- Test: `tests/test_writeups.py`

- [ ] **Step 1: 在协调器流程测试里固定“确认提交后释放环境并写出 writeup”的行为**

```python
@pytest.mark.asyncio
async def test_finalize_swarm_result_releases_env_and_writes_writeup(tmp_path: Path) -> None:
    platform = FakePlatform()
    settings = make_settings()
    settings.writeup_mode = "confirmed"
    settings.writeup_dir = str(tmp_path / "writeups")
    deps = CoordinatorDeps(
        ctfd=platform,
        cost_tracker=CostTracker(),
        settings=settings,
        no_submit=False,
    )
    deps.released_envs = set()

    challenge_dir = tmp_path / "echo-2483"
    challenge_dir.mkdir()
    meta = ChallengeMeta(
        name="echo",
        platform="lingxu-event-ctf",
        event_id=198,
        platform_challenge_id=2483,
        requires_env_start=True,
    )
    result = SolverResult(
        flag="flag{real}",
        status=FLAG_FOUND,
        findings_summary="格式化字符串打 GOT。",
        step_count=6,
        cost_usd=0.21,
        log_path=str(tmp_path / "trace.jsonl"),
        model_spec="codex/gpt-5.4",
    )

    class FakeSwarm:
        confirmed_flag = "flag{real}"
        confirmed_submit_status = "correct"
        confirmed_submit_display = 'CORRECT — "flag{real}" accepted.'
        confirmed_submit_message = ""

    record = await finalize_swarm_result(
        deps=deps,
        challenge_name="echo",
        challenge_dir=str(challenge_dir),
        meta=meta,
        swarm=FakeSwarm(),
        result=result,
    )

    assert platform.released == [meta]
    assert record["confirmed"] is True
    assert record["submit_status"] == "correct"
    assert record["env_cleanup_status"] == "released"
    assert record["writeup_status"] == "generated"
    assert record["writeup_path"].endswith("writeups/lingxu-event-ctf-198/echo.md")


@pytest.mark.asyncio
async def test_finalize_swarm_result_skips_release_but_still_writes_on_dry_run(tmp_path: Path) -> None:
    platform = FakePlatform()
    settings = make_settings()
    settings.writeup_mode = "solved"
    settings.writeup_dir = str(tmp_path / "writeups")
    deps = CoordinatorDeps(
        ctfd=platform,
        cost_tracker=CostTracker(),
        settings=settings,
        no_submit=True,
    )
    deps.released_envs = set()

    challenge_dir = tmp_path / "rsa-2485"
    challenge_dir.mkdir()
    meta = ChallengeMeta(name="rsa", platform="lingxu-event-ctf", event_id=198, platform_challenge_id=2485, requires_env_start=True)
    result = SolverResult(
        flag="flag{offline}",
        status=FLAG_FOUND,
        findings_summary="分解 N 后恢复私钥。",
        step_count=4,
        cost_usd=0.11,
        log_path=str(tmp_path / "trace.jsonl"),
        model_spec="codex/gpt-5.4-mini",
    )

    class FakeSwarm:
        confirmed_flag = None
        confirmed_submit_status = ""
        confirmed_submit_display = ""
        confirmed_submit_message = ""

    record = await finalize_swarm_result(
        deps=deps,
        challenge_name="rsa",
        challenge_dir=str(challenge_dir),
        meta=meta,
        swarm=FakeSwarm(),
        result=result,
    )

    assert platform.released == []
    assert record["confirmed"] is False
    assert record["env_cleanup_status"] == "skipped"
    assert record["writeup_status"] == "generated"
    assert "未自动提交" in Path(record["writeup_path"]).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_finalize_swarm_result_records_release_failure_without_breaking_success(tmp_path: Path) -> None:
    platform = FakePlatform()
    platform.release_error = RuntimeError("release failed")
    settings = make_settings()
    settings.writeup_mode = "confirmed"
    settings.writeup_dir = str(tmp_path / "writeups")
    deps = CoordinatorDeps(ctfd=platform, cost_tracker=CostTracker(), settings=settings, no_submit=False)
    deps.released_envs = set()

    challenge_dir = tmp_path / "web-3001"
    challenge_dir.mkdir()
    meta = ChallengeMeta(name="web", platform="lingxu-event-ctf", event_id=198, platform_challenge_id=3001, requires_env_start=True)
    result = SolverResult(
        flag="flag{ok}",
        status=FLAG_FOUND,
        findings_summary="FastCGI 参数注入拿到命令执行。",
        step_count=5,
        cost_usd=0.14,
        log_path=str(tmp_path / "trace.jsonl"),
        model_spec="codex/gpt-5.4",
    )

    class FakeSwarm:
        confirmed_flag = "flag{ok}"
        confirmed_submit_status = "correct"
        confirmed_submit_display = 'CORRECT — "flag{ok}" accepted.'
        confirmed_submit_message = ""

    record = await finalize_swarm_result(
        deps=deps,
        challenge_name="web",
        challenge_dir=str(challenge_dir),
        meta=meta,
        swarm=FakeSwarm(),
        result=result,
    )

    assert record["confirmed"] is True
    assert record["env_cleanup_status"] == "failed"
    assert "release failed" in record["env_cleanup_error"]


@pytest.mark.asyncio
async def test_finalize_swarm_result_records_writeup_failure_without_crashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform = FakePlatform()
    settings = make_settings()
    settings.writeup_mode = "confirmed"
    settings.writeup_dir = str(tmp_path / "writeups")
    deps = CoordinatorDeps(ctfd=platform, cost_tracker=CostTracker(), settings=settings, no_submit=False)
    deps.released_envs = set()

    challenge_dir = tmp_path / "misc-3002"
    challenge_dir.mkdir()
    meta = ChallengeMeta(name="misc", platform="lingxu-event-ctf", event_id=198, platform_challenge_id=3002)
    result = SolverResult(
        flag="flag{ok}",
        status=FLAG_FOUND,
        findings_summary="binwalk 分离出内嵌压缩包。",
        step_count=3,
        cost_usd=0.09,
        log_path=str(tmp_path / "trace.jsonl"),
        model_spec="codex/gpt-5.4-mini",
    )

    class FakeSwarm:
        confirmed_flag = "flag{ok}"
        confirmed_submit_status = "correct"
        confirmed_submit_display = 'CORRECT — "flag{ok}" accepted.'
        confirmed_submit_message = ""

    def boom(**kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("backend.solve_lifecycle.write_writeup", boom)

    record = await finalize_swarm_result(
        deps=deps,
        challenge_name="misc",
        challenge_dir=str(challenge_dir),
        meta=meta,
        swarm=FakeSwarm(),
        result=result,
    )

    assert record["confirmed"] is True
    assert record["writeup_status"] == "failed"
    assert "disk full" in record["writeup_error"]
    assert record["writeup_path"] == ""
```

- [ ] **Step 2: 运行测试，确认当前 swarm 完成后还没有统一收尾**

Run: `uv run pytest tests/test_coordinator_platform_flow.py tests/test_writeups.py -q`  
Expected: FAIL because `CoordinatorDeps` 还没有 `released_envs`，`ChallengeSwarm` 也没有确认提交状态字段，`finalize_swarm_result()` 尚不存在

- [ ] **Step 3: 在 `CoordinatorDeps` 和 `ChallengeSwarm` 中补齐收尾所需状态**

```python
@dataclass
class CoordinatorDeps:
    ctfd: CompetitionPlatformClient
    cost_tracker: CostTracker
    settings: Any
    model_specs: list[str] = field(default_factory=list)
    challenges_root: str = "challenges"
    no_submit: bool = False
    max_concurrent_challenges: int = 10
    msg_port: int = 0
    coordinator_inbox: asyncio.Queue = field(default_factory=asyncio.Queue)
    operator_inbox: asyncio.Queue = field(default_factory=asyncio.Queue)
    swarms: dict[str, Any] = field(default_factory=dict)
    swarm_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    results: dict[str, dict] = field(default_factory=dict)
    challenge_dirs: dict[str, str] = field(default_factory=dict)
    challenge_metas: dict[str, Any] = field(default_factory=dict)
    released_envs: set[str] = field(default_factory=set)
```

```python
self.released: list[Any] = []
self.release_error: Exception | None = None

async def release_challenge_env(self, challenge_ref: Any) -> None:
    if self.release_error:
        raise self.release_error
    self.released.append(challenge_ref)
```

```python
winner: SolverResult | None = None
confirmed_flag: str | None = None
confirmed_submit_status: str = ""
confirmed_submit_display: str = ""
confirmed_submit_message: str = ""
_flag_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
```

```python
result = await self.ctfd.submit_flag(self.meta, normalized)
is_confirmed = result.status in ("correct", "already_solved")
if is_confirmed:
    self.confirmed_flag = normalized
    self.confirmed_submit_status = result.status
    self.confirmed_submit_display = result.display
    self.confirmed_submit_message = result.message
else:
    self._submit_count[model_spec] = wrong_count + 1
    self._last_submit_time[model_spec] = time.monotonic()
return result.display, is_confirmed
```

- [ ] **Step 4: 在 `backend/solve_lifecycle.py` 实现统一收尾 helper，并在 `coordinator_core` 调用**

```python
async def finalize_swarm_result(
    *,
    deps: CoordinatorDeps,
    challenge_name: str,
    challenge_dir: str,
    meta: ChallengeMeta,
    swarm,
    result: SolverResult | None,
) -> ChallengeResultRecord:
    if result is None:
        record = {
            "flag": None,
            "solve_status": "no_result",
            "submit_status": "not_attempted",
            "submit_display": "",
            "confirmed": False,
            "winner_model": "",
            "findings_summary": "",
            "log_path": "",
            "writeup_path": "",
            "writeup_status": "skipped",
            "writeup_error": "",
            "env_cleanup_status": "skipped",
            "env_cleanup_error": "",
        }
        deps.results[challenge_name] = record
        return record

    record = build_result_record(
        result=result,
        confirmed=bool(swarm.confirmed_flag),
        submit_status=swarm.confirmed_submit_status or ("dry_run" if deps.no_submit and result.status == FLAG_FOUND else "not_attempted"),
        submit_display=swarm.confirmed_submit_display or ("DRY RUN — 未自动提交。" if deps.no_submit and result.status == FLAG_FOUND else ""),
        env_cleanup_status="skipped",
        env_cleanup_error="",
    )

    if (
        swarm.confirmed_submit_status in ("correct", "already_solved")
        and meta.requires_env_start
        and not deps.no_submit
        and challenge_name not in deps.released_envs
    ):
        try:
            await deps.ctfd.release_challenge_env(meta)
            deps.released_envs.add(challenge_name)
            record["env_cleanup_status"] = "released"
        except Exception as exc:
            record["env_cleanup_status"] = "failed"
            record["env_cleanup_error"] = str(exc)

    if should_generate_writeup(deps.settings.writeup_mode, record):
        try:
            record["writeup_path"] = write_writeup(
                meta=meta,
                challenge_dir=challenge_dir,
                record=record,
                base_dir=deps.settings.writeup_dir,
            )
            record["writeup_status"] = "generated"
        except Exception as exc:
            record["writeup_path"] = ""
            record["writeup_status"] = "failed"
            record["writeup_error"] = str(exc)
    else:
        record["writeup_status"] = "skipped"

    deps.results[challenge_name] = record
    return record
```

```python
async def _run_and_cleanup() -> None:
    result = await swarm.run()
    await finalize_swarm_result(
        deps=deps,
        challenge_name=challenge_name,
        challenge_dir=deps.challenge_dirs[challenge_name],
        meta=meta,
        swarm=swarm,
        result=result,
    )
```

- [ ] **Step 5: 重新运行收尾相关测试**

Run: `uv run pytest tests/test_coordinator_platform_flow.py tests/test_writeups.py -q`  
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add tests/test_coordinator_platform_flow.py backend/deps.py backend/agents/swarm.py backend/solve_lifecycle.py backend/agents/coordinator_core.py
git commit -m "feat: 串起解题收尾与环境清理流程"
```

### Task 5: 在共享事件循环里实现全解后退出策略

**Files:**
- Modify: `tests/test_coordinator_platform_flow.py`
- Modify: `backend/agents/coordinator_loop.py`
- Test: `tests/test_coordinator_platform_flow.py`

- [ ] **Step 1: 先把 `wait|exit|idle` 的决策函数测试写出来**

```python
def test_all_solved_policy_wait_never_exits() -> None:
    settings = make_settings()
    settings.all_solved_policy = "wait"
    deps = CoordinatorDeps(ctfd=FakePlatform(), cost_tracker=CostTracker(), settings=settings)

    should_exit, idle_since = coordinator_loop._evaluate_all_solved_policy(
        deps=deps,
        known_challenges={"echo"},
        known_solved={"echo"},
        active_swarms=0,
        now=100.0,
        idle_since=None,
    )

    assert should_exit is False
    assert idle_since is None


def test_all_solved_policy_exit_exits_immediately() -> None:
    settings = make_settings()
    settings.all_solved_policy = "exit"
    deps = CoordinatorDeps(ctfd=FakePlatform(), cost_tracker=CostTracker(), settings=settings)

    should_exit, idle_since = coordinator_loop._evaluate_all_solved_policy(
        deps=deps,
        known_challenges={"echo"},
        known_solved={"echo"},
        active_swarms=0,
        now=100.0,
        idle_since=None,
    )

    assert should_exit is True
    assert idle_since == 100.0


def test_all_solved_policy_idle_waits_then_exits() -> None:
    settings = make_settings()
    settings.all_solved_policy = "idle"
    settings.all_solved_idle_seconds = 30
    deps = CoordinatorDeps(ctfd=FakePlatform(), cost_tracker=CostTracker(), settings=settings)

    first_exit, idle_since = coordinator_loop._evaluate_all_solved_policy(
        deps=deps,
        known_challenges={"echo"},
        known_solved={"echo"},
        active_swarms=0,
        now=100.0,
        idle_since=None,
    )
    second_exit, second_idle_since = coordinator_loop._evaluate_all_solved_policy(
        deps=deps,
        known_challenges={"echo"},
        known_solved={"echo"},
        active_swarms=0,
        now=131.0,
        idle_since=idle_since,
    )

    assert first_exit is False
    assert idle_since == 100.0
    assert second_exit is True
    assert second_idle_since == 100.0


def test_all_solved_policy_idle_resets_when_new_challenge_appears() -> None:
    settings = make_settings()
    settings.all_solved_policy = "idle"
    settings.all_solved_idle_seconds = 30
    deps = CoordinatorDeps(ctfd=FakePlatform(), cost_tracker=CostTracker(), settings=settings)

    _exit, idle_since = coordinator_loop._evaluate_all_solved_policy(
        deps=deps,
        known_challenges={"echo"},
        known_solved={"echo"},
        active_swarms=0,
        now=100.0,
        idle_since=None,
    )
    reset_exit, reset_idle_since = coordinator_loop._evaluate_all_solved_policy(
        deps=deps,
        known_challenges={"echo", "rsa"},
        known_solved={"echo"},
        active_swarms=0,
        now=110.0,
        idle_since=idle_since,
    )

    assert reset_exit is False
    assert reset_idle_since is None


def test_all_solved_policy_uses_local_results_in_dry_run() -> None:
    settings = make_settings()
    settings.all_solved_policy = "exit"
    deps = CoordinatorDeps(ctfd=FakePlatform(), cost_tracker=CostTracker(), settings=settings, no_submit=True)
    deps.results["echo"] = {"solve_status": FLAG_FOUND}

    should_exit, idle_since = coordinator_loop._evaluate_all_solved_policy(
        deps=deps,
        known_challenges={"echo"},
        known_solved=set(),
        active_swarms=0,
        now=200.0,
        idle_since=None,
    )

    assert should_exit is True
    assert idle_since == 200.0
```

- [ ] **Step 2: 运行测试，确认共享循环还没有该决策函数**

Run: `uv run pytest tests/test_coordinator_platform_flow.py -q`  
Expected: FAIL because `backend.agents.coordinator_loop` 还没有 `_evaluate_all_solved_policy()`

- [ ] **Step 3: 在共享循环里实现可测试的策略函数，并支持 dry-run 本地已解视图**

```python
def _effective_solved_names(deps: CoordinatorDeps, known_solved: set[str]) -> set[str]:
    effective = set(known_solved)
    if deps.no_submit:
        effective |= {
            name
            for name, record in deps.results.items()
            if record.get("solve_status") == FLAG_FOUND
        }
    return effective


def _evaluate_all_solved_policy(
    *,
    deps: CoordinatorDeps,
    known_challenges: set[str],
    known_solved: set[str],
    active_swarms: int,
    now: float,
    idle_since: float | None,
) -> tuple[bool, float | None]:
    policy = getattr(deps.settings, "all_solved_policy", "wait")
    solved_names = _effective_solved_names(deps, known_solved)
    all_solved = bool(known_challenges) and known_challenges <= solved_names and active_swarms == 0

    if policy == "wait":
        return False, None
    if not all_solved:
        return False, None
    if policy == "exit":
        return True, now

    if idle_since is None:
        return False, now
    if now - idle_since >= getattr(deps.settings, "all_solved_idle_seconds", 300):
        return True, idle_since
    return False, idle_since
```

- [ ] **Step 4: 在 `run_event_loop()` 里接入退出判定**

```python
        idle_since: float | None = None

        while True:
            events = []
            evt = await poller.get_event(timeout=5.0)
            if evt:
                events.append(evt)
            events.extend(poller.drain_events())

            now = asyncio.get_event_loop().time()
            active_count = sum(1 for task in deps.swarm_tasks.values() if not task.done())
            should_exit, idle_since = _evaluate_all_solved_policy(
                deps=deps,
                known_challenges=poller.known_challenges,
                known_solved=poller.known_solved,
                active_swarms=active_count,
                now=now,
                idle_since=idle_since,
            )
            if should_exit:
                logger.info(
                    "All challenges solved; policy=%s, active_swarms=%d, exiting coordinator loop",
                    deps.settings.all_solved_policy,
                    active_count,
                )
                break
```

- [ ] **Step 5: 重新运行协调器流程测试**

Run: `uv run pytest tests/test_coordinator_platform_flow.py -q`  
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add tests/test_coordinator_platform_flow.py backend/agents/coordinator_loop.py
git commit -m "feat: 增加全解后退出策略"
```

### Task 6: 更新 README 并做最终验证

**Files:**
- Modify: `README.md`
- Test: `README.md`

- [ ] **Step 1: 在 README 中新增自动收尾章节与三条中文示例命令**

```md
## 自动收尾、环境释放与 Writeup

- `--all-solved-policy wait|exit|idle`
  - `wait`：全部解出后继续等待新题
  - `exit`：全部解出且无活跃 swarm 后立即退出
  - `idle`：全部解出后继续等待一段时间，无新题再退出
- `--all-solved-idle-seconds N`
  - 仅在 `idle` 策略下生效
- `--writeup-mode off|confirmed|solved`
  - `off`：不生成题解
  - `confirmed`：只有平台确认提交成功后生成
  - `solved`：即使 `--no-submit` 也会生成草稿
- `--writeup-dir PATH`
  - writeup 输出根目录，默认是 `writeups/`

注意：

- 只有平台确认提交成功且题目 `requires_env_start: true` 时，才会自动释放环境
- `--no-submit` 不会自动释放环境
- `--coordinator none` 同样支持这三项能力
```

```bash
uv run ctf-solve \
  --platform lingxu-event-ctf \
  --platform-url https://ctf.yunyansec.com \
  --lingxu-event-id 198 \
  --lingxu-cookie-file ./lingxu.cookie \
  --coordinator codex \
  --models codex/gpt-5.4 \
  --models codex/gpt-5.4-mini \
  --all-solved-policy exit
```

```bash
uv run ctf-solve \
  --platform lingxu-event-ctf \
  --platform-url https://ctf.yunyansec.com \
  --lingxu-event-id 198 \
  --lingxu-cookie-file ./lingxu.cookie \
  --coordinator none \
  --models azure/gpt-5.4 \
  --models azure/gpt-5.4-mini \
  --all-solved-policy idle \
  --all-solved-idle-seconds 300 \
  --writeup-mode confirmed
```

```bash
uv run ctf-solve \
  --platform lingxu-event-ctf \
  --platform-url https://ctf.yunyansec.com \
  --lingxu-event-id 198 \
  --lingxu-cookie-file ./lingxu.cookie \
  --coordinator none \
  --models azure/gpt-5.4-mini \
  --max-challenges 5 \
  --no-submit \
  --writeup-mode solved \
  --writeup-dir ./writeups-dry-run
```

- [ ] **Step 2: 运行最终测试与 smoke**

Run: `uv run pytest tests/test_cli.py tests/test_writeups.py tests/test_lingxu_event_ctf_client.py tests/test_coordinator_platform_flow.py -q`  
Expected: PASS

Run: `uv run ruff check backend/cli.py backend/config.py backend/solver_base.py backend/agents/solver.py backend/agents/codex_solver.py backend/agents/claude_solver.py backend/agents/swarm.py backend/deps.py backend/solve_lifecycle.py backend/writeups.py backend/platforms/base.py backend/ctfd.py backend/platforms/lingxu_event_ctf.py backend/agents/coordinator_core.py backend/agents/coordinator_loop.py tests/test_cli.py tests/test_writeups.py tests/test_lingxu_event_ctf_client.py tests/test_coordinator_platform_flow.py`  
Expected: PASS

Run: `uv run ctf-solve --help`  
Expected: 输出中出现 `--all-solved-policy`、`--all-solved-idle-seconds`、`--writeup-mode`、`--writeup-dir`

- [ ] **Step 3: 提交**

```bash
git add README.md
git commit -m "docs: 更新自动收尾与 writeup 用法说明"
```
