"""Approval-gated, single-arm H1/H2 fit for riding conditions.

Importing or running without the explicit fit-approved action is inert. The
fit stage never generates evaluation predictions or performance metrics.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit, logit

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261015_pair_riding_conditions_v1"
OUT = STUDY / "outputs"
PREFIT = STUDY / "outputs_prefit_v2"
PLAN = STUDY / "PLAN.md"
PREFLIGHT = PREFIT / "FEATURE_PREFLIGHT.json"
DRY_RUN = PREFIT / "DESIGN_DRY_RUN.json"
RUNNER_BASIS = PREFIT / "riding_conditions_runner_basis.parquet"
RECONCILIATION = PREFIT / "SAVED_ID_RECONCILIATION.json"
NEW_DESIGN_RECONCILIATION = PREFIT / "NEW_CANDIDATE_FIRST60_RECONCILIATION.json"
ROOT_SOURCE_REVIEW = STUDY / "ROOT_SOURCE_REVIEW.json"
SOURCE_HASHES = STUDY / "SOURCE_HASHES.json"
SOURCE_CACHE = STUDY / "outputs/source_started_event_rider.parquet"
SOURCE_CACHE_RECEIPT = STUDY / "outputs/SOURCE_CACHE_RECEIPT.json"
APPROVAL = OUT / "APPROVAL.json"
FIT_PATH = OUT / "FIT.json"
FIT_RECEIPT = OUT / "FIT_RECEIPT.json"
FIT_CODE = STUDY / "pair_riding_conditions_fit.py"
PREDICT_CODE = STUDY / "pair_riding_conditions_predict.py"
BASIS_CODE = STUDY / "riding_conditions_basis.py"
PREPARE_CODE = STUDY / "prepare.py"
BASE = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
ID = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
EXPANSION = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
RELIABILITY = ROOT / "jeju/research/20261014_pair_reliability_v1"
BASE_FIT_CODE = BASE / "pair_jockey_fit.py"
BASE_FIT = BASE / "outputs/FIT.json"
ID_FIT_CODE = ID / "pair_jockey_id_fit.py"
ID_BASIS_CODE = ID / "pair_jockey_id_basis.py"
ID_FIT = ID / "outputs/FIT.json"
ID_PREDICTIONS = ID / "outputs/evaluation_pair_predictions.parquet"
ID_PREDICTION_RECEIPT = ID / "outputs/PREDICTION_RECEIPT.json"
EXPANDED_FIT = EXPANSION / "outputs/expanded_h1_fit.json"
RELIABILITY_FIT_HELPER = RELIABILITY / "pair_reliability_fit.py"
FIT_YEARS = (2024, 2025, 2026)
H1_RACES = {2024: 2147, 2025: 2818, 2026: 3458}
H2_RACES = {2024: 336, 2025: 311, 2026: 325}
MODEL_SCOPE = "pair_riding_conditions_h1_h2_fit"
FIT_SCOPE = "single fixed riding-conditions arm; three H1 fits and three H2 Platt fits only; no evaluation predictions or metrics"


class FitError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise FitError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked(path: Path) -> Path:
    require(not path.is_symlink(), f"input symlink rejected: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"input outside workspace: {path}")
    return resolved


def json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(json_safe(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, checked(path))
    require(spec is not None and spec.loader is not None, f"cannot load frozen helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_gate() -> tuple[dict, dict, dict]:
    require(OUT.is_dir(), "root must create outputs/APPROVAL.json before fit")
    require(APPROVAL.is_file() and not APPROVAL.is_symlink(), "root fit approval is missing")
    require(not FIT_PATH.exists() and not FIT_PATH.is_symlink()
            and not FIT_RECEIPT.exists() and not FIT_RECEIPT.is_symlink(),
            "fit output exists; refusing retry/overwrite")
    preflight = json.loads(checked(PREFLIGHT).read_text(encoding="utf-8"))
    dry_run = json.loads(checked(DRY_RUN).read_text(encoding="utf-8"))
    approval = json.loads(checked(APPROVAL).read_text(encoding="utf-8"))
    cache_receipt = json.loads(checked(SOURCE_CACHE_RECEIPT).read_text(encoding="utf-8"))
    reconcile = json.loads(checked(RECONCILIATION).read_text(encoding="utf-8"))
    new_design_reconcile = json.loads(checked(NEW_DESIGN_RECONCILIATION).read_text(encoding="utf-8"))
    root_review = json.loads(checked(ROOT_SOURCE_REVIEW).read_text(encoding="utf-8"))
    source_hashes = json.loads(checked(SOURCE_HASHES).read_text(encoding="utf-8"))

    require(preflight.get("status") == "PASS"
            and preflight.get("target_current_outcome_used_in_features") is False
            and preflight.get("future_history_after_cutoff_used") is False
            and preflight.get("database_reopened_after_event_rider_cache_creation") is False,
            "frozen feature preflight failed or scope changed")
    require(dry_run.get("status") == "PASS" and dry_run.get("optimizer_runs") == 0
            and dry_run.get("candidate_h1_fit_runs") == 0 and dry_run.get("candidate_h2_platt_runs") == 0
            and dry_run.get("evaluation_predictions_created") is False
            and dry_run.get("performance_metrics_computed") is False,
            "frozen dry-run is not a no-fit PASS")
    require(cache_receipt.get("status") == "PASS"
            and cache_receipt.get("cache_sha256") == sha256(SOURCE_CACHE)
            and cache_receipt.get("cache_sha256") == preflight.get("source_cache_sha256"),
            "frozen event-rider cache/receipt mismatch")
    require(preflight.get("source_lock_sha256") == sha256(SOURCE_HASHES)
            and cache_receipt.get("source_lock_sha256") == sha256(SOURCE_HASHES),
            "frozen source-lock hash mismatch")
    require(preflight.get("runner_basis_sha256") == sha256(RUNNER_BASIS)
            and preflight.get("basis_code_sha256") == sha256(BASIS_CODE)
            and preflight.get("prepare_code_sha256") == sha256(PREPARE_CODE),
            "final prefit code or runner-basis hash changed")
    require(reconcile.get("status") == "PASS" and reconcile.get("pair_rows") == 76848
            and reconcile.get("races") == 1779 and reconcile.get("evaluation_dates") == 269
            and reconcile.get("selection_mismatches") == 0
            and max(reconcile.get("maximum_absolute_difference", {}).values()) <= 1e-12,
            "saved ID probability reconstruction is not a PASS")
    require(root_review.get("status") == "PASS"
            and root_review.get("final_preflight_sha256") == sha256(PREFLIGHT)
            and root_review.get("final_dry_run_sha256") == sha256(DRY_RUN)
            and root_review.get("final_runner_basis_sha256") == sha256(RUNNER_BASIS)
            and root_review.get("frozen_old_id_probability_reconstruction_receipt_sha256")
            == sha256(RECONCILIATION)
            and root_review.get("active_new_features") == 9
            and root_review.get("active_joint_features") == 69
            and root_review.get("optimizer_runs") == 0,
            "root's independent prefit review is missing or mismatched")
    require(new_design_reconcile.get("status") == "PASS"
            and new_design_reconcile.get("pair_rows") == 76848
            and new_design_reconcile.get("races") == 1779
            and new_design_reconcile.get("evaluation_dates") == 269
            and new_design_reconcile.get("selection_mismatches") == 0
            and max(new_design_reconcile.get("max_abs_differences", {}).values()) <= 1e-12,
            "new candidate predictor's first-60 design reconciliation is not a PASS")
    for relative, expected in preflight.get("verified_pinned_sources", {}).items():
        require(sha256(checked(ROOT / relative)) == expected, f"pinned source changed: {relative}")
    require(sha256(checked(ID_PREDICTIONS)) == preflight["verified_pinned_sources"].get(
        ID_PREDICTIONS.relative_to(ROOT).as_posix()), "frozen ID reference prediction hash changed")
    require(sha256(checked(ID_PREDICTION_RECEIPT)) == preflight["verified_pinned_sources"].get(
        ID_PREDICTION_RECEIPT.relative_to(ROOT).as_posix()), "frozen ID reference receipt hash changed")

    required_approval = {
        "approved": True, "approved_by": "root", "scope": MODEL_SCOPE,
        "plan_sha256": sha256(checked(PLAN)),
        "fit_code_sha256": sha256(checked(FIT_CODE)),
        "predict_code_sha256": sha256(checked(PREDICT_CODE)),
        "basis_code_sha256": sha256(checked(BASIS_CODE)),
        "prepare_code_sha256": sha256(checked(PREPARE_CODE)),
        "preflight_sha256": sha256(checked(PREFLIGHT)),
        "dry_run_sha256": sha256(checked(DRY_RUN)),
        "runner_basis_sha256": sha256(checked(RUNNER_BASIS)),
        "source_hashes_sha256": sha256(checked(SOURCE_HASHES)),
        "cache_receipt_sha256": sha256(checked(SOURCE_CACHE_RECEIPT)),
        "reconciliation_sha256": sha256(checked(RECONCILIATION)),
        "new_design_reconciliation_sha256": sha256(checked(NEW_DESIGN_RECONCILIATION)),
        "root_source_review_sha256": sha256(checked(ROOT_SOURCE_REVIEW)),
        "reliability_fit_helper_sha256": sha256(checked(RELIABILITY_FIT_HELPER)),
    }
    for key, expected in required_approval.items():
        require(approval.get(key) == expected, f"root approval hash/scope mismatch: {key}")
    require(approval.get("fit_budget") == {
        "h1_fits": 3, "h2_positive_slope_platt_fits": 3, "no_retry_or_tuning": True,
    }, "root approval does not match the frozen six-call fit budget")
    require(source_hashes.get("status") == "PINNED_SOURCE_FILES",
            "frozen source-lock status changed")
    return preflight, dry_run, approval


def attach_runner_basis(yearly: dict[int, pd.DataFrame], basis_module) -> dict[int, pd.DataFrame]:
    columns = ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "distance_m",
               *basis_module.RUNNER_COLUMNS]
    source = pd.read_parquet(checked(RUNNER_BASIS), columns=columns)
    for column in ("api_record_id", "race_id", "horse_id"):
        source[column] = source[column].astype("string")
    source["race_date"] = pd.to_datetime(source["race_date"], errors="coerce").dt.normalize()
    require(source["api_record_id"].is_unique and source["race_date"].notna().all(),
            "frozen runner-basis key/date invalid")
    attached = {}
    join_keys = ("race_id", "race_date", "year", "horse_id", "horse_number", "distance_m")
    for year, rows in yearly.items():
        left = rows.copy()
        for column in ("api_record_id", "race_id", "horse_id"):
            left[column] = left[column].astype("string")
        left["race_date"] = pd.to_datetime(left["race_date"], errors="coerce").dt.normalize()
        right = source.loc[source["year"].eq(year)]
        require(left["api_record_id"].is_unique and right["api_record_id"].is_unique,
                f"training runner key duplicated: {year}")
        require(set(left["api_record_id"]) == set(right["api_record_id"]),
                f"frozen feature/source API coverage differs: {year}")
        merged = left.merge(right, on="api_record_id", how="left", suffixes=("", "_source"),
                            validate="one_to_one")
        for column in join_keys:
            source_column = f"{column}_source" if column in left.columns else column
            lhs, rhs = merged[column], merged[source_column]
            if column in ("year", "horse_number", "distance_m"):
                lhs, rhs = pd.to_numeric(lhs, errors="coerce"), pd.to_numeric(rhs, errors="coerce")
            elif column == "race_date":
                lhs = pd.to_datetime(lhs, errors="coerce").dt.normalize()
                rhs = pd.to_datetime(rhs, errors="coerce").dt.normalize()
            else:
                lhs, rhs = lhs.astype("string"), rhs.astype("string")
            require(lhs.notna().all() and rhs.notna().all() and lhs.eq(rhs).all(),
                    f"frozen runner feature {column} mismatch: {year}")
        require(len(merged) == len(left), f"feature attach changed training row count: {year}")
        attached[year] = merged
    return attached


def loss_gradient(core, beta: np.ndarray, x: np.ndarray, p0: np.ndarray,
                  labels: np.ndarray, race_ids: np.ndarray) -> tuple[float, np.ndarray]:
    beta = np.asarray(beta, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    p0 = np.asarray(p0, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.float64)
    require(x.ndim == 2 and x.shape[1] == len(beta) and len(x) == len(p0) == len(labels) == len(race_ids),
            "fit design/objective dimensions differ")
    require(np.isfinite(x).all() and np.isfinite(beta).all() and np.isfinite(p0).all()
            and np.isfinite(labels).all() and ((p0 > 0) & (p0 < 1)).all(),
            "non-finite or invalid H1 objective input")
    weights = core._race_pair_weights(race_ids)
    eta = logit(p0) + x @ beta
    losses = np.logaddexp(0.0, eta) - labels * eta
    residual = weights * (expit(eta) - labels)
    value = float(np.dot(weights, losses) + 0.5 * float(core.LAMBDA) * np.dot(beta, beta))
    gradient = x.T @ residual + float(core.LAMBDA) * beta
    require(math.isfinite(value) and np.isfinite(gradient).all(), "non-finite H1 objective/gradient")
    return value, gradient


def fit_one_fold(evaluation_year: int, h1: pd.DataFrame, h2: pd.DataFrame, runtime: tuple,
                 baseline_fold: dict, basic_fold: dict, id_fold: dict,
                 dry_run_fold: dict) -> dict:
    core, pair_fit, basic_fit, _, _, _, id_basis, reliability_fit = runtime
    basis_module = import_module("riding_conditions_basis_for_fit", BASIS_CODE)
    runner_stats, _ = basic_fit.stats_from_baseline(core, baseline_fold)
    h1_races = pair_fit.build_races(core, h1, runner_stats)
    h2_races = pair_fit.build_races(core, h2, runner_stats)
    require(len(h1_races) == H1_RACES[evaluation_year] and len(h2_races) == H2_RACES[evaluation_year],
            f"H1/H2 race count changed: {evaluation_year}")
    require(all(int(np.asarray(race["labels"]).sum()) == 3 for race in h1_races + h2_races),
            f"Top3 pair label arithmetic changed: {evaluation_year}")

    # This reviewed helper creates the identical style+rolling+ID first 60 columns.
    old = reliability_fit._old_60_design(
        core, basic_fit, id_basis, pair_fit, h1_races, h2_races,
        baseline_fold, basic_fold, id_fold,
    )
    moments = basis_module.fit_race_equal_moments(h1)
    expected_moments = dry_run_fold["h1_candidate_pair_moments"]
    require(moments["columns"] == expected_moments["columns"]
            and moments["exact_duplicate_columns"] == expected_moments["exact_duplicate_columns"]
            and moments["fit_excluded_columns"] == expected_moments["fit_excluded_columns"]
            and moments["fit_retained_columns"] == expected_moments["fit_retained_columns"],
            f"candidate duplicate/active feature set differs from reviewed dry-run: {evaluation_year}")
    for value_kind in ("mean", "scale"):
        diffs = [abs(float(moments[value_kind][name]) - float(expected_moments[value_kind][name]))
                 for name in moments["columns"]]
        require(max(diffs) <= 1e-12, f"candidate {value_kind} differs from reviewed dry-run: {evaluation_year}")
    require(dry_run_fold["joint_candidate_columns_after_degenerate_drop"]
            == 60 + len(moments["fit_retained_columns"]),
            f"reviewed joint width differs from candidate design: {evaluation_year}")
    extra_h1 = np.vstack([
        basis_module.transform_pair_features(basis_module.pair_features_for_race(race["rows"]), moments)
        for race in h1_races
    ])
    extra_h2 = np.vstack([
        basis_module.transform_pair_features(basis_module.pair_features_for_race(race["rows"]), moments)
        for race in h2_races
    ])
    x_h1 = np.column_stack((old["x_h1"], extra_h1))
    x_h2 = np.column_stack((old["x_h2"], extra_h2))
    expected_width = 60 + len(moments["fit_retained_columns"])
    require(x_h1.shape[1] == x_h2.shape[1] == expected_width,
            "joint matrix width differs from exact duplicate/degenerate rule")
    require(np.isfinite(x_h1).all() and np.isfinite(x_h2).all(), "non-finite candidate matrix")

    result = minimize(
        fun=lambda beta: loss_gradient(core, beta, x_h1, old["p0_h1"], old["y_h1"], old["race_h1"]),
        x0=np.zeros(x_h1.shape[1], dtype=np.float64), method="L-BFGS-B", jac=True,
        options={"maxiter": core.H1_MAXITER, "ftol": core.H1_FTOL, "gtol": core.H1_GTOL},
    )
    require(result.success and np.isfinite(result.x).all() and math.isfinite(float(result.fun))
            and np.isfinite(result.jac).all(), f"H1 optimizer failed {evaluation_year}: {result.message}")
    grad_inf = float(np.max(np.abs(result.jac)))
    require(grad_inf <= core.ACCEPT_GRAD_INF, f"H1 stationarity failed {evaluation_year}: {grad_inf}")
    eta_h2 = logit(old["p0_h2"]) + x_h2 @ result.x
    calibration = core.fit_platt(eta_h2, old["y_h2"], old["race_h2"])
    require(calibration.success and float(calibration.x[1]) > 0.0,
            f"H2 Platt fit failed or nonpositive slope: {evaluation_year}")
    require(int(old["y_h1"].sum()) == 3 * H1_RACES[evaluation_year]
            and int(old["y_h2"].sum()) == 3 * H2_RACES[evaluation_year],
            f"fit labels do not match three Top3 runners per race: {evaluation_year}")

    names = list(core.BASIS_NAMES) + ["jockey365_pair_sum"] + [
        f"jockey_id:{value}" for value in old["vocabulary"]
    ] + list(moments["fit_retained_columns"])
    require(len(names) == len(result.x) and len(names) == len(set(names)), "joint coefficient names changed")
    return {
        "evaluation_year": evaluation_year,
        "h1_races": int(len(h1_races)), "h1_dates": int(h1["race_date"].dt.date.nunique()),
        "h1_rows": int(len(h1)), "h1_pairs": int(len(old["y_h1"])),
        "h1_positive_pairs": int(old["y_h1"].sum()),
        "h2_races": int(len(h2_races)), "h2_dates": int(h2["race_date"].dt.date.nunique()),
        "h2_rows": int(len(h2)), "h2_pairs": int(len(old["y_h2"])),
        "h2_positive_pairs": int(old["y_h2"].sum()),
        "h1_last_date": h1["race_date"].max().date().isoformat(),
        "h2_first_date": h2["race_date"].min().date().isoformat(),
        "coefficient_order": names,
        "coefficients": [float(value) for value in result.x],
        "coefficients_by_basis": {name: float(result.x[i]) for i, name in enumerate(names)},
        "frozen_60_column_contract": {
            "count": 60,
            "old_style_and_current_rider_columns": list(core.BASIS_NAMES) + ["jockey365_pair_sum"],
            "h1_only_id_vocabulary": list(old["vocabulary"]),
            "reference_id_fit_sha256": sha256(checked(ID_FIT)),
            "evaluation_probability_reconstruction": str(RECONCILIATION.relative_to(ROOT)),
        },
        "frozen_21st_rolling_moment": basic_fold["new_pair_moment"],
        "category_encoding": id_fold["category_encoding"],
        "new_basis_moments": moments,
        "optimizer": {
            "success": bool(result.success), "status": int(result.status), "message": str(result.message),
            "iterations": int(result.nit), "function_evaluations": int(result.nfev),
            "objective": float(result.fun), "gradient_inf_norm": grad_inf,
            "coefficient_count": int(len(result.x)), "lambda": float(core.LAMBDA),
            "maxiter": int(core.H1_MAXITER), "ftol": float(core.H1_FTOL), "gtol": float(core.H1_GTOL),
        },
        "h2_candidate_platt": {
            "A": float(calibration.x[0]), "B": float(calibration.x[1]),
            "projected_gradient_inf_norm": float(np.max(np.abs(calibration.projected_gradient))),
            "objective": float(calibration.fun), "iterations": int(calibration.nit),
            "success": bool(calibration.success),
        },
        "source_preflight_sha256": sha256(checked(PREFLIGHT)),
        "design_dry_run_sha256": sha256(checked(DRY_RUN)),
    }


def load_runtime() -> tuple:
    basic_fit = import_module("riding_conditions_basic_fit_helper", BASE_FIT_CODE)
    core, pair_fit, jockey_input, historical = basic_fit.load_helpers()
    import_module("riding_conditions_id_fit_helper", ID_FIT_CODE)
    id_basis = import_module("riding_conditions_id_basis_helper", ID_BASIS_CODE)
    reliability_fit = import_module("riding_conditions_reliability_fit_helper", RELIABILITY_FIT_HELPER)
    return core, pair_fit, basic_fit, jockey_input, historical, None, id_basis, reliability_fit


def run_fit() -> None:
    preflight, dry_run, approval = validate_gate()
    runtime = load_runtime()
    _, pair_fit, basic_fit, jockey_input, historical, _, _, _ = runtime
    baseline = json.loads(checked(EXPANDED_FIT).read_text(encoding="utf-8"))
    basic = json.loads(checked(BASE_FIT).read_text(encoding="utf-8"))
    id_fit = json.loads(checked(ID_FIT).read_text(encoding="utf-8"))
    require(baseline.get("folds") and basic.get("status") == id_fit.get("status") == "PASS",
            "frozen 60-column source fits are incomplete")
    yearly, score_sources = basic_fit.prepare_training_rows(pair_fit, jockey_input, historical)
    yearly = attach_runner_basis(yearly, import_module("riding_conditions_basis_training", BASIS_CODE))
    fit_folds = []
    for evaluation_year in FIT_YEARS:
        h1, h2 = basic_fit.split_h1_h2(yearly, evaluation_year)
        baseline_fold = next(row for row in baseline["folds"] if int(row["evaluation_year"]) == evaluation_year)
        basic_fold = next(row for row in basic["folds"] if int(row["evaluation_year"]) == evaluation_year)
        id_fold = next(row for row in id_fit["folds"] if int(row["evaluation_year"]) == evaluation_year)
        dry_run_fold = dry_run["folds"][str(evaluation_year)]
        fit_folds.append(fit_one_fold(evaluation_year, h1, h2, runtime,
                                      baseline_fold, basic_fold, id_fold, dry_run_fold))
    require(len(fit_folds) == 3, "fit budget requires exactly three H1 and three H2 fits")
    fit_doc = {
        "status": "PASS", "study": STUDY.name, "scope": FIT_SCOPE,
        "candidate_input": "single fixed 10-feature pair bundle; exact H1 duplicates and H1-degenerate columns excluded",
        "model": "frozen 60-column ID model plus retained H1-standardized rider-condition features; race-equal pair BCE, fixed logit(p0) offset, lambda=1 ridge, H2 positive-slope Platt",
        "fit_budget": {"h1_fits": 3, "h2_positive_slope_platt_fits": 3,
                       "total_optimizer_calls": 6, "no_retry_or_tuning": True},
        "baseline_preserved": "F1_STYLE6 scores, 20 style columns, current rider365 scalar, H1-only 39-ID encoding, labels, date splits, purge, optimizer and H2 calibration protocol",
        "preflight_sha256": sha256(checked(PREFLIGHT)),
        "design_dry_run_sha256": sha256(checked(DRY_RUN)),
        "approval_sha256": sha256(checked(APPROVAL)),
        "source_lock_sha256": sha256(checked(SOURCE_HASHES)),
        "frozen_reliability_fit_helper_sha256": sha256(checked(RELIABILITY_FIT_HELPER)),
        "source_cache_sha256": sha256(checked(SOURCE_CACHE)),
        "runner_basis_sha256": sha256(checked(RUNNER_BASIS)),
        "source_hashes": preflight["verified_pinned_sources"],
        "score_sources_by_year": score_sources,
        "h1_fit_count": 3, "h2_candidate_map_count": 3, "folds": fit_folds,
        "historical_results_read": True, "target_evaluation_outcomes_used": False,
        "evaluation_predictions_generated": False, "performance_metrics_computed": False,
        "code_sha256": {"fit": sha256(checked(FIT_CODE)), "predict": sha256(checked(PREDICT_CODE)),
                        "basis": sha256(checked(BASIS_CODE)), "prepare": sha256(checked(PREPARE_CODE))},
    }
    write_json_once(FIT_PATH, fit_doc)
    fit_receipt = {
        "status": "PASS", "scope": MODEL_SCOPE, "candidate_fit_sha256": sha256(FIT_PATH),
        "approval_sha256": sha256(checked(APPROVAL)),
        "fit_code_sha256": sha256(checked(FIT_CODE)),
        "predict_code_sha256": sha256(checked(PREDICT_CODE)),
        "fit_count": {"h1": 3, "h2_platt": 3},
        "evaluation_predictions_generated": False, "performance_metrics_computed": False,
    }
    write_json_once(FIT_RECEIPT, fit_receipt)
    print(json.dumps(fit_receipt, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("fit-approved",), nargs="?", default=None)
    args = parser.parse_args()
    if args.action is None:
        print("inert: use fit-approved only after a matching root approval exists")
        return
    run_fit()


if __name__ == "__main__":
    main()
