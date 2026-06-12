"""Stage 4: reconcile contract terms across amendments into a chronological timeline.

Provider contracts evolve through amendments. Given per-document extractions, this
builds a timeline for each field (assigning effective/terminate dates) and resolves the
value in force as of a target date.
"""

import logging
from datetime import date, timedelta

from models import ExtractedTerms, ReimbursementRate, ResolvedTerms, TimelineEntry

logger = logging.getLogger(__name__)

_MIN_DATE = date(1900, 1, 1)


class TimelineBuilder:
    """Builds a reconciled timeline and resolves point-in-time contract terms."""

    def build(
        self, extracted: list[ExtractedTerms], as_of: date, provider_npi: str
    ) -> ResolvedTerms:
        """Reconcile ``extracted`` documents into terms effective on ``as_of``."""
        timeline: list[TimelineEntry] = []

        # timely_filing_days
        tf_points: list[tuple[date, str, str]] = []
        for terms in extracted:
            if terms.timely_filing is not None:
                eff = terms.timely_filing.effective_date or terms.effective_date or _MIN_DATE
                tf_points.append((eff, str(terms.timely_filing.days_to_file), terms.doc_id))
        tf_entries = _field_timeline("timely_filing_days", tf_points)
        timeline.extend(tf_entries)
        tf_value = _active_value(tf_entries, as_of)
        timely_filing_days = int(tf_value) if tf_value is not None else None

        # lesser_of_applies
        lo_points: list[tuple[date, str, str]] = []
        for terms in extracted:
            if terms.lesser_of is not None:
                eff = terms.lesser_of.effective_date or terms.effective_date or _MIN_DATE
                lo_points.append((eff, str(terms.lesser_of.applies).lower(), terms.doc_id))
        lo_entries = _field_timeline("lesser_of_applies", lo_points)
        timeline.extend(lo_entries)
        lo_value = _active_value(lo_entries, as_of)
        lesser_of_applies = (lo_value == "true") if lo_value is not None else None

        # reimbursement rates: latest effective-on-or-before as_of, per service
        resolved_rates = _resolve_rates(extracted, as_of)

        return ResolvedTerms(
            provider_npi=provider_npi,
            as_of=as_of,
            timely_filing_days=timely_filing_days,
            lesser_of_applies=lesser_of_applies,
            reimbursement_rates=resolved_rates,
            timeline=timeline,
        )


def _field_timeline(field: str, points: list[tuple[date, str, str]]) -> list[TimelineEntry]:
    """Build time-bounded entries for one field; later entries supersede earlier ones."""
    if not points:
        return []
    ordered = sorted(points, key=lambda p: p[0])
    entries: list[TimelineEntry] = []
    for index, (effective, value, doc_id) in enumerate(ordered):
        terminate: date | None = None
        if index + 1 < len(ordered):
            terminate = ordered[index + 1][0] - timedelta(days=1)
        entries.append(
            TimelineEntry(
                field=field,
                value=value,
                effective_date=effective,
                terminate_date=terminate,
                source_doc_id=doc_id,
            )
        )
    return entries


def _active_value(entries: list[TimelineEntry], as_of: date) -> str | None:
    """Return the value of the entry in force on ``as_of`` (latest qualifying)."""
    active: TimelineEntry | None = None
    for entry in entries:
        if entry.effective_date <= as_of and (
            entry.terminate_date is None or as_of <= entry.terminate_date
        ):
            if active is None or entry.effective_date >= active.effective_date:
                active = entry
    return active.value if active is not None else None


def _resolve_rates(extracted: list[ExtractedTerms], as_of: date) -> list[ReimbursementRate]:
    """Pick the latest effective-on-or-before-``as_of`` rate per service."""
    latest: dict[str, tuple[date, ReimbursementRate]] = {}
    for terms in extracted:
        doc_effective = terms.effective_date or _MIN_DATE
        for rate in terms.reimbursement_rates:
            effective = rate.effective_date or doc_effective
            if effective > as_of:
                continue
            key = rate.service.strip().lower()
            if key not in latest or effective >= latest[key][0]:
                latest[key] = (effective, rate)
    return [rate for _, rate in latest.values()]
