"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest

from agents import llm_client


@pytest.fixture(autouse=True)
def _reset_llm_client_cache() -> Iterator[None]:
    """Clear the cached LLM client so each test resolves it from its own env."""
    llm_client._build_client.cache_clear()
    yield
    llm_client._build_client.cache_clear()
