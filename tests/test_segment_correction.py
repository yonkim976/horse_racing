from __future__ import annotations

import polars as pl

from horse_racing.analysis.segment_correction import run_segment_correction_walk_forward
from test_lightgbm_model import _synthetic_frame


def test_segment_correction_walk_forward_runs() -> None:
    frame = _synthetic_frame().with_columns(
        pl.when(pl.col("meet") == "서울").then(2).otherwise(3).alias("meet_code"),
        pl.when(pl.col("meet") == "부산").then(1800).otherwise(1200).alias("distance_m"),
    )
    result = run_segment_correction_walk_forward(
        frame,
        feature_names=["score", "meet", "horse_number"],
        dataset_version="synthetic",
        as_of_policy="start_minus_30m",
        years=[2026],
        seed=8,
        hyperparameters={
            "n_estimators": 40,
            "learning_rate": 0.1,
            "num_leaves": 7,
            "min_child_samples": 5,
            "n_jobs": 1,
        },
    )
    assert result.aggregate_metrics["auc"] > 0.8
    assert result.predictions["fold_year"].unique().to_list() == [2026]
