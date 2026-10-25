#!/usr/bin/env python3
"""Independent replay of the frozen gain/loss diagnosis artifacts.

This script reads frozen source artifacts and the gain/loss study outputs. It
writes only VERIFICATION.json in this review's owned directory.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[3]
REVIEW = Path(__file__).resolve().parent
MAIN = ROOT / "jeju/research/20261025_top5_direct_learning_v1"
GAIN = ROOT / "jeju/research/20261025_top5_direct_gain_loss_v1"
OUT = GAIN / "outputs"
BASE = ROOT / "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
BOOTSTRAP = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
ROOT_REVIEW = ROOT / "jeju/research/20261025_top5_direct_gain_loss_rootreview_v1/ROOT_PLAN_REVIEW.json"
SOURCE_CORRECTION = ROOT / "jeju/research/20261025_top5_direct_gain_loss_rootreview_v1/SOURCE_HASH_METADATA_CORRECTION.json"

EXPECTED = {
    "plan": "cc0a1019d034287e10d74ea8fbb6a0288e79342a4d0d86fa1d2bc971c13ac5fa",
    "main_manifest": "29cb6310bbecf79245b69ddc43521d01257b80a99f802e48840742a0752dc8e5",
    "baseline": "c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1",
    "features": "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
    "choices": "eacbea0404a41dd70872a9936a9547804579b3e41ca13386e84924ec06899545",
    "choice_receipt": "13ab7d8f6aadab64771c43a73fcd7e813a10eb7268be0dcc7680cdf2bd7f5754",
    "race_outcomes": "e6d12fb52d01a15b2144a5ff4282ac337cedd13f764f4eb19895dc48b24c7e3f",
    "outcomes": "669fcf5067c029ab1d0b3c4c00ce1dd1b8bbe9f0d03d43a4fc18c7aaf2c9888d",
    "schedule": "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
    "schedule_receipt": "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e",
    "root_plan_review": "56c6f646f05f25bf786676bcabc6e57a908d0a31bd4092ee7aac7ccb8bc3a2a4",
    "source_correction": "dfa60f6e7ced44f6c565be406a6cbd5e6784da74c5752d9dada608c7e8bd648d",
}
PRIMARY_DISTANCES = {900.0, 1000.0, 1110.0, 1200.0}
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
STYLE_COLUMNS = [
    ("hist_s1f_relpos_mean5", "hist_s1f_relpos_n"),
    ("hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n"),
    ("hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n"),
]
FORM_COLUMNS = ["last_time_s", "mean5_s", "best5_s", "fast2mean5_s", "std5_s", "trend_s"]
OUTCOME_CLASSES = ["caught", "lost", "both_hit", "both_miss"]


def require(test: bool, message: str) -> None:
    if not test:
        raise AssertionError(message)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def near(a: Any, b: Any, atol: float = 2e-10) -> bool:
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return (a is None or pd.isna(a)) and (b is None or pd.isna(b))
    return bool(np.isclose(float(a), float(b), atol=atol, rtol=0))


def as_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes"}


def fmt(value: Any) -> str:
    if value is None or pd.isna(value):
        return "missing"
    if isinstance(value, (np.integer, int)):
        return str(int(value))
    if isinstance(value, (np.floating, float)):
        return f"{float(value):g}"
    return str(value)


def outcome_class(base_hit: int, head_hit: int) -> str:
    if base_hit == 3 and head_hit < 3:
        return "lost"
    if head_hit == 3 and base_hit < 3:
        return "caught"
    if base_hit == head_hit == 3:
        return "both_hit"
    return "both_miss"


def bucket_starts(value: Any) -> str:
    if pd.isna(value): return "missing"
    value = int(value)
    return "0" if value == 0 else ("1-4" if value <= 4 else "5+")


def bucket_valid_n5(value: Any) -> str:
    if pd.isna(value): return "missing"
    value = int(value)
    return "0" if value == 0 else ("1-2" if value <= 2 else "3-5")


def bucket_same(value: Any) -> str:
    if pd.isna(value): return "missing"
    value = int(value)
    return "0" if value == 0 else ("1" if value == 1 else "2+")


def bucket_recency(value: Any) -> str:
    if pd.isna(value): return "missing"
    value = float(value)
    return "<15" if value < 15 else ("15-28" if value <= 28 else ("29-60" if value <= 60 else "61+"))


def bucket_gap(value: float) -> str:
    return "<=0.10" if value <= 0.10 else ("(0.10,0.25]" if value <= 0.25 else ">0.25")


def audit_lock_and_sources() -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = read_json(OUT / "ANALYSIS_RECEIPT.json")
    require(receipt.get("status") == "PASS", "main analysis receipt is not PASS")
    require(sha(GAIN / "PLAN_LOCK.md") == EXPECTED["plan"] == receipt["locked_plan_sha256"], "locked plan hash mismatch")
    require(sha(GAIN / "analyze_gain_loss.py") == receipt["analysis_code_sha256"], "main code hash differs from its receipt")
    paths = {
        "plan": GAIN / "PLAN_LOCK.md",
        "main_manifest": MAIN / "FINAL_MANIFEST.json",
        "baseline": BASE,
        "features": FEATURES,
        "choices": MAIN / "outputs/candidate_choices.jsonl",
        "choice_receipt": MAIN / "outputs/CHOICES_RECEIPT.json",
        "race_outcomes": MAIN / "outputs/race_outcomes.jsonl",
        "outcomes": MAIN / "outputs/outcomes.json",
        "schedule": BOOTSTRAP,
        "schedule_receipt": BOOTSTRAP_RECEIPT,
        "root_plan_review": ROOT_REVIEW,
        "source_correction": SOURCE_CORRECTION,
    }
    actual = {key: sha(path) for key, path in paths.items()}
    receipt_key = {
        "plan": "locked_plan_sha256",
        "choice_receipt": "choices_receipt",
        "schedule": "bootstrap",
        "schedule_receipt": "bootstrap_receipt",
        "root_plan_review": "root_plan_review_sha256",
        "source_correction": "source_hash_metadata_correction_sha256",
    }
    for key, value in EXPECTED.items():
        require(actual[key] == value, f"frozen {key} source hash mismatch")
        require(receipt["source_hashes"][receipt_key.get(key, key)] == value, f"main receipt {key} hash mismatch")
    root_review = read_json(ROOT_REVIEW)
    correction = read_json(SOURCE_CORRECTION)
    require(root_review.get("approved") is True and root_review.get("plan_sha256") == EXPECTED["plan"], "root plan approval mismatch")
    require(correction.get("correct_source_sha256") == EXPECTED["baseline"], "baseline correction receipt mismatch")
    manifest = read_json(paths["main_manifest"])
    wrong = manifest["frozen_sources"]["evaluation_raw_score_and_roster"]["sha256"]
    require(wrong == correction["incorrect_value_in_preserved_manifest"], "unexpected old manifest typo value")
    require(wrong != EXPECTED["baseline"], "expected metadata discrepancy is not present")
    require(receipt["source_hashes"]["baseline_manifest_metadata_mismatch"] is True, "main receipt did not disclose metadata typo")
    for artifact in receipt["outputs_excluding_receipt"]:
        path = (GAIN / artifact["path"]) if not artifact["path"].startswith("outputs/") else (GAIN / artifact["path"])
        require(path.is_file() and sha(path) == artifact["sha256"], f"main output receipt mismatch: {artifact['path']}")
        require(path.stat().st_size == artifact["bytes"], f"main output size mismatch: {artifact['path']}")
    total = sum(item["bytes"] for item in receipt["outputs_excluding_receipt"])
    require(total == receipt["outputs_bytes_excluding_receipt"] < 10 * 1024 * 1024, "main output size/cap mismatch")
    return receipt, actual


def read_sources() -> tuple[pd.DataFrame, dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    base_cols = ["api_record_id", "race_id", "race_date", "year", "distance_m", "grade_raw", "horse_id", "horse_number", "field_n", "score", "y"]
    feature_cols = [
        "api_record_id", "race_id", "race_date", "year", "distance_m", "horse_id", "horse_number", "field_n", "history_cutoff", "latest_history_date",
        "observed_starts", "same_starts", "same_valid_times", "days_since_start", "last_time_s", "mean5_s", "valid_n5", "best5_s",
        "fast2mean5_s", "std5_s", "previous3_mean_s", "previous3_valid_n", "valid_n3", "trend_s", "mean5_rank_fraction",
        "hist_s1f_relpos_mean5", "hist_s1f_relpos_n", "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
        "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
    ]
    base = pq.read_table(BASE, columns=base_cols).to_pandas()
    features = pq.read_table(FEATURES, columns=feature_cols).to_pandas()
    labels = pq.read_table(FEATURES, columns=["api_record_id", "finish_position"]).to_pandas()
    require(len(base) == 17412 and base["api_record_id"].is_unique, "baseline runner roster integrity failed")
    require(features["api_record_id"].is_unique and labels["api_record_id"].is_unique, "feature/label key uniqueness failed")
    features = features.loc[features.api_record_id.isin(base.api_record_id)].copy()
    labels = labels.loc[labels.api_record_id.isin(base.api_record_id)].copy()
    require(len(features) == len(labels) == len(base), "evaluation feature or label coverage mismatch")
    f = base.merge(features, on="api_record_id", how="inner", suffixes=("_base", ""), validate="one_to_one")
    f = f.merge(labels, on="api_record_id", how="inner", validate="one_to_one")
    require(len(f) == len(base), "evaluation roster changed during joins")
    for col in ("race_id", "race_date", "horse_id", "horse_number", "field_n"):
        require((f[f"{col}_base"].astype(str) == f[col].astype(str)).all(), f"source roster mismatch for {col}")
    require((pd.to_numeric(f["distance_m_base"]) == pd.to_numeric(f["distance_m"])).all(), "source distance mismatch")
    require((pd.to_numeric(f["year_base"]) == pd.to_numeric(f["year"])).all(), "source year mismatch")
    race_date = pd.to_datetime(f["race_date"], errors="raise").dt.date
    cutoff = pd.to_datetime(f["history_cutoff"], errors="raise").dt.date
    latest = pd.to_datetime(f["latest_history_date"], errors="coerce").dt.date
    require((cutoff == race_date - pd.Timedelta(days=2)).all(), "feature history cutoff is not T-2")
    require(((latest.isna()) | (latest <= cutoff)).all(), "feature history exceeds T-2 cutoff")
    require(not f.horse_id.astype(str).eq("3005648").any(), "excluded horse 3005648 appears")
    require((pd.to_numeric(f["y"], errors="raise").astype(int) == pd.to_numeric(f["finish_position"], errors="raise").le(3).astype(int)).all(), "frozen y disagrees with finish ranks")
    require(set(pd.to_numeric(f["y"], errors="raise").astype(int).unique()) <= {0, 1}, "evaluation y is not binary")

    choices = {str(row["race_id"]): row for row in read_jsonl(MAIN / "outputs/candidate_choices.jsonl")}
    outcomes = {str(row["race_id"]): row for row in read_jsonl(MAIN / "outputs/race_outcomes.jsonl")}
    require(len(choices) == len(outcomes) == 1779, "frozen race artifact count mismatch")
    require(set(choices) == set(outcomes), "choice/outcome race IDs differ")
    return f, choices, outcomes, read_json(MAIN / "outputs/outcomes.json")


def build_races(frame: pd.DataFrame, choices: dict[str, dict[str, Any]], outcomes: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, pd.DataFrame]]:
    races: list[dict[str, Any]] = []
    actual_by_race: dict[str, set[str]] = {}
    groups: dict[str, pd.DataFrame] = {}
    for rid, group in frame.groupby("race_id", sort=True):
        rid = str(rid)
        c = choices[rid]
        g = group.sort_values(["score", "horse_number"], ascending=[False, True], kind="mergesort").copy()
        require(sorted(pd.to_numeric(g.finish_position).astype(int).tolist()) == list(range(1, len(g) + 1)), f"race ranks not complete: {rid}")
        require(int(pd.to_numeric(g.y).sum()) == 3, f"race does not have exactly three y labels: {rid}")
        require(str(pd.to_datetime(g.race_date_base.iloc[0]).date()) == str(c["race_date"]), f"choice date mismatch: {rid}")
        require(int(g.year_base.iloc[0]) == int(c["year"]), f"choice year mismatch: {rid}")
        require(float(g.distance_m_base.iloc[0]) == float(c["distance_m"]), f"choice distance mismatch: {rid}")
        require(len(g) == int(c["field_n"]) == int(g.field_n_base.iloc[0]), f"choice field size mismatch: {rid}")
        ids = g.horse_id.astype(str).tolist()
        by_id = dict(zip(ids, g.to_dict(orient="records"), strict=True))
        base_ids = set(map(str, c["baseline_top5_horse_ids"]))
        head_ids = set(map(str, c["selector_top5_horse_ids"]))
        require(len(base_ids) == len(head_ids) == 5, f"choice set width mismatch: {rid}")
        require(base_ids <= set(ids) and head_ids <= set(ids), f"choice includes nonstarter: {rid}")
        require(base_ids == set(ids[:5]), f"raw Top5 rank replay failed: {rid}")
        number_by_id = {str(row["horse_id"]): int(row["horse_number"]) for row in g.to_dict(orient="records")}
        require([number_by_id[x] for x in c["baseline_top5_horse_ids"]] == list(map(int, c["baseline_top5_horse_numbers"])), f"baseline ID/number mismatch: {rid}")
        require([number_by_id[x] for x in c["selector_top5_horse_ids"]] == list(map(int, c["selector_top5_horse_numbers"])), f"selector ID/number mismatch: {rid}")
        actual = set(g.loc[pd.to_numeric(g.finish_position).le(3), "horse_id"].astype(str))
        actual_by_race[rid] = actual
        result = outcomes[rid]
        bcap, hcap = len(actual & base_ids), len(actual & head_ids)
        require(bcap == int(result["baseline_captured_top3"]), f"baseline capture replay mismatch: {rid}")
        require(hcap == int(result["selector_captured_top3"]), f"selector capture replay mismatch: {rid}")
        status = outcome_class(bcap, hcap)
        require(status == outcome_class(int(result["baseline_captured_top3"]), int(result["selector_captured_top3"])), f"outcome class mismatch: {rid}")
        added, removed = head_ids - base_ids, base_ids - head_ids
        require(len(added) == len(removed), f"swap additions/removals not balanced: {rid}")
        fifth = g.iloc[4]
        sixth = g.iloc[5]
        scores = pd.to_numeric(g.score, errors="raise").to_numpy(dtype=np.float64)
        gap = float(scores[4] - scores[5])
        sd = float(scores.std(ddof=0))
        zgap = gap / sd if sd else 0.0
        d = float(c["distance_m"])
        rec = {
            "race_id": rid, "race_date": str(c["race_date"]), "year": int(c["year"]), "distance_m": d,
            "grade_raw": fifth.get("grade_raw"), "field_n": int(c["field_n"]), "primary": d in PRIMARY_DISTANCES,
            "changed": bool(added), "swap_count": len(added), "status": status, "base_hit": bcap == 3, "head_hit": hcap == 3,
            "baseline_hits": bcap, "selector_hits": hcap, "caught": status == "caught", "lost": status == "lost",
            "both_hit": status == "both_hit", "both_miss": status == "both_miss", "raw_gap": gap, "z_gap": zgap,
            "z_gap_bin": bucket_gap(zgap), "score5_horse_id": str(fifth.horse_id),
        }
        for col in [
            "observed_starts", "same_starts", "same_valid_times", "days_since_start", "valid_n5", "valid_n3", "previous3_valid_n",
            "last_time_s", "mean5_s", "best5_s", "fast2mean5_s", "std5_s", "trend_s", "mean5_rank_fraction",
            "hist_s1f_relpos_mean5", "hist_s1f_relpos_n", "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
            "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
        ]:
            rec[f"score5_{col}"] = fifth[col]
        races.append(rec)
        groups[rid] = g
    require(len(races) == 1779 and sum(row["primary"] for row in races) == 1503, "fixed full/primary race counts changed")
    classes = Counter(row["status"] for row in races if row["primary"])
    require(dict(classes) == {"both_hit": 404, "both_miss": 1033, "caught": 31, "lost": 35}, f"primary outcome classes changed: {classes}")
    require(sum(row["changed"] and row["primary"] for row in races) == 254 and sum(row["changed"] for row in races) == 304, "changed-set counts changed")
    return races, actual_by_race, groups


def bootstrap_group(group: list[dict[str, Any]], all_dates: list[str], schedule: np.ndarray) -> dict[str, Any]:
    n_by_date = np.zeros(len(all_dates), dtype=np.int64)
    delta_by_date = np.zeros(len(all_dates), dtype=np.int64)
    index = {d: i for i, d in enumerate(all_dates)}
    for row in group:
        i = index[row["race_date"]]
        n_by_date[i] += 1
        delta_by_date[i] += int(row["caught"]) - int(row["lost"])
    den = n_by_date[schedule].sum(axis=1, dtype=np.int64)
    num = delta_by_date[schedule].sum(axis=1, dtype=np.int64)
    valid = den > 0
    if not valid.all():
        return {"bootstrap_lower95_pp": None, "bootstrap_upper95_pp": None, "bootstrap_valid_replicates": int(valid.sum()), "bootstrap_zero_group_replicates": int((~valid).sum()), "bootstrap_status": "undefined_zero_group_resample"}
    q = np.quantile(100.0 * num / den, [0.025, 0.975], method="linear")
    return {"bootstrap_lower95_pp": float(q[0]), "bootstrap_upper95_pp": float(q[1]), "bootstrap_valid_replicates": len(den), "bootstrap_zero_group_replicates": 0, "bootstrap_status": "defined_exploratory_date_cluster_ci"}


def expected_conditions(races: list[dict[str, Any]], schedule: np.ndarray, dates: list[str]) -> dict[tuple[str, str], dict[str, Any]]:
    primary = [row for row in races if row["primary"]]
    specs: list[tuple[str, str, Any]] = [
        ("year", "evaluation year", lambda r: str(r["year"])),
        ("distance_m", "race distance in meters", lambda r: fmt(r["distance_m"])),
        ("grade_raw", "source grade_raw category", lambda r: fmt(r["grade_raw"])),
        ("field_n", "exact field size", lambda r: str(r["field_n"])),
        ("z_gap_bin", "fifth-minus-sixth raw-score gap / within-race score SD", lambda r: r["z_gap_bin"]),
        ("score5_observed_starts_bin", "baseline Top5 boundary runner career starts", lambda r: bucket_starts(r["score5_observed_starts"])),
        ("score5_valid_n5_bin", "baseline Top5 boundary runner valid recent times", lambda r: bucket_valid_n5(r["score5_valid_n5"])),
        ("score5_same_valid_times_bin", "baseline Top5 boundary runner same-distance valid times", lambda r: bucket_same(r["score5_same_valid_times"])),
        ("score5_days_since_start_bin", "baseline Top5 boundary runner days since prior start", lambda r: bucket_recency(r["score5_days_since_start"])),
    ]
    for _, support in STYLE_COLUMNS:
        key = f"score5_{support}"
        specs.append((key, f"boundary runner {support} exact support", lambda r, k=key: fmt(r[k])))
    specs.append(("year_by_distance", "only cross-tab: year × distance", lambda r: f"{r['year']}-{int(r['distance_m'])}"))
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for cond, desc, getter in specs:
        values = sorted({getter(r) for r in primary})
        for value in values:
            g = [r for r in primary if getter(r) == value]
            n = len(g)
            caught = sum(r["caught"] for r in g)
            lost = sum(r["lost"] for r in g)
            base_hits = sum(r["base_hit"] for r in g)
            head_hits = sum(r["head_hit"] for r in g)
            stats = {
                "condition": cond, "condition_value": str(value), "n_races": n,
                "changed_races": sum(r["changed"] for r in g), "caught": caught, "lost": lost,
                "both_hit": sum(r["both_hit"] for r in g), "both_miss": sum(r["both_miss"] for r in g),
                "baseline_all_three_hits": base_hits, "selector_all_three_hits": head_hits,
                "baseline_hit_rate": base_hits / n, "selector_hit_rate": head_hits / n,
                "net_delta_races_caught_minus_lost": caught - lost,
                "net_delta_pp_full_condition_denominator": 100.0 * (caught - lost) / n,
                "small_sample_n_lt_30": n < 30, "description": desc,
            }
            stats.update(bootstrap_group(g, dates, schedule))
            result[(cond, str(value))] = stats
    return result


def check_condition_output(races: list[dict[str, Any]]) -> int:
    path = OUT / "PRIMARY_CONDITION_SUMMARIES.csv"
    table = pd.read_csv(path, dtype={"condition": str, "condition_value": str})
    dates = sorted({row["race_date"] for row in races if row["primary"]})
    schedule = np.load(BOOTSTRAP, allow_pickle=False)
    require(schedule.shape == (2000, 269) and schedule.dtype == np.int32, "bootstrap schedule dimensions changed")
    require(sha(BOOTSTRAP_RECEIPT) == EXPECTED["schedule_receipt"], "bootstrap receipt hash changed")
    expected = expected_conditions(races, schedule, dates)
    actual = {(row.condition, row.condition_value): row._asdict() for row in table.itertuples(index=False)}
    require(set(actual) == set(expected), "condition-cell inventory differs")
    for key, want in expected.items():
        got = actual[key]
        for col, val in want.items():
            if col in {"condition", "condition_value", "description", "small_sample_n_lt_30", "bootstrap_status", "bootstrap_valid_replicates", "bootstrap_zero_group_replicates"}:
                require(str(got[col]) == str(val), f"condition cell {key} field {col} mismatch")
            elif val is None:
                require(pd.isna(got[col]), f"condition cell {key} expected undefined {col}")
            else:
                require(near(got[col], val, atol=1e-10), f"condition cell {key} field {col} mismatch: {got[col]} != {val}")
    require(sum(1 for c, _ in actual if c == "year_by_distance") <= 12, "unexpected cross-tabs beyond year × distance")
    return len(actual)


def check_primary_race_ledger(races: list[dict[str, Any]]) -> int:
    table = pd.read_csv(OUT / "PRIMARY_RACE_LEDGER.csv", dtype={"race_id": str})
    expected = {row["race_id"]: row for row in races if row["primary"]}
    got = {str(row.race_id): row._asdict() for row in table.itertuples(index=False)}
    require(len(got) == 1503 and set(got) == set(expected), "primary race ledger race IDs/count mismatch")
    for rid, row in expected.items():
        g = got[rid]
        require(int(g["year"]) == row["year"] and float(g["distance_m"]) == row["distance_m"], f"primary race metadata mismatch: {rid}")
        require(str(g["outcome_class"]) == row["status"] and as_bool(g["selection_changed"]) == row["changed"], f"primary race class/change mismatch: {rid}")
        require(int(g["field_n"]) == row["field_n"] and int(g["swap_count"]) == row["swap_count"], f"primary race size mismatch: {rid}")
        for col, val in (("raw_score_5_6_gap", row["raw_gap"]), ("z_score_5_6_gap", row["z_gap"])):
            require(near(g[col], val), f"primary race gap mismatch: {rid} {col}")
    return len(got)


def check_gap_summary(races: list[dict[str, Any]]) -> int:
    table = pd.read_csv(OUT / "GAP_CONTINUOUS_SUMMARY.csv", dtype={"outcome_class": str, "metric": str})
    primary = [r for r in races if r["primary"]]
    specs = [("all_primary", primary)] + [(name, [r for r in primary if r["status"] == name]) for name in OUTCOME_CLASSES]
    expected: dict[tuple[str, str], dict[str, Any]] = {}
    for status, group in specs:
        for metric, key, unit in (("raw_score_5_6_gap", "raw_gap", "raw F1_STYLE6 score units"), ("z_score_5_6_gap", "z_gap", "within-race population SD units")):
            vals = np.asarray([r[key] for r in group], dtype=float)
            expected[(status, metric)] = {
                "unit": unit, "n_races": len(group), "n": len(vals), "mean": vals.mean(), "median": np.median(vals),
                "q25": np.quantile(vals, .25), "q75": np.quantile(vals, .75),
            }
    actual = {(r.outcome_class, r.metric): r._asdict() for r in table.itertuples(index=False)}
    require(set(actual) == set(expected), "continuous gap summary inventory mismatch")
    for key, want in expected.items():
        got = actual[key]
        for col, val in want.items():
            if col == "unit":
                require(str(got[col]) == str(val), f"continuous gap summary mismatch {key} {col}")
            else:
                require(near(got[col], val), f"continuous gap summary mismatch {key} {col}")
    return len(actual)


def check_support4_overlap(races: list[dict[str, Any]]) -> dict[str, Any]:
    primary = [r for r in races if r["primary"]]
    relpos4 = {
        r["race_id"] for r in primary
        if r["status"] == "lost" and fmt(r["score5_hist_s1f_relpos_n"]) == "4"
    }
    pair4 = {
        r["race_id"] for r in primary
        if r["status"] == "lost" and fmt(r["score5_hist_s1f_to_c4_pair_n"]) == "4"
    }
    require(len(relpos4) == len(pair4) == 4 and relpos4 == pair4, "support-4 adverse cells do not share the same four lost races")
    table = pd.read_csv(OUT / "PRIMARY_CONDITION_SUMMARIES.csv", dtype={"condition": str, "condition_value": str})
    positive_lower = int(pd.to_numeric(table.bootstrap_lower95_pp, errors="coerce").gt(0).sum())
    negative_upper = int(pd.to_numeric(table.bootstrap_upper95_pp, errors="coerce").lt(0).sum())
    require(positive_lower == 0 and negative_upper == 2, "condition bootstrap tail-count summary changed")
    return {
        "support4_lost_races_overlap": True,
        "shared_race_ids": sorted(relpos4),
        "condition_cells_with_lower_ci_above_zero": positive_lower,
        "condition_cells_with_upper_ci_below_zero": negative_upper,
        "interpretation": "both adverse support cells refer to the same four posthoc-selected races; neither is a validated switching rule",
    }


def check_form_summary(frame: pd.DataFrame, races: list[dict[str, Any]]) -> int:
    path = OUT / "BOUNDARY_FORM_STYLE_SUMMARY.csv"
    table = pd.read_csv(path)
    require("primary_cohort" in table.columns and table.primary_cohort.map(as_bool).all(), "boundary form summary lacks primary cohort marking")
    primary = {r["race_id"]: r for r in races if r["primary"]}
    outcome = {rid: row["status"] for rid, row in primary.items()}
    boundary_rows: list[dict[str, Any]] = []
    f = frame.loc[frame.race_id.astype(str).isin(primary)].copy()
    for rid, group in f.groupby("race_id", sort=False):
        g = group.sort_values(["score", "horse_number"], ascending=[False, True], kind="mergesort")
        if len(g) >= 5:
            boundary_rows.append(g.iloc[4].to_dict() | {"race_id": str(rid), "outcome_class": outcome[str(rid)]})
    boundary = pd.DataFrame(boundary_rows)
    require(len(boundary) == 1503, "boundary runner population is not 1,503 primary races")
    distances = set(float(x) for x in table.distance_m.unique())
    require(distances == PRIMARY_DISTANCES, f"boundary form summary contains nonprimary distances: {distances}")
    grouped = {(float(r.distance_m), str(r.outcome_class)): r._asdict() for r in table.itertuples(index=False)}
    want_groups = {(float(d), str(s)) for d in PRIMARY_DISTANCES for s in OUTCOME_CLASSES if ((boundary.distance_m.astype(float) == float(d)) & (boundary.outcome_class == s)).any()}
    require(set(grouped) == want_groups, "boundary form summary group inventory mismatch")
    for key, got in grouped.items():
        d, status = key
        g = boundary.loc[boundary.distance_m.astype(float).eq(d) & boundary.outcome_class.eq(status)]
        require(int(got["n_races"]) == len(g), f"boundary form denominator mismatch: {key}")
        for col in FORM_COLUMNS:
            vals = pd.to_numeric(g[col], errors="coerce").dropna().to_numpy(dtype=float)
            require(int(got[f"{col}_n"]) == len(vals), f"form support mismatch: {key} {col}")
            if len(vals):
                for suffix, val in (("mean", vals.mean()), ("median", np.median(vals)), ("q25", np.quantile(vals, .25)), ("q75", np.quantile(vals, .75))):
                    require(near(got[f"{col}_{suffix}"], val), f"form summary mismatch: {key} {col}_{suffix}")
            require(near(got[f"{col}_support_valid_n5_mean"], pd.to_numeric(g.valid_n5).mean()), f"valid_n5 support mismatch: {key} {col}")
        for col in ["valid_n3", "previous3_valid_n", "valid_n5"]:
            vals = pd.to_numeric(g[col], errors="coerce")
            require(near(got[f"{col}_mean"], vals.mean()), f"support mean mismatch: {key} {col}")
            max_support = 5 if col == "valid_n5" else 3
            for value in range(max_support + 1):
                expected_count = int(vals.eq(value).sum())
                require(int(got[f"{col}_support_{value}"]) == expected_count, f"support distribution mismatch: {key} {col}={value}")
        for mean, support in STYLE_COLUMNS:
            vals = pd.to_numeric(g[mean], errors="coerce").dropna().to_numpy(dtype=float)
            require(int(got[f"{mean}_n"]) == len(vals), f"style mean support mismatch: {key} {mean}")
            if len(vals):
                for suffix, val in (("mean", vals.mean()), ("median", np.median(vals)), ("q25", np.quantile(vals, .25)), ("q75", np.quantile(vals, .75))):
                    require(near(got[f"{mean}_{suffix}"], val), f"style summary mismatch: {key} {mean}_{suffix}")
            support_vals = pd.to_numeric(g[support], errors="coerce")
            require(int(got[f"{support}_observed_races"]) == int(support_vals.notna().sum()), f"style support observed mismatch: {key} {support}")
            require(near(got[f"{support}_mean"], support_vals.mean()), f"style support mean mismatch: {key} {support}")
    return len(grouped)


def check_changed_ledgers(races: list[dict[str, Any]], actual_by_race: dict[str, set[str]], groups: dict[str, pd.DataFrame], choices: dict[str, dict[str, Any]]) -> tuple[int, int, dict[str, Any]]:
    changed = {r["race_id"]: r for r in races if r["changed"]}
    race_table = pd.read_csv(OUT / "CHANGED_RACE_LEDGER.csv", dtype={"race_id": str})
    require(len(race_table) == len(changed) == 304, "changed-race ledger denominator mismatch")
    race_out = {str(r.race_id): r._asdict() for r in race_table.itertuples(index=False)}
    require(set(race_out) == set(changed), "changed-race ledger identity mismatch")
    primary_counts = Counter()
    for rid, expect in changed.items():
        row = race_out[rid]
        c_base = set(map(str, choices[rid]["baseline_top5_horse_ids"]))
        c_head = set(map(str, choices[rid]["selector_top5_horse_ids"]))
        add, rem = c_head - c_base, c_base - c_head
        actual = actual_by_race[rid]
        require(set(filter(None, str(row["added_horse_ids"]).split(";"))) == add, f"added ID set mismatch: {rid}")
        require(set(filter(None, str(row["removed_horse_ids"]).split(";"))) == rem, f"removed ID set mismatch: {rid}")
        require(int(row["swap_count"]) == len(add) and as_bool(row["single_swap"]) == (len(add) == 1), f"swap count mismatch: {rid}")
        require(str(row["outcome_class"]) == expect["status"] and as_bool(row["primary_cohort"]) == expect["primary"], f"changed-race class/cohort mismatch: {rid}")
        counts = {
            "added_actual_top3_count": len(add & actual), "removed_actual_top3_count": len(rem & actual),
            "retained_actual_top3_count": len((c_base & c_head) & actual),
            "actual_top3_missed_by_both_count": len(actual - (c_base | c_head)),
            "baseline_top3_captured": len(c_base & actual), "selector_top3_captured": len(c_head & actual),
        }
        for key, value in counts.items():
            require(int(row[key]) == value, f"changed-race truth membership mismatch: {rid} {key}")
        if expect["primary"]:
            primary_counts[expect["status"]] += 1
    require(dict(primary_counts) == {"lost": 35, "both_miss": 143, "caught": 31, "both_hit": 45}, f"changed primary outcome counts differ: {primary_counts}")
    primary_both_miss = [r for r in changed.values() if r["primary"] and r["status"] == "both_miss"]
    by_missed = {row["race_id"]: int(race_out[row["race_id"]]["actual_top3_missed_by_both_count"]) for row in primary_both_miss}
    require(sum(v > 0 for v in by_missed.values()) == 129, "both-miss missed-by-both count differs")
    require(sum(by_missed.values()) == 155 and sum(v == 0 for v in by_missed.values()) == 14, "both-miss union miss totals differ")
    require(sum(int(race_out[rid]["added_actual_top3_count"]) for rid, r in changed.items() if r["primary"] and r["status"] == "caught") == 31, "caught additions do not contribute the 31 Top3 captures")
    require(sum(int(race_out[rid]["removed_actual_top3_count"]) for rid, r in changed.items() if r["primary"] and r["status"] == "lost") == 35, "lost removals do not account for the 35 Top3 misses")
    require(sum(int(race_out[rid]["removed_actual_top3_count"]) for rid, r in changed.items() if r["primary"] and r["status"] == "caught") == 0, "caught races removed a Top3 runner")
    require(sum(int(race_out[rid]["added_actual_top3_count"]) for rid, r in changed.items() if r["primary"] and r["status"] == "lost") == 0, "lost races added an actual Top3 runner")
    single_by_status = Counter(
        expect["status"] for rid, expect in changed.items()
        if expect["primary"] and len(set(map(str, choices[rid]["selector_top5_horse_ids"])) - set(map(str, choices[rid]["baseline_top5_horse_ids"]))) == 1
    )
    require(single_by_status["caught"] == 30 and single_by_status["lost"] == 35, "caught/lost single-swap counts differ")

    runner_table = pd.read_csv(OUT / "CHANGED_RUNNER_LEDGER.csv", dtype={"race_id": str, "horse_id": str})
    expected_n = sum(2 * r["swap_count"] for r in changed.values())
    require(len(runner_table) == expected_n, "changed-runner row count differs from swap count")
    require(runner_table.groupby("race_id").size().to_dict() == {rid: 2 * r["swap_count"] for rid, r in changed.items()}, "runner ledger per-race size mismatch")
    feature_by_id = {
        (str(row.race_id), str(row.horse_id)): row._asdict()
        for group in groups.values() for row in group.itertuples(index=False)
    }
    for row in runner_table.itertuples(index=False):
        rid = str(row.race_id)
        source = feature_by_id[(rid, str(row.horse_id))]
        require(int(row.actual_top3) == int(str(row.horse_id) in actual_by_race[rid]), f"runner Top3 membership mismatch: {rid}/{row.horse_id}")
        for col in [
            "observed_starts", "same_starts", "same_valid_times", "days_since_start", "last_time_s", "mean5_s", "valid_n5", "best5_s",
            "fast2mean5_s", "std5_s", "previous3_mean_s", "previous3_valid_n", "valid_n3", "trend_s", "mean5_rank_fraction",
            "hist_s1f_relpos_mean5", "hist_s1f_relpos_n", "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
            "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
        ]:
            require(near(getattr(row, col), source[col]), f"runner profile mismatch: {rid}/{row.horse_id} {col}")
    check_runner_contrasts(runner_table, race_table)
    summary = {
        "primary_changed_outcome_counts": dict(sorted(primary_counts.items())),
        "primary_caught_single_swap_races": single_by_status["caught"],
        "primary_lost_single_swap_races": single_by_status["lost"],
        "primary_both_miss_with_union_miss_races": 129,
        "primary_both_miss_union_missed_top3_runner_count": 155,
        "primary_both_miss_with_union_complete_but_no_full_five_set": 14,
    }
    return len(race_table), len(runner_table), summary


def check_runner_contrasts(runners: pd.DataFrame, races: pd.DataFrame) -> None:
    metrics = [
        "baseline_raw_score_rank", "raw_score", "observed_starts", "same_starts", "same_valid_times", "days_since_start",
        "last_time_s", "mean5_s", "valid_n5", "best5_s", "fast2mean5_s", "std5_s", "previous3_mean_s",
        "previous3_valid_n", "valid_n3", "trend_s", "mean5_rank_fraction", "hist_s1f_relpos_mean5", "hist_s1f_relpos_n",
        "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n", "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
    ]
    expected: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for cohort in ("primary", "secondary"):
        cohort_mask = runners.primary_cohort.map(as_bool).eq(cohort == "primary")
        for status in ("all_changed", *OUTCOME_CLASSES):
            status_mask = pd.Series(True, index=runners.index) if status == "all_changed" else runners.outcome_class.eq(status)
            selected = runners.loc[cohort_mask & status_mask].copy()
            race_ids = set(selected.race_id.astype(str))
            race_subset = races.loc[races.race_id.astype(str).isin(race_ids)].copy()
            for metric in metrics:
                if metric in FORM_COLUMNS or metric == "previous3_mean_s":
                    distances: list[str | float] = sorted(set(pd.to_numeric(selected.distance_m, errors="coerce").dropna().astype(float)))
                else:
                    distances = ["all"]
                for distance in distances:
                    filtered = selected if distance == "all" else selected.loc[pd.to_numeric(selected.distance_m).eq(float(distance))]
                    add_by: dict[str, list[float]] = defaultdict(list)
                    rem_by: dict[str, list[float]] = defaultdict(list)
                    add_values: list[float] = []
                    rem_values: list[float] = []
                    for row in filtered.to_dict(orient="records"):
                        value = row.get(metric)
                        if value is None or pd.isna(value):
                            continue
                        val = float(value)
                        if row["role"] == "added":
                            add_by[str(row["race_id"])].append(val)
                            add_values.append(val)
                        else:
                            rem_by[str(row["race_id"])].append(val)
                            rem_values.append(val)
                    race_diffs: list[float] = []
                    single_diffs: list[float] = []
                    for row in race_subset.to_dict(orient="records"):
                        rid = str(row["race_id"])
                        if distance != "all" and float(row["distance_m"]) != float(distance):
                            continue
                        a, r = add_by.get(rid, []), rem_by.get(rid, [])
                        if a and r:
                            race_diffs.append(float(np.mean(a) - np.mean(r)))
                        if as_bool(row["single_swap"]) and a and r:
                            single_diffs.append(float(a[0] - r[0]))
                    key = (cohort, status, "all" if distance == "all" else str(float(distance)), metric)
                    expected[key] = {
                        "changed_races": len(race_subset),
                        "single_swap_races": int(race_subset.single_swap.map(as_bool).sum()),
                        "multi_swap_races": int((~race_subset.single_swap.map(as_bool)).sum()),
                        "added_runner_n_observed": len(add_values), "removed_runner_n_observed": len(rem_values),
                        "runner_weighted_added_mean": float(np.mean(add_values)) if add_values else None,
                        "runner_weighted_removed_mean": float(np.mean(rem_values)) if rem_values else None,
                        "race_equal_pair_means_n": len(race_diffs),
                        "race_equal_mean_added_minus_removed": float(np.mean(race_diffs)) if race_diffs else None,
                        "single_swap_pair_n": len(single_diffs),
                        "single_swap_mean_added_minus_removed": float(np.mean(single_diffs)) if single_diffs else None,
                    }
    actual_table = pd.read_csv(OUT / "CHANGED_RUNNER_CONTRASTS.csv", dtype={"cohort": str, "outcome_class": str, "metric": str})
    actual: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in actual_table.to_dict(orient="records"):
        distance = str(row["distance_m"])
        if distance != "all":
            distance = str(float(distance))
        actual[(str(row["cohort"]), str(row["outcome_class"]), distance, str(row["metric"]))] = row
    require(set(actual) == set(expected), "changed-runner contrast inventory mismatch")
    for key, want in expected.items():
        got = actual[key]
        for col, val in want.items():
            if isinstance(val, (int, np.integer)):
                require(int(got[col]) == int(val), f"changed-runner contrast count mismatch: {key} {col}")
            elif val is None:
                require(pd.isna(got[col]), f"changed-runner contrast expected empty: {key} {col}")
            else:
                require(near(got[col], val, 1e-10), f"changed-runner contrast mismatch: {key} {col}")


def read_choices() -> dict[str, dict[str, Any]]:
    return {str(row["race_id"]): row for row in read_jsonl(MAIN / "outputs/candidate_choices.jsonl")}


def selector_raw_matrix(group: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    cols: dict[str, np.ndarray] = {}
    for source, target in [("observed_starts", "log_observed_starts"), ("same_starts", "log_same_starts"), ("same_valid_times", "log_same_valid_times"),
                           ("hist_s1f_relpos_n", "log_hist_s1f_relpos_n"), ("hist_s1f_to_c4_pair_n", "log_hist_s1f_to_c4_pair_n"), ("hist_c4_to_g1f_pair_n", "log_hist_c4_to_g1f_pair_n")]:
        vals = pd.to_numeric(group[source], errors="raise").to_numpy(dtype=np.float64)
        cols[target] = np.log1p(vals)
    rank = pd.to_numeric(group["mean5_rank_fraction"], errors="coerce").to_numpy(dtype=np.float64)
    cols["mean5_rank_fraction"] = rank
    cols["mean5_rank_fraction_missing"] = np.isnan(rank).astype(np.float64)
    for source, _support in STYLE_COLUMNS:
        cols[source] = pd.to_numeric(group[source], errors="coerce").to_numpy(dtype=np.float64)
    names = [n for n in RAW_INPUT_NAMES]
    return names, np.column_stack([cols[n] for n in names])


def check_energy_decomposition(races: list[dict[str, Any]], groups: dict[str, pd.DataFrame]) -> tuple[int, float, float]:
    choices = read_choices()
    fit_receipt = read_json(MAIN / "outputs/FIT_RECEIPT.json")
    energy_table = pd.read_csv(OUT / "ENERGY_DECOMPOSITION.csv", dtype={"race_id": str})
    require(len(energy_table) == 304, "energy decomposition must cover all 304 changed races")
    energy = {str(r.race_id): r._asdict() for r in energy_table.itertuples(index=False)}
    require(set(energy) == {r["race_id"] for r in races if r["changed"]}, "energy ledger race IDs differ from all changed races")
    model_by_year: dict[int, dict[str, Any]] = {}
    for year in (2024, 2025, 2026):
        path = MAIN / "outputs" / f"model_{year}.json"
        model = read_json(path)
        require(sha(path) == fit_receipt["model_artifacts"][f"model_{year}.json"]["sha256"], f"fitted model hash mismatch: {year}")
        require(model["feature_names"] == RAW_INPUT_NAMES, f"model feature order changed: {year}")
        model_by_year[year] = model
    max_head_error = 0.0
    max_residual = 0.0
    feature_indices = {name: [RAW_INPUT_NAMES.index(col) for col in cols] for name, cols in FEATURE_GROUPS.items()}
    energy_summary_expect: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    status_by = {r["race_id"]: r["status"] for r in races}
    primary_by = {r["race_id"]: r["primary"] for r in races}
    for rid, group in groups.items():
        c = choices[rid]
        model = model_by_year[int(c["year"])]
        names, raw = selector_raw_matrix(group)
        means, scales = np.asarray(model["feature_means"], float), np.asarray(model["feature_scales"], float)
        x = np.zeros_like(raw)
        for j in range(len(names)):
            valid = np.isfinite(raw[:, j])
            x[valid, j] = (raw[valid, j] - means[j]) / scales[j]
            x[~valid, j] = 0.0
        horse_ids = group.horse_id.astype(str).tolist()
        x_by = {hid: x[i] for i, hid in enumerate(horse_ids)}
        scores = pd.to_numeric(group.score, errors="raise").to_numpy(dtype=np.float64)
        sd = float(scores.std(ddof=0))
        z = np.zeros_like(scores) if sd == 0 else (scores - scores.mean()) / sd
        z_by = {hid: float(z[i]) for i, hid in enumerate(horse_ids)}
        b, s = set(map(str, c["baseline_top5_horse_ids"])), set(map(str, c["selector_top5_horse_ids"]))
        prior_b, prior_s = sum(z_by[k] for k in b), sum(z_by[k] for k in s)
        require(near(prior_b, c["baseline_energy"], 1e-10), f"saved baseline energy is not prior-only: {rid}")
        beta = np.asarray(model["beta"], float)
        head_b = prior_b + sum(float(x_by[k] @ beta) for k in b)
        head_s = prior_s + sum(float(x_by[k] @ beta) for k in s)
        require(near(head_s, c["selector_energy"], 1e-8), f"saved selected head energy replay mismatch: {rid}")
        max_head_error = max(max_head_error, abs(head_s - float(c["selector_energy"])))
        if b == s:
            continue
        add, rem = s - b, b - s
        dx = np.vstack([x_by[k] for k in sorted(add)]).sum(axis=0) - np.vstack([x_by[k] for k in sorted(rem)]).sum(axis=0)
        contrib = beta * dx
        delta = head_s - head_b
        prior_delta = prior_s - prior_b
        rec = energy[rid]
        require(as_bool(rec["primary_cohort"]) == primary_by[rid], f"energy cohort flag mismatch: {rid}")
        for col, val in (("raw_prior_delta", prior_delta), ("head_baseline_energy_reconstructed", head_b), ("head_selector_energy_reconstructed", head_s), ("head_set_energy_delta", delta), ("decomposition_residual", prior_delta + contrib.sum() - delta)):
            require(near(rec[col], val, 1e-8), f"energy ledger mismatch: {rid} {col}")
        for name, val in zip(RAW_INPUT_NAMES, contrib):
            require(near(rec[f"contrib_{name}"], val, 1e-8), f"individual energy contribution mismatch: {rid}/{name}")
        for name, indices in feature_indices.items():
            require(near(rec[f"contrib_group_{name}"], contrib[indices].sum(), 1e-8), f"group energy contribution mismatch: {rid}/{name}")
        residual = abs(float(rec["decomposition_residual"]))
        max_residual = max(max_residual, residual)
        cohort = "primary" if primary_by[rid] else "secondary"
        status = status_by[rid]
        for metric in ["raw_prior_delta", *[f"contrib_{n}" for n in RAW_INPUT_NAMES], *[f"contrib_group_{n}" for n in FEATURE_GROUPS], "head_set_energy_delta"]:
            energy_summary_expect[(cohort, "all_changed", metric)].append(float(rec[metric]))
            energy_summary_expect[(cohort, status, metric)].append(float(rec[metric]))
    require(max_head_error < 1e-8 and max_residual < 1e-8, "energy reconstruction residual exceeds tolerance")
    summary = pd.read_csv(OUT / "ENERGY_DECOMPOSITION_SUMMARY.csv", dtype={"cohort": str, "outcome_class": str, "metric": str})
    got = {(r.cohort, r.outcome_class, r.metric): r._asdict() for r in summary.itertuples(index=False)}
    metric_names = ["raw_prior_delta", *[f"contrib_{n}" for n in RAW_INPUT_NAMES], *[f"contrib_group_{n}" for n in FEATURE_GROUPS], "head_set_energy_delta"]
    all_summary_keys = {
        (cohort, status, metric)
        for cohort in ("primary", "secondary")
        for status in ("all_changed", *OUTCOME_CLASSES)
        for metric in metric_names
    }
    require(set(got) == all_summary_keys, "energy summary inventory mismatch")
    for key in all_summary_keys:
        values = energy_summary_expect.get(key, [])
        if not values:
            require(int(got[key]["changed_races"]) == 0 and pd.isna(got[key]["race_equal_mean"]), f"empty energy summary cell mismatch: {key}")
            continue
        arr = np.asarray(values, dtype=float)
        row = got[key]
        require(int(row["changed_races"]) == len(arr), f"energy summary n mismatch: {key}")
        for col, val in (("race_equal_mean", arr.mean()), ("race_equal_median", np.median(arr)), ("race_equal_q25", np.quantile(arr, .25)), ("race_equal_q75", np.quantile(arr, .75))):
            require(near(row[col], val, 1e-8), f"energy summary mismatch: {key} {col}")
    return len(energy), max_head_error, max_residual


def check_main_source_and_static_code(receipt: dict[str, Any]) -> dict[str, Any]:
    code = (GAIN / "analyze_gain_loss.py").read_text(encoding="utf-8")
    ast.parse(code, filename="analyze_gain_loss.py")
    banned = ["sqlite3", "supabase", "requests.", "httpx", "subprocess", "os.system"]
    imports_or_calls = {needle: needle in code for needle in banned}
    require(not any(imports_or_calls.values()), f"unexpected DB/network/process API in main analysis: {imports_or_calls}")
    require("finish_position" in code and "labels = pq.read_table(FEATURES, columns=[\"api_record_id\", \"finish_position\"])" in code, "separate label-only read contract not found")
    require("ROOT_REVIEW" in code and "SOURCE_CORRECTION" in code and "PLAN_SHA" in code, "analysis approval/source correction gates missing")
    return {"ast_parse": "PASS", "database_network_subprocess_imports": imports_or_calls, "code_sha256": receipt["analysis_code_sha256"]}


def main() -> None:
    receipt, hashes = audit_lock_and_sources()
    frame, choices, outcomes, _summary = read_sources()
    races, actual_by_race, groups = build_races(frame, choices, outcomes)
    form = check_form_summary(frame, races)
    condition_cells = check_condition_output(races)
    primary_ledger = check_primary_race_ledger(races)
    gap_rows = check_gap_summary(races)
    support_overlap = check_support4_overlap(races)
    changed_races, changed_runners, changed_summary = check_changed_ledgers(races, actual_by_race, groups, choices)
    energy_rows, energy_error, energy_residual = check_energy_decomposition(races, groups)
    classes_primary = Counter(r["status"] for r in races if r["primary"])
    classes_full = Counter(r["status"] for r in races)
    status_summary = check_main_source_and_static_code(receipt)
    result = {
        "status": "PASS",
        "review_scope": "independent source, roster, labels, choices, condition cells, time/style profiles, changed runners, and exact energy decomposition replay",
        "owned_path": "jeju/research/20261025_top5_direct_gain_loss_review_v1",
        "source_hashes": hashes,
        "main_analysis_code_sha256": receipt["analysis_code_sha256"],
        "source_and_static_review": status_summary,
        "row_counts": {
            "evaluation_runner_rows": len(frame), "races_full": len(races), "races_primary": sum(r["primary"] for r in races),
            "races_primary_outcomes": dict(sorted(classes_primary.items())), "races_full_outcomes": dict(sorted(classes_full.items())),
            "condition_cells_replayed": condition_cells, "primary_race_ledger_rows": primary_ledger,
            "continuous_gap_summary_rows": gap_rows, "primary_boundary_form_groups": form,
            "changed_race_ledger_rows": changed_races, "changed_runner_ledger_rows": changed_runners,
            "energy_decomposition_rows": energy_rows,
        },
        "independent_checks": {
            "feature_join_1_to_1": True, "T_minus_2_all_rows": True, "no_latest_history_after_cutoff": True,
            "excluded_horse_absent": True, "y_matches_finish_position_le3": True,
            "complete_rank_1_to_N_and_exactly_three_top3_per_race": True,
            "choices_match_baseline_rank_and_outcome_ledger": True,
            "all_condition_cell_counts_rates_and_bootstrap_intervals_match": True,
            "boundary_time_style_summary_matches_primary_only": True,
            "all_changed_runner_profiles_match_frozen_features": True,
            "all_304_head_and_prior_energies_reconstructed": True,
            "max_saved_selector_energy_error": energy_error,
            "max_energy_decomposition_residual": energy_residual,
        },
        "primary_changed_outcomes": {
            "caught": 31, "lost": 35, "changed_both_hit": 45, "changed_both_miss": 143,
            "both_miss_with_at_least_one_actual_top3_outside_both_sets": 129,
        },
        "changed_ledger_replay": changed_summary,
        "posthoc_support4_overlap": support_overlap,
        "main_output_bytes_excluding_receipt": receipt["outputs_bytes_excluding_receipt"],
        "main_storage_cap_bytes": receipt["storage_limit_bytes"],
    }
    (REVIEW / "VERIFICATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
