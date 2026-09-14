#!/usr/bin/env python3
"""Execute the sealed E7-B twelve-feature, two-arm, three-fold development study."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import time
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl

from horse_racing.analysis.confirmed_starter_e5_r3r4 import diagnose_temperature
from horse_racing.analysis.confirmed_starter_e5b import (
    array_sha256,
    key_sha256,
    validate_exact_keys,
)
from horse_racing.analysis.confirmed_starter_e6a_v2 import prepare_diagnosed_arm
from horse_racing.analysis.confirmed_starter_e6b import group_sizes, partition_frame
from horse_racing.analysis.confirmed_starter_e7a import FEATURES
from horse_racing.analysis.confirmed_starter_e7b import (
    ARMS,
    PARTITIONS,
    E7BContractError,
    evaluate_arm,
    orchestrate_fold,
    paired_comparison,
    pooled_metrics,
    verify_sequence_contract,
    verify_shared_base_matrices,
)
from horse_racing.analysis.experiments import hash_feature_names
from horse_racing.analysis.lightgbm_model import (
    FeatureEncoder,
    fit_feature_encoder,
    transform_features,
)
from scripts.run_confirmed_starter_e5b import (
    binary_weights,
    make_predictions,
    params,
    refit,
    train_selector,
)
from scripts.run_confirmed_starter_e6b import evaluate_reload

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_BASE = ROOT / "data/experiments/confirmed_starter_e7b_20260913"
H1 = ROOT / "data/datasets/confirmed_starter_e2_h1_remediation_retrospective"
H1 = H1 / "start_minus_30m/dataset.parquet"
H1_MANIFEST = H1.with_name("manifest.json")
E7A = ROOT / "data/experiments/confirmed_starter_e7a_20260913_attempt4"
SEQUENCE = E7A / "sequence_features.parquet"
EVIDENCE = E7A / "sequence_evidence.parquet"
E7A_MANIFEST = E7A / "artifact_manifest.json"
DRAFT = ROOT / "docs/CONFIRMED_STARTER_E7B_PROTOCOL_DRAFT_2026-09-13.md"
AUTHORIZATION = ROOT / "docs/CONFIRMED_STARTER_E7B_AGENT_PROMPT_2026-09-13.md"
E6B = ROOT / "data/experiments/confirmed_starter_e6b_20260913"
REGISTRY = ROOT / "data/experiments/model_runs.jsonl"
FEATURE_HASH = "b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48"
SEALED = {
    H1: "9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7",
    H1_MANIFEST: "f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801",
    E7A_MANIFEST: "4a2a9aad7c6c7c24f99bf57c201a9b3820736d769361ef56034875fd0f772ce3",
    SEQUENCE: "4cf65df396542271c5b7574584b4c1991f52a4d05896e0b7ee4af8b2849fefea",
    EVIDENCE: "ca02f11923f354e90f429fd2c06e7209f591ca6c0a3b6c77c6a4468aff41fd08",
    ROOT / "src/horse_racing/analysis/confirmed_starter_e7a.py": (
        "d3744f478fdb2fc0a9f597d3c652057fcf7b02c7031ba0378614d98b0a287682"
    ),
    DRAFT: "d6a1dafb6af62d29e2eb2efc158650a9c1ad65969b0e854d1049d3ffff7c531d",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def output_path() -> Path:
    if not OUTPUT_BASE.exists():
        return OUTPUT_BASE
    index = 2
    while Path(f"{OUTPUT_BASE}_attempt{index}").exists():
        index += 1
    return Path(f"{OUTPUT_BASE}_attempt{index}")


def frozen_paths() -> set[Path]:
    e7a = json.loads(E7A_MANIFEST.read_text())
    return (
        set(SEALED)
        | {ROOT / name for name in e7a["sealed_hashes_before"]}
        | {ROOT / name for name in e7a["outputs"]}
        | {ROOT / "scripts/audit_confirmed_starter_e7a.py", REGISTRY, AUTHORIZATION}
    )


def frozen_hashes() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(frozen_paths())}


def verify_sealed() -> dict[str, str]:
    for path, expected in SEALED.items():
        if sha(path) != expected:
            raise E7BContractError(f"sealed hash mismatch: {path}")
    manifest = json.loads(E7A_MANIFEST.read_text())
    for name, expected in {**manifest["sealed_hashes_before"], **manifest["outputs"]}.items():
        if sha(ROOT / name) != expected:
            raise E7BContractError(f"E7-A preservation/output mismatch: {name}")
    return frozen_hashes()


def preflight_input() -> tuple[pl.DataFrame, list[str], dict[str, Any]]:
    h1 = pl.read_parquet(H1)
    sequence = pl.read_parquet(SEQUENCE)
    evidence = pl.read_parquet(EVIDENCE)
    if (
        h1.height != 15579
        or h1["race_id"].n_unique() != 1488
        or h1["race_date_local"].max() != "2026-05-31"
    ):
        raise E7BContractError("H1 denominator/date contract changed")
    manifest = json.loads(H1_MANIFEST.read_text())
    expected = pl.DataFrame(
        manifest["field_contract"]["expected_keys"],
        schema=["race_id", "race_entry_id"],
        orient="row",
    )
    validate_exact_keys(expected, h1, name="H1 manifest")
    verify_sequence_contract(h1, sequence, evidence)
    features = manifest["selected_feature_names"]
    if len(features) != 136 or hash_feature_names(features) != FEATURE_HASH:
        raise E7BContractError("136 feature names/order changed")
    if set(features) & set(FEATURES):
        raise E7BContractError("sequence feature collides with baseline")
    joined = h1.join(sequence, on=["race_id", "race_entry_id"], how="left", validate="1:1")
    if joined.height != h1.height:
        raise E7BContractError("sequence join denominator changed")
    return (
        joined,
        features,
        {
            "H1_rows": h1.height,
            "H1_races": h1["race_id"].n_unique(),
            "H1_key_sha256": key_sha256(h1),
            "sequence_key_sha256": key_sha256(sequence),
            "evidence_rows": evidence.height,
            "base_feature_names_sha256": FEATURE_HASH,
            "sequence_feature_names": list(FEATURES),
            "null_counts": {name: sequence[name].null_count() for name in FEATURES},
            "feature_counts": {ARMS[0]: 136, ARMS[1]: 148},
            "post_2026_02_28_rows_used_for_model": 0,
            "database_or_raw_queried": False,
        },
    )


def fold_input(
    frame: pl.DataFrame, features: list[str], fold: str
) -> tuple[dict[str, pl.DataFrame], dict[str, dict[str, np.ndarray]], dict[str, Any]]:
    parts = {stage: partition_frame(frame, fold, stage) for stage in PARTITIONS[fold]}
    intervals = [PARTITIONS[fold][stage] for stage in ("fit", "tune", "calibration", "evaluation")]
    if not (
        intervals[0][1]
        < intervals[1][0]
        <= intervals[1][1]
        < intervals[2][0]
        <= intervals[2][1]
        < intervals[3][0]
    ):
        raise E7BContractError(f"{fold}: time order invalid")
    encoder = fit_feature_encoder(parts["fit"], features)
    expanded = FeatureEncoder(
        features + list(FEATURES),
        encoder.categorical_features.copy(),
        encoder.category_maps.copy(),
    )
    matrices = {
        ARMS[0]: {stage: transform_features(part, encoder) for stage, part in parts.items()},
        ARMS[1]: {stage: transform_features(part, expanded) for stage, part in parts.items()},
    }
    shared = verify_shared_base_matrices(matrices[ARMS[0]], matrices[ARMS[1]])
    contracts = {}
    for stage, part in parts.items():
        groups = group_sizes(part)
        labels = part["win"].to_numpy().astype(np.int8)
        if not np.isin(labels, [0, 1]).all() or int(groups.sum()) != part.height:
            raise E7BContractError(f"{fold}/{stage}: group or binary label invalid")
        if any(int(race["win"].sum()) < 1 for race in part.partition_by("race_id")):
            raise E7BContractError(f"{fold}/{stage}: winnerless race")
        weights = binary_weights(groups).astype(np.float32)
        if not np.isfinite(weights).all() or not np.all(weights > 0):
            raise E7BContractError(f"{fold}/{stage}: BINARY weight invalid")
        contracts[stage] = {
            "rows": part.height,
            "races": part["race_id"].n_unique(),
            "race_days": part["race_date_local"].n_unique(),
            "dates": [part["race_date_local"].min(), part["race_date_local"].max()],
            "keys_sha256": key_sha256(part),
            "groups_sha256": array_sha256(groups),
            "labels_sha256": array_sha256(labels),
            "weights_float32_sha256": array_sha256(weights),
            "matrices": shared[stage],
        }
    return (
        parts,
        matrices,
        {
            "encoder": {
                "fit_scope": f"{fold}/selector_fit_only",
                "fit_rows": parts["fit"].height,
                "base_feature_names": features,
                "expanded_feature_names": expanded.feature_names,
                "categorical_features": encoder.categorical_features,
                "categorical_indices": encoder.categorical_indices,
                "category_maps": encoder.category_maps,
                "unknown_category_policy": "NaN",
                "numeric_null_policy": "NaN from existing transform_features",
            },
            "partitions": contracts,
        },
    )


def baseline_reproduction(fold: str, result: dict[str, Any], temperature: float) -> dict[str, Any]:
    prior = E6B / fold / ARMS[0]
    prior_run = json.loads((prior / "run.json").read_text())
    iteration = result["best_iteration"]
    if iteration != prior_run["best_iteration"]:
        raise E7BContractError(f"{fold}: baseline best_iteration changed")
    t_error = abs(temperature - prior_run["temperature"]["solution"]["temperature"])
    if t_error > 1e-10:
        raise E7BContractError(f"{fold}: baseline temperature changed")
    errors = {}
    for stage in ("calibration", "evaluation"):
        current = result[f"{stage}_predictions"]
        old = pl.read_parquet(prior / f"{stage}_predictions.parquet")
        validate_exact_keys(old, current, name=f"{fold}/baseline/{stage}")
        joined = old.join(
            current,
            on=["race_id", "race_entry_id", "horse_number"],
            suffix="_new",
            validate="1:1",
        )
        errors[stage] = {
            name: float((joined[name] - joined[f"{name}_new"]).abs().max() or 0.0)
            for name in ("raw_margin", "prob_win")
        }
        if max(errors[stage].values()) > 1e-12:
            raise E7BContractError(f"{fold}: baseline {stage} predictions changed")
    metric_errors = {
        name: abs(value - prior_run["evaluation_metrics"][name])
        for name, value in result["evaluation"]["metrics"].items()
        if isinstance(value, float) and name in prior_run["evaluation_metrics"]
    }
    if metric_errors and max(metric_errors.values()) > 1e-12:
        raise E7BContractError(f"{fold}: baseline evaluation metrics changed")
    return {
        "best_iteration": iteration,
        "temperature_abs_error": t_error,
        "prediction_max_abs_errors": errors,
        "metric_max_abs_error": max(metric_errors.values(), default=0.0),
        "E6B_baseline_run_sha256": sha(prior / "run.json"),
    }


def run_fold(
    fold: str,
    parts: dict[str, pl.DataFrame],
    matrices: dict[str, dict[str, np.ndarray]],
    features: list[str],
    encoder: dict[str, Any],
    output: Path,
    ledger: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    fold_dir = output / fold
    fold_dir.mkdir()
    categorical = encoder["categorical_features"]

    def record(stage: str, arm: str) -> None:
        ledger["fit_calls_started"] += 1
        ledger["events"].append({"fold": fold, "arm": arm, "fit": stage, "status": "started"})
        save_json(output / "fit_ledger.json", ledger)

    def prepared(arm: str):
        arm_dir = fold_dir / arm
        arm_dir.mkdir()
        matrix = matrices[arm]
        names = features if arm == ARMS[0] else features + list(FEATURES)
        record("selector", arm)
        selector, selector_audit = train_selector(
            "BINARY",
            matrix["fit"],
            parts["fit"]["win"].to_numpy().astype(np.int8),
            group_sizes(parts["fit"]),
            matrix["tune"],
            parts["tune"]["win"].to_numpy().astype(np.int8),
            group_sizes(parts["tune"]),
            names,
            categorical,
            arm_dir,
        )
        ledger["fit_calls_completed"] += 1
        ledger["events"][-1]["status"] = "completed"
        save_json(output / "fit_ledger.json", ledger)
        combined = pl.concat([parts["fit"], parts["tune"]], how="vertical")
        combined_matrix = np.vstack([matrix["fit"], matrix["tune"]])
        record("refit", arm)
        booster, refit_audit = refit(
            "BINARY",
            combined_matrix,
            combined["win"].to_numpy().astype(np.int8),
            group_sizes(combined),
            names,
            categorical,
            selector.best_iteration,
            arm_dir,
        )
        ledger["fit_calls_completed"] += 1
        ledger["events"][-1]["status"] = "completed"
        save_json(output / "fit_ledger.json", ledger)
        calibration_raw = np.asarray(
            booster.predict(
                matrix["calibration"],
                raw_score=True,
                num_iteration=selector.best_iteration,
            )
        )
        diagnosis = diagnose_temperature(
            calibration_raw,
            parts["calibration"]["win"].to_numpy().astype(np.int8),
            group_sizes(parts["calibration"]),
        )
        temperature = diagnosis.to_dict()
        temperature["calibration_raw_sha256"] = array_sha256(calibration_raw)
        save_json(arm_dir / "temperature.json", temperature)
        return prepare_diagnosed_arm(
            arm,
            diagnosis,
            payload={
                "booster": booster,
                "arm_dir": arm_dir,
                "selector_audit": selector_audit,
                "refit_audit": refit_audit,
                "temperature": temperature,
            },
        )

    def evaluate(item):
        arm = item.name
        payload = item.payload
        t = item.temperature_diagnostic.solution.temperature
        matrix = matrices[arm]
        calibration = make_predictions(
            payload["booster"],
            parts["calibration"],
            matrix["calibration"],
            group_sizes(parts["calibration"]),
            t,
        )
        evaluation = make_predictions(
            payload["booster"],
            parts["evaluation"],
            matrix["evaluation"],
            group_sizes(parts["evaluation"]),
            t,
        )
        cal_result = evaluate_arm(
            parts["calibration"], calibration, temperature=t, name=f"{fold}/{arm}/cal"
        )
        eval_result = evaluate_arm(
            parts["evaluation"], evaluation, temperature=t, name=f"{fold}/{arm}/eval"
        )
        reload_errors = evaluate_reload(payload["booster"], payload["arm_dir"], parts, matrix, t)
        return {
            "calibration_predictions": calibration,
            "evaluation_predictions": evaluation,
            "calibration_coverage": cal_result["coverage"],
            "evaluation": eval_result,
            "reload": reload_errors,
            "temperature": payload["temperature"],
            "best_iteration": payload["selector_audit"]["best_iteration"],
        }

    results = orchestrate_fold(ARMS, ARMS, prepared, evaluate)
    baseline = baseline_reproduction(
        fold, results[ARMS[0]], results[ARMS[0]]["temperature"]["solution"]["temperature"]
    )
    save_json(fold_dir / "baseline_reproduction.json", baseline)
    for arm in ARMS:
        arm_dir = fold_dir / arm
        result = results[arm]
        result["calibration_predictions"].write_parquet(arm_dir / "calibration_predictions.parquet")
        result["evaluation_predictions"].write_parquet(arm_dir / "evaluation_predictions.parquet")
        result["evaluation"]["per_race"].write_parquet(arm_dir / "evaluation_per_race.parquet")
        save_json(
            arm_dir / "run.json",
            {
                "fold": fold,
                "arm": arm,
                "objective": "BINARY custom weighted Bernoulli",
                "best_iteration": result["best_iteration"],
                "temperature": result["temperature"],
                "calibration_coverage": result["calibration_coverage"],
                "evaluation_coverage": result["evaluation"]["coverage"],
                "evaluation_metrics": result["evaluation"]["metrics"],
                "reload_max_errors": result["reload"],
                "selector_callback_audit": "selector_callback_audit.json",
                "refit_audit": "refit_audit.json",
            },
        )
    comparison, paired = paired_comparison(
        {arm: results[arm]["evaluation"] for arm in ARMS},
        expected_races=PARTITIONS[fold]["evaluation"][3],
    )
    paired.write_parquet(fold_dir / "paired_race_losses.parquet")
    save_json(fold_dir / "comparison.json", comparison)
    return comparison, {arm: results[arm]["evaluation"] for arm in ARMS}


def save_manifest(output: Path, before: dict[str, str], status: str) -> None:
    after = frozen_hashes()
    if before != after:
        raise E7BContractError("sealed source/registry changed during E7-B")
    save_json(
        output / "artifact_manifest.json",
        {
            "status": status,
            "frozen_hashes_before": before,
            "frozen_hashes_after": after,
            "frozen_unchanged": True,
            "outputs": {
                str(path.relative_to(ROOT)): sha(path)
                for path in sorted(output.rglob("*"))
                if path.is_file() and path.name != "artifact_manifest.json"
            },
            "model_fit_and_evaluation_upper_bound": "2026-02-28",
            "database_queried": False,
            "operating_registry_modified": False,
        },
    )


def main() -> int:
    output = output_path()
    output.mkdir(parents=True)
    started = time.time()
    ledger: dict[str, Any] = {
        "fit_calls_started": 0,
        "fit_calls_completed": 0,
        "planned_fit_calls": 12,
        "events": [],
        "status": "preflight",
    }
    save_json(output / "fit_ledger.json", ledger)
    frozen_before = frozen_hashes()
    try:
        verify_sealed()
        frame, features, input_audit = preflight_input()
        all_inputs = {fold: fold_input(frame, features, fold) for fold in PARTITIONS}
        evaluation_ids = [
            set(all_inputs[fold][0]["evaluation"]["race_id"].to_list()) for fold in PARTITIONS
        ]
        if len(set.union(*evaluation_ids)) != 407 or sum(map(len, evaluation_ids)) != 407:
            raise E7BContractError("evaluation race overlap or denominator changed")
        save_json(output / "input_contract.json", input_audit)
        save_json(
            output / "execution_protocol.json",
            {
                "status": "sealed_before_first_tree_fit",
                "authorization": str(AUTHORIZATION.relative_to(ROOT)),
                "authorization_sha256": sha(AUTHORIZATION),
                "draft": str(DRAFT.relative_to(ROOT)),
                "draft_sha256": sha(DRAFT),
                "candidate_names": list(ARMS),
                "feature_counts": {ARMS[0]: 136, ARMS[1]: 148},
                "sequence_feature_names": list(FEATURES),
                "input": input_audit,
                "folds": {fold: values[2] for fold, values in all_inputs.items()},
                "planned_fit_calls": 12,
                "num_boost_round": 1200,
                "early_stopping_patience": 80,
                "parameters": {
                    key: value for key, value in params("CUSTOM").items() if key != "objective"
                },
                "objective": "custom weighted Bernoulli BINARY for both arms",
                "temperature": "existing beta endpoint/root; boundary rejects evaluation",
                "common_gate": "run_e6b_fold via E7-B orchestrate_fold",
                "evaluation": "race-equal stable log-domain winner-set NLL; E6-B secondary metrics",
                "bootstrap": {"paired_race_and_date_cluster": 5000, "seed": 20260911},
                "failure_policy": "stop fold and pooled comparison; no retry or tuning",
                "frozen_hashes_before": frozen_before,
                "code_sha256": {
                    "runner": sha(Path(__file__)),
                    "evaluator": sha(ROOT / "src/horse_racing/analysis/confirmed_starter_e7b.py"),
                    "E5B_runner": sha(ROOT / "scripts/run_confirmed_starter_e5b.py"),
                    "E5B_evaluator": sha(
                        ROOT / "src/horse_racing/analysis/confirmed_starter_e5b.py"
                    ),
                    "E6B_reload_helper": sha(ROOT / "scripts/run_confirmed_starter_e6b.py"),
                    "E6A_common_gate": sha(
                        ROOT / "src/horse_racing/analysis/confirmed_starter_e6a_v2.py"
                    ),
                },
                "environment": {
                    "python": platform.python_version(),
                    "lightgbm": lgb.__version__,
                    "numpy": np.__version__,
                    "polars": pl.__version__,
                    "scipy": importlib.metadata.version("scipy"),
                    "platform": platform.platform(),
                },
            },
        )
        ledger["status"] = "running"
        save_json(output / "fit_ledger.json", ledger)
        fold_results: dict[str, Any] = {}
        pooled: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
        for fold, (parts, matrices, contract) in all_inputs.items():
            ledger["current_fold"] = fold
            save_json(output / "fit_ledger.json", ledger)
            comparison, results = run_fold(
                fold, parts, matrices, features, contract["encoder"], output, ledger
            )
            fold_results[fold] = comparison
            for arm in ARMS:
                pooled[arm].append(results[arm])
            ledger["completed_folds"] = list(fold_results)
            save_json(output / "fit_ledger.json", ledger)
        if ledger["fit_calls_started"] != 12 or ledger["fit_calls_completed"] != 12:
            raise E7BContractError("12-fit budget did not complete exactly")
        pooled_results = {}
        for arm in ARMS:
            joined = pl.concat([result["joined"] for result in pooled[arm]], how="vertical").sort(
                "race_date_local", "race_id", "race_entry_id"
            )
            validate_exact_keys(joined, joined, name="pooled unique keys")
            per_race = pl.concat(
                [result["per_race"] for result in pooled[arm]], how="vertical"
            ).sort("race_id")
            pooled_results[arm] = {
                "joined": joined,
                "per_race": per_race,
                "metrics": pooled_metrics(joined, per_race),
            }
        overall, paired = paired_comparison(pooled_results, expected_races=407)
        paired.write_parquet(output / "pooled_paired_race_losses.parquet")
        comparison = {
            "status": "all_three_folds_completed",
            "folds": fold_results,
            "pooled": overall,
            "interpretation": {
                "single_seed": 42,
                "reused_development_data": True,
                "not_independent_future_test": True,
                "bundle_not_pure_sequence_effect": True,
                "causal_or_individual_feature_contribution_claimed": False,
                "bootstrap_conditional_on_saved_predictions": True,
                "operational_promotion": False,
            },
        }
        save_json(output / "comparison.json", comparison)
        ledger["status"] = "completed"
        ledger["elapsed_seconds"] = time.time() - started
        save_json(output / "fit_ledger.json", ledger)
        save_manifest(output, frozen_before, "completed")
        print(output)
        return 0
    except Exception as exc:
        ledger["status"] = "failed"
        ledger["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        ledger["elapsed_seconds"] = time.time() - started
        save_json(output / "fit_ledger.json", ledger)
        save_json(
            output / "failure.json",
            {
                "stage": ledger.get("current_fold", "preflight"),
                "reason": ledger["failure"],
                "fit_calls_started": ledger["fit_calls_started"],
                "fit_calls_completed": ledger["fit_calls_completed"],
                "completed_folds": ledger.get("completed_folds", []),
                "pooled_comparison_created": False,
            },
        )
        save_manifest(output, frozen_before, "failed")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
