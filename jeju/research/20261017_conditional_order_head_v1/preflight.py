#!/usr/bin/env python3
"""Outcome-free source and mathematical preflight for the conditional order head."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.special import logsumexp


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY_REL = "jeju/research/20261017_conditional_order_head_v1"
STUDY = ROOT / STUDY_REL
OUT = STUDY / "outputs"

STYLE_ROOT = "jeju/research/20261010_style_history_ablation_v1"
FEATURE_PATH = f"{STYLE_ROOT}/outputs/features.parquet"
LINEAGE_PATH = f"{STYLE_ROOT}/outputs/style_history_lineage.parquet"
RUNNER_PRED_PATH = f"{STYLE_ROOT}/outputs/report/runner_predictions.parquet"
TLA_PATH = "jeju/research/20261015_research_other_pool_support_v1/tla_set_probabilities.parquet"
COHORT_PATH = "jeju/research/20261015_operating_postrace_value_comparison_v1/cohort.csv"
SCHEDULE_PATH = "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
SCHEDULE_RECEIPT_PATH = "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
ROOT_PROOF_PATH = "jeju/research/20261017_order_head_rootreview_v1/ROOT_SOURCE_PREFLIGHT.json"

ATOL = 1e-12
STYLE_MEANS = (
    "hist_s1f_relpos_mean5",
    "hist_s1f_to_c4_forward_mean5",
    "hist_c4_to_g1f_forward_mean5",
)
STYLE_COUNTS = (
    "hist_s1f_relpos_n",
    "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_pair_n",
)
STYLE_COLUMNS = (
    "hist_s1f_relpos_mean5",
    "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5",
    "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5",
    "hist_c4_to_g1f_pair_n",
)
FEATURE_COLUMNS = [
    "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
    "field_n", "finish_position", "distance_m", "history_cutoff", "latest_history_date",
    *STYLE_COLUMNS,
]
SCORE_COLUMNS = ["api_record_id", "score"]
EXPECTED_EVAL = {
    2024: (6329, 637, "2024-01-05", "2024-12-28"),
    2025: (6410, 654, "2025-01-03", "2025-12-27"),
    2026: (4673, 488, "2026-01-02", "2026-09-19"),
}
EXPECTED_SPLIT = {
    2024: {"H1": (3089, 312, "2023-01-06", "2023-06-24"),
           "H2": (3327, 336, "2023-07-01", "2023-12-30")},
    2025: {"H1": (3244, 326, "2024-01-05", "2024-06-29"),
           "H2": (3085, 311, "2024-07-05", "2024-12-28")},
    2026: {"H1": (3238, 329, "2025-01-03", "2025-06-28"),
           "H2": (3172, 325, "2025-07-04", "2025-12-27")},
}

SOURCE_HASHES = {
    FEATURE_PATH: "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
    LINEAGE_PATH: "679501dc29cecdf82cf24946cfff3ba43728bfdfdcf69647425f823b40be86e8",
    RUNNER_PRED_PATH: "706bca01e5f5e780a8ffbe9e2ad4553fea9e3d76df097b4c9648d7aabac44e56",
    f"{STYLE_ROOT}/CONTRACT.md": "c10aac8f6faa6e841afd9ef829bfa0b29ada2dceabcbb5405fdfad9c12536bf9",
    f"{STYLE_ROOT}/ARTIFACT_MANIFEST.json": "6afc0e8f73ec086052fad4cde4d7edcd62fdf1bbc782108da89732dc3a5b4a4e",
    f"{STYLE_ROOT}/outputs/F1_STYLE6_2024/calibration_scores.parquet": "360cc559b1ab19cde177e0bb23206fd36f123b707714fbcb63547fdb9bed05b2",
    f"{STYLE_ROOT}/outputs/F1_STYLE6_2025/calibration_scores.parquet": "b092d28f0cbd45dd3a184a4a8ab89e9b5b5a78eef8068c45fda3de92734a3755",
    f"{STYLE_ROOT}/outputs/F1_STYLE6_2026/calibration_scores.parquet": "6a7ed320e59add698faafd9008c882dc8a83a84f9198094371525f4c4ebd37d8",
    f"{STYLE_ROOT}/outputs/F1_STYLE6_2024/evaluation_scores.parquet": "b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60",
    f"{STYLE_ROOT}/outputs/F1_STYLE6_2025/evaluation_scores.parquet": "45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12",
    f"{STYLE_ROOT}/outputs/F1_STYLE6_2026/evaluation_scores.parquet": "0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a",
    f"{STYLE_ROOT}/outputs/F1_STYLE6_2024/meta.json": "15acbf959654da82d2240027e7b7d768bb9226af18395dac9ec92a68a4471726",
    f"{STYLE_ROOT}/outputs/F1_STYLE6_2025/meta.json": "23c4b0684477f34fbb2e99c22d0037cd903d5459db369f084773ec25c640f4a8",
    f"{STYLE_ROOT}/outputs/F1_STYLE6_2026/meta.json": "e9dbfe5226571cb29e34b352a4ad8808a735d70929e66b42efb41b3e807ff06d",
    TLA_PATH: "7c7bafcb315a9f9595e06aa1ee12ca0affbcf3abcc13426e90e079261d29b382",
    "jeju/research/20261015_research_other_pool_support_v1/REPORT.json": "e2f3e99d2af8d247fa6448708c39f95d4786d1e5e9321411d7d02fec77df99a4",
    "jeju/research/20261015_research_other_pool_support_v1/SOURCE_MANIFEST.json": "bab791f8bc5f73b0c3b155b3befaa4ecd443d8deff4f9cd5d67f64cc2ae33096",
    COHORT_PATH: "4f87d05e0f7e2db48f1029dbf1fc78c393ba3804eb20ccb8d28cf6e20e73983f",
    SCHEDULE_PATH: "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
    SCHEDULE_RECEIPT_PATH: "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e",
    ROOT_PROOF_PATH: "a8a605ab2130702ea5b37a02c9b1a6bf0fc6e52ef4f61cb924ac4b2b07e3bf0d",
}


class PreflightError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PreflightError(message)


def checked_path(relative: str) -> Path:
    candidate = ROOT / relative
    require(not candidate.is_symlink(), f"input must not be a symlink: {relative}")
    resolved = candidate.resolve(strict=True)
    require(resolved.is_relative_to(ROOT), f"input escaped repository root: {relative}")
    require(resolved.is_file(), f"input is not a regular file: {relative}")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_source_hashes() -> dict[str, dict[str, Any]]:
    verified: dict[str, dict[str, Any]] = {}
    for relative, expected in SOURCE_HASHES.items():
        path = checked_path(relative)
        actual = sha256_file(path)
        require(actual == expected, f"SHA-256 mismatch for {relative}: {actual}")
        verified[relative] = {"sha256": actual, "bytes": path.stat().st_size}
    return verified


def read_parquet(relative: str, columns: list[str]) -> pd.DataFrame:
    path = checked_path(relative)
    schema = pq.ParquetFile(path).schema_arrow
    missing = sorted(set(columns) - set(schema.names))
    require(not missing, f"missing columns in {relative}: {missing}")
    return pq.read_table(path, columns=columns).to_pandas()


def read_score(relative: str) -> pd.DataFrame:
    path = checked_path(relative)
    schema = pq.ParquetFile(path).schema_arrow
    require(schema.names == SCORE_COLUMNS, f"score schema mismatch in {relative}: {schema.names}")
    require(str(schema.field("api_record_id").type) == "int64", f"api_record_id is not int64 in {relative}")
    require(str(schema.field("score").type) == "double", f"score is not double in {relative}")
    df = pq.read_table(path, columns=SCORE_COLUMNS).to_pandas()
    require(not df["api_record_id"].duplicated().any(), f"duplicate score key in {relative}")
    require(np.isfinite(df["score"].to_numpy(dtype=float)).all(), f"non-finite score in {relative}")
    return df


def parse_dates(values: pd.Series, field: str, allow_null: bool = False) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    if not allow_null:
        require(parsed.notna().all(), f"invalid/null {field}")
    else:
        require(parsed[values.notna()].notna().all(), f"invalid non-null {field}")
    return parsed.dt.date


def load_features() -> pd.DataFrame:
    df = read_parquet(FEATURE_PATH, FEATURE_COLUMNS)
    require(len(df) == 52_155, f"feature row count changed: {len(df)}")
    df["race_date_parsed"] = parse_dates(df["race_date"], "race_date")
    df["history_cutoff_parsed"] = parse_dates(df["history_cutoff"], "history_cutoff")
    df["latest_history_date_parsed"] = parse_dates(
        df["latest_history_date"], "latest_history_date", allow_null=True
    )
    require(df["year"].astype(int).eq(pd.Series(df["race_date_parsed"]).map(lambda d: d.year)).all(),
            "feature year/date mismatch")
    require(not df["api_record_id"].isna().any(), "null api_record_id in frozen features")
    require(not df["api_record_id"].duplicated().any(), "duplicate api_record_id in frozen features")
    require(not df[["race_id", "horse_number"]].duplicated().any(), "duplicate race/horse-number key")
    require(not df[["race_id", "horse_id"]].duplicated().any(), "duplicate race/horse-id key")
    require(df[["race_id", "horse_id", "horse_number"]].notna().all().all(), "null runner key")

    cutoff_expected = pd.Series(df["race_date_parsed"]).map(lambda d: d - timedelta(days=2))
    require(df["history_cutoff_parsed"].eq(cutoff_expected).all(), "feature cutoff is not race_date−2d")
    has_latest = df["latest_history_date_parsed"].notna()
    require((df.loc[has_latest, "latest_history_date_parsed"] <=
             df.loc[has_latest, "history_cutoff_parsed"]).all(), "latest history exceeds T−2 cutoff")

    for mean_col, count_col in zip(STYLE_MEANS, STYLE_COUNTS, strict=True):
        counts = pd.to_numeric(df[count_col], errors="coerce")
        count_values = counts.to_numpy(dtype=float)
        require(np.isfinite(count_values).all(), f"non-finite {count_col}")
        require(np.equal(count_values, np.floor(count_values)).all(), f"non-integer {count_col}")
        require(((count_values >= 0) & (count_values <= 5)).all(), f"{count_col} outside 0..5")
        means = pd.to_numeric(df[mean_col], errors="coerce")
        mean_values = means.to_numpy(dtype=float)
        missing = means.isna().to_numpy()
        require(np.isfinite(mean_values[~missing]).all(), f"non-finite observed {mean_col}")
        require(np.array_equal(missing, count_values == 0), f"mean/count missingness mismatch: {mean_col}/{count_col}")

    for race_id, race in df.groupby("race_id", sort=False):
        n = int(race["field_n"].iloc[0])
        require(race["race_date"].nunique(dropna=False) == 1, f"race date varies in {race_id}")
        require(race["year"].nunique(dropna=False) == 1, f"year varies in {race_id}")
        require(race["field_n"].nunique(dropna=False) == 1, f"field_n varies in {race_id}")
        require(n >= 4 and len(race) == n, f"incomplete field in {race_id}")
        require(race["horse_number"].nunique() == n and race["horse_id"].nunique() == n,
                f"duplicate or missing horse in {race_id}")
        positions = sorted(int(x) for x in race["finish_position"].tolist())
        require(positions == list(range(1, n + 1)), f"finish positions are not a complete permutation in {race_id}")
        require(sum(position <= 3 for position in positions) == 3, f"Top3 label roster invalid in {race_id}")
    require(df["race_id"].nunique() == 5_206, "full feature race count changed")
    return df


def verify_lineage(features: pd.DataFrame) -> dict[str, Any]:
    columns = [
        "target_api_record_id", "target_race_id", "target_horse_id", "target_distance_m",
        "target_cutoff", "source_api_record_id", "source_race_id", "source_horse_id",
        "source_distance_m", "source_race_date", "slot_position",
    ]
    lineage = read_parquet(LINEAGE_PATH, columns)
    require(len(lineage) == 178_459, f"style history lineage row count changed: {len(lineage)}")
    require(lineage[["target_api_record_id", "source_api_record_id", "slot_position"]].notna().all().all(),
            "null source/target lineage key")
    target_rows = features[["api_record_id", "race_id", "horse_id", "distance_m", "history_cutoff"]].rename(
        columns={
            "api_record_id": "target_api_record_id",
            "race_id": "feature_race_id",
            "horse_id": "feature_horse_id",
            "distance_m": "feature_distance_m",
            "history_cutoff": "feature_cutoff",
        }
    )
    joined = lineage.merge(target_rows, on="target_api_record_id", how="left", validate="many_to_one", indicator=True)
    require(joined["_merge"].eq("both").all(), "lineage target is absent from frozen features")
    require(joined["target_race_id"].eq(joined["feature_race_id"]).all(), "lineage target race mismatch")
    require(joined["target_horse_id"].eq(joined["feature_horse_id"]).all(), "lineage target horse mismatch")
    require(joined["target_cutoff"].eq(joined["feature_cutoff"]).all(), "lineage target cutoff mismatch")
    require(np.allclose(joined["target_distance_m"].to_numpy(float),
                        joined["feature_distance_m"].to_numpy(float), rtol=0, atol=0),
            "lineage target distance mismatch")
    require(joined["source_horse_id"].eq(joined["target_horse_id"]).all(), "history source horse mismatch")
    require(joined["source_distance_m"].eq(joined["target_distance_m"]).all(), "history source distance mismatch")
    source_date = parse_dates(joined["source_race_date"], "lineage source_race_date")
    target_cutoff = parse_dates(joined["target_cutoff"], "lineage target_cutoff")
    # The frozen feature cutoff is exactly target date minus two days; comparing source dates
    # directly to the cutoff avoids using any current database or reconstructed release time.
    require((source_date <= target_cutoff).all(), "lineage source race date exceeds target T−2 cutoff")
    require(not joined.duplicated(["target_api_record_id", "slot_position"]).any(), "duplicate target slot position")
    require(not joined.duplicated(["target_api_record_id", "source_api_record_id"]).any(),
            "duplicate source ID within target history")
    slot_counts = joined.groupby("target_api_record_id")["slot_position"].agg(["min", "max", "nunique"])
    require((slot_counts["min"] >= 1).all() and (slot_counts["max"] <= 5).all(), "lineage slot outside 1..5")
    return {
        "rows": int(len(lineage)),
        "targets": int(lineage["target_api_record_id"].nunique()),
        "all_targets_match_frozen_features": True,
        "all_source_dates_at_or_before_target_t2": True,
        "slot_positions_unique_and_within_1_5": True,
    }


def add_score(features: pd.DataFrame, scores: pd.DataFrame, label: str) -> pd.DataFrame:
    feature_ids = set(features["api_record_id"].astype(int))
    score_ids = set(scores["api_record_id"].astype(int))
    require(feature_ids == score_ids, f"score/feature key set mismatch for {label}")
    merged = features.merge(scores, on="api_record_id", how="inner", validate="one_to_one")
    require(len(merged) == len(features) == len(scores), f"score/feature row count mismatch for {label}")
    require(np.isfinite(merged["score"].to_numpy(float)).all(), f"non-finite joined score for {label}")
    return merged


def split_support(frame: pd.DataFrame) -> dict[str, Any]:
    support: dict[str, Any] = {}
    for col in STYLE_COLUMNS:
        values = pd.to_numeric(frame[col], errors="coerce")
        support[col] = {
            "valid_rows": int(values.notna().sum()),
            "missing_rows": int(values.isna().sum()),
        }
    for mean_col in STYLE_MEANS:
        support[f"missing_indicator:{mean_col}"] = {
            "one_rows": int(frame[mean_col].isna().sum()),
            "zero_rows": int(frame[mean_col].notna().sum()),
        }
    return support


def check_fold(year: int, features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    folder = f"{STYLE_ROOT}/outputs/F1_STYLE6_{year}"
    meta = json.loads(checked_path(f"{folder}/meta.json").read_text(encoding="utf-8"))
    cal_scores = read_score(f"{folder}/calibration_scores.parquet")
    eval_scores = read_score(f"{folder}/evaluation_scores.parquet")
    cal_year = year - 1
    cal_features = features.loc[features["year"].eq(cal_year)].copy()
    eval_features = features.loc[features["year"].eq(year)].copy()
    cal = add_score(cal_features, cal_scores, f"{year} calibration")
    evaluation = add_score(eval_features, eval_scores, f"{year} evaluation")

    require(meta.get("variant") == "F1_STYLE6", f"wrong saved variant for {year}")
    require(int(meta.get("evaluation_year")) == year, f"wrong evaluation year in {year} meta")
    require(len(cal) == int(meta["calibration_rows"]), f"calibration row count mismatch for {year}")
    require(cal["race_id"].nunique() == int(meta["calibration_races"]), f"calibration race count mismatch for {year}")
    eval_rows, eval_races, eval_min, eval_max = EXPECTED_EVAL[year]
    require(len(evaluation) == eval_rows == int(meta["evaluation_rows"]), f"evaluation rows mismatch for {year}")
    require(evaluation["race_id"].nunique() == eval_races == int(meta["evaluation_races"]),
            f"evaluation races mismatch for {year}")
    eval_date_text = evaluation["race_date_parsed"].map(str)
    require(eval_date_text.min() == eval_min == meta["evaluation_min"], f"evaluation min date mismatch for {year}")
    require(eval_date_text.max() == eval_max == meta["evaluation_max"], f"evaluation max date mismatch for {year}")
    require(set(cal["year"].astype(int).unique()) == {cal_year}, f"wrong calibration feature year for {year}")
    require(set(evaluation["year"].astype(int).unique()) == {year}, f"wrong evaluation feature year for {year}")

    cal["_date"] = cal["race_date_parsed"]
    evaluation["_date"] = evaluation["race_date_parsed"]
    h1_candidates = cal.loc[cal["_date"].map(lambda d: d.month <= 6)].copy()
    h2 = cal.loc[cal["_date"].map(lambda d: d.month >= 7)].copy()
    require(not h1_candidates.empty and not h2.empty, f"empty calibration half for {year}")
    first_h2 = min(h2["_date"])
    last_h1_allowed = first_h2 - timedelta(days=2)
    h1 = h1_candidates.loc[h1_candidates["_date"] <= last_h1_allowed].copy()
    purged = h1_candidates.loc[h1_candidates["_date"] > last_h1_allowed].copy()
    expected_h1 = EXPECTED_SPLIT[year]["H1"]
    expected_h2 = EXPECTED_SPLIT[year]["H2"]
    for split_name, split, expected in (("H1", h1, expected_h1), ("H2", h2, expected_h2)):
        rows, races, minimum, maximum = expected
        actual_min = str(min(split["_date"])) if len(split) else None
        actual_max = str(max(split["_date"])) if len(split) else None
        require((len(split), split["race_id"].nunique(), actual_min, actual_max) == expected,
                f"{year} {split_name} split differs from frozen source review")
    first_h1 = min(h1["_date"])
    last_h1 = max(h1["_date"])
    last_h2 = max(h2["_date"])
    first_eval = min(evaluation["_date"])
    refit_max = date.fromisoformat(meta["refit_max"])
    require(refit_max <= first_h1 - timedelta(days=2), f"saved refit to H1 T−2 failed for {year}")
    require(last_h1 <= first_h2 - timedelta(days=2), f"H1 to H2 T−2 failed for {year}")
    require(last_h2 <= first_eval - timedelta(days=2), f"H2 to evaluation T−2 failed for {year}")

    fold = {
        "evaluation_year": year,
        "calibration_label_year": cal_year,
        "saved_refit_max": meta["refit_max"],
        "saved_tau_for_native_q_only": float(meta["tau"]),
        "calibration_source_rows": int(len(cal)),
        "calibration_source_races": int(cal["race_id"].nunique()),
        "H1": {"rows": int(len(h1)), "races": int(h1["race_id"].nunique()),
               "date_min": str(first_h1), "date_max": str(last_h1),
               "race_dates_purged_before_H2": int(purged["_date"].nunique()),
               "purged_races": int(purged["race_id"].nunique()),
               "feature_support": split_support(h1)},
        "H2": {"rows": int(len(h2)), "races": int(h2["race_id"].nunique()),
               "date_min": str(min(h2["_date"])), "date_max": str(last_h2),
               "feature_support": split_support(h2)},
        "evaluation": {"rows": int(len(evaluation)), "races": int(evaluation["race_id"].nunique()),
                       "date_min": eval_min, "date_max": eval_max,
                       "feature_support": split_support(evaluation)},
        "temporal_checks": {
            "saved_refit_max_le_first_H1_minus_2d": True,
            "last_H1_le_first_H2_minus_2d": True,
            "last_H2_le_first_eval_minus_2d": True,
            "race_dates_kept_whole": True,
        },
    }
    return cal, evaluation, fold


def pl_log_probability_and_gradient(x: np.ndarray, beta: np.ndarray, order: tuple[int, int, int]) -> tuple[float, np.ndarray]:
    utility = x @ beta
    remaining = [0, 1, 2]
    log_probability = 0.0
    gradient_log = np.zeros_like(beta, dtype=float)
    for chosen in order[:2]:
        logits = utility[remaining]
        probs = np.exp(logits - logsumexp(logits))
        local_choice = remaining.index(chosen)
        log_probability += float(utility[chosen] - logsumexp(logits))
        gradient_log += x[chosen] - probs @ x[remaining]
        remaining.remove(chosen)
    return log_probability, gradient_log


def conditional_nll_gradient(
    races: list[np.ndarray], orders: list[tuple[int, int, int]], beta: np.ndarray, ridge: float
) -> tuple[float, np.ndarray]:
    loss = 0.0
    gradient = np.zeros_like(beta, dtype=float)
    for x, order in zip(races, orders, strict=True):
        logp, grad_log = pl_log_probability_and_gradient(x, beta, order)
        loss -= logp
        gradient -= grad_log
    loss /= len(races)
    gradient /= len(races)
    loss += 0.5 * ridge * float(beta @ beta)
    gradient += ridge * beta
    return float(loss), gradient


def conditional_order_probability(utilities: np.ndarray, order: tuple[int, int, int]) -> float:
    remaining = [0, 1, 2]
    probability = 1.0
    for chosen in order[:2]:
        logits = utilities[remaining]
        probability *= float(np.exp(logits[remaining.index(chosen)] - logsumexp(logits)))
        remaining.remove(chosen)
    return probability


def synthetic_gradient_and_coherence_check() -> dict[str, Any]:
    rng = np.random.default_rng(20261017)
    races = [rng.normal(size=(3, 10)) for _ in range(4)]
    orders = [(0, 1, 2), (2, 0, 1), (1, 2, 0), (1, 0, 2)]
    beta = rng.normal(scale=0.2, size=10)
    loss, analytic = conditional_nll_gradient(races, orders, beta, ridge=0.01)
    step = 1e-6
    numeric = np.empty_like(beta)
    for j in range(len(beta)):
        plus, minus = beta.copy(), beta.copy()
        plus[j] += step
        minus[j] -= step
        numeric[j] = (
            conditional_nll_gradient(races, orders, plus, ridge=0.01)[0]
            - conditional_nll_gradient(races, orders, minus, ridge=0.01)[0]
        ) / (2 * step)
    max_abs_error = float(np.max(np.abs(analytic - numeric)))
    max_rel_error = float(np.max(np.abs(analytic - numeric) / np.maximum(1.0, np.abs(numeric))))
    require(np.isfinite(loss) and np.isfinite(analytic).all(), "synthetic PL objective/gradient is non-finite")
    require(max_abs_error < 1e-7, f"synthetic PL gradient check failed: {max_abs_error}")

    zero_probabilities = [conditional_order_probability(np.zeros(3), p) for p in itertools.permutations(range(3))]
    require(np.allclose(zero_probabilities, np.full(6, 1 / 6), rtol=0, atol=ATOL),
            "zero-coefficient PL is not uniform over six orders")

    horse_numbers = [1, 2, 3, 4]
    scores = np.asarray([0.42, -0.35, 1.12, 0.05], dtype=float)
    tau = 1.1
    triple_indices = list(itertools.combinations(range(4), 3))
    energy = np.asarray([np.sort(scores[list(ix)]).sum() for ix in triple_indices], dtype=float)
    q = np.exp(energy / tau - logsumexp(energy / tau))
    utilities = np.asarray([0.2, -0.7, 1.1, 0.4])
    q_by_set = {tuple(horse_numbers[j] for j in ix): float(q[k]) for k, ix in enumerate(triple_indices)}
    joint: list[tuple[tuple[int, int, int], tuple[int, int, int], float]] = []
    for set_key, q_value in q_by_set.items():
        set_util = np.asarray([utilities[horse_numbers.index(h)] for h in set_key])
        for order_ix in itertools.permutations(range(3)):
            ordered_horses = tuple(set_key[j] for j in order_ix)
            order_prob = conditional_order_probability(set_util, order_ix)
            joint.append((set_key, ordered_horses, q_value * order_prob))

    recovered_q = {
        set_key: math.fsum(p for key, _, p in joint if key == set_key)
        for set_key in q_by_set
    }
    require(all(math.isclose(recovered_q[k], q_by_set[k], rel_tol=0, abs_tol=ATOL) for k in q_by_set),
            "conditional orders fail to preserve unordered q on synthetic race")
    require(math.isclose(math.fsum(p for _, _, p in joint), 1.0, rel_tol=0, abs_tol=ATOL),
            "synthetic full ordered joint does not sum to one")

    runner_q = {h: math.fsum(qv for set_key, qv in q_by_set.items() if h in set_key) for h in horse_numbers}
    runner_joint = {h: math.fsum(p for set_key, _, p in joint if h in set_key) for h in horse_numbers}
    pair_q = {
        pair: math.fsum(qv for set_key, qv in q_by_set.items() if set(pair).issubset(set_key))
        for pair in itertools.combinations(horse_numbers, 2)
    }
    pair_joint = {
        pair: math.fsum(p for set_key, _, p in joint if set(pair).issubset(set_key))
        for pair in itertools.combinations(horse_numbers, 2)
    }
    require(all(math.isclose(runner_q[h], runner_joint[h], rel_tol=0, abs_tol=ATOL) for h in horse_numbers),
            "synthetic conditional order changed runner Top3 marginals")
    require(all(math.isclose(pair_q[pair], pair_joint[pair], rel_tol=0, abs_tol=ATOL) for pair in pair_q),
            "synthetic conditional order changed q-derived QPL pair events")

    win_events: dict[int, list[float]] = {h: [] for h in horse_numbers}
    qnl_events: dict[tuple[int, int], list[float]] = {
        pair: [] for pair in itertools.combinations(horse_numbers, 2)
    }
    exa_events: dict[tuple[int, int], list[float]] = {
        pair: [] for pair in itertools.permutations(horse_numbers, 2)
    }
    tri_events: dict[tuple[int, int, int], list[float]] = {
        order: [] for order in itertools.permutations(horse_numbers, 3)
    }
    for _, order, probability in joint:
        win_events[order[0]].append(probability)
        qnl_events[tuple(sorted(order[:2]))].append(probability)
        exa_events[order[:2]].append(probability)
        tri_events[order].append(probability)
    win_mass = math.fsum(math.fsum(values) for values in win_events.values())
    qnl_mass = math.fsum(math.fsum(values) for values in qnl_events.values())
    exa_mass = math.fsum(math.fsum(values) for values in exa_events.values())
    tri_mass = math.fsum(math.fsum(values) for values in tri_events.values())
    require(all(math.isclose(mass, 1.0, rel_tol=0, abs_tol=ATOL)
                for mass in (win_mass, qnl_mass, exa_mass, tri_mass)),
            "synthetic derived pool categorical event space does not sum to one")
    return {
        "status": "PASS",
        "scope": "synthetic_math_only_no_source_labels_no_fit",
        "ridge_lambda": 0.01,
        "gradient": {
            "finite_difference": "central, step=1e-6",
            "max_absolute_error": max_abs_error,
            "max_scaled_relative_error": max_rel_error,
            "pass_tolerance": 1e-7,
        },
        "zero_coefficient_order_probability_is_uniform_six_way": True,
        "synthetic_q_mass_preserved_after_conditional_order": True,
        "synthetic_runner_top3_marginals_preserved": True,
        "synthetic_q_derived_qpl_pair_events_preserved": True,
        "synthetic_full_ordered_joint_mass": float(math.fsum(p for _, _, p in joint)),
        "synthetic_pool_event_mass": {"WIN": win_mass, "QNL": qnl_mass, "EXA": exa_mass, "TRI": tri_mass},
    }


def verify_root_proof() -> dict[str, Any]:
    proof = json.loads(checked_path(ROOT_PROOF_PATH).read_text(encoding="utf-8"))
    require(proof.get("status") == "PASS", "independent root source proof is not PASS")
    require(proof.get("training_performed") is False, "root source proof reports training")
    require(int(proof.get("labels_and_horse_keys_match_frozen_api_snapshot", -1)) == 52_155,
            "root source proof label/key count mismatch")
    require(int(proof.get("source_lineage_rows_before_target_cutoff", -1)) == 178_459,
            "root source proof lineage count mismatch")
    return {"status": proof["status"], "training_performed": False,
            "frozen_feature_label_key_rows": 52_155,
            "lineage_rows_before_target_cutoff": 178_459}


def verify_schedule() -> dict[str, Any]:
    receipt = json.loads(checked_path(SCHEDULE_RECEIPT_PATH).read_text(encoding="utf-8"))
    schedule = np.load(checked_path(SCHEDULE_PATH), allow_pickle=False)
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS", "bootstrap schedule was not frozen in advance")
    require(receipt.get("seed") == 20261011 and receipt.get("draws") == 2000 and receipt.get("dates_per_draw") == 269,
            "bootstrap schedule receipt parameters changed")
    require(schedule.shape == (2000, 269) and schedule.dtype == np.int32, "bootstrap schedule shape/dtype mismatch")
    require(schedule.min() >= 0 and schedule.max() < 269, "bootstrap schedule has out-of-range date indices")
    require(sha256_file(checked_path(SCHEDULE_PATH)) == receipt.get("schedule_sha256"),
            "bootstrap schedule differs from its receipt")
    require(receipt.get("numpy_version") == np.__version__, "bootstrap schedule NumPy version mismatch")
    rng = np.random.default_rng(20261011)
    expected = rng.integers(0, 269, size=(2000, 269), endpoint=False, dtype=np.int32)
    require(np.array_equal(schedule, expected), "bootstrap schedule differs from frozen deterministic recipe")
    return {"status": "PASS", "draws": 2000, "dates_per_draw": 269,
            "schedule_sha256": receipt["schedule_sha256"], "seed": 20261011}


def native_q_check(
    evaluation_2026: pd.DataFrame,
    cohort: pd.DataFrame,
    runner_predictions: pd.DataFrame,
) -> dict[str, Any]:
    matched = cohort.loc[cohort["reason"].eq("matched"), ["race_id", "race_date", "field_n"]].copy()
    require(len(matched) == 467 and matched["race_id"].nunique() == 467, "frozen common cohort is not 467 races")
    common_ids = set(matched["race_id"].astype(str))
    eval_common = evaluation_2026.loc[evaluation_2026["race_id"].astype(str).isin(common_ids)].copy()
    require(eval_common["race_id"].nunique() == 467, "2026 evaluation scores miss common cohort races")
    require(set(eval_common["race_id"].astype(str)) == common_ids, "2026 common race IDs differ from fixed cohort")

    cohort_dates = matched.set_index("race_id")["race_date"].astype(str).to_dict()
    cohort_sizes = matched.set_index("race_id")["field_n"].astype(int).to_dict()
    runner_predictions = runner_predictions.loc[runner_predictions["race_id"].astype(str).isin(common_ids)].copy()
    require(len(runner_predictions) == 4_475, "saved runner prediction rows differ from common cohort")
    require(not runner_predictions["api_record_id"].duplicated().any(), "duplicate saved runner prediction ID")
    eval_keys = set(eval_common["api_record_id"].astype(int))
    pred_keys = set(runner_predictions["api_record_id"].astype(int))
    require(eval_keys == pred_keys, "saved runner prediction IDs differ from evaluation score IDs")
    score_join = eval_common[["api_record_id", "race_id", "horse_number", "score"]].merge(
        runner_predictions[["api_record_id", "race_id", "horse_number", "score", "p_top3"]],
        on="api_record_id", how="inner", validate="one_to_one", suffixes=("_eval", "_saved"),
    )
    require(len(score_join) == 4_475, "saved runner prediction join row count mismatch")
    require(score_join["race_id_eval"].eq(score_join["race_id_saved"]).all(), "saved runner prediction race key mismatch")
    require(score_join["horse_number_eval"].eq(score_join["horse_number_saved"]).all(),
            "saved runner prediction horse-number key mismatch")
    require(np.array_equal(score_join["score_eval"].to_numpy(float), score_join["score_saved"].to_numpy(float)),
            "saved runner predictions do not retain original raw scores")
    require(np.isfinite(score_join["p_top3"].to_numpy(float)).all(), "non-finite saved F1_STYLE6 pTop3")

    native = read_parquet(
        TLA_PATH,
        ["race_id", "race_date", "field_n", "horse_no_1", "horse_no_2", "horse_no_3",
         "set_probability", "native_energy_rank"],
    )
    require(len(native) == 50_017, f"native TLA set row count changed: {len(native)}")
    require(set(native["race_id"].astype(str).unique()) == common_ids,
            "native TLA race IDs differ from the fixed common cohort")
    require(not native.duplicated(["race_id", "horse_no_1", "horse_no_2", "horse_no_3"]).any(),
            "duplicate native TLA set key")

    meta = json.loads(checked_path(f"{STYLE_ROOT}/outputs/F1_STYLE6_2026/meta.json").read_text(encoding="utf-8"))
    tau = float(meta["tau"])
    require(math.isfinite(tau) and tau > 0.0, "saved 2026 tau is invalid")
    max_probability_error = 0.0
    marginal_errors: list[float] = []
    race_mass_errors: list[float] = []
    checked_triples = 0
    checked_energy_ranks = 0
    saved_p_top3 = score_join.set_index(["race_id_eval", "horse_number_eval"])["p_top3"].to_dict()

    for race_id, race in eval_common.groupby("race_id", sort=True):
        rid = str(race_id)
        one = race.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
        n = len(one)
        require(n == cohort_sizes[rid] == int(one["field_n"].iloc[0]), f"common field size mismatch in {rid}")
        date_text = str(one["race_date"].iloc[0])
        require(date_text == cohort_dates[rid], f"common race date mismatch in {rid}")
        numbers = one["horse_number"].to_numpy(dtype=int)
        scores = one["score"].to_numpy(dtype=float)
        require(np.isfinite(scores).all() and len(set(numbers.tolist())) == n, f"invalid common roster in {rid}")
        triple_indices = np.asarray(list(itertools.combinations(range(n), 3)), dtype=np.int64)
        energy = np.sort(scores[triple_indices], axis=1).sum(axis=1)
        log_probability = energy / tau - logsumexp(energy / tau)
        probabilities = np.exp(log_probability)
        require(np.isfinite(probabilities).all() and (probabilities > 0.0).all(), f"invalid native q values in {rid}")
        require(math.isclose(math.fsum(float(x) for x in probabilities), 1.0, rel_tol=0, abs_tol=ATOL),
                f"native q does not sum to one in {rid}")
        native_order = np.argsort(-energy, kind="stable")
        energy_rank = np.empty(len(energy), dtype=np.int64)
        energy_rank[native_order] = np.arange(1, len(energy) + 1, dtype=np.int64)

        expected: dict[tuple[int, int, int], tuple[float, int]] = {}
        for ix, triple in enumerate(triple_indices):
            key = tuple(int(numbers[j]) for j in triple)
            expected[key] = (float(probabilities[ix]), int(energy_rank[ix]))
        actual_group = native.loc[native["race_id"].astype(str).eq(rid)]
        require(len(actual_group) == math.comb(n, 3), f"native q set count mismatch in {rid}")
        actual: dict[tuple[int, int, int], tuple[float, int]] = {}
        for row in actual_group.itertuples(index=False):
            key = (int(row.horse_no_1), int(row.horse_no_2), int(row.horse_no_3))
            require(key == tuple(sorted(key)) and len(set(key)) == 3, f"native TLA key is not canonical in {rid}")
            actual[key] = (float(row.set_probability), int(row.native_energy_rank))
        require(set(expected) == set(actual), f"native q exact set keys differ in {rid}")
        for key, (probability, rank) in expected.items():
            saved_probability, saved_rank = actual[key]
            error = abs(probability - saved_probability)
            max_probability_error = max(max_probability_error, error)
            require(error <= ATOL, f"native q set probability differs in {rid} {key}: {error}")
            require(rank == saved_rank, f"native energy ordering differs in {rid} {key}")
            checked_energy_ranks += 1
        checked_triples += len(expected)

        marginal = np.zeros(n, dtype=float)
        for col in range(3):
            np.add.at(marginal, triple_indices[:, col], probabilities)
        for j, horse_number in enumerate(numbers):
            saved = float(saved_p_top3[(rid, int(horse_number))])
            error = abs(float(marginal[j]) - saved)
            marginal_errors.append(error)
            require(error <= ATOL, f"native q marginal differs from saved pTop3 in {rid} horse {horse_number}")
        pair_masses: dict[tuple[int, int], list[float]] = {
            pair: [] for pair in itertools.combinations(numbers.tolist(), 2)
        }
        for triple_ix, probability in zip(triple_indices, probabilities, strict=True):
            triple_numbers = [int(numbers[j]) for j in triple_ix]
            for pair in itertools.combinations(triple_numbers, 2):
                pair_masses[pair].append(float(probability))
        pair_probability_sum = math.fsum(math.fsum(values) for values in pair_masses.values())
        require(math.isclose(pair_probability_sum, 3.0, rel_tol=0, abs_tol=ATOL),
                f"native q-derived pair-in-Top3 mass sum is not 3 in {rid}")
        race_mass_errors.append(abs(math.fsum(float(x) for x in probabilities) - 1.0))

    return {
        "status": "PASS",
        "common_races": 467,
        "common_runners": 4_475,
        "native_exact_set_rows": int(len(native)),
        "reconstructed_q_set_rows": checked_triples,
        "saved_tau": tau,
        "native_energy_rank_exact_match": checked_energy_ranks == len(native),
        "max_abs_set_probability_difference": max_probability_error,
        "max_abs_saved_p_top3_marginal_difference": max(marginal_errors),
        "max_abs_race_q_mass_error": max(race_mass_errors),
        "q_derived_pair_mass_sum_is_three_every_race": True,
        "raw_scores_and_p_top3_source_rows_match_frozen_evaluation": True,
    }


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.exists() and not path.is_symlink(), f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)


def main() -> int:
    try:
        require(ROOT.exists() and STUDY.is_relative_to(ROOT), "unexpected study path")
        require(not STUDY.is_symlink(), "study directory must not be a symlink")
        for filename in ("SOURCE_PREFLIGHT.json", "GRADIENT_CHECK.json", "PREFIT_SOURCE_LOCK.json"):
            require(not (OUT / filename).exists(), f"refusing to overwrite existing {filename}")

        verified_sources = verify_source_hashes()
        features = load_features()
        lineage = verify_lineage(features)
        folds: dict[str, Any] = {}
        eval_2026: pd.DataFrame | None = None
        eval_date_race_rows: list[pd.DataFrame] = []
        for year in (2024, 2025, 2026):
            _, evaluation, fold = check_fold(year, features)
            folds[str(year)] = fold
            eval_date_race_rows.append(evaluation[["race_id", "race_date", "year"]].drop_duplicates("race_id"))
            if year == 2026:
                eval_2026 = evaluation
        require(eval_2026 is not None, "2026 evaluation fold missing")
        eval_summary = pd.concat(eval_date_race_rows, ignore_index=True)
        dates = sorted(eval_summary["race_date"].drop_duplicates().map(str).tolist())
        require(len(eval_summary) == 1_779, "evaluation race total changed")
        require(len(dates) == 269, "evaluation date count changed")

        cohort = pd.read_csv(checked_path(COHORT_PATH), dtype={"race_id": "string"})
        runner_preds = read_parquet(
            RUNNER_PRED_PATH,
            ["api_record_id", "race_id", "year", "horse_number", "field_n", "variant", "score", "p_top3"],
        )
        runner_preds = runner_preds.loc[
            runner_preds["variant"].eq("F1_STYLE6") & runner_preds["year"].eq(2026)
        ].copy()

        q_report = native_q_check(eval_2026, cohort, runner_preds)
        schedule_report = verify_schedule()
        root_proof = verify_root_proof()
        gradient_report = synthetic_gradient_and_coherence_check()

        preflight = {
            "status": "PASS",
            "study": "20261017_conditional_order_head_v1",
            "scope": "outcome_free_source_structure_and_synthetic_math_preflight",
            "source_sha256_and_bytes": verified_sources,
            "feature_cohort": {
                "rows": int(len(features)),
                "races": int(features["race_id"].nunique()),
                "evaluation_rows": 17_412,
                "evaluation_races": 1_779,
                "evaluation_dates": len(dates),
                "evaluation_date_min": dates[0],
                "evaluation_date_max": dates[-1],
                "2026_partial_through": "2026-09-19",
                "input_feature_names": ["saved_raw_score", *STYLE_COLUMNS,
                                         *(f"missing:{col}" for col in STYLE_MEANS)],
                "input_feature_count": 10,
                "missingness_by_feature": {
                    col: {"valid_rows": int(features[col].notna().sum()),
                          "missing_rows": int(features[col].isna().sum())}
                    for col in STYLE_MEANS
                },
                "mean_count_missingness_pairs_valid": True,
                "race_rosters_and_finish_positions_complete": True,
                "feature_history_cutoff_is_t2": True,
            },
            "lineage": lineage,
            "folds": folds,
            "native_q_preservation": q_report,
            "date_bootstrap_schedule": schedule_report,
            "independent_root_source_proof": root_proof,
            "fit_performed": False,
            "calibration_performed": False,
            "evaluation_outcome_metrics_computed": False,
            "market_odds_read_for_selection": False,
            "database_or_network_access": False,
            "registry_or_production_artifact_changed": False,
        }
        gradient_report["study"] = "20261017_conditional_order_head_v1"

        plan_path = checked_path(f"{STUDY_REL}/PLAN.md")
        contract_path = checked_path(f"{STUDY_REL}/INPUT_CONTRACT.md")
        script_path = checked_path(f"{STUDY_REL}/preflight.py")
        write_json_once(OUT / "GRADIENT_CHECK.json", gradient_report)
        write_json_once(OUT / "SOURCE_PREFLIGHT.json", preflight)
        lock = {
            "status": "PREFIT_SOURCE_LOCKED_ROOT_REVIEW_PENDING",
            "study": "20261017_conditional_order_head_v1",
            "inputs": verified_sources,
            "design_files": {
                "PLAN.md": {"sha256": sha256_file(plan_path), "bytes": plan_path.stat().st_size},
                "INPUT_CONTRACT.md": {"sha256": sha256_file(contract_path), "bytes": contract_path.stat().st_size},
                "preflight.py": {"sha256": sha256_file(script_path), "bytes": script_path.stat().st_size},
            },
            "preflight_outputs": {
                "SOURCE_PREFLIGHT.json": {"sha256": sha256_file(OUT / "SOURCE_PREFLIGHT.json"),
                                           "bytes": (OUT / "SOURCE_PREFLIGHT.json").stat().st_size},
                "GRADIENT_CHECK.json": {"sha256": sha256_file(OUT / "GRADIENT_CHECK.json"),
                                         "bytes": (OUT / "GRADIENT_CHECK.json").stat().st_size},
            },
            "model_or_calibration_fit_performed": False,
            "outcome_metrics_computed": False,
        }
        write_json_once(OUT / "PREFIT_SOURCE_LOCK.json", lock)
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        print(json.dumps(lock, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"PREFLIGHT_FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
