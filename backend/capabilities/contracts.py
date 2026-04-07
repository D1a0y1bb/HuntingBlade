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


def build_dynamic_tool_specs(
    capabilities: frozenset[CapabilitySpec], runtime: RuntimeProfile
) -> tuple[dict[str, object], ...]:
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
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string", "default": "/challenge/distfiles"}},
            },
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
    if CapabilitySpec.COORDINATION_FINDINGS in capabilities:
        specs.append(
            {
                "name": "check_findings",
                "description": "Check for new findings from other agents working on the same challenge.",
                "inputSchema": {"type": "object", "properties": {}},
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


def build_prompt_fragments(
    capabilities: frozenset[CapabilitySpec], runtime: RuntimeProfile
) -> tuple[str, ...]:
    fragments: list[str] = []
    if CapabilitySpec.VISION_INSPECT_IMAGE in capabilities:
        if runtime.supports_named_tools or runtime.supports_dynamic_tools:
            fragments.append("**Images: call `view_image` FIRST, before any other analysis.**")
        else:
            fragments.append("**Images: use `exiftool`, `steghide`, `zsteg`, `strings`, `xxd` via bash.**")
    if CapabilitySpec.NETWORK_WEBHOOK_OOB in capabilities:
        fragments.append("Web: fuzz params, check JS source, cookies, robots.txt. For XSS/SSRF: use `webhook_create`.")
    if CapabilitySpec.FLAG_SUBMIT in capabilities:
        if runtime.prefers_bash_only:
            fragments.append("**Verify every candidate with `submit_flag '<flag>'`** (bash command) before reporting.")
        else:
            fragments.append("**Verify every candidate with `submit_flag`** before reporting.")
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
    return tuple(
        AttachmentHint(path=name, suffix=_IMAGE_HINT)
        for name in profile.distfile_names
        if Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
    )
