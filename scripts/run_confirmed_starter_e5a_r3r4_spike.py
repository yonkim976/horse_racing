#!/usr/bin/env python3
"""Run the bounded E5-A R3/R4 synthetic LightGBM validation."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl

from horse_racing.analysis.confirmed_starter_e3 import sha256_file
from horse_racing.analysis.confirmed_starter_e5 import fit_temperature as old_fit_temperature
from horse_racing.analysis.confirmed_starter_e5_r3r4 import (
    CallbackEvidence,
    E5R3R4ContractError,
    NativeBinaryObjective,
    NativeRaceSoftmaxObjective,
    NativeRawRaceMetric,
    diagnose_temperature,
    group_slices,
    grouped_softmax,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/experiments/confirmed_starter_e5a_r3_r4_20260912"
SEED = 42
MAX_ROUNDS = 20
PATIENCE = 3
FEATURES = ["signal", "noise", "field_size"]
FROZEN_PATHS = [
    ROOT / "data/experiments/confirmed_starter_e5a_20260912/artifact_manifest.json",
    ROOT / "docs/CONFIRMED_STARTER_E5A_2026-09-12.md",
    ROOT / "docs/CONFIRMED_STARTER_RACE_OBJECTIVE_PROTOCOL_V2_2026-09-12.md",
    ROOT / "src/horse_racing/analysis/confirmed_starter_e5.py",
    ROOT / "data/experiments/confirmed_starter_e4_diagnostic_20260911/artifact_manifest.json",
    ROOT / "data/experiments/model_runs.jsonl",
]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha_array(values: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()


def _frame() -> pl.DataFrame:
    rows = []
    rng = np.random.default_rng(SEED)
    entry_id = 1
    for race_index in range(40):
        size = 4 + race_index % 5
        winners = (1, 1, 2, 3)[race_index % 4]
        for horse_number in range(1, size + 1):
            rows.append(
                {
                    "race_id": race_index + 1,
                    "race_entry_id": entry_id,
                    "horse_number": horse_number,
                    "signal": (size - horse_number) / size,
                    "noise": float(rng.normal()),
                    "field_size": float(size),
                    "win": int(horse_number <= winners),
                    "split": "fit" if race_index < 30 else "tune",
                }
            )
            entry_id += 1
    return (
        pl.DataFrame(rows)
        .sample(fraction=1.0, shuffle=True, seed=SEED + 4)
        .with_row_index("source_order")
    )


def _arrays(frame: pl.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (
        frame.select(FEATURES).to_numpy(),
        frame["win"].to_numpy(),
        frame.group_by("race_id", maintain_order=True).len()["len"].to_numpy(),
    )


def _binary_weights(groups: np.ndarray) -> np.ndarray:
    return np.concatenate([np.full(int(size), 1.0 / int(size)) for size in groups])


def _params(objective: Any, *, rounds: int = MAX_ROUNDS) -> dict[str, Any]:
    del rounds
    return {
        "objective": objective,
        "metric": "None",
        "boost_from_average": False,
        "learning_rate": 0.1,
        "num_leaves": 7,
        "max_depth": 3,
        "min_data_in_leaf": 3,
        "min_sum_hessian_in_leaf": 1e-6,
        "feature_fraction": 1.0,
        "bagging_fraction": 1.0,
        "bagging_freq": 0,
        "lambda_l2": 0.0,
        "seed": SEED,
        "num_threads": 1,
        "verbosity": -1,
    }


def _independent_ce(logits: np.ndarray, winners: np.ndarray, groups: np.ndarray) -> float:
    losses = []
    for block in group_slices(groups, len(logits)):
        scores = logits[block] - np.max(logits[block])
        labels = winners[block].astype(np.float64)
        labels /= labels.sum()
        losses.append(float(np.logaddexp.reduce(scores) - np.dot(labels, scores)))
    return float(np.mean(losses))


def _train_selector(
    candidate: str,
    fit_x: np.ndarray,
    fit_y: np.ndarray,
    fit_groups: np.ndarray,
    tune_x: np.ndarray,
    tune_y: np.ndarray,
    tune_groups: np.ndarray,
) -> tuple[lgb.Booster, CallbackEvidence, dict[str, Any]]:
    evidence = CallbackEvidence()
    if candidate == "BINARY":
        objective = NativeBinaryObjective(evidence)
        fit_weights = _binary_weights(fit_groups)
        tune_weights = _binary_weights(tune_groups)
    else:
        objective = NativeRaceSoftmaxObjective(evidence)
        fit_weights = None
        tune_weights = None
    fit_dataset = lgb.Dataset(
        fit_x,
        label=fit_y,
        weight=fit_weights,
        group=fit_groups,
        feature_name=FEATURES,
        free_raw_data=False,
    )
    tune_dataset = lgb.Dataset(
        tune_x,
        label=tune_y,
        weight=tune_weights,
        group=tune_groups,
        feature_name=FEATURES,
        reference=fit_dataset,
        free_raw_data=False,
    )
    metric = NativeRawRaceMetric(evidence)
    booster = lgb.train(
        _params(objective),
        fit_dataset,
        num_boost_round=MAX_ROUNDS,
        valid_sets=[tune_dataset],
        valid_names=["tune"],
        feval=metric,
        keep_training_booster=True,
        callbacks=[
            lgb.early_stopping(PATIENCE, first_metric_only=True, verbose=False),
            lgb.log_evaluation(0),
        ],
    )
    if not evidence.objective_calls or not evidence.metric_calls:
        raise E5R3R4ContractError(f"{candidate}: callback evidence missing")
    if set(booster.best_score) != {"tune"} or set(booster.best_score["tune"]) != {
        "race_equal_soft_label_ce"
    }:
        raise E5R3R4ContractError(f"{candidate}: unintended metric entered stopping")
    fit_group_hash = _sha_array(fit_groups.astype(np.int32))
    tune_group_hash = _sha_array(tune_groups.astype(np.int32))
    fit_label_hash = _sha_array(fit_y.astype(np.float32))
    tune_label_hash = _sha_array(tune_y.astype(np.float32))
    if any(
        call["groups"]["sha256"] != fit_group_hash or call["labels"]["sha256"] != fit_label_hash
        for call in evidence.objective_calls
    ):
        raise E5R3R4ContractError(f"{candidate}: objective partition/group/label mixed")
    if any(
        call["groups"]["sha256"] != tune_group_hash or call["labels"]["sha256"] != tune_label_hash
        for call in evidence.metric_calls
    ):
        raise E5R3R4ContractError(f"{candidate}: metric partition/group/label mixed")
    if candidate == "BINARY":
        expected_weight_hash = _sha_array(_binary_weights(fit_groups).astype(np.float32))
        if any(
            call["weights"]["sha256"] != expected_weight_hash for call in evidence.objective_calls
        ):
            raise E5R3R4ContractError("BINARY: objective weight buffer changed")
    elif any(call["weights"] is not None for call in evidence.objective_calls):
        raise E5R3R4ContractError("RACE_SOFTMAX: expected actual weight=None policy")
    per_iteration = []
    for iteration, call in enumerate(evidence.metric_calls, start=1):
        raw = np.asarray(booster.predict(tune_x, raw_score=True, num_iteration=iteration))
        expected = _independent_ce(raw, tune_y, tune_groups)
        hash_match = _sha_array(raw) == call["raw_margins"]["sha256"]
        error = abs(expected - call["metric"])
        if not hash_match or error > 1e-12:
            raise E5R3R4ContractError(f"{candidate}: iteration {iteration} metric mismatch")
        per_iteration.append(
            {
                "iteration": iteration,
                "raw_margin_hash_match": hash_match,
                "callback_metric": call["metric"],
                "independent_metric": expected,
                "absolute_error": error,
            }
        )
    return (
        booster,
        evidence,
        {
            "per_iteration": per_iteration,
            "best_iteration": booster.best_iteration,
            "current_iteration": booster.current_iteration(),
            "best_score": booster.best_score,
            "only_primary_metric": True,
        },
    )


def _refit(
    candidate: str,
    matrix: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
    iterations: int,
) -> lgb.Booster:
    evidence = CallbackEvidence()
    objective = (
        NativeBinaryObjective(evidence)
        if candidate == "BINARY"
        else NativeRaceSoftmaxObjective(evidence)
    )
    weights = _binary_weights(groups) if candidate == "BINARY" else None
    dataset = lgb.Dataset(
        matrix,
        label=labels,
        weight=weights,
        group=groups,
        feature_name=FEATURES,
        free_raw_data=False,
    )
    return lgb.train(
        _params(objective),
        dataset,
        num_boost_round=iterations,
        keep_training_booster=True,
        callbacks=[lgb.log_evaluation(0)],
    )


def _extreme_callback_case(initial_scores: list[float]) -> dict[str, Any]:
    matrix = np.array([[0.0], [1.0]])
    labels = np.array([1, 0])
    groups = np.array([2])
    weights = np.array([0.5, 0.5])
    evidence = CallbackEvidence()
    objective = NativeBinaryObjective(evidence)
    train = lgb.Dataset(matrix, label=labels, weight=weights, group=groups)
    valid = lgb.Dataset(
        matrix,
        label=labels,
        weight=weights,
        group=groups,
        init_score=np.asarray(initial_scores),
        reference=train,
    )
    lgb.train(
        {
            **_params(objective),
            "learning_rate": 1e-12,
            "min_data_in_leaf": 1,
            "feature_pre_filter": False,
            "lambda_l2": 1e20,
        },
        train,
        num_boost_round=1,
        valid_sets=[valid],
        valid_names=["extreme"],
        feval=NativeRawRaceMetric(evidence),
        callbacks=[lgb.log_evaluation(0)],
    )
    call = evidence.metric_calls[0]
    observed = np.asarray(call["raw_margins"]["head"], dtype=float)
    expected = _independent_ce(observed, labels, groups)
    return {
        "requested_init_score": initial_scores,
        "callback_raw_margin": observed.tolist(),
        "callback_metric": call["metric"],
        "independent_metric": expected,
        "absolute_error": abs(call["metric"] - expected),
        "matches": abs(call["metric"] - expected) <= 1e-12,
    }


def _temperature_evidence() -> dict[str, Any]:
    cases = {
        "upper_counterexample": (np.array([0.0, 0.01]), np.array([1, 0]), np.array([2])),
        "lower_counterexample": (np.array([0.0, 1.0]), np.array([0, 1]), np.array([2])),
        "true_flat": (np.array([3.0, 3.0]), np.array([1, 0]), np.array([2])),
        "perfect_separation_rounding": (
            np.array([0.0, 1000.0]),
            np.array([0, 1]),
            np.array([2]),
        ),
        "known_interior": (
            np.tile(np.array([1.0, 0.0]), 3),
            np.array([1, 0, 1, 0, 0, 1]),
            np.array([2, 2, 2]),
        ),
    }
    before = {}
    after = {}
    for name, (logits, labels, groups) in cases.items():
        try:
            old = old_fit_temperature(logits, labels, groups)
            before[name] = {
                "status": old.status,
                "log_temperature": old.log_temperature,
                "temperature": old.temperature,
                "objective": old.objective,
            }
        except Exception as exc:  # noqa: BLE001 - capturing sealed counterexample behavior
            before[name] = {"raised": type(exc).__name__, "message": str(exc)}
        after[name] = diagnose_temperature(logits, labels, groups).to_dict()
    return {
        "beta_parameterization": "beta=1/T; convex equal-race soft-label CE",
        "before": before,
        "after": after,
        "known_interior_expected_temperature": 1.0 / math.log(2.0),
        "approximate_flat_allowed": False,
    }


def main() -> int:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite R3/R4 output: {OUTPUT}")
    frozen_before = {str(path.relative_to(ROOT)): sha256_file(path) for path in FROZEN_PATHS}
    OUTPUT.mkdir(parents=True)
    frame = _frame()
    fit = frame.filter(pl.col("split") == "fit").sort("race_id", "race_entry_id")
    tune = frame.filter(pl.col("split") == "tune").sort("race_id", "race_entry_id")
    source_tune = frame.filter(pl.col("split") == "tune").select(
        "source_order", "race_id", "race_entry_id", "horse_number"
    )
    fit_x, fit_y, fit_groups = _arrays(fit)
    tune_x, tune_y, tune_groups = _arrays(tune)
    combined = pl.concat([fit, tune]).sort("race_id", "race_entry_id")
    combined_x, combined_y, combined_groups = _arrays(combined)
    candidates = {}
    predictions = []
    for candidate in ("BINARY", "RACE_SOFTMAX"):
        selector, evidence, checks = _train_selector(
            candidate, fit_x, fit_y, fit_groups, tune_x, tune_y, tune_groups
        )
        refit = _refit(
            candidate,
            combined_x,
            combined_y,
            combined_groups,
            checks["best_iteration"],
        )
        model_path = OUTPUT / f"{candidate.lower()}_refit_model.txt"
        refit.save_model(model_path)
        raw = np.asarray(refit.predict(tune_x, raw_score=True))
        probability = grouped_softmax(raw, tune_groups)
        reloaded = lgb.Booster(model_file=str(model_path))
        reload_raw = np.asarray(reloaded.predict(tune_x, raw_score=True))
        reload_probability = grouped_softmax(reload_raw, tune_groups)
        raw_error = float(np.max(np.abs(raw - reload_raw)))
        probability_error = float(np.max(np.abs(probability - reload_probability)))
        keyed = tune.select("race_id", "race_entry_id", "horse_number").with_columns(
            pl.lit(candidate).alias("candidate"),
            pl.Series("raw_margin", raw),
            pl.Series("prob_win", probability),
        )
        restored = (
            source_tune.join(
                keyed,
                on=["race_id", "race_entry_id", "horse_number"],
                validate="1:1",
            )
            .sort("source_order")
            .drop("source_order")
        )
        predictions.append(restored)
        candidates[candidate] = {
            **checks,
            "objective_callback_calls": len(evidence.objective_calls),
            "metric_callback_calls": len(evidence.metric_calls),
            "callback_matches_raw_margin": all(
                item["raw_margin_hash_match"] for item in checks["per_iteration"]
            ),
            "weight_policy": "1/field_size" if candidate == "BINARY" else "weight=None",
            "boost_from_average": False,
            "objective_first": evidence.objective_calls[0],
            "metric_first": evidence.metric_calls[0],
            "reload_raw_max_abs_error": raw_error,
            "reload_probability_max_abs_error": probability_error,
            "model_sha256": sha256_file(model_path),
        }
    prediction_path = OUTPUT / "synthetic_predictions.parquet"
    pl.concat(predictions).write_parquet(prediction_path)
    extremes = {
        "positive_40_41": _extreme_callback_case([40.0, 41.0]),
        "negative_40_41": _extreme_callback_case([-40.0, -41.0]),
    }
    if not all(value["matches"] for value in extremes.values()):
        raise E5R3R4ContractError("extreme raw-margin callback check failed")
    temperature = _temperature_evidence()
    _write_json(OUTPUT / "temperature_evidence.json", temperature)
    frozen_after = {str(path.relative_to(ROOT)): sha256_file(path) for path in FROZEN_PATHS}
    if frozen_before != frozen_after:
        raise E5R3R4ContractError("frozen E5-A or operating input changed")
    callback = {
        "study": "E5-A R3/R4 bounded synthetic raw-margin API spike",
        "actual_horse_data_used": False,
        "public_api": "lightgbm.train + Dataset(group=...) + two custom objectives",
        "synthetic_rows": frame.height,
        "synthetic_races": frame["race_id"].n_unique(),
        "max_rounds": MAX_ROUNDS,
        "toy_settings": True,
        "candidates": candidates,
        "extreme_raw_margin_checks": extremes,
        "source_order_restored": True,
        "prediction_sha256": sha256_file(prediction_path),
        "frozen_hashes_before": frozen_before,
        "frozen_hashes_after": frozen_after,
        "frozen_hashes_unchanged": True,
        "actual_horse_tree_training_count": 0,
        "post_2026_05_31_actual_rows_accessed": False,
        "operating_registry_modified": False,
    }
    _write_json(OUTPUT / "callback_evidence.json", callback)
    bundle = {
        "interface": "Booster.predict(raw_score=True) -> grouped stable softmax",
        "models": {
            candidate: {
                "path": f"{candidate.lower()}_refit_model.txt",
                "sha256": candidates[candidate]["model_sha256"],
                "best_iteration": candidates[candidate]["best_iteration"],
            }
            for candidate in candidates
        },
        "predictions": {
            "path": "synthetic_predictions.parquet",
            "sha256": sha256_file(prediction_path),
        },
        "reload_exact": all(
            values["reload_raw_max_abs_error"] == 0.0
            and values["reload_probability_max_abs_error"] == 0.0
            for values in candidates.values()
        ),
    }
    _write_json(OUTPUT / "synthetic_bundle.json", bundle)
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
