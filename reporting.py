"""Portfolio-level aggregation for the dashboard (pure, deterministic, testable)."""

from collections import Counter

from models import (
    AuditErrorCode,
    AuditOutcome,
    AuditResponse,
    FlaggedItem,
    PortfolioSummary,
)

# Illustrative dollar exposure assumed per non-compliant contract (clearly an estimate,
# configurable). Used only to give the dashboard a tangible business number.
DEFAULT_EXPOSURE_PER_FAILURE_USD = 5_000.0

# Codes that suggest the AI extraction may have missed/been uncertain — surface these
# for a human to confirm rather than trusting them blindly.
_REVIEW_CODES = {AuditErrorCode.TF002, AuditErrorCode.LL001, AuditErrorCode.DOC001}


def summarize_portfolio(
    responses: list[AuditResponse],
    exposure_per_failure_usd: float = DEFAULT_EXPOSURE_PER_FAILURE_USD,
) -> PortfolioSummary:
    """Aggregate a batch of audit responses into a dashboard summary."""
    total = len(responses)
    passed = sum(1 for r in responses if r.status == AuditOutcome.PASS)
    failed = sum(1 for r in responses if r.status == AuditOutcome.FAIL)
    errored = sum(1 for r in responses if r.status == AuditOutcome.ERROR)

    code_counts: Counter[str] = Counter()
    flagged: list[FlaggedItem] = []
    for response in responses:
        report = response.report
        if report is None:
            continue
        for finding in report.findings:
            if finding.code is not None and not finding.passed:
                code_counts[finding.code.value] += 1
        review_reasons = [
            f.code.value
            for f in report.findings
            if not f.passed and f.code is not None and f.code in _REVIEW_CODES
        ]
        if response.status == AuditOutcome.ERROR or review_reasons:
            flagged.append(
                FlaggedItem(
                    contract_id=report.contract_id,
                    provider_npi=report.provider_npi,
                    reason=(
                        response.message
                        or f"Possible missing/uncertain extraction: {', '.join(review_reasons)}"
                    ),
                )
            )

    return PortfolioSummary(
        total_contracts=total,
        passed=passed,
        failed=failed,
        errored=errored,
        compliance_rate=(passed / total) if total else 0.0,
        findings_by_code=dict(code_counts),
        estimated_exposure_usd=failed * exposure_per_failure_usd,
        flagged_for_review=flagged,
    )
