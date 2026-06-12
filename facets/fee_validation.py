"""Stage 5: the strict grader — 6 case types, parameterized SQL audit, error codes.

The AI proposes; the SQL disposes. This compares resolved contract terms against
ground-truth benchmarks pulled from facets_sim and emits coded findings.
"""

import logging

from config import Settings
from db.repository import FacetsRepository
from models import (
    AuditErrorCode,
    AuditFinding,
    AuditOutcome,
    AuditReport,
    CaseType,
    FacilityType,
    FindingSeverity,
    MatchType,
    ProviderAgreement,
    RateType,
    ResolvedTerms,
)

logger = logging.getLogger(__name__)

# (state, lob-lowercased, facility) -> case type. One of the 6 supported combinations.
CASE_TYPE_MAP: dict[tuple[str, str, FacilityType], CaseType] = {
    ("TX", "medicare", FacilityType.PROFESSIONAL): CaseType.TX_MEDICARE_PROFESSIONAL,
    ("FL", "medicare", FacilityType.PROFESSIONAL): CaseType.FL_MEDICARE_PROFESSIONAL,
    ("CA", "medicare", FacilityType.SNF): CaseType.CA_MEDICARE_SNF,
    ("CA", "medicare", FacilityType.OUTPATIENT): CaseType.CA_MEDICARE_OUTPATIENT,
    ("NY", "medicaid", FacilityType.OUTPATIENT): CaseType.NY_MEDICAID_OUTPATIENT,
    ("TX", "medicaid", FacilityType.PROFESSIONAL): CaseType.TX_MEDICAID_PROFESSIONAL,
}


def resolve_case_type(state: str, lob: str, facility: FacilityType) -> CaseType | None:
    """Map (state, lob, facility) to one of the 6 validation case types."""
    return CASE_TYPE_MAP.get((state.strip().upper(), lob.strip().lower(), facility))


def _fail(
    code: AuditErrorCode,
    field: str,
    expected: str | None,
    actual: str | None,
    message: str,
    match_type: MatchType | None = None,
) -> AuditFinding:
    return AuditFinding(
        code=code,
        field=field,
        passed=False,
        severity=FindingSeverity.ERROR,
        expected=expected,
        actual=actual,
        match_type=match_type,
        message=message,
    )


def _ok(
    field: str,
    expected: str | None,
    actual: str | None,
    message: str,
    match_type: MatchType | None = None,
) -> AuditFinding:
    return AuditFinding(
        code=None,
        field=field,
        passed=True,
        severity=FindingSeverity.INFO,
        expected=expected,
        actual=actual,
        match_type=match_type,
        message=message,
    )


class StrictGrader:
    """Compares resolved contract terms against facets_sim ground truth."""

    def __init__(self, settings: Settings, facets_repo: FacetsRepository) -> None:
        self._settings = settings
        self._facets = facets_repo

    async def validate(
        self,
        *,
        agreement: ProviderAgreement,
        resolved: ResolvedTerms,
        facility: FacilityType,
    ) -> AuditReport:
        """Run all checks and assemble the audit report."""
        case_type = resolve_case_type(agreement.state, agreement.lob, facility)

        findings: list[AuditFinding] = []
        findings.extend(await self._check_timely_filing(agreement, resolved))
        findings.extend(await self._check_lesser_of(agreement, resolved))
        findings.extend(await self._check_fee_schedule(agreement, resolved))

        failed = [f for f in findings if not f.passed and f.severity == FindingSeverity.ERROR]
        outcome = AuditOutcome.FAIL if failed else AuditOutcome.PASS
        return AuditReport(
            contract_id=agreement.contract_id,
            provider_npi=agreement.provider_npi,
            state=agreement.state,
            lob=agreement.lob,
            case_type=case_type,
            outcome=outcome,
            findings=findings,
            checks_total=len(findings),
            checks_failed=len(failed),
        )

    async def _check_timely_filing(
        self, agreement: ProviderAgreement, resolved: ResolvedTerms
    ) -> list[AuditFinding]:
        benchmark = await self._facets.filing_benchmark(agreement.state, agreement.lob)
        actual = resolved.timely_filing_days
        if actual is None:
            return [
                _fail(
                    AuditErrorCode.TF002,
                    "timely_filing_days",
                    str(benchmark) if benchmark is not None else None,
                    None,
                    "Contract is missing a timely-filing rule.",
                )
            ]
        if benchmark is None:
            return [
                _ok(
                    "timely_filing_days",
                    None,
                    str(actual),
                    "No benchmark configured; recorded the contract value.",
                )
            ]
        if actual == benchmark:
            return [
                _ok(
                    "timely_filing_days",
                    str(benchmark),
                    str(actual),
                    "Timely-filing window matches benchmark.",
                    MatchType.EXACT,
                )
            ]
        return [
            _fail(
                AuditErrorCode.TF001,
                "timely_filing_days",
                str(benchmark),
                str(actual),
                f"Timely-filing window {actual} days does not match benchmark {benchmark}.",
                MatchType.EXACT,
            )
        ]

    async def _check_lesser_of(
        self, agreement: ProviderAgreement, resolved: ResolvedTerms
    ) -> list[AuditFinding]:
        policy = await self._facets.reimbursement_policy(agreement.state, agreement.lob)
        required = bool(policy["lesser_of_required"]) if policy else False
        if not required:
            return []
        if resolved.lesser_of_applies is None:
            return [
                _fail(
                    AuditErrorCode.LL001,
                    "lesser_of",
                    "required",
                    None,
                    "Lesser-of logic is required for this case type but is missing.",
                )
            ]
        if resolved.lesser_of_applies:
            return [_ok("lesser_of", "required", "applies", "Lesser-of logic is present.")]
        return [
            _fail(
                AuditErrorCode.LL003,
                "lesser_of",
                "required",
                "does not apply",
                "Lesser-of logic is required but the contract does not apply it.",
            )
        ]

    async def _check_fee_schedule(
        self, agreement: ProviderAgreement, resolved: ResolvedTerms
    ) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        policy = await self._facets.reimbursement_policy(agreement.state, agreement.lob)
        expected_pct: float | None = None
        if policy and policy.get("expected_pct_of_medicare") is not None:
            expected_pct = float(policy["expected_pct_of_medicare"])

        for rate in resolved.reimbursement_rates:
            if rate.rate_type == RateType.PERCENT_OF_MEDICARE and expected_pct is not None:
                deviation = abs(rate.value - expected_pct)
                if deviation <= self._settings.percent_tolerance:
                    findings.append(
                        _ok(
                            f"rate:{rate.service}",
                            f"{expected_pct}%",
                            f"{rate.value}%",
                            "Rate is within tolerance of the benchmark.",
                            MatchType.TOLERANCE,
                        )
                    )
                else:
                    findings.append(
                        _fail(
                            AuditErrorCode.FS002,
                            f"rate:{rate.service}",
                            f"{expected_pct}%",
                            f"{rate.value}%",
                            f"Rate for {rate.service} deviates {deviation:.2f} points beyond "
                            f"tolerance {self._settings.percent_tolerance}.",
                            MatchType.TOLERANCE,
                        )
                    )
            elif rate.rate_type == RateType.FLAT_AMOUNT and rate.cpt_codes:
                for cpt in rate.cpt_codes:
                    mpfs = await self._facets.mpfs_amount(cpt, self._settings.default_locality)
                    if mpfs is None:
                        continue
                    if abs(rate.value - mpfs) <= self._settings.amount_tolerance:
                        findings.append(
                            _ok(
                                f"fee:{cpt}",
                                f"${mpfs:.2f}",
                                f"${rate.value:.2f}",
                                "Flat fee matches the MPFS amount.",
                                MatchType.EXACT,
                            )
                        )
                    else:
                        findings.append(
                            _fail(
                                AuditErrorCode.FS001,
                                f"fee:{cpt}",
                                f"${mpfs:.2f}",
                                f"${rate.value:.2f}",
                                f"Flat fee for CPT {cpt} deviates from the MPFS amount.",
                                MatchType.EXACT,
                            )
                        )
        return findings
