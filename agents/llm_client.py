"""Provider abstraction — the single entry point for every LLM call in the codebase.

CLAUDE.md hard rule: no other module may import or instantiate an LLM provider SDK
(``openai``, ``langchain_openai``, …). If new behaviour is needed, extend this module.

Provider selection is driven by the ``LLM_PROVIDER`` env var:

* ``github`` (default) — base_url ``https://models.inference.ai.azure.com``;
  key ``GITHUB_TOKEN``; model ``LLM_MODEL`` (default ``gpt-4o-mini``).
* ``azure`` — base_url ``AZURE_OPENAI_ENDPOINT`` + deployment path;
  key ``AZURE_OPENAI_KEY``; model ``AZURE_OPENAI_DEPLOYMENT``.
* ``groq`` — base_url ``https://api.groq.com/openai/v1``;
  key ``GROQ_API_KEY``; model ``LLM_MODEL`` (default ``llama-3.3-70b-versatile``).

All three are OpenAI-compatible, so a single ``openai.AsyncOpenAI`` client serves them.
Structured outputs are obtained via forced tool-calling and validated against a Pydantic
model; any failure raises :class:`LLMExtractionError`.
"""

import functools
import json
import logging
import os
import ssl
from dataclasses import dataclass
from typing import Any, cast

import httpx
from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "github"
VALID_PROVIDERS: tuple[str, ...] = ("github", "azure", "groq")

GITHUB_BASE_URL = "https://models.inference.ai.azure.com"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GITHUB_MODEL = "gpt-4o-mini"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_AZURE_API_VERSION = "2024-10-21"


class LLMConfigurationError(RuntimeError):
    """Raised when provider selection or credentials are misconfigured."""


class LLMExtractionError(RuntimeError):
    """Raised when a model response cannot be parsed/validated into the target schema."""


@dataclass(frozen=True)
class ProviderConfig:
    """Resolved configuration for a provider."""

    provider: str
    base_url: str
    api_key: str
    model: str
    api_key_env: str  # env var the key was read from (observability / tests)
    default_query: dict[str, str] | None = None
    default_headers: dict[str, str] | None = None


def get_active_provider() -> str:
    """Return the active provider name, validated. Defaults to ``github``."""
    provider = os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    if provider not in VALID_PROVIDERS:
        raise LLMConfigurationError(
            f"LLM_PROVIDER={provider!r} is not supported; choose one of {VALID_PROVIDERS}."
        )
    return provider


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise LLMConfigurationError(
            f"Environment variable {name!r} is required for the selected LLM provider."
        )
    return value


def get_provider_config(provider: str | None = None) -> ProviderConfig:
    """Resolve base_url, api key, and model for ``provider`` (default: active provider).

    Reads ``os.environ`` live, so callers (and tests) always see the current environment.
    """
    provider = (provider or get_active_provider()).strip().lower()

    if provider == "github":
        return ProviderConfig(
            provider=provider,
            base_url=GITHUB_BASE_URL,
            api_key=_require_env("GITHUB_TOKEN"),
            model=os.environ.get("LLM_MODEL", DEFAULT_GITHUB_MODEL),
            api_key_env="GITHUB_TOKEN",
        )
    if provider == "groq":
        return ProviderConfig(
            provider=provider,
            base_url=GROQ_BASE_URL,
            api_key=_require_env("GROQ_API_KEY"),
            model=os.environ.get("LLM_MODEL", DEFAULT_GROQ_MODEL),
            api_key_env="GROQ_API_KEY",
        )
    if provider == "azure":
        endpoint = _require_env("AZURE_OPENAI_ENDPOINT").rstrip("/")
        key = _require_env("AZURE_OPENAI_KEY")
        deployment = _require_env("AZURE_OPENAI_DEPLOYMENT")
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", DEFAULT_AZURE_API_VERSION)
        # Drive Azure OpenAI through the plain OpenAI client: a deployment-scoped base
        # URL plus the api-version query and the 'api-key' header (Azure does not use a
        # bearer token). This is the one place the providers genuinely differ.
        return ProviderConfig(
            provider=provider,
            base_url=f"{endpoint}/openai/deployments/{deployment}",
            api_key=key,
            model=deployment,
            api_key_env="AZURE_OPENAI_KEY",
            default_query={"api-version": api_version},
            default_headers={"api-key": key},
        )

    raise LLMConfigurationError(
        f"LLM_PROVIDER={provider!r} is not supported; choose one of {VALID_PROVIDERS}."
    )


@functools.cache
def _system_ssl_context() -> ssl.SSLContext:
    """An SSL context using the OS trust store.

    Required behind TLS-intercepting corporate proxies: httpx defaults to ``certifi``,
    which does not include the proxy's root CA, whereas the OS store does.
    """
    return ssl.create_default_context()


@functools.cache
def _build_client(provider: str) -> AsyncOpenAI:
    """Build and cache an ``AsyncOpenAI`` client for ``provider``.

    Cached per provider so the client (and its connection pool) is reused across calls.
    """
    config = get_provider_config(provider)
    http_client = httpx.AsyncClient(verify=_system_ssl_context(), timeout=httpx.Timeout(60.0))
    logger.info("Initialised LLM client for provider=%s model=%s", config.provider, config.model)
    return AsyncOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
        default_query=config.default_query,
        default_headers=config.default_headers,
        http_client=http_client,
    )


def get_client() -> AsyncOpenAI:
    """Return the cached ``AsyncOpenAI`` client for the active provider."""
    return _build_client(get_active_provider())


DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


async def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Return embedding vectors for ``texts`` via the active provider's embedding model.

    Routes through the same provider abstraction as chat. Raises
    :class:`LLMExtractionError` on transport failure.
    """
    if not texts:
        return []
    client = get_client()
    embed_model = model or os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    try:
        response = await client.embeddings.create(model=embed_model, input=cast(Any, texts))
    except APIError as exc:
        raise LLMExtractionError(f"Embedding request failed: {exc}") from exc
    return [item.embedding for item in response.data]


def _tool_schema(response_model: type[BaseModel]) -> dict[str, Any]:
    """Build an OpenAI function-tool definition from a Pydantic model."""
    return {
        "type": "function",
        "function": {
            "name": response_model.__name__,
            "description": (response_model.__doc__ or response_model.__name__).strip(),
            "parameters": response_model.model_json_schema(),
        },
    }


async def chat_structured[T: BaseModel](
    messages: list[dict],
    response_model: type[T],
    temperature: float = 0.0,
) -> T:
    """Call the active LLM and return a validated instance of ``response_model``.

    Forces a single tool call shaped like ``response_model`` (works across all three
    OpenAI-compatible providers), then parses and validates the arguments. Raises
    :class:`LLMExtractionError` on transport, JSON, or schema-validation failure.
    """
    provider = get_active_provider()
    config = get_provider_config(provider)
    client = _build_client(provider)
    tool = _tool_schema(response_model)
    tool_choice = {"type": "function", "function": {"name": response_model.__name__}}

    try:
        completion = await client.chat.completions.create(
            model=config.model,
            messages=cast(Any, messages),
            temperature=temperature,
            tools=cast(Any, [tool]),
            tool_choice=cast(Any, tool_choice),
        )
    except APIError as exc:
        raise LLMExtractionError(
            f"LLM request failed for {response_model.__name__}: {exc}"
        ) from exc

    choice = completion.choices[0]
    tool_calls = choice.message.tool_calls
    if not tool_calls:
        raise LLMExtractionError(
            f"Model returned no tool call for {response_model.__name__} "
            f"(finish_reason={choice.finish_reason!r})."
        )

    tool_call = tool_calls[0]
    if tool_call.type != "function":
        raise LLMExtractionError(
            f"Model returned a non-function tool call ({tool_call.type!r}) "
            f"for {response_model.__name__}."
        )

    raw_arguments = tool_call.function.arguments
    try:
        payload = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise LLMExtractionError(
            f"Model returned invalid JSON for {response_model.__name__}: {exc}"
        ) from exc

    try:
        return response_model.model_validate(payload)
    except ValidationError as exc:
        raise LLMExtractionError(
            f"Model output failed {response_model.__name__} validation: {exc}"
        ) from exc
