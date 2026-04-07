# Capability Packs / Tool Contracts Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改写 solver 主执行循环的前提下，引入显式 capability 装配层，并把 `solver.py`、`codex_solver.py`、`claude_solver.py` 与 `prompts.py` 统一迁移到同一套 `ChallengeProfile + RuntimeProfile -> Capability Packs -> Tool Contracts -> ResolvedCapabilities` 链路。

**Architecture:** 先新增独立的 `backend/capabilities/` 包，里面只放纯数据模型、题目画像、运行时画像、pack 选择、contract 映射和 assembler。随后分三批迁移调用方：先迁 prompt，确保 `has_named_tools` 不再是主控制面；再迁主 `solver.py`；最后迁 `codex_solver.py` 与 `claude_solver.py`。整个过程保持“工具实现不动、执行循环不动、策略层不动”，只重构执行面的能力装配边界。

**Tech Stack:** Python 3.14, dataclasses, enum, pydantic-ai, pytest, Ruff

---

## Scope Check

这份 spec 只覆盖一个独立子系统：solver 执行面的 capability 抽象与装配，不包含 coordinator 主循环改写、memory/strategy 反馈闭环、长期知识库或递归 planner。因此它适合落成一份独立实现计划，不需要继续拆成多个子 spec。

---

## File Structure

- `backend/capabilities/__init__.py`
  责任：导出 capability 层公开对象，避免调用方散读内部模块。
- `backend/capabilities/specs.py`
  责任：定义 `CapabilitySpec`、`AttachmentHint`、`ResolvedCapabilities` 等稳定数据模型。
- `backend/capabilities/challenge_profile.py`
  责任：从 `ChallengeMeta + distfile_names + connection_info` 提炼题目画像。
- `backend/capabilities/runtime_profile.py`
  责任：定义 `RuntimeProfile` 和现有三类 solver runtime 的 helper 构造函数。
- `backend/capabilities/packs.py`
  责任：根据 `ChallengeProfile` 选择 capability packs，并展开为能力集合。
- `backend/capabilities/contracts.py`
  责任：把能力映射成当前 runtime 下的工具暴露、动态工具描述和 prompt 片段。
- `backend/capabilities/assembler.py`
  责任：统一执行 `profile -> packs -> contracts -> resolved` 装配流程。
- `backend/prompts.py`
  责任：继续负责 challenge/task prompt 主体，但不再承担 `has_named_tools` 分叉逻辑。
- `backend/agents/solver.py`
  责任：通过 assembler 获取 `tool_functions` 与 prompt capability fragments，替代硬编码 `_build_toolset()`。
- `backend/agents/codex_solver.py`
  责任：通过 assembler 获取 `dynamic_tool_specs` 与 prompt capability fragments，替代硬编码 `SANDBOX_TOOLS`。
- `backend/agents/claude_solver.py`
  责任：通过 assembler 获取 bash-only prompt fragments，替代 `has_named_tools=False` 分叉。
- `tests/test_capability_profiles.py`
  责任：验证题目画像和 runtime 画像。
- `tests/test_capability_assembler.py`
  责任：验证 pack 选择、contract 映射、装配结果稳定性。
- `tests/test_prompts.py`
  责任：验证 prompt 改为消费 capability fragments 后，关键提示语不退化。
- `tests/test_solver_capabilities.py`
  责任：验证主 solver、codex solver、claude solver 对 capability 装配的接线。
- `README.md`
  责任：在实现完成后补一小段 Capability Layer 架构说明。

---

### Task 1: 建立 capability 基础数据模型与画像入口

**Files:**
- Create: `backend/capabilities/__init__.py`
- Create: `backend/capabilities/specs.py`
- Create: `backend/capabilities/challenge_profile.py`
- Create: `backend/capabilities/runtime_profile.py`
- Create: `tests/test_capability_profiles.py`

- [ ] **Step 1: 先写题目画像与 runtime 画像失败测试**

```python
from pathlib import Path

from backend.capabilities.challenge_profile import build_challenge_profile
from backend.capabilities.runtime_profile import (
    claude_runtime_profile,
    codex_runtime_profile,
    solver_runtime_profile,
)
from backend.prompts import ChallengeMeta


def test_build_challenge_profile_detects_image_and_web_service(tmp_path: Path) -> None:
    distfiles = tmp_path / "distfiles"
    distfiles.mkdir()
    (distfiles / "badge.png").write_bytes(b"png")

    profile = build_challenge_profile(
        ChallengeMeta(
            name="imgweb",
            category="web",
            description="see image",
            connection_info="http://host.docker.internal:8080",
        ),
        ["badge.png"],
    )

    assert profile.challenge_name == "imgweb"
    assert profile.has_images is True
    assert profile.has_connection_info is True
    assert profile.connection_kind == "web"
    assert profile.needs_web_fetch is True
    assert profile.needs_flag_submission is True


def test_build_challenge_profile_marks_reverse_binary_analysis() -> None:
    profile = build_challenge_profile(
        ChallengeMeta(name="tea", category="reverse", description=""),
        ["Tea_or_Xtea.zip"],
    )

    assert profile.needs_binary_analysis is True
    assert profile.needs_oob_hooks is False


def test_runtime_profile_helpers_map_existing_solver_modes() -> None:
    assert solver_runtime_profile(use_vision=True).supports_named_tools is True
    assert solver_runtime_profile(use_vision=True).supports_dynamic_tools is False
    assert codex_runtime_profile(use_vision=True).supports_dynamic_tools is True
    assert claude_runtime_profile().prefers_bash_only is True
```

- [ ] **Step 2: 跑测试，确认模块尚不存在**

Run: `uv run pytest tests/test_capability_profiles.py -q`  
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.capabilities'`

- [ ] **Step 3: 写最小实现，建立稳定数据模型和 helper**

```python
# backend/capabilities/specs.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CapabilitySpec(str, Enum):
    SHELL_EXEC = "shell.exec"
    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    FILESYSTEM_LIST = "filesystem.list"
    FLAG_SUBMIT = "flag.submit"
    NETWORK_WEB_FETCH = "network.web_fetch"
    NETWORK_WEBHOOK_OOB = "network.webhook_oob"
    VISION_INSPECT_IMAGE = "vision.inspect_image"
    COORDINATION_FINDINGS = "coordination.findings"
    COORDINATION_NOTIFY = "coordination.notify"
    BINARY_ANALYSIS = "binary.analysis"


@dataclass(frozen=True)
class ChallengeProfile:
    challenge_name: str
    category: str
    distfile_names: tuple[str, ...]
    has_images: bool
    has_connection_info: bool
    connection_kind: str | None
    needs_binary_analysis: bool
    needs_web_fetch: bool
    needs_oob_hooks: bool
    needs_flag_submission: bool


@dataclass(frozen=True)
class RuntimeProfile:
    runtime_name: str
    supports_named_tools: bool
    supports_dynamic_tools: bool
    supports_vision: bool
    prefers_bash_only: bool


@dataclass(frozen=True)
class AttachmentHint:
    path: str
    suffix: str


@dataclass(frozen=True)
class ResolvedCapabilities:
    challenge_profile: ChallengeProfile
    runtime_profile: RuntimeProfile
    capabilities: frozenset[CapabilitySpec]
    tool_functions: tuple[object, ...] = ()
    dynamic_tool_specs: tuple[dict[str, object], ...] = ()
    prompt_fragments: tuple[str, ...] = ()
    attachment_hints: tuple[AttachmentHint, ...] = ()
    capability_summary: str = ""
```

```python
# backend/capabilities/challenge_profile.py
from __future__ import annotations

from pathlib import Path

from backend.capabilities.specs import ChallengeProfile
from backend.prompts import ChallengeMeta
from backend.tools.core import IMAGE_EXTS_FOR_VISION


def build_challenge_profile(meta: ChallengeMeta, distfile_names: list[str]) -> ChallengeProfile:
    conn = meta.connection_info.strip()
    connection_kind: str | None = None
    if conn.startswith("http://") or conn.startswith("https://"):
        connection_kind = "web"
    elif conn.startswith("nc "):
        connection_kind = "tcp"
    elif conn:
        connection_kind = "other"

    category = (meta.category or "").lower()
    has_images = any(Path(name).suffix.lower() in IMAGE_EXTS_FOR_VISION for name in distfile_names)
    needs_binary_analysis = category in {"reverse", "reversing", "re", "pwn", "binary", "misc", ""}
    needs_web_fetch = connection_kind == "web" or category == "web"
    needs_oob_hooks = category == "web"

    return ChallengeProfile(
        challenge_name=meta.name,
        category=meta.category,
        distfile_names=tuple(distfile_names),
        has_images=has_images,
        has_connection_info=bool(conn),
        connection_kind=connection_kind,
        needs_binary_analysis=needs_binary_analysis,
        needs_web_fetch=needs_web_fetch,
        needs_oob_hooks=needs_oob_hooks,
        needs_flag_submission=True,
    )
```

```python
# backend/capabilities/runtime_profile.py
from __future__ import annotations

from backend.capabilities.specs import RuntimeProfile


def solver_runtime_profile(*, use_vision: bool) -> RuntimeProfile:
    return RuntimeProfile(
        runtime_name="pydantic-named-tools",
        supports_named_tools=True,
        supports_dynamic_tools=False,
        supports_vision=use_vision,
        prefers_bash_only=False,
    )


def codex_runtime_profile(*, use_vision: bool) -> RuntimeProfile:
    return RuntimeProfile(
        runtime_name="codex-dynamic-tools",
        supports_named_tools=False,
        supports_dynamic_tools=True,
        supports_vision=use_vision,
        prefers_bash_only=False,
    )


def claude_runtime_profile() -> RuntimeProfile:
    return RuntimeProfile(
        runtime_name="claude-bash-only",
        supports_named_tools=False,
        supports_dynamic_tools=False,
        supports_vision=False,
        prefers_bash_only=True,
    )
```

```python
# backend/capabilities/__init__.py
from backend.capabilities.challenge_profile import build_challenge_profile
from backend.capabilities.runtime_profile import (
    claude_runtime_profile,
    codex_runtime_profile,
    solver_runtime_profile,
)
from backend.capabilities.specs import (
    AttachmentHint,
    CapabilitySpec,
    ChallengeProfile,
    ResolvedCapabilities,
    RuntimeProfile,
)
```

- [ ] **Step 4: 跑测试，确认基础模型成立**

Run: `uv run pytest tests/test_capability_profiles.py -q`  
Expected: PASS

- [ ] **Step 5: 提交基础画像与数据模型**

```bash
git add backend/capabilities/__init__.py backend/capabilities/specs.py backend/capabilities/challenge_profile.py backend/capabilities/runtime_profile.py tests/test_capability_profiles.py
git commit -m "feat: 增加 capability 基础画像模型"
```

---

### Task 2: 实现 pack 选择、tool contracts 与统一 assembler

**Files:**
- Create: `backend/capabilities/packs.py`
- Create: `backend/capabilities/contracts.py`
- Create: `backend/capabilities/assembler.py`
- Create: `tests/test_capability_assembler.py`

- [ ] **Step 1: 先写 assembler 失败测试**

```python
from backend.capabilities.assembler import resolve_capabilities
from backend.capabilities.challenge_profile import build_challenge_profile
from backend.capabilities.runtime_profile import claude_runtime_profile, codex_runtime_profile, solver_runtime_profile
from backend.capabilities.specs import CapabilitySpec
from backend.prompts import ChallengeMeta


def test_resolve_capabilities_for_named_tool_solver_includes_view_image_and_submit() -> None:
    profile = build_challenge_profile(
        ChallengeMeta(name="img", category="web", description="", connection_info="https://example.com"),
        ["images/badge.png"],
    )

    resolved = resolve_capabilities(profile, solver_runtime_profile(use_vision=True))

    assert CapabilitySpec.VISION_INSPECT_IMAGE in resolved.capabilities
    assert CapabilitySpec.FLAG_SUBMIT in resolved.capabilities
    assert any(getattr(tool, "__name__", "") == "view_image" for tool in resolved.tool_functions)
    assert any("view_image" in fragment for fragment in resolved.prompt_fragments)


def test_resolve_capabilities_for_codex_runtime_builds_dynamic_tool_specs() -> None:
    profile = build_challenge_profile(ChallengeMeta(name="echo", category="web", description=""), [])

    resolved = resolve_capabilities(profile, codex_runtime_profile(use_vision=False))

    tool_names = [tool["name"] for tool in resolved.dynamic_tool_specs]
    assert "bash" in tool_names
    assert "submit_flag" in tool_names
    assert "view_image" not in tool_names


def test_resolve_capabilities_for_claude_runtime_uses_prompt_only_for_submission_and_images() -> None:
    profile = build_challenge_profile(
        ChallengeMeta(name="img", category="web", description="", connection_info="https://example.com"),
        ["flag.png"],
    )

    resolved = resolve_capabilities(profile, claude_runtime_profile())

    assert resolved.tool_functions == ()
    assert resolved.dynamic_tool_specs == ()
    assert any("submit_flag '<flag>'" in fragment for fragment in resolved.prompt_fragments)
    assert any("exiftool" in fragment for fragment in resolved.prompt_fragments)
```

- [ ] **Step 2: 跑测试，确认 assembler 还不存在**

Run: `uv run pytest tests/test_capability_assembler.py -q`  
Expected: FAIL with `ModuleNotFoundError` for `backend.capabilities.assembler`

- [ ] **Step 3: 实现 pack 选择和 contract 映射**

```python
# backend/capabilities/packs.py
from __future__ import annotations

from backend.capabilities.specs import CapabilitySpec, ChallengeProfile

CORE_PACK = frozenset(
    {
        CapabilitySpec.SHELL_EXEC,
        CapabilitySpec.FILESYSTEM_READ,
        CapabilitySpec.FILESYSTEM_WRITE,
        CapabilitySpec.FILESYSTEM_LIST,
        CapabilitySpec.FLAG_SUBMIT,
        CapabilitySpec.COORDINATION_FINDINGS,
        CapabilitySpec.COORDINATION_NOTIFY,
    }
)


def select_capabilities(profile: ChallengeProfile) -> frozenset[CapabilitySpec]:
    capabilities = set(CORE_PACK)
    if profile.needs_web_fetch:
        capabilities.add(CapabilitySpec.NETWORK_WEB_FETCH)
    if profile.needs_oob_hooks:
        capabilities.add(CapabilitySpec.NETWORK_WEBHOOK_OOB)
    if profile.has_images:
        capabilities.add(CapabilitySpec.VISION_INSPECT_IMAGE)
    if profile.needs_binary_analysis:
        capabilities.add(CapabilitySpec.BINARY_ANALYSIS)
    return frozenset(sorted(capabilities, key=lambda item: item.value))
```

```python
# backend/capabilities/contracts.py
from __future__ import annotations

from pathlib import Path

from backend.capabilities.specs import AttachmentHint, CapabilitySpec, ChallengeProfile, RuntimeProfile
from backend.tools.flag import submit_flag
from backend.tools.sandbox import (
    bash,
    check_findings,
    list_files,
    notify_coordinator,
    read_file,
    web_fetch,
    webhook_create,
    webhook_get_requests,
    write_file,
)
from backend.tools.vision import view_image


_IMAGE_HINT = "**IMAGE: call `view_image` immediately** (fix magic bytes first if corrupt)"


def build_tool_functions(capabilities: frozenset[CapabilitySpec], runtime: RuntimeProfile) -> tuple[object, ...]:
    if not runtime.supports_named_tools:
        return ()
    tool_map = {
        CapabilitySpec.SHELL_EXEC: bash,
        CapabilitySpec.FILESYSTEM_READ: read_file,
        CapabilitySpec.FILESYSTEM_WRITE: write_file,
        CapabilitySpec.FILESYSTEM_LIST: list_files,
        CapabilitySpec.FLAG_SUBMIT: submit_flag,
        CapabilitySpec.NETWORK_WEB_FETCH: web_fetch,
        CapabilitySpec.COORDINATION_FINDINGS: check_findings,
        CapabilitySpec.COORDINATION_NOTIFY: notify_coordinator,
    }
    ordered = [tool_map[cap] for cap in sorted(capabilities, key=lambda item: item.value) if cap in tool_map]
    if CapabilitySpec.NETWORK_WEBHOOK_OOB in capabilities:
        ordered.extend([webhook_create, webhook_get_requests])
    if CapabilitySpec.VISION_INSPECT_IMAGE in capabilities and runtime.supports_vision:
        ordered.append(view_image)
    return tuple(ordered)


def build_dynamic_tool_specs(capabilities: frozenset[CapabilitySpec], runtime: RuntimeProfile) -> tuple[dict[str, object], ...]:
    if not runtime.supports_dynamic_tools:
        return ()
    specs: list[dict[str, object]] = [
        {
            "name": "bash",
            "description": "Execute a bash command in the Docker sandbox.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "default": 60},
                },
                "required": ["command"],
            },
        },
        {
            "name": "read_file",
            "description": "Read a file from the sandbox container.",
            "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        },
        {
            "name": "write_file",
            "description": "Write a file into the sandbox container.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
        {
            "name": "list_files",
            "description": "List files in a directory in the sandbox.",
            "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "default": "/challenge/distfiles"}}},
        },
        {
            "name": "submit_flag",
            "description": "Submit a flag to CTFd. Returns CORRECT, ALREADY SOLVED, or INCORRECT.",
            "inputSchema": {"type": "object", "properties": {"flag": {"type": "string"}}, "required": ["flag"]},
        },
    ]
    if CapabilitySpec.NETWORK_WEB_FETCH in capabilities:
        specs.append(
            {
                "name": "web_fetch",
                "description": "Fetch a URL from the host network.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "method": {"type": "string", "default": "GET"},
                        "body": {"type": "string", "default": ""},
                    },
                    "required": ["url"],
                },
            }
        )
    if CapabilitySpec.NETWORK_WEBHOOK_OOB in capabilities:
        specs.extend(
            [
                {
                    "name": "webhook_create",
                    "description": "Create a webhook.site token for out-of-band HTTP callbacks (XSS, SSRF, bot challenges).",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                {
                    "name": "webhook_get_requests",
                    "description": "Retrieve HTTP requests received by a webhook.site token.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"uuid": {"type": "string"}},
                        "required": ["uuid"],
                    },
                },
            ]
        )
    if CapabilitySpec.VISION_INSPECT_IMAGE in capabilities and runtime.supports_vision:
        specs.append(
            {
                "name": "view_image",
                "description": "View an image file from the sandbox for visual/steg analysis.",
                "inputSchema": {"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]},
            }
        )
    if CapabilitySpec.COORDINATION_NOTIFY in capabilities:
        specs.append(
            {
                "name": "notify_coordinator",
                "description": "Send a strategic message to the coordinator.",
                "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
            }
        )
    return tuple(specs)


def build_prompt_fragments(capabilities: frozenset[CapabilitySpec], runtime: RuntimeProfile) -> tuple[str, ...]:
    fragments: list[str] = []
    if CapabilitySpec.VISION_INSPECT_IMAGE in capabilities:
        if runtime.supports_named_tools or runtime.supports_dynamic_tools:
            fragments.append("**Images: call `view_image` FIRST, before any other analysis.**")
        else:
            fragments.append("**Images: use `exiftool`, `steghide`, `zsteg`, `strings`, `xxd` via bash.**")
    if CapabilitySpec.NETWORK_WEBHOOK_OOB in capabilities:
        fragments.append("Web: fuzz params, check JS source, cookies, robots.txt. For XSS/SSRF: use `webhook_create`.")
    if CapabilitySpec.FLAG_SUBMIT in capabilities:
        fragments.append(
            "**Verify every candidate with `submit_flag`** before reporting."
            if not runtime.prefers_bash_only
            else "**Verify every candidate with `submit_flag '<flag>'`** (bash command) before reporting."
        )
    if CapabilitySpec.BINARY_ANALYSIS in capabilities:
        fragments.append("Binary: use pyghidra, r2, gdb, angr, capstone when the challenge includes binaries.")
    return tuple(fragments)


def build_attachment_hints(
    profile: ChallengeProfile,
    capabilities: frozenset[CapabilitySpec],
    runtime: RuntimeProfile,
) -> tuple[AttachmentHint, ...]:
    if CapabilitySpec.VISION_INSPECT_IMAGE not in capabilities:
        return ()
    if not (runtime.supports_named_tools or runtime.supports_dynamic_tools):
        return ()
    hints = []
    for name in profile.distfile_names:
        if Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
            hints.append(AttachmentHint(path=name, suffix=_IMAGE_HINT))
    return tuple(hints)
```

```python
# backend/capabilities/assembler.py
from __future__ import annotations

from backend.capabilities.contracts import (
    build_attachment_hints,
    build_dynamic_tool_specs,
    build_prompt_fragments,
    build_tool_functions,
)
from backend.capabilities.packs import select_capabilities
from backend.capabilities.specs import ResolvedCapabilities


def resolve_capabilities(profile, runtime):
    capabilities = select_capabilities(profile)
    tool_functions = build_tool_functions(capabilities, runtime)
    dynamic_tool_specs = build_dynamic_tool_specs(capabilities, runtime)
    prompt_fragments = build_prompt_fragments(capabilities, runtime)
    attachment_hints = build_attachment_hints(profile, capabilities, runtime)
    capability_summary = ", ".join(cap.value for cap in sorted(capabilities, key=lambda item: item.value))
    return ResolvedCapabilities(
        challenge_profile=profile,
        runtime_profile=runtime,
        capabilities=capabilities,
        tool_functions=tool_functions,
        dynamic_tool_specs=dynamic_tool_specs,
        prompt_fragments=prompt_fragments,
        attachment_hints=attachment_hints,
        capability_summary=capability_summary,
    )
```

- [ ] **Step 4: 细化 contract 实现，确保 runtime 分支互斥且顺序稳定**

```python
def build_attachment_hints(
    profile: ChallengeProfile,
    capabilities: frozenset[CapabilitySpec],
    runtime: RuntimeProfile,
) -> tuple[AttachmentHint, ...]:
    if CapabilitySpec.VISION_INSPECT_IMAGE not in capabilities:
        return ()
    if not (runtime.supports_named_tools or runtime.supports_dynamic_tools):
        return ()
    return tuple(
        AttachmentHint(path=name, suffix=_IMAGE_HINT)
        for name in profile.distfile_names
        if Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
    )
```

- [ ] **Step 5: 跑装配测试，确认 named/dynamic/bash-only 三条路径都成立**

Run: `uv run pytest tests/test_capability_profiles.py tests/test_capability_assembler.py -q`  
Expected: PASS

- [ ] **Step 6: 提交 capability assembler**

```bash
git add backend/capabilities/packs.py backend/capabilities/contracts.py backend/capabilities/assembler.py tests/test_capability_assembler.py
git commit -m "feat: 增加 capability 装配链路"
```

---

### Task 3: 迁移 prompt builder，让 capability fragments 取代 `has_named_tools`

**Files:**
- Modify: `backend/prompts.py`
- Modify: `tests/test_prompts.py`

- [ ] **Step 1: 先补 prompt 回归测试**

```python
from backend.capabilities import (
    AttachmentHint,
    ChallengeProfile,
    ResolvedCapabilities,
    RuntimeProfile,
)
from backend.capabilities.specs import CapabilitySpec


def _resolved(*, fragments: tuple[str, ...], attachment_hints: tuple[AttachmentHint, ...] = ()) -> ResolvedCapabilities:
    return ResolvedCapabilities(
        challenge_profile=ChallengeProfile(
            challenge_name="img",
            category="web",
            distfile_names=(),
            has_images=True,
            has_connection_info=False,
            connection_kind=None,
            needs_binary_analysis=False,
            needs_web_fetch=True,
            needs_oob_hooks=False,
            needs_flag_submission=True,
        ),
        runtime_profile=RuntimeProfile(
            runtime_name="pydantic-named-tools",
            supports_named_tools=True,
            supports_dynamic_tools=False,
            supports_vision=True,
            prefers_bash_only=False,
        ),
        capabilities=frozenset({CapabilitySpec.VISION_INSPECT_IMAGE, CapabilitySpec.FLAG_SUBMIT}),
        prompt_fragments=fragments,
        attachment_hints=attachment_hints,
        capability_summary="flag.submit, vision.inspect_image",
    )


def test_build_prompt_uses_attachment_hints_from_resolved_capabilities(tmp_path: Path) -> None:
    prompt = build_prompt(
        ChallengeMeta(name="img", category="web", description="see image"),
        ["images/badge.png"],
        resolved_capabilities=_resolved(
            fragments=("**Images: call `view_image` FIRST, before any other analysis.**",),
            attachment_hints=(
                AttachmentHint(
                    path="images/badge.png",
                    suffix="**IMAGE: call `view_image` immediately** (fix magic bytes first if corrupt)",
                ),
            ),
        ),
    )

    assert "**IMAGE: call `view_image` immediately**" in prompt
    assert "**Images: call `view_image` FIRST" in prompt


def test_build_prompt_uses_bash_only_submission_hint_when_named_tools_absent() -> None:
    prompt = build_prompt(
        ChallengeMeta(name="img", category="web", description="see image"),
        [],
        resolved_capabilities=_resolved(
            fragments=("**Verify every candidate with `submit_flag '<flag>'`** (bash command) before reporting.",),
        ),
    )

    assert "submit_flag '<flag>'" in prompt
    assert "has_named_tools" not in prompt
```

- [ ] **Step 2: 跑 prompt 测试，确认签名仍停留在旧逻辑**

Run: `uv run pytest tests/test_prompts.py -q`  
Expected: FAIL because `build_prompt()` still expects `has_named_tools`

- [ ] **Step 3: 重构 `build_prompt()` 签名和图片/指令片段装配**

```python
def build_prompt(
    meta: ChallengeMeta,
    distfile_names: list[str],
    container_arch: str = "unknown",
    resolved_capabilities: ResolvedCapabilities | None = None,
) -> str:
    resolved = resolved_capabilities
    attachment_suffixes = {
        hint.path: hint.suffix
        for hint in (resolved.attachment_hints if resolved else ())
    }
    capability_fragments = list(resolved.prompt_fragments if resolved else ())
```

```python
    if distfile_names:
        lines.append("## Attached Files")
        for name in distfile_names:
            suffix = ""
            if name in attachment_suffixes:
                suffix = f"  <- {attachment_suffixes[name]}"
            lines.append(f"- `/challenge/distfiles/{name}`{suffix}")
        lines.append("")
```

```python
    lines += [
        "",
        "## Instructions",
        "**Use tools immediately. Do not describe — execute.**",
        "",
        "1. " + ("Connect to the service now." if conn_info else "Inspect distfiles now."),
        "2. Keep using tools until you have the flag.",
        "3. **Be creative and thorough** — try the obvious path, then explore further:",
        "   - Hidden files, env vars, backup files, HTTP headers, error messages, timing, encoding tricks.",
    ]
    for fragment in capability_fragments:
        lines.append(f"   - {fragment}")
```

- [ ] **Step 4: 删除 `has_named_tools` 分叉并补默认 fallback**

```python
DEFAULT_PROMPT_FRAGMENTS = (
    "**Verify every candidate with `submit_flag`** before reporting.",
)

if not capability_fragments:
    capability_fragments = list(DEFAULT_PROMPT_FRAGMENTS)
```

- [ ] **Step 5: 跑 prompt 测试，确认行为不退化**

Run: `uv run pytest tests/test_prompts.py -q`  
Expected: PASS

- [ ] **Step 6: 提交 prompt capability 迁移**

```bash
git add backend/prompts.py tests/test_prompts.py
git commit -m "refactor: 让 prompt 消费 capability 片段"
```

---

### Task 4: 迁移主 `solver.py` 到 capability toolset

**Files:**
- Modify: `backend/agents/solver.py`
- Create: `tests/test_solver_capabilities.py`

- [ ] **Step 1: 先写主 solver 的接线失败测试**

```python
from backend.agents.solver import _build_resolved_capabilities
from backend.prompts import ChallengeMeta


def test_solver_build_resolved_capabilities_includes_named_tools_for_vision(tmp_path: Path) -> None:
    distfiles = tmp_path / "distfiles"
    distfiles.mkdir()
    (distfiles / "flag.png").write_bytes(b"png")

    resolved = _build_resolved_capabilities(
        challenge_dir=str(tmp_path),
        meta=ChallengeMeta(name="img", category="web", description="see image"),
        use_vision=True,
    )

    tool_names = [tool.__name__ for tool in resolved.tool_functions]
    assert "bash" in tool_names
    assert "submit_flag" in tool_names
    assert "view_image" in tool_names
```

- [ ] **Step 2: 跑测试，确认 helper 尚不存在**

Run: `uv run pytest tests/test_solver_capabilities.py -q`  
Expected: FAIL with `ImportError` for `_build_resolved_capabilities`

- [ ] **Step 3: 提取 helper，先装配 prompt 和 toolset，再接回 `Solver.start()`**

```python
# backend/agents/solver.py
from backend.capabilities import build_challenge_profile, solver_runtime_profile
from backend.capabilities.assembler import resolve_capabilities


def _build_resolved_capabilities(
    *,
    challenge_dir: str,
    meta: ChallengeMeta,
    use_vision: bool,
):
    distfile_names = list_distfiles(challenge_dir)
    challenge_profile = build_challenge_profile(meta, distfile_names)
    runtime_profile = solver_runtime_profile(use_vision=use_vision)
    return resolve_capabilities(challenge_profile, runtime_profile)
```

```python
def _build_toolset(resolved_capabilities: ResolvedCapabilities) -> FunctionToolset[SolverDeps]:
    return FunctionToolset(tools=list(resolved_capabilities.tool_functions), max_retries=4)
```

```python
        distfile_names = list_distfiles(self.challenge_dir)
        resolved_capabilities = _build_resolved_capabilities(
            challenge_dir=self.challenge_dir,
            meta=self.meta,
            use_vision=self.use_vision,
        )
        system_prompt = build_prompt(
            self.meta,
            distfile_names,
            container_arch=container_arch,
            resolved_capabilities=resolved_capabilities,
        )
        raw_toolset = _build_toolset(resolved_capabilities)
```

- [ ] **Step 4: 跑主 solver capability 测试**

Run: `uv run pytest tests/test_solver_capabilities.py -q`  
Expected: PASS

- [ ] **Step 5: 提交主 solver 接线迁移**

```bash
git add backend/agents/solver.py tests/test_solver_capabilities.py
git commit -m "refactor: 让 solver 使用 capability toolset"
```

---

### Task 5: 迁移 `codex_solver.py` 到 dynamic tool contracts

**Files:**
- Modify: `backend/agents/codex_solver.py`
- Modify: `tests/test_solver_capabilities.py`

- [ ] **Step 1: 为 codex dynamic tools 新增失败测试**

```python
from backend.agents.codex_solver import _build_codex_resolved_capabilities
from backend.prompts import ChallengeMeta


def test_codex_resolved_capabilities_build_dynamic_tool_specs(tmp_path: Path) -> None:
    distfiles = tmp_path / "distfiles"
    distfiles.mkdir()
    (distfiles / "flag.png").write_bytes(b"png")

    resolved = _build_codex_resolved_capabilities(
        challenge_dir=str(tmp_path),
        meta=ChallengeMeta(name="img", category="web", description="see image"),
        use_vision=True,
    )

    tool_names = [tool["name"] for tool in resolved.dynamic_tool_specs]
    assert "bash" in tool_names
    assert "submit_flag" in tool_names
    assert "view_image" in tool_names
```

- [ ] **Step 2: 跑测试，确认 codex 仍使用硬编码 `SANDBOX_TOOLS`**

Run: `uv run pytest tests/test_solver_capabilities.py::test_codex_resolved_capabilities_build_dynamic_tool_specs -q`  
Expected: FAIL with `ImportError` for `_build_codex_resolved_capabilities`

- [ ] **Step 3: 提取 codex helper，替换 `SANDBOX_TOOLS` 来源**

```python
# backend/agents/codex_solver.py
from backend.capabilities import build_challenge_profile, codex_runtime_profile
from backend.capabilities.assembler import resolve_capabilities


def _build_codex_resolved_capabilities(*, challenge_dir: str, meta: ChallengeMeta, use_vision: bool):
    distfile_names = list_distfiles(challenge_dir)
    return resolve_capabilities(
        build_challenge_profile(meta, distfile_names),
        codex_runtime_profile(use_vision=use_vision),
    )
```

```python
        distfile_names = list_distfiles(self.challenge_dir)
        resolved_capabilities = _build_codex_resolved_capabilities(
            challenge_dir=self.challenge_dir,
            meta=self.meta,
            use_vision=self.use_vision,
        )
        system_prompt = build_prompt(
            self.meta,
            distfile_names,
            container_arch=container_arch,
            resolved_capabilities=resolved_capabilities,
        )
        dynamic_tools = list(resolved_capabilities.dynamic_tool_specs)
```

```python
        tool_names = [t["name"] for t in dynamic_tools]
        sandbox_preamble = (
            "IMPORTANT: You are running inside a Docker sandbox. "
            "All files are under /challenge/ — distfiles at /challenge/distfiles/, "
            "workspace at /challenge/workspace/. Do NOT use any paths outside /challenge/. "
            f"Your tools: {', '.join(tool_names)}. Use these for ALL operations.\n\n"
        )
```

- [ ] **Step 4: 跑 codex capability 测试**

Run: `uv run pytest tests/test_solver_capabilities.py::test_codex_resolved_capabilities_build_dynamic_tool_specs -q`  
Expected: PASS

- [ ] **Step 5: 提交 codex dynamic tools 迁移**

```bash
git add backend/agents/codex_solver.py tests/test_solver_capabilities.py
git commit -m "refactor: 让 codex solver 使用 capability contracts"
```

---

### Task 6: 迁移 `claude_solver.py` 到 bash-only capability fragments

**Files:**
- Modify: `backend/agents/claude_solver.py`
- Modify: `tests/test_solver_capabilities.py`

- [ ] **Step 1: 为 claude bash-only prompt fragments 新增失败测试**

```python
from backend.agents.claude_solver import _build_claude_resolved_capabilities
from backend.prompts import ChallengeMeta


def test_claude_resolved_capabilities_use_prompt_only_fragments(tmp_path: Path) -> None:
    distfiles = tmp_path / "distfiles"
    distfiles.mkdir()
    (distfiles / "flag.png").write_bytes(b"png")

    resolved = _build_claude_resolved_capabilities(
        challenge_dir=str(tmp_path),
        meta=ChallengeMeta(name="img", category="web", description="see image"),
    )

    assert resolved.tool_functions == ()
    assert resolved.dynamic_tool_specs == ()
    assert any("submit_flag '<flag>'" in fragment for fragment in resolved.prompt_fragments)
    assert any("exiftool" in fragment for fragment in resolved.prompt_fragments)
```

- [ ] **Step 2: 跑测试，确认 helper 尚不存在**

Run: `uv run pytest tests/test_solver_capabilities.py::test_claude_resolved_capabilities_use_prompt_only_fragments -q`  
Expected: FAIL with `ImportError` for `_build_claude_resolved_capabilities`

- [ ] **Step 3: 提取 bash-only helper，并让 `build_prompt()` 消费 resolved capabilities**

```python
# backend/agents/claude_solver.py
from backend.capabilities import build_challenge_profile, claude_runtime_profile
from backend.capabilities.assembler import resolve_capabilities


def _build_claude_resolved_capabilities(*, challenge_dir: str, meta: ChallengeMeta):
    distfile_names = list_distfiles(challenge_dir)
    return resolve_capabilities(
        build_challenge_profile(meta, distfile_names),
        claude_runtime_profile(),
    )
```

```python
        distfile_names = list_distfiles(self.challenge_dir)
        resolved_capabilities = _build_claude_resolved_capabilities(
            challenge_dir=self.challenge_dir,
            meta=self.meta,
        )
        system_prompt = sandbox_preamble + build_prompt(
            self.meta,
            distfile_names,
            container_arch=container_arch,
            resolved_capabilities=resolved_capabilities,
        )
```

- [ ] **Step 4: 跑 claude capability 测试**

Run: `uv run pytest tests/test_solver_capabilities.py::test_claude_resolved_capabilities_use_prompt_only_fragments -q`  
Expected: PASS

- [ ] **Step 5: 提交 claude bash-only contract 迁移**

```bash
git add backend/agents/claude_solver.py tests/test_solver_capabilities.py
git commit -m "refactor: 让 claude solver 使用 bash capability fragments"
```

---

### Task 7: 清理遗留参数、更新 README，并跑完整验证

**Files:**
- Modify: `backend/prompts.py`
- Modify: `README.md`
- Modify: `tests/test_prompts.py`
- Modify: `tests/test_solver_capabilities.py`

- [ ] **Step 1: 加测试锁定 `has_named_tools` 已不再是主入口**

```python
import inspect

from backend.prompts import build_prompt


def test_build_prompt_signature_no_longer_exposes_has_named_tools() -> None:
    assert "has_named_tools" not in inspect.signature(build_prompt).parameters
```

- [ ] **Step 2: 删除遗留注释与参数说明，补 README capability layer 文案**

```python
def build_prompt(
    meta: ChallengeMeta,
    distfile_names: list[str],
    container_arch: str = "unknown",
    resolved_capabilities: ResolvedCapabilities | None = None,
) -> str:
    """Build the solver system prompt from challenge metadata and resolved capabilities."""
```

```markdown
Platform State
    -> Working Memory
    -> Strategy Layer
    -> Policy Engine
    -> Capability Layer
    -> Solver Runtime
```

```markdown
- `backend/capabilities/`
  - 负责把 challenge 需求和 runtime 约束装配成统一的工具暴露与 prompt 能力片段。
```

- [ ] **Step 3: 跑定向测试，确认 prompt/solver 文档链路都稳定**

Run: `uv run pytest tests/test_capability_profiles.py tests/test_capability_assembler.py tests/test_prompts.py tests/test_solver_capabilities.py -q`  
Expected: PASS

- [ ] **Step 4: 跑完整测试与静态检查**

Run: `uv run pytest -q`  
Expected: PASS

Run: `uv run ruff check backend tests`  
Expected: `All checks passed!`

- [ ] **Step 5: 提交清理与文档更新**

```bash
git add backend/prompts.py README.md tests/test_prompts.py tests/test_solver_capabilities.py
git commit -m "docs: 更新 capability layer 架构说明"
```

---

## Spec Coverage Check

- `ChallengeProfile` / `RuntimeProfile`：由 `Task 1` 覆盖。
- `Capability Packs` / `Tool Contracts` / `ResolvedCapabilities`：由 `Task 2` 覆盖。
- prompt 不再使用 `has_named_tools`：由 `Task 3` 与 `Task 7` 覆盖。
- 主 `solver.py` 迁移：由 `Task 4` 覆盖。
- `codex_solver.py` 迁移：由 `Task 5` 覆盖。
- `claude_solver.py` 迁移：由 `Task 6` 覆盖。
- README 与最终验收：由 `Task 7` 覆盖。

没有缺失的 spec 要求；本计划没有覆盖的内容，都是 spec 明确列为非目标的部分。

---

## Verification Notes

- 优先按任务顺序执行，不要跨任务混改。
- 每一任务先写失败测试，再做最小实现，再跑定向测试，再提交。
- `writeups/` 是用户保留目录，不要加入任何 `git add` 命令。
- 如果 capability contract 设计在实现时需要补一个小型辅助对象，优先放进 `backend/capabilities/specs.py`，不要把运行时分叉重新塞回 `prompts.py` 或 solver 文件。
