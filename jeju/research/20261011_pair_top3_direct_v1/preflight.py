#!/usr/bin/env python3
"""Outcome-free structural preflight for the locked Jeju direct-pair study.

This program validates immutable source hashes, source schemas, row/race keys,
historical T-2 metadata, H1/H2 dates, label-count invariants, selector parity,
and saved joint-policy reconstruction. It deliberately does not fit a model,
score selected pairs against labels, or compute performance metrics.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
OUT = STUDY / "outputs"
STUDY_REL = "jeju/research/20261011_pair_top3_direct_v1"
STUDY_LOCK_REL = f"{STUDY_REL}/PREFLIGHT_SOURCE_LOCK.json"

SOURCE_HASHES = {
    "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet": "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/calibration_scores.parquet": "360cc559b1ab19cde177e0bb23206fd36f123b707714fbcb63547fdb9bed05b2",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/calibration_scores.parquet": "b092d28f0cbd45dd3a184a4a8ab89e9b5b5a78eef8068c45fda3de92734a3755",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/calibration_scores.parquet": "6a7ed320e59add698faafd9008c882dc8a83a84f9198094371525f4c4ebd37d8",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/evaluation_scores.parquet": "b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/evaluation_scores.parquet": "45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/evaluation_scores.parquet": "0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/meta.json": "15acbf959654da82d2240027e7b7d768bb9226af18395dac9ec92a68a4471726",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/meta.json": "23c4b0684477f34fbb2e99c22d0037cd903d5459db369f084773ec25c640f4a8",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/meta.json": "e9dbfe5226571cb29e34b352a4ad8808a735d70929e66b42efb41b3e807ff06d",
    "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv": "0e6a01607164a7cb54fbbb5fb445e975ea9fbadad21d4e7a842adfc915616a09",
    "jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet": "13409e65353c0cb6dab14df97317cce24de913056ae464ee3524520759de681c",
    "jeju/research/20261010_pair_axis_v1/outputs/per_race_metrics.csv": "78b75895ddd82a72a406aa2b9d4fa889946d25e6a8d8c8f50069aac286b267c1",
    "jeju/research/20261010_style_history_ablation_v1/ARTIFACT_MANIFEST.json": "6afc0e8f73ec086052fad4cde4d7edcd62fdf1bbc782108da89732dc3a5b4a4e",
    "jeju/research/20261010_joint_relationship_v1/ARTIFACT_MANIFEST.json": "d0d1a749afb6a6f894de1bb4263c9d67dd1e3b2d1a35bf1b5fd38d8948c656b0",
    "jeju/research/20261010_pair_axis_v1/PLAN.md": "fcecdd848f3e4e46cc9c41d9cb4f86b1cf6ae02a0e4ceef196b422b40e102d4a",
    "jeju/research/20261010_pair_axis_v1/outputs/ARTIFACT_MANIFEST.json": "0f82c19c8d3dd318e984d860bff098738e27429c7006f7acdd9312d75f01a0ad",
    "jeju/research/20261010_style_history_ablation_v1/CONTRACT.md": "c10aac8f6faa6e841afd9ef829bfa0b29ada2dceabcbb5405fdfad9c12536bf9",
}

FEATURE_PATH = "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
MARGINAL_PATH = "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv"
TRIPLES_PATH = "jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet"
PAIR_AXIS_PATH = "jeju/research/20261010_pair_axis_v1/outputs/per_race_metrics.csv"

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
FEATURE_COLUMNS = [
    "api_record_id",
    "race_id",
    "race_date",
    "year",
    "horse_id",
    "horse_number",
    "field_n",
    "finish_position",
    "history_cutoff",
    "latest_history_date",
    *STYLE_COUNTS,
    *STYLE_MEANS,
]
SCORE_COLUMNS = ["api_record_id", "score"]
MARGINAL_COLUMNS = [
    "api_record_id",
    "race_id",
    "horse_number",
    "saved_f1_style6_p_top3",
    "candidate_joint_marginal",
]
TRIPLE_COLUMNS = [
    "race_id",
    "race_date",
    "evaluation_year",
    "distance_m",
    "arm",
    "triple_numbers",
    "probability",
]
PAIR_AXIS_COLUMNS = [
    "race_id",
    "race_date",
    "evaluation_year",
    "arm",
    "policy",
    "budget_k",
    "axis_horses",
    "axis_probability",
]
EXPECTED_H1_H2_RACES = {2024: (312, 336), 2025: (326, 311), 2026: (329, 325)}
EXPECTED_EVAL = {
    2024: (6329, 637, "2024-01-05", "2024-12-28"),
    2025: (6410, 654, "2025-01-03", "2025-12-27"),
    2026: (4673, 488, "2026-01-02", "2026-09-19"),
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
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_hashes() -> dict[str, str]:
    actual: dict[str, str] = {}
    for relative, expected in SOURCE_HASHES.items():
        digest = sha256_file(checked_path(relative))
        require(digest == expected, f"SHA-256 mismatch for {relative}: {digest}")
        actual[relative] = digest
    return actual


def verify_study_source_lock() -> tuple[dict[str, str], str]:
    lock_path = checked_path(STUDY_LOCK_REL)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    require(lock.get("study") == "20261011_pair_top3_direct_v1", "wrong study source lock")
    frozen = lock.get("frozen_artifacts")
    require(isinstance(frozen, dict), "frozen_artifacts missing from study source lock")
    expected_paths = {
        f"{STUDY_REL}/PLAN.md",
        f"{STUDY_REL}/INPUT_CONTRACT.md",
        f"{STUDY_REL}/AMENDMENT.md",
        f"{STUDY_REL}/core.py",
        f"{STUDY_REL}/preflight.py",
    }
    require(set(frozen) == expected_paths, "study source lock artifact set mismatch")
    actual: dict[str, str] = {}
    for relative, expected in frozen.items():
        digest = sha256_file(checked_path(relative))
        require(digest == expected, f"study artifact hash mismatch for {relative}: {digest}")
        actual[relative] = digest
    pinned_inputs = lock.get("source_inputs")
    require(pinned_inputs == SOURCE_HASHES, "study source lock inputs differ from preflight source pins")
    return actual, sha256_file(lock_path)


def parquet_columns(relative: str, expected: list[str]) -> pd.DataFrame:
    path = checked_path(relative)
    schema = pq.ParquetFile(path).schema_arrow
    names = schema.names
    require(set(expected).issubset(names), f"missing columns in {relative}: {sorted(set(expected)-set(names))}")
    return pq.read_table(path, columns=expected).to_pandas()


def read_score(relative: str) -> pd.DataFrame:
    path = checked_path(relative)
    schema = pq.ParquetFile(path).schema_arrow
    require(schema.names == SCORE_COLUMNS, f"score schema mismatch in {relative}: {schema.names}")
    require(str(schema.field("api_record_id").type) == "int64", f"api_record_id must be int64 in {relative}")
    require(str(schema.field("score").type) == "double", f"score must be double in {relative}")
    df = pq.read_table(path, columns=SCORE_COLUMNS).to_pandas()
    require(not df["api_record_id"].duplicated().any(), f"duplicate score key in {relative}")
    require(np.isfinite(df["score"].to_numpy(dtype=float)).all(), f"non-finite score in {relative}")
    return df


def parse_date(value: Any, field: str) -> date:
    parsed = pd.to_datetime(value, errors="coerce")
    require(not pd.isna(parsed), f"invalid {field}: {value!r}")
    return parsed.date()


def canonical_pair(numbers: tuple[int, int] | list[int]) -> tuple[int, int]:
    require(len(numbers) == 2, f"expected a pair, got {numbers!r}")
    a, b = sorted(int(x) for x in numbers)
    require(a != b, f"pair contains duplicate horse number: {numbers!r}")
    return (a, b)


def parse_pair_text(value: Any) -> tuple[int, int]:
    text = str(value).strip()
    found = re.fullmatch(r"\s*\[?\s*(\d+)\s*,\s*(\d+)\s*\]?\s*", text)
    require(found is not None, f"invalid saved pair encoding: {value!r}")
    return canonical_pair((int(found.group(1)), int(found.group(2))))


def parse_triple_text(value: Any) -> tuple[int, int, int]:
    text = str(value).strip()
    found = re.fullmatch(r"\s*\[?\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]?\s*", text)
    require(found is not None, f"invalid triple encoding: {value!r}")
    triple = tuple(sorted(int(found.group(i)) for i in (1, 2, 3)))
    require(len(set(triple)) == 3, f"duplicate number in saved triple: {value!r}")
    return triple


def selected_pair_by_value(
    items: list[tuple[int, float]], *, descending: bool = True
) -> tuple[int, int]:
    require(len(items) >= 2, "not enough horses to choose a pair")
    if descending:
        ordered = sorted(items, key=lambda item: (-float(item[1]), int(item[0])))
    else:
        ordered = sorted(items, key=lambda item: (float(item[1]), int(item[0])))
    return canonical_pair((ordered[0][0], ordered[1][0]))


def exact_argmax_pair(masses: dict[tuple[int, int], float]) -> tuple[int, int]:
    require(bool(masses), "cannot select from an empty pair-mass map")
    maximum = max(masses.values())
    return min(pair for pair, value in masses.items() if value == maximum)


def validate_feature_rows(df: pd.DataFrame, label: str) -> dict[str, int]:
    require(not df["api_record_id"].isna().any(), f"null api_record_id in {label}")
    require(not df["api_record_id"].duplicated().any(), f"duplicate api_record_id in {label}")
    require(not df[["race_id", "horse_number"]].duplicated().any(), f"duplicate runner key in {label}")
    require(not df[["race_id", "horse_id"]].duplicated().any(), f"duplicate horse id in race in {label}")
    require(df["race_id"].notna().all() and df["horse_id"].notna().all(), f"null race/horse key in {label}")

    pair_races = 0
    positive_pair_total = 0
    for race_id, race in df.groupby("race_id", sort=True):
        require(race["race_date"].nunique(dropna=False) == 1, f"race date changes within {race_id}")
        require(race["year"].nunique(dropna=False) == 1, f"calendar year changes within {race_id}")
        require(race["field_n"].nunique(dropna=False) == 1, f"field_n changes within {race_id}")
        n = int(race["field_n"].iloc[0])
        require(n >= 4, f"field_n < 4 in {race_id}")
        numbers = [int(x) for x in race["horse_number"].tolist()]
        require(len(numbers) == n and len(set(numbers)) == n, f"roster/field_n mismatch in {race_id}")
        positions = [int(x) for x in race["finish_position"].tolist()]
        require(len(set(positions)) == len(positions), f"duplicate finish_position in {race_id}")
        require(sorted(positions) == list(range(1, n + 1)), f"finish positions are not a complete 1..N permutation in {race_id}")
        require(sorted(x for x in positions if x <= 3) == [1, 2, 3], f"Top3 roster invalid in {race_id}")

        finish_by_number = {
            int(row.horse_number): int(row.finish_position)
            for row in race[["horse_number", "finish_position"]].itertuples(index=False)
        }
        enumerated = list(itertools.combinations(sorted(numbers), 2))
        require(len(enumerated) == math.comb(n, 2), f"C(N,2) enumeration mismatch in {race_id}")
        positive_pairs = sum(
            1
            for a, b in enumerated
            if finish_by_number[a] <= 3 and finish_by_number[b] <= 3
        )
        require(positive_pairs == 3, f"expected exactly 3 positive pairs in {race_id}")
        pair_races += 1
        positive_pair_total += positive_pairs

    return {"races": pair_races, "positive_pairs": positive_pair_total}


def validate_style_missingness(df: pd.DataFrame, label: str) -> None:
    for mean_col, count_col in zip(STYLE_MEANS, STYLE_COUNTS, strict=True):
        counts = pd.to_numeric(df[count_col], errors="coerce")
        require(counts.notna().all(), f"null {count_col} in {label}")
        count_values = counts.to_numpy(dtype=float)
        require(np.isfinite(count_values).all(), f"non-finite {count_col} in {label}")
        require(np.equal(count_values, np.floor(count_values)).all(), f"non-integer {count_col} in {label}")
        require(((count_values >= 0) & (count_values <= 5)).all(), f"out-of-range {count_col} in {label}")
        means = pd.to_numeric(df[mean_col], errors="coerce")
        mean_values = means.to_numpy(dtype=float)
        missing = means.isna().to_numpy()
        require(np.isfinite(mean_values[~missing]).all(), f"non-finite {mean_col} in {label}")
        require((missing == (count_values == 0)).all(), f"mean/count missingness mismatch: {mean_col}/{count_col} in {label}")


def validate_history_t2(df: pd.DataFrame, label: str) -> dict[str, int]:
    race_dates = pd.to_datetime(df["race_date"], errors="coerce").dt.date
    cutoffs = pd.to_datetime(df["history_cutoff"], errors="coerce").dt.date
    latest_source = df["latest_history_date"]
    latest_parsed = pd.to_datetime(latest_source, errors="coerce")
    latest_nonnull = latest_source.notna()
    require(latest_parsed[latest_nonnull].notna().all(), f"invalid non-null latest_history_date in {label}")
    latest = latest_parsed.dt.date
    require(race_dates.notna().all(), f"invalid race_date in {label}")
    require(cutoffs.notna().all(), f"null/invalid history_cutoff in {label}")
    expected = race_dates.map(lambda d: d - timedelta(days=2))
    require((cutoffs == expected).all(), f"history_cutoff is not race date T-2 in {label}")
    has_latest = latest.notna()
    require((latest[has_latest] <= cutoffs[has_latest]).all(), f"latest_history_date exceeds T-2 in {label}")
    return {"rows": int(len(df)), "history_rows_with_latest_date": int(has_latest.sum())}


def q0_max_pair(score_rows: pd.DataFrame) -> tuple[int, int]:
    ordered = score_rows.sort_values("horse_number", kind="mergesort")
    numbers = [int(x) for x in ordered["horse_number"].tolist()]
    scores = [float(x) for x in ordered["score"].tolist()]
    require(len(numbers) >= 4 and len(numbers) == len(set(numbers)), "invalid roster for q0")
    triples = list(itertools.combinations(range(len(numbers)), 3))
    energies = [math.fsum(scores[index] for index in triple) for triple in triples]
    require(all(math.isfinite(x) for x in energies), "non-finite q0 triple energy")
    max_energy = max(energies)
    unnormalized = [math.exp(value - max_energy) for value in energies]
    denominator = math.fsum(unnormalized)
    require(math.isfinite(denominator) and denominator > 0.0, "invalid q0 normalizer")
    triple_probabilities = [weight / denominator for weight in unnormalized]

    pair_terms: dict[tuple[int, int], list[float]] = defaultdict(list)
    for triple_indexes, probability in zip(triples, triple_probabilities, strict=True):
        triple_numbers = [numbers[index] for index in triple_indexes]
        for pair in itertools.combinations(triple_numbers, 2):
            pair_terms[pair].append(probability)
    pair_mass = {pair: math.fsum(values) for pair, values in pair_terms.items()}
    require(len(pair_mass) == math.comb(len(numbers), 2), "q0 pair coverage mismatch")
    require(all(math.isfinite(p) and 0.0 < p < 1.0 for p in pair_mass.values()), "q0 pair probability outside (0,1)")
    return exact_argmax_pair(pair_mass)


def add_scores(features: pd.DataFrame, scores: pd.DataFrame, label: str) -> pd.DataFrame:
    require(not scores["api_record_id"].duplicated().any(), f"duplicate score ids for {label}")
    feature_ids = set(features["api_record_id"].astype(int))
    score_ids = set(scores["api_record_id"].astype(int))
    require(score_ids == feature_ids, f"score/feature key-set mismatch for {label}")
    merged = features.merge(scores, on="api_record_id", how="inner", validate="one_to_one")
    require(len(merged) == len(features) == len(scores), f"score/feature row count mismatch for {label}")
    require(np.isfinite(merged["score"].to_numpy(dtype=float)).all(), f"non-finite score after join for {label}")
    return merged


def check_fold(
    year: int,
    features: pd.DataFrame,
    expected_score_hashes: dict[str, str],
    reports: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    folder = f"jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_{year}"
    meta_path = f"{folder}/meta.json"
    meta = json.loads(checked_path(meta_path).read_text(encoding="utf-8"))
    cal_path = f"{folder}/calibration_scores.parquet"
    eval_path = f"{folder}/evaluation_scores.parquet"
    cal_scores = read_score(cal_path)
    eval_scores = read_score(eval_path)

    calibration_year = year - 1
    cal_features = features.loc[features["year"].eq(calibration_year)].copy()
    eval_features = features.loc[features["year"].eq(year)].copy()
    cal_joined = add_scores(cal_features, cal_scores, f"{year} calibration")
    eval_joined = add_scores(eval_features, eval_scores, f"{year} evaluation")

    require(int(meta["evaluation_year"]) == year, f"wrong evaluation_year in {meta_path}")
    require(len(cal_joined) == int(meta["calibration_rows"]), f"calibration row count mismatch in {meta_path}")
    require(cal_joined["race_id"].nunique() == int(meta["calibration_races"]), f"calibration race count mismatch in {meta_path}")
    eval_rows, eval_races, eval_min, eval_max = EXPECTED_EVAL[year]
    require(len(eval_joined) == eval_rows == int(meta["evaluation_rows"]), f"evaluation row count mismatch for {year}")
    require(eval_joined["race_id"].nunique() == eval_races == int(meta["evaluation_races"]), f"evaluation race count mismatch for {year}")
    dates = pd.to_datetime(eval_joined["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    require(dates.min() == eval_min == meta["evaluation_min"], f"evaluation minimum date mismatch for {year}")
    require(dates.max() == eval_max == meta["evaluation_max"], f"evaluation maximum date mismatch for {year}")
    require(set(cal_joined["year"].unique()) == {calibration_year}, f"wrong calibration year IDs in {year}")
    require(set(eval_joined["year"].unique()) == {year}, f"wrong evaluation year IDs in {year}")

    refit_max = parse_date(meta["refit_max"], f"{year} refit_max")
    cal_joined["_date"] = pd.to_datetime(cal_joined["race_date"], errors="coerce").dt.date
    eval_joined["_date"] = pd.to_datetime(eval_joined["race_date"], errors="coerce").dt.date
    h1_candidates = cal_joined.loc[cal_joined["_date"].map(lambda d: d.month <= 6)].copy()
    h2 = cal_joined.loc[cal_joined["_date"].map(lambda d: d.month >= 7)].copy()
    require(len(h1_candidates) > 0 and len(h2) > 0, f"empty H1/H2 for {year}")
    first_h2 = min(h2["_date"])
    last_h1_allowed = first_h2 - timedelta(days=2)
    h1 = h1_candidates.loc[h1_candidates["_date"] <= last_h1_allowed].copy()
    purged = h1_candidates.loc[h1_candidates["_date"] > last_h1_allowed].copy()
    first_h1 = min(h1["_date"])
    last_h1 = max(h1["_date"])
    last_h2 = max(h2["_date"])
    first_eval = min(eval_joined["_date"])
    require(refit_max <= first_h1 - timedelta(days=2), f"refit T-2 boundary failed for {year}")
    require(last_h1 <= first_h2 - timedelta(days=2), f"H1/H2 T-2 boundary failed for {year}")
    require(last_h2 <= first_eval - timedelta(days=2), f"H2/evaluation T-2 boundary failed for {year}")

    expected_h1, expected_h2 = EXPECTED_H1_H2_RACES[year]
    h1_races, h2_races = h1["race_id"].nunique(), h2["race_id"].nunique()
    require((h1_races, h2_races) == (expected_h1, expected_h2), f"H1/H2 race inventory mismatch for {year}: {(h1_races,h2_races)}")
    for split_name, split in (("H1", h1), ("H2", h2), ("evaluation", eval_joined)):
        validate_style_missingness(split, f"{year} {split_name}")
        label_inventory = validate_feature_rows(split, f"{year} {split_name}")
        reports[f"{year}_{split_name.lower()}_label_inventory"] = label_inventory
    reports[f"{year}_split"] = {
        "calibration_year": calibration_year,
        "refit_max": refit_max.isoformat(),
        "h1_races": int(h1_races),
        "h1_dates": [first_h1.isoformat(), last_h1.isoformat()],
        "h1_first_allowed_by_refit": (refit_max + timedelta(days=2)).isoformat(),
        "h1_purged_races": int(purged["race_id"].nunique()),
        "h1_purged_dates": sorted(pd.Series(purged["_date"]).dropna().astype(str).unique().tolist()),
        "h2_races": int(h2_races),
        "h2_dates": [min(h2["_date"]).isoformat(), last_h2.isoformat()],
        "evaluation_races": int(eval_races),
        "evaluation_dates": [eval_min, eval_max],
        "calibration_score_sha256": expected_score_hashes[cal_path],
        "evaluation_score_sha256": expected_score_hashes[eval_path],
    }
    return eval_joined, cal_joined


def validate_p0_and_raw_parity(eval_frames: dict[int, pd.DataFrame]) -> dict[str, int]:
    checked = 0
    mismatches: list[dict[str, Any]] = []
    for year, df in eval_frames.items():
        for race_id, race in df.groupby("race_id", sort=True):
            raw_pair = selected_pair_by_value(
                [(int(row.horse_number), float(row.score)) for row in race.itertuples(index=False)]
            )
            p0_pair = q0_max_pair(race[["horse_number", "score"]])
            checked += 1
            if p0_pair != raw_pair:
                mismatches.append({"year": year, "race_id": str(race_id), "raw_pair": raw_pair, "p0_pair": p0_pair})
    require(not mismatches, f"p0 maximum-pair/raw-score top2 parity failed: {mismatches[:5]}")
    return {"races_checked": checked, "mismatches": 0}


def validate_saved_style6_parity(
    eval_frames: dict[int, pd.DataFrame], marginals: pd.DataFrame
) -> dict[str, Any]:
    eval_all = pd.concat(eval_frames.values(), ignore_index=True)
    require(not marginals["api_record_id"].duplicated().any(), "duplicate runner marginal api_record_id")
    require(not marginals[["race_id", "horse_number"]].duplicated().any(), "duplicate runner marginal race/number key")
    require(len(marginals) == len(eval_all), "runner marginal rows differ from evaluation cohort")
    require(set(marginals["api_record_id"].astype(int)) == set(eval_all["api_record_id"].astype(int)), "runner marginal ID set differs from evaluation cohort")
    joined = eval_all.merge(marginals, on=["api_record_id", "race_id", "horse_number"], how="inner", validate="one_to_one")
    require(len(joined) == len(eval_all), "runner marginal key join mismatch")
    scores = joined[["race_id", "horse_number", "score", "saved_f1_style6_p_top3"]].copy()
    require(np.isfinite(scores["saved_f1_style6_p_top3"].to_numpy(dtype=float)).all(), "non-finite saved F1_STYLE6 probability")
    mismatch_failures = []
    tie_diagnostics: list[dict[str, Any]] = []
    checked = 0
    for race_id, race in scores.groupby("race_id", sort=True):
        score_items = [(int(row.horse_number), float(row.score)) for row in race.itertuples(index=False)]
        raw_pair = selected_pair_by_value(score_items)
        probability_pair = selected_pair_by_value(
            [(int(row.horse_number), float(row.saved_f1_style6_p_top3)) for row in race.itertuples(index=False)]
        )
        checked += 1
        if raw_pair != probability_pair:
            ranked_scores = sorted(score_items, key=lambda item: (-item[1], item[0]))
            boundary_score = ranked_scores[1][1]
            boundary_tied = ranked_scores[1][1] == ranked_scores[2][1]
            score_by_number = dict(score_items)
            probability_items = [
                (int(row.horse_number), float(row.saved_f1_style6_p_top3))
                for row in race.itertuples(index=False)
            ]
            ranked_probabilities = sorted(probability_items, key=lambda item: (-item[1], item[0]))
            if not boundary_tied:
                mismatch_failures.append({"race_id": str(race_id), "raw_pair": raw_pair, "probability_pair": probability_pair})
                continue
            selected_scores = [score_by_number[number] for number in probability_pair]
            high_score_horses = {number for number, score in score_items if score > boundary_score}
            if not all(score >= boundary_score for score in selected_scores) or not high_score_horses.issubset(set(probability_pair)):
                mismatch_failures.append({"race_id": str(race_id), "raw_pair": raw_pair, "probability_pair": probability_pair, "reason": "outside raw score boundary tie block"})
                continue
            tie_diagnostics.append({
                "race_id": str(race_id),
                "raw_score_pair": list(raw_pair),
                "saved_probability_pair": list(probability_pair),
                "rank2_rank3_score_exact_tie": True,
                "boundary_score": boundary_score,
                "saved_probability_rank2_rank3_gap": float(ranked_probabilities[1][1] - ranked_probabilities[2][1]),
            })
    require(not mismatch_failures, f"saved F1_STYLE6 probability/raw-score parity failed outside allowed tie block: {mismatch_failures[:5]}")
    require(len(tie_diagnostics) == 6, f"expected six saved-probability ULP tie exceptions, found {len(tie_diagnostics)}")
    return {"races_checked": checked, "mismatches_outside_exact_boundary_ties": 0, "allowed_exact_boundary_ties": tie_diagnostics}


def reconstruct_joint_policies(
    eval_frames: dict[int, pd.DataFrame], marginals: pd.DataFrame
) -> dict[str, int]:
    triples = parquet_columns(TRIPLES_PATH, TRIPLE_COLUMNS)
    require(set(triples["arm"].dropna().unique()) == {"candidate", "matched_baseline"}, "unexpected joint arms")
    require(np.isfinite(triples["probability"].to_numpy(dtype=float)).all(), "non-finite joint triple probability")
    require((triples["probability"] > 0).all(), "non-positive joint triple probability")
    require((triples["distance_m"] > 0).all(), "invalid report-only distance_m")
    race_rosters = {
        str(race_id): set(int(x) for x in race["horse_number"].tolist())
        for df in eval_frames.values()
        for race_id, race in df.groupby("race_id", sort=True)
    }
    eval_race_meta = {
        str(race_id): (str(race["race_date"].iloc[0]), int(race["year"].iloc[0]))
        for df in eval_frames.values()
        for race_id, race in df.groupby("race_id", sort=True)
    }
    require(triples["race_id"].astype(str).isin(race_rosters).all(), "joint triples contain race outside evaluation cohort")
    require(triples["race_id"].nunique() == len(race_rosters), "joint triple race cohort mismatch")
    require(len(triples) > 0, "empty joint triples source")

    axis = pd.read_csv(checked_path(PAIR_AXIS_PATH), usecols=PAIR_AXIS_COLUMNS)
    axis = axis.loc[
        axis["budget_k"].eq(3)
        & (
            axis["policy"].eq("maximum_joint_pair")
            | (axis["arm"].eq("candidate") & axis["policy"].eq("top_two_marginal_pair"))
        )
    ].copy()
    require(not axis.duplicated(["race_id", "arm", "policy", "budget_k"]).any(), "duplicate saved pair-axis policy row")
    expected_axis_keys = {
        (race_id, arm, policy, 3)
        for race_id in race_rosters
        for arm, policy in (
            ("candidate", "top_two_marginal_pair"),
            ("candidate", "maximum_joint_pair"),
            ("matched_baseline", "maximum_joint_pair"),
        )
    }
    actual_axis_keys = set(
        (str(row.race_id), str(row.arm), str(row.policy), int(row.budget_k))
        for row in axis.itertuples(index=False)
    )
    require(actual_axis_keys == expected_axis_keys, "saved pair-axis selector rows do not match locked race/policy set")
    axis_lookup = {
        (str(row.race_id), str(row.arm), str(row.policy), int(row.budget_k)): row
        for row in axis.itertuples(index=False)
    }
    for axis_key, row in axis_lookup.items():
        race_id = axis_key[0]
        expected_date, expected_year = eval_race_meta[race_id]
        require(str(row.race_date) == expected_date, f"saved pair-axis race_date mismatch for {race_id}")
        require(int(row.evaluation_year) == expected_year, f"saved pair-axis evaluation_year mismatch for {race_id}")

    marginal_lookup = marginals.set_index(["race_id", "horse_number"])
    candidate_top2 = 0
    candidate_max = 0
    matched_max = 0
    triple_rows_seen = 0
    distance_by_race_arm: dict[tuple[str, str], int] = {}

    for (race_id_raw, arm), group in triples.groupby(["race_id", "arm"], sort=True):
        race_id = str(race_id_raw)
        roster = race_rosters[race_id]
        expected_date, expected_year = eval_race_meta[race_id]
        require(group["race_date"].astype(str).eq(expected_date).all(), f"triple race_date mismatch: {race_id}")
        require(group["evaluation_year"].astype(int).eq(expected_year).all(), f"triple evaluation year mismatch: {race_id}")
        require(group["distance_m"].nunique(dropna=False) == 1, f"triple distance changes within race: {race_id}")
        distance = int(group["distance_m"].iloc[0])
        distance_by_race_arm[(race_id, str(arm))] = distance
        parsed = [(parse_triple_text(value), float(prob)) for value, prob in zip(group["triple_numbers"], group["probability"], strict=True)]
        parsed.sort(key=lambda item: item[0])
        triple_keys = [triple for triple, _ in parsed]
        expected_triples = list(itertools.combinations(sorted(roster), 3))
        require(triple_keys == expected_triples, f"joint triple enumeration mismatch in {race_id}/{arm}")
        probability_sum = math.fsum(prob for _, prob in parsed)
        require(math.isclose(probability_sum, 1.0, rel_tol=0.0, abs_tol=1e-12), f"joint probabilities do not sum to 1 in {race_id}/{arm}")
        pair_terms: dict[tuple[int, int], list[float]] = defaultdict(list)
        horse_terms: dict[int, list[float]] = defaultdict(list)
        for triple, probability in parsed:
            for pair in itertools.combinations(triple, 2):
                pair_terms[pair].append(probability)
            for number in triple:
                horse_terms[number].append(probability)
        pair_mass = {pair: math.fsum(values) for pair, values in pair_terms.items()}
        require(len(pair_mass) == math.comb(len(roster), 2), f"joint pair coverage mismatch in {race_id}/{arm}")
        selected_max = exact_argmax_pair(pair_mass)
        policy = "maximum_joint_pair"
        axis_row = axis_lookup[(race_id, str(arm), policy, 3)]
        saved_pair = parse_pair_text(axis_row.axis_horses)
        require(saved_pair == selected_max, f"saved {arm} maximum_joint_pair mismatch in {race_id}")
        require(math.isclose(float(axis_row.axis_probability), pair_mass[selected_max], rel_tol=0.0, abs_tol=1e-12), f"saved {arm} maximum-pair mass mismatch in {race_id}")
        if arm == "candidate":
            candidate_max += 1
            marginal_values = []
            for number in sorted(roster):
                key = (race_id, number)
                require(key in marginal_lookup.index, f"missing candidate marginal in {race_id}/{number}")
                value = float(marginal_lookup.loc[key, "candidate_joint_marginal"])
                derived = math.fsum(horse_terms[number])
                require(math.isclose(value, derived, rel_tol=0.0, abs_tol=1e-12), f"saved candidate joint marginal mismatch in {race_id}/{number}")
                # The historical selector is rebuilt from the full triple
                # probabilities.  The CSV marginal is a rounded export and
                # can break exact ties by one ULP; validate that export above
                # but apply the selector to the canonical fsum reconstruction.
                marginal_values.append((number, derived))
            top2 = selected_pair_by_value(marginal_values)
            top2_row = axis_lookup[(race_id, "candidate", "top_two_marginal_pair", 3)]
            top2_saved = parse_pair_text(top2_row.axis_horses)
            require(top2_saved == top2, f"saved candidate top-two-marginal pair mismatch in {race_id}")
            require(math.isclose(float(top2_row.axis_probability), pair_mass[top2], rel_tol=0.0, abs_tol=1e-12), f"saved candidate top-two pair mass mismatch in {race_id}")
            candidate_top2 += 1
        else:
            matched_max += 1
        triple_rows_seen += len(group)

    require(
        set(distance_by_race_arm)
        == {(race_id, arm) for race_id in race_rosters for arm in ("candidate", "matched_baseline")},
        "distance metadata coverage mismatch",
    )
    for race_id in race_rosters:
        require(
            distance_by_race_arm[(race_id, "candidate")] == distance_by_race_arm[(race_id, "matched_baseline")],
            f"candidate/matched distance metadata mismatch for {race_id}",
        )
    require(candidate_top2 == candidate_max == matched_max == len(race_rosters), "joint selector coverage mismatch")
    return {
        "races": len(race_rosters),
        "arms": 2,
        "triple_rows": triple_rows_seen,
        "candidate_marginal_pair_rows": candidate_top2,
        "candidate_maximum_pair_rows": candidate_max,
        "matched_maximum_pair_rows": matched_max,
        "distance_values": len(set(distance_by_race_arm.values())),
    }


def main() -> int:
    try:
        require(ROOT.exists() and STUDY.is_relative_to(ROOT), "unexpected study path")
        hashes = verify_hashes()
        study_artifact_hashes, study_lock_hash = verify_study_source_lock()

        feature = parquet_columns(FEATURE_PATH, FEATURE_COLUMNS)
        feature["race_date"] = pd.to_datetime(feature["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        require(feature["race_date"].notna().all(), "invalid feature race_date")
        require(feature["year"].astype(int).eq(pd.to_datetime(feature["race_date"]).dt.year).all(), "feature year/date mismatch")
        require(not feature["api_record_id"].duplicated().any(), "duplicate feature api_record_id")
        require(not feature[["race_id", "horse_number"]].duplicated().any(), "duplicate feature runner key")
        validate_history_t2(feature, "all STYLE6 feature rows")

        score_hashes = {path: digest for path, digest in hashes.items() if path.endswith("scores.parquet")}
        fold_reports: dict[str, Any] = {}
        eval_frames: dict[int, pd.DataFrame] = {}
        for year in (2024, 2025, 2026):
            eval_joined, cal_joined = check_fold(year, feature, score_hashes, fold_reports)
            eval_frames[year] = eval_joined
            validate_history_t2(cal_joined, f"{year} calibration score rows")
            validate_history_t2(eval_joined, f"{year} evaluation score rows")

        marginals = pd.read_csv(checked_path(MARGINAL_PATH), usecols=MARGINAL_COLUMNS)
        require(not marginals["api_record_id"].duplicated().any(), "duplicate marginal api_record_id")
        require(marginals["saved_f1_style6_p_top3"].notna().all(), "null saved F1_STYLE6 probability")
        require(marginals["candidate_joint_marginal"].notna().all(), "null candidate joint marginal")

        p0_parity = validate_p0_and_raw_parity(eval_frames)
        style6_parity = validate_saved_style6_parity(eval_frames, marginals)
        joint_reconstruction = reconstruct_joint_policies(eval_frames, marginals)

        report = {
            "status": "PASS",
            "scope": "structural_preflight_only_no_fit_no_pair_hit_metrics",
            "study": "20261011_pair_top3_direct_v1",
            "source_sha256": hashes,
            "study_artifact_sha256": study_artifact_hashes,
            "study_source_lock_sha256": study_lock_hash,
            "feature_rows": int(len(feature)),
            "feature_races": int(feature["race_id"].nunique()),
            "evaluation_rows": int(sum(len(df) for df in eval_frames.values())),
            "evaluation_races": int(sum(df["race_id"].nunique() for df in eval_frames.values())),
            "folds": fold_reports,
            "history_t2": "all feature rows pass history_cutoff=race_date-2d and latest_history_date<=cutoff when present",
            "p0_max_pair_raw_score_top2_parity": p0_parity,
            "saved_f1_top3_probability_raw_score_top2_parity": style6_parity,
            "saved_joint_policy_reconstruction": joint_reconstruction,
            "performance_metrics_computed": False,
            "model_fit_performed": False,
        }
        OUT.mkdir(parents=True, exist_ok=True)
        output_path = OUT / "structural_preflight.json"
        require(output_path.resolve().is_relative_to(STUDY), "output escaped study directory")
        require(not output_path.exists(), f"refusing to overwrite existing receipt: {output_path}")
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"PREFLIGHT_FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
