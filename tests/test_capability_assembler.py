from backend.capabilities.assembler import resolve_capabilities
from backend.capabilities.challenge_profile import build_challenge_profile
from backend.capabilities.runtime_profile import (
    claude_runtime_profile,
    codex_runtime_profile,
    solver_runtime_profile,
)
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
