"""Tests for the end-to-end audit pipeline orchestration (mocked components)."""

from datetime import date
from typing import Any, cast

from agents.agent_rag import RagAgent
from config import Settings
from db.repository import (
    DocumentRepository,
    FacetsRepository,
    ProviderAgreementRepository,
)
from document_extraction.timeline_builder import TimelineBuilder
from facets.fee_validation import StrictGrader
from models import (
    AuditErrorCode,
    AuditOutcome,
    AuditRequest,
    DocumentMeta,
    DocumentType,
    ExtractedTerms,
    LesserOfRule,
    ProviderAgreement,
    RateType,
    ReimbursementRate,
    TimelyFilingRule,
)
from pipeline import AuditPipeline

AS_OF = date(2024, 6, 1)


class FakeAgreementRepo:
    def __init__(self, agreement: ProviderAgreement | None) -> None:
        self._agreement = agreement

    async def get(
        self, provider_npi: str, contract_id: str, state: str
    ) -> ProviderAgreement | None:
        return self._agreement


class FakeDocumentRepo:
    def __init__(self, docs: list[DocumentMeta]) -> None:
        self._docs = docs

    async def list_for(self, provider_npi: str, state: str) -> list[DocumentMeta]:
        return self._docs


class FakeRag:
    def __init__(self, terms: ExtractedTerms) -> None:
        self._terms = terms

    async def extract_terms(self, doc: DocumentMeta) -> ExtractedTerms:
        return self._terms


class FakeFacets:
    def __init__(self, filing: int | None, policy: dict[str, Any] | None) -> None:
        self._filing = filing
        self._policy = policy

    async def filing_benchmark(self, state: str, lob: str) -> int | None:
        return self._filing

    async def reimbursement_policy(self, state: str, lob: str) -> dict[str, Any] | None:
        return self._policy

    async def mpfs_amount(self, cpt_code: str, locality: str) -> float | None:
        return None


def _doc() -> DocumentMeta:
    return DocumentMeta(
        doc_id="d1",
        provider_npi="1234567890",
        state="TX",
        doc_type=DocumentType.CONTRACT,
        blob_path="blob://x",
        doc_hash="h1",
        effective_date=date(2023, 1, 1),
    )


def _pipeline(
    agreement: ProviderAgreement | None,
    docs: list[DocumentMeta],
    terms: ExtractedTerms,
    facets: FakeFacets,
) -> AuditPipeline:
    settings = Settings()
    return AuditPipeline(
        settings=settings,
        agreement_repo=cast(ProviderAgreementRepository, FakeAgreementRepo(agreement)),
        document_repo=cast(DocumentRepository, FakeDocumentRepo(docs)),
        rag_agent=cast(RagAgent, FakeRag(terms)),
        timeline_builder=TimelineBuilder(),
        grader=StrictGrader(settings, cast(FacetsRepository, facets)),
        audit_repo=None,
    )


def _agreement(state: str, lob: str, terminate: date | None = None) -> ProviderAgreement:
    return ProviderAgreement(
        provider_npi="1234567890",
        contract_id="C-1",
        state=state,
        lob=lob,
        effective_date=date(2023, 1, 1),
        terminate_date=terminate,
    )


def _compliant_terms() -> ExtractedTerms:
    return ExtractedTerms(
        doc_id="d1",
        provider_npi="1234567890",
        effective_date=date(2023, 1, 1),
        timely_filing=TimelyFilingRule(
            days_to_file=90, effective_date=date(2023, 1, 1), source_excerpt="90 days"
        ),
        lesser_of=LesserOfRule(applies=True, basis="lesser of", source_excerpt="x"),
        reimbursement_rates=[
            ReimbursementRate(
                service="Physical Therapy",
                rate_type=RateType.PERCENT_OF_MEDICARE,
                value=100.0,
                source_excerpt="100%",
            )
        ],
    )


async def test_missing_agreement_returns_error() -> None:
    pipeline = _pipeline(None, [], _compliant_terms(), FakeFacets(90, None))
    response = await pipeline.run(
        AuditRequest(provider_npi="1234567890", state="TX", lob="Medicare", contract_id="C-1"),
        as_of=AS_OF,
    )
    assert response.status == AuditOutcome.ERROR
    assert response.report is None
    assert response.message


async def test_inactive_agreement_fails_ag001() -> None:
    agreement = _agreement("TX", "Medicare", terminate=date(2023, 12, 31))
    pipeline = _pipeline(agreement, [_doc()], _compliant_terms(), FakeFacets(90, None))
    response = await pipeline.run(
        AuditRequest(provider_npi="1234567890", state="TX", lob="Medicare", contract_id="C-1"),
        as_of=AS_OF,
    )
    assert response.status == AuditOutcome.FAIL
    assert response.report is not None
    assert any(f.code == AuditErrorCode.AG001 for f in response.report.findings)


async def test_no_documents_fails_doc001() -> None:
    pipeline = _pipeline(_agreement("TX", "Medicare"), [], _compliant_terms(), FakeFacets(90, None))
    response = await pipeline.run(
        AuditRequest(provider_npi="1234567890", state="TX", lob="Medicare", contract_id="C-1"),
        as_of=AS_OF,
    )
    assert response.status == AuditOutcome.FAIL
    assert response.report is not None
    assert any(f.code == AuditErrorCode.DOC001 for f in response.report.findings)


async def test_compliant_contract_passes_end_to_end() -> None:
    facets = FakeFacets(90, {"lesser_of_required": 1, "expected_pct_of_medicare": 100.0})
    pipeline = _pipeline(_agreement("TX", "Medicare"), [_doc()], _compliant_terms(), facets)
    response = await pipeline.run(
        AuditRequest(provider_npi="1234567890", state="TX", lob="Medicare", contract_id="C-1"),
        as_of=AS_OF,
    )
    assert response.status == AuditOutcome.PASS
    assert response.report is not None
    assert response.report.checks_failed == 0


async def test_noncompliant_contract_fails_end_to_end() -> None:
    bad_terms = ExtractedTerms(
        doc_id="d1",
        provider_npi="1234567890",
        effective_date=date(2022, 3, 1),
        timely_filing=TimelyFilingRule(
            days_to_file=180, effective_date=date(2022, 3, 1), source_excerpt="180 days"
        ),
        lesser_of=None,
        reimbursement_rates=[
            ReimbursementRate(
                service="Speech Therapy",
                rate_type=RateType.PERCENT_OF_MEDICARE,
                value=130.0,
                source_excerpt="130%",
            )
        ],
    )
    facets = FakeFacets(90, {"lesser_of_required": 1, "expected_pct_of_medicare": 100.0})
    pipeline = _pipeline(_agreement("NY", "Medicaid"), [_doc()], bad_terms, facets)
    response = await pipeline.run(
        AuditRequest(provider_npi="1987654321", state="NY", lob="Medicaid", contract_id="C-NY-001"),
        as_of=AS_OF,
    )
    assert response.status == AuditOutcome.FAIL
    assert response.report is not None
    codes = {f.code for f in response.report.findings if f.code}
    assert AuditErrorCode.TF001 in codes
    assert AuditErrorCode.LL001 in codes
    assert AuditErrorCode.FS002 in codes
