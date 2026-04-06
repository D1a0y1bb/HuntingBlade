from collections.abc import Callable
from typing import Any

import pytest

from backend.config import Settings
from backend.ctfd import CTFdClient
from backend.platforms import (
    CompetitionPlatformClient,
    PlatformConfigError,
    create_platform_client,
    validate_platform_settings,
)
from backend.platforms.lingxu_event_ctf import LingxuEventCTFClient


def make_settings(**overrides: Any) -> Settings:
    values = {
        "platform": "ctfd",
        "platform_url": "",
        "lingxu_event_id": 0,
        "lingxu_cookie": "",
        "lingxu_cookie_file": "",
        "ctfd_url": "https://ctfd.example.com",
        "ctfd_user": "admin",
        "ctfd_pass": "password",
        "ctfd_token": "token-1",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_competition_platform_client_exposes_required_methods() -> None:
    protocol_methods = {
        name
        for name, value in CompetitionPlatformClient.__dict__.items()
        if isinstance(value, Callable)
    }

    assert {
        "validate_access",
        "fetch_challenge_stubs",
        "fetch_all_challenges",
        "fetch_solved_names",
        "pull_challenge",
        "prepare_challenge",
        "submit_flag",
        "close",
    } <= protocol_methods


def test_validate_platform_settings_requires_cookie_for_lingxu_event_ctf() -> None:
    settings = make_settings(
        platform="lingxu-event-ctf",
        platform_url="https://platform.example",
        lingxu_event_id=42,
        lingxu_cookie="",
        lingxu_cookie_file="",
    )

    with pytest.raises(PlatformConfigError, match="lingxu_cookie"):
        validate_platform_settings(settings)


def test_create_platform_client_returns_ctfd_client_by_default() -> None:
    settings = make_settings()

    client = create_platform_client(settings)

    assert isinstance(client, CTFdClient)
    assert client.base_url == settings.ctfd_url
    assert client.token == settings.ctfd_token
    assert client.username == settings.ctfd_user
    assert client.password == settings.ctfd_pass


def test_create_platform_client_returns_lingxu_event_ctf_client() -> None:
    settings = make_settings(
        platform="lingxu-event-ctf",
        platform_url="https://platform.example",
        lingxu_event_id=42,
        lingxu_cookie="sessionid=sid123; csrftoken=csrf456",
    )

    client = create_platform_client(settings)

    assert isinstance(client, LingxuEventCTFClient)
    assert client.base_url == settings.platform_url
    assert client.event_id == settings.lingxu_event_id
    assert client.cookie == settings.lingxu_cookie


def test_create_platform_client_reads_lingxu_cookie_file(tmp_path) -> None:
    cookie_file = tmp_path / "lingxu.cookie"
    cookie_file.write_text("sessionid=sid123; csrftoken=csrf456", encoding="utf-8")
    settings = make_settings(
        platform="lingxu-event-ctf",
        platform_url="https://platform.example",
        lingxu_event_id=42,
        lingxu_cookie="",
        lingxu_cookie_file=str(cookie_file),
    )

    client = create_platform_client(settings)

    assert isinstance(client, LingxuEventCTFClient)
    assert client.cookie == "sessionid=sid123; csrftoken=csrf456"
