"""RaceFit V1: scenario-conditioned utility correction over a base ranker."""

from __future__ import annotations

import pickle
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from scipy.optimize import minimize

from horse_racing.analysis.baselines import assign_split
from horse_racing.analysis.lightgbm_model import (
    ModelInputError,
    temporal_train_partitions,
    transform_features,
)
from horse_racing.analysis.metrics import evaluate_probabilities
from horse_racing.analysis.plackett_luce import (
    PROBABILITY_EPSILON,
    plackett_luce_marginals,
    valid_ordered_top3_indices,
)
from horse_racing.analysis.ranking_model import (
    RankingModelBundle,
    _finish_positions,
    train_ranking_model,
)

STATIC_SCENARIO_FEATURES = (
    "condition_state",
    "condition_weight_abs",
    "condition_uncertainty",
    "front_pressure_energy_fit",
    "closer_pressure_energy_fit",
    "gate_front_pressure",
    "load_distance_cost",
    "wet_finish_fit",
    "distance_energy_balance",
)
PACE_SENSITIVITY_FEATURES = (
    "pace_front_exposure",
    "pace_front_resilience",
    "pace_closing_kick",
    "pace_outer_front",
)
SCENARIO_SHIFTS = np.asarray([-1.0, 0.0, 1.0], dtype=float)


@dataclass(frozen=True)
class ScenarioFeatureEncoder:
    static_names: tuple[str, ...]
    pace_names: tuple[str, ...]
    static_means: np.ndarray
    static_scales: np.ndarray
    pace_means: np.ndarray
    pace_scales: np.ndarray


@dataclass
class RaceFitModelBundle:
    dataset_version: str
    as_of_policy: str
    base_bundle: RankingModelBundle
    scenario_encoder: ScenarioFeatureEncoder
    log_beta: float
    static_coefficients: np.ndarray
    pace_coefficients: np.ndarray
    objective_weights: tuple[float, float]
    l2_penalty: float
    calibration_metrics: dict[str, float]
    split_dates: dict[str, str]
    seed: int
    created_at_ms: int = field(default_factory=lambda: time.time_ns() // 1_000_000)

    def predict(self, frame: pl.DataFrame) -> pl.DataFrame:
        ordered = frame.sort("race_date_local", "race_id", "horse_number")
        base = self.base_bundle.predict(ordered)
        scenario = scenario_feature_matrix(ordered)
        static, pace = transform_scenario_features(scenario, self.scenario_encoder)
        score = base["rank_score"].to_numpy().astype(float)
        race_ids = ordered["race_id"].to_numpy()
        uncertainty = scenario["scenario_uncertainty"].to_numpy().astype(float)
        expected_utility = np.exp(self.log_beta) * score + static @ self.static_coefficients
        probabilities = _mixture_marginals(
            expected_utility,
            pace,
            self.pace_coefficients,
            race_ids,
            uncertainty,
        )
        return ordered.select("race_id", "race_entry_id", "horse_number").with_columns(
            *(pl.Series(name, values) for name, values in probabilities.items()),
            pl.Series("rank_score", score),
            pl.Series("racefit_score", expected_utility),
            pl.Series("scenario_uncertainty", uncertainty),
        )


@dataclass
class RaceFitTrainResult:
    bundle: RaceFitModelBundle
    valid_predictions: pl.DataFrame
    valid_target_metrics: dict[str, dict[str, float]]
    ordered_top3_nll: float

    @property
    def valid_metrics(self) -> dict[str, float]:
        return self.valid_target_metrics["win"]


def _values(frame: pl.DataFrame, name: str, *, default: float = 0.0) -> np.ndarray:
    if name not in frame.columns:
        return np.full(frame.height, default, dtype=float)
    return (
        frame[name]
        .cast(pl.Float64, strict=False)
        .fill_null(default)
        .fill_nan(default)
        .to_numpy()
        .astype(float)
    )


def scenario_feature_matrix(frame: pl.DataFrame) -> pl.DataFrame:
    """Build interpretable race-fit and pace-sensitivity interactions."""
    early_pct = np.clip(_values(frame, "early_pos_pct_avg5", default=0.5), 0.0, 1.0)
    frontness = 1.0 - early_pct
    closerness = early_pct
    starters = np.maximum(_values(frame, "starters", default=1.0), 2.0)
    front_rivals = np.clip(
        _values(frame, "front_rival_count") / np.maximum(starters - 1.0, 1.0),
        0.0,
        1.0,
    )
    front_share = np.clip(_values(frame, "front_runner_count") / starters, 0.0, 1.0)
    resilience = _values(frame, "energy_resilience_avg5")
    closing_kick = _values(frame, "energy_finish_change_avg5")
    energy_balance = _values(frame, "energy_early_late_balance_avg5")
    gate = np.clip(_values(frame, "horse_number_pct", default=0.5), 0.0, 1.0)
    distance = _values(frame, "distance_m", default=1200.0)
    distance_scaled = np.clip((distance - 1200.0) / 800.0, -1.0, 1.5)
    moisture = np.clip(
        _values(frame, "track_moisture_percent_planned") / 20.0,
        0.0,
        2.0,
    )
    load_rel = _values(frame, "carried_weight_rel")
    condition_state = _values(frame, "condition_state")
    condition_weight = np.abs(_values(frame, "condition_weight_z"))
    condition_uncertainty = np.clip(_values(frame, "condition_uncertainty", default=0.5), 0.0, 1.0)
    known_share = np.clip(_values(frame, "known_style_share", default=0.0), 0.0, 1.0)

    output = pl.DataFrame(
        {
            "condition_state": condition_state,
            "condition_weight_abs": condition_weight,
            "condition_uncertainty": condition_uncertainty,
            "front_pressure_energy_fit": frontness * front_rivals * resilience,
            "closer_pressure_energy_fit": closerness * front_share * closing_kick,
            "gate_front_pressure": frontness * gate * (0.5 + front_rivals),
            "load_distance_cost": load_rel * (distance / 1600.0),
            "wet_finish_fit": moisture * closing_kick,
            "distance_energy_balance": distance_scaled * energy_balance,
            "pace_front_exposure": frontness,
            "pace_front_resilience": frontness * resilience,
            "pace_closing_kick": closerness * closing_kick,
            "pace_outer_front": frontness * gate,
            "scenario_uncertainty": np.clip(
                0.10 + 0.55 * (1.0 - known_share) + 0.35 * condition_uncertainty,
                0.10,
                0.75,
            ),
        }
    )
    return output


def fit_scenario_encoder(features: pl.DataFrame) -> ScenarioFeatureEncoder:
    static = features.select(STATIC_SCENARIO_FEATURES).to_numpy().astype(float)
    pace = features.select(PACE_SENSITIVITY_FEATURES).to_numpy().astype(float)
    static_means = np.nanmean(static, axis=0)
    pace_means = np.nanmean(pace, axis=0)
    static_scales = np.nanstd(static, axis=0)
    pace_scales = np.nanstd(pace, axis=0)
    static_scales[static_scales < 1e-8] = 1.0
    pace_scales[pace_scales < 1e-8] = 1.0
    return ScenarioFeatureEncoder(
        static_names=STATIC_SCENARIO_FEATURES,
        pace_names=PACE_SENSITIVITY_FEATURES,
        static_means=static_means,
        static_scales=static_scales,
        pace_means=pace_means,
        pace_scales=pace_scales,
    )


def transform_scenario_features(
    features: pl.DataFrame,
    encoder: ScenarioFeatureEncoder,
) -> tuple[np.ndarray, np.ndarray]:
    static = features.select(encoder.static_names).to_numpy().astype(float)
    pace = features.select(encoder.pace_names).to_numpy().astype(float)
    static = np.nan_to_num((static - encoder.static_means) / encoder.static_scales)
    pace = np.nan_to_num((pace - encoder.pace_means) / encoder.pace_scales)
    return static, pace


def _race_locations(race_ids: np.ndarray) -> list[np.ndarray]:
    groups: dict[Any, list[int]] = {}
    for index, race_id in enumerate(np.asarray(race_ids)):
        key = race_id.item() if hasattr(race_id, "item") else race_id
        groups.setdefault(key, []).append(index)
    return [np.asarray(indices, dtype=int) for indices in groups.values()]


def _scenario_weights(uncertainty: float) -> np.ndarray:
    spread = float(np.clip(uncertainty, 0.0, 0.9))
    return np.asarray([spread / 2.0, 1.0 - spread, spread / 2.0])


def _order_probability(utility: np.ndarray, order: tuple[int, int, int]) -> float:
    logits = np.clip(np.asarray(utility, dtype=float), -50.0, 50.0)
    worth = np.exp(logits - logits.max())
    first, second, third = order
    mask_first = np.arange(len(worth)) != first
    mask_second = mask_first & (np.arange(len(worth)) != second)
    return float(
        worth[first]
        / worth.sum()
        * worth[second]
        / worth[mask_first].sum()
        * worth[third]
        / worth[mask_second].sum()
    )


def _winner_indices(positions: np.ndarray) -> list[int]:
    valid = [int(value) for value in positions if value is not None and int(value) > 0]
    if not valid:
        return []
    best = min(valid)
    return [index for index, value in enumerate(positions) if int(value) == best]


def _racefit_loss(
    parameters: np.ndarray,
    scores: np.ndarray,
    static: np.ndarray,
    pace: np.ndarray,
    race_ids: np.ndarray,
    finish_positions: np.ndarray,
    uncertainty: np.ndarray,
    *,
    ordered_weight: float,
    winner_weight: float,
    l2_penalty: float,
) -> float:
    beta = float(np.exp(parameters[0]))
    static_coefficients = parameters[1 : 1 + static.shape[1]]
    pace_coefficients = parameters[1 + static.shape[1] :]
    base_utility = beta * scores + static @ static_coefficients
    losses: list[float] = []
    for locations in _race_locations(race_ids):
        orders = valid_ordered_top3_indices(finish_positions[locations])
        winners = _winner_indices(finish_positions[locations])
        if not orders or not winners:
            continue
        weights = _scenario_weights(float(np.mean(uncertainty[locations])))
        ordered_probability = 0.0
        winner_probability = 0.0
        for scenario_weight, shift in zip(weights, SCENARIO_SHIFTS, strict=True):
            utility = base_utility[locations] + shift * (pace[locations] @ pace_coefficients)
            ordered_probability += scenario_weight * sum(
                _order_probability(utility, order) for order in orders
            )
            logits = np.clip(utility, -50.0, 50.0)
            worth = np.exp(logits - logits.max())
            winner_probability += scenario_weight * float(worth[winners].sum() / worth.sum())
        losses.append(
            ordered_weight * -np.log(max(ordered_probability, PROBABILITY_EPSILON))
            + winner_weight * -np.log(max(winner_probability, PROBABILITY_EPSILON))
        )
    if not losses:
        raise ValueError("RaceFit calibration에 유효한 착순 경주가 없습니다.")
    penalty = l2_penalty * float(np.sum(parameters[1:] ** 2))
    return float(np.mean(losses) + penalty)


def fit_scenario_calibrator(
    scores: np.ndarray,
    features: pl.DataFrame,
    race_ids: np.ndarray,
    finish_positions: np.ndarray,
    *,
    initial_beta: float,
    ordered_weight: float = 0.75,
    winner_weight: float = 0.25,
    l2_penalty: float = 0.03,
) -> tuple[ScenarioFeatureEncoder, np.ndarray, dict[str, float]]:
    if not np.isclose(ordered_weight + winner_weight, 1.0):
        raise ValueError("RaceFit objective weight 합은 1이어야 합니다.")
    encoder = fit_scenario_encoder(features)
    static, pace = transform_scenario_features(features, encoder)
    uncertainty = features["scenario_uncertainty"].to_numpy().astype(float)
    initial = np.zeros(1 + static.shape[1] + pace.shape[1], dtype=float)
    initial[0] = np.log(initial_beta)
    objective = lambda values: _racefit_loss(  # noqa: E731
        values,
        scores,
        static,
        pace,
        race_ids,
        finish_positions,
        uncertainty,
        ordered_weight=ordered_weight,
        winner_weight=winner_weight,
        l2_penalty=l2_penalty,
    )
    baseline_loss = objective(initial)
    bounds = [(-3.5, 3.5), *[(-2.5, 2.5)] * (len(initial) - 1)]
    scenario_start = initial.copy()
    scenario_start[-pace.shape[1] :] = 0.08
    candidates = [
        minimize(
            objective,
            start,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 240, "ftol": 1e-9, "maxls": 30},
        )
        for start in (initial, scenario_start)
    ]
    successful = [candidate for candidate in candidates if candidate.success]
    if not successful:
        messages = "; ".join(str(candidate.message) for candidate in candidates)
        raise ModelInputError(f"RaceFit scenario calibration 실패: {messages}")
    optimized = min(successful, key=lambda candidate: float(candidate.fun))
    metrics = {
        "baseline_objective": float(baseline_loss),
        "racefit_objective": float(optimized.fun),
        "objective_improvement": float(baseline_loss - optimized.fun),
        "iterations": float(optimized.nit),
    }
    return encoder, np.asarray(optimized.x, dtype=float), metrics


def _mixture_marginals(
    base_utility: np.ndarray,
    pace: np.ndarray,
    pace_coefficients: np.ndarray,
    race_ids: np.ndarray,
    uncertainty: np.ndarray,
) -> dict[str, np.ndarray]:
    output = {
        name: np.zeros(len(base_utility), dtype=float)
        for name in ("prob_win", "prob_second", "prob_third", "prob_top2", "prob_top3")
    }
    race_weights = np.zeros((3, len(base_utility)), dtype=float)
    for locations in _race_locations(race_ids):
        weights = _scenario_weights(float(np.mean(uncertainty[locations])))
        race_weights[:, locations] = weights[:, None]
    pace_effect = pace @ pace_coefficients
    for scenario_index, shift in enumerate(SCENARIO_SHIFTS):
        scenario = plackett_luce_marginals(
            base_utility + shift * pace_effect,
            race_ids,
            beta=1.0,
        )
        for name in output:
            output[name] += race_weights[scenario_index] * scenario[name]
    return output


def racefit_ordered_top3_nll(
    bundle: RaceFitModelBundle,
    frame: pl.DataFrame,
) -> float:
    ordered = frame.sort("race_date_local", "race_id", "horse_number")
    base = bundle.base_bundle.predict(ordered)
    features = scenario_feature_matrix(ordered)
    static, pace = transform_scenario_features(features, bundle.scenario_encoder)
    score = base["rank_score"].to_numpy().astype(float)
    race_ids = ordered["race_id"].to_numpy()
    positions = _finish_positions(ordered)
    uncertainty = features["scenario_uncertainty"].to_numpy().astype(float)
    parameters = np.concatenate(
        (
            [bundle.log_beta],
            bundle.static_coefficients,
            bundle.pace_coefficients,
        )
    )
    # Report the ordered component without winner weight or regularization.
    return _racefit_loss(
        parameters,
        score,
        static,
        pace,
        race_ids,
        positions,
        uncertainty,
        ordered_weight=1.0,
        winner_weight=0.0,
        l2_penalty=0.0,
    )


def train_racefit_model(
    frame: pl.DataFrame,
    *,
    feature_names: list[str],
    dataset_version: str,
    as_of_policy: str,
    seed: int = 42,
    hyperparameters: dict[str, Any] | None = None,
    split_bounds: Mapping[str, tuple[str | None, str | None]] | None = None,
    ordered_weight: float = 0.75,
    winner_weight: float = 0.25,
    l2_penalty: float = 0.03,
) -> RaceFitTrainResult:
    required_features = {
        "condition_state",
        "condition_uncertainty",
        "energy_resilience_avg5",
        "energy_finish_change_avg5",
        "energy_early_late_balance_avg5",
    }
    missing = sorted(required_features - set(frame.columns))
    if missing:
        raise ModelInputError(
            "RaceFit feature 없음: " + ", ".join(missing) + "; racefit feature_set 필요"
        )
    base_result = train_ranking_model(
        frame,
        feature_names=feature_names,
        dataset_version=dataset_version,
        as_of_policy=as_of_policy,
        seed=seed,
        hyperparameters=hyperparameters,
        split_bounds=split_bounds,
        calibration_objective="winner",
    )
    _, _, calibration, _ = temporal_train_partitions(frame, split_bounds=split_bounds)
    calibration = calibration.sort("race_date_local", "race_id", "horse_number")
    calibration_scores = np.asarray(
        base_result.bundle.estimator.predict(
            transform_features(calibration, base_result.bundle.feature_encoder)
        ),
        dtype=float,
    )
    scenario_features = scenario_feature_matrix(calibration)
    encoder, parameters, calibration_metrics = fit_scenario_calibrator(
        calibration_scores,
        scenario_features,
        calibration["race_id"].to_numpy(),
        _finish_positions(calibration),
        initial_beta=base_result.bundle.softmax_beta,
        ordered_weight=ordered_weight,
        winner_weight=winner_weight,
        l2_penalty=l2_penalty,
    )
    n_static = len(STATIC_SCENARIO_FEATURES)
    bundle = RaceFitModelBundle(
        dataset_version=dataset_version,
        as_of_policy=as_of_policy,
        base_bundle=base_result.bundle,
        scenario_encoder=encoder,
        log_beta=float(parameters[0]),
        static_coefficients=parameters[1 : 1 + n_static],
        pace_coefficients=parameters[1 + n_static :],
        objective_weights=(ordered_weight, winner_weight),
        l2_penalty=l2_penalty,
        calibration_metrics=calibration_metrics,
        split_dates=base_result.bundle.split_dates,
        seed=seed,
    )
    valid = (
        assign_split(frame, split_bounds=split_bounds)
        .filter(pl.col("split") == "valid")
        .drop("split")
        .sort("race_date_local", "race_id", "horse_number")
    )
    predictions = bundle.predict(valid)
    scored = valid.join(
        predictions,
        on=["race_id", "race_entry_id", "horse_number"],
    )
    target_metrics = {
        target: evaluate_probabilities(scored, f"prob_{target}", label_column=target)
        for target in ("win", "top2", "top3")
    }
    return RaceFitTrainResult(
        bundle=bundle,
        valid_predictions=predictions,
        valid_target_metrics=target_metrics,
        ordered_top3_nll=racefit_ordered_top3_nll(bundle, valid),
    )


def save_racefit_bundle(bundle: RaceFitModelBundle, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(bundle, handle, protocol=pickle.HIGHEST_PROTOCOL)


def load_racefit_bundle(path: Path) -> RaceFitModelBundle:
    if not path.exists():
        raise ModelInputError(f"RaceFit artifact 없음: {path}")
    with path.open("rb") as handle:
        bundle = pickle.load(handle)  # noqa: S301 - trusted local artifact
    if not isinstance(bundle, RaceFitModelBundle):
        raise ModelInputError(f"지원하지 않는 RaceFit artifact: {path}")
    return bundle


def render_racefit_report(result: RaceFitTrainResult, *, run_id: str) -> str:
    bundle = result.bundle
    lines = [
        "# RaceFit V1 시나리오 순위모델 리포트",
        "",
        f"- run_id: `{run_id}`",
        f"- 데이터셋: `{bundle.dataset_version}` / `{bundle.as_of_policy}`",
        f"- base feature: {len(bundle.base_bundle.feature_encoder.feature_names)}개",
        f"- best iteration: {bundle.base_bundle.best_iteration}",
        f"- scenario beta: {np.exp(bundle.log_beta):.6f}",
        f"- objective: ordered={bundle.objective_weights[0]:.2f}, "
        f"winner={bundle.objective_weights[1]:.2f}, L2={bundle.l2_penalty:.3f}",
        f"- calibration objective improvement: "
        f"{bundle.calibration_metrics['objective_improvement']:.6f}",
        f"- valid ordered-top3 NLL: {result.ordered_top3_nll:.6f}",
        "",
        "| target | log loss | brier | AUC | ECE |",
        "|---|---:|---:|---:|---:|",
    ]
    for target in ("win", "top2", "top3"):
        values = result.valid_target_metrics[target]
        lines.append(
            f"| {target} | {values['log_loss']:.4f} | {values['brier']:.4f} | "
            f"{values.get('auc', float('nan')):.4f} | {values['ece']:.4f} |"
        )
    lines.extend(
        [
            "",
            f"- Top1: {result.valid_metrics['top1_hit_rate']:.4%}",
            f"- 우승마 Top3 포함: {result.valid_metrics['top3_inclusion_rate']:.4%}",
            "- test split은 평가하지 않았다.",
            "",
        ]
    )
    return "\n".join(lines)
