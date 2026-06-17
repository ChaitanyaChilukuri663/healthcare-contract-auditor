"""Tests for model-level LLM-output coercion (dates + rate types)."""

from datetime import date

from models import LesserOfRule, RateType, ReimbursementRate, TimelyFilingRule


def test_timely_filing_accepts_natural_language_date() -> None:
    rule = TimelyFilingRule(days_to_file=90, effective_date="January 1, 2024", source_excerpt="x")
    assert rule.effective_date == date(2024, 1, 1)


def test_iso_date_still_works() -> None:
    rule = TimelyFilingRule(days_to_file=90, effective_date="2024-01-01", source_excerpt="x")
    assert rule.effective_date == date(2024, 1, 1)


def test_lesser_of_accepts_natural_language_date() -> None:
    rule = LesserOfRule(applies=True, effective_date="January 1, 2023", source_excerpt="y")
    assert rule.effective_date == date(2023, 1, 1)


def test_rate_type_coerces_unknown_to_billed() -> None:
    rate = ReimbursementRate(
        service="s", rate_type="lesser_of_billed", value=100.0, source_excerpt="x"
    )
    assert rate.rate_type == RateType.PERCENT_OF_BILLED


def test_rate_type_known_value_preserved() -> None:
    rate = ReimbursementRate(
        service="s", rate_type="percent_of_medicare", value=100.0, source_excerpt="x"
    )
    assert rate.rate_type == RateType.PERCENT_OF_MEDICARE
