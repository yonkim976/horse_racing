#!/usr/bin/env python3
"""Fit exactly the approved conditional order heads, then freeze eval joint probabilities."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import itertools
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import order_head_core as core
import preflight


ROOT = preflight.ROOT
STUDY = preflight.STUDY
OUT = preflight.OUT
FIT_APPROVAL = OUT / "ROOT_FIT_APPROVAL.json"
FIT_SOURCE_LOCK = OUT / "FIT_SOURCE_LOCK.json"
FIT_ARTIFACTS = OUT / "FIT_ARTIFACTS.json"
FIT_RECEIPT = OUT / "FIT_RECEIPT.json"
PREDICTIONS = OUT / "evaluation_ordered_joint.parquet"
PREDICTION_RECEIPT = OUT / "PREDICTION_RECEIPT.json"
IMPLEMENTATION_SELFTEST = OUT / "IMPLEMENTATION_SELFTEST.json"
ROOT_STANDARDIZATION = ROOT / "jeju/research/20261017_order_head_rootreview_v1/ROOT_H1_STANDARDIZATION.json"
ROOT_STANDARDIZATION_SHA256 = "ec064fab6b6908dde891a877d6615a083feaacda1cc618307e25002d04e695c9"
ROOT_REVIEW = ROOT / "jeju/research/20261017_order_head_rootreview_v1/ROOT_CORE_REVIEW.json"
ROOT_TRIPLE_FILES = {
    (year, half): ROOT / f"jeju/research/20261017_order_head_rootreview_v1/ROOT_TRIPLES_{year}_{half}.npz"
    for year in (2024, 2025, 2026) for half in ("H1", "H2")
}
PIPELINE_SCRIPT = STUDY / "fit_predict.py"
CORE_SCRIPT = STUDY / "order_head_core.py"
MODEL_LABEL = "F1_STYLE6_COND_ORDER_V1"
OUTPUT_COLUMNS = [
    "evaluation_year", "race_date", "race_id", "distance_m", "field_n",
    "horse_no_1", "horse_no_2", "horse_no_3", "q_top3_set",
    "p_conditional_order", "p_ordered_joint",
    "control_p_conditional_order", "control_p_ordered_joint",
    "uniform_p_conditional_order", "uniform_p_ordered_joint", "model_label",
]
OUTPUT_SCHEMA = pa.schema([
    ("evaluation_year", pa.int16()), ("race_date", pa.string()), ("race_id", pa.string()),
    ("distance_m", pa.int32()), ("field_n", pa.int16()),
    ("horse_no_1", pa.int16()), ("horse_no_2", pa.int16()), ("horse_no_3", pa.int16()),
    ("q_top3_set", pa.float64()), ("p_conditional_order", pa.float64()),
    ("p_ordered_joint", pa.float64()), ("control_p_conditional_order", pa.float64()),
    ("control_p_ordered_joint", pa.float64()), ("uniform_p_conditional_order", pa.float64()),
    ("uniform_p_ordered_joint", pa.float64()), ("model_label", pa.string()),
])


class PipelineError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PipelineError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_output(path: Path) -> Path:
    require(not path.is_symlink(), f"refusing symlink output: {path}")
    resolved_parent = path.parent.resolve(strict=True)
    require(resolved_parent.is_relative_to(STUDY), f"output parent escaped study: {path}")
    resolved = resolved_parent / path.name
    require(resolved.is_relative_to(STUDY), f"output escaped study: {path}")
    return resolved


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    target = checked_output(path)
    require(not target.exists(), f"refusing to overwrite output: {target}")
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with target.open("x", encoding="utf-8") as handle:
        handle.write(payload)


def versions() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": importlib.metadata.version("scipy"),
        "pyarrow": pa.__version__,
    }


def verify_prefit_and_approval() -> tuple[dict, dict, dict]:
    prefit_path = OUT / "PREFIT_SOURCE_LOCK.json"
    source_path = OUT / "SOURCE_PREFLIGHT.json"
    grad_path = OUT / "GRADIENT_CHECK.json"
    require(prefit_path.is_file() and source_path.is_file() and grad_path.is_file(),
            "outcome-free source preflight artifacts are missing")
    prefit_lock = json.loads(prefit_path.read_text(encoding="utf-8"))
    source = json.loads(source_path.read_text(encoding="utf-8"))
    gradient = json.loads(grad_path.read_text(encoding="utf-8"))
    require(prefit_lock.get("status") == "PREFIT_SOURCE_LOCKED_ROOT_REVIEW_PENDING",
            "unexpected prefit source lock status")
    require(source.get("status") == "PASS" and source.get("fit_performed") is False
            and source.get("evaluation_outcome_metrics_computed") is False,
            "source preflight is not clean PASS")
    require(gradient.get("status") == "PASS", "synthetic gradient check did not pass")
    require(FIT_APPROVAL.is_file(), "root fit approval receipt is missing")
    approval = json.loads(FIT_APPROVAL.read_text(encoding="utf-8"))
    require(approval.get("status") == "APPROVED", "root fit approval is not APPROVED")
    require(approval.get("scope", "").startswith("Exactly three prescribed H1 conditional PL fits"),
            "root approval scope differs from this fit pipeline")
    require(approval.get("h1_fit_count") == 3 and approval.get("h2_calibration_count") == 3,
            "root approval fit/calibration count differs")
    require(approval.get("ridge_lambda") == 0.01 and approval.get("feature_columns") == 10,
            "root approval feature or ridge contract differs")
    require(approval.get("temperature_bounds") == [0.05, 20.0], "root temperature bounds differ")
    require(approval.get("source_prefight_sha256") == sha256_file(source_path),
            "root approval does not match the frozen source preflight")
    require(approval.get("prefit_source_lock_sha256") == sha256_file(prefit_path),
            "root approval does not match the frozen prefit source lock")
    require(approval.get("plan_sha256") == sha256_file(STUDY / "PLAN.md"),
            "root approval does not match frozen PLAN")
    require(approval.get("input_contract_sha256") == sha256_file(STUDY / "INPUT_CONTRACT.md"),
            "root approval does not match frozen input contract")
    require(approval.get("root_source_proof_sha256") == sha256_file(preflight.checked_path(preflight.ROOT_PROOF_PATH)),
            "root approval does not match root source proof")
    require(approval.get("root_gradient_proof_sha256") == sha256_file(ROOT / "jeju/research/20261017_order_head_rootreview_v1/ROOT_GRADIENT_REVIEW.json"),
            "root approval does not match independent gradient review")
    require(sha256_file(ROOT_STANDARDIZATION) == ROOT_STANDARDIZATION_SHA256,
            "independent H1 standardization reference hash changed")
    require(ROOT_REVIEW.is_file(), "independent root core review is missing")
    core_review = json.loads(ROOT_REVIEW.read_text(encoding="utf-8"))
    require(core_review.get("status") == "PASS"
            and core_review.get("all_3_h1_only_standardizers_match_independent") is True
            and core_review.get("all_6_h1_h2_true_order_designs_match_independent") is True
            and core_review.get("coefficient_objective_gradient_match") is True
            and core_review.get("temperature_objective_gradient_match") is True,
            "independent root core review is not PASS")
    return prefit_lock, source, approval


def implementation_self_check() -> dict:
    require(not IMPLEMENTATION_SELFTEST.exists(), "implementation self-test receipt already exists")
    rng = np.random.default_rng(20261017)
    synthetic_races = [rng.normal(size=(3, 10)) for _ in range(40)]
    synthetic_orders = [np.asarray(race) for race in synthetic_races]
    beta = rng.normal(scale=0.2, size=10)
    objective, gradient = core.nll_gradient(beta, synthetic_orders)
    step = 1e-6
    numerical = np.empty_like(beta)
    for j in range(len(beta)):
        plus, minus = beta.copy(), beta.copy()
        plus[j] += step
        minus[j] -= step
        numerical[j] = (core.nll_gradient(plus, synthetic_orders)[0]
                        - core.nll_gradient(minus, synthetic_orders)[0]) / (2 * step)
    beta_gradient_error = float(np.max(np.abs(gradient - numerical)))

    log_t = 0.17
    _temp_objective, temp_gradient = core.temperature_objective(np.asarray([log_t]), synthetic_orders, beta)
    temp_numerical = (
        core.temperature_objective(np.asarray([log_t + step]), synthetic_orders, beta)[0]
        - core.temperature_objective(np.asarray([log_t - step]), synthetic_orders, beta)[0]
    ) / (2 * step)
    temp_gradient_error = abs(float(temp_gradient[0]) - float(temp_numerical))
    fitted_beta, beta_fit = core.fit_beta(synthetic_races)
    fitted_temperature, temp_fit = core.fit_temperature(synthetic_races, fitted_beta)

    utilities = rng.normal(size=5)
    score = rng.normal(size=5)
    triples = list(itertools.combinations(range(5), 3))
    energies = np.asarray([np.sort(score[list(triple)]).sum() for triple in triples]) / 1.1
    q_values = core.softmax(energies)
    event_masses = {pool: {} for pool in ("WIN", "QNL", "EXA", "TRI")}
    joint_total = 0.0
    for triple_ix, q in zip(triples, q_values, strict=True):
        cond = core.order_probabilities(utilities[list(triple_ix)])
        for order_index, order in enumerate(core.PL_ORDERS):
            ordered = tuple(int(triple_ix[pos] + 1) for pos in order)
            p = float(q) * float(cond[order_index])
            joint_total += p
            keys = {
                "WIN": (ordered[0],),
                "QNL": tuple(sorted(ordered[:2])),
                "EXA": ordered[:2],
                "TRI": ordered,
            }
            for pool, key in keys.items():
                event_masses[pool][key] = event_masses[pool].get(key, 0.0) + p
    pool_mass = {pool: math.fsum(events.values()) for pool, events in event_masses.items()}
    require(beta_gradient_error < 1e-7 and temp_gradient_error < 1e-7,
            "synthetic implementation finite-difference gradient test failed")
    require(beta_fit["success"] and temp_fit["success"], "synthetic optimizer self-check failed")
    require(abs(joint_total - 1.0) <= 1e-12 and all(abs(value - 1.0) <= 1e-12 for value in pool_mass.values()),
            "synthetic pool event coherence test failed")
    result = {
        "status": "PASS",
        "scope": "synthetic_only_no_saved_labels_or_odds",
        "random_seed": 20261017,
        "synthetic_races": len(synthetic_races),
        "coefficient_gradient_max_abs_error": beta_gradient_error,
        "log_temperature_gradient_abs_error": temp_gradient_error,
        "synthetic_beta_optimizer": beta_fit,
        "synthetic_temperature_optimizer": temp_fit,
        "synthetic_temperature": fitted_temperature,
        "synthetic_ordered_joint_mass": joint_total,
        "synthetic_pool_event_masses": pool_mass,
        "real_model_fit_or_calibration_performed": False,
        "evaluation_metrics_computed": False,
        "market_odds_read": False,
    }
    write_json_once(IMPLEMENTATION_SELFTEST, result)
    return result


def create_fit_source_lock() -> dict:
    require(not FIT_SOURCE_LOCK.exists(), "fit source lock already exists")
    prefit_lock, source, approval = verify_prefit_and_approval()
    verified_sources = preflight.verify_source_hashes()
    files = {
        "PLAN.md": STUDY / "PLAN.md",
        "INPUT_CONTRACT.md": STUDY / "INPUT_CONTRACT.md",
        "preflight.py": STUDY / "preflight.py",
        "order_head_core.py": CORE_SCRIPT,
        "fit_predict.py": PIPELINE_SCRIPT,
        "PREFIT_SOURCE_LOCK.json": OUT / "PREFIT_SOURCE_LOCK.json",
        "SOURCE_PREFLIGHT.json": OUT / "SOURCE_PREFLIGHT.json",
        "GRADIENT_CHECK.json": OUT / "GRADIENT_CHECK.json",
        "ROOT_FIT_APPROVAL.json": FIT_APPROVAL,
        "ROOT_H1_STANDARDIZATION.json": ROOT_STANDARDIZATION,
        "ROOT_GRADIENT_REVIEW.json": ROOT / "jeju/research/20261017_order_head_rootreview_v1/ROOT_GRADIENT_REVIEW.json",
        "ROOT_CORE_REVIEW.json": ROOT_REVIEW,
        "IMPLEMENTATION_SELFTEST.json": IMPLEMENTATION_SELFTEST,
        **{f"ROOT_TRIPLES_{year}_{half}.npz": path for (year, half), path in ROOT_TRIPLE_FILES.items()},
    }
    for label, path in files.items():
        require(path.is_file(), f"fit source file missing: {label}")
    design_files = {
        label: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for label, path in files.items()
    }
    lock = {
        "status": "FIT_SOURCE_LOCKED_BEFORE_FIT",
        "study": "20261017_conditional_order_head_v1",
        "prefit_lock_sha256": sha256_file(OUT / "PREFIT_SOURCE_LOCK.json"),
        "root_fit_approval_sha256": sha256_file(FIT_APPROVAL),
        "root_h1_standardization_sha256": ROOT_STANDARDIZATION_SHA256,
        "root_gradient_review_sha256": sha256_file(files["ROOT_GRADIENT_REVIEW.json"]),
        "source_inputs": verified_sources,
        "locked_code_and_receipts": design_files,
        "runtime_versions": versions(),
        "fit_performed": False,
        "calibration_performed": False,
        "evaluation_predictions_performed": False,
        "evaluation_metrics_performed": False,
        "market_odds_read": False,
        "database_or_network_access": False,
    }
    write_json_once(FIT_SOURCE_LOCK, lock)
    return lock


def verify_fit_source_lock() -> dict:
    require(FIT_SOURCE_LOCK.is_file(), "FIT_SOURCE_LOCK.json is missing; freeze sources first")
    lock = json.loads(FIT_SOURCE_LOCK.read_text(encoding="utf-8"))
    require(lock.get("status") == "FIT_SOURCE_LOCKED_BEFORE_FIT", "fit source lock status is invalid")
    require(lock.get("runtime_versions") == versions(), "runtime versions changed after source lock")
    current_paths = {
        "PLAN.md": STUDY / "PLAN.md",
        "INPUT_CONTRACT.md": STUDY / "INPUT_CONTRACT.md",
        "preflight.py": STUDY / "preflight.py",
        "order_head_core.py": CORE_SCRIPT,
        "fit_predict.py": PIPELINE_SCRIPT,
        "PREFIT_SOURCE_LOCK.json": OUT / "PREFIT_SOURCE_LOCK.json",
        "SOURCE_PREFLIGHT.json": OUT / "SOURCE_PREFLIGHT.json",
        "GRADIENT_CHECK.json": OUT / "GRADIENT_CHECK.json",
        "ROOT_FIT_APPROVAL.json": FIT_APPROVAL,
        "ROOT_H1_STANDARDIZATION.json": ROOT_STANDARDIZATION,
        "ROOT_GRADIENT_REVIEW.json": ROOT / "jeju/research/20261017_order_head_rootreview_v1/ROOT_GRADIENT_REVIEW.json",
        "ROOT_CORE_REVIEW.json": ROOT_REVIEW,
        "IMPLEMENTATION_SELFTEST.json": IMPLEMENTATION_SELFTEST,
    }
    for year in (2024, 2025, 2026):
        for half in ("H1", "H2"):
            label = f"ROOT_TRIPLES_{year}_{half}.npz"
            current_paths[label] = ROOT_TRIPLE_FILES[(year, half)]
    for label, path in current_paths.items():
        saved = lock["locked_code_and_receipts"][label]
        require(path.is_file() and sha256_file(path) == saved["sha256"],
                f"fit source lock mismatch: {label}")
    require(sha256_file(FIT_APPROVAL) == lock["root_fit_approval_sha256"],
            "root fit approval changed after source lock")
    current_sources = preflight.verify_source_hashes()
    require(current_sources == lock["source_inputs"], "pinned prefit source hashes changed")
    return lock


def make_h1_h2(calibration: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    h1_candidates = calibration.loc[calibration["race_date_parsed"].map(lambda value: value.month <= 6)].copy()
    h2 = calibration.loc[calibration["race_date_parsed"].map(lambda value: value.month >= 7)].copy()
    require(not h1_candidates.empty and not h2.empty, "empty H1/H2 calibration period")
    first_h2 = min(h2["race_date_parsed"])
    cutoff = first_h2 - pd.Timedelta(days=2)
    h1 = h1_candidates.loc[h1_candidates["race_date_parsed"] <= cutoff].copy()
    h1["finish_position"] = h1["finish_position"].astype(int)
    h2["finish_position"] = h2["finish_position"].astype(int)
    return h1, h2


def compare_standardization(year: int, standardizer: core.H1Standardizer, reference: dict) -> dict:
    saved = reference[str(year)]
    require(saved["raw_columns"] == list(core.RAW_COLUMNS), f"independent raw columns differ for {year}")
    observed = {
        "impute_means": np.asarray(standardizer.impute_means),
        "centers": np.asarray(standardizer.centers),
        "scales": np.asarray(standardizer.scales),
        "degenerate": np.asarray(standardizer.degenerate, dtype=bool),
    }
    for key, field in (("impute_means", "raw_imputation_means"),
                       ("centers", "center"), ("scales", "scale")):
        expected = np.asarray(saved[field], dtype=float)
        require(observed[key].shape == expected.shape and np.allclose(observed[key], expected, rtol=0, atol=5e-12),
                f"H1 {key} differs from independent root calculation for {year}")
    require(np.array_equal(observed["degenerate"], np.asarray(saved["degenerate"], dtype=bool)),
            f"H1 degenerate feature mask differs from independent root calculation for {year}")
    require(standardizer.h1_rows == int(saved["h1_rows"])
            and standardizer.h1_races == int(saved["h1_races"]),
            f"H1 cohort differs from independent root calculation for {year}")
    return {
        "status": "PASS",
        "root_reference_max_abs_center_error": float(np.max(np.abs(observed["centers"] - np.asarray(saved["center"])))),
        "root_reference_max_abs_scale_error": float(np.max(np.abs(observed["scales"] - np.asarray(saved["scale"])))),
        "root_reference_max_abs_imputation_error": float(np.max(np.abs(observed["impute_means"] - np.asarray(saved["raw_imputation_means"])))),
    }


def fit_all_folds() -> dict:
    lock = verify_fit_source_lock()
    require(not FIT_ARTIFACTS.exists() and not FIT_RECEIPT.exists(), "fit artifacts already exist")
    features = preflight.load_features()
    root_standardization = json.loads(ROOT_STANDARDIZATION.read_text(encoding="utf-8"))
    artifacts: dict[str, Any] = {
        "status": "PASS_FITS_FROZEN_BEFORE_EVALUATION_METRICS",
        "model_label": MODEL_LABEL,
        "fit_source_lock_sha256": sha256_file(FIT_SOURCE_LOCK),
        "root_fit_approval_sha256": sha256_file(FIT_APPROVAL),
        "fit_contract": {
            "h1_fit_count": 3,
            "h2_calibration_count": 3,
            "ridge_lambda": core.RIDGE,
            "feature_count": len(core.FEATURE_NAMES),
            "feature_names": list(core.FEATURE_NAMES),
            "no_intercept": True,
            "h1_race_equal_weighting": "one conditional-order observation per race; H1 transform weight=1/field_n per runner",
            "h2_temperature_bounds": list(core.TEMPERATURE_BOUNDS),
            "q_tau_used_in_fit_or_calibration": False,
            "evaluation_labels_used_in_fit_or_calibration": False,
        },
        "folds": {},
        "runtime_versions": versions(),
    }
    for year in (2024, 2025, 2026):
        calibration, _evaluation, fold_preflight = preflight.check_fold(year, features)
        h1, h2 = make_h1_h2(calibration)
        for split_name, split in (("H1", h1), ("H2", h2)):
            saved_split = fold_preflight[split_name]
            require(len(split) == saved_split["rows"]
                    and split["race_id"].nunique() == saved_split["races"],
                    f"rebuilt {year} {split_name} row/race counts differ from source preflight")
            require(str(min(split["race_date_parsed"])) == saved_split["date_min"]
                    and str(max(split["race_date_parsed"])) == saved_split["date_max"],
                    f"rebuilt {year} {split_name} dates differ from source preflight")
        standardizer = core.H1Standardizer.fit(h1)
        standardization_check = compare_standardization(year, standardizer, root_standardization)
        h1_x = standardizer.transform(h1)
        h2_x = standardizer.transform(h2)
        h1_races = core.ordered_top3_design(h1, h1_x)
        h2_races = core.ordered_top3_design(h2, h2_x)
        beta, beta_fit = core.fit_beta(h1_races)
        temperature, temp_fit = core.fit_temperature(h2_races, beta)
        artifacts["folds"][str(year)] = {
            "calibration_label_year": year - 1,
            "H1": {"rows": int(len(h1)), "races": int(h1["race_id"].nunique()),
                   "date_min": str(min(h1["race_date_parsed"])),
                   "date_max": str(max(h1["race_date_parsed"])),
                   "conditional_order_nll_ridge": beta_fit["objective"],
                   "optimizer": beta_fit},
            "H2": {"rows": int(len(h2)), "races": int(h2["race_id"].nunique()),
                   "date_min": str(min(h2["race_date_parsed"])),
                   "date_max": str(max(h2["race_date_parsed"])),
                   "conditional_order_nll": temp_fit["objective"],
                   "optimizer": temp_fit},
            "beta": [float(value) for value in beta],
            "order_temperature": temperature,
            "saved_tau_for_native_q_only": float(fold_preflight["saved_tau_for_native_q_only"]),
            "standardizer": standardizer.to_dict(),
            "independent_standardization_check": standardization_check,
            "evaluation_source_structure_checked": True,
            "evaluation_outcome_metrics_computed": False,
        }
        print(f"fit {year}: H1 {len(h1)} rows/{h1.race_id.nunique()} races; "
              f"H2 {len(h2)} rows/{h2.race_id.nunique()} races; T={temperature:.8f}")

    artifacts["fit_completed"] = True
    artifacts["evaluation_predictions_generated"] = False
    artifacts["evaluation_metrics_computed"] = False
    artifacts["odds_or_market_sources_read"] = False
    artifacts["database_or_network_access"] = False
    write_json_once(FIT_ARTIFACTS, artifacts)
    fit_receipt = {
        "status": "PASS_FIT_ARTIFACTS_FROZEN_BEFORE_EVALUATION_METRICS",
        "model_label": MODEL_LABEL,
        "fit_artifact_path": "outputs/FIT_ARTIFACTS.json",
        "fit_artifacts_sha256": sha256_file(FIT_ARTIFACTS),
        "fit_source_lock_sha256": sha256_file(FIT_SOURCE_LOCK),
        "root_fit_approval_sha256": sha256_file(FIT_APPROVAL),
        "h1_fit_count": 3,
        "h2_calibration_count": 3,
        "evaluation_predictions_generated": False,
        "evaluation_metrics_computed": False,
        "odds_or_market_sources_read": False,
        "database_or_network_access": False,
    }
    write_json_once(FIT_RECEIPT, fit_receipt)
    return fit_receipt


def load_fit_artifacts() -> tuple[dict, dict, dict]:
    require(FIT_ARTIFACTS.is_file() and FIT_RECEIPT.is_file(), "frozen fit artifacts are missing")
    artifacts = json.loads(FIT_ARTIFACTS.read_text(encoding="utf-8"))
    receipt = json.loads(FIT_RECEIPT.read_text(encoding="utf-8"))
    lock = verify_fit_source_lock()
    require(receipt.get("status") == "PASS_FIT_ARTIFACTS_FROZEN_BEFORE_EVALUATION_METRICS",
            "fit receipt status is invalid")
    require(receipt.get("fit_artifacts_sha256") == sha256_file(FIT_ARTIFACTS), "fit artifacts hash mismatch")
    require(receipt.get("fit_source_lock_sha256") == sha256_file(FIT_SOURCE_LOCK), "fit source lock hash mismatch")
    require(artifacts.get("status") == "PASS_FITS_FROZEN_BEFORE_EVALUATION_METRICS"
            and artifacts.get("fit_completed") is True
            and artifacts.get("evaluation_metrics_computed") is False,
            "fit artifact status is invalid")
    require(len(artifacts.get("folds", {})) == 3, "fit artifact does not contain exactly three folds")
    return artifacts, receipt, lock


def eval_features_without_labels(year: int) -> pd.DataFrame:
    columns = [column for column in preflight.FEATURE_COLUMNS if column != "finish_position"]
    features = preflight.read_parquet(preflight.FEATURE_PATH, columns)
    features = features.loc[features["year"].eq(year)].copy()
    features["race_date_parsed"] = preflight.parse_dates(features["race_date"], "race_date")
    score_path = f"{preflight.STYLE_ROOT}/outputs/F1_STYLE6_{year}/evaluation_scores.parquet"
    scores = preflight.read_score(score_path)
    result = preflight.add_score(features, scores, f"{year} label-free evaluation")
    expected = preflight.EXPECTED_EVAL[year]
    require(len(result) == expected[0] and result["race_id"].nunique() == expected[1],
            f"label-free evaluation coverage changed for {year}")
    dates = result["race_date_parsed"].map(str)
    require(dates.min() == expected[2] and dates.max() == expected[3],
            f"label-free evaluation date boundaries changed for {year}")
    return result


def predictor_metadata(race: pd.DataFrame) -> tuple[int, str, int, int]:
    if race["race_date"].nunique() != 1 or race["distance_m"].nunique() != 1 or race["field_n"].nunique() != 1:
        raise PipelineError("race metadata differs within runner roster")
    return (int(race["distance_m"].iloc[0]), str(race["race_date"].iloc[0]),
            int(race["field_n"].iloc[0]), len(race))


def prediction_rows_for_race(year: int, race_id: str, race: pd.DataFrame, fold: dict) -> tuple[pd.DataFrame, dict]:
    race = race.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
    distance, race_date, field_n, n = predictor_metadata(race)
    require(n == field_n and n >= 4, f"incomplete evaluation roster in {race_id}")
    numbers = race["horse_number"].to_numpy(dtype=int)
    scores = race["score"].to_numpy(dtype=float)
    require(len(set(numbers.tolist())) == n and np.isfinite(scores).all(), f"invalid evaluation roster/scores in {race_id}")
    beta = np.asarray(fold["beta"], dtype=float)
    temperature = float(fold["order_temperature"])
    standardizer = core.H1Standardizer(**{
        **fold["standardizer"],
        "feature_names": tuple(fold["standardizer"]["feature_names"]),
        "impute_means": tuple(fold["standardizer"]["impute_means"]),
        "centers": tuple(fold["standardizer"]["centers"]),
        "scales": tuple(fold["standardizer"]["scales"]),
        "degenerate": tuple(fold["standardizer"]["degenerate"]),
    })
    design = standardizer.transform(race)

    triples = np.asarray(list(itertools.combinations(range(n), 3)), dtype=np.int64)
    energies = np.sort(scores[triples], axis=1).sum(axis=1)
    q_values = core.softmax(energies / float(fold["saved_tau_for_native_q_only"]))
    require(math.isclose(math.fsum(q_values.tolist()), 1.0, rel_tol=0, abs_tol=1e-12),
            f"unordered q probability mass failed in {race_id}")

    row_data: dict[str, list] = {column: [] for column in OUTPUT_COLUMNS}
    q_recovered: list[float] = []
    pair_mass: dict[tuple[int, int], list[float]] = {
        pair: [] for pair in itertools.combinations(numbers.tolist(), 2)
    }
    max_conditional_mass_error = 0.0
    max_q_recovery_error = 0.0
    for set_ix, triple_ix in enumerate(triples):
        set_numbers = tuple(int(numbers[j]) for j in triple_ix)
        q = float(q_values[set_ix])
        candidate_cond = core.order_probabilities((design[triple_ix] @ beta) / temperature)
        control_cond = core.order_probabilities(scores[triple_ix])
        uniform_cond = np.full(6, 1.0 / 6.0)
        max_conditional_mass_error = max(
            max_conditional_mass_error,
            abs(math.fsum(candidate_cond.tolist()) - 1.0),
            abs(math.fsum(control_cond.tolist()) - 1.0),
            abs(math.fsum(uniform_cond.tolist()) - 1.0),
        )
        set_joint_sum: list[float] = []
        for perm_ix, order in enumerate(core.PL_ORDERS):
            ordered_numbers = tuple(int(numbers[triple_ix[j]]) for j in order)
            cand_joint = q * float(candidate_cond[perm_ix])
            control_joint = q * float(control_cond[perm_ix])
            uniform_joint = q / 6.0
            for col, value in (
                ("evaluation_year", year), ("race_date", race_date), ("race_id", race_id),
                ("distance_m", distance), ("field_n", field_n),
                ("horse_no_1", ordered_numbers[0]), ("horse_no_2", ordered_numbers[1]),
                ("horse_no_3", ordered_numbers[2]), ("q_top3_set", q),
                ("p_conditional_order", float(candidate_cond[perm_ix])),
                ("p_ordered_joint", cand_joint),
                ("control_p_conditional_order", float(control_cond[perm_ix])),
                ("control_p_ordered_joint", control_joint),
                ("uniform_p_conditional_order", float(uniform_cond[perm_ix])),
                ("uniform_p_ordered_joint", uniform_joint), ("model_label", MODEL_LABEL),
            ):
                row_data[col].append(value)
            set_joint_sum.append(cand_joint)
        recovered = math.fsum(set_joint_sum)
        q_recovered.append(recovered)
        max_q_recovery_error = max(max_q_recovery_error, abs(recovered - q))
        for pair in itertools.combinations(set_numbers, 2):
            pair_mass[pair].append(q)

    q_sum = math.fsum(q_values.tolist())
    candidate_sum = math.fsum(row_data["p_ordered_joint"])
    control_sum = math.fsum(row_data["control_p_ordered_joint"])
    uniform_sum = math.fsum(row_data["uniform_p_ordered_joint"])
    require(abs(candidate_sum - 1.0) <= 1e-12 and abs(control_sum - 1.0) <= 1e-12
            and abs(uniform_sum - 1.0) <= 1e-12, f"joint mass failed in {race_id}")
    require(max_conditional_mass_error <= 1e-12 and max_q_recovery_error <= 1e-12,
            f"conditional order changed set mass in {race_id}")
    require(math.isclose(math.fsum(math.fsum(values) for values in pair_mass.values()), 3.0,
                         rel_tol=0, abs_tol=1e-12), f"q-derived QPL pair mass changed in {race_id}")
    frame = pd.DataFrame(row_data, columns=OUTPUT_COLUMNS)
    return frame, {
        "race_id": race_id,
        "field_n": n,
        "q_mass_error": abs(q_sum - 1.0),
        "candidate_joint_mass_error": abs(candidate_sum - 1.0),
        "fixed_score_joint_mass_error": abs(control_sum - 1.0),
        "uniform_joint_mass_error": abs(uniform_sum - 1.0),
        "max_conditional_mass_error": max_conditional_mass_error,
        "max_q_recovery_error": max_q_recovery_error,
        "set_count": int(len(triples)),
        "ordered_rows": int(len(triples) * 6),
    }


def make_predictions() -> dict:
    artifacts, fit_receipt, source_lock = load_fit_artifacts()
    require(not PREDICTIONS.exists() and not PREDICTION_RECEIPT.exists(), "prediction artifact already exists")
    if OUT.resolve() != PREDICTIONS.parent.resolve():
        raise PipelineError("prediction output path escaped outputs directory")
    frames: list[pd.DataFrame] = []
    race_audit: list[dict] = []
    counts_by_year: dict[str, dict[str, int]] = {}
    target = checked_output(PREDICTIONS)
    temp = checked_output(PREDICTIONS.with_name(f".{PREDICTIONS.name}.partial"))
    require(not target.exists() and not temp.exists(), "prediction target or partial file already exists")
    writer = None
    rows = 0

    def flush_frames() -> None:
        nonlocal writer, rows
        if not frames:
            return
        combined = pd.concat(frames, ignore_index=True)
        table = pa.Table.from_pandas(combined, schema=OUTPUT_SCHEMA, preserve_index=False, safe=True)
        if writer is None:
            writer = pq.ParquetWriter(temp, OUTPUT_SCHEMA, compression="zstd", version="2.6")
        writer.write_table(table, row_group_size=100_000)
        rows += table.num_rows
        frames.clear()

    for year in (2024, 2025, 2026):
        frame = eval_features_without_labels(year)
        fold = artifacts["folds"][str(year)]
        year_races = 0
        year_rows = 0
        for race_id, race in frame.groupby("race_id", sort=True):
            prediction_frame, audit = prediction_rows_for_race(year, str(race_id), race, fold)
            frames.append(prediction_frame)
            race_audit.append(audit)
            year_races += 1
            year_rows += len(prediction_frame)
            if len(frames) >= 64:
                flush_frames()
        counts_by_year[str(year)] = {"races": year_races, "ordered_rows": year_rows,
                                     "runners": int(len(frame))}
    try:
        flush_frames()
        if writer is None:
            raise PipelineError("no evaluation predictions were generated")
        writer.close()
        writer = None
        os.replace(temp, target)
    except Exception:
        if writer is not None:
            writer.close()
        if temp.exists():
            temp.unlink()
        raise
    byte_count = target.stat().st_size
    saved = pq.read_table(PREDICTIONS, columns=["race_id", "evaluation_year"])
    saved_df = saved.to_pandas()
    saved_race_counts = saved_df.groupby("evaluation_year")["race_id"].nunique().to_dict()
    require(saved_race_counts == {2024: 637, 2025: 654, 2026: 488},
            "frozen prediction race coverage differs from predeclared evaluation cohort")
    require(len(saved_df) == rows, "prediction parquet row count changed after write")

    cohort = pd.read_csv(preflight.checked_path(preflight.COHORT_PATH), dtype={"race_id": "string"})
    common_ids = set(cohort.loc[cohort["reason"].eq("matched"), "race_id"].astype(str))
    eval_2026_ids = set(saved_df.loc[saved_df["evaluation_year"].eq(2026), "race_id"].astype(str))
    require(len(common_ids) == 467 and common_ids.issubset(eval_2026_ids),
            "prediction output misses fixed 467-race HY comparison cohort")
    receipt = {
        "status": "PASS_FROZEN_BEFORE_EVALUATION_METRICS",
        "artifact_path": "outputs/evaluation_ordered_joint.parquet",
        "artifact_sha256": sha256_file(PREDICTIONS),
        "ordered_joint_sha256": sha256_file(PREDICTIONS),
        "artifact_bytes": byte_count,
        "artifact_rows": rows,
        "model_label": MODEL_LABEL,
        "prediction_schema": OUTPUT_SCHEMA.names,
        "evaluation_coverage_by_year": counts_by_year,
        "common_2026_hy_cohort_races": 467,
        "common_2026_hy_cohort_ids_included": True,
        "fit_artifacts_sha256": sha256_file(FIT_ARTIFACTS),
        "fit_receipt_sha256": sha256_file(FIT_RECEIPT),
        "fit_source_lock_sha256": sha256_file(FIT_SOURCE_LOCK),
        "root_fit_approval_sha256": sha256_file(FIT_APPROVAL),
        "prefit_source_lock_sha256": sha256_file(OUT / "PREFIT_SOURCE_LOCK.json"),
        "h1_fit_count": 3,
        "h2_calibration_count": 3,
        "q_tau_used_only_to_reconstruct_native_unordered_q": True,
        "candidate_q_set_probabilities_and_top3_qpl_unchanged_by_construction": True,
        "max_abs_q_mass_error": max(row["q_mass_error"] for row in race_audit),
        "max_abs_candidate_joint_mass_error": max(row["candidate_joint_mass_error"] for row in race_audit),
        "max_abs_fixed_score_joint_mass_error": max(row["fixed_score_joint_mass_error"] for row in race_audit),
        "max_abs_uniform_joint_mass_error": max(row["uniform_joint_mass_error"] for row in race_audit),
        "max_abs_conditional_mass_error": max(row["max_conditional_mass_error"] for row in race_audit),
        "max_abs_q_recovery_error": max(row["max_q_recovery_error"] for row in race_audit),
        "evaluation_labels_joined": False,
        "evaluation_metrics_computed": False,
        "market_odds_read": False,
        "database_or_network_access": False,
    }
    receipt["race_audit_sha256"] = hashlib.sha256(
        json.dumps(race_audit, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    write_json_once(PREDICTION_RECEIPT, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("self-check", "freeze-fit-source", "fit", "predict"))
    args = parser.parse_args()
    try:
        if args.phase == "self-check":
            result = implementation_self_check()
        elif args.phase == "freeze-fit-source":
            result = create_fit_source_lock()
        elif args.phase == "fit":
            result = fit_all_folds()
        else:
            result = make_predictions()
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except Exception as exc:
        print(f"ORDER_HEAD_FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
