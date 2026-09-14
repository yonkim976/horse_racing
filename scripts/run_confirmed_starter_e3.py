#!/usr/bin/env python3
"""Run the sealed E3 confirmed-starter N-vs-A controlled development study."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import pickle
import subprocess
import sys
from pathlib import Path
from typing import Any

import lightgbm
import numpy as np
import polars as pl

from horse_racing.analysis.confirmed_starter_e3 import (
    E3ContractError,
    evaluate_validation,
    key_sha256,
    paired_bootstrap,
    paired_date_cluster_bootstrap,
    sha256_file,
    validate_exact_keys,
    validate_pre_normalization,
    validate_predictions,
)
from horse_racing.analysis.experiments import (
    ModelRun,
    current_git_commit,
    hash_feature_names,
    new_run_id,
    record_run,
)
from horse_racing.analysis.lightgbm_model import (
    load_bundle,
    save_bundle,
    temporal_train_partitions,
    train_lightgbm_models,
    transform_features,
)

ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = ROOT / "data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m"
DATASET_PATH = INPUT_DIR / "dataset.parquet"
MANIFEST_PATH = INPUT_DIR / "manifest.json"
EVIDENCE_PATH = ROOT / "data/logs/pre_race_field_dnf_evidence_e1_v2_20260911.parquet"
DEFAULT_OUTPUT = ROOT / "data/experiments/confirmed_starter_e3_20260911"
EXPECTED_DATASET_SHA256 = "9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7"
EXPECTED_MANIFEST_SHA256 = "f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801"
EXPECTED_FEATURE_SHA256 = "b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48"
SEED = 42
BOOTSTRAP_SEED = 20260911
ITERATIONS = 5000
SPLIT_BOUNDS = {
    "train": (None, "2026-02-28"),
    "valid": ("2026-03-01", "2026-05-31"),
    "test": ("2026-06-01", None),
}
ESTIMATOR_PARAMS: dict[str, Any] = {
    "objective": "binary",
    "n_estimators": 1200,
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
    "random_state": SEED,
}
EXPECTED_PARTITIONS = {
    "N": {"fit": 8701, "tune": 1992, "calibration": 1800, "train": 12493},
    "A": {"fit": 8719, "tune": 2001, "calibration": 1808, "train": 12528},
}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _git_status() -> dict[str, Any]:
    completed = subprocess.run(
        ["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    paths = [line for line in completed.stdout.splitlines() if line]
    return {"head": current_git_commit(), "dirty": bool(paths), "status_short": paths}


def _state_counts(frame: pl.DataFrame) -> dict[str, int]:
    return {
        str(state): int(count) for state, count in frame.group_by("outcome_state").len().iter_rows()
    }


def _preflight(dataset: pl.DataFrame, manifest: dict[str, Any]) -> dict[str, Any]:
    if sha256_file(DATASET_PATH) != EXPECTED_DATASET_SHA256:
        raise E3ContractError("sealed H1 dataset hash mismatch")
    if sha256_file(MANIFEST_PATH) != EXPECTED_MANIFEST_SHA256:
        raise E3ContractError("sealed H1 manifest hash mismatch")
    selected = manifest["selected_feature_names"]
    if len(selected) != 136 or hash_feature_names(selected) != EXPECTED_FEATURE_SHA256:
        raise E3ContractError("selected feature contract mismatch")
    if dataset.filter(pl.col("race_date_local") > "2026-05-31").height:
        raise E3ContractError("post-bound actual row in H1 dataset")

    manifest_keys = pl.DataFrame(
        manifest["field_contract"]["expected_keys"],
        schema=["race_id", "race_entry_id"],
        orient="row",
    )
    validate_exact_keys(manifest_keys, dataset, name="manifest-vs-dataset")
    evidence = pl.read_parquet(EVIDENCE_PATH).filter(
        pl.col("outcome_state_e1").is_in(["normal_finish", "started_dnf", "disqualified"])
    )
    validate_exact_keys(evidence, dataset, name="evidence-vs-dataset")
    special = dataset.filter(pl.col("outcome_state") != "normal_finish")
    if special.height != 48:
        raise E3ContractError("special-state row count mismatch")
    if special.select(pl.sum("win"), pl.sum("top2"), pl.sum("top3")).row(0) != (0, 0, 0):
        raise E3ContractError("special-state binary labels are not zero")
    if (
        special["finish_position_target"].null_count() != 48
        or special["finish_time_ms_target"].null_count() != 48
        or special["auxiliary_rank_observed"].any()
        or special["auxiliary_finish_time_observed"].any()
    ):
        raise E3ContractError("special-state auxiliary masks invalid")
    return {
        "dataset_sha256": EXPECTED_DATASET_SHA256,
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "feature_names_sha256": EXPECTED_FEATURE_SHA256,
        "feature_count": len(selected),
        "dataset_rows": dataset.height,
        "dataset_races": dataset["race_id"].n_unique(),
        "dataset_key_sha256": key_sha256(dataset),
        "evidence_sha256": sha256_file(EVIDENCE_PATH),
        "missing_keys": 0,
        "extra_keys": 0,
        "duplicate_keys": 0,
        "labels_and_auxiliary_masks_valid": True,
    }


def _arm_frame(dataset: pl.DataFrame, arm: str) -> pl.DataFrame:
    train = dataset.filter(pl.col("race_date_local") <= "2026-02-28")
    valid = dataset.filter(
        (pl.col("race_date_local") >= "2026-03-01") & (pl.col("race_date_local") <= "2026-05-31")
    )
    if arm == "N":
        train = train.filter(pl.col("outcome_state") == "normal_finish")
    elif arm != "A":
        raise ValueError(arm)
    return pl.concat([train, valid], how="vertical")


def _partition_contract(frame: pl.DataFrame, arm: str) -> dict[str, Any]:
    fit, tune, calibration, bounds = temporal_train_partitions(frame, split_bounds=SPLIT_BOUNDS)
    train = pl.concat([fit, tune, calibration], how="vertical")
    valid = frame.filter(pl.col("race_date_local") >= "2026-03-01")
    observed = {
        "fit": fit.height,
        "tune": tune.height,
        "calibration": calibration.height,
        "train": train.height,
    }
    if observed != EXPECTED_PARTITIONS[arm]:
        raise E3ContractError(f"{arm}: partition count mismatch {observed}")
    expected_dates = {
        "fit_end": "2025-10-26",
        "tune_start": "2025-11-01",
        "tune_end": "2025-12-27",
        "calibration_start": "2025-12-28",
        "calibration_end": "2026-02-28",
    }
    if bounds != expected_dates:
        raise E3ContractError(f"{arm}: partition date mismatch {bounds}")
    if valid.height != 3051 or valid["race_id"].n_unique() != 288:
        raise E3ContractError(f"{arm}: validation denominator mismatch")
    return {
        "counts": observed,
        "dates": bounds,
        "state_counts": {
            "fit": _state_counts(fit),
            "tune": _state_counts(tune),
            "calibration": _state_counts(calibration),
            "train": _state_counts(train),
            "validation": _state_counts(valid),
        },
        "train_key_sha256": key_sha256(train),
        "validation_key_sha256": key_sha256(valid),
    }


def _save_component(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(value, handle, protocol=pickle.HIGHEST_PROTOCOL)


def _run_report(arm: str, run_id: str, metadata: dict[str, Any]) -> str:
    lines = [
        f"# E3 {arm} arm run",
        "",
        f"- run_id: `{run_id}`",
        f"- policy: `{metadata['training_policy']}`",
        "- input: sealed H1 retrospective actual-starter conditional A feature table",
        "- validation: 2026-03-01~2026-05-31 development validation; candidate selection에도 사용",
        "- test/holdout: 미평가",
        "- seed: 42 (single seed)",
        "",
        "## Best iterations and calibration",
        "",
        "| target | best iteration | selected calibration |",
        "|---|---:|---|",
    ]
    for target in ("win", "top2", "top3"):
        lines.append(
            f"| {target} | {metadata['best_iterations'][target]} | "
            f"{metadata['calibration_selected'][target]} |"
        )
    lines.extend(
        [
            "",
            "후보 raw/sigmoid/isotonic은 calibration 구간에서 적합된 뒤 같은 development "
            "validation binary log loss로 선택됐다. 이 수치는 독립 test 성능이 아니다.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output_root
    if output.exists():
        raise SystemExit(f"refusing to overwrite E3 output: {output}")
    output.mkdir(parents=True)

    dataset = pl.read_parquet(DATASET_PATH)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    preflight = _preflight(dataset, manifest)
    selected_features = list(manifest["selected_feature_names"])
    frames = {arm: _arm_frame(dataset, arm) for arm in ("N", "A")}
    partitions = {arm: _partition_contract(frame, arm) for arm, frame in frames.items()}
    valid_frames = {
        arm: frame.filter(pl.col("race_date_local") >= "2026-03-01")
        for arm, frame in frames.items()
    }
    validate_exact_keys(valid_frames["N"], valid_frames["A"], name="N-vs-A-validation")
    if (
        not valid_frames["N"]
        .select(selected_features, "win", "top2", "top3")
        .equals(valid_frames["A"].select(selected_features, "win", "top2", "top3"))
    ):
        raise E3ContractError("N/A validation feature or label values differ")
    special_validation = valid_frames["A"].filter(pl.col("outcome_state") != "normal_finish")
    if (
        special_validation.height != 13
        or special_validation["race_id"].n_unique() != 12
        or _state_counts(valid_frames["A"])
        != {"normal_finish": 3038, "started_dnf": 12, "disqualified": 1}
    ):
        raise E3ContractError("validation state contract mismatch")

    run_ids = {arm: new_run_id() for arm in ("N", "A")}
    protocol = {
        "study": "confirmed-starter E3 N-vs-A controlled development study",
        "created_before_training": True,
        "run_ids": run_ids,
        "input": preflight,
        "field_contract": (
            "retrospective confirmed-starter conditional A; start_minus_30m does not prove F_t"
        ),
        "feature_set": "racefit_canonical_history",
        "model_profile": "racefit_v5_sand",
        "selected_feature_names": selected_features,
        "partitions": partitions,
        "common_validation": {
            "rows": 3051,
            "races": 288,
            "normal_finish": 3038,
            "started_dnf": 12,
            "disqualified": 1,
            "special_state_races": 12,
            "key_sha256": key_sha256(valid_frames["A"]),
            "features_and_labels_identical_between_arms": True,
        },
        "arms": {
            "N": "normal_finish filter on train only; validation unfiltered; A predictors retained",
            "A": "all confirmed-starter states in train and validation",
        },
        "estimator_parameters": ESTIMATOR_PARAMS,
        "seed": SEED,
        "calibration_requested": "auto",
        "calibration_candidates": ["raw", "sigmoid", "isotonic"],
        "calibration_selection": (
            "target-specific minimum entry-weighted binary log loss on common development "
            "validation after race-total normalization"
        ),
        "primary_metric": {
            "name": "race_equal_weight_winner_set_nll",
            "delta": "A-N; negative favors A",
            "epsilon": 1e-15,
        },
        "secondary_metrics": [
            "entry-weighted win binary log loss/Brier",
            "prob_win expected-tie Top1/Top3/Top5 winner inclusion",
            "entry-weighted top2/top3 binary log loss/Brier",
        ],
        "bootstrap": {
            "paired_race": {"iterations": ITERATIONS, "seed": BOOTSTRAP_SEED},
            "paired_race_date_cluster": {"iterations": ITERATIONS, "seed": BOOTSTRAP_SEED},
        },
        "probability_sum_tolerance": 1e-8,
        "reload_prediction_tolerance": 1e-12,
        "git": _git_status(),
        "code_sha256": {
            str(Path(__file__).resolve().relative_to(ROOT)): sha256_file(Path(__file__).resolve()),
            "src/horse_racing/analysis/confirmed_starter_e3.py": sha256_file(
                ROOT / "src/horse_racing/analysis/confirmed_starter_e3.py"
            ),
            "src/horse_racing/analysis/lightgbm_model.py": sha256_file(
                ROOT / "src/horse_racing/analysis/lightgbm_model.py"
            ),
            "src/horse_racing/analysis/metrics.py": sha256_file(
                ROOT / "src/horse_racing/analysis/metrics.py"
            ),
        },
        "no_post_2026_05_31_actual_evaluation": True,
    }
    _write_json(output / "protocol.json", protocol)

    results: dict[str, Any] = {}
    joined_predictions: dict[str, pl.DataFrame] = {}
    race_losses: dict[str, pl.DataFrame] = {}
    ledger_path = output / "model_runs.jsonl"
    for arm in ("N", "A"):
        frame = frames[arm]
        if _partition_contract(frame, arm) != partitions[arm]:
            raise E3ContractError(f"{arm}: trainer-entry partition contract changed")
        trained = train_lightgbm_models(
            frame,
            feature_names=selected_features,
            dataset_version="confirmed_starter_e2_h1_remediation_retrospective",
            as_of_policy="start_minus_30m",
            seed=SEED,
            calibration="auto",
            hyperparameters=ESTIMATOR_PARAMS,
            split_bounds=SPLIT_BOUNDS,
        )
        run_id = run_ids[arm]
        run_dir = output / run_id
        run_dir.mkdir()
        model_path = run_dir / "model.pkl"
        save_bundle(trained.bundle, model_path)
        _save_component(run_dir / "encoder.pkl", trained.bundle.feature_encoder)
        for target, target_model in trained.bundle.targets.items():
            _save_component(run_dir / f"{target}_estimator.pkl", target_model.estimator)
            _save_component(run_dir / f"{target}_calibrator.pkl", target_model.calibrator)
        predictions_path = run_dir / "predictions_valid.parquet"
        trained.valid_predictions.write_parquet(predictions_path)

        valid = valid_frames[arm]
        joined, coverage = validate_predictions(valid, trained.valid_predictions, name=arm)
        metrics, per_race = evaluate_validation(joined)
        joined_predictions[arm] = joined
        race_losses[arm] = per_race
        matrix = transform_features(valid, trained.bundle.feature_encoder)
        pre_normalization = {}
        for target, target_model in trained.bundle.targets.items():
            raw = np.asarray(target_model.estimator.predict_proba(matrix)[:, 1], dtype=float)
            calibrated = target_model.calibrate(raw)
            pre_normalization[target] = validate_pre_normalization(
                raw, calibrated, arm=arm, target=target
            )

        reloaded = load_bundle(model_path).predict(valid)
        validate_exact_keys(trained.valid_predictions, reloaded, name=f"{arm}-reload")
        reload_join = trained.valid_predictions.join(
            reloaded, on=["race_id", "race_entry_id", "horse_number"], suffix="_reload"
        )
        reload_max = {
            column: float(
                (reload_join[column] - reload_join[f"{column}_reload"]).abs().max() or 0.0
            )
            for column in ("prob_win", "prob_top2", "prob_top3")
        }
        if max(reload_max.values()) > 1e-12:
            raise E3ContractError(f"{arm}: reload prediction mismatch {reload_max}")

        best_iterations = {
            target: model.best_iteration for target, model in trained.bundle.targets.items()
        }
        calibration_selected = {
            target: model.calibration_method for target, model in trained.bundle.targets.items()
        }
        candidates = {
            target: model.valid_candidates for target, model in trained.bundle.targets.items()
        }
        encoder_contract = {
            "feature_count": len(trained.bundle.feature_encoder.feature_names),
            "categorical_features": trained.bundle.feature_encoder.categorical_features,
            "category_maps_sha256": __import__("hashlib")
            .sha256(
                json.dumps(
                    trained.bundle.feature_encoder.category_maps,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
            .hexdigest(),
        }
        metadata = {
            "arm": arm,
            "run_id": run_id,
            "training_policy": protocol["arms"][arm],
            "partitions": partitions[arm],
            "encoder": encoder_contract,
            "best_iterations": best_iterations,
            "calibration_requested": "auto",
            "calibration_selected": calibration_selected,
            "calibration_candidate_metrics": candidates,
            "pre_normalization_finite_checks": pre_normalization,
            "coverage": coverage,
            "metrics": metrics,
            "reload_prediction": {
                "exactly_equal": all(value == 0.0 for value in reload_max.values()),
                "max_absolute_error": reload_max,
                "tolerance": 1e-12,
            },
            "libraries": {
                "python": sys.version.split()[0],
                "polars": pl.__version__,
                "numpy": np.__version__,
                "lightgbm": lightgbm.__version__,
                "scikit_learn": importlib.metadata.version("scikit-learn"),
            },
        }
        _write_json(run_dir / "run.json", metadata)
        (run_dir / "report.md").write_text(_run_report(arm, run_id, metadata), encoding="utf-8")
        artifact_paths = [
            model_path,
            run_dir / "encoder.pkl",
            predictions_path,
            run_dir / "run.json",
            run_dir / "report.md",
            *[run_dir / f"{target}_estimator.pkl" for target in ("win", "top2", "top3")],
            *[run_dir / f"{target}_calibrator.pkl" for target in ("win", "top2", "top3")],
        ]
        artifact_hashes = {
            str(path.relative_to(ROOT)): sha256_file(path) for path in artifact_paths
        }
        _write_json(run_dir / "artifact_manifest.json", artifact_hashes)
        flat_metrics = {
            key: float(value)
            for key, value in metrics.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        run = ModelRun(
            run_id=run_id,
            dataset_version="confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m",
            dataset_manifest={
                "dataset_sha256": EXPECTED_DATASET_SHA256,
                "manifest_sha256": EXPECTED_MANIFEST_SHA256,
                "feature_hash": EXPECTED_FEATURE_SHA256,
                "validation_key_sha256": partitions[arm]["validation_key_sha256"],
                "train_key_sha256": partitions[arm]["train_key_sha256"],
            },
            feature_names=selected_features,
            model_type="lightgbm_binary_bundle_research",
            hyperparameters={
                "estimator": ESTIMATOR_PARAMS,
                "arm": arm,
                "model_profile": "racefit_v5_sand",
                "calibration_requested": "auto",
                "calibration_selected": calibration_selected,
                "best_iterations": best_iterations,
                "artifact_hashes": artifact_hashes,
            },
            seed=SEED,
            train_period="2025-01-04~2026-02-28",
            valid_period="2026-03-01~2026-05-31",
            test_period="",
            metrics=flat_metrics,
            notes=(
                "E3 isolated research registry; common unfiltered A validation; "
                "development validation used for calibration candidate selection and reporting"
            ),
        )
        record_run(run, ledger_path=ledger_path)
        results[arm] = metadata

    for column in selected_features + ["win", "top2", "top3", "outcome_state"]:
        left = valid_frames["N"][column]
        right = valid_frames["A"][column]
        if not left.equals(right):
            raise E3ContractError(f"post-training validation divergence: {column}")

    paired = (
        race_losses["N"]
        .select(
            "race_id",
            "race_date",
            "contains_special_state",
            pl.col("winner_nll").alias("winner_nll_n"),
        )
        .join(
            race_losses["A"].select("race_id", pl.col("winner_nll").alias("winner_nll_a")),
            on="race_id",
            validate="1:1",
        )
        .with_columns((pl.col("winner_nll_a") - pl.col("winner_nll_n")).alias("delta_a_minus_n"))
    )
    paired_path = output / "paired_race_winner_nll.parquet"
    paired.write_parquet(paired_path)
    bootstraps = {
        "paired_race": paired_bootstrap(paired, iterations=ITERATIONS, seed=BOOTSTRAP_SEED),
        "paired_race_date_cluster": paired_date_cluster_bootstrap(
            paired, iterations=ITERATIONS, seed=BOOTSTRAP_SEED
        ),
    }
    subset_metrics = {}
    special_races = set(paired.filter(pl.col("contains_special_state") == 1)["race_id"].to_list())
    for arm in ("N", "A"):
        special_joined = joined_predictions[arm].filter(pl.col("race_id").is_in(special_races))
        other_joined = joined_predictions[arm].filter(~pl.col("race_id").is_in(special_races))
        subset_metrics[arm] = {
            "special_state_12_races": evaluate_validation(special_joined)[0],
            "other_276_races": evaluate_validation(other_joined)[0],
        }

    metric_names = [
        "race_equal_weight_winner_set_nll",
        "win_binary_log_loss",
        "win_brier",
        "top1_winner_inclusion",
        "top3_winner_inclusion",
        "top5_winner_inclusion",
        "top2_binary_log_loss",
        "top2_brier",
        "top3_binary_log_loss",
        "top3_brier",
    ]
    deltas = {
        name: results["A"]["metrics"][name] - results["N"]["metrics"][name] for name in metric_names
    }
    shuffled_checks = {}
    for arm in ("N", "A"):
        original = results[arm]["metrics"]
        for order_name, shuffled in {
            "reverse": joined_predictions[arm].reverse(),
            "random": joined_predictions[arm].sample(
                fraction=1.0, shuffle=True, seed=BOOTSTRAP_SEED
            ),
        }.items():
            reordered = evaluate_validation(shuffled)[0]
            differences = {
                metric: abs(reordered[metric] - original[metric])
                for metric in (
                    "top1_winner_inclusion",
                    "top3_winner_inclusion",
                    "top5_winner_inclusion",
                )
            }
            if max(differences.values()) > 1e-15:
                raise E3ContractError(f"{arm}/{order_name}: TopK order dependence {differences}")
            shuffled_checks[f"{arm}_{order_name}"] = differences

    comparison = {
        "delta_definition": "A-N; negative loss delta favors A",
        "scope": {
            "development_validation_rows": 3051,
            "development_validation_races": 288,
            "dates": ["2026-03-01", "2026-05-31"],
            "special_state_races": 12,
            "other_races": 276,
            "independent_test": False,
            "single_seed": SEED,
        },
        "run_ids": run_ids,
        "metrics": {arm: results[arm]["metrics"] for arm in ("N", "A")},
        "metric_deltas_a_minus_n": deltas,
        "coverage": {arm: results[arm]["coverage"] for arm in ("N", "A")},
        "calibration": {
            arm: {
                "selected": results[arm]["calibration_selected"],
                "candidates": results[arm]["calibration_candidate_metrics"],
            }
            for arm in ("N", "A")
        },
        "best_iterations": {arm: results[arm]["best_iterations"] for arm in ("N", "A")},
        "encoder": {arm: results[arm]["encoder"] for arm in ("N", "A")},
        "pre_normalization_finite_checks": {
            arm: results[arm]["pre_normalization_finite_checks"] for arm in ("N", "A")
        },
        "reload_prediction": {arm: results[arm]["reload_prediction"] for arm in ("N", "A")},
        "bootstrap": bootstraps,
        "fixed_diagnostic_subsets": subset_metrics,
        "topk_input_order_invariance": shuffled_checks,
        "tie_policy": (
            "predicted-probability ties use result-independent expected inclusion; official "
            "dead heats use the union winner event and summed winner probability"
        ),
        "unsupported": ["ordered TopK", "joint probabilities"],
        "conditional_interval": "stored predictions only; no retraining inside bootstrap",
    }
    _write_json(output / "comparison.json", comparison)

    report_lines = [
        "# Confirmed-starter E3 N-vs-A controlled development study",
        "",
        "두 arm은 동일한 retrospective A predictor 표와 공통 validation을 사용한다. N은 train의 "
        "정상완주만 사용하고 A는 train 전체를 사용하므로 fit뿐 아니라 tune·calibration 포함 정책도 "
        "비교한다. development validation은 calibration 후보 선택과 보고에 함께 사용됐으며 독립 "
        "test가 아니다.",
        "",
        "## Main results",
        "",
        "| metric | N | A | A-N |",
        "|---|---:|---:|---:|",
    ]
    for name in metric_names:
        report_lines.append(
            f"| {name} | {results['N']['metrics'][name]:.9f} | "
            f"{results['A']['metrics'][name]:.9f} | {deltas[name]:+.9f} |"
        )
    race_ci = bootstraps["paired_race"]["percentile_95_ci"]
    date_ci = bootstraps["paired_race_date_cluster"]["percentile_95_ci"]
    report_lines.extend(
        [
            "",
            "## Paired uncertainty",
            "",
            f"- race bootstrap 95% CI: [{race_ci[0]:+.9f}, {race_ci[1]:+.9f}]",
            f"- race-date cluster bootstrap 95% CI: [{date_ci[0]:+.9f}, {date_ci[1]:+.9f}]",
            "- 두 구간은 저장 예측에 조건부이며 bootstrap 내부 재학습은 없다.",
            "- bootstrap 음수 비율은 A가 실제로 우월할 확률로 해석하지 않는다.",
            "",
            "전체 288경주가 주 분석이다. 특수 상태 포함 12경주와 나머지 276경주는 고정 진단이며 "
            "결론 선택에 사용하지 않는다. 단일 seed 결과이고, 2026-06-01 이후 holdout은 평가하지 "
            "않았다. 운영 승격이나 성능 보장은 하지 않는다.",
            "",
        ]
    )
    (output / "report.md").write_text("\n".join(report_lines), encoding="utf-8")
    final_paths = [
        output / "protocol.json",
        output / "comparison.json",
        paired_path,
        output / "report.md",
        ledger_path,
    ]
    _write_json(
        output / "artifact_manifest.json",
        {str(path.relative_to(ROOT)): sha256_file(path) for path in final_paths},
    )
    print(output)
    print(json.dumps(run_ids, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
