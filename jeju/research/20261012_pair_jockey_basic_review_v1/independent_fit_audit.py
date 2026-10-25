"""Independent post-fit H1/H2 arithmetic audit; no optimizer or candidate code imports."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from independent_jockey_reference import (
    fit_jockey_pair_moments,
    h1_objective_gradient_21,
    h2_objective_gradient,
    pair_jockey_sums,
    ref,
    standardize_21d_basis,
)


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
OUT = STUDY / "outputs"
REVIEW = Path(__file__).resolve().parent
APPROVAL = OUT / "APPROVAL.json"
SOURCE_PREFLIGHT = OUT / "SOURCE_PREFLIGHT.json"
FIT_PATH = OUT / "FIT.json"
FIT_RECEIPT_PATH = OUT / "FIT_RECEIPT.json"
BASE = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
BASE_OUT = BASE / "outputs"
BASE_FIT_PATH = BASE_OUT / "expanded_h1_fit.json"
BASE_FIT_RECEIPT_PATH = BASE_OUT / "PAIR_FIT_RECEIPT.json"
BASE_HISTORICAL_RECEIPT_PATH = BASE_OUT / "HISTORICAL_REFIT_RECEIPT.json"
FEATURES_PATH = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
STARTS_PATH = ROOT / "jeju/research/20261009_jockey_effects_v1/input01/starts.csv"
EVAL_YEARS = (2024, 2025, 2026)
H1_COUNTS = {2024: 2147, 2025: 2818, 2026: 3458}
H2_COUNTS = {2024: 336, 2025: 311, 2026: 325}
PLATT_BOUNDS = ((-20.0, 20.0), (0.05, 20.0))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"required JSON missing/symlink: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def verify_approved_artifacts() -> tuple[dict, dict, dict, dict, dict]:
    approval = read_json(APPROVAL)
    preflight = read_json(SOURCE_PREFLIGHT)
    fit = read_json(FIT_PATH)
    fit_receipt = read_json(FIT_RECEIPT_PATH)
    base_receipt = read_json(BASE_FIT_RECEIPT_PATH)
    base_historical = read_json(BASE_HISTORICAL_RECEIPT_PATH)
    require(approval.get("approved") is True and approval.get("approved_by") == "root",
            "root fit approval missing")
    require(approval.get("scope") == "pair_jockey_basic_h1_h2_fit", "root approval scope changed")
    require(approval.get("h1_fit_count") == 3 and approval.get("h2_candidate_map_count") == 3,
            "root approval fit budget changed")
    require(sha256(STUDY / "PLAN.md") == approval.get("plan_sha256"), "approved plan hash changed")
    require(sha256(STUDY / "jockey_input.py") == approval.get("input_helper_sha256"), "approved input helper changed")
    require(sha256(STUDY / "pair_jockey_fit.py") == approval.get("fit_code_sha256"), "approved fit code changed")
    require(sha256(SOURCE_PREFLIGHT) == approval.get("source_preflight_sha256") == fit.get("source_preflight_sha256"),
            "source preflight is not pinned consistently")
    require(preflight.get("status") == "PASS" and preflight.get("finish_labels_read") is False,
            "source preflight not PASS/no-label")
    require(fit_receipt.get("status") == "PASS" and fit_receipt.get("h1_fit_count") == 3
            and fit_receipt.get("h2_candidate_map_count") == 3,
            "candidate fit receipt not PASS or fit count changed")
    require(fit_receipt.get("approval_sha256") == sha256(APPROVAL), "fit receipt points to another approval")
    require(fit_receipt.get("candidate_fit_sha256") == sha256(FIT_PATH), "candidate FIT hash mismatch")
    require(fit.get("status") == "PASS" and fit.get("evaluation_predictions_generated") is False
            and fit.get("performance_metrics_computed") is False,
            "fit artifact scope includes prohibited evaluation work")
    require(base_receipt.get("status") == "PASS" and base_receipt.get("h1_fit_count") == 3,
            "frozen baseline fit receipt not PASS")
    require(base_receipt.get("historical_refit_receipt_sha256") == sha256(BASE_HISTORICAL_RECEIPT_PATH),
            "historical score lineage differs from baseline fit receipt")
    require(base_historical.get("status") == "PASS", "historical score receipt not PASS")
    require(sha256(BASE_FIT_PATH) == base_receipt.get("expanded_h1_fit_sha256"), "baseline H1 fit hash mismatch")
    return approval, preflight, fit, fit_receipt, read_json(BASE_FIT_PATH)


def load_independent_rolling_function():
    path = REVIEW / "independent_rolling.py"
    spec = importlib.util.spec_from_file_location("independent_rolling_windows_for_fit_audit", path)
    require(spec is not None and spec.loader is not None, "cannot load independent rolling-window source")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.independent_windows


def load_joined_training_rows(fit: dict, historical_base_fit: dict) -> tuple[dict[int, pd.DataFrame], dict[str, str]]:
    expected_source_hashes = {
        str(FEATURES_PATH.relative_to(ROOT)): "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
        str(STARTS_PATH.relative_to(ROOT)): "78800c5c91219d58855ce046e39ead6a87729a49c8ba0d58ca9f78765921801a",
    }
    source_hashes = {relative: sha256(ROOT / relative) for relative in expected_source_hashes}
    require(source_hashes == expected_source_hashes, "pinned feature/history source changed")
    score_meta = fit["score_sources_by_race_year"]
    runner_cols = list(ref.RUNNER_COLUMNS[1:])
    feature_cols = [
        "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
        "field_n", "finish_position", *runner_cols,
    ]
    features = pd.read_parquet(
        FEATURES_PATH, columns=feature_cols,
        filters=[("year", ">=", 2019), ("year", "<=", 2025)],
    )
    for column in ("api_record_id", "race_id", "horse_id"):
        features[column] = features[column].astype("string")
    features["race_date"] = pd.to_datetime(features["race_date"], errors="raise").dt.normalize()
    require(features["api_record_id"].is_unique, "duplicate source feature API key")
    starts = pd.read_csv(
        STARTS_PATH,
        usecols=["api_record_id", "race_id", "horse_id", "race_date", "jockey_id", "field_n", "finish_position"],
        dtype={"api_record_id": "string", "race_id": "string", "horse_id": "string", "jockey_id": "string"},
        low_memory=False,
    )
    starts["race_date"] = pd.to_datetime(starts["race_date"], errors="raise").dt.normalize()
    require(starts["api_record_id"].is_unique, "duplicate source event API key")
    event_cols = starts[["api_record_id", "race_id", "horse_id", "race_date", "jockey_id"]]
    joined_parts = {}
    source_scores = {}
    for year in range(2019, 2026):
        meta = score_meta[str(year)]
        score_path = ROOT / meta["source_path"]
        require(score_path.is_file() and not score_path.is_symlink(), f"score source missing/symlink: {score_path}")
        require(sha256(score_path) == meta["source_sha256"], f"score source hash changed for {year}")
        scores = pd.read_parquet(score_path)
        require(scores.columns.tolist() == ["api_record_id", "score"], f"score schema changed for {year}")
        scores["api_record_id"] = scores["api_record_id"].astype("string")
        require(scores["api_record_id"].is_unique and np.isfinite(scores["score"].to_numpy(dtype=float)).all(),
                f"invalid score key/value for {year}")
        year_features = features.loc[features["year"].eq(year)].copy()
        require(set(year_features["api_record_id"]) == set(scores["api_record_id"]), f"score key coverage changed for {year}")
        year_rows = year_features.merge(scores, on="api_record_id", how="left", validate="one_to_one")
        require(year_rows["score"].notna().all(), f"score value missing for {year}")
        year_rows = year_rows.merge(event_cols, on="api_record_id", how="left", validate="one_to_one", suffixes=("_feature", "_event"), indicator=True)
        require(year_rows["_merge"].eq("both").all(), f"event jockey join missing for {year}")
        for left, right in (("race_id_feature", "race_id_event"), ("horse_id_feature", "horse_id_event"), ("race_date_feature", "race_date_event")):
            require(year_rows[left].eq(year_rows[right]).all(), f"event key/date mismatch for {year}: {left}")
        year_rows["race_id"] = year_rows["race_id_feature"]
        year_rows["horse_id"] = year_rows["horse_id_feature"]
        year_rows["race_date"] = year_rows["race_date_feature"]
        year_rows = year_rows.drop(columns=["_merge", "race_id_feature", "race_id_event", "horse_id_feature", "horse_id_event", "race_date_feature", "race_date_event"])
        require(year_rows["jockey_id"].notna().all(), f"event jockey ID missing for {year}")
        require(len(year_rows) == meta["rows"] and year_rows["race_id"].nunique() == meta["races"],
                f"score-source coverage differs from fit receipt for {year}")
        joined_parts[year] = year_rows
        source_scores[str(year)] = meta["source_sha256"]
    all_rows = pd.concat([joined_parts[year] for year in range(2019, 2026)], ignore_index=True)
    independent_rolling = load_independent_rolling_function()
    rolling = independent_rolling(all_rows, starts)
    rolled = all_rows.merge(
        rolling[["api_record_id", "n_independent", "s_independent", "e_independent", "d_independent", "latest_history_date"]],
        on="api_record_id", how="left", validate="one_to_one",
    )
    require(rolled["d_independent"].notna().all(), "independent rolling value missing")
    cutoff = rolled["race_date"] - pd.Timedelta(days=2)
    latest = pd.to_datetime(rolled["latest_history_date"], errors="coerce")
    require((latest.isna() | (latest <= cutoff)).all(), "independent H1/H2 history crossed T-2 cutoff")
    return {year: rolled.loc[rolled["year"].eq(year)].copy() for year in range(2019, 2026)}, source_scores


def split_fold(yearly: dict[int, pd.DataFrame], evaluation_year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    calibration_year = evaluation_year - 1
    rows = yearly[calibration_year]
    h2 = rows.loc[rows["race_date"].dt.month.ge(7)].copy()
    first_h2 = h2["race_date"].min().date()
    h1_parts = [yearly[year] for year in range(2019, evaluation_year - 1)]
    current = rows.loc[
        rows["race_date"].dt.month.le(6)
        & rows["race_date"].dt.date.map(lambda date: date <= first_h2 - pd.Timedelta(days=2))
    ].copy()
    h1 = pd.concat([*h1_parts, current], ignore_index=True)
    require(h1["api_record_id"].is_unique and h2["api_record_id"].is_unique, f"duplicate H1/H2 rows {evaluation_year}")
    require(h1["race_id"].nunique() == H1_COUNTS[evaluation_year], f"H1 race count changed {evaluation_year}")
    require(h2["race_id"].nunique() == H2_COUNTS[evaluation_year], f"H2 race count changed {evaluation_year}")
    require(h1["race_date"].max().date() <= first_h2 - pd.Timedelta(days=2), f"H1/H2 purge failed {evaluation_year}")
    return h1, h2


def build_independent_races(rows: pd.DataFrame, runner_moments) -> list[dict[str, Any]]:
    races = []
    for race_id, frame in rows.groupby("race_id", sort=True):
        race = frame.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
        numbers = race["horse_number"].astype(int).tolist()
        finishes = race["finish_position"].astype(int).tolist()
        field_n = int(race["field_n"].iloc[0])
        require(len(race) == field_n and len(set(numbers)) == field_n, f"roster mismatch {race_id}")
        require(sorted(finishes) == list(range(1, field_n + 1)), f"finish ranks not 1..N {race_id}")
        require(sum(value <= 3 for value in finishes) == 3, f"Top3 runner labels differ {race_id}")
        runner_values = {name: race[name].to_numpy() for name in ref.RUNNER_COLUMNS}
        z, missing = ref.transform_runner_values(runner_values, runner_moments)
        pairs, raw20 = ref.race_pair_matrix(numbers, z, missing)
        prior_pairs, p0, q0 = ref.exact_top3_pair_prior(numbers, runner_values["score"])
        require(prior_pairs == pairs, f"independent pair ordering mismatch {race_id}")
        finish_by_horse = dict(zip(numbers, finishes, strict=True))
        labels = ref.pair_label(finish_by_horse, pairs)
        require(int(labels.sum()) == 3, f"pair label sum differs in {race_id}")
        d_by_horse = {int(row.horse_number): float(row.d_independent) for row in race.itertuples(index=False)}
        jockey_pair = pair_jockey_sums(pairs, d_by_horse)
        races.append({
            "race_id": str(race_id), "race_date": race["race_date"].iloc[0].date().isoformat(),
            "rows": race, "numbers": numbers, "pairs": pairs, "raw20": raw20,
            "jockey_pair": jockey_pair, "p0": p0, "q0": q0, "labels": labels,
        })
    require(bool(races), "empty independent race cohort")
    return races


def load_runner_moments(fit_row: dict[str, Any]):
    doc = fit_row["runner_standardization"]
    return ref.RunnerMoments(
        columns=ref.RUNNER_COLUMNS,
        mean=np.asarray([doc[name]["mean"] for name in ref.RUNNER_COLUMNS], dtype=float),
        scale=np.asarray([doc[name]["scale"] for name in ref.RUNNER_COLUMNS], dtype=float),
        degenerate=tuple(bool(doc[name]["degenerate"]) for name in ref.RUNNER_COLUMNS),
        support_weight=tuple(float(doc[name]["support_weight"]) for name in ref.RUNNER_COLUMNS),
    )


def load_old_pair_moments(fit_row: dict[str, Any]):
    doc = fit_row["pair_standardization"]
    return ref.PairMoments(
        mean=np.asarray([doc[name]["mean"] for name in ref.BASIS_NAMES], dtype=float),
        scale=np.asarray([doc[name]["scale"] for name in ref.BASIS_NAMES], dtype=float),
        degenerate=tuple(bool(doc[name]["degenerate"]) for name in ref.BASIS_NAMES),
        support_weight=tuple(float(doc[name]["support_weight"]) for name in ref.BASIS_NAMES),
    )


def audit_fold(evaluation_year: int, h1: pd.DataFrame, h2: pd.DataFrame,
               baseline_row: dict[str, Any], candidate_row: dict[str, Any]) -> dict[str, Any]:
    runner_moments = load_runner_moments(baseline_row)
    old_pair_moments = load_old_pair_moments(baseline_row)
    require(candidate_row["old_pair_moments"] == baseline_row["pair_standardization"],
            f"candidate did not preserve frozen old20 moments {evaluation_year}")
    h1_races = build_independent_races(h1, runner_moments)
    h2_races = build_independent_races(h2, runner_moments)
    rider_moments = fit_jockey_pair_moments([race["jockey_pair"] for race in h1_races])
    stored_moment = candidate_row["new_pair_moment"]
    for key in ("mean", "scale"):
        require(abs(float(stored_moment[key]) - float(rider_moments[key])) <= 1e-12,
                f"independent H1 jockey {key} differs {evaluation_year}")
    require(bool(stored_moment["degenerate"]) == rider_moments["degenerate"], f"jockey degeneracy differs {evaluation_year}")
    require(float(stored_moment["support_weight"]) == rider_moments["support_weight"], f"jockey support differs {evaluation_year}")
    x_h1_by_race = standardize_21d_basis(
        [race["raw20"] for race in h1_races], [race["jockey_pair"] for race in h1_races], old_pair_moments, rider_moments,
    )
    beta_doc = candidate_row["beta_by_basis"]
    beta = np.asarray([beta_doc[name] for name in ref.BASIS_NAMES] + [candidate_row["gamma_jockey365_pair_sum"]], dtype=float)
    h1_objective, h1_gradient = h1_objective_gradient_21(
        beta, x_h1_by_race, [race["p0"] for race in h1_races], [race["labels"] for race in h1_races],
    )
    optimizer = candidate_row["optimizer"]
    require(abs(h1_objective - float(optimizer["objective"])) <= 1e-9, f"H1 objective mismatch {evaluation_year}")
    require(float(np.max(np.abs(h1_gradient))) <= 1e-7, f"independent H1 gradient too large {evaluation_year}")
    require(abs(float(np.max(np.abs(h1_gradient))) - float(optimizer["gradient_inf_norm"])) <= 1e-7,
            f"H1 gradient norm differs from fit receipt {evaluation_year}")

    x_h2_by_race = standardize_21d_basis(
        [race["raw20"] for race in h2_races], [race["jockey_pair"] for race in h2_races], old_pair_moments, rider_moments,
    )
    candidate_raw_h2 = [ref.logit(race["p0"]) + x @ beta for race, x in zip(h2_races, x_h2_by_race, strict=True)]
    calibration = candidate_row["h2_candidate_platt"]
    theta = np.asarray([calibration["A"], calibration["B"]], dtype=float)
    h2_objective, h2_gradient = h2_objective_gradient(
        theta, candidate_raw_h2, [race["labels"] for race in h2_races],
    )
    projected = ref.projected_box_gradient(theta, h2_gradient, PLATT_BOUNDS)
    projected_norm = float(np.max(np.abs(projected)))
    require(abs(h2_objective - float(calibration["objective"])) <= 1e-9, f"H2 objective mismatch {evaluation_year}")
    require(projected_norm <= 1e-7, f"independent H2 projected gradient too large {evaluation_year}")
    require(abs(projected_norm - float(calibration["projected_gradient_inf_norm"])) <= 1e-7,
            f"H2 projected gradient norm differs {evaluation_year}")
    require(theta[1] > 0.0, f"candidate H2 Platt slope not positive {evaluation_year}")
    return {
        "evaluation_year": evaluation_year,
        "h1_races": len(h1_races), "h2_races": len(h2_races),
        "h1_runner_rows": int(len(h1)), "h1_pairs": int(sum(len(r["labels"]) for r in h1_races)),
        "h1_positive_pairs": int(sum(int(r["labels"].sum()) for r in h1_races)),
        "h2_runner_rows": int(len(h2)), "h2_pairs": int(sum(len(r["labels"]) for r in h2_races)),
        "h2_positive_pairs": int(sum(int(r["labels"].sum()) for r in h2_races)),
        "h1_last_date": h1["race_date"].max().date().isoformat(),
        "h2_first_date": h2["race_date"].min().date().isoformat(),
        "h1_h2_purge_days": (h2["race_date"].min().date() - h1["race_date"].max().date()).days,
        "independent_new_pair_moment": rider_moments,
        "stored_new_pair_moment": stored_moment,
        "h1_objective": h1_objective,
        "h1_objective_abs_difference": abs(h1_objective - float(optimizer["objective"])),
        "h1_independent_gradient_inf_norm": float(np.max(np.abs(h1_gradient))),
        "h1_saved_gradient_inf_norm": float(optimizer["gradient_inf_norm"]),
        "h2_objective": h2_objective,
        "h2_objective_abs_difference": abs(h2_objective - float(calibration["objective"])),
        "h2_independent_projected_gradient_inf_norm": projected_norm,
        "h2_saved_projected_gradient_inf_norm": float(calibration["projected_gradient_inf_norm"]),
        "candidate_h2_slope_positive": bool(theta[1] > 0.0),
        "frozen_old20_pair_moments_exact": True,
    }


def main() -> None:
    approval, preflight, fit, fit_receipt, baseline_fit = verify_approved_artifacts()
    yearly, score_hashes = load_joined_training_rows(fit, baseline_fit)
    baseline_rows = {int(row["evaluation_year"]): row for row in baseline_fit["folds"]}
    candidate_rows = {int(row["evaluation_year"]): row for row in fit["folds"]}
    require(set(candidate_rows) == set(EVAL_YEARS), "candidate fit folds changed")
    results = []
    for year in EVAL_YEARS:
        h1, h2 = split_fold(yearly, year)
        row = audit_fold(year, h1, h2, baseline_rows[year], candidate_rows[year])
        require(row["h1_races"] == H1_COUNTS[year] and row["h2_races"] == H2_COUNTS[year],
                f"independent H1/H2 fold count mismatch {year}")
        results.append(row)
    receipt = {
        "status": "PASS",
        "scope": "independent H1 moments/objective-gradient and H2 Platt arithmetic only; no optimizer, predictions, or candidate outcomes",
        "approval_sha256": sha256(APPROVAL), "source_preflight_sha256": sha256(SOURCE_PREFLIGHT),
        "candidate_fit_receipt_sha256": sha256(FIT_RECEIPT_PATH), "candidate_fit_sha256": sha256(FIT_PATH),
        "frozen_baseline_fit_sha256": sha256(BASE_FIT_PATH),
        "independent_reference_sha256": sha256(REVIEW / "independent_jockey_reference.py"),
        "independent_rolling_source_sha256": sha256(REVIEW / "independent_rolling.py"),
        "source_hashes": {str(FEATURES_PATH.relative_to(ROOT)): sha256(FEATURES_PATH),
                          str(STARTS_PATH.relative_to(ROOT)): sha256(STARTS_PATH), **score_hashes},
        "folds": results,
        "optimizer_calls": 0,
        "candidate_predictions_generated": False,
        "candidate_outcome_metrics_computed": False,
    }
    out = REVIEW / "independent_fit_audit.json"
    require(not out.exists() and not out.is_symlink(), "refusing to overwrite independent fit audit receipt")
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

