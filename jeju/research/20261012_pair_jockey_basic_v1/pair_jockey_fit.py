"""Fit-only helpers for the frozen 20-style + one rolling-jockey pair arm.

This module has no import-time data reads and no automatic fit entry point.
The caller must obtain the root's pinned approval before calling fit_three_folds.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit, logit

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
BASE = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
BASE_OUT = BASE / "outputs"
BASE_FIT = BASE_OUT / "expanded_h1_fit.json"
BASE_FIT_RECEIPT = BASE_OUT / "PAIR_FIT_RECEIPT.json"
BASE_HISTORICAL_RECEIPT = BASE_OUT / "HISTORICAL_REFIT_RECEIPT.json"
APPROVAL = STUDY / "outputs/APPROVAL.json"
SOURCE_PREFLIGHT = STUDY / "outputs/SOURCE_PREFLIGHT.json"
FIT_PATH = STUDY / "outputs/FIT.json"
FIT_RECEIPT_PATH = STUDY / "outputs/FIT_RECEIPT.json"
DIRECT_CORE = ROOT / "jeju/research/20261011_pair_top3_direct_v1/core.py"
FIT_YEARS = (2024, 2025, 2026)
H1_RACES = {2024: 2147, 2025: 2818, 2026: 3458}
H2_RACES = {2024: 336, 2025: 311, 2026: 325}
BASE_H1_SHA256 = "3a42446feb21aeaf156e59dd24238ce3ea9f9af137d48665c61393571a3774c7"
BASE_FIT_RECEIPT_SHA256 = "7b92ca5fcf3db460d83dd6574d0e43b386ee400a706767eaf158c54572d0e946"
BASE_CORE_SHA256 = "0a51495c6c1d08f65e1400a6d47c7710d3b32806f678a6bbefe2fab3a8e2de1e"
BASE_PAIR_FIT_SHA256 = "5187288115621e6affc5079d4c24a6a35a9563385d7b336e958f179484fa3e16"
JOCKEY_BASIS = "jockey365_past_field_relative_top3_sum"
SHRINKAGE_STARTS = 20.0


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


def _load_module(name: str, path: Path):
    path = checked(path)
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot import frozen helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_helpers():
    """Import the unchanged pair fit/core helpers and this study's input code."""
    require(sha256(BASE_FIT) == BASE_H1_SHA256, "frozen expanded H1 moments changed")
    require(sha256(BASE_FIT_RECEIPT) == BASE_FIT_RECEIPT_SHA256, "frozen expanded fit receipt changed")
    require(sha256(DIRECT_CORE) == BASE_CORE_SHA256, "frozen direct-pair core changed")
    require(sha256(BASE / "pair_fit.py") == BASE_PAIR_FIT_SHA256, "frozen expanded fit helper changed")
    core = _load_module("frozen_direct_pair_core_jockey_basic", DIRECT_CORE)
    pair_fit = _load_module("frozen_expanded_pair_fit_jockey_basic", BASE / "pair_fit.py")
    jockey_input = _load_module("pair_jockey_input_for_fit", STUDY / "jockey_input.py")
    historical_path = checked(BASE_HISTORICAL_RECEIPT)
    historical = json.loads(historical_path.read_text(encoding="utf-8"))
    base_receipt = json.loads(checked(BASE_FIT_RECEIPT).read_text(encoding="utf-8"))
    require(base_receipt.get("historical_refit_receipt_sha256") == sha256(historical_path),
            "historical score receipt differs from the frozen baseline fit lineage")
    require(historical.get("status") == "PASS" and historical.get("pair_fit_performed") is False
            and historical.get("pair_performance_metrics_computed") is False,
            "historical score receipt scope changed")
    return core, pair_fit, jockey_input, historical


def load_baseline_fit() -> dict[str, Any]:
    require(sha256(BASE_FIT) == BASE_H1_SHA256, "frozen expanded H1 fit changed")
    receipt = json.loads(checked(BASE_FIT_RECEIPT).read_text(encoding="utf-8"))
    require(receipt.get("status") == "PASS" and receipt.get("h1_fit_count") == 3,
            "frozen baseline pair fit receipt is not PASS")
    require(receipt.get("expanded_h1_fit_sha256") == BASE_H1_SHA256,
            "frozen baseline H1 fit receipt/hash mismatch")
    return json.loads(checked(BASE_FIT).read_text(encoding="utf-8"))


def prepare_training_rows(pair_fit, jockey_input, historical: dict[str, Any]):
    """Read only the locked H1/H2 runner families and attach T-2 history."""
    features = pair_fit.read_features()
    starts = jockey_input.load_starts(include_results=True)
    yearly: dict[int, pd.DataFrame] = {}
    score_sources: dict[str, Any] = {}
    for year in range(2019, 2026):
        rows, source = pair_fit.read_year_scores(features, year, historical)
        for key in ("api_record_id", "race_id", "horse_id"):
            rows[key] = rows[key].astype("string")
        rows["race_date"] = pd.to_datetime(rows["race_date"], errors="coerce").dt.normalize()
        require(rows["race_date"].notna().all(), f"invalid normalized training date: {year}")
        event = jockey_input.attach_event_jockey(rows, starts)
        rolling = jockey_input.rolling_features(event, starts)
        joined = event.merge(
            rolling[["api_record_id", "jockey365_n", "jockey365_top3", "jockey365_expected_top3", "jockey365_field_relative_top3"]],
            on="api_record_id", how="left", validate="one_to_one",
        )
        require(joined["jockey365_field_relative_top3"].notna().all(), f"rolling rider value missing: {year}")
        require(len(joined) == len(rows) and joined["api_record_id"].is_unique, f"training runner coverage changed: {year}")
        yearly[year] = joined
        score_sources[str(year)] = source
    return yearly, score_sources


def split_h1_h2(yearly: dict[int, pd.DataFrame], evaluation_year: int):
    """Reuse the existing expanded pair's exact H1/H2 calendar split and purge."""
    calibration_year = evaluation_year - 1
    source = yearly[calibration_year]
    h2 = source.loc[source["race_date"].dt.month.ge(7)].copy()
    first_h2 = h2["race_date"].min().date()
    cutoff = first_h2 - timedelta(days=2)
    h1_parts = [yearly[year] for year in range(2019, evaluation_year - 1)]
    current = source.loc[
        source["race_date"].dt.month.le(6)
        & source["race_date"].dt.date.map(lambda value: value <= cutoff)
    ].copy()
    h1_parts.append(current)
    h1 = pd.concat(h1_parts, ignore_index=True)
    require(h1["api_record_id"].is_unique and h2["api_record_id"].is_unique,
            f"duplicate runner key in H1/H2: {evaluation_year}")
    require(h1["race_id"].nunique() == H1_RACES[evaluation_year], f"H1 race count changed: {evaluation_year}")
    require(h2["race_id"].nunique() == H2_RACES[evaluation_year], f"H2 race count changed: {evaluation_year}")
    require(h1["race_date"].max().date() <= first_h2 - timedelta(days=2),
            f"H1/H2 2-day purge failed: {evaluation_year}")
    return h1, h2


def stats_from_baseline(core, fit_row: dict[str, Any]):
    """Rebuild the stored runner and 20-basis moments without refitting them."""
    require(list(fit_row["pair_standardization"]) == list(core.BASIS_NAMES),
            "frozen 20-basis standardization names/order changed")
    runner_doc = fit_row["runner_standardization"]
    pair_doc = fit_row["pair_standardization"]
    runner = core.Standardization(
        columns=core.RUNNER_COLUMNS,
        mean=np.asarray([runner_doc[name]["mean"] for name in core.RUNNER_COLUMNS], dtype=float),
        scale=np.asarray([runner_doc[name]["scale"] for name in core.RUNNER_COLUMNS], dtype=float),
        degenerate=tuple(bool(runner_doc[name]["degenerate"]) for name in core.RUNNER_COLUMNS),
        support_weight=tuple(float(runner_doc[name]["support_weight"]) for name in core.RUNNER_COLUMNS),
    )
    pair = core.PairStandardization(
        mean=np.asarray([pair_doc[name]["mean"] for name in core.BASIS_NAMES], dtype=float),
        scale=np.asarray([pair_doc[name]["scale"] for name in core.BASIS_NAMES], dtype=float),
        degenerate=tuple(bool(pair_doc[name]["degenerate"]) for name in core.BASIS_NAMES),
        support_weight=tuple(float(pair_doc[name]["support_weight"]) for name in core.BASIS_NAMES),
    )
    require(len(runner.mean) == 7 and len(pair.mean) == 20, "frozen baseline moments have wrong dimension")
    return runner, pair


def candidate_pair_bases(core, races: list[dict[str, Any]]):
    """Append symmetric d_i+d_j to each race's unchanged raw 20-vector basis."""
    raw20: list[np.ndarray] = []
    rider_sum: list[np.ndarray] = []
    for race in races:
        rows = race["rows"].sort_values("horse_number", kind="mergesort")
        by_number = {
            int(row.horse_number): float(row.jockey365_field_relative_top3)
            for row in rows.itertuples(index=False)
        }
        rider_values = np.asarray(
            [by_number[a] + by_number[b] for a, b in race["pairs"]], dtype=float,
        )
        basis20 = np.asarray(race["basis"], dtype=float)
        require(basis20.shape == (len(rider_values), 20), "base pair basis shape changed")
        require(np.isfinite(rider_values).all(), "non-finite symmetric rider pair input")
        raw20.append(basis20)
        rider_sum.append(rider_values)
    require(bool(races) and len(raw20) == len(rider_sum), "empty or mismatched race pair bases")
    return raw20, rider_sum


def fit_rider_pair_moments(rider_sum: list[np.ndarray]) -> dict[str, Any]:
    """Use the frozen race-equal pair-weight convention for the 21st scalar only."""
    require(bool(rider_sum) and all(x.ndim == 1 and len(x) > 0 and np.isfinite(x).all() for x in rider_sum),
            "invalid H1 rider-pair basis")
    mean = float(np.mean(np.asarray([x.mean() for x in rider_sum], dtype=float)))
    variance = float(np.mean(np.asarray([((x - mean) ** 2).mean() for x in rider_sum], dtype=float)))
    require(math.isfinite(mean) and math.isfinite(variance) and variance >= 0.0,
            "invalid H1 rider-pair moments")
    scale = math.sqrt(variance)
    degenerate = scale <= 1e-12
    return {
        "mean": 0.0 if degenerate else mean,
        "scale": 1.0 if degenerate else scale,
        "degenerate": bool(degenerate),
        "support_weight": float(len(rider_sum)),
        "standardization_scope": "H1-only race-equal pair rows, race total weight 1",
    }


def transform_candidate_basis(core, races, old_pair_stats, rider_moments):
    raw20, rider_sum = candidate_pair_bases(core, races)
    x_values = []
    p_values = []
    y_values = []
    id_values = []
    for race, basis20, rider in zip(races, raw20, rider_sum, strict=True):
        base_x = core.transform_pair_basis(basis20, old_pair_stats)
        rider_x = np.zeros(len(rider), dtype=float) if rider_moments["degenerate"] else (
            rider - float(rider_moments["mean"])
        ) / float(rider_moments["scale"])
        x = np.column_stack((base_x, rider_x))
        require(x.shape == (len(race["pairs"]), 21) and np.isfinite(x).all(),
                "invalid standardized 21-column pair design")
        # Guard exact preservation of the frozen first 20 columns.
        require(np.array_equal(x[:, :20], base_x), "old 20 standardized columns changed")
        x_values.append(x)
        p_values.append(np.asarray(race["p0"], dtype=float))
        y_values.append(np.asarray(race["labels"], dtype=float))
        id_values.append(np.full(len(race["pairs"]), race["race_id"], dtype=object))
    return np.vstack(x_values), np.concatenate(p_values), np.concatenate(y_values), np.concatenate(id_values)


def loss_gradient_21(core, beta, basis, p0, labels, race_ids):
    """The frozen 20-d BCE/ridge objective extended by one coefficient, lambda=1."""
    x = np.asarray(basis, dtype=float)
    b = np.asarray(beta, dtype=float)
    y = np.asarray(labels, dtype=float)
    prior = np.asarray(p0, dtype=float)
    require(x.ndim == 2 and x.shape[1] == 21 and b.shape == (21,), "candidate design/coefficient shape mismatch")
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


def fit_h1_21(core, basis, p0, labels, race_ids):
    """One no-retry L-BFGS-B fit with the frozen recipe and 21 coefficients."""
    result = minimize(
        fun=lambda beta: loss_gradient_21(core, beta, basis, p0, labels, race_ids),
        x0=np.zeros(21, dtype=float), method="L-BFGS-B", jac=True,
        options={"maxiter": core.H1_MAXITER, "ftol": core.H1_FTOL, "gtol": core.H1_GTOL},
    )
    require(result.success and np.isfinite(result.x).all() and np.isfinite(result.fun) and np.isfinite(result.jac).all(),
            f"candidate H1 optimizer failed: {result.message}")
    require(float(np.max(np.abs(result.jac))) <= core.ACCEPT_GRAD_INF,
            f"candidate H1 stationarity failed: {np.max(np.abs(result.jac))}")
    return result


def fit_candidate_fold(core, pair_fit, evaluation_year: int, h1: pd.DataFrame, h2: pd.DataFrame,
                       fit_row: dict[str, Any]):
    """Fit one approved fold; return in-memory parameters/metadata without writing."""
    runner_stats, old_pair_stats = stats_from_baseline(core, fit_row)
    h1_races = pair_fit.build_races(core, h1, runner_stats)
    require(all(int(np.asarray(race["labels"]).sum()) == 3 for race in h1_races),
            f"H1 positive-pair arithmetic changed: {evaluation_year}")
    old_x_h1 = [core.transform_pair_basis(race["basis"], old_pair_stats) for race in h1_races]
    raw20_h1, rider_h1 = candidate_pair_bases(core, h1_races)
    require(all(np.array_equal(x, core.transform_pair_basis(raw, old_pair_stats))
                for x, raw in zip(old_x_h1, raw20_h1, strict=True)),
            "candidate H1 changed a frozen 20-column pair transform")
    rider_moments = fit_rider_pair_moments(rider_h1)
    x_h1, p0_h1, y_h1, id_h1 = transform_candidate_basis(core, h1_races, old_pair_stats, rider_moments)
    result = fit_h1_21(core, x_h1, p0_h1, y_h1, id_h1)

    h2_races = pair_fit.build_races(core, h2, runner_stats)
    require(all(int(np.asarray(race["labels"]).sum()) == 3 for race in h2_races),
            f"H2 positive-pair arithmetic changed: {evaluation_year}")
    x_h2, p0_h2, y_h2, id_h2 = transform_candidate_basis(core, h2_races, old_pair_stats, rider_moments)
    eta_h2 = logit(p0_h2) + x_h2 @ result.x
    calibration = core.fit_platt(eta_h2, y_h2, id_h2)
    require(float(calibration.x[1]) > 0.0, "candidate H2 calibrator must preserve pair ranking")
    require(len(h1_races) == H1_RACES[evaluation_year] and len(h2_races) == H2_RACES[evaluation_year],
            f"candidate fold count mismatch: {evaluation_year}")
    require(int(y_h1.sum()) == 3 * len(h1_races) and int(y_h2.sum()) == 3 * len(h2_races),
            f"candidate H1/H2 positive-pair total changed: {evaluation_year}")
    return {
        "evaluation_year": evaluation_year,
        "h1_races": len(h1_races), "h1_dates": int(h1["race_date"].dt.date.nunique()),
        "h1_rows": len(h1), "h1_pairs": len(y_h1), "positive_pairs": int(y_h1.sum()),
        "h2_races": len(h2_races), "h2_dates": int(h2["race_date"].dt.date.nunique()),
        "h2_pairs": len(y_h2), "h2_positive_pairs": int(y_h2.sum()),
        "h1_last_date": h1["race_date"].max().date().isoformat(),
        "h2_first_date": h2["race_date"].min().date().isoformat(),
        "old_pair_moments": fit_row["pair_standardization"],
        "new_pair_moment": rider_moments,
        "beta_by_basis": {name: float(result.x[i]) for i, name in enumerate(core.BASIS_NAMES)},
        "gamma_jockey365_pair_sum": float(result.x[20]),
        "optimizer": {
            "success": bool(result.success), "status": int(result.status), "message": str(result.message),
            "iterations": int(result.nit), "function_evaluations": int(result.nfev),
            "objective": float(result.fun), "gradient_inf_norm": float(np.max(np.abs(result.jac))),
        },
        "h2_candidate_platt": {
            "A": float(calibration.x[0]), "B": float(calibration.x[1]),
            "projected_gradient_inf_norm": float(np.max(np.abs(calibration.projected_gradient))),
            "objective": float(calibration.fun), "iterations": int(calibration.nit),
            "success": bool(calibration.success),
        },
        "_runner_stats": runner_stats, "_old_pair_stats": old_pair_stats,
        "_beta": np.asarray(result.x, dtype=float), "_rider_moments": rider_moments,
    }


def fit_three_folds(core, pair_fit, yearly: dict[int, pd.DataFrame], baseline_fit: dict[str, Any]):
    """Run the single 3-H1 + 3-candidate-H2 arm after caller approval."""
    folds = []
    for evaluation_year in FIT_YEARS:
        h1, h2 = split_h1_h2(yearly, evaluation_year)
        fit_row = next(row for row in baseline_fit["folds"] if int(row["evaluation_year"]) == evaluation_year)
        folds.append(fit_candidate_fold(core, pair_fit, evaluation_year, h1, h2, fit_row))
    return folds


def run_approved_fit() -> None:
    """Validate the single pinned root approval, fit once, and save immediately."""
    core, pair_fit, jockey_input, historical = load_helpers()
    approval = json.loads(checked(APPROVAL).read_text(encoding="utf-8"))
    source_record = json.loads(checked(SOURCE_PREFLIGHT).read_text(encoding="utf-8"))
    require(approval.get("approved") is True and approval.get("approved_by") == "root",
            "root approval is required for candidate fit")
    require(approval.get("scope") == "pair_jockey_basic_h1_h2_fit", "approval scope mismatch")
    require(approval.get("plan_sha256") == sha256(STUDY / "PLAN.md"), "approval plan hash mismatch")
    require(approval.get("input_helper_sha256") == sha256(STUDY / "jockey_input.py"),
            "approval rolling-input helper hash mismatch")
    require(approval.get("fit_code_sha256") == sha256(Path(__file__).resolve()),
            "approval fit-code hash mismatch")
    require(approval.get("source_preflight_sha256") == sha256(SOURCE_PREFLIGHT),
            "approval source-preflight hash mismatch")
    require(source_record.get("status") == "PASS" and source_record.get("finish_labels_read") is False,
            "source preflight is not a no-label PASS")
    current_preflight = jockey_input.preflight_source()
    require(current_preflight == source_record, "current source preflight differs from the pinned preflight")
    require(not FIT_PATH.exists() and not FIT_RECEIPT_PATH.exists(), "candidate fit outputs already exist")

    baseline_fit = load_baseline_fit()
    yearly, score_sources = prepare_training_rows(pair_fit, jockey_input, historical)
    fitted = fit_three_folds(core, pair_fit, yearly, baseline_fit)
    fold_documents = []
    for fold in fitted:
        fold_documents.append({key: value for key, value in fold.items() if not key.startswith("_")})
    document = {
        "status": "PASS",
        "study": STUDY.name,
        "scope": "one 365-day jockey-basic-information arm; H1/H2 fitting only",
        "candidate_input": {
            "history_window": "C=T-2 calendar days; (C-365 days,C]",
            "rider_value": "(past Top3 count - sum(3/field_n))/(eligible observed starts + 20); n=0 -> 0",
            "pair_basis": "symmetric d_i+d_j appended after unchanged 20 style pair columns",
            "interpretation": "past observed field-relative Top3 frequency measure; not rider ability",
            "rider_id_role": "official event ID used only to group historical starts",
        },
        "model": "race-equal pair BCE with fixed lambda=1, no intercept; candidate beta20+gamma jointly fit",
        "baseline_preserved": {
            "study": "20261011_pair_top3_oos_expansion_v1",
            "h1_fit_sha256": sha256(BASE_FIT),
            "fit_receipt_sha256": sha256(BASE_FIT_RECEIPT),
            "direct_core_sha256": sha256(DIRECT_CORE),
            "baseline_coefficients_refit_or_modified": False,
            "first_20_h1_moments_reused_exactly": True,
        },
        "source_preflight_sha256": sha256(SOURCE_PREFLIGHT),
        "approval_sha256": sha256(APPROVAL),
        "score_sources_by_race_year": score_sources,
        "h1_fit_count": 3,
        "h2_candidate_map_count": 3,
        "folds": fold_documents,
        "evaluation_predictions_generated": False,
        "performance_metrics_computed": False,
    }
    jockey_input.write_once(FIT_PATH, document)
    receipt = {
        "status": "PASS", "study": STUDY.name,
        "scope": "single approved arm H1/H2 fits only; no evaluation prediction or performance metric",
        "h1_fit_count": 3, "h2_candidate_map_count": 3,
        "evaluation_predictions_generated": False, "performance_metrics_computed": False,
        "plan_sha256": sha256(STUDY / "PLAN.md"),
        "input_helper_sha256": sha256(STUDY / "jockey_input.py"),
        "fit_code_sha256": sha256(Path(__file__).resolve()),
        "source_preflight_sha256": sha256(SOURCE_PREFLIGHT),
        "approval_sha256": sha256(APPROVAL),
        "frozen_baseline_h1_sha256": sha256(BASE_FIT),
        "candidate_fit_sha256": sha256(FIT_PATH),
    }
    jockey_input.write_once(FIT_RECEIPT_PATH, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "fit-approved":
        raise SystemExit("usage: pair_jockey_fit.py fit-approved")
    run_approved_fit()
