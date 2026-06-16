"""Pure, testable accuracy metrics for the extraction eval.

Values are compared as normalized strings (e.g. "90", "true", "100.0") so numeric,
boolean, and categorical fields are handled uniformly.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldResult:
    """One field prediction vs. its ground-truth label."""

    example_id: str
    field: str
    expected: str
    predicted: str

    @property
    def correct(self) -> bool:
        return self.expected == self.predicted


def overall_accuracy(results: list[FieldResult]) -> float:
    """Fraction of all field predictions that are correct."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.correct) / len(results)


def accuracy_by_field(results: list[FieldResult]) -> dict[str, tuple[int, int, float]]:
    """Per-field (correct, total, accuracy)."""
    totals: dict[str, list[int]] = {}
    for r in results:
        bucket = totals.setdefault(r.field, [0, 0])
        bucket[0] += 1 if r.correct else 0
        bucket[1] += 1
    return {field: (c, t, (c / t if t else 0.0)) for field, (c, t) in totals.items()}


def binary_precision_recall_f1(
    results: list[FieldResult], field: str, positive: str
) -> dict[str, float]:
    """Precision/recall/F1 for a binary field, treating ``positive`` as the positive class."""
    relevant = [r for r in results if r.field == field]
    tp = sum(1 for r in relevant if r.predicted == positive and r.expected == positive)
    fp = sum(1 for r in relevant if r.predicted == positive and r.expected != positive)
    fn = sum(1 for r in relevant if r.predicted != positive and r.expected == positive)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": float(tp),
        "fp": float(fp),
        "fn": float(fn),
    }
