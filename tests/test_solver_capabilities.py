from pathlib import Path

from backend.agents.claude_solver import _build_claude_resolved_capabilities
from backend.agents.codex_solver import _build_codex_resolved_capabilities
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
