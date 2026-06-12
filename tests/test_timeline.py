"""Tests for Stage 4 amendment-timeline reconciliation (pure logic)."""

from datetime import date

from document_extraction.timeline_builder import TimelineBuilder
from models import ExtractedTerms, LesserOfRule, RateType, ReimbursementRate, TimelyFilingRule


def _base_terms() -> ExtractedTerms:
    return ExtractedTerms(
        doc_id="doc-base",
        provider_npi="1234567890",
        effective_date=date(2023, 1, 1),
        timely_filing=TimelyFilingRule(
            days_to_file=90, effective_date=date(2023, 1, 1), source_excerpt="within 90 days"
        ),
        lesser_of=LesserOfRule(applies=True, basis="lesser of billed or fee", source_excerpt="x"),
        reimbursement_rates=[
            ReimbursementRate(
                service="Physical Therapy",
                rate_type=RateType.PERCENT_OF_MEDICARE,
                value=100.0,
                effective_date=date(2023, 1, 1),
                source_excerpt="100% of Medicare",
            )
        ],
    )


def _amendment_terms() -> ExtractedTerms:
    return ExtractedTerms(
        doc_id="doc-amend",
        provider_npi="1234567890",
        effective_date=date(2024, 1, 1),
        timely_filing=TimelyFilingRule(
            days_to_file=120, effective_date=date(2024, 1, 1), source_excerpt="amended to 120 days"
        ),
    )


def test_amendment_supersedes_base_after_effective_date() -> None:
    builder = TimelineBuilder()
    resolved = builder.build([_base_terms(), _amendment_terms()], date(2024, 6, 1), "1234567890")
    assert resolved.timely_filing_days == 120
    assert resolved.lesser_of_applies is True
    assert len(resolved.reimbursement_rates) == 1


def test_base_value_in_force_before_amendment() -> None:
    builder = TimelineBuilder()
    resolved = builder.build([_base_terms(), _amendment_terms()], date(2023, 6, 1), "1234567890")
    assert resolved.timely_filing_days == 90


def test_timeline_entries_have_terminate_dates() -> None:
    builder = TimelineBuilder()
    resolved = builder.build([_base_terms(), _amendment_terms()], date(2024, 6, 1), "n")
    tf_entries = [e for e in resolved.timeline if e.field == "timely_filing_days"]
    assert len(tf_entries) == 2
    # The earlier entry terminates the day before the amendment's effective date.
    earlier = min(tf_entries, key=lambda e: e.effective_date)
    assert earlier.terminate_date == date(2023, 12, 31)


def test_rates_effective_after_as_of_are_excluded() -> None:
    builder = TimelineBuilder()
    future_rate = ExtractedTerms(
        doc_id="doc-future",
        provider_npi="n",
        effective_date=date(2030, 1, 1),
        reimbursement_rates=[
            ReimbursementRate(
                service="Future Service",
                rate_type=RateType.PERCENT_OF_MEDICARE,
                value=150.0,
                effective_date=date(2030, 1, 1),
                source_excerpt="future",
            )
        ],
    )
    resolved = builder.build([_base_terms(), future_rate], date(2024, 6, 1), "n")
    services = {rate.service for rate in resolved.reimbursement_rates}
    assert "Future Service" not in services
    assert "Physical Therapy" in services


def test_empty_input_resolves_to_none() -> None:
    resolved = TimelineBuilder().build([], date(2024, 1, 1), "n")
    assert resolved.timely_filing_days is None
    assert resolved.lesser_of_applies is None
    assert resolved.reimbursement_rates == []
