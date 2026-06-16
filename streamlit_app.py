"""Streamlit demo UI for the contract auditor.

Two views (sidebar): a single-contract audit, and a portfolio dashboard that audits every
contract on file and shows aggregate compliance. Run locally:  streamlit run streamlit_app.py
Needs the same AZURE_* / GITHUB_TOKEN settings as the API (see SETUP.md).
"""

import asyncio

import streamlit as st

from agents.llm_client import get_active_provider
from config import ConfigurationError, get_settings, get_version
from models import AuditOutcome, AuditRequest, AuditResponse, PortfolioSummary
from pipeline import build_default_pipeline
from reporting import summarize_portfolio

# Demo providers seeded by db/seed_data.sql.
DEMO_PROVIDERS = {
    "Provider A — TX Medicare": AuditRequest(
        provider_npi="1234567890", state="TX", lob="Medicare", contract_id="C-TX-001"
    ),
    "Provider B — NY Medicaid": AuditRequest(
        provider_npi="1987654321", state="NY", lob="Medicaid", contract_id="C-NY-001"
    ),
}


async def _run_audit(request: AuditRequest) -> AuditResponse:
    """Build the pipeline, run one audit, tear down the DB pool."""
    settings = get_settings()
    pipeline, db = await build_default_pipeline(settings)
    try:
        return await pipeline.run(request)
    finally:
        await db.close()


async def _run_portfolio() -> tuple[PortfolioSummary, list[AuditResponse]]:
    """Audit every contract on file and summarise."""
    settings = get_settings()
    pipeline, db = await build_default_pipeline(settings)
    try:
        responses = await pipeline.run_all()
        return summarize_portfolio(responses), responses
    finally:
        await db.close()


def _render_report(response: AuditResponse) -> None:
    if response.status == AuditOutcome.PASS:
        st.success("✅ PASS — contract matches the benchmarks")
    elif response.status == AuditOutcome.FAIL:
        st.error("❌ FAIL — see findings below")
    else:
        st.warning(f"⚠️ ERROR — {response.message or 'could not complete the audit'}")

    report = response.report
    if report is None:
        return
    st.caption(
        f"Case type: {report.case_type or 'n/a'} · "
        f"{report.checks_failed}/{report.checks_total} checks failed · "
        f"request {response.request_id}"
    )
    rows = [
        {
            "code": str(f.code) if f.code else "",
            "field": f.field,
            "passed": "✅" if f.passed else "❌",
            "expected": f.expected or "",
            "actual": f.actual or "",
            "message": f.message,
        }
        for f in report.findings
    ]
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_dashboard(summary: PortfolioSummary, responses: list[AuditResponse]) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Contracts audited", summary.total_contracts)
    col2.metric("Compliance rate", f"{summary.compliance_rate * 100:.0f}%")
    col3.metric("Est. exposure", f"${summary.estimated_exposure_usd:,.0f}")
    st.caption(
        f"{summary.passed} pass · {summary.failed} fail · {summary.errored} error  ·  "
        "exposure is an illustrative estimate per non-compliant contract"
    )

    if summary.findings_by_code:
        st.subheader("Violations by error code")
        st.bar_chart(
            {
                "code": list(summary.findings_by_code.keys()),
                "count": list(summary.findings_by_code.values()),
            },
            x="code",
            y="count",
        )

    st.subheader("Per-contract results")
    st.dataframe(
        [
            {
                "contract": r.report.contract_id if r.report else "—",
                "provider": r.report.provider_npi if r.report else "—",
                "state": r.report.state if r.report else "—",
                "outcome": r.status.value.upper(),
                "checks_failed": r.report.checks_failed if r.report else "—",
                "case_type": (r.report.case_type or "n/a") if r.report else "n/a",
            }
            for r in responses
        ],
        use_container_width=True,
        hide_index=True,
    )

    if summary.flagged_for_review:
        st.subheader("⚠️ Flagged for human review (uncertain extraction)")
        st.dataframe(
            [
                {"contract": f.contract_id, "provider": f.provider_npi, "reason": f.reason}
                for f in summary.flagged_for_review
            ],
            use_container_width=True,
            hide_index=True,
        )


def _single_audit_view() -> None:
    choice = st.radio("Pick a provider to audit", list(DEMO_PROVIDERS.keys()))
    request = DEMO_PROVIDERS[choice]
    with st.expander("Or enter custom details"):
        npi = st.text_input("Provider NPI", request.provider_npi)
        state = st.text_input("State", request.state)
        lob = st.text_input("Line of business", request.lob)
        contract_id = st.text_input("Contract ID", request.contract_id)
        if st.checkbox("Use custom details"):
            request = AuditRequest(provider_npi=npi, state=state, lob=lob, contract_id=contract_id)

    if st.button("Run audit", type="primary"):
        with st.spinner("Running the 5-stage pipeline…"):
            try:
                response = asyncio.run(_run_audit(request))
            except ConfigurationError as exc:
                st.warning(f"Azure not configured yet (see SETUP.md). Details: {exc}")
                return
            except Exception as exc:  # surface DB/LLM errors in the UI rather than crashing
                st.error(f"Audit failed: {exc}")
                return
        _render_report(response)


def _dashboard_view() -> None:
    st.write("Audit every contract on file and view aggregate compliance.")
    if st.button("Run portfolio audit", type="primary"):
        with st.spinner("Auditing all contracts…"):
            try:
                summary, responses = asyncio.run(_run_portfolio())
            except ConfigurationError as exc:
                st.warning(f"Azure not configured yet (see SETUP.md). Details: {exc}")
                return
            except Exception as exc:  # surface DB/LLM errors in the UI rather than crashing
                st.error(f"Portfolio audit failed: {exc}")
                return
        _render_dashboard(summary, responses)


def main() -> None:
    st.set_page_config(page_title="Healthcare Contract Auditor", page_icon="📄", layout="wide")
    st.title("📄 Healthcare Contract Auditor")
    st.write(
        "An LLM extracts contract terms; a deterministic rules engine checks them against "
        "CMS Medicare benchmarks and returns PASS/FAIL reports with error codes."
    )
    st.caption(f"LLM provider: **{get_active_provider()}** · version {get_version()}")

    view = st.sidebar.radio("View", ["Single contract audit", "Portfolio dashboard"])
    if view == "Portfolio dashboard":
        _dashboard_view()
    else:
        _single_audit_view()


main()
