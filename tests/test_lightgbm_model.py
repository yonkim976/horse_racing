from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from horse_racing.analysis.lightgbm_model import (
    fit_feature_encoder,
    normalize_race_probabilities,
    temporal_train_partitions,
    train_lightgbm_models,
    transform_features,
)


def test_normalize_race_probabilities_respects_target_and_bounds() -> None:
    probabilities = np.array([0.9, 0.6, 0.2, 0.1, 0.8, 0.3])
    race_ids = np.array([1, 1, 1, 1, 2, 2])

    win = normalize_race_probabilities(probabilities, race_ids, target_total=1)
    top2 = normalize_race_probabilities(probabilities, race_ids, target_total=2)

    assert win[:4].sum() == pytest.approx(1.0)
    assert win[4:].sum() == pytest.approx(1.0)
    assert top2[:4].sum() == pytest.approx(2.0)
    assert top2[4:].sum() == pytest.approx(2.0)
    assert np.all((top2 >= 0) & (top2 <= 1))


def test_feature_encoder_maps_unknown_category_to_missing() -> None:
    train = pl.DataFrame({"numeric": [1.0, None], "category": ["서울", "부산"]})
    encoder = fit_feature_encoder(train, ["numeric", "category"])
    matrix = transform_features(
        pl.DataFrame({"numeric": [2.0], "category": ["제주"]}), encoder
    )

    assert encoder.categorical_indices == [1]
    assert matrix.shape == (1, 2)
    assert np.isnan(matrix[0, 1])


def _synthetic_frame() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = date(2025, 9, 1)
    race_id = 0
    entry_id = 0
    # 36 dates reach the fixed valid period (2026-03~05).
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


def test_temporal_train_partitions_are_ordered() -> None:
    fit, tune, calibration, boundaries = temporal_train_partitions(_synthetic_frame())

    assert fit["race_date_local"].max() < tune["race_date_local"].min()
    assert tune["race_date_local"].max() < calibration["race_date_local"].min()
    assert boundaries["fit_end"] == fit["race_date_local"].max()


def test_temporal_train_partitions_accept_custom_walk_forward_bounds() -> None:
    bounds = {
        "train": (None, "2025-12-31"),
        "valid": ("2026-01-01", "2026-04-30"),
        "test": ("2026-05-01", None),
    }
    fit, tune, calibration, _ = temporal_train_partitions(
        _synthetic_frame(),
        split_bounds=bounds,
    )

    assert calibration["race_date_local"].max() <= "2025-12-31"
    assert fit["race_date_local"].max() < tune["race_date_local"].min()


def test_train_lightgbm_models_produces_coherent_valid_probabilities() -> None:
    result = train_lightgbm_models(
        _synthetic_frame(),
        feature_names=["score", "meet", "horse_number"],
        dataset_version="synthetic",
        as_of_policy="start_minus_30m",
        seed=7,
        calibration="raw",
        hyperparameters={
            "n_estimators": 60,
            "learning_rate": 0.1,
            "num_leaves": 7,
            "min_child_samples": 5,
            "n_jobs": 1,
        },
    )

    predictions = result.valid_predictions
    assert set(result.bundle.targets) == {"win", "top2", "top3"}
    sums = predictions.group_by("race_id").agg(
        pl.col("prob_win").sum(),
        pl.col("prob_top2").sum(),
        pl.col("prob_top3").sum(),
    )
    assert sums["prob_win"].to_list() == pytest.approx([1.0] * sums.height)
    assert sums["prob_top2"].to_list() == pytest.approx([2.0] * sums.height)
    assert sums["prob_top3"].to_list() == pytest.approx([3.0] * sums.height)
    assert result.valid_metrics["win"]["auc"] > 0.8
