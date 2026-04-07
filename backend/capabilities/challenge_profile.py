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
