"""Race-grouped LightGBM LambdaRank model with probability conversion."""

from __future__ import annotations

import pickle
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl

from horse_racing.analysis.baselines import assign_split
from horse_racing.analysis.lightgbm_model import (
    FeatureEncoder,
    ModelInputError,
    fit_feature_encoder,
    temporal_train_partitions,
    transform_features,
)
from horse_racing.analysis.metrics import evaluate_probabilities, log_loss
from horse_racing.analysis.plackett_luce import (
    fit_plackett_luce_beta_topk,
    plackett_luce_rank_marginals,
    plackett_luce_top3_nll,
    plackett_luce_topk_nll,
)

CALIBRATION_WINNER = "winner"
CALIBRATION_FULL_TOP3 = "full_top3"
CALIBRATION_FULL_TOP5 = "full_top5"
RELEVANCE_FINISH_ORDER = "finish_order"
RELEVANCE_MARGIN = "margin"
RELEVANCE_MODES = {RELEVANCE_FINISH_ORDER, RELEVANCE_MARGIN}
MARGIN_MAX_RELEVANCE = 10
MARGIN_HALF_LIFE_LENGTHS = 5.0
HORSE_LENGTH_M = 2.4
PERFORMANCE_WEIGHT_GRID = (
    0.0,
    0.05,
    0.1,
    0.15,
    0.2,
    0.3,
    0.4,
    0.5,
    0.75,
    1.0,
    1.25,
    1.5,
    2.0,
)
CALIBRATION_OBJECTIVES = {
    CALIBRATION_WINNER,
    CALIBRATION_FULL_TOP3,
    CALIBRATION_FULL_TOP5,
}

DEFAULT_RANKING_PARAMS: dict[str, Any] = {
    "objective": "lambdarank",
    "metric": "ndcg",
    "n_estimators": 1_200,
    "learning_rate": 0.03,
    "num_leaves": 31,
    "max_depth": -1,
    "min_child_samples": 80,
    "subsample": 0.9,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "verbosity": -1,
    "n_jobs": -1,
}


@dataclass
class RankingModelBundle:
    dataset_version: str
    as_of_policy: str
    feature_encoder: FeatureEncoder
    estimator: lgb.LGBMRanker
    softmax_beta: float
    best_iteration: int
    hyperparameters: dict[str, Any]
    seed: int
    split_dates: dict[str, str]
    created_at_ms: int = field(default_factory=lambda: time.time_ns() // 1_000_000)
    calibration_objective: str = CALIBRATION_WINNER
    full_distribution: bool = False
    max_rank: int = 3
    relevance_depth: int = 3
    relevance_mode: str = RELEVANCE_FINISH_ORDER
    performance_estimator: lgb.LGBMRegressor | None = None
    performance_weight: float = 0.0
    performance_scale: float = 1.0
    performance_best_iteration: int = 0

    def predict(self, frame: pl.DataFrame) -> pl.DataFrame:
        ordered = _ordered(frame)
        base_scores = np.asarray(
            self.estimator.predict(transform_features(ordered, self.feature_encoder)),
            dtype=float,
        )
        race_ids = ordered["race_id"].to_numpy()
        performance_component = np.zeros_like(base_scores)
        performance_estimator = getattr(self, "performance_estimator", None)
        if performance_estimator is not None and getattr(self, "performance_weight", 0.0) > 0:
            performance_scores = np.asarray(
                performance_estimator.predict(transform_features(ordered, self.feature_encoder)),
                dtype=float,
            )
            performance_component = (
                float(self.performance_weight)
                * float(getattr(self, "performance_scale", 1.0))
                * _race_centered(performance_scores, race_ids)
            )
        scores = base_scores + performance_component
        objective = getattr(self, "calibration_objective", CALIBRATION_WINNER)
        if objective in {CALIBRATION_FULL_TOP3, CALIBRATION_FULL_TOP5} or getattr(
            self, "full_distribution", False
        ):
            max_rank = int(getattr(self, "max_rank", 3))
            probabilities = plackett_luce_rank_marginals(
                scores,
                race_ids,
                beta=self.softmax_beta,
                max_rank=max_rank,
            )
            return ordered.select("race_id", "race_entry_id", "horse_number").with_columns(
                *(pl.Series(name, values) for name, values in probabilities.items()),
                pl.Series("rank_score_base", base_scores),
                pl.Series("margin_performance_score", performance_component),
                pl.Series("rank_score", scores),
            )
        probabilities = race_softmax(scores, race_ids, beta=self.softmax_beta)
        return ordered.select("race_id", "race_entry_id", "horse_number").with_columns(
            pl.Series("prob_win", probabilities),
            pl.Series("rank_score_base", base_scores),
            pl.Series("margin_performance_score", performance_component),
            pl.Series("rank_score", scores),
        )


@dataclass
class RankingTrainResult:
    bundle: RankingModelBundle
    valid_predictions: pl.DataFrame
    valid_metrics: dict[str, float]
    valid_target_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    ordered_top3_nll: float | None = None
    ordered_topk_nll: float | None = None
    topk_rps: float | None = None
    actual_rank_nll: float | None = None


def _ordered(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.sort("race_date_local", "race_id", "horse_number")


def _group_sizes(frame: pl.DataFrame) -> np.ndarray:
    return frame.group_by("race_id", maintain_order=True).len().get_column("len").to_numpy()


def _race_centered(values: np.ndarray, race_ids: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    race_ids = np.asarray(race_ids)
    result = np.empty_like(values)
    groups: dict[object, list[int]] = {}
    for index, race_id in enumerate(race_ids):
        key = race_id.item() if hasattr(race_id, "item") else race_id
        groups.setdefault(key, []).append(index)
    for indices in groups.values():
        locations = np.asarray(indices, dtype=int)
        result[locations] = values[locations] - float(np.mean(values[locations]))
    return result


def margin_performance_target(frame: pl.DataFrame) -> np.ndarray:
    """Continuous within-race performance target from elapsed-time margins."""
    required = {"race_id", "finish_time_ms"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ModelInputError("착차 성능 target 입력 컬럼 없음: " + ", ".join(missing))
    values = (
        frame.select(
            (
                100.0
                * (
                    pl.col("finish_time_ms").median().over("race_id") / pl.col("finish_time_ms")
                ).log()
            )
            .clip(-10.0, 10.0)
            .alias("target")
        )
        .get_column("target")
        .to_numpy()
    )
    return np.nan_to_num(np.asarray(values, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)


def margin_performance_weight(frame: pl.DataFrame) -> np.ndarray:
    """Exclude the few historical rows without a valid elapsed-time target."""
    values = frame["finish_time_ms"].cast(pl.Float64).to_numpy()
    return (np.isfinite(values) & (values > 0)).astype(float)


def ranking_relevance(
    frame: pl.DataFrame,
    *,
    relevance_depth: int = 3,
    relevance_mode: str = RELEVANCE_FINISH_ORDER,
) -> np.ndarray:
    """Top-heavy relevance through third or fifth place."""
    if relevance_depth not in {3, 5}:
        raise ModelInputError("ranking relevance_depth는 3 또는 5만 지원합니다.")
    if relevance_mode not in RELEVANCE_MODES:
        raise ModelInputError(f"지원하지 않는 relevance_mode: {relevance_mode}")
    if relevance_mode == RELEVANCE_MARGIN:
        if relevance_depth != 5:
            raise ModelInputError("margin relevance는 relevance_depth=5가 필요합니다.")
        return margin_aware_relevance(frame, relevance_depth=relevance_depth)
    if relevance_depth == 5:
        if "finish_position" not in frame.columns:
            raise ModelInputError("Top5 relevance에는 finish_position이 필요합니다.")
        return (
            frame.select(
                pl.when(pl.col("finish_position").is_between(1, relevance_depth))
                .then(relevance_depth + 1 - pl.col("finish_position"))
                .otherwise(0)
                .cast(pl.Int32)
                .alias("relevance")
            )
            .get_column("relevance")
            .to_numpy()
        )
    return (
        frame.select(
            pl.when(pl.col("win") == 1)
            .then(3)
            .when(pl.col("top2") == 1)
            .then(2)
            .when(pl.col("top3") == 1)
            .then(1)
            .otherwise(0)
            .cast(pl.Int32)
            .alias("relevance")
        )
        .get_column("relevance")
        .to_numpy()
    )


def margin_aware_relevance(
    frame: pl.DataFrame,
    *,
    relevance_depth: int = 5,
    max_relevance: int = MARGIN_MAX_RELEVANCE,
    half_life_lengths: float = MARGIN_HALF_LIFE_LENGTHS,
) -> np.ndarray:
    """Convert finish gaps to linear-gain relevance while retaining the Top5 boundary.

    The elapsed-time gap is converted to an approximate distance gap and then to
    horse lengths.  A five-length deficit halves relevance.  Close finishes can
    therefore share a label, while a badly beaten placed horse receives less gain.
    """
    required = {"race_id", "finish_position", "finish_time_ms", "distance_m"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ModelInputError("margin relevance 입력 컬럼 없음: " + ", ".join(missing))
    if max_relevance < 1 or half_life_lengths <= 0:
        raise ModelInputError("margin relevance 설정값이 올바르지 않습니다.")

    race_ids = frame["race_id"].to_numpy()
    positions = frame["finish_position"].to_numpy()
    times = frame["finish_time_ms"].cast(pl.Float64).to_numpy()
    distances = frame["distance_m"].cast(pl.Float64).to_numpy()
    result = np.zeros(frame.height, dtype=np.int32)
    groups: dict[object, list[int]] = {}
    for index, race_id in enumerate(race_ids):
        key = race_id.item() if hasattr(race_id, "item") else race_id
        groups.setdefault(key, []).append(index)

    for indices in groups.values():
        locations = np.asarray(indices, dtype=int)
        race_positions = positions[locations]
        eligible = (race_positions >= 1) & (race_positions <= relevance_depth)
        if not eligible.any():
            continue
        race_times = times[locations]
        race_distances = distances[locations]
        winner_mask = race_positions == 1
        usable = (
            np.isfinite(race_times).all()
            and np.all(race_times > 0)
            and np.isfinite(race_distances).all()
            and np.all(race_distances > 0)
            and winner_mask.any()
        )
        if not usable:
            fallback = np.maximum(
                0,
                (relevance_depth + 1 - race_positions) * max_relevance / relevance_depth,
            )
            result[locations[eligible]] = np.rint(fallback[eligible]).astype(np.int32)
            continue
        winner_time = float(np.min(race_times[winner_mask]))
        gap_m = race_distances * np.maximum(0.0, race_times - winner_time) / winner_time
        gap_lengths = gap_m / HORSE_LENGTH_M
        quality = max_relevance * np.power(0.5, gap_lengths / half_life_lengths)
        labels = np.rint(quality).astype(np.int32)
        labels[~eligible] = 0
        labels[winner_mask] = max_relevance
        result[locations] = np.clip(labels, 0, max_relevance)
    return result


def with_topk_labels(frame: pl.DataFrame, *, max_rank: int) -> pl.DataFrame:
    """Attach cumulative actual top-k labels from official finish position."""
    if "finish_position" not in frame.columns:
        if max_rank <= 3:
            return frame
        raise ModelInputError("Top4/Top5 평가에는 finish_position이 필요합니다.")
    return frame.with_columns(
        (pl.col("finish_position") == 1).cast(pl.Int8).alias("win"),
        *[
            (pl.col("finish_position") <= rank).cast(pl.Int8).alias(f"top{rank}")
            for rank in range(2, max_rank + 1)
        ],
    )


def topk_ranked_probability_score(frame: pl.DataFrame, *, max_rank: int) -> float:
    """Truncated ordinal RPS over cumulative rank thresholds 1..max_rank."""
    labeled = with_topk_labels(frame, max_rank=max_rank)
    errors = []
    for rank in range(1, max_rank + 1):
        probability = "prob_win" if rank == 1 else f"prob_top{rank}"
        label = "win" if rank == 1 else f"top{rank}"
        errors.append((pl.col(probability) - pl.col(label)).pow(2))
    return float(labeled.select(pl.mean_horizontal(errors).mean()).item())


def actual_rank_bucket_nll(frame: pl.DataFrame, *, max_rank: int) -> float:
    """Categorical NLL of exact ranks 1..K plus a K+ bucket."""
    positions = _finish_positions(frame)
    topk = frame[f"prob_top{max_rank}"].to_numpy()
    probabilities = np.maximum(1.0 - topk, 0.0)
    for rank in range(1, max_rank + 1):
        mask = positions == rank
        probabilities[mask] = frame[f"prob_rank{rank}"].to_numpy()[mask]
    return -float(np.log(np.clip(probabilities, 1e-15, 1.0)).mean())


def rank_comparison_frame(
    frame: pl.DataFrame,
    predictions: pl.DataFrame,
    *,
    max_rank: int,
) -> pl.DataFrame:
    """Horse-level predicted rank distribution beside the official result."""
    keys = ["race_id", "race_entry_id", "horse_number"]
    context = [
        column
        for column in (
            "race_date_local",
            "race_number",
            "horse_id",
            "finish_position",
        )
        if column in frame.columns
    ]
    joined = frame.select(*keys, *context).join(predictions, on=keys, how="inner")
    joined = with_topk_labels(joined, max_rank=max_rank)
    tail = (1.0 - pl.col(f"prob_top{max_rank}")).clip(0.0, 1.0)
    expected = (
        sum(rank * pl.col(f"prob_rank{rank}") for rank in range(1, max_rank + 1))
        + (max_rank + 1) * tail
    )
    actual_probability = tail
    for rank in range(max_rank, 0, -1):
        actual_probability = (
            pl.when(pl.col("finish_position") == rank)
            .then(pl.col(f"prob_rank{rank}"))
            .otherwise(actual_probability)
        )
    return joined.with_columns(
        pl.col("finish_position").clip(1, max_rank + 1).alias("actual_rank_bucket"),
        expected.alias("expected_rank_bucket"),
        actual_probability.alias("prob_actual_rank_bucket"),
    ).sort("race_date_local", "race_id", "horse_number")


def race_softmax(scores: np.ndarray, race_ids: np.ndarray, *, beta: float) -> np.ndarray:
    scores = np.asarray(scores, dtype=float)
    race_ids = np.asarray(race_ids)
    if len(scores) != len(race_ids):
        raise ValueError("rank score와 race_id 길이가 다릅니다.")
    output = np.empty(len(scores), dtype=float)
    groups: dict[Any, list[int]] = {}
    for index, race_id in enumerate(race_ids):
        key = race_id.item() if hasattr(race_id, "item") else race_id
        groups.setdefault(key, []).append(index)
    for indices in groups.values():
        locations = np.asarray(indices, dtype=int)
        logits = np.clip(scores[locations] * beta, -50.0, 50.0)
        exponentials = np.exp(logits - logits.max())
        output[locations] = exponentials / exponentials.sum()
    return output


def fit_softmax_beta(
    scores: np.ndarray,
    race_ids: np.ndarray,
    labels: np.ndarray,
) -> float:
    """Select the score temperature on the pre-validation calibration block."""
    candidates = np.geomspace(0.03, 30.0, 121)
    losses = [
        log_loss(race_softmax(scores, race_ids, beta=float(beta)).tolist(), labels.tolist())
        for beta in candidates
    ]
    best_index = int(np.argmin(losses))
    if 0 < best_index < len(candidates) - 1:
        candidates = np.geomspace(candidates[best_index - 1], candidates[best_index + 1], 81)
        losses = [
            log_loss(
                race_softmax(scores, race_ids, beta=float(beta)).tolist(),
                labels.tolist(),
            )
            for beta in candidates
        ]
        best_index = int(np.argmin(losses))
    return float(candidates[best_index])


def _finish_positions(frame: pl.DataFrame) -> np.ndarray:
    """Use exact official positions, with a label-derived fallback for old fixtures."""
    if "finish_position" in frame.columns:
        return frame["finish_position"].cast(pl.Int64).to_numpy()
    return (
        frame.select(
            pl.when(pl.col("win") == 1)
            .then(1)
            .when(pl.col("top2") == 1)
            .then(2)
            .when(pl.col("top3") == 1)
            .then(3)
            .otherwise(4)
            .cast(pl.Int64)
            .alias("finish_position")
        )
        .get_column("finish_position")
        .to_numpy()
    )


def train_ranking_model(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    seed: int = 42,
    hyperparameters: dict[str, Any] | None = None,
    split_bounds: Mapping[str, tuple[str | None, str | None]] | None = None,
    calibration_objective: str = CALIBRATION_WINNER,
    relevance_depth: int = 3,
    relevance_mode: str = RELEVANCE_FINISH_ORDER,
    margin_performance: bool = False,
) -> RankingTrainResult:
    required = {
        "race_id",
        "race_entry_id",
        "horse_number",
        "race_date_local",
        "win",
        "top2",
        "top3",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ModelInputError(f"ranking 입력 컬럼 없음: {', '.join(missing)}")
    if calibration_objective not in CALIBRATION_OBJECTIVES:
        raise ModelInputError(
            f"지원하지 않는 ranking calibration objective: {calibration_objective}"
        )
    if relevance_depth not in {3, 5}:
        raise ModelInputError("ranking relevance_depth는 3 또는 5만 지원합니다.")
    if relevance_mode not in RELEVANCE_MODES:
        raise ModelInputError(f"지원하지 않는 relevance_mode: {relevance_mode}")
    if relevance_mode == RELEVANCE_MARGIN and relevance_depth != 5:
        raise ModelInputError("margin relevance는 relevance_depth=5가 필요합니다.")
    if margin_performance and (
        relevance_depth != 5 or calibration_objective != CALIBRATION_FULL_TOP5
    ):
        raise ModelInputError(
            "착차 성능 보조모델은 relevance_depth=5와 full_top5 calibration이 필요합니다."
        )
    if relevance_depth == 5 and "finish_position" not in frame.columns:
        raise ModelInputError("Top5 relevance에는 finish_position이 필요합니다.")
    max_rank = 5 if relevance_depth == 5 or calibration_objective == CALIBRATION_FULL_TOP5 else 3
    if calibration_objective == CALIBRATION_FULL_TOP5 and relevance_depth != 5:
        raise ModelInputError("full_top5 calibration은 relevance_depth=5가 필요합니다.")

    fit, tune, calibration, split_dates = temporal_train_partitions(
        frame,
        split_bounds=split_bounds,
    )
    valid = (
        assign_split(frame, split_bounds=split_bounds)
        .filter(pl.col("split") == "valid")
        .drop("split")
    )
    if valid.height == 0:
        raise ModelInputError("ranking valid split이 비어 있습니다.")
    fit = _ordered(fit)
    tune = _ordered(tune)
    calibration = _ordered(calibration)
    valid = _ordered(valid)
    fit_tune = _ordered(pl.concat([fit, tune], how="vertical"))

    encoder = fit_feature_encoder(fit_tune, feature_names)
    params = {**DEFAULT_RANKING_PARAMS, **(hyperparameters or {})}
    params["random_state"] = seed
    if relevance_mode == RELEVANCE_MARGIN:
        params["label_gain"] = list(range(MARGIN_MAX_RELEVANCE + 1))
    selector = lgb.LGBMRanker(**params)
    selector.fit(
        transform_features(fit, encoder),
        ranking_relevance(
            fit,
            relevance_depth=relevance_depth,
            relevance_mode=relevance_mode,
        ),
        group=_group_sizes(fit),
        eval_X=transform_features(tune, encoder),
        eval_y=ranking_relevance(
            tune,
            relevance_depth=relevance_depth,
            relevance_mode=relevance_mode,
        ),
        eval_group=[_group_sizes(tune)],
        eval_at=[1, 3, 5] if relevance_depth == 5 else [1, 3],
        categorical_feature=encoder.categorical_indices,
        callbacks=[lgb.early_stopping(80, verbose=False), lgb.log_evaluation(0)],
    )
    best_iteration = int(selector.best_iteration_ or params["n_estimators"])
    final_params = {**params, "n_estimators": best_iteration}
    estimator = lgb.LGBMRanker(**final_params)
    estimator.fit(
        transform_features(fit_tune, encoder),
        ranking_relevance(
            fit_tune,
            relevance_depth=relevance_depth,
            relevance_mode=relevance_mode,
        ),
        group=_group_sizes(fit_tune),
        categorical_feature=encoder.categorical_indices,
        callbacks=[lgb.log_evaluation(0)],
    )

    rank_calibration_scores = np.asarray(
        estimator.predict(transform_features(calibration, encoder)), dtype=float
    )
    calibration_scores = rank_calibration_scores
    performance_estimator: lgb.LGBMRegressor | None = None
    performance_weight = 0.0
    performance_scale = 1.0
    performance_best_iteration = 0
    selected_beta: float | None = None
    if margin_performance:
        regression_params = {
            key: value
            for key, value in params.items()
            if key not in {"objective", "metric", "label_gain", "n_estimators"}
        }
        regression_params.update(
            {
                "objective": "huber",
                "metric": "l1",
                "n_estimators": int(params["n_estimators"]),
            }
        )
        performance_selector = lgb.LGBMRegressor(**regression_params)
        performance_selector.fit(
            transform_features(fit, encoder),
            margin_performance_target(fit),
            sample_weight=margin_performance_weight(fit),
            eval_X=transform_features(tune, encoder),
            eval_y=margin_performance_target(tune),
            eval_sample_weight=[margin_performance_weight(tune)],
            categorical_feature=encoder.categorical_indices,
            callbacks=[lgb.early_stopping(80, verbose=False), lgb.log_evaluation(0)],
        )
        performance_best_iteration = int(
            performance_selector.best_iteration_ or regression_params["n_estimators"]
        )
        performance_estimator = lgb.LGBMRegressor(
            **{**regression_params, "n_estimators": performance_best_iteration}
        )
        performance_estimator.fit(
            transform_features(fit_tune, encoder),
            margin_performance_target(fit_tune),
            sample_weight=margin_performance_weight(fit_tune),
            categorical_feature=encoder.categorical_indices,
            callbacks=[lgb.log_evaluation(0)],
        )
        race_ids = calibration["race_id"].to_numpy()
        centered_rank = _race_centered(rank_calibration_scores, race_ids)
        centered_performance = _race_centered(
            np.asarray(
                performance_estimator.predict(transform_features(calibration, encoder)),
                dtype=float,
            ),
            race_ids,
        )
        performance_scale = float(np.std(centered_rank) / max(np.std(centered_performance), 1e-12))
        finish_positions = _finish_positions(calibration)
        candidates: list[tuple[float, float, float, np.ndarray]] = []
        for weight in PERFORMANCE_WEIGHT_GRID:
            candidate_scores = (
                rank_calibration_scores + weight * performance_scale * centered_performance
            )
            candidate_beta = fit_plackett_luce_beta_topk(
                candidate_scores,
                race_ids,
                finish_positions,
                max_rank=5,
            )
            candidate_nll = plackett_luce_topk_nll(
                candidate_scores,
                race_ids,
                finish_positions,
                beta=candidate_beta,
                max_rank=5,
            )
            candidates.append((candidate_nll, weight, candidate_beta, candidate_scores))
        _, performance_weight, selected_beta, calibration_scores = min(
            candidates, key=lambda item: item[0]
        )
    if calibration_objective in {CALIBRATION_FULL_TOP3, CALIBRATION_FULL_TOP5}:
        calibration_rank = 5 if calibration_objective == CALIBRATION_FULL_TOP5 else 3
        beta = (
            selected_beta
            if selected_beta is not None
            else fit_plackett_luce_beta_topk(
                calibration_scores,
                calibration["race_id"].to_numpy(),
                _finish_positions(calibration),
                max_rank=calibration_rank,
            )
        )
    else:
        beta = fit_softmax_beta(
            calibration_scores,
            calibration["race_id"].to_numpy(),
            calibration["win"].cast(pl.Int64).to_numpy(),
        )
    bundle = RankingModelBundle(
        dataset_version=dataset_version,
        as_of_policy=as_of_policy,
        feature_encoder=encoder,
        estimator=estimator,
        softmax_beta=beta,
        best_iteration=best_iteration,
        hyperparameters=params,
        seed=seed,
        split_dates={
            **split_dates,
            **(
                {
                    "valid_start": str(split_bounds["valid"][0]),
                    "valid_end": str(split_bounds["valid"][1]),
                }
                if split_bounds is not None
                else {}
            ),
        },
        calibration_objective=calibration_objective,
        full_distribution=True,
        max_rank=max_rank,
        relevance_depth=relevance_depth,
        relevance_mode=relevance_mode,
        performance_estimator=performance_estimator,
        performance_weight=performance_weight,
        performance_scale=performance_scale,
        performance_best_iteration=performance_best_iteration,
    )
    predictions = bundle.predict(valid)
    scored = valid.join(
        predictions,
        on=["race_id", "race_entry_id", "horse_number"],
    )
    scored = with_topk_labels(scored, max_rank=max_rank)
    targets = ["win", *[f"top{rank}" for rank in range(2, max_rank + 1)]]
    target_metrics = {
        target: evaluate_probabilities(
            scored,
            f"prob_{target}",
            label_column=target,
        )
        for target in targets
        if f"prob_{target}" in scored.columns
    }
    ordered_nll = None
    ordered_topk_nll = None
    rps = None
    rank_nll = None
    if "prob_top3" in scored.columns:
        ordered_nll = plackett_luce_top3_nll(
            scored["rank_score"].to_numpy(),
            scored["race_id"].to_numpy(),
            _finish_positions(scored),
            beta=bundle.softmax_beta,
        )
        ordered_topk_nll = plackett_luce_topk_nll(
            scored["rank_score"].to_numpy(),
            scored["race_id"].to_numpy(),
            _finish_positions(scored),
            beta=bundle.softmax_beta,
            max_rank=max_rank,
        )
        rps = topk_ranked_probability_score(scored, max_rank=max_rank)
        rank_nll = actual_rank_bucket_nll(scored, max_rank=max_rank)
    return RankingTrainResult(
        bundle=bundle,
        valid_predictions=predictions,
        valid_metrics=target_metrics["win"],
        valid_target_metrics=target_metrics,
        ordered_top3_nll=ordered_nll,
        ordered_topk_nll=ordered_topk_nll,
        topk_rps=rps,
        actual_rank_nll=rank_nll,
    )


def save_ranking_bundle(bundle: RankingModelBundle, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(bundle, handle, protocol=pickle.HIGHEST_PROTOCOL)


def load_ranking_bundle(path: Path) -> RankingModelBundle:
    if not path.exists():
        raise ModelInputError(f"ranking artifact 없음: {path}")
    with path.open("rb") as handle:
        bundle = pickle.load(handle)  # noqa: S301 - trusted local experiment artifact
    if not isinstance(bundle, RankingModelBundle):
        raise ModelInputError(f"지원하지 않는 ranking artifact: {path}")
    return bundle


def render_ranking_report(
    bundle: RankingModelBundle,
    metrics: dict[str, float],
    *,
    run_id: str,
    target_metrics: dict[str, dict[str, float]] | None = None,
    ordered_top3_nll: float | None = None,
    ordered_topk_nll: float | None = None,
    topk_rps: float | None = None,
    actual_rank_nll: float | None = None,
) -> str:
    relevance_depth = int(getattr(bundle, "relevance_depth", 3))
    relevance_mode = getattr(bundle, "relevance_mode", RELEVANCE_FINISH_ORDER)
    if relevance_mode == RELEVANCE_MARGIN:
        relevance_text = "착차 기반 0~10 선형 gain (5마신마다 절반, 1~5착만 양수 가능)"
    else:
        relevance_text = (
            "1착=5, 2착=4, 3착=3, 4착=2, 5착=1, 6착 이하=0"
            if relevance_depth == 5
            else "1착=3, 2착=2, 3착=1, 4착 이하=0"
        )
    lines = [
        "# LightGBM LambdaRank 리포트",
        "",
        f"- run_id: `{run_id}`",
        f"- 데이터셋: `{bundle.dataset_version}` / `{bundle.as_of_policy}`",
        f"- feature: {len(bundle.feature_encoder.feature_names)}개",
        f"- seed: {bundle.seed}",
        f"- best iteration: {bundle.best_iteration}",
        f"- calibration softmax beta: {bundle.softmax_beta:.6f}",
        "- calibration objective: "
        f"`{getattr(bundle, 'calibration_objective', CALIBRATION_WINNER)}`",
        f"- relevance: {relevance_text}",
        f"- relevance mode: `{relevance_mode}`",
        "- margin performance auxiliary: "
        f"weight={getattr(bundle, 'performance_weight', 0.0):.3f}, "
        f"best iteration={getattr(bundle, 'performance_best_iteration', 0)}",
        "",
        "| log loss | brier | AUC | ECE | Top1 | Top3 |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {metrics['log_loss']:.4f} | {metrics['brier']:.4f} | "
        f"{metrics.get('auc', float('nan')):.4f} | {metrics['ece']:.4f} | "
        f"{metrics['top1_hit_rate']:.4f} | {metrics['top3_inclusion_rate']:.4f} |",
        "",
        "test split은 평가하지 않았다.",
        "",
    ]
    if target_metrics and len(target_metrics) > 1:
        lines.extend(
            [
                "## 일관된 순위 주변확률",
                "",
                "| target | log loss | brier | AUC | ECE |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for target in ("win", "top2", "top3", "top4", "top5"):
            target_values = target_metrics.get(target)
            if target_values is None:
                continue
            lines.append(
                f"| {target} | {target_values['log_loss']:.4f} | "
                f"{target_values['brier']:.4f} | "
                f"{target_values.get('auc', float('nan')):.4f} | "
                f"{target_values['ece']:.4f} |"
            )
        if ordered_top3_nll is not None:
            lines.extend(
                [
                    "",
                    f"- ordered top3 race NLL: {ordered_top3_nll:.6f}",
                ]
            )
        max_rank = int(getattr(bundle, "max_rank", 3))
        if max_rank > 3 and ordered_topk_nll is not None:
            lines.extend(
                [
                    f"- ordered top{max_rank} race NLL: {ordered_topk_nll:.6f}",
                    f"- top{max_rank} truncated RPS: {topk_rps:.6f}",
                    f"- actual rank bucket NLL (1..{max_rank},{max_rank + 1}+): "
                    f"{actual_rank_nll:.6f}",
                ]
            )
        lines.append("")
    return "\n".join(lines)
