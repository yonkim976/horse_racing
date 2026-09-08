from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from horse_racing.analysis.catboost_model import (
    train_catboost_models,
    transform_catboost_features,
)
from horse_racing.analysis.lightgbm_model import fit_feature_encoder


def _synthetic_frame() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = date(2025, 9, 1)
    race_id = 0
    entry_id = 0
    for day_index in range(36):
        race_date = start + timedelta(days=day_index * 7)
        for repeat in range(2):
            race_id += 1
            winner = (day_index + repeat) % 6
            scores = [6 - abs(horse - winner) for horse in range(6)]
            order = sorted(range(6), key=lambda horse: scores[horse], reverse=True)
            for horse in range(6):
                entry_id += 1
                rank = order.index(horse) + 1
                rows.append(
                    {
                        "race_id": race_id,
                        "race_entry_id": entry_id,
                        "horse_number": horse + 1,
                        "race_date_local": race_date.isoformat(),
                        "score": float(scores[horse]),
                        "meet": "서울" if repeat == 0 else "부산",
                        "win": int(rank == 1),
                        "top2": int(rank <= 2),
                        "top3": int(rank <= 3),
                    }
                )
    return pl.DataFrame(rows)


def test_transform_catboost_features_preserves_strings_and_missing() -> None:
    frame = pl.DataFrame({"score": [1.0, None], "meet": ["서울", None]})
    encoder = fit_feature_encoder(frame, ["score", "meet"])
    transformed = transform_catboost_features(frame, encoder)

    assert transformed.columns.to_list() == ["score", "meet"]
    assert transformed.loc[0, "meet"] == "서울"
    assert transformed.loc[1, "meet"] == "__MISSING__"


def test_train_catboost_models_produces_race_probability_totals() -> None:
    result = train_catboost_models(
        _synthetic_frame(),
        feature_names=["score", "meet", "horse_number"],
        dataset_version="synthetic",
        as_of_policy="start_minus_30m",
        seed=7,
        calibration="raw",
        hyperparameters={
            "iterations": 50,
            "depth": 4,
            "learning_rate": 0.1,
            "thread_count": 1,
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
    assert result.valid_metrics["win"]["auc"] > 0.8
