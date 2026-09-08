"""Small local correction models layered on top of the common model."""

from __future__ import annotations

from typing import Any

import polars as pl

from horse_racing.analysis.lightgbm_model import ModelInputError, train_lightgbm_models
from horse_racing.analysis.metrics import evaluate_probabilities
from horse_racing.analysis.ranking_model import train_ranking_model
from horse_racing.analysis.walk_forward import WalkForwardFold, WalkForwardResult, fold_bounds

_KEYS = ["race_id", "race_entry_id", "horse_number"]


def _segment_frame(frame: pl.DataFrame, name: str) -> pl.DataFrame:
    if name == "jeju":
        return frame.filter(pl.col("meet_code") == 2)
    if name == "long":
        return frame.filter(pl.col("distance_m") >= 1700)
    raise ValueError(f"알 수 없는 보정 구간: {name}")


def run_segment_correction_walk_forward(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    years: list[int],
    seed: int = 42,
    rank_weight: float = 0.25,
    local_weight: float = 0.25,
    hyperparameters: dict[str, Any] | None = None,
) -> WalkForwardResult:
    """Blend common binary/ranking models, then add Jeju/long local residuals."""
    if not 0 <= rank_weight <= 1 or not 0 <= local_weight <= 1:
        raise ValueError("ensemble weight는 0~1이어야 합니다.")
    required = {"meet_code", "distance_m"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ModelInputError(f"구간 보정 입력 컬럼 없음: {', '.join(missing)}")

    folds: list[WalkForwardFold] = []
    prediction_frames: list[pl.DataFrame] = []
    for year in sorted(set(years)):
        bounds = fold_bounds(year)
        binary = train_lightgbm_models(
            frame,
            feature_names=feature_names,
            dataset_version=dataset_version,
            as_of_policy=as_of_policy,
            seed=seed,
            calibration="sigmoid",
            hyperparameters=hyperparameters,
            target_labels=("win",),
            split_bounds=bounds,
        )
        ranking = train_ranking_model(
            frame,
            feature_names=feature_names,
            dataset_version=dataset_version,
            as_of_policy=as_of_policy,
            seed=seed,
            hyperparameters=hyperparameters,
            split_bounds=bounds,
        )
        predictions = binary.valid_predictions.select(
            *_KEYS,
            pl.col("prob_win").alias("_prob_binary"),
        ).join(
            ranking.valid_predictions.select(
                *_KEYS,
                pl.col("prob_win").alias("_prob_ranking"),
            ),
            on=_KEYS,
        ).with_columns(
            (
                pl.col("_prob_binary") * (1.0 - rank_weight)
                + pl.col("_prob_ranking") * rank_weight
            ).alias("prob_win")
        )

        for segment_name in ("jeju", "long"):
            segment = _segment_frame(frame, segment_name)
            if segment.height == 0:
                continue
            local = train_lightgbm_models(
                segment,
                feature_names=feature_names,
                dataset_version=dataset_version,
                as_of_policy=as_of_policy,
                seed=seed + (10 if segment_name == "jeju" else 20),
                calibration="sigmoid",
                hyperparameters=hyperparameters,
                target_labels=("win",),
                split_bounds=bounds,
            )
            local_column = f"_prob_{segment_name}"
            predictions = predictions.join(
                local.valid_predictions.select(
                    *_KEYS,
                    pl.col("prob_win").alias(local_column),
                ),
                on=_KEYS,
                how="left",
            ).with_columns(
                pl.when(pl.col(local_column).is_not_null())
                .then(
                    pl.col("prob_win") * (1.0 - local_weight)
                    + pl.col(local_column) * local_weight
                )
                .otherwise(pl.col("prob_win"))
                .alias("prob_win")
            )

        predictions = predictions.select(*_KEYS, "prob_win")
        valid_start, valid_end = bounds["valid"]
        valid = frame.filter(
            (pl.col("race_date_local") >= valid_start)
            & (pl.col("race_date_local") <= valid_end)
        )
        scored = valid.join(predictions, on=_KEYS)
        metrics = evaluate_probabilities(scored, "prob_win", label_column="win")
        folds.append(
            WalkForwardFold(
                year=year,
                train_end=str(bounds["train"][1]),
                valid_start=str(valid_start),
                valid_end=str(valid_end),
                metrics=metrics,
                best_iteration=0,
                calibration_method=(
                    f"binary {1-rank_weight:.0%}+rank {rank_weight:.0%}; "
                    f"local {local_weight:.0%}"
                ),
            )
        )
        prediction_frames.append(
            predictions.with_columns(pl.lit(year).cast(pl.Int32).alias("fold_year"))
        )

    all_predictions = pl.concat(prediction_frames, how="vertical")
    labels = frame.select(*_KEYS, "win")
    aggregate = evaluate_probabilities(
        labels.join(all_predictions, on=_KEYS),
        "prob_win",
        label_column="win",
    )
    return WalkForwardResult(folds, aggregate, all_predictions)
