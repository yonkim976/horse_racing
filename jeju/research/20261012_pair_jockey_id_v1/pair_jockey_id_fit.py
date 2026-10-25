"""Fit the approved H1-only categorical jockey-ID pair arm once."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logit

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
OUT = STUDY / "outputs"
BASE = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
BASE_FIT_HELPER = BASE / "pair_jockey_fit.py"
ID_BASIS = STUDY / "pair_jockey_id_basis.py"
PLAN = STUDY / "PLAN.md"
PREFLIGHT_SCRIPT = STUDY / "source_preflight.py"
PREFLIGHT = OUT / "SOURCE_PREFLIGHT.json"
APPROVAL = OUT / "APPROVAL.json"
FIT_PATH = OUT / "FIT.json"
FIT_RECEIPT = OUT / "FIT_RECEIPT.json"
DRY_RUN = OUT / "DESIGN_DRY_RUN.json"
FIT_YEARS = (2024, 2025, 2026)
H1_RACES = {2024: 2147, 2025: 2818, 2026: 3458}
H2_RACES = {2024: 336, 2025: 311, 2026: 325}


class CandidateFitError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise CandidateFitError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked(path: Path) -> Path:
    require(not path.is_symlink(), f"input symlink is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"input outside workspace: {path}")
    return resolved


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, checked(path))
    require(spec is not None and spec.loader is not None, f"cannot load frozen helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def loss_gradient(core, beta: np.ndarray, basis: np.ndarray, p0: np.ndarray,
                  labels: np.ndarray, race_ids: np.ndarray) -> tuple[float, np.ndarray]:
    x = np.asarray(basis, dtype=float)
    b = np.asarray(beta, dtype=float)
    y = np.asarray(labels, dtype=float)
    prior = np.asarray(p0, dtype=float)
    require(x.ndim == 2 and x.shape[1] == len(b) and len(b) > 21,
            "candidate design/coefficient dimensions differ")
    require(len(x) == len(y) == len(prior) == len(race_ids), "candidate objective input lengths differ")
    require(np.isfinite(x).all() and np.isfinite(b).all() and np.isfinite(y).all() and np.isfinite(prior).all(),
            "non-finite candidate objective input")
    weights = core._race_pair_weights(race_ids)
    eta = logit(prior) + x @ b
    losses = np.logaddexp(0.0, eta) - y * eta
    residual = weights * (expit(eta) - y)
    value = float(np.dot(weights, losses) + 0.5 * float(core.LAMBDA) * np.dot(b, b))
    gradient = x.T @ residual + float(core.LAMBDA) * b
    require(math.isfinite(value) and np.isfinite(gradient).all(), "non-finite candidate objective")
    return value, gradient


def category_design(id_basis, races: list[dict[str, Any]], vocabulary: tuple[str, ...], moments: dict[str, Any]) -> np.ndarray:
    blocks = [
        id_basis.race_pair_basis(race["rows"], race["pairs"], vocabulary, moments["pi"], moments["sigma"])
        for race in races
    ]
    require(bool(blocks), "empty categorical race design")
    matrix = np.vstack(blocks)
    require(np.isfinite(matrix).all(), "non-finite categorical race design")
    return matrix


def fit_fold(core, pair_fit, basic_fit, id_basis, evaluation_year: int,
             h1, h2, baseline_fold: dict[str, Any], rolling_fold: dict[str, Any]) -> dict[str, Any]:
    runner_stats, old_pair_stats = basic_fit.stats_from_baseline(core, baseline_fold)
    h1_races = pair_fit.build_races(core, h1, runner_stats)
    h2_races = pair_fit.build_races(core, h2, runner_stats)
    require(len(h1_races) == H1_RACES[evaluation_year] and len(h2_races) == H2_RACES[evaluation_year],
            f"H1/H2 race count mismatch: {evaluation_year}")
    require(all(int(np.asarray(race["labels"]).sum()) == 3 for race in h1_races + h2_races),
            f"pair label arithmetic changed: {evaluation_year}")
    vocabulary = id_basis.fit_vocabulary(h1)
    require(len(vocabulary) == 39, f"H1-only jockey vocabulary changed: {evaluation_year}")
    id_moments = id_basis.fit_moments([race["rows"] for race in h1_races], vocabulary)
    require(not id_moments["degenerate_ids"], f"degenerate H1 category feature: {evaluation_year}")

    rolling_moments = rolling_fold["new_pair_moment"]
    x21_h1, p0_h1, y_h1, race_id_h1 = basic_fit.transform_candidate_basis(
        core, h1_races, old_pair_stats, rolling_moments,
    )
    x21_h2, p0_h2, y_h2, race_id_h2 = basic_fit.transform_candidate_basis(
        core, h2_races, old_pair_stats, rolling_moments,
    )
    x_cat_h1 = category_design(id_basis, h1_races, vocabulary, id_moments)
    x_cat_h2 = category_design(id_basis, h2_races, vocabulary, id_moments)
    require(len(x_cat_h1) == len(x21_h1) and len(x_cat_h2) == len(x21_h2),
            "categorical and frozen 21-column pair design row counts differ")
    x_h1 = np.column_stack((x21_h1, x_cat_h1))
    x_h2 = np.column_stack((x21_h2, x_cat_h2))
    require(x_h1.shape[1] == x_h2.shape[1] == 60, "expected exactly 21 frozen + 39 categorical columns")
    require(np.array_equal(x_h1[:, :21], x21_h1) and np.array_equal(x_h2[:, :21], x21_h2),
            "frozen style/rolling basis changed")

    result = minimize(
        fun=lambda beta: loss_gradient(core, beta, x_h1, p0_h1, y_h1, race_id_h1),
        x0=np.zeros(x_h1.shape[1], dtype=float), method="L-BFGS-B", jac=True,
        options={"maxiter": core.H1_MAXITER, "ftol": core.H1_FTOL, "gtol": core.H1_GTOL},
    )
    require(result.success and np.isfinite(result.x).all() and np.isfinite(result.fun) and np.isfinite(result.jac).all(),
            f"candidate H1 optimizer failed in {evaluation_year}: {result.message}")
    grad_inf = float(np.max(np.abs(result.jac)))
    require(grad_inf <= core.ACCEPT_GRAD_INF, f"candidate H1 stationarity failed: {grad_inf}")

    eta_h2 = logit(p0_h2) + x_h2 @ result.x
    calibration = core.fit_platt(eta_h2, y_h2, race_id_h2)
    require(calibration.success and float(calibration.x[1]) > 0.0,
            f"candidate H2 calibrator failed or reverses rank: {evaluation_year}")
    require(int(y_h1.sum()) == 3 * H1_RACES[evaluation_year]
            and int(y_h2.sum()) == 3 * H2_RACES[evaluation_year], "H1/H2 positive pair totals changed")

    theta = np.asarray(result.x[21:], dtype=float)
    alpha = id_basis.raw_effects(theta, id_moments["pi"], id_moments["sigma"])
    category_rows = []
    for i, jockey_id in enumerate(vocabulary):
        category_rows.append({
            "jockey_id": jockey_id, "h1_starts": int(id_moments["starts_by_id"][i]),
            "h1_races": int(id_moments["races_by_id"][i]), "mu_pair_count": float(id_moments["mu"][i]),
            "pi_runner_weight": float(id_moments["pi"][i]), "sigma_pair_count": float(id_moments["sigma"][i]),
            "theta_standardized_basis": float(theta[i]), "alpha_centered_runner_logit_effect": float(alpha[i]),
        })
    return {
        "evaluation_year": evaluation_year,
        "h1_races": len(h1_races), "h1_dates": int(h1["race_date"].dt.date.nunique()),
        "h1_rows": len(h1), "h1_pairs": int(len(y_h1)), "h1_positive_pairs": int(y_h1.sum()),
        "h2_races": len(h2_races), "h2_dates": int(h2["race_date"].dt.date.nunique()),
        "h2_rows": len(h2), "h2_pairs": int(len(y_h2)), "h2_positive_pairs": int(y_h2.sum()),
        "h1_last_date": h1["race_date"].max().date().isoformat(),
        "h2_first_date": h2["race_date"].min().date().isoformat(),
        "frozen_21st_rolling_moment": rolling_moments,
        "category_encoding": {
            "vocabulary_h1_only": list(vocabulary), "vocabulary_count": len(vocabulary),
            "mu": {vocabulary[i]: float(id_moments["mu"][i]) for i in range(len(vocabulary))},
            "pi": {vocabulary[i]: float(id_moments["pi"][i]) for i in range(len(vocabulary))},
            "sigma": {vocabulary[i]: float(id_moments["sigma"][i]) for i in range(len(vocabulary))},
            "support_and_effects": category_rows,
            "degenerate_ids": id_moments["degenerate_ids"],
            "unknown_policy": "unknown runner categorical basis is exactly zero",
            "effective_ridge_limit": "lambda applies to standardized theta; raw alpha penalty varies with sigma and support",
        },
        "beta_by_basis": {name: float(result.x[i]) for i, name in enumerate(core.BASIS_NAMES)},
        "gamma_jockey365_pair_sum": float(result.x[20]),
        "theta_by_jockey_id": {vocabulary[i]: float(theta[i]) for i in range(len(vocabulary))},
        "alpha_centered_runner_logit_effect_by_jockey_id": {
            vocabulary[i]: float(alpha[i]) for i in range(len(vocabulary))
        },
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
        "_runner_stats": runner_stats, "_old_pair_stats": old_pair_stats,
        "_beta": np.asarray(result.x, dtype=float), "_rolling_moments": rolling_moments,
        "_id_vocabulary": vocabulary, "_id_moments": id_moments,
    }


def validate_approval() -> tuple[dict[str, Any], Any, Any, Any, Any]:
    require(checked(PREFLIGHT).exists(), "label-free source preflight is missing")
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    approval = json.loads(checked(APPROVAL).read_text(encoding="utf-8"))
    require(preflight.get("status") == "PASS" and preflight.get("finish_labels_read") is False
            and preflight.get("performance_metrics_computed") is False,
            "source preflight is not a no-label PASS")
    require(approval.get("approved") is True and approval.get("approved_by") == "root",
            "root fit approval is required")
    require(approval.get("scope") == "pair_jockey_id_h1_h2_fit", "approval scope mismatch")
    for key, path in (
        ("plan_sha256", PLAN), ("source_preflight_sha256", PREFLIGHT),
        ("source_preflight_code_sha256", PREFLIGHT_SCRIPT), ("id_basis_sha256", ID_BASIS),
        ("fit_code_sha256", Path(__file__).resolve()), ("design_dry_run_sha256", DRY_RUN),
    ):
        require(approval.get(key) == sha256(checked(path)), f"approval hash mismatch: {key}")
    for relative, expected in preflight.get("source_hashes", {}).items():
        require(sha256(checked(ROOT / relative)) == expected, f"pinned source changed: {relative}")

    current_preflight_module = import_module("jockey_id_preflight_for_fit", PREFLIGHT_SCRIPT)
    current_preflight = current_preflight_module.collect()
    require(current_preflight == preflight, "current label-free preflight differs from frozen file")
    basic_fit = import_module("frozen_basic_jockey_fit_for_id", BASE_FIT_HELPER)
    core, pair_fit, jockey_input, historical = basic_fit.load_helpers()
    baseline_fit = basic_fit.load_baseline_fit()
    return preflight, basic_fit, core, pair_fit, (jockey_input, historical, baseline_fit)


def run_design_dry_run() -> None:
    """Materialize only input shapes and moments; run no optimizer or metric."""
    preflight = json.loads(checked(PREFLIGHT).read_text(encoding="utf-8"))
    require(preflight.get("status") == "PASS" and preflight.get("finish_labels_read") is False,
            "label-free source preflight is not PASS")
    preflight_module = import_module("jockey_id_preflight_for_dry_run", PREFLIGHT_SCRIPT)
    require(preflight_module.collect() == preflight, "current label-free source preflight differs")
    basic_fit = import_module("frozen_basic_jockey_fit_for_id_dry_run", BASE_FIT_HELPER)
    core, pair_fit, jockey_input, historical = basic_fit.load_helpers()
    baseline_fit = basic_fit.load_baseline_fit()
    basic_fit_doc = json.loads(checked(BASE / "outputs/FIT.json").read_text(encoding="utf-8"))
    yearly, _ = basic_fit.prepare_training_rows(pair_fit, jockey_input, historical)
    id_basis = import_module("pair_jockey_id_basis_for_dry_run", ID_BASIS)
    fold_summary = {}
    for year in FIT_YEARS:
        h1, h2 = basic_fit.split_h1_h2(yearly, year)
        baseline_fold = next(row for row in baseline_fit["folds"] if int(row["evaluation_year"]) == year)
        rolling_fold = next(row for row in basic_fit_doc["folds"] if int(row["evaluation_year"]) == year)
        require(rolling_fold["old_pair_moments"] == baseline_fold["pair_standardization"],
                f"saved rolling candidate's first 20 moments differ from frozen base: {year}")
        runner_stats, old_pair_stats = basic_fit.stats_from_baseline(core, baseline_fold)
        h1_races = pair_fit.build_races(core, h1, runner_stats)
        h2_races = pair_fit.build_races(core, h2, runner_stats)
        vocabulary = id_basis.fit_vocabulary(h1)
        moments = id_basis.fit_moments([race["rows"] for race in h1_races], vocabulary)
        x21_h1, p0_h1, y_h1, race_ids_h1 = basic_fit.transform_candidate_basis(
            core, h1_races, old_pair_stats, rolling_fold["new_pair_moment"],
        )
        x21_h2, p0_h2, y_h2, race_ids_h2 = basic_fit.transform_candidate_basis(
            core, h2_races, old_pair_stats, rolling_fold["new_pair_moment"],
        )
        cat_h1 = category_design(id_basis, h1_races, vocabulary, moments)
        cat_h2 = category_design(id_basis, h2_races, vocabulary, moments)
        x_h1 = np.column_stack((x21_h1, cat_h1))
        x_h2 = np.column_stack((x21_h2, cat_h2))
        require(x_h1.dtype == x_h2.dtype == np.dtype("float64"), f"candidate input dtype changed: {year}")
        require(x_h1.shape == (len(y_h1), 21 + len(vocabulary))
                and x_h2.shape == (len(y_h2), 21 + len(vocabulary)),
                f"candidate design dimensions changed: {year}")
        require(np.isfinite(x_h1).all() and np.isfinite(x_h2).all()
                and np.isfinite(p0_h1).all() and np.isfinite(p0_h2).all(),
                f"non-finite candidate design: {year}")
        require(len(race_ids_h1) == len(y_h1) and len(race_ids_h2) == len(y_h2),
                f"pair label/design length mismatch: {year}")
        require(np.array_equal(x_h1[:, :21], x21_h1) and np.array_equal(x_h2[:, :21], x21_h2),
                f"frozen 21-column pair design changed: {year}")
        fold_summary[str(year)] = {
            "h1_races": len(h1_races), "h1_pair_rows": len(y_h1), "h1_design_shape": list(x_h1.shape),
            "h2_races": len(h2_races), "h2_pair_rows": len(y_h2), "h2_design_shape": list(x_h2.shape),
            "category_count": len(vocabulary), "sigma_min": float(moments["sigma"].min()),
            "frozen_21_columns_equal": True, "all_numeric_dtypes_float64": True,
        }
    value = {
        "status": "PASS", "study": STUDY.name,
        "scope": "typed H1/H2 pair-design construction only; no optimization, calibration fit, predictions, or metrics",
        "optimizer_runs": 0, "calibration_fits": 0, "evaluation_predictions_generated": False,
        "performance_metrics_computed": False,
        "source_preflight_sha256": sha256(PREFLIGHT), "id_basis_sha256": sha256(ID_BASIS),
        "fit_code_sha256": sha256(Path(__file__).resolve()), "folds": fold_summary,
    }
    write_json_once(DRY_RUN, value)
    print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)


def run_approved_fit() -> None:
    preflight, basic_fit, core, pair_fit, support = validate_approval()
    jockey_input, historical, baseline_fit = support
    require(not FIT_PATH.exists() and not FIT_RECEIPT.exists(), "candidate fit outputs already exist")
    fold_paths = [OUT / f"FOLD_FIT_{year}.json" for year in FIT_YEARS]
    require(all(not path.exists() and not path.is_symlink() for path in fold_paths),
            "candidate fold fit output already exists; no retry permitted")
    basic_fit_doc = json.loads(checked(BASE / "outputs/FIT.json").read_text(encoding="utf-8"))
    basic_fit_receipt = json.loads(checked(BASE / "outputs/FIT_RECEIPT.json").read_text(encoding="utf-8"))
    basic_approval = json.loads(checked(BASE / "outputs/APPROVAL.json").read_text(encoding="utf-8"))
    require(basic_fit_doc.get("status") == "PASS" and basic_fit_doc.get("h1_fit_count") == 3
            and basic_fit_doc.get("h2_candidate_map_count") == 3,
            "saved basic rolling candidate fit is missing or invalid")
    require(basic_fit_receipt.get("status") == "PASS"
            and basic_fit_receipt.get("candidate_fit_sha256") == sha256(BASE / "outputs/FIT.json")
            and basic_fit_receipt.get("fit_code_sha256") == sha256(BASE_FIT_HELPER),
            "saved basic rolling candidate fit receipt/hash mismatch")
    require(basic_approval.get("approved") is True and basic_approval.get("approved_by") == "root",
            "saved basic rolling candidate root approval missing")
    yearly, score_sources = basic_fit.prepare_training_rows(pair_fit, jockey_input, historical)
    fold_docs = []
    for evaluation_year in FIT_YEARS:
        h1, h2 = basic_fit.split_h1_h2(yearly, evaluation_year)
        baseline_fold = next(row for row in baseline_fit["folds"] if int(row["evaluation_year"]) == evaluation_year)
        rolling_fold = next(row for row in basic_fit_doc["folds"] if int(row["evaluation_year"]) == evaluation_year)
        require(rolling_fold["old_pair_moments"] == baseline_fold["pair_standardization"],
                f"saved rolling candidate's first 20 moments differ from frozen base: {evaluation_year}")
        id_basis = import_module("pair_jockey_id_basis_for_fit", ID_BASIS)
        fitted = fit_fold(core, pair_fit, basic_fit, id_basis, evaluation_year, h1, h2,
                          baseline_fold, rolling_fold)
        fold_doc = {key: value for key, value in fitted.items() if not key.startswith("_")}
        fold_doc["source_preflight_sha256"] = sha256(PREFLIGHT)
        fold_doc["approval_sha256"] = sha256(APPROVAL)
        write_json_once(OUT / f"FOLD_FIT_{evaluation_year}.json", fold_doc)
        fold_docs.append(fold_doc)

    document = {
        "status": "PASS", "study": STUDY.name,
        "scope": "one H1-only official jockey-ID categorical pair arm; no evaluation prediction or metrics",
        "candidate_input": {
            "horse_score": "saved F1_STYLE6 score, unchanged",
            "pair_bases": "unchanged 20 style + saved-H1-moment rolling365 scalar + 39 H1-only jockey-ID effect-coded columns",
            "jockey_id_numeric_or_name_input": False,
            "unknown_policy": "H1-unknown event ID runner categorical basis exactly zero",
            "interpretation": "H1-centered observed rider-ID associations, not causal effects or pure ability",
        },
        "model": "joint race-equal pair BCE with lambda=1, no explicit intercept; candidate 21+39 coefficients jointly fit",
        "baseline_preserved": {
            "rolling_candidate_study": "20261012_pair_jockey_basic_v1",
            "rolling_candidate_coefficients_refit_for_comparison": False,
            "F1_STYLE6_score_changed": False,
            "first_21_pair_basis_moments_reused_exactly": True,
            "loss_optimizer_calibration": "existing frozen basic pair recipe; three H1 and three candidate H2 map fits only",
        },
        "source_preflight_sha256": sha256(PREFLIGHT), "approval_sha256": sha256(APPROVAL),
        "source_hashes": preflight["source_hashes"], "score_sources_by_race_year": score_sources,
        "h1_fit_count": 3, "h2_candidate_map_count": 3, "folds": fold_docs,
        "evaluation_predictions_generated": False, "performance_metrics_computed": False,
    }
    write_json_once(FIT_PATH, document)
    receipt = {
        "status": "PASS", "study": STUDY.name, "h1_fit_count": 3, "h2_candidate_map_count": 3,
        "evaluation_predictions_generated": False, "performance_metrics_computed": False,
        "plan_sha256": sha256(PLAN), "source_preflight_sha256": sha256(PREFLIGHT),
        "source_preflight_code_sha256": sha256(PREFLIGHT_SCRIPT), "id_basis_sha256": sha256(ID_BASIS),
        "fit_code_sha256": sha256(Path(__file__).resolve()), "approval_sha256": sha256(APPROVAL),
        "candidate_fit_sha256": sha256(FIT_PATH),
    }
    write_json_once(FIT_RECEIPT, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"design-dry-run", "fit-approved"}:
        raise SystemExit("usage: pair_jockey_id_fit.py {design-dry-run|fit-approved}")
    if sys.argv[1] == "design-dry-run":
        run_design_dry_run()
    else:
        run_approved_fit()

