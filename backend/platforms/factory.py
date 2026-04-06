"""Factory helpers for constructing competition platform clients."""

from __future__ import annotations

from pathlib import Path

from backend.config import Settings
from backend.ctfd import CTFdClient
from backend.platforms.base import CompetitionPlatformClient, PlatformConfigError


def _platform_name(settings: Settings) -> str:
    return (settings.platform or "ctfd").strip()


def _read_cookie_file(path: str) -> str:
    try:
        cookie = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PlatformConfigError(f"failed to read lingxu_cookie_file: {path}") from exc

    if not cookie:
        raise PlatformConfigError("lingxu_cookie_file is empty")
    return cookie


def validate_platform_settings(settings: Settings) -> None:
    platform = _platform_name(settings)

    if platform == "ctfd":
        if not settings.ctfd_url:
            raise PlatformConfigError("ctfd_url is required when platform=ctfd")
        return

    if platform != "lingxu-event-ctf":
        raise PlatformConfigError(f"unsupported platform: {platform}")

    if not settings.platform_url:
        raise PlatformConfigError("platform_url is required when platform=lingxu-event-ctf")
    if not settings.lingxu_event_id:
        raise PlatformConfigError("lingxu_event_id is required when platform=lingxu-event-ctf")
    if not settings.lingxu_cookie and not settings.lingxu_cookie_file:
        raise PlatformConfigError("lingxu_cookie or lingxu_cookie_file is required when platform=lingxu-event-ctf")


def create_platform_client(settings: Settings) -> CompetitionPlatformClient:
    validate_platform_settings(settings)

    platform = _platform_name(settings)
    if platform == "ctfd":
        return CTFdClient(
            base_url=settings.ctfd_url,
            token=settings.ctfd_token,
            username=settings.ctfd_user,
            password=settings.ctfd_pass,
        )

    try:
        from backend.platforms.lingxu_event_ctf import LingxuEventCTFClient
    except ModuleNotFoundError as exc:
        raise PlatformConfigError("lingxu-event-ctf client is not available yet") from exc

    cookie = settings.lingxu_cookie or _read_cookie_file(settings.lingxu_cookie_file)
    return LingxuEventCTFClient(
        base_url=settings.platform_url,
        event_id=settings.lingxu_event_id,
        cookie=cookie,
    )
