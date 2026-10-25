#!/usr/bin/env python3
"""Frozen proper-probability evaluation; consumes predictions before outcomes/odds."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import fit_predict as pipeline
import preflight


ROOT = preflight.ROOT
STUDY = preflight.STUDY
OUT = preflight.OUT
PREDICTIONS = pipeline.PREDICTIONS
PREDICTION_RECEIPT = pipeline.PREDICTION_RECEIPT
EVAL_SOURCE_LOCK = OUT / "EVALUATION_SOURCE_LOCK.json"
RACE_POOL_METRICS = OUT / "evaluation_race_pool_metrics.parquet"
CONDITIONAL_METRICS = OUT / "evaluation_conditional_order_metrics.parquet"
HY_DECOMPOSITION = OUT / "hy_same467_tri_nll_decomposition.parquet"
METRICS_JSON = OUT / "METRICS.json"
HY_CANDIDATE_ROWS = ROOT / "jeju/research/20261015_other_pools_postrace_value_v1/candidate_rows.csv"
HY_FINAL_MANIFEST = ROOT / "jeju/research/20261015_other_pools_postrace_value_v1/FINAL_MANIFEST.json"
HY_SOURCE_MANIFEST = ROOT / "jeju/research/20261015_other_pools_postrace_value_v1/SOURCE_MANIFEST.json"
HY_COHORT = ROOT / "jeju/research/20261015_operating_postrace_value_comparison_v1/cohort.csv"
HY_EXPECTED_CANDIDATE_SHA = "74f35fbf3fe18fb29a6942b89a8d06c89e5aa7a3f6ba69c5c8471ebba7068682"
HY_EXPECTED_ROWS = {"WIN": 4475, "QNL": 19388, "EXA": 38776, "TRI": 300102}
SCHEDULE_PATH = preflight.checked_path(preflight.SCHEDULE_PATH)
SCHEDULE_RECEIPT_PATH = preflight.checked_path(preflight.SCHEDULE_RECEIPT_PATH)
EVAL_YEAR_SET = (2024, 2025, 2026)
POOLS = ("WIN", "QNL", "EXA", "TRI")
PROBABILITY_COLUMNS = (
    "p_ordered_joint", "control_p_ordered_joint", "uniform_p_ordered_joint",
)
MODEL_COLUMNS = {
    "F1_STYLE6_COND_ORDER_V1": "p_ordered_joint",
    "fixed_score_conditional_PL": "control_p_ordered_joint",
    "uniform_conditional_order": "uniform_p_ordered_joint",
}
KEY_COLUMNS = ["horse_no_1", "horse_no_2", "horse_no_3"]


class MetricsError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MetricsError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_dates(dates: list[str]) -> str:
    return hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(not path.is_symlink(), f"refusing symlink output: {path}")
    resolved = path.parent.resolve(strict=True) / path.name
    require(resolved.is_relative_to(STUDY), f"output escaped study: {path}")
    require(not resolved.exists(), f"refusing to overwrite output: {resolved}")
    with resolved.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def file_record(path: Path) -> dict:
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def create_evaluation_source_lock() -> dict:
    require(not EVAL_SOURCE_LOCK.exists(), "evaluation source lock already exists")
    require(PREDICTIONS.is_file() and PREDICTION_RECEIPT.is_file(),
            "frozen predictions are required before evaluation source lock")
    receipt = json.loads(PREDICTION_RECEIPT.read_text(encoding="utf-8"))
    require(receipt.get("status") == "PASS_FROZEN_BEFORE_EVALUATION_METRICS"
            and receipt.get("evaluation_metrics_computed") is False,
            "prediction artifact is not frozen before metrics")
    require(receipt.get("artifact_sha256") == sha256_file(PREDICTIONS), "prediction hash differs from receipt")
    require(pipeline.verify_fit_source_lock().get("status") == "FIT_SOURCE_LOCKED_BEFORE_FIT",
            "fit source lock is invalid")
    require(pipeline.sha256_file(pipeline.FIT_ARTIFACTS) == receipt.get("fit_artifacts_sha256"),
            "fit artifact hash differs from prediction receipt")

    require(sha256_file(HY_CANDIDATE_ROWS) == HY_EXPECTED_CANDIDATE_SHA,
            "saved HY event-probability artifact hash changed")
    final_manifest = json.loads(HY_FINAL_MANIFEST.read_text(encoding="utf-8"))
    candidate_record = final_manifest.get("files", {}).get("candidate_rows.csv", {})
    require(candidate_record.get("sha256") == HY_EXPECTED_CANDIDATE_SHA,
            "saved HY final manifest does not pin candidate event probabilities")

    inputs = {
        "evaluation_ordered_joint.parquet": file_record(PREDICTIONS),
        "PREDICTION_RECEIPT.json": file_record(PREDICTION_RECEIPT),
        "FIT_ARTIFACTS.json": file_record(pipeline.FIT_ARTIFACTS),
        "FIT_RECEIPT.json": file_record(pipeline.FIT_RECEIPT),
        "FIT_SOURCE_LOCK.json": file_record(pipeline.FIT_SOURCE_LOCK),
        "ROOT_FIT_APPROVAL.json": file_record(pipeline.FIT_APPROVAL),
        "prior_other_pool_candidate_rows.csv": file_record(HY_CANDIDATE_ROWS),
        "prior_other_pool_FINAL_MANIFEST.json": file_record(HY_FINAL_MANIFEST),
        "prior_other_pool_SOURCE_MANIFEST.json": file_record(HY_SOURCE_MANIFEST),
        "fixed_HY_common_cohort.csv": file_record(HY_COHORT),
        "date_bootstrap_schedule.npy": file_record(SCHEDULE_PATH),
        "date_bootstrap_schedule.json": file_record(SCHEDULE_RECEIPT_PATH),
        "frozen_features.parquet": file_record(preflight.checked_path(preflight.FEATURE_PATH)),
    }
    lock = {
        "status": "EVALUATION_SOURCES_LOCKED_BEFORE_METRICS",
        "study": "20261017_conditional_order_head_v1",
        "phase": "proper_probability_metrics_and_same467_saved_HY_comparison",
        "evaluation_code_sha256": sha256_file(Path(__file__).resolve()),
        "input_hashes": inputs,
        "HY_candidate_rows_sha256": HY_EXPECTED_CANDIDATE_SHA,
        "HY_candidate_rows_read_columns_only": [
            "race_id", "pool", "model", "selection_key", "field_n", "horse_no_1", "horse_no_2", "horse_no_3", "p"
        ],
        "HY_odds_and_hit_columns_loaded": False,
        "odds_read_for_probability_metrics": False,
        "evaluation_outcomes_used_only_after_predictions_were_frozen": True,
        "prediction_artifact_sha256": receipt["artifact_sha256"],
        "prediction_receipt_sha256": sha256_file(PREDICTION_RECEIPT),
        "fit_artifacts_sha256": sha256_file(pipeline.FIT_ARTIFACTS),
        "root_fit_approval_sha256": sha256_file(pipeline.FIT_APPROVAL),
        "metrics_computed": False,
    }
    write_json_once(EVAL_SOURCE_LOCK, lock)
    return lock


def verify_evaluation_source_lock() -> dict:
    require(EVAL_SOURCE_LOCK.is_file(), "evaluation source lock is missing")
    lock = json.loads(EVAL_SOURCE_LOCK.read_text(encoding="utf-8"))
    require(lock.get("status") == "EVALUATION_SOURCES_LOCKED_BEFORE_METRICS",
            "evaluation source lock status is invalid")
    require(lock.get("evaluation_code_sha256") == sha256_file(Path(__file__).resolve()),
            "evaluation code changed after source freeze")
    current = {
        "evaluation_ordered_joint.parquet": PREDICTIONS,
        "PREDICTION_RECEIPT.json": PREDICTION_RECEIPT,
        "FIT_ARTIFACTS.json": pipeline.FIT_ARTIFACTS,
        "FIT_RECEIPT.json": pipeline.FIT_RECEIPT,
        "FIT_SOURCE_LOCK.json": pipeline.FIT_SOURCE_LOCK,
        "ROOT_FIT_APPROVAL.json": pipeline.FIT_APPROVAL,
        "prior_other_pool_candidate_rows.csv": HY_CANDIDATE_ROWS,
        "prior_other_pool_FINAL_MANIFEST.json": HY_FINAL_MANIFEST,
        "prior_other_pool_SOURCE_MANIFEST.json": HY_SOURCE_MANIFEST,
        "fixed_HY_common_cohort.csv": HY_COHORT,
        "date_bootstrap_schedule.npy": SCHEDULE_PATH,
        "date_bootstrap_schedule.json": SCHEDULE_RECEIPT_PATH,
        "frozen_features.parquet": preflight.checked_path(preflight.FEATURE_PATH),
    }
    for label, path in current.items():
        require(file_record(path) == lock["input_hashes"][label], f"evaluation input hash changed: {label}")
    require(sha256_file(HY_CANDIDATE_ROWS) == HY_EXPECTED_CANDIDATE_SHA,
            "saved HY event probability hash changed")
    return lock


def load_truth() -> tuple[pd.DataFrame, dict[str, tuple[int, int, int]]]:
    cols = ["race_id", "race_date", "year", "horse_number", "finish_position", "field_n"]
    features = preflight.read_parquet(preflight.FEATURE_PATH, cols)
    features = features.loc[features["year"].isin(EVAL_YEAR_SET)].copy()
    require(features["race_id"].nunique() == 1779 and len(features) == 17_412,
            "evaluation truth cohort changed from frozen preflight")
    truth_rows: list[dict] = []
    truth_orders: dict[str, tuple[int, int, int]] = {}
    for race_id, race in features.groupby("race_id", sort=True):
        race = race.sort_values(["finish_position", "horse_number"], kind="mergesort")
        top3 = race.loc[race["finish_position"].astype(int).le(3)]
        require(top3["finish_position"].astype(int).tolist() == [1, 2, 3],
                f"evaluation true Top3 incomplete in {race_id}")
        order = tuple(int(value) for value in top3["horse_number"].tolist())
        truth_orders[str(race_id)] = order
        truth_rows.append({"race_id": str(race_id), "race_date": str(race["race_date"].iloc[0]),
                           "evaluation_year": int(race["year"].iloc[0]), "field_n": int(race["field_n"].iloc[0]),
                           "winner": order[0], "second": order[1], "third": order[2]})
    truth = pd.DataFrame(truth_rows)
    return truth, truth_orders


def event_key(pool: str, order: tuple[int, int, int]) -> tuple[int, int, int]:
    if pool == "WIN":
        return (order[0], 0, 0)
    if pool == "QNL":
        return (*tuple(sorted(order[:2])), 0)
    if pool == "EXA":
        return (order[0], order[1], 0)
    if pool == "TRI":
        return order
    raise ValueError(f"unsupported pool: {pool}")


def event_key_for_truth(pool: str, actual: tuple[int, int, int]) -> tuple[int, int, int]:
    return event_key(pool, actual)


def event_probabilities(predictions: pd.DataFrame, pool: str) -> pd.DataFrame:
    group_cols = ["evaluation_year", "race_date", "race_id", "field_n"]
    frame = predictions.copy()
    if pool == "WIN":
        frame["horse_no_2"] = np.int16(0)
        frame["horse_no_3"] = np.int16(0)
        group_cols += KEY_COLUMNS
    elif pool == "QNL":
        a = predictions["horse_no_1"].to_numpy(dtype=np.int16)
        b = predictions["horse_no_2"].to_numpy(dtype=np.int16)
        frame["horse_no_1"] = np.minimum(a, b)
        frame["horse_no_2"] = np.maximum(a, b)
        frame["horse_no_3"] = np.int16(0)
        group_cols += KEY_COLUMNS
    elif pool == "EXA":
        frame["horse_no_3"] = np.int16(0)
        group_cols += KEY_COLUMNS
    elif pool == "TRI":
        group_cols += KEY_COLUMNS
    else:
        raise ValueError(f"unsupported pool: {pool}")
    aggregated = frame.groupby(group_cols, sort=True, as_index=False)[list(MODEL_COLUMNS.values())].sum()
    return aggregated


def event_count(pool: str, field_n: int) -> int:
    if pool == "WIN":
        return field_n
    if pool == "QNL":
        return math.comb(field_n, 2)
    if pool == "EXA":
        return field_n * (field_n - 1)
    if pool == "TRI":
        return field_n * (field_n - 1) * (field_n - 2)
    raise ValueError(pool)


def rank_key(frame: pd.DataFrame, probability_column: str) -> tuple[int, int, int]:
    ordered = frame.sort_values([probability_column, *KEY_COLUMNS],
                                ascending=[False, True, True, True], kind="mergesort")
    row = ordered.iloc[0]
    return tuple(int(row[column]) for column in KEY_COLUMNS)


def race_event_metric_rows(
    event_tables: dict[str, pd.DataFrame], truth: pd.DataFrame, truth_orders: dict[str, tuple[int, int, int]],
    *, hy_events: dict[str, pd.DataFrame] | None = None, common_ids: set[str] | None = None,
) -> pd.DataFrame:
    truth_lookup = truth.set_index("race_id").to_dict("index")
    rows: list[dict] = []
    variants = list(MODEL_COLUMNS.items())
    for pool, events in event_tables.items():
        for race_id, group in events.groupby("race_id", sort=True):
            rid = str(race_id)
            truth_info = truth_lookup[rid]
            actual = truth_orders[rid]
            expected_count = event_count(pool, int(truth_info["field_n"]))
            require(len(group) == expected_count, f"{pool} support count differs in {rid}")
            truth_key = event_key_for_truth(pool, actual)
            key_values = [tuple(int(value) for value in row)
                          for row in group[KEY_COLUMNS].itertuples(index=False, name=None)]
            require(len(set(key_values)) == len(key_values), f"duplicate {pool} event key in {rid}")
            require(truth_key in set(key_values), f"true {pool} event missing in {rid}")
            truth_ix = key_values.index(truth_key)
            for model, p_column in variants:
                p = group[p_column].to_numpy(dtype=float)
                require(np.isfinite(p).all() and (p >= 0.0).all(), f"invalid {pool} probabilities in {rid}/{model}")
                mass = math.fsum(p.tolist())
                require(abs(mass - 1.0) <= 1e-10, f"{pool} event mass != 1 in {rid}/{model}: {mass}")
                p_true = float(p[truth_ix])
                keys = key_values
                order = sorted(range(len(p)), key=lambda i: (-float(p[i]), keys[i]))
                rank1 = keys[order[0]]
                maximum_count = int(np.count_nonzero(p == np.max(p)))
                rows.append({
                    "evaluation_year": int(truth_info["evaluation_year"]),
                    "race_date": truth_info["race_date"], "race_id": rid, "pool": pool,
                    "model": model, "event_count": expected_count,
                    "event_mass": mass, "p_true": p_true,
                    "nll": -math.log(max(p_true, np.finfo(float).tiny)),
                    "brier": float(np.dot(p, p) - 2.0 * p_true + 1.0),
                    "rank1_hit": int(rank1 == truth_key),
                    "rank1_top_tie_count": maximum_count,
                    "rank1_horse_no_1": rank1[0], "rank1_horse_no_2": rank1[1],
                    "rank1_horse_no_3": rank1[2], "truth_horse_no_1": truth_key[0],
                    "truth_horse_no_2": truth_key[1], "truth_horse_no_3": truth_key[2],
                })
        if hy_events is not None and common_ids is not None:
            hy = hy_events[pool]
            for race_id, group in hy.groupby("race_id", sort=True):
                rid = str(race_id)
                require(rid in common_ids, f"HY saved event probability outside fixed cohort: {rid}")
                truth_info = truth_lookup[rid]
                actual = truth_orders[rid]
                expected_count = event_count(pool, int(truth_info["field_n"]))
                require(len(group) == expected_count, f"saved HY {pool} support count differs in {rid}")
                key_values = [tuple(int(value) for value in row)
                              for row in group[KEY_COLUMNS].itertuples(index=False, name=None)]
                require(len(set(key_values)) == len(key_values), f"duplicate saved HY {pool} key in {rid}")
                truth_key = event_key_for_truth(pool, actual)
                require(truth_key in set(key_values), f"saved HY true {pool} event missing in {rid}")
                truth_ix = key_values.index(truth_key)
                p = group["p_hy"].to_numpy(dtype=float)
                require(np.isfinite(p).all() and (p >= 0.0).all(), f"invalid saved HY {pool} probabilities in {rid}")
                mass = math.fsum(p.tolist())
                require(abs(mass - 1.0) <= 1e-10, f"saved HY {pool} mass != 1 in {rid}")
                p_true = float(p[truth_ix])
                order = sorted(range(len(p)), key=lambda i: (-float(p[i]), key_values[i]))
                rank1 = key_values[order[0]]
                rows.append({
                    "evaluation_year": int(truth_info["evaluation_year"]),
                    "race_date": truth_info["race_date"], "race_id": rid, "pool": pool,
                    "model": "operating_hy_r_form", "event_count": expected_count,
                    "event_mass": mass, "p_true": p_true,
                    "nll": -math.log(max(p_true, np.finfo(float).tiny)),
                    "brier": float(np.dot(p, p) - 2.0 * p_true + 1.0),
                    "rank1_hit": int(rank1 == truth_key),
                    "rank1_horse_no_1": rank1[0], "rank1_horse_no_2": rank1[1],
                    "rank1_horse_no_3": rank1[2], "truth_horse_no_1": truth_key[0],
                    "truth_horse_no_2": truth_key[1], "truth_horse_no_3": truth_key[2],
                })
    return pd.DataFrame(rows)


def load_hy_events(common_ids: set[str], event_tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    columns = ["race_id", "pool", "model", "selection_key", "field_n",
               "horse_no_1", "horse_no_2", "horse_no_3", "p"]
    raw = pd.read_csv(HY_CANDIDATE_ROWS, usecols=columns,
                      dtype={"race_id": "string", "pool": "string", "model": "string",
                             "selection_key": "string"})
    raw = raw.loc[raw["model"].eq("operating_hy_r_form") & raw["pool"].isin(POOLS)].copy()
    raw["race_id"] = raw["race_id"].astype(str)
    require(raw["race_id"].nunique() == 467 and set(raw["race_id"]) == common_ids,
            "saved HY event rows do not cover exactly the fixed 467-race cohort")
    require(raw.groupby("pool").size().to_dict() == HY_EXPECTED_ROWS,
            "saved HY event row counts changed")
    parsed = [tuple(int(x) for x in str(value).split("-")) for value in raw["selection_key"]]
    raw[KEY_COLUMNS] = pd.DataFrame([
        (*key, *([0] * (3 - len(key)))) for key in parsed
    ], index=raw.index, columns=KEY_COLUMNS, dtype="int16")
    raw["p"] = pd.to_numeric(raw["p"], errors="raise").astype(float)
    require(np.isfinite(raw["p"].to_numpy()).all() and raw["p"].between(0.0, 1.0).all(),
            "saved HY probabilities outside [0,1]")
    result: dict[str, pd.DataFrame] = {}
    for pool in POOLS:
        group = raw.loc[raw["pool"].eq(pool), ["race_id", *KEY_COLUMNS, "p"]].copy()
        require(not group.duplicated(["race_id", *KEY_COLUMNS]).any(), f"duplicate saved HY {pool} key")
        sums = group.groupby("race_id")["p"].sum()
        require(len(sums) == 467 and np.allclose(sums.to_numpy(), 1.0, rtol=0, atol=1e-10),
                f"saved HY {pool} event mass does not sum to one")
        # Exact event support equality is needed before the operating comparison.
        research_keys = event_tables[pool].loc[
            event_tables[pool]["evaluation_year"].eq(2026)
            & event_tables[pool]["race_id"].astype(str).isin(common_ids),
            ["race_id", *KEY_COLUMNS]
        ]
        hy_keys = group[["race_id", *KEY_COLUMNS]]
        joined = research_keys.merge(hy_keys, on=["race_id", *KEY_COLUMNS], how="outer",
                                     validate="one_to_one", indicator=True)
        require(joined["_merge"].eq("both").all(), f"saved HY {pool} event support differs from research roster")
        result[pool] = group.rename(columns={"p": "p_hy"})
    return result


def conditional_race_metrics(
    predictions: pd.DataFrame, truth: pd.DataFrame, truth_orders: dict[str, tuple[int, int, int]],
) -> pd.DataFrame:
    truth_lookup = truth.set_index("race_id").to_dict("index")
    rows = []
    for race_id, group in predictions.groupby("race_id", sort=True):
        rid = str(race_id)
        actual = truth_orders[rid]
        actual_set = tuple(sorted(actual))
        group_sets = [
            tuple(sorted((int(row.horse_no_1), int(row.horse_no_2), int(row.horse_no_3))))
            for row in group.itertuples(index=False)
        ]
        mask = np.asarray([key == actual_set for key in group_sets], dtype=bool)
        conditional = group.loc[mask].copy()
        require(len(conditional) == 6, f"actual Top3 set must have six conditional orders in {rid}")
        ordered_keys = [tuple(int(value) for value in row)
                        for row in conditional[KEY_COLUMNS].itertuples(index=False, name=None)]
        require(len(set(ordered_keys)) == 6 and actual in set(ordered_keys),
                f"actual Top3 conditional order support invalid in {rid}")
        actual_index = ordered_keys.index(actual)
        truth_info = truth_lookup[rid]
        q_values = conditional["q_top3_set"].to_numpy(float)
        require(np.allclose(q_values, q_values[0], rtol=0, atol=1e-12),
                f"q value differs across conditional order rows in {rid}")
        q_true = float(q_values[0])
        row = {"evaluation_year": int(truth_info["evaluation_year"]),
               "race_date": truth_info["race_date"], "race_id": rid,
               "true_top3_set_probability": q_true,
               "q_nll": -math.log(max(q_true, np.finfo(float).tiny))}
        for model, pcol, ccol in (
            ("F1_STYLE6_COND_ORDER_V1", "p_ordered_joint", "p_conditional_order"),
            ("fixed_score_conditional_PL", "control_p_ordered_joint", "control_p_conditional_order"),
            ("uniform_conditional_order", "uniform_p_ordered_joint", "uniform_p_conditional_order"),
        ):
            p_cond = conditional[ccol].to_numpy(float)
            p_joint = conditional[pcol].to_numpy(float)
            require(abs(math.fsum(p_cond.tolist()) - 1.0) <= 1e-12,
                    f"{model} conditional order mass != 1 in {rid}")
            p_cond_true = float(p_cond[actual_index])
            p_joint_true = float(p_joint[actual_index])
            cond_nll = -math.log(max(p_cond_true, np.finfo(float).tiny))
            full_tri_nll = -math.log(max(p_joint_true, np.finfo(float).tiny))
            require(abs(full_tri_nll - (-math.log(q_true) + cond_nll)) <= 1e-11,
                    f"full TRI NLL does not decompose into q+conditional in {rid}/{model}")
            conditional_order = sorted(range(6), key=lambda i: (-float(p_cond[i]), ordered_keys[i]))[0]
            rows.append({
                **row, "model": model, "conditional_order_nll": cond_nll,
                "full_tri_nll": full_tri_nll,
                "conditional_order_brier": float(np.dot(p_cond, p_cond) - 2.0 * p_cond_true + 1.0),
                "conditional_rank1_hit": int(ordered_keys[conditional_order] == actual),
                "actual_conditional_probability": p_cond_true,
                "actual_full_tri_probability": p_joint_true,
                "candidate_q_preserved": True,
            })
    return pd.DataFrame(rows)


def bootstrap_summary(values: pd.DataFrame, value_column: str, schedule: np.ndarray,
                      dates: list[str], date_column: str = "race_date") -> dict:
    date_to_ix = {date: index for index, date in enumerate(dates)}
    mapped = values[date_column].astype(str).map(date_to_ix)
    require(mapped.notna().all(), f"bootstrap values contain date outside fixed inventory: {value_column}")
    ix = mapped.to_numpy(dtype=int)
    val = values[value_column].to_numpy(dtype=float)
    require(np.isfinite(val).all(), f"non-finite paired bootstrap values: {value_column}")
    count_by_date = np.bincount(ix, minlength=len(dates)).astype(float)
    sum_by_date = np.bincount(ix, weights=val, minlength=len(dates)).astype(float)
    draws = np.asarray(schedule)
    draw_weights = np.zeros_like(draws, dtype=np.float64)
    for i, row in enumerate(draws):
        draw_weights[i] = np.bincount(row, minlength=len(dates))
    denominators = draw_weights @ count_by_date
    numerators = draw_weights @ sum_by_date
    require((denominators > 0).all(), f"bootstrap generated empty cohort for {value_column}")
    estimates = numerators / denominators
    return {
        "mean": float(np.mean(val)),
        "bootstrap_95pct": [float(np.quantile(estimates, 0.025)), float(np.quantile(estimates, 0.975))],
        "bootstrap_draws": int(len(estimates)),
        "unit": "date_block_race_equal",
    }


def paired_bootstrap_differences(
    metric_rows: pd.DataFrame, model_a: str, model_b: str, metric: str,
    schedule: np.ndarray, dates: list[str], pool: str | None = None,
) -> dict:
    part = metric_rows.copy()
    if pool is not None:
        part = part.loc[part["pool"].eq(pool)]
    a = part.loc[part["model"].eq(model_a), ["race_id", "race_date", metric]].rename(columns={metric: "a"})
    b = part.loc[part["model"].eq(model_b), ["race_id", metric]].rename(columns={metric: "b"})
    merged = a.merge(b, on="race_id", how="inner", validate="one_to_one")
    require(len(merged) == len(a) == len(b), f"paired rows differ for {model_a}/{model_b}/{metric}/{pool}")
    merged["difference"] = merged["a"] - merged["b"]
    result = bootstrap_summary(merged.rename(columns={"difference": "metric_difference"}),
                               "metric_difference", schedule, dates)
    result.update({"model_a": model_a, "model_b": model_b, "metric": metric,
                   "pool": pool, "direction": "model_a_minus_model_b"})
    return result


def read_bootstrap(dates: list[str]) -> tuple[np.ndarray, dict]:
    receipt = json.loads(SCHEDULE_RECEIPT_PATH.read_text(encoding="utf-8"))
    schedule = np.load(SCHEDULE_PATH, allow_pickle=False)
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS"
            and receipt.get("draws") == 2000 and receipt.get("dates_per_draw") == 269,
            "date schedule receipt is not frozen 2,000x269")
    require(schedule.shape == (2000, 269) and schedule.dtype == np.int32,
            "fixed date schedule shape/dtype changed")
    require(receipt.get("date_inventory_sha256") == hash_dates(dates),
            "fixed date schedule inventory differs from evaluation dates")
    require(sha256_file(SCHEDULE_PATH) == receipt.get("schedule_sha256"),
            "fixed date schedule file differs from receipt")
    return schedule, receipt


def pool_summary(metric_rows: pd.DataFrame, model: str, pool: str) -> dict:
    part = metric_rows.loc[metric_rows["model"].eq(model) & metric_rows["pool"].eq(pool)]
    unique_top = part.loc[part["rank1_top_tie_count"].eq(1)]
    return {
        "races": int(len(part)),
        "mean_categorical_nll": float(part["nll"].mean()),
        "mean_multiclass_brier": float(part["brier"].mean()),
        "rank1_hit_rate": float(part["rank1_hit"].mean()),
        "rank1_tied_top_races": int(part["rank1_top_tie_count"].gt(1).sum()),
        "rank1_unique_top_races": int(len(unique_top)),
        "rank1_hit_rate_unique_top_only": (float(unique_top["rank1_hit"].mean())
                                             if len(unique_top) else None),
    }


def conditional_summary(frame: pd.DataFrame, model: str) -> dict:
    part = frame.loc[frame["model"].eq(model)]
    return {
        "races": int(part["race_id"].nunique()),
        "conditional_order_nll": float(part["conditional_order_nll"].mean()),
        "full_tri_nll": float(part["full_tri_nll"].mean()),
        "six_order_brier": float(part["conditional_order_brier"].mean()),
        "conditional_rank1_accuracy_given_true_top3": float(part["conditional_rank1_hit"].mean()),
    }


def save_parquet_once(frame: pd.DataFrame, path: Path) -> None:
    require(not path.exists() and not path.is_symlink(), f"refusing to overwrite metrics output: {path}")
    require(path.parent.resolve(strict=True).is_relative_to(STUDY), f"metrics output escaped study: {path}")
    temp = path.with_name(f".{path.name}.partial")
    require(not temp.exists() and not temp.is_symlink(), f"metrics temp exists: {temp}")
    frame.to_parquet(temp, index=False, compression="zstd")
    os.replace(temp, path)


def evaluate() -> dict:
    source_lock = verify_evaluation_source_lock()
    require(not any(path.exists() for path in (RACE_POOL_METRICS, CONDITIONAL_METRICS, HY_DECOMPOSITION, METRICS_JSON)),
            "one or more evaluation outputs already exist")
    pred = pd.read_parquet(PREDICTIONS)
    require(pred.columns.tolist() == pipeline.OUTPUT_COLUMNS, "ordered joint prediction schema changed")
    require(len(pred) == int(json.loads(PREDICTION_RECEIPT.read_text()) ["artifact_rows"]),
            "ordered joint prediction row count differs from receipt")
    require(not pred.duplicated(["race_id", *KEY_COLUMNS]).any(), "ordered joint has duplicate exact order keys")
    require(np.isfinite(pred[list(PROBABILITY_COLUMNS)].to_numpy(float)).all(),
            "ordered joint probabilities contain non-finite values")
    require((pred[list(PROBABILITY_COLUMNS)].to_numpy(float) >= 0.0).all()
            and (pred[list(PROBABILITY_COLUMNS)].to_numpy(float) <= 1.0 + 1e-12).all(),
            "ordered joint probabilities outside [0,1]")
    truth, truth_orders = load_truth()
    pred_races = set(pred["race_id"].astype(str))
    require(pred_races == set(truth["race_id"].astype(str)), "prediction and frozen evaluation race IDs differ")
    dates = sorted(truth["race_date"].astype(str).unique().tolist())
    require(len(dates) == 269, "evaluation date inventory changed")
    schedule, schedule_receipt = read_bootstrap(dates)

    event_tables = {pool: event_probabilities(pred, pool) for pool in POOLS}
    for pool, events in event_tables.items():
        # Verify every pool probability vector is categorical for each race and model.
        for column in MODEL_COLUMNS.values():
            sums = events.groupby("race_id")[column].sum()
            require(len(sums) == 1779 and np.allclose(sums.to_numpy(), 1.0, rtol=0, atol=1e-10),
                    f"{pool}/{column} event mass is not one for all evaluation races")
    cohort = pd.read_csv(HY_COHORT, dtype={"race_id": "string", "race_date": "string"})
    matched = cohort.loc[cohort["qpl_eligible"].astype(bool)].copy()
    common_ids = set(matched["race_id"].astype(str))
    require(len(common_ids) == 467, "saved HY cohort does not contain 467 common races")
    hy_events = load_hy_events(common_ids, event_tables)
    pool_metrics = race_event_metric_rows(event_tables, truth, truth_orders,
                                          hy_events=hy_events, common_ids=common_ids)
    conditional_metrics = conditional_race_metrics(pred, truth, truth_orders)

    primary = conditional_metrics.pivot(index=["race_id", "race_date", "evaluation_year"],
                                        columns="model", values=["conditional_order_nll", "full_tri_nll",
                                                                 "conditional_rank1_hit"])
    primary.columns = ["_".join(column).strip("_") for column in primary.columns.to_flat_index()]
    primary = primary.reset_index()
    primary["conditional_nll_difference_candidate_minus_fixed"] = (
        primary["conditional_order_nll_F1_STYLE6_COND_ORDER_V1"]
        - primary["conditional_order_nll_fixed_score_conditional_PL"]
    )
    primary["full_tri_nll_difference_candidate_minus_fixed"] = (
        primary["full_tri_nll_F1_STYLE6_COND_ORDER_V1"]
        - primary["full_tri_nll_fixed_score_conditional_PL"]
    )
    require(np.allclose(primary["conditional_nll_difference_candidate_minus_fixed"],
                         primary["full_tri_nll_difference_candidate_minus_fixed"],
                         rtol=0, atol=1e-11),
            "full ordered TRI NLL difference differs from conditional NLL difference")
    primary["tri_rank1_hit_difference_candidate_minus_fixed"] = (
        pool_metrics.loc[pool_metrics["pool"].eq("TRI") & pool_metrics["model"].eq("F1_STYLE6_COND_ORDER_V1")]
        .set_index("race_id")["rank1_hit"].reindex(primary["race_id"]).to_numpy()
        - pool_metrics.loc[pool_metrics["pool"].eq("TRI") & pool_metrics["model"].eq("fixed_score_conditional_PL")]
        .set_index("race_id")["rank1_hit"].reindex(primary["race_id"]).to_numpy()
    )
    primary_ci = bootstrap_summary(primary, "conditional_nll_difference_candidate_minus_fixed", schedule, dates)
    full_tri_ci = bootstrap_summary(primary, "full_tri_nll_difference_candidate_minus_fixed", schedule, dates)
    tri_hit_ci = bootstrap_summary(primary, "tri_rank1_hit_difference_candidate_minus_fixed", schedule, dates)
    cond_acc_diff = bootstrap_summary(
        primary.assign(diff=(primary["conditional_rank1_hit_F1_STYLE6_COND_ORDER_V1"]
                             - primary["conditional_rank1_hit_fixed_score_conditional_PL"])),
        "diff", schedule, dates,
    )
    gate_primary = primary_ci["bootstrap_95pct"][1] < 0.0
    gate_tri_hit = float(primary["tri_rank1_hit_difference_candidate_minus_fixed"].mean()) >= 0.0

    overall_pool = {}
    for pool in POOLS:
        overall_pool[pool] = {
            model: pool_summary(pool_metrics, model, pool)
            for model in MODEL_COLUMNS
        }
    year_pool = {}
    for year in EVAL_YEAR_SET:
        year_pool[str(year)] = {
            pool: {
                model: {
                    "races": int(len(pool_metrics.loc[pool_metrics["evaluation_year"].eq(year)
                                                       & pool_metrics["pool"].eq(pool)
                                                       & pool_metrics["model"].eq(model)])),
                    "mean_categorical_nll": float(pool_metrics.loc[pool_metrics["evaluation_year"].eq(year)
                                                                   & pool_metrics["pool"].eq(pool)
                                                                   & pool_metrics["model"].eq(model), "nll"].mean()),
                    "mean_multiclass_brier": float(pool_metrics.loc[pool_metrics["evaluation_year"].eq(year)
                                                                         & pool_metrics["pool"].eq(pool)
                                                                         & pool_metrics["model"].eq(model), "brier"].mean()),
                    "rank1_hit_rate": float(pool_metrics.loc[pool_metrics["evaluation_year"].eq(year)
                                                               & pool_metrics["pool"].eq(pool)
                                                               & pool_metrics["model"].eq(model), "rank1_hit"].mean()),
                    "rank1_tied_top_races": int(pool_metrics.loc[pool_metrics["evaluation_year"].eq(year)
                                                                     & pool_metrics["pool"].eq(pool)
                                                                     & pool_metrics["model"].eq(model),
                                                                     "rank1_top_tie_count"].gt(1).sum()),
                    "rank1_unique_top_races": int(pool_metrics.loc[pool_metrics["evaluation_year"].eq(year)
                                                                       & pool_metrics["pool"].eq(pool)
                                                                       & pool_metrics["model"].eq(model),
                                                                       "rank1_top_tie_count"].eq(1).sum()),
                    "rank1_hit_rate_unique_top_only": (
                        float(pool_metrics.loc[pool_metrics["evaluation_year"].eq(year)
                                               & pool_metrics["pool"].eq(pool)
                                               & pool_metrics["model"].eq(model)
                                               & pool_metrics["rank1_top_tie_count"].eq(1),
                                               "rank1_hit"].mean())
                        if pool_metrics.loc[pool_metrics["evaluation_year"].eq(year)
                                            & pool_metrics["pool"].eq(pool)
                                            & pool_metrics["model"].eq(model)
                                            & pool_metrics["rank1_top_tie_count"].eq(1)].shape[0] else None
                    ),
                }
                for model in MODEL_COLUMNS
            }
            for pool in POOLS
        }

    hy_comparison = {}
    same467_2026 = pool_metrics.loc[
        pool_metrics["evaluation_year"].eq(2026)
        & pool_metrics["race_id"].astype(str).isin(common_ids)
        & pool_metrics["model"].isin(("F1_STYLE6_COND_ORDER_V1", "operating_hy_r_form"))
    ]
    for pool in POOLS:
        hy_comparison[pool] = {}
        for metric in ("nll", "brier", "rank1_hit"):
            hy_comparison[pool][metric] = paired_bootstrap_differences(
                same467_2026,
                "F1_STYLE6_COND_ORDER_V1", "operating_hy_r_form", metric, schedule, dates, pool,
            )

    tri_decomp = tri_nll_decomposition(pred, hy_events["TRI"], truth, truth_orders, common_ids)
    nll_summaries = {
        model: conditional_summary(conditional_metrics, model)
        for model in MODEL_COLUMNS
    }
    metrics = {
        "status": "PASS_FROZEN_PREDICTION_EVALUATION",
        "study": "20261017_conditional_order_head_v1",
        "evaluation_years": {str(y): nll_summaries_for_year(conditional_metrics, y) for y in EVAL_YEAR_SET},
        "all_year_conditional_order": nll_summaries,
        "primary_candidate_minus_fixed_score_conditional_nll": primary_ci,
        "full_ordered_tri_nll_difference_assertion": {
            "point_mean": float(primary["full_tri_nll_difference_candidate_minus_fixed"].mean()),
            "paired_bootstrap_95pct": full_tri_ci["bootstrap_95pct"],
            "race_level_equal_to_conditional_nll_delta": True,
            "max_abs_race_level_delta_difference": float(np.max(np.abs(
                primary["conditional_nll_difference_candidate_minus_fixed"]
                - primary["full_tri_nll_difference_candidate_minus_fixed"]
            ))),
        },
        "whole_race_tri_rank1_hit_guard_vs_fixed_score": {
            "point_difference": float(primary["tri_rank1_hit_difference_candidate_minus_fixed"].mean()),
            "paired_bootstrap_95pct": tri_hit_ci["bootstrap_95pct"],
            "point_nonregression_pass": gate_tri_hit,
        },
        "conditional_rank1_accuracy_diagnostic_only": cond_acc_diff,
        "pool_metrics_all_evaluation_races": overall_pool,
        "pool_metrics_by_year": year_pool,
        "rank1_tie_handling": {
            "deterministic_rank1_key_tie_break": "ascending horse_no_1, horse_no_2, horse_no_3",
            "unique_top_hit_rate_and_tie_counts_reported": True,
            "uniform_order_tied_rank1_should_not_be_interpreted_as_a_unique_winner": True,
        },
        "same_2026_common_467_vs_saved_operating_hy_r_form": hy_comparison,
        "same_467_tri_nll_decomposition_candidate_minus_hy": tri_decomp["summary"],
        "same_467_tri_nll_decomposition_identity_max_abs_error": tri_decomp["max_identity_error"],
        "primary_research_gate": {
            "source_and_probability_coherence_pass": True,
            "conditional_order_nll_95pct_ci_favors_candidate": gate_primary,
            "whole_race_tri_rank1_point_nonregression": gate_tri_hit,
            "gate_pass": bool(gate_primary and gate_tri_hit),
            "conditional_rank1_accuracy_is_not_used_as_whole_race_guard": True,
        },
        "bootstrap": {"draws": int(len(schedule)), "dates_per_draw": int(schedule.shape[1]),
                      "schedule_sha256": schedule_receipt["schedule_sha256"],
                      "date_inventory_sha256": schedule_receipt["date_inventory_sha256"]},
        "source_lock_sha256": sha256_file(EVAL_SOURCE_LOCK),
        "prediction_sha256": sha256_file(PREDICTIONS),
        "evaluation_code_sha256": sha256_file(Path(__file__).resolve()),
        "HY_probability_source_sha256": HY_EXPECTED_CANDIDATE_SHA,
        "HY_odds_or_hit_columns_read": False,
        "market_odds_read_for_probability_metrics": False,
        "model_or_temperature_tuned_on_evaluation": False,
        "production_or_registry_changed": False,
    }
    save_parquet_once(pool_metrics, RACE_POOL_METRICS)
    save_parquet_once(conditional_metrics, CONDITIONAL_METRICS)
    save_parquet_once(tri_decomp["frame"], HY_DECOMPOSITION)
    metrics["outputs"] = {
        "evaluation_race_pool_metrics.parquet": file_record(RACE_POOL_METRICS),
        "evaluation_conditional_order_metrics.parquet": file_record(CONDITIONAL_METRICS),
        "hy_same467_tri_nll_decomposition.parquet": file_record(HY_DECOMPOSITION),
    }
    write_json_once(METRICS_JSON, metrics)
    return metrics


def nll_summaries_for_year(frame: pd.DataFrame, year: int) -> dict:
    result = {}
    for model in MODEL_COLUMNS:
        part = frame.loc[frame["evaluation_year"].eq(year) & frame["model"].eq(model)]
        result[model] = {
            "races": int(len(part)),
            "conditional_order_nll": float(part["conditional_order_nll"].mean()),
            "full_tri_nll": float(part["full_tri_nll"].mean()),
            "six_order_brier": float(part["conditional_order_brier"].mean()),
            "conditional_rank1_accuracy_given_true_top3": float(part["conditional_rank1_hit"].mean()),
        }
    return result


def tri_nll_decomposition(predictions: pd.DataFrame, hy_tri: pd.DataFrame, truth: pd.DataFrame,
                          truth_orders: dict[str, tuple[int, int, int]], common_ids: set[str]) -> dict:
    truth_lookup = truth.set_index("race_id").to_dict("index")
    pred = predictions.loc[predictions["evaluation_year"].eq(2026)
                           & predictions["race_id"].astype(str).isin(common_ids)].copy()
    hy = hy_tri.copy()
    hy["set_key"] = [tuple(sorted((int(a), int(b), int(c))))
                     for a, b, c in zip(hy["horse_no_1"], hy["horse_no_2"], hy["horse_no_3"])]
    rows = []
    for rid in sorted(common_ids):
        actual = truth_orders[rid]
        set_key = tuple(sorted(actual))
        research_race = pred.loc[pred["race_id"].astype(str).eq(rid)].copy()
        research_race["set_key"] = [tuple(sorted((int(a), int(b), int(c))))
                                    for a, b, c in zip(research_race["horse_no_1"],
                                                       research_race["horse_no_2"], research_race["horse_no_3"])]
        research_set = research_race.loc[[key == set_key for key in research_race["set_key"]]]
        require(len(research_set) == 6, f"research actual Top3 set has !=6 orders: {rid}")
        research_q_values = research_set["q_top3_set"].unique()
        require(len(research_q_values) == 1, f"research q varies within actual Top3 set: {rid}")
        research_q = float(research_q_values[0])
        research_order_mask = [
            tuple(int(row[column]) for column in KEY_COLUMNS) == actual
            for _, row in research_set.iterrows()
        ]
        research_order = research_set.loc[research_order_mask]
        require(len(research_order) == 1, f"research exact actual TRI order missing: {rid}")
        research_p = float(research_order["p_ordered_joint"].iloc[0])
        research_cond = research_p / research_q

        hy_race = hy.loc[hy["race_id"].astype(str).eq(rid)]
        hy_set = hy_race.loc[[key == set_key for key in hy_race["set_key"]]]
        require(len(hy_set) == 6, f"HY actual Top3 set has !=6 orders: {rid}")
        hy_q = math.fsum(hy_set["p_hy"].to_numpy(float).tolist())
        hy_order_mask = [
            tuple(int(row[column]) for column in KEY_COLUMNS) == actual
            for _, row in hy_set.iterrows()
        ]
        hy_order = hy_set.loc[hy_order_mask]
        require(len(hy_order) == 1, f"HY exact actual TRI order missing: {rid}")
        hy_p = float(hy_order["p_hy"].iloc[0])
        hy_cond = hy_p / hy_q
        row = {
            "race_id": rid,
            "race_date": truth_lookup[rid]["race_date"],
            "f1_q_top3_set_probability": research_q,
            "hy_q_top3_set_probability": hy_q,
            "f1_order_conditional_probability": research_cond,
            "hy_order_conditional_probability": hy_cond,
            "f1_tri_joint_probability": research_p,
            "hy_tri_joint_probability": hy_p,
            "f1_q_nll": -math.log(max(research_q, np.finfo(float).tiny)),
            "hy_q_nll": -math.log(max(hy_q, np.finfo(float).tiny)),
            "f1_conditional_order_nll": -math.log(max(research_cond, np.finfo(float).tiny)),
            "hy_conditional_order_nll": -math.log(max(hy_cond, np.finfo(float).tiny)),
            "f1_full_tri_nll": -math.log(max(research_p, np.finfo(float).tiny)),
            "hy_full_tri_nll": -math.log(max(hy_p, np.finfo(float).tiny)),
        }
        row["q_nll_gap_f1_minus_hy"] = row["f1_q_nll"] - row["hy_q_nll"]
        row["conditional_order_nll_gap_f1_minus_hy"] = (
            row["f1_conditional_order_nll"] - row["hy_conditional_order_nll"]
        )
        row["full_tri_nll_gap_f1_minus_hy"] = row["f1_full_tri_nll"] - row["hy_full_tri_nll"]
        rows.append(row)
    frame = pd.DataFrame(rows)
    identity_error = frame["full_tri_nll_gap_f1_minus_hy"] - (
        frame["q_nll_gap_f1_minus_hy"] + frame["conditional_order_nll_gap_f1_minus_hy"]
    )
    max_error = float(np.max(np.abs(identity_error)))
    require(max_error <= 1e-11, "F1−HY TRI NLL gap does not decompose into q and order components")
    schedule, receipt = read_bootstrap(sorted(truth["race_date"].astype(str).unique().tolist()))
    summary = {}
    for column in ("q_nll_gap_f1_minus_hy", "conditional_order_nll_gap_f1_minus_hy",
                   "full_tri_nll_gap_f1_minus_hy"):
        summary[column] = bootstrap_summary(frame, column, schedule,
                                            sorted(truth["race_date"].astype(str).unique().tolist()))
    summary["races"] = int(len(frame))
    summary["identity_max_abs_error"] = max_error
    summary["schedule_sha256"] = receipt["schedule_sha256"]
    return {"frame": frame, "summary": summary, "max_identity_error": max_error}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze-evaluation-sources", "evaluate"))
    args = parser.parse_args()
    try:
        if args.phase == "freeze-evaluation-sources":
            result = create_evaluation_source_lock()
        else:
            result = evaluate()
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except Exception as exc:
        print(f"ORDER_HEAD_METRICS_FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
