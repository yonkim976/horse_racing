"""Label-free source, key, timing, split, and definition audit for one pair arm."""

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


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261014_pair_reliability_v1"
OUT = STUDY / "outputs"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
STYLE_OUT = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
EXPANSION = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
ID_STUDY = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
ID_BASIC = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
BASE_PAIR_FIT = EXPANSION / "pair_fit.py"
HISTORICAL_RECEIPT = EXPANSION / "outputs/HISTORICAL_REFIT_RECEIPT.json"
HISTORICAL_LOCK = EXPANSION / "outputs/HISTORICAL_SOURCE_LOCK.json"
HISTORICAL_FIT = EXPANSION / "outputs/expanded_h1_fit.json"
HISTORICAL_FIT_RECEIPT = EXPANSION / "outputs/PAIR_FIT_RECEIPT.json"
CURRENT_PAIR_PREDICTIONS = ID_STUDY / "outputs/evaluation_pair_predictions.parquet"
CURRENT_PREDICTION_RECEIPT = ID_STUDY / "outputs/PREDICTION_RECEIPT.json"
DIRECT_SCHEDULE = DIRECT / "outputs/date_bootstrap_schedule.npy"
EXCLUDED_HORSE = "3005648"
YEARS = (2024, 2025, 2026)
H1_RACES = {2024: 2147, 2025: 2818, 2026: 3458}
H2_RACES = {2024: 336, 2025: 311, 2026: 325}
EVAL_RACES = {2024: 637, 2025: 654, 2026: 488}
DISTANCES = {800, 900, 1000, 1110, 1200, 1300, 1400, 1610}
FEATURE_COLUMNS = [
    "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
    "field_n", "distance_m", "history_cutoff", "observed_starts", "same_starts",
    "same_valid_times", "days_since_same", "mean5_s", "valid_n5", "std5_s",
]
PAIR_COLUMNS = [
    "race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j",
    "p0", "jockey_id_candidate_calibrated_probability", "selected_jockey_id_candidate",
    "selected_raw_top2", "selected_jockey_basic_candidate",
]
PINNED_HASHES = {
    "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet":
        "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
    "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet":
        "0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6",
    "jeju/research/20261012_pair_jockey_id_v1/outputs/FIT.json":
        "39d18ff0f842eb379b280190c96104d0216a8a1a774d2df4d32425795f26dea8",
    "jeju/research/20261012_pair_jockey_id_v1/outputs/FIT_RECEIPT.json":
        "f80c7bafebcc0d0e29ccaf7f0702c208bac83bfac959cafe8f5a3daae17cb74b",
    "jeju/research/20261012_pair_jockey_id_v1/outputs/APPROVAL.json":
        "d866de93716e9030acd7213a7bd6551d6a7d7182d2ffc0eecfd5ec868bc0bbf9",
    "jeju/research/20261012_pair_jockey_id_v1/outputs/SOURCE_PREFLIGHT.json":
        "deferred_to_existing_receipt",
    "jeju/research/20261012_pair_jockey_id_v1/outputs/PREDICTION_RECEIPT.json":
        "deferred_to_existing_receipt",
    "jeju/research/20261012_pair_jockey_basic_v1/outputs/FIT.json":
        "c52db2c6f136bf7ef95d0d0489c368b6131cb054a2a7c97f6d9d6f3675433f9f",
    "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/expanded_h1_fit.json":
        "3a42446feb21aeaf156e59dd24238ce3ea9f9af137d48665c61393571a3774c7",
    "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/PAIR_FIT_RECEIPT.json":
        "7b92ca5fcf3db460d83dd6574d0e43b386ee400a706767eaf158c54572d0e946",
    "jeju/research/20261011_pair_top3_direct_v1/core.py":
        "0a51495c6c1d08f65e1400a6d47c7710d3b32806f678a6bbefe2fab3a8e2de1e",
    "jeju/research/20261011_pair_top3_oos_expansion_v1/pair_fit.py":
        "5187288115621e6affc5079d4c24a6a35a9563385d7b336e958f179484fa3e16",
    "jeju/research/20261012_pair_jockey_basic_v1/pair_jockey_fit.py":
        "2e58ee467bcd573a37cf0780773d940bbc38e1b793e359248dec26242f82741f",
    "jeju/research/20261012_pair_jockey_basic_v1/jockey_input.py":
        "480bc13a42c73d9a5190fb33446bfae6ad74489e146825a1cf4e158ed0658c75",
    "jeju/research/20261012_pair_jockey_id_v1/pair_jockey_id_fit.py":
        "0f89d71fdcbe6bf7e1bbf35af26e6fb68dfc247110b558082e355f3726b7c6d7",
    "jeju/research/20261012_pair_jockey_id_v1/pair_jockey_id_basis.py":
        "0b5f18e49ba0e4671a18cf972924d05c698fd507e7401ad7341877f61efaf3ef",
    "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy":
        "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
}


class PreflightError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise PreflightError(message)


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


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, checked(path))
    require(spec is not None and spec.loader is not None, f"cannot load source helper: {path}")
    sys.modules[name] = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sys.modules[name])
    return sys.modules[name]


def _read_features() -> pd.DataFrame:
    frame = pd.read_parquet(checked(FEATURES), columns=FEATURE_COLUMNS,
                            filters=[("year", ">=", 2019), ("year", "<=", 2026)])
    frame["api_record_id"] = frame["api_record_id"].astype("string")
    frame["race_id"] = frame["race_id"].astype("string")
    frame["horse_id"] = frame["horse_id"].astype("string")
    frame["race_date"] = pd.to_datetime(frame["race_date"], errors="coerce").dt.normalize()
    frame["history_cutoff"] = pd.to_datetime(frame["history_cutoff"], errors="coerce").dt.normalize()
    require(frame["api_record_id"].notna().all() and frame["api_record_id"].is_unique,
            "source api_record_id missing or duplicated")
    require(frame["race_id"].notna().all() and frame["horse_id"].notna().all(),
            "source race/horse key missing")
    require(frame["race_date"].notna().all() and frame["history_cutoff"].notna().all(),
            "source race date/history cutoff missing")
    require(frame["year"].between(2019, 2026).all(), "feature year filter changed")
    require((frame["history_cutoff"] == frame["race_date"] - pd.Timedelta(days=2)).all(),
            "feature history cutoff is not exactly target T-2")
    require(not frame["horse_id"].eq(EXCLUDED_HORSE).any(), "excluded horse entered fixed roster")
    require(set(pd.to_numeric(frame["distance_m"], errors="coerce").dropna().astype(int).unique()) == DISTANCES,
            "distance inventory differs from frozen pair roster")
    require(frame["field_n"].notna().all() and frame["field_n"].ge(4).all(), "invalid field size")
    for key, race in frame.groupby("race_id", sort=False):
        require(race["race_date"].nunique() == 1 and race["year"].nunique() == 1
                and race["distance_m"].nunique() == 1, f"race condition keys conflict: {key}")
        require(race["horse_id"].is_unique and race["horse_number"].notna().all()
                and race["horse_number"].is_unique, f"race runner keys conflict: {key}")
        require(int(race["field_n"].iloc[0]) == len(race), f"field_n/roster size mismatch: {key}")

    counts = ("observed_starts", "same_starts", "same_valid_times", "valid_n5")
    count_detail = {}
    for column in counts:
        values = pd.to_numeric(frame[column], errors="coerce")
        require(values.notna().all(), f"actual source missingness in count column {column}")
        require(np.isfinite(values.to_numpy(dtype=float)).all() and values.ge(0).all()
                and np.equal(values.to_numpy(dtype=float), np.floor(values.to_numpy(dtype=float))).all(),
                f"count column is not nonnegative finite integer: {column}")
        count_detail[column] = {
            "missing": int(values.isna().sum()), "minimum": int(values.min()), "maximum": int(values.max()),
            "unique_nonmissing": int(values.nunique()),
        }
    require(pd.to_numeric(frame["valid_n5"], errors="coerce").le(5).all(), "valid_n5 exceeds 5")
    require(pd.to_numeric(frame["same_valid_times"], errors="coerce").le(
        pd.to_numeric(frame["same_starts"], errors="coerce")).all(),
        "same_valid_times exceeds same_starts")
    require((frame["days_since_same"].isna() == frame["same_starts"].eq(0)).all(),
            "days_since_same missingness conflicts with same_starts")
    require(frame.loc[frame["same_starts"].gt(0), "days_since_same"].notna().all(),
            "same-distance start gap is missing despite same_starts > 0")
    gap = pd.to_numeric(frame["days_since_same"], errors="coerce")
    require(gap.isna().eq(frame["same_starts"].eq(0)).all()
            and gap.dropna().ge(0).all(), "days_since_same must be NULL or a nonnegative gap")

    valid_n = frame["valid_n5"].astype(int)
    mean = pd.to_numeric(frame["mean5_s"], errors="coerce")
    std = pd.to_numeric(frame["std5_s"], errors="coerce")
    require(mean.isna().eq(valid_n.eq(0)).all(), "mean5_s/valid_n5 missingness contract mismatch")
    require((valid_n.lt(3) == std.isna()).all(), "std5_s is not limited to valid_n5 >= 3")
    require(mean.dropna().gt(0).all() and np.isfinite(mean.dropna().to_numpy(dtype=float)).all(),
            "observed mean5_s must be finite and positive")
    require(std.dropna().ge(0).all() and np.isfinite(std.dropna().to_numpy(dtype=float)).all(),
            "observed std5_s must be finite and nonnegative")
    frame.attrs["count_source_checks"] = count_detail
    return frame


def _split(calibration_yearly: dict[int, pd.DataFrame], evaluation_yearly: dict[int, pd.DataFrame],
           evaluation_year: int):
    source = calibration_yearly[evaluation_year - 1]
    h2 = source.loc[source["race_date"].dt.month.ge(7)].copy()
    require(not h2.empty, f"empty H2 roster: {evaluation_year}")
    first_h2 = h2["race_date"].min().date()
    cutoff = first_h2 - timedelta(days=2)
    earlier = [calibration_yearly[year] for year in range(2019, evaluation_year - 1)]
    current = source.loc[
        source["race_date"].dt.month.le(6)
        & source["race_date"].dt.date.map(lambda value: value <= cutoff)
    ].copy()
    h1 = pd.concat([*earlier, current], ignore_index=True)
    require(h1["api_record_id"].is_unique and h2["api_record_id"].is_unique,
            f"duplicate H1/H2 api key: {evaluation_year}")
    require(h1["race_date"].max().date() <= first_h2 - timedelta(days=2),
            f"H1/H2 two-day purge failed: {evaluation_year}")
    evaluation = evaluation_yearly.get(evaluation_year)
    require(evaluation is not None and not evaluation.empty, f"empty evaluation roster: {evaluation_year}")
    first_evaluation = evaluation["race_date"].min().date()
    last_h2 = h2["race_date"].max().date()
    require(last_h2 <= first_evaluation - timedelta(days=2),
            f"H2/evaluation two-day purge failed: {evaluation_year}")
    require(h1["race_id"].nunique() == H1_RACES[evaluation_year], f"H1 race count changed: {evaluation_year}")
    require(h2["race_id"].nunique() == H2_RACES[evaluation_year], f"H2 race count changed: {evaluation_year}")
    require(evaluation["race_id"].nunique() == EVAL_RACES[evaluation_year],
            f"evaluation race count changed: {evaluation_year}")
    return h1, h2, evaluation


def _source_row_summary(rows: pd.DataFrame) -> dict[str, Any]:
    values = {}
    for column in ("observed_starts", "same_valid_times", "valid_n5", "days_since_same", "mean5_s", "std5_s"):
        numeric = pd.to_numeric(rows[column], errors="coerce")
        finite = numeric.dropna().to_numpy(dtype=np.float64)
        values[column] = {
            "rows": int(len(rows)), "missing": int(numeric.isna().sum()),
            "unique_nonmissing": int(numeric.nunique()),
            "minimum": float(np.min(finite)) if len(finite) else None,
            "median": float(np.median(finite)) if len(finite) else None,
            "maximum": float(np.max(finite)) if len(finite) else None,
        }
    return values


def _score_lineage(features: pd.DataFrame) -> tuple[
    dict[int, pd.DataFrame], dict[int, pd.DataFrame], dict[str, Any], dict[str, str]
]:
    pair_fit = import_module("reliability_pair_score_source_helper", BASE_PAIR_FIT)
    historical = json.loads(checked(HISTORICAL_RECEIPT).read_text(encoding="utf-8"))
    historical_lock = json.loads(checked(HISTORICAL_LOCK).read_text(encoding="utf-8"))
    fit_receipt = json.loads(checked(HISTORICAL_FIT_RECEIPT).read_text(encoding="utf-8"))
    require(historical.get("status") == "PASS" and historical.get("pair_fit_performed") is False
            and historical.get("pair_performance_metrics_computed") is False,
            "frozen historical score source receipt changed scope")
    require(historical_lock.get("status") == "PASS" and fit_receipt.get("status") == "PASS",
            "frozen historical score source lock/receipt is not PASS")
    for relative, expected in historical_lock.get("sources", {}).items():
        require(sha256(checked(ROOT / relative)) == expected, f"historical OOS source changed: {relative}")

    calibration_yearly: dict[int, pd.DataFrame] = {}
    evaluation_yearly: dict[int, pd.DataFrame] = {}
    lineage: dict[str, Any] = {}
    hashes: dict[str, str] = {}
    for year in range(2019, 2026):
        score_path, provider_fold = pair_fit.score_source(year)
        score_path = checked(score_path)
        scores = pd.read_parquet(score_path, columns=["api_record_id", "score"])
        scores["api_record_id"] = scores["api_record_id"].astype("string")
        require(scores["api_record_id"].notna().all() and scores["api_record_id"].is_unique,
                f"score API key missing/duplicated: {year}")
        require(np.isfinite(scores["score"].to_numpy(dtype=np.float64)).all(),
                f"non-finite OOS score provider: {year}")
        rows = features.loc[features["year"].eq(year)].copy()
        require(set(rows["api_record_id"]) == set(scores["api_record_id"]),
                f"OOS score coverage mismatch: {year}")
        rows = rows.merge(scores, on="api_record_id", how="left", validate="one_to_one")
        require(rows["score"].notna().all(), f"OOS score join missing: {year}")
        meta_path = (EXPANSION / f"outputs/F1_STYLE6_{provider_fold}/meta.json"
                     if provider_fold <= 2023 else STYLE_OUT / f"F1_STYLE6_{provider_fold}/meta.json")
        meta_path = checked(meta_path)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        refit_max = pd.Timestamp(meta["refit_max"]).normalize()
        require(((rows["race_date"] - pd.Timedelta(days=2)) >= refit_max).all(),
                f"score-provider row violates T-2 lineage: {year}")
        source_hash = sha256(score_path)
        meta_hash = sha256(meta_path)
        if provider_fold <= 2023:
            receipt_row = next((row for row in historical.get("folds", [])
                                if int(row["fold"]) == int(provider_fold)), None)
            require(receipt_row is not None
                    and receipt_row.get("calibration_scores_sha256") == source_hash
                    and receipt_row.get("meta_sha256") == meta_hash,
                    f"historical OOS score receipt mismatch: {year}")
        source_rel = str(score_path.relative_to(ROOT))
        meta_rel = str(meta_path.relative_to(ROOT))
        hashes[source_rel] = source_hash
        hashes[meta_rel] = meta_hash
        rows["score_provider_fold_year"] = int(provider_fold)
        rows["score_provider_role"] = "calibration"
        calibration_yearly[year] = rows
        lineage[f"calibration:{year}"] = {
            "provider_fold_year": int(provider_fold), "provider_role": "calibration",
            "score_path": source_rel, "score_sha256": source_hash,
            "meta_path": meta_rel, "meta_sha256": meta_hash,
            "refit_max": str(meta["refit_max"]), "rows": int(len(rows)),
            "races": int(rows["race_id"].nunique()),
        }
    for year in YEARS:
        path = checked(STYLE_OUT / f"F1_STYLE6_{year}/evaluation_scores.parquet")
        score = pd.read_parquet(path, columns=["api_record_id", "score"])
        score["api_record_id"] = score["api_record_id"].astype("string")
        rows = features.loc[features["year"].eq(year)].copy()
        require(score["api_record_id"].is_unique and set(score["api_record_id"]) == set(rows["api_record_id"]),
                f"evaluation score source coverage mismatch: {year}")
        require(np.isfinite(score["score"].to_numpy(dtype=np.float64)).all(),
                f"non-finite evaluation score source: {year}")
        rows = rows.merge(score, on="api_record_id", how="left", validate="one_to_one")
        meta_path = checked(STYLE_OUT / f"F1_STYLE6_{year}/meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        refit_max = pd.Timestamp(meta["refit_max"]).normalize()
        require(((rows["race_date"] - pd.Timedelta(days=2)) >= refit_max).all(),
                f"evaluation score provider violates T-2: {year}")
        score_rel, meta_rel = str(path.relative_to(ROOT)), str(meta_path.relative_to(ROOT))
        hashes[score_rel] = sha256(path)
        hashes[meta_rel] = sha256(meta_path)
        rows["score_provider_fold_year"] = int(year)
        rows["score_provider_role"] = "evaluation"
        evaluation_yearly[year] = rows
        lineage[f"evaluation:{year}"] = {
            "provider_fold_year": int(year), "provider_role": "evaluation",
            "score_path": score_rel, "score_sha256": sha256(path),
            "meta_path": meta_rel, "meta_sha256": sha256(meta_path),
            "refit_max": str(meta["refit_max"]), "rows": int(len(rows)),
            "races": int(rows["race_id"].nunique()),
        }
    return calibration_yearly, evaluation_yearly, lineage, hashes


def collect() -> dict[str, Any]:
    hashes: dict[str, str] = {}
    for relative, expected in PINNED_HASHES.items():
        if expected == "deferred_to_existing_receipt":
            continue
        path = checked(ROOT / relative)
        observed = sha256(path)
        require(observed == expected, f"pinned artifact hash changed: {relative}")
        hashes[relative] = observed
    style_lock = checked(STYLE_OUT / "prepared_lock.json")
    style_final = checked(STYLE_OUT / "final_verification.json")
    style_verify = json.loads(style_final.read_text(encoding="utf-8"))
    require(style_verify.get("passed") is True and style_verify.get("production_or_registry_changed") is False
            and style_verify.get("database_changed") is False,
            "frozen F1_STYLE6 source preparation verification changed")
    hashes[str(style_lock.relative_to(ROOT))] = sha256(style_lock)
    hashes[str(style_final.relative_to(ROOT))] = sha256(style_final)

    old_preflight_path = checked(ID_STUDY / "outputs/SOURCE_PREFLIGHT.json")
    old_preflight = json.loads(old_preflight_path.read_text(encoding="utf-8"))
    require(old_preflight.get("status") == "PASS" and old_preflight.get("finish_labels_read") is False
            and old_preflight.get("performance_metrics_computed") is False,
            "existing jockey-ID label-free source preflight changed")
    old_receipt = json.loads(checked(CURRENT_PREDICTION_RECEIPT).read_text(encoding="utf-8"))
    require(old_receipt.get("status") == "PASS" and old_receipt.get("prediction_rows") == 76848
            and old_receipt.get("prediction_races") == 1779,
            "existing jockey-ID prediction receipt changed scope")
    require(old_receipt.get("pair_predictions_sha256") == sha256(CURRENT_PAIR_PREDICTIONS),
            "fixed current pair prediction receipt/hash mismatch")
    hashes[str(old_preflight_path.relative_to(ROOT))] = sha256(old_preflight_path)
    hashes[str(CURRENT_PREDICTION_RECEIPT.relative_to(ROOT))] = sha256(CURRENT_PREDICTION_RECEIPT)

    features = _read_features()
    count_detail = features.attrs["count_source_checks"]
    calibration_yearly, evaluation_yearly, score_lineage, score_hashes = _score_lineage(features)
    hashes.update(score_hashes)
    split_detail = {}
    for year in YEARS:
        h1, h2, evaluation = _split(calibration_yearly, evaluation_yearly, year)
        split_detail[str(year)] = {
            "h1_rows": int(len(h1)), "h1_races": int(h1["race_id"].nunique()),
            "h1_dates": int(h1["race_date"].nunique()),
            "h1_first_date": h1["race_date"].min().date().isoformat(),
            "h1_last_date": h1["race_date"].max().date().isoformat(),
            "h2_rows": int(len(h2)), "h2_races": int(h2["race_id"].nunique()),
            "h2_dates": int(h2["race_date"].nunique()),
            "h2_first_date": h2["race_date"].min().date().isoformat(),
            "h2_last_date": h2["race_date"].max().date().isoformat(),
            "evaluation_rows": int(len(evaluation)),
            "evaluation_races": int(evaluation["race_id"].nunique()),
            "evaluation_dates": int(evaluation["race_date"].nunique()),
            "evaluation_first_date": evaluation["race_date"].min().date().isoformat(),
            "evaluation_last_date": evaluation["race_date"].max().date().isoformat(),
            "h1_to_h2_days": int((h2["race_date"].min() - h1["race_date"].max()).days),
            "h2_to_evaluation_days": int((evaluation["race_date"].min() - h2["race_date"].max()).days),
            "h1_h2_purge_days": 2, "h2_evaluation_purge_days": 2,
        }
    eval_roster = pd.concat([evaluation_yearly[year] for year in YEARS], ignore_index=True)
    require(len(eval_roster) == 17412 and eval_roster["race_id"].nunique() == 1779
            and eval_roster["race_date"].nunique() == 269,
            "fixed evaluation runner/race/date roster changed")
    require(eval_roster.groupby("year")["race_id"].nunique().to_dict() == EVAL_RACES,
            "evaluation year race inventory changed")

    # Read only outcome-free columns from the immutable pair table.
    fixed = pd.read_parquet(checked(CURRENT_PAIR_PREDICTIONS), columns=PAIR_COLUMNS)
    fixed["race_id"] = fixed["race_id"].astype("string")
    fixed["race_date"] = pd.to_datetime(fixed["race_date"], errors="coerce").dt.normalize()
    require(len(fixed) == 76848 and fixed["race_id"].nunique() == 1779,
            "fixed current selected-pair table shape changed")
    require(not fixed.duplicated(["race_id", "horse_i", "horse_j"]).any(),
            "fixed pair key duplicated")
    for col in ("selected_jockey_id_candidate", "selected_raw_top2", "selected_jockey_basic_candidate"):
        require(fixed.groupby("race_id")[col].sum().eq(1).all(), f"fixed selector must select one pair: {col}")
    old_p = pd.to_numeric(fixed["jockey_id_candidate_calibrated_probability"], errors="coerce")
    p0 = pd.to_numeric(fixed["p0"], errors="coerce")
    require(old_p.notna().all() and np.isfinite(old_p.to_numpy(dtype=float)).all()
            and old_p.between(0, 1, inclusive="neither").all(), "fixed current probabilities invalid")
    require(p0.notna().all() and np.isfinite(p0.to_numpy(dtype=float)).all()
            and p0.between(0, 1, inclusive="neither").all(), "frozen pair prior invalid")
    pair_coverage: dict[str, int] = {}
    eval_by_race = {str(race_id): group for race_id, group in eval_roster.groupby("race_id", sort=False)}
    for race_id, group in fixed.groupby("race_id", sort=False):
        key = str(race_id)
        require(key in eval_by_race, f"fixed pair race absent from evaluation roster: {key}")
        roster = eval_by_race[key]
        numbers = sorted(pd.to_numeric(roster["horse_number"], errors="raise").astype(int).tolist())
        expected_pairs = {(a, b) for i, a in enumerate(numbers) for b in numbers[i + 1:]}
        observed_pairs = set(zip(group["horse_i"].astype(int), group["horse_j"].astype(int), strict=True))
        require(observed_pairs == expected_pairs, f"fixed pair horse numbers differ from API roster: {key}")
        require(group["race_date"].nunique() == 1 and group["race_date"].iloc[0] == roster["race_date"].iloc[0],
                f"fixed pair race date differs from score roster: {key}")
        require(group["evaluation_year"].nunique() == 1 and int(group["evaluation_year"].iloc[0]) == int(roster["year"].iloc[0]),
                f"fixed pair evaluation year differs from score roster: {key}")
        require(group["distance_m"].nunique() == 1 and int(group["distance_m"].iloc[0]) == int(roster["distance_m"].iloc[0]),
                f"fixed pair distance differs from score roster: {key}")
        pair_coverage[key] = len(observed_pairs)
    require(sum(pair_coverage.values()) == 76848, "fixed pair enumeration total changed")

    schedule = np.load(checked(DIRECT_SCHEDULE), allow_pickle=False)
    require(schedule.shape == (2000, 269) and schedule.dtype == np.int32,
            "fixed date bootstrap schedule dimensions/dtype changed")

    # All work through this point reads only keys, date/score/features and saved
    # probability columns; no finish-position or y_pair column is selected.
    source_hashes = dict(sorted(hashes.items()))
    return {
        "status": "PASS", "study": STUDY.name,
        "scope": "label-free source identity, T-2, fixed split, feature definition, score-provider lineage, and stored pair-key audit",
        "finish_labels_read": False, "evaluation_target_labels_read": False,
        "evaluation_pair_labels_read": False, "feature_moments_computed": False,
        "performance_metrics_computed": False, "optimizer_runs": 0,
        "h2_calibration_fits": 0, "evaluation_predictions_generated": False,
        "database_or_network_access": False,
        "feature_source": {
            "path": str(FEATURES.relative_to(ROOT)), "sha256": sha256(FEATURES),
            "rows_2019_2026": int(len(features)), "races_2019_2026": int(features["race_id"].nunique()),
            "date_min": features["race_date"].min().date().isoformat(),
            "date_max": features["race_date"].max().date().isoformat(),
            "key_checks": {"api_record_id_unique": True, "race_horse_id_unique": True,
                           "horse_number_unique_within_race": True, "field_n_matches_roster": True,
                           "horse_id_distance_date_join_basis": True, "history_cutoff_equals_T_minus_2": True},
            "count_source_checks": count_detail,
            "same_valid_times_le_same_starts": True,
            "mean5_source_contract": "mean of positive valid times among the latest at most five actual same-distance started slots; valid_n5 counts finite observed times",
            "std5_source_contract": "sample standard deviation ddof=1; provided only when valid_n5 >= 3; never recomputed for n=1 or n=2",
            "days_since_same_source_contract": "calendar days to the latest same-distance started event, which need not have valid finish time",
            "runner_feature_distribution": _source_row_summary(features),
            "career_scope_limit": "observed_starts and same_valid_times describe cached historical coverage, not a lifetime census",
        },
        "score_provider_lineage_by_year": score_lineage,
        "split_by_evaluation_year": split_detail,
        "evaluation_roster": {
            "rows": int(len(eval_roster)), "races": int(eval_roster["race_id"].nunique()),
            "dates": int(eval_roster["race_date"].nunique()),
            "by_year_rows": {str(int(k)): int(v) for k, v in eval_roster.groupby("year").size().items()},
            "by_year_races": {str(int(k)): int(v) for k, v in eval_roster.groupby("year")["race_id"].nunique().items()},
        },
        "fixed_current_pair_reference": {
            "path": str(CURRENT_PAIR_PREDICTIONS.relative_to(ROOT)),
            "sha256": sha256(CURRENT_PAIR_PREDICTIONS), "rows": int(len(fixed)),
            "races": int(fixed["race_id"].nunique()), "pairs_per_race_matches_full_roster": True,
            "selected_probability_column": "jockey_id_candidate_calibrated_probability",
            "selected_pair_column": "selected_jockey_id_candidate",
            "secondary_selectors": ["selected_raw_top2", "selected_jockey_basic_candidate"],
            "pair_labels_loaded": False,
        },
        "date_bootstrap_schedule": {
            "path": str(DIRECT_SCHEDULE.relative_to(ROOT)), "sha256": sha256(DIRECT_SCHEDULE),
            "shape": list(schedule.shape), "dtype": str(schedule.dtype),
        },
        "source_hashes": source_hashes,
        "code_hashes": {
            "plan_sha256": sha256(STUDY / "PLAN.md"),
            "source_preflight_sha256": sha256(Path(__file__).resolve()),
            "basis_sha256": sha256(STUDY / "pair_reliability_basis.py"),
            "fit_code_sha256": sha256(STUDY / "pair_reliability_fit.py"),
        },
    }


def write_once(path: Path, payload: dict[str, Any]) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main() -> None:
    value = collect()
    write_once(OUT / "SOURCE_PREFLIGHT.json", value)
    print(json.dumps({
        "status": value["status"], "scope": value["scope"],
        "eval_rows": value["evaluation_roster"]["rows"],
        "eval_races": value["evaluation_roster"]["races"],
        "count_source_checks": value["feature_source"]["count_source_checks"],
        "split": value["split_by_evaluation_year"],
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
