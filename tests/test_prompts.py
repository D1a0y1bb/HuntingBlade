from pathlib import Path

from backend.capabilities import (
    AttachmentHint,
    ChallengeProfile,
    ResolvedCapabilities,
    RuntimeProfile,
)
from backend.capabilities.specs import CapabilitySpec
from backend.prompts import ChallengeMeta, build_prompt, list_distfiles


def _resolved(
    *, fragments: tuple[str, ...], attachment_hints: tuple[AttachmentHint, ...] = ()
) -> ResolvedCapabilities:
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


def test_list_distfiles_returns_recursive_relative_paths(tmp_path: Path) -> None:
    distfiles = tmp_path / "distfiles"
    (distfiles / "nested").mkdir(parents=True)
    (distfiles / "top.txt").write_text("top\n", encoding="utf-8")
    (distfiles / "nested" / "inner.txt").write_text("inner\n", encoding="utf-8")

    assert list_distfiles(str(tmp_path)) == ["nested/inner.txt", "top.txt"]


def test_build_prompt_marks_nested_images_for_vision(tmp_path: Path) -> None:
    distfiles = tmp_path / "distfiles"
    (distfiles / "images").mkdir(parents=True)
    (distfiles / "images" / "badge.png").write_bytes(b"png")

    prompt = build_prompt(
        ChallengeMeta(name="img", category="web", description="see image"),
        list_distfiles(str(tmp_path)),
    )

    attached_image_line = (
        "- `/challenge/distfiles/images/badge.png`  <- "
        "**IMAGE: call `view_image` immediately** (fix magic bytes first if corrupt)"
    )
    assert attached_image_line in prompt


def test_build_prompt_uses_attachment_hints_from_resolved_capabilities() -> None:
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
            fragments=(
                "**Verify every candidate with `submit_flag '<flag>'`** (bash command) before reporting.",
            ),
        ),
    )

    assert "submit_flag '<flag>'" in prompt
    assert "has_named_tools" not in prompt
