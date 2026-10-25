#!/usr/bin/env python3
"""Single-run H1/H2 fitting and frozen-cohort pair prediction.

Stages are deliberately separate. ``fit`` reads only calibration-year labels,
writes a pre-fit authorization receipt containing this file's hash, then runs
the three fixed H1 and six fixed H2 fits once. ``predict`` requires a passing
fit receipt and only then opens evaluation labels to write the all-pair table.
No performance metrics are computed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import scipy
from scipy.special import expit, logit

import core
import preflight


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
OUT = STUDY / "outputs"
FIT_APPROVAL_PATH = OUT / "FIT_APPROVAL.json"
FIT_RECEIPT_PATH = OUT / "fit_receipt.json"
H1_PATH = OUT / "h1_fit.json"
H2_PATH = OUT / "h2_calibration.json"
PREDICTION_PATH = OUT / "evaluation_pair_predictions.parquet"
RACE_DIAGNOSTICS_PATH = OUT / "evaluation_race_probabilities.parquet"
PRE_FLIGHT_HASH = "37b7a1539d46619501f731477662a87f97e9f31a3db8a54337d7340231100d15"
EXPECTED_H1_H2 = {2024: (312, 336), 2025: (326, 311), 2026: (329, 325)}
FEATURE_PATH = "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
MARGINAL_PATH = "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv"
TRIPLES_PATH = "jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet"
PAIR_AXIS_PATH = "jeju/research/20261010_pair_axis_v1/outputs/per_race_metrics.csv"
FIT_FEATURE_COLUMNS = [
    "api_record_id", "race_id", "race_date", "year", "horse_id",
    "horse_number", "field_n", "finish_position",
    *(column for column in core.RUNNER_COLUMNS if column != "score"),
]
PREDICTION_COLUMNS = [
    "race_id", "race_date", "evaluation_year", "distance_m",
    "horse_i", "horse_j", "score_i", "score_j", "p0", "eta",
    "candidate_raw_probability", "candidate_calibrated_probability",
    "baseline_calibrated_probability", "y_pair", "selected_candidate",
    "selected_baseline", "selected_raw_top2", "selected_saved_f1_top2",
    "selected_candidate_joint_marginal_top2", "selected_candidate_joint_maxpair",
    "selected_matched_joint_maxpair",
]


class FitError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FitError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked(relative: str) -> Path:
    path = ROOT / relative
    require(not path.is_symlink(), f"input must not be a symlink: {relative}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"invalid input path: {relative}")
    return resolved


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.exists(), f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    require(not temporary.exists(), f"temporary output already exists: {temporary}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def verify_preflight() -> tuple[dict[str, Any], dict[str, str], str]:
    receipt_path = checked("jeju/research/20261011_pair_top3_direct_v1/outputs/structural_preflight.json")
    receipt_hash = sha256_file(receipt_path)
    require(receipt_hash == PRE_FLIGHT_HASH, f"unexpected structural preflight receipt hash: {receipt_hash}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(receipt.get("status") == "PASS", "structural preflight is not PASS")
    require(receipt.get("model_fit_performed") is False, "preflight receipt already records a model fit")
    require(receipt.get("performance_metrics_computed") is False, "preflight receipt already records performance metrics")
    source_hashes = preflight.verify_hashes()
    artifact_hashes, lock_hash = preflight.verify_study_source_lock()
    require(receipt.get("source_sha256") == source_hashes, "preflight source hashes changed")
    require(receipt.get("study_artifact_sha256") == artifact_hashes, "frozen design/code changed after preflight")
    require(receipt.get("study_source_lock_sha256") == lock_hash, "source lock changed after preflight")
    return receipt, artifact_hashes, lock_hash


def feature_rows(years: tuple[int, ...]) -> pd.DataFrame:
    frame = pq.read_table(
        checked(FEATURE_PATH), columns=FIT_FEATURE_COLUMNS,
        filters=[("year", "in", list(years))],
    ).to_pandas()
    frame["race_date"] = pd.to_datetime(frame["race_date"], errors="coerce")
    require(frame["race_date"].notna().all(), "invalid feature race_date")
    require(np.isfinite(frame["finish_position"].to_numpy(dtype=float)).all(), "invalid feature finish_position")
    require(set(frame["year"].astype(int).unique()) <= set(years), "feature year filter failed")
    return frame


def fold_calibration(year: int, features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    folder = f"jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_{year}"
    scores = preflight.read_score(f"{folder}/calibration_scores.parquet")
    rows = features.loc[features["year"].eq(year - 1)].copy()
    joined = preflight.add_scores(rows, scores, f"{year} calibration")
    date_values = joined["race_date"].dt.date
    h1_candidates = joined.loc[date_values.map(lambda d: d.month <= 6)].copy()
    h2 = joined.loc[date_values.map(lambda d: d.month >= 7)].copy()
    require(len(h1_candidates) > 0 and len(h2) > 0, f"empty H1/H2 calibration fold {year}")
    first_h2 = h2["race_date"].min().date()
    h1_deadline = first_h2 - timedelta(days=2)
    h1 = h1_candidates.loc[h1_candidates["race_date"].dt.date <= h1_deadline].copy()
    expected_h1, expected_h2 = EXPECTED_H1_H2[year]
    require((h1["race_id"].nunique(), h2["race_id"].nunique()) == (expected_h1, expected_h2), f"frozen H1/H2 counts changed for {year}")
    require(h1["race_date"].max().date() <= first_h2 - timedelta(days=2), f"H1/H2 T-2 failed for {year}")
    return h1, h2


def runner_stats_to_json(stats: core.Standardization) -> dict[str, Any]:
    return {
        column: {
            "mean": float(stats.mean[index]),
            "scale": float(stats.scale[index]),
            "degenerate": bool(stats.degenerate[index]),
            "support_weight": float(stats.support_weight[index]),
        }
        for index, column in enumerate(stats.columns)
    }


def pair_stats_to_json(stats: core.PairStandardization) -> dict[str, Any]:
    return {
        name: {
            "mean": float(stats.mean[index]),
            "scale": float(stats.scale[index]),
            "degenerate": bool(stats.degenerate[index]),
            "support_weight": float(stats.support_weight[index]),
        }
        for index, name in enumerate(core.BASIS_NAMES)
    }


def runner_stats_from_json(value: dict[str, Any]) -> core.Standardization:
    return core.Standardization(
        columns=core.RUNNER_COLUMNS,
        mean=np.asarray([value[name]["mean"] for name in core.RUNNER_COLUMNS], dtype=float),
        scale=np.asarray([value[name]["scale"] for name in core.RUNNER_COLUMNS], dtype=float),
        degenerate=tuple(bool(value[name]["degenerate"]) for name in core.RUNNER_COLUMNS),
        support_weight=tuple(float(value[name]["support_weight"]) for name in core.RUNNER_COLUMNS),
    )


def pair_stats_from_json(value: dict[str, Any]) -> core.PairStandardization:
    return core.PairStandardization(
        mean=np.asarray([value[name]["mean"] for name in core.BASIS_NAMES], dtype=float),
        scale=np.asarray([value[name]["scale"] for name in core.BASIS_NAMES], dtype=float),
        degenerate=tuple(bool(value[name]["degenerate"]) for name in core.BASIS_NAMES),
        support_weight=tuple(float(value[name]["support_weight"]) for name in core.BASIS_NAMES),
    )


def race_pair_data(rows: pd.DataFrame, runner_stats: core.Standardization) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for race_id, race in rows.groupby("race_id", sort=True):
        race = race.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
        z, missing = core.transform_runners(race, runner_stats)
        p0_by_pair, _ = core.q0_from_scores(
            race["horse_number"].astype(int).tolist(), race["score"].astype(float).tolist()
        )
        pairs, basis, labels, p0 = core.enumerate_race_pairs(race, z, missing, p0_by_pair)
        result.append({
            "race_id": str(race_id),
            "race_date": race["race_date"].iloc[0].date().isoformat(),
            "evaluation_year": int(race["year"].iloc[0]),
            "rows": race,
            "pairs": pairs,
            "basis": basis,
            "labels": labels,
            "p0": p0,
        })
    require(bool(result), "empty race-pair data")
    return result


def flatten_races(races: list[dict[str, Any]], stats: core.PairStandardization) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x: list[np.ndarray] = []
    prior: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    race_ids: list[np.ndarray] = []
    for race in races:
        x.append(core.transform_pair_basis(race["basis"], stats))
        prior.append(race["p0"])
        labels.append(race["labels"])
        race_ids.append(np.full(len(race["pairs"]), race["race_id"], dtype=object))
    return np.vstack(x), np.concatenate(prior), np.concatenate(labels), np.concatenate(race_ids)


def optimizer_fields(result: Any) -> dict[str, Any]:
    return {
        "success": bool(result.success),
        "status": int(result.status),
        "message": str(result.message),
        "iterations": int(result.nit),
        "function_evaluations": int(result.nfev),
        "objective": float(result.fun),
        "gradient": [float(x) for x in result.jac],
        "gradient_inf_norm": float(np.max(np.abs(result.jac))),
    }


def h2_fit_entry(name: str, raw_logits: np.ndarray, labels: np.ndarray, race_ids: np.ndarray, races: list[dict[str, Any]]) -> dict[str, Any]:
    result = core.fit_platt(raw_logits, labels, race_ids)
    projected = core.projected_gradient(result.x, result.jac)
    boundary = [
        "lower" if value == bounds[0] else "upper" if value == bounds[1] else "interior"
        for value, bounds in zip(result.x, core.PLATT_BOUNDS, strict=True)
    ]
    return {
        "map": name,
        "raw_input_family": "candidate_eta" if name == "candidate" else "logit_p0",
        "A": float(result.x[0]),
        "B": float(result.x[1]),
        "bounds": {"A": list(core.PLATT_BOUNDS[0]), "B": list(core.PLATT_BOUNDS[1])},
        "boundary_status": {"A": boundary[0], "B": boundary[1]},
        "projected_gradient": [float(x) for x in projected],
        "projected_gradient_inf_norm": float(np.max(np.abs(projected))),
        **optimizer_fields(result),
        "h2_races": int(len(races)),
        "h2_dates": int(len({race["race_date"] for race in races})),
        "h2_pairs": int(len(labels)),
        "positive_pairs": int(labels.sum()),
    }


def fit_stage() -> None:
    preflight_receipt, artifact_hashes, lock_hash = verify_preflight()
    require(not H1_PATH.exists() and not H2_PATH.exists() and not FIT_RECEIPT_PATH.exists(), "fit outputs already exist; no retry is allowed")
    features = feature_rows((2023, 2024, 2025))
    fold_inputs: dict[int, tuple[pd.DataFrame, pd.DataFrame]] = {}
    calibration_hashes: dict[str, str] = {}
    for year in (2024, 2025, 2026):
        folder = f"jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_{year}"
        path = f"{folder}/calibration_scores.parquet"
        calibration_hashes[path] = sha256_file(checked(path))
        fold_inputs[year] = fold_calibration(year, features)

    approval = {
        "status": "CONDITIONAL_FIT_AUTHORIZATION_CONSUMED",
        "study": "20261011_pair_top3_direct_v1",
        "authorized_action": "Run exactly three fixed H1 fits and six fixed H2 positive-slope Platt fits once, conditional on the passing outcome-free preflight and C no-blocker review.",
        "authorizing_root_message": "Root approved the single prescribed 3 H1 + 6 H2 fits after the pinned structural preflight PASS and C no-blocker review; no retry; fit artifacts must be written before evaluation labels/metrics.",
        "structural_preflight_sha256": PRE_FLIGHT_HASH,
        "structural_preflight_status": preflight_receipt["status"],
        "structural_preflight_source_lock_sha256": lock_hash,
        "frozen_design_artifacts": artifact_hashes,
        "fit_runner_path": "jeju/research/20261011_pair_top3_direct_v1/fit.py",
        "fit_runner_sha256": sha256_file(Path(__file__).resolve()),
        "calibration_source_sha256": calibration_hashes,
        "fit_label_roles": "calibration_year_only",
        "same_fold_evaluation_labels_used_for_fit": False,
        "performance_metrics_computed": False,
        "runtime_versions": {"python": sys.version.split()[0], "numpy": np.__version__, "scipy": scipy.__version__},
    }
    # This write-once receipt pins the exact runner before any optimizer call.
    write_json_once(FIT_APPROVAL_PATH, approval)

    h1_rows: list[dict[str, Any]] = []
    h2_rows: list[dict[str, Any]] = []
    for year in (2024, 2025, 2026):
        h1, h2 = fold_inputs[year]
        runner_stats = core.fit_runner_standardization(h1, h1["race_id"].astype(str).to_numpy())
        h1_races_raw = race_pair_data(h1, runner_stats)
        pair_stats = core.fit_pair_standardization([race["basis"] for race in h1_races_raw])
        x_h1, p0_h1, y_h1, race_id_h1 = flatten_races(h1_races_raw, pair_stats)
        optimizer = core.fit_h1(np.zeros(20, dtype=float), x_h1, p0_h1, y_h1, race_id_h1)
        beta = np.asarray(optimizer.x, dtype=float)
        h1_races = len(h1_races_raw)
        require(int(y_h1.sum()) == 3 * h1_races, f"H1 positive pair count mismatch for {year}")
        h1_rows.append({
            "evaluation_year": year,
            "calibration_year": year - 1,
            "h1_source_sha256": {
                FEATURE_PATH: sha256_file(checked(FEATURE_PATH)),
                f"jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_{year}/calibration_scores.parquet": calibration_hashes[f"jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_{year}/calibration_scores.parquet"],
            },
            "h1_races": h1_races,
            "h1_dates": len({race["race_date"] for race in h1_races_raw}),
            "h1_pairs": int(len(y_h1)),
            "positive_pairs": int(y_h1.sum()),
            "runner_standardization": runner_stats_to_json(runner_stats),
            "pair_standardization": pair_stats_to_json(pair_stats),
            "beta_by_basis": {name: float(beta[index]) for index, name in enumerate(core.BASIS_NAMES)},
            "objective": float(optimizer.fun),
            "gradient_inf_norm": float(np.max(np.abs(optimizer.jac))),
            **optimizer_fields(optimizer),
        })

        h2_races = race_pair_data(h2, runner_stats)
        x_h2, p0_h2, y_h2, race_id_h2 = flatten_races(h2_races, pair_stats)
        candidate_logits = logit(p0_h2) + x_h2 @ beta
        baseline_logits = logit(p0_h2)
        candidate_map = h2_fit_entry("candidate", candidate_logits, y_h2, race_id_h2, h2_races)
        baseline_map = h2_fit_entry("baseline", baseline_logits, y_h2, race_id_h2, h2_races)
        require(candidate_map["h2_races"] == baseline_map["h2_races"], f"H2 calibration race mismatch for {year}")
        h2_rows.extend([
            {"evaluation_year": year, "calibration_year": year - 1, **candidate_map},
            {"evaluation_year": year, "calibration_year": year - 1, **baseline_map},
        ])

    h1_document = {
        "study": "20261011_pair_top3_direct_v1",
        "source_lock_sha256": lock_hash,
        "fit_approval_sha256": sha256_file(FIT_APPROVAL_PATH),
        "model": "symmetric_direct_pair_bce_ridge",
        "lambda": core.LAMBDA,
        "basis_names": list(core.BASIS_NAMES),
        "folds": h1_rows,
    }
    h2_document = {
        "study": "20261011_pair_top3_direct_v1",
        "fit_approval_sha256": sha256_file(FIT_APPROVAL_PATH),
        "calibration": "separate_race_equal_positive_slope_platt",
        "maxiter": 500,
        "ftol": 1e-12,
        "gtol": 1e-8,
        "fold_maps": h2_rows,
    }
    write_json_once(H1_PATH, h1_document)
    write_json_once(H2_PATH, h2_document)
    receipt = {
        "status": "PASS",
        "study": "20261011_pair_top3_direct_v1",
        "fit_approval_sha256": sha256_file(FIT_APPROVAL_PATH),
        "fit_runner_sha256": sha256_file(Path(__file__).resolve()),
        "source_lock_sha256": lock_hash,
        "source_sha256": preflight_receipt["source_sha256"],
        "h1_fit_sha256": sha256_file(H1_PATH),
        "h2_calibration_sha256": sha256_file(H2_PATH),
        "h1_fit_count": len(h1_rows),
        "h2_calibration_count": len(h2_rows),
        "fit_label_roles": "calibration_year_only",
        "same_fold_evaluation_labels_used_for_fit": False,
        "performance_metrics_computed": False,
        "optimizer_retry_count": 0,
    }
    write_json_once(FIT_RECEIPT_PATH, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


def load_fold_artifacts(year: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    h1 = json.loads(H1_PATH.read_text(encoding="utf-8"))
    h2 = json.loads(H2_PATH.read_text(encoding="utf-8"))
    fit_row = next(row for row in h1["folds"] if int(row["evaluation_year"]) == year)
    calibration = {row["map"]: row for row in h2["fold_maps"] if int(row["evaluation_year"]) == year}
    require(set(calibration) == {"candidate", "baseline"}, f"missing H2 calibration maps for {year}")
    return fit_row, calibration["candidate"], calibration["baseline"]


def prediction_stage() -> None:
    require(FIT_RECEIPT_PATH.is_file(), "fit receipt missing; run the authorized fit stage once first")
    fit_receipt = json.loads(FIT_RECEIPT_PATH.read_text(encoding="utf-8"))
    require(fit_receipt.get("status") == "PASS", "fit receipt is not PASS")
    require(fit_receipt.get("same_fold_evaluation_labels_used_for_fit") is False, "fit used same-fold evaluation labels")
    require(fit_receipt.get("fit_runner_sha256") == sha256_file(Path(__file__).resolve()), "fit runner changed after approval")
    require(sha256_file(H1_PATH) == fit_receipt.get("h1_fit_sha256"), "H1 fit artifact changed after receipt")
    require(sha256_file(H2_PATH) == fit_receipt.get("h2_calibration_sha256"), "H2 calibration artifact changed after receipt")
    require(not PREDICTION_PATH.exists() and not RACE_DIAGNOSTICS_PATH.exists(), "prediction outputs already exist; no retry allowed")
    _, artifact_hashes, lock_hash = verify_preflight()
    require(lock_hash == fit_receipt.get("source_lock_sha256"), "source lock changed after fit")

    features = feature_rows((2024, 2025, 2026))
    marginals = pd.read_csv(checked(MARGINAL_PATH), usecols=["api_record_id", "race_id", "horse_number", "saved_f1_style6_p_top3"])
    joint_marginals = pd.read_csv(checked(MARGINAL_PATH), usecols=["race_id", "horse_number", "candidate_joint_marginal"])
    axis = pd.read_csv(checked(PAIR_AXIS_PATH), usecols=["race_id", "race_date", "evaluation_year", "arm", "policy", "budget_k", "axis_horses"])
    axis = axis.loc[axis["budget_k"].eq(3)].copy()
    triples = pd.read_parquet(checked(TRIPLES_PATH), columns=["race_id", "distance_m", "arm"])
    candidate_distances = triples.loc[triples["arm"].eq("candidate"), ["race_id", "distance_m"]].drop_duplicates()
    require(not candidate_distances["race_id"].duplicated().any(), "duplicate race distance in candidate triples")
    distance_by_race = candidate_distances.set_index("race_id")["distance_m"].astype(int).to_dict()
    marginal_lookup = marginals.set_index(["race_id", "horse_number"])
    joint_marginal_lookup = joint_marginals.set_index(["race_id", "horse_number"])["candidate_joint_marginal"]
    axis_lookup = {
        (str(row.race_id), str(row.arm), str(row.policy)): preflight.parse_pair_text(row.axis_horses)
        for row in axis.itertuples(index=False)
        if str(row.policy) in {"top_two_marginal_pair", "maximum_joint_pair"}
    }
    eval_rows_by_year: dict[int, pd.DataFrame] = {}
    for year in (2024, 2025, 2026):
        folder = f"jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_{year}"
        scores = preflight.read_score(f"{folder}/evaluation_scores.parquet")
        rows = features.loc[features["year"].eq(year)].copy()
        eval_rows_by_year[year] = preflight.add_scores(rows, scores, f"{year} evaluation")

    all_pair_rows: list[dict[str, Any]] = []
    race_diagnostics: list[dict[str, Any]] = []
    for year, eval_rows in eval_rows_by_year.items():
        h1_row, candidate_cal, baseline_cal = load_fold_artifacts(year)
        runner_stats = runner_stats_from_json(h1_row["runner_standardization"])
        pair_stats = pair_stats_from_json(h1_row["pair_standardization"])
        beta = np.asarray([h1_row["beta_by_basis"][name] for name in core.BASIS_NAMES], dtype=float)
        eval_races = race_pair_data(eval_rows, runner_stats)
        for race in eval_races:
            race_id = race["race_id"]
            scores_by_number = {
                int(row.horse_number): float(row.score)
                for row in race["rows"].itertuples(index=False)
            }
            pairs = race["pairs"]
            x = core.transform_pair_basis(race["basis"], pair_stats)
            p0 = race["p0"]
            eta = logit(p0) + x @ beta
            candidate_raw = expit(eta)
            candidate_probability = expit(float(candidate_cal["A"]) + float(candidate_cal["B"]) * eta)
            baseline_probability = expit(float(baseline_cal["A"]) + float(baseline_cal["B"]) * logit(p0))
            selected_candidate = core.pair_choice_from_logits(pairs, eta)
            selected_baseline = core.pair_choice_from_logits(pairs, logit(p0))
            score_top2 = preflight.selected_pair_by_value(list(scores_by_number.items()))
            require(selected_baseline == score_top2, f"p0/raw Top2 mismatch after H1 fit for {race_id}")
            saved_style_pair = preflight.selected_pair_by_value([
                (int(number), float(marginal_lookup.loc[(race_id, int(number)), "saved_f1_style6_p_top3"]))
                for number in scores_by_number
            ])
            # Read selector pairs from the frozen axis artifact; the preflight
            # already reconstructed those selectors from the canonical source.
            candidate_joint_marginal_pair = axis_lookup[(race_id, "candidate", "top_two_marginal_pair")]
            candidate_joint_max_pair = axis_lookup[(race_id, "candidate", "maximum_joint_pair")]
            matched_joint_max_pair = axis_lookup[(race_id, "matched_baseline", "maximum_joint_pair")]
            selected_map = {
                "selected_candidate": selected_candidate,
                "selected_baseline": selected_baseline,
                "selected_raw_top2": score_top2,
                "selected_saved_f1_top2": saved_style_pair,
                "selected_candidate_joint_marginal_top2": candidate_joint_marginal_pair,
                "selected_candidate_joint_maxpair": candidate_joint_max_pair,
                "selected_matched_joint_maxpair": matched_joint_max_pair,
            }
            label_lookup = {pair: int(label) for pair, label in zip(pairs, race["labels"], strict=True)}
            date_text = race["race_date"]
            distance = int(distance_by_race[race_id])
            candidate_sum_delta = math.fsum(float(x) for x in candidate_probability) - 3.0
            baseline_sum_delta = math.fsum(float(x) for x in baseline_probability) - 3.0
            race_diagnostics.append({
                "race_id": race_id,
                "race_date": date_text,
                "evaluation_year": year,
                "distance_m": distance,
                "candidate_sum_calibrated_pair_probability_minus_3": candidate_sum_delta,
                "baseline_sum_calibrated_pair_probability_minus_3": baseline_sum_delta,
                "candidate_abs_sum_deviation": abs(candidate_sum_delta),
                "baseline_abs_sum_deviation": abs(baseline_sum_delta),
            })
            for index, (horse_i, horse_j) in enumerate(pairs):
                record = {
                    "race_id": race_id,
                    "race_date": date_text,
                    "evaluation_year": year,
                    "distance_m": distance,
                    "horse_i": int(horse_i),
                    "horse_j": int(horse_j),
                    "score_i": scores_by_number[int(horse_i)],
                    "score_j": scores_by_number[int(horse_j)],
                    "p0": float(p0[index]),
                    "eta": float(eta[index]),
                    "candidate_raw_probability": float(candidate_raw[index]),
                    "candidate_calibrated_probability": float(candidate_probability[index]),
                    "baseline_calibrated_probability": float(baseline_probability[index]),
                    "y_pair": int(label_lookup[(horse_i, horse_j)]),
                }
                for selector_name, selector_pair in selected_map.items():
                    record[selector_name] = int((horse_i, horse_j) == selector_pair)
                all_pair_rows.append(record)

    predictions = pd.DataFrame(all_pair_rows, columns=PREDICTION_COLUMNS)
    diagnostics = pd.DataFrame(race_diagnostics)
    require(len(diagnostics) == 1779 and diagnostics["race_id"].nunique() == 1779, "evaluation race coverage changed")
    require(len(predictions) == sum(math.comb(int(n), 2) for n in features.loc[features["year"].isin((2024, 2025, 2026))].groupby("race_id")["field_n"].first()), "evaluation pair coverage changed")
    require(not predictions.duplicated(["race_id", "horse_i", "horse_j"]).any(), "duplicate evaluation pair")
    require((predictions.groupby("race_id")["y_pair"].sum() == 3).all(), "evaluation pair labels not exactly three positives per race")
    require((predictions.groupby("race_id")["selected_candidate"].sum() == 1).all(), "candidate must select exactly one pair per race")
    require((predictions.groupby("race_id")["selected_baseline"].sum() == 1).all(), "baseline must select exactly one pair per race")
    require(np.isfinite(predictions.select_dtypes(include=[np.number]).to_numpy(dtype=float)).all(), "non-finite evaluation pair artifact")
    require(((predictions["candidate_calibrated_probability"] >= 0) & (predictions["candidate_calibrated_probability"] <= 1)).all(), "candidate calibrated probability outside [0,1]")
    require(((predictions["baseline_calibrated_probability"] >= 0) & (predictions["baseline_calibrated_probability"] <= 1)).all(), "baseline calibrated probability outside [0,1]")
    # The positive Platt slopes preserve ordering; verify chosen pairs agree.
    for _, group in predictions.groupby("race_id", sort=True):
        chosen = group.loc[group["selected_candidate"].eq(1)].iloc[0]
        require(chosen["candidate_calibrated_probability"] == group["candidate_calibrated_probability"].max(), "candidate raw/calibrated selector parity failed")
        base = group.loc[group["selected_baseline"].eq(1)].iloc[0]
        require(base["baseline_calibrated_probability"] == group["baseline_calibrated_probability"].max(), "baseline raw/calibrated selector parity failed")

    OUT.mkdir(parents=True, exist_ok=True)
    require(not PREDICTION_PATH.exists() and not RACE_DIAGNOSTICS_PATH.exists(), "refusing to overwrite evaluation outputs")
    temp_predictions = PREDICTION_PATH.with_suffix(".parquet.tmp")
    temp_diagnostics = RACE_DIAGNOSTICS_PATH.with_suffix(".parquet.tmp")
    require(not temp_predictions.exists() and not temp_diagnostics.exists(), "temporary prediction output already exists")
    predictions.to_parquet(temp_predictions, index=False)
    diagnostics.to_parquet(temp_diagnostics, index=False)
    temp_predictions.replace(PREDICTION_PATH)
    temp_diagnostics.replace(RACE_DIAGNOSTICS_PATH)
    prediction_receipt = {
        "status": "PASS",
        "study": "20261011_pair_top3_direct_v1",
        "fit_receipt_sha256": sha256_file(FIT_RECEIPT_PATH),
        "fit_runner_sha256": sha256_file(Path(__file__).resolve()),
        "source_lock_sha256": lock_hash,
        "frozen_design_artifacts": artifact_hashes,
        "prediction_rows": int(len(predictions)),
        "prediction_races": int(predictions["race_id"].nunique()),
        "prediction_schema": {column: str(dtype) for column, dtype in predictions.dtypes.items()},
        "race_probability_diagnostics_sha256": sha256_file(RACE_DIAGNOSTICS_PATH),
        "evaluation_pair_predictions_sha256": sha256_file(PREDICTION_PATH),
        "performance_metrics_computed": False,
    }
    write_json_once(OUT / "prediction_receipt.json", prediction_receipt)
    print(json.dumps(prediction_receipt, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("fit", "predict"))
    args = parser.parse_args()
    try:
        if args.stage == "fit":
            fit_stage()
        else:
            prediction_stage()
        return 0
    except Exception as error:
        print(f"FIT_RUN_FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
