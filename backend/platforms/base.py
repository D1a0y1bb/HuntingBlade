"""Platform protocol shared by CTFd and alternate competition clients."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class PlatformConfigError(ValueError):
    """Raised when the selected platform settings are incomplete or invalid."""


@runtime_checkable
class CompetitionPlatformClient(Protocol):
    async def validate_access(self) -> None: ...

    async def fetch_challenge_stubs(self) -> list[dict[str, Any]]: ...

    async def fetch_all_challenges(self) -> list[dict[str, Any]]: ...

    async def fetch_solved_names(self) -> set[str]: ...

    async def pull_challenge(self, challenge: dict[str, Any], output_dir: str) -> str: ...

    async def prepare_challenge(self, challenge_dir: str) -> None: ...

    async def release_challenge_env(self, challenge_ref: Any) -> None: ...

    async def submit_flag(self, challenge_ref: Any, flag: str) -> Any: ...

    async def close(self) -> None: ...
