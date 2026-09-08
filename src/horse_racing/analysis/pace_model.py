"""Leakage-safe first-stage pace prediction and scenario features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl

from horse_racing.analysis.lightgbm_model import (
    ModelInputError,
    TrainResult,
    fit_feature_encoder,
    train_lightgbm_models,
    transform_features,
)
from horse_racing.analysis.ranking_model import RankingModelBundle, RankingTrainResult

PACE_TARGET = "early_position_pct_target"
PACE_GATE_INPUT_FEATURES = [
    "pace_gate_pct",
    "pace_gate_center_distance",
    "pace_gate_outer_edge",
    "pace_gate_inner_edge",
    "pace_gate_short_outer",
    "pace_gate_front_outer",
    "pace_gate_closer_inner",
    "pace_gate_field_outer",
    "pace_gate_context_key",
]
PACE_FEATURES = [
    "pace_pred_early_pct",
    "pace_pred_early_rank_pct",
    "pace_pred_front_count",
    "pace_pred_front_rivals",
    "pace_pred_pressure",
    "pace_pred_early_advantage",
    "pace_pred_style_shift",
    "pace_pred_front_energy_fit",
    "pace_pred_closer_kick_fit",
    "pace_pred_outer_cost",
    "pace_pred_load_cost",
    "pace_pred_gate_early_effect",
    "pace_pred_gate_outer_break_cost",
    "pace_pred_gate_inner_closer_risk",
]

DEFAULT_PACE_PARAMS: dict[str, Any] = {
    "objective": "huber",
    "n_estimators": 180,
    "learning_rate": 0.04,
    "num_leaves": 25,
    "min_child_samples": 80,
    "subsample": 0.9,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "verbosity": -1,
    "n_jobs": -1,
}


@dataclass
class PaceRegressor:
    encoder: Any
    estimator: lgb.LGBMRegressor

    def predict(self, frame: pl.DataFrame) -> np.ndarray:
        return self._predict_frame(add_gate_aware_pace_inputs(frame))

    def predict_neutral_gate(self, frame: pl.DataFrame) -> np.ndarray:
        """Counterfactual S1F position at the middle gate for the same runner."""
        field_size = (
            pl.col("starters").cast(pl.Float64)
            if "starters" in frame.columns
            else pl.len().over("race_id").cast(pl.Float64)
        )
        neutral = frame.with_columns(
            pl.lit(0.5).alias("horse_number_pct"),
            ((field_size + 1.0) / 2.0).alias("horse_number"),
        )
        return self._predict_frame(add_gate_aware_pace_inputs(neutral))

    def _predict_frame(self, frame: pl.DataFrame) -> np.ndarray:
        values = np.asarray(
            self.estimator.predict(transform_features(frame, self.encoder)),
            dtype=float,
        )
        return np.clip(values, 0.0, 1.0)


@dataclass
class TwoStageFoldResult:
    outcome: TrainResult
    pace_valid_mae: float
    augmented_feature_names: list[str]


@dataclass
class PaceRankingBundle:
    pace_regressor: PaceRegressor
    outcome_bundle: RankingModelBundle
    augmented_feature_names: list[str]

    def predict(self, frame: pl.DataFrame) -> pl.DataFrame:
        augmented = add_pace_scenario_features(
            frame,
            self.pace_regressor.predict(frame),
            neutral_gate_predictions=self.pace_regressor.predict_neutral_gate(frame),
        )
        return self.outcome_bundle.predict(augmented)


@dataclass
class TwoStageRankingResult:
    bundle: PaceRankingBundle
    outcome: RankingTrainResult
    pace_valid_mae: float
    augmented_feature_names: list[str]


def fit_pace_regressor(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    seed: int,
    hyperparameters: dict[str, Any] | None = None,
) -> PaceRegressor:
    labeled = frame.filter(pl.col(PACE_TARGET).is_not_null())
    if labeled.height == 0:
        raise ModelInputError("초반 위치 보조 라벨이 없습니다.")
    labeled = add_gate_aware_pace_inputs(labeled)
    pace_feature_names = list(dict.fromkeys([*feature_names, *PACE_GATE_INPUT_FEATURES]))
    encoder = fit_feature_encoder(labeled, pace_feature_names)
    params = {**DEFAULT_PACE_PARAMS, **(hyperparameters or {}), "random_state": seed}
    estimator = lgb.LGBMRegressor(**params)
    estimator.fit(
        transform_features(labeled, encoder),
        labeled[PACE_TARGET].cast(pl.Float64).to_numpy(),
        categorical_feature=encoder.categorical_indices,
        callbacks=[lgb.log_evaluation(0)],
    )
    return PaceRegressor(encoder, estimator)


def add_gate_aware_pace_inputs(frame: pl.DataFrame) -> pl.DataFrame:
    """Add pre-race gate interactions used only by the first-stage pace model.

    Gate position is expressed relative to field size.  The interactions let a
    small pace model distinguish an outer front-runner in a short race from an
    inner closer in a large field without treating either gate as universally
    good or bad.
    """
    starters = (
        pl.col("starters").cast(pl.Float64).fill_null(10.0)
        if "starters" in frame.columns
        else pl.len().over("race_id").cast(pl.Float64)
    )
    relative_number = (
        pl.col("horse_number").cast(pl.Float64) / starters
        if "horse_number" in frame.columns
        else pl.lit(0.5)
    )
    gate = (
        pl.col("horse_number_pct").cast(pl.Float64).fill_null(relative_number)
        if "horse_number_pct" in frame.columns
        else relative_number
    ).fill_null(0.5).clip(0.0, 1.0)
    historical_early = (
        pl.col("early_pos_pct_avg5").cast(pl.Float64).fill_null(0.5)
        if "early_pos_pct_avg5" in frame.columns
        else pl.lit(0.5)
    )
    style_reliability = (
        (pl.col("section_coverage5").cast(pl.Float64) / 5.0).clip(0.0, 1.0)
        if "section_coverage5" in frame.columns
        else pl.lit(0.0)
    )
    distance = (
        pl.col("distance_m").cast(pl.Float64).fill_null(1400.0)
        if "distance_m" in frame.columns
        else pl.lit(1400.0)
    )
    short_factor = ((1600.0 - distance) / 600.0).clip(0.0, 1.0)
    field_density = ((starters - 6.0) / 8.0).clip(0.0, 1.0)
    outer_edge = ((gate - 0.5) * 2.0).clip(0.0, 1.0)
    inner_edge = ((0.5 - gate) * 2.0).clip(0.0, 1.0)
    frontness = (1.0 - historical_early) * style_reliability
    closerness = historical_early * style_reliability
    distance_band = (
        pl.when(distance <= 1200)
        .then(pl.lit("sprint"))
        .when(distance <= 1600)
        .then(pl.lit("mile"))
        .otherwise(pl.lit("route"))
    )
    field_band = (
        pl.when(starters <= 8)
        .then(pl.lit("small"))
        .when(starters <= 12)
        .then(pl.lit("medium"))
        .otherwise(pl.lit("large"))
    )
    gate_band = (
        pl.when(gate <= 1.0 / 3.0)
        .then(pl.lit("inner"))
        .when(gate <= 2.0 / 3.0)
        .then(pl.lit("middle"))
        .otherwise(pl.lit("outer"))
    )
    meet = (
        pl.col("meet_code").cast(pl.Utf8).fill_null("unknown")
        if "meet_code" in frame.columns
        else pl.col("meet").cast(pl.Utf8).fill_null("unknown")
        if "meet" in frame.columns
        else pl.lit("unknown")
    )
    return frame.with_columns(
        gate.alias("pace_gate_pct"),
        (gate - 0.5).abs().alias("pace_gate_center_distance"),
        outer_edge.alias("pace_gate_outer_edge"),
        inner_edge.alias("pace_gate_inner_edge"),
        (outer_edge * short_factor).alias("pace_gate_short_outer"),
        (outer_edge * short_factor * frontness).alias("pace_gate_front_outer"),
        (inner_edge * field_density * closerness).alias("pace_gate_closer_inner"),
        (outer_edge * field_density).alias("pace_gate_field_outer"),
        pl.concat_str(
            [
                meet,
                distance_band,
                field_band,
                gate_band,
            ],
            separator="_",
        ).alias("pace_gate_context_key"),
    )


def add_pace_scenario_features(
    frame: pl.DataFrame,
    predictions: np.ndarray,
    *,
    neutral_gate_predictions: np.ndarray | None = None,
) -> pl.DataFrame:
    if len(predictions) != frame.height:
        raise ValueError("전개 예측과 frame 길이가 다릅니다.")
    if neutral_gate_predictions is None:
        neutral_gate_predictions = predictions
    if len(neutral_gate_predictions) != frame.height:
        raise ValueError("중립 게이트 전개 예측과 frame 길이가 다릅니다.")
    result = frame.with_columns(
        pl.Series("pace_pred_early_pct", np.clip(predictions, 0.0, 1.0))
        ,
        pl.Series(
            "_pace_pred_neutral_gate_pct",
            np.clip(neutral_gate_predictions, 0.0, 1.0),
        ),
    )
    rank = pl.col("pace_pred_early_pct").rank("average").over("race_id")
    denominator = (pl.len().over("race_id") - 1).cast(pl.Float64)
    result = result.with_columns(
        pl.when(denominator > 0)
        .then((rank - 1.0) / denominator)
        .otherwise(0.0)
        .alias("pace_pred_early_rank_pct"),
        (pl.col("pace_pred_early_pct") <= 0.35)
        .cast(pl.Int64)
        .sum()
        .over("race_id")
        .alias("pace_pred_front_count"),
        (
            pl.col("pace_pred_early_pct").mean().over("race_id")
            - pl.col("pace_pred_early_pct")
        ).alias("pace_pred_early_advantage"),
    )
    is_front = (pl.col("pace_pred_early_pct") <= 0.35).cast(pl.Int64)
    result = result.with_columns(
        (pl.col("pace_pred_front_count") - is_front).alias("pace_pred_front_rivals"),
        (pl.col("pace_pred_front_count") / pl.len().over("race_id")).alias(
            "pace_pred_pressure"
        ),
    )
    historical_style = (
        pl.col("early_pos_pct_avg5").fill_null(0.5)
        if "early_pos_pct_avg5" in result.columns
        else pl.lit(0.5)
    )
    resilience = (
        pl.col("energy_resilience_avg5").fill_null(0.0)
        if "energy_resilience_avg5" in result.columns
        else pl.lit(0.0)
    )
    closing_kick = (
        pl.col("energy_finish_change_avg5").fill_null(0.0)
        if "energy_finish_change_avg5" in result.columns
        else pl.lit(0.0)
    )
    gate = (
        pl.col("horse_number_pct").fill_null(0.5)
        if "horse_number_pct" in result.columns
        else pl.lit(0.5)
    )
    load = (
        pl.col("carried_weight_rel").fill_null(0.0)
        if "carried_weight_rel" in result.columns
        else pl.lit(0.0)
    )
    distance = (
        pl.col("distance_m").fill_null(1200.0) / 1600.0
        if "distance_m" in result.columns
        else pl.lit(0.75)
    )
    frontness = 1.0 - pl.col("pace_pred_early_pct")
    closerness = pl.col("pace_pred_early_pct")
    pressure = pl.col("pace_pred_pressure")
    field_density = (
        ((pl.col("starters").cast(pl.Float64) - 6.0) / 8.0).clip(0.0, 1.0)
        if "starters" in result.columns
        else pl.lit(0.5)
    )
    gate_early_effect = pl.col("_pace_pred_neutral_gate_pct") - pl.col(
        "pace_pred_early_pct"
    )
    return result.with_columns(
        (pl.col("pace_pred_early_pct") - historical_style).alias("pace_pred_style_shift"),
        (frontness * pressure * resilience).alias("pace_pred_front_energy_fit"),
        (closerness * pressure * closing_kick).alias("pace_pred_closer_kick_fit"),
        (frontness * pressure * gate).alias("pace_pred_outer_cost"),
        (frontness * pressure * load * distance).alias("pace_pred_load_cost"),
        gate_early_effect.alias("pace_pred_gate_early_effect"),
        ((-gate_early_effect).clip(lower_bound=0.0) * frontness).alias(
            "pace_pred_gate_outer_break_cost"
        ),
        ((1.0 - gate) * closerness * pressure * field_density).alias(
            "pace_pred_gate_inner_closer_risk"
        ),
    ).drop("_pace_pred_neutral_gate_pct")


def _cross_fitted_train_pace(
    train: pl.DataFrame,
    *,
    feature_names: list[str],
    seed: int,
) -> pl.DataFrame:
    dates = sorted(train["race_date_local"].unique().to_list())
    if len(dates) < 12:
        raise ModelInputError("전개 교차예측에는 최소 12개 경주일이 필요합니다.")
    first_index = max(1, int(len(dates) * 0.50))
    second_index = max(first_index + 1, int(len(dates) * 0.75))
    boundaries = [first_index, second_index, len(dates)]
    blocks: list[pl.DataFrame] = []
    for block_index, (start, end) in enumerate(
        zip(boundaries[:-1], boundaries[1:], strict=True)
    ):
        history = train.filter(pl.col("race_date_local") < dates[start])
        target = train.filter(
            (pl.col("race_date_local") >= dates[start])
            & (pl.col("race_date_local") <= dates[end - 1])
        )
        model = fit_pace_regressor(
            history,
            feature_names=feature_names,
            seed=seed + block_index,
        )
        blocks.append(
            add_pace_scenario_features(
                target,
                model.predict(target),
                neutral_gate_predictions=model.predict_neutral_gate(target),
            )
        )
    return pl.concat(blocks, how="vertical").sort(
        "race_date_local", "race_id", "horse_number"
    )


def _cross_fitted_train_pace_v2(
    train: pl.DataFrame,
    *,
    feature_names: list[str],
    seed: int,
) -> pl.DataFrame:
    """Expanding predictions covering the final 70% of outer-train dates."""
    dates = sorted(train["race_date_local"].unique().to_list())
    if len(dates) < 16:
        raise ModelInputError("V2 전개 교차예측에는 최소 16개 경주일이 필요합니다.")
    fractions = (0.30, 0.50, 0.70, 0.85, 1.00)
    boundaries = [min(len(dates), max(1, int(len(dates) * value))) for value in fractions]
    boundaries[-1] = len(dates)
    blocks: list[pl.DataFrame] = []
    for block_index, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:], strict=True)):
        if end <= start:
            continue
        history = train.filter(pl.col("race_date_local") < dates[start])
        target = train.filter(
            (pl.col("race_date_local") >= dates[start])
            & (pl.col("race_date_local") <= dates[end - 1])
        )
        model = fit_pace_regressor(history, feature_names=feature_names, seed=seed + block_index)
        blocks.append(
            add_pace_scenario_features(
                target,
                model.predict(target),
                neutral_gate_predictions=model.predict_neutral_gate(target),
            )
        )
    if not blocks:
        raise ModelInputError("V2 전개 교차예측 block이 비어 있습니다.")
    return pl.concat(blocks, how="vertical").sort(
        "race_date_local", "race_id", "horse_number"
    )


def train_two_stage_fold(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    split_bounds: dict[str, tuple[str | None, str | None]],
    seed: int = 42,
) -> TwoStageFoldResult:
    if PACE_TARGET not in frame.columns:
        raise ModelInputError(f"보조 라벨 없음: {PACE_TARGET}")
    train_end = split_bounds["train"][1]
    valid_start, valid_end = split_bounds["valid"]
    if train_end is None or valid_start is None or valid_end is None:
        raise ModelInputError("2단계 fold 날짜 경계가 불완전합니다.")
    outer_train = frame.filter(pl.col("race_date_local") <= train_end)
    outer_valid = frame.filter(
        (pl.col("race_date_local") >= valid_start)
        & (pl.col("race_date_local") <= valid_end)
    )
    if min(outer_train.height, outer_valid.height) == 0:
        raise ModelInputError("2단계 train 또는 valid가 비어 있습니다.")

    cross_fitted = _cross_fitted_train_pace(
        outer_train,
        feature_names=feature_names,
        seed=seed,
    )
    final_pace = fit_pace_regressor(
        outer_train,
        feature_names=feature_names,
        seed=seed + 100,
    )
    valid_predictions = final_pace.predict(outer_valid)
    augmented_valid = add_pace_scenario_features(
        outer_valid,
        valid_predictions,
        neutral_gate_predictions=final_pace.predict_neutral_gate(outer_valid),
    )
    combined = pl.concat([cross_fitted, augmented_valid], how="vertical").sort(
        "race_date_local", "race_id", "horse_number"
    )
    augmented_names = [*feature_names, *PACE_FEATURES]
    outcome = train_lightgbm_models(
        combined,
        feature_names=augmented_names,
        dataset_version=dataset_version,
        as_of_policy=as_of_policy,
        seed=seed,
        calibration="sigmoid",
        target_labels=("win",),
        split_bounds=split_bounds,
    )
    known = outer_valid[PACE_TARGET].is_not_null().to_numpy()
    errors = np.abs(
        valid_predictions[known]
        - outer_valid.filter(pl.col(PACE_TARGET).is_not_null())[PACE_TARGET].to_numpy()
    )
    return TwoStageFoldResult(
        outcome=outcome,
        pace_valid_mae=float(errors.mean()),
        augmented_feature_names=augmented_names,
    )


def train_two_stage_ranking_fold(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    split_bounds: dict[str, tuple[str | None, str | None]],
    seed: int = 42,
) -> TwoStageRankingResult:
    """Cross-fit a pace model, then train LambdaRank on predicted pace only."""
    from horse_racing.analysis.ranking_model import train_ranking_model

    if PACE_TARGET not in frame.columns:
        raise ModelInputError(f"보조 라벨 없음: {PACE_TARGET}")
    train_end = split_bounds["train"][1]
    valid_start, valid_end = split_bounds["valid"]
    if train_end is None or valid_start is None or valid_end is None:
        raise ModelInputError("2단계 ranking fold 날짜 경계가 불완전합니다.")
    outer_train = frame.filter(pl.col("race_date_local") <= train_end)
    outer_valid = frame.filter(
        (pl.col("race_date_local") >= valid_start)
        & (pl.col("race_date_local") <= valid_end)
    )
    if min(outer_train.height, outer_valid.height) == 0:
        raise ModelInputError("2단계 ranking train 또는 valid가 비어 있습니다.")

    cross_fitted = _cross_fitted_train_pace_v2(
        outer_train,
        feature_names=feature_names,
        seed=seed,
    )
    final_pace = fit_pace_regressor(
        outer_train,
        feature_names=feature_names,
        seed=seed + 100,
    )
    valid_predictions = final_pace.predict(outer_valid)
    augmented_valid = add_pace_scenario_features(
        outer_valid,
        valid_predictions,
        neutral_gate_predictions=final_pace.predict_neutral_gate(outer_valid),
    )
    combined = pl.concat([cross_fitted, augmented_valid], how="vertical").sort(
        "race_date_local", "race_id", "horse_number"
    )
    augmented_names = [*feature_names, *PACE_FEATURES]
    outcome = train_ranking_model(
        combined,
        feature_names=augmented_names,
        dataset_version=dataset_version,
        as_of_policy=as_of_policy,
        seed=seed,
        split_bounds=split_bounds,
        calibration_objective="winner",
    )
    known = outer_valid[PACE_TARGET].is_not_null().to_numpy()
    errors = np.abs(
        valid_predictions[known]
        - outer_valid.filter(pl.col(PACE_TARGET).is_not_null())[PACE_TARGET].to_numpy()
    )
    return TwoStageRankingResult(
        bundle=PaceRankingBundle(
            pace_regressor=final_pace,
            outcome_bundle=outcome.bundle,
            augmented_feature_names=augmented_names,
        ),
        outcome=outcome,
        pace_valid_mae=float(errors.mean()),
        augmented_feature_names=augmented_names,
    )
