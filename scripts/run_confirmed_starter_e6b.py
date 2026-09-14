#!/usr/bin/env python3
"""Run the sealed two-arm, three-fold E6-B retrospective development comparison."""

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
from horse_racing.analysis.confirmed_starter_e6a_v2 import (
    load_sealed_protocol_candidates,
    prepare_diagnosed_arm,
)
from horse_racing.analysis.confirmed_starter_e6b import (
    ARMS,
    EXTRA_FEATURES,
    PARTITIONS,
    E6BContractError,
    evaluate_arm,
    group_sizes,
    orchestrate_fold,
    paired_comparison,
    partition_frame,
    pooled_metrics,
    verify_feature_keyset,
    verify_shared_base_matrices,
)
from horse_racing.analysis.experiments import hash_feature_names
from horse_racing.analysis.lightgbm_model import (
    FeatureEncoder,
    fit_feature_encoder,
    transform_features,
)

# These sealed E5-B functions contain the approved native LightGBM callback,
# objective, per-iteration raw-margin audit, and selector/refit contracts.
from scripts.run_confirmed_starter_e5b import (
    binary_weights,
    make_predictions,
    params,
    refit,
    train_selector,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_BASE = ROOT / "data/experiments/confirmed_starter_e6b_20260913"
H1_DIR = ROOT / ("data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m")
H1 = H1_DIR / "dataset.parquet"
H1_MANIFEST = H1_DIR / "manifest.json"
E6A_DIR = ROOT / "data/experiments/confirmed_starter_e6a_v2_20260913_attempt4"
EXTRA = E6A_DIR / "confirmed_starter_e6a_v2_features.parquet"
DRAFT = E6A_DIR / "e6b_protocol_v2_draft.json"
E6A_MANIFEST = E6A_DIR / "artifact_manifest.json"
MATH = ROOT / "src/horse_racing/analysis/confirmed_starter_e5_r3r4.py"
E6A_HELPER = ROOT / "src/horse_racing/analysis/confirmed_starter_e6a_v2.py"
OPERATING_REGISTRY = ROOT / "data/experiments/model_runs.jsonl"
SEALED = {
    str(H1.relative_to(ROOT)): "9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7",
    str(
        H1_MANIFEST.relative_to(ROOT)
    ): "f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801",
    str(
        E6A_MANIFEST.relative_to(ROOT)
    ): "24c667ed059fbf59eabc7676ee9222279fbd895711f958a6241efd2b0789d3b2",
    str(
        EXTRA.relative_to(ROOT)
    ): "b6bc85abfcd6ce2fd1ee4dce621ad91d573942008308341a68af48b7ac45ae0d",
    str(
        DRAFT.relative_to(ROOT)
    ): "c9e8be81659da5f1315355845a46a0f32809f4c4a04de76e719265f9826490ad",
    str(
        E6A_HELPER.relative_to(ROOT)
    ): "d400aac796518a9e2da78a95849de330f6962d64d392f746697c257e5baacb4c",
    str(MATH.relative_to(ROOT)): "55c7dcf686e4bf068b488beb396ffe18fd37a9f179939195494b21f9f35982d0",
}
FEATURE_HASH = "b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48"
MAX_ROUNDS = 1200
PATIENCE = 80
BOOTSTRAP_SEED = 20260911
BOOTSTRAP_ITERATIONS = 5000


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


def all_frozen_paths() -> set[Path]:
    e6a = json.loads(E6A_MANIFEST.read_text())
    old = json.loads(
        (
            ROOT / "data/experiments/confirmed_starter_e6a_20260912_attempt4/preservation.json"
        ).read_text()
    )
    return (
        {ROOT / name for name in SEALED}
        | {ROOT / name for name in e6a["files"]}
        | {ROOT / name for name in old["after"]}
        | {ROOT / name for name in old["e5b_execution_code_matches_preserved_manifest"]}
        | {OPERATING_REGISTRY}
    )


def frozen_hashes() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(all_frozen_paths())}


def verify_sealed_files() -> dict[str, str]:
    for name, expected in SEALED.items():
        if sha(ROOT / name) != expected:
            raise E6BContractError(f"sealed hash mismatch: {name}")
    e6a = json.loads(E6A_MANIFEST.read_text())
    for name, expected in e6a["files"].items():
        if sha(ROOT / name) != expected:
            raise E6BContractError(f"E6-A v2 manifest entry mismatch: {name}")
    old = json.loads(
        (
            ROOT / "data/experiments/confirmed_starter_e6a_20260912_attempt4/preservation.json"
        ).read_text()
    )
    for name, expected in {
        **old["after"],
        **old["e5b_execution_code_matches_preserved_manifest"],
    }.items():
        if sha(ROOT / name) != expected:
            raise E6BContractError(f"upstream frozen hash mismatch: {name}")
    return frozen_hashes()


def preflight_input() -> tuple[pl.DataFrame, list[str], dict[str, Any]]:
    manifest = json.loads(H1_MANIFEST.read_text())
    h1 = pl.read_parquet(H1)
    extra = pl.read_parquet(EXTRA)
    if h1.height != 15579 or h1["race_id"].n_unique() != 1488:
        raise E6BContractError("H1 denominator changed")
    if h1["race_date_local"].max() != "2026-05-31":
        raise E6BContractError("H1 date upper bound changed")
    expected = pl.DataFrame(
        manifest["field_contract"]["expected_keys"],
        schema=["race_id", "race_entry_id"],
        orient="row",
    )
    validate_exact_keys(expected, h1, name="H1 manifest")
    verify_feature_keyset(h1, extra)
    features = manifest["selected_feature_names"]
    if len(features) != 136 or hash_feature_names(features) != FEATURE_HASH:
        raise E6BContractError("136 predictor name/order hash changed")
    for name in EXTRA_FEATURES:
        if name in features or name not in extra.columns or extra.schema[name] != pl.Float64:
            raise E6BContractError(f"extra numeric feature contract failed: {name}")
    if set(features) & set(EXTRA_FEATURES):
        raise E6BContractError("new feature collides with existing predictor")
    extra_values = extra.select("race_id", "race_entry_id", *EXTRA_FEATURES)
    full = h1.join(extra_values, on=["race_id", "race_entry_id"], how="left", validate="1:1")
    if full.height != h1.height:
        raise E6BContractError("feature join changed H1 denominator")
    if full["condition_carried_weight_delta_prev_start"].null_count() != 843:
        raise E6BContractError("sealed delta missing-count contract changed")
    return (
        full,
        features,
        {
            "H1_rows": h1.height,
            "H1_races": h1["race_id"].n_unique(),
            "H1_key_sha256": key_sha256(h1),
            "E6A_v2_key_sha256": key_sha256(extra),
            "base_feature_names_sha256": FEATURE_HASH,
            "added_feature_names": list(EXTRA_FEATURES),
            "added_feature_null_counts": {
                name: extra[name].null_count() for name in EXTRA_FEATURES
            },
            "source_unverified_delta_null_rows": 17,
            "post_2026_02_28_rows_used_for_model": 0,
        },
    )


def fold_input(
    frame: pl.DataFrame, features: list[str], fold: str
) -> tuple[dict[str, pl.DataFrame], dict[str, dict[str, np.ndarray]], dict[str, Any]]:
    parts = {stage: partition_frame(frame, fold, stage) for stage in PARTITIONS[fold]}
    dates = [PARTITIONS[fold][stage] for stage in ("fit", "tune", "calibration", "evaluation")]
    if not (dates[0][1] < dates[1][0] <= dates[1][1] < dates[2][0] <= dates[2][1] < dates[3][0]):
        raise E6BContractError(f"{fold}: time order invalid")
    base_encoder = fit_feature_encoder(parts["fit"], features)
    expanded_encoder = FeatureEncoder(
        features + list(EXTRA_FEATURES),
        base_encoder.categorical_features.copy(),
        base_encoder.category_maps.copy(),
    )
    matrices = {
        ARMS[0]: {stage: transform_features(part, base_encoder) for stage, part in parts.items()},
        ARMS[1]: {
            stage: transform_features(part, expanded_encoder) for stage, part in parts.items()
        },
    }
    shared = verify_shared_base_matrices(matrices[ARMS[0]], matrices[ARMS[1]])
    contracts = {}
    for stage, part in parts.items():
        groups = group_sizes(part)
        labels = part["win"].to_numpy().astype(np.int8)
        if not np.isin(labels, [0, 1]).all():
            raise E6BContractError(f"{fold}/{stage}: nonbinary winner indicator")
        if int(groups.sum()) != part.height:
            raise E6BContractError(f"{fold}/{stage}: group sum mismatch")
        if any(int(race["win"].sum()) < 1 for race in part.partition_by("race_id")):
            raise E6BContractError(f"{fold}/{stage}: winnerless race")
        weights = binary_weights(groups)
        if not np.isfinite(weights).all() or not np.all(weights > 0):
            raise E6BContractError(f"{fold}/{stage}: weight invalid")
        contracts[stage] = {
            "rows": part.height,
            "races": part["race_id"].n_unique(),
            "race_days": part["race_date_local"].n_unique(),
            "dates": [part["race_date_local"].min(), part["race_date_local"].max()],
            "keys_sha256": key_sha256(part),
            "groups_sha256": array_sha256(groups),
            "labels_sha256": array_sha256(labels),
            "weights_float32_sha256": array_sha256(weights.astype(np.float32)),
            "matrices": shared[stage],
        }
    if len(base_encoder.feature_names) != 136 or len(expanded_encoder.feature_names) != 139:
        raise E6BContractError("encoder feature count changed")
    encoder = {
        "fit_scope": f"{fold}/selector_fit_only",
        "fit_rows": parts["fit"].height,
        "fit_races": parts["fit"]["race_id"].n_unique(),
        "base_feature_names": features,
        "expanded_feature_names": expanded_encoder.feature_names,
        "categorical_features": base_encoder.categorical_features,
        "categorical_indices": base_encoder.categorical_indices,
        "category_maps": base_encoder.category_maps,
        "unknown_category_policy": "NaN",
        "numeric_null_policy": "NaN from existing transform_features",
    }
    return parts, matrices, {"encoder": encoder, "partitions": contracts}


def evaluate_reload(
    booster: lgb.Booster,
    arm_dir: Path,
    parts: dict[str, pl.DataFrame],
    matrices: dict[str, np.ndarray],
    temperature: float,
) -> dict[str, Any]:
    reloaded = lgb.Booster(model_file=str(arm_dir / "refit_model.txt"))
    errors = {}
    for stage in ("calibration", "evaluation"):
        original = make_predictions(
            booster, parts[stage], matrices[stage], group_sizes(parts[stage]), temperature
        )
        saved = make_predictions(
            reloaded, parts[stage], matrices[stage], group_sizes(parts[stage]), temperature
        )
        joined = original.join(
            saved,
            on=["race_id", "race_entry_id", "horse_number"],
            suffix="_reloaded",
            validate="1:1",
        )
        errors[stage] = {
            column: float((joined[column] - joined[f"{column}_reloaded"]).abs().max() or 0.0)
            for column in ("raw_margin", "prob_win")
        }
        if max(errors[stage].values()) > 1e-12:
            raise E6BContractError(f"{stage}: refit reload mismatch")
    return errors


def run_fold(
    fold: str,
    parts: dict[str, pl.DataFrame],
    matrices: dict[str, dict[str, np.ndarray]],
    features: list[str],
    encoder: dict[str, Any],
    output: Path,
    protocol_candidates: tuple[str, str],
    ledger: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    fold_dir = output / fold
    fold_dir.mkdir()
    prepared: dict[str, dict[str, Any]] = {}
    categorical = encoder["categorical_features"]

    def record(stage: str, arm: str) -> None:
        ledger["fit_calls_started"] += 1
        ledger["events"].append({"fold": fold, "arm": arm, "fit": stage, "status": "started"})
        save_json(output / "fit_ledger.json", ledger)

    def prepare(arm: str):
        arm_dir = fold_dir / arm
        arm_dir.mkdir()
        matrix = matrices[arm]
        arm_features = features if arm == ARMS[0] else features + list(EXTRA_FEATURES)
        fit_labels = parts["fit"]["win"].to_numpy().astype(np.int8)
        tune_labels = parts["tune"]["win"].to_numpy().astype(np.int8)
        record("selector", arm)
        selector, selector_audit = train_selector(
            "BINARY",
            matrix["fit"],
            fit_labels,
            group_sizes(parts["fit"]),
            matrix["tune"],
            tune_labels,
            group_sizes(parts["tune"]),
            arm_features,
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
            arm_features,
            categorical,
            selector.best_iteration,
            arm_dir,
        )
        ledger["fit_calls_completed"] += 1
        ledger["events"][-1]["status"] = "completed"
        save_json(output / "fit_ledger.json", ledger)
        calibration_raw = np.asarray(
            booster.predict(
                matrix["calibration"], raw_score=True, num_iteration=selector.best_iteration
            )
        )
        diagnostic = diagnose_temperature(
            calibration_raw,
            parts["calibration"]["win"].to_numpy().astype(np.int8),
            group_sizes(parts["calibration"]),
        )
        temperature = diagnostic.to_dict()
        temperature["calibration_raw_sha256"] = array_sha256(calibration_raw)
        save_json(arm_dir / "temperature.json", temperature)
        prepared[arm] = {
            "booster": booster,
            "arm_dir": arm_dir,
            "selector": selector_audit,
            "refit": refit_audit,
            "temperature": temperature,
        }
        return prepare_diagnosed_arm(arm, diagnostic, payload=prepared[arm])

    def evaluate(item):
        arm = item.name
        payload = item.payload
        booster = payload["booster"]
        temperature = item.temperature_diagnostic.solution.temperature
        matrix = matrices[arm]
        calibration = make_predictions(
            booster,
            parts["calibration"],
            matrix["calibration"],
            group_sizes(parts["calibration"]),
            temperature,
        )
        evaluation = make_predictions(
            booster,
            parts["evaluation"],
            matrix["evaluation"],
            group_sizes(parts["evaluation"]),
            temperature,
        )
        cal_result = evaluate_arm(
            parts["calibration"], calibration, temperature=temperature, name=f"{fold}/{arm}/cal"
        )
        eval_result = evaluate_arm(
            parts["evaluation"], evaluation, temperature=temperature, name=f"{fold}/{arm}/eval"
        )
        reload_errors = evaluate_reload(booster, payload["arm_dir"], parts, matrix, temperature)
        return {
            "calibration_predictions": calibration,
            "evaluation_predictions": evaluation,
            "calibration_coverage": cal_result["coverage"],
            "evaluation": eval_result,
            "reload": reload_errors,
            "temperature": payload["temperature"],
            "best_iteration": payload["selector"]["best_iteration"],
        }

    results = orchestrate_fold(protocol_candidates, protocol_candidates, prepare, evaluate)
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
    compare, paired = paired_comparison(
        {arm: results[arm]["evaluation"] for arm in ARMS},
        expected_races=PARTITIONS[fold]["evaluation"][3],
    )
    paired.write_parquet(fold_dir / "paired_race_losses.parquet")
    save_json(fold_dir / "comparison.json", compare)
    return compare, {arm: results[arm]["evaluation"] for arm in ARMS}


def save_manifest(output: Path, before: dict[str, str], status: str) -> None:
    after = frozen_hashes()
    if before != after:
        raise E6BContractError("frozen input or registry changed during E6-B")
    paths = sorted(
        path
        for path in output.rglob("*")
        if path.is_file() and path.name != "artifact_manifest.json"
    )
    save_json(
        output / "artifact_manifest.json",
        {
            "study": "E6-B two-arm three-fold carried-weight development study",
            "status": status,
            "frozen_hashes_before": before,
            "frozen_hashes_after": after,
            "frozen_unchanged": True,
            "outputs": {str(path.relative_to(ROOT)): sha(path) for path in paths},
            "actual_result_upper_bound_for_input_contract": "2026-05-31",
            "model_fit_and_evaluation_upper_bound": "2026-02-28",
            "post_2026_05_31_actual_rows_accessed": False,
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
        verify_sealed_files()
        candidates = load_sealed_protocol_candidates(DRAFT, SEALED[str(DRAFT.relative_to(ROOT))])
        if candidates != ARMS:
            raise E6BContractError("sealed draft arm identities changed")
        frame, features, input_audit = preflight_input()
        all_inputs = {fold: fold_input(frame, features, fold) for fold in PARTITIONS}
        evaluation_ids = [
            set(all_inputs[fold][0]["evaluation"]["race_id"].to_list()) for fold in PARTITIONS
        ]
        if len(set.union(*evaluation_ids)) != 407 or sum(map(len, evaluation_ids)) != 407:
            raise E6BContractError("evaluation folds overlap or denominator changed")
        save_json(output / "input_contract.json", input_audit)
        save_json(
            output / "execution_protocol.json",
            {
                "status": "sealed_before_first_tree_fit",
                "authorization": "docs/CONFIRMED_STARTER_E6B_AGENT_PROMPT_2026-09-13.md",
                "authorization_sha256": sha(
                    ROOT / "docs/CONFIRMED_STARTER_E6B_AGENT_PROMPT_2026-09-13.md"
                ),
                "candidate_names": list(candidates),
                "objective": "custom weighted Bernoulli BINARY for both arms",
                "feature_counts": {ARMS[0]: 136, ARMS[1]: 139},
                "added_features": list(EXTRA_FEATURES),
                "input": input_audit,
                "folds": {fold: values[2] for fold, values in all_inputs.items()},
                "planned_fit_calls": 12,
                "num_boost_round": MAX_ROUNDS,
                "early_stopping_patience": PATIENCE,
                "common_parameters": {
                    key: value for key, value in params("CUSTOM").items() if key != "objective"
                },
                "temperature": {
                    "adapter": "diagnose_temperature",
                    "log_T_bounds": [-4, 4],
                    "structural_flat_T": 1,
                    "boundary_policy": "stop without evaluation",
                },
                "evaluation_gate": "run_e6b_fold through orchestrate_fold",
                "metric": "race-equal stable log-domain winner-set NLL",
                "secondary": [
                    "race-equal soft-label CE",
                    "entry-equal binary NLL epsilon=1e-15",
                    "entry-equal Brier",
                    "expected-tie Top1/3/5",
                ],
                "bootstrap": {
                    "paired_race": {"iterations": BOOTSTRAP_ITERATIONS, "seed": BOOTSTRAP_SEED},
                    "race_date_cluster": {
                        "iterations": BOOTSTRAP_ITERATIONS,
                        "seed": BOOTSTRAP_SEED,
                    },
                },
                "failure_policy": "stop current fold and all pooled comparison; preserve artifacts",
                "sealed_source_hashes": SEALED,
                "frozen_hashes_before": frozen_before,
                "code_sha256": {
                    "runner": sha(Path(__file__)),
                    "evaluator": sha(ROOT / "src/horse_racing/analysis/confirmed_starter_e6b.py"),
                    "E5B_runner": sha(ROOT / "scripts/run_confirmed_starter_e5b.py"),
                    "E5B_evaluator": sha(
                        ROOT / "src/horse_racing/analysis/confirmed_starter_e5b.py"
                    ),
                    "math_adapter": sha(MATH),
                    "E6A_gate": sha(E6A_HELPER),
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
            compare, results = run_fold(
                fold,
                parts,
                matrices,
                features,
                contract["encoder"],
                output,
                candidates,
                ledger,
            )
            fold_results[fold] = compare
            for arm in ARMS:
                pooled[arm].append(results[arm])
            ledger["completed_folds"] = list(fold_results)
            save_json(output / "fit_ledger.json", ledger)
        if ledger["fit_calls_started"] != 12 or ledger["fit_calls_completed"] != 12:
            raise E6BContractError("12-fit budget not completed exactly")
        pooled_results = {}
        for arm in ARMS:
            joined = pl.concat([result["joined"] for result in pooled[arm]], how="vertical").sort(
                "race_date_local", "race_id", "race_entry_id"
            )
            validate_exact_keys(joined, joined, name="pooled unique keys")
            per_race = pl.concat(
                [result["per_race"] for result in pooled[arm]], how="vertical"
            ).sort("race_id")
            metrics = pooled_metrics(joined, per_race)
            pooled_results[arm] = {"joined": joined, "per_race": per_race, "metrics": metrics}
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
                "causal_effect_or_individual_feature_contribution_claimed": False,
                "bootstrap_conditional_on_saved_predictions": True,
                "operational_promotion": False,
            },
        }
        save_json(output / "comparison.json", comparison)
        base_nll = overall["metrics"][ARMS[0]]["race_equal_winner_set_nll"]
        added_nll = overall["metrics"][ARMS[1]]["race_equal_winner_set_nll"]
        delta_nll = overall["metric_deltas_added_minus_base"]["race_equal_winner_set_nll"]
        report = [
            "# Confirmed-starter E6-B 후향 개발 비교",
            "",
            "세 fold와 정확히 12 fit을 완료했다. 독립 미래 성능·운영 승격 주장은 하지 않는다.",
            "",
            f"BASE_136 pooled NLL: {base_nll:.12f}",
            f"CURRENT_WEIGHT_A_PREV pooled NLL: {added_nll:.12f}",
            f"Delta (added-base): {delta_nll:+.12f}",
            "",
            "원문 미확인 직전 출발 중량 17건의 delta null을 유지했다.",
        ]
        (output / "report.md").write_text("\n".join(report) + "\n")
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
