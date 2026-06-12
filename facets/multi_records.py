"""Coordinator: regex provider-type standardization and facility inference.

Used by the orchestrator to derive a FacilityType for case-type resolution from the
contract's extracted services when one is not supplied.
"""

import logging
import re

from models import FacilityType, ResolvedTerms

logger = logging.getLogger(__name__)

# Ordered (regex -> facility) rules; first match wins.
_FACILITY_PATTERNS: list[tuple[re.Pattern[str], FacilityType]] = [
    (re.compile(r"\bskilled nursing|nursing facility|\bsnf\b", re.IGNORECASE), FacilityType.SNF),
    (re.compile(r"\boutpatient\b|\bopps\b|\basc\b", re.IGNORECASE), FacilityType.OUTPATIENT),
    (re.compile(r"\binpatient\b|\bdrg\b|hospital stay", re.IGNORECASE), FacilityType.INPATIENT),
]


def standardize_provider_type(raw: str) -> FacilityType:
    """Map a free-text provider/facility description to a FacilityType (default professional)."""
    for pattern, facility in _FACILITY_PATTERNS:
        if pattern.search(raw):
            return facility
    return FacilityType.PROFESSIONAL


def infer_facility(resolved: ResolvedTerms) -> FacilityType:
    """Infer the facility type from the resolved contract's service names."""
    haystack = " ".join(rate.service for rate in resolved.reimbursement_rates)
    return standardize_provider_type(haystack)
