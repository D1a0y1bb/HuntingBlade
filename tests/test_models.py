from __future__ import annotations

from pydantic_ai.models.openai import OpenAIResponsesModel

from backend.config import Settings
from backend.models import resolve_model, resolve_model_settings


def test_resolve_model_uses_openai_responses_for_azure() -> None:
    settings = Settings(
        _env_file=None,
        azure_openai_endpoint="https://api.example.com/v1",
        azure_openai_api_key="test-key",
    )

    model = resolve_model("azure/gpt-5.4", settings)

    assert isinstance(model, OpenAIResponsesModel)


def test_resolve_model_settings_uses_gateway_compatible_responses_defaults_for_azure() -> None:
    settings = resolve_model_settings("azure/gpt-5.4")

    assert settings["max_tokens"] == 128_000
    assert settings["openai_reasoning_effort"] == "medium"
    assert settings["openai_reasoning_summary"] == "auto"
    assert settings["openai_truncation"] == "auto"
    assert "openai_previous_response_id" not in settings


def test_resolve_model_settings_keeps_zen_on_chat_defaults() -> None:
    settings = resolve_model_settings("zen/gpt-5.4")

    assert settings["max_tokens"] == 128_000
    assert "openai_previous_response_id" not in settings
