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
