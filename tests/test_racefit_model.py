from __future__ import annotations

import polars as pl
import pytest
from test_lightgbm_model import _synthetic_frame

from horse_racing.analysis.racefit_model import (
    STATIC_SCENARIO_FEATURES,
    scenario_feature_matrix,
    train_racefit_model,
)
from horse_racing.analysis.walk_forward import fold_bounds


def _racefit_frame() -> pl.DataFrame:
    return _synthetic_frame().with_columns(
        ((pl.col("score") - 3.5) / 3.5).alias("condition_state"),
        pl.lit(0.25).alias("condition_uncertainty"),
        ((pl.col("score") - 3.5) * 0.3).alias("energy_resilience_avg5"),
        ((pl.col("score") - 3.5) * 0.2).alias("energy_finish_change_avg5"),
        ((pl.col("score") - 3.5) * 0.1).alias("energy_early_late_balance_avg5"),
        ((pl.col("horse_number") - 1) / 5).alias("early_pos_pct_avg5"),
        pl.lit(0.9).alias("known_style_share"),
        pl.lit(2).alias("front_runner_count"),
        pl.lit(1).alias("front_rival_count"),
        (pl.col("horse_number") / 6).alias("horse_number_pct"),
        pl.lit(6).alias("starters"),
        pl.lit(1200).alias("distance_m"),
        pl.lit(8.0).alias("track_moisture_percent_planned"),
        pl.lit(0.0).alias("carried_weight_rel"),
    )


def test_scenario_feature_matrix_has_finite_contract() -> None:
    features = scenario_feature_matrix(_racefit_frame().head(6))
    assert set(STATIC_SCENARIO_FEATURES) <= set(features.columns)
    assert features.null_count().sum_horizontal().item() == 0
    assert features["scenario_uncertainty"].min() >= 0.1
    assert features["scenario_uncertainty"].max() <= 0.75


def test_racefit_model_produces_coherent_valid_probabilities() -> None:
    result = train_racefit_model(
        _racefit_frame(),
        feature_names=["score", "meet", "horse_number"],
        dataset_version="synthetic_racefit",
        as_of_policy="start_minus_30m",
        seed=11,
        split_bounds=fold_bounds(2026),
        hyperparameters={
            "n_estimators": 50,
            "learning_rate": 0.1,
            "num_leaves": 7,
            "min_child_samples": 5,
            "n_jobs": 1,
        },
    )
    sums = result.valid_predictions.group_by("race_id").agg(
        pl.col("prob_win").sum(),
        pl.col("prob_top2").sum(),
        pl.col("prob_top3").sum(),
    )
    assert sums["prob_win"].to_list() == pytest.approx([1.0] * sums.height)
    assert sums["prob_top2"].to_list() == pytest.approx([2.0] * sums.height)
    assert sums["prob_top3"].to_list() == pytest.approx([3.0] * sums.height)
    assert result.valid_metrics["auc"] > 0.8
    assert result.bundle.calibration_metrics["objective_improvement"] >= 0
    assert result.ordered_top3_nll > 0
