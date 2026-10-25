#!/usr/bin/env python3
"""Independent post-approval reconstruction for the Jeju direct-pair study.

This runner imports only the independent NumPy/math reference module. It never
imports A's core, preflight, or fit helpers and never calls an optimizer. The
first source/output read is gated by A's receipt of the root-authorized fit.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import independent_reference as ref


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
REVIEW_DIR = Path(__file__).resolve().parent
STUDY_REL = "jeju/research/20261011_pair_top3_direct_v1"
STUDY = ROOT / STUDY_REL
OUT = STUDY / "outputs"
FIT_APPROVAL = OUT / "FIT_APPROVAL.json"
FIT_RECEIPT = OUT / "fit_receipt.json"
H1_PATH = OUT / "h1_fit.json"
H2_PATH = OUT / "h2_calibration.json"
PREDICTION_RECEIPT = OUT / "prediction_receipt.json"
PREDICTION_PATH = OUT / "evaluation_pair_predictions.parquet"
RACE_DIAGNOSTICS_PATH = OUT / "evaluation_race_probabilities.parquet"
LOCK_PATH = STUDY / "PREFLIGHT_SOURCE_LOCK.json"
PREFLIGHT_PATH = OUT / "structural_preflight.json"

PLAN_SHA256 = "7fab8fa552d0572e303e626df153b4a231820544b9394d61f133a0f44c917ee5"
CONTRACT_SHA256 = "01b811a7a8aaaae43c7bb16fd08e5505ffbd385e285b6aa6cdb471c15da80b6d"
EVAL_YEARS = (2024, 2025, 2026)
EXPECTED_H1_H2 = {2024: (312, 336), 2025: (326, 311), 2026: (329, 325)}
FEATURE_PATH = "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
MARGINAL_PATH = "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv"
TRIPLES_PATH = "jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet"
PAIR_AXIS_PATH = "jeju/research/20261010_pair_axis_v1/outputs/per_race_metrics.csv"
FEATURE_COLUMNS = [
    "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
    "field_n", "finish_position", *ref.RUNNER_COLUMNS[1:],
]
SCORE_COLUMNS = ["api_record_id", "score"]
TRIPLE_COLUMNS = ["race_id", "race_date", "evaluation_year", "distance_m", "arm", "triple_numbers", "probability"]
AXIS_COLUMNS = ["race_id", "race_date", "evaluation_year", "arm", "policy", "budget_k", "axis_horses", "axis_probability"]
MARGINAL_COLUMNS = ["api_record_id", "race_id", "horse_number", "saved_f1_style6_p_top3", "candidate_joint_marginal"]
PREDICTION_COLUMNS = [
    "race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j", "score_i", "score_j",
    "p0", "eta", "candidate_raw_probability", "candidate_calibrated_probability",
    "baseline_calibrated_probability", "y_pair", "selected_candidate", "selected_baseline",
    "selected_raw_top2", "selected_saved_f1_top2", "selected_candidate_joint_marginal_top2",
    "selected_candidate_joint_maxpair", "selected_matched_joint_maxpair",
]


class ReviewError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_source(relative: str) -> Path:
    candidate = ROOT / relative
    require(not candidate.is_symlink(), f"source path must not be a symlink: {relative}")
    resolved = candidate.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"source path is outside repository or not a file: {relative}")
    return resolved


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"required receipt is missing or a symlink: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"expected a JSON object: {path}")
    return value


def verify_authorization_and_artifact_chain() -> dict[str, Any]:
    # Do this before opening source tables, fitted parameters, or predictions.
    approval = ref.approval_gate(
        FIT_APPROVAL,
        expected_plan_sha256=PLAN_SHA256,
        expected_contract_sha256=CONTRACT_SHA256,
    )
    fit_receipt = read_json(FIT_RECEIPT)
    prediction_receipt = read_json(PREDICTION_RECEIPT)
    lock = read_json(LOCK_PATH)
    preflight = read_json(PREFLIGHT_PATH)
    require(preflight.get("status") == "PASS", "pinned structural preflight is not PASS")
    preflight_sha = sha256_file(PREFLIGHT_PATH)
    require(preflight_sha == approval.get("structural_preflight_sha256"), "approval points to another preflight receipt")
    lock_sha = sha256_file(LOCK_PATH)
    require(lock_sha == fit_receipt.get("source_lock_sha256") == approval.get("structural_preflight_source_lock_sha256"),
            "source lock hash differs across fit receipts")
    require(lock.get("study") == "20261011_pair_top3_direct_v1", "wrong source lock study")
    for relative, digest in lock["frozen_artifacts"].items():
        require(sha256_file(checked_source(relative)) == digest, f"frozen study artifact changed: {relative}")
    for relative, digest in lock["source_inputs"].items():
        require(sha256_file(checked_source(relative)) == digest, f"frozen study input changed: {relative}")

    approval_sha = sha256_file(FIT_APPROVAL)
    require(fit_receipt.get("status") == "PASS" and fit_receipt.get("study") == lock["study"], "fit receipt is not PASS")
    require(fit_receipt.get("fit_approval_sha256") == approval_sha, "fit receipt does not pin fit approval")
    require(fit_receipt.get("same_fold_evaluation_labels_used_for_fit") is False, "fit receipt permits same-fold eval labels")
    require(fit_receipt.get("performance_metrics_computed") is False, "fit receipt claims evaluation metrics")
    require(fit_receipt.get("optimizer_retry_count") == 0, "fit receipt records optimizer retry")
    fit_runner = checked_source(f"{STUDY_REL}/fit.py")
    fit_runner_sha = sha256_file(fit_runner)
    require(fit_runner_sha == approval.get("fit_runner_sha256") == fit_receipt.get("fit_runner_sha256"),
            "fit runner hash differs from approval/receipt")
    require(sha256_file(H1_PATH) == fit_receipt.get("h1_fit_sha256"), "H1 artifact hash differs from fit receipt")
    require(sha256_file(H2_PATH) == fit_receipt.get("h2_calibration_sha256"), "H2 artifact hash differs from fit receipt")

    require(prediction_receipt.get("status") == "PASS", "prediction receipt is not PASS")
    require(prediction_receipt.get("performance_metrics_computed") is False, "A prediction stage computed metrics")
    require(prediction_receipt.get("fit_receipt_sha256") == sha256_file(FIT_RECEIPT), "prediction receipt points to another fit run")
    require(prediction_receipt.get("fit_runner_sha256") == fit_runner_sha, "prediction receipt uses a different runner")
    require(prediction_receipt.get("source_lock_sha256") == lock_sha, "prediction receipt source lock differs")
    require(sha256_file(PREDICTION_PATH) == prediction_receipt.get("evaluation_pair_predictions_sha256"),
            "all-pair prediction hash differs from prediction receipt")
    require(sha256_file(RACE_DIAGNOSTICS_PATH) == prediction_receipt.get("race_probability_diagnostics_sha256"),
            "race diagnostics hash differs from prediction receipt")
    return {
        "approval_sha256": approval_sha,
        "fit_receipt_sha256": sha256_file(FIT_RECEIPT),
        "prediction_receipt_sha256": sha256_file(PREDICTION_RECEIPT),
        "fit_runner_sha256": fit_runner_sha,
        "source_lock_sha256": lock_sha,
        "structural_preflight_sha256": preflight_sha,
        "h1_fit_sha256": sha256_file(H1_PATH),
        "h2_calibration_sha256": sha256_file(H2_PATH),
        "evaluation_pair_predictions_sha256": sha256_file(PREDICTION_PATH),
        "race_probability_diagnostics_sha256": sha256_file(RACE_DIAGNOSTICS_PATH),
        "source_input_sha256": lock["source_inputs"],
        "frozen_study_artifact_sha256": lock["frozen_artifacts"],
        "authorization_status": approval.get("status"),
    }


def load_features(years: tuple[int, ...]) -> pd.DataFrame:
    table = pq.read_table(
        checked_source(FEATURE_PATH),
        columns=FEATURE_COLUMNS,
        filters=[("year", "in", list(years))],
    )
    frame = table.to_pandas()
    frame["race_date"] = pd.to_datetime(frame["race_date"], errors="coerce")
    require(frame["race_date"].notna().all(), "invalid feature race_date")
    require(set(frame["year"].astype(int).unique()) <= set(years), "feature year filter returned other years")
    require(not frame["api_record_id"].duplicated().any(), "duplicate feature api_record_id")
    return frame


def load_scores(relative: str) -> pd.DataFrame:
    path = checked_source(relative)
    schema = pq.ParquetFile(path).schema_arrow
    require(schema.names == SCORE_COLUMNS, f"unexpected saved-score schema: {relative}")
    require(str(schema.field("api_record_id").type) == "int64", f"score key is not int64: {relative}")
    require(str(schema.field("score").type) == "double", f"score is not float64: {relative}")
    frame = pq.read_table(path, columns=SCORE_COLUMNS).to_pandas()
    require(not frame["api_record_id"].duplicated().any(), f"duplicate score key: {relative}")
    require(np.isfinite(frame["score"].to_numpy(dtype=float)).all(), f"non-finite score: {relative}")
    return frame


def merge_scores(features: pd.DataFrame, scores: pd.DataFrame, label: str) -> pd.DataFrame:
    feature_ids = set(features["api_record_id"].astype(int))
    score_ids = set(scores["api_record_id"].astype(int))
    require(feature_ids == score_ids, f"score/features key mismatch in {label}")
    joined = features.merge(scores, on="api_record_id", how="inner", validate="one_to_one", sort=False)
    require(len(joined) == len(features) == len(scores), f"score/features row count mismatch in {label}")
    require(np.isfinite(joined["score"].to_numpy(dtype=float)).all(), f"non-finite joined score in {label}")
    return joined


def calibration_split(year: int, calibration_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    require(set(calibration_rows["year"].astype(int).unique()) == {year - 1}, f"wrong calibration-year rows in fold {year}")
    dates = calibration_rows["race_date"].dt.date
    h1_candidates = calibration_rows.loc[dates.map(lambda value: value.month <= 6)].copy()
    h2 = calibration_rows.loc[dates.map(lambda value: value.month >= 7)].copy()
    require(len(h1_candidates) > 0 and len(h2) > 0, f"empty H1/H2 in fold {year}")
    h2_first = h2["race_date"].min().date()
    h1 = h1_candidates.loc[h1_candidates["race_date"].dt.date <= h2_first - timedelta(days=2)].copy()
    require((h1["race_id"].nunique(), h2["race_id"].nunique()) == EXPECTED_H1_H2[year],
            f"H1/H2 race inventory differs in fold {year}")
    require(h1["race_date"].max().date() <= h2_first - timedelta(days=2), f"H1/H2 T-2 boundary failed in {year}")
    return h1, h2


def independent_races(rows: pd.DataFrame, moments: ref.RunnerMoments) -> list[dict[str, Any]]:
    races: list[dict[str, Any]] = []
    for race_id, race in rows.groupby("race_id", sort=True):
        race = race.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
        n = int(race["field_n"].iloc[0])
        numbers = race["horse_number"].astype(int).tolist()
        finishes = race["finish_position"].astype(int).tolist()
        require(len(race) == n and len(set(numbers)) == n, f"roster/field_n mismatch in {race_id}")
        require(sorted(finishes) == list(range(1, n + 1)), f"finish ranks are not 1..N in {race_id}")
        require(sum(position <= 3 for position in finishes) == 3, f"Top3 runner count differs in {race_id}")
        runner_values = {name: race[name].to_numpy() for name in ref.RUNNER_COLUMNS}
        z, missing = ref.transform_runner_values(runner_values, moments)
        pairs, raw_basis = ref.race_pair_matrix(numbers, z, missing)
        prior_pairs, p0, q0 = ref.exact_top3_pair_prior(numbers, runner_values["score"])
        require(pairs == prior_pairs, f"pair ordering differs across independent calculations in {race_id}")
        finish_by_number = {int(row.horse_number): int(row.finish_position) for row in race.itertuples(index=False)}
        labels = ref.pair_label(finish_by_number, pairs)
        require(int(labels.sum()) == 3, f"pair labels do not have three positives in {race_id}")
        dates = pd.to_datetime(race["race_date"], errors="coerce")
        require(dates.notna().all() and dates.dt.date.nunique() == 1, f"race date mismatch in {race_id}")
        require(race["year"].nunique() == 1, f"year mismatch in {race_id}")
        races.append({
            "race_id": str(race_id),
            "race_date": dates.iloc[0].date().isoformat(),
            "evaluation_year": int(race["year"].iloc[0]),
            "field_n": n,
            "distance_m": None,
            "rows": race,
            "runner_values": runner_values,
            "horse_numbers": numbers,
            "pairs": pairs,
            "basis": raw_basis,
            "labels": labels,
            "p0": p0,
            "q0": q0,
        })
    require(bool(races), "empty independent race set")
    return races


def check_standardization(saved: dict[str, Any], actual: Any, names: tuple[str, ...], label: str) -> dict[str, float]:
    mean_diff=[]; scale_diff=[]; support_diff=[]
    for index, name in enumerate(names):
        require(name in saved, f"stored {label} moments missing {name}")
        record=saved[name]
        mean_diff.append(abs(float(record["mean"])-float(actual.mean[index])))
        scale_diff.append(abs(float(record["scale"])-float(actual.scale[index])))
        support_diff.append(abs(float(record["support_weight"])-float(actual.support_weight[index])))
        require(bool(record["degenerate"]) == bool(actual.degenerate[index]), f"{label} degeneracy differs at {name}")
    maximum={"mean":max(mean_diff,default=0.),"scale":max(scale_diff,default=0.),"support_weight":max(support_diff,default=0.)}
    require(max(maximum.values()) <= 2e-12, f"independent {label} standardization differs from saved values: {maximum}")
    return maximum


def independent_fit_audit(chain: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]], dict[str, Any]]:
    h1_document=read_json(H1_PATH)
    h2_document=read_json(H2_PATH)
    require(h1_document.get("source_lock_sha256")==chain["source_lock_sha256"],"H1 document source lock mismatch")
    require(h1_document.get("fit_approval_sha256")==chain["approval_sha256"],"H1 approval hash mismatch")
    require(h2_document.get("fit_approval_sha256")==chain["approval_sha256"],"H2 approval hash mismatch")
    require(h1_document.get("basis_names")==list(ref.BASIS_NAMES),"H1 basis names/order differ")
    require(h1_document.get("lambda")==1.0,"H1 ridge differs from fixed lambda")
    require(len(h1_document.get("folds",[]))==3 and len(h2_document.get("fold_maps",[]))==6,"wrong number of stored fits")

    feature_rows=load_features((2023,2024,2025))
    h1_folds: dict[int,dict[str,Any]]={}
    h2_folds: dict[int,dict[str,Any]]={}
    audit_rows=[]
    for year in EVAL_YEARS:
        folder=f"jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_{year}"
        cal_path=f"{folder}/calibration_scores.parquet"
        source_cal=merge_scores(feature_rows.loc[feature_rows["year"].eq(year-1)].copy(),load_scores(cal_path),f"{year} calibration")
        h1_rows,h2_rows=calibration_split(year,source_cal)
        fit_row=next((row for row in h1_document["folds"] if int(row["evaluation_year"])==year),None)
        require(fit_row is not None and int(fit_row["calibration_year"])==year-1,f"missing H1 fold row {year}")
        require(int(fit_row["h1_races"])==h1_rows["race_id"].nunique(),f"stored H1 race count differs in {year}")
        require(int(fit_row["h1_dates"])==h1_rows["race_date"].dt.date.nunique(),f"stored H1 date count differs in {year}")

        runner_values={name:h1_rows[name].to_numpy() if name!="score" else h1_rows["score"].to_numpy() for name in ref.RUNNER_COLUMNS}
        runner_moments=ref.fit_runner_moments(runner_values,h1_rows["race_id"].astype(str).to_numpy())
        runner_diff=check_standardization(fit_row["runner_standardization"],runner_moments,ref.RUNNER_COLUMNS,f"H1 runner {year}")
        h1_races=independent_races(h1_rows,runner_moments)
        pair_moments=ref.fit_pair_moments([race["basis"] for race in h1_races])
        pair_diff=check_standardization(fit_row["pair_standardization"],pair_moments,ref.BASIS_NAMES,f"H1 pair {year}")
        beta=np.asarray([fit_row["beta_by_basis"][name] for name in ref.BASIS_NAMES],dtype=float)
        standardized=[ref.apply_pair_moments(race["basis"],pair_moments) for race in h1_races]
        objective,gradient=ref.h1_objective_gradient(
            beta,standardized,[race["p0"] for race in h1_races],[race["labels"] for race in h1_races]
        )
        stored_gradient=np.asarray(fit_row["gradient"],dtype=float)
        gradient_diff=ref.assert_close(gradient,stored_gradient,label=f"H1 gradient {year}")
        objective_diff=abs(objective-float(fit_row["objective"]))
        require(objective_diff<=2e-12,f"H1 objective differs in {year}: {objective_diff}")
        beta_inf=float(np.max(np.abs(gradient)))
        require(bool(fit_row["success"]) and beta_inf<=1e-6,f"H1 stationarity/solver status failed in {year}")
        require(int(fit_row["h1_pairs"])==sum(len(race["pairs"]) for race in h1_races),f"stored H1 pair count differs in {year}")
        require(int(fit_row["positive_pairs"])==3*len(h1_races),f"stored H1 positive count differs in {year}")
        h1_folds[year]={"runner_moments":runner_moments,"pair_moments":pair_moments,"beta":beta,"fit_row":fit_row}

        h2_races=independent_races(h2_rows,runner_moments)
        standardized_h2=[ref.apply_pair_moments(race["basis"],pair_moments) for race in h2_races]
        candidate_logits=[ref.logit(race["p0"])+matrix@beta for race,matrix in zip(h2_races,standardized_h2,strict=True)]
        baseline_logits=[ref.logit(race["p0"]) for race in h2_races]
        maps={row["map"]:row for row in h2_document["fold_maps"] if int(row["evaluation_year"])==year}
        require(set(maps)=={"candidate","baseline"},f"H2 maps missing or duplicated in {year}")
        h2_audit={}
        for name,logits in (("candidate",candidate_logits),("baseline",baseline_logits)):
            entry=maps[name]
            require(entry["raw_input_family"]==("candidate_eta" if name=="candidate" else "logit_p0"),f"H2 input family differs for {year}/{name}")
            params=(float(entry["A"]),float(entry["B"]))
            objective_h2,gradient_h2=ref.platt_objective_gradient(params,logits,[race["labels"] for race in h2_races])
            pg=ref.projected_box_gradient(params,gradient_h2)
            gradient_delta=ref.assert_close(gradient_h2,entry["gradient"],label=f"H2 gradient {year}/{name}")
            pg_delta=ref.assert_close(pg,entry["projected_gradient"],label=f"H2 projected gradient {year}/{name}")
            objective_delta=abs(objective_h2-float(entry["objective"]))
            require(objective_delta<=2e-12,f"H2 objective differs for {year}/{name}: {objective_delta}")
            require(bool(entry["success"]) and float(np.max(np.abs(pg)))<=1e-6,f"H2 KKT/solver status failed for {year}/{name}")
            require(-20.0<=params[0]<=20.0 and .05<=params[1]<=20.0,f"H2 bounds failed for {year}/{name}")
            require(int(entry["h2_races"])==len(h2_races) and int(entry["h2_pairs"])==sum(len(race["pairs"]) for race in h2_races),f"H2 count mismatch for {year}/{name}")
            require(int(entry["positive_pairs"])==3*len(h2_races),f"H2 positive pair count mismatch for {year}/{name}")
            boundary=["lower" if params[0]==-20.0 else "upper" if params[0]==20.0 else "interior",
                      "lower" if params[1]==.05 else "upper" if params[1]==20.0 else "interior"]
            require(entry["boundary_status"]=={"A":boundary[0],"B":boundary[1]},f"H2 boundary status mismatch for {year}/{name}")
            h2_audit[name]={"objective_abs_error":objective_delta,"gradient_max_abs_error":gradient_delta,
                            "projected_gradient_max_abs_error":pg_delta,"projected_gradient_inf_norm":float(np.max(np.abs(pg))),
                            "parameters":{"A":params[0],"B":params[1]},"h2_races":len(h2_races),
                            "h2_pairs":sum(len(race["pairs"]) for race in h2_races)}
        h2_folds[year]={"maps":maps,"races":h2_races}
        audit_rows.append({"evaluation_year":year,"calibration_year":year-1,"h1_races":len(h1_races),
                           "h2_races":len(h2_races),"runner_standardization_max_abs_error":runner_diff,
                           "pair_standardization_max_abs_error":pair_diff,"h1_objective_abs_error":objective_diff,
                           "h1_gradient_max_abs_error":gradient_diff,"h1_gradient_inf_norm":beta_inf,
                           "h2":h2_audit})
    return h1_folds,h2_folds,{"folds":audit_rows,"optimizer_calls":0}


def select_horses_top2(values: list[tuple[int,float]]) -> tuple[int,int]:
    require(len(values)>=2,"not enough runners to select top two")
    ordered=sorted(((int(number),float(value)) for number,value in values),key=lambda item:(-item[1],item[0]))
    return ref.canonical_pair((ordered[0][0],ordered[1][0]))


def parse_pair(value: Any) -> tuple[int,int]:
    match=re.fullmatch(r"\s*\[?\s*(\d+)\s*,\s*(\d+)\s*\]?\s*",str(value).strip())
    require(match is not None,f"invalid saved pair source value: {value!r}")
    return ref.canonical_pair((int(match.group(1)),int(match.group(2))))


def parse_triple(value: Any) -> tuple[int,int,int]:
    match=re.fullmatch(r"\s*\[?\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]?\s*",str(value).strip())
    require(match is not None,f"invalid saved triple source value: {value!r}")
    triple=tuple(sorted(int(match.group(index)) for index in (1,2,3)))
    require(len(set(triple))==3,f"duplicate horse number in triple: {value!r}")
    return triple


def reconstruct_joint_comparators(eval_races: dict[str,dict[str,Any]], marginals: pd.DataFrame) -> tuple[dict[str,dict[str,tuple[int,int]]],dict[str,int]]:
    triples=pq.read_table(checked_source(TRIPLES_PATH),columns=TRIPLE_COLUMNS).to_pandas()
    axis=pd.read_csv(checked_source(PAIR_AXIS_PATH),usecols=AXIS_COLUMNS)
    axis=axis.loc[axis["budget_k"].eq(3)].copy()
    require(not axis.duplicated(["race_id","arm","policy","budget_k"]).any(),"duplicate saved joint selector")
    axis_lookup={(str(row.race_id),str(row.arm),str(row.policy)):row for row in axis.itertuples(index=False)}
    marginal_lookup=marginals.set_index([marginals["race_id"].astype(str),marginals["horse_number"].astype(int)])
    derived_top2={}; candidate_max={}; matched_max={}; distances={}
    rows_by_race_arm={(str(race_id),str(arm)):group for (race_id,arm),group in triples.groupby(["race_id","arm"],sort=True)}
    require(set(str(rid) for rid in eval_races)=={race_id for race_id,_ in rows_by_race_arm},"joint triple race coverage differs from evaluation")
    for race_id,race in eval_races.items():
        roster=sorted(race["horse_numbers"])
        for arm in ("candidate","matched_baseline"):
            key=(race_id,arm)
            require(key in rows_by_race_arm,f"missing joint triples: {key}")
            group=rows_by_race_arm[key]
            parsed=sorted(((parse_triple(row.triple_numbers),float(row.probability)) for row in group.itertuples(index=False)),key=lambda item:item[0])
            require([triple for triple,_ in parsed]==list(itertools.combinations(roster,3)),f"joint triple enumeration differs: {key}")
            require(all(math.isfinite(probability) and probability>0.0 for _,probability in parsed),f"invalid joint probability: {key}")
            require(math.isclose(math.fsum(probability for _,probability in parsed),1.0,rel_tol=0.,abs_tol=1e-12),f"joint probabilities do not sum to one: {key}")
            pair_terms={pair:[] for pair in itertools.combinations(roster,2)}
            horse_terms={horse:[] for horse in roster}
            for triple,probability in parsed:
                for pair in itertools.combinations(triple,2): pair_terms[pair].append(probability)
                for horse in triple: horse_terms[horse].append(probability)
            pair_mass={pair:math.fsum(terms) for pair,terms in pair_terms.items()}
            chosen_max=min(pair for pair,value in pair_mass.items() if value==max(pair_mass.values()))
            policy_row=axis_lookup[(race_id,arm,"maximum_joint_pair")]
            require(parse_pair(policy_row.axis_horses)==chosen_max,f"saved {arm} maximum-pair selector differs from triple reconstruction: {race_id}")
            require(str(policy_row.race_date)==race["race_date"] and int(policy_row.evaluation_year)==race["evaluation_year"],f"joint selector metadata mismatch: {key}")
            distance_values=group["distance_m"].astype(int).unique().tolist()
            require(len(distance_values)==1,f"joint race distance varies: {key}")
            distances[(race_id,arm)]=int(distance_values[0])
            if arm=="candidate":
                candidate_max[race_id]=chosen_max
                for horse in roster:
                    exported=float(marginal_lookup.loc[(race_id,horse),"candidate_joint_marginal"])
                    derived=math.fsum(horse_terms[horse])
                    require(math.isclose(exported,derived,rel_tol=0.,abs_tol=1e-12),f"exported candidate marginal differs from triples: {race_id}/{horse}")
                top2=select_horses_top2([(horse,math.fsum(horse_terms[horse])) for horse in roster])
                axis_top2=axis_lookup[(race_id,"candidate","top_two_marginal_pair")]
                require(parse_pair(axis_top2.axis_horses)==top2,f"saved candidate marginal top-two differs from triple reconstruction: {race_id}")
                require(str(axis_top2.race_date)==race["race_date"] and int(axis_top2.evaluation_year)==race["evaluation_year"],f"candidate marginal selector metadata mismatch: {race_id}")
                derived_top2[race_id]=top2
            else:
                matched_max[race_id]=chosen_max
    for race_id in eval_races:
        require(distances[(race_id,"candidate")]==distances[(race_id,"matched_baseline")],f"candidate/matched distance mismatch: {race_id}")
    return {"candidate_joint_marginal_top2":derived_top2,"candidate_joint_maxpair":candidate_max,
            "matched_joint_maxpair":matched_max}, {"triple_rows":int(len(triples)),"races":len(eval_races),
                "candidate_marginal_top2_reconstructed":len(derived_top2),"candidate_maxpair_reconstructed":len(candidate_max),
                "matched_maxpair_reconstructed":len(matched_max),"distance_values":len(set(distances.values()))}


def independent_evaluation(h1_folds: dict[int,dict[str,Any]],h2_folds: dict[int,dict[str,Any]],chain:dict[str,Any]) -> dict[str,Any]:
    features=load_features(EVAL_YEARS)
    marginals=pd.read_csv(checked_source(MARGINAL_PATH),usecols=MARGINAL_COLUMNS)
    require(not marginals["api_record_id"].duplicated().any(),"duplicate saved marginal api_record_id")
    require(not marginals[["race_id","horse_number"]].duplicated().any(),"duplicate saved marginal runner key")
    marginals["race_id"]=marginals["race_id"].astype(str)
    marginal_lookup=marginals.set_index(["race_id","horse_number"])
    all_races:dict[str,dict[str,Any]]={}
    score_rows_by_race:dict[str,dict[int,float]]={}
    for year in EVAL_YEARS:
        path=f"jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_{year}/evaluation_scores.parquet"
        eval_rows=merge_scores(features.loc[features["year"].eq(year)].copy(),load_scores(path),f"{year} evaluation")
        races=independent_races(eval_rows,h1_folds[year]["runner_moments"])
        for race in races:
            race_id=race["race_id"]
            require(race_id not in all_races,f"duplicate evaluation race across folds: {race_id}")
            all_races[race_id]=race
            score_rows_by_race[race_id]={int(row.horse_number):float(row.score) for row in race["rows"].itertuples(index=False)}

    for race_id,race in all_races.items():
        race["distance_m"]=None
    joint_comparators,joint_audit=reconstruct_joint_comparators(all_races,marginals)
    distance_triples=pq.read_table(checked_source(TRIPLES_PATH),columns=["race_id","arm","distance_m"]).to_pandas()
    distance_lookup=distance_triples.loc[distance_triples["arm"].eq("candidate"),["race_id","distance_m"]].drop_duplicates()
    require(not distance_lookup["race_id"].duplicated().any(),"duplicate candidate distance per race")
    distance_by_race={str(row.race_id):int(row.distance_m) for row in distance_lookup.itertuples(index=False)}
    require(set(distance_by_race)==set(all_races),"distance source race coverage differs")
    for race_id in all_races: all_races[race_id]["distance_m"]=distance_by_race[race_id]

    comparator_pairs={name:dict(mapping) for name,mapping in joint_comparators.items()}
    comparator_pairs["raw_score_top2"]={race_id:select_horses_top2(list(values.items())) for race_id,values in score_rows_by_race.items()}
    comparator_pairs["saved_f1_style6_top2"]={
        race_id:select_horses_top2([(horse,float(marginal_lookup.loc[(race_id,horse),"saved_f1_style6_p_top3"]))
                                    for horse in race["horse_numbers"]])
        for race_id,race in all_races.items()
    }
    norm_rows=[]
    stored_to_expected=[]
    race_probability_expected=[]
    candidate_platt={};baseline_platt={}
    for year in EVAL_YEARS:
        candidate_platt[year]=(float(h2_folds[year]["maps"]["candidate"]["A"]),float(h2_folds[year]["maps"]["candidate"]["B"]))
        baseline_platt[year]=(float(h2_folds[year]["maps"]["baseline"]["A"]),float(h2_folds[year]["maps"]["baseline"]["B"]))
    for race_id in sorted(all_races):
        race=all_races[race_id]
        year=race["evaluation_year"]
        fold=h1_folds[year]
        prediction=ref.produce_race_predictions(
            race["horse_numbers"],race["runner_values"]["score"],race["runner_values"],
            fold["runner_moments"],fold["pair_moments"],fold["beta"],candidate_platt[year],baseline_platt[year],
        )
        require(prediction["baseline_pair"]==comparator_pairs["raw_score_top2"][race_id],f"p0 baseline is not raw-score Top2: {race_id}")
        require(prediction["pairs"]==race["pairs"],f"prediction pair list differs: {race_id}")
        labels=dict(zip(race["pairs"],race["labels"].astype(int).tolist(),strict=True))
        score_by_number=score_rows_by_race[race_id]
        selectors={
            "selected_candidate":prediction["candidate_pair"],
            "selected_baseline":prediction["baseline_pair"],
            "selected_raw_top2":comparator_pairs["raw_score_top2"][race_id],
            "selected_saved_f1_top2":comparator_pairs["saved_f1_style6_top2"][race_id],
            "selected_candidate_joint_marginal_top2":comparator_pairs["candidate_joint_marginal_top2"][race_id],
            "selected_candidate_joint_maxpair":comparator_pairs["candidate_joint_maxpair"][race_id],
            "selected_matched_joint_maxpair":comparator_pairs["matched_joint_maxpair"][race_id],
        }
        pair_lookup={pair:index for index,pair in enumerate(prediction["pairs"])}
        for index,(horse_i,horse_j) in enumerate(prediction["pairs"]):
            record={
                "race_id":race_id,"race_date":race["race_date"],"evaluation_year":year,"distance_m":race["distance_m"],
                "horse_i":horse_i,"horse_j":horse_j,"score_i":score_by_number[horse_i],"score_j":score_by_number[horse_j],
                "p0":float(prediction["p0"][index]),"eta":float(prediction["eta"][index]),
                "candidate_raw_probability":float(prediction["candidate_raw_probability"][index]),
                "candidate_calibrated_probability":float(prediction["candidate_calibrated_probability"][index]),
                "baseline_calibrated_probability":float(prediction["baseline_calibrated_probability"][index]),
                "y_pair":int(labels[(horse_i,horse_j)]),
            }
            for field,pair in selectors.items(): record[field]=int((horse_i,horse_j)==pair)
            stored_to_expected.append(record)
            norm_rows.append({
                "race_id":race_id,"race_date":race["race_date"],"evaluation_year":year,"distance_m":race["distance_m"],
                "horse_a":horse_i,"horse_b":horse_j,"score_a":score_by_number[horse_i],"score_b":score_by_number[horse_j],
                "p0":float(prediction["p0"][index]),"eta":float(prediction["eta"][index]),
                "candidate_calibrated_probability":float(prediction["candidate_calibrated_probability"][index]),
                "baseline_calibrated_probability":float(prediction["baseline_calibrated_probability"][index]),
                "y_pair":int(labels[(horse_i,horse_j)]),"candidate_selected":selectors["selected_candidate"]== (horse_i,horse_j),
            })
        race_probability_expected.append({
            "race_id":race_id,"race_date":race["race_date"],"evaluation_year":year,"distance_m":race["distance_m"],
            "candidate_sum_calibrated_pair_probability_minus_3":math.fsum(prediction["candidate_calibrated_probability"].tolist())-3.,
            "baseline_sum_calibrated_pair_probability_minus_3":math.fsum(prediction["baseline_calibrated_probability"].tolist())-3.,
            "candidate_abs_sum_deviation":abs(math.fsum(prediction["candidate_calibrated_probability"].tolist())-3.),
            "baseline_abs_sum_deviation":abs(math.fsum(prediction["baseline_calibrated_probability"].tolist())-3.),
        })

    stored_table=pq.read_table(checked_source(f"{STUDY_REL}/outputs/evaluation_pair_predictions.parquet"),columns=PREDICTION_COLUMNS).to_pandas()
    expected_fields=["selected_candidate","selected_baseline","selected_raw_top2","selected_saved_f1_top2",
                     "selected_candidate_joint_marginal_top2","selected_candidate_joint_maxpair","selected_matched_joint_maxpair"]
    prediction_parity=ref.verify_prediction_records(
        stored_table.to_dict(orient="records"),stored_to_expected,
        key_fields=("race_id","horse_i","horse_j"),
        numeric_fields=("score_i","score_j","p0","eta","candidate_raw_probability","candidate_calibrated_probability","baseline_calibrated_probability","y_pair"),
        exact_fields=("race_date","evaluation_year","distance_m",*expected_fields),
    )
    stored_diagnostics=pq.read_table(checked_source(f"{STUDY_REL}/outputs/evaluation_race_probabilities.parquet")).to_pandas()
    diag_fields=("candidate_sum_calibrated_pair_probability_minus_3","baseline_sum_calibrated_pair_probability_minus_3",
                 "candidate_abs_sum_deviation","baseline_abs_sum_deviation")
    diag_expected={str(row["race_id"]):row for row in race_probability_expected}
    require(stored_diagnostics["race_id"].astype(str).is_unique and set(stored_diagnostics["race_id"].astype(str))==set(diag_expected),
            "stored per-race diagnostics keys differ")
    diagnostics_max_error={field:0. for field in diag_fields}
    for row in stored_diagnostics.to_dict(orient="records"):
        race_id=str(row["race_id"]); expected=diag_expected[race_id]
        require(str(row["race_date"])==expected["race_date"] and int(row["evaluation_year"])==expected["evaluation_year"]
                and int(row["distance_m"])==expected["distance_m"],f"race diagnostic metadata mismatch: {race_id}")
        for field in diag_fields:
            delta=abs(float(row[field])-float(expected[field]))
            diagnostics_max_error[field]=max(diagnostics_max_error[field],delta)
            require(delta<=1e-12,f"race diagnostic differs at {race_id}/{field}")

    schedule=ref.make_date_bootstrap_schedule([race["race_date"] for race in all_races.values()])
    schedule_receipt=ref.date_bootstrap_schedule_receipt(schedule)
    normalized_report=ref.evaluate_prediction_records(norm_rows,comparator_pairs,candidate_platt,baseline_platt,schedule)
    return {
        "prediction_reproduction":prediction_parity,
        "race_probability_diagnostics_max_abs_error":diagnostics_max_error,
        "joint_comparator_reconstruction":joint_audit,
        "date_bootstrap_schedule":schedule_receipt,
        "evaluation":normalized_report,
        "optimizer_calls":0,
        "a_helpers_imported":False,
    }


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(path.parent.resolve().is_relative_to(REVIEW_DIR), f"review output escaped review directory: {path}")
    require(not path.exists() and not path.is_symlink(), f"refusing to overwrite review artifact: {path}")
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+".tmp")
    require(not temporary.exists(),f"temporary review artifact exists: {temporary}")
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    try:
        chain=verify_authorization_and_artifact_chain()
        h1_folds,h2_folds,fit_audit=independent_fit_audit(chain)
        evaluation=independent_evaluation(h1_folds,h2_folds,chain)
        report={"status":"PASS","study":"20261011_pair_top3_direct_v1",
                "review_scope":"independent stored-fit reconstruction, all-pair predictions, pair selectors, calibration metrics and paired date bootstrap",
                "artifact_chain":chain,"fit_reconstruction":fit_audit,"evaluation_reconstruction":evaluation,
                "source_data_loaded_after_root_fit_approval":True,"operational_or_central_publication_write":False}
        output=REVIEW_DIR/"independent_reproduction.json"
        write_json_once(output,report)
        output_sha=sha256_file(output)
        receipt={"status":"PASS","study":"20261011_pair_top3_direct_v1",
                 "independent_reproduction_sha256":output_sha,
                 "independent_runner_sha256":sha256_file(Path(__file__).resolve()),
                 "independent_reference_sha256":sha256_file(Path(__file__).with_name("independent_reference.py")),
                 "source_lock_sha256":chain["source_lock_sha256"],
                 "fit_receipt_sha256":chain["fit_receipt_sha256"],
                 "prediction_receipt_sha256":chain["prediction_receipt_sha256"],
                 "optimizer_calls":0,"a_helpers_imported":False,
                 "prediction_rows_reproduced":evaluation["prediction_reproduction"]["rows"],
                 "date_bootstrap_schedule":evaluation["date_bootstrap_schedule"]}
        write_json_once(REVIEW_DIR/"INDEPENDENT_REVIEW_RECEIPT.json",receipt)
        print(json.dumps({"status":"PASS","receipt":receipt,
                          "primary_hit_rates":report["evaluation_reconstruction"]["evaluation"]["selected_pair_hit_rates"],
                          "paired_date_ci":report["evaluation_reconstruction"]["evaluation"]["selected_pair_date_bootstrap"],
                          "all_pair_calibration":report["evaluation_reconstruction"]["evaluation"]["all_pair_calibration"]},
                         ensure_ascii=False,indent=2))
        return 0
    except Exception as error:
        print(f"INDEPENDENT_REVIEW_FAIL: {type(error).__name__}: {error}",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
