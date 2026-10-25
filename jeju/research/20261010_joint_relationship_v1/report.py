"""Outcome report for an already-fitted, immutable relationship model."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import joint_model as jm
from fit import feature_state


PARAMETERS_PATH = jm.OUT / "fit_parameters.json"
FIT_RECEIPT_PATH = jm.OUT / "fit_receipt.json"


def verify_model_inputs() -> tuple[dict, dict]:
    source_lock = jm.load_json(jm.OUT / "source_lock.json")
    preflight = jm.load_json(jm.OUT / "preflight_receipt.json")
    parameters = jm.load_json(PARAMETERS_PATH)
    fit_receipt = jm.load_json(FIT_RECEIPT_PATH)
    independent_path = jm.OUT / "independent_preflight_receipt.json"
    independent = jm.load_json(independent_path)
    a_verification = jm.load_json(jm.OUT / "a_verification_receipt.json")
    acceptance = jm.load_json(jm.OUT / "c_preflight_acceptance.json")
    if parameters.get("plan_sha256") != jm.EXPECTED_PLAN_SHA256:
        raise AssertionError("fit parameters name a different plan")
    if parameters.get("source_lock_sha256") != jm.sha256(jm.OUT / "source_lock.json"):
        raise AssertionError("fit parameters do not match current source lock")
    if parameters.get("preflight_receipt_sha256") != jm.sha256(jm.OUT / "preflight_receipt.json"):
        raise AssertionError("fit parameters do not match preflight")
    if fit_receipt.get("parameters_sha256") != jm.sha256(PARAMETERS_PATH):
        raise AssertionError("fit receipt does not match immutable parameters")
    if (parameters.get("independent_preflight_receipt_sha256") != jm.sha256(independent_path) or
            not independent.get("passed") or
            independent.get("source_lock_sha256") != jm.sha256(jm.OUT / "source_lock.json") or
            jm.sha256(independent_path) != jm.sha256(jm.C_FINAL_RECEIPT_PATH) or
            parameters.get("a_verification_receipt_sha256") != jm.sha256(jm.OUT / "a_verification_receipt.json") or
            not a_verification.get("passed") or
            parameters.get("c_preflight_acceptance_sha256") != jm.sha256(jm.OUT / "c_preflight_acceptance.json") or
            not acceptance.get("passed")):
        raise AssertionError("fit parameters do not match passing independent C preflight")
    if not preflight.get("passed") or not fit_receipt.get("passed"):
        raise AssertionError("passing preflight and fit receipts are required")
    current = jm.lock_sources()
    locked = source_lock.get("sources", {})
    if {k: v["sha256"] for k, v in current.items()} != {k: v["sha256"] for k, v in locked.items()}:
        raise AssertionError("source hashes differ from preflight lock")
    return parameters, fit_receipt


def exact_metrics(group: pd.DataFrame, beta: np.ndarray, baseline_tau: float,
                  candidate_tau: float, scaler: dict,
                  pair_rms: np.ndarray) -> tuple[dict, list[dict], list[dict]]:
    state = feature_state(group, scaler, pair_rms)
    triples = state["triples"]
    baseline_energy = state["baseline_energy"]
    candidate_energy = baseline_energy + state["triple_features"] @ beta
    truth_index = state["truth_index"]
    baseline_probability = jm.probability_distribution(baseline_energy, baseline_tau)
    candidate_probability = jm.probability_distribution(candidate_energy, candidate_tau)
    baseline_order = jm.stable_top_indices(baseline_energy, 6)
    candidate_order = jm.stable_top_indices(candidate_energy, 6)
    baseline_full_order = np.argsort(-baseline_energy, kind="stable")
    candidate_full_order = np.argsort(-candidate_energy, kind="stable")
    baseline_rank = np.empty(len(triples), dtype=np.int32)
    candidate_rank = np.empty(len(triples), dtype=np.int32)
    baseline_rank[baseline_full_order] = np.arange(1, len(triples) + 1, dtype=np.int32)
    candidate_rank[candidate_full_order] = np.arange(1, len(triples) + 1, dtype=np.int32)
    finish = group.finish_position.to_numpy(int)
    truth = set(np.flatnonzero(finish <= 3).tolist())
    baseline_hit = any(set(triples[idx].tolist()) == truth for idx in baseline_order)
    candidate_hit = any(set(triples[idx].tolist()) == truth for idx in candidate_order)
    baseline_marginal = np.zeros(len(group), dtype=np.float64)
    candidate_marginal = np.zeros(len(group), dtype=np.float64)
    for column in range(3):
        np.add.at(baseline_marginal, triples[:, column], baseline_probability)
        np.add.at(candidate_marginal, triples[:, column], candidate_probability)
    y = (finish <= 3).astype(np.int64)
    runner_records = []
    for index, row in group.reset_index(drop=True).iterrows():
        runner_records.append({
            "api_record_id": int(row.api_record_id),
            "race_id": str(row.race_id),
            "race_date": str(pd.Timestamp(row.race_date).date()),
            "evaluation_year": int(row.year),
            "horse_number": int(row.horse_number),
            "y_top3": int(y[index]),
            "baseline_joint_marginal": float(baseline_marginal[index]),
            "candidate_joint_marginal": float(candidate_marginal[index]),
        })
    numbers = group.horse_number.to_numpy(int)
    relation_energy = state["triple_features"] @ beta
    triple_records = []
    for arm, energy, tau, probability, rank, relation in (
            ("matched_baseline", baseline_energy, baseline_tau, baseline_probability,
             baseline_rank, np.zeros(len(triples), dtype=np.float64)),
            ("candidate", candidate_energy, candidate_tau, candidate_probability,
             candidate_rank, relation_energy)):
        for index, triple in enumerate(triples):
            ticket = ",".join(str(int(number)) for number in sorted(numbers[triple]))
            triple_records.append({
                "race_id": str(group.race_id.iloc[0]),
                "race_date": str(pd.Timestamp(group.race_date.iloc[0]).date()),
                "evaluation_year": int(group.year.iloc[0]),
                "distance_m": int(group.distance_m.iloc[0]),
                "arm": arm,
                "triple_index": int(index),
                "triple_numbers": ticket,
                "baseline_score_energy": float(baseline_energy[index]),
                "relationship_energy": float(relation[index]),
                "total_energy": float(energy[index]),
                "temperature": float(tau),
                "probability": float(probability[index]),
                "is_true_set": bool(index == truth_index),
                "canonical_rank": int(rank[index]),
            })
    race = {
        "race_id": str(group.race_id.iloc[0]),
        "race_date": str(pd.Timestamp(group.race_date.iloc[0]).date()),
        "evaluation_year": int(group.year.iloc[0]),
        "distance_m": float(group.distance_m.iloc[0]),
        "runner_rows": len(group),
        "triple_count": len(triples),
        "baseline_hit6": int(baseline_hit),
        "candidate_hit6": int(candidate_hit),
        "baseline_joint_true_set_nll": jm.set_nll(baseline_energy, truth_index, baseline_tau),
        "candidate_joint_true_set_nll": jm.set_nll(candidate_energy, truth_index, candidate_tau),
        "baseline_joint_brier": float(np.sum(np.square(
            baseline_probability - np.eye(1, len(triples), truth_index)[0]))),
        "candidate_joint_brier": float(np.sum(np.square(
            candidate_probability - np.eye(1, len(triples), truth_index)[0]))),
        "baseline_six_mass": float(baseline_probability[baseline_order].sum()),
        "candidate_six_mass": float(candidate_probability[candidate_order].sum()),
        "baseline_six_tickets": jm.top_ticket_numbers(group, triples, baseline_order),
        "candidate_six_tickets": jm.top_ticket_numbers(group, triples, candidate_order),
        "delta_hit6": int(candidate_hit) - int(baseline_hit),
        "delta_joint_true_set_nll": float(
            jm.set_nll(candidate_energy, truth_index, candidate_tau) -
            jm.set_nll(baseline_energy, truth_index, baseline_tau)),
    }
    return race, runner_records, triple_records


def aggregate_marginal_loss(runners: pd.DataFrame, prediction_column: str) -> dict:
    y = runners.y_top3.to_numpy(float)
    p = np.clip(runners[prediction_column].to_numpy(float), 1e-15, 1.0 - 1e-15)
    contributions = pd.DataFrame({
        "race_id": runners.race_id.to_numpy(),
        "log_loss": -(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)),
        "brier": np.square(p - y),
    })
    race_means = contributions.groupby("race_id", sort=True, observed=True)[["log_loss", "brier"]].mean()
    return {
        "runner_rows": int(len(runners)),
        "aggregation": {
            "primary": "mean of per-race runner-mean losses (strict race-equal)",
            "runner_weighted_secondary": "mean over all runner rows",
        },
        "race_equal": {"races": int(len(race_means)),
                       "binary_log_loss": float(race_means.log_loss.mean()),
                       "brier": float(race_means.brier.mean())},
        "runner_weighted_secondary": {
            "binary_log_loss": float(contributions.log_loss.mean()),
            "brier": float(contributions.brier.mean()),
        },
    }


def reliability_table(races: pd.DataFrame, mass_column: str, hit_column: str) -> list[dict]:
    mass = races[mass_column].to_numpy(float)
    bins = np.minimum(np.floor(mass * 10.0).astype(int), 9)
    records = []
    for bucket in range(10):
        mask = bins == bucket
        if not mask.any():
            continue
        records.append({"bin": bucket, "lower": bucket / 10.0, "upper": (bucket + 1) / 10.0,
                        "races": int(mask.sum()), "mean_six_mass": float(mass[mask].mean()),
                        "observed_six_hit_rate": float(races.loc[mask, hit_column].mean())})
    return records


def write_csv_exclusive(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8", mode="x")


def write_parquet_exclusive(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        table = pa.Table.from_pandas(frame, preserve_index=False)
        pq.write_table(table, stream, compression="zstd", use_dictionary=["race_id", "arm"])
        stream.flush()
        os.fsync(stream.fileno())


def cohort_secondary_summary(group: pd.DataFrame, label: str, value: object) -> dict:
    hit_ci = jm.paired_date_bootstrap(group, "delta_hit6")
    nll_ci = jm.paired_date_bootstrap(group, "delta_joint_true_set_nll")
    return {
        label: value,
        "races": int(len(group)),
        "race_days": int(group.race_date.nunique()),
        "period_start": str(group.race_date.min()),
        "period_end": str(group.race_date.max()),
        "field_size_support": sorted(int(value) for value in group.runner_rows.unique()),
        "candidate_hit6": int(group.candidate_hit6.sum()),
        "baseline_hit6": int(group.baseline_hit6.sum()),
        "delta_hit6_mean": float(group.delta_hit6.mean()),
        "delta_hit6_paired_date_ci95": hit_ci,
        "candidate_joint_true_set_nll": float(group.candidate_joint_true_set_nll.mean()),
        "baseline_joint_true_set_nll": float(group.baseline_joint_true_set_nll.mean()),
        "delta_joint_true_set_nll_mean": float(group.delta_joint_true_set_nll.mean()),
        "delta_joint_true_set_nll_paired_date_ci95": nll_ci,
    }


def run_report(output_dir: Path) -> dict:
    parameters, fit_receipt = verify_model_inputs()
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"report output directory exists; refusing overwrite: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    features = pd.read_parquet(jm.confined(jm.FEATURES_PATH))
    all_races = []
    all_runners = []
    all_triples = []
    for fold in parameters["folds"]:
        year = int(fold["evaluation_year"])
        meta = jm.load_json(jm.STYLE_OUT / f"F1_STYLE6_{year}" / "meta.json")
        evaluation = jm.join_scores(
            features, jm.STYLE_OUT / f"F1_STYLE6_{year}" / "evaluation_scores.parquet",
            year, int(meta["evaluation_rows"]), role="evaluation")
        jm.assert_runner_features(evaluation)
        groups = jm.race_groups(evaluation)
        beta = np.asarray(fold["beta"], dtype=np.float64)
        baseline_tau = float(fold["baseline_tau"]["tau"])
        candidate_tau = float(fold["candidate_tau"]["tau"])
        pair_rms = np.asarray(fold["pair_rms"], dtype=np.float64)
        for group in groups:
            race, runners, triples = exact_metrics(group, beta, baseline_tau, candidate_tau,
                                                    fold["runner_scaler"], pair_rms)
            all_races.append(race)
            all_runners.extend(runners)
            all_triples.extend(triples)

    races = pd.DataFrame(all_races)
    runners = pd.DataFrame(all_runners)
    triples = pd.DataFrame(all_triples)
    if len(races) != jm.EXPECTED_COHORT["races"] or len(runners) != jm.EXPECTED_COHORT["runner_rows"]:
        raise AssertionError("report evaluation cohort differs from fixed 1,779-race contract")
    if races.race_date.nunique() != jm.EXPECTED_COHORT["race_days"]:
        raise AssertionError("report race-day count differs from fixed 269-day contract")
    if len(triples) != 2 * 201404:
        raise AssertionError(f"all-triples report row count mismatch: {len(triples)}")
    arm_counts = triples.arm.value_counts().to_dict()
    if arm_counts != {"matched_baseline": 201404, "candidate": 201404}:
        raise AssertionError(f"all-triples arm counts mismatch: {arm_counts}")
    probability_sums = triples.groupby(["race_id", "arm"], sort=True, observed=True).probability.sum()
    truth_counts = triples.groupby(["race_id", "arm"], sort=True, observed=True).is_true_set.sum()
    rank_counts = triples.groupby(["race_id", "arm"], sort=True, observed=True).canonical_rank.agg(
        ["size", "nunique", "min", "max"])
    if (np.max(np.abs(probability_sums.to_numpy(float) - 1.0)) > 1e-12 or
            not truth_counts.eq(1).all() or
            not rank_counts["size"].eq(rank_counts["nunique"]).all() or
            not rank_counts["min"].eq(1).all() or
            not rank_counts["max"].eq(rank_counts["size"]).all()):
        raise AssertionError("all-triples report probability/truth/rank invariants failed")

    hit_bootstrap = jm.paired_date_bootstrap(races, "delta_hit6", expected_days=269)
    nll_bootstrap = jm.paired_date_bootstrap(races, "delta_joint_true_set_nll", expected_days=269)
    primary = {
        "comparison": "candidate - H2-matched raw-score baseline",
        "candidate_hit6_mean": float(races.candidate_hit6.mean()),
        "baseline_hit6_mean": float(races.baseline_hit6.mean()),
        "candidate_hit6_total": int(races.candidate_hit6.sum()),
        "baseline_hit6_total": int(races.baseline_hit6.sum()),
        "delta_hit6_mean": float(races.delta_hit6.mean()),
        "delta_hit6_date_bootstrap_95ci": hit_bootstrap,
        "candidate_joint_true_set_nll_mean": float(races.candidate_joint_true_set_nll.mean()),
        "baseline_joint_true_set_nll_mean": float(races.baseline_joint_true_set_nll.mean()),
        "delta_joint_true_set_nll_mean": float(races.delta_joint_true_set_nll.mean()),
        "delta_joint_true_set_nll_date_bootstrap_95ci": nll_bootstrap,
    }
    primary["research_signal_gate_passed"] = bool(
        primary["delta_hit6_mean"] > 0 and hit_bootstrap["ci95_low"] > 0 and
        nll_bootstrap["ci95_high"] <= 0
    )

    runners = runners.sort_values(["race_date", "race_id", "horse_number"], kind="stable")
    baseline_marginal_loss = aggregate_marginal_loss(runners, "baseline_joint_marginal")
    candidate_marginal_loss = aggregate_marginal_loss(runners, "candidate_joint_marginal")
    saved_runner = pd.read_parquet(jm.confined(jm.SAVED_STYLE_RUNNER_PATH))
    saved_runner = saved_runner.loc[saved_runner.variant.eq("F1_STYLE6"),
                                    ["api_record_id", "p_top3", "y"]].copy()
    saved_runner.api_record_id = saved_runner.api_record_id.astype("int64")
    saved_runner = saved_runner.rename(columns={"p_top3": "saved_f1_style6_p_top3", "y": "saved_y_top3"})
    runners = runners.merge(saved_runner, on="api_record_id", how="left", validate="one_to_one")
    if runners.saved_f1_style6_p_top3.isna().any() or not np.array_equal(
            runners.y_top3.to_numpy(int), runners.saved_y_top3.to_numpy(int)):
        raise AssertionError("saved F1_STYLE6 runner reference fails complete key/label parity")
    saved_model_marginal = aggregate_marginal_loss(runners, "saved_f1_style6_p_top3")

    yearly = []
    for year, group in races.groupby("evaluation_year", sort=True):
        summary = cohort_secondary_summary(group, "evaluation_year", int(year))
        summary["partial_year"] = bool(int(year) == 2026)
        summary["candidate_joint_brier"] = float(group.candidate_joint_brier.mean())
        summary["baseline_joint_brier"] = float(group.baseline_joint_brier.mean())
        yearly.append(summary)
    distance = []
    for value, group in races.groupby("distance_m", sort=True):
        summary = cohort_secondary_summary(group, "distance_m", int(value))
        summary["candidate_joint_brier"] = float(group.candidate_joint_brier.mean())
        summary["baseline_joint_brier"] = float(group.baseline_joint_brier.mean())
        distance.append(summary)

    write_csv_exclusive(output_dir / "race_metrics.csv", races)
    write_csv_exclusive(output_dir / "runner_marginals.csv", runners)
    write_parquet_exclusive(output_dir / "all_triples.parquet", triples)
    write_csv_exclusive(output_dir / "candidate_six_mass_reliability.csv",
                        pd.DataFrame(reliability_table(races, "candidate_six_mass", "candidate_hit6")))
    write_csv_exclusive(output_dir / "baseline_six_mass_reliability.csv",
                        pd.DataFrame(reliability_table(races, "baseline_six_mass", "baseline_hit6")))
    metrics = {
        "study": "20261010_joint_relationship_v1",
        "plan_sha256": jm.EXPECTED_PLAN_SHA256,
        "fit_parameters_sha256": jm.sha256(PARAMETERS_PATH),
        "fit_receipt_sha256": jm.sha256(FIT_RECEIPT_PATH),
        "preflight_receipt_sha256": jm.sha256(jm.OUT / "preflight_receipt.json"),
        "evaluation_cohort": {"races": int(len(races)), "runner_rows": int(len(runners)),
                              "race_days": int(races.race_date.nunique()),
                              "start_date": str(races.race_date.min()), "end_date": str(races.race_date.max()),
                              "partial_year_2026": True},
        "all_triples_artifact": {"rows": int(len(triples)), "arms": {
                                     str(key): int(value) for key, value in
                                     triples.arm.value_counts().sort_index().items()},
                                 "columns": list(triples.columns)},
        "primary_gate": primary,
        "secondary_descriptive": {
            "overall_joint_brier": {
                "baseline": float(races.baseline_joint_brier.mean()),
                "candidate": float(races.candidate_joint_brier.mean()),
            },
            "runner_marginal_log_loss_and_brier": {
                "h2_matched_baseline": baseline_marginal_loss,
                "candidate_joint_marginal": candidate_marginal_loss,
                "saved_f1_style6_runner_probability": saved_model_marginal,
            },
            "yearly": yearly,
            "distance_m": distance,
            "selected_six_mass_mean": {
                "baseline": float(races.baseline_six_mass.mean()),
                "candidate": float(races.candidate_six_mass.mean()),
            },
        },
        "interpretation": "Retrospective repeated historical development cohort; no independent future holdout or operational promotion.",
        "fit_receipt": fit_receipt,
    }
    jm.write_json_new(output_dir / "report_metrics.json", metrics)
    receipt = {
        "passed": True,
        "study": "20261010_joint_relationship_v1",
        "plan_sha256": jm.EXPECTED_PLAN_SHA256,
        "report_metrics_sha256": jm.sha256(output_dir / "report_metrics.json"),
        "race_metrics_sha256": jm.sha256(output_dir / "race_metrics.csv"),
        "runner_marginals_sha256": jm.sha256(output_dir / "runner_marginals.csv"),
        "all_triples_sha256": jm.sha256(output_dir / "all_triples.parquet"),
        "fit_parameters_sha256": jm.sha256(PARAMETERS_PATH),
        "outcome_metrics_computed_after_fit_artifact": True,
        "research_signal_gate_passed": primary["research_signal_gate_passed"],
        "primary_hit6_ci": hit_bootstrap,
        "primary_joint_nll_ci": nll_bootstrap,
    }
    jm.write_json_new(output_dir / "report_receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))
    return receipt


def main() -> None:
    run_report(jm.OUT / "report")


if __name__ == "__main__":
    main()
