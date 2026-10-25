#!/usr/bin/env python3
"""Frozen F1_STYLE6 full-field PL comparison for the Jeju 7 pools.

The structural preflight and synthetic checks are safe before review.  The
fit/evaluate path is deliberately guarded by a supervisor-owned approval file.
This script never imports the horse-racing application or opens a database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import scipy
from scipy.optimize import minimize_scalar


PROJECT = Path(__file__).resolve().parents[4]
EXPERIMENT = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/experiment"
OUTPUT = EXPERIMENT / "outputs"
ASSET_MANIFEST = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/assets_audit/assets_manifest.json"
RULES_JSON = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/rules_contract/rules_contract.json"
RULES_README = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/rules_contract/README.md"
FEATURES = PROJECT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
STYLE_ROOT = PROJECT / "jeju/research/20261010_style_history_ablation_v1/outputs"
PAIR_ROOT = PROJECT / "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs"
BOOTSTRAP = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
APPROVAL = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/supervisor/BASELINE_EXECUTION_APPROVAL.json"
STYLE_PRODUCER = PROJECT / "jeju/research/20261010_style_history_ablation_v1/run.py"
PAIR_PRODUCER = PROJECT / "jeju/research/20261011_pair_top3_oos_expansion_v1/historical_refit.py"
STYLE_CONTRACT = PROJECT / "jeju/research/20261010_style_history_ablation_v1/CONTRACT.md"

EPS = 1e-15
T_BOUNDS = (0.35, 4.0)
POOL_ORDER = ("WIN", "PLC", "QNL", "EXA", "QPL", "TLA", "TRI")
CATEGORICAL = frozenset(("WIN", "QNL", "EXA", "TLA", "TRI"))
POOL_MIN_STARTERS = {"WIN": 2, "QNL": 3, "EXA": 3, "TLA": 4, "TRI": 4, "PLC": 5, "QPL": 5}
BIN_EDGES = np.asarray(
    [0.0, 0.00001, 0.00005, 0.0001, 0.00025, 0.0005, 0.001, 0.0025,
     0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0],
    dtype=np.float64,
)
EXPECTED_FEATURES_SHA = "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f"
EXPECTED_SCHEDULE_SHA = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
EXPECTED_DATE_SHA = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"
EXPECTED_CAL = {2019: (5890, 576), 2020: (3290, 329), 2021: (4331, 418), 2022: (5261, 512), 2023: (6506, 657)}
EXPECTED_EVAL = {2024: (6329, 637), 2025: (6410, 654), 2026: (4673, 488)}
EXPECTED_STUDY = "20261010_style_history_ablation_v1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT.resolve()).as_posix()


def project_path(relative_name: str) -> Path:
    candidate = (PROJECT / relative_name).resolve()
    require(candidate.is_relative_to(PROJECT.resolve()), "manifest input path escaped project root")
    return candidate


def json_read(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    require(isinstance(value, dict), f"expected JSON object: {relative(path)}")
    return value


def output_path(name: str) -> Path:
    path = (OUTPUT / name).resolve()
    require(path.is_relative_to(OUTPUT.resolve()), "output path escaped experiment outputs")
    return path


def write_json_once(name: str, value: Any) -> None:
    path = output_path(name)
    require(not path.exists(), f"refusing to overwrite existing output: {path.name}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=OUTPUT)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def write_parquet_once(name: str, frame: pd.DataFrame) -> None:
    path = output_path(name)
    require(not path.exists(), f"refusing to overwrite existing output: {path.name}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=OUTPUT)
    os.close(fd)
    try:
        frame.to_parquet(tmp_name, index=False, compression="zstd")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def check_storage_budget() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    size = sum(p.stat().st_size for p in OUTPUT.rglob("*") if p.is_file())
    require(size < 250_000_000, f"experiment output hard stop exceeded: {size} bytes")
    return size


@dataclass(frozen=True)
class ScoreSource:
    year: int
    role: str
    score_path: Path
    meta_path: Path
    expected_score_sha: str
    expected_rows: int
    expected_races: int


def source_specs(manifest: dict[str, Any]) -> list[ScoreSource]:
    spec_by_year: dict[tuple[int, str], ScoreSource] = {}
    for row in manifest["raw_oos_score_assets"]:
        year = int(row["label_year"])
        spec_by_year[(year, "calibration")] = ScoreSource(
            year, "calibration", project_path(row["path"]), project_path(row["provider_meta_path"]),
            str(row["sha256"]), int(row["rows"]), int(row["races"]),
        )
    for row in manifest["evaluation_score_assets"]:
        year = int(row["evaluation_year"])
        score_path = project_path(row["path"])
        meta_path = project_path(row.get("provider_meta_path", str(Path(row["path"]).parent / "meta.json")))
        spec_by_year[(year, "evaluation")] = ScoreSource(
            year, "evaluation", score_path, meta_path,
            str(row["sha256"]), int(row["rows"]), int(row["races"]),
        )
    require(set(spec_by_year) == {(y, "calibration") for y in range(2019, 2026)} | {(y, "evaluation") for y in range(2024, 2027)},
            "asset manifest does not have the frozen calibration/evaluation years")
    return [spec_by_year[key] for key in sorted(spec_by_year)]


def validate_source_meta(spec: ScoreSource, feature_sha: str) -> dict[str, Any]:
    require(spec.score_path.is_file() and spec.meta_path.is_file(), f"missing score input: {relative(spec.score_path)}")
    meta = json_read(spec.meta_path)
    require(meta.get("variant") == "F1_STYLE6", f"variant mismatch: {relative(spec.meta_path)}")
    expected_fold = spec.year + 1 if spec.role == "calibration" else spec.year
    require(int(meta.get("evaluation_year", -1)) == expected_fold, f"provider fold mismatch: {relative(spec.meta_path)}")
    require(meta.get("refit_max"), f"missing refit cutoff: {relative(spec.meta_path)}")
    score_sha = sha256_file(spec.score_path)
    require(score_sha == spec.expected_score_sha, f"source score SHA mismatch: {relative(spec.score_path)}")
    meta_sha = meta.get("calibration_scores_sha256" if spec.role == "calibration" else "evaluation_scores_sha256")
    require(meta_sha == score_sha, f"score SHA not committed by provider metadata: {relative(spec.meta_path)}")
    # Historical pair-fold sources have no temperature fit. Later raw score
    # files are consumed verbatim; their tau and calibrated probabilities are
    # never read or applied by this experiment.
    if spec.year <= 2022:
        require(meta.get("score_role_generated") == "calibration_only", "historical score role is not calibration-only")
        require(int(meta.get("temperature_optimizations", -1)) == 0, "historical raw calibration file unexpectedly used temperature fitting")
    if spec.role == "calibration":
        require(meta.get("calibration_min") and meta.get("calibration_max"), "calibration year range missing")
    return {
        "year": spec.year,
        "role": spec.role,
        "score_path": relative(spec.score_path),
        "meta_path": relative(spec.meta_path),
        "score_sha256": score_sha,
        "meta_sha256": sha256_file(spec.meta_path),
        "rows_expected": spec.expected_rows,
        "races_expected": spec.expected_races,
        "refit_max": meta["refit_max"],
        "feature_sha256": feature_sha,
    }


def load_feature_frame() -> tuple[pd.DataFrame, str]:
    require(FEATURES.is_file(), "frozen features parquet missing")
    feature_sha = sha256_file(FEATURES)
    require(feature_sha == EXPECTED_FEATURES_SHA, "frozen feature SHA mismatch")
    cols = ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "finish_position", "field_n", "history_cutoff"]
    frame = pd.read_parquet(FEATURES, columns=cols)
    require(list(frame.columns) == cols, "feature schema columns changed")
    require(frame["api_record_id"].is_unique, "feature api_record_id is not unique")
    require(frame["race_id"].notna().all() and frame["horse_id"].notna().all(), "null race or horse key")
    frame["race_date"] = pd.to_datetime(frame["race_date"], errors="coerce")
    require(frame["race_date"].notna().all(), "invalid race date in frozen features")
    frame["history_cutoff"] = pd.to_datetime(frame["history_cutoff"], errors="coerce")
    require(frame["history_cutoff"].notna().all(), "null or invalid frozen feature history_cutoff")
    require(((frame["race_date"] - frame["history_cutoff"]).dt.days == 2).all(),
            "feature history_cutoff is not exactly race_date minus two calendar days")
    frame["year"] = frame["year"].astype(np.int16)
    for name in ("api_record_id", "horse_number", "finish_position", "field_n"):
        require(frame[name].notna().all(), f"null required label/key field: {name}")
    return frame, feature_sha


def load_year_join(frame: pd.DataFrame, spec: ScoreSource) -> pd.DataFrame:
    year_features = frame.loc[frame["year"] == spec.year].copy()
    require(len(year_features) == spec.expected_rows, f"feature runner count mismatch in {spec.year} {spec.role}")
    score = pd.read_parquet(spec.score_path)
    require(list(score.columns) == ["api_record_id", "score"], f"raw score schema mismatch: {relative(spec.score_path)}")
    require(score["api_record_id"].dtype == np.dtype("int64"), "score key is not int64")
    require(score["score"].dtype == np.dtype("float64"), "score is not float64")
    require(score["api_record_id"].is_unique and score["score"].map(np.isfinite).all(), "duplicate key or non-finite raw score")
    require(len(score) == spec.expected_rows, f"raw score row count mismatch: {spec.year} {spec.role}")
    left_ids = set(year_features["api_record_id"].astype(np.int64).tolist())
    right_ids = set(score["api_record_id"].tolist())
    require(left_ids == right_ids, f"raw score key coverage mismatch: {spec.year} {spec.role}")
    joined = year_features.merge(score, on="api_record_id", how="inner", validate="one_to_one", sort=False)
    require(len(joined) == len(year_features), "one-to-one score join changed row count")
    return joined


def validate_races(joined: pd.DataFrame, expected_races: int, cohort: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    race_count = int(joined["race_id"].nunique())
    require(race_count == expected_races, f"race count mismatch for {cohort}: {race_count}")
    for race_id, group in joined.groupby("race_id", sort=True):
        n = int(group["field_n"].iloc[0])
        require(group["field_n"].nunique() == 1 and n == len(group), f"roster/field_n mismatch race={race_id}")
        require(group["horse_id"].is_unique and group["horse_number"].is_unique, f"duplicate horse in race={race_id}")
        require(group["race_date"].nunique() == 1 and group["year"].nunique() == 1, f"race date/year mismatch race={race_id}")
        positions = group["finish_position"].astype(int).to_numpy()
        require(n >= 3 and sorted(positions.tolist()) == list(range(1, n + 1)), f"incomplete, tied, or invalid final ranks race={race_id}")
        require(group["api_record_id"].is_unique, f"duplicate score key within race={race_id}")
        ordered = group.sort_values("horse_number", kind="mergesort")
        numbers = ordered["horse_number"].astype(int).to_numpy()
        ranks = ordered["finish_position"].astype(int).to_numpy()
        scores = ordered["score"].astype(np.float64).to_numpy()
        date = pd.Timestamp(group["race_date"].iloc[0]).strftime("%Y-%m-%d")
        year = int(group["year"].iloc[0])
        rec = {"race_id": str(race_id), "date": date, "year": year, "n": n,
               "numbers": numbers, "scores": scores, "ranks": ranks}
        records.append(rec)
        if cohort == "evaluation" and 5 <= n <= 7:
            quarantine.append({"race_id": str(race_id), "race_date": date, "year": year, "pool": "PLC",
                               "reason": "opening_field_unknown_actual_7", "opening_count": None,
                               "opening_count_source": "unknown", "actual_field_n": n})
    return records, quarantine


def prepare_cohorts() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    manifest = json_read(ASSET_MANIFEST)
    rules = json_read(RULES_JSON)
    official_minima = rules["primary_rule"]["article_4_minimum_starters"]
    require({pool: int(official_minima[pool]) for pool in POOL_ORDER} == POOL_MIN_STARTERS,
            "pool minimum starter contract differs from official rules JSON")
    plc_split = rules["primary_rule"]["plc_field_split"]
    require(plc_split.get("5_to_7") == "Top2" and plc_split.get("8_or_more") == "Top3",
            "official PLC opening-field split differs from frozen event code")
    qpl_rule = next(p for p in rules["event_space"]["pools"] if p["code"] == "QPL")
    require("places 1-3" in qpl_rule["event"], "official QPL event is not frozen Top3")
    feature, feature_sha = load_feature_frame()
    specs = source_specs(manifest)
    sources = [validate_source_meta(spec, feature_sha) for spec in specs]
    cal_records: list[dict[str, Any]] = []
    eval_records: list[dict[str, Any]] = []
    for spec in specs:
        joined = load_year_join(feature, spec)
        expected = (spec.expected_rows, spec.expected_races)
        require((len(joined), joined["race_id"].nunique()) == expected, f"source counts changed: {spec.year} {spec.role}")
        source_row = next(x for x in sources if x["year"] == spec.year and x["role"] == spec.role)
        source_meta = json_read(spec.meta_path)
        target_min = pd.Timestamp(joined["race_date"].min())
        target_max = pd.Timestamp(joined["race_date"].max())
        refit_max = pd.Timestamp(source_meta["refit_max"])
        require(refit_max <= target_min - pd.Timedelta(days=2),
                f"provider refit_max violates T-2 for source year={spec.year} role={spec.role}")
        range_prefix = "calibration" if spec.role == "calibration" else "evaluation"
        declared_min = pd.Timestamp(source_meta[f"{range_prefix}_min"])
        declared_max = pd.Timestamp(source_meta[f"{range_prefix}_max"])
        require(declared_min == target_min and declared_max == target_max,
                f"provider date range mismatch for source year={spec.year} role={spec.role}")
        source_row.update({"target_min_date": target_min.strftime("%Y-%m-%d"),
                           "target_max_date": target_max.strftime("%Y-%m-%d"),
                           "minimum_race_date_minus_refit_days": int((target_min - refit_max).days),
                           "feature_history_cutoff_rows": int(joined["history_cutoff"].nunique()),
                           "feature_history_cutoff_rule": "race_date_minus_2_calendar_days_checked_rowwise"})
        records, _ = validate_races(joined, spec.expected_races, f"{spec.role}-{spec.year}")
        if spec.role == "calibration" and spec.year <= 2023:
            cal_records.extend(records)
        elif spec.role == "evaluation":
            eval_records.extend(records)
    require(len(cal_records) == 2492 and sum(r["n"] for r in cal_records) == 25278, "frozen calibration cohort total changed")
    require(len(eval_records) == 1779 and sum(r["n"] for r in eval_records) == 17412, "frozen evaluation cohort total changed")
    require(len({r["date"] for r in eval_records}) == 269, "evaluation date count changed")
    require(sum(5 <= r["n"] <= 7 for r in eval_records) == 36, "PLC unknown race count changed")
    require(sum(r["n"] == 7 for r in eval_records) == 36, "expected 36 unknown PLC races with actual field size seven")
    report = {
        "feature_path": relative(FEATURES), "feature_sha256": feature_sha,
        "feature_rows": int(len(feature)), "feature_races": int(feature["race_id"].nunique()),
        "feature_years": {str(y): int((feature["year"] == y).sum()) for y in sorted(feature["year"].unique())},
        "calibration_races": len(cal_records), "calibration_runners": sum(r["n"] for r in cal_records),
        "evaluation_races": len(eval_records), "evaluation_runners": sum(r["n"] for r in eval_records),
        "evaluation_dates": len({r["date"] for r in eval_records}),
        "plc_unknown_races": sum(5 <= r["n"] <= 7 for r in eval_records),
        "plc_eligible_races": sum(r["n"] >= 8 for r in eval_records),
        "sources": sources,
        "producer_code_evidence": {
            "style_run_py": {"path": relative(STYLE_PRODUCER), "sha256": sha256_file(STYLE_PRODUCER)},
            "historical_refit_py": {"path": relative(PAIR_PRODUCER), "sha256": sha256_file(PAIR_PRODUCER)},
            "style_contract_md": {"path": relative(STYLE_CONTRACT), "sha256": sha256_file(STYLE_CONTRACT)},
        },
        "rules_contract_sha256": sha256_file(RULES_JSON),
        "rules_readme_sha256": sha256_file(RULES_README),
    }
    return cal_records, eval_records, report


def race_log_probability(scores: np.ndarray, ranks: np.ndarray, temperature: float) -> float:
    require(temperature > 0 and math.isfinite(temperature), "temperature must be positive finite")
    utility = np.asarray(scores, dtype=np.float64) / temperature
    chosen = []
    for target_rank in (1, 2, 3):
        idx = np.flatnonzero(ranks == target_rank)
        require(len(idx) == 1, "rank label is not unique")
        chosen.append(int(idx[0]))
    remaining = np.ones(len(utility), dtype=bool)
    logp = 0.0
    for idx in chosen:
        vals = utility[remaining]
        maximum = float(np.max(vals))
        log_den = maximum + math.log(float(np.exp(vals - maximum).sum()))
        logp += float(utility[idx]) - log_den
        remaining[idx] = False
    return logp


def fit_temperature(cal_records: list[dict[str, Any]]) -> dict[str, Any]:
    require(len(cal_records) == 2492, "fit cohort size changed")
    def objective(temperature: float) -> float:
        values = [-race_log_probability(r["scores"], r["ranks"], float(temperature)) for r in cal_records]
        result = float(np.mean(values))
        require(math.isfinite(result), "non-finite calibration objective")
        return result
    result = minimize_scalar(objective, bounds=T_BOUNDS, method="bounded", options={"xatol": 1e-12})
    require(result.success and math.isfinite(float(result.x)), f"temperature optimizer failed: {result.message}")
    candidates = [(T_BOUNDS[0], objective(T_BOUNDS[0])), (T_BOUNDS[1], objective(T_BOUNDS[1])),
                  (float(result.x), objective(float(result.x)))]
    temperature, best_nll = min(candidates, key=lambda pair: pair[1])
    require(T_BOUNDS[0] <= temperature <= T_BOUNDS[1], "fitted T outside frozen bounds")
    return {"temperature": temperature, "objective_nll": best_nll, "optimizer_x": float(result.x),
            "optimizer_success": bool(result.success), "optimizer_message": str(result.message),
            "bound_objectives": {str(T_BOUNDS[0]): candidates[0][1], str(T_BOUNDS[1]): candidates[1][1]},
            "observation_races": len(cal_records), "method": "scipy.optimize.minimize_scalar(method=bounded,xatol=1e-12)"}


def ordered_q(scores: np.ndarray, temperature: float) -> tuple[list[tuple[int, int, int, float]], dict[str, np.ndarray]]:
    n = len(scores)
    utility = np.asarray(scores, dtype=np.float64) / temperature
    numbers = np.arange(n, dtype=np.int64)
    triples: list[tuple[int, int, int, float]] = []
    p1 = np.zeros(n, dtype=np.float64)
    p2 = np.zeros(n, dtype=np.float64)
    p3 = np.zeros(n, dtype=np.float64)
    log_norm_all = _logsumexp(utility)
    for i in range(n):
        logp_i = utility[i] - log_norm_all
        rem_i = numbers != i
        log_norm_i = _logsumexp(utility[rem_i])
        for j in range(n):
            if j == i:
                continue
            logp_j = utility[j] - log_norm_i
            rem_ij = rem_i & (numbers != j)
            log_norm_ij = _logsumexp(utility[rem_ij])
            logp_ij = logp_i + logp_j
            for k in range(n):
                if k == i or k == j:
                    continue
                q = math.exp(logp_ij + float(utility[k] - log_norm_ij))
                triples.append((i, j, k, q))
                p1[i] += q
                p2[j] += q
                p3[k] += q
    mass = float(sum(t[3] for t in triples))
    require(abs(mass - 1.0) <= 2e-11, f"PL ordered triple mass is {mass:.17g}")
    top2, top3 = p1 + p2, p1 + p2 + p3
    require(abs(float(p1.sum()) - 1) <= 2e-11, "win marginal mass mismatch")
    require(abs(float(top2.sum()) - 2) <= 2e-11 and abs(float(top3.sum()) - 3) <= 2e-11,
            "top-k marginal mass mismatch")
    require(np.all(p1 <= top2 + 2e-14) and np.all(top2 <= top3 + 2e-14), "nested marginal invariant failed")
    return triples, {"p_win": p1, "p_exact2": p2, "p_exact3": p3, "p_top2": top2, "p_top3": top3}


def _logsumexp(values: np.ndarray) -> float:
    maximum = float(np.max(values))
    return maximum + math.log(float(np.exp(values - maximum).sum()))


def make_ticket_maps(triples: list[tuple[int, int, int, float]], marginal: dict[str, np.ndarray], numbers: np.ndarray,
                     plc_top: int) -> dict[str, dict[tuple[int, ...], float]]:
    maps: dict[str, defaultdict[tuple[int, ...], float]] = {
        pool: defaultdict(float) for pool in POOL_ORDER
    }
    for i, j, k, q in triples:
        maps["QNL"][tuple(sorted((int(numbers[i]), int(numbers[j]))) )] += q
        maps["EXA"][(int(numbers[i]), int(numbers[j]))] += q
        maps["TLA"][tuple(sorted((int(numbers[i]), int(numbers[j]), int(numbers[k]))))] += q
        maps["TRI"][(int(numbers[i]), int(numbers[j]), int(numbers[k]))] += q
        for pair in combinations(sorted((int(numbers[i]), int(numbers[j]), int(numbers[k]))), 2):
            maps["QPL"][pair] += q
    for ix, horse_number in enumerate(numbers):
        maps["WIN"][(int(horse_number),)] = float(marginal["p_win"][ix])
        place_key = "p_top2" if plc_top == 2 else "p_top3"
        maps["PLC"][(int(horse_number),)] = float(marginal[place_key][ix])
    final = {pool: dict(items) for pool, items in maps.items()}
    expected_mass = {"WIN": 1.0, "QNL": 1.0, "EXA": 1.0, "QPL": 3.0, "TLA": 1.0, "TRI": 1.0,
                     "PLC": float(plc_top)}
    for pool, tickets in final.items():
        require(abs(sum(tickets.values()) - expected_mass[pool]) <= 3e-11,
                f"{pool} event probability mass mismatch")
    return final


def truth_keys(pool: str, record: dict[str, Any], plc_top: int) -> set[tuple[int, ...]]:
    by_rank = {int(rank): int(number) for number, rank in zip(record["numbers"], record["ranks"])}
    first, second, third = by_rank[1], by_rank[2], by_rank[3]
    if pool == "WIN":
        return {(first,)}
    if pool == "PLC":
        return {(horse,) for horse, rank in zip(record["numbers"], record["ranks"]) if int(rank) <= plc_top}
    if pool == "QNL":
        return {tuple(sorted((first, second)))}
    if pool == "EXA":
        return {(first, second)}
    if pool == "QPL":
        return {tuple(sorted(pair)) for pair in combinations((first, second, third), 2)}
    if pool == "TLA":
        return {tuple(sorted((first, second, third)))}
    if pool == "TRI":
        return {(first, second, third)}
    raise AssertionError(pool)


def plc_event_top(actual_field_n: int, opening_field_n: int | None = None,
                  opening_observed: bool = False) -> tuple[int | None, str]:
    """Resolve the legal PLC event rank count without inferring unknown 5–7 fields."""
    if opening_observed:
        require(opening_field_n is not None, "observed PLC opening count is missing")
        if 5 <= opening_field_n <= 7:
            return 2, "observed_sales_opening_count"
        if opening_field_n >= 8:
            return 3, "observed_sales_opening_count"
        return None, "below_statutory_minimum"
    if actual_field_n >= 8:
        return 3, "actual_starter_lower_bound_assuming_no_post_open_additions"
    return None, "opening_field_unknown"


def _key_json(key: tuple[int, ...]) -> str:
    return json.dumps([int(value) for value in key], separators=(",", ":"))


def pool_race_result(pool: str, tickets: dict[tuple[int, ...], float], truths: set[tuple[int, ...]]) -> tuple[dict[str, Any], dict[str, Any]]:
    require(bool(tickets) and truths.issubset(tickets.keys()), f"missing tickets/outcome for {pool}")
    keys = list(tickets)
    probs = np.asarray([tickets[k] for k in keys], dtype=np.float64)
    ys = np.fromiter((1.0 if k in truths else 0.0 for k in keys), dtype=np.float64, count=len(keys))
    if pool in CATEGORICAL:
        require(len(truths) == 1, f"categorical pool has {len(truths)} true tickets: {pool}")
        true_key = next(iter(truths))
        true_p = float(tickets[true_key])
        nll = -math.log(max(true_p, EPS))
        brier = float(np.square(probs - ys).sum())
    else:
        clipped = np.clip(probs, EPS, 1.0 - EPS)
        ll = -(ys * np.log(clipped) + (1.0 - ys) * np.log1p(-clipped))
        nll = float(ll.mean())
        brier = float(np.square(probs - ys).mean())
        true_p = float(np.mean([tickets[k] for k in truths]))
    max_p = float(probs.max())
    selected = min(k for k, p in tickets.items() if p == max_p)
    selected_hit = selected in truths
    realized_ps = [float(tickets[k]) for k in sorted(truths)]
    result = {"pool": pool, "race_nll": nll, "race_brier": brier, "ticket_count": len(tickets),
              "event_count": len(truths), "realized_event_p_mean": true_p,
              "realized_event_nll_mean": float(np.mean([-math.log(max(p, EPS)) for p in realized_ps]))}
    selection = {"pool": pool, "selected_ticket_key": _key_json(selected), "selected_probability": max_p,
                 "selected_hit": bool(selected_hit), "realized_event_count": len(truths),
                 "realized_event_keys_json": json.dumps([[int(value) for value in k] for k in sorted(truths)], separators=(",", ":")),
                 "realized_event_probabilities_json": json.dumps(realized_ps, separators=(",", ":")),
                 "realized_event_p_mean": true_p,
                 "realized_event_nlls_json": json.dumps([-math.log(max(p, EPS)) for p in realized_ps], separators=(",", ":")),
                 "realized_event_nll_mean": result["realized_event_nll_mean"]}
    return result, selection


def bin_accumulate(acc: dict[tuple[str, str, int], list[float]], pool: str, arm: str,
                   tickets: dict[tuple[int, ...], float], truths: set[tuple[int, ...]]) -> None:
    for key, probability in tickets.items():
        idx = int(np.searchsorted(BIN_EDGES, probability, side="right") - 1)
        idx = min(max(idx, 0), len(BIN_EDGES) - 2)
        row = acc[(pool, arm, idx)]
        observed = 1.0 if key in truths else 0.0
        row[0] += 1.0
        row[1] += probability
        row[2] += observed
        row[3] += (probability - observed) ** 2


def evaluate_race(record: dict[str, Any], temperature: float, arm: str,
                  bins: dict[tuple[str, str, int], list[float]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    numbers = np.asarray(record["numbers"], dtype=np.int64)
    triples, marginal = ordered_q(record["scores"], temperature)
    plc_top, plc_basis = plc_event_top(int(record["n"]))
    if plc_top is None:
        plc_top = 2  # Internal map shape only; PLC is excluded below when opening field is unknown.
    maps = make_ticket_maps(triples, marginal, numbers, plc_top)
    metrics: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    for pool in POOL_ORDER:
        min_n = POOL_MIN_STARTERS[pool]
        if record["n"] < min_n or (pool == "PLC" and plc_basis == "opening_field_unknown"):
            continue
        truths = truth_keys(pool, record, plc_top)
        pool_metric, selection = pool_race_result(pool, maps[pool], truths)
        pool_metric.update({"race_id": record["race_id"], "race_date": record["date"], "year": record["year"],
                            "field_n": record["n"], "arm": arm})
        selection.update({"race_id": record["race_id"], "race_date": record["date"], "year": record["year"],
                          "field_n": record["n"], "arm": arm})
        metrics.append(pool_metric)
        selections.append(selection)
        bin_accumulate(bins, pool, arm, maps[pool], truths)
    marginal_rows = []
    for idx, horse_number in enumerate(numbers):
        marginal_rows.append({"race_id": record["race_id"], "race_date": record["date"], "year": record["year"],
                              "horse_number": int(horse_number), "arm": arm,
                              "p_win": float(marginal["p_win"][idx]), "p_exact2": float(marginal["p_exact2"][idx]),
                              "p_exact3": float(marginal["p_exact3"][idx]), "p_top2": float(marginal["p_top2"][idx]),
                              "p_top3": float(marginal["p_top3"][idx])})
    return metrics, selections, marginal_rows


def build_bin_frame(bins: dict[tuple[str, str, int], list[float]]) -> pd.DataFrame:
    rows = []
    for pool in POOL_ORDER:
        for arm in ("T1", "TEMP"):
            for ix in range(len(BIN_EDGES) - 1):
                count, sum_p, sum_y, sum_brier = bins[(pool, arm, ix)]
                rows.append({"pool": pool, "arm": arm, "bin_index": ix, "bin_left": BIN_EDGES[ix],
                             "bin_right": BIN_EDGES[ix + 1], "right_inclusive": ix == len(BIN_EDGES) - 2,
                             "event_count": int(count), "mean_probability": (sum_p / count if count else None),
                             "observed_rate": (sum_y / count if count else None),
                             "mean_event_brier": (sum_brier / count if count else None),
                             "weighting": "pooled_ticket_event_count"})
    return pd.DataFrame(rows)


def race_contract_ledger(eval_records: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for race in eval_records:
        n = int(race["n"])
        opening_lower_bound = 8 if n >= 8 else None
        opening_source = ("actual_starter_lower_bound_assuming_no_post_open_additions"
                          if n >= 8 else "unknown_actual_field_below_8")
        plc_top, plc_basis = plc_event_top(n)
        for pool in POOL_ORDER:
            minimum = POOL_MIN_STARTERS[pool]
            if n < minimum:
                status = "below_statutory_minimum"
            elif pool == "PLC" and plc_top is None:
                status = "opening_field_unknown_quarantined"
            else:
                status = "structural_event_label_available_pool_offering_unverified"
            rows.append({
                "race_id": race["race_id"], "race_date": race["date"], "year": race["year"],
                "pool": pool, "actual_field_n": n, "statutory_minimum_starters": minimum,
                "pool_minimum_met_from_actual_field": n >= minimum,
                "official_race_status": "not_audited", "pool_offered_status": "not_audited",
                "pool_offering_evidence": "not_audited", "N_at_open": None,
                "N_at_open_observed": False, "N_at_open_lower_bound": opening_lower_bound,
                "N_at_open_count_source": opening_source,
                "plc_event_top_k": plc_top, "plc_rule_basis": plc_basis,
                "event_label_status": status,
                "plc_top3_robust_under_no_post_open_additions": bool(pool == "PLC" and n >= 8),
            })
    return pd.DataFrame(rows)


def summarize_metrics(metrics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    all_summary = metrics.groupby(["pool", "arm"], sort=False).agg(
        races=("race_id", "nunique"), mean_race_nll=("race_nll", "mean"), mean_race_brier=("race_brier", "mean"),
        total_ticket_events=("ticket_count", "sum"), realized_events=("event_count", "sum"),
    ).reset_index()
    year_summary = metrics.groupby(["pool", "arm", "year"], sort=False).agg(
        races=("race_id", "nunique"), mean_race_nll=("race_nll", "mean"), mean_race_brier=("race_brier", "mean"),
        total_ticket_events=("ticket_count", "sum"), realized_events=("event_count", "sum"),
    ).reset_index()
    comparison: dict[str, Any] = {}
    for pool in POOL_ORDER:
        part = metrics.loc[metrics["pool"] == pool]
        piv = part.pivot(index=["race_id", "race_date", "year"], columns="arm", values=["race_nll", "race_brier"])
        require(set(piv.columns.get_level_values(1)) == {"T1", "TEMP"}, f"missing arm in {pool}")
        d_nll = piv[("race_nll", "TEMP")] - piv[("race_nll", "T1")]
        d_brier = piv[("race_brier", "TEMP")] - piv[("race_brier", "T1")]
        comparison[pool] = {"races": int(len(piv)), "candidate_minus_t1_mean_race_nll": float(d_nll.mean()),
                            "candidate_minus_t1_mean_race_brier": float(d_brier.mean())}
    return all_summary, year_summary, comparison


def primary_bootstrap(metrics: pd.DataFrame, eval_records: list[dict[str, Any]]) -> dict[str, Any]:
    receipt = json_read(BOOTSTRAP_RECEIPT)
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS", "bootstrap schedule was not frozen in advance")
    require(receipt.get("schedule_sha256") == EXPECTED_SCHEDULE_SHA == sha256_file(BOOTSTRAP), "bootstrap SHA mismatch")
    dates = sorted({r["date"] for r in eval_records})
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(date_hash == EXPECTED_DATE_SHA == receipt.get("date_inventory_sha256"), "bootstrap date inventory mismatch")
    schedule = np.load(BOOTSTRAP, mmap_mode="r", allow_pickle=False)
    require(schedule.shape == (2000, 269) and schedule.dtype == np.int32, "bootstrap schedule shape/dtype mismatch")
    require(int(schedule.min()) >= 0 and int(schedule.max()) < len(dates), "bootstrap index outside date roster")
    part = metrics.loc[(metrics["pool"] == "TRI")]
    wide = part.pivot(index=["race_id", "race_date"], columns="arm", values=["race_nll", "race_brier"])
    diff = (wide[("race_nll", "TEMP")] - wide[("race_nll", "T1")]).to_numpy(dtype=np.float64)
    by_date: dict[str, list[float]] = defaultdict(list)
    date_vals = wide.index.get_level_values("race_date").to_numpy()
    for date, value in zip(date_vals, diff):
        by_date[str(date)].append(float(value))
    day_sums = np.asarray([sum(by_date[d]) for d in dates], dtype=np.float64)
    day_counts = np.asarray([len(by_date[d]) for d in dates], dtype=np.float64)
    draws = np.empty(schedule.shape[0], dtype=np.float64)
    for ix, draw in enumerate(schedule):
        multiplicity = np.bincount(draw, minlength=len(dates)).astype(np.float64)
        denominator = float(np.dot(multiplicity, day_counts))
        require(denominator > 0, "empty date bootstrap draw")
        draws[ix] = float(np.dot(multiplicity, day_sums) / denominator)
    low, high = np.quantile(draws, [0.025, 0.975], method="linear")
    point_nll = float(diff.mean())
    brier_diff = float((wide[("race_brier", "TEMP")] - wide[("race_brier", "T1")]).mean())
    return {"pool": "TRI", "date_count": len(dates), "race_count": int(len(diff)),
            "paired_date_bootstrap_draws": len(draws), "point_candidate_minus_t1_race_equal_nll": point_nll,
            "nll_difference_ci95": [float(low), float(high)],
            "sum_brier_candidate_minus_t1_point": brier_diff,
            "gate_pass": bool(high < 0.0 and brier_diff <= 0.0),
            "schedule_sha256": receipt["schedule_sha256"], "date_inventory_sha256": date_hash,
            "bootstrap_weighting": "sample dates with replacement; all races on each drawn date; race-equal within resampled cohort",
            "temperature_fixed_across_draws": True}


def source_preflight() -> None:
    require(OUTPUT.is_dir() and not any(OUTPUT.iterdir()), "experiment outputs directory must be empty before first preflight")
    cal, evaluation, report = prepare_cohorts()
    plc_quarantine = []
    for r in evaluation:
        if 5 <= r["n"] <= 7:
            plc_quarantine.append({"race_id": r["race_id"], "race_date": r["date"], "year": r["year"],
                                   "pool": "PLC", "reason": "opening_field_unknown_actual_5_to_7",
                                   "opening_count": None, "opening_count_source": "unknown",
                                   "opening_count_lower_bound": None, "actual_field_n": r["n"],
                                   "event_range": "Top2 or Top3 unresolved; excluded only from PLC"})
    require(len(plc_quarantine) == 36 and len(cal) == 2492, "preflight contract counts mismatch")
    contract_ledger = race_contract_ledger(evaluation)
    report.update({"status": "PASS_STRUCTURAL_PREFLIGHT_NO_FIT_OR_METRICS", "quarantine_rows": len(plc_quarantine),
                   "quarantine_reason_counts": {"opening_field_unknown_actual_5_to_7": len(plc_quarantine)},
                   "models_loaded": False, "database_opened": False, "temperatures_fit": False,
                   "probabilities_or_outcome_metrics_computed": False,
                   "asset_manifest_sha256": sha256_file(ASSET_MANIFEST), "rules_contract_sha256": sha256_file(RULES_JSON),
                   "race_contract_ledger_rows": int(len(contract_ledger))})
    write_parquet_once("preflight_race_contract.parquet", contract_ledger)
    write_parquet_once("preflight_quarantine.parquet", pd.DataFrame(plc_quarantine))
    report["race_contract_ledger_sha256"] = sha256_file(output_path("preflight_race_contract.parquet"))
    write_json_once("source_preflight.json", report)
    print(json.dumps({k: report[k] for k in ("status", "calibration_races", "evaluation_races", "evaluation_dates", "plc_unknown_races")}, indent=2))


def validate_execution_approval() -> dict[str, Any]:
    require(APPROVAL.is_file(), "supervisor fit/evaluate approval file is missing")
    approval = json_read(APPROVAL)
    plan_sha = sha256_file(EXPERIMENT / "PLAN.md")
    code_sha = sha256_file(Path(__file__).resolve())
    require(output_path("source_preflight.json").is_file(), "source preflight approval target missing")
    preflight_sha = sha256_file(output_path("source_preflight.json"))
    asset_sha = sha256_file(ASSET_MANIFEST)
    rules_sha = sha256_file(RULES_JSON)
    require(approval.get("status") == "PASS", "supervisor fit/evaluate review is not PASS")
    require(approval.get("plan_sha256") == plan_sha, "approval plan SHA does not match current PLAN.md")
    require(approval.get("code_sha256") == code_sha, "approval code SHA does not match current baseline.py")
    require(approval.get("source_preflight_sha256") == preflight_sha, "approval source preflight SHA does not match current source_preflight.json")
    require(approval.get("asset_manifest_sha256") == asset_sha, "approval asset manifest SHA does not match current assets_manifest.json")
    require(approval.get("rules_contract_sha256") == rules_sha, "approval rules contract SHA does not match current rules_contract.json")
    require(approval.get("scope") == "fit_evaluate_only", "approval scope is not fit_evaluate_only")
    return {"approval_sha256": sha256_file(APPROVAL), "plan_sha256": plan_sha, "code_sha256": code_sha,
            "source_preflight_sha256": preflight_sha, "asset_manifest_sha256": asset_sha, "rules_contract_sha256": rules_sha,
            "reviewer": approval.get("reviewer"), "reviewed_at": approval.get("reviewed_at")}


def run_fit_evaluate() -> None:
    approval = validate_execution_approval()
    initial_output_bytes = check_storage_budget()
    require(OUTPUT.is_dir() and (OUTPUT / "source_preflight.json").is_file(), "run structural preflight first")
    preflight = json_read(OUTPUT / "source_preflight.json")
    require(preflight.get("status") == "PASS_STRUCTURAL_PREFLIGHT_NO_FIT_OR_METRICS", "preflight did not pass")
    require(not any(output_path(name).exists() for name in ("fit_receipt.json", "race_metrics.parquet", "selected_ticket_ledger.parquet",
                                                             "runner_marginals.parquet", "pool_summary.parquet", "pool_year_summary.parquet",
                                                             "reliability_bins.parquet", "evaluation_quarantine.parquet", "report.json")),
            "fit/evaluation outputs already exist; refusing overwrite")
    cal_records, eval_records, input_report = prepare_cohorts()
    for key in ("feature_sha256", "calibration_races", "calibration_runners", "evaluation_races", "evaluation_runners",
                "evaluation_dates", "plc_unknown_races", "plc_eligible_races", "sources", "rules_contract_sha256"):
        require(preflight.get(key) == input_report.get(key), f"approved preflight input changed: {key}")
    require(preflight.get("asset_manifest_sha256") == sha256_file(ASSET_MANIFEST), "approved asset manifest changed")
    require(preflight.get("rules_contract_sha256") == sha256_file(RULES_JSON), "approved rules contract changed")
    fit = fit_temperature(cal_records)
    bins: dict[tuple[str, str, int], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    metric_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    marginal_rows: list[dict[str, Any]] = []
    for record in eval_records:
        for arm, temperature in (("T1", 1.0), ("TEMP", fit["temperature"])):
            m, s, runners = evaluate_race(record, temperature, arm, bins)
            metric_rows.extend(m)
            selection_rows.extend(s)
            marginal_rows.extend(runners)
    metrics = pd.DataFrame(metric_rows)
    selections = pd.DataFrame(selection_rows)
    marginals = pd.DataFrame(marginal_rows)
    require(metrics["race_id"].nunique() == 1779 and len(metrics.loc[metrics.pool == "TRI"]) == 3558, "evaluation metric cohort changed")
    summary, year_summary, comparison = summarize_metrics(metrics)
    bootstrap = primary_bootstrap(metrics, eval_records)
    bins_frame = build_bin_frame(bins)
    selection = selections.pivot(index=["pool", "race_id"], columns="arm", values=["selected_ticket_key", "selected_hit"])
    choice_change = {}
    for pool in POOL_ORDER:
        p = selection.loc[pool]
        choice_change[pool] = {"races": int(len(p)), "changed_ticket_count": int((p[("selected_ticket_key", "T1")] != p[("selected_ticket_key", "TEMP")]).sum()),
                               "t1_selected_hit_count": int(p[("selected_hit", "T1")].sum()),
                               "temp_selected_hit_count": int(p[("selected_hit", "TEMP")].sum()),
                               "hit_count_difference": int(p[("selected_hit", "TEMP")].sum() - p[("selected_hit", "T1")].sum())}
    quarantine_rows = [{"race_id": r["race_id"], "race_date": r["date"], "year": r["year"], "pool": "PLC",
                        "reason": "opening_field_unknown_actual_5_to_7", "opening_count": None,
                        "opening_count_observed": False, "opening_count_lower_bound": None,
                        "rule_basis": "unknown; actual 5-7 does not determine opening 5-7 vs 8+"}
                       for r in eval_records if 5 <= r["n"] <= 7]
    contract_ledger = race_contract_ledger(eval_records)
    report = {
        "study": "jeju_20261022_joint_wager_baseline_v1", "interpretation": "research calibration candidate only; no deployment/native q replacement",
        "input_report": input_report, "approval": approval, "fit": fit,
        "primary": bootstrap, "pool_comparisons": comparison, "selection_diagnostics": choice_change,
        "temperature_fit_labels": "2019-2023 exact ordered 1->2->3 labels; raw scores only; race-equal NLL",
        "evaluation_labels": "2024-2026-09-19 frozen complete normal-finish cohort; score vintage per year; no update on 2024/25",
        "metric_contract": {"categorical": "race-equal categorical NLL clipped at EPS and sum Brier",
                            "multiple_hit": "per-ticket Bernoulli NLL/Brier clipped only for log loss, ticket mean within race, then race-equal",
                            "reliability": "pooled ticket-event count weighting", "epsilon": EPS,
                            "brier_uses_unclipped_probability": True},
        "candidate_gate_status": "PASS_RESEARCH_CANDIDATE_ONLY" if bootstrap["gate_pass"] else "FAIL",
        "limitations": ["No historical pool availability/settlement proof", "opening roster count not observed; PLC actual-7 races quarantined",
                        "full-field sequential PL is a simple baseline, not validated horse interaction model",
                        "2024-2026 evaluation has prior reuse and is not an independent holdout",
                        "date bootstrap holds fitted T fixed; excludes fit uncertainty"],
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__},
        "code_sha256": sha256_file(Path(__file__).resolve()), "plan_sha256": sha256_file(EXPERIMENT / "PLAN.md"),
        "rules_contract_sha256": sha256_file(RULES_JSON), "rules_readme_sha256": sha256_file(RULES_README),
        "created_at_local": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    write_parquet_once("race_metrics.parquet", metrics)
    write_parquet_once("selected_ticket_ledger.parquet", selections)
    write_parquet_once("runner_marginals.parquet", marginals)
    write_parquet_once("pool_summary.parquet", summary)
    write_parquet_once("pool_year_summary.parquet", year_summary)
    write_parquet_once("reliability_bins.parquet", bins_frame)
    write_parquet_once("evaluation_quarantine.parquet", pd.DataFrame(quarantine_rows))
    write_parquet_once("race_contract_ledger.parquet", contract_ledger)
    write_json_once("fit_receipt.json", {"fit": fit, "approval": approval, "input_report": input_report,
                                           "code_sha256": report["code_sha256"], "plan_sha256": report["plan_sha256"],
                                           "initial_output_bytes": initial_output_bytes,
                                           "environment": report["environment"]})
    write_json_once("report.json", report)
    stored = check_storage_budget()
    print(json.dumps({"status": report["candidate_gate_status"], "temperature": fit["temperature"],
                      "primary": bootstrap, "stored_bytes": stored, "selection_diagnostics": choice_change}, indent=2))


def synthetic_checks() -> None:
    scores = np.asarray([0.0, 0.7, -0.4, 1.2, -0.8], dtype=np.float64)
    rec = {"race_id": 1, "date": "2026-01-01", "year": 2026, "n": 5,
           "numbers": np.asarray([1, 2, 3, 4, 5]), "scores": scores,
           "ranks": np.asarray([1, 2, 3, 4, 5])}
    for temperature in (1.0, 0.6, 2.0):
        triples, marginal = ordered_q(scores, temperature)
        maps = make_ticket_maps(triples, marginal, rec["numbers"], plc_top=2)
        require(len(triples) == 5 * 4 * 3, "synthetic ordered triple count mismatch")
        require(abs(sum(maps["QPL"].values()) - 3.0) < 1e-12, "synthetic QPL mass failed")
        require(abs(sum(maps["PLC"].values()) - 2.0) < 1e-12, "synthetic PLC Top2 mass failed")
        require(abs(sum(maps["TLA"].values()) - 1.0) < 1e-12, "synthetic TLA mass failed")
    shifted, _ = ordered_q(scores + 8.25, 1.0)
    baseline, _ = ordered_q(scores, 1.0)
    require(np.allclose([q[3] for q in shifted], [q[3] for q in baseline], rtol=1e-12, atol=1e-14),
            "synthetic score-shift invariance failed")
    tied = {(1,): 0.4, (2,): 0.4, (3,): 0.2}
    metric, selection = pool_race_result("WIN", tied, {(2,)})
    require(selection["selected_ticket_key"] == "[1]" and not selection["selected_hit"], "synthetic deterministic tie-break failed")
    for n_open, expected_top in ((5, 2), (7, 2), (8, 3), (12, 3)):
        top, basis = plc_event_top(actual_field_n=n_open, opening_field_n=n_open, opening_observed=True)
        require(top == expected_top and basis == "observed_sales_opening_count", "synthetic PLC opening-field branch failed")
    n_actual, opening_observed = 7, False
    top, basis = plc_event_top(actual_field_n=n_actual, opening_field_n=None, opening_observed=opening_observed)
    require(top is None and basis == "opening_field_unknown", "synthetic unknown actual-7 PLC branch failed")
    top, basis = plc_event_top(actual_field_n=8, opening_field_n=None, opening_observed=False)
    require(top == 3 and "lower_bound" in basis, "synthetic PLC actual-8 lower-bound branch failed")
    require(len(truth_keys("QPL", rec, 2)) == 3 and all(len(k) == 2 for k in truth_keys("QPL", rec, 2)),
            "QPL must always mean Top3 pair events")
    print(json.dumps({"status": "PASS_SYNTHETIC_ONLY", "ordered_triples": 60,
                      "checks": ["joint mass", "marginal masses", "pool event masses", "score shift invariance",
                                 "stable deterministic tie-break", "PLC opening-count branches", "QPL always Top3" ]}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--synthetic-checks", action="store_true")
    group.add_argument("--source-preflight", action="store_true")
    group.add_argument("--fit-evaluate", action="store_true")
    args = parser.parse_args()
    if args.synthetic_checks:
        synthetic_checks()
    elif args.source_preflight:
        source_preflight()
    else:
        run_fit_evaluate()


if __name__ == "__main__":
    main()
