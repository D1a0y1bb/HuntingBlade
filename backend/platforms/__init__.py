"""Competition platform abstractions and client factory."""

from backend.platforms.base import CompetitionPlatformClient, PlatformConfigError
from backend.platforms.factory import create_platform_client, validate_platform_settings

__all__ = [
    "CompetitionPlatformClient",
    "PlatformConfigError",
    "create_platform_client",
    "validate_platform_settings",
]
