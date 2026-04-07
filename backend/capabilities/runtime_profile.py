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
