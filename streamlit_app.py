"""Streamlit demo UI for the contract auditor.

Pick a provider, run the audit pipeline, and see the PASS/FAIL report with error codes.
Run locally:  streamlit run streamlit_app.py
Needs the same AZURE_* / GITHUB_TOKEN settings as the API (see SETUP.md).
"""

import asyncio

import streamlit as st

from agents.llm_client import get_active_provider
from config import ConfigurationError, get_settings, get_version
from models import AuditOutcome, AuditRequest, AuditResponse
from pipeline import build_default_pipeline

# Demo providers seeded by db/seed_data.sql.
DEMO_PROVIDERS = {
    "Provider A — TX Medicare (expected: PASS)": AuditRequest(
        provider_npi="1234567890", state="TX", lob="Medicare", contract_id="C-TX-001"
    ),
    "Provider B — NY Medicaid (expected: FAIL)": AuditRequest(
        provider_npi="1987654321", state="NY", lob="Medicaid", contract_id="C-NY-001"
    ),
}


async def _run_audit(request: AuditRequest) -> AuditResponse:
    """Build the pipeline, run one audit, and tear down the DB pool."""
    settings = get_settings()
    pipeline, db = await build_default_pipeline(settings)
    try:
        return await pipeline.run(request)
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
            "code": str(finding.code) if finding.code else "",
            "field": finding.field,
            "passed": "✅" if finding.passed else "❌",
            "expected": finding.expected or "",
            "actual": finding.actual or "",
            "message": finding.message,
        }
        for finding in report.findings
    ]
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Healthcare Contract Auditor", page_icon="📄")
    st.title("📄 Healthcare Contract Auditor")
    st.write(
        "An LLM extracts contract terms; a deterministic rules engine checks them against "
        "CMS Medicare benchmarks and returns a PASS/FAIL report with error codes."
    )
    st.caption(f"LLM provider: **{get_active_provider()}** · version {get_version()}")

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
                st.warning(
                    "Azure is not configured yet, so the audit can't run. "
                    f"Set the AZURE_* values (see SETUP.md). Details: {exc}"
                )
                return
            except Exception as exc:  # surface DB/LLM errors in the UI rather than crashing
                st.error(f"Audit failed: {exc}")
                return
        _render_report(response)


main()
