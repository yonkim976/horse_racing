from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import polars as pl
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/compare_canonical_section_runs.py"
SPEC = importlib.util.spec_from_file_location("compare_canonical_section_runs", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ComparisonInputError = MODULE.ComparisonInputError
_race_metrics = MODULE._race_metrics
validate_and_join_predictions = MODULE.validate_and_join_predictions


def _expected() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1, 1, 1, 1, 1],
            "race_entry_id": [1, 2, 3, 4, 5],
            "race_date_local": ["2026-03-01"] * 5,
            "meet_code": [1] * 5,
            "horse_number": [1, 2, 3, 4, 5],
            "win": [0, 1, 0, 0, 0],
        }
    )


def _predictions() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1, 1, 1, 1, 1],
            "race_entry_id": [1, 2, 3, 4, 5],
            "horse_number": [1, 2, 3, 4, 5],
            "prob_win": [0.3, 0.2, 0.2, 0.2, 0.1],
        }
    )


def test_prediction_coverage_rejects_one_missing_row() -> None:
    with pytest.raises(ComparisonInputError, match="missing=1"):
        validate_and_join_predictions(_expected(), _predictions().slice(0, 4), name="fixture")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda frame: pl.concat([frame, frame.slice(0, 1)]), "duplicate"),
        (
            lambda frame: frame.with_columns(
                pl.when(pl.col("race_entry_id") == 1)
                .then(float("nan"))
                .otherwise(pl.col("prob_win"))
                .alias("prob_win")
            ),
            "non-finite",
        ),
        (
            lambda frame: frame.with_columns((pl.col("prob_win") * 0.5).alias("prob_win")),
            "probability sums",
        ),
    ],
)
def test_prediction_contract_rejects_invalid_artifacts(mutation, message: str) -> None:
    with pytest.raises(ComparisonInputError, match=message):
        validate_and_join_predictions(_expected(), mutation(_predictions()), name="fixture")


def test_tie_aware_metrics_are_invariant_to_reverse_and_random_row_order() -> None:
    joined, _ = validate_and_join_predictions(_expected(), _predictions(), name="fixture")
    baseline, _ = _race_metrics(joined)
    reversed_metrics, _ = _race_metrics(joined.reverse())
    indices = list(range(joined.height))
    random.Random(20260911).shuffle(indices)
    shuffled, _ = _race_metrics(joined[indices])
    keys = ("top1", "winner_top3", "winner_top5", "race_winner_nll")
    for key in keys:
        assert reversed_metrics[key] == pytest.approx(baseline[key])
        assert shuffled[key] == pytest.approx(baseline[key])


def test_boundary_probability_tie_uses_expected_inclusion() -> None:
    joined, _ = validate_and_join_predictions(_expected(), _predictions(), name="fixture")
    metrics, _ = _race_metrics(joined)
    assert metrics["top1"] == 0.0
    assert metrics["winner_top3"] == pytest.approx(2 / 3)
    assert metrics["winner_top5"] == 1.0
