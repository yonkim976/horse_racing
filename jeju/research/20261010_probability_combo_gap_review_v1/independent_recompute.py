"""Independent saved-score reconstruction for the F1 / F1_STYLE6 gap review.

This reads only frozen research outputs and writes only this review directory.
It does not call the original evaluator, load a model, fit, tune tau, query a DB,
or contact a network service.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import logsumexp


ROOT = Path(__file__).resolve().parents[3]
OWN = Path(__file__).resolve().parent
OUT = OWN / "outputs"
ABLA = ROOT / "jeju/research/20261010_style_history_ablation_v1"
AB_OUT = ABLA / "outputs"
BASE = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
BASE_OUT = BASE / "outputs"
BASE_MANIFEST_PATH = BASE / "ARTIFACT_MANIFEST.json"
SOURCE = ROOT / "jeju/research/20261010_style_history_source_audit_v1"
PLAN_PATH = ROOT / "jeju/research/20261010_probability_combo_gap_v1/PLAN.md"
CONTRACT_PATH = ROOT / "jeju/research/20261010_probability_combo_gap_v1/data_contract.json"

APPROVED_PLAN_SHA256 = "09cb2d20554f2f98a7f9aeaef21b722f86e544e46e904d1b7d80278ab086d4d4"
APPROVED_CONTRACT_SHA256 = "7ea6ba197c76e1f83dd73e3dc84939704261695733e93b55dfbb45539d3c018d"
YEARS = (2024, 2025, 2026)
VARIANTS = ("F1", "F1_STYLE6")
TOP_K = (1, 3, 6, 10, 20)
METRIC_ATOL = 1e-12
BOOTSTRAP_REPS = 2000
BOOTSTRAP_SEED = 20261008


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_root_path(relative: str) -> Path:
    candidate = Path(relative)
    assert not candidate.is_absolute(), relative
    resolved = (ROOT / candidate).resolve()
    assert resolved.is_relative_to(ROOT.resolve()), relative
    return resolved


def verify_digest(path: Path, expected: str, label: str) -> dict:
    assert path.is_file(), f"missing locked input: {label}"
    actual = sha256(path)
    assert actual == expected, f"SHA-256 mismatch: {label}"
    return {"path": str(path.relative_to(ROOT)), "sha256": actual,
            "bytes": int(path.stat().st_size)}


def verify_inputs() -> dict:
    assert sha256(PLAN_PATH) == APPROVED_PLAN_SHA256, "approved PLAN changed"
    assert sha256(CONTRACT_PATH) == APPROVED_CONTRACT_SHA256, "approved contract changed"
    manifest_path = ABLA / "ARTIFACT_MANIFEST.json"
    lock_path = AB_OUT / "prepared_lock.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base_manifest = json.loads(BASE_MANIFEST_PATH.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert manifest["prepared_lock_sha256"] == sha256(lock_path)

    checked = []
    for relative, expected in lock.get("references", {}).items():
        checked.append(verify_digest(safe_root_path(relative), expected,
                                     f"prepared reference {relative}"))
    for relative, info in lock.get("protected", {}).items():
        path = safe_root_path(relative)
        row = verify_digest(path, info["sha256"], f"protected source {relative}")
        assert row["bytes"] == int(info["bytes"]), f"protected size mismatch: {relative}"
        checked.append(row)
    for name, expected in lock.get("artifacts", {}).items():
        path = AB_OUT / name
        checked.append(verify_digest(path, expected, f"prepared artifact {name}"))
    source_paths = {
        "source_audit.json": SOURCE / "source_audit.json",
        "api4_full_started_point_quality_cache.parquet":
            SOURCE / "api4_full_started_point_quality_cache.parquet",
        "actual_slot_point_eligibility.parquet": SOURCE / "actual_slot_point_eligibility.parquet",
    }
    for name, expected in lock.get("source_cache_hashes", {}).items():
        assert name in source_paths, f"unknown locked cache: {name}"
        checked.append(verify_digest(source_paths[name], expected, f"source cache {name}"))

    manifest_entries = manifest["study_artifacts"]
    explicit_paths = [
        AB_OUT / "f1_reproduced_runner_predictions.parquet",
        AB_OUT / "f1_reproduced_race_metrics.csv",
        AB_OUT / "f1_reproduced_six_combinations.csv",
        AB_OUT / "candidate_scores_fit_stage.parquet",
        AB_OUT / "report" / "runner_predictions.parquet",
        AB_OUT / "report" / "race_metrics.parquet",
        AB_OUT / "report" / "canonical_six_combinations.csv",
        AB_OUT / "report" / "report_receipt.json",
        AB_OUT / "f1_replay_verification.json",
        AB_OUT / "final_verification.json",
    ]
    for year in YEARS:
        explicit_paths.extend([
            AB_OUT / f"F1_STYLE6_{year}" / "evaluation_scores.parquet",
            AB_OUT / f"F1_STYLE6_{year}" / "meta.json",
            AB_OUT / f"F1_STYLE6_{year}" / "top3.txt",
        ])
    for path in explicit_paths:
        relative = str(path.relative_to(ROOT))
        entry = manifest_entries.get(relative)
        assert entry is not None, f"missing manifest entry: {relative}"
        row = verify_digest(path, entry["sha256"], f"manifest artifact {relative}")
        assert row["bytes"] == int(entry["bytes"]), f"manifest size mismatch: {relative}"
        checked.append(row)
    for year in YEARS:
        for suffix in ("meta.json", "top3.txt"):
            relative = f"outputs/F1_{year}/{suffix}"
            entry = base_manifest["local_files"].get(relative)
            assert entry is not None, f"missing baseline manifest entry: {relative}"
            path = BASE / relative
            row = verify_digest(path, entry["sha256"], f"baseline artifact {relative}")
            assert row["bytes"] == int(entry["bytes"]), f"baseline size mismatch: {relative}"
            checked.append(row)

    report_receipt = json.loads((AB_OUT / "report/report_receipt.json").read_text(encoding="utf-8"))
    for filename, expected in report_receipt["report_artifacts"].items():
        checked.append(verify_digest(AB_OUT / "report" / filename, expected,
                                     f"report artifact {filename}"))
    replay = json.loads((AB_OUT / "f1_replay_verification.json").read_text(encoding="utf-8"))
    assert replay.get("passed") is True
    assert replay.get("runner_rows_reproduced") == 17412
    assert replay.get("distinct_races_reproduced") == 1779
    assert replay.get("canonical_six_combination_rows_reproduced") == 10674
    return {
        "approved_plan_sha256": APPROVED_PLAN_SHA256,
        "approved_data_contract_sha256": APPROVED_CONTRACT_SHA256,
        "prepared_lock_sha256": sha256(lock_path),
        "artifact_manifest_sha256": sha256(manifest_path),
        "baseline_artifact_manifest_sha256": sha256(BASE_MANIFEST_PATH),
        "checked_locked_file_references": len(checked),
        "verified_inputs": checked,
        "database_query_performed": False,
        "model_loaded": False,
        "fit_calls": 0,
        "tau_optimization_calls": 0,
    }


def as_horse_key(values) -> tuple[str, ...]:
    return tuple(str(value) for value in values)


def evaluate_race(frame: pd.DataFrame, scores: np.ndarray, tau: float,
                  variant: str) -> tuple[dict, list[dict], list[dict], list[dict], dict]:
    frame = frame.reset_index(drop=True)
    scores = np.asarray(scores, dtype=np.float64)
    n = len(frame)
    assert n >= 6
    assert len(scores) == n and np.isfinite(scores).all()
    assert frame.horse_number.is_monotonic_increasing
    assert frame.horse_id.astype(str).is_unique
    assert float(tau) > 0 and np.isfinite(tau)

    triples = np.asarray(list(itertools.combinations(range(n), 3)), dtype=np.int64)
    # Keep the source evaluator's sorted-score row reduction exactly.
    energies = np.sort(scores[triples], axis=1).sum(axis=1)
    log_q_saved = energies / float(tau) - logsumexp(energies / float(tau))
    q_saved = np.exp(log_q_saved)
    log_q_tau1 = energies - logsumexp(energies)
    q_tau1 = np.exp(log_q_tau1)
    assert np.isclose(q_saved.sum(), 1.0, rtol=0, atol=1e-12)
    assert np.isclose(q_tau1.sum(), 1.0, rtol=0, atol=1e-12)

    marginals_saved = np.zeros(n, dtype=np.float64)
    marginals_tau1 = np.zeros(n, dtype=np.float64)
    for index, triple in enumerate(triples):
        marginals_saved[triple] += q_saved[index]
        marginals_tau1[triple] += q_tau1[index]
    assert np.isclose(marginals_saved.sum(), 3.0, rtol=0, atol=1e-10)
    assert np.isclose(marginals_tau1.sum(), 3.0, rtol=0, atol=1e-10)

    y = frame.y.to_numpy(dtype=np.int64)
    assert set(np.unique(y)).issubset({0, 1}) and int(y.sum()) == 3
    truth_indices = np.flatnonzero(y == 1)
    truth_tuple = tuple(int(v) for v in truth_indices)
    truth_mask = (triples == np.asarray(truth_tuple, dtype=np.int64)).all(axis=1)
    assert int(truth_mask.sum()) == 1
    truth_index = int(np.flatnonzero(truth_mask)[0])

    rank_order = np.argsort(-energies, kind="stable")
    # Use the contract's explicit scaled-energy order. Sorting log-q first
    # subtracts a normalizer and could introduce avoidable rounding ties.
    scaled_tau_order = np.argsort(-(energies / float(tau)), kind="stable")
    tau1_order = np.argsort(-energies, kind="stable")
    rank_position = np.empty(len(energies), dtype=np.int64)
    rank_position[rank_order] = np.arange(1, len(energies) + 1)
    scaled_tau_position = np.empty(len(energies), dtype=np.int64)
    scaled_tau_position[scaled_tau_order] = np.arange(1, len(energies) + 1)
    tau1_position = np.empty(len(energies), dtype=np.int64)
    tau1_position[tau1_order] = np.arange(1, len(energies) + 1)
    top6 = rank_order[:6]
    scaled_tau_top6_mismatch = set(rank_order[:6]) != set(scaled_tau_order[:6])
    tau1_top6_mismatch = set(rank_order[:6]) != set(tau1_order[:6])

    tie_counts = Counter(float(value) for value in energies)
    tie_size_by_energy = tie_counts
    exact_tie_groups = sum(1 for count in tie_counts.values() if count > 1)
    tied_triple_rows = sum(count for count in tie_counts.values() if count > 1)
    truth_rank = int(rank_position[truth_index])
    truth_energy = float(energies[truth_index])
    truth_tie_size = int(tie_size_by_energy[truth_energy])

    p_saved_order_violations = 0
    p_tau1_order_violations = 0
    for i in range(n):
        for j in range(i + 1, n):
            score_delta = scores[i] - scores[j]
            saved_delta = marginals_saved[i] - marginals_saved[j]
            tau1_delta = marginals_tau1[i] - marginals_tau1[j]
            if score_delta == 0:
                p_saved_order_violations += int(abs(saved_delta) > METRIC_ATOL)
                p_tau1_order_violations += int(abs(tau1_delta) > METRIC_ATOL)
            else:
                p_saved_order_violations += int(score_delta * saved_delta < 0 and abs(saved_delta) > METRIC_ATOL)
                p_tau1_order_violations += int(score_delta * tau1_delta < 0 and abs(tau1_delta) > METRIC_ATOL)

    clipped_saved = np.clip(marginals_saved, 1e-12, 1 - 1e-12)
    clipped_tau1 = np.clip(marginals_tau1, 1e-12, 1 - 1e-12)
    ll_saved = -y * np.log(clipped_saved) - (1 - y) * np.log1p(-clipped_saved)
    br_saved = (marginals_saved - y) ** 2
    ll_tau1 = -y * np.log(clipped_tau1) - (1 - y) * np.log1p(-clipped_tau1)
    br_tau1 = (marginals_tau1 - y) ** 2
    joint_brier_saved = float(np.square(q_saved).sum() - 2 * q_saved[truth_index] + 1)
    joint_brier_tau1 = float(np.square(q_tau1).sum() - 2 * q_tau1[truth_index] + 1)

    horse_ids = frame.horse_id.astype(str).to_numpy()
    horse_numbers = frame.horse_number.to_numpy(dtype=np.int64)
    triple_records = []
    ticket_records = []
    for order_rank, triple_index in enumerate(rank_order, start=1):
        triple = triples[triple_index]
        triple_ids = as_horse_key(horse_ids[triple])
        triple_numbers = tuple(int(v) for v in horse_numbers[triple])
        triple_records.append({
            "race_id": str(frame.race_id.iloc[0]),
            "variant": variant,
            "triple_horse_ids": ",".join(triple_ids),
            "triple_numbers": ",".join(str(v) for v in triple_numbers),
            "triple_energy": float(energies[triple_index]),
            "joint_probability_saved_tau": float(q_saved[triple_index]),
            "joint_probability_tau1": float(q_tau1[triple_index]),
            "stable_rank": int(order_rank),
            "rank_after_saved_tau": int(scaled_tau_position[triple_index]),
            "rank_after_tau1": int(tau1_position[triple_index]),
            "exact_energy_tie_size": int(tie_size_by_energy[float(energies[triple_index])]),
            "is_truth": bool(triple_index == truth_index),
        })
    for selection_rank, triple_index in enumerate(top6, start=1):
        triple = triples[triple_index]
        ticket_records.append({
            "race_id": str(frame.race_id.iloc[0]),
            "variant": variant,
            "selection_rank": selection_rank,
            "numbers": ",".join(str(int(horse_numbers[k])) for k in triple),
            "horse_ids": ",".join(str(horse_ids[k]) for k in triple),
            "probability": float(q_saved[triple_index]),
            "probability_tau1": float(q_tau1[triple_index]),
            "hit": int(triple_index == truth_index),
        })

    truth_horse_ids = as_horse_key(horse_ids[truth_indices])
    six_mass_saved = float(q_saved[top6].sum())
    six_mass_tau1 = float(q_tau1[top6].sum())
    race = {
        "race_id": str(frame.race_id.iloc[0]),
        "race_date": str(frame.race_date.iloc[0]),
        "year": int(frame.year.iloc[0]),
        "distance_m": int(frame.distance_m.iloc[0]),
        "variant": variant,
        "field_n": n,
        "saved_tau": float(tau),
        "true_triple_rank": truth_rank,
        "true_rank_after_saved_tau": int(scaled_tau_position[truth_index]),
        "true_rank_after_tau1": int(tau1_position[truth_index]),
        "true_triple_energy": truth_energy,
        "sixth_seventh_energy_gap": float(energies[rank_order[5]] - energies[rank_order[6]]),
        "true_triple_tie_size": truth_tie_size,
        "hit_at_1": int(truth_rank <= 1),
        "hit_at_3": int(truth_rank <= 3),
        "hit_at_6": int(truth_rank <= 6),
        "hit_at_10": int(truth_rank <= 10),
        "hit_at_20": int(truth_rank <= 20),
        "joint_true_nll_saved_tau": float(-log_q_saved[truth_index]),
        "full_joint_brier_saved_tau": joint_brier_saved,
        "top3_marginal_log_loss_saved_tau": float(ll_saved.mean()),
        "top3_marginal_brier_saved_tau": float(br_saved.mean()),
        "joint_true_nll_tau1": float(-log_q_tau1[truth_index]),
        "full_joint_brier_tau1": joint_brier_tau1,
        "top3_marginal_log_loss_tau1": float(ll_tau1.mean()),
        "top3_marginal_brier_tau1": float(br_tau1.mean()),
        "six_mass_saved_tau": six_mass_saved,
        "six_mass_tau1": six_mass_tau1,
        "six_mass_brier_saved_tau": float((six_mass_saved - int(truth_rank <= 6)) ** 2),
        "six_hit": int(truth_rank <= 6),
        "scaled_tau_rank_mismatch_n": int(np.count_nonzero(
            rank_position != scaled_tau_position)),
        "scaled_tau_top6_mismatch": bool(scaled_tau_top6_mismatch),
        "tau1_rank_mismatch_n": int(np.count_nonzero(rank_position != tau1_position)),
        "tau1_top6_mismatch": bool(tau1_top6_mismatch),
        "p_top3_saved_tau_score_order_violations": int(p_saved_order_violations),
        "p_top3_tau1_score_order_violations": int(p_tau1_order_violations),
        "exact_energy_tie_groups": int(exact_tie_groups),
        "tied_triple_rows": int(tied_triple_rows),
        "max_exact_energy_tie_size": int(max(tie_counts.values())),
        "exact_tie_counts": json.dumps(
            {str(size): sum(1 for count in tie_counts.values() if count == size)
             for size in sorted(set(tie_counts.values())) if size > 1},
            sort_keys=True, separators=(",", ":")),
    }
    runners = []
    for index, row in enumerate(frame.itertuples(index=False)):
        runners.append({
            "api_record_id": int(row.api_record_id),
            "race_id": str(row.race_id), "race_date": str(row.race_date),
            "year": int(row.year), "distance_m": int(row.distance_m),
            "horse_id": str(row.horse_id), "horse_number": int(row.horse_number),
            "variant": variant, "score": float(scores[index]),
            "field_n": n,
            "p_top3_saved_tau": float(marginals_saved[index]),
            "p_top3_tau1": float(marginals_tau1[index]), "y": int(y[index]),
            "log_loss_saved_tau": float(ll_saved[index]),
            "brier_saved_tau": float(br_saved[index]),
            "log_loss_tau1": float(ll_tau1[index]),
            "brier_tau1": float(br_tau1[index]),
        })
    summary = {
        "race": race,
        "runners": runners,
        "tickets": ticket_records,
        "triples": triple_records,
        "top6_keys": {tuple(record["horse_ids"].split(",")) for record in ticket_records},
        "top6_ids": {str(v) for record in ticket_records for v in record["horse_ids"].split(",")},
        "truth_ids": set(truth_horse_ids),
    }
    return race, runners, ticket_records, triple_records, summary


def load_data() -> tuple[pd.DataFrame, dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    f1_path = AB_OUT / "f1_reproduced_runner_predictions.parquet"
    baseline = pd.read_parquet(f1_path)
    baseline = baseline.loc[baseline.variant.eq("F1")].copy()
    assert len(baseline) == 17412 and baseline.api_record_id.is_unique
    baseline["horse_id"] = baseline.horse_id.astype(str)
    baseline["race_id"] = baseline.race_id.astype(str)
    baseline["y"] = baseline.y.astype(np.int64)
    baseline["horse_number"] = baseline.horse_number.astype(np.int64)
    assert baseline.groupby("race_id", sort=False).y.sum().eq(3).all()
    assert baseline.race_id.nunique() == 1779
    assert baseline.race_date.nunique() == 269
    assert set(baseline.year.astype(int).unique()) == set(YEARS)
    assert not baseline.duplicated(["race_id", "horse_id"]).any()
    assert not baseline.duplicated(["race_id", "horse_number"]).any()
    assert baseline.groupby("race_id", sort=False).year.nunique().eq(1).all()
    assert baseline.groupby("race_id", sort=False).race_date.nunique().eq(1).all()
    assert baseline.groupby("race_id", sort=False).distance_m.nunique().eq(1).all()
    for _, roster in baseline.groupby("race_id", sort=False):
        assert roster.horse_number.sort_values(kind="stable").is_monotonic_increasing

    saved_report_tickets = pd.read_csv(AB_OUT / "report/canonical_six_combinations.csv")
    saved_report_runners = pd.read_parquet(AB_OUT / "report/runner_predictions.parquet")
    saved_report_races = pd.read_parquet(AB_OUT / "report/race_metrics.parquet")
    tau_by_year = {}
    score_by_variant_year = {}
    for year in YEARS:
        f1_meta = json.loads((BASE_OUT / f"F1_{year}/meta.json").read_text(encoding="utf-8"))
        style_meta = json.loads((AB_OUT / f"F1_STYLE6_{year}/meta.json").read_text(encoding="utf-8"))
        assert int(style_meta["evaluation_year"]) == year
        f1_model = BASE_OUT / f"F1_{year}/top3.txt"
        style_model = AB_OUT / f"F1_STYLE6_{year}/top3.txt"
        assert sha256(f1_model) == f1_meta["model_sha256"]
        assert sha256(style_model) == style_meta["model_sha256"]
        f1_tau = float(f1_meta["tau"])
        style_tau = float(style_meta["tau"])
        assert f1_tau > 0 and style_tau > 0
        tau_by_year[("F1", year)] = f1_tau
        tau_by_year[("F1_STYLE6", year)] = style_tau
        score_path = AB_OUT / f"F1_STYLE6_{year}/evaluation_scores.parquet"
        assert sha256(score_path) == style_meta["evaluation_scores_sha256"]
        candidate = pd.read_parquet(score_path)
        assert list(candidate.columns) == ["api_record_id", "score"]
        assert candidate.api_record_id.is_unique
        candidate["api_record_id"] = candidate.api_record_id.astype(np.int64)
        candidate["score"] = candidate.score.astype(np.float64)
        baseline_year = baseline.loc[baseline.year.eq(year)]
        assert set(candidate.api_record_id) == set(baseline_year.api_record_id)
        score_by_variant_year[("F1_STYLE6", year)] = candidate.set_index("api_record_id").score
    report_tickets = saved_report_tickets.copy()
    report_runners = saved_report_runners.copy()
    return (baseline, {"tau": tau_by_year, "candidate_scores": score_by_variant_year},
            report_tickets, report_runners, saved_report_races)


def assert_frame_numeric(saved: pd.DataFrame, calculated: pd.DataFrame,
                         keys: list[str], numeric: list[str], strings: list[str]) -> None:
    left = saved.sort_values(keys, kind="stable").reset_index(drop=True)
    right = calculated.sort_values(keys, kind="stable").reset_index(drop=True)
    assert len(left) == len(right), (len(left), len(right))
    for column in keys + strings:
        a = left[column].fillna("<NA>").astype(str)
        b = right[column].fillna("<NA>").astype(str)
        assert a.equals(b), f"saved parity mismatch: {column}"
    for column in numeric:
        a = pd.to_numeric(left[column], errors="coerce").to_numpy(dtype=np.float64)
        b = pd.to_numeric(right[column], errors="coerce").to_numpy(dtype=np.float64)
        assert np.allclose(a, b, rtol=0, atol=METRIC_ATOL, equal_nan=True), column


def build_results(baseline: pd.DataFrame, inputs: dict) -> tuple[list, list, list, list, list, dict]:
    race_rows: list[dict] = []
    runner_rows: list[dict] = []
    ticket_rows: list[dict] = []
    triple_rows: list[dict] = []
    race_models: dict[str, dict] = {}
    per_race_frames = {str(race_id): group.sort_values(
        "horse_number", kind="stable").reset_index(drop=True)
        for race_id, group in baseline.groupby("race_id", sort=False)}

    for race_id, frame in per_race_frames.items():
        assert frame.horse_number.is_monotonic_increasing
        race_models[race_id] = {}
        for variant in VARIANTS:
            year = int(frame.year.iloc[0])
            if variant == "F1":
                scores = frame.score.to_numpy(dtype=np.float64)
            else:
                series = inputs["candidate_scores"][(variant, year)]
                scores = frame.api_record_id.map(series).to_numpy(dtype=np.float64)
                assert np.isfinite(scores).all(), f"missing candidate score: {race_id}"
            tau = inputs["tau"][(variant, year)]
            race, runners, tickets, triples, summary = evaluate_race(frame, scores, tau, variant)
            race_rows.append(race)
            runner_rows.extend(runners)
            ticket_rows.extend(tickets)
            triple_rows.extend(triples)
            race_models[race_id][variant] = summary

    pair_rows = []
    for race_id, variants in race_models.items():
        f1 = variants["F1"]
        style = variants["F1_STYLE6"]
        f1_hit = bool(f1["race"]["six_hit"])
        style_hit = bool(style["race"]["six_hit"])
        if f1_hit and style_hit:
            hit_pair = "hit_both"
        elif f1_hit:
            hit_pair = "F1_only"
        elif style_hit:
            hit_pair = "STYLE6_only"
        else:
            hit_pair = "neither"
        overlap_n = len(f1["top6_keys"] & style["top6_keys"])
        changed = overlap_n != 6
        assert 0 <= overlap_n <= 6
        assert 12 - 2 * overlap_n == len(f1["top6_keys"] ^ style["top6_keys"])
        for variant in VARIANTS:
            own = variants[variant]
            other = variants["F1_STYLE6" if variant == "F1" else "F1"]
            all3_in_union = own["truth_ids"].issubset(own["top6_ids"])
            if own["race"]["six_hit"]:
                union_state = "hit"
            elif all3_in_union:
                union_state = "allocation_miss"
            else:
                union_state = "union_miss"
            assert (union_state == "hit") == bool(own["race"]["six_hit"])
            own_union_ids = sorted(own["top6_ids"])
            other_union_ids = sorted(other["top6_ids"])
            pair_rows.append({
                "race_id": race_id, "variant": variant,
                "race_date": own["race"]["race_date"],
                "year": own["race"]["year"],
                "distance_m": own["race"]["distance_m"],
                "ticket_overlap_n": overlap_n,
                "ticket_symmetric_difference_n": 12 - 2 * overlap_n,
                "ticket_changed": "changed" if changed else "unchanged",
                "hit_both_or_only_or_neither": hit_pair,
                "own_six_horse_union_n": len(own["top6_ids"]),
                "own_six_horse_union_ids": ",".join(own_union_ids),
                "other_union_overlap_n": len(own["top6_ids"] & other["top6_ids"]),
                "own_only_union_horse_ids": ",".join(sorted(own["top6_ids"] - other["top6_ids"])),
                "other_only_union_horse_ids": ",".join(sorted(other["top6_ids"] - own["top6_ids"])),
                "all3inU6_v": int(all3_in_union),
                "union_state": union_state,
            })
    return race_rows, runner_rows, ticket_rows, triple_rows, pair_rows, race_models


def parity_checks(baseline: pd.DataFrame, inputs: dict, races: list[dict],
                  runners: list[dict], tickets: list[dict], saved_tickets: pd.DataFrame,
                  saved_runners: pd.DataFrame, saved_report_races: pd.DataFrame) -> dict:
    race_frame = pd.DataFrame(races)
    runner_frame = pd.DataFrame(runners)
    ticket_frame = pd.DataFrame(tickets)
    assert len(race_frame) == 3558 and race_frame.race_id.nunique() == 1779
    assert race_frame.groupby("variant").size().to_dict() == {"F1": 1779, "F1_STYLE6": 1779}
    assert len(runner_frame) == 34824
    assert len(ticket_frame) == 21348
    assert ticket_frame.groupby("variant").size().to_dict() == {"F1": 10674, "F1_STYLE6": 10674}

    for variant in VARIANTS:
        calculated_tickets = ticket_frame.loc[ticket_frame.variant.eq(variant)].copy()
        expected_tickets = saved_tickets.loc[saved_tickets.variant.eq(variant)].copy()
        assert_frame_numeric(expected_tickets, calculated_tickets,
            ["race_id", "selection_rank"], ["probability", "hit"], ["numbers"])
        calculated_runners = runner_frame.loc[runner_frame.variant.eq(variant)].copy()
        expected_runners = saved_runners.loc[saved_runners.variant.eq(variant)].copy()
        expected_runners = expected_runners.rename(columns={"p_top3": "p_top3_saved_tau"})
        if variant == "F1_STYLE6":
            assert_frame_numeric(expected_runners, calculated_runners,
                ["api_record_id"], ["score", "p_top3_saved_tau", "y"], ["race_id", "horse_id"])
        else:
            assert_frame_numeric(expected_runners, calculated_runners,
                ["api_record_id"], ["score", "p_top3_saved_tau", "y"], ["race_id", "horse_id"])

    replay = pd.read_parquet(AB_OUT / "f1_reproduced_runner_predictions.parquet")
    f1_report_rows = saved_runners.loc[saved_runners.variant.eq("F1")]
    replay_f1 = replay.loc[replay.variant.eq("F1")]
    assert_frame_numeric(replay_f1, f1_report_rows,
        ["api_record_id"], ["score", "p_top3", "y"], ["race_id", "horse_id"])
    calculated_races = pd.DataFrame(races)
    for variant in VARIANTS:
        expected = saved_report_races.loc[saved_report_races.variant.eq(variant)].copy()
        calculated = calculated_races.loc[calculated_races.variant.eq(variant)].copy()
        calculated["six_combo_mass"] = calculated.six_mass_saved_tau
        calculated["six_combo_hit"] = calculated.six_hit
        assert_frame_numeric(expected, calculated,
            ["race_id"], ["six_combo_mass", "six_combo_hit"], ["race_date"])
    return {
        "race_rows": len(race_frame), "runner_rows": len(runner_frame),
        "canonical_ticket_rows": len(ticket_frame),
        "f1_canonical_ticket_parity": True,
        "style6_canonical_ticket_parity": True,
        "f1_runner_raw_score_and_marginal_parity": True,
        "style6_runner_raw_score_and_marginal_parity": True,
        "all_race_joint_probability_sums_one": True,
        "all_race_marginal_sums_three": True,
        "canonical_order_and_probabilities_match_atol_1e-12": True,
        "saved_six_mass_and_hit_match_atol_1e-12": True,
        "temperature_order_and_six_invariant": True,
        "saved_replay_roster_label_parity": True,
    }


def build_loss_contributions(runners: list[dict], ticket_rows: list[dict],
                             pair_rows: list[dict], race_rows: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    runner_frame = pd.DataFrame(runners)
    tickets = pd.DataFrame(ticket_rows)
    pairs = pd.DataFrame(pair_rows)
    races = pd.DataFrame(race_rows)
    top6_sets = {
        (variant, race_id): set(group.sort_values("selection_rank").horse_ids)
        for (variant, race_id), group in tickets.groupby(["variant", "race_id"], sort=False)
    }
    changed_by_race = {
        race_id: ("unchanged" if top6_sets[("F1", race_id)] == top6_sets[("F1_STYLE6", race_id)] else "changed")
        for race_id in runner_frame.race_id.unique().tolist()
    }
    runner_frame["ticket_changed"] = runner_frame.race_id.map(changed_by_race)
    runner_frame["outcome_group"] = np.where(runner_frame.y.eq(1), "top3", "other")
    runner_counts = runner_frame.groupby(["variant", "race_id", "outcome_group"], sort=False).size()
    race_sizes = runner_frame.groupby(["variant", "race_id"], sort=False).field_n.first()
    for (variant, race_id), field_n in race_sizes.items():
        assert int(runner_counts.loc[(variant, race_id, "top3")]) == 3
        assert int(runner_counts.loc[(variant, race_id, "other")]) == int(field_n) - 3
    runner_frame = runner_frame.merge(
        pairs[["race_id", "variant", "hit_both_or_only_or_neither", "union_state",
               "own_six_horse_union_n"]],
        on=["race_id", "variant"], how="left", validate="many_to_one")

    contribution_rows = []
    cross_rows = []
    base_keys = ["variant", "race_id", "race_date", "year", "distance_m", "ticket_changed",
                 "hit_both_or_only_or_neither", "union_state", "own_six_horse_union_n", "field_n"]
    for metric, column in (("log_loss", "log_loss_saved_tau"), ("brier", "brier_saved_tau")):
        runner_frame["_loss"] = runner_frame[column]
        by_race = runner_frame.groupby(
            base_keys + ["outcome_group"], sort=False, dropna=False)._loss.agg(
                ["sum", "count"]).reset_index()
        by_race["race_contribution"] = by_race["sum"] / by_race["field_n"]

        # Contract table: average each outcome group's loss contribution over all
        # races in that ticket-change stratum, with race denominator N.
        for changed in ("unchanged", "changed"):
            for outcome in ("top3", "other"):
                for variant in VARIANTS:
                    base_group = runner_frame.loc[
                        runner_frame.ticket_changed.eq(changed) & runner_frame.variant.eq(variant),
                        ["race_id", "race_date", "year", "distance_m"]].drop_duplicates()
                    observed = by_race.loc[
                        by_race.ticket_changed.eq(changed) & by_race.variant.eq(variant)
                        & by_race.outcome_group.eq(outcome)]
                    filled = base_group[["race_id", "race_date"]].merge(
                        observed[["race_id", "race_contribution", "count"]],
                        on="race_id", how="left", validate="one_to_one")
                    contribution = filled.race_contribution.fillna(0.0)
                    contribution_rows.append({
                        "metric": metric, "ticket_changed": changed, "outcome_group": outcome,
                        "variant": variant,
                        "race_equal_loss_contribution": float(contribution.mean()) if len(filled) else np.nan,
                        "contribution_sum_over_races": float(contribution.sum()),
                        "runner_rows": int(observed["count"].sum()) if len(observed) else 0,
                        "races": int(len(base_group)),
                        "race_days": int(base_group.race_date.nunique()),
                    })

        # Expanded diagnostic table: stratify the contribution by ticket change,
        # paired hit state, own U6 state/size, year and fixed distance.
        for group_kind, group_value, data in [
            ("overall", "all", by_race),
            *[("year", str(int(year)), group) for year, group in by_race.groupby("year", sort=True)],
            *[("distance_m", str(int(distance)), group)
              for distance, group in by_race.groupby("distance_m", sort=True)],
        ]:
            summary = data.groupby(
                ["variant", "ticket_changed", "hit_both_or_only_or_neither", "union_state",
                 "own_six_horse_union_n", "outcome_group"], sort=True, dropna=False).agg(
                    races=("race_id", "nunique"), race_days=("race_date", "nunique"),
                    runner_rows=("count", "sum"),
                    race_equal_loss_contribution=("race_contribution", "mean"),
                    contribution_sum_over_races=("race_contribution", "sum"),
                ).reset_index()
            summary.insert(0, "metric", metric)
            summary.insert(1, "group", group_kind)
            summary.insert(2, "value", group_value)
            cross_rows.extend(summary.to_dict("records"))

    # Ticket-set changes crossed with paired race-level loss direction.
    race_wide = races.pivot(index=["race_id", "race_date", "year", "distance_m"],
                            columns="variant", values=[
                                "top3_marginal_log_loss_saved_tau",
                                "top3_marginal_brier_saved_tau"]).reset_index()
    race_wide.columns = ["_".join(str(part) for part in col if part) if isinstance(col, tuple) else col
                         for col in race_wide.columns]
    pair_meta = pairs.loc[pairs.variant.eq("F1"), ["race_id", "ticket_changed"]]
    race_wide = race_wide.merge(pair_meta, on="race_id", how="left", validate="one_to_one")
    ticket_change_rows = []
    for metric, prefix in (("log_loss", "top3_marginal_log_loss_saved_tau"),
                           ("brier", "top3_marginal_brier_saved_tau")):
        race_wide["delta"] = race_wide[f"{prefix}_F1_STYLE6"] - race_wide[f"{prefix}_F1"]
        for changed, subset in race_wide.groupby("ticket_changed", sort=True):
            delta = subset.delta.to_numpy(dtype=np.float64)
            ticket_change_rows.append({
                "ticket_changed": changed, "metric": metric, "races": int(len(subset)),
                "improved_races": int((delta < -METRIC_ATOL).sum()),
                "worsened_races": int((delta > METRIC_ATOL).sum()),
                "unchanged_races": int((np.abs(delta) <= METRIC_ATOL).sum()),
                "mean_delta_STYLE6_minus_F1": float(delta.mean()),
            })
    # Extend the ticket/loss cross-tab by year, fixed distance, paired hit
    # outcome, and each model's own selected-six horse union state/size.
    context = pairs.loc[:, ["race_id", "variant", "race_date", "year", "distance_m",
                            "ticket_changed", "hit_both_or_only_or_neither",
                            "union_state", "own_six_horse_union_n"]].copy()
    delta_rows = []
    for metric, prefix in (("log_loss", "top3_marginal_log_loss_saved_tau"),
                           ("brier", "top3_marginal_brier_saved_tau")):
        values = races.pivot(index=["race_id", "race_date", "year", "distance_m"],
                             columns="variant", values=prefix).reset_index()
        values["delta_STYLE6_minus_F1"] = values["F1_STYLE6"] - values["F1"]
        for model_context in VARIANTS:
            model_context_rows = context.loc[context.variant.eq(model_context)]
            joined = values.merge(model_context_rows, on=["race_id", "race_date", "year", "distance_m"],
                                  how="left", validate="one_to_one")
            group_specs = [("overall", "all", joined)]
            group_specs.extend(("year", str(int(value)), group)
                               for value, group in joined.groupby("year", sort=True))
            group_specs.extend(("distance_m", str(int(value)), group)
                               for value, group in joined.groupby("distance_m", sort=True))
            for group_kind, group_value, data in group_specs:
                by = data.groupby(["ticket_changed", "hit_both_or_only_or_neither",
                                   "union_state", "own_six_horse_union_n"],
                                  sort=True, dropna=False).delta_STYLE6_minus_F1.agg(
                                      races="size", mean_delta="mean").reset_index()
                for row in by.to_dict("records"):
                    delta = data.loc[
                        data.ticket_changed.eq(row["ticket_changed"])
                        & data.hit_both_or_only_or_neither.eq(row["hit_both_or_only_or_neither"])
                        & data.union_state.eq(row["union_state"])
                        & data.own_six_horse_union_n.eq(row["own_six_horse_union_n"]),
                        "delta_STYLE6_minus_F1"].to_numpy(dtype=np.float64)
                    delta_rows.append({
                        "metric": metric, "u6_context_variant": model_context,
                        "group": group_kind, "value": group_value,
                        **row,
                        "improved_races": int((delta < -METRIC_ATOL).sum()),
                        "worsened_races": int((delta > METRIC_ATOL).sum()),
                        "unchanged_races": int((np.abs(delta) <= METRIC_ATOL).sum()),
                    })
    return (pd.DataFrame(contribution_rows), pd.DataFrame(cross_rows),
            pd.DataFrame(ticket_change_rows), pd.DataFrame(delta_rows))


def build_decomposition_summaries(ticket_union: pd.DataFrame) -> pd.DataFrame:
    output = []
    groups = [("overall", "all", ticket_union)]
    groups.extend(("year", str(int(year)), data)
                  for year, data in ticket_union.groupby("year", sort=True))
    groups.extend(("distance_m", str(int(distance)), data)
                  for distance, data in ticket_union.groupby("distance_m", sort=True))
    for group_kind, group_value, data in groups:
        summary = data.groupby(
            ["variant", "ticket_changed", "hit_both_or_only_or_neither", "union_state",
             "own_six_horse_union_n"], sort=True, dropna=False).agg(
                races=("race_id", "nunique"), race_days=("race_date", "nunique"),
                mean_ticket_overlap=("ticket_overlap_n", "mean"),
                mean_ticket_symmetric_difference=("ticket_symmetric_difference_n", "mean"),
            ).reset_index()
        summary.insert(0, "group", group_kind)
        summary.insert(1, "value", group_value)
        output.extend(summary.to_dict("records"))
    return pd.DataFrame(output)


def make_bootstrap(race_frame: pd.DataFrame) -> pd.DataFrame:
    metrics_by_basis = {
        "saved_tau": [
            "joint_true_nll_saved_tau", "full_joint_brier_saved_tau",
            "top3_marginal_log_loss_saved_tau", "top3_marginal_brier_saved_tau",
            "six_mass_saved_tau",
            "hit_at_1", "hit_at_3", "hit_at_6", "hit_at_10", "hit_at_20",
        ],
        "fixed_tau_1": [
            "joint_true_nll_tau1", "full_joint_brier_tau1",
            "top3_marginal_log_loss_tau1", "top3_marginal_brier_tau1", "six_mass_tau1",
        ],
    }
    rows = []
    for basis, metrics in metrics_by_basis.items():
        for metric in metrics:
            wide = race_frame.pivot(index=["race_id", "race_date", "year", "distance_m"],
                                    columns="variant", values=metric).reset_index()
            assert wide.F1.notna().all() and wide.F1_STYLE6.notna().all()
            wide["delta"] = wide.F1_STYLE6 - wide.F1
            groups = [("overall", "all", wide)]
            groups.extend(("year", str(int(value)), group)
                          for value, group in wide.groupby("year", sort=True))
            groups.extend(("distance_m", str(int(value)), group)
                          for value, group in wide.groupby("distance_m", sort=True))
            for group_kind, group_value, frame in groups:
                daily = frame.groupby("race_date", sort=True).delta.agg(["sum", "size"])
                rng = np.random.default_rng(BOOTSTRAP_SEED)
                index = rng.integers(0, len(daily), size=(BOOTSTRAP_REPS, len(daily)))
                daily_sum = daily["sum"].to_numpy(dtype=np.float64)
                daily_size = daily["size"].to_numpy(dtype=np.float64)
                samples = daily_sum[index].sum(axis=1) / daily_size[index].sum(axis=1)
                rows.append({
                    "metric": metric, "temperature_basis": basis,
                    "group": group_kind, "value": group_value,
                    "delta_STYLE6_minus_F1": float(frame.delta.mean()),
                    "ci95_low": float(np.quantile(samples, 0.025)),
                    "ci95_high": float(np.quantile(samples, 0.975)),
                    "races": int(len(frame)), "race_days": int(frame.race_date.nunique()),
                    "resamples": BOOTSTRAP_REPS, "seed": BOOTSTRAP_SEED,
                })
    return pd.DataFrame(rows)


def make_extra_rank_bootstrap(race_frame: pd.DataFrame) -> pd.DataFrame:
    """Additional diagnostic only; not part of the approved primary gate table."""
    metrics = [("six_hit_alias", "six_hit"),
               ("true_triple_rank", "true_triple_rank")]
    rows = []
    for label, column in metrics:
        wide = race_frame.pivot(index=["race_id", "race_date", "year", "distance_m"],
                                columns="variant", values=column).reset_index()
        wide["delta"] = wide.F1_STYLE6 - wide.F1
        groups = [("overall", "all", wide)]
        groups.extend(("year", str(int(value)), group)
                      for value, group in wide.groupby("year", sort=True))
        groups.extend(("distance_m", str(int(value)), group)
                      for value, group in wide.groupby("distance_m", sort=True))
        for group_kind, group_value, frame in groups:
            daily = frame.groupby("race_date", sort=True).delta.agg(["sum", "size"])
            rng = np.random.default_rng(BOOTSTRAP_SEED)
            index = rng.integers(0, len(daily), size=(BOOTSTRAP_REPS, len(daily)))
            samples = (daily["sum"].to_numpy(dtype=np.float64)[index].sum(axis=1)
                       / daily["size"].to_numpy(dtype=np.float64)[index].sum(axis=1))
            rows.append({
                "diagnostic_only": label, "group": group_kind, "value": group_value,
                "delta_STYLE6_minus_F1": float(frame.delta.mean()),
                "ci95_low": float(np.quantile(samples, 0.025)),
                "ci95_high": float(np.quantile(samples, 0.975)),
                "races": int(len(frame)), "race_days": int(frame.race_date.nunique()),
                "resamples": BOOTSTRAP_REPS, "seed": BOOTSTRAP_SEED,
                "not_primary_gate": True,
            })
    return pd.DataFrame(rows)


def build_mass_reliability(race_frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variant in VARIANTS:
        frame = race_frame.loc[race_frame.variant.eq(variant)].copy()
        mass = frame.six_mass_saved_tau.to_numpy(dtype=np.float64)
        assert np.isfinite(mass).all() and ((mass >= -1e-12) & (mass <= 1 + 1e-12)).all()
        indices = np.minimum(np.floor(np.clip(mass, 0, 1) * 10).astype(int), 9)
        frame["bin_index"] = indices
        for index in range(10):
            group = frame.loc[frame.bin_index.eq(index)]
            rows.append({
                "variant": variant, "bin_left": index / 10,
                "bin_right": (index + 1) / 10,
                "races": int(len(group)),
                "race_days": int(group.race_date.nunique()),
                "mean_predicted_mass": float(group.six_mass_saved_tau.mean()) if len(group) else np.nan,
                "observed_hit_rate": float(group.six_hit.mean()) if len(group) else np.nan,
            })
    return pd.DataFrame(rows)


def build_summary(race_frame: pd.DataFrame) -> pd.DataFrame:
    metric_columns = [
        "joint_true_nll_saved_tau", "full_joint_brier_saved_tau",
        "top3_marginal_log_loss_saved_tau", "top3_marginal_brier_saved_tau",
        "joint_true_nll_tau1", "full_joint_brier_tau1",
        "top3_marginal_log_loss_tau1", "top3_marginal_brier_tau1",
        "six_mass_saved_tau", "six_mass_tau1", "six_mass_brier_saved_tau",
        "six_hit", "true_triple_rank", "sixth_seventh_energy_gap",
        "hit_at_1", "hit_at_3", "hit_at_6", "hit_at_10", "hit_at_20",
    ]
    rows = []
    for variant in VARIANTS:
        frame = race_frame.loc[race_frame.variant.eq(variant)]
        groups = [("overall", "all", frame)]
        groups.extend(("year", str(int(value)), group)
                      for value, group in frame.groupby("year", sort=True))
        groups.extend(("distance_m", str(int(value)), group)
                      for value, group in frame.groupby("distance_m", sort=True))
        for kind, value, group in groups:
            record = {"variant": variant, "group": kind, "value": value,
                      "races": int(len(group)), "race_days": int(group.race_date.nunique())}
            record.update({column: float(group[column].mean()) for column in metric_columns})
            rows.append(record)
    return pd.DataFrame(rows)


def create_markdown(summary: pd.DataFrame, paired: pd.DataFrame,
                    parity: dict, decomposition: pd.DataFrame,
                    union_checks: dict, loss_cross: pd.DataFrame,
                    extra_rank_bootstrap: pd.DataFrame) -> str:
    overall = summary.loc[summary.group.eq("overall")].set_index("variant")
    overall_deltas = paired.loc[(paired.group.eq("overall"))
                                & paired.temperature_basis.eq("saved_tau")].set_index("metric")
    lines = [
        "# F1_STYLE6 확률·최대 6조합 독립 재산출 결과", "",
        "입력은 승인된 PLAN/data contract 해시와 기존 source lock으로 확인한 저장 raw score, saved tau 및 F1 replay roster다. 새 fit·tau 최적화·DB 조회를 하지 않았다. 이 결과는 기존 후향 코호트 진단이며 미래 검증이나 원인 인과 추론이 아니다.", "",
        "## 전체 코호트", "",
        "| 지표 | F1 | F1_STYLE6 | STYLE6−F1 | 날짜 paired 95% 구간 |",
        "|---|---:|---:|---:|---:|",
    ]
    metric_labels = [
        ("top3_marginal_log_loss_saved_tau", "Top3 주변 log loss"),
        ("top3_marginal_brier_saved_tau", "Top3 주변 Brier"),
        ("joint_true_nll_saved_tau", "정답 세두 joint NLL"),
        ("full_joint_brier_saved_tau", "전체 joint Brier"),
        ("hit_at_6", "canonical six 적중률 (= hit@6)"),
        ("six_mass_saved_tau", "선택 six 예측 질량"),
        ("hit_at_1", "hit@1"), ("hit_at_3", "hit@3"),
        ("hit_at_10", "hit@10"), ("hit_at_20", "hit@20"),
    ]
    for column, label in metric_labels:
        delta = float(overall.loc["F1_STYLE6", column] - overall.loc["F1", column])
        boot = overall_deltas.loc[column]
        lines.append(f"| {label} | {overall.loc['F1', column]:.6f} | {overall.loc['F1_STYLE6', column]:.6f} | {delta:+.6f} | [{boot.ci95_low:+.6f}, {boot.ci95_high:+.6f}] |")
    lines += [
        "", "## 연도별 적중과 proper loss", "",
        "| 연도 | F1 six hit | STYLE6 six hit | 차이 | 주변 LL 차이 | joint NLL 차이 |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    years = summary.loc[summary.group.eq("year")]
    for year in sorted(years.value.unique(), key=int):
        f = years.loc[(years.value == year) & years.variant.eq("F1")].iloc[0]
        c = years.loc[(years.value == year) & years.variant.eq("F1_STYLE6")].iloc[0]
        lines.append(f"| {year} | {f.six_hit:.6f} | {c.six_hit:.6f} | {c.six_hit-f.six_hit:+.6f} | {c.top3_marginal_log_loss_saved_tau-f.top3_marginal_log_loss_saved_tau:+.6f} | {c.joint_true_nll_saved_tau-f.joint_true_nll_saved_tau:+.6f} |")
    lines += [
        "", "## 재현 및 U6 분해", "",
        f"독립 계산은 {parity['runner_rows']:,}개 runner 행, {parity['race_rows']:,}개 variant-race 행, {parity['canonical_ticket_rows']:,}개 canonical ticket을 확인했다. 저장 raw score와 marginal, ticket 번호·순위·확률을 1e-12 허용오차로 대조했고 모두 일치했다. 각 경주에서 전체 joint 합은 1, runner marginal 합은 3이었다. 저장 tau와 tau=1의 canonical six가 모두 같음을 직접 검증했다.", "",
        "| 모델 | hit | allocation miss | union miss | 평균 U6 크기 |",
        "|---|---:|---:|---:|---:|",
    ]
    for variant, counts in union_checks.items():
        subset = decomposition.loc[decomposition.group.eq("overall") & decomposition.variant.eq(variant)]
        avg_u6 = float((subset.own_six_horse_union_n * subset.races).sum() / 1779)
        lines.append(f"| {variant} | {counts['hit']} | {counts['allocation_miss']} | {counts['union_miss']} | {avg_u6:.3f} |")
    lines += [
        "", "U6_v는 각 모델의 선택된 여섯 ticket에서 사후적으로 나온 말 합집합이다. 이 분해는 현재 선택 결과의 기술이며 독립적으로 고정한 후보 pool이 아니므로 union miss만으로 말 평가의 원인이나 조합 학습의 필요성을 확정하지 않는다.", "",
        "## 추가 순위·hit 별칭 진단 (주 평가 gate 아님)", "",
        "| 진단 | delta | 날짜 paired 95% 구간 |",
        "|---|---:|---:|",
    ]
    extra_overall = extra_rank_bootstrap.loc[extra_rank_bootstrap.group.eq("overall")]
    for _, row in extra_overall.iterrows():
        lines.append(f"| {row.diagnostic_only} | {row.delta_STYLE6_minus_F1:+.6f} | [{row.ci95_low:+.6f}, {row.ci95_high:+.6f}] |")
    lines += [
        "", "`six_hit`는 `hit_at_6`의 별칭이며 이 bootstrap은 주 지표 CI와 별도 보조 진단으로 분리했다. 정답 triple 평균 순위도 선택된 여섯 장 성능을 대체하지 않는 순위 진단이다.", "",
        "가산 triple 분포가 고정되면 canonical top6은 그 분포에서 기대 적중이 가장 큰 여섯 ticket이다. 관측 hit은 같은 과거 코호트에서의 실현 결과로만 해석한다. tau=1 표는 tau 최적화가 아닌 확률 크기 민감도 진단이다.", "",
        "주변 LL/Brier와 정답 triple joint NLL/full-joint Brier를 함께 보고 주변확률만 개선됐다는 식으로 미리 원인을 정하지 않았다. `ticket_change_loss_cross.csv`는 변경/유지별 개선·악화·동률을, `loss_vs_ticket_change_cross.csv`와 `runner_loss_contributions.csv`는 연도·거리·hit 상태·U6 상태/크기 및 Top3/기타 출전 기여를 교차한다. 손실 변화는 |delta|≤1e-12를 동률로 분류했다.", "",
        "Six mass 신뢰도는 고정 구간별 평균 예측 mass와 실제 hit rate로 제시한다. 날짜 bootstrap CI 및 모든 상세표는 `outputs/`에 있다. 전체 triple 확률·순위는 `outputs/all_triples.parquet`, 경주 진단은 `outputs/race_diagnostics.parquet`, U6/ticket 집계는 `outputs/ticket_and_union_decomposition.csv`다.", "",
    ]
    return "\n".join(lines)


def write_outputs(payloads: dict) -> dict:
    OUT.mkdir(exist_ok=False)
    for name in payloads:
        assert not (OUT / name).exists(), f"refusing to overwrite: {name}"
    payloads["all_triples.parquet"].to_parquet(OUT / "all_triples.parquet", index=False)
    payloads["race_diagnostics.parquet"].to_parquet(OUT / "race_diagnostics.parquet", index=False)
    payloads["ticket_and_union_decomposition.csv"].to_csv(OUT / "ticket_and_union_decomposition.csv", index=False)
    payloads["paired_date_bootstrap.csv"].to_csv(OUT / "paired_date_bootstrap.csv", index=False)
    payloads["rank_hit_extra_bootstrap.csv"].to_csv(OUT / "rank_hit_extra_bootstrap.csv", index=False)
    payloads["six_mass_reliability.csv"].to_csv(OUT / "six_mass_reliability.csv", index=False)
    payloads["runner_loss_contributions.csv"].to_csv(OUT / "runner_loss_contributions.csv", index=False)
    payloads["loss_contribution_cross_strata.csv"].to_csv(OUT / "loss_contribution_cross_strata.csv", index=False)
    payloads["ticket_change_loss_cross.csv"].to_csv(OUT / "ticket_change_loss_cross.csv", index=False)
    payloads["loss_vs_ticket_change_cross.csv"].to_csv(OUT / "loss_vs_ticket_change_cross.csv", index=False)
    payloads["decomposition_summaries.csv"].to_csv(OUT / "decomposition_summaries.csv", index=False)
    payloads["metric_summaries.csv"].to_csv(OUT / "metric_summaries.csv", index=False)
    output_hashes = {}
    for path in sorted(OUT.iterdir()):
        output_hashes[path.name] = {"bytes": int(path.stat().st_size), "sha256": sha256(path)}
    return output_hashes


def main() -> None:
    assert sha256(PLAN_PATH) == APPROVED_PLAN_SHA256
    assert sha256(CONTRACT_PATH) == APPROVED_CONTRACT_SHA256
    assert not OUT.exists(), f"refusing to overwrite output directory: {OUT}"
    input_lock = verify_inputs()
    baseline, inputs, saved_tickets, saved_report_runners, saved_report_races = load_data()
    races, runners, tickets, triples, ticket_union, race_models = build_results(baseline, inputs)
    parity = parity_checks(baseline, inputs, races, runners, tickets,
                           saved_tickets, saved_report_runners, saved_report_races)
    race_frame = pd.DataFrame(races)
    runner_frame = pd.DataFrame(runners)
    ticket_frame = pd.DataFrame(tickets)
    triple_frame = pd.DataFrame(triples)
    ticket_union_frame = pd.DataFrame(ticket_union)
    assert len(triple_frame) == sum(
        math.comb(int(n), 3) for n in
        baseline.groupby("race_id", sort=False).size().to_numpy()
    ) * 2
    assert ticket_union_frame.groupby("variant").size().eq(1779).all()

    variant_union_checks = {}
    for variant in VARIANTS:
        group = ticket_union_frame.loc[ticket_union_frame.variant.eq(variant)]
        counts = group.union_state.value_counts().to_dict()
        assert sum(counts.values()) == 1779
        assert int(group.all3inU6_v.sum()) == int(
            group.union_state.isin(["hit", "allocation_miss"]).sum())
        assert int(group.union_state.eq("hit").sum()) == int(
            race_frame.loc[race_frame.variant.eq(variant), "six_hit"].sum())
        variant_union_checks[variant] = {
            "race_count": 1779,
            "hit": int(counts.get("hit", 0)),
            "allocation_miss": int(counts.get("allocation_miss", 0)),
            "union_miss": int(counts.get("union_miss", 0)),
            "all3inU6_v": int(group.all3inU6_v.sum()),
            "partition_passed": True,
        }

    # Verify raw-score ordering and tau invariance of runner marginals.
    order_checks = 0
    marginal_order_violations = 0
    marginal_exact_rank_mismatch_races = 0
    marginal_ambiguous_pairs = 0
    for _, group in runner_frame.groupby(["race_id", "variant"], sort=False):
        score_order = np.argsort(-group.score.to_numpy(dtype=np.float64), kind="stable")
        p_saved_order = np.argsort(-group.p_top3_saved_tau.to_numpy(dtype=np.float64), kind="stable")
        p_tau1_order = np.argsort(-group.p_top3_tau1.to_numpy(dtype=np.float64), kind="stable")
        # For exact score ties, stable score ordering is the canonical tie policy.
        # Floating-point marginal differences are checked against the score order
        # only where the source scores are distinct.
        scores = group.score.to_numpy(dtype=np.float64)
        p_saved = group.p_top3_saved_tau.to_numpy(dtype=np.float64)
        p_tau1 = group.p_top3_tau1.to_numpy(dtype=np.float64)
        for i in range(len(scores)):
            for j in range(i + 1, len(scores)):
                score_delta = scores[i] - scores[j]
                for marginal_delta in (p_saved[i] - p_saved[j], p_tau1[i] - p_tau1[j]):
                    if score_delta == 0:
                        if abs(marginal_delta) > 1e-12:
                            marginal_order_violations += 1
                        else:
                            marginal_ambiguous_pairs += 1
                    elif abs(marginal_delta) <= 1e-12:
                        marginal_ambiguous_pairs += 1
                    elif np.sign(score_delta) != np.sign(marginal_delta):
                        marginal_order_violations += 1
        if p_saved_order.tolist() != score_order.tolist() or p_tau1_order.tolist() != score_order.tolist():
            marginal_exact_rank_mismatch_races += 1
        order_checks += 1
    assert marginal_order_violations == 0, "marginal order violation beyond 1e-12 tolerance"
    assert race_frame.scaled_tau_top6_mismatch.sum() == 0
    assert race_frame.tau1_top6_mismatch.sum() == 0

    paired = make_bootstrap(race_frame)
    extra_rank_bootstrap = make_extra_rank_bootstrap(race_frame)
    reliability = build_mass_reliability(race_frame)
    contributions, contribution_cross, ticket_loss_cross, loss_ticket_cross = build_loss_contributions(
        runners, tickets, ticket_union, races)
    summary = build_summary(race_frame)
    decomposition_summary = build_decomposition_summaries(ticket_union_frame)
    for variant in VARIANTS:
        for changed in ("unchanged", "changed"):
            race_meta = ticket_union_frame.loc[
                ticket_union_frame.variant.eq(variant)
                & ticket_union_frame.ticket_changed.eq(changed), ["race_id", "race_date"]]
            expected_top3 = 3 * len(race_meta)
            expected_other = int(baseline.loc[
                baseline.race_id.isin(race_meta.race_id.unique())].groupby("race_id").size().sum()
                - expected_top3)
            for metric, col in (("log_loss", "top3_marginal_log_loss_saved_tau"),
                                ("brier", "top3_marginal_brier_saved_tau")):
                rows = contributions.loc[
                    contributions.variant.eq(variant)
                    & contributions.ticket_changed.eq(changed)
                    & contributions.metric.eq(metric)].set_index("outcome_group")
                assert int(rows.loc["top3", "runner_rows"]) == expected_top3
                assert int(rows.loc["other", "runner_rows"]) == expected_other
                summary_loss = race_frame.loc[
                    race_frame.variant.eq(variant)
                    & race_frame.race_id.isin(race_meta.race_id), col].mean()
                assert np.isclose(rows.race_equal_loss_contribution.sum(), summary_loss,
                                  rtol=0, atol=1e-10)
    input_lock_after = verify_inputs()
    assert input_lock_after == input_lock, "locked inputs changed during independent calculations"
    required_payloads = {
        "all_triples.parquet": triple_frame,
        "race_diagnostics.parquet": race_frame,
        "ticket_and_union_decomposition.csv": ticket_union_frame,
        "paired_date_bootstrap.csv": paired,
        "rank_hit_extra_bootstrap.csv": extra_rank_bootstrap,
        "six_mass_reliability.csv": reliability,
        "runner_loss_contributions.csv": contributions,
        "loss_contribution_cross_strata.csv": contribution_cross,
        "ticket_change_loss_cross.csv": ticket_loss_cross,
        "loss_vs_ticket_change_cross.csv": loss_ticket_cross,
        "decomposition_summaries.csv": decomposition_summary,
        "metric_summaries.csv": summary,
    }
    output_hashes = write_outputs(required_payloads)
    results_md = create_markdown(summary, paired, parity, decomposition_summary,
                                 variant_union_checks, loss_ticket_cross,
                                 extra_rank_bootstrap)
    result_path = OWN / "REVIEW_RESULTS.md"
    assert not result_path.exists()
    result_path.write_text(results_md, encoding="utf-8")
    verification = {
        "passed": True,
        "approved_plan_sha256": APPROVED_PLAN_SHA256,
        "approved_data_contract_sha256": APPROVED_CONTRACT_SHA256,
        "verified_source_lock": input_lock,
        "verified_source_lock_after_calculation": input_lock_after,
        "cohort": {"races": 1779, "runners_per_variant": 17412, "race_days": 269},
        "parity": parity,
        "variant_specific_U6_partition": variant_union_checks,
        "score_marginal_order_race_checks": order_checks,
        "score_marginal_order_violations_beyond_1e-12": marginal_order_violations,
        "score_marginal_order_pairs_within_1e-12_or_exact_tie": marginal_ambiguous_pairs,
        "score_marginal_exact_argsort_mismatch_races_from_float_ties": marginal_exact_rank_mismatch_races,
        "saved_tau_vs_tau1_canonical_six_identical": bool(
            race_frame.scaled_tau_top6_mismatch.sum() == 0
            and race_frame.tau1_top6_mismatch.sum() == 0),
        "saved_tau_top6_mismatch_races": int(race_frame.scaled_tau_top6_mismatch.sum()),
        "tau1_top6_mismatch_races": int(race_frame.tau1_top6_mismatch.sum()),
        "bootstrap_resamples": BOOTSTRAP_REPS,
        "bootstrap_seed_reset_per_metric_group": BOOTSTRAP_SEED,
        "score_rounding": False,
        "fit_calls": 0,
        "tau_optimization_calls": 0,
        "database_queries": 0,
        "database_or_production_changed": False,
        "output_hashes": output_hashes,
    }
    receipt_path = OUT / "independent_verification.json"
    receipt_path.write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    manifest = {
        "study": "F1 to F1_STYLE6 probability and canonical six gap review",
        "status": "independent saved-score reconstruction complete",
        "inputs": {
            "approved_plan_sha256": APPROVED_PLAN_SHA256,
            "approved_data_contract_sha256": APPROVED_CONTRACT_SHA256,
            "prepared_lock_sha256": input_lock["prepared_lock_sha256"],
            "artifact_manifest_sha256": input_lock["artifact_manifest_sha256"],
        },
        "review_memo_sha256": sha256(OWN / "REVIEW_MEMO.md"),
        "independent_recompute_sha256": sha256(OWN / "independent_recompute.py"),
        "outputs": {
            str(path.relative_to(OWN)): {"bytes": int(path.stat().st_size), "sha256": sha256(path)}
            for path in sorted(OUT.iterdir())
        },
        "review_results_sha256": sha256(result_path),
        "fit_calls": 0,
        "tau_optimization_calls": 0,
        "database_queries": 0,
    }
    manifest_path = OWN / "ARTIFACT_MANIFEST.json"
    assert not manifest_path.exists()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    print(json.dumps({
        "passed": True,
        "races": 1779,
        "runner_rows_per_variant": 17412,
        "all_triple_rows": len(triple_frame),
        "score_marginal_order_race_checks": order_checks,
        "union_partitions": variant_union_checks,
        "outputs": output_hashes,
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
