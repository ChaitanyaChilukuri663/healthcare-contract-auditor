"""Streamlit demo UI for the contract auditor.

Three sidebar views: **Upload a contract** (LLM extraction only — needs just the LLM token,
no Azure), a single-contract audit, and a portfolio dashboard (the latter two use the Azure
backend). Run locally:  streamlit run streamlit_app.py   (see SETUP.md for configuration).
"""

import asyncio
import os

import streamlit as st

from agents.agent_rag import extract_terms_from_text
from agents.llm_client import get_active_provider
from config import ConfigurationError, get_settings, get_version
from document_extraction.pdf_ingest import extract_pages
from models import AuditOutcome, AuditRequest, AuditResponse, ExtractedTerms, PortfolioSummary
from pipeline import build_default_pipeline
from reporting import summarize_portfolio

# On Streamlit Cloud, config is provided via st.secrets; mirror it into the environment so
# the standard Settings / llm_client (which read os.environ) pick it up. Locally this is a
# no-op and the .env file is used instead.
try:
    for _secret_key, _secret_value in st.secrets.items():
        os.environ.setdefault(_secret_key, str(_secret_value))
except Exception:
    pass

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


def _render_terms(terms: ExtractedTerms) -> None:
    st.subheader("Extracted terms")
    tf = terms.timely_filing
    if tf is not None:
        eff = f" · effective {tf.effective_date}" if tf.effective_date else ""
        st.markdown(f"**Timely filing:** {tf.days_to_file} days{eff}")
        if tf.source_excerpt:
            st.caption(tf.source_excerpt)
    else:
        st.markdown("**Timely filing:** _not found_")

    lo = terms.lesser_of
    if lo is not None:
        st.markdown(
            f"**Lesser-of logic:** applies — {lo.basis or 'lesser of billed vs fee schedule'}"
        )
        if lo.source_excerpt:
            st.caption(lo.source_excerpt)
    else:
        st.markdown("**Lesser-of logic:** _not found_")

    if terms.reimbursement_rates:
        st.markdown("**Reimbursement rates:**")
        st.dataframe(
            [
                {
                    "service": r.service,
                    "type": r.rate_type.value,
                    "value": r.value,
                    "cpt": ", ".join(r.cpt_codes),
                }
                for r in terms.reimbursement_rates
            ],
            hide_index=True,
        )
    else:
        st.markdown("**Reimbursement rates:** _none found_")

    st.caption(
        "Extraction only. The full pipeline also validates these against CMS benchmarks with a "
        "deterministic rules engine (see the other views and the README)."
    )


def _upload_view() -> None:
    st.write(
        "Upload a provider-contract PDF and the AI extracts the key terms — timely-filing "
        "window, lesser-of logic, and reimbursement rates. No account needed."
    )
    uploaded = st.file_uploader("Contract PDF", type=["pdf"])
    if uploaded is not None and st.button("Extract terms", type="primary"):
        with st.spinner("Reading the contract and extracting terms…"):
            try:
                text = "\n".join(extract_pages(uploaded.getvalue()))
            except Exception as exc:  # malformed / unreadable PDF
                st.error(f"Couldn't read that PDF: {exc}")
                return
            if not text.strip():
                st.warning("No text found — is this a scanned image rather than a text PDF?")
                return
            try:
                terms = asyncio.run(extract_terms_from_text(text))
            except Exception as exc:  # LLM / network / rate limit
                st.error(
                    "Extraction failed — the free demo token may be rate-limited (150/day). "
                    f"Please try again later. ({exc})"
                )
                return
        _render_terms(terms)


def main() -> None:
    st.set_page_config(page_title="Healthcare Contract Auditor", page_icon="📄", layout="wide")
    st.title("📄 Healthcare Contract Auditor")
    st.write(
        "An LLM extracts contract terms; a deterministic rules engine checks them against "
        "CMS Medicare benchmarks and returns PASS/FAIL reports with error codes."
    )
    st.caption(f"LLM provider: **{get_active_provider()}** · version {get_version()}")

    view = st.sidebar.radio(
        "View", ["Upload a contract", "Single contract audit", "Portfolio dashboard"]
    )
    if view == "Upload a contract":
        _upload_view()
    elif view == "Portfolio dashboard":
        _dashboard_view()
    else:
        _single_audit_view()


main()
