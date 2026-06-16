"""Live extraction-accuracy eval — opt-in (uses the LLM).

Runs each labeled contract excerpt in evals/dataset.jsonl through the real extraction
(``llm_client.chat_structured``) and reports per-field accuracy + lesser-of precision/recall,
writing evals/results.md.

Run:  python -m evals.run_eval
Needs the active provider's creds (e.g. GITHUB_TOKEN in .env). ~3 LLM calls per example.
"""

import asyncio
import json
import logging
from pathlib import Path

from agents import llm_client
from agents.llm_client import LLMExtractionError
from config import load_env
from evals.metrics import (
    FieldResult,
    accuracy_by_field,
    binary_precision_recall_f1,
    overall_accuracy,
)
from models import LesserOfRule, RateType, ReimbursementRateSet, TimelyFilingRule

logger = logging.getLogger(__name__)

DATASET = Path(__file__).parent / "dataset.jsonl"
RESULTS = Path(__file__).parent / "results.md"

_SYSTEM = "Extract the requested fields from the healthcare provider contract excerpt."


def _messages(text: str) -> list[dict]:
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": text}]


async def _predict(text: str) -> tuple[str, str, str]:
    """Return normalized (timely_filing_days, lesser_of_applies, rate_pct) predictions."""
    try:
        tf = await llm_client.chat_structured(_messages(text), TimelyFilingRule)
        tf_pred = str(tf.days_to_file)
    except LLMExtractionError:
        tf_pred = "error"

    try:
        lo = await llm_client.chat_structured(_messages(text), LesserOfRule)
        lo_pred = str(lo.applies).lower()
    except LLMExtractionError:
        lo_pred = "error"

    try:
        rates = await llm_client.chat_structured(_messages(text), ReimbursementRateSet)
        pct = next(
            (r.value for r in rates.rates if r.rate_type == RateType.PERCENT_OF_MEDICARE), None
        )
        rate_pred = f"{float(pct):.1f}" if pct is not None else "none"
    except LLMExtractionError:
        rate_pred = "error"

    return tf_pred, lo_pred, rate_pred


def _load_examples() -> list[dict]:
    lines = DATASET.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _render_report(results: list[FieldResult], example_count: int) -> str:
    by_field = accuracy_by_field(results)
    overall = overall_accuracy(results)
    prf = binary_precision_recall_f1(results, "lesser_of_applies", "true")

    lines = [
        "# Extraction accuracy eval",
        "",
        f"Dataset: **{example_count} contracts** · {len(results)} field predictions · "
        f"provider `{llm_client.get_active_provider()}`",
        "",
        "| Field | Correct | Total | Accuracy |",
        "| --- | --- | --- | --- |",
    ]
    for field, (correct, total, acc) in by_field.items():
        lines.append(f"| {field} | {correct} | {total} | {acc * 100:.0f}% |")
    lines += [
        "",
        f"**Overall extraction accuracy: {overall * 100:.0f}%**",
        "",
        "Lesser-of (binary classification): "
        f"precision {prf['precision'] * 100:.0f}% · "
        f"recall {prf['recall'] * 100:.0f}% · "
        f"F1 {prf['f1'] * 100:.0f}%",
    ]
    return "\n".join(lines)


async def run() -> str:
    """Run the eval, write results.md, and return the report text."""
    load_env()
    examples = _load_examples()
    results: list[FieldResult] = []
    for example in examples:
        tf_pred, lo_pred, rate_pred = await _predict(example["text"])
        results.append(
            FieldResult(
                example["id"], "timely_filing_days", str(example["timely_filing_days"]), tf_pred
            )
        )
        results.append(
            FieldResult(
                example["id"],
                "lesser_of_applies",
                str(example["lesser_of_applies"]).lower(),
                lo_pred,
            )
        )
        results.append(
            FieldResult(example["id"], "rate_pct", f"{float(example['rate_pct']):.1f}", rate_pred)
        )
        logger.info("Evaluated %s", example["id"])

    report = _render_report(results, len(examples))
    RESULTS.write_text(report + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(run()))
