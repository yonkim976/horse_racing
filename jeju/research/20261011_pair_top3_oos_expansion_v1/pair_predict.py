"""Apply approved expanded-pair fits to the unchanged evaluation cohort."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit, logit

sys.dont_write_bytecode = True

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
OUT = STUDY / "outputs"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
STYLE_OUT = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
DIRECT_CORE = DIRECT / "core.py"
OLD_PAIR_PREDICTIONS = DIRECT / "outputs/evaluation_pair_predictions.parquet"
OLD_RACE_DIAGNOSTICS = DIRECT / "outputs/evaluation_race_probabilities.parquet"
OLD_PREDICTION_RECEIPT = DIRECT / "outputs/prediction_receipt.json"
FIT_RECEIPT = OUT / "PAIR_FIT_RECEIPT.json"
H1_FIT = OUT / "expanded_h1_fit.json"
H2_FIT = OUT / "expanded_h2_calibration.json"
SOURCE_LOCK = OUT / "HISTORICAL_SOURCE_LOCK.json"
PREDICTIONS = OUT / "evaluation_pair_predictions.parquet"
DIAGNOSTICS = OUT / "evaluation_race_probabilities.parquet"
PREDICTION_RECEIPT = OUT / "prediction_receipt.json"
EVAL_YEARS = (2024, 2025, 2026)
EXPECTED_RACES = {2024: 637, 2025: 654, 2026: 488}
EXPECTED_OLD_PREDICTIONS_SHA256 = "a8db4d50646b01e009acdf33cfa458840e804a7fb4c26b6387939e12dabbbfa8"
EXPECTED_OLD_DIAGNOSTICS_SHA256 = "be72cc90162738f6e2bf8dfb36fb710531fd37eb6b9b7e9ea9a9f3509e9af510"
EVAL_FEATURE_COLUMNS = [
    "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "field_n",
    "distance_m", "hist_s1f_relpos_mean5", "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
]
OLD_COLUMNS = [
    "race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j",
    "score_i", "score_j", "p0", "eta", "candidate_raw_probability",
    "candidate_calibrated_probability", "baseline_calibrated_probability", "y_pair",
    "selected_candidate", "selected_baseline", "selected_raw_top2", "selected_saved_f1_top2",
    "selected_candidate_joint_marginal_top2", "selected_candidate_joint_maxpair",
    "selected_matched_joint_maxpair",
]


class PredictionError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise PredictionError(message)


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


def write_parquet_once(path: Path, frame: pd.DataFrame) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False)


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def load_core():
    path = checked(DIRECT_CORE)
    spec = importlib.util.spec_from_file_location("frozen_direct_pair_core_prediction", path)
    require(spec is not None and spec.loader is not None, "cannot load frozen pair core")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_stats(core, fit_row):
    runner = fit_row["runner_standardization"]
    runner_stats = core.Standardization(
        columns=core.RUNNER_COLUMNS,
        mean=np.asarray([runner[name]["mean"] for name in core.RUNNER_COLUMNS], dtype=float),
        scale=np.asarray([runner[name]["scale"] for name in core.RUNNER_COLUMNS], dtype=float),
        degenerate=tuple(bool(runner[name]["degenerate"]) for name in core.RUNNER_COLUMNS),
        support_weight=tuple(float(runner[name]["support_weight"]) for name in core.RUNNER_COLUMNS),
    )
    pair = fit_row["pair_standardization"]
    pair_stats = core.PairStandardization(
        mean=np.asarray([pair[name]["mean"] for name in core.BASIS_NAMES], dtype=float),
        scale=np.asarray([pair[name]["scale"] for name in core.BASIS_NAMES], dtype=float),
        degenerate=tuple(bool(pair[name]["degenerate"]) for name in core.BASIS_NAMES),
        support_weight=tuple(float(pair[name]["support_weight"]) for name in core.BASIS_NAMES),
    )
    return runner_stats, pair_stats


def verify_fit() -> tuple[dict, dict, dict, dict]:
    require(FIT_RECEIPT.is_file() and H1_FIT.is_file() and H2_FIT.is_file(), "expanded pair fit receipts missing")
    require(SOURCE_LOCK.is_file(), "historical source lock missing")
    receipt = json.loads(checked(FIT_RECEIPT).read_text(encoding="utf-8"))
    h1 = json.loads(checked(H1_FIT).read_text(encoding="utf-8"))
    h2 = json.loads(checked(H2_FIT).read_text(encoding="utf-8"))
    lock = json.loads(checked(SOURCE_LOCK).read_text(encoding="utf-8"))
    require(receipt.get("status") == "PASS" and receipt.get("evaluation_predictions_generated") is False,
            "pair fit receipt is not a fit-only PASS")
    require(receipt.get("performance_metrics_computed") is False, "pair fit already computes metrics")
    require(receipt.get("direct_core_sha256") == sha256(checked(DIRECT_CORE)), "frozen pair core changed after fit")
    require(receipt.get("expanded_h1_fit_sha256") == sha256(H1_FIT), "H1 fit changed after receipt")
    require(receipt.get("expanded_h2_calibration_sha256") == sha256(H2_FIT), "H2 maps changed after receipt")
    require(receipt.get("source_lock_sha256") == sha256(SOURCE_LOCK), "pair fit source-lock pin mismatch")
    require(lock.get("status") == "PASS", "historical source lock not PASS")
    for relative, expected in lock.get("sources", {}).items():
        require(sha256(checked(ROOT / relative)) == expected, f"locked source changed after fit: {relative}")
    require(receipt.get("pair_fit_receipt_sha256") is None, "unexpected recursive receipt field")
    require(h1.get("study") == STUDY.name and h2.get("study") == STUDY.name, "wrong pair study artifacts")
    require(not PREDICTIONS.exists() and not DIAGNOSTICS.exists() and not PREDICTION_RECEIPT.exists(),
            "pair prediction outputs already exist")
    old_receipt = json.loads(checked(OLD_PREDICTION_RECEIPT).read_text(encoding="utf-8"))
    require(old_receipt.get("status") == "PASS" and old_receipt.get("prediction_rows") == 76848,
            "fixed old direct prediction receipt changed")
    require(sha256(checked(OLD_PAIR_PREDICTIONS)) == old_receipt.get("evaluation_pair_predictions_sha256"),
            "old direct pair predictions changed")
    require(sha256(checked(OLD_RACE_DIAGNOSTICS)) == old_receipt.get("race_probability_diagnostics_sha256"),
            "old direct race diagnostics changed")
    require(sha256(OLD_PAIR_PREDICTIONS) == EXPECTED_OLD_PREDICTIONS_SHA256, "old direct reference hash differs from frozen study")
    require(sha256(OLD_RACE_DIAGNOSTICS) == EXPECTED_OLD_DIAGNOSTICS_SHA256, "old direct diagnostics hash differs from frozen study")
    return receipt, h1, h2, lock


def evaluation_runner_scores(year: int, features: pd.DataFrame, lock: dict) -> tuple[pd.DataFrame, dict[str, Any]]:
    folder = STYLE_OUT / f"F1_STYLE6_{year}"
    score_path = checked(folder / "evaluation_scores.parquet")
    score = pd.read_parquet(score_path)
    require(score.columns.tolist() == ["api_record_id", "score"] and score["api_record_id"].is_unique,
            f"evaluation score schema/key changed for {year}")
    require(np.isfinite(score["score"].to_numpy(dtype=float)).all(), f"nonfinite evaluation score for {year}")
    rows = features.loc[features["year"].eq(year)].copy()
    require(set(score["api_record_id"]) == set(rows["api_record_id"]), f"evaluation score coverage changed for {year}")
    joined = rows.merge(score, on="api_record_id", how="left", validate="one_to_one")
    require(joined["score"].notna().all(), f"evaluation score join missing for {year}")
    meta_path = checked(folder / "meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    require(lock["sources"].get(str(score_path.relative_to(ROOT))) == sha256(score_path),
            f"fixed evaluation source not in lock: {year}")
    refit_max = pd.Timestamp(meta["refit_max"]).normalize()
    require(((joined["race_date"].dt.normalize() - pd.Timedelta(days=2)) >= refit_max).all(),
            f"evaluation provider T-2 failed for {year}")
    return joined, {
        "score_path": str(score_path.relative_to(ROOT)), "score_sha256": sha256(score_path),
        "meta_path": str(meta_path.relative_to(ROOT)), "meta_sha256": sha256(meta_path),
        "refit_max": meta["refit_max"], "rows": int(len(joined)),
        "races": int(joined["race_id"].nunique()),
    }


def score_expanded_pairs(core, rows: pd.DataFrame, fit_row: dict, map_row: dict) -> tuple[list[dict], list[dict]]:
    runner_stats, pair_stats = load_stats(core, fit_row)
    beta = np.asarray([fit_row["beta_by_basis"][name] for name in core.BASIS_NAMES], dtype=float)
    A, B = float(map_row["A"]), float(map_row["B"])
    prediction_rows: list[dict] = []
    diagnostics: list[dict] = []
    for race_id, race in rows.groupby("race_id", sort=True):
        race = race.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
        numbers = race["horse_number"].to_numpy(dtype=int)
        require(len(numbers) >= 4 and len(set(numbers.tolist())) == len(numbers), f"invalid evaluation roster: {race_id}")
        z, missing = core.transform_runners(race, runner_stats)
        pair_list = list(itertools.combinations(sorted(numbers.tolist()), 2))
        position = {int(number): index for index, number in enumerate(numbers.tolist())}
        basis = np.vstack([
            core.pair_basis(z[position[a]], z[position[b]], missing[position[a]], missing[position[b]])
            for a, b in pair_list
        ])
        prior_map, _ = core.q0_from_scores(numbers.tolist(), race["score"].astype(float).tolist())
        p0 = np.asarray([prior_map[pair] for pair in pair_list], dtype=float)
        require(np.isfinite(p0).all() and ((p0 > 0) & (p0 < 1)).all(), f"invalid pair prior: {race_id}")
        x = core.transform_pair_basis(basis, pair_stats)
        eta = logit(p0) + x @ beta
        raw = expit(eta)
        calibrated = expit(A + B * eta)
        selected = core.pair_choice_from_logits(pair_list, eta)
        selected_calibrated = core.pair_choice_from_logits(pair_list, A + B * eta)
        require(selected == selected_calibrated, f"positive-slope H2 map changed pair ranking: {race_id}")
        scores = {int(row.horse_number): float(row.score) for row in race.itertuples(index=False)}
        require(selected in pair_list, f"expanded selector did not return a race pair: {race_id}")
        date = race["race_date"].iloc[0].date().isoformat()
        year = int(race["year"].iloc[0])
        distance = int(race["distance_m"].iloc[0])
        diagnostics.append({
            "race_id": str(race_id), "race_date": date, "evaluation_year": year, "distance_m": distance,
            "expanded_candidate_sum_calibrated_pair_probability_minus_3": math.fsum(map(float, calibrated)) - 3.0,
        })
        for i, (a, b) in enumerate(pair_list):
            prediction_rows.append({
                "race_id": str(race_id), "race_date": date, "evaluation_year": year, "distance_m": distance,
                "horse_i": int(a), "horse_j": int(b), "score_i": scores[a], "score_j": scores[b],
                "p0_check": float(p0[i]), "expanded_eta": float(eta[i]),
                "expanded_candidate_raw_probability": float(raw[i]),
                "expanded_candidate_calibrated_probability": float(calibrated[i]),
                "selected_expanded_candidate": int((a, b) == selected),
            })
    return prediction_rows, diagnostics


def run() -> None:
    fit_receipt, h1, h2, lock = verify_fit()
    core = load_core()
    features = pd.read_parquet(
        checked(FEATURES), columns=EVAL_FEATURE_COLUMNS,
        filters=[("year", ">=", 2024), ("year", "<=", 2026)],
    )
    features["race_date"] = pd.to_datetime(features["race_date"], errors="coerce")
    require(features["race_date"].notna().all() and features["year"].isin(EVAL_YEARS).all(),
            "evaluation feature range/schema changed")
    outputs: list[dict] = []
    expanded_diagnostics: list[dict] = []
    eval_sources = {}
    for year in EVAL_YEARS:
        rows, eval_sources[str(year)] = evaluation_runner_scores(year, features, lock)
        fit_row = next(row for row in h1["folds"] if int(row["evaluation_year"]) == year)
        map_row = next(row for row in h2["fold_maps"] if int(row["evaluation_year"]) == year and row["map"] == "candidate")
        year_preds, year_diag = score_expanded_pairs(core, rows, fit_row, map_row)
        require(len(year_diag) == EXPECTED_RACES[year], f"evaluation race count changed: {year}")
        outputs.extend(year_preds)
        expanded_diagnostics.extend(year_diag)

    expanded = pd.DataFrame(outputs)
    new_diag = pd.DataFrame(expanded_diagnostics)
    require(not expanded.duplicated(["race_id", "horse_i", "horse_j"]).any(), "expanded predictions contain duplicate pair")
    require((expanded.groupby("race_id")["selected_expanded_candidate"].sum() == 1).all(), "expanded selector must choose one pair/race")
    require(np.isfinite(expanded.select_dtypes(include=[np.number]).to_numpy(dtype=float)).all(), "nonfinite expanded pair predictions")

    # The old table is read only after expanded predictions have been selected.
    old = pd.read_parquet(checked(OLD_PAIR_PREDICTIONS), columns=OLD_COLUMNS)
    require(len(old) == 76848 and old["race_id"].nunique() == 1779, "old evaluation pair table shape changed")
    require(not old.duplicated(["race_id", "horse_i", "horse_j"]).any(), "old evaluation pair key is not unique")
    keys = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j"]
    merged = old.merge(expanded, on=keys, how="outer", validate="one_to_one", indicator=True, suffixes=("", "_new"))
    require(merged["_merge"].eq("both").all(), "expanded and fixed evaluation pair keys differ")
    old_selection = old.set_index(keys)["selected_candidate"]
    merged_selection = old_selection.reindex(merged.set_index(keys).index).to_numpy(dtype=int)
    require(np.array_equal(merged["selected_candidate"].to_numpy(dtype=int), merged_selection),
            "old direct selection did not align by pair key")
    require(np.allclose(merged["p0"], merged["p0_check"], rtol=0, atol=1e-15), "fixed p0 changed under expanded model")
    require(np.allclose(merged["score_i"], merged["score_i_new"], rtol=0, atol=0), "fixed evaluation scores changed")
    require(np.allclose(merged["score_j"], merged["score_j_new"], rtol=0, atol=0), "fixed evaluation scores changed")
    merged["old_direct_eta"] = merged["eta"]
    merged["old_direct_candidate_raw_probability"] = merged["candidate_raw_probability"]
    merged["old_direct_candidate_calibrated_probability"] = merged["candidate_calibrated_probability"]
    merged["selected_old_direct"] = merged["selected_candidate"]
    merged["eta"] = merged["expanded_eta"]
    merged["candidate_raw_probability"] = merged["expanded_candidate_raw_probability"]
    merged["candidate_calibrated_probability"] = merged["expanded_candidate_calibrated_probability"]
    merged["selected_candidate"] = merged["selected_expanded_candidate"]
    merged = merged.drop(columns=["_merge", "p0_check", "score_i_new", "score_j_new"])
    require((merged.groupby("race_id")["selected_old_direct"].sum() == 1).all(), "old direct selector was not preserved")
    require((merged.groupby("race_id")["selected_candidate"].sum() == 1).all(), "expanded selector must choose one pair/race")

    old_diag = pd.read_parquet(checked(OLD_RACE_DIAGNOSTICS))
    require(len(old_diag) == 1779 and old_diag["race_id"].is_unique, "old race diagnostic shape changed")
    new_diag = old_diag.merge(new_diag, on=["race_id", "race_date", "evaluation_year", "distance_m"],
                              how="outer", validate="one_to_one", indicator=True)
    require(new_diag["_merge"].eq("both").all(), "expanded race diagnostics differ from fixed cohort")
    new_diag = new_diag.drop(columns="_merge").rename(columns={
        "candidate_sum_calibrated_pair_probability_minus_3": "old_direct_candidate_sum_calibrated_pair_probability_minus_3",
        "candidate_abs_sum_deviation": "old_direct_candidate_abs_sum_deviation",
        "expanded_candidate_sum_calibrated_pair_probability_minus_3": "candidate_sum_calibrated_pair_probability_minus_3",
    })
    new_diag["candidate_abs_sum_deviation"] = new_diag["candidate_sum_calibrated_pair_probability_minus_3"].abs()

    merged = merged.sort_values(["race_id", "horse_i", "horse_j"], kind="mergesort").reset_index(drop=True)
    new_diag = new_diag.sort_values("race_id", kind="mergesort").reset_index(drop=True)
    write_parquet_once(PREDICTIONS, merged)
    write_parquet_once(DIAGNOSTICS, new_diag)
    receipt = {
        "status": "PASS", "study": STUDY.name,
        "scope": "expanded model evaluation pair predictions; no performance metrics",
        "pair_fit_receipt_sha256": sha256(FIT_RECEIPT),
        "expanded_h1_fit_sha256": sha256(H1_FIT),
        "expanded_h2_calibration_sha256": sha256(H2_FIT),
        "evaluation_score_sources": eval_sources,
        "fixed_old_direct_prediction_receipt_sha256": sha256(OLD_PREDICTION_RECEIPT),
        "fixed_old_direct_pair_predictions_sha256": sha256(OLD_PAIR_PREDICTIONS),
        "fixed_old_direct_race_diagnostics_sha256": sha256(OLD_RACE_DIAGNOSTICS),
        "prediction_rows": int(len(merged)), "prediction_races": int(merged["race_id"].nunique()),
        "evaluation_dates": int(merged["race_date"].nunique()),
        "selected_per_race": int(merged.groupby("race_id")["selected_candidate"].sum().eq(1).sum()),
        "old_direct_selector_preserved": True,
        "pair_prediction_sha256": sha256(PREDICTIONS),
        "race_diagnostics_sha256": sha256(DIAGNOSTICS),
        "performance_metrics_computed": False,
    }
    write_json_once(PREDICTION_RECEIPT, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    run()
