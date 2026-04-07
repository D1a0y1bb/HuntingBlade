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
