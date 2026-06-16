"""Tests for Stage 5 strict grader, case-type resolution, and normalization."""

from datetime import date
from typing import Any, cast

from config import Settings
from db.repository import FacetsRepository
from facets.fee_extraction import dedupe_rates, map_facility, map_lob, normalize_service
from facets.fee_validation import StrictGrader, resolve_case_type
from facets.multi_records import infer_facility, standardize_provider_type
from models import (
    AuditErrorCode,
    AuditOutcome,
    CaseType,
    FacilityType,
    ProviderAgreement,
    RateType,
    ReimbursementRate,
    ResolvedTerms,
)


class FakeFacets:
    """Hand-rolled fake of FacetsRepository for grader tests."""

    def __init__(
        self,
        filing: int | None,
        policy: dict[str, Any] | None,
        mpfs: float | None = None,
    ) -> None:
        self._filing = filing
        self._policy = policy
        self._mpfs = mpfs

    async def filing_benchmark(self, state: str, lob: str) -> int | None:
        return self._filing

    async def reimbursement_policy(self, state: str, lob: str) -> dict[str, Any] | None:
        return self._policy

    async def mpfs_amount(self, cpt_code: str, locality: str) -> float | None:
        return self._mpfs


def _grader(fake: FakeFacets) -> StrictGrader:
    return StrictGrader(Settings(), cast(FacetsRepository, fake))


def _agreement(state: str, lob: str) -> ProviderAgreement:
    return ProviderAgreement(
        provider_npi="1234567890",
        contract_id="C-1",
        state=state,
        lob=lob,
        effective_date=date(2023, 1, 1),
    )


# --- case-type resolution -------------------------------------------------


def test_resolve_case_type_known() -> None:
    assert (
        resolve_case_type("TX", "Medicare", FacilityType.PROFESSIONAL)
        == CaseType.TX_MEDICARE_PROFESSIONAL
    )
    assert (
        resolve_case_type("ny", "medicaid", FacilityType.OUTPATIENT)
        == CaseType.NY_MEDICAID_OUTPATIENT
    )


def test_resolve_case_type_unknown() -> None:
    assert resolve_case_type("WA", "Commercial", FacilityType.INPATIENT) is None


def test_resolve_case_type_falls_back_on_facility() -> None:
    # NY/Medicaid with a non-outpatient facility still classifies via the (state, lob) fallback.
    assert (
        resolve_case_type("NY", "Medicaid", FacilityType.PROFESSIONAL)
        == CaseType.NY_MEDICAID_OUTPATIENT
    )


# --- grader: compliant path ----------------------------------------------


async def test_compliant_contract_passes() -> None:
    grader = _grader(
        FakeFacets(filing=90, policy={"lesser_of_required": 1, "expected_pct_of_medicare": 100.0})
    )
    resolved = ResolvedTerms(
        provider_npi="1234567890",
        as_of=date(2024, 6, 1),
        timely_filing_days=90,
        lesser_of_applies=True,
        reimbursement_rates=[
            ReimbursementRate(
                service="Physical Therapy",
                rate_type=RateType.PERCENT_OF_MEDICARE,
                value=100.0,
                source_excerpt="100% of Medicare",
            )
        ],
    )
    report = await grader.validate(
        agreement=_agreement("TX", "Medicare"),
        resolved=resolved,
        facility=FacilityType.PROFESSIONAL,
    )
    assert report.outcome == AuditOutcome.PASS
    assert report.case_type == CaseType.TX_MEDICARE_PROFESSIONAL
    assert report.checks_failed == 0


# --- grader: non-compliant path ------------------------------------------


async def test_noncompliant_contract_fails_with_codes() -> None:
    grader = _grader(
        FakeFacets(filing=90, policy={"lesser_of_required": 1, "expected_pct_of_medicare": 100.0})
    )
    resolved = ResolvedTerms(
        provider_npi="1987654321",
        as_of=date(2024, 6, 1),
        timely_filing_days=180,  # != 90 -> TF001
        lesser_of_applies=None,  # required but missing -> LL001
        reimbursement_rates=[
            ReimbursementRate(
                service="Speech Therapy",
                rate_type=RateType.PERCENT_OF_MEDICARE,
                value=130.0,  # != 100 beyond tolerance -> FS002
                source_excerpt="130% of Medicare",
            )
        ],
    )
    report = await grader.validate(
        agreement=_agreement("NY", "Medicaid"),
        resolved=resolved,
        facility=FacilityType.OUTPATIENT,
    )
    assert report.outcome == AuditOutcome.FAIL
    codes = {finding.code for finding in report.findings if finding.code}
    assert AuditErrorCode.TF001 in codes
    assert AuditErrorCode.LL001 in codes
    assert AuditErrorCode.FS002 in codes


async def test_missing_timely_filing_emits_tf002() -> None:
    grader = _grader(FakeFacets(filing=90, policy=None))
    resolved = ResolvedTerms(provider_npi="n", as_of=date(2024, 1, 1), timely_filing_days=None)
    report = await grader.validate(
        agreement=_agreement("TX", "Medicare"),
        resolved=resolved,
        facility=FacilityType.PROFESSIONAL,
    )
    assert report.outcome == AuditOutcome.FAIL
    assert any(f.code == AuditErrorCode.TF002 for f in report.findings)


async def test_flat_fee_mismatch_emits_fs001() -> None:
    grader = _grader(FakeFacets(filing=90, policy=None, mpfs=50.00))
    resolved = ResolvedTerms(
        provider_npi="n",
        as_of=date(2024, 1, 1),
        timely_filing_days=90,
        reimbursement_rates=[
            ReimbursementRate(
                service="Office Visit",
                rate_type=RateType.FLAT_AMOUNT,
                value=75.00,  # != 50.00 MPFS -> FS001
                cpt_codes=["99213"],
                source_excerpt="flat $75",
            )
        ],
    )
    report = await grader.validate(
        agreement=_agreement("TX", "Medicare"),
        resolved=resolved,
        facility=FacilityType.PROFESSIONAL,
    )
    assert any(f.code == AuditErrorCode.FS001 for f in report.findings)


# --- normalization helpers -----------------------------------------------


def test_map_lob_and_facility() -> None:
    assert map_lob("Medicaid") == "CAID"
    assert map_lob("Medicare Advantage") == "MAPD"
    assert map_facility("Skilled Nursing Facility") == "SNF"


def test_normalize_service_and_dedupe() -> None:
    assert normalize_service("  physical   therapy ") == "Physical Therapy"
    rate = ReimbursementRate(
        service="PT", rate_type=RateType.PERCENT_OF_MEDICARE, value=100.0, source_excerpt="x"
    )
    assert len(dedupe_rates([rate, rate.model_copy()])) == 1


def test_standardize_and_infer_facility() -> None:
    assert standardize_provider_type("Skilled Nursing Facility services") == FacilityType.SNF
    resolved = ResolvedTerms(
        provider_npi="n",
        as_of=date(2024, 1, 1),
        reimbursement_rates=[
            ReimbursementRate(
                service="Outpatient surgery",
                rate_type=RateType.PERCENT_OF_MEDICARE,
                value=100.0,
                source_excerpt="x",
            )
        ],
    )
    assert infer_facility(resolved) == FacilityType.OUTPATIENT
