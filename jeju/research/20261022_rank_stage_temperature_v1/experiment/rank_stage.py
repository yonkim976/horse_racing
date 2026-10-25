#!/usr/bin/env python3
"""One rank-specific full-field sequential PL calibration candidate.

Preparation commands (synthetic checks and source preflight) never fit a real
temperature or calculate real-race probabilities. The fit/evaluation command
is hash-gated by the supervisor approval file.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import platform
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import scipy
from scipy.optimize import minimize_scalar


PROJECT = Path(__file__).resolve().parents[4]
STUDY = PROJECT / "jeju/research/20261022_rank_stage_temperature_v1"
EXPERIMENT = STUDY / "experiment"
OUTPUT = EXPERIMENT / "outputs"
ASSET_MANIFEST = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/assets_audit/assets_manifest.json"
BASELINE_ROOT = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/experiment"
BASELINE_PREFLIGHT = BASELINE_ROOT / "outputs/source_preflight.json"
BASELINE_METRICS = BASELINE_ROOT / "outputs/race_metrics.parquet"
BASELINE_RUNNERS = BASELINE_ROOT / "outputs/runner_marginals.parquet"
BASELINE_SELECTION = BASELINE_ROOT / "outputs/selected_ticket_ledger.parquet"
BASELINE_YEAR = BASELINE_ROOT / "outputs/pool_year_summary.parquet"
BASELINE_BINS = BASELINE_ROOT / "outputs/reliability_bins.parquet"
BASELINE_CONTRACT = BASELINE_ROOT / "outputs/race_contract_ledger.parquet"
BASELINE_REPORT = BASELINE_ROOT / "outputs/report.json"
BASELINE_PLAN = BASELINE_ROOT / "PLAN.md"
BASELINE_CODE = BASELINE_ROOT / "baseline.py"
RULES_JSON = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/rules_contract/rules_contract.json"
RULES_README = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/rules_contract/README.md"
FEATURES = PROJECT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
BOOTSTRAP = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
APPROVAL = STUDY / "supervisor/RANK_STAGE_EXECUTION_APPROVAL.json"

ASSET_SHA = "ea2d2b0363539f3b7b0b88c3b2254c14f04095715ac1f137f71beba77a9a36a3"
FEATURE_SHA = "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f"
RULES_SHA = "20cd4b17274018a36efbb1b0cea64eb5d5c9809ed5f3481bea59c734f99fee83"
BASELINE_REFERENCE_HASHES = {
    "baseline_plan": "818e8a268d2955890f7185157f9503ffc4c24df035839354bc74f5804a71fe62",
    "baseline_code": "c7c6fb27ac43bdf4eba952a30ecdb957f4c1c19575bd856e50eba9b87455a6c7",
    "baseline_preflight": "10c5a75c79055da3e5c9278ab23dd3a75bfbd6a8fd64121a3dbff315d8754494",
    "baseline_metrics": "35dd5adbe954af6b086e917267a4ae08ca0d1974cdea43ed61a93a2db60d86ff",
    "baseline_runners": "c4416ec90ff426d2debedbfc897dbc5be6ee85df48180ba940e96a81a5b15110",
    "baseline_selection": "6f0dcce5e3c2e68f06c7cb209bc8cc279e24e6b274aef45cd33e5e3d97e8e7f0",
    "baseline_year_summaries": "4c67d073f812d909c6e52db0a2511c111af4c2e70f65964cc6a50e4489082444",
    "baseline_reliability": "d319ff030e62c08365e42c699a0000eb079d43d291166cc3df2d364b477a3652",
    "baseline_contract_ledger": "fe3f58e3ab071e1f8eb5a527c28f665fbdecca1314ec778bbd98e320ccd51bac",
    "baseline_report": "adab63dab6fe8ebe5eb663788b5e7dd4dd4618d0d9ac5f54fc32c7e288565ed1",
    "rules_contract": RULES_SHA,
}

STUDY_ID = "F1_STYLE6_FULLFIELD_PL_RANK_STAGE_TEMPERATURE_20261022_V1"
T_BOUNDS = (0.35, 4.0)
COMMON_T = 1.1837152381349905
RAW_T = 1.0
EPS = 1e-15
TIE_TOLERANCE = 1e-12
OUTPUT_BUDGET = 20_000_000
SESSION_BUDGET = 300_000_000
POOL_ORDER = ("WIN", "PLC", "QNL", "EXA", "QPL", "TLA", "TRI")
CATEGORICAL = frozenset(("WIN", "QNL", "EXA", "TLA", "TRI"))
POOL_MIN_STARTERS = {"WIN": 2, "QNL": 3, "EXA": 3, "TLA": 4, "TRI": 4, "PLC": 5, "QPL": 5}
BIN_EDGES = np.asarray(
    [0.0, 0.00001, 0.00005, 0.0001, 0.00025, 0.0005, 0.001, 0.0025,
     0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0],
    dtype=np.float64,
)
EXPECTED_CAL = {2019: (5890, 576), 2020: (3290, 329), 2021: (4331, 418), 2022: (5261, 512), 2023: (6506, 657)}
EXPECTED_EVAL = {2024: (6329, 637), 2025: (6410, 654), 2026: (4673, 488)}
EXPECTED_SCHEDULE_SHA = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
EXPECTED_DATE_SHA = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"

FIT_OUTPUT_NAMES = (
    "fit_receipt.json", "report.json", "candidate_race_metrics.parquet",
    "candidate_runner_marginals.parquet", "candidate_reliability_bins.parquet",
    "pool_comparisons.parquet", "pool_year_comparisons.parquet",
    "selection_ledger.parquet", "selection_change_ledger.parquet",
    "selection_change_summary.json",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def json_read(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def project_relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT.resolve()).as_posix()


def experiment_bytes() -> int:
    return sum(p.stat().st_size for p in EXPERIMENT.rglob("*") if p.is_file())


def check_output_budget() -> None:
    size = experiment_bytes()
    require(size <= OUTPUT_BUDGET, f"rank-stage experiment storage {size} exceeds {OUTPUT_BUDGET} bytes")


def atomic_json(path: Path, value: Any, *, replace: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(replace or not path.exists(), f"refusing to overwrite {project_relative(path)}")
    temp = path.with_name(path.name + ".tmp")
    require(not temp.exists(), f"temporary output already exists: {project_relative(temp)}")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    check_output_budget()
    os.replace(temp, path)
    check_output_budget()


def atomic_parquet(path: Path, frame: pd.DataFrame, *, replace: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(replace or not path.exists(), f"refusing to overwrite {project_relative(path)}")
    temp = path.with_name(path.name + ".tmp")
    require(not temp.exists(), f"temporary output already exists: {project_relative(temp)}")
    frame.to_parquet(temp, index=False, compression="zstd")
    check_output_budget()
    os.replace(temp, path)
    check_output_budget()


def expected_reference_paths() -> dict[str, Path]:
    return {
        "baseline_plan": BASELINE_PLAN,
        "baseline_code": BASELINE_CODE,
        "baseline_preflight": BASELINE_PREFLIGHT,
        "baseline_metrics": BASELINE_METRICS,
        "baseline_runners": BASELINE_RUNNERS,
        "baseline_selection": BASELINE_SELECTION,
        "baseline_year_summaries": BASELINE_YEAR,
        "baseline_reliability": BASELINE_BINS,
        "baseline_contract_ledger": BASELINE_CONTRACT,
        "baseline_report": BASELINE_REPORT,
        "rules_contract": RULES_JSON,
    }


def verify_references() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name, path in expected_reference_paths().items():
        require(path.is_file(), f"missing immutable reference: {project_relative(path)}")
        actual = sha256_file(path)
        expected = BASELINE_REFERENCE_HASHES[name]
        require(actual == expected, f"immutable reference hash changed: {name}")
        hashes[name] = actual
    require(sha256_file(ASSET_MANIFEST) == ASSET_SHA, "raw asset manifest SHA mismatch")
    require(sha256_file(FEATURES) == FEATURE_SHA, "frozen feature SHA mismatch")
    require(sha256_file(RULES_JSON) == RULES_SHA, "official rules contract SHA mismatch")
    require(RULES_README.is_file(), "rules contract README is missing")
    return hashes


@dataclass(frozen=True)
class ScoreSource:
    year: int
    role: str
    score_path: Path
    meta_path: Path
    score_sha: str
    meta_sha: str
    expected_rows: int
    expected_races: int
    min_date: str
    max_date: str


def source_specs(manifest: dict[str, Any], previous_preflight: dict[str, Any]) -> tuple[list[ScoreSource], list[ScoreSource]]:
    previous_sources = {(int(s["year"]), str(s["role"])): s for s in previous_preflight["sources"]}
    training: list[ScoreSource] = []
    evaluation: list[ScoreSource] = []
    for asset in manifest["raw_oos_score_assets"]:
        year = int(asset["label_year"])
        if year not in EXPECTED_CAL:
            continue
        prior = previous_sources[(year, "calibration")]
        require(asset["score_semantics"] == "raw_score_before_temperature", f"non-raw training score year={year}")
        require(asset["sha256"] == prior["score_sha256"], f"training manifest hash differs from baseline audit year={year}")
        training.append(ScoreSource(
            year=year, role="calibration", score_path=PROJECT / asset["path"],
            meta_path=PROJECT / asset["provider_meta_path"], score_sha=asset["sha256"],
            meta_sha=prior["meta_sha256"], expected_rows=int(asset["rows"]), expected_races=int(asset["races"]),
            min_date=str(asset["date_range"][0]), max_date=str(asset["date_range"][1])))
    for asset in manifest["evaluation_score_assets"]:
        year = int(asset["evaluation_year"])
        prior = previous_sources[(year, "evaluation")]
        require(asset["sha256"] == prior["score_sha256"], f"evaluation manifest hash differs from baseline audit year={year}")
        evaluation.append(ScoreSource(
            year=year, role="evaluation", score_path=PROJECT / asset["path"],
            meta_path=PROJECT / prior["meta_path"], score_sha=asset["sha256"],
            meta_sha=prior["meta_sha256"], expected_rows=int(asset["rows"]), expected_races=int(asset["races"]),
            min_date=str(prior["target_min_date"]), max_date=str(prior["target_max_date"])))
    training.sort(key=lambda s: s.year)
    evaluation.sort(key=lambda s: s.year)
    require([s.year for s in training] == sorted(EXPECTED_CAL), "training score years are not 2019–2023")
    require([s.year for s in evaluation] == sorted(EXPECTED_EVAL), "evaluation score years are not 2024–2026")
    return training, evaluation


def load_feature_frame() -> pd.DataFrame:
    cols = ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
            "finish_position", "field_n", "history_cutoff"]
    frame = pd.read_parquet(FEATURES, columns=cols)
    require(list(frame.columns) == cols, "frozen feature schema changed")
    require(frame["api_record_id"].is_unique, "duplicate feature api_record_id")
    require(frame["race_id"].notna().all() and frame["horse_id"].notna().all(), "null feature race/horse key")
    frame["race_date"] = pd.to_datetime(frame["race_date"], errors="coerce")
    frame["history_cutoff"] = pd.to_datetime(frame["history_cutoff"], errors="coerce")
    require(frame["race_date"].notna().all() and frame["history_cutoff"].notna().all(), "invalid feature date")
    require(((frame["race_date"] - frame["history_cutoff"]).dt.days == 2).all(), "history cutoff is not race date minus two days")
    for col in ("api_record_id", "horse_id", "horse_number", "finish_position", "field_n", "year"):
        require(frame[col].notna().all(), f"null required feature column {col}")
    return frame


def validate_provider_meta(spec: ScoreSource, joined: pd.DataFrame) -> dict[str, Any]:
    require(spec.score_path.is_file() and spec.meta_path.is_file(), f"missing score/meta for {spec.year} {spec.role}")
    require(sha256_file(spec.score_path) == spec.score_sha, f"score hash mismatch year={spec.year} role={spec.role}")
    require(sha256_file(spec.meta_path) == spec.meta_sha, f"metadata hash mismatch year={spec.year} role={spec.role}")
    meta = json_read(spec.meta_path)
    prefix = "calibration" if spec.role == "calibration" else "evaluation"
    target_min = pd.Timestamp(joined["race_date"].min())
    target_max = pd.Timestamp(joined["race_date"].max())
    require(target_min.strftime("%Y-%m-%d") == spec.min_date and target_max.strftime("%Y-%m-%d") == spec.max_date,
            f"target date range mismatch year={spec.year} role={spec.role}")
    require(pd.Timestamp(meta["refit_max"]) <= target_min - pd.Timedelta(days=2),
            f"provider refit_max violates T-2 year={spec.year} role={spec.role}")
    require(pd.Timestamp(meta[f"{prefix}_min"]) == target_min and pd.Timestamp(meta[f"{prefix}_max"]) == target_max,
            f"metadata target dates changed year={spec.year} role={spec.role}")
    return {"refit_max": str(meta["refit_max"]), "target_min_date": spec.min_date,
            "target_max_date": spec.max_date,
            "minimum_target_minus_refit_days": int((target_min - pd.Timestamp(meta["refit_max"])).days),
            "score_sha256": spec.score_sha, "meta_sha256": spec.meta_sha,
            "rows": int(spec.expected_rows), "races": int(spec.expected_races),
            "role": spec.role, "year": spec.year, "score_semantics": "raw_score_before_temperature"}


def records_from_joined(joined: pd.DataFrame, expected_races: int, *, keep_scores: bool) -> list[dict[str, Any]]:
    require(joined["race_id"].nunique() == expected_races, f"race count changed: expected {expected_races}")
    records: list[dict[str, Any]] = []
    for race_id, group in joined.groupby("race_id", sort=True):
        n = int(group["field_n"].iloc[0])
        require(group["field_n"].nunique() == 1 and n == len(group), f"field count/roster mismatch {race_id}")
        require(group["horse_id"].is_unique and group["horse_number"].is_unique, f"duplicate horse key {race_id}")
        require(group["race_date"].nunique() == 1 and group["year"].nunique() == 1, f"race date/year conflict {race_id}")
        ranks = group["finish_position"].astype(int).to_numpy()
        require(n >= 3 and sorted(ranks.tolist()) == list(range(1, n + 1)), f"incomplete/tied/invalid ranks {race_id}")
        require(group["api_record_id"].is_unique, f"duplicate score join key within race {race_id}")
        ordered = group.sort_values("horse_number", kind="mergesort")
        rec: dict[str, Any] = {
            "race_id": str(race_id),
            "date": pd.Timestamp(group["race_date"].iloc[0]).strftime("%Y-%m-%d"),
            "year": int(group["year"].iloc[0]),
            "n": n,
            "numbers": ordered["horse_number"].astype(np.int64).to_numpy(),
            "ranks": ordered["finish_position"].astype(np.int64).to_numpy(),
        }
        if keep_scores:
            rec["scores"] = ordered["score"].astype(np.float64).to_numpy()
        records.append(rec)
    return records


def load_source_records(frame: pd.DataFrame, spec: ScoreSource, *, keep_scores: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    subset = frame.loc[frame["year"] == spec.year].copy()
    require(len(subset) == spec.expected_rows, f"feature row count changed year={spec.year}")
    score = pd.read_parquet(spec.score_path)
    require(list(score.columns) == ["api_record_id", "score"], f"raw score schema changed: {project_relative(spec.score_path)}")
    require(score["api_record_id"].dtype == np.dtype("int64"), "score api_record_id must be int64")
    require(score["score"].dtype == np.dtype("float64"), "raw score must be float64")
    require(score["api_record_id"].is_unique and np.isfinite(score["score"].to_numpy()).all(), "duplicate key/non-finite raw score")
    require(len(score) == spec.expected_rows, f"score row count changed year={spec.year} role={spec.role}")
    require(set(subset["api_record_id"].astype(np.int64)) == set(score["api_record_id"]),
            f"score-feature one-to-one key coverage mismatch year={spec.year} role={spec.role}")
    joined = subset.merge(score, on="api_record_id", how="inner", validate="one_to_one", sort=False)
    require(len(joined) == spec.expected_rows, "score join changed row count")
    meta_summary = validate_provider_meta(spec, joined)
    records = records_from_joined(joined, spec.expected_races, keep_scores=keep_scores)
    require(sum(r["n"] for r in records) == spec.expected_rows, f"race roster runner count changed year={spec.year}")
    return records, meta_summary


def load_cohorts(*, keep_scores: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    manifest = json_read(ASSET_MANIFEST)
    previous_preflight = json_read(BASELINE_PREFLIGHT)
    train_specs, eval_specs = source_specs(manifest, previous_preflight)
    features = load_feature_frame()
    source_summaries: list[dict[str, Any]] = []
    training: list[dict[str, Any]] = []
    evaluation: list[dict[str, Any]] = []
    for spec in train_specs + eval_specs:
        records, summary = load_source_records(features, spec, keep_scores=keep_scores)
        source_summaries.append(summary)
        if spec.role == "calibration":
            training.extend(records)
        else:
            evaluation.extend(records)
    training.sort(key=lambda r: (r["date"], r["race_id"]))
    evaluation.sort(key=lambda r: (r["date"], r["race_id"]))
    require(len(training) == 2492 and sum(r["n"] for r in training) == 25278, "2019–2023 training cohort changed")
    require(len(evaluation) == 1779 and sum(r["n"] for r in evaluation) == 17412, "2024–2026 evaluation cohort changed")
    require({r["year"] for r in training} == {2019, 2020, 2021, 2022, 2023}, "training year boundary changed")
    require({r["year"] for r in evaluation} == {2024, 2025, 2026}, "evaluation year boundary changed")
    dates = sorted({r["date"] for r in evaluation})
    require(len(dates) == 269, "evaluation date count changed")
    require(sum(r["n"] == 7 for r in evaluation) == 36, "expected 36 PLC-unknown actual-seven races")
    return training, evaluation, {"sources": source_summaries, "evaluation_dates": dates}


def verify_baseline_artifacts() -> dict[str, Any]:
    preflight = json_read(BASELINE_PREFLIGHT)
    report = json_read(BASELINE_REPORT)
    require(preflight.get("status") == "PASS_STRUCTURAL_PREFLIGHT_NO_FIT_OR_METRICS", "prior baseline preflight is not PASS")
    require(preflight.get("calibration_races") == 2492 and preflight.get("evaluation_races") == 1779,
            "prior baseline cohort counts differ")
    require(report["fit"]["temperature"] == COMMON_T, "previous common-T comparator changed")
    require(report["metric_contract"]["epsilon"] == EPS, "previous epsilon contract changed")
    old_metrics = pd.read_parquet(BASELINE_METRICS)
    required_cols = {"pool", "race_nll", "race_brier", "ticket_count", "event_count", "race_id", "race_date", "year", "field_n", "arm"}
    require(required_cols.issubset(old_metrics.columns), "baseline race metric schema changed")
    require(set(old_metrics["arm"].unique()) == {"T1", "TEMP"}, "baseline arms changed")
    require(len(old_metrics) == 24834, "baseline metric row count changed")
    require(old_metrics.groupby(["arm", "pool"]).size().to_dict() == {
        (arm, pool): (1743 if pool == "PLC" else 1779)
        for arm in ("T1", "TEMP") for pool in POOL_ORDER
    }, "baseline metric denominators changed")
    for path, expected_rows, required in (
        (BASELINE_RUNNERS, 34824, {"race_id", "race_date", "year", "horse_number", "arm", "p_win", "p_exact2", "p_exact3", "p_top2", "p_top3"}),
        (BASELINE_SELECTION, 24834, {"pool", "selected_ticket_key", "selected_probability", "selected_hit", "race_id", "race_date", "year", "arm"}),
        (BASELINE_YEAR, 42, {"pool", "arm", "year", "races", "mean_race_nll", "mean_race_brier"}),
        (BASELINE_BINS, 224, {"pool", "arm", "bin_index", "event_count", "mean_probability", "observed_rate", "weighting"}),
        (BASELINE_CONTRACT, 12453, {"race_id", "pool", "actual_field_n", "N_at_open", "event_label_status"}),
    ):
        table = pd.read_parquet(path)
        require(len(table) == expected_rows and required.issubset(table.columns), f"baseline output schema/count changed: {path.name}")
    return {"report": report, "metrics": old_metrics, "preflight": preflight}


def source_preflight() -> None:
    require(OUTPUT.is_dir(), "outputs directory missing")
    ref_hashes = verify_references()
    baseline = verify_baseline_artifacts()
    training, evaluation, cohort_info = load_cohorts(keep_scores=False)
    rules = json_read(RULES_JSON)
    minima = rules["primary_rule"]["article_4_minimum_starters"]
    require({pool: int(minima[pool]) for pool in POOL_ORDER} == POOL_MIN_STARTERS,
            "official minimum-starter rule changed")
    plc_rule = rules["primary_rule"]["plc_field_split"]
    require(plc_rule.get("5_to_7") == "Top2" and plc_rule.get("8_or_more") == "Top3", "PLC split changed")
    qpl = next(pool for pool in rules["event_space"]["pools"] if pool["code"] == "QPL")
    require("places 1-3" in qpl["event"], "QPL Top3 event rule changed")
    plc_unknown = [r for r in evaluation if 5 <= r["n"] <= 7]
    require(len(plc_unknown) == 36 and all(r["n"] == 7 for r in plc_unknown), "PLC unknown denominator changed")
    schedule_receipt = json_read(BOOTSTRAP_RECEIPT)
    require(schedule_receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS", "bootstrap schedule is not frozen")
    require(schedule_receipt.get("schedule_sha256") == EXPECTED_SCHEDULE_SHA == sha256_file(BOOTSTRAP),
            "bootstrap schedule hash mismatch")
    dates = cohort_info["evaluation_dates"]
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(date_hash == EXPECTED_DATE_SHA == schedule_receipt.get("date_inventory_sha256"), "bootstrap date roster changed")
    schedule = np.load(BOOTSTRAP, mmap_mode="r", allow_pickle=False)
    require(schedule.shape == (2000, 269) and schedule.dtype == np.int32, "bootstrap shape/dtype changed")
    require(int(schedule.min()) >= 0 and int(schedule.max()) < len(dates), "bootstrap index out of range")
    quarantine = pd.DataFrame([{
        "race_id": r["race_id"], "race_date": r["date"], "year": r["year"], "pool": "PLC",
        "actual_field_n": r["n"], "opening_count": None, "opening_count_source": "unknown",
        "reason": "opening_field_unknown_actual_5_to_7", "scope": "PLC only",
    } for r in plc_unknown])
    require(len(quarantine) == 36, "preflight PLC quarantine ledger changed")
    report = {
        "status": "PASS_STRUCTURAL_PREFLIGHT_NO_FIT_NO_REAL_PROBABILITIES_NO_METRICS",
        "study_id": STUDY_ID,
        "code_sha256": sha256_file(EXPERIMENT / "rank_stage.py"),
        "plan_sha256": sha256_file(EXPERIMENT / "PLAN.md"),
        "asset_manifest_path": project_relative(ASSET_MANIFEST),
        "asset_manifest_sha256": sha256_file(ASSET_MANIFEST),
        "feature_path": project_relative(FEATURES),
        "feature_sha256": sha256_file(FEATURES),
        "rules_contract_path": project_relative(RULES_JSON),
        "rules_contract_sha256": sha256_file(RULES_JSON),
        "rules_readme_sha256": sha256_file(RULES_README),
        "baseline_reference_hashes": ref_hashes,
        "baseline_common_temperature": COMMON_T,
        "raw_win_reference_temperature": RAW_T,
        "training_years": sorted(EXPECTED_CAL),
        "training_races": len(training),
        "training_runners": sum(r["n"] for r in training),
        "evaluation_years": sorted(EXPECTED_EVAL),
        "evaluation_races": len(evaluation),
        "evaluation_runners": sum(r["n"] for r in evaluation),
        "evaluation_dates": len(dates),
        "source_rows": cohort_info["sources"],
        "plc_eligible_races": sum(r["n"] >= 8 for r in evaluation),
        "plc_unknown_races": len(quarantine),
        "quarantine_path": "outputs/preflight_quarantine.parquet",
        "quarantine_rows": len(quarantine),
        "bootstrap_schedule_path": project_relative(BOOTSTRAP),
        "bootstrap_schedule_sha256": sha256_file(BOOTSTRAP),
        "bootstrap_receipt_path": project_relative(BOOTSTRAP_RECEIPT),
        "bootstrap_receipt_sha256": sha256_file(BOOTSTRAP_RECEIPT),
        "bootstrap_date_inventory_sha256": date_hash,
        "baseline_contract_ledger_path": project_relative(BASELINE_CONTRACT),
        "baseline_contract_ledger_sha256": sha256_file(BASELINE_CONTRACT),
        "baseline_metric_rows_per_arm": {"WIN": 1779, "PLC": 1743, "QNL": 1779, "EXA": 1779,
                                          "QPL": 1779, "TLA": 1779, "TRI": 1779},
        "models_loaded": False,
        "database_opened": False,
        "temperatures_fit": False,
        "real_race_probabilities_computed": False,
        "outcome_metrics_computed": False,
        "outputs_bytes_before_preflight": experiment_bytes(),
        "new_experiment_storage_cap_bytes": OUTPUT_BUDGET,
        "session_storage_cap_bytes": SESSION_BUDGET,
        "note": "Structural checks only; no PL probabilities or observed-outcome metrics were calculated.",
    }
    atomic_parquet(OUTPUT / "preflight_quarantine.parquet", quarantine, replace=True)
    report["preflight_quarantine_sha256"] = sha256_file(OUTPUT / "preflight_quarantine.parquet")
    atomic_json(OUTPUT / "source_preflight.json", report, replace=True)
    print(json.dumps({k: report[k] for k in (
        "status", "training_races", "training_runners", "evaluation_races", "evaluation_dates",
        "plc_eligible_races", "plc_unknown_races", "code_sha256", "plan_sha256")}, indent=2))


def remaining_indices(n: int, chosen: Iterable[int]) -> np.ndarray:
    mask = np.ones(n, dtype=bool)
    for ix in chosen:
        mask[int(ix)] = False
    return np.flatnonzero(mask)


def log_softmax_choice(scores: np.ndarray, chosen_index: int, remaining: np.ndarray, temperature: float) -> float:
    vals = np.asarray(scores, dtype=np.float64)[remaining] / float(temperature)
    selected = int(np.flatnonzero(remaining == int(chosen_index))[0])
    maximum = float(vals.max())
    return float(vals[selected] - maximum - math.log(float(np.exp(vals - maximum).sum())))


def actual_order_indices(ranks: np.ndarray) -> list[int]:
    order = []
    for rank in (1, 2, 3):
        found = np.flatnonzero(np.asarray(ranks) == rank)
        require(len(found) == 1, f"actual rank {rank} is not unique")
        order.append(int(found[0]))
    return order


def stage_conditional_nll(record: dict[str, Any], temperature: float, stage: int) -> float:
    require(stage in (1, 2, 3), "stage must be 1, 2, or 3")
    scores = np.asarray(record["scores"], dtype=np.float64)
    actual = actual_order_indices(np.asarray(record["ranks"], dtype=np.int64))
    earlier = actual[:stage - 1]
    remaining = remaining_indices(len(scores), earlier)
    # This full-field set contains all starters not selected at an earlier stage,
    # including actual finishers below third for stage 3.
    return -log_softmax_choice(scores, actual[stage - 1], remaining, temperature)


def fit_one_stage(training: list[dict[str, Any]], stage: int) -> dict[str, Any]:
    require(len(training) == 2492, "fixed training race count changed")

    def objective(temperature: float) -> float:
        values = [stage_conditional_nll(record, float(temperature), stage) for record in training]
        result = float(np.mean(values))
        require(math.isfinite(result), f"non-finite stage {stage} calibration objective")
        return result

    result = minimize_scalar(objective, bounds=T_BOUNDS, method="bounded", options={"xatol": 1e-12})
    require(result.success and math.isfinite(float(result.x)), f"stage {stage} temperature optimizer failed: {result.message}")
    candidates = [(T_BOUNDS[0], objective(T_BOUNDS[0])), (T_BOUNDS[1], objective(T_BOUNDS[1])),
                  (float(result.x), objective(float(result.x)))]
    temperature, best_nll = min(candidates, key=lambda item: (item[1], item[0]))
    common_nll = objective(COMMON_T)
    beta_stats = stage_inverse_temperature_stats(training, 1.0 / temperature, stage)
    require(beta_stats["mean_hessian"] > 0.0, f"stage {stage} temperature is flat/unidentified at selected point")
    candidate_minus_common = float(best_nll - common_nll)
    require(candidate_minus_common <= 1e-10,
            f"stage {stage} fitted training NLL is worse than common-T beyond numerical tolerance")
    boundary = temperature in T_BOUNDS
    boundary_gradient_check = None
    if boundary and temperature == T_BOUNDS[0]:
        boundary_gradient_check = bool(beta_stats["mean_gradient"] <= 1e-8)
        require(boundary_gradient_check, f"stage {stage} lower-T boundary has inconsistent inverse-T gradient")
    elif boundary and temperature == T_BOUNDS[1]:
        boundary_gradient_check = bool(beta_stats["mean_gradient"] >= -1e-8)
        require(boundary_gradient_check, f"stage {stage} upper-T boundary has inconsistent inverse-T gradient")
    return {
        "stage": stage, "temperature": float(temperature), "objective_mean_conditional_nll": float(best_nll),
        "common_T_training_mean_conditional_nll": common_nll,
        "candidate_minus_common_T_training_mean_conditional_nll": candidate_minus_common,
        "training_not_worse_than_common_T_with_1e-10_numeric_tolerance": candidate_minus_common <= 1e-10,
        "optimizer_x": float(result.x), "optimizer_success": bool(result.success),
        "optimizer_message": str(result.message),
        "bound_objectives": {str(T_BOUNDS[0]): candidates[0][1], str(T_BOUNDS[1]): candidates[1][1]},
        "observation_races": len(training), "bounds": list(T_BOUNDS),
        "method": "scipy.optimize.minimize_scalar(method=bounded,xatol=1e-12)",
        "training_denominator": "all remaining full-field starters after actual earlier ranks removed",
        "inverse_temperature_objective_diagnostics": beta_stats,
        "convexity_checked_in_inverse_temperature": True,
        "boundary_optimum": boundary,
        "boundary_inverse_temperature_gradient_sign_check": boundary_gradient_check,
    }


def stage_inverse_temperature_stats(records: list[dict[str, Any]], beta: float, stage: int) -> dict[str, float]:
    losses: list[float] = []
    gradients: list[float] = []
    hessians: list[float] = []
    for record in records:
        scores = np.asarray(record["scores"], dtype=np.float64)
        actual = actual_order_indices(np.asarray(record["ranks"], dtype=np.int64))
        remaining = remaining_indices(len(scores), actual[:stage - 1])
        values = beta * scores[remaining]
        probabilities = stable_softmax(values)
        selected_pos = int(np.flatnonzero(remaining == actual[stage - 1])[0])
        selected_score = float(scores[actual[stage - 1]])
        mean_score = float(np.dot(probabilities, scores[remaining]))
        variance = float(np.dot(probabilities, np.square(scores[remaining] - mean_score)))
        maximum = float(values.max())
        lse = maximum + math.log(float(np.exp(values - maximum).sum()))
        losses.append(float(lse - beta * selected_score))
        gradients.append(mean_score - selected_score)
        hessians.append(variance)
        require(0 <= selected_pos < len(remaining), "selected horse is absent from stage risk set")
    hessian = float(np.mean(hessians))
    require(math.isfinite(hessian) and math.isfinite(float(np.mean(gradients))) and math.isfinite(float(np.mean(losses))),
            f"stage {stage} inverse-temperature diagnostics are non-finite")
    require(hessian >= -1e-12, f"stage {stage} inverse-temperature Hessian is negative")
    return {"mean_objective": float(np.mean(losses)), "mean_gradient": float(np.mean(gradients)),
            "mean_hessian": hessian, "minimum_race_hessian": float(min(hessians)),
            "maximum_race_hessian": float(max(hessians)), "observations": len(records)}


def fit_stages(training: list[dict[str, Any]]) -> dict[str, Any]:
    stages = [fit_one_stage(training, stage) for stage in (1, 2, 3)]
    return {"stages": stages, "temperatures": [x["temperature"] for x in stages],
            "training_years": [2019, 2020, 2021, 2022, 2023], "training_races": len(training),
            "training_runner_rows": sum(r["n"] for r in training), "regularization": "none",
            "objective_scope": "each stage separately minimizes race-equal conditional NLL on the same 2,492 races"}


def plc_top_from_actual(n: int) -> int | None:
    return 3 if n >= 8 else None


def stable_softmax(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    maximum = float(np.max(values))
    exp_values = np.exp(values - maximum)
    return exp_values / float(exp_values.sum())


def probability_maps(record: dict[str, Any], temperatures: tuple[float, float, float]) -> tuple[dict[str, dict[tuple[int, ...], float]], dict[str, np.ndarray], float]:
    scores = np.asarray(record["scores"], dtype=np.float64)
    numbers = np.asarray(record["numbers"], dtype=np.int64)
    n = len(scores)
    require(n == int(record["n"]) and n >= 3, "race runner count invalid")
    require(len(set(map(int, numbers))) == n, "duplicate horse number in race")
    t1, t2, t3 = map(float, temperatures)
    require(all(math.isfinite(t) and t > 0 for t in (t1, t2, t3)), "temperatures must be positive and finite")
    utility1, utility2, utility3 = scores / t1, scores / t2, scores / t3
    maps: dict[str, defaultdict[tuple[int, ...], float]] = {pool: defaultdict(float) for pool in POOL_ORDER}
    p_win = np.zeros(n, dtype=np.float64)
    p_exact2 = np.zeros(n, dtype=np.float64)
    p_exact3 = np.zeros(n, dtype=np.float64)
    joint_mass = 0.0
    for i in range(n):
        rem1 = remaining_indices(n, ())
        p_i = float(stable_softmax(utility1[rem1])[i])
        left_after_i = remaining_indices(n, (i,))
        p2_values = stable_softmax(utility2[left_after_i])
        for j in left_after_i:
            p_j_given_i = float(p2_values[np.flatnonzero(left_after_i == j)[0]])
            left_after_ij = remaining_indices(n, (i, int(j)))
            # Crucial full-field stage-3 denominator: N-2 remaining runners,
            # including actual finishers below third. Never condition on a Top3 set.
            p3_values = stable_softmax(utility3[left_after_ij])
            pair_mass = p_i * p_j_given_i
            for ix_k, k in enumerate(left_after_ij):
                q = pair_mass * float(p3_values[ix_k])
                joint_mass += q
                p_win[i] += q
                p_exact2[j] += q
                p_exact3[k] += q
                hn_i, hn_j, hn_k = int(numbers[i]), int(numbers[j]), int(numbers[k])
                maps["QNL"][tuple(sorted((hn_i, hn_j)))] += q
                maps["EXA"][(hn_i, hn_j)] += q
                maps["TLA"][tuple(sorted((hn_i, hn_j, hn_k)))] += q
                maps["TRI"][(hn_i, hn_j, hn_k)] += q
                for pair in itertools.combinations(sorted((hn_i, hn_j, hn_k)), 2):
                    maps["QPL"][pair] += q
    top2 = p_win + p_exact2
    top3 = top2 + p_exact3
    for ix, horse in enumerate(numbers):
        maps["WIN"][(int(horse),)] = float(p_win[ix])
        # For actual N=5..7 the PLC event is unresolved without opening roster.
        # Store a Top2 placeholder only for synthetic/internal shape; no PLC metric is scored.
        maps["PLC"][(int(horse),)] = float(top3[ix] if n >= 8 else top2[ix])
    require(abs(joint_mass - 1.0) <= 3e-11, f"full ordered joint mass mismatch: {joint_mass:.17g}")
    require(abs(float(p_win.sum()) - 1.0) <= 3e-11, "WIN marginal mass mismatch")
    require(abs(float(top2.sum()) - 2.0) <= 3e-11 and abs(float(top3.sum()) - 3.0) <= 3e-11,
            "Top-k marginal mass mismatch")
    require(np.all(p_win <= top2 + 3e-14) and np.all(top2 <= top3 + 3e-14), "nested runner marginals invalid")
    expected_mass = {"WIN": 1.0, "QNL": 1.0, "EXA": 1.0, "QPL": 3.0, "TLA": 1.0, "TRI": 1.0}
    if n >= 8:
        expected_mass["PLC"] = 3.0
    for pool, mass in expected_mass.items():
        require(abs(sum(maps[pool].values()) - mass) <= 4e-11, f"{pool} event mass mismatch")
    marginal = {"p_win": p_win, "p_exact2": p_exact2, "p_exact3": p_exact3, "p_top2": top2, "p_top3": top3}
    return {pool: dict(tickets) for pool, tickets in maps.items()}, marginal, joint_mass


def truth_keys(pool: str, record: dict[str, Any], plc_top: int | None) -> set[tuple[int, ...]]:
    by_rank = {int(rank): int(number) for number, rank in zip(record["numbers"], record["ranks"])}
    first, second, third = by_rank[1], by_rank[2], by_rank[3]
    if pool == "WIN":
        return {(first,)}
    if pool == "PLC":
        require(plc_top in (2, 3), "PLC event top-k is unresolved")
        return {(int(number),) for number, rank in zip(record["numbers"], record["ranks"]) if int(rank) <= plc_top}
    if pool == "QNL":
        return {tuple(sorted((first, second)))}
    if pool == "EXA":
        return {(first, second)}
    if pool == "QPL":
        return {tuple(sorted(pair)) for pair in itertools.combinations((first, second, third), 2)}
    if pool == "TLA":
        return {tuple(sorted((first, second, third)))}
    if pool == "TRI":
        return {(first, second, third)}
    raise AssertionError(pool)


def select_ticket(tickets: dict[tuple[int, ...], float], tolerance: float = TIE_TOLERANCE) -> tuple[tuple[int, ...], float, float, int]:
    require(tickets, "cannot select from empty ticket map")
    maximum = max(float(p) for p in tickets.values())
    tied = [key for key, p in tickets.items() if float(p) >= maximum - tolerance]
    selected = min(tied)
    return selected, float(tickets[selected]), maximum, len(tied)


def event_result(pool: str, tickets: dict[tuple[int, ...], float], truths: set[tuple[int, ...]]) -> dict[str, Any]:
    require(tickets and truths and truths.issubset(tickets), f"missing ticket/outcome: {pool}")
    probs = np.fromiter((float(p) for p in tickets.values()), dtype=np.float64, count=len(tickets))
    labels = np.fromiter((1.0 if key in truths else 0.0 for key in tickets), dtype=np.float64, count=len(tickets))
    if pool in CATEGORICAL:
        require(len(truths) == 1, f"categorical pool has multiple outcomes: {pool}")
        true_p = float(tickets[next(iter(truths))])
        nll = -math.log(max(true_p, EPS))
        brier = float(np.square(probs - labels).sum())
        event_p_mean = true_p
    else:
        clipped = np.clip(probs, EPS, 1.0 - EPS)
        losses = -(labels * np.log(clipped) + (1.0 - labels) * np.log1p(-clipped))
        nll = float(losses.mean())
        brier = float(np.square(probs - labels).mean())
        event_p_mean = float(np.mean([tickets[key] for key in truths]))
    event_probs = [float(tickets[key]) for key in sorted(truths)]
    selected, selected_p, max_p, n_tied = select_ticket(tickets)
    return {
        "race_nll": float(nll), "race_brier": float(brier), "ticket_count": len(tickets),
        "event_count": len(truths), "realized_event_p_mean": float(event_p_mean),
        "realized_event_nll_mean": float(np.mean([-math.log(max(p, EPS)) for p in event_probs])),
        "selected_ticket_key": json.dumps(list(selected), separators=(",", ":")),
        "selected_probability": selected_p, "maximum_probability": max_p,
        "tied_ticket_count": n_tied, "selected_hit": selected in truths,
        "realized_event_keys_json": json.dumps([list(key) for key in sorted(truths)], separators=(",", ":")),
        "realized_event_probabilities_json": json.dumps(event_probs, separators=(",", ":")),
        "tie_tolerance": TIE_TOLERANCE,
    }


def reliability_bin_index(probability: float) -> int:
    ix = int(np.searchsorted(BIN_EDGES, probability, side="right") - 1)
    return min(max(ix, 0), len(BIN_EDGES) - 2)


def accumulate_reliability(acc: dict[tuple[str, int], list[float]], pool: str,
                           tickets: dict[tuple[int, ...], float], truths: set[tuple[int, ...]]) -> None:
    for key, probability in tickets.items():
        idx = reliability_bin_index(float(probability))
        row = acc[(pool, idx)]
        outcome = 1.0 if key in truths else 0.0
        row[0] += 1.0
        row[1] += float(probability)
        row[2] += outcome
        row[3] += (float(probability) - outcome) ** 2


def metric_rows_for_race(record: dict[str, Any], temps: tuple[float, float, float], arm: str,
                         reliability: dict[tuple[str, int], list[float]], *, include_selections: bool
                         ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], float]:
    maps, marginal, joint_mass = probability_maps(record, temps)
    metrics: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    n = int(record["n"])
    plc_top = plc_top_from_actual(n)
    for pool in POOL_ORDER:
        if n < POOL_MIN_STARTERS[pool] or (pool == "PLC" and plc_top is None):
            continue
        truths = truth_keys(pool, record, plc_top)
        result = event_result(pool, maps[pool], truths)
        accumulate_reliability(reliability, pool, maps[pool], truths)
        metrics.append({"pool": pool, "race_id": record["race_id"], "race_date": record["date"],
                        "year": int(record["year"]), "field_n": n, "arm": arm,
                        **{key: result[key] for key in ("race_nll", "race_brier", "ticket_count", "event_count",
                                                        "realized_event_p_mean", "realized_event_nll_mean")}})
        if include_selections:
            selections.append({"pool": pool, "race_id": record["race_id"], "race_date": record["date"],
                               "year": int(record["year"]), "field_n": n, "arm": arm,
                               **{key: result[key] for key in ("selected_ticket_key", "selected_probability",
                                                               "maximum_probability", "tied_ticket_count",
                                                               "selected_hit",
                                                               "realized_event_keys_json", "realized_event_probabilities_json",
                                                               "tie_tolerance")},
                               "realized_event_count": result["event_count"]})
    runner_rows = [{"race_id": record["race_id"], "race_date": record["date"], "year": int(record["year"]),
                    "horse_number": int(number), "p_win": float(marginal["p_win"][ix]),
                    "p_exact2": float(marginal["p_exact2"][ix]), "p_exact3": float(marginal["p_exact3"][ix]),
                    "p_top2": float(marginal["p_top2"][ix]), "p_top3": float(marginal["p_top3"][ix])}
                   for ix, number in enumerate(record["numbers"])]
    return metrics, selections, runner_rows, joint_mass


def reliability_frame(acc: dict[tuple[str, int], list[float]]) -> pd.DataFrame:
    rows = []
    for pool in POOL_ORDER:
        for ix in range(len(BIN_EDGES) - 1):
            count, sum_p, sum_y, sum_brier = acc[(pool, ix)]
            rows.append({"pool": pool, "arm": "CANDIDATE", "bin_index": ix,
                         "bin_left": float(BIN_EDGES[ix]), "bin_right": float(BIN_EDGES[ix + 1]),
                         "right_inclusive": ix == len(BIN_EDGES) - 2, "event_count": int(count),
                         "mean_probability": (sum_p / count if count else None),
                         "observed_rate": (sum_y / count if count else None),
                         "mean_event_brier": (sum_brier / count if count else None),
                         "weighting": "pooled_ticket_event_count"})
    return pd.DataFrame(rows)


def compute_candidate_eval(evaluation: list[dict[str, Any]], temperatures: tuple[float, float, float]
                           ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    reliability = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    metric_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    runner_rows: list[dict[str, Any]] = []
    for record in evaluation:
        rows, choices, runners, _ = metric_rows_for_race(record, temperatures, "CANDIDATE", reliability, include_selections=True)
        metric_rows.extend(rows)
        selection_rows.extend(choices)
        runner_rows.extend(runners)
    expected_rows = 6 * 1779 + 1743
    require(len(metric_rows) == expected_rows, f"candidate evaluation metric rows changed: {len(metric_rows)}")
    require(len(runner_rows) == 17412 and len(selection_rows) == expected_rows, "candidate runner/selection row count changed")
    return pd.DataFrame(metric_rows), pd.DataFrame(runner_rows), reliability_frame(reliability), pd.DataFrame(selection_rows)


def selection_only_rows(record: dict[str, Any], temperatures: tuple[float, float, float], arm: str) -> list[dict[str, Any]]:
    maps, _, _ = probability_maps(record, temperatures)
    rows = []
    n = int(record["n"])
    plc_top = plc_top_from_actual(n)
    for pool in POOL_ORDER:
        if n < POOL_MIN_STARTERS[pool] or (pool == "PLC" and plc_top is None):
            continue
        truths = truth_keys(pool, record, plc_top)
        chosen, selected_p, maximum_p, tied_count = select_ticket(maps[pool])
        realized_ps = [float(maps[pool][key]) for key in sorted(truths)]
        rows.append({"pool": pool, "race_id": record["race_id"], "race_date": record["date"],
                     "year": int(record["year"]), "field_n": n, "arm": arm,
                     "selected_ticket_key": json.dumps(list(chosen), separators=(",", ":")),
                     "selected_probability": selected_p, "maximum_probability": maximum_p,
                     "tied_ticket_count": tied_count, "selected_hit": chosen in truths,
                     "realized_event_count": len(truths),
                     "realized_event_keys_json": json.dumps([list(key) for key in sorted(truths)], separators=(",", ":")),
                     "realized_event_probabilities_json": json.dumps(realized_ps, separators=(",", ":")),
                     "tie_tolerance": TIE_TOLERANCE})
    return rows


def build_selection_diagnostics(evaluation: list[dict[str, Any]], candidate_selections: pd.DataFrame
                                ) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = candidate_selections.to_dict(orient="records")
    for record in evaluation:
        rows.extend(selection_only_rows(record, (COMMON_T, COMMON_T, COMMON_T), "COMMON"))
        rows.extend(selection_only_rows(record, (RAW_T, RAW_T, RAW_T), "RAW_T1"))
    frame = pd.DataFrame(rows)
    require(len(frame) == (6 * 1779 + 1743) * 3, "selection diagnostic denominator changed")
    changes: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"tie_tolerance": TIE_TOLERANCE, "policy": "p >= pmax - tolerance; lexicographically smallest horse-number tuple",
                               "probability_or_loss_values_use_tolerance": False, "comparisons": {}}
    for name, left_arm, right_arm in (("candidate_vs_common", "CANDIDATE", "COMMON"),
                                      ("candidate_vs_raw_T1", "CANDIDATE", "RAW_T1"),
                                      ("common_vs_raw_T1", "COMMON", "RAW_T1")):
        left = frame.loc[frame["arm"] == left_arm].set_index(["pool", "race_id"])
        right = frame.loc[frame["arm"] == right_arm].set_index(["pool", "race_id"])
        require(left.index.equals(right.index), f"selection keys differ for {name}")
        changed = left["selected_ticket_key"].astype(str) != right["selected_ticket_key"].astype(str)
        per_pool = {}
        for pool in POOL_ORDER:
            idx = left.index.get_level_values("pool") == pool
            count = int(changed[idx].sum())
            per_pool[pool] = {"race_pools": int(idx.sum()), "ticket_key_changes": count,
                              "left_hit_count": int(left.loc[idx, "selected_hit"].sum()),
                              "right_hit_count": int(right.loc[idx, "selected_hit"].sum())}
            if count:
                keys = left.index[idx][changed[idx]]
                for key in keys:
                    lrow, rrow = left.loc[key], right.loc[key]
                    changes.append({"comparison": name, "pool": key[0], "race_id": key[1],
                                    "left_arm": left_arm, "right_arm": right_arm,
                                    "left_ticket_key": lrow["selected_ticket_key"],
                                    "right_ticket_key": rrow["selected_ticket_key"],
                                    "left_selected_probability": float(lrow["selected_probability"]),
                                    "right_selected_probability": float(rrow["selected_probability"]),
                                    "left_maximum_probability": float(lrow["maximum_probability"]),
                                    "right_maximum_probability": float(rrow["maximum_probability"]),
                                    "left_selected_hit": bool(lrow["selected_hit"]),
                                    "right_selected_hit": bool(rrow["selected_hit"]),
                                    "same_hit": bool(lrow["selected_hit"]) == bool(rrow["selected_hit"])})
        summary["comparisons"][name] = per_pool
    change_columns = ["comparison", "pool", "race_id", "left_arm", "right_arm", "left_ticket_key",
                      "right_ticket_key", "left_selected_probability", "right_selected_probability",
                      "left_maximum_probability", "right_maximum_probability", "left_selected_hit",
                      "right_selected_hit", "same_hit"]
    return frame, pd.DataFrame(changes, columns=change_columns), summary


def compare_losses(candidate: pd.DataFrame, old_metrics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    cand = candidate.copy()
    old_common = old_metrics.loc[old_metrics["arm"] == "TEMP"].copy()
    old_raw = old_metrics.loc[old_metrics["arm"] == "T1"].copy()
    keys = ["pool", "race_id"]
    common = cand.merge(old_common, on=keys, how="outer", suffixes=("_candidate", "_common"), indicator=True,
                       validate="one_to_one")
    require((common["_merge"] == "both").all(), "candidate/common-T race-pool key mismatch")
    for field in ("race_date", "year", "field_n"):
        require((common[f"{field}_candidate"] == common[f"{field}_common"]).all(), f"candidate/common {field} mismatch")
    common["delta_nll"] = common["race_nll_candidate"] - common["race_nll_common"]
    common["delta_brier"] = common["race_brier_candidate"] - common["race_brier_common"]
    rows = []
    years = []
    pool_year_merge = common
    for pool in POOL_ORDER:
        part = pool_year_merge.loc[pool_year_merge["pool"] == pool]
        rows.append({"pool": pool, "races": int(len(part)),
                     "candidate_mean_race_nll": float(part["race_nll_candidate"].mean()),
                     "common_t_mean_race_nll": float(part["race_nll_common"].mean()),
                     "candidate_minus_common_nll": float(part["delta_nll"].mean()),
                     "candidate_mean_race_brier": float(part["race_brier_candidate"].mean()),
                     "common_t_mean_race_brier": float(part["race_brier_common"].mean()),
                     "candidate_minus_common_brier": float(part["delta_brier"].mean())})
        for year in sorted(part["year_candidate"].unique()):
            yp = part.loc[part["year_candidate"] == year]
            years.append({"pool": pool, "year": int(year), "races": int(len(yp)),
                          "candidate_mean_race_nll": float(yp["race_nll_candidate"].mean()),
                          "common_t_mean_race_nll": float(yp["race_nll_common"].mean()),
                          "candidate_minus_common_nll": float(yp["delta_nll"].mean()),
                          "candidate_mean_race_brier": float(yp["race_brier_candidate"].mean()),
                          "common_t_mean_race_brier": float(yp["race_brier_common"].mean()),
                          "candidate_minus_common_brier": float(yp["delta_brier"].mean())})
    win_candidate = cand.loc[cand["pool"] == "WIN"]
    win_raw = win_candidate.merge(old_raw.loc[old_raw["pool"] == "WIN"], on=keys, how="outer",
                                  suffixes=("_candidate", "_raw_T1"), indicator=True, validate="one_to_one")
    require((win_raw["_merge"] == "both").all() and len(win_raw) == 1779, "WIN raw-T1 comparison mismatch")
    for field in ("race_date", "year", "field_n"):
        require((win_raw[f"{field}_candidate"] == win_raw[f"{field}_raw_T1"]).all(), f"WIN candidate/raw {field} mismatch")
    win_nll = float((win_raw["race_nll_candidate"] - win_raw["race_nll_raw_T1"]).mean())
    win_brier = float((win_raw["race_brier_candidate"] - win_raw["race_brier_raw_T1"]).mean())
    return pd.DataFrame(rows), pd.DataFrame(years), {
        "comparisons": rows,
        "win_protection_vs_raw_T1": {"races": 1779, "candidate_minus_raw_T1_mean_race_nll": win_nll,
                                     "candidate_minus_raw_T1_mean_race_brier": win_brier,
                                     "nll_point_gate_pass": win_nll <= 0.0,
                                     "brier_point_gate_pass": win_brier <= 0.0,
                                     "gate_pass": bool(win_nll <= 0.0 and win_brier <= 0.0),
                                     "statistical_noninferiority_claimed": False},
    }


def primary_bootstrap(candidate: pd.DataFrame, old_metrics: pd.DataFrame, evaluation: list[dict[str, Any]]) -> dict[str, Any]:
    schedule = np.load(BOOTSTRAP, mmap_mode="r", allow_pickle=False)
    cand = candidate.loc[candidate["pool"] == "TRI", ["race_id", "race_date", "race_nll", "race_brier"]].copy()
    common = old_metrics.loc[(old_metrics["pool"] == "TRI") & (old_metrics["arm"] == "TEMP"),
                             ["race_id", "race_date", "race_nll", "race_brier"]].copy()
    joined = cand.merge(common, on=["race_id", "race_date"], suffixes=("_candidate", "_common"), how="outer",
                        indicator=True, validate="one_to_one")
    require((joined["_merge"] == "both").all() and len(joined) == 1779, "TRI bootstrap race-pool pairing mismatch")
    dates = sorted({r["date"] for r in evaluation})
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(date_hash == EXPECTED_DATE_SHA, "TRI paired bootstrap date roster changed")
    joined["delta_nll"] = joined["race_nll_candidate"] - joined["race_nll_common"]
    joined["delta_brier"] = joined["race_brier_candidate"] - joined["race_brier_common"]
    day_sums: dict[str, float] = defaultdict(float)
    day_counts: dict[str, int] = defaultdict(int)
    for date, value in zip(joined["race_date"].astype(str), joined["delta_nll"]):
        day_sums[date] += float(value)
        day_counts[date] += 1
    ordered_sums = np.asarray([day_sums[d] for d in dates], dtype=np.float64)
    ordered_counts = np.asarray([day_counts[d] for d in dates], dtype=np.float64)
    draws = np.empty(schedule.shape[0], dtype=np.float64)
    for ix, draw in enumerate(schedule):
        multiplicity = np.bincount(draw, minlength=len(dates)).astype(np.float64)
        denominator = float(np.dot(multiplicity, ordered_counts))
        require(denominator > 0, "empty bootstrap draw")
        draws[ix] = float(np.dot(multiplicity, ordered_sums) / denominator)
    low, high = np.quantile(draws, [0.025, 0.975], method="linear")
    point_nll = float(joined["delta_nll"].mean())
    point_brier = float(joined["delta_brier"].mean())
    return {
        "pool": "TRI", "comparison": "candidate_minus_common_T", "races": len(joined), "dates": len(dates),
        "paired_date_bootstrap_draws": int(schedule.shape[0]), "point_mean_race_nll_difference": point_nll,
        "nll_difference_ci95": [float(low), float(high)],
        "mean_race_sum_brier_difference": point_brier,
        "nll_ci_upper_gate_pass": bool(high < 0.0), "brier_point_gate_pass": bool(point_brier <= 0.0),
        "gate_pass": bool(high < 0.0 and point_brier <= 0.0),
        "schedule_sha256": EXPECTED_SCHEDULE_SHA, "date_inventory_sha256": date_hash,
        "weighting": "paired dates sampled with replacement; races date-clustered, equal weight per race",
        "temperatures_fixed_across_draws": True, "calibration_fit_uncertainty_included": False,
        "statistical_noninferiority_claimed": False,
    }


def execution_conditions() -> dict[str, Any]:
    return {
        "training_years": [2019, 2020, 2021, 2022, 2023], "training_races": 2492,
        "evaluation_years": [2024, 2025, 2026], "evaluation_races": 1779,
        "candidate_temperatures": 3, "temperature_bounds": list(T_BOUNDS), "regularization": "none",
        "common_comparator_temperature": COMMON_T, "win_protection_temperature": RAW_T,
        "stage_denominators": {"rank_1": "all N starters", "rank_2": "all N-1 starters after actual rank 1 removed",
                               "rank_3": "all N-2 starters after actual ranks 1 and 2 removed, including actual finishers below third"},
        "tri_gate": "candidate_minus_common_TRI_NLL_paired_date_bootstrap_CI95_upper<0_and_sum_Brier_point<=0",
        "win_gate": "candidate_minus_raw_T1_WIN_NLL_point<=0_and_Brier_point<=0",
        "statistical_noninferiority_claimed": False,
        "tie_rule": "for diagnostics only, tickets p >= pmax - 1e-12 are tied; lexicographically smallest horse-number tuple wins",
        "choice_tolerance_affects_probabilities_or_losses": False,
        "plc_unknown_races": 36,
    }


def validate_approval() -> dict[str, Any]:
    require(APPROVAL.is_file(), f"supervisor approval missing: {project_relative(APPROVAL)}")
    approval = json_read(APPROVAL)
    preflight_path = OUTPUT / "source_preflight.json"
    require(preflight_path.is_file(), "new source preflight missing")
    expected = {
        "status": "PASS",
        "candidate_id": STUDY_ID,
        "code_sha256": sha256_file(EXPERIMENT / "rank_stage.py"),
        "plan_sha256": sha256_file(EXPERIMENT / "PLAN.md"),
        "source_preflight_sha256": sha256_file(preflight_path),
        "asset_manifest_sha256": ASSET_SHA,
        "rules_contract_sha256": RULES_SHA,
        "baseline_reference_hashes": BASELINE_REFERENCE_HASHES,
        "conditions": execution_conditions(),
    }
    for key, value in expected.items():
        require(approval.get(key) == value, f"approval field mismatch: {key}")
    actual_refs = verify_references()
    require(actual_refs == BASELINE_REFERENCE_HASHES, "immutable baseline references changed after approval")
    preflight = json_read(preflight_path)
    require(preflight.get("status") == "PASS_STRUCTURAL_PREFLIGHT_NO_FIT_NO_REAL_PROBABILITIES_NO_METRICS",
            "new structural preflight not PASS")
    require(preflight.get("real_race_probabilities_computed") is False and preflight.get("outcome_metrics_computed") is False,
            "source preflight unexpectedly includes probability/metric results")
    require(preflight.get("code_sha256") == expected["code_sha256"], "preflight code SHA differs from current approved code")
    require(preflight.get("plan_sha256") == expected["plan_sha256"], "preflight PLAN SHA differs from current approved plan")
    require(preflight.get("asset_manifest_sha256") == approval["asset_manifest_sha256"],
            "preflight asset manifest SHA differs from approval")
    require(preflight.get("rules_contract_sha256") == approval["rules_contract_sha256"],
            "preflight rules contract SHA differs from approval")
    require(sha256_file(ASSET_MANIFEST) == approval["asset_manifest_sha256"], "raw asset manifest changed after approval")
    require(sha256_file(RULES_JSON) == approval["rules_contract_sha256"], "rules changed after approval")
    return approval


def run_fit_evaluate() -> None:
    approval = validate_approval()
    require(not any((OUTPUT / name).exists() for name in FIT_OUTPUT_NAMES), "fit/evaluate outputs already exist; refusing rerun/overwrite")
    for name in ("*.tmp",):
        require(not list(OUTPUT.glob(name)), "temporary output exists; inspect before execution")
    check_output_budget()
    training, evaluation, cohort_info = load_cohorts(keep_scores=True)
    fit = fit_stages(training)
    temperatures = tuple(fit["temperatures"])
    candidate_metrics, runner_rows, reliability, candidate_selections = compute_candidate_eval(evaluation, temperatures)
    baseline = verify_baseline_artifacts()
    pool_comparisons, year_comparisons, comparison_summary = compare_losses(candidate_metrics, baseline["metrics"])
    tri = primary_bootstrap(candidate_metrics, baseline["metrics"], evaluation)
    selection_ledger, change_ledger, change_summary = build_selection_diagnostics(evaluation, candidate_selections)
    require(len(candidate_selections) == 12417, "candidate one-pass selection rows changed")
    require(set(candidate_selections["selected_ticket_key"]) <= set(selection_ledger["selected_ticket_key"]),
            "candidate selection ledger not included in arm diagnostic")
    report = {
        "study_id": STUDY_ID,
        "approval": {"path": project_relative(APPROVAL), "sha256": sha256_file(APPROVAL),
                     "status": approval["status"]},
        "code_sha256": sha256_file(EXPERIMENT / "rank_stage.py"),
        "plan_sha256": sha256_file(EXPERIMENT / "PLAN.md"),
        "source_preflight_sha256": sha256_file(OUTPUT / "source_preflight.json"),
        "asset_manifest_sha256": sha256_file(ASSET_MANIFEST),
        "rules_contract_sha256": sha256_file(RULES_JSON),
        "baseline_reference_hashes": BASELINE_REFERENCE_HASHES,
        "fit": fit,
        "evaluation": {"years": [2024, 2025, 2026], "races": len(evaluation),
                       "runner_rows": sum(r["n"] for r in evaluation), "dates": len(cohort_info["evaluation_dates"]),
                       "reused_development_material": True,
                       "scope": "2024–2026 outcomes were previously used in development and are not an independent holdout"},
        "primary_tri_gate": tri,
        "win_protection": comparison_summary["win_protection_vs_raw_T1"],
        "pool_comparisons_vs_common_T": comparison_summary["comparisons"],
        "candidate_gate_status": "PASS_RESEARCH_CALIBRATION_CANDIDATE" if tri["gate_pass"] and comparison_summary["win_protection_vs_raw_T1"]["gate_pass"] else "FAIL_OR_PARTIAL",
        "metric_contract": {"categorical": "race-equal categorical NLL clipped at EPS and ticket-space sum Brier",
                            "multiple_winner": "ticket Bernoulli NLL clipped at EPS, ticket Brier unclipped, ticket mean within race then race-equal",
                            "epsilon": EPS, "reliability_weighting": "pooled_ticket_event_count",
                            "bins": BIN_EDGES.tolist(), "pool_order": list(POOL_ORDER)},
        "selection_diagnostics": {"tie_tolerance": TIE_TOLERANCE, "tie_rule": change_summary["policy"],
                                  "changes": change_summary, "not_a_probability_or_loss_rule": True},
        "limitations": [
            "2024–2026 evaluation dates and outcomes are repeated development material, not an independent holdout.",
            "Bootstrap intervals hold the three fitted temperatures fixed and omit fit uncertainty.",
            "WIN protection gates are point-estimate checks only; statistical non-inferiority is not claimed.",
            "Historical pool offering and settlement were not audited race by race; this is not ROI evidence.",
            "A TRI gate pass does not establish all-pool superiority, native q(T) improvement, or production readiness.",
            "The fixed numerical tie rule affects only one-ticket selection diagnostics, never probability or loss calculations.",
        ],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__,
                        "pandas": pd.__version__, "scipy": scipy.__version__},
    }
    fit_receipt = {
        "approval_sha256": sha256_file(APPROVAL), "code_sha256": report["code_sha256"],
        "plan_sha256": report["plan_sha256"], "source_preflight_sha256": report["source_preflight_sha256"],
        "asset_manifest_sha256": report["asset_manifest_sha256"], "rules_contract_sha256": report["rules_contract_sha256"],
        "baseline_reference_hashes": BASELINE_REFERENCE_HASHES, "fit": fit,
        "run_count": 1, "successful_evaluation_passes": 1,
        "selection_rule": execution_conditions()["tie_rule"],
        "output_storage_cap_bytes": OUTPUT_BUDGET,
    }
    atomic_parquet(OUTPUT / "candidate_race_metrics.parquet", candidate_metrics)
    atomic_parquet(OUTPUT / "candidate_runner_marginals.parquet", runner_rows)
    atomic_parquet(OUTPUT / "candidate_reliability_bins.parquet", reliability)
    atomic_parquet(OUTPUT / "pool_comparisons.parquet", pool_comparisons)
    atomic_parquet(OUTPUT / "pool_year_comparisons.parquet", year_comparisons)
    atomic_parquet(OUTPUT / "selection_ledger.parquet", selection_ledger)
    atomic_parquet(OUTPUT / "selection_change_ledger.parquet", change_ledger)
    atomic_json(OUTPUT / "selection_change_summary.json", change_summary)
    atomic_json(OUTPUT / "fit_receipt.json", fit_receipt)
    report["experiment_bytes_before_report_write"] = experiment_bytes()
    atomic_json(OUTPUT / "report.json", report)
    print(json.dumps({"status": report["candidate_gate_status"], "temperatures": fit["temperatures"],
                      "tri": tri, "win_protection": report["win_protection"],
                      "experiment_bytes": experiment_bytes(), "outputs": FIT_OUTPUT_NAMES}, indent=2))


def synthetic_checks() -> None:
    # Fixed full-field example with actual ranks 1–3 followed by two runners.
    scores = np.asarray([1.7, 0.8, 0.1, -0.4, -1.2], dtype=np.float64)
    ranks = np.asarray([1, 2, 3, 4, 5], dtype=np.int64)
    record = {"race_id": "synthetic", "date": "2099-01-01", "year": 2099, "n": 5,
              "numbers": np.asarray([8, 2, 7, 1, 5], dtype=np.int64), "scores": scores, "ranks": ranks}
    t = 1.3
    actual = actual_order_indices(ranks)
    stage3_left = remaining_indices(len(scores), actual[:2])
    require(len(stage3_left) == len(scores) - 2 == 3, "synthetic stage-3 denominator is not N-2")
    require(set(stage3_left.tolist()) == {actual[2], 3, 4}, "synthetic stage-3 set omitted finishers below third")
    lp3 = -stage_conditional_nll(record, t, 3)
    require(lp3 < -1e-9, "synthetic stage-3 likelihood collapsed to a three-horse-only probability")
    shifted = dict(record, scores=scores + 1234.5)
    require(abs(stage_conditional_nll(record, t, 3) - stage_conditional_nll(shifted, t, 3)) < 1e-12,
            "synthetic stage conditional is not score-shift invariant")
    maps, marginal, mass = probability_maps(record, (0.72, 1.41, 2.63))
    require(abs(mass - 1.0) < 2e-12, "synthetic joint Q mass does not sum to one")
    require(abs(sum(marginal["p_win"]) - 1) < 2e-12, "synthetic WIN mass mismatch")
    require(abs(sum(marginal["p_top2"]) - 2) < 2e-12 and abs(sum(marginal["p_top3"]) - 3) < 2e-12,
            "synthetic Top-k marginal mass mismatch")
    require(abs(sum(maps["QNL"].values()) - 1) < 2e-12, "synthetic QNL event mass mismatch")
    require(abs(sum(maps["EXA"].values()) - 1) < 2e-12, "synthetic EXA event mass mismatch")
    require(abs(sum(maps["TLA"].values()) - 1) < 2e-12, "synthetic TLA event mass mismatch")
    require(abs(sum(maps["TRI"].values()) - 1) < 2e-12, "synthetic TRI event mass mismatch")
    require(abs(sum(maps["QPL"].values()) - 3) < 2e-12, "synthetic QPL event mass mismatch")
    require(abs(sum(marginal["p_top3"]) - 3) < 2e-12, "synthetic PLC Top3 mass mismatch")
    require(plc_top_from_actual(8) == 3 and plc_top_from_actual(7) is None,
            "synthetic unresolved PLC actual-field branch changed")
    plc_top2_truths = truth_keys("PLC", record, 2)
    require(len(plc_top2_truths) == 2 and abs(sum(maps["PLC"].values()) - 2.0) < 2e-12,
            "synthetic observed-opening 5-runner PLC Top2 outcomes/mass mismatch")
    record8 = {"race_id": "synthetic-8", "date": "2099-01-02", "year": 2099, "n": 8,
               "numbers": np.arange(1, 9, dtype=np.int64), "scores": np.linspace(1.0, -1.0, 8),
               "ranks": np.arange(1, 9, dtype=np.int64)}
    maps8, _, _ = probability_maps(record8, (0.8, 1.2, 2.4))
    plc_top3_truths = truth_keys("PLC", record8, 3)
    require(len(plc_top3_truths) == 3 and abs(sum(maps8["PLC"].values()) - 3.0) < 2e-12,
            "synthetic 8-runner PLC Top3 outcomes/mass mismatch")
    require(plc_top_from_actual(7) is None, "synthetic actual-seven PLC must remain unresolved without opening roster")
    qpl_truths = truth_keys("QPL", record, None)
    require(len(qpl_truths) == 3, "synthetic QPL must have three Top3 pairs")
    near_tie = {(8,): 0.2, (2,): 0.2 - 0.5e-12, (7,): 0.19}
    selected, selected_p, max_p, tied_count = select_ticket(near_tie)
    require(selected == (2,) and tied_count == 2 and selected_p <= max_p,
            "synthetic absolute tie tolerance/lexicographic rule mismatch")
    synthetic_bins = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    synthetic_metrics, synthetic_selections, synthetic_runners, _ = metric_rows_for_race(
        record, (0.72, 1.41, 2.63), "SYNTHETIC", synthetic_bins, include_selections=True)
    require(len(synthetic_metrics) == 6 and len(synthetic_selections) == 6 and len(synthetic_runners) == 5,
            "synthetic race metric/selection/runner construction failed")
    for row in synthetic_selections:
        require(row["selected_probability"] <= row["maximum_probability"] and row["tied_ticket_count"] >= 1,
                "selected_probability must remain the chosen ticket's actual probability")
    common_selection = selection_only_rows(record, (COMMON_T, COMMON_T, COMMON_T), "COMMON")
    require(len(common_selection) == 6 and all("race_nll" not in row for row in common_selection),
            "baseline selection-only diagnostic unexpectedly calculated losses")
    flip_scores = np.asarray([0.2, 0.1, 0.0, -0.1, -0.2], dtype=np.float64)
    flip_record = dict(record, scores=flip_scores, numbers=np.asarray([1, 2, 3, 4, 5], dtype=np.int64))
    flip_maps, _, _ = probability_maps(flip_record, (4.0, 0.35, 2.0))
    require(flip_maps["TRI"][(2, 1, 3)] > flip_maps["TRI"][(1, 2, 3)],
            "synthetic full-field candidate failed to demonstrate order reversal within bounds")
    # The stage-specific candidate's full-field ordered MAP can differ from
    # raw-score order; no raw-score-MAP assertion belongs in this contract.
    print(json.dumps({"status": "PASS_SYNTHETIC_ONLY", "full_field_runners": len(scores),
                      "stage_2_denominator": len(scores) - 1, "stage_3_denominator": len(stage3_left),
                      "stage_3_includes_below_third": True, "joint_mass": mass,
                      "tie_tolerance": TIE_TOLERANCE}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--synthetic-checks", action="store_true")
    modes.add_argument("--source-preflight", action="store_true")
    modes.add_argument("--fit-evaluate", action="store_true")
    args = parser.parse_args()
    if args.synthetic_checks:
        synthetic_checks()
    elif args.source_preflight:
        source_preflight()
    else:
        run_fit_evaluate()


if __name__ == "__main__":
    main()
