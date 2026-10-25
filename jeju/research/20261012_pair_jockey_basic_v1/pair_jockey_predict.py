"""Predict and report the single approved jockey-basic pair arm."""

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

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
OUT = STUDY / "outputs"
BASE = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
BASE_OUT = BASE / "outputs"
BASE_PAIR_PREDICTIONS = BASE_OUT / "evaluation_pair_predictions.parquet"
BASE_RACE_DIAGNOSTICS = BASE_OUT / "evaluation_race_probabilities.parquet"
BASE_SOURCE_LOCK = BASE_OUT / "HISTORICAL_SOURCE_LOCK.json"
BASELINE_FIT = BASE_OUT / "expanded_h1_fit.json"
BASE_PAIR_FIT = BASE / "pair_fit.py"
BASE_PAIR_PREDICT = BASE / "pair_predict.py"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
DIRECT_CORE = DIRECT / "core.py"
DIRECT_REPORT = DIRECT / "report.py"
DIRECT_SCHEDULE = DIRECT / "outputs/date_bootstrap_schedule.npy"
FIT_PATH = OUT / "FIT.json"
FIT_RECEIPT_PATH = OUT / "FIT_RECEIPT.json"
PREDICTIONS = OUT / "evaluation_pair_predictions.parquet"
DIAGNOSTICS = OUT / "evaluation_race_probabilities.parquet"
PREDICTION_RECEIPT = OUT / "PREDICTION_RECEIPT.json"
REPORT_PATH = OUT / "REPORT.json"
REPORT_RECEIPT = OUT / "REPORT_RECEIPT.json"
README_PATH = STUDY / "README.md"
MANIFEST_PATH = STUDY / "ARTIFACT_MANIFEST.json"
EVAL_YEARS = (2024, 2025, 2026)
EXPECTED_RACES = {2024: 637, 2025: 654, 2026: 488}
EXPECTED_BASE_PAIR_SHA256 = "f983d9c5dfa7c4d1129b407d5a3e367dc38e193c0c8fdbbaeff34d86b31af499"
EXPECTED_BASE_CORE_SHA256 = "0a51495c6c1d08f65e1400a6d47c7710d3b32806f678a6bbefe2fab3a8e2de1e"
EXPECTED_BASE_PAIR_FIT_SHA256 = "5187288115621e6affc5079d4c24a6a35a9563385d7b336e958f179484fa3e16"
EXPECTED_BASE_PAIR_PREDICT_SHA256 = "69b19509552f4c12db9191b30dd8c5f6fc623cbed3f3265ba466b805c0614f75"
EXPECTED_BOOTSTRAP_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
INPUT_HELPER = STUDY / "jockey_input.py"
SOURCE_PREFLIGHT = OUT / "SOURCE_PREFLIGHT.json"
KEYS = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j"]


class EvaluationError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise EvaluationError(message)


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
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_parquet_once(path: Path, frame: pd.DataFrame) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False)


def import_module(name: str, path: Path):
    path = checked(path)
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_fit() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    receipt = json.loads(checked(FIT_RECEIPT_PATH).read_text(encoding="utf-8"))
    fit = json.loads(checked(FIT_PATH).read_text(encoding="utf-8"))
    approval = json.loads(checked(OUT / "APPROVAL.json").read_text(encoding="utf-8"))
    source_preflight_path = SOURCE_PREFLIGHT
    source_preflight = json.loads(checked(source_preflight_path).read_text(encoding="utf-8"))
    require(receipt.get("status") == "PASS" and receipt.get("h1_fit_count") == 3
            and receipt.get("h2_candidate_map_count") == 3, "approved candidate fits did not pass")
    require(receipt.get("performance_metrics_computed") is False
            and receipt.get("evaluation_predictions_generated") is False,
            "fit stage already contains evaluation work")
    require(receipt.get("candidate_fit_sha256") == sha256(FIT_PATH), "candidate fit artifact changed")
    require(receipt.get("fit_code_sha256") == sha256(STUDY / "pair_jockey_fit.py"), "fit code changed after approval")
    require(receipt.get("approval_sha256") == sha256(OUT / "APPROVAL.json"), "root approval changed after fit")
    require(receipt.get("input_helper_sha256") == sha256(STUDY / "jockey_input.py"),
            "approved rolling-input helper changed after fit")
    require(receipt.get("source_preflight_sha256") == sha256(source_preflight_path),
            "source preflight changed after fit")
    require(source_preflight.get("status") == "PASS" and source_preflight.get("finish_labels_read") is False,
            "source preflight is not a no-label PASS")
    require(approval.get("approved") is True and approval.get("approved_by") == "root",
            "root approval missing")
    require(approval.get("input_helper_sha256") == sha256(STUDY / "jockey_input.py")
            and approval.get("source_preflight_sha256") == sha256(source_preflight_path),
            "approval does not pin the input helper/source preflight")
    for relative, expected in source_preflight.get("source_hashes", {}).items():
        require(sha256(checked(ROOT / relative)) == expected, f"preflight source changed: {relative}")
    require(sha256(BASE_PAIR_PREDICTIONS) == EXPECTED_BASE_PAIR_SHA256,
            "frozen latest-pair evaluation reference changed")
    require(not PREDICTIONS.exists() and not DIAGNOSTICS.exists() and not PREDICTION_RECEIPT.exists(),
            "evaluation prediction outputs already exist")
    return receipt, fit, approval


def candidate_race_predictions(core, race: pd.DataFrame, fit_fold: dict[str, Any], baseline_fold: dict[str, Any]):
    runner_stats, old_pair_stats = _stats_from_baseline(core, baseline_fold)
    race = race.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
    numbers = race["horse_number"].to_numpy(dtype=int)
    require(len(numbers) >= 4 and len(set(numbers.tolist())) == len(numbers), "invalid evaluation roster")
    z, missing = core.transform_runners(race, runner_stats)
    pairs = list(itertools.combinations(sorted(numbers.tolist()), 2))
    position = {int(number): index for index, number in enumerate(numbers.tolist())}
    basis20 = np.vstack([
        core.pair_basis(z[position[a]], z[position[b]], missing[position[a]], missing[position[b]])
        for a, b in pairs
    ])
    p0_by_pair, _ = core.q0_from_scores(numbers.tolist(), race["score"].astype(float).tolist())
    p0 = np.asarray([p0_by_pair[pair] for pair in pairs], dtype=float)
    d_by_number = {int(row.horse_number): float(row.jockey365_field_relative_top3)
                   for row in race.itertuples(index=False)}
    n_by_number = {int(row.horse_number): int(row.jockey365_n) for row in race.itertuples(index=False)}
    d_i = np.asarray([d_by_number[a] for a, _ in pairs], dtype=float)
    d_j = np.asarray([d_by_number[b] for _, b in pairs], dtype=float)
    pair_d = d_i + d_j
    moment = fit_fold["new_pair_moment"]
    pair_z = np.zeros(len(pair_d), dtype=float) if moment["degenerate"] else (
        pair_d - float(moment["mean"])
    ) / float(moment["scale"])
    x = np.column_stack((core.transform_pair_basis(basis20, old_pair_stats), pair_z))
    require(x.shape == (len(pairs), 21) and np.isfinite(x).all(), "invalid evaluation 21-basis")
    beta = np.asarray([fit_fold["beta_by_basis"][name] for name in core.BASIS_NAMES]
                      + [fit_fold["gamma_jockey365_pair_sum"]], dtype=float)
    eta = logit(p0) + x @ beta
    raw = expit(eta)
    h2 = fit_fold["h2_candidate_platt"]
    calibrated_logits = float(h2["A"]) + float(h2["B"]) * eta
    calibrated = expit(calibrated_logits)
    selected = core.pair_choice_from_logits(pairs, eta)
    require(float(h2["B"]) > 0.0 and selected == core.pair_choice_from_logits(pairs, calibrated_logits),
            "candidate H2 map changed pair ranking")
    score_by_number = {int(row.horse_number): float(row.score) for row in race.itertuples(index=False)}
    rows = []
    for k, (a, b) in enumerate(pairs):
        rows.append({
            "race_id": str(race["race_id"].iloc[0]),
            "race_date": race["race_date"].iloc[0].date().isoformat(),
            "evaluation_year": int(race["year"].iloc[0]),
            "distance_m": int(race["distance_m"].iloc[0]),
            "horse_i": int(a), "horse_j": int(b),
            "score_i": score_by_number[a], "score_j": score_by_number[b],
            "candidate_p0_check": float(p0[k]),
            "candidate_eta": float(eta[k]),
            "candidate_raw_probability": float(raw[k]),
            "candidate_calibrated_probability": float(calibrated[k]),
            "selected_candidate": int((a, b) == selected),
            "jockey365_n_i": n_by_number[a], "jockey365_n_j": n_by_number[b],
            "jockey365_d_i": float(d_i[k]), "jockey365_d_j": float(d_j[k]),
            "jockey365_pair_sum": float(pair_d[k]),
            "jockey365_pair_z": float(pair_z[k]),
        })
    diagnostics = {
        "race_id": str(race["race_id"].iloc[0]),
        "race_date": race["race_date"].iloc[0].date().isoformat(),
        "evaluation_year": int(race["year"].iloc[0]),
        "distance_m": int(race["distance_m"].iloc[0]),
        "jockey_basic_candidate_sum_probability_minus_3": math.fsum(map(float, calibrated)) - 3.0,
    }
    return rows, diagnostics


def _stats_from_baseline(core, fit_row):
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
    return runner, pair


def run_predictions() -> None:
    fit_receipt, fit, approval = validate_fit()
    core = import_module("frozen_direct_pair_core_jockey_eval", DIRECT_CORE)
    pair_fit = import_module("frozen_expanded_pair_fit_jockey_eval", BASE_PAIR_FIT)
    pair_predict = import_module("frozen_expanded_pair_predict_jockey_eval", BASE_PAIR_PREDICT)
    jockey_input = import_module("pair_jockey_input_for_eval", STUDY / "jockey_input.py")
    require(sha256(DIRECT_CORE) == EXPECTED_BASE_CORE_SHA256, "frozen direct core changed")
    require(sha256(BASE_PAIR_FIT) == EXPECTED_BASE_PAIR_FIT_SHA256, "frozen pair fit helper changed")
    require(sha256(BASE_PAIR_PREDICT) == EXPECTED_BASE_PAIR_PREDICT_SHA256, "frozen pair predictor changed")
    require(sha256(DIRECT_SCHEDULE) == EXPECTED_BOOTSTRAP_SHA256, "frozen date schedule changed")
    source_lock = json.loads(checked(BASE_SOURCE_LOCK).read_text(encoding="utf-8"))
    require(source_lock.get("status") == "PASS", "baseline source lock not PASS")
    baseline_fit_doc = json.loads(checked(BASELINE_FIT).read_text(encoding="utf-8"))
    require(sha256(BASELINE_FIT) == fit_receipt["frozen_baseline_h1_sha256"], "baseline moment source changed")

    features = pd.read_parquet(
        checked(pair_predict.FEATURES), columns=pair_predict.EVAL_FEATURE_COLUMNS,
        filters=[("year", ">=", 2024), ("year", "<=", 2026)],
    )
    features["race_date"] = pd.to_datetime(features["race_date"], errors="coerce").dt.normalize()
    require(features["race_date"].notna().all() and features["year"].isin(EVAL_YEARS).all(),
            "evaluation feature schema/date changed")
    starts = jockey_input.load_starts(include_results=True)
    all_predictions: list[dict[str, Any]] = []
    all_diagnostics: list[dict[str, Any]] = []
    eval_sources: dict[str, Any] = {}
    for year in EVAL_YEARS:
        rows, eval_sources[str(year)] = pair_predict.evaluation_runner_scores(year, features, source_lock)
        for key in ("api_record_id", "race_id", "horse_id"):
            rows[key] = rows[key].astype("string")
        rows["race_date"] = pd.to_datetime(rows["race_date"], errors="coerce").dt.normalize()
        event = jockey_input.attach_event_jockey(rows, starts)
        rolling = jockey_input.rolling_features(event, starts)
        event = event.merge(
            rolling[["api_record_id", "jockey365_n", "jockey365_top3", "jockey365_expected_top3", "jockey365_field_relative_top3"]],
            on="api_record_id", how="left", validate="one_to_one",
        )
        require(event["jockey365_field_relative_top3"].notna().all(), f"evaluation rolling feature missing: {year}")
        expected_fit = next(row for row in fit["folds"] if int(row["evaluation_year"]) == year)
        baseline_fold = next(row for row in baseline_fit_doc["folds"] if int(row["evaluation_year"]) == year)
        year_count = 0
        for _, race in event.groupby("race_id", sort=True):
            race_predictions, diagnostic = candidate_race_predictions(core, race, expected_fit, baseline_fold)
            all_predictions.extend(race_predictions)
            all_diagnostics.append(diagnostic)
            year_count += 1
        require(year_count == EXPECTED_RACES[year], f"evaluation race count changed: {year}")

    candidate = pd.DataFrame(all_predictions)
    new_diag = pd.DataFrame(all_diagnostics)
    require(len(new_diag) == 1779 and new_diag["race_id"].is_unique, "candidate race prediction coverage changed")
    require(not candidate.duplicated(KEYS).any(), "candidate pair prediction key duplicated")
    require((candidate.groupby("race_id")["selected_candidate"].sum() == 1).all(),
            "candidate must select exactly one pair per race")
    require(np.isfinite(candidate.select_dtypes(include=[np.number]).to_numpy(dtype=float)).all(),
            "non-finite candidate evaluation prediction")

    # Append this candidate to the frozen pair table by exact pair key; all saved
    # labels, probabilities, selectors, and comparator columns remain read-only.
    old = pd.read_parquet(checked(BASE_PAIR_PREDICTIONS))
    require(len(old) == 76848 and old["race_id"].nunique() == 1779, "frozen evaluation pair table shape changed")
    merged = old.merge(candidate, on=KEYS, how="outer", validate="one_to_one", indicator=True, suffixes=("", "_new"))
    require(merged["_merge"].eq("both").all(), "new and frozen evaluation pair keys differ")
    require(np.allclose(merged["p0"], merged["candidate_p0_check"], rtol=0, atol=1e-15),
            "fixed pair prior changed")
    require(np.allclose(merged["score_i"], merged["score_i_new"], rtol=0, atol=0)
            and np.allclose(merged["score_j"], merged["score_j_new"], rtol=0, atol=0),
            "frozen F1_STYLE6 horse score changed")
    merged["latest_pair_eta"] = merged["expanded_eta"]
    merged["latest_pair_raw_probability"] = merged["expanded_candidate_raw_probability"]
    merged["latest_pair_calibrated_probability"] = merged["expanded_candidate_calibrated_probability"]
    merged["selected_latest_pair"] = merged["selected_expanded_candidate"]
    merged["old_direct_calibrated_probability"] = merged["old_direct_candidate_calibrated_probability"]
    merged["eta"] = merged["candidate_eta"]
    merged["candidate_raw_probability"] = merged["candidate_raw_probability_new"]
    merged["candidate_calibrated_probability"] = merged["candidate_calibrated_probability_new"]
    merged["selected_candidate"] = merged["selected_candidate_new"]
    merged["selected_jockey_basic_candidate"] = merged["selected_candidate_new"]
    merged = merged.drop(columns=[
        "_merge", "score_i_new", "score_j_new", "candidate_p0_check",
        "candidate_raw_probability_new", "candidate_calibrated_probability_new", "selected_candidate_new",
    ])
    require((merged.groupby("race_id")["selected_candidate"].sum() == 1).all(), "candidate selector count changed")
    merged = merged.sort_values(KEYS, kind="mergesort").reset_index(drop=True)

    old_diag = pd.read_parquet(checked(BASE_RACE_DIAGNOSTICS))
    require(len(old_diag) == 1779 and old_diag["race_id"].is_unique, "frozen race diagnostics changed")
    old_diag = old_diag.rename(columns={
        "candidate_sum_calibrated_pair_probability_minus_3": "latest_pair_sum_probability_minus_3",
        "candidate_abs_sum_deviation": "latest_pair_abs_sum_deviation",
    })
    new_diag = old_diag.merge(new_diag, on=["race_id", "race_date", "evaluation_year", "distance_m"],
                              how="outer", validate="one_to_one", indicator=True)
    require(new_diag["_merge"].eq("both").all(), "candidate and frozen race keys differ")
    new_diag = new_diag.drop(columns="_merge")
    new_diag["jockey_basic_candidate_abs_sum_deviation"] = new_diag[
        "jockey_basic_candidate_sum_probability_minus_3"
    ].abs()
    new_diag = new_diag.sort_values("race_id", kind="mergesort").reset_index(drop=True)
    write_parquet_once(PREDICTIONS, merged)
    write_parquet_once(DIAGNOSTICS, new_diag)
    receipt = {
        "status": "PASS", "study": STUDY.name,
        "scope": "fixed evaluation pair predictions only; no performance metrics",
        "fit_receipt_sha256": sha256(FIT_RECEIPT_PATH),
        "fit_sha256": sha256(FIT_PATH), "approval_sha256": sha256(OUT / "APPROVAL.json"),
        "input_helper_sha256": sha256(INPUT_HELPER),
        "source_preflight_sha256": sha256(SOURCE_PREFLIGHT),
        "prediction_code_sha256": sha256(Path(__file__).resolve()),
        "fixed_pair_reference_sha256": sha256(BASE_PAIR_PREDICTIONS),
        "fixed_source_lock_sha256": sha256(BASE_SOURCE_LOCK),
        "frozen_core_sha256": sha256(DIRECT_CORE),
        "bootstrap_schedule_sha256": sha256(DIRECT_SCHEDULE),
        "evaluation_score_sources": eval_sources,
        "prediction_rows": int(len(merged)), "prediction_races": int(merged["race_id"].nunique()),
        "evaluation_dates": int(merged["race_date"].nunique()),
        "selected_candidate_per_race": int(merged.groupby("race_id")["selected_candidate"].sum().eq(1).sum()),
        "old_pair_columns_and_selectors_preserved": True,
        "performance_metrics_computed": False,
        "pair_predictions_sha256": sha256(PREDICTIONS),
        "race_diagnostics_sha256": sha256(DIAGNOSTICS),
    }
    write_json_once(PREDICTION_RECEIPT, receipt)



if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "predict":
        raise SystemExit("usage: pair_jockey_predict.py predict")
    run_predictions()
