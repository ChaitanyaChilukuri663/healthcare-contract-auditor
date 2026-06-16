"""Pydantic v2 schemas for the full audit pipeline.

Per CLAUDE.md, every field carries ``Field(description=...)`` — for models fed to LLM
structured outputs the descriptions become part of the tool schema. Enums subclass ``str``
so they serialise cleanly to JSON.
"""

import uuid
from datetime import UTC, date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Enumerations                                                                #
# --------------------------------------------------------------------------- #


class DocumentType(StrEnum):
    """Kind of provider document."""

    CONTRACT = "contract"
    AMENDMENT = "amendment"


class FacilityType(StrEnum):
    """Facility/provider setting used for case-type resolution."""

    PROFESSIONAL = "professional"
    OUTPATIENT = "outpatient"
    SNF = "snf"
    INPATIENT = "inpatient"


class CaseType(StrEnum):
    """The 6 validation case types (State x LOB x Facility)."""

    TX_MEDICARE_PROFESSIONAL = "TX_MEDICARE_PROFESSIONAL"
    FL_MEDICARE_PROFESSIONAL = "FL_MEDICARE_PROFESSIONAL"
    CA_MEDICARE_SNF = "CA_MEDICARE_SNF"
    CA_MEDICARE_OUTPATIENT = "CA_MEDICARE_OUTPATIENT"
    NY_MEDICAID_OUTPATIENT = "NY_MEDICAID_OUTPATIENT"
    TX_MEDICAID_PROFESSIONAL = "TX_MEDICAID_PROFESSIONAL"


class RateType(StrEnum):
    """How a reimbursement rate is expressed."""

    PERCENT_OF_MEDICARE = "percent_of_medicare"
    PERCENT_OF_BILLED = "percent_of_billed"
    FLAT_AMOUNT = "flat_amount"


class AuditOutcome(StrEnum):
    """Overall result of an audit run."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


class FindingSeverity(StrEnum):
    """Severity of an individual audit finding."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class MatchType(StrEnum):
    """How a comparison was evaluated."""

    EXACT = "exact"
    TOLERANCE = "tolerance"


class AuditErrorCode(StrEnum):
    """Structured error codes emitted by the strict grader."""

    TF001 = "TF001"  # Timely filing window mismatch
    TF002 = "TF002"  # Timely filing rule missing from contract
    FS001 = "FS001"  # Fee schedule value mismatch
    FS002 = "FS002"  # Fee schedule deviation beyond tolerance
    LL001 = "LL001"  # Lesser-of logic missing
    LL003 = "LL003"  # Lesser-of logic mismatch
    AG001 = "AG001"  # Provider agreement inactive/expired
    DOC001 = "DOC001"  # No contract documents found
    EXT001 = "EXT001"  # Extraction failed


ERROR_DESCRIPTIONS: dict[AuditErrorCode, str] = {
    AuditErrorCode.TF001: "Timely filing window does not match the benchmark.",
    AuditErrorCode.TF002: "Contract is missing a timely filing rule.",
    AuditErrorCode.FS001: "Fee schedule value does not match ground truth.",
    AuditErrorCode.FS002: "Fee schedule deviation exceeds the allowed tolerance.",
    AuditErrorCode.LL001: "Contract is missing required lesser-of logic.",
    AuditErrorCode.LL003: "Lesser-of logic does not match the expected basis.",
    AuditErrorCode.AG001: "Provider agreement is inactive or expired.",
    AuditErrorCode.DOC001: "No contract documents found for the provider/state.",
    AuditErrorCode.EXT001: "AI extraction failed or returned no usable data.",
}

# --------------------------------------------------------------------------- #
# API request/response                                                        #
# --------------------------------------------------------------------------- #


class HealthResponse(BaseModel):
    """Payload for ``GET /health``."""

    status: str = Field(description="Liveness indicator; 'ok' when the service is up.")
    provider: str = Field(description="Active LLM provider (github | azure | groq).")
    version: str = Field(description="Service version, read from pyproject.toml.")


class AuditRequest(BaseModel):
    """Input to ``POST /audit_contract`` (Stage 1 of the pipeline)."""

    provider_npi: str = Field(description="10-digit National Provider Identifier (NPI).")
    state: str = Field(description="Two-letter US state code, e.g. 'TX'.")
    lob: str = Field(description="Line of business, e.g. 'Medicare', 'Medicaid', 'MAPD'.")
    contract_id: str = Field(description="Identifier of the provider agreement to audit.")


# --------------------------------------------------------------------------- #
# Stage 1-2: agreements & documents                                           #
# --------------------------------------------------------------------------- #


class ProviderAgreement(BaseModel):
    """A provider agreement row from facets_sim.provider_agreement."""

    provider_npi: str = Field(description="Provider NPI.")
    contract_id: str = Field(description="Agreement identifier.")
    state: str = Field(description="Two-letter state code.")
    lob: str = Field(description="Line of business.")
    effective_date: date = Field(description="Agreement effective date.")
    terminate_date: date | None = Field(default=None, description="Agreement end date, if any.")

    def is_active(self, as_of: date) -> bool:
        """Whether the agreement is active on ``as_of``."""
        if as_of < self.effective_date:
            return False
        return self.terminate_date is None or as_of <= self.terminate_date


class DocumentMeta(BaseModel):
    """A contract document tracked in app_config.meta_index."""

    doc_id: str = Field(description="Unique document id.")
    provider_npi: str = Field(description="Owning provider NPI.")
    state: str = Field(description="State the document applies to.")
    doc_type: DocumentType = Field(description="Contract or amendment.")
    blob_path: str = Field(description="Path/URL of the PDF in Blob Storage.")
    doc_hash: str = Field(description="SHA-256 of the PDF bytes (cache key component).")
    effective_date: date | None = Field(default=None, description="Document effective date.")
    uploaded_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Ingestion timestamp."
    )


class DocumentChunk(BaseModel):
    """A chunk of contract text prepared for indexing."""

    chunk_id: str = Field(description="Unique chunk id.")
    doc_id: str = Field(description="Parent document id.")
    provider_npi: str = Field(description="Owning provider NPI (search filter).")
    state: str = Field(description="State (search filter).")
    content: str = Field(description="Chunk text.")
    page: int = Field(description="Source page number (1-based).")
    embedding: list[float] | None = Field(default=None, description="Embedding vector.")


class RetrievedChunk(BaseModel):
    """A chunk returned from AI Search retrieval."""

    chunk_id: str = Field(description="Chunk id.")
    doc_id: str = Field(description="Parent document id.")
    content: str = Field(description="Chunk text.")
    score: float = Field(description="Relevance/similarity score.")


# --------------------------------------------------------------------------- #
# Stage 3: extraction (LLM structured outputs)                                #
# --------------------------------------------------------------------------- #


class TimelyFilingRule(BaseModel):
    """A timely-filing rule extracted from a provider contract."""

    days_to_file: int = Field(
        gt=0,
        description="Number of days from the date of service within which a claim must be filed.",
    )
    effective_date: date = Field(
        description="Date this timely-filing rule becomes effective (ISO 8601, YYYY-MM-DD).",
    )
    source_excerpt: str = Field(
        description="Verbatim sentence(s) from the contract that this rule was extracted from.",
    )


class LesserOfRule(BaseModel):
    """A 'lesser of' reimbursement rule extracted from a contract."""

    applies: bool = Field(description="Whether lesser-of logic applies to this contract.")
    basis: str = Field(
        default="",
        description="The comparison basis, e.g. 'lesser of billed charges or fee schedule'. "
        "Empty when applies is false.",
    )
    effective_date: date | None = Field(
        default=None, description="Date this rule becomes effective, if stated."
    )
    source_excerpt: str = Field(
        default="",
        description="Verbatim contract text supporting this rule. Empty when applies is false.",
    )


class ReimbursementRate(BaseModel):
    """A reimbursement rate for a service extracted from a contract."""

    service: str = Field(description="Service or service category, e.g. 'Physical Therapy'.")
    rate_type: RateType = Field(description="How the rate is expressed.")
    value: float = Field(
        description="Rate value: a percentage (e.g. 110 for 110%) or a dollar amount.",
    )
    cpt_codes: list[str] = Field(
        default_factory=list, description="Associated CPT/HCPCS codes, if any."
    )
    effective_date: date | None = Field(
        default=None, description="Date this rate becomes effective, if stated."
    )
    source_excerpt: str = Field(description="Verbatim contract text supporting this rate.")


class ReimbursementRateSet(BaseModel):
    """Wrapper so the LLM can return a list of rates as a single structured output."""

    rates: list[ReimbursementRate] = Field(
        default_factory=list,
        description="All distinct reimbursement rates found in the contract excerpts.",
    )


class ExtractedTerms(BaseModel):
    """Aggregated extraction output for a single document (not an LLM output)."""

    doc_id: str = Field(description="Source document id.")
    provider_npi: str = Field(description="Owning provider NPI.")
    effective_date: date | None = Field(default=None, description="Document effective date.")
    timely_filing: TimelyFilingRule | None = Field(
        default=None, description="Extracted timely-filing rule, if present."
    )
    lesser_of: LesserOfRule | None = Field(
        default=None, description="Extracted lesser-of rule, if present."
    )
    reimbursement_rates: list[ReimbursementRate] = Field(
        default_factory=list, description="Extracted reimbursement rates."
    )


# --------------------------------------------------------------------------- #
# Stage 4: timeline                                                           #
# --------------------------------------------------------------------------- #


class TimelineEntry(BaseModel):
    """A single time-bounded value for one contract field."""

    field: str = Field(description="Logical field name, e.g. 'timely_filing_days'.")
    value: str = Field(description="String-encoded value effective in this window.")
    effective_date: date = Field(description="When this value takes effect.")
    terminate_date: date | None = Field(
        default=None, description="When this value is superseded (None = still in effect)."
    )
    source_doc_id: str = Field(description="Document that introduced this value.")


class ResolvedTerms(BaseModel):
    """Contract terms resolved to a point in time after amendment reconciliation."""

    provider_npi: str = Field(description="Provider NPI.")
    as_of: date = Field(description="Date the terms were resolved as of.")
    timely_filing_days: int | None = Field(
        default=None, description="Resolved timely-filing window in days."
    )
    lesser_of_applies: bool | None = Field(
        default=None, description="Resolved lesser-of applicability."
    )
    reimbursement_rates: list[ReimbursementRate] = Field(
        default_factory=list, description="Resolved (currently-effective) reimbursement rates."
    )
    timeline: list[TimelineEntry] = Field(
        default_factory=list, description="Full reconciled timeline for traceability."
    )


# --------------------------------------------------------------------------- #
# Stage 5: validation report                                                  #
# --------------------------------------------------------------------------- #


class AuditFinding(BaseModel):
    """A single check result in the audit report."""

    code: AuditErrorCode | None = Field(
        default=None, description="Error code when the check fails; None when it passes."
    )
    field: str = Field(description="The field/check this finding concerns.")
    passed: bool = Field(description="Whether the check passed.")
    severity: FindingSeverity = Field(
        default=FindingSeverity.ERROR, description="Severity of the finding."
    )
    expected: str | None = Field(default=None, description="Benchmark/ground-truth value.")
    actual: str | None = Field(default=None, description="Value extracted from the contract.")
    match_type: MatchType | None = Field(
        default=None, description="Whether comparison was exact or tolerance-based."
    )
    message: str = Field(description="Human-readable explanation.")


class AuditReport(BaseModel):
    """The final audit report persisted to app_config.audit_runs."""

    contract_id: str = Field(description="Audited agreement id.")
    provider_npi: str = Field(description="Provider NPI.")
    state: str = Field(description="State code.")
    lob: str = Field(description="Line of business.")
    case_type: CaseType | None = Field(default=None, description="Resolved validation case type.")
    outcome: AuditOutcome = Field(description="Overall PASS/FAIL/ERROR.")
    findings: list[AuditFinding] = Field(
        default_factory=list, description="All individual check results."
    )
    checks_total: int = Field(default=0, description="Number of checks performed.")
    checks_failed: int = Field(default=0, description="Number of failed checks.")
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Report generation timestamp."
    )


class AuditResponse(BaseModel):
    """Response envelope for ``POST /audit_contract``."""

    request_id: uuid.UUID = Field(
        default_factory=uuid.uuid4, description="Unique id for this audit request."
    )
    status: AuditOutcome = Field(description="Overall outcome (pass | fail | error).")
    report: AuditReport | None = Field(default=None, description="Full report (None on error).")
    message: str | None = Field(default=None, description="Error/diagnostic message, if any.")


# --------------------------------------------------------------------------- #
# Portfolio dashboard (batch audit aggregation)                               #
# --------------------------------------------------------------------------- #


class FlaggedItem(BaseModel):
    """A contract flagged for human review (e.g. uncertain/missing extraction)."""

    contract_id: str = Field(description="Flagged agreement id.")
    provider_npi: str = Field(description="Provider NPI.")
    reason: str = Field(description="Why it needs review.")


class PortfolioSummary(BaseModel):
    """Aggregate compliance view across many audited contracts."""

    total_contracts: int = Field(description="Number of contracts audited.")
    passed: int = Field(description="Count with outcome PASS.")
    failed: int = Field(description="Count with outcome FAIL.")
    errored: int = Field(description="Count with outcome ERROR.")
    compliance_rate: float = Field(description="Fraction passed (0-1).")
    findings_by_code: dict[str, int] = Field(
        default_factory=dict, description="Count of failed checks per error code."
    )
    estimated_exposure_usd: float = Field(
        description="Illustrative $ exposure from non-compliant contracts."
    )
    flagged_for_review: list[FlaggedItem] = Field(
        default_factory=list, description="Contracts needing a human look."
    )
