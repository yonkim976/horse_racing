#!/usr/bin/env python3
"""Run the sealed E5-B BINARY versus RACE_SOFTMAX development study."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl

from horse_racing.analysis.confirmed_starter_e3 import sha256_file
from horse_racing.analysis.confirmed_starter_e5_r3r4 import (
    CallbackEvidence,
    NativeBinaryObjective,
    NativeRaceSoftmaxObjective,
    NativeRawRaceMetric,
    diagnose_temperature,
    grouped_softmax,
)
from horse_racing.analysis.confirmed_starter_e5b import (
    E5BContractError,
    array_sha256,
    date_cluster_bootstrap,
    evaluate_predictions,
    key_sha256,
    paired_bootstrap,
    stable_race_losses,
    validate_exact_keys,
    validate_prediction_frame,
)
from horse_racing.analysis.experiments import current_git_commit, hash_feature_names
from horse_racing.analysis.lightgbm_model import fit_feature_encoder, transform_features

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m"
DATASET_PATH = INPUT / "dataset.parquet"
INPUT_MANIFEST_PATH = INPUT / "manifest.json"
OUTPUT_BASE = ROOT / "data/experiments/confirmed_starter_e5b_race_objective_20260912"
PROTOCOL_V3 = ROOT / "docs/CONFIRMED_STARTER_RACE_OBJECTIVE_PROTOCOL_V3_2026-09-12.md"
MATH_ADAPTER = ROOT / "src/horse_racing/analysis/confirmed_starter_e5_r3r4.py"
OPERATING_REGISTRY = ROOT / "data/experiments/model_runs.jsonl"

EXPECTED = {
    "protocol_v3": "d539b7333b7dd2eb0ec8d7589879ca7de2a7e623d654c56f8c9349bd91da6984",
    "math_adapter": "55c7dcf686e4bf068b488beb396ffe18fd37a9f179939195494b21f9f35982d0",
    "dataset": "9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7",
    "input_manifest": "f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801",
    "feature_names": "b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48",
    "category_maps": "f3800b712d39af44a0d5ae7cfa9c74ca7ebdd9ff287e38c4a477a7b0c4b55d00",
}
PARTITIONS = {
    "fit": ("2025-01-04", "2025-10-26", 8719, 844),
    "tune": ("2025-11-01", "2025-12-27", 2001, 187),
    "calibration": ("2025-12-28", "2026-02-28", 1808, 169),
    "validation": ("2026-03-01", "2026-05-31", 3051, 288),
}
SEED = 42
BOOTSTRAP_SEED = 20260911
BOOTSTRAP_ITERATIONS = 5000
MAX_ROUNDS = 1200
PATIENCE = 80
FEATURE_SUM_TOLERANCE = 1e-8

FROZEN_PATHS = [
    DATASET_PATH,
    INPUT_MANIFEST_PATH,
    PROTOCOL_V3,
    MATH_ADAPTER,
    OPERATING_REGISTRY,
    ROOT / "data/experiments/confirmed_starter_e5a_r3_r4_20260912/artifact_manifest.json",
    ROOT / "data/experiments/confirmed_starter_e5a_20260912/artifact_manifest.json",
    ROOT / "data/experiments/confirmed_starter_e4_diagnostic_20260911/artifact_manifest.json",
    ROOT / "data/experiments/confirmed_starter_e3_20260911/artifact_manifest.json",
]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def git_state() -> dict[str, Any]:
    completed = subprocess.run(
        ["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return {
        "head": current_git_commit(),
        "dirty": bool(completed.stdout.strip()),
        "status_short": completed.stdout.splitlines(),
    }


def frozen_hashes() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): sha256_file(path) for path in FROZEN_PATHS}


def choose_output() -> Path:
    if not OUTPUT_BASE.exists():
        return OUTPUT_BASE
    index = 2
    while (candidate := Path(f"{OUTPUT_BASE}_attempt{index}")).exists():
        index += 1
    return candidate


def sort_partition(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.sort("race_date_local", "race_id", "race_entry_id", maintain_order=True)


def group_sizes(frame: pl.DataFrame) -> np.ndarray:
    return frame.group_by("race_id", maintain_order=True).len()["len"].to_numpy().astype(np.int32)


def binary_weights(groups: np.ndarray) -> np.ndarray:
    return np.concatenate([np.full(int(size), 1.0 / int(size)) for size in groups])


def partition_frame(dataset: pl.DataFrame, name: str) -> pl.DataFrame:
    start, end, rows, races = PARTITIONS[name]
    frame = sort_partition(
        dataset.filter((pl.col("race_date_local") >= start) & (pl.col("race_date_local") <= end))
    )
    observed = (frame.height, frame["race_id"].n_unique())
    if observed != (rows, races):
        raise E5BContractError(f"{name}: partition count mismatch {observed}")
    if frame["race_date_local"].min() != start or frame["race_date_local"].max() != end:
        raise E5BContractError(f"{name}: partition date mismatch")
    groups = group_sizes(frame)
    if groups.sum() != rows or len(groups) != races:
        raise E5BContractError(f"{name}: invalid group contract")
    return frame


def preflight(dataset: pl.DataFrame, manifest: dict[str, Any]) -> dict[str, Any]:
    actual_hashes = {
        "protocol_v3": sha256_file(PROTOCOL_V3),
        "math_adapter": sha256_file(MATH_ADAPTER),
        "dataset": sha256_file(DATASET_PATH),
        "input_manifest": sha256_file(INPUT_MANIFEST_PATH),
    }
    if actual_hashes != {key: EXPECTED[key] for key in actual_hashes}:
        raise E5BContractError(f"sealed hash mismatch: {actual_hashes}")
    selected = manifest["selected_feature_names"]
    if len(selected) != 136 or hash_feature_names(selected) != EXPECTED["feature_names"]:
        raise E5BContractError("feature-name contract mismatch")
    if dataset.height != 15579 or dataset["race_id"].n_unique() != 1488:
        raise E5BContractError("H1 total row/race count mismatch")
    if dataset.filter(pl.col("race_date_local") > "2026-05-31").height:
        raise E5BContractError("post-2026-05-31 row present in sealed dataset")
    manifest_keys = pl.DataFrame(
        manifest["field_contract"]["expected_keys"],
        schema=["race_id", "race_entry_id"],
        orient="row",
    )
    validate_exact_keys(manifest_keys, dataset, name="manifest-vs-dataset")
    duplicate_keys = dataset.group_by("race_id", "race_entry_id").len().filter(pl.col("len") != 1)
    if duplicate_keys.height:
        raise E5BContractError("dataset contains duplicate independent-manifest keys")
    if dataset.filter(~pl.col("win").is_in([0, 1])).height:
        raise E5BContractError("win label is not binary")
    winners = dataset.group_by("race_id").agg(pl.col("win").sum().alias("winner_count"))
    if winners.filter(pl.col("winner_count") < 1).height:
        raise E5BContractError("race without official winner")
    special = dataset.filter(pl.col("outcome_state") != "normal_finish")
    if special.height != 48 or special.select(pl.sum("win"), pl.sum("top2"), pl.sum("top3")).row(
        0
    ) != (0, 0, 0):
        raise E5BContractError("special-state label contract mismatch")
    if (
        special["finish_position_target"].null_count() != 48
        or special["finish_time_ms_target"].null_count() != 48
        or special["auxiliary_rank_observed"].any()
        or special["auxiliary_finish_time_observed"].any()
    ):
        raise E5BContractError("special-state mask contract mismatch")
    return {
        **{f"{key}_sha256": value for key, value in actual_hashes.items()},
        "feature_names_sha256": EXPECTED["feature_names"],
        "feature_count": len(selected),
        "dataset_rows": dataset.height,
        "dataset_races": dataset["race_id"].n_unique(),
        "dataset_key_sha256": key_sha256(dataset),
        "manifest_key_sha256": key_sha256(manifest_keys),
        "special_state_rows": special.height,
        "labels_and_masks_valid": True,
        "post_bound_rows": 0,
    }


def partition_contract(frame: pl.DataFrame, matrix: np.ndarray) -> dict[str, Any]:
    groups = group_sizes(frame)
    labels = frame["win"].to_numpy().astype(np.int8)
    return {
        "rows": frame.height,
        "races": len(groups),
        "date_min": frame["race_date_local"].min(),
        "date_max": frame["race_date_local"].max(),
        "key_sha256": key_sha256(frame),
        "group_sha256": array_sha256(groups),
        "label_sha256": array_sha256(labels),
        "matrix_sha256": array_sha256(matrix),
        "matrix_shape": list(matrix.shape),
        "matrix_nonfinite_count": int((~np.isfinite(matrix)).sum()),
        "categorical_values_integral_or_missing": True,
    }


def params(objective: Any) -> dict[str, Any]:
    return {
        "objective": objective,
        "metric": "None",
        "boost_from_average": False,
        "learning_rate": 0.03,
        "num_leaves": 31,
        "max_depth": -1,
        "min_data_in_leaf": 80,
        "min_sum_hessian_in_leaf": 0.001,
        "feature_fraction": 0.8,
        "bagging_fraction": 1.0,
        "bagging_freq": 0,
        "lambda_l2": 1.0,
        "deterministic": True,
        "force_col_wise": True,
        "seed": SEED,
        "data_random_seed": SEED,
        "feature_fraction_seed": SEED,
        "bagging_seed": SEED,
        "drop_seed": SEED,
        "extra_seed": SEED,
        "num_threads": -1,
        "verbosity": -1,
    }


class AuditedObjective:
    def __init__(self, candidate: str, evidence: CallbackEvidence, partition: str):
        self.candidate = candidate
        self.evidence = evidence
        self.partition = partition
        self.inner = (
            NativeBinaryObjective(evidence)
            if candidate == "BINARY"
            else NativeRaceSoftmaxObjective(evidence)
        )
        self.return_audit: list[dict[str, Any]] = []

    def __deepcopy__(self, memo: dict[int, Any]) -> AuditedObjective:
        del memo
        return self

    def __call__(
        self, predictions: np.ndarray, dataset: lgb.Dataset
    ) -> tuple[np.ndarray, np.ndarray]:
        if not np.isfinite(predictions).all():
            raise E5BContractError(f"{self.candidate}: non-finite callback margin")
        gradient, hessian = self.inner(predictions, dataset)
        invalid_gradient = int((~np.isfinite(gradient)).sum())
        invalid_hessian = int((~np.isfinite(hessian)).sum())
        nonpositive_hessian = int((hessian <= 0.0).sum())
        if invalid_gradient or invalid_hessian or nonpositive_hessian:
            raise E5BContractError(f"{self.candidate}: invalid objective return")
        floor_count = (
            int(self.evidence.objective_calls[-1]["hessian_floor_count"])
            if self.candidate == "RACE_SOFTMAX"
            else 0
        )
        self.return_audit.append(
            {
                "iteration": len(self.return_audit) + 1,
                "partition": self.partition,
                "gradient_nonfinite": invalid_gradient,
                "hessian_nonfinite": invalid_hessian,
                "nonpositive_hessian": nonpositive_hessian,
                "hessian_floor_count": floor_count,
                "gradient_sha256": array_sha256(gradient),
                "hessian_sha256": array_sha256(hessian),
            }
        )
        return gradient, hessian


def dataset_for(
    matrix: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
    features: list[str],
    categorical: list[str],
    *,
    candidate: str,
    reference: lgb.Dataset | None = None,
) -> lgb.Dataset:
    weights = binary_weights(groups) if candidate == "BINARY" else None
    return lgb.Dataset(
        matrix,
        label=labels,
        weight=weights,
        group=groups,
        feature_name=features,
        categorical_feature=categorical,
        reference=reference,
        free_raw_data=False,
    )


def verify_objective_calls(
    candidate: str,
    evidence: CallbackEvidence,
    labels: np.ndarray,
    groups: np.ndarray,
    weights: np.ndarray | None,
) -> None:
    label_hash = array_sha256(labels.astype(np.float32))
    group_hash = array_sha256(groups.astype(np.int32))
    weight_hash = None if weights is None else array_sha256(weights.astype(np.float32))
    for call in evidence.objective_calls:
        if call["labels"]["sha256"] != label_hash or call["groups"]["sha256"] != group_hash:
            raise E5BContractError(f"{candidate}: objective label/group partition mixed")
        observed_weight = None if call["weights"] is None else call["weights"]["sha256"]
        if observed_weight != weight_hash:
            raise E5BContractError(f"{candidate}: objective weight policy changed")
        if candidate == "BINARY":
            actual = np.asarray(call["weights"]["head"], dtype=np.float64)
            expected = weights[: len(actual)]
            if np.max(np.abs(actual - expected)) > 1e-7:
                raise E5BContractError("BINARY float32 weight tolerance violated")


def verify_metric_calls(
    candidate: str,
    booster: lgb.Booster,
    evidence: CallbackEvidence,
    matrix: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
) -> list[dict[str, Any]]:
    label_hash = array_sha256(labels.astype(np.float32))
    group_hash = array_sha256(groups.astype(np.int32))
    audit = []
    for iteration, call in enumerate(evidence.metric_calls, start=1):
        if call["labels"]["sha256"] != label_hash or call["groups"]["sha256"] != group_hash:
            raise E5BContractError(f"{candidate}: metric label/group partition mixed")
        raw = np.asarray(booster.predict(matrix, raw_score=True, num_iteration=iteration))
        independent = stable_race_losses(raw, labels, groups, beta=1.0)[0].mean()
        hash_match = array_sha256(raw) == call["raw_margins"]["sha256"]
        error = abs(float(independent) - float(call["metric"]))
        if not hash_match or error > 1e-12:
            raise E5BContractError(f"{candidate}: raw callback audit failed at {iteration}")
        audit.append(
            {
                "iteration": iteration,
                "raw_margin_sha256": array_sha256(raw),
                "raw_margin_hash_match": True,
                "callback_ce": call["metric"],
                "independent_ce": float(independent),
                "absolute_error": error,
            }
        )
    return audit


def train_selector(
    candidate: str,
    fit_matrix: np.ndarray,
    fit_labels: np.ndarray,
    fit_groups: np.ndarray,
    tune_matrix: np.ndarray,
    tune_labels: np.ndarray,
    tune_groups: np.ndarray,
    features: list[str],
    categorical: list[str],
    run_dir: Path,
) -> tuple[lgb.Booster, dict[str, Any]]:
    evidence = CallbackEvidence()
    objective = AuditedObjective(candidate, evidence, "fit")
    fit_data = dataset_for(
        fit_matrix, fit_labels, fit_groups, features, categorical, candidate=candidate
    )
    tune_data = dataset_for(
        tune_matrix,
        tune_labels,
        tune_groups,
        features,
        categorical,
        candidate=candidate,
        reference=fit_data,
    )
    metric = NativeRawRaceMetric(evidence)
    booster = lgb.train(
        params(objective),
        fit_data,
        num_boost_round=MAX_ROUNDS,
        valid_sets=[tune_data],
        valid_names=["tune"],
        feval=metric,
        keep_training_booster=True,
        callbacks=[
            lgb.early_stopping(PATIENCE, first_metric_only=True, verbose=False),
            lgb.log_evaluation(0),
        ],
    )
    if not 1 <= booster.best_iteration <= MAX_ROUNDS:
        raise E5BContractError(f"{candidate}: invalid best iteration")
    if set(booster.best_score) != {"tune"} or set(booster.best_score["tune"]) != {
        "race_equal_soft_label_ce"
    }:
        raise E5BContractError(f"{candidate}: unintended stopping metric")
    fit_weights = binary_weights(fit_groups) if candidate == "BINARY" else None
    verify_objective_calls(candidate, evidence, fit_labels, fit_groups, fit_weights)
    callback_audit = verify_metric_calls(
        candidate, booster, evidence, tune_matrix, tune_labels, tune_groups
    )
    selector_path = run_dir / "selector_model.txt"
    booster.save_model(selector_path, num_iteration=booster.current_iteration())
    reloaded = lgb.Booster(model_file=str(selector_path))
    last_original = booster.predict(
        tune_matrix, raw_score=True, num_iteration=booster.current_iteration()
    )
    last_reload = reloaded.predict(
        tune_matrix, raw_score=True, num_iteration=booster.current_iteration()
    )
    reload_error = float(np.max(np.abs(last_original - last_reload)))
    if reload_error > 1e-12:
        raise E5BContractError(f"{candidate}: selector reload mismatch")
    audit = {
        "candidate": candidate,
        "best_iteration": booster.best_iteration,
        "current_iteration": booster.current_iteration(),
        "best_score": booster.best_score,
        "only_stopping_metric": "race_equal_soft_label_ce",
        "objective_calls": len(evidence.objective_calls),
        "metric_calls": len(evidence.metric_calls),
        "callback_iterations": callback_audit,
        "objective_return_audit": objective.return_audit,
        "selector_reload_raw_max_abs_error": reload_error,
        "selector_saved_with_num_iteration": booster.current_iteration(),
        "weight_policy": "1/field_size float32" if candidate == "BINARY" else "None",
        "boost_from_average": False,
    }
    write_json(run_dir / "selector_callback_audit.json", audit)
    return booster, audit


def refit(
    candidate: str,
    matrix: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
    features: list[str],
    categorical: list[str],
    iterations: int,
    run_dir: Path,
) -> tuple[lgb.Booster, dict[str, Any]]:
    evidence = CallbackEvidence()
    objective = AuditedObjective(candidate, evidence, "fit_plus_tune")
    data = dataset_for(matrix, labels, groups, features, categorical, candidate=candidate)
    booster = lgb.train(
        params(objective),
        data,
        num_boost_round=iterations,
        keep_training_booster=True,
        callbacks=[lgb.log_evaluation(0)],
    )
    weights = binary_weights(groups) if candidate == "BINARY" else None
    verify_objective_calls(candidate, evidence, labels, groups, weights)
    if booster.current_iteration() != iterations:
        raise E5BContractError(f"{candidate}: refit iteration mismatch")
    path = run_dir / "refit_model.txt"
    booster.save_model(path, num_iteration=iterations)
    reloaded = lgb.Booster(model_file=str(path))
    raw = np.asarray(booster.predict(matrix, raw_score=True, num_iteration=iterations))
    raw_reload = np.asarray(reloaded.predict(matrix, raw_score=True, num_iteration=iterations))
    error = float(np.max(np.abs(raw - raw_reload)))
    if error > 1e-12:
        raise E5BContractError(f"{candidate}: refit reload mismatch")
    audit = {
        "iterations": iterations,
        "objective_calls": len(evidence.objective_calls),
        "objective_return_audit": objective.return_audit,
        "reload_training_raw_max_abs_error": error,
    }
    write_json(run_dir / "refit_audit.json", audit)
    return booster, audit


def make_predictions(
    booster: lgb.Booster,
    frame: pl.DataFrame,
    matrix: np.ndarray,
    groups: np.ndarray,
    temperature: float,
) -> pl.DataFrame:
    raw = np.asarray(
        booster.predict(matrix, raw_score=True, num_iteration=booster.current_iteration())
    )
    if not np.isfinite(raw).all():
        raise E5BContractError("non-finite refit raw margin")
    probability = grouped_softmax(raw / temperature, groups)
    return frame.select("race_id", "race_entry_id", "horse_number").with_columns(
        pl.Series("raw_margin", raw), pl.Series("prob_win", probability)
    )


def candidate_run(
    candidate: str,
    partitions: dict[str, pl.DataFrame],
    matrices: dict[str, np.ndarray],
    features: list[str],
    categorical: list[str],
    output: Path,
) -> dict[str, Any]:
    run_id = f"e5b_{candidate.lower()}_seed42"
    run_dir = output / run_id
    run_dir.mkdir()
    arrays = {
        name: {
            "matrix": matrices[name],
            "labels": partitions[name]["win"].to_numpy().astype(np.int8),
            "groups": group_sizes(partitions[name]),
        }
        for name in partitions
    }
    selector, selector_audit = train_selector(
        candidate,
        arrays["fit"]["matrix"],
        arrays["fit"]["labels"],
        arrays["fit"]["groups"],
        arrays["tune"]["matrix"],
        arrays["tune"]["labels"],
        arrays["tune"]["groups"],
        features,
        categorical,
        run_dir,
    )
    combined_frame = pl.concat([partitions["fit"], partitions["tune"]], how="vertical")
    combined_matrix = np.vstack([matrices["fit"], matrices["tune"]])
    combined_labels = combined_frame["win"].to_numpy().astype(np.int8)
    combined_groups = group_sizes(combined_frame)
    refitted, refit_audit = refit(
        candidate,
        combined_matrix,
        combined_labels,
        combined_groups,
        features,
        categorical,
        selector.best_iteration,
        run_dir,
    )
    calibration_raw = np.asarray(
        refitted.predict(
            matrices["calibration"], raw_score=True, num_iteration=selector.best_iteration
        )
    )
    temperature_diagnostic = diagnose_temperature(
        calibration_raw, arrays["calibration"]["labels"], arrays["calibration"]["groups"]
    )
    temperature_payload = temperature_diagnostic.to_dict()
    temperature_payload["calibration_raw_sha256"] = array_sha256(calibration_raw)
    write_json(run_dir / "temperature.json", temperature_payload)
    if temperature_diagnostic.status not in {"interior_optimum", "flat_use_T1"}:
        raise E5BContractError(
            f"{candidate}: temperature failed with {temperature_diagnostic.status}"
        )
    temperature = temperature_diagnostic.solution.temperature
    calibration_predictions = make_predictions(
        refitted,
        partitions["calibration"],
        matrices["calibration"],
        arrays["calibration"]["groups"],
        temperature,
    )
    validation_predictions = make_predictions(
        refitted,
        partitions["validation"],
        matrices["validation"],
        arrays["validation"]["groups"],
        temperature,
    )
    calibration_predictions.write_parquet(run_dir / "calibration_predictions.parquet")
    validation_predictions.write_parquet(run_dir / "validation_predictions.parquet")
    joined, coverage = validate_prediction_frame(
        partitions["validation"], validation_predictions, name=candidate
    )
    metrics, per_race = evaluate_predictions(joined, beta=1.0 / temperature)
    per_race.write_parquet(run_dir / "validation_per_race.parquet")
    reloaded = lgb.Booster(model_file=str(run_dir / "refit_model.txt"))
    reload_predictions = make_predictions(
        reloaded,
        partitions["validation"],
        matrices["validation"],
        arrays["validation"]["groups"],
        temperature,
    )
    reload_join = validation_predictions.join(
        reload_predictions,
        on=["race_id", "race_entry_id", "horse_number"],
        suffix="_reload",
        validate="1:1",
    )
    reload_errors = {
        column: float((reload_join[column] - reload_join[f"{column}_reload"]).abs().max() or 0.0)
        for column in ("raw_margin", "prob_win")
    }
    if max(reload_errors.values()) > 1e-12:
        raise E5BContractError(f"{candidate}: validation reload mismatch")
    metadata = {
        "run_id": run_id,
        "candidate": candidate,
        "selector": {
            key: selector_audit[key]
            for key in (
                "best_iteration",
                "current_iteration",
                "best_score",
                "objective_calls",
                "metric_calls",
                "selector_reload_raw_max_abs_error",
            )
        },
        "refit": {
            "rows": combined_frame.height,
            "races": combined_frame["race_id"].n_unique(),
            "iterations": selector.best_iteration,
            "audit": refit_audit,
        },
        "temperature": temperature_payload,
        "coverage": coverage,
        "metrics": metrics,
        "reload": {"max_absolute_error": reload_errors, "tolerance": 1e-12},
        "hessian_floor_count": {
            "selector_fit": sum(
                item["hessian_floor_count"] for item in selector_audit["objective_return_audit"]
            ),
            "refit_fit_plus_tune": sum(
                item["hessian_floor_count"] for item in refit_audit["objective_return_audit"]
            ),
        },
    }
    write_json(run_dir / "run.json", metadata)
    return {"metadata": metadata, "joined": joined, "per_race": per_race}


def subset_metrics(joined: pl.DataFrame, race_ids: set[int], beta: float) -> dict[str, Any]:
    special = joined.filter(pl.col("race_id").is_in(race_ids))
    other = joined.filter(~pl.col("race_id").is_in(race_ids))
    return {
        "special_state_12_races": evaluate_predictions(special, beta=beta)[0],
        "other_276_races": evaluate_predictions(other, beta=beta)[0],
    }


def protocol_payload(
    output: Path,
    preflight_result: dict[str, Any],
    partition_contracts: dict[str, Any],
    encoder_contract: dict[str, Any],
    frozen_before: dict[str, str],
) -> dict[str, Any]:
    return {
        "study": "E5-B same-A-input BINARY vs RACE_SOFTMAX development study",
        "status_at_write": "sealed_before_first_tree_fit",
        "output": str(output.relative_to(ROOT)),
        "protocol_v3_sha256": EXPECTED["protocol_v3"],
        "approved_math_adapter_sha256": EXPECTED["math_adapter"],
        "preflight": preflight_result,
        "partitions": partition_contracts,
        "encoder": encoder_contract,
        "candidates": {
            "BINARY": {
                "objective": "custom weighted Bernoulli",
                "label": "winner indicator 0/1",
                "weight": "1/field_size float32 Dataset buffer",
                "hessian_floor": None,
            },
            "RACE_SOFTMAX": {
                "objective": "custom grouped softmax",
                "label": "winner indicator converted to q in callback",
                "weight": None,
                "hessian_floor": 1e-6,
            },
        },
        "common_parameters": {
            key: value for key, value in params("CUSTOM").items() if key != "objective"
        },
        "num_boost_round": MAX_ROUNDS,
        "early_stopping_patience": PATIENCE,
        "selector_calls": 2,
        "refit_calls": 2,
        "temperature": {
            "parameterization": "beta=1/T",
            "log_temperature_bounds": [-4.0, 4.0],
            "flat_policy": "structural exact only; T=1",
            "boundary_policy": "stop comparison",
            "root": {
                "solver": "scipy.brentq",
                "xtol": 1e-12,
                "rtol": "4*float64_eps",
                "maxiter": 200,
            },
        },
        "primary_metric": "stable log-domain race-equal winner-set NLL",
        "secondary_metrics": [
            "race-equal soft-label CE",
            "entry-equal binary NLL epsilon=1e-15 and Brier",
            "expected-tie Top1/Top3/Top5",
        ],
        "delta": "RACE_SOFTMAX-BINARY; negative loss delta favors RACE_SOFTMAX",
        "bootstrap": {
            "paired_race": {"iterations": BOOTSTRAP_ITERATIONS, "seed": BOOTSTRAP_SEED},
            "race_date_cluster": {"iterations": BOOTSTRAP_ITERATIONS, "seed": BOOTSTRAP_SEED},
            "conditional_on": "stored predictions; no retraining or search variation",
        },
        "validation": {
            "rows": 3051,
            "races": 288,
            "probability_sum_tolerance": 1e-8,
            "reload_tolerance": 1e-12,
            "development_reused": True,
        },
        "stop_conditions": [
            "sealed input/code mismatch",
            "candidate matrix/key/group/label mismatch",
            "callback raw metric mismatch",
            "non-finite objective input/output",
            "temperature boundary or solver failure",
            "validation coverage or reload failure",
        ],
        "code_sha256": {
            str(Path(__file__).relative_to(ROOT)): sha256_file(Path(__file__)),
            "src/horse_racing/analysis/confirmed_starter_e5b.py": sha256_file(
                ROOT / "src/horse_racing/analysis/confirmed_starter_e5b.py"
            ),
            "src/horse_racing/analysis/confirmed_starter_e5_r3r4.py": sha256_file(MATH_ADAPTER),
        },
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "polars": pl.__version__,
            "lightgbm": lgb.__version__,
            "scipy": importlib.metadata.version("scipy"),
            "platform": platform.platform(),
            "pid": os.getpid(),
        },
        "git": git_state(),
        "frozen_hashes_before": frozen_before,
        "actual_result_upper_bound": "2026-05-31",
        "operating_registry_write_authorized": False,
    }


def comparison_payload(results: dict[str, Any]) -> dict[str, Any]:
    binary = results["BINARY"]
    race = results["RACE_SOFTMAX"]
    paired = (
        binary["per_race"]
        .select(
            "race_id",
            "race_date",
            "contains_special_state",
            pl.col("winner_set_nll").alias("binary_winner_set_nll"),
            pl.col("soft_label_ce").alias("binary_soft_label_ce"),
        )
        .join(
            race["per_race"].select(
                "race_id",
                pl.col("winner_set_nll").alias("race_softmax_winner_set_nll"),
                pl.col("soft_label_ce").alias("race_softmax_soft_label_ce"),
            ),
            on="race_id",
            validate="1:1",
        )
        .with_columns(
            (pl.col("race_softmax_winner_set_nll") - pl.col("binary_winner_set_nll")).alias(
                "delta"
            ),
            (pl.col("race_softmax_soft_label_ce") - pl.col("binary_soft_label_ce")).alias(
                "soft_label_ce_delta"
            ),
        )
    )
    metrics = {candidate: results[candidate]["metadata"]["metrics"] for candidate in results}
    metric_deltas = {
        key: metrics["RACE_SOFTMAX"][key] - metrics["BINARY"][key]
        for key in (
            "race_equal_winner_set_nll",
            "race_equal_soft_label_ce",
            "entry_equal_binary_nll",
            "entry_equal_brier",
            "top1_winner_inclusion",
            "top3_winner_inclusion",
            "top5_winner_inclusion",
        )
    }
    special_ids = set(paired.filter(pl.col("contains_special_state") == 1)["race_id"].to_list())
    if len(special_ids) != 12:
        raise E5BContractError(f"validation special-state race count={len(special_ids)}")
    subsets = {
        candidate: subset_metrics(
            results[candidate]["joined"],
            special_ids,
            beta=1.0 / results[candidate]["metadata"]["temperature"]["solution"]["temperature"],
        )
        for candidate in results
    }
    return {
        "delta_definition": "RACE_SOFTMAX-BINARY; negative loss delta favors RACE_SOFTMAX",
        "scope": {
            "development_validation_rows": 3051,
            "development_validation_races": 288,
            "dates": ["2026-03-01", "2026-05-31"],
            "independent_test": False,
            "development_validation_reused": True,
            "single_seed": SEED,
        },
        "run_ids": {candidate: results[candidate]["metadata"]["run_id"] for candidate in results},
        "metrics": metrics,
        "metric_deltas": metric_deltas,
        "temperature": {
            candidate: results[candidate]["metadata"]["temperature"] for candidate in results
        },
        "best_iterations": {
            candidate: results[candidate]["metadata"]["selector"]["best_iteration"]
            for candidate in results
        },
        "coverage": {
            candidate: results[candidate]["metadata"]["coverage"] for candidate in results
        },
        "reload": {candidate: results[candidate]["metadata"]["reload"] for candidate in results},
        "hessian_floor_count": {
            candidate: results[candidate]["metadata"]["hessian_floor_count"]
            for candidate in results
        },
        "bootstrap": {
            "paired_race": paired_bootstrap(
                paired["delta"].to_numpy(), iterations=BOOTSTRAP_ITERATIONS, seed=BOOTSTRAP_SEED
            ),
            "race_date_cluster": date_cluster_bootstrap(
                paired, iterations=BOOTSTRAP_ITERATIONS, seed=BOOTSTRAP_SEED
            ),
            "conditional_on_stored_predictions": True,
            "retraining_or_search_variation_included": False,
        },
        "fixed_diagnostic_subsets": subsets,
        "tie_policy": "result-independent expected inclusion for score/probability ties",
        "primary_loss_policy": "stable log-domain; no epsilon clipping",
        "binary_nll_policy": "secondary entry-equal metric; epsilon=1e-15 clipping",
        "paired_frame": paired,
    }


def write_report(output: Path, comparison: dict[str, Any]) -> None:
    metrics = comparison["metrics"]
    delta = comparison["metric_deltas"]
    race_ci = comparison["bootstrap"]["paired_race"]["percentile_95_ci"]
    date_ci = comparison["bootstrap"]["race_date_cluster"]["percentile_95_ci"]
    lines = [
        "# Confirmed-starter E5-B BINARY vs RACE_SOFTMAX 개발 연구",
        "",
        "작성일: 2026-09-12 KST",
        "",
        "## 주 결과",
        "",
        "- BINARY race-equal winner-set NLL: "
        f"`{metrics['BINARY']['race_equal_winner_set_nll']:.12f}`",
        "- RACE_SOFTMAX race-equal winner-set NLL: "
        f"`{metrics['RACE_SOFTMAX']['race_equal_winner_set_nll']:.12f}`",
        f"- delta(RACE_SOFTMAX-BINARY): `{delta['race_equal_winner_set_nll']:+.12f}`",
        f"- paired race bootstrap 95% CI: `[{race_ci[0]:+.12f}, {race_ci[1]:+.12f}]`",
        f"- race-date cluster bootstrap 95% CI: `[{date_ci[0]:+.12f}, {date_ci[1]:+.12f}]`",
        "",
        "음수 loss delta가 RACE_SOFTMAX 개선 방향이다. 이 구간은 저장 예측에 "
        "조건부이며 재학습·탐색 변동성을 포함하지 않는다.",
        "",
        "## 실행 계약",
        "",
    ]
    for candidate in ("BINARY", "RACE_SOFTMAX"):
        metadata = comparison["temperature"][candidate]
        lines.append(
            f"- {candidate}: best iteration {comparison['best_iterations'][candidate]}, "
            f"temperature `{metadata['solution']['temperature']:.12f}`, "
            f"status `{metadata['status']}`, "
            f"validation coverage `{comparison['coverage'][candidate]['coverage']:.1f}`."
        )
    lines.extend(
        [
            "",
            "양 후보 모두 3,051행·288경주를 평가했고 selector callback의 모든 iteration "
            "raw margin hash와 독립 CE를 대조했다. 최종 refit과 selector는 별도 저장했다.",
            "",
            "## 보조 지표",
            "",
        ]
    )
    for key in (
        "race_equal_soft_label_ce",
        "entry_equal_binary_nll",
        "entry_equal_brier",
        "top1_winner_inclusion",
        "top3_winner_inclusion",
        "top5_winner_inclusion",
    ):
        lines.append(
            f"- {key}: BINARY `{metrics['BINARY'][key]:.12f}`, "
            f"RACE_SOFTMAX `{metrics['RACE_SOFTMAX'][key]:.12f}`, "
            f"delta `{delta[key]:+.12f}`"
        )
    lines.extend(
        [
            "",
            "## 해석 제한",
            "",
            "3~5월 validation은 반복 사용된 개발 평가이며 독립 test가 아니다. 단일 seed의 "
            "조건부 비교이고 실제 2026-06-01 이후 결과는 열지 않았다. 결과는 운영 승격이나 "
            "미래 성능의 증거가 아니다. 기본 registry/champion 및 운영 prediction·배팅 경로는 "
            "변경하지 않았다.",
            "",
        ]
    )
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def finalize_manifest(output: Path, frozen_before: dict[str, str], status: str) -> None:
    frozen_after = frozen_hashes()
    if frozen_after != frozen_before:
        raise E5BContractError("frozen input or operating registry changed")
    files = sorted(
        path
        for path in output.rglob("*")
        if path.is_file() and path.name != "artifact_manifest.json"
    )
    payload = {
        "study": "E5-B BINARY versus RACE_SOFTMAX development study",
        "status": status,
        "frozen_hashes_before": frozen_before,
        "frozen_hashes_after": frozen_after,
        "frozen_hashes_unchanged": True,
        "outputs": {str(path.relative_to(ROOT)): sha256_file(path) for path in files},
        "actual_result_upper_bound": "2026-05-31",
        "post_2026_05_31_actual_rows_accessed": False,
        "operating_registry_modified": False,
        "champion_or_active_pointer_modified": False,
        "candidate_count": 2,
        "additional_seed_or_setting_search": False,
    }
    write_json(output / "artifact_manifest.json", payload)


def main() -> int:
    started = time.time()
    output = choose_output()
    output.mkdir(parents=True)
    frozen_before = frozen_hashes()
    attempts: list[dict[str, Any]] = []
    try:
        dataset = pl.read_parquet(DATASET_PATH)
        manifest = json.loads(INPUT_MANIFEST_PATH.read_text(encoding="utf-8"))
        preflight_result = preflight(dataset, manifest)
        features = manifest["selected_feature_names"]
        partitions = {name: partition_frame(dataset, name) for name in PARTITIONS}
        train = pl.concat(
            [partitions["fit"], partitions["tune"], partitions["calibration"]], how="vertical"
        )
        if train.height != 12528 or train["race_id"].n_unique() != 1200:
            raise E5BContractError("encoder train denominator mismatch")
        encoder = fit_feature_encoder(train, features)
        category_hash = json_hash(encoder.category_maps)
        if category_hash != EXPECTED["category_maps"]:
            raise E5BContractError("category-map hash mismatch")
        matrices = {name: transform_features(frame, encoder) for name, frame in partitions.items()}
        for name, matrix in matrices.items():
            for categorical_index in encoder.categorical_indices:
                values = matrix[:, categorical_index]
                finite = values[np.isfinite(values)]
                if not np.equal(finite, np.floor(finite)).all():
                    raise E5BContractError(f"{name}: non-integral categorical matrix value")
        contracts = {
            name: partition_contract(partitions[name], matrices[name]) for name in PARTITIONS
        }
        encoder_contract = {
            "fit_scope": "A train fit+tune+calibration only",
            "rows": train.height,
            "races": train["race_id"].n_unique(),
            "feature_names": features,
            "feature_names_sha256": hash_feature_names(features),
            "categorical_features": encoder.categorical_features,
            "categorical_indices": encoder.categorical_indices,
            "category_maps": encoder.category_maps,
            "category_maps_sha256": category_hash,
            "validation_used_for_fit": False,
        }
        protocol = protocol_payload(
            output, preflight_result, contracts, encoder_contract, frozen_before
        )
        write_json(output / "protocol.json", protocol)
        attempts.append(
            {"stage": "preflight_and_protocol", "status": "passed", "first_tree_fit_started": False}
        )
        results: dict[str, Any] = {}
        for candidate in ("BINARY", "RACE_SOFTMAX"):
            results[candidate] = candidate_run(
                candidate, partitions, matrices, features, encoder.categorical_features, output
            )
            attempts.append(
                {
                    "stage": candidate,
                    "status": "passed",
                    "selector_calls": 1,
                    "refit_calls": 1,
                    "additional_retries": 0,
                }
            )
        if contracts["validation"] != partition_contract(
            partitions["validation"], matrices["validation"]
        ):
            raise E5BContractError("post-training validation matrix contract changed")
        comparison = comparison_payload(results)
        paired = comparison.pop("paired_frame")
        paired.write_parquet(output / "paired_validation_race_losses.parquet")
        write_json(output / "comparison.json", comparison)
        write_report(output, comparison)
        ledger = [
            {
                "run_id": results[candidate]["metadata"]["run_id"],
                "candidate": candidate,
                "dataset_sha256": EXPECTED["dataset"],
                "feature_names_sha256": EXPECTED["feature_names"],
                "seed": SEED,
                "train_period": "2025-01-04~2025-12-27",
                "calibration_period": "2025-12-28~2026-02-28",
                "development_validation_period": "2026-03-01~2026-05-31",
                "best_iteration": results[candidate]["metadata"]["selector"]["best_iteration"],
                "temperature": results[candidate]["metadata"]["temperature"]["solution"][
                    "temperature"
                ],
                "metrics": results[candidate]["metadata"]["metrics"],
                "operational": False,
            }
            for candidate in ("BINARY", "RACE_SOFTMAX")
        ]
        (output / "research_model_runs.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in ledger), encoding="utf-8"
        )
        attempts.append(
            {
                "stage": "comparison",
                "status": "passed",
                "validation_rows": 3051,
                "validation_races": 288,
                "additional_retraining": False,
            }
        )
        write_json(
            output / "attempts.json",
            {
                "attempts": attempts,
                "status": "completed",
                "elapsed_seconds": time.time() - started,
                "selector_fit_calls": 2,
                "refit_fit_calls": 2,
                "extra_fit_calls": 0,
            },
        )
        finalize_manifest(output, frozen_before, "completed")
        print(output)
        return 0
    except Exception as exc:
        attempts.append(
            {
                "stage": "failed",
                "status": "failed",
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
        )
        write_json(
            output / "attempts.json",
            {
                "attempts": attempts,
                "status": "failed",
                "elapsed_seconds": time.time() - started,
            },
        )
        write_json(
            output / "failure.json",
            {
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "comparison_performed": False,
                "temperature_fallback_used": False,
                "settings_changed_and_retried": False,
            },
        )
        finalize_manifest(output, frozen_before, "failed")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
