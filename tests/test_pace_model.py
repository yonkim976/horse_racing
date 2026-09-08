from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from test_lightgbm_model import _synthetic_frame

from horse_racing.analysis.pace_model import (
    PACE_FEATURES,
    PACE_GATE_INPUT_FEATURES,
    add_gate_aware_pace_inputs,
    add_pace_scenario_features,
    train_two_stage_fold,
    train_two_stage_ranking_fold,
)
from horse_racing.analysis.walk_forward import fold_bounds


def _pace_frame() -> pl.DataFrame:
    frame = _synthetic_frame()
    return frame.with_columns(
        (
            (pl.col("horse_number") - 1) / 5.0 * 0.8
            + (pl.col("score") % 2) * 0.05
        )
        .clip(0.0, 1.0)
        .alias("early_position_pct_target")
    )


def test_pace_scenario_features_are_race_relative() -> None:
    frame = _pace_frame().head(6)
    result = add_pace_scenario_features(
        frame,
        np.array([0.1, 0.2, 0.4, 0.5, 0.7, 0.9]),
    )
    assert all(name in result.columns for name in PACE_FEATURES)
    assert result["pace_pred_front_count"].to_list() == [2] * 6
    assert result["pace_pred_front_rivals"].to_list()[:2] == [1, 1]
    assert result["pace_pred_front_rivals"].to_list()[2:] == [2, 2, 2, 2]


def test_gate_aware_inputs_condition_gate_on_distance_field_and_style() -> None:
    frame = pl.DataFrame(
        {
            "race_id": [1, 1],
            "horse_number": [1, 12],
            "horse_number_pct": [1 / 12, 1.0],
            "starters": [12, 12],
            "meet_code": [1, 1],
            "distance_m": [1000, 1000],
            "early_pos_pct_avg5": [0.8, 0.2],
            "section_coverage5": [5, 5],
        }
    )
    result = add_gate_aware_pace_inputs(frame)

    assert set(PACE_GATE_INPUT_FEATURES) <= set(result.columns)
    assert result["pace_gate_closer_inner"][0] > 0
    assert result["pace_gate_front_outer"][1] > 0
    assert result["pace_gate_short_outer"][1] > result["pace_gate_short_outer"][0]
    assert result["pace_gate_context_key"][0].endswith("sprint_medium_inner")


def test_pace_scenario_features_expose_counterfactual_gate_effect() -> None:
    frame = _pace_frame().head(6).with_columns(
        pl.lit(6).alias("starters"),
        (pl.col("horse_number") / 6.0).alias("horse_number_pct"),
    )
    actual = np.array([0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
    neutral = actual + np.array([0.05, 0.0, 0.0, 0.0, -0.05, -0.1])
    result = add_pace_scenario_features(
        frame,
        actual,
        neutral_gate_predictions=neutral,
    )

    assert result["pace_pred_gate_early_effect"].to_list() == pytest.approx(
        (neutral - actual).tolist()
    )
    assert result["pace_pred_gate_outer_break_cost"][-1] > 0


def test_two_stage_fold_uses_cross_fitted_pace_predictions() -> None:
    result = train_two_stage_fold(
        _pace_frame(),
        feature_names=["score", "meet", "horse_number"],
        dataset_version="synthetic",
        as_of_policy="start_minus_30m",
        split_bounds=fold_bounds(2026),
        seed=5,
    )
    sums = result.outcome.valid_predictions.group_by("race_id").agg(
        pl.col("prob_win").sum()
    )
    assert sums["prob_win"].to_list() == pytest.approx([1.0] * sums.height)
    assert result.pace_valid_mae < 0.25
    assert result.augmented_feature_names[-len(PACE_FEATURES) :] == PACE_FEATURES


def test_two_stage_ranking_fold_returns_coherent_rank_probabilities() -> None:
    result = train_two_stage_ranking_fold(
        _pace_frame(),
        feature_names=["score", "meet", "horse_number"],
        dataset_version="synthetic_v2",
        as_of_policy="start_minus_30m",
        split_bounds=fold_bounds(2026),
        seed=7,
    )
    sums = result.outcome.valid_predictions.group_by("race_id").agg(
        pl.col("prob_win").sum(),
        pl.col("prob_top2").sum(),
        pl.col("prob_top3").sum(),
    )
    assert sums["prob_win"].to_list() == pytest.approx([1.0] * sums.height)
    assert sums["prob_top2"].to_list() == pytest.approx([2.0] * sums.height)
    assert sums["prob_top3"].to_list() == pytest.approx([3.0] * sums.height)
    assert result.pace_valid_mae < 0.25
