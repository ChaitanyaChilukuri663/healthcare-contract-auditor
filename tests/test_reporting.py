"""Tests for portfolio aggregation (reporting.summarize_portfolio)."""

from models import (
    AuditErrorCode,
    AuditFinding,
    AuditOutcome,
    AuditReport,
    AuditResponse,
    FindingSeverity,
)
from reporting import DEFAULT_EXPOSURE_PER_FAILURE_USD, summarize_portfolio


def _fail(code: AuditErrorCode) -> AuditFinding:
    return AuditFinding(
        code=code, field="x", passed=False, severity=FindingSeverity.ERROR, message="m"
    )


def _ok() -> AuditFinding:
    return AuditFinding(
        code=None, field="x", passed=True, severity=FindingSeverity.INFO, message="ok"
    )


def _report(
    contract_id: str, npi: str, outcome: AuditOutcome, findings: list[AuditFinding], failed: int
) -> AuditReport:
    return AuditReport(
        contract_id=contract_id,
        provider_npi=npi,
        state="TX",
        lob="Medicare",
        outcome=outcome,
        findings=findings,
        checks_total=len(findings),
        checks_failed=failed,
    )


def test_summarize_counts_codes_exposure_and_flags() -> None:
    responses = [
        AuditResponse(
            status=AuditOutcome.PASS,
            report=_report("C1", "n1", AuditOutcome.PASS, [_ok()], 0),
        ),
        AuditResponse(
            status=AuditOutcome.FAIL,
            report=_report(
                "C2",
                "n2",
                AuditOutcome.FAIL,
                [_fail(AuditErrorCode.TF001), _fail(AuditErrorCode.FS002)],
                2,
            ),
        ),
        AuditResponse(
            status=AuditOutcome.FAIL,
            report=_report("C3", "n3", AuditOutcome.FAIL, [_fail(AuditErrorCode.LL001)], 1),
        ),
    ]
    summary = summarize_portfolio(responses)

    assert summary.total_contracts == 3
    assert (summary.passed, summary.failed, summary.errored) == (1, 2, 0)
    assert summary.compliance_rate == 1 / 3
    assert summary.findings_by_code == {"TF001": 1, "FS002": 1, "LL001": 1}
    assert summary.estimated_exposure_usd == 2 * DEFAULT_EXPOSURE_PER_FAILURE_USD
    # Only C3 has a review-flagged code (LL001).
    assert [f.contract_id for f in summary.flagged_for_review] == ["C3"]


def test_summarize_empty() -> None:
    summary = summarize_portfolio([])
    assert summary.total_contracts == 0
    assert summary.compliance_rate == 0.0
    assert summary.estimated_exposure_usd == 0.0
    assert summary.findings_by_code == {}
