#!/usr/bin/env python3
"""Approval-gated fixed 50:50 mixture of frozen R/S Top-3 PL distributions.

Default/--synthetic-checks performs synthetic math checks only. --source-preflight
checks frozen sources, cohort keys, rules and reference ledger keys, without
constructing E or computing evaluation probabilities/losses. --run is the only
real E evaluation path and requires a one-run supervisor approval.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations, zip_longest
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import scipy


PROJECT = Path(__file__).resolve().parents[4]
STUDY = PROJECT / "jeju/research/20261022_rs_equal_mixture_v1"
EXPERIMENT = STUDY / "experiment"
OUTPUTS = EXPERIMENT / "outputs"
PLAN = EXPERIMENT / "PLAN.md"
TEST = EXPERIMENT / "test_rs_equal_mixture.py"
CONTRACT = STUDY / "supervisor/DESIGN_CONTRACT.md"
APPROVAL = STUDY / "supervisor/EXECUTION_APPROVAL.json"

F1_STUDY = PROJECT / "jeju/research/20261010_style_history_ablation_v1"
F1_MANIFEST = F1_STUDY / "ARTIFACT_MANIFEST.json"
F1_FEATURES = F1_STUDY / "outputs/features.parquet"
F1_SCORE_PATHS = {
    2024: F1_STUDY / "outputs/F1_STYLE6_2024/evaluation_scores.parquet",
    2025: F1_STUDY / "outputs/F1_STYLE6_2025/evaluation_scores.parquet",
    2026: F1_STUDY / "outputs/F1_STYLE6_2026/evaluation_scores.parquet",
}
R_STUDY = PROJECT / "jeju/research/20261022_dynamic_ability_pace_v1"
R_PARAMS = R_STUDY / "experiment/outputs/parameters.json"
R_METRICS = R_STUDY / "experiment/outputs/race_pool_metrics.parquet"
R_SELECTIONS = R_STUDY / "experiment/outputs/selected_ticket_ledger.parquet"
R_MARGINALS = R_STUDY / "experiment/outputs/evaluation_runner_marginals.parquet"
R_AXIS = R_STUDY / "experiment/outputs/win_axis_ledger.parquet"
R_MANIFEST = R_STUDY / "FINAL_MANIFEST.json"
S_STUDY = PROJECT / "jeju/research/20261022_tb_state_transfer_v1"
S_SCORES = S_STUDY / "experiment/outputs/candidate_oos_scores.parquet"
S_PARAMS = S_STUDY / "experiment/outputs/parameters.json"
S_METRICS = S_STUDY / "experiment/outputs/race_pool_metrics.parquet"
S_SELECTIONS = S_STUDY / "experiment/outputs/selected_ticket_ledger.parquet"
S_MARGINALS = S_STUDY / "experiment/outputs/evaluation_runner_marginals.parquet"
S_AXIS = S_STUDY / "experiment/outputs/win_axis_ledger.parquet"
S_PAIR_DIAGNOSTICS = S_STUDY / "experiment/outputs/pair_selection_diagnostics.parquet"
S_ENGINE = S_STUDY / "experiment/state_transfer.py"
S_MANIFEST = S_STUDY / "FINAL_MANIFEST.json"
MATH_ENGINE = R_STUDY / "experiment/dynamic_ability_pace.py"
RULES = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/rules_contract/rules_contract.json"
BOOTSTRAP = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
PREFLIGHT = OUTPUTS / "source_preflight.json"

CONTRACT_SHA256 = "e3cd97f4c2081e23dc077bf20641e5012e39ece3a396b11fd6838bef971e13a8"
MATH_ENGINE_SHA256 = "706b2e94a6b311e5bd9b3706da7df4f6a08117e917d22171fbde63a4d1a3210c"
EXPECTED_DATE_SHA256 = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"
EXPECTED_BOOTSTRAP_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
EXPECTED_BOOTSTRAP_RECEIPT_SHA256 = "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e"
EXPECTED_EVAL = {"races": 1779, "runners": 17412, "dates": 269, "plc_races": 1743, "plc_unknown": 36}
EXPECTED_YEAR_RACES = {2024: 637, 2025: 654, 2026: 488}
EXPECTED_R_TEMPERATURES = {
    2024: 1.2378241690081193,
    2025: 1.2652561077417601,
    2026: 1.11598418811972,
}
EXPECTED_S_TEMPERATURES = {
    2024: 1.2839358195588775,
    2025: 1.323027519896799,
    2026: 1.165540100038154,
}
MIXTURE_WEIGHT = 0.5
SELECTION_TOLERANCE = 1e-12
EPS = 1e-15
EVAL_END = "2026-09-19"
EXPECTED_STUDY_BYTES = 25_000_000

SOURCE_HASHES = {
    "F1_ARTIFACT_MANIFEST": (F1_MANIFEST, "6afc0e8f73ec086052fad4cde4d7edcd62fdf1bbc782108da89732dc3a5b4a4e"),
    "F1_FEATURES": (F1_FEATURES, "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f"),
    "F1_EVAL_2024": (F1_SCORE_PATHS[2024], "b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60"),
    "F1_EVAL_2025": (F1_SCORE_PATHS[2025], "45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12"),
    "F1_EVAL_2026": (F1_SCORE_PATHS[2026], "0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a"),
    "R_PARAMETERS": (R_PARAMS, "28da20c16c65450c024b07a4a12b916e88eaf8b9d16b8fdc66e1a6e582934dff"),
    "R_REFERENCE_METRICS": (R_METRICS, "8e8bdf9597b0b3251f9faff3a58e369e14734a27e06d12f18fc8f6ab688c3f7a"),
    "R_REFERENCE_SELECTIONS": (R_SELECTIONS, "f67f2076a996f5e420324868ff4d3af165eaa7b31851e2ad94e42a6b50f3a79c"),
    "R_REFERENCE_MARGINALS": (R_MARGINALS, "93c025a0e6d89ab97ac1d7d8e718156128c2052cd9d31cc0c7153e2df40a80aa"),
    "R_REFERENCE_AXIS": (R_AXIS, "b99b491970c661d15c66120c583cda1c98b14a1d51ddde79c82e5cba8102671d"),
    "R_FINAL_MANIFEST": (R_MANIFEST, "33b3af723dc9f9ddb0dc1435e151f91e77513d04e998a128cad7fbc58a2ad312"),
    "S_OOS_SCORES": (S_SCORES, "fe08bdf93b07f8a180ad02416cbbc1488db282c761564b67b886114ece56f6e9"),
    "S_PARAMETERS": (S_PARAMS, "46fda546b2a537373291c83190ef7c6f00ffda94fccebcf9090c6f01dfc9c23e"),
    "S_REFERENCE_METRICS": (S_METRICS, "ce503ae93d6afe8d167e430cb6556428caa0e7100b72465799a734e3fba83001"),
    "S_REFERENCE_SELECTIONS": (S_SELECTIONS, "abc8cf48d0e489124043864f071697f253a61444900c2d731f61d66fe203f82d"),
    "S_REFERENCE_MARGINALS": (S_MARGINALS, "8d5c1de77fca4ea555f92c88b894ad89cf07ccf0f8b8a156ef50e38979ed6d4d"),
    "S_REFERENCE_AXIS": (S_AXIS, "ccce48ac981230de12ac7096627d95169e6040f114ea7bcf527fe16929d90d0a"),
    "S_PAIR_DIAGNOSTICS": (S_PAIR_DIAGNOSTICS, "e47d67518cb6b86745ed14c853be98fe87fa3ccafc39049dd546cb608aff652f"),
    "S_ENGINE": (S_ENGINE, "963b2bcb574f3d49e539ae4e944a8a2f8f9bd769568d83018c2dcbcd2fa0623c"),
    "S_FINAL_MANIFEST": (S_MANIFEST, "86d0153e287f877add1b10c3172471cf5c3aac9f251890423cd7d97f75abba3a"),
    "MATH_ENGINE": (MATH_ENGINE, MATH_ENGINE_SHA256),
    "RULES_CONTRACT": (RULES, "20cd4b17274018a36efbb1b0cea64eb5d5c9809ed5f3481bea59c734f99fee83"),
    "BOOTSTRAP_SCHEDULE": (BOOTSTRAP, EXPECTED_BOOTSTRAP_SHA256),
    "BOOTSTRAP_RECEIPT": (BOOTSTRAP_RECEIPT, EXPECTED_BOOTSTRAP_RECEIPT_SHA256),
    "DESIGN_CONTRACT": (CONTRACT, CONTRACT_SHA256),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def file_pins() -> dict[str, dict[str, str]]:
    pins: dict[str, dict[str, str]] = {}
    for name, (path, expected) in SOURCE_HASHES.items():
        require(path.is_file(), f"pinned source missing: {name} {path}")
        actual = sha256_file(path)
        require(actual == expected, f"pinned source SHA mismatch: {name} expected={expected} actual={actual}")
        pins[name] = {"path": path.relative_to(PROJECT).as_posix(), "sha256": actual}
    return pins


def _code_hashes() -> dict[str, str]:
    require(PLAN.is_file() and TEST.is_file(), "PLAN and test must exist before preflight");
    hashes = {
        "plan_sha256": sha256_file(PLAN),
        "engine_sha256": sha256_file(Path(__file__).resolve()),
        "test_sha256": sha256_file(TEST),
    }
    bundle = {key: hashes[key] for key in ("engine_sha256", "test_sha256", "plan_sha256")}
    hashes["code_bundle_sha256"] = sha256_bytes(json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode())
    return hashes


def _norm(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return str(value)


def key_digest(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    require(set(columns).issubset(frame.columns), f"missing key digest columns {set(columns) - set(frame.columns)}")
    ordered = frame.loc[:, list(columns)].sort_values(list(columns), kind="mergesort", na_position="first")
    digest = hashlib.sha256()
    for row in ordered.itertuples(index=False, name=None):
        raw = json.dumps([_norm(value) for value in row], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        digest.update(raw + b"\n")
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _expected_pool_counts(races: pd.DataFrame, engine: Any | None = None) -> dict[str, int]:
    from_codes = ("WIN", "PLC", "QNL", "EXA", "QPL", "TLA", "TRI")
    minimums = {"WIN": 2, "PLC": 5, "QNL": 3, "EXA": 3, "QPL": 5, "TLA": 4, "TRI": 4}
    result = {pool: int((races.field_n >= minimums[pool]).sum()) for pool in from_codes}
    result["PLC"] = int((races.field_n >= 8).sum())
    return result


def build_source_preflight() -> dict[str, Any]:
    hashes = file_pins()
    code_hashes = _code_hashes()
    f1_params_manifest = _json(F1_MANIFEST)
    require(f1_params_manifest.get("variant") == "F1_STYLE6", "F1 manifest variant is not F1_STYLE6")
    require(f1_params_manifest.get("cohort", {}).get("evaluation_races") == EXPECTED_EVAL["races"],
            "F1 manifest evaluation race count changed")

    columns = ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
               "finish_position", "field_n", "distance_m"]
    features = pd.read_parquet(F1_FEATURES, columns=columns)
    features["race_date"] = features.race_date.astype(str)
    target = features.loc[
        features.year.isin(EXPECTED_YEAR_RACES) & features.race_date.between("2024-01-01", EVAL_END)
    ].copy()
    require(target.api_record_id.is_unique and not target.duplicated(["race_id", "horse_number"]).any(),
            "F1 evaluation runner keys are not unique")
    require(target.horse_id.notna().all() and target.race_id.notna().all(), "F1 evaluation roster has null horse/race keys")
    require(len(target) == EXPECTED_EVAL["runners"], f"F1 evaluation runner count changed: {len(target)}")
    races = target.groupby("race_id", sort=True).agg(
        race_date=("race_date", "first"), year=("year", "first"), field_n=("field_n", "first"),
        rows=("api_record_id", "size"), distance_m=("distance_m", "first"),
    ).reset_index()
    require(len(races) == EXPECTED_EVAL["races"] and races.race_date.nunique() == EXPECTED_EVAL["dates"],
            "F1 evaluation race/date count changed")
    require(all(int(n) == int(rows) for n, rows in zip(races.field_n, races.rows)), "field_n differs from frozen roster")
    require(races.groupby("year").race_id.nunique().to_dict() == EXPECTED_YEAR_RACES,
            "F1 evaluation annual race counts changed")
    for race_id, group in target.groupby("race_id", sort=False):
        ranks = group.finish_position.to_numpy(dtype=np.int64)
        n = len(group)
        require(set(ranks.tolist()) == set(range(1, n + 1)), f"strict complete unique finish labels changed: {race_id}")
    pool_counts = _expected_pool_counts(races)
    require(pool_counts == {"WIN": 1779, "PLC": 1743, "QNL": 1779, "EXA": 1779,
                            "QPL": 1779, "TLA": 1779, "TRI": 1779},
            f"legal pool denominators changed: {pool_counts}")
    unknown_plc = int((races.field_n.between(5, 7)).sum())
    require(unknown_plc == EXPECTED_EVAL["plc_unknown"], "unknown PLC field count changed")

    # R source preflight reads only source keys, not raw score values.
    r_fit_params = _json(R_PARAMS)
    r_refs = r_fit_params["R_reference_fits"]
    r_key_parts: list[pd.DataFrame] = []
    r_provider_rows: dict[str, Any] = {}
    for year, path in F1_SCORE_PATHS.items():
        frame = pd.read_parquet(path, columns=["api_record_id"])
        require(frame.api_record_id.is_unique, f"R raw score API keys duplicate in {year}")
        expected_ids = target.loc[target.year.eq(year), "api_record_id"]
        require(set(frame.api_record_id.astype(int)) == set(expected_ids.astype(int)),
                f"R raw score keys differ from frozen F1 rows in {year}")
        ref = r_refs[str(year)]
        require(ref.get("score_semantics") == "raw_score_before_temperature" and
                ref.get("evaluation_score_sha256") == SOURCE_HASHES[f"F1_EVAL_{year}"][1] and
                abs(float(ref["temperature"]) - EXPECTED_R_TEMPERATURES[year]) < 1e-15,
                f"R raw score/temperature provenance mismatch for {year}")
        require(ref.get("provider") == f"F1_STYLE6_{year}" and int(ref.get("evaluation_year")) == year,
                f"R provider/year mismatch for {year}")
        r_provider_rows[str(year)] = {
            "path": path.relative_to(PROJECT).as_posix(), "sha256": SOURCE_HASHES[f"F1_EVAL_{year}"][1],
            "rows": len(frame), "temperature": float(ref["temperature"]), "score_semantics": ref["score_semantics"],
        }
        r_key_parts.append(target.loc[target.year.eq(year), ["api_record_id", "race_id", "race_date", "year",
                                                               "horse_id", "horse_number", "field_n"]])
    require(len(pd.concat(r_key_parts, ignore_index=True)) == EXPECTED_EVAL["runners"], "R source annual coverage mismatch")

    # S source preflight reads roster keys only, not its score column.
    s_params = _json(S_PARAMS)
    s_scores = pd.read_parquet(S_SCORES, columns=["arm", "role", "year", "api_record_id", "race_id",
                                                  "race_date", "horse_number", "field_n"])
    s_eval = s_scores.loc[s_scores.arm.eq("S") & s_scores.role.eq("evaluation") &
                          s_scores.year.isin(EXPECTED_YEAR_RACES)].copy()
    s_eval["race_date"] = s_eval.race_date.astype(str)
    require(s_eval.api_record_id.is_unique and not s_eval.duplicated(["race_id", "horse_number"]).any(),
            "S evaluation keys are not unique")
    s_expected = target[["api_record_id", "race_id", "race_date", "year", "horse_number", "field_n"]]
    s_join = s_expected.merge(s_eval, on=["api_record_id", "race_id", "race_date", "year", "horse_number", "field_n"],
                              how="outer", indicator=True, validate="one_to_one")
    require(s_join._merge.eq("both").all() and len(s_eval) == EXPECTED_EVAL["runners"],
            "S OOS evaluation source is not the exact F1 roster")
    s_temps = {int(row["year"]): float(row["temperature_fit"]["temperature"])
               for row in s_params["models"] if row.get("arm") == "S"}
    require(s_temps == EXPECTED_S_TEMPERATURES, f"S annual temperatures changed: {s_temps}")
    require({int(row["year"]) for row in s_params["models"] if row.get("arm") == "S"} == set(EXPECTED_YEAR_RACES),
            "S evaluation vintage inventory changed")

    # Existing event/selection ledgers are hash-pinned, read-only references.
    r_metrics = pd.read_parquet(R_METRICS, columns=["arm", "pool", "race_id", "race_date", "year", "field_n"])
    s_metrics = pd.read_parquet(S_METRICS, columns=["arm", "pool", "race_id", "race_date", "year", "field_n"])
    r_ref_metrics = r_metrics.loc[r_metrics.arm.eq("R")].copy()
    s_ref_metrics = s_metrics.loc[s_metrics.arm.eq("S")].copy()
    metric_key = ["pool", "race_id", "race_date", "year", "field_n"]
    require(len(r_ref_metrics) == len(s_ref_metrics) == 12417, "R/S reference metric row count changed")
    require(not r_ref_metrics.duplicated(metric_key).any() and not s_ref_metrics.duplicated(metric_key).any(),
            "R/S reference metric key duplicated")
    rmk = r_ref_metrics[metric_key].sort_values(metric_key).reset_index(drop=True)
    smk = s_ref_metrics[metric_key].sort_values(metric_key).reset_index(drop=True)
    require(rmk.equals(smk), "R/S reference metric key inventories differ")
    expected_by_pool = r_ref_metrics.groupby("pool").race_id.nunique().to_dict()
    require(expected_by_pool == {"WIN": 1779, "PLC": 1743, "QNL": 1779, "EXA": 1779,
                                 "QPL": 1779, "TLA": 1779, "TRI": 1779},
            f"R/S reference pool denominators changed: {expected_by_pool}")

    r_selections = pd.read_parquet(R_SELECTIONS, columns=["arm", *metric_key])
    s_selections = pd.read_parquet(S_SELECTIONS, columns=["arm", *metric_key])
    for rows, arm, expected in ((r_selections, "R", r_ref_metrics), (s_selections, "S", s_ref_metrics)):
        part = rows.loc[rows.arm.eq(arm), metric_key].sort_values(metric_key).reset_index(drop=True)
        ref = expected[metric_key].sort_values(metric_key).reset_index(drop=True)
        require(part.equals(ref), f"{arm} reference selection keys differ from metrics")

    r_marg = pd.read_parquet(R_MARGINALS, columns=["arm", "race_id", "race_date", "year", "horse_number"])
    s_marg = pd.read_parquet(S_MARGINALS, columns=["arm", "race_id", "race_date", "year", "horse_number"])
    runner_keys = ["race_id", "race_date", "year", "horse_number"]
    rmk_runner = r_marg.loc[r_marg.arm.eq("R"), runner_keys].sort_values(runner_keys).reset_index(drop=True)
    smk_runner = s_marg.loc[s_marg.arm.eq("S"), runner_keys].sort_values(runner_keys).reset_index(drop=True)
    expect_runner = target[["race_id", "race_date", "year", "horse_number"]].sort_values(runner_keys).reset_index(drop=True)
    require(len(rmk_runner) == len(smk_runner) == len(expect_runner) == EXPECTED_EVAL["runners"] and
            rmk_runner.equals(smk_runner) and rmk_runner.equals(expect_runner), "R/S reference runner marginal keys changed")

    axes: list[pd.DataFrame] = []
    for path, arm in ((R_AXIS, "R"), (S_AXIS, "S")):
        axis = pd.read_parquet(path, columns=["arm", "race_id", "race_date", "year", "selected_horse_number"])
        part = axis.loc[axis.arm.eq(arm)].copy()
        require(part.race_id.is_unique and len(part) == EXPECTED_EVAL["races"], f"{arm} WIN axis roster changed")
        keys = part[["race_id", "race_date", "year"]].sort_values(["race_id", "race_date", "year"]).reset_index(drop=True)
        race_keys = races[["race_id", "race_date", "year"]].sort_values(["race_id", "race_date", "year"]).reset_index(drop=True)
        require(keys.equals(race_keys), f"{arm} WIN axis race keys differ from F1 cohort")
        axes.append(part)

    pair_ref = pd.read_parquet(S_PAIR_DIAGNOSTICS, columns=["arm", "pool", "k", "race_id", "race_date", "year", "field_n"])
    pair_counts: dict[str, int] = {}
    pair_key = ["pool", "k", "race_id", "race_date", "year", "field_n"]
    for arm in ("R", "S"):
        part = pair_ref.loc[pair_ref.arm.eq(arm)].copy()
        require(len(part) == 7116 and not part.duplicated(pair_key).any(), f"{arm} reference pair diagnostic inventory changed")
        counts = part.groupby(["pool", "k"]).race_id.nunique().to_dict()
        require(counts == {("QNL", 1): 1779, ("QNL", 3): 1779, ("QPL", 1): 1779, ("QPL", 3): 1779},
                f"{arm} reference pair denominators changed: {counts}")
        pair_counts[arm] = len(part)

    rules = _json(RULES)
    minimums = rules["primary_rule"]["article_4_minimum_starters"]
    legal_minimums = {"WIN": 2, "PLC": 5, "QNL": 3, "EXA": 3, "QPL": 5, "TLA": 4, "TRI": 4}
    require({pool: int(minimums[pool]) for pool in legal_minimums} == legal_minimums,
            "official minimum-starter rule changed")
    plc = rules["primary_rule"]["plc_field_split"]
    require(plc.get("5_to_7") == "Top2" and plc.get("8_or_more") == "Top3",
            "official PLC split changed")
    receipt = _json(BOOTSTRAP_RECEIPT)
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS" and
            receipt.get("schedule_sha256") == EXPECTED_BOOTSTRAP_SHA256,
            "bootstrap receipt is not the frozen schedule")
    dates = sorted(races.race_date.astype(str).unique())
    date_hash = sha256_bytes("\n".join(dates).encode("utf-8"))
    require(date_hash == EXPECTED_DATE_SHA256 and receipt.get("date_inventory_sha256") == date_hash,
            "date inventory does not match frozen bootstrap roster")
    schedule = np.load(BOOTSTRAP, mmap_mode="r", allow_pickle=False)
    require(schedule.shape == (2000, EXPECTED_EVAL["dates"]) and schedule.dtype == np.int32 and
            int(schedule.min()) >= 0 and int(schedule.max()) < len(dates), "frozen bootstrap shape/type/index changed")

    return {
        "status": "PASS_STRUCTURE_ONLY_NO_E_DISTRIBUTION_OR_METRICS",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "study": "jeju/research/20261022_rs_equal_mixture_v1",
        "contract_sha256": CONTRACT_SHA256,
        **code_hashes,
        "source_hashes": hashes,
        "inputs": {name: {"path": F1_SCORE_PATHS[year].relative_to(PROJECT).as_posix(),
                           "sha256": SOURCE_HASHES[name][1], "rows": int(len(target.loc[target.year.eq(year)])),
                           "provider_temperature": float(r_provider_rows[str(year)]["temperature"])}
                   for year, name in ((2024, "F1_EVAL_2024"), (2025, "F1_EVAL_2025"), (2026, "F1_EVAL_2026"))},
        "score_role_contract": {
            "R": "raw F1_STYLE6 evaluation_scores.score; temperature from dynamic_ability_pace_v1 R_reference_fits",
            "S": "candidate_oos_scores score filtered arm=S,role=evaluation; temperature from TB state-transfer S model metadata",
            "R_temperatures": {str(k): float(v) for k, v in EXPECTED_R_TEMPERATURES.items()},
            "S_temperatures": {str(k): float(v) for k, v in EXPECTED_S_TEMPERATURES.items()},
            "same_year_recalibration": False,
        },
        "cohort": {
            "races": len(races), "runners": len(target), "dates": len(dates),
            "year_races": {str(k): int(v) for k, v in races.groupby("year").race_id.nunique().to_dict().items()},
            "plc_usable": pool_counts["PLC"], "plc_unknown_actual_5_to_7": unknown_plc,
            "pool_denominators": pool_counts,
            "runner_key_sha256": key_digest(target, ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "field_n"]),
            "race_key_sha256": key_digest(races, ["race_id", "race_date", "year", "field_n", "distance_m"]),
            "score_join_keys_equal_f1": True,
            "R_S_reference_pool_keys_equal": True,
            "R_S_reference_runner_keys_equal": True,
            "R_S_reference_pair_diagnostic_rows": pair_counts,
        },
        "rules": {"sha256": SOURCE_HASHES["RULES_CONTRACT"][1], "plc_split": {"5_to_7": "Top2", "8_or_more": "Top3"}},
        "bootstrap": {"sha256": EXPECTED_BOOTSTRAP_SHA256, "receipt_sha256": EXPECTED_BOOTSTRAP_RECEIPT_SHA256,
                      "shape": list(schedule.shape), "dtype": str(schedule.dtype), "date_inventory_sha256": date_hash},
        "guard": {"E_distribution_constructed": False, "E_probabilities_or_losses_computed": False,
                  "models_or_inputs_copied": False, "database_opened": False},
    }


def _load_math_engine() -> Any:
    require(sha256_file(MATH_ENGINE) == MATH_ENGINE_SHA256, "pinned pure math engine SHA changed")
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("rs_mix_math_reference", MATH_ENGINE)
    require(spec is not None and spec.loader is not None, "cannot load pinned math helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(sha256_file(MATH_ENGINE) == MATH_ENGINE_SHA256, "math helper source changed during read-only load")
    return module


def _top_k(tickets: Mapping[tuple[int, ...], float], k: int) -> list[tuple[int, ...]]:
    require(k > 0 and len(tickets) >= k, "not enough tickets for fixed selection")
    remaining = dict(tickets)
    chosen: list[tuple[int, ...]] = []
    for _ in range(k):
        max_p = max(float(p) for p in remaining.values())
        ticket = min(key for key, p in remaining.items() if float(p) >= max_p - SELECTION_TOLERANCE)
        chosen.append(ticket)
        del remaining[ticket]
    return chosen


def _pair_diagnostic(engine: Any, numbers: Sequence[int], scores_r: np.ndarray, temp_r: float,
                     scores_s: np.ndarray, temp_s: float, pool: str, selected: Sequence[tuple[int, ...]],
                     truths: set[tuple[int, ...]], tickets: Mapping[tuple[int, ...], float]) -> dict[str, Any]:
    require(pool in ("QNL", "QPL") and len(selected) in (1, 3), "invalid pair diagnostic request")
    counts = np.zeros(4, dtype=np.float64)
    r_iter = engine.iter_pl_top3(scores_r / temp_r)
    s_iter = engine.iter_pl_top3(scores_s / temp_s)
    sentinel = object()
    for left, right in zip_longest(r_iter, s_iter, fillvalue=sentinel):
        require(left is not sentinel and right is not sentinel and left[:3] == right[:3],
                "R/S ordered triple index stream differs")
        i, j, k, p_r = left
        p_s = right[3]
        p_e = 0.5 * float(p_r) + 0.5 * float(p_s)
        top = (int(numbers[i]), int(numbers[j]), int(numbers[k]))
        if pool == "QNL":
            realized_pairs = {tuple(sorted(top[:2]))}
        else:
            realized_pairs = {tuple(sorted(pair)) for pair in combinations(top, 2)}
        count = len(set(selected).intersection(realized_pairs))
        counts[count] += p_e
    require(abs(float(counts.sum()) - 1.0) <= 3e-11, f"{pool} selected-pair PMF mass mismatch")
    return {
        "selected_tickets_json": json.dumps([list(t) for t in selected], separators=(",", ":")),
        "selected_probabilities_json": json.dumps([float(tickets[t]) for t in selected], separators=(",", ":")),
        "selected_union_probability": float(counts[1:].sum()),
        "expected_hits": float(np.dot(np.arange(4, dtype=np.float64), counts)),
        "realized_hit_count": int(sum(t in truths for t in selected)),
        **{f"count_probability_{i}": float(counts[i]) for i in range(4)},
        "selected_ticket_count": len(selected),
        "count_semantics": "ordered Q exact count of selected unordered pair tickets hit; QNL count is 0/1",
    }


def _synthetic_direct_pl(scores: Sequence[float], temperature: float, order: Sequence[int]) -> float:
    utility = np.asarray(scores, dtype=np.float64) / temperature
    remaining = list(range(len(utility)))
    logp = 0.0
    for ix in order:
        values = utility[remaining]
        maxv = float(values.max())
        logp += float(utility[ix] - maxv - math.log(float(np.exp(values - maxv).sum())))
        remaining.remove(ix)
    return math.exp(logp)


def run_synthetic_checks() -> dict[str, Any]:
    engine = _load_math_engine()
    checks: list[str] = []
    nums = [1, 2, 3, 4, 5]
    ranks = [1, 2, 3, 4, 5]
    raw_r = np.asarray([0.8, 0.4, 0.1, -0.2, -0.7], dtype=np.float64)
    raw_s = np.asarray([-0.1, 0.9, 0.2, 0.5, -0.4], dtype=np.float64)
    tr, ts = 1.15, 1.42
    m_r, marg_r, mass_r = engine.probability_maps_from_scenarios([raw_r / tr], [1.0], nums, 2)
    m_s, marg_s, mass_s = engine.probability_maps_from_scenarios([raw_s / ts], [1.0], nums, 2)
    m_e, marg_e, mass_e = engine.probability_maps_from_scenarios(
        [raw_r / tr, raw_s / ts], [0.5, 0.5], nums, 2)
    require(abs(mass_r - 1.0) < 3e-11 and abs(mass_s - 1.0) < 3e-11 and abs(mass_e - 1.0) < 3e-11,
            "synthetic PL/Q mass")
    checks.append("normalized_full_field_pl_q_mass")
    for pool in ("WIN", "PLC", "QNL", "EXA", "QPL", "TLA", "TRI"):
        keys = set(m_r[pool]) | set(m_s[pool])
        require(keys == set(m_e[pool]), f"synthetic event key mismatch {pool}")
        for key in keys:
            expected = 0.5 * float(m_r[pool].get(key, 0.0)) + 0.5 * float(m_s[pool].get(key, 0.0))
            require(abs(float(m_e[pool][key]) - expected) <= 3e-15, f"synthetic event linearity failed {pool}/{key}")
    checks.append("seven_pool_event_probability_linearity")
    for name in marg_r:
        require(np.allclose(marg_e[name], 0.5 * marg_r[name] + 0.5 * marg_s[name], rtol=0.0, atol=3e-15),
                f"synthetic marginal mixture failed {name}")
    require(abs(float(marg_e["p_win"].sum()) - 1.0) < 3e-11 and
            abs(float(marg_e["p_top2"].sum()) - 2.0) < 3e-11 and
            abs(float(marg_e["p_top3"].sum()) - 3.0) < 3e-11, "synthetic runner marginal masses")
    checks.append("runner_marginal_linearity_and_mass")

    # Independent permutation enumeration verifies the 5-horse top-2 PLC branch.
    plc_truth = engine.truth_ticket_keys("PLC", nums, ranks, 2)
    require(plc_truth == {(1,), (2,)}, "synthetic 5-horse PLC Top2 truth")
    require(abs(sum(m_e["PLC"].values()) - 2.0) < 5e-11, "synthetic PLC Top2 ticket mass")
    checks.append("synthetic_five_horse_plc_top2")
    eight_nums = list(range(1, 9))
    eight_ranks = list(range(1, 9))
    m8, marginal8, mass8 = engine.probability_maps_from_scenarios(
        [np.linspace(0.5, -0.5, 8)], [1.0], eight_nums, 3)
    require(abs(mass8 - 1.0) < 3e-11 and abs(sum(m8["PLC"].values()) - 3.0) < 5e-11 and
            engine.truth_ticket_keys("PLC", eight_nums, eight_ranks, 3) == {(1,), (2,), (3,)},
            "synthetic 8-horse PLC Top3 branch")
    checks.append("synthetic_eight_horse_plc_top3")

    # Compare streamed pair hit-count PMFs to independent direct permutation enumeration.
    for pool in ("QNL", "QPL"):
        truths = engine.truth_ticket_keys(pool, nums, ranks, 2)
        for ksel in (1, 3):
            selected = _top_k(m_e[pool], ksel)
            diag = _pair_diagnostic(engine, nums, raw_r, tr, raw_s, ts, pool, selected, truths, m_e[pool])
            pmf_direct = np.zeros(4, dtype=np.float64)
            from itertools import permutations
            for order in permutations(range(5), 3):
                q = 0.5 * _synthetic_direct_pl(raw_r, tr, order) + 0.5 * _synthetic_direct_pl(raw_s, ts, order)
                top = tuple(nums[i] for i in order)
                actual = {tuple(sorted(top[:2]))} if pool == "QNL" else {tuple(sorted(pair)) for pair in combinations(top, 2)}
                pmf_direct[len(set(selected).intersection(actual))] += q
            pmf_got = np.asarray([diag[f"count_probability_{i}"] for i in range(4)])
            require(np.allclose(pmf_got, pmf_direct, rtol=0.0, atol=4e-14),
                    f"synthetic exact pair count PMF mismatch {pool}/k={ksel}")
            require(abs(diag["selected_union_probability"] - (1.0 - pmf_direct[0])) < 4e-14,
                    f"synthetic exact union mismatch {pool}/k={ksel}")
    checks.append("qnl_qpl_exact_union_and_count_pmf")

    equal_scores = np.zeros(5, dtype=np.float64)
    tie_map, _, _ = engine.probability_maps_from_scenarios([equal_scores], [1.0], nums, 2)
    require(_top_k(tie_map["QNL"], 3) == [(1, 2), (1, 3), (1, 4)] and
            _top_k(tie_map["QPL"], 3) == [(1, 2), (1, 3), (1, 4)], "fixed numerical tie rule")
    checks.append("fixed_1e12_tie_tolerance_horse_number_order")
    require(MIXTURE_WEIGHT == 0.5 and not any("fit" in name.lower() or "optimize" in name.lower()
                                              for name in globals() if callable(globals()[name])),
            "mixture must not fit or search weights")
    checks.append("fixed_weight_no_fit_or_search_path")
    return {"status": "PASS_SYNTHETIC_ONLY", "checks": checks, "check_count": len(checks),
            "real_sources_opened": False, "E_real_data_constructed": False}


def _exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    with path.open("xb") as handle:
        handle.write(data)


def _exclusive_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".parquet", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        frame.to_parquet(tmp, index=False, compression="zstd")
        os.link(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _study_bytes() -> int:
    return sum(path.stat().st_size for path in STUDY.rglob("*") if path.is_file())


def write_source_preflight() -> dict[str, Any]:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    require(not PREFLIGHT.exists(), "source_preflight already exists; preserve it before requesting a new review")
    report = build_source_preflight()
    _exclusive_json(PREFLIGHT, report)
    require(_study_bytes() <= EXPECTED_STUDY_BYTES, "study storage budget exceeded after preflight")
    return report


def _validate_approval(preflight: Mapping[str, Any]) -> dict[str, Any]:
    require(APPROVAL.is_file(), "missing supervisor/EXECUTION_APPROVAL.json")
    approval = _json(APPROVAL)
    require(approval.get("status") == "PASS" and approval.get("scope") == "evaluate_fixed_mixture" and
            approval.get("run_count") == 1, "supervisor approval status/scope/run_count mismatch")
    require(approval.get("study") == "jeju/research/20261022_rs_equal_mixture_v1", "approval study mismatch")
    expected = {
        "contract_sha256": CONTRACT_SHA256,
        "plan_sha256": _code_hashes()["plan_sha256"],
        "engine_sha256": _code_hashes()["engine_sha256"],
        "test_sha256": _code_hashes()["test_sha256"],
        "code_bundle_sha256": _code_hashes()["code_bundle_sha256"],
        "source_preflight_sha256": sha256_file(PREFLIGHT),
    }
    for key, value in expected.items():
        require(approval.get(key) == value, f"approval hash mismatch: {key}")
    source_hashes = {key: row["sha256"] for key, row in preflight["source_hashes"].items()}
    require(approval.get("source_hashes") == source_hashes, "approval source hashes differ from fresh preflight")
    return approval


def _fresh_preflight_guard() -> dict[str, Any]:
    require(PREFLIGHT.is_file(), "run source-preflight before execution")
    saved = _json(PREFLIGHT)
    fresh = build_source_preflight()
    saved_canonical = {k: v for k, v in saved.items() if k != "created_at_utc"}
    fresh_canonical = {k: v for k, v in fresh.items() if k != "created_at_utc"}
    require(fresh_canonical == saved_canonical,
            "fresh input preflight differs from saved receipt")
    require(saved.get("status") == "PASS_STRUCTURE_ONLY_NO_E_DISTRIBUTION_OR_METRICS",
            "source preflight status is not PASS")
    return saved


def _read_run_inputs() -> tuple[pd.DataFrame, dict[int, float], dict[int, float]]:
    columns = ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
               "finish_position", "field_n", "distance_m"]
    features = pd.read_parquet(F1_FEATURES, columns=columns)
    features["race_date"] = features.race_date.astype(str)
    target = features.loc[features.year.isin(EXPECTED_YEAR_RACES) &
                           features.race_date.between("2024-01-01", EVAL_END)].copy()
    r_parts = []
    for year, path in F1_SCORE_PATHS.items():
        scores = pd.read_parquet(path, columns=["api_record_id", "score"])
        scores = scores.rename(columns={"score": "score_r"})
        year_rows = target.loc[target.year.eq(year)].merge(scores, on="api_record_id", how="left",
                                                            validate="one_to_one", indicator=True)
        require(year_rows._merge.eq("both").all() and year_rows.score_r.notna().all(),
                f"R raw scores fail evaluation join for {year}")
        r_parts.append(year_rows.drop(columns="_merge"))
    r = pd.concat(r_parts, ignore_index=True)
    s = pd.read_parquet(S_SCORES, columns=["arm", "role", "year", "api_record_id", "race_id", "race_date",
                                           "horse_number", "field_n", "score"])
    s = s.loc[s.arm.eq("S") & s.role.eq("evaluation") & s.year.isin(EXPECTED_YEAR_RACES)].copy()
    s["race_date"] = s.race_date.astype(str)
    s = s.rename(columns={"score": "score_s"})
    keys = ["api_record_id", "race_id", "race_date", "year", "horse_number", "field_n"]
    joined = r.merge(s[keys + ["score_s"]], on=keys, how="outer", indicator=True, validate="one_to_one")
    require(joined._merge.eq("both").all() and len(joined) == EXPECTED_EVAL["runners"],
            "R/S raw evaluation score sources do not match exact F1 roster")
    joined = joined.drop(columns="_merge")
    require(np.isfinite(joined[["score_r", "score_s"]].to_numpy(dtype=np.float64)).all(),
            "non-finite raw OOS score")
    rparams, sparams = _json(R_PARAMS), _json(S_PARAMS)
    r_t = {int(y): float(row["temperature"]) for y, row in rparams["R_reference_fits"].items()}
    s_t = {int(row["year"]): float(row["temperature_fit"]["temperature"])
           for row in sparams["models"] if row.get("arm") == "S"}
    require(r_t == EXPECTED_R_TEMPERATURES and s_t == EXPECTED_S_TEMPERATURES, "frozen temperatures changed")
    return joined, r_t, s_t


def _reliability_add(bins: dict[tuple[str, int, str], list[float]], pool: str, year: int,
                     tickets: Mapping[tuple[int, ...], float], truths: set[tuple[int, ...]], edges: np.ndarray) -> None:
    for period in ("ALL", str(year)):
        for key, p_raw in tickets.items():
            p = float(p_raw)
            require(math.isfinite(p) and 0.0 <= p <= 1.0, "invalid reliability ticket probability")
            ix = min(max(int(np.searchsorted(edges, p, side="right") - 1), 0), len(edges) - 2)
            bucket = bins[(pool, ix, period)]
            y = float(key in truths)
            bucket[0] += 1.0
            bucket[1] += p
            bucket[2] += y
            bucket[3] += (p - y) ** 2


def _aggregate_pair_summary(pair_diag: pd.DataFrame, ref_diag: pd.DataFrame) -> pd.DataFrame:
    frames = [("E", pair_diag)]
    for arm in ("R", "S"):
        frames.append((arm, ref_diag.loc[ref_diag.arm.eq(arm)].copy()))
    rows: list[dict[str, Any]] = []
    for arm, frame in frames:
        for (pool, k), group in frame.groupby(["pool", "k"], sort=True):
            rows.append({"arm": arm, "pool": pool, "k": int(k), "races": int(group.race_id.nunique()),
                         "mean_union_probability": float(group.selected_union_probability.mean()),
                         "mean_expected_hits": float(group.expected_hits.mean()),
                         "mean_realized_hits": float(group.realized_hit_count.mean()),
                         "hit_any_rate": float((group.realized_hit_count > 0).mean()),
                         **{f"mean_count_probability_{i}": float(group[f"count_probability_{i}"].mean()) for i in range(4)}})
    return pd.DataFrame(rows)


def _date_bootstrap_values(paired: pd.DataFrame, schedule: np.ndarray, dates: Sequence[str],
                           *, comparison: str, metric: str, left_values: pd.Series,
                           right_values: pd.Series | None = None) -> list[dict[str, Any]]:
    delta = left_values.to_numpy(dtype=np.float64)
    if right_values is not None:
        delta = delta - right_values.to_numpy(dtype=np.float64)
    date_series = paired.race_date.astype(str).to_numpy()
    date_sums: dict[str, float] = defaultdict(float)
    date_counts: dict[str, int] = defaultdict(int)
    for day, value in zip(date_series, delta):
        date_sums[day] += float(value)
        date_counts[day] += 1
    sums = np.asarray([date_sums[day] for day in dates], dtype=np.float64)
    counts = np.asarray([date_counts[day] for day in dates], dtype=np.float64)
    out: list[dict[str, Any]] = []
    for draw_index, draw in enumerate(schedule):
        multiplicity = np.bincount(draw, minlength=len(dates)).astype(np.float64)
        denom = float(np.dot(multiplicity, counts))
        require(denom > 0.0, "empty frozen date bootstrap draw")
        out.append({"comparison": comparison, "metric": metric, "draw": draw_index,
                    "difference": float(np.dot(multiplicity, sums) / denom)})
    return out


def _evaluate_approved_once() -> dict[str, Any]:
    fresh_preflight = _fresh_preflight_guard()
    _validate_approval(fresh_preflight)
    allowed_existing = {PREFLIGHT.name}
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in OUTPUTS.iterdir() if p.is_file()}
    require(existing == allowed_existing, f"outputs are not pristine/exclusive: {sorted(existing)}")
    claim_path = OUTPUTS / "execution_claim.json"
    _exclusive_json(claim_path, {"status": "CONSUMED_SINGLE_RUN", "created_at_utc": datetime.now(timezone.utc).isoformat(),
                                 "approval_sha256": sha256_file(APPROVAL), "preflight_sha256": sha256_file(PREFLIGHT),
                                 "run_count": 1, "fit_count": 0, "calibration_count": 0, "weight_search_count": 0})
    start = time.monotonic()
    engine = _load_math_engine()
    joined, r_temps, s_temps = _read_run_inputs()
    races = joined.groupby("race_id", sort=True).agg(
        race_date=("race_date", "first"), year=("year", "first"), field_n=("field_n", "first")
    ).reset_index()
    require(len(races) == EXPECTED_EVAL["races"] and races.race_date.nunique() == EXPECTED_EVAL["dates"],
            "evaluation race/date count changed after approval")
    expected_pools = {"WIN": 2, "PLC": 5, "QNL": 3, "EXA": 3, "QPL": 5, "TLA": 4, "TRI": 4}
    bins = {(pool, i, period): [0.0, 0.0, 0.0, 0.0]
            for pool in engine.POOL_ORDER for i in range(len(engine.BIN_EDGES) - 1)
            for period in ("ALL", "2024", "2025", "2026")}
    metric_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    marginal_rows: list[dict[str, Any]] = []
    axis_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    contract_rows: list[dict[str, Any]] = []
    quarantine_rows: list[dict[str, Any]] = []

    for race_id, group in joined.groupby("race_id", sort=True):
        group = group.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
        year = int(group.year.iloc[0]); race_date = str(group.race_date.iloc[0]); n = len(group)
        require(group.year.nunique() == group.race_date.nunique() == group.field_n.nunique() == 1,
                f"race metadata is inconsistent: {race_id}")
        numbers = group.horse_number.to_numpy(dtype=np.int64)
        ranks = group.finish_position.to_numpy(dtype=np.int64)
        require(n == int(group.field_n.iloc[0]) and set(ranks.tolist()) == set(range(1, n + 1)),
                f"race is not a unique complete strict-order target: {race_id}")
        score_r = group.score_r.to_numpy(dtype=np.float64); score_s = group.score_s.to_numpy(dtype=np.float64)
        plc_top, plc_status = engine.plc_top_for_actual_field(n)
        contract_rows.append({"race_id": str(race_id), "race_date": race_date, "year": year, "field_n": n,
                              "N_at_open": None, "N_at_open_observed": False,
                              "N_at_open_lower_bound": 8 if n >= 8 else None,
                              "plc_top": plc_top, "plc_status": plc_status,
                              "official_sales_or_pool_availability": "not_audited"})
        if plc_top is None and 5 <= n <= 7:
            quarantine_rows.append({"race_id": str(race_id), "race_date": race_date, "field_n": n,
                                    "pool": "PLC", "reason": "opening_field_unknown_actual_5_to_7"})
        maps, marginal, full_mass = engine.probability_maps_from_scenarios(
            [score_r / r_temps[year], score_s / s_temps[year]], [0.5, 0.5], numbers, plc_top)
        require(abs(float(full_mass) - 1.0) <= 3e-11, f"E Q mass mismatch: {race_id}")
        truths_by_pool: dict[str, set[tuple[int, ...]]] = {}
        for pool in engine.POOL_ORDER:
            if n < expected_pools[pool] or (pool == "PLC" and plc_top is None):
                continue
            truths = engine.truth_ticket_keys(pool, numbers, ranks, plc_top)
            truths_by_pool[pool] = truths
            metric, selection = engine.pool_race_metrics(pool, maps[pool], truths)
            metric.update({"race_id": str(race_id), "race_date": race_date, "year": year, "field_n": n, "arm": "E"})
            selection.update({"race_id": str(race_id), "race_date": race_date, "year": year, "field_n": n, "arm": "E"})
            metric_rows.append(metric); selection_rows.append(selection)
            _reliability_add(bins, pool, year, maps[pool], truths, engine.BIN_EDGES)
        for ix, horse_number in enumerate(numbers):
            marginal_rows.append({"api_record_id": int(group.api_record_id.iloc[ix]), "race_id": str(race_id),
                                  "race_date": race_date, "year": year, "horse_number": int(horse_number), "arm": "E",
                                  **{key: float(value[ix]) for key, value in marginal.items()}})
        p_win = marginal["p_win"]; p_max = float(p_win.max())
        chosen_ix = min(ix for ix, p in enumerate(p_win) if float(p) >= p_max - SELECTION_TOLERANCE)
        axis_rows.append({"race_id": str(race_id), "race_date": race_date, "year": year,
                          "selected_horse_number": int(numbers[chosen_ix]), "selected_probability": float(p_win[chosen_ix]),
                          "selected_hit_top3": bool(ranks[chosen_ix] <= 3), "arm": "E"})
        for pool in ("QNL", "QPL"):
            tickets = maps[pool]; truths = truths_by_pool[pool]
            for k in (1, 3):
                selected = _top_k(tickets, k)
                diag = _pair_diagnostic(engine, numbers, score_r, r_temps[year], score_s, s_temps[year],
                                        pool, selected, truths, tickets)
                pair_rows.append({"race_id": str(race_id), "race_date": race_date, "year": year, "field_n": n,
                                  "arm": "E", "pool": pool, "k": k, **diag})

    metrics = pd.DataFrame(metric_rows)
    selections = pd.DataFrame(selection_rows)
    marginals = pd.DataFrame(marginal_rows)
    axis = pd.DataFrame(axis_rows)
    pair_diag = pd.DataFrame(pair_rows)
    race_contract = pd.DataFrame(contract_rows)
    quarantine = pd.DataFrame(quarantine_rows, columns=["race_id", "race_date", "field_n", "pool", "reason"])
    require(len(metrics) == 12417 and len(selections) == 12417 and len(marginals) == EXPECTED_EVAL["runners"] and
            len(axis) == EXPECTED_EVAL["races"] and len(pair_diag) == 7116 and len(quarantine) == 36,
            "E ledger denominator mismatch")
    require(metrics.groupby("pool").race_id.nunique().to_dict() == {
        "WIN": 1779, "PLC": 1743, "QNL": 1779, "EXA": 1779, "QPL": 1779, "TLA": 1779, "TRI": 1779},
        "E per-pool denominator mismatch")

    # Read-only reference ledgers are used for paired summaries, never copied as E outputs.
    r_metrics = pd.read_parquet(R_METRICS).loc[lambda x: x.arm.eq("R")].copy()
    s_metrics = pd.read_parquet(S_METRICS).loc[lambda x: x.arm.eq("S")].copy()
    reference_metrics = pd.concat([r_metrics, s_metrics], ignore_index=True)
    references = {"R": r_metrics, "S": s_metrics}
    pool_summary_rows: list[dict[str, Any]] = []
    paired_metric_parts: dict[str, pd.DataFrame] = {}
    for arm, reference in references.items():
        merged = metrics.merge(reference, on=["pool", "race_id", "race_date", "year", "field_n"],
                               suffixes=("_E", f"_{arm}"), how="outer", indicator=True, validate="one_to_one")
        require(merged._merge.eq("both").all(), f"E/{arm} pool metric race keys differ")
        merged = merged.drop(columns="_merge")
        merged["delta_nll"] = merged.race_nll_E - merged[f"race_nll_{arm}"]
        merged["delta_brier"] = merged.race_brier_E - merged[f"race_brier_{arm}"]
        paired_metric_parts[arm] = merged
        for pool in engine.POOL_ORDER:
            for period in ("ALL", "2024", "2025", "2026"):
                part = merged.loc[merged.pool.eq(pool)]
                if period != "ALL":
                    part = part.loc[part.year.eq(int(period))]
                require(len(part) > 0, f"empty pool summary {arm}/{pool}/{period}")
                pool_summary_rows.append({"comparison": f"E_minus_{arm}", "pool": pool, "period": period,
                                         "races": int(part.race_id.nunique()),
                                         "E_nll": float(part.race_nll_E.mean()), "reference_nll": float(part[f"race_nll_{arm}"].mean()),
                                         "delta_nll": float(part.delta_nll.mean()),
                                         "E_brier": float(part.race_brier_E.mean()), "reference_brier": float(part[f"race_brier_{arm}"].mean()),
                                         "delta_brier": float(part.delta_brier.mean())})
    pool_summary = pd.DataFrame(pool_summary_rows)

    ref_pair = pd.read_parquet(S_PAIR_DIAGNOSTICS)
    ref_pair = ref_pair.loc[ref_pair.arm.isin(("R", "S"))].copy()
    pair_summary = _aggregate_pair_summary(pair_diag, ref_pair)

    # Compare bootstrap draws using the frozen date schedule, preserving equal-race scoring.
    schedule = np.load(BOOTSTRAP, mmap_mode="r", allow_pickle=False)
    dates = sorted(metrics.race_date.astype(str).unique())
    require(len(dates) == EXPECTED_EVAL["dates"] and
            sha256_bytes("\n".join(dates).encode("utf-8")) == EXPECTED_DATE_SHA256, "bootstrap date roster changed")
    bootstrap_rows: list[dict[str, Any]] = []
    for arm, merged in paired_metric_parts.items():
        for pool in engine.POOL_ORDER:
            part = merged.loc[merged.pool.eq(pool)].sort_values(["race_date", "race_id"]).reset_index(drop=True)
            for metric in ("delta_nll", "delta_brier"):
                bootstrap_rows.extend(_date_bootstrap_values(part, schedule, dates, comparison=f"E_minus_{arm}",
                                                              metric=f"{pool}_{metric}",
                                                              left_values=part["race_nll_E" if metric == "delta_nll" else "race_brier_E"],
                                                              right_values=part[f"race_nll_{arm}" if metric == "delta_nll" else f"race_brier_{arm}"]))
        axis_ref_path = R_AXIS if arm == "R" else S_AXIS
        axis_ref_arm = arm
        axis_ref = pd.read_parquet(axis_ref_path, columns=["arm", "race_id", "race_date", "selected_hit_top3"])
        axis_ref = axis_ref.loc[axis_ref.arm.eq(axis_ref_arm), ["race_id", "race_date", "selected_hit_top3"]]
        axis_pair = axis.merge(axis_ref, on=["race_id", "race_date"], suffixes=("_E", f"_{arm}"),
                               how="outer", indicator=True, validate="one_to_one")
        require(axis_pair._merge.eq("both").all(), f"E/{arm} axis keys differ")
        axis_pair = axis_pair.drop(columns="_merge").sort_values(["race_date", "race_id"]).reset_index(drop=True)
        bootstrap_rows.extend(_date_bootstrap_values(axis_pair, schedule, dates, comparison=f"E_minus_{arm}",
                                                      metric="WIN_axis_top3_hit_rate",
                                                      left_values=axis_pair.selected_hit_top3_E.astype(float),
                                                      right_values=axis_pair[f"selected_hit_top3_{arm}"].astype(float)))
        ref_pairs = ref_pair.loc[ref_pair.arm.eq(arm)]
        for pool in ("QNL", "QPL"):
            for k in (1, 3):
                e_part = pair_diag.loc[pair_diag.pool.eq(pool) & pair_diag.k.eq(k),
                                       ["race_id", "race_date", "realized_hit_count"]]
                r_part = ref_pairs.loc[ref_pairs.pool.eq(pool) & ref_pairs.k.eq(k),
                                       ["race_id", "race_date", "realized_hit_count"]]
                pair_join = e_part.merge(r_part, on=["race_id", "race_date"], suffixes=("_E", f"_{arm}"),
                                         how="outer", indicator=True, validate="one_to_one")
                require(pair_join._merge.eq("both").all(), f"E/{arm}/{pool}/k{k} pair keys differ")
                pair_join = pair_join.drop(columns="_merge").sort_values(["race_date", "race_id"]).reset_index(drop=True)
                bootstrap_rows.extend(_date_bootstrap_values(pair_join, schedule, dates,
                                                              comparison=f"E_minus_{arm}",
                                                              metric=f"{pool}_k{k}_hit_any_rate",
                                                              left_values=(pair_join.realized_hit_count_E > 0).astype(float),
                                                              right_values=(pair_join[f"realized_hit_count_{arm}"] > 0).astype(float)))
    bootstrap_draws = pd.DataFrame(bootstrap_rows)

    bin_rows: list[dict[str, Any]] = []
    for pool in engine.POOL_ORDER:
        for period in ("ALL", "2024", "2025", "2026"):
            for ix, (lower, upper) in enumerate(zip(engine.BIN_EDGES[:-1], engine.BIN_EDGES[1:])):
                count, sump, sumy, brier = bins[(pool, ix, period)]
                bin_rows.append({"pool": pool, "arm": "E", "evaluation_period": period, "bin_index": ix,
                                 "bin_lower": float(lower), "bin_upper": float(upper),
                                 "upper_inclusive": bool(ix == len(engine.BIN_EDGES) - 2),
                                 "ticket_events": int(count), "mean_probability": float(sump / count) if count else np.nan,
                                 "observed_event_rate": float(sumy / count) if count else np.nan,
                                 "mean_ticket_brier": float(brier / count) if count else np.nan,
                                 "weighting": "pooled_ticket_event_count"})
    reliability = pd.DataFrame(bin_rows)

    bootstrap_summary: list[dict[str, Any]] = []
    for comparison in ("E_minus_R", "E_minus_S"):
        for metric in ("TRI_delta_nll", "TRI_delta_brier", "WIN_delta_nll", "WIN_delta_brier"):
            part = pool_summary.loc[pool_summary.comparison.eq(comparison) & pool_summary.pool.eq(metric.split("_")[0]) &
                                    pool_summary.period.eq("ALL")]
            row = part.iloc[0]
            diff_col = "delta_nll" if metric.endswith("nll") else "delta_brier"
            draws = bootstrap_draws.loc[bootstrap_draws.comparison.eq(comparison) &
                                        bootstrap_draws.metric.eq(f"{metric.split('_')[0]}_{diff_col}")].difference.to_numpy()
            lo, hi = np.quantile(draws, [0.025, 0.975], method="linear")
            bootstrap_summary.append({"comparison": comparison, "metric": metric, "point_difference": float(row[diff_col]),
                                      "ci95": [float(lo), float(hi)]})
    gate_reports: dict[str, Any] = {}
    for arm in ("R", "S"):
        tri_nll = next(x for x in bootstrap_summary if x["comparison"] == f"E_minus_{arm}" and x["metric"] == "TRI_delta_nll")
        tri_brier = next(x for x in bootstrap_summary if x["comparison"] == f"E_minus_{arm}" and x["metric"] == "TRI_delta_brier")
        win_nll = next(x for x in bootstrap_summary if x["comparison"] == f"E_minus_{arm}" and x["metric"] == "WIN_delta_nll")
        win_brier = next(x for x in bootstrap_summary if x["comparison"] == f"E_minus_{arm}" and x["metric"] == "WIN_delta_brier")
        primary = bool(tri_nll["ci95"][1] < 0.0 and tri_brier["point_difference"] <= 0.0)
        win = bool(win_nll["point_difference"] <= 0.0 and win_brier["point_difference"] <= 0.0)
        gate_reports[arm] = {"TRI_NLL_bootstrap_upper_lt_0": tri_nll["ci95"][1] < 0.0,
                             "TRI_Brier_point_le_0": tri_brier["point_difference"] <= 0.0,
                             "WIN_NLL_point_le_0": win_nll["point_difference"] <= 0.0,
                             "WIN_Brier_point_le_0": win_brier["point_difference"] <= 0.0,
                             "comparison_pass": bool(primary and win), "statistical_noninferiority_claimed": False}
    report = {
        "status": "COMPLETED_RESEARCH_ONLY", "study": "jeju/research/20261022_rs_equal_mixture_v1",
        "candidate": "E = 0.5 Q_R + 0.5 Q_S after each arm's frozen annual raw-score temperature",
        "fit_count": 0, "calibration_count": 0, "weight_search_count": 0,
        "cohort": {"races": len(races), "runners": len(joined), "dates": len(dates),
                   "years": {str(k): int(v) for k, v in races.groupby("year").race_id.nunique().to_dict().items()},
                   "pool_denominators": {pool: int(metrics.loc[metrics.pool.eq(pool)].race_id.nunique()) for pool in engine.POOL_ORDER}},
        "comparisons": gate_reports,
        "overall_research_candidate_gate_pass": bool(
            gate_reports["R"]["comparison_pass"] and gate_reports["S"]["comparison_pass"]),
        "paired_point_and_bootstrap_summary": bootstrap_summary,
        "win_axis": {"races": len(axis), "selected_top3_hits": int(axis.selected_hit_top3.sum()),
                     "selected_top3_hit_rate": float(axis.selected_hit_top3.mean()),
                     "fixed_reference_R_hits": 1023},
        "pair_selection_summary": pair_summary.to_dict("records"),
        "pool_summary_path": "outputs/pool_summary.parquet", "pair_selection_summary_path": "outputs/pair_selection_summary.parquet",
        "reliability_weighting": "pooled ticket-event count by ALL/year, separate from race-equal proper losses",
        "selection_tolerance": SELECTION_TOLERANCE, "EPS": EPS,
        "training_or_calibration": "none; fixed mixture weight 0.5",
        "future_independent_validation": False, "market_roi_evaluated": False,
        "operational_promotion": False,
    }
    parameters = {
        "study": "20261022_rs_equal_mixture_v1", "contract_sha256": CONTRACT_SHA256,
        "candidate": "E = 0.5 Q_R + 0.5 Q_S", "mixture_weight": MIXTURE_WEIGHT,
        "fit_count": 0, "calibration_count": 0, "weight_search_count": 0,
        "R_temperatures": {str(k): float(v) for k, v in r_temps.items()},
        "S_temperatures": {str(k): float(v) for k, v in s_temps.items()},
        "sources": fresh_preflight["source_hashes"],
        "score_sources": fresh_preflight["inputs"],
        "selection": {"topk_tie_tolerance": SELECTION_TOLERANCE, "tie_break": "horse_number_lexicographic"},
        "environment": {"python": sys.version, "numpy": np.__version__, "pandas": pd.__version__,
                        "scipy": scipy.__version__, "platform": platform.platform()},
    }
    outputs: dict[str, Any] = {
        "race_pool_metrics.parquet": metrics,
        "selected_ticket_ledger.parquet": selections,
        "evaluation_runner_marginals.parquet": marginals,
        "win_axis_ledger.parquet": axis,
        "pair_selection_diagnostics.parquet": pair_diag,
        "pair_selection_summary.parquet": pair_summary,
        "reliability_bins.parquet": reliability,
        "pool_summary.parquet": pool_summary,
        "comparison_bootstrap_draws.parquet": bootstrap_draws,
        "race_contract_ledger.parquet": race_contract,
        "evaluation_quarantine.parquet": quarantine,
    }
    for name, frame in outputs.items():
        _exclusive_parquet(OUTPUTS / name, frame)
        require(_study_bytes() <= EXPECTED_STUDY_BYTES, "study storage budget exceeded during evaluation")
    _exclusive_json(OUTPUTS / "parameters.json", parameters)
    _exclusive_json(OUTPUTS / "report.json", report)
    artifact_receipt = {name: {"sha256": sha256_file(OUTPUTS / name), "bytes": (OUTPUTS / name).stat().st_size,
                               "rows": int(pq.ParquetFile(OUTPUTS / name).metadata.num_rows)}
                        for name in outputs}
    artifact_receipt.update({name: {"sha256": sha256_file(OUTPUTS / name), "bytes": (OUTPUTS / name).stat().st_size}
                             for name in ("parameters.json", "report.json")})
    receipt = {"status": "COMPLETED_RESEARCH_ONLY", "completed_at_utc": datetime.now(timezone.utc).isoformat(),
               "elapsed_seconds": time.monotonic() - start, "run_count": 1, "fit_count": 0,
               "calibration_count": 0, "weight_search_count": 0,
               "approval_sha256": sha256_file(APPROVAL), "source_preflight_sha256": sha256_file(PREFLIGHT),
               "code_bundle_sha256": _code_hashes()["code_bundle_sha256"], "artifacts": artifact_receipt,
               "study_bytes_before_receipt": _study_bytes(), "report_gates": gate_reports}
    _exclusive_json(OUTPUTS / "fit_run_receipt.json", receipt)
    require(_study_bytes() <= EXPECTED_STUDY_BYTES, "study storage budget exceeded after receipt")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--synthetic-checks", action="store_true")
    group.add_argument("--source-preflight", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.source_preflight:
        result = write_source_preflight()
    elif args.run:
        result = _evaluate_approved_once()
    else:
        result = run_synthetic_checks()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
