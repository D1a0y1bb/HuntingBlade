from __future__ import annotations

from backend.capabilities.contracts import (
    build_attachment_hints,
    build_dynamic_tool_specs,
    build_prompt_fragments,
    build_tool_functions,
)
from backend.capabilities.packs import select_capabilities
from backend.capabilities.specs import ChallengeProfile, ResolvedCapabilities, RuntimeProfile


def resolve_capabilities(
    profile: ChallengeProfile, runtime: RuntimeProfile
) -> ResolvedCapabilities:
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
