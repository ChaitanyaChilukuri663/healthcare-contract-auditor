"""Stage 3: LangChain-style RAG agent — retrieval, DB-driven prompts, cache, extraction.

Every LLM call routes through ``agents.llm_client`` (provider-abstraction rule). Prompts
are loaded from app_config.prompt_registry (hot-reloadable) with built-in fallbacks.
Extractions are cached on ``(doc_hash, prompt_hash, provider)``.
"""

import hashlib
import logging

from pydantic import BaseModel

from agents import llm_client
from agents.llm_client import LLMExtractionError
from config import Settings
from db.repository import DocCacheRepository, PromptRepository
from document_extraction.search_index import SearchIndex
from models import (
    DocumentMeta,
    ExtractedTerms,
    LesserOfRule,
    ReimbursementRateSet,
    RetrievedChunk,
    TimelyFilingRule,
)

logger = logging.getLogger(__name__)

# Retrieval queries per extraction (used for vector search).
_QUERIES = {
    "timely_filing": "timely filing claim submission deadline days to file",
    "lesser_of": "lesser of billed charges or fee schedule reimbursement",
    "reimbursement_rates": "reimbursement rate percent of medicare fee schedule services",
}

# Built-in fallback prompts when app_config.prompt_registry has no entry.
DEFAULT_PROMPTS: dict[str, str] = {
    "timely_filing": (
        "You extract the timely-filing rule from healthcare provider contract excerpts. "
        "Return the number of days within which a claim must be filed, the effective date, "
        "and the verbatim source sentence. If multiple windows exist, use the most specific."
    ),
    "lesser_of": (
        "You extract 'lesser of' reimbursement logic from provider contract excerpts. "
        "Set applies=true ONLY if the excerpts contain explicit 'lesser of' wording (e.g. "
        "'the lesser of billed charges or the fee schedule amount'). If there is no explicit "
        "lesser-of language, set applies=false and leave basis and source_excerpt empty. "
        "When applies is true, give the comparison basis, the effective date if stated, and "
        "the verbatim source sentence."
    ),
    "reimbursement_rates": (
        "You extract reimbursement rates from provider contract excerpts. For each service, "
        "return the service name, whether the rate is a percent of Medicare, a percent of "
        "billed charges, or a flat amount, the numeric value, any CPT/HCPCS codes, the "
        "effective date if stated, and the verbatim source sentence."
    ),
}


class RagAgent:
    """Retrieves relevant clauses and extracts structured contract terms."""

    def __init__(
        self,
        settings: Settings,
        search_index: SearchIndex,
        prompt_repo: PromptRepository,
        cache_repo: DocCacheRepository,
        top_k: int = 5,
    ) -> None:
        self._settings = settings
        self._search = search_index
        self._prompts = prompt_repo
        self._cache = cache_repo
        self._top_k = top_k

    async def get_prompt(self, name: str) -> str:
        """Return the DB prompt for ``name``, falling back to the built-in default."""
        text = await self._prompts.get(name)
        if text:
            return text
        return DEFAULT_PROMPTS[name]

    async def retrieve(self, query: str, provider_npi: str, state: str) -> list[RetrievedChunk]:
        """Embed ``query`` and vector-search the index, filtered by provider/state."""
        vectors = await llm_client.embed([query])
        if not vectors:
            return []
        return await self._search.search(
            vectors[0], provider_npi=provider_npi, state=state, top=self._top_k
        )

    @staticmethod
    def _prompt_hash(prompt: str, model_name: str) -> str:
        return hashlib.sha256(f"{model_name}|{prompt}".encode()).hexdigest()

    async def extract[T: BaseModel](
        self,
        response_model: type[T],
        prompt_name: str,
        doc: DocumentMeta,
    ) -> T | None:
        """Extract one structured model from a document, using the response cache.

        Returns ``None`` if the model could not extract usable data.
        """
        provider = llm_client.get_active_provider()
        prompt = await self.get_prompt(prompt_name)
        prompt_hash = self._prompt_hash(prompt, response_model.__name__)

        cached = await self._cache.get(doc.doc_hash, prompt_hash, provider)
        if cached is not None:
            logger.debug("Cache hit for %s on doc %s", response_model.__name__, doc.doc_id)
            return response_model.model_validate_json(cached)

        chunks = await self.retrieve(
            _QUERIES.get(prompt_name, prompt_name), doc.provider_npi, doc.state
        )
        context = "\n\n".join(chunk.content for chunk in chunks)
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    f"Contract excerpts:\n{context}\n\n"
                    f"Extract the requested information as structured data."
                ),
            },
        ]
        try:
            result = await llm_client.chat_structured(messages, response_model)
        except LLMExtractionError as exc:
            logger.warning("Extraction failed for %s: %s", response_model.__name__, exc)
            return None

        await self._cache.put(doc.doc_hash, prompt_hash, provider, result.model_dump_json())
        return result

    async def extract_terms(self, doc: DocumentMeta) -> ExtractedTerms:
        """Run all extractions for a single document and aggregate them."""
        timely = await self.extract(TimelyFilingRule, "timely_filing", doc)
        lesser = await self.extract(LesserOfRule, "lesser_of", doc)
        rate_set = await self.extract(ReimbursementRateSet, "reimbursement_rates", doc)
        # Treat "applies=false" (or a failed extraction) as "this document does not establish
        # lesser-of logic", so a document that is silent on it doesn't override one that has it.
        lesser_of = lesser if (lesser is not None and lesser.applies) else None
        return ExtractedTerms(
            doc_id=doc.doc_id,
            provider_npi=doc.provider_npi,
            effective_date=doc.effective_date,
            timely_filing=timely,
            lesser_of=lesser_of,
            reimbursement_rates=rate_set.rates if rate_set else [],
        )


async def extract_terms_from_text(text: str) -> ExtractedTerms:
    """Extract contract terms straight from raw text via the LLM.

    No retrieval, cache, or Azure — only the provider abstraction. Powers the lightweight
    upload demo (anyone can paste/upload a contract). A field that fails extraction is omitted.
    """
    body = f"Contract text:\n{text}\n\nExtract the requested information as structured data."

    def _messages(prompt_name: str) -> list[dict]:
        return [
            {"role": "system", "content": DEFAULT_PROMPTS[prompt_name]},
            {"role": "user", "content": body},
        ]

    timely: TimelyFilingRule | None = None
    lesser: LesserOfRule | None = None
    rate_set: ReimbursementRateSet | None = None
    try:
        timely = await llm_client.chat_structured(_messages("timely_filing"), TimelyFilingRule)
    except LLMExtractionError:
        logger.warning("Upload demo: timely-filing extraction failed")
    try:
        lesser = await llm_client.chat_structured(_messages("lesser_of"), LesserOfRule)
    except LLMExtractionError:
        logger.warning("Upload demo: lesser-of extraction failed")
    try:
        rate_set = await llm_client.chat_structured(
            _messages("reimbursement_rates"), ReimbursementRateSet
        )
    except LLMExtractionError:
        logger.warning("Upload demo: reimbursement-rate extraction failed")

    return ExtractedTerms(
        doc_id="upload",
        provider_npi="upload",
        timely_filing=timely,
        lesser_of=lesser if (lesser is not None and lesser.applies) else None,
        reimbursement_rates=rate_set.rates if rate_set else [],
    )
