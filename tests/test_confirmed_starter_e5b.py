from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest

from horse_racing.analysis.confirmed_starter_e5b import (
    E5BContractError,
    evaluate_predictions,
    stable_race_losses,
    validate_prediction_frame,
)


def test_winner_set_nll_uses_stable_log_domain_for_extreme_margin() -> None:
    ce, winner = stable_race_losses(
        np.array([1000.0, 0.0, -1000.0]), np.array([0, 1, 0]), np.array([3]), beta=1.0
    )
    assert ce[0] == pytest.approx(1000.0)
    assert winner[0] == pytest.approx(1000.0)


def test_dead_heat_soft_ce_and_winner_set_are_distinct() -> None:
    ce, winner = stable_race_losses(
        np.array([2.0, 0.0, -1.0]), np.array([1, 1, 0]), np.array([3]), beta=1.0
    )
    assert ce[0] > winner[0]
    assert math.isfinite(ce[0]) and math.isfinite(winner[0])


def _frames() -> tuple[pl.DataFrame, pl.DataFrame]:
    expected = pl.DataFrame(
        {
            "race_id": [1, 1],
            "race_entry_id": [10, 11],
            "horse_number": [1, 2],
            "race_date_local": ["2026-03-01", "2026-03-01"],
            "win": [1, 0],
            "outcome_state": ["normal_finish", "normal_finish"],
        }
    )
    predictions = pl.DataFrame(
        {
            "race_id": [1, 1],
            "race_entry_id": [10, 11],
            "horse_number": [1, 2],
            "raw_margin": [0.0, 0.0],
            "prob_win": [0.5, 0.5],
        }
    )
    return expected, predictions


def test_prediction_coverage_rejects_missing_row() -> None:
    expected, predictions = _frames()
    with pytest.raises(E5BContractError, match="missing=1"):
        validate_prediction_frame(expected, predictions.head(1), name="missing")


def test_prediction_coverage_rejects_duplicate_and_extra() -> None:
    expected, predictions = _frames()
    with pytest.raises(E5BContractError, match="duplicate actual"):
        validate_prediction_frame(
            expected, pl.concat([predictions, predictions.head(1)]), name="dup"
        )
    extra = predictions.with_columns(
        pl.when(pl.int_range(pl.len()) == 1)
        .then(12)
        .otherwise(pl.col("race_entry_id"))
        .alias("race_entry_id")
    )
    with pytest.raises(E5BContractError, match="missing=1, extra=1"):
        validate_prediction_frame(expected, extra, name="extra")


def test_probability_tie_topk_is_order_invariant() -> None:
    expected, predictions = _frames()
    joined, _ = validate_prediction_frame(expected, predictions, name="tie")
    metrics, _ = evaluate_predictions(joined, beta=1.0)
    reversed_joined, _ = validate_prediction_frame(expected, predictions.reverse(), name="reverse")
    reversed_metrics, _ = evaluate_predictions(reversed_joined, beta=1.0)
    for key in ("top1_winner_inclusion", "top3_winner_inclusion", "top5_winner_inclusion"):
        assert metrics[key] == reversed_metrics[key]
    assert metrics["top1_winner_inclusion"] == 0.5


def test_probability_validation_rejects_bad_sum_and_nonfinite() -> None:
    expected, predictions = _frames()
    with pytest.raises(E5BContractError, match="probability-sum"):
        validate_prediction_frame(
            expected, predictions.with_columns(pl.Series("prob_win", [0.6, 0.5])), name="sum"
        )
    with pytest.raises(E5BContractError, match="invalid raw/probability"):
        validate_prediction_frame(
            expected,
            predictions.with_columns(pl.Series("raw_margin", [float("nan"), 0.0])),
            name="finite",
        )
