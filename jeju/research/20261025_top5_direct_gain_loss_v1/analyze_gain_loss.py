#!/usr/bin/env python3
"""Read-only diagnosis of frozen Top5 selector gains and losses.

All source paths and output locations are fixed constants under this repository.
The script never mutates source artifacts and only writes to this study's outputs/.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE / "outputs"
MAIN = REPO / "jeju/research/20261025_top5_direct_learning_v1"
BASELINE = REPO / "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
FEATURES = REPO / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
BOOTSTRAP = REPO / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = REPO / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
ROOT_REVIEW = REPO / "jeju/research/20261025_top5_direct_gain_loss_rootreview_v1/ROOT_PLAN_REVIEW.json"
SOURCE_CORRECTION = REPO / "jeju/research/20261025_top5_direct_gain_loss_rootreview_v1/SOURCE_HASH_METADATA_CORRECTION.json"
PRIMARY_DISTANCES = {900.0, 1000.0, 1110.0, 1200.0}
PRIMARY_N = 1503
FULL_N = 1779
BOOTSTRAP_DATES = 269
BOOTSTRAP_DRAWS = 2000
DATE_INVENTORY_SHA = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"
BOOTSTRAP_SHA = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"

EXPECTED = {
    "main_manifest": "29cb6310bbecf79245b69ddc43521d01257b80a99f802e48840742a0752dc8e5",
    "choices": "eacbea0404a41dd70872a9936a9547804579b3e41ca13386e84924ec06899545",
    "choices_receipt": "13ab7d8f6aadab64771c43a73fcd7e813a10eb7268be0dcc7680cdf2bd7f5754",
    "race_outcomes": "e6d12fb52d01a15b2144a5ff4282ac337cedd13f764f4eb19895dc48b24c7e3f",
    "outcomes": "669fcf5067c029ab1d0b3c4c00ce1dd1b8bbe9f0d03d43a4fc18c7aaf2c9888d",
    "baseline": "c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1",
    "features": "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
    "bootstrap": BOOTSTRAP_SHA,
}
PLAN_SHA = "cc0a1019d034287e10d74ea8fbb6a0288e79342a4d0d86fa1d2bc971c13ac5fa"
ROOT_REVIEW_SHA = "56c6f646f05f25bf786676bcabc6e57a908d0a31bd4092ee7aac7ccb8bc3a2a4"
SOURCE_CORRECTION_SHA = "dfa60f6e7ced44f6c565be406a6cbd5e6784da74c5752d9dada608c7e8bd648d"

BASELINE_COLUMNS = [
    "api_record_id", "race_id", "race_date", "year", "distance_m", "grade_raw",
    "horse_id", "horse_number", "observed_starts", "same_valid_times", "field_n", "score",
]
FEATURE_COLUMNS = [
    "api_record_id", "race_id", "race_date", "horse_id", "horse_number", "field_n",
    "history_cutoff", "latest_history_date", "observed_starts", "same_starts", "same_valid_times",
    "days_since_start", "last_time_s", "mean5_s", "valid_n5", "valid_n3", "best5_s", "fast2mean5_s",
    "std5_s", "previous3_mean_s", "previous3_valid_n", "trend_s", "mean5_rank_fraction",
    "hist_s1f_relpos_mean5", "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
]
RAW_INPUT_NAMES = [
    "log_observed_starts", "log_same_starts", "log_same_valid_times",
    "mean5_rank_fraction", "mean5_rank_fraction_missing",
    "hist_s1f_relpos_mean5", "log_hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5", "log_hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5", "log_hist_c4_to_g1f_pair_n",
]
FEATURE_GROUPS = {
    "career": ["log_observed_starts"],
    "same_distance_experience": ["log_same_starts", "log_same_valid_times"],
    "rank": ["mean5_rank_fraction", "mean5_rank_fraction_missing"],
    "style_means": ["hist_s1f_relpos_mean5", "hist_s1f_to_c4_forward_mean5", "hist_c4_to_g1f_forward_mean5"],
    "style_support": ["log_hist_s1f_relpos_n", "log_hist_s1f_to_c4_pair_n", "log_hist_c4_to_g1f_pair_n"],
}
FORM_COLUMNS = ["last_time_s", "mean5_s", "best5_s", "fast2mean5_s", "std5_s", "trend_s"]
STYLE_COLUMNS = [
    ("hist_s1f_relpos_mean5", "hist_s1f_relpos_n"),
    ("hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n"),
    ("hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n"),
]
OUTCOME_CLASSES = ["caught", "lost", "both_hit", "both_miss"]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_hash(label: str, path: Path) -> str:
    actual = sha256(path)
    require(actual == EXPECTED[label], f"{label} SHA-256 changed: {actual}")
    return actual


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSONL {path.name}:{line_number}") from exc
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields = list(dict.fromkeys(key for row in rows for key in row.keys()))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def clean(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def verify_sources() -> dict[str, str]:
    paths = {
        "main_manifest": MAIN / "FINAL_MANIFEST.json",
        "choices": MAIN / "outputs/candidate_choices.jsonl",
        "choices_receipt": MAIN / "outputs/CHOICES_RECEIPT.json",
        "race_outcomes": MAIN / "outputs/race_outcomes.jsonl",
        "outcomes": MAIN / "outputs/outcomes.json",
        "baseline": BASELINE,
        "features": FEATURES,
        "bootstrap": BOOTSTRAP,
    }
    result = {name: check_hash(name, path) for name, path in paths.items()}
    # The frozen main manifest has one metadata typo for the baseline SHA.
    # Preserve the manifest unchanged; bind this study to the verified source file
    # SHA which also appears in the original choice receipt and root audit.
    manifest = load_json(paths["main_manifest"])
    baseline_entry = manifest.get("frozen_sources", {}).get("evaluation_raw_score_and_roster")
    require(baseline_entry is not None, "baseline source entry absent from frozen main manifest")
    result["baseline_sha_in_frozen_manifest"] = str(baseline_entry.get("sha256"))
    result["baseline_manifest_metadata_mismatch"] = str(baseline_entry.get("sha256")) != result["baseline"]
    require(result["baseline_manifest_metadata_mismatch"], "expected manifest metadata discrepancy was not present")
    review_hash = sha256(ROOT_REVIEW)
    correction_hash = sha256(SOURCE_CORRECTION)
    require(review_hash == ROOT_REVIEW_SHA, "root plan review receipt hash changed")
    require(correction_hash == SOURCE_CORRECTION_SHA, "source metadata correction receipt hash changed")
    review = load_json(ROOT_REVIEW)
    require(review.get("approved") is True and review.get("plan_sha256") == PLAN_SHA, "locked plan lacks root approval")
    correction = load_json(SOURCE_CORRECTION)
    require(correction.get("correct_source_sha256") == result["baseline"], "source correction does not bind the actual baseline")
    result["root_plan_review_sha256"] = review_hash
    result["source_hash_metadata_correction_sha256"] = correction_hash
    result["locked_plan_sha256"] = sha256(HERE / "PLAN_LOCK.md")
    require(result["locked_plan_sha256"] == PLAN_SHA, "locked plan changed after approval")
    return result


def source_path_inventory() -> dict[str, str]:
    return {
        "main_frozen_manifest": "jeju/research/20261025_top5_direct_learning_v1/FINAL_MANIFEST.json",
        "candidate_choices": "jeju/research/20261025_top5_direct_learning_v1/outputs/candidate_choices.jsonl",
        "choices_receipt": "jeju/research/20261025_top5_direct_learning_v1/outputs/CHOICES_RECEIPT.json",
        "race_outcomes": "jeju/research/20261025_top5_direct_learning_v1/outputs/race_outcomes.jsonl",
        "outcomes_summary": "jeju/research/20261025_top5_direct_learning_v1/outputs/outcomes.json",
        "baseline_runners": "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet",
        "features": "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet",
        "fit_receipt": "jeju/research/20261025_top5_direct_learning_v1/outputs/FIT_RECEIPT.json",
        "yearly_heads": "jeju/research/20261025_top5_direct_learning_v1/outputs/model_{2024,2025,2026}.json",
        "date_bootstrap_schedule": "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy",
        "date_bootstrap_receipt": "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json",
        "root_plan_review": "jeju/research/20261025_top5_direct_gain_loss_rootreview_v1/ROOT_PLAN_REVIEW.json",
        "source_hash_metadata_correction": "jeju/research/20261025_top5_direct_gain_loss_rootreview_v1/SOURCE_HASH_METADATA_CORRECTION.json",
    }


def load_choices() -> list[dict[str, Any]]:
    choices = load_jsonl(MAIN / "outputs/candidate_choices.jsonl")
    require(len(choices) == FULL_N, "choice row count changed")
    require(len({str(row["race_id"]) for row in choices}) == FULL_N, "duplicate choice race")
    return choices


def primary_date_inventory(choices: list[dict[str, Any]]) -> list[str]:
    dates = sorted({str(row["race_date"]) for row in choices if float(row["distance_m"]) in PRIMARY_DISTANCES})
    require(len(dates) == BOOTSTRAP_DATES, "primary date count differs from frozen bootstrap")
    require(hashlib.sha256("\n".join(dates).encode()).hexdigest() == DATE_INVENTORY_SHA, "primary date inventory SHA differs")
    return dates


def read_pregame() -> pd.DataFrame:
    base = pq.read_table(BASELINE, columns=BASELINE_COLUMNS).to_pandas()
    feat = pq.read_table(FEATURES, columns=FEATURE_COLUMNS).to_pandas()
    require(len(base) == 17412 and base["api_record_id"].is_unique, "baseline roster rows or keys changed")
    require(feat["api_record_id"].is_unique, "feature source has duplicate API record key")
    feat = feat.loc[feat["api_record_id"].isin(base["api_record_id"])].copy()
    require(len(feat) == len(base), "not all evaluation runners have pre-race features")
    frame = base.merge(feat, on="api_record_id", how="inner", suffixes=("_base", ""), validate="one_to_one")
    require(len(frame) == len(base), "runner join lost or multiplied rows")
    for column in ("race_id", "horse_id", "horse_number", "year", "distance_m", "field_n"):
        base_name = f"{column}_base"
        if base_name in frame.columns:
            require((frame[base_name].astype(str) == frame[column].astype(str)).all(), f"source key mismatch: {column}")
    for column in ("observed_starts", "same_valid_times"):
        require(np.array_equal(
            pd.to_numeric(frame[f"{column}_base"], errors="raise").to_numpy(),
            pd.to_numeric(frame[column], errors="raise").to_numpy(),
        ), f"baseline/features input mismatch: {column}")
    dates = pd.to_datetime(frame["race_date"], errors="raise").dt.date
    cutoffs = pd.to_datetime(frame["history_cutoff"], errors="raise").dt.date
    require((cutoffs == dates - pd.Timedelta(days=2)).all(), "history cutoff is not race_date - 2 days")
    latest = pd.to_datetime(frame["latest_history_date"], errors="coerce").dt.date
    require(((latest.isna()) | (latest <= cutoffs)).all(), "latest feature history exceeds cutoff")
    return frame


def score_ranked(group: pd.DataFrame) -> pd.DataFrame:
    ranked = group.sort_values(["score", "horse_number"], ascending=[False, True], kind="mergesort").copy()
    ranked["score_rank"] = np.arange(1, len(ranked) + 1, dtype=np.int16)
    return ranked


def exact_set(values: Any) -> set[str]:
    return {str(value) for value in values}


def bucket_starts(value: Any) -> str:
    if pd.isna(value): return "missing"
    value = int(value)
    if value == 0: return "0"
    if value <= 4: return "1-4"
    return "5+"


def bucket_valid_n5(value: Any) -> str:
    if pd.isna(value): return "missing"
    value = int(value)
    if value == 0: return "0"
    if value <= 2: return "1-2"
    return "3-5"


def bucket_same_times(value: Any) -> str:
    if pd.isna(value): return "missing"
    value = int(value)
    return "0" if value == 0 else ("1" if value == 1 else "2+")


def bucket_recency(value: Any) -> str:
    if pd.isna(value): return "missing"
    value = float(value)
    if value < 15: return "<15"
    if value <= 28: return "15-28"
    if value <= 60: return "29-60"
    return "61+"


def bucket_gap(value: Any) -> str:
    if value <= 0.10: return "<=0.10"
    if value <= 0.25: return "(0.10,0.25]"
    return ">0.25"


def primary_outcome_class(row: dict[str, Any]) -> str:
    if bool(row["selector_only_caught"]): return "caught"
    if bool(row["baseline_only_lost"]): return "lost"
    if bool(row["baseline_all_three_hit"]) and bool(row["selector_all_three_hit"]): return "both_hit"
    return "both_miss"


def build_race_data(frame: pd.DataFrame, choices: list[dict[str, Any]], outcome_rows: list[dict[str, Any]] | None = None) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    choice_by_race = {str(row["race_id"]): row for row in choices}
    outcome_by_race = {str(row["race_id"]): row for row in outcome_rows} if outcome_rows is not None else {}
    if outcome_rows is not None:
        require(set(choice_by_race) == set(outcome_by_race), "choice/outcome race inventories differ")
    ranked_by_race: dict[str, pd.DataFrame] = {}
    races: list[dict[str, Any]] = []
    for race_id, group in frame.groupby("race_id", sort=True):
        race_id = str(race_id)
        ranked = score_ranked(group)
        ranked_by_race[race_id] = ranked
        choice = choice_by_race[race_id]
        first = ranked.iloc[0]
        require(str(pd.to_datetime(first["race_date"]).date()) == str(choice["race_date"]), f"choice race_date differs from roster: {race_id}")
        require(int(first["year"]) == int(choice["year"]), f"choice year differs from roster: {race_id}")
        require(float(first["distance_m"]) == float(choice["distance_m"]), f"choice distance differs from roster: {race_id}")
        require(int(first["field_n"]) == int(choice["field_n"]) == len(ranked), f"choice field_n differs from roster: {race_id}")
        require(ranked["grade_raw"].nunique(dropna=False) == 1, f"grade_raw is not race-constant: {race_id}")
        base_ids = exact_set(choice["baseline_top5_horse_ids"])
        head_ids = exact_set(choice["selector_top5_horse_ids"])
        # The pre-outcome pass has no finish_position in its read allowlist.
        require(base_ids == exact_set(ranked.loc[ranked["score_rank"].le(5), "horse_id"]), f"raw Top5 roster mismatch: {race_id}")
        require(len(base_ids) == len(head_ids) == 5, f"choice set width changed: {race_id}")
        added = head_ids - base_ids
        removed = base_ids - head_ids
        require(len(added) == len(removed), f"added/removed size mismatch: {race_id}")
        fifth = ranked.loc[ranked["score_rank"] == 5].iloc[0]
        sixth = ranked.loc[ranked["score_rank"] == 6].iloc[0]
        score_sd = float(pd.to_numeric(ranked["score"], errors="raise").std(ddof=0))
        raw_gap = float(fifth["score"] - sixth["score"])
        z_gap = raw_gap / score_sd if score_sd else 0.0
        result = outcome_by_race.get(race_id)
        changed = bool(added)
        is_primary = float(choice["distance_m"]) in PRIMARY_DISTANCES
        if result is None:
            status = "not_read"
        else:
            status = primary_outcome_class(result) if is_primary else ("caught" if result["selector_only_caught"] else ("lost" if result["baseline_only_lost"] else ("both_hit" if result["baseline_all_three_hit"] else "both_miss")))
        races.append({
            "race_id": race_id, "race_date": str(choice["race_date"]), "year": int(choice["year"]),
            "distance_m": float(choice["distance_m"]), "grade_raw": clean(fifth.get("grade_raw")),
            "field_n": int(choice["field_n"]), "primary": is_primary, "selection_changed": changed,
            "swap_count": len(added), "score5_horse_id": str(fifth["horse_id"]),
            "score5_horse_number": int(fifth["horse_number"]), "score5_score": float(fifth["score"]),
            "raw_score_5_6_gap": raw_gap, "z_score_5_6_gap": z_gap,
            "z_gap_bin": bucket_gap(z_gap),
            "score5_observed_starts": clean(fifth["observed_starts"]),
            "score5_observed_starts_bin": bucket_starts(fifth["observed_starts"]),
            "score5_valid_n5": clean(fifth["valid_n5"]),
            "score5_valid_n3": clean(fifth["valid_n3"]),
            "score5_valid_n5_bin": bucket_valid_n5(fifth["valid_n5"]),
            "score5_same_valid_times": clean(fifth["same_valid_times"]),
            "score5_same_valid_times_bin": bucket_same_times(fifth["same_valid_times"]),
            "score5_days_since_start": clean(fifth["days_since_start"]),
            "score5_days_since_start_bin": bucket_recency(fifth["days_since_start"]),
            "score5_same_starts": clean(fifth["same_starts"]),
            "score5_last_time_s": clean(fifth["last_time_s"]),
            "score5_mean5_s": clean(fifth["mean5_s"]),
            "score5_best5_s": clean(fifth["best5_s"]),
            "score5_fast2mean5_s": clean(fifth["fast2mean5_s"]),
            "score5_std5_s": clean(fifth["std5_s"]),
            "score5_previous3_mean_s": clean(fifth["previous3_mean_s"]),
            "score5_previous3_valid_n": clean(fifth["previous3_valid_n"]),
            "score5_trend_s": clean(fifth["trend_s"]),
            "score5_mean5_rank_fraction": clean(fifth["mean5_rank_fraction"]),
            "score5_hist_s1f_relpos_mean5": clean(fifth["hist_s1f_relpos_mean5"]),
            "score5_hist_s1f_relpos_n": clean(fifth["hist_s1f_relpos_n"]),
            "score5_hist_s1f_to_c4_forward_mean5": clean(fifth["hist_s1f_to_c4_forward_mean5"]),
            "score5_hist_s1f_to_c4_pair_n": clean(fifth["hist_s1f_to_c4_pair_n"]),
            "score5_hist_c4_to_g1f_forward_mean5": clean(fifth["hist_c4_to_g1f_forward_mean5"]),
            "score5_hist_c4_to_g1f_pair_n": clean(fifth["hist_c4_to_g1f_pair_n"]),
            "outcome_class": status,
            "baseline_all_three_hit": None if result is None else bool(result["baseline_all_three_hit"]),
            "selector_all_three_hit": None if result is None else bool(result["selector_all_three_hit"]),
            "both_hit": None if result is None else bool(result["baseline_all_three_hit"] and result["selector_all_three_hit"]),
            "both_miss": None if result is None else bool(not result["baseline_all_three_hit"] and not result["selector_all_three_hit"]),
            "selector_only_caught": None if result is None else bool(result["selector_only_caught"]),
            "baseline_only_lost": None if result is None else bool(result["baseline_only_lost"]),
        })
    race_frame = pd.DataFrame(races)
    require(len(race_frame) == FULL_N and int(race_frame["primary"].sum()) == PRIMARY_N, "primary/full cohort counts changed")
    return race_frame, ranked_by_race


def pregame_profile(frame: pd.DataFrame, choices: list[dict[str, Any]]) -> dict[str, Any]:
    races, _ = build_race_data(frame, choices, None)
    primary = races.loc[races["primary"]].copy()
    profile: dict[str, Any] = {
        "status": "PRE_OUTCOME_INPUT_PROFILE",
        "primary_races": len(primary),
        "changed_choices": int(primary["selection_changed"].sum()),
        "category_support": {},
        "full_cohort_field_n_distribution": {},
        "secondary_cohort_field_n_distribution": {},
        "gap_raw_score_units": {},
        "gap_z": {},
    }
    categories = [
        "year", "distance_m", "grade_raw", "field_n", "z_gap_bin",
        "score5_observed_starts_bin", "score5_valid_n5_bin", "score5_same_valid_times_bin",
        "score5_days_since_start_bin",
    ]
    for col in categories:
        vals = primary[col].fillna("missing").astype(str).value_counts().sort_index()
        profile["category_support"][col] = {key: int(value) for key, value in vals.items()}
    for scope, subset in (("full_cohort", races), ("secondary_cohort", races.loc[~races["primary"]])):
        vals = subset["field_n"].astype(str).value_counts().sort_index()
        profile[f"{scope}_field_n_distribution"] = {key: int(value) for key, value in vals.items()}
    for col, dest in (("raw_score_5_6_gap", "gap_raw_score_units"), ("z_score_5_6_gap", "gap_z")):
        values = pd.to_numeric(primary[col], errors="coerce").dropna().to_numpy(dtype=float)
        profile[dest] = {
            "n": int(len(values)), "mean": float(values.mean()), "sd": float(values.std(ddof=0)),
            "q25": float(np.quantile(values, 0.25)), "median": float(np.quantile(values, 0.5)),
            "q75": float(np.quantile(values, 0.75)), "min": float(values.min()), "max": float(values.max()),
        }
    return profile


def audit_frozen_counts(choices: list[dict[str, Any]], outcome_rows: list[dict[str, Any]], outcomes: dict[str, Any]) -> dict[str, Any]:
    choice_by = {str(row["race_id"]): row for row in choices}
    out_by = {str(row["race_id"]): row for row in outcome_rows}
    require(set(choice_by) == set(out_by), "race outcomes do not match choice IDs")
    per_distance = Counter()
    classes_primary = Counter()
    classes_full = Counter()
    changed_primary = 0
    changed_full = 0
    for race_id, choice in choice_by.items():
        changed = exact_set(choice["baseline_top5_horse_ids"]) != exact_set(choice["selector_top5_horse_ids"])
        result = out_by[race_id]
        primary = float(choice["distance_m"]) in PRIMARY_DISTANCES
        status = primary_outcome_class(result)
        classes_full[status] += 1
        if primary:
            classes_primary[status] += 1
            per_distance[float(choice["distance_m"])] += 1
            changed_primary += int(changed)
        changed_full += int(changed)
    require(dict(classes_primary) == {"both_hit": 404, "caught": 31, "lost": 35, "both_miss": 1033}, f"primary status counts changed: {dict(classes_primary)}")
    require(dict(classes_full) == {"both_hit": 482, "caught": 38, "lost": 37, "both_miss": 1222}, f"full status counts changed: {dict(classes_full)}")
    require(changed_primary == 254 and changed_full == 304, "frozen changed-choice counts changed")
    primary_metrics = outcomes["primary"]
    full_metrics = outcomes["full"]
    require((primary_metrics["races"], primary_metrics["baseline_all_three_hits"], primary_metrics["selector_all_three_hits"]) == (1503, 439, 435), "aggregate primary outcome receipt changed")
    require((full_metrics["races"], full_metrics["baseline_all_three_hits"], full_metrics["selector_all_three_hits"]) == (1779, 519, 520), "aggregate full outcome receipt changed")
    return {
        "status": "PASS",
        "primary_races": 1503,
        "primary_distances": {str(key): int(value) for key, value in sorted(per_distance.items())},
        "primary_changed_choices": changed_primary,
        "primary_outcome_class_counts": dict(sorted(classes_primary.items())),
        "primary_baseline_hits": int(primary_metrics["baseline_all_three_hits"]),
        "primary_selector_hits": int(primary_metrics["selector_all_three_hits"]),
        "full_races": 1779,
        "full_changed_choices": changed_full,
        "full_outcome_class_counts": dict(sorted(classes_full.items())),
        "full_baseline_hits": int(full_metrics["baseline_all_three_hits"]),
        "full_selector_hits": int(full_metrics["selector_all_three_hits"]),
        "primary_discordant_posthoc_subset": 66,
        "full_discordant_secondary": 75,
    }


def profile_phase() -> None:
    source_hashes = verify_sources()
    choices = load_choices()
    frame = read_pregame()
    payload = pregame_profile(frame, choices)
    payload["source_hashes"] = source_hashes
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "PREGAME_PROFILE.json", payload)


def audit_phase() -> None:
    source_hashes = verify_sources()
    choices = load_choices()
    outcome_rows = load_jsonl(MAIN / "outputs/race_outcomes.jsonl")
    outcomes = load_json(MAIN / "outputs/outcomes.json")
    counts = audit_frozen_counts(choices, outcome_rows, outcomes)
    receipt_path = MAIN / "outputs/CHOICES_RECEIPT.json"
    choice_receipt = load_json(receipt_path)
    outcomes_receipt = load_json(MAIN / "outputs/OUTCOME_RECEIPT.json")
    payload = {
        **counts,
        "source_hashes": source_hashes,
        "source_paths": source_path_inventory(),
        "source_sizes_bytes": {
            "choices": (MAIN / "outputs/candidate_choices.jsonl").stat().st_size,
            "choices_receipt": receipt_path.stat().st_size,
            "race_outcomes": (MAIN / "outputs/race_outcomes.jsonl").stat().st_size,
            "outcomes": (MAIN / "outputs/outcomes.json").stat().st_size,
        },
        "choice_receipt_status": choice_receipt.get("status"),
        "outcome_receipt_status": outcomes_receipt.get("status"),
        "baseline_manifest_note": "The preserved main manifest contains a mistyped baseline SHA. This study binds the actual parquet SHA, consistent with the original choice receipt, prior root source audit, and new correction receipt; the old manifest remains unchanged.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "SOURCE_AUDIT.json", payload)


def format_group_value(value: Any) -> str:
    if value is None or pd.isna(value): return "missing"
    if isinstance(value, (np.integer, int)): return str(int(value))
    if isinstance(value, (np.floating, float)): return f"{float(value):g}"
    return str(value)


def read_labels_only(frame: pd.DataFrame) -> pd.DataFrame:
    labels = pq.read_table(FEATURES, columns=["api_record_id", "finish_position"]).to_pandas()
    labels = labels.loc[labels["api_record_id"].isin(frame["api_record_id"])].copy()
    require(len(labels) == len(frame) and labels["api_record_id"].is_unique, "separate label-only read is incomplete or duplicated")
    labels["finish_position"] = pd.to_numeric(labels["finish_position"], errors="coerce")
    require(labels["finish_position"].notna().all(), "evaluation finish labels contain missing values")
    merged = frame[["api_record_id", "race_id", "horse_id", "horse_number"]].merge(labels, on="api_record_id", validate="one_to_one")
    return merged


def add_outcomes_to_roster(frame: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    merged = frame.merge(labels[["api_record_id", "finish_position"]], on="api_record_id", how="inner", validate="one_to_one")
    require(len(merged) == len(frame), "label join changed roster size")
    return merged


def summary_metrics(group: pd.DataFrame, label: str, condition: str, value: str) -> dict[str, Any]:
    n = int(len(group))
    caught = int(group["selector_only_caught"].sum())
    lost = int(group["baseline_only_lost"].sum())
    both_hit = int(group["both_hit"].sum())
    both_miss = int(group["both_miss"].sum())
    baseline_hits = int(group["baseline_all_three_hit"].sum())
    selector_hits = int(group["selector_all_three_hit"].sum())
    require(caught + lost + both_hit + both_miss == n, f"outcome partition does not sum for {condition}={value}")
    return {
        "condition": condition, "condition_value": value, "n_races": n,
        "changed_races": int(group["selection_changed"].sum()), "caught": caught, "lost": lost,
        "both_hit": both_hit, "both_miss": both_miss,
        "baseline_all_three_hits": baseline_hits, "selector_all_three_hits": selector_hits,
        "baseline_hit_rate": baseline_hits / n if n else None,
        "selector_hit_rate": selector_hits / n if n else None,
        "net_delta_races_caught_minus_lost": caught - lost,
        "net_delta_pp_full_condition_denominator": 100.0 * (caught - lost) / n if n else None,
        "small_sample_n_lt_30": n < 30,
        "description": label,
    }


def group_bootstrap_ci(group: pd.DataFrame, dates: list[str], schedule: np.ndarray) -> dict[str, Any]:
    by_date = group.assign(_delta=group["selector_only_caught"].astype(int) - group["baseline_only_lost"].astype(int))
    agg = by_date.groupby("race_date", sort=True).agg(n=("race_id", "size"), delta=("_delta", "sum"))
    n_by_date = np.zeros(len(dates), dtype=np.int64)
    delta_by_date = np.zeros(len(dates), dtype=np.int64)
    date_index = {day: i for i, day in enumerate(dates)}
    for day, row in agg.iterrows():
        if str(day) in date_index:
            index = date_index[str(day)]
            n_by_date[index] = int(row["n"])
            delta_by_date[index] = int(row["delta"])
    denominators = n_by_date[schedule].sum(axis=1, dtype=np.int64)
    numerators = delta_by_date[schedule].sum(axis=1, dtype=np.int64)
    valid = denominators > 0
    if not valid.all():
        return {
            "bootstrap_lower95_pp": None, "bootstrap_upper95_pp": None,
            "bootstrap_valid_replicates": int(valid.sum()), "bootstrap_zero_group_replicates": int((~valid).sum()),
            "bootstrap_status": "undefined_zero_group_resample",
        }
    samples = 100.0 * numerators / denominators
    lo, hi = np.quantile(samples, [0.025, 0.975], method="linear")
    return {
        "bootstrap_lower95_pp": float(lo), "bootstrap_upper95_pp": float(hi),
        "bootstrap_valid_replicates": int(len(samples)), "bootstrap_zero_group_replicates": 0,
        "bootstrap_status": "defined_exploratory_date_cluster_ci",
    }


def condition_summary(races: pd.DataFrame, choices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    primary = races.loc[races["primary"]].copy()
    dates = primary_date_inventory(choices)
    schedule = np.load(BOOTSTRAP, allow_pickle=False)
    receipt = load_json(BOOTSTRAP_RECEIPT)
    require(sha256(BOOTSTRAP_RECEIPT) == "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e", "bootstrap receipt hash changed")
    require(receipt.get("date_inventory_sha256") == DATE_INVENTORY_SHA and receipt.get("schedule_sha256") == BOOTSTRAP_SHA, "bootstrap receipt identity changed")
    require(schedule.shape == (BOOTSTRAP_DRAWS, BOOTSTRAP_DATES) and schedule.dtype == np.int32, "bootstrap schedule shape/dtype changed")
    require(bool(((schedule >= 0) & (schedule < BOOTSTRAP_DATES)).all()), "bootstrap schedule index out of range")
    primary_dates = sorted(primary["race_date"].astype(str).unique().tolist())
    require(primary_dates == dates, "condition summary date inventory differs from frozen schedule")

    conditions: list[tuple[str, str, pd.Series]] = [
        ("year", "evaluation year", primary["year"].astype(str)),
        ("distance_m", "race distance in meters", primary["distance_m"].map(format_group_value)),
        ("grade_raw", "source grade_raw category", primary["grade_raw"].map(format_group_value)),
        ("field_n", "exact field size", primary["field_n"].astype(str)),
        ("z_gap_bin", "fifth-minus-sixth raw-score gap / within-race score SD", primary["z_gap_bin"].astype(str)),
        ("score5_observed_starts_bin", "baseline Top5 boundary runner career starts", primary["score5_observed_starts_bin"].astype(str)),
        ("score5_valid_n5_bin", "baseline Top5 boundary runner valid recent times", primary["score5_valid_n5_bin"].astype(str)),
        ("score5_same_valid_times_bin", "baseline Top5 boundary runner same-distance valid times", primary["score5_same_valid_times_bin"].astype(str)),
        ("score5_days_since_start_bin", "baseline Top5 boundary runner days since prior start", primary["score5_days_since_start_bin"].astype(str)),
    ]
    for raw, support in STYLE_COLUMNS:
        key = f"score5_{support}"
        series = primary[key].map(format_group_value)
        conditions.append((key, f"boundary runner {support} exact support", series))
    year_distance = primary.apply(lambda row: f"{int(row['year'])}-{int(row['distance_m'])}", axis=1)
    conditions.append(("year_by_distance", "only cross-tab: year × distance", year_distance))

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for name, description, series in conditions:
        for value in sorted(series.dropna().unique().tolist()):
            mask = series.eq(value)
            group = primary.loc[mask].copy()
            row = summary_metrics(group, description, name, str(value))
            row.update(group_bootstrap_ci(group, dates, schedule))
            identity = (name, str(value))
            require(identity not in seen, f"duplicate condition cell: {identity}")
            seen.add(identity)
            result.append(row)
    require(len([row for row in result if row["condition"] == "year_by_distance"]) <= 12, "year-by-distance cross-tab exceeded 12 cells")
    return result


def quant_summary(values: pd.Series) -> dict[str, Any]:
    x = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if not len(x):
        return {"n": 0, "mean": None, "median": None, "q25": None, "q75": None}
    return {
        "n": int(len(x)), "mean": float(x.mean()), "median": float(np.median(x)),
        "q25": float(np.quantile(x, .25)), "q75": float(np.quantile(x, .75)),
    }


def boundary_form_summary(primary_roster: pd.DataFrame, primary_races: pd.DataFrame) -> list[dict[str, Any]]:
    primary_races = primary_races.loc[primary_races["primary"]].copy()
    primary_ids = set(primary_races["race_id"].astype(str))
    class_map = primary_races.set_index("race_id")["outcome_class"].to_dict()
    rows: list[dict[str, Any]] = []
    roster = primary_roster.loc[
        primary_roster["score_rank"].eq(5) & primary_roster["race_id"].astype(str).isin(primary_ids)
    ].copy()
    roster["outcome_class"] = roster["race_id"].astype(str).map(class_map)
    for (distance, status), group in roster.groupby(["distance_m", "outcome_class"], sort=True):
        row: dict[str, Any] = {"primary_cohort": True, "distance_m": float(distance), "outcome_class": status, "n_races": int(len(group))}
        for col in FORM_COLUMNS:
            stats = quant_summary(group[col])
            for key, value in stats.items():
                row[f"{col}_{key}"] = value
            row[f"{col}_support_valid_n5_mean"] = clean(pd.to_numeric(group["valid_n5"], errors="coerce").mean())
        for mean, support in STYLE_COLUMNS:
            stats = quant_summary(group[mean])
            for key, value in stats.items():
                row[f"{mean}_{key}"] = value
            row[f"{support}_observed_races"] = int(pd.to_numeric(group[support], errors="coerce").notna().sum())
            row[f"{support}_mean"] = clean(pd.to_numeric(group[support], errors="coerce").mean())
        row["same_starts_mean"] = clean(pd.to_numeric(group["same_starts"], errors="coerce").mean())
        row["same_valid_times_mean"] = clean(pd.to_numeric(group["same_valid_times"], errors="coerce").mean())
        row["previous3_valid_n_mean"] = clean(pd.to_numeric(group["previous3_valid_n"], errors="coerce").mean())
        row["valid_n3_mean"] = clean(pd.to_numeric(group["valid_n3"], errors="coerce").mean())
        row["valid_n5_mean"] = clean(pd.to_numeric(group["valid_n5"], errors="coerce").mean())
        for support_col, maximum in (("valid_n3", 3), ("previous3_valid_n", 3), ("valid_n5", 5)):
            counts = pd.to_numeric(group[support_col], errors="coerce").value_counts(dropna=False)
            for support_value in range(maximum + 1):
                row[f"{support_col}_support_{support_value}"] = int(counts.get(support_value, 0))
        rows.append(row)
    return rows


def gap_continuous_summary(races: pd.DataFrame) -> list[dict[str, Any]]:
    primary = races.loc[races["primary"]]
    rows: list[dict[str, Any]] = []
    for status in ["all_primary", *OUTCOME_CLASSES]:
        group = primary if status == "all_primary" else primary.loc[primary["outcome_class"] == status]
        for metric, unit in (("raw_score_5_6_gap", "raw F1_STYLE6 score units"), ("z_score_5_6_gap", "within-race population SD units")):
            row = {"outcome_class": status, "metric": metric, "unit": unit, "n_races": int(len(group))}
            row.update(quant_summary(group[metric]))
            rows.append(row)
    return rows


def selector_input_matrix(frame: pd.DataFrame) -> np.ndarray:
    raw: dict[str, np.ndarray] = {}
    for col in ("observed_starts", "same_starts", "same_valid_times", "hist_s1f_relpos_n", "hist_s1f_to_c4_pair_n", "hist_c4_to_g1f_pair_n"):
        values = pd.to_numeric(frame[col], errors="raise").to_numpy(dtype=np.float64)
        require(np.isfinite(values).all() and (values >= 0).all(), f"invalid selector count input {col}")
        raw[f"log_{col}"] = np.log1p(values)
    rank_series = pd.to_numeric(frame["mean5_rank_fraction"], errors="raise")
    rank_values = rank_series.to_numpy(dtype=np.float64, na_value=np.nan)
    raw["mean5_rank_fraction"] = rank_values
    raw["mean5_rank_fraction_missing"] = rank_series.isna().to_numpy(dtype=np.float64)
    for mean, _support in STYLE_COLUMNS:
        values = pd.to_numeric(frame[mean], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
        raw[mean] = values
    require(set(raw) == set(RAW_INPUT_NAMES), "selector input allowlist changed")
    return np.column_stack([raw[name] for name in RAW_INPUT_NAMES]).astype(np.float64)


def load_models() -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    fit_path = MAIN / "outputs/FIT_RECEIPT.json"
    fit_receipt = load_json(fit_path)
    fit_sha = sha256(fit_path)
    choice_receipt = load_json(MAIN / "outputs/CHOICES_RECEIPT.json")
    require(choice_receipt.get("fit_receipt_sha256") == fit_sha, "choice receipt points to a different fit receipt")
    models: dict[int, dict[str, Any]] = {}
    for year in (2024, 2025, 2026):
        name = f"model_{year}.json"
        path = MAIN / "outputs" / name
        expected_sha = fit_receipt["model_artifacts"][name]["sha256"]
        require(sha256(path) == expected_sha, f"fitted head hash mismatch for {year}")
        model = load_json(path)
        require(model.get("evaluation_year") == year and model.get("feature_names") == RAW_INPUT_NAMES, f"unexpected model contract for {year}")
        require(len(model.get("beta", [])) == len(RAW_INPUT_NAMES), f"unexpected beta width for {year}")
        models[year] = model
    return models, {"fit_receipt_sha256": fit_sha, "model_sha256": {str(y): sha256(MAIN / "outputs" / f"model_{y}.json") for y in models}}


def model_standardize(raw: np.ndarray, model: dict[str, Any]) -> np.ndarray:
    means = np.asarray(model["feature_means"], dtype=np.float64)
    scales = np.asarray(model["feature_scales"], dtype=np.float64)
    require(raw.shape[1] == len(means) == len(scales), "model scaler dimensions differ from inputs")
    require(np.isfinite(means).all() and np.isfinite(scales).all() and (scales > 0).all(), "invalid frozen model scaler")
    x = np.zeros_like(raw, dtype=np.float64)
    for j in range(raw.shape[1]):
        finite = np.isfinite(raw[:, j])
        x[finite, j] = (raw[finite, j] - means[j]) / scales[j]
        x[~finite, j] = 0.0
    require(np.isfinite(x).all(), "nonfinite standardized selector matrix")
    return x


def energy_decomposition(frame: pd.DataFrame, choices: list[dict[str, Any]], models: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    raw = selector_input_matrix(frame)
    api_ids = pd.to_numeric(frame["api_record_id"], errors="raise").to_numpy(dtype=np.int64)
    raw_by_id = {int(api_id): raw[index] for index, api_id in enumerate(api_ids)}
    frame_by_race = {str(race_id): group for race_id, group in frame.groupby("race_id", sort=False)}
    choice_by_race = {str(row["race_id"]): row for row in choices}
    out: list[dict[str, Any]] = []
    group_indices = {group: [RAW_INPUT_NAMES.index(col) for col in cols] for group, cols in FEATURE_GROUPS.items()}
    for race_id, group in frame_by_race.items():
        choice = choice_by_race[race_id]
        model = models[int(choice["year"])]
        beta = np.asarray(model["beta"], dtype=np.float64)
        ids = group["horse_id"].astype(str).tolist()
        scores = pd.to_numeric(group["score"], errors="raise").to_numpy(dtype=np.float64)
        sd = float(scores.std(ddof=0))
        z = np.zeros_like(scores) if sd == 0 else (scores - float(scores.mean())) / sd
        z_by_id = {horse_id: float(z[index]) for index, horse_id in enumerate(ids)}
        x_race = np.vstack([model_standardize(raw_by_id[int(api_id)][None, :], model)[0] for api_id in group["api_record_id"]])
        x_by_id = {horse_id: x_race[index] for index, horse_id in enumerate(ids)}
        baseline_ids = exact_set(choice["baseline_top5_horse_ids"])
        selector_ids = exact_set(choice["selector_top5_horse_ids"])
        prior_baseline = sum(z_by_id[key] for key in baseline_ids)
        prior_selector = sum(z_by_id[key] for key in selector_ids)
        require(np.isclose(prior_baseline, float(choice["baseline_energy"]), atol=1e-10, rtol=0), f"prior-only baseline energy mismatch: {race_id}")
        feature_baseline = sum((x_by_id[key] @ beta) for key in baseline_ids)
        feature_selector = sum((x_by_id[key] @ beta) for key in selector_ids)
        head_baseline = prior_baseline + feature_baseline
        head_selector = prior_selector + feature_selector
        require(np.isclose(head_selector, float(choice["selector_energy"]), atol=1e-8, rtol=0), f"reconstructed selected head energy mismatch: {race_id}")
        # Report exact per-feature energy changes for every changed race; secondary
        # distances remain explicitly separated downstream.
        changed = baseline_ids != selector_ids
        primary = float(choice["distance_m"]) in PRIMARY_DISTANCES
        if not changed:
            continue
        added = selector_ids - baseline_ids
        removed = baseline_ids - selector_ids
        dx = np.vstack([x_by_id[key] for key in sorted(added)]).sum(axis=0) - np.vstack([x_by_id[key] for key in sorted(removed)]).sum(axis=0)
        prior_delta = prior_selector - prior_baseline
        contributions = beta * dx
        total_delta = head_selector - head_baseline
        require(np.isclose(prior_delta + contributions.sum(), total_delta, atol=1e-8, rtol=0), f"energy contribution sum mismatch: {race_id}")
        record: dict[str, Any] = {
            "race_id": race_id, "year": int(choice["year"]), "distance_m": float(choice["distance_m"]),
            "primary_cohort": primary,
            "raw_prior_delta": prior_delta, "head_baseline_energy_reconstructed": head_baseline,
            "head_selector_energy_reconstructed": head_selector, "head_set_energy_delta": total_delta,
        }
        for name, value in zip(RAW_INPUT_NAMES, contributions):
            record[f"contrib_{name}"] = float(value)
        for group_name, indices in group_indices.items():
            record[f"contrib_group_{group_name}"] = float(contributions[indices].sum())
        record["decomposition_residual"] = float(prior_delta + contributions.sum() - total_delta)
        out.append(record)
    require(len(out) == 304, f"full changed energy rows changed: {len(out)}")
    return out


def changed_ledgers(roster: pd.DataFrame, races: pd.DataFrame, choices: list[dict[str, Any]], energy_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    choice_by = {str(row["race_id"]): row for row in choices}
    race_by = races.set_index("race_id").to_dict(orient="index")
    energy_by = {row["race_id"]: row for row in energy_rows}
    runner_rows: list[dict[str, Any]] = []
    race_rows: list[dict[str, Any]] = []
    all_changed = races.loc[races["selection_changed"]]
    for race_id in sorted(all_changed["race_id"].astype(str)):
        choice = choice_by[race_id]
        race = race_by[race_id]
        group = roster.loc[roster["race_id"].astype(str) == race_id].copy()
        ranked = score_ranked(group)
        by_horse = {str(row.horse_id): row._asdict() for row in ranked.itertuples(index=False)}
        baseline_ids = exact_set(choice["baseline_top5_horse_ids"])
        selector_ids = exact_set(choice["selector_top5_horse_ids"])
        added, removed = selector_ids - baseline_ids, baseline_ids - selector_ids
        actual_top3 = {str(row["horse_id"]) for row in group.loc[group["finish_position"] <= 3, ["horse_id"]].to_dict(orient="records")}
        retained = baseline_ids & selector_ids
        top3_missed_by_both = actual_top3 - (baseline_ids | selector_ids)
        add_hits = len(added & actual_top3)
        remove_hits = len(removed & actual_top3)
        retained_hits = len(retained & actual_top3)
        baseline_capture = len(actual_top3 & baseline_ids)
        selector_capture = len(actual_top3 & selector_ids)
        require((baseline_capture == 3) == bool(race["baseline_all_three_hit"]), f"baseline hit boolean mismatch {race_id}")
        require((selector_capture == 3) == bool(race["selector_all_three_hit"]), f"selector hit boolean mismatch {race_id}")
        energy = energy_by[race_id]
        race_record = {
            "race_id": race_id, "race_date": race["race_date"], "year": race["year"], "distance_m": race["distance_m"],
            "grade_raw": race["grade_raw"], "field_n": race["field_n"], "primary_cohort": bool(race["primary"]),
            "outcome_class": race["outcome_class"],
            "swap_count": len(added), "single_swap": len(added) == 1,
            "added_horse_ids": ";".join(sorted(added)), "removed_horse_ids": ";".join(sorted(removed)),
            "added_actual_top3_count": add_hits, "removed_actual_top3_count": remove_hits,
            "retained_actual_top3_count": retained_hits, "actual_top3_missed_by_both_count": len(top3_missed_by_both),
            "baseline_top3_captured": baseline_capture, "selector_top3_captured": selector_capture,
            "raw_prior_delta": energy["raw_prior_delta"], "head_set_energy_delta": energy["head_set_energy_delta"],
            "energy_reconstruction_residual": energy["decomposition_residual"],
        }
        race_rows.append(race_record)
        for role, ids in (("added", added), ("removed", removed)):
            for horse_id in sorted(ids, key=lambda hid: int(by_horse[hid]["score_rank"])):
                horse = by_horse[horse_id]
                runner_record: dict[str, Any] = {
                    "race_id": race_id, "race_date": race["race_date"], "year": race["year"], "distance_m": race["distance_m"],
                    "primary_cohort": bool(race["primary"]), "outcome_class": race["outcome_class"], "swap_count": len(added), "role": role,
                    "horse_id": horse_id, "horse_number": int(horse["horse_number"]), "baseline_raw_score_rank": int(horse["score_rank"]),
                    "raw_score": float(horse["score"]), "actual_top3": int(horse_id in actual_top3),
                }
                for col in [
                    "observed_starts", "same_starts", "same_valid_times", "days_since_start", "last_time_s", "mean5_s", "valid_n5",
                    "best5_s", "fast2mean5_s", "std5_s", "previous3_mean_s", "previous3_valid_n", "valid_n3", "trend_s",
                    "mean5_rank_fraction", "hist_s1f_relpos_mean5", "hist_s1f_relpos_n",
                    "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
                    "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
                ]:
                    runner_record[col] = clean(horse[col])
                runner_rows.append(runner_record)
    contrast_metrics = [
        "baseline_raw_score_rank", "raw_score", "observed_starts", "same_starts", "same_valid_times", "days_since_start",
        "last_time_s", "mean5_s", "valid_n5", "valid_n3", "best5_s", "fast2mean5_s", "std5_s", "previous3_mean_s",
        "previous3_valid_n", "trend_s", "mean5_rank_fraction", "hist_s1f_relpos_mean5", "hist_s1f_relpos_n",
        "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n", "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
    ]
    contrast_rows: list[dict[str, Any]] = []
    for cohort in ("primary", "secondary"):
        for status in ["all_changed", *OUTCOME_CLASSES]:
            status_rows = [
                row for row in runner_rows
                if row["primary_cohort"] == (cohort == "primary")
                and (status == "all_changed" or row["outcome_class"] == status)
            ]
            race_ids = {row["race_id"] for row in status_rows}
            race_subset = [row for row in race_rows if row["race_id"] in race_ids]
            for metric in contrast_metrics:
                if metric in FORM_COLUMNS or metric in {"previous3_mean_s"}:
                    distances: list[str | float] = sorted({float(row["distance_m"]) for row in status_rows})
                else:
                    distances = ["all"]
                for distance in distances:
                    filtered = [row for row in status_rows if distance == "all" or float(row["distance_m"]) == float(distance)]
                    add_by_race: dict[str, list[float]] = defaultdict(list)
                    rem_by_race: dict[str, list[float]] = defaultdict(list)
                    add_runner_values: list[float] = []
                    rem_runner_values: list[float] = []
                    for row in filtered:
                        value = row.get(metric)
                        if value is None: continue
                        numeric = float(value)
                        (add_by_race if row["role"] == "added" else rem_by_race)[row["race_id"]].append(numeric)
                        (add_runner_values if row["role"] == "added" else rem_runner_values).append(numeric)
                    race_diffs = []
                    single_diffs = []
                    for item in race_subset:
                        if distance != "all" and float(item["distance_m"]) != float(distance): continue
                        a = add_by_race.get(item["race_id"], [])
                        r = rem_by_race.get(item["race_id"], [])
                        if a and r: race_diffs.append(float(np.mean(a) - np.mean(r)))
                        if item["single_swap"] and a and r: single_diffs.append(float(a[0] - r[0]))
                    contrast_rows.append({
                        "cohort": cohort, "outcome_class": status, "distance_m": distance, "metric": metric,
                        "changed_races": len(race_subset), "single_swap_races": sum(bool(row["single_swap"]) for row in race_subset),
                        "multi_swap_races": sum(not bool(row["single_swap"]) for row in race_subset),
                        "added_runner_n_observed": len(add_runner_values), "removed_runner_n_observed": len(rem_runner_values),
                        "runner_weighted_added_mean": float(np.mean(add_runner_values)) if add_runner_values else None,
                        "runner_weighted_removed_mean": float(np.mean(rem_runner_values)) if rem_runner_values else None,
                        "race_equal_pair_means_n": len(race_diffs),
                        "race_equal_mean_added_minus_removed": float(np.mean(race_diffs)) if race_diffs else None,
                        "single_swap_pair_n": len(single_diffs),
                        "single_swap_mean_added_minus_removed": float(np.mean(single_diffs)) if single_diffs else None,
                    })
    return race_rows, runner_rows, contrast_rows


def energy_summary_rows(energy_rows: list[dict[str, Any]], race_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status_by_race = {row["race_id"]: row["outcome_class"] for row in race_rows}
    detail_cols = [key for key in energy_rows[0] if key.startswith("contrib_") and not key.startswith("contrib_group_")]
    group_cols = [key for key in energy_rows[0] if key.startswith("contrib_group_")]
    metrics = ["raw_prior_delta", *detail_cols, *group_cols, "head_set_energy_delta"]
    summaries: list[dict[str, Any]] = []
    primary_by_race = {row["race_id"]: bool(row["primary_cohort"]) for row in race_rows}
    for cohort in ("primary", "secondary"):
        for status in ["all_changed", *OUTCOME_CLASSES]:
            selected = [
                row for row in energy_rows
                if primary_by_race[row["race_id"]] == (cohort == "primary")
                and (status == "all_changed" or status_by_race[row["race_id"]] == status)
            ]
            for metric in metrics:
                values = np.asarray([float(row[metric]) for row in selected], dtype=float)
                summaries.append({
                    "cohort": cohort, "outcome_class": status, "metric": metric, "changed_races": len(selected),
                    "race_equal_mean": float(values.mean()) if len(values) else None,
                    "race_equal_median": float(np.median(values)) if len(values) else None,
                    "race_equal_q25": float(np.quantile(values, .25)) if len(values) else None,
                    "race_equal_q75": float(np.quantile(values, .75)) if len(values) else None,
                })
    return summaries


def validate_labels_and_replay(roster: pd.DataFrame, choices: list[dict[str, Any]], outcome_rows: list[dict[str, Any]]) -> dict[str, Any]:
    choice_by = {str(row["race_id"]): row for row in choices}
    outcome_by = {str(row["race_id"]): row for row in outcome_rows}
    complete_rank_races = 0
    baseline_capture_match = 0
    selector_capture_match = 0
    for race_id, group in roster.groupby("race_id", sort=False):
        race_id = str(race_id)
        ranks = pd.to_numeric(group["finish_position"], errors="raise").astype(int).tolist()
        require(sorted(ranks) == list(range(1, len(group) + 1)), f"evaluation rank roster is incomplete: {race_id}")
        require(sum(rank <= 3 for rank in ranks) == 3, f"evaluation race lacks exactly three Top3 labels: {race_id}")
        complete_rank_races += 1
        actual = {str(row["horse_id"]) for row in group.loc[group["finish_position"] <= 3, ["horse_id"]].to_dict(orient="records")}
        choice = choice_by[race_id]
        result = outcome_by[race_id]
        baseline_count = len(actual & exact_set(choice["baseline_top5_horse_ids"]))
        selector_count = len(actual & exact_set(choice["selector_top5_horse_ids"]))
        require(baseline_count == int(result["baseline_captured_top3"]), f"baseline Top3 capture mismatch: {race_id}")
        require(selector_count == int(result["selector_captured_top3"]), f"selector Top3 capture mismatch: {race_id}")
        baseline_capture_match += 1
        selector_capture_match += 1
    require(complete_rank_races == FULL_N, "evaluation race rank verification did not cover full cohort")
    return {
        "complete_rank_races": complete_rank_races,
        "baseline_runner_truth_capture_matches": baseline_capture_match,
        "selector_runner_truth_capture_matches": selector_capture_match,
        "status": "PASS",
    }


def output_inventory(exclude: set[str] | None = None) -> list[dict[str, Any]]:
    excluded = exclude or set()
    return [
        {"path": str(path.relative_to(HERE)), "bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted(HERE.rglob("*"))
        if path.is_file() and path.name not in excluded and "__pycache__" not in path.parts
    ]


def update_receipt(source_hashes: dict[str, str], audit: dict[str, Any], model_receipt: dict[str, Any] | None = None) -> None:
    previous_path = OUT / "ANALYSIS_RECEIPT.json"
    previous = load_json(previous_path) if previous_path.exists() else {}
    if model_receipt is None:
        model_receipt = previous.get("model_receipt")
        source_hashes = previous.get("source_hashes", source_hashes)
    inventory = output_inventory(exclude={"ANALYSIS_RECEIPT.json"})
    total_bytes = sum(item["bytes"] for item in inventory)
    require(total_bytes < 10 * 1024 * 1024, f"research output exceeded 10 MiB: {total_bytes}")
    payload = {
        "status": "PASS",
        "study": "20261025_top5_direct_gain_loss_v1",
        "objective": "retrospective gain/loss diagnosis for the frozen primary Top5 selector comparison",
        "locked_plan_sha256": PLAN_SHA,
        "analysis_code_sha256": sha256(HERE / "analyze_gain_loss.py"),
        "root_plan_review_sha256": ROOT_REVIEW_SHA,
        "source_hash_metadata_correction_sha256": SOURCE_CORRECTION_SHA,
        "source_hashes": source_hashes,
        "source_paths": source_path_inventory(),
        "source_audit_counts": audit,
        "model_receipt": model_receipt,
        "outputs_excluding_receipt": inventory,
        "outputs_bytes_excluding_receipt": total_bytes,
        "storage_limit_bytes": 10 * 1024 * 1024,
    }
    write_json(OUT / "ANALYSIS_RECEIPT.json", payload)


def analyze_phase() -> None:
    source_hashes = verify_sources()
    choices = load_choices()
    outcome_rows = load_jsonl(MAIN / "outputs/race_outcomes.jsonl")
    outcomes = load_json(MAIN / "outputs/outcomes.json")
    counts = audit_frozen_counts(choices, outcome_rows, outcomes)
    choice_receipt = load_json(MAIN / "outputs/CHOICES_RECEIPT.json")
    fit_receipt_sha = sha256(MAIN / "outputs/FIT_RECEIPT.json")
    require(choice_receipt.get("fit_receipt_sha256") == fit_receipt_sha, "choices and fit receipt disagree")
    source_hashes["fit_receipt"] = fit_receipt_sha
    source_hashes["outcome_receipt"] = sha256(MAIN / "outputs/OUTCOME_RECEIPT.json")

    # Condition features and choices are read first. Evaluation labels are loaded
    # only afterward via a separate one-column allowlist for runner-level truth.
    pregame = read_pregame()
    pregame_profile_payload = pregame_profile(pregame, choices)
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "PREGAME_PROFILE.json", pregame_profile_payload | {"source_hashes": source_hashes})
    labels = read_labels_only(pregame)
    roster = add_outcomes_to_roster(pregame, labels)
    roster = pd.concat([score_ranked(group) for _, group in roster.groupby("race_id", sort=False)], ignore_index=True)
    replay = validate_labels_and_replay(roster, choices, outcome_rows)
    races, _ranked = build_race_data(roster, choices, outcome_rows)
    require(races.loc[races["primary"], "outcome_class"].value_counts().to_dict() == {"both_miss": 1033, "both_hit": 404, "lost": 35, "caught": 31}, "primary race outcome labels changed")
    primary = races.loc[races["primary"]].copy()
    actual_top3_by_race = {
        str(race_id): {str(row["horse_id"]) for row in group.loc[group["finish_position"] <= 3, ["horse_id"]].to_dict(orient="records")}
        for race_id, group in roster.groupby("race_id", sort=False)
    }
    primary["score5_actual_top3"] = primary.apply(lambda row: int(str(row["score5_horse_id"]) in actual_top3_by_race[str(row["race_id"])]), axis=1)
    source_hashes["bootstrap_receipt"] = sha256(BOOTSTRAP_RECEIPT)
    audit_payload = {
        **counts,
        "source_hashes": source_hashes,
        "source_paths": source_path_inventory(),
        "source_sizes_bytes": {
            "choices": (MAIN / "outputs/candidate_choices.jsonl").stat().st_size,
            "choices_receipt": (MAIN / "outputs/CHOICES_RECEIPT.json").stat().st_size,
            "race_outcomes": (MAIN / "outputs/race_outcomes.jsonl").stat().st_size,
            "outcomes": (MAIN / "outputs/outcomes.json").stat().st_size,
        },
        "label_replay": replay,
        "baseline_manifest_note": "The preserved main manifest has a mistyped baseline SHA. This study binds the verified parquet SHA, consistent with the original choice receipt, prior root source audit and new metadata correction receipt; the preserved old manifest was not edited.",
    }
    write_json(OUT / "SOURCE_AUDIT.json", audit_payload)

    condition_rows = condition_summary(races, choices)
    models, model_receipt = load_models()
    source_hashes["fit_receipt"] = model_receipt["fit_receipt_sha256"]
    for year, model_sha in model_receipt["model_sha256"].items():
        source_hashes[f"model_{year}"] = model_sha
    energy_rows = energy_decomposition(pregame, choices, models)
    changed_races, changed_runners, changed_contrasts = changed_ledgers(roster, races, choices, energy_rows)
    energy_summaries = energy_summary_rows(energy_rows, changed_races)
    form_summaries = boundary_form_summary(roster, races)
    gap_summaries = gap_continuous_summary(races)

    write_csv(OUT / "PRIMARY_RACE_LEDGER.csv", primary.to_dict(orient="records"))
    write_csv(OUT / "PRIMARY_CONDITION_SUMMARIES.csv", condition_rows)
    write_csv(OUT / "BOUNDARY_FORM_STYLE_SUMMARY.csv", form_summaries)
    write_csv(OUT / "GAP_CONTINUOUS_SUMMARY.csv", gap_summaries)
    write_csv(OUT / "CHANGED_RACE_LEDGER.csv", changed_races)
    write_csv(OUT / "CHANGED_RUNNER_LEDGER.csv", changed_runners)
    write_csv(OUT / "CHANGED_RUNNER_CONTRASTS.csv", changed_contrasts)
    write_csv(OUT / "ENERGY_DECOMPOSITION.csv", energy_rows)
    write_csv(OUT / "ENERGY_DECOMPOSITION_SUMMARY.csv", energy_summaries)
    update_receipt(source_hashes, audit_payload, model_receipt)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("audit", "profile", "analyze", "receipt"), default="audit")
    args = parser.parse_args()
    if args.phase == "audit":
        audit_phase()
    elif args.phase == "profile":
        profile_phase()
    elif args.phase == "analyze":
        analyze_phase()
    else:
        source_hashes = verify_sources()
        update_receipt(source_hashes, load_json(OUT / "SOURCE_AUDIT.json"), None)


if __name__ == "__main__":
    main()
