"""Tests for chunking, embeddings, and the RAG agent's cache behavior."""

from datetime import date
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from pytest_mock import MockerFixture

from agents.agent_rag import RagAgent
from config import Settings
from db.repository import DocCacheRepository, PromptRepository
from document_extraction.blob_store import BlobStore
from document_extraction.pdf_ingest import PdfIngestor, chunk_text, sha256_hex
from document_extraction.search_index import SearchIndex
from models import (
    DocumentMeta,
    DocumentType,
    LesserOfRule,
    ReimbursementRateSet,
    TimelyFilingRule,
)

# --- chunking -------------------------------------------------------------


def test_chunk_text_short_returns_single() -> None:
    assert chunk_text("a short clause", max_chars=2000, overlap_chars=100) == ["a short clause"]


def test_chunk_text_empty_returns_empty() -> None:
    assert chunk_text("   ", max_chars=100, overlap_chars=10) == []


def test_chunk_text_long_splits_with_overlap() -> None:
    text = "x" * 250
    chunks = chunk_text(text, max_chars=100, overlap_chars=20)
    assert len(chunks) >= 3
    assert all(len(c) <= 100 for c in chunks)


def test_sha256_is_stable() -> None:
    assert sha256_hex(b"abc") == sha256_hex(b"abc")
    assert sha256_hex(b"abc") != sha256_hex(b"abd")


def test_build_chunks_assigns_pages() -> None:
    ingestor = PdfIngestor(Settings(), cast(BlobStore, object()), cast(SearchIndex, object()))
    chunks = ingestor.build_chunks(
        doc_id="d1", provider_npi="n", state="TX", pages=["page one", "page two"]
    )
    assert [c.page for c in chunks] == [1, 2]
    assert {c.doc_id for c in chunks} == {"d1"}


# --- embeddings -----------------------------------------------------------


async def test_embed_returns_vectors(mocker: MockerFixture) -> None:
    from agents import llm_client

    fake_response = SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1, 0.2]), SimpleNamespace(embedding=[0.3, 0.4])]
    )
    fake_client = SimpleNamespace(
        embeddings=SimpleNamespace(create=AsyncMock(return_value=fake_response))
    )
    mocker.patch.object(llm_client, "_build_client", return_value=fake_client)
    vectors = await llm_client.embed(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


async def test_embed_empty_input_short_circuits() -> None:
    from agents import llm_client

    assert await llm_client.embed([]) == []


# --- RAG agent cache ------------------------------------------------------


class FakePromptRepo:
    async def get(self, name: str) -> str | None:
        return None  # force built-in default prompt


class FakeCacheRepo:
    def __init__(self, preset: str | None = None) -> None:
        self.store: dict[tuple[str, str, str], str] = {}
        self._preset = preset

    async def get(self, doc_hash: str, prompt_hash: str, provider: str) -> str | None:
        return self._preset

    async def put(self, doc_hash: str, prompt_hash: str, provider: str, response_json: str) -> None:
        self.store[(doc_hash, prompt_hash, provider)] = response_json


def _doc() -> DocumentMeta:
    return DocumentMeta(
        doc_id="d1",
        provider_npi="1234567890",
        state="TX",
        doc_type=DocumentType.CONTRACT,
        blob_path="blob://x",
        doc_hash="hash123",
        effective_date=date(2023, 1, 1),
    )


def _agent(cache: FakeCacheRepo) -> RagAgent:
    return RagAgent(
        settings=Settings(),
        search_index=cast(SearchIndex, object()),
        prompt_repo=cast(PromptRepository, FakePromptRepo()),
        cache_repo=cast(DocCacheRepository, cache),
    )


async def test_extract_cache_hit_skips_llm(mocker: MockerFixture) -> None:
    cached = TimelyFilingRule(
        days_to_file=90, effective_date=date(2023, 1, 1), source_excerpt="cached"
    )
    cache = FakeCacheRepo(preset=cached.model_dump_json())
    chat = mocker.patch("agents.llm_client.chat_structured", new=AsyncMock())
    result = await _agent(cache).extract(TimelyFilingRule, "timely_filing", _doc())
    assert result == cached
    chat.assert_not_awaited()


async def test_extract_cache_miss_calls_llm_and_caches(mocker: MockerFixture) -> None:
    cache = FakeCacheRepo(preset=None)
    extracted = TimelyFilingRule(
        days_to_file=120, effective_date=date(2024, 1, 1), source_excerpt="fresh"
    )
    mocker.patch("agents.llm_client.embed", new=AsyncMock(return_value=[[0.0, 0.0]]))
    mocker.patch(
        "document_extraction.search_index.SearchIndex.search",
        new=AsyncMock(return_value=[]),
    )
    # The agent holds a dummy SearchIndex; patch retrieve to avoid the Azure client.
    agent = _agent(cache)
    mocker.patch.object(agent, "retrieve", new=AsyncMock(return_value=[]))
    chat = mocker.patch("agents.llm_client.chat_structured", new=AsyncMock(return_value=extracted))
    result = await agent.extract(TimelyFilingRule, "timely_filing", _doc())
    assert result == extracted
    chat.assert_awaited_once()
    assert len(cache.store) == 1


async def test_extract_returns_none_on_llm_failure(mocker: MockerFixture) -> None:
    from agents.llm_client import LLMExtractionError

    cache = FakeCacheRepo(preset=None)
    agent = _agent(cache)
    mocker.patch.object(agent, "retrieve", new=AsyncMock(return_value=[]))
    mocker.patch(
        "agents.llm_client.chat_structured",
        new=AsyncMock(side_effect=LLMExtractionError("boom")),
    )
    result = await agent.extract(TimelyFilingRule, "timely_filing", _doc())
    assert result is None


async def test_extract_terms_drops_inapplicable_lesser_of(mocker: MockerFixture) -> None:
    # A document that says lesser-of does NOT apply must not record a lesser-of rule,
    # so it can't override another document that does establish it.
    agent = _agent(FakeCacheRepo())
    timely = TimelyFilingRule(days_to_file=90, effective_date=date(2023, 1, 1), source_excerpt="x")
    mocker.patch.object(
        agent,
        "extract",
        new=AsyncMock(side_effect=[timely, LesserOfRule(applies=False), ReimbursementRateSet()]),
    )
    terms = await agent.extract_terms(_doc())
    assert terms.lesser_of is None
    assert terms.timely_filing == timely


async def test_extract_terms_keeps_applicable_lesser_of(mocker: MockerFixture) -> None:
    agent = _agent(FakeCacheRepo())
    lesser = LesserOfRule(applies=True, basis="lesser of billed or fee", source_excerpt="...")
    mocker.patch.object(
        agent,
        "extract",
        new=AsyncMock(side_effect=[None, lesser, ReimbursementRateSet()]),
    )
    terms = await agent.extract_terms(_doc())
    assert terms.lesser_of == lesser
