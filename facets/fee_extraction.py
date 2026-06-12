"""Stage 4 helper: normalize AI-extracted terms, dedupe rows, map free text to codes."""

import logging

from models import ExtractedTerms, ReimbursementRate

logger = logging.getLogger(__name__)

# Free-text line-of-business -> internal system code.
LOB_CODE_MAP: dict[str, str] = {
    "medicaid": "CAID",
    "medicare advantage": "MAPD",
    "medicare": "MCR",
    "commercial": "COMM",
}

# Free-text facility/setting -> internal code.
FACILITY_CODE_MAP: dict[str, str] = {
    "skilled nursing facility": "SNF",
    "snf": "SNF",
    "outpatient": "OP",
    "inpatient": "IP",
    "professional": "PROF",
}


def map_lob(raw: str) -> str:
    """Map a free-text line of business to its system code (idempotent on codes)."""
    return LOB_CODE_MAP.get(raw.strip().lower(), raw.strip().upper())


def map_facility(raw: str) -> str:
    """Map a free-text facility/setting to its system code."""
    return FACILITY_CODE_MAP.get(raw.strip().lower(), raw.strip().upper())


def normalize_service(name: str) -> str:
    """Normalize a service name (collapse whitespace, title-case)."""
    return " ".join(name.split()).title()


def dedupe_rates(rates: list[ReimbursementRate]) -> list[ReimbursementRate]:
    """Remove duplicate rate rows keyed on (service, rate_type, value, effective_date)."""
    seen: set[tuple[str, str, float, str]] = set()
    unique: list[ReimbursementRate] = []
    for rate in rates:
        key = (
            rate.service.strip().lower(),
            rate.rate_type.value,
            round(rate.value, 4),
            rate.effective_date.isoformat() if rate.effective_date else "",
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(rate)
    return unique


def normalize_terms(terms: ExtractedTerms) -> ExtractedTerms:
    """Return a cleaned copy: normalized service names and de-duplicated rates."""
    normalized = [
        rate.model_copy(update={"service": normalize_service(rate.service)})
        for rate in terms.reimbursement_rates
    ]
    return terms.model_copy(update={"reimbursement_rates": dedupe_rates(normalized)})
