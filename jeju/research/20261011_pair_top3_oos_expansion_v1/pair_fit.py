"""Fit the frozen direct-pair model on expanded historical-OOS H1 rows only."""

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
from scipy.special import logit

sys.dont_write_bytecode = True

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
OUT = STUDY / "outputs"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
STYLE_OUT = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
DIRECT_CORE = ROOT / "jeju/research/20261011_pair_top3_direct_v1/core.py"
HISTORICAL_RECEIPT = OUT / "HISTORICAL_REFIT_RECEIPT.json"
SOURCE_LOCK = OUT / "HISTORICAL_SOURCE_LOCK.json"
PREFLIGHT = OUT / "HISTORICAL_PREFLIGHT.json"
APPROVAL = OUT / "PAIR_FIT_APPROVAL.json"
FIT_RECEIPT = OUT / "PAIR_FIT_RECEIPT.json"
H1_PATH = OUT / "expanded_h1_fit.json"
H2_PATH = OUT / "expanded_h2_calibration.json"
FIT_YEARS = (2024, 2025, 2026)
EXPANDED_RACES = {2024: 2147, 2025: 2818, 2026: 3458}
H2_RACES = {2024: 336, 2025: 311, 2026: 325}
INPUT_COLUMNS = [
    "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
    "field_n", "finish_position", "hist_s1f_relpos_mean5", "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
]


class PairFitError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise PairFitError(message)


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
    require(path.resolve().is_relative_to(STUDY), f"output escaped study: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def load_core():
    path = checked(DIRECT_CORE)
    spec = importlib.util.spec_from_file_location("frozen_direct_pair_core", path)
    require(spec is not None and spec.loader is not None, "cannot import frozen direct-pair core")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_stage_gates() -> tuple[dict, dict, dict]:
    require(PREFLIGHT.is_file() and SOURCE_LOCK.is_file() and HISTORICAL_RECEIPT.is_file(),
            "historical source preflight and raw-score receipt must pass first")
    preflight = json.loads(checked(PREFLIGHT).read_text(encoding="utf-8"))
    lock = json.loads(checked(SOURCE_LOCK).read_text(encoding="utf-8"))
    historical = json.loads(checked(HISTORICAL_RECEIPT).read_text(encoding="utf-8"))
    approval = json.loads(checked(APPROVAL).read_text(encoding="utf-8"))
    require(preflight.get("status") == "PASS" and lock.get("status") == "PASS", "source preflight/lock not PASS")
    require(isinstance(lock.get("sources"), dict) and bool(lock["sources"]), "source lock has no source hashes")
    for relative, expected_hash in lock["sources"].items():
        source_path = checked(ROOT / relative)
        require(sha256(source_path) == expected_hash, f"locked source changed: {relative}")
    require(historical.get("status") == "PASS" and historical.get("calibration_raw_scores_generated") is True,
            "historical OOS raw-score generation is incomplete")
    require(historical.get("pair_fit_performed") is False and historical.get("pair_performance_metrics_computed") is False,
            "historical score stage contains pair fit or performance work")
    require(historical.get("lightgbm_train_calls") == 8 and historical.get("temperature_optimizations") == 0,
            "historical score receipt scope changed")
    require([int(row["fold"]) for row in historical.get("folds", [])] == [2020, 2021, 2022, 2023],
            "historical score provider folds are incomplete or reordered")
    require(approval.get("approved") is True and approval.get("approved_by") == "root", "root pair-fit approval required")
    require(approval.get("scope") == "expanded_direct_pair_h1_h2_fit_only", "pair-fit approval scope mismatch")
    require(approval.get("years") == list(FIT_YEARS) and approval.get("h1_fit_count") == 3 and approval.get("h2_map_count") == 6,
            "pair-fit approval budget mismatch")
    require(approval.get("preflight_sha256") == sha256(PREFLIGHT), "pair approval preflight pin mismatch")
    require(approval.get("source_lock_sha256") == sha256(SOURCE_LOCK), "pair approval source-lock pin mismatch")
    require(approval.get("historical_receipt_sha256") == sha256(HISTORICAL_RECEIPT), "pair approval historic-score pin mismatch")
    require(approval.get("pair_fit_sha256") == sha256(Path(__file__).resolve()), "pair approval code hash mismatch")
    require(approval.get("direct_core_sha256") == sha256(checked(DIRECT_CORE)), "direct core hash mismatch")
    require(approval.get("plan_sha256") == sha256(STUDY / "PLAN.md"), "plan hash mismatch")
    require(not FIT_RECEIPT.exists() and not H1_PATH.exists() and not H2_PATH.exists(), "pair outputs already exist")
    return preflight, lock, historical


def read_features() -> pd.DataFrame:
    frame = pd.read_parquet(
        checked(FEATURES), columns=INPUT_COLUMNS,
        filters=[("year", ">=", 2019), ("year", "<=", 2025)],
    )
    frame["race_date"] = pd.to_datetime(frame["race_date"], errors="coerce")
    require(frame["race_date"].notna().all(), "invalid feature race date")
    require(frame["api_record_id"].is_unique, "feature runner key is not unique")
    require(frame["year"].between(2019, 2025).all(), "fit-stage feature filter included out-of-scope labels")
    return frame


def score_source(calibration_year: int) -> tuple[Path, int]:
    require(2019 <= calibration_year <= 2025, f"unsupported calibration year: {calibration_year}")
    fold = calibration_year + 1
    historical_path = OUT / f"F1_STYLE6_{fold}/calibration_scores.parquet"
    if fold in (2020, 2021, 2022, 2023):
        return historical_path, fold
    return STYLE_OUT / f"F1_STYLE6_{fold}/calibration_scores.parquet", fold


def read_year_scores(features: pd.DataFrame, year: int, historical: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    path, provider_fold = score_source(year)
    path = checked(path)
    scores = pd.read_parquet(path)
    require(scores.columns.tolist() == ["api_record_id", "score"], f"unexpected score schema: {path}")
    require(scores["api_record_id"].is_unique, f"duplicate API score key: {path}")
    require(np.isfinite(scores["score"].to_numpy(dtype=float)).all(), f"nonfinite scores: {path}")
    rows = features.loc[features["year"].eq(year)].copy()
    require(set(scores["api_record_id"]) == set(rows["api_record_id"]), f"score coverage mismatch for {year}")
    joined = rows.merge(scores, on="api_record_id", how="left", validate="one_to_one")
    require(joined["score"].notna().all(), f"score missing for year {year}")
    meta_path = OUT / f"F1_STYLE6_{provider_fold}/meta.json" if provider_fold <= 2023 else STYLE_OUT / f"F1_STYLE6_{provider_fold}/meta.json"
    meta = json.loads(checked(meta_path).read_text(encoding="utf-8"))
    refit_max = pd.Timestamp(meta["refit_max"]).normalize()
    dates = joined["race_date"].dt.normalize()
    require((dates - pd.Timedelta(days=2) >= refit_max).all(), f"provider {provider_fold} violates row-level T-2 for {year}")
    source = {
        "race_year": year,
        "provider_fold_year": provider_fold,
        "provider_role": "calibration",
        "source_path": str(path.relative_to(ROOT)),
        "source_sha256": sha256(path),
        "meta_path": str(meta_path.relative_to(ROOT)),
        "meta_sha256": sha256(meta_path),
        "refit_max": meta["refit_max"],
        "rows": int(len(joined)),
        "races": int(joined["race_id"].nunique()),
    }
    if provider_fold <= 2023:
        fold_receipt = next((item for item in historical["folds"] if int(item["fold"]) == provider_fold), None)
        require(fold_receipt is not None, f"missing historical score receipt fold {provider_fold}")
        require(source["source_sha256"] == fold_receipt["calibration_scores_sha256"],
                f"historical score hash differs from fit receipt: fold {provider_fold}")
        require(source["meta_sha256"] == fold_receipt["meta_sha256"],
                f"historical metadata hash differs from fit receipt: fold {provider_fold}")
        require(sha256(checked(OUT / f"F1_STYLE6_{provider_fold}/top3.txt")) == fold_receipt["model_sha256"],
                f"historical model hash differs from fit receipt: fold {provider_fold}")
    joined["score_provider_fold_year"] = provider_fold
    joined["score_provider_role"] = "calibration"
    joined["score_source_path"] = source["source_path"]
    joined["score_source_sha256"] = source["source_sha256"]
    return joined, source


def build_races(core, rows: pd.DataFrame, runner_stats) -> list[dict[str, Any]]:
    result = []
    for race_id, race in rows.groupby("race_id", sort=True):
        race = race.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
        z, missing = core.transform_runners(race, runner_stats)
        prior, _ = core.q0_from_scores(race["horse_number"].astype(int).tolist(), race["score"].astype(float).tolist())
        pairs, basis, labels, p0 = core.enumerate_race_pairs(race, z, missing, prior)
        result.append({
            "race_id": str(race_id),
            "race_date": race["race_date"].iloc[0].date().isoformat(),
            "rows": race,
            "pairs": pairs,
            "basis": basis,
            "labels": labels,
            "p0": p0,
        })
    require(bool(result), "empty race-pair input")
    return result


def flatten(core, races: list[dict[str, Any]], pair_stats):
    bases, priors, labels, race_ids = [], [], [], []
    for race in races:
        bases.append(core.transform_pair_basis(race["basis"], pair_stats))
        priors.append(race["p0"])
        labels.append(race["labels"])
        race_ids.append(np.full(len(race["pairs"]), race["race_id"], dtype=object))
    return np.vstack(bases), np.concatenate(priors), np.concatenate(labels), np.concatenate(race_ids)


def stats_json(stats, names) -> dict[str, Any]:
    return {
        name: {
            "mean": float(stats.mean[index]), "scale": float(stats.scale[index]),
            "degenerate": bool(stats.degenerate[index]), "support_weight": float(stats.support_weight[index]),
        }
        for index, name in enumerate(names)
    }


def optimizer_json(result) -> dict[str, Any]:
    return {
        "success": bool(result.success), "status": int(result.status), "message": str(result.message),
        "iterations": int(result.nit), "function_evaluations": int(result.nfev),
        "objective": float(result.fun), "gradient": [float(x) for x in result.jac],
        "gradient_inf_norm": float(np.max(np.abs(result.jac))),
    }


def fit_h2_map(core, name: str, values, labels, race_ids, races) -> dict[str, Any]:
    result = core.fit_platt(values, labels, race_ids)
    projected = core.projected_gradient(result.x, result.jac)
    boundaries = [
        "lower" if value == bounds[0] else "upper" if value == bounds[1] else "interior"
        for value, bounds in zip(result.x, core.PLATT_BOUNDS, strict=True)
    ]
    require(result.success and np.isfinite(result.x).all() and np.isfinite(result.fun), f"H2 map optimizer failed: {name}")
    require(float(np.max(np.abs(projected))) <= core.ACCEPT_GRAD_INF, f"H2 projected gradient failed: {name}")
    return {
        "map": name, "raw_input_family": "candidate_eta" if name == "candidate" else "logit_p0",
        "A": float(result.x[0]), "B": float(result.x[1]),
        "bounds": {"A": list(core.PLATT_BOUNDS[0]), "B": list(core.PLATT_BOUNDS[1])},
        "boundary_status": {"A": boundaries[0], "B": boundaries[1]},
        "projected_gradient": [float(x) for x in projected],
        "projected_gradient_inf_norm": float(np.max(np.abs(projected))),
        **optimizer_json(result), "h2_races": int(len(races)),
        "h2_dates": int(len({race["race_date"] for race in races})),
        "h2_pairs": int(len(labels)), "positive_pairs": int(labels.sum()),
    }


def run() -> None:
    preflight, lock, historical = verify_stage_gates()
    core = load_core()
    features = read_features()
    yearly = {}
    source_rows = {}
    for year in range(2019, 2026):
        yearly[year], source_rows[str(year)] = read_year_scores(features, year, historical)

    h1_results = []
    h2_results = []
    for evaluation_year in FIT_YEARS:
        calibration_year = evaluation_year - 1
        h2_dates_rows = yearly[calibration_year]
        h2 = h2_dates_rows.loc[pd.to_datetime(h2_dates_rows["race_date"]).dt.month.ge(7)].copy()
        first_h2 = h2["race_date"].min().date()
        cutoff = first_h2 - timedelta(days=2)
        h1_parts = [yearly[y] for y in range(2019, evaluation_year - 1)]
        current_h1 = h2_dates_rows.loc[
            pd.to_datetime(h2_dates_rows["race_date"]).dt.month.le(6)
            & pd.to_datetime(h2_dates_rows["race_date"]).dt.date.map(lambda value: value <= cutoff)
        ].copy()
        h1_parts.append(current_h1)
        h1 = pd.concat(h1_parts, ignore_index=True)
        require(not h1.duplicated(["api_record_id", "score_provider_fold_year", "score_provider_role"]).any(),
                f"duplicate H1 score-provider runner key for {evaluation_year}")
        require(not h1.duplicated(["api_record_id"]).any(), f"score family mixed/deduplicated in H1 {evaluation_year}")
        require(not h2.duplicated(["api_record_id"]).any(), f"duplicate H2 runner key {evaluation_year}")
        require(h1["race_id"].nunique() == EXPANDED_RACES[evaluation_year], f"expanded H1 count changed: {evaluation_year}")
        require(h2["race_id"].nunique() == H2_RACES[evaluation_year], f"H2 count changed: {evaluation_year}")
        require(h1["race_date"].max().date() <= first_h2 - timedelta(days=2), f"H1/H2 purge failed: {evaluation_year}")

        runner_stats = core.fit_runner_standardization(h1, h1["race_id"].astype(str).to_numpy())
        h1_races = build_races(core, h1, runner_stats)
        pair_stats = core.fit_pair_standardization([race["basis"] for race in h1_races])
        x_h1, p0_h1, y_h1, id_h1 = flatten(core, h1_races, pair_stats)
        h1_optimizer = core.fit_h1(np.zeros(20, dtype=float), x_h1, p0_h1, y_h1, id_h1)
        beta = np.asarray(h1_optimizer.x, dtype=float)
        require(h1_optimizer.success and np.isfinite(beta).all(), f"H1 optimizer failed: {evaluation_year}")
        require(float(np.max(np.abs(h1_optimizer.jac))) <= core.ACCEPT_GRAD_INF, f"H1 gradient failed: {evaluation_year}")
        require(int(y_h1.sum()) == 3 * len(h1_races), f"H1 label arithmetic failed: {evaluation_year}")

        h2_races = build_races(core, h2, runner_stats)
        x_h2, p0_h2, y_h2, id_h2 = flatten(core, h2_races, pair_stats)
        candidate_logits = logit(p0_h2) + x_h2 @ beta
        baseline_logits = logit(p0_h2)
        candidate = fit_h2_map(core, "candidate", candidate_logits, y_h2, id_h2, h2_races)
        baseline = fit_h2_map(core, "baseline", baseline_logits, y_h2, id_h2, h2_races)
        require(candidate["h2_races"] == baseline["h2_races"], "candidate/baseline H2 race mismatch")

        h1_results.append({
            "evaluation_year": evaluation_year,
            "calibration_year": calibration_year,
            "h1_races": int(len(h1_races)),
            "h1_dates": int(h1["race_date"].dt.date.nunique()),
            "h1_rows": int(len(h1)), "h1_pairs": int(len(y_h1)),
            "positive_pairs": int(y_h1.sum()),
            "h1_sources": [source_rows[str(y)] for y in range(2019, evaluation_year - 1)] + [source_rows[str(calibration_year)]],
            "h1_last_date": h1["race_date"].max().date().isoformat(),
            "h2_first_date": first_h2.isoformat(),
            "runner_standardization": stats_json(runner_stats, core.RUNNER_COLUMNS),
            "pair_standardization": stats_json(pair_stats, core.BASIS_NAMES),
            "beta_by_basis": {name: float(beta[index]) for index, name in enumerate(core.BASIS_NAMES)},
            **optimizer_json(h1_optimizer),
        })
        h2_results.extend([
            {"evaluation_year": evaluation_year, "calibration_year": calibration_year, **candidate},
            {"evaluation_year": evaluation_year, "calibration_year": calibration_year, **baseline},
        ])

    fit_document = {
        "study": STUDY.name, "scope": "expanded H1 and unchanged H2 fit only; no evaluation scoring/metrics",
        "source_lock_sha256": sha256(SOURCE_LOCK), "preflight_sha256": sha256(PREFLIGHT),
        "historical_refit_receipt_sha256": sha256(HISTORICAL_RECEIPT),
        "pair_fit_approval_sha256": sha256(APPROVAL), "direct_core_sha256": sha256(DIRECT_CORE),
        "model": "symmetric_direct_pair_bce_ridge", "lambda": core.LAMBDA,
        "basis_names": list(core.BASIS_NAMES), "folds": h1_results,
    }
    calibration_document = {
        "study": STUDY.name, "calibration": "separate_race_equal_positive_slope_platt",
        "maxiter": 500, "ftol": 1e-12, "gtol": 1e-8, "fold_maps": h2_results,
        "pair_fit_approval_sha256": sha256(APPROVAL),
    }
    write_json_once(H1_PATH, fit_document)
    write_json_once(H2_PATH, calibration_document)
    receipt = {
        "status": "PASS", "study": STUDY.name,
        "h1_fit_count": len(h1_results), "h2_map_count": len(h2_results),
        "scope": "pair fits only; no evaluation predictions or performance metrics",
        "evaluation_scores_used_for_fit": False,
        "evaluation_predictions_generated": False,
        "performance_metrics_computed": False,
        "source_lock_sha256": sha256(SOURCE_LOCK),
        "preflight_sha256": sha256(PREFLIGHT),
        "historical_refit_receipt_sha256": sha256(HISTORICAL_RECEIPT),
        "pair_fit_approval_sha256": sha256(APPROVAL),
        "pair_fit_code_sha256": sha256(Path(__file__).resolve()),
        "direct_core_sha256": sha256(DIRECT_CORE),
        "expanded_h1_fit_sha256": sha256(H1_PATH),
        "expanded_h2_calibration_sha256": sha256(H2_PATH),
    }
    write_json_once(FIT_RECEIPT, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "fit-approved-expanded-pair":
        raise SystemExit("usage: pair_fit.py fit-approved-expanded-pair")
    run()
