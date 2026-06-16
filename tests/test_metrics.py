"""Tests for the eval metrics (evals.metrics)."""

from evals.metrics import (
    FieldResult,
    accuracy_by_field,
    binary_precision_recall_f1,
    overall_accuracy,
)


def _r(field: str, expected: str, predicted: str, ex: str = "e") -> FieldResult:
    return FieldResult(ex, field, expected, predicted)


def test_overall_accuracy() -> None:
    results = [_r("a", "1", "1"), _r("a", "2", "3"), _r("b", "x", "x")]
    assert overall_accuracy(results) == 2 / 3


def test_overall_accuracy_empty() -> None:
    assert overall_accuracy([]) == 0.0


def test_accuracy_by_field() -> None:
    results = [_r("tf", "90", "90"), _r("tf", "120", "100"), _r("lo", "true", "true")]
    by_field = accuracy_by_field(results)
    assert by_field["tf"] == (1, 2, 0.5)
    assert by_field["lo"] == (1, 1, 1.0)


def test_binary_precision_recall_f1() -> None:
    results = [
        _r("lo", "true", "true"),  # tp
        _r("lo", "true", "true"),  # tp
        _r("lo", "false", "true"),  # fp
        _r("lo", "true", "false"),  # fn
        _r("lo", "false", "false"),  # tn
    ]
    prf = binary_precision_recall_f1(results, "lo", "true")
    assert (prf["tp"], prf["fp"], prf["fn"]) == (2.0, 1.0, 1.0)
    assert abs(prf["precision"] - 2 / 3) < 1e-9
    assert abs(prf["recall"] - 2 / 3) < 1e-9
    assert abs(prf["f1"] - 2 / 3) < 1e-9
