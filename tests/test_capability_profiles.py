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
