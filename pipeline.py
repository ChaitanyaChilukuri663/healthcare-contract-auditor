"""End-to-end audit pipeline orchestration (the 5 stages).

Factored out of ``app.py`` so the flow can be unit-tested with mocked components.
"""

import logging
from datetime import UTC, date, datetime

from agents.agent_rag import RagAgent
from config import ConfigurationError, Settings
from db.database import Database
from db.repository import (
    AuditRunRepository,
    DocCacheRepository,
    DocumentRepository,
    FacetsRepository,
    PromptRepository,
    ProviderAgreementRepository,
)
from document_extraction.blob_store import BlobStore
from document_extraction.search_index import SearchIndex
from document_extraction.timeline_builder import TimelineBuilder
from facets.fee_extraction import normalize_terms
from facets.fee_validation import StrictGrader
from facets.multi_records import infer_facility
from models import (
    AuditErrorCode,
    AuditFinding,
    AuditOutcome,
    AuditReport,
    AuditRequest,
    AuditResponse,
    FindingSeverity,
    ProviderAgreement,
)

logger = logging.getLogger(__name__)


class AuditPipeline:
    """Runs Stages 1-5 for a single audit request."""

    def __init__(
        self,
        settings: Settings,
        agreement_repo: ProviderAgreementRepository,
        document_repo: DocumentRepository,
        rag_agent: RagAgent,
        timeline_builder: TimelineBuilder,
        grader: StrictGrader,
        audit_repo: AuditRunRepository | None = None,
    ) -> None:
        self._settings = settings
        self._agreements = agreement_repo
        self._documents = document_repo
        self._rag = rag_agent
        self._timeline = timeline_builder
        self._grader = grader
        self._audit_repo = audit_repo

    async def run(self, request: AuditRequest, as_of: date | None = None) -> AuditResponse:
        """Execute the pipeline and return the audit response."""
        when = as_of or datetime.now(UTC).date()

        # --- Stage 1: agreement pre-check ---
        agreement = await self._agreements.get(
            request.provider_npi, request.contract_id, request.state
        )
        if agreement is None:
            return AuditResponse(
                status=AuditOutcome.ERROR,
                message=(
                    f"No provider agreement {request.contract_id!r} found for NPI "
                    f"{request.provider_npi} in {request.state}."
                ),
            )
        if not agreement.is_active(when):
            return self._early_fail(
                agreement,
                AuditErrorCode.AG001,
                "agreement",
                f"Provider agreement is inactive/expired as of {when.isoformat()}.",
            )

        # --- Stage 2: documents ---
        documents = await self._documents.list_for(request.provider_npi, request.state)
        if not documents:
            return self._early_fail(
                agreement,
                AuditErrorCode.DOC001,
                "documents",
                "No contract documents found for the provider/state.",
            )

        # --- Stage 3: extraction (per document) ---
        extracted = []
        for doc in documents:
            terms = await self._rag.extract_terms(doc)
            extracted.append(normalize_terms(terms))

        # --- Stage 4: timeline reconciliation ---
        resolved = self._timeline.build(extracted, when, request.provider_npi)

        # --- Stage 5: strict grader ---
        facility = infer_facility(resolved)
        report = await self._grader.validate(
            agreement=agreement, resolved=resolved, facility=facility
        )

        if self._audit_repo is not None:
            await self._audit_repo.save(report)

        return AuditResponse(status=report.outcome, report=report)

    async def run_all(self, as_of: date | None = None) -> list[AuditResponse]:
        """Audit every provider agreement on file (powers the portfolio dashboard)."""
        agreements = await self._agreements.list_all()
        responses: list[AuditResponse] = []
        for agreement in agreements:
            request = AuditRequest(
                provider_npi=agreement.provider_npi,
                state=agreement.state,
                lob=agreement.lob,
                contract_id=agreement.contract_id,
            )
            responses.append(await self.run(request, as_of=as_of))
        return responses

    def _early_fail(
        self,
        agreement: ProviderAgreement,
        code: AuditErrorCode,
        field: str,
        message: str,
    ) -> AuditResponse:
        finding = AuditFinding(
            code=code,
            field=field,
            passed=False,
            severity=FindingSeverity.ERROR,
            message=message,
        )
        report = AuditReport(
            contract_id=agreement.contract_id,
            provider_npi=agreement.provider_npi,
            state=agreement.state,
            lob=agreement.lob,
            outcome=AuditOutcome.FAIL,
            findings=[finding],
            checks_total=1,
            checks_failed=1,
        )
        return AuditResponse(status=AuditOutcome.FAIL, report=report)


def _require(value: str | None, what: str) -> str:
    if not value:
        raise ConfigurationError(f"{what} is not configured.")
    return value


async def build_default_pipeline(settings: Settings) -> tuple[AuditPipeline, Database]:
    """Construct the Azure-backed pipeline and open the DB pool.

    Raises :class:`ConfigurationError` if required Azure settings are missing.
    """
    db = Database(settings.sql_connection_string())
    await db.connect()

    search = SearchIndex(
        endpoint=_require(settings.azure_search_endpoint, "AZURE_SEARCH_ENDPOINT"),
        key=_require(settings.azure_search_key, "AZURE_SEARCH_KEY"),
        index_name=settings.azure_search_index,
        dimensions=settings.embedding_dimensions,
    )
    # Constructed for completeness/lifecycle parity; ingestion uses it directly.
    BlobStore(
        container=settings.blob_container,
        connection_string=settings.azure_blob_connection_string,
        account_url=settings.azure_blob_account_url,
    )

    rag_agent = RagAgent(
        settings=settings,
        search_index=search,
        prompt_repo=PromptRepository(db),
        cache_repo=DocCacheRepository(db),
    )
    pipeline = AuditPipeline(
        settings=settings,
        agreement_repo=ProviderAgreementRepository(db),
        document_repo=DocumentRepository(db),
        rag_agent=rag_agent,
        timeline_builder=TimelineBuilder(),
        grader=StrictGrader(settings, FacetsRepository(db)),
        audit_repo=AuditRunRepository(db),
    )
    return pipeline, db
