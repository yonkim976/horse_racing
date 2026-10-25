"""Approved-only H1 relationship fit and H2 temperature calibration.

This module intentionally refuses to fit until a root approval artifact names the
frozen plan and the preflight receipt. It never reloads or retrains the base model.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import joint_model as jm


APPROVAL_PATH = jm.OUT / "root_fit_approval.json"
PARAMETERS_PATH = jm.OUT / "fit_parameters.json"
FIT_RECEIPT_PATH = jm.OUT / "fit_receipt.json"
INDEPENDENT_RECEIPT_PATH = jm.OUT / "independent_preflight_receipt.json"
A_VERIFICATION_PATH = jm.OUT / "a_verification_receipt.json"
C_ACCEPTANCE_PATH = jm.OUT / "c_preflight_acceptance.json"


def verify_preflight_sources() -> tuple[dict, dict, dict, dict[str, str]]:
    source_lock_path = jm.OUT / "source_lock.json"
    preflight_path = jm.OUT / "preflight_receipt.json"
    source_lock = jm.load_json(source_lock_path)
    preflight = jm.load_json(preflight_path)
    if not INDEPENDENT_RECEIPT_PATH.is_file():
        raise PermissionError("independent C preflight receipt is required before fitting")
    independent = jm.load_json(INDEPENDENT_RECEIPT_PATH)
    a_verification = jm.load_json(A_VERIFICATION_PATH)
    acceptance = jm.load_json(C_ACCEPTANCE_PATH)
    external_c_hash = jm.sha256(jm.C_FINAL_RECEIPT_PATH)
    if source_lock.get("plan_sha256") != jm.EXPECTED_PLAN_SHA256:
        raise AssertionError("source lock plan hash differs from fixed plan")
    if preflight.get("plan_sha256") != jm.EXPECTED_PLAN_SHA256 or not preflight.get("passed"):
        raise AssertionError("a passing preflight receipt for the frozen plan is required")
    if (not independent.get("passed") or
            independent.get("plan_sha256") != jm.EXPECTED_PLAN_SHA256 or
            independent.get("source_lock_sha256") != jm.sha256(source_lock_path) or
            independent.get("preflight_receipt_sha256") != jm.sha256(preflight_path) or
            jm.sha256(INDEPENDENT_RECEIPT_PATH) != external_c_hash or
            not a_verification.get("passed") or
            a_verification.get("source_lock_sha256") != jm.sha256(source_lock_path) or
            a_verification.get("preflight_receipt_sha256") != jm.sha256(preflight_path) or
            not acceptance.get("passed") or acceptance.get("c_sha256") != external_c_hash or
            acceptance.get("a_copy_sha256") != jm.sha256(INDEPENDENT_RECEIPT_PATH)):
        raise AssertionError("independent C preflight receipt is invalid or refers to other inputs")
    expected = source_lock.get("sources", {})
    current = jm.lock_sources()
    if {key: value["sha256"] for key, value in current.items()} != {
            key: value["sha256"] for key, value in expected.items()}:
        raise AssertionError("source hashes differ from passing preflight lock")
    hashes = {key: value["sha256"] for key, value in current.items()}
    return source_lock, preflight, independent, hashes


def require_root_approval(source_lock: dict, preflight: dict) -> dict:
    approval = jm.load_json(APPROVAL_PATH)
    if approval.get("approved") is not True:
        raise PermissionError("root_fit_approval.json does not explicitly set approved=true")
    if approval.get("plan_sha256") != jm.EXPECTED_PLAN_SHA256:
        raise PermissionError("root approval names a different plan hash")
    if approval.get("preflight_receipt_sha256") != jm.sha256(jm.OUT / "preflight_receipt.json"):
        raise PermissionError("root approval does not name this preflight receipt")
    if approval.get("source_lock_sha256") != jm.sha256(jm.OUT / "source_lock.json"):
        raise PermissionError("root approval does not name this source lock")
    if approval.get("scope") != "fit_h1_relationship_and_h2_temperature_only":
        raise PermissionError("root approval scope is not the fixed H1/H2 fit stage")
    if approval.get("approved_by") != "root":
        raise PermissionError("root approval must identify approved_by='root'")
    independent_path = jm.OUT / "independent_preflight_receipt.json"
    if approval.get("independent_preflight_receipt_sha256") != jm.sha256(independent_path):
        raise PermissionError("root approval does not name the passing independent C preflight")
    if approval.get("a_verification_receipt_sha256") != jm.sha256(A_VERIFICATION_PATH):
        raise PermissionError("root approval does not name this A verification receipt")
    if approval.get("c_preflight_acceptance_sha256") != jm.sha256(C_ACCEPTANCE_PATH):
        raise PermissionError("root approval does not name the byte-identical C receipt acceptance")
    return approval


def feature_state(group: pd.DataFrame, scaler: dict, pair_rms: np.ndarray):
    runner_values, runner_valid = jm.transform_runner(group, scaler)
    pair_ids, phi = jm.pair_basis(runner_values, runner_valid)
    residual, _ = jm.project_pair_basis(pair_ids, phi, len(group))
    normalized = np.zeros_like(residual)
    active = pair_rms > jm.DEGENERATE_TOL
    normalized[:, active] = residual[:, active] / pair_rms[active]
    cleaned, preclean_max = jm.clean_degenerate_residual(normalized)
    triples = jm.triple_indices(len(group))
    triple_features = jm.triple_relation_features(pair_ids, cleaned, triples)
    scores = group.score.to_numpy(float)
    baseline_energy = jm.baseline_energies(scores, triples)
    finish = group.finish_position.to_numpy(int)
    truth_rows = np.flatnonzero(finish <= 3)
    truth_tuple = tuple(sorted(int(i) for i in truth_rows))
    truth_index = next((idx for idx, triple in enumerate(triples)
                        if tuple(int(i) for i in triple) == truth_tuple), None)
    if truth_index is None:
        raise AssertionError(f"could not locate exact unordered truth set: {group.race_id.iloc[0]}")
    return {
        "triple_features": triple_features,
        "baseline_energy": baseline_energy,
        "truth_index": int(truth_index),
        "triples": triples,
        "preclean_max_abs": preclean_max,
    }


def prepare_fold_inputs(year: int, features: pd.DataFrame) -> dict:
    folder = jm.STYLE_OUT / f"F1_STYLE6_{year}"
    meta = jm.load_json(folder / "meta.json")
    calibration = jm.join_scores(features, folder / "calibration_scores.parquet", year - 1,
                                 int(meta["calibration_rows"]), role="calibration")
    evaluation = jm.join_scores(features, folder / "evaluation_scores.parquet", year,
                                int(meta["evaluation_rows"]), role="evaluation")
    jm.assert_runner_features(calibration)
    jm.assert_runner_features(evaluation)
    split = jm.split_calibration(calibration, evaluation, meta)
    h1_groups = jm.race_groups(split["h1"])
    h2_groups = jm.race_groups(split["h2"])
    scaler = jm.fit_runner_scaler(split["h1"])

    race_residuals = []
    for group in h1_groups:
        values, valid = jm.transform_runner(group, scaler)
        pair_ids, phi = jm.pair_basis(values, valid)
        residual, _ = jm.project_pair_basis(pair_ids, phi, len(group))
        race_residuals.append(np.mean(np.square(residual), axis=0))
    pair_rms = np.sqrt(np.mean(np.vstack(race_residuals), axis=0))
    active = np.flatnonzero(pair_rms > jm.DEGENERATE_TOL)

    return {
        "evaluation_year": year,
        "calibration_year": year - 1,
        "dates": {
            "h1_min": str(pd.to_datetime(split["h1"].race_date).min().date()),
            "h1_max": str(split["h1_max"].date()),
            "h2_min": str(split["h2"].race_date.min().date()),
            "h2_max": str(split["h2_max"].date()),
            "evaluation_min": str(split["evaluation_min"].date()),
            "evaluation_max": str(split["evaluation_max"].date()),
            "refit_max": str(split["refit_max"].date()),
        },
        "h1_races": len(h1_groups),
        "h2_races": len(h2_groups),
        "h1_purged_races": split["purged_races"],
        "runner_scaler": scaler,
        "pair_rms": pair_rms.tolist(),
        "active_columns": active.tolist(),
        "h1_groups": h1_groups,
        "h2_groups": h2_groups,
    }


def checkpoint_header(year: int, source_lock_sha: str, preflight_sha: str,
                      independent_sha: str, approval_sha: str) -> dict:
    return {"evaluation_year": year, "plan_sha256": jm.EXPECTED_PLAN_SHA256,
            "source_lock_sha256": source_lock_sha, "preflight_receipt_sha256": preflight_sha,
            "independent_preflight_receipt_sha256": independent_sha,
            "approval_sha256": approval_sha}


def load_checkpoint(path: Path, expected_header: dict) -> dict:
    record = jm.load_json(path)
    for key, value in expected_header.items():
        if record.get(key) != value:
            raise AssertionError(f"fit checkpoint {path.name} has mismatched {key}")
    return record


def fit_or_resume_fold(year: int, features: pd.DataFrame, source_lock_sha: str,
                       preflight_sha: str, independent_sha: str,
                       approval_sha: str) -> dict:
    beta_checkpoint = jm.OUT / f"fit_fold_{year}_beta.json"
    full_checkpoint = jm.OUT / f"fit_fold_{year}.json"
    header = checkpoint_header(year, source_lock_sha, preflight_sha, independent_sha, approval_sha)
    if full_checkpoint.exists():
        return load_checkpoint(full_checkpoint, header)

    fold_inputs = prepare_fold_inputs(year, features)
    if beta_checkpoint.exists():
        beta_record = load_checkpoint(beta_checkpoint, header)
    else:
        h1_data = [feature_state(group, fold_inputs["runner_scaler"],
                                 np.asarray(fold_inputs["pair_rms"], dtype=np.float64))
                   for group in fold_inputs["h1_groups"]]
        for race in h1_data:
            race["active_columns"] = np.asarray(fold_inputs["active_columns"], dtype=np.int64)
        fitted = jm.fit_beta(h1_data)
        beta_record = {
            **header,
            **{key: value for key, value in fold_inputs.items()
               if key not in {"h1_groups", "h2_groups"}},
            "beta": fitted["beta"],
            "fit": fitted,
            "checkpoint_stage": "H1 relationship coefficients complete; H2 temperatures pending",
        }
        jm.write_json_new(beta_checkpoint, beta_record)

    beta = np.asarray(beta_record["beta"], dtype=np.float64)
    h2_data = [feature_state(group, beta_record["runner_scaler"],
                             np.asarray(beta_record["pair_rms"], dtype=np.float64))
               for group in fold_inputs["h2_groups"]]
    for race in h2_data:
        race["candidate_energy"] = race["baseline_energy"] + race["triple_features"] @ beta
    baseline_tau = jm.fit_temperature(h2_data, "baseline_energy")
    candidate_tau = jm.fit_temperature(h2_data, "candidate_energy")
    full_record = {
        **beta_record,
        "baseline_tau": baseline_tau,
        "candidate_tau": candidate_tau,
        "checkpoint_stage": "H1 relationship coefficients and both H2 temperatures complete",
    }
    jm.write_json_new(full_checkpoint, full_record)
    return full_record


def main() -> None:
    if jm.sha256(jm.HERE / "PLAN.md") != jm.EXPECTED_PLAN_SHA256:
        raise AssertionError("PLAN.md differs from the root-approved frozen plan")
    if PARAMETERS_PATH.exists() or FIT_RECEIPT_PATH.exists():
        raise FileExistsError("fit artifacts already exist; refusing to overwrite")
    source_lock, preflight, independent, source_hashes_before = verify_preflight_sources()
    approval = require_root_approval(source_lock, preflight)
    source_lock_sha = jm.sha256(jm.OUT / "source_lock.json")
    preflight_sha = jm.sha256(jm.OUT / "preflight_receipt.json")
    independent_sha = jm.sha256(INDEPENDENT_RECEIPT_PATH)
    approval_sha = jm.sha256(APPROVAL_PATH)
    features = pd.read_parquet(jm.confined(jm.FEATURES_PATH))
    folds = [fit_or_resume_fold(year, features, source_lock_sha, preflight_sha,
                                independent_sha, approval_sha) for year in jm.YEARS]
    before_after = jm.lock_sources()
    locked_hashes = {key: value["sha256"] for key, value in source_lock["sources"].items()}
    if {key: value["sha256"] for key, value in before_after.items()} != locked_hashes:
        raise AssertionError("locked input source changed during approved fit")

    parameters = {
        "schema_version": 1,
        "study": "20261010_joint_relationship_v1",
        "plan_sha256": jm.EXPECTED_PLAN_SHA256,
        "source_lock_sha256": jm.sha256(jm.OUT / "source_lock.json"),
        "preflight_receipt_sha256": jm.sha256(jm.OUT / "preflight_receipt.json"),
        "approval_sha256": jm.sha256(APPROVAL_PATH),
        "approval_scope": approval["scope"],
        "approval_approved_by": approval["approved_by"],
        "independent_preflight_receipt_sha256": independent_sha,
        "a_verification_receipt_sha256": jm.sha256(A_VERIFICATION_PATH),
        "c_preflight_acceptance_sha256": jm.sha256(C_ACCEPTANCE_PATH),
        "fit_scope": "H1 relationship coefficients and H2 matched temperatures; no base refit",
        "relationship_lambda": jm.REGULARIZATION_LAMBDA,
        "optimizer": {"method": "L-BFGS-B", "options": jm.OPTIMIZER_OPTIONS,
                      "analytic_gradient": True},
        "temperature_bounds": list(jm.TEMP_BOUNDS),
        "temperature_optimizer": {"method": "bounded", "xatol": jm.TEMP_XATOL},
        "pair_features": list(jm.PAIR_FEATURES),
        "source_hashes_unchanged_after_fit": True,
        "source_hashes_before_fit": source_hashes_before,
        "source_hashes_after_fit": {key: value["sha256"] for key, value in before_after.items()},
        "folds": folds,
    }
    jm.write_json_new(PARAMETERS_PATH, parameters)
    receipt = {
        "passed": True,
        "study": "20261010_joint_relationship_v1",
        "plan_sha256": jm.EXPECTED_PLAN_SHA256,
        "parameters_sha256": jm.sha256(PARAMETERS_PATH),
        "source_lock_sha256": parameters["source_lock_sha256"],
        "preflight_receipt_sha256": parameters["preflight_receipt_sha256"],
        "approval_sha256": parameters["approval_sha256"],
        "independent_preflight_receipt_sha256": independent_sha,
        "a_verification_receipt_sha256": parameters["a_verification_receipt_sha256"],
        "c_preflight_acceptance_sha256": parameters["c_preflight_acceptance_sha256"],
        "base_model_fit_or_reload": False,
        "completed_h1_coefficient_fit_folds": sum(1 for fold in folds if fold.get("fit")),
        "h1_coefficient_optimizer_calls": sum(
            0 if fold["fit"].get("optimizer_skipped") else 1 for fold in folds
        ),
        "h2_temperature_optimizer_calls": 2 * len(folds),
        "evaluation_outcome_metrics_computed": False,
        "source_hashes_unchanged_before_and_after_fit": True,
        "folds": [{"evaluation_year": fold["evaluation_year"],
                   "active_columns": fold["active_columns"],
                   "fit_objective": fold["fit"]["objective"],
                   "h1_races": fold["h1_races"], "h2_races": fold["h2_races"]}
                  for fold in folds],
    }
    jm.write_json_new(FIT_RECEIPT_PATH, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
