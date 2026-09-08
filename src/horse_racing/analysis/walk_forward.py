"""Expanding-window validation for chronological horse-racing models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl

from horse_racing.analysis.lightgbm_model import ModelInputError, train_lightgbm_models
from horse_racing.analysis.metrics import evaluate_probabilities


@dataclass(frozen=True)
class WalkForwardFold:
    year: int
    train_end: str
    valid_start: str
    valid_end: str
    metrics: dict[str, float]
    best_iteration: int
    calibration_method: str


@dataclass
class WalkForwardResult:
    folds: list[WalkForwardFold]
    aggregate_metrics: dict[str, float]
    predictions: pl.DataFrame
    aggregate_target_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    aggregate_rank_metrics: dict[str, float] = field(default_factory=dict)


def fold_bounds(year: int) -> dict[str, tuple[str | None, str | None]]:
    if year < 1901:
        raise ValueError("walk-forward 연도가 올바르지 않습니다.")
    return {
        "train": (None, f"{year - 1:04d}-12-31"),
        "valid": (f"{year:04d}-01-01", f"{year:04d}-12-31"),
        "test": (f"{year + 1:04d}-01-01", None),
    }


def run_lightgbm_walk_forward(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    years: list[int],
    seed: int = 42,
    calibration: str = "sigmoid",
    hyperparameters: dict[str, Any] | None = None,
) -> WalkForwardResult:
    """Train only on prior years and evaluate each requested calendar year."""
    ordered_years = sorted(set(years))
    if not ordered_years:
        raise ModelInputError("walk-forward 평가 연도가 없습니다.")

    folds: list[WalkForwardFold] = []
    prediction_frames: list[pl.DataFrame] = []
    for year in ordered_years:
        bounds = fold_bounds(year)
        valid_start, valid_end = bounds["valid"]
        valid_rows = frame.filter(
            (pl.col("race_date_local") >= valid_start) & (pl.col("race_date_local") <= valid_end)
        )
        if valid_rows.height == 0:
            raise ModelInputError(f"{year}년 valid 표본이 없습니다.")
        result = train_lightgbm_models(
            frame,
            feature_names=feature_names,
            dataset_version=dataset_version,
            as_of_policy=as_of_policy,
            seed=seed,
            calibration=calibration,
            hyperparameters=hyperparameters,
            target_labels=("win",),
            split_bounds=bounds,
        )
        target = result.bundle.targets["win"]
        folds.append(
            WalkForwardFold(
                year=year,
                train_end=str(bounds["train"][1]),
                valid_start=str(valid_start),
                valid_end=str(valid_end),
                metrics=result.valid_metrics["win"],
                best_iteration=target.best_iteration,
                calibration_method=target.calibration_method,
            )
        )
        prediction_frames.append(
            result.valid_predictions.with_columns(pl.lit(year, dtype=pl.Int32).alias("fold_year"))
        )

    predictions = pl.concat(prediction_frames, how="vertical")
    labels = frame.select("race_id", "race_entry_id", "horse_number", "win")
    scored = labels.join(
        predictions,
        on=["race_id", "race_entry_id", "horse_number"],
        how="inner",
    )
    aggregate = evaluate_probabilities(scored, "prob_win", label_column="win")
    return WalkForwardResult(
        folds=folds,
        aggregate_metrics=aggregate,
        predictions=predictions,
    )


def run_ranking_walk_forward(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    years: list[int],
    seed: int = 42,
    hyperparameters: dict[str, Any] | None = None,
    calibration_objective: str = "winner",
    relevance_depth: int = 3,
    relevance_mode: str = "finish_order",
    margin_performance: bool = False,
) -> WalkForwardResult:
    """Expanding-window LambdaRank evaluation with calibration-block temperature."""
    from horse_racing.analysis.ranking_model import (
        actual_rank_bucket_nll,
        topk_ranked_probability_score,
        train_ranking_model,
        with_topk_labels,
    )

    ordered_years = sorted(set(years))
    if not ordered_years:
        raise ModelInputError("walk-forward 평가 연도가 없습니다.")
    folds: list[WalkForwardFold] = []
    prediction_frames: list[pl.DataFrame] = []
    for year in ordered_years:
        bounds = fold_bounds(year)
        valid_start, valid_end = bounds["valid"]
        valid_rows = frame.filter(
            (pl.col("race_date_local") >= valid_start) & (pl.col("race_date_local") <= valid_end)
        )
        if valid_rows.height == 0:
            raise ModelInputError(f"{year}년 valid 표본이 없습니다.")
        result = train_ranking_model(
            frame,
            feature_names=feature_names,
            dataset_version=dataset_version,
            as_of_policy=as_of_policy,
            seed=seed,
            hyperparameters=hyperparameters,
            split_bounds=bounds,
            calibration_objective=calibration_objective,
            relevance_depth=relevance_depth,
            relevance_mode=relevance_mode,
            margin_performance=margin_performance,
        )
        folds.append(
            WalkForwardFold(
                year=year,
                train_end=str(bounds["train"][1]),
                valid_start=str(valid_start),
                valid_end=str(valid_end),
                metrics=result.valid_metrics,
                best_iteration=result.bundle.best_iteration,
                calibration_method=(
                    f"{calibration_objective} PL β={result.bundle.softmax_beta:.3f}"
                ),
            )
        )
        prediction_frames.append(
            result.valid_predictions.with_columns(pl.lit(year, dtype=pl.Int32).alias("fold_year"))
        )
    predictions = pl.concat(prediction_frames, how="vertical")
    max_rank = 5 if relevance_depth == 5 else 3
    label_columns = [
        "race_id",
        "race_entry_id",
        "horse_number",
        "win",
        "top2",
        "top3",
    ]
    if max_rank == 5:
        label_columns.append("finish_position")
    labels = with_topk_labels(frame.select(*label_columns), max_rank=max_rank)
    scored = labels.join(
        predictions,
        on=["race_id", "race_entry_id", "horse_number"],
        how="inner",
    )
    aggregate_target_metrics = {
        target: evaluate_probabilities(
            scored,
            f"prob_{target}",
            label_column=target,
        )
        for target in ("win", "top2", "top3", "top4", "top5")[:max_rank]
        if f"prob_{target}" in scored.columns
    }
    aggregate_rank_metrics = {
        "topk_rps": topk_ranked_probability_score(scored, max_rank=max_rank),
        "actual_rank_bucket_nll": actual_rank_bucket_nll(scored, max_rank=max_rank),
    }
    return WalkForwardResult(
        folds=folds,
        aggregate_metrics=aggregate_target_metrics["win"],
        predictions=predictions,
        aggregate_target_metrics=aggregate_target_metrics,
        aggregate_rank_metrics=aggregate_rank_metrics,
    )


def run_racefit_walk_forward(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    years: list[int],
    seed: int = 42,
    hyperparameters: dict[str, Any] | None = None,
) -> WalkForwardResult:
    """Expanding-window RaceFit scenario-mixture evaluation."""
    from horse_racing.analysis.racefit_model import train_racefit_model

    ordered_years = sorted(set(years))
    if not ordered_years:
        raise ModelInputError("walk-forward 평가 연도가 없습니다.")
    folds: list[WalkForwardFold] = []
    prediction_frames: list[pl.DataFrame] = []
    for year in ordered_years:
        bounds = fold_bounds(year)
        valid_start, valid_end = bounds["valid"]
        valid_rows = frame.filter(
            (pl.col("race_date_local") >= valid_start) & (pl.col("race_date_local") <= valid_end)
        )
        if valid_rows.height == 0:
            raise ModelInputError(f"{year}년 valid 표본이 없습니다.")
        result = train_racefit_model(
            frame,
            feature_names=feature_names,
            dataset_version=dataset_version,
            as_of_policy=as_of_policy,
            seed=seed,
            hyperparameters=hyperparameters,
            split_bounds=bounds,
        )
        folds.append(
            WalkForwardFold(
                year=year,
                train_end=str(bounds["train"][1]),
                valid_start=str(valid_start),
                valid_end=str(valid_end),
                metrics=result.valid_metrics,
                best_iteration=result.bundle.base_bundle.best_iteration,
                calibration_method=(f"RaceFit mix β={np.exp(result.bundle.log_beta):.3f}"),
            )
        )
        prediction_frames.append(
            result.valid_predictions.with_columns(pl.lit(year, dtype=pl.Int32).alias("fold_year"))
        )
    predictions = pl.concat(prediction_frames, how="vertical")
    labels = frame.select("race_id", "race_entry_id", "horse_number", "win", "top2", "top3")
    scored = labels.join(
        predictions,
        on=["race_id", "race_entry_id", "horse_number"],
        how="inner",
    )
    aggregate_target_metrics = {
        target: evaluate_probabilities(
            scored,
            f"prob_{target}",
            label_column=target,
        )
        for target in ("win", "top2", "top3")
    }
    return WalkForwardResult(
        folds=folds,
        aggregate_metrics=aggregate_target_metrics["win"],
        predictions=predictions,
        aggregate_target_metrics=aggregate_target_metrics,
    )


def run_two_stage_walk_forward(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    years: list[int],
    seed: int = 42,
) -> WalkForwardResult:
    """Evaluate leakage-safe predicted-pace features in expanding-year folds."""
    from horse_racing.analysis.pace_model import train_two_stage_fold

    folds: list[WalkForwardFold] = []
    prediction_frames: list[pl.DataFrame] = []
    for year in sorted(set(years)):
        bounds = fold_bounds(year)
        result = train_two_stage_fold(
            frame,
            feature_names=feature_names,
            dataset_version=dataset_version,
            as_of_policy=as_of_policy,
            split_bounds=bounds,
            seed=seed,
        )
        target = result.outcome.bundle.targets["win"]
        folds.append(
            WalkForwardFold(
                year=year,
                train_end=str(bounds["train"][1]),
                valid_start=str(bounds["valid"][0]),
                valid_end=str(bounds["valid"][1]),
                metrics=result.outcome.valid_metrics["win"],
                best_iteration=target.best_iteration,
                calibration_method=f"sigmoid; pace MAE={result.pace_valid_mae:.3f}",
            )
        )
        prediction_frames.append(
            result.outcome.valid_predictions.with_columns(
                pl.lit(year, dtype=pl.Int32).alias("fold_year")
            )
        )
    predictions = pl.concat(prediction_frames, how="vertical")
    labels = frame.select("race_id", "race_entry_id", "horse_number", "win")
    scored = labels.join(
        predictions,
        on=["race_id", "race_entry_id", "horse_number"],
        how="inner",
    )
    aggregate = evaluate_probabilities(scored, "prob_win", label_column="win")
    return WalkForwardResult(folds, aggregate, predictions)


def run_two_stage_ranking_walk_forward(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    years: list[int],
    seed: int = 42,
) -> WalkForwardResult:
    """Evaluate cross-fitted learned pace feeding a LambdaRank outcome model."""
    from horse_racing.analysis.pace_model import train_two_stage_ranking_fold

    folds: list[WalkForwardFold] = []
    prediction_frames: list[pl.DataFrame] = []
    for year in sorted(set(years)):
        bounds = fold_bounds(year)
        result = train_two_stage_ranking_fold(
            frame,
            feature_names=feature_names,
            dataset_version=dataset_version,
            as_of_policy=as_of_policy,
            split_bounds=bounds,
            seed=seed,
        )
        outcome = result.outcome
        folds.append(
            WalkForwardFold(
                year=year,
                train_end=str(bounds["train"][1]),
                valid_start=str(bounds["valid"][0]),
                valid_end=str(bounds["valid"][1]),
                metrics=outcome.valid_metrics,
                best_iteration=outcome.bundle.best_iteration,
                calibration_method=(
                    f"winner PL β={outcome.bundle.softmax_beta:.3f}; "
                    f"pace MAE={result.pace_valid_mae:.3f}"
                ),
            )
        )
        prediction_frames.append(
            outcome.valid_predictions.with_columns(pl.lit(year, dtype=pl.Int32).alias("fold_year"))
        )
    predictions = pl.concat(prediction_frames, how="vertical")
    labels = frame.select("race_id", "race_entry_id", "horse_number", "win", "top2", "top3")
    scored = labels.join(
        predictions,
        on=["race_id", "race_entry_id", "horse_number"],
        how="inner",
    )
    target_metrics = {
        target: evaluate_probabilities(scored, f"prob_{target}", label_column=target)
        for target in ("win", "top2", "top3")
    }
    return WalkForwardResult(
        folds=folds,
        aggregate_metrics=target_metrics["win"],
        predictions=predictions,
        aggregate_target_metrics=target_metrics,
    )


def run_segment_walk_forward(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    years: list[int],
    seed: int = 42,
) -> WalkForwardResult:
    from horse_racing.analysis.segment_correction import (
        run_segment_correction_walk_forward,
    )

    return run_segment_correction_walk_forward(
        frame,
        feature_names=feature_names,
        dataset_version=dataset_version,
        as_of_policy=as_of_policy,
        years=years,
        seed=seed,
    )


def render_walk_forward_report(
    result: WalkForwardResult,
    *,
    dataset_version: str,
    as_of_policy: str,
    profile: str,
    seed: int,
    model_name: str = "LightGBM binary",
) -> str:
    lines = [
        f"# {model_name} 연도별 walk-forward 리포트",
        "",
        f"- 데이터셋: `{dataset_version}` / `{as_of_policy}`",
        f"- profile: `{profile}`",
        f"- seed: {seed}",
        "- 각 fold는 해당 연도 이전 데이터만 학습에 사용",
        "- calibration 방법은 fold 평가 전에 고정",
        "",
        "| 연도 | 학습 종료 | 경주 | 행 | best iter | calibration | "
        "log loss | AUC | ECE | Top1 | Top3 |",
        "|---:|---|---:|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for fold in result.folds:
        metrics = fold.metrics
        lines.append(
            f"| {fold.year} | {fold.train_end} | {metrics['n_races']:.0f} | "
            f"{metrics['n_rows']:.0f} | {fold.best_iteration} | "
            f"{fold.calibration_method} | {metrics['log_loss']:.4f} | "
            f"{metrics.get('auc', float('nan')):.4f} | {metrics['ece']:.4f} | "
            f"{metrics['top1_hit_rate']:.4f} | {metrics['top3_inclusion_rate']:.4f} |"
        )
    metrics = result.aggregate_metrics
    lines.extend(
        [
            "",
            "## 전체 fold 결합",
            "",
            f"- 경주: {metrics['n_races']:.0f}",
            f"- 행: {metrics['n_rows']:.0f}",
            f"- win log loss: {metrics['log_loss']:.6f}",
            f"- AUC: {metrics.get('auc', float('nan')):.6f}",
            f"- ECE: {metrics['ece']:.6f}",
            f"- Top1: {metrics['top1_hit_rate']:.4%}",
            f"- 우승마 Top3 포함: {metrics['top3_inclusion_rate']:.4%}",
            "",
            "이 리포트는 모델 선택용 과거 시뮬레이션이며 신규 미래 holdout을 대체하지 않는다.",
            "",
        ]
    )
    if len(result.aggregate_target_metrics) > 1:
        lines.extend(
            [
                "## Full ranking 주변확률",
                "",
                "| target | log loss | brier | AUC | ECE |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for target in ("win", "top2", "top3", "top4", "top5"):
            target_metrics = result.aggregate_target_metrics.get(target)
            if target_metrics is None:
                continue
            lines.append(
                f"| {target} | {target_metrics['log_loss']:.4f} | "
                f"{target_metrics['brier']:.4f} | "
                f"{target_metrics.get('auc', float('nan')):.4f} | "
                f"{target_metrics['ece']:.4f} |"
            )
        lines.append("")
    if result.aggregate_rank_metrics:
        rank_metrics = result.aggregate_rank_metrics
        lines.extend(
            [
                "## 순위분포 전체 평가",
                "",
                f"- truncated RPS: {rank_metrics['topk_rps']:.6f}",
                f"- actual-rank bucket NLL: {rank_metrics['actual_rank_bucket_nll']:.6f}",
                "",
            ]
        )
    return "\n".join(lines)
