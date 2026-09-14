#!/usr/bin/env python3
"""Run the bounded synthetic LightGBM API spike for confirmed-starter E5-A."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl

from horse_racing.analysis.confirmed_starter_e3 import sha256_file
from horse_racing.analysis.confirmed_starter_e5 import (
    HESSIAN_FLOOR,
    CallbackEvidence,
    E5ContractError,
    NativeRaceMetric,
    NativeRaceSoftmaxObjective,
    group_slices,
    grouped_softmax,
    json_sha256,
    soft_labels_from_winners,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/experiments/confirmed_starter_e5a_20260912"
SEED = 42
MAX_ROUNDS = 20
EARLY_STOPPING_PATIENCE = 3
FEATURE_NAMES = ["signal", "noise", "field_size"]
FROZEN_PATHS = [
    ROOT
    / "data/datasets/confirmed_starter_e2_h1_remediation_retrospective"
    / "start_minus_30m/dataset.parquet",
    ROOT
    / "data/datasets/confirmed_starter_e2_h1_remediation_retrospective"
    / "start_minus_30m/manifest.json",
    ROOT / "data/experiments/confirmed_starter_e3_20260911/protocol.json",
    ROOT / "data/experiments/confirmed_starter_e3_20260911/comparison.json",
    ROOT / "data/experiments/confirmed_starter_e4_diagnostic_20260911/artifact_manifest.json",
    ROOT / "data/experiments/confirmed_starter_e4_diagnostic_20260911/diagnostic.json",
    ROOT / "src/horse_racing/analysis/confirmed_starter_e4.py",
    ROOT / "data/experiments/model_runs.jsonl",
]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _synthetic_frame() -> pl.DataFrame:
    """Build 40 ordered races with single, two-way, and three-way dead heats."""
    rows: list[dict[str, Any]] = []
    rng = np.random.default_rng(SEED)
    entry_id = 1
    for race_index in range(40):
        field_size = 4 + race_index % 5
        winner_count = (1, 1, 2, 3)[race_index % 4]
        winner_numbers = set(range(1, winner_count + 1))
        for horse_number in range(1, field_size + 1):
            rows.append(
                {
                    "race_id": race_index + 1,
                    "race_entry_id": entry_id,
                    "horse_number": horse_number,
                    "signal": float(field_size - horse_number) / field_size,
                    "noise": float(rng.normal()),
                    "field_size": float(field_size),
                    "win": int(horse_number in winner_numbers),
                    "split": "fit" if race_index < 30 else "tune",
                }
            )
            entry_id += 1
    return (
        pl.DataFrame(rows)
        .sample(fraction=1.0, shuffle=True, seed=SEED + 1)
        .with_row_index("original_row_index")
    )


def _arrays(frame: pl.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    matrix = frame.select(FEATURE_NAMES).to_numpy()
    labels = frame["win"].to_numpy()
    groups = frame.group_by("race_id", maintain_order=True).len()["len"].to_numpy()
    race_weights = np.concatenate(
        [np.full(int(size), 1.0 / int(size), dtype=np.float64) for size in groups]
    )
    return matrix, labels, groups, race_weights


def _toy_softmax_weights(groups: np.ndarray) -> np.ndarray:
    """Use visible race-constant weights only to prove Dataset buffer delivery."""
    return np.concatenate(
        [
            np.full(int(size), 1.0 + 0.25 * (index % 2), dtype=np.float64)
            for index, size in enumerate(groups)
        ]
    )


def _params(objective: Any) -> dict[str, Any]:
    return {
        "objective": objective,
        "metric": "None",
        "learning_rate": 0.1,
        "num_leaves": 7,
        "max_depth": 3,
        "min_data_in_leaf": 3,
        "min_sum_hessian_in_leaf": 1e-6,
        "feature_fraction": 1.0,
        "bagging_fraction": 1.0,
        "bagging_freq": 0,
        "lambda_l2": 0.0,
        "verbosity": -1,
        "seed": SEED,
        "num_threads": 1,
    }


def _predict_interface(
    booster: lgb.Booster, matrix: np.ndarray, groups: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    raw = np.asarray(
        booster.predict(matrix, raw_score=True, num_iteration=booster.current_iteration()),
        dtype=np.float64,
    )
    return raw, grouped_softmax(raw, groups)


def _max_error(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.max(np.abs(np.asarray(left) - np.asarray(right))))


def main() -> int:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite E5-A output: {OUTPUT}")
    frozen_before = {str(path.relative_to(ROOT)): sha256_file(path) for path in FROZEN_PATHS}
    OUTPUT.mkdir(parents=True)
    frame = _synthetic_frame()
    fit = frame.filter(pl.col("split") == "fit").sort("race_id", "race_entry_id")
    tune = frame.filter(pl.col("split") == "tune").sort("race_id", "race_entry_id")
    original_tune_keys = frame.filter(pl.col("split") == "tune").select(
        "original_row_index", "race_id", "race_entry_id", "horse_number"
    )
    fit_x, fit_y, fit_groups, binary_fit_weights = _arrays(fit)
    tune_x, tune_y, tune_groups, binary_tune_weights = _arrays(tune)
    if fit.height + tune.height < 200:
        raise E5ContractError("synthetic spike must contain a few hundred rows")
    q_fit = soft_labels_from_winners(fit_y, fit_groups)
    q_tune = soft_labels_from_winners(tune_y, tune_groups)

    common_dataset_args = {"feature_name": FEATURE_NAMES, "free_raw_data": False}
    binary_fit = lgb.Dataset(
        fit_x,
        label=fit_y,
        weight=binary_fit_weights,
        group=fit_groups,
        **common_dataset_args,
    )
    binary_tune = lgb.Dataset(
        tune_x,
        label=tune_y,
        weight=binary_tune_weights,
        group=tune_groups,
        reference=binary_fit,
        **common_dataset_args,
    )
    binary_evidence = CallbackEvidence()
    binary_metric = NativeRaceMetric(binary_evidence, prediction_semantics="binary_probability")
    binary_booster = lgb.train(
        _params("binary"),
        binary_fit,
        num_boost_round=MAX_ROUNDS,
        valid_sets=[binary_tune],
        valid_names=["tune"],
        feval=binary_metric,
        callbacks=[
            lgb.early_stopping(EARLY_STOPPING_PATIENCE, first_metric_only=True, verbose=False),
            lgb.log_evaluation(0),
        ],
    )

    softmax_evidence = CallbackEvidence()
    softmax_objective = NativeRaceSoftmaxObjective(softmax_evidence, hessian_floor=HESSIAN_FLOOR)
    softmax_metric = NativeRaceMetric(softmax_evidence, prediction_semantics="raw_margin")
    softmax_fit_weights = _toy_softmax_weights(fit_groups)
    softmax_tune_weights = _toy_softmax_weights(tune_groups)
    softmax_fit = lgb.Dataset(
        fit_x,
        label=fit_y,
        weight=softmax_fit_weights,
        group=fit_groups,
        **common_dataset_args,
    )
    softmax_tune = lgb.Dataset(
        tune_x,
        label=tune_y,
        weight=softmax_tune_weights,
        group=tune_groups,
        reference=softmax_fit,
        **common_dataset_args,
    )
    softmax_booster = lgb.train(
        _params(softmax_objective),
        softmax_fit,
        num_boost_round=MAX_ROUNDS,
        valid_sets=[softmax_tune],
        valid_names=["tune"],
        feval=softmax_metric,
        callbacks=[
            lgb.early_stopping(EARLY_STOPPING_PATIENCE, first_metric_only=True, verbose=False),
            lgb.log_evaluation(0),
        ],
    )
    if not softmax_evidence.objective_calls:
        raise E5ContractError("RACE_SOFTMAX objective callback was not observed")
    if softmax_evidence.objective_calls[0]["group_values"] != fit_groups.tolist():
        raise E5ContractError("RACE_SOFTMAX objective did not receive fit groups")
    if softmax_evidence.evaluation_calls[0]["groups"]["head"] != tune_groups.tolist():
        raise E5ContractError("RACE_SOFTMAX metric did not receive tune groups")
    if binary_evidence.evaluation_calls[0]["groups"]["head"] != tune_groups.tolist():
        raise E5ContractError("BINARY metric did not receive tune groups")

    candidates = {
        "BINARY": (binary_booster, binary_evidence, binary_tune, binary_tune_weights),
        "RACE_SOFTMAX": (
            softmax_booster,
            softmax_evidence,
            softmax_tune,
            softmax_tune_weights,
        ),
    }
    results: dict[str, Any] = {}
    prediction_frames = []
    for candidate, (booster, evidence, dataset, expected_weights) in candidates.items():
        model_path = OUTPUT / f"{candidate.lower()}_model.txt"
        booster.save_model(model_path)
        raw, probabilities = _predict_interface(booster, tune_x, tune_groups)
        reloaded = lgb.Booster(model_file=str(model_path))
        reload_raw, reload_probabilities = _predict_interface(reloaded, tune_x, tune_groups)
        reload_raw_error = _max_error(raw, reload_raw)
        reload_probability_error = _max_error(probabilities, reload_probabilities)
        if reload_raw_error != 0.0 or reload_probability_error != 0.0:
            raise E5ContractError(f"{candidate}: reload mismatch")
        sums = [
            float(probabilities[block].sum()) for block in group_slices(tune_groups, tune.height)
        ]
        if max(abs(value - 1.0) for value in sums) > 1e-12:
            raise E5ContractError(f"{candidate}: race probability sum mismatch")
        callback_first_values = evidence.evaluation_calls[0]["callback_predictions"]
        normal_prediction = np.asarray(booster.predict(tune_x, raw_score=False, num_iteration=1))
        raw_prediction = np.asarray(booster.predict(tune_x, raw_score=True, num_iteration=1))
        # Round one is retained even when early stopping rolls the returned Booster back.
        callback_hash = callback_first_values["sha256"]
        normal_hash = hashlib.sha256(np.ascontiguousarray(normal_prediction).tobytes()).hexdigest()
        raw_hash = hashlib.sha256(np.ascontiguousarray(raw_prediction).tobytes()).hexdigest()
        expected_semantics = (
            callback_hash == normal_hash if candidate == "BINARY" else callback_hash == raw_hash
        )
        if not expected_semantics:
            raise E5ContractError(f"{candidate}: callback prediction semantics mismatch")
        dataset.construct()
        observed_groups = dataset.get_group()
        observed_labels = dataset.get_label()
        observed_weights = dataset.get_weight()
        if not np.array_equal(observed_groups, tune_groups):
            raise E5ContractError(f"{candidate}: tune group buffer mismatch")
        if not np.array_equal(observed_labels, tune_y.astype(observed_labels.dtype)):
            raise E5ContractError(f"{candidate}: tune label buffer mismatch")
        if _max_error(observed_weights, expected_weights) > 1e-7:
            raise E5ContractError(f"{candidate}: tune weight buffer mismatch")
        best_scores = booster.best_score
        if set(best_scores) != {"tune"} or set(best_scores["tune"]) != {"race_equal_soft_label_ce"}:
            raise E5ContractError(f"{candidate}: unexpected early-stopping metrics {best_scores}")
        results[candidate] = {
            "public_training_api": "lightgbm.train",
            "objective": "built-in binary" if candidate == "BINARY" else "custom callable",
            "fit_rows": fit.height,
            "fit_groups": fit_groups.tolist(),
            "tune_rows": tune.height,
            "tune_groups": tune_groups.tolist(),
            "best_iteration": booster.best_iteration,
            "current_iteration": booster.current_iteration(),
            "best_score": best_scores,
            "default_metric_disabled": True,
            "first_metric_only": True,
            "callback_evidence": evidence.compact(),
            "round_one_callback_matches_normal_prediction_hash": callback_hash == normal_hash,
            "round_one_callback_matches_raw_prediction_hash": callback_hash == raw_hash,
            "buffer": {
                "label_dtype": str(observed_labels.dtype),
                "label_unique": np.unique(observed_labels).tolist(),
                "weight_dtype": str(observed_weights.dtype),
                "weight_unique": np.unique(observed_weights).tolist(),
                "group_dtype": str(observed_groups.dtype),
                "group_values": observed_groups.tolist(),
                "group_sum": int(observed_groups.sum()),
            },
            "reload": {
                "raw_margin_max_abs_error": reload_raw_error,
                "probability_max_abs_error": reload_probability_error,
            },
            "probability_max_race_sum_error": max(abs(value - 1.0) for value in sums),
            "model_sha256": sha256_file(model_path),
        }
        keyed_prediction = tune.select("race_id", "race_entry_id", "horse_number").with_columns(
            pl.lit(candidate).alias("candidate"),
            pl.Series("raw_margin", raw),
            pl.Series("prob_win", probabilities),
        )
        restored_prediction = (
            original_tune_keys.join(
                keyed_prediction,
                on=["race_id", "race_entry_id", "horse_number"],
                how="left",
                validate="1:1",
            )
            .sort("original_row_index")
            .drop("original_row_index")
        )
        expected_restored_keys = original_tune_keys.sort("original_row_index").select(
            "race_id", "race_entry_id", "horse_number"
        )
        if not restored_prediction.select("race_id", "race_entry_id", "horse_number").equals(
            expected_restored_keys
        ):
            raise E5ContractError(f"{candidate}: original key order was not restored")
        prediction_frames.append(restored_prediction)

    pl.concat(prediction_frames, how="vertical").write_parquet(
        OUTPUT / "synthetic_predictions.parquet"
    )
    q_thirds = q_fit[np.isclose(q_fit, 1.0 / 3.0)]
    if q_thirds.size == 0 or not np.equal(q_thirds, q_thirds[0]).all():
        raise E5ContractError("three-way dead-heat q evidence missing")
    frozen_after = {str(path.relative_to(ROOT)): sha256_file(path) for path in FROZEN_PATHS}
    if frozen_before != frozen_after:
        raise E5ContractError("frozen source or artifact changed during spike")
    evidence = {
        "study": "confirmed-starter E5-A bounded synthetic public-API spike",
        "actual_horse_data_used": False,
        "synthetic": {
            "rows": frame.height,
            "races": frame["race_id"].n_unique(),
            "fit_rows": fit.height,
            "fit_races": fit["race_id"].n_unique(),
            "tune_rows": tune.height,
            "tune_races": tune["race_id"].n_unique(),
            "field_sizes": sorted(frame["field_size"].unique().to_list()),
            "winner_counts": sorted(
                frame.group_by("race_id").agg(pl.col("win").sum())["win"].unique().to_list()
            ),
            "negative_label_rows": int((frame["win"] == 0).sum()),
            "original_shuffled_key_sha256": json_sha256(
                frame.sort("original_row_index").select("race_id", "race_entry_id").rows()
            ),
            "group_sorted_key_sha256": json_sha256(
                pl.concat([fit, tune]).select("race_id", "race_entry_id").rows()
            ),
        },
        "label_policy": {
            "dataset_buffer": "original 0/1 official-winner indicator",
            "callback_reconstruction": "float64 winner indicator divided by winner count per race",
            "q_one_third_repr": repr(float(q_thirds[0])),
            "q_fit_group_sums": [
                float(q_fit[block].sum()) for block in group_slices(fit_groups, q_fit.size)
            ],
            "q_tune_dtype": str(q_tune.dtype),
        },
        "candidates": results,
        "hessian": {
            "full": "diag(p)-p p.T retained by math function for verification",
            "trainer": "max(p*(1-p), 1e-6) diagonal approximation",
            "floor": HESSIAN_FLOOR,
        },
        "toy_weight_policy": {
            "purpose": "prove non-null weight buffer delivery",
            "RACE_SOFTMAX": "race-constant 1.0/1.25 alternating; not the real-study policy",
            "BINARY": "1/field_size to exercise race-equal row-weight delivery",
        },
        "row_order": {
            "input": "synthetic source shuffled, then sorted by race_id/race_entry_id per split",
            "group_correspondence_asserted": True,
            "prediction_keys_restored": True,
            "restored_tune_key_sha256": json_sha256(
                original_tune_keys.sort("original_row_index")
                .select("race_id", "race_entry_id")
                .rows()
            ),
        },
        "frozen_hashes_before": frozen_before,
        "frozen_hashes_after": frozen_after,
        "frozen_hashes_unchanged": True,
        "operating_registry_modified": False,
        "post_2026_05_31_actual_rows_accessed": False,
    }
    _write_json(OUTPUT / "callback_evidence.json", evidence)
    bundle = {
        "interface": "Booster raw_score=True -> grouped stable softmax",
        "feature_names": FEATURE_NAMES,
        "candidate_models": {
            candidate: {
                "path": f"{candidate.lower()}_model.txt",
                "sha256": results[candidate]["model_sha256"],
            }
            for candidate in results
        },
        "prediction_path": "synthetic_predictions.parquet",
        "prediction_sha256": sha256_file(OUTPUT / "synthetic_predictions.parquet"),
        "reload_exact": True,
    }
    _write_json(OUTPUT / "synthetic_bundle.json", bundle)
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
