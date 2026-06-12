"""Unit + smoke tests for the LLM provider abstraction (agents.llm_client)."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openai import AsyncOpenAI
from pytest_mock import MockerFixture

from agents import llm_client
from agents.llm_client import (
    LLMConfigurationError,
    LLMExtractionError,
    chat_structured,
    get_active_provider,
    get_client,
    get_provider_config,
)
from models import TimelyFilingRule

# --------------------------------------------------------------------------- #
# Provider selection logic (unit, no network)                                 #
# --------------------------------------------------------------------------- #


def test_default_provider_is_github(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert get_active_provider() == "github"


def test_github_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "github")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-secret")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    cfg = get_provider_config()
    assert cfg.provider == "github"
    assert cfg.base_url == "https://models.inference.ai.azure.com"
    assert cfg.api_key == "gh-secret"
    assert cfg.api_key_env == "GITHUB_TOKEN"
    assert cfg.model == "gpt-4o-mini"


def test_github_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "github")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-secret")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o")
    assert get_provider_config().model == "gpt-4o"


def test_groq_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    cfg = get_provider_config()
    assert cfg.provider == "groq"
    assert cfg.base_url == "https://api.groq.com/openai/v1"
    assert cfg.api_key == "groq-secret"
    assert cfg.api_key_env == "GROQ_API_KEY"
    assert cfg.model == "llama-3.3-70b-versatile"


def test_azure_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://contoso.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "azure-secret")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini-dep")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    cfg = get_provider_config()
    assert cfg.provider == "azure"
    assert cfg.base_url == "https://contoso.openai.azure.com/openai/deployments/gpt-4o-mini-dep"
    assert cfg.api_key == "azure-secret"
    assert cfg.api_key_env == "AZURE_OPENAI_KEY"
    assert cfg.model == "gpt-4o-mini-dep"
    assert cfg.default_query == {"api-version": "2024-10-21"}
    assert cfg.default_headers == {"api-key": "azure-secret"}


def test_invalid_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    with pytest.raises(LLMConfigurationError):
        get_active_provider()


def test_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "github")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(LLMConfigurationError):
        get_provider_config()


def test_client_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "github")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-secret")
    first = get_client()
    second = get_client()
    assert isinstance(first, AsyncOpenAI)
    assert first is second


# --------------------------------------------------------------------------- #
# chat_structured (mocked client — no live calls, per CLAUDE.md)              #
# --------------------------------------------------------------------------- #


def _fake_completion(arguments: str | None, *, with_tool_call: bool = True) -> SimpleNamespace:
    tool_calls = None
    if with_tool_call:
        tool_calls = [
            SimpleNamespace(type="function", function=SimpleNamespace(arguments=arguments))
        ]
    message = SimpleNamespace(tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason="tool_calls")
    return SimpleNamespace(choices=[choice])


def _patch_client(mocker: MockerFixture, completion: SimpleNamespace) -> None:
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=completion)))
    )
    mocker.patch.object(llm_client, "_build_client", return_value=fake_client)


@pytest.fixture
def github_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a valid github provider for the structured-output tests."""
    monkeypatch.setenv("LLM_PROVIDER", "github")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-secret")


async def test_chat_structured_parses_tool_call(github_env: None, mocker: MockerFixture) -> None:
    args = (
        '{"days_to_file": 90, "effective_date": "2025-01-01", "source_excerpt": "within 90 days"}'
    )
    _patch_client(mocker, _fake_completion(args))
    result = await chat_structured([{"role": "user", "content": "extract"}], TimelyFilingRule)
    assert isinstance(result, TimelyFilingRule)
    assert result.days_to_file == 90
    assert result.effective_date.isoformat() == "2025-01-01"


async def test_chat_structured_invalid_json_raises(github_env: None, mocker: MockerFixture) -> None:
    _patch_client(mocker, _fake_completion("{not valid json"))
    with pytest.raises(LLMExtractionError):
        await chat_structured([{"role": "user", "content": "x"}], TimelyFilingRule)


async def test_chat_structured_no_tool_call_raises(github_env: None, mocker: MockerFixture) -> None:
    _patch_client(mocker, _fake_completion(None, with_tool_call=False))
    with pytest.raises(LLMExtractionError):
        await chat_structured([{"role": "user", "content": "x"}], TimelyFilingRule)


async def test_chat_structured_validation_error_raises(
    github_env: None, mocker: MockerFixture
) -> None:
    # days_to_file must be > 0 — a negative value should fail Pydantic validation.
    bad = '{"days_to_file": -5, "effective_date": "2025-01-01", "source_excerpt": "x"}'
    _patch_client(mocker, _fake_completion(bad))
    with pytest.raises(LLMExtractionError):
        await chat_structured([{"role": "user", "content": "x"}], TimelyFilingRule)


# --------------------------------------------------------------------------- #
# Live smoke test (opt-in: pytest -m live; needs a real GITHUB_TOKEN)         #
# --------------------------------------------------------------------------- #


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("GITHUB_TOKEN"),
    reason="GITHUB_TOKEN not set; skipping live GitHub Models smoke test.",
)
async def test_live_timely_filing_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "github")
    messages = [
        {
            "role": "system",
            "content": "Extract the timely-filing rule from the contract clause.",
        },
        {
            "role": "user",
            "content": (
                "Claims must be submitted within 90 days of the date of service. "
                "This provision is effective January 1, 2025."
            ),
        },
    ]
    result = await chat_structured(messages, TimelyFilingRule)
    assert isinstance(result, TimelyFilingRule)
    assert result.days_to_file == 90
    assert result.effective_date.year == 2025
