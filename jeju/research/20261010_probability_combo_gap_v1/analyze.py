"""Explain saved runner-probability vs canonical six-ticket outcomes."""
from __future__ import annotations

import argparse
from itertools import combinations
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import logsumexp


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDY = ROOT / "jeju/research/20261010_style_history_ablation_v1"
BASE = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
OUT = HERE / "outputs"
YEARS = (2024, 2025, 2026)
VARIANTS = ("F1", "F1_STYLE6")
K_VALUES = (1, 3, 6, 10, 20)
BOOTSTRAPS = 2000
BOOTSTRAP_SEED = 20261008
PROB_TOL = 1e-12
APPROVED_PLAN_SHA256 = "09cb2d20554f2f98a7f9aeaef21b722f86e544e46e904d1b7d80278ab086d4d4"
APPROVED_CONTRACT_SHA256 = "7ea6ba197c76e1f83dd73e3dc84939704261695733e93b55dfbb45539d3c018d"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict:
    return {"sha256": sha256(path), "bytes": path.stat().st_size}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def locked_hash_record(value):
    if isinstance(value, dict):
        return value.get("sha256")
    return value


def freeze_inputs() -> dict:
    paths = {
        "plan": HERE / "PLAN.md",
        "data_contract": HERE / "data_contract.json",
        "final_results": STUDY / "FINAL_RESULTS.md",
        "artifact_manifest": STUDY / "ARTIFACT_MANIFEST.json",
        "prepared_lock": STUDY / "outputs/prepared_lock.json",
        "f1_replay_receipt": STUDY / "outputs/f1_replay_verification.json",
        "f1_runner_scores": STUDY / "outputs/f1_reproduced_runner_predictions.parquet",
        "f1_race_metrics": STUDY / "outputs/f1_reproduced_race_metrics.csv",
        "f1_six_tickets": STUDY / "outputs/f1_reproduced_six_combinations.csv",
        "report_receipt": STUDY / "outputs/report/report_receipt.json",
        "report_runner_predictions": STUDY / "outputs/report/runner_predictions.parquet",
        "report_race_metrics": STUDY / "outputs/report/race_metrics.parquet",
        "report_six_tickets": STUDY / "outputs/report/canonical_six_combinations.csv",
        "candidate_score_stage": STUDY / "outputs/candidate_scores_fit_stage.parquet",
        "candidate_report_source": STUDY / "report.py",
        "candidate_replay_source": STUDY / "run.py",
        "baseline_evaluator_source": ROOT / "jeju/research/20261008_horse_profile_baseline_v1/run.py",
        "baseline_prepare_source": BASE / "prepare.py",
        "baseline_lock": BASE / "outputs/prepared_lock.json",
    }
    for year in YEARS:
        paths[f"candidate_score_{year}"] = STUDY / f"outputs/F1_STYLE6_{year}/evaluation_scores.parquet"
        paths[f"candidate_meta_{year}"] = STUDY / f"outputs/F1_STYLE6_{year}/meta.json"
        paths[f"candidate_model_{year}"] = STUDY / f"outputs/F1_STYLE6_{year}/top3.txt"
        paths[f"baseline_meta_{year}"] = BASE / f"outputs/F1_{year}/meta.json"
        paths[f"baseline_model_{year}"] = BASE / f"outputs/F1_{year}/top3.txt"

    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256(paths["plan"]) != APPROVED_PLAN_SHA256:
        raise AssertionError("PLAN hash differs from the approved analysis plan")
    if sha256(paths["data_contract"]) != APPROVED_CONTRACT_SHA256:
        raise AssertionError("data contract hash differs from the approved analysis contract")
    if read_json(paths["f1_replay_receipt"]).get("passed") is not True:
        raise AssertionError("saved F1 replay receipt is not PASS")
    if read_json(paths["report_receipt"]).get("passed") is not True:
        raise AssertionError("saved comparison report receipt is not PASS")

    manifest = read_json(paths["artifact_manifest"])
    prepared = read_json(paths["prepared_lock"])
    baseline_lock = read_json(paths["baseline_lock"])
    expected = {}
    for section in ("source_references", "study_artifacts"):
        for relative, value in manifest.get(section, {}).items():
            expected[relative] = locked_hash_record(value)
    for lock in (prepared, baseline_lock):
        expected.update(lock.get("references", {}))
        # These lock entries are names relative to the owning output directory.
        for name, digest in lock.get("artifacts", {}).items():
            if lock is prepared:
                expected[str((STUDY / "outputs" / name).relative_to(ROOT))] = digest
            else:
                expected[str((BASE / "outputs" / name).relative_to(ROOT))] = digest

    records = {}
    for name, path in paths.items():
        relative = str(path.relative_to(ROOT))
        actual = file_record(path)
        frozen = expected.get(relative)
        if frozen is not None and actual["sha256"] != frozen:
            raise AssertionError(f"frozen reference hash differs: {relative}")
        records[relative] = {**actual, "matched_frozen_reference": frozen is not None}

    candidate_meta = {}
    baseline_meta = {}
    for year in YEARS:
        candidate_meta[year] = read_json(paths[f"candidate_meta_{year}"])
        baseline_meta[year] = read_json(paths[f"baseline_meta_{year}"])
        cmeta = candidate_meta[year]
        fmeta = baseline_meta[year]
        assert int(cmeta["evaluation_year"]) == year
        assert math.isfinite(float(cmeta["tau"])) and float(cmeta["tau"]) > 0
        assert math.isfinite(float(fmeta["tau"])) and float(fmeta["tau"]) > 0
        assert sha256(paths[f"candidate_score_{year}"]) == cmeta["evaluation_scores_sha256"]
        assert sha256(paths[f"candidate_model_{year}"]) == cmeta["model_sha256"]
        assert sha256(paths[f"baseline_model_{year}"]) == fmeta["model_sha256"]

    return {
        "study": "20261010_probability_combo_gap_v1",
        "plan_sha256": sha256(paths["plan"]),
        "data_contract_sha256": sha256(paths["data_contract"]),
        "artifact_manifest_sha256": sha256(paths["artifact_manifest"]),
        "prepared_lock_sha256": sha256(paths["prepared_lock"]),
        "baseline_lock_sha256": sha256(paths["baseline_lock"]),
        "source_files": records,
        "tau_by_year": {
            str(year): {"F1": float(baseline_meta[year]["tau"]),
                        "F1_STYLE6": float(candidate_meta[year]["tau"])}
            for year in YEARS
        },
        "saved_scores_used_without_model_reload": True,
        "network_or_database_access": False,
    }


def probability_and_losses(energy: np.ndarray, combos: np.ndarray, n: int, tau: float,
                           y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, float]:
    logits = energy / float(tau)
    q = np.exp(logits - logsumexp(logits))
    incidence = np.zeros((len(combos), n), dtype=np.float64)
    incidence[np.arange(len(combos))[:, None], combos] = 1.0
    p = q @ incidence
    clipped = np.clip(p, 1e-12, 1.0 - 1e-12)
    ll = -y * np.log(clipped) - (1.0 - y) * np.log1p(-clipped)
    brier = np.square(p - y)
    return q, p, ll, brier, float(np.mean(ll)), float(np.mean(brier))


def tie_sizes(energy: np.ndarray) -> tuple[np.ndarray, dict]:
    values, inverse, counts = np.unique(energy, return_inverse=True, return_counts=True)
    sizes = counts[inverse]
    tied = counts[counts > 1]
    return sizes, {
        "exact_tie_groups_n": int(len(tied)),
        "exact_tied_triples_n": int(tied.sum()),
        "exact_tie_pairs_n": int(np.sum(tied * (tied - 1) // 2)),
    }


def ranks_from_order(order: np.ndarray) -> np.ndarray:
    ranks = np.empty(len(order), dtype=np.int64)
    ranks[order] = np.arange(1, len(order) + 1, dtype=np.int64)
    return ranks


def score_order_violations(scores: np.ndarray, probabilities: np.ndarray) -> int:
    score_delta = scores[:, None] - scores[None, :]
    probability_delta = probabilities[:, None] - probabilities[None, :]
    upper = np.triu(np.ones(score_delta.shape, dtype=bool), k=1)
    inverted = ((score_delta > 0.0) & (probability_delta < -PROB_TOL) |
                (score_delta < 0.0) & (probability_delta > PROB_TOL))
    tied_score_unequal_marginal = ((score_delta == 0.0) &
                                    (np.abs(probability_delta) > PROB_TOL))
    return int(np.count_nonzero(upper & (inverted | tied_score_unequal_marginal)))


def read_saved_inputs():
    base = pd.read_parquet(STUDY / "outputs/f1_reproduced_runner_predictions.parquet")
    assert len(base) == 17412 and base.api_record_id.is_unique
    assert base.variant.astype(str).eq("F1").all()
    assert base.groupby("race_id").y.sum().eq(3).all()
    assert base.race_id.nunique() == 1779
    assert base.race_date.nunique() == 269
    assert not base.duplicated(["race_id", "horse_id"]).any()
    assert not base.duplicated(["race_id", "horse_number"]).any()
    assert base.groupby("race_id").size().eq(base.groupby("race_id").field_n.first()).all()

    saved_scores = []
    saved_taus = {"F1": {}, "F1_STYLE6": {}}
    for year in YEARS:
        path = STUDY / f"outputs/F1_STYLE6_{year}/evaluation_scores.parquet"
        one = pd.read_parquet(path)
        assert list(one.columns) == ["api_record_id", "score"]
        assert one.api_record_id.is_unique
        one["year"] = year
        saved_scores.append(one)
        saved_taus["F1_STYLE6"][year] = float(
            read_json(STUDY / f"outputs/F1_STYLE6_{year}/meta.json")["tau"])
        saved_taus["F1"][year] = float(
            read_json(BASE / f"outputs/F1_{year}/meta.json")["tau"])
    candidate_scores = pd.concat(saved_scores, ignore_index=True)
    stage = pd.read_parquet(STUDY / "outputs/candidate_scores_fit_stage.parquet")
    stage = stage[["api_record_id", "score", "year"]]
    assert stage.api_record_id.is_unique
    stage_by_id = stage.set_index("api_record_id").sort_index()
    scores_by_id = candidate_scores.set_index("api_record_id").sort_index()
    assert stage_by_id.index.equals(scores_by_id.index)
    assert np.array_equal(stage_by_id.score.to_numpy(), scores_by_id.score.to_numpy())
    assert np.array_equal(stage_by_id.year.to_numpy(), scores_by_id.year.to_numpy())
    assert len(candidate_scores) == 17412

    report_runners = pd.read_parquet(STUDY / "outputs/report/runner_predictions.parquet")
    assert len(report_runners) == 34824
    report_by_variant = {variant: group.copy() for variant, group in report_runners.groupby("variant", sort=False)}
    assert set(report_by_variant) == set(VARIANTS)
    for variant in VARIANTS:
        assert len(report_by_variant[variant]) == 17412
        assert report_by_variant[variant].api_record_id.is_unique
    f1_report = report_by_variant["F1"].set_index("api_record_id").sort_index()
    baseline_by_id = base.set_index("api_record_id").sort_index()
    assert f1_report.index.equals(baseline_by_id.index)
    assert np.array_equal(f1_report.score.to_numpy(), baseline_by_id.score.to_numpy())
    for column in ("race_id", "year", "horse_id", "horse_number", "y"):
        assert f1_report[column].astype(str).equals(baseline_by_id[column].astype(str))
    candidate_report = report_by_variant["F1_STYLE6"].set_index("api_record_id").sort_index()
    assert candidate_report.index.equals(scores_by_id.index)
    assert np.array_equal(candidate_report.score.to_numpy(), scores_by_id.score.to_numpy())
    for column in ("race_id", "year", "horse_id", "horse_number", "y"):
        assert candidate_report[column].astype(str).equals(baseline_by_id[column].astype(str))

    report_races = pd.read_parquet(STUDY / "outputs/report/race_metrics.parquet")
    assert len(report_races) == 3558
    saved_tickets = pd.read_csv(STUDY / "outputs/report/canonical_six_combinations.csv", dtype={"race_id": str})
    assert len(saved_tickets) == 21348
    f1_tickets = pd.read_csv(STUDY / "outputs/f1_reproduced_six_combinations.csv", dtype={"race_id": str})
    assert len(f1_tickets) == 10674
    assert report_runners.race_date.nunique() == 269
    for variant in VARIANTS:
        part = report_by_variant[variant]
        assert part.race_id.nunique() == 1779
        assert not part.duplicated(["race_id", "horse_id"]).any()
        assert not part.duplicated(["race_id", "horse_number"]).any()
        assert part.groupby("race_id").size().eq(part.groupby("race_id").field_n.first()).all()
        part_by_id = part.set_index("api_record_id").sort_index()
        for column in ("race_id", "race_date", "year", "distance_m", "field_n",
                       "horse_id", "horse_number", "y"):
            assert part_by_id[column].astype(str).equals(baseline_by_id[column].astype(str)), column
    assert set(report_races.variant.astype(str)) == set(VARIANTS)
    assert report_races.groupby("variant").race_id.nunique().eq(1779).all()
    return base, candidate_scores, saved_taus, report_runners, report_races, saved_tickets, f1_tickets


def evaluate_all(base: pd.DataFrame, candidate_scores: pd.DataFrame, saved_taus: dict,
                 report_runners: pd.DataFrame, report_races: pd.DataFrame,
                 saved_tickets: pd.DataFrame, f1_tickets: pd.DataFrame):
    candidate_score_map = candidate_scores.set_index("api_record_id").score
    runner_report_by_variant = {
        variant: group.set_index("api_record_id")
        for variant, group in report_runners.groupby("variant", sort=False)
    }
    race_report_by_variant = {
        variant: group.set_index("race_id")
        for variant, group in report_races.groupby("variant", sort=False)
    }
    ticket_reference = {
        variant: group.copy()
        for variant, group in saved_tickets.groupby("variant", sort=False)
    }
    ticket_reference["F1"] = f1_tickets.copy()

    triple_rows = []
    race_rows = []
    parity = {variant: {"races": 0, "tickets_checked": 0, "ticket_order_exact": True,
                        "ticket_probability_max_abs_diff": 0.0,
                        "marginal_max_abs_diff": 0.0,
                        "runner_log_loss_max_abs_diff": 0.0,
                        "runner_brier_max_abs_diff": 0.0,
                        "race_metric_max_abs_diff": 0.0,
                        "scaled_tau_rank_mismatch_races": 0,
                        "scaled_tau_rank_mismatch_triples": 0,
                        "scaled_tau_top6_mismatch_races": 0,
                        "tau1_rank_mismatch_races": 0,
                        "tau1_rank_mismatch_triples": 0,
                        "tau1_top6_mismatch_races": 0,
                        "p_top3_saved_tau_score_order_violations": 0,
                        "p_top3_tau1_score_order_violations": 0}
              for variant in VARIANTS}
    report_ticket_index = {}
    for variant in VARIANTS:
        tickets = ticket_reference[variant]
        assert len(tickets) == 10674
        assert tickets.groupby("race_id").size().eq(6).all()
        report_ticket_index[variant] = {
            str(race_id): group.sort_values("selection_rank", kind="stable").reset_index(drop=True)
            for race_id, group in tickets.groupby("race_id", sort=False)
        }
    for race_id, group in base.groupby("race_id", sort=False):
        group = group.reset_index(drop=True)
        rid = str(race_id)
        n = len(group)
        assert group.race_date.nunique() == 1
        assert group.year.nunique() == 1
        assert group.distance_m.nunique() == 1
        assert group.field_n.nunique() == 1 and int(group.field_n.iloc[0]) == n
        numbers = group.horse_number.to_numpy(dtype=np.int64)
        if not np.all(numbers[1:] > numbers[:-1]):
            raise AssertionError(f"horse-number order changed in {rid}")
        ids = group.horse_id.astype(str).to_numpy()
        if len(set(ids)) != n:
            raise AssertionError(f"duplicate horse ID in race roster: {rid}")
        y = group.y.to_numpy(dtype=np.float64)
        true_idx = np.flatnonzero(y == 1)
        assert len(true_idx) == 3
        combos = np.asarray(list(combinations(range(n), 3)), dtype=np.int64)
        assert len(combos) >= 6
        truth = np.all(combos == true_idx[None, :], axis=1)
        target_idx = np.flatnonzero(truth)
        assert len(target_idx) == 1
        target = int(target_idx[0])

        score_arrays = {
            "F1": group.score.to_numpy(dtype=np.float64),
            "F1_STYLE6": group.api_record_id.map(candidate_score_map).to_numpy(dtype=np.float64),
        }
        if not np.isfinite(score_arrays["F1"]).all() or not np.isfinite(score_arrays["F1_STYLE6"]).all():
            raise AssertionError(f"non-finite raw score in {rid}")
        per_race = {}
        for variant in VARIANTS:
            scores = score_arrays[variant]
            # This is the source evaluator's sum order and full precision.
            energy = np.sort(scores[combos], axis=1).sum(axis=1)
            order = np.argsort(-energy, kind="stable")
            stable_rank = ranks_from_order(order)
            tie_size, tie_summary = tie_sizes(energy)
            saved_tau = float(saved_taus[variant][int(group.year.iloc[0])])
            order_saved_tau = np.argsort(-(energy / saved_tau), kind="stable")
            order_tau1 = np.argsort(-energy, kind="stable")
            rank_saved_tau = ranks_from_order(order_saved_tau)
            rank_tau1 = ranks_from_order(order_tau1)
            scaled_tau_rank_mismatch_n = int(np.count_nonzero(rank_saved_tau != stable_rank))
            tau1_rank_mismatch_n = int(np.count_nonzero(rank_tau1 != stable_rank))
            scaled_tau_top6_mismatch = not np.array_equal(order_saved_tau[:6], order[:6])
            tau1_top6_mismatch = not np.array_equal(order_tau1[:6], order[:6])
            q, p, ll, br, marginal_ll, marginal_brier = probability_and_losses(
                energy, combos, n, saved_tau, y)
            q1, p1, ll1, br1, marginal_ll1, marginal_brier1 = probability_and_losses(
                energy, combos, n, 1.0, y)
            if not np.isclose(q.sum(), 1.0, rtol=0, atol=1e-12):
                raise AssertionError(f"joint distribution does not sum to one: {rid}/{variant}")
            if not np.isclose(p.sum(), 3.0, rtol=0, atol=1e-10):
                raise AssertionError(f"Top3 marginals do not sum to three: {rid}/{variant}")
            saved_p_order_violations = score_order_violations(scores, p)
            tau1_p_order_violations = score_order_violations(scores, p1)
            parity[variant]["scaled_tau_rank_mismatch_races"] += int(scaled_tau_rank_mismatch_n > 0)
            parity[variant]["scaled_tau_rank_mismatch_triples"] += scaled_tau_rank_mismatch_n
            parity[variant]["scaled_tau_top6_mismatch_races"] += int(scaled_tau_top6_mismatch)
            parity[variant]["tau1_rank_mismatch_races"] += int(tau1_rank_mismatch_n > 0)
            parity[variant]["tau1_rank_mismatch_triples"] += tau1_rank_mismatch_n
            parity[variant]["tau1_top6_mismatch_races"] += int(tau1_top6_mismatch)
            parity[variant]["p_top3_saved_tau_score_order_violations"] += saved_p_order_violations
            parity[variant]["p_top3_tau1_score_order_violations"] += tau1_p_order_violations
            true_rank = int(stable_rank[target])
            six_mass = float(q[order[:6]].sum())
            six_mass_tau1 = float(q1[order[:6]].sum())
            joint_nll = float(logsumexp(energy / saved_tau) - energy[target] / saved_tau)
            joint_brier = float(np.square(q).sum() - 2.0 * q[target] + 1.0)
            joint_nll_tau1 = float(logsumexp(energy) - energy[target])
            joint_brier_tau1 = float(np.square(q1).sum() - 2.0 * q1[target] + 1.0)
            if not (-1e-12 <= joint_brier <= 2.0 + 1e-12):
                raise AssertionError(f"joint Brier outside conventional range: {rid}/{variant}")

            report_rows = runner_report_by_variant[variant].loc[group.api_record_id.to_numpy()]
            report_p = report_rows.p_top3.to_numpy(dtype=np.float64)
            report_ll = report_rows.log_loss.to_numpy(dtype=np.float64)
            report_br = report_rows.brier.to_numpy(dtype=np.float64)
            for actual, expected, label in ((p, report_p, "marginal"),
                                            (ll, report_ll, "runner log loss"),
                                            (br, report_br, "runner Brier")):
                if not np.allclose(actual, expected, rtol=0, atol=PROB_TOL):
                    raise AssertionError(f"saved {label} parity failed: {rid}/{variant}")
            parity[variant]["marginal_max_abs_diff"] = max(
                parity[variant]["marginal_max_abs_diff"], float(np.max(np.abs(p - report_p))))
            parity[variant]["runner_log_loss_max_abs_diff"] = max(
                parity[variant]["runner_log_loss_max_abs_diff"], float(np.max(np.abs(ll - report_ll))))
            parity[variant]["runner_brier_max_abs_diff"] = max(
                parity[variant]["runner_brier_max_abs_diff"], float(np.max(np.abs(br - report_br))))

            ref_tickets = report_ticket_index[variant][rid]
            chosen = order[:6]
            numbers_text = [",".join(str(int(numbers[ix])) for ix in combos[j]) for j in chosen]
            saved_numbers = ref_tickets.numbers.astype(str).tolist()
            if numbers_text != saved_numbers:
                raise AssertionError(f"canonical ticket rank/selection parity failed: {rid}/{variant}")
            parity[variant]["ticket_order_exact"] = parity[variant]["ticket_order_exact"] and (numbers_text == saved_numbers)
            for rank, j in enumerate(chosen, start=1):
                saved_ticket = ref_tickets.iloc[rank - 1]
                prob_diff = abs(float(q[j]) - float(saved_ticket.probability))
                parity[variant]["ticket_probability_max_abs_diff"] = max(
                    parity[variant]["ticket_probability_max_abs_diff"], prob_diff)
                if prob_diff > PROB_TOL:
                    raise AssertionError(f"canonical ticket probability parity failed: {rid}/{variant}/{rank}")
                if int(saved_ticket.hit) != int(j == target):
                    raise AssertionError(f"canonical ticket hit parity failed: {rid}/{variant}/{rank}")
            parity[variant]["tickets_checked"] += 6
            parity[variant]["races"] += 1

            race_reference = race_report_by_variant[variant].loc[rid]
            source_values = {
                "log_loss": marginal_ll,
                "brier": marginal_brier,
                "trio_nll": joint_nll,
                "six_combo_hit": int(target in chosen),
                "six_combo_mass": six_mass,
            }
            for metric, computed in source_values.items():
                difference = abs(float(computed) - float(race_reference[metric]))
                parity[variant]["race_metric_max_abs_diff"] = max(
                    parity[variant]["race_metric_max_abs_diff"], difference)
                if metric in ("six_combo_hit",):
                    assert int(computed) == int(race_reference[metric])
                elif difference > PROB_TOL:
                    raise AssertionError(f"saved race metric parity failed: {rid}/{variant}/{metric}")

            top3_contrib = {
                "log_loss": float(ll[y == 1].sum() / n),
                "brier": float(br[y == 1].sum() / n),
            }
            non_top3_contrib = {
                "log_loss": float(ll[y == 0].sum() / n),
                "brier": float(br[y == 0].sum() / n),
            }
            top3_contrib_tau1 = {
                "log_loss": float(ll1[y == 1].sum() / n),
                "brier": float(br1[y == 1].sum() / n),
            }
            non_top3_contrib_tau1 = {
                "log_loss": float(ll1[y == 0].sum() / n),
                "brier": float(br1[y == 0].sum() / n),
            }
            per_race[variant] = {
                "variant": variant, "tau": saved_tau, "field_n": n, "energy": energy, "combos": combos,
                "order": order, "ranks": stable_rank, "rank_saved_tau": rank_saved_tau,
                "rank_tau1": rank_tau1, "order_saved_tau": order_saved_tau,
                "order_tau1": order_tau1, "scaled_tau_rank_mismatch_n": scaled_tau_rank_mismatch_n,
                "tau1_rank_mismatch_n": tau1_rank_mismatch_n,
                "scaled_tau_top6_mismatch": scaled_tau_top6_mismatch,
                "tau1_top6_mismatch": tau1_top6_mismatch,
                "p_order_violations": saved_p_order_violations,
                "p1_order_violations": tau1_p_order_violations,
                "q": q, "q1": q1, "p": p, "p1": p1,
                "ll": ll, "br": br, "ll1": ll1, "br1": br1, "target": target,
                "truth_ids": set(ids[true_idx]), "selected": [frozenset(ids[combos[j]]) for j in chosen],
                "selected_ids": [list(ids[combos[j]]) for j in chosen],
                "selected_numbers": numbers_text, "six_mass": six_mass,
                "six_mass_tau1": six_mass_tau1, "six_hit": int(target in chosen),
                "true_rank": true_rank, "tie_size": int(tie_size[target]),
                "tie_summary": tie_summary,
                "joint_nll": joint_nll, "joint_brier": joint_brier,
                "joint_nll_tau1": joint_nll_tau1, "joint_brier_tau1": joint_brier_tau1,
                "marginal_ll": marginal_ll, "marginal_brier": marginal_brier,
                "marginal_ll_tau1": marginal_ll1, "marginal_brier_tau1": marginal_brier1,
                "top3_contrib": top3_contrib, "non_top3_contrib": non_top3_contrib,
                "top3_contrib_tau1": top3_contrib_tau1,
                "non_top3_contrib_tau1": non_top3_contrib_tau1,
            }
            for j, triple in enumerate(combos):
                triple_rows.append({
                    "race_id": rid, "race_date": str(group.race_date.iloc[0]),
                    "year": int(group.year.iloc[0]), "distance_m": int(group.distance_m.iloc[0]),
                    "variant": variant, "triple_horse_ids": [str(ids[ix]) for ix in triple],
                    "triple_numbers": [int(numbers[ix]) for ix in triple],
                    "triple_energy": float(energy[j]),
                    "joint_probability_saved_tau": float(q[j]),
                    "joint_probability_tau1": float(q1[j]),
                    "stable_rank": int(stable_rank[j]),
                    "rank_after_saved_tau": int(rank_saved_tau[j]),
                    "rank_after_tau1": int(rank_tau1[j]),
                    "exact_energy_tie_size": int(tie_size[j]),
                    "is_truth": bool(j == target),
                })

        # Ticket-set movement and each model's own selected-six horse union.
        f1 = per_race["F1"]
        style = per_race["F1_STYLE6"]
        f1_set = set(f1["selected"])
        style_set = set(style["selected"])
        overlap = len(f1_set & style_set)
        delta_n = len(f1_set ^ style_set)
        hit_status = ("hit_both" if f1["six_hit"] and style["six_hit"] else
                      "F1_only" if f1["six_hit"] else
                      "STYLE6_only" if style["six_hit"] else "neither")
        date = str(group.race_date.iloc[0])
        year = int(group.year.iloc[0])
        distance = int(group.distance_m.iloc[0])
        for variant in VARIANTS:
            result = per_race[variant]
            own_union = set().union(*result["selected"])
            other_variant = "F1_STYLE6" if variant == "F1" else "F1"
            other_union = set().union(*per_race[other_variant]["selected"])
            own_union_ids = [str(ids[ix]) for ix in range(n) if str(ids[ix]) in own_union]
            other_union_ids = [str(ids[ix]) for ix in range(n) if str(ids[ix]) in other_union]
            shared_union_ids = [horse_id for horse_id in own_union_ids if horse_id in other_union]
            own_only_union_ids = [horse_id for horse_id in own_union_ids if horse_id not in other_union]
            other_only_union_ids = [horse_id for horse_id in other_union_ids if horse_id not in own_union]
            all_three_inside = result["truth_ids"].issubset(own_union)
            state = ("hit" if result["six_hit"] else
                     "allocation_miss" if all_three_inside else "union_miss")
            race_rows.append({
                "race_id": rid, "race_date": date, "year": year, "distance_m": distance,
                "field_n": n,
                "variant": variant, "saved_tau": result["tau"],
                "true_triple_rank": result["true_rank"],
                "true_rank_after_saved_tau": int(result["rank_saved_tau"][result["target"]]),
                "true_rank_after_tau1": int(result["rank_tau1"][result["target"]]),
                **{f"hit_at_{k}": int(result["true_rank"] <= k) for k in K_VALUES},
                "true_triple_exact_tie_size": result["tie_size"],
                **result["tie_summary"],
                "exact_tie_counts": json.dumps(result["tie_summary"], sort_keys=True),
                "hit_at_k": json.dumps({str(k): int(result["true_rank"] <= k)
                                         for k in K_VALUES}, sort_keys=True),
                "joint_true_nll_saved_tau": result["joint_nll"],
                "full_joint_brier_saved_tau": result["joint_brier"],
                "top3_marginal_log_loss_saved_tau": result["marginal_ll"],
                "top3_marginal_brier_saved_tau": result["marginal_brier"],
                "joint_true_nll_tau1": result["joint_nll_tau1"],
                "full_joint_brier_tau1": result["joint_brier_tau1"],
                "top3_marginal_log_loss_tau1": result["marginal_ll_tau1"],
                "top3_marginal_brier_tau1": result["marginal_brier_tau1"],
                "six_mass_saved_tau": result["six_mass"],
                "six_mass_tau1": result["six_mass_tau1"],
                "six_hit": result["six_hit"],
                "scaled_tau_rank_mismatch_n": result["scaled_tau_rank_mismatch_n"],
                "scaled_tau_top6_mismatch": result["scaled_tau_top6_mismatch"],
                "tau1_rank_mismatch_n": result["tau1_rank_mismatch_n"],
                "tau1_top6_mismatch": result["tau1_top6_mismatch"],
                "p_top3_saved_tau_score_order_violations": result["p_order_violations"],
                "p_top3_tau1_score_order_violations": result["p1_order_violations"],
                "ticket_overlap_n": overlap,
                "ticket_symmetric_difference_n": delta_n,
                "ticket_changed": bool(delta_n),
                "ticket_hit_status": hit_status,
                "own_six_horse_union_n": len(own_union),
                "own_six_horse_union_ids": json.dumps(own_union_ids, ensure_ascii=False),
                "other_union_overlap_n": len(shared_union_ids),
                "own_only_union_horse_ids": json.dumps(own_only_union_ids, ensure_ascii=False),
                "other_only_union_horse_ids": json.dumps(other_only_union_ids, ensure_ascii=False),
                "all3in_own_union": bool(all_three_inside),
                "union_state": state,
            })

    race_df = pd.DataFrame(race_rows)
    triples_df = pd.DataFrame(triple_rows)
    assert race_df.groupby("variant").size().eq(1779).all()
    assert triples_df.groupby(["race_id", "variant"]).size().gt(0).all()
    assert race_df.groupby("variant").six_hit.sum().ge(0).all()
    for variant, group in race_df.groupby("variant", sort=False):
        counts = group.union_state.value_counts()
        assert int(counts.sum()) == len(group)
        assert int(group.all3in_own_union.sum()) == int(
            group.union_state.isin(["hit", "allocation_miss"]).sum())
    return triples_df, race_df, parity


def add_ticket_change_and_verify(race_df: pd.DataFrame) -> pd.DataFrame:
    wide = race_df.pivot(index="race_id", columns="variant",
                         values=["ticket_overlap_n", "ticket_symmetric_difference_n", "ticket_changed", "ticket_hit_status"])
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    wide = wide.reset_index()
    assert wide.race_id.nunique() == 1779
    assert wide.ticket_overlap_n_F1.equals(wide.ticket_overlap_n_F1_STYLE6)
    assert wide.ticket_symmetric_difference_n_F1.equals(wide.ticket_symmetric_difference_n_F1_STYLE6)
    assert wide.ticket_changed_F1.equals(wide.ticket_changed_F1_STYLE6)
    assert wide.ticket_hit_status_F1.equals(wide.ticket_hit_status_F1_STYLE6)
    return wide


def reliability_table(race_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    edges = np.linspace(0.0, 1.0, 11)
    for variant, group in race_df.groupby("variant", sort=False):
        value = group.six_mass_saved_tau.to_numpy(dtype=float)
        indices = np.searchsorted(edges, value, side="right") - 1
        indices = np.clip(indices, 0, 9)
        for bin_index in range(10):
            one = group.iloc[np.flatnonzero(indices == bin_index)]
            rows.append({
                "variant": variant, "bin_left": float(edges[bin_index]),
                "bin_right": float(edges[bin_index + 1]),
                "right_endpoint_inclusive": bool(bin_index == 9),
                "races": int(len(one)), "race_days": int(one.race_date.nunique()),
                "mean_predicted_mass": float(one.six_mass_saved_tau.mean()) if len(one) else np.nan,
                "observed_hit_rate": float(one.six_hit.mean()) if len(one) else np.nan,
            })
    result = pd.DataFrame(rows)
    assert result.groupby("variant").races.sum().eq(1779).all()
    return result


def runner_loss_contributions(race_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    # Each row's two outcome contributions sum to that race's macro runner loss.
    for _, race in race_df.iterrows():
        changed = bool(race.ticket_changed)
        field_n = int(race.field_n)
        for metric in ("log_loss", "brier"):
            for outcome, source_name in (("actual_top3", "top3_contrib"),
                                         ("other_runners", "non_top3_contrib")):
                # Per-runner values are regenerated from stored report inputs in evaluate_all.
                # Recover the race contribution from the reported total and joint diagnostics
                # only through a cached column attached below.
                field = f"{outcome}_{metric}_contribution"
                contribution = float(race[field])
                rows.append({
                    "ticket_changed": changed, "outcome_group": outcome,
                    "variant": race.variant, "metric": metric,
                    "race_equal_loss_contribution": contribution,
                    "runner_rows": 3 if outcome == "actual_top3" else field_n - 3,
                    "races": 1, "race_date": race.race_date,
                    "year": int(race.year), "distance_m": int(race.distance_m),
                })
    raw = pd.DataFrame(rows)
    out = raw.groupby(["ticket_changed", "outcome_group", "variant", "metric"], as_index=False).agg(
        race_equal_loss_contribution=("race_equal_loss_contribution", "mean"),
        races=("races", "sum"), race_days=("race_date", "nunique"),
        runner_rows=("runner_rows", "sum"),
    )
    return out


def ticket_change_loss_cross(race_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for changed, group in race_df.groupby("ticket_changed", sort=True):
        for metric, field in (("log_loss", "top3_marginal_log_loss_saved_tau"),
                              ("brier", "top3_marginal_brier_saved_tau")):
            wide = group.pivot(index="race_id", columns="variant", values=field)
            delta = wide["F1_STYLE6"] - wide["F1"]
            rows.append({
                "ticket_changed": bool(changed), "metric": metric, "races": int(len(delta)),
                "improved_races": int((delta < -PROB_TOL).sum()),
                "worsened_races": int((delta > PROB_TOL).sum()),
                "unchanged_races": int((np.abs(delta) <= PROB_TOL).sum()),
                "mean_delta_STYLE6_minus_F1": float(delta.mean()),
            })
    result = pd.DataFrame(rows)
    assert result.groupby("metric").races.sum().eq(1779).all()
    return result


def paired_bootstrap(race_df: pd.DataFrame) -> pd.DataFrame:
    value_columns = {
        "saved_tau": [
            "joint_true_nll_saved_tau", "full_joint_brier_saved_tau",
            "top3_marginal_log_loss_saved_tau", "top3_marginal_brier_saved_tau",
            "six_mass_saved_tau", "hit_at_1", "hit_at_3", "hit_at_6", "hit_at_10", "hit_at_20",
        ],
        "fixed_tau_1": [
            "joint_true_nll_tau1", "full_joint_brier_tau1",
            "top3_marginal_log_loss_tau1", "top3_marginal_brier_tau1", "six_mass_tau1",
        ],
    }
    rows = []
    for basis, metrics in value_columns.items():
        for metric in metrics:
            wide = race_df.pivot(index="race_id", columns="variant", values=metric)
            info = race_df.loc[race_df.variant.eq("F1"), ["race_id", "race_date", "year", "distance_m"]].set_index("race_id")
            pair = info.join(wide, how="inner")
            assert len(pair) == 1779 and pair[["F1", "F1_STYLE6"]].notna().all().all()
            pair["delta"] = pair.F1_STYLE6 - pair.F1
            contexts = [("overall", "all", pair)]
            contexts.extend(("year", str(int(year)), one) for year, one in pair.groupby("year", sort=True))
            contexts.extend(("distance_m", str(int(distance)), one)
                            for distance, one in pair.groupby("distance_m", sort=True))
            for group_name, value, one in contexts:
                daily = one.groupby("race_date", sort=True).delta.agg(["sum", "size"])
                rng = np.random.default_rng(BOOTSTRAP_SEED)
                indices = rng.integers(0, len(daily), size=(BOOTSTRAPS, len(daily)))
                samples = (daily["sum"].to_numpy()[indices].sum(axis=1) /
                           daily["size"].to_numpy()[indices].sum(axis=1))
                rows.append({
                    "metric": metric, "temperature_basis": basis,
                    "group": group_name, "value": value,
                    "delta_STYLE6_minus_F1": float(one.delta.mean()),
                    "ci95_low": float(np.quantile(samples, 0.025)),
                    "ci95_high": float(np.quantile(samples, 0.975)),
                    "races": int(len(one)), "race_days": int(one.race_date.nunique()),
                    "resamples": BOOTSTRAPS, "seed": BOOTSTRAP_SEED,
                })
    return pd.DataFrame(rows)


def attach_loss_contribution_columns(race_df: pd.DataFrame, cache: dict) -> pd.DataFrame:
    result = race_df.copy()
    for index, row in result.iterrows():
        values = cache[(str(row.race_id), str(row.variant))]
        result.loc[index, "actual_top3_log_loss_contribution"] = values["top3_log_loss"]
        result.loc[index, "other_runners_log_loss_contribution"] = values["other_log_loss"]
        result.loc[index, "actual_top3_brier_contribution"] = values["top3_brier"]
        result.loc[index, "other_runners_brier_contribution"] = values["other_brier"]
    return result


def write_new_parquet(path: Path, frame: pd.DataFrame):
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False)


def write_new_csv(path: Path, frame: pd.DataFrame):
    with path.open("x", encoding="utf-8", newline="") as stream:
        frame.to_csv(stream, index=False)


def write_new_json(path: Path, value: dict):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_new_text(path: Path, value: str):
    with path.open("x", encoding="utf-8", newline="") as stream:
        stream.write(value)


def markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "(no rows)"
    columns = [str(column) for column in frame.columns]
    rows = []
    for row in frame.itertuples(index=False, name=None):
        cells = []
        for value in row:
            if pd.isna(value):
                cells.append("")
            elif isinstance(value, (float, np.floating)):
                cells.append(f"{float(value):.6f}")
            else:
                cells.append(str(value))
        rows.append(cells)
    lines = ["| " + " | ".join(columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def result_summary(races: pd.DataFrame, parity: dict, union: pd.DataFrame,
                   bootstrap: pd.DataFrame, reliability: pd.DataFrame,
                   contributions: pd.DataFrame, ticket_cross: pd.DataFrame) -> str:
    metrics = [
        "joint_true_nll_saved_tau", "full_joint_brier_saved_tau",
        "top3_marginal_log_loss_saved_tau", "top3_marginal_brier_saved_tau",
        "six_mass_saved_tau", "six_hit", "hit_at_1", "hit_at_3", "hit_at_6",
        "hit_at_10", "hit_at_20", "true_triple_rank",
    ]
    # Expand the fixed k diagnostics from the contract's compact per-race JSON field.
    # Individual hit_at_k columns are retained internally for the report only.
    scope_parts = [("overall", "all", races)]
    scope_parts.extend(("year", str(int(v)), one) for v, one in races.groupby("year", sort=True))
    scope_parts.extend(("distance_m", str(int(v)), one)
                       for v, one in races.groupby("distance_m", sort=True))
    aggregate_rows = []
    for scope, value, frame in scope_parts:
        for variant, group in frame.groupby("variant", sort=False):
            row = {"scope": scope, "value": value, "variant": variant, "races": len(group)}
            for metric in metrics:
                row[metric] = float(group[metric].mean())
            aggregate_rows.append(row)
    aggregate = pd.DataFrame(aggregate_rows)

    status_rows = []
    one_per_race = races[races.variant.eq("F1")]
    status_parts = [("overall", "all", one_per_race)]
    status_parts.extend(("year", str(int(v)), g) for v, g in one_per_race.groupby("year", sort=True))
    status_parts.extend(("distance_m", str(int(v)), g)
                        for v, g in one_per_race.groupby("distance_m", sort=True))
    statuses = ("hit_both", "F1_only", "STYLE6_only", "neither")
    for scope, value, frame in status_parts:
        counts = frame.ticket_hit_status.value_counts()
        status_rows.append({"scope": scope, "value": value, "races": len(frame),
                            **{status: int(counts.get(status, 0)) for status in statuses}})
    status_table = pd.DataFrame(status_rows)

    union_rows = []
    union_parts = [("overall", "all", union)]
    union_parts.extend(("year", str(int(v)), g) for v, g in union.groupby("year", sort=True))
    union_parts.extend(("distance_m", str(int(v)), g)
                       for v, g in union.groupby("distance_m", sort=True))
    for scope, value, frame in union_parts:
        for variant, group in frame.groupby("variant", sort=False):
            counts = group.union_state.value_counts()
            union_rows.append({
                "scope": scope, "value": value, "variant": variant, "races": len(group),
                "hit": int(counts.get("hit", 0)),
                "allocation_miss": int(counts.get("allocation_miss", 0)),
                "union_miss": int(counts.get("union_miss", 0)),
                "mean_U6_size": float(group.own_six_horse_union_n.mean()),
                "mean_U6_overlap": float(group.other_union_overlap_n.mean()),
            })
    union_table = pd.DataFrame(union_rows)

    lines = [
        "# Saved-score probability and six-ticket gap results",
        "",
        "This report analyzes the frozen 1,779-race / 17,412-runner / 269-day retrospective cohort. It does not fit a model, search tau, or change ticket selection.",
        "",
        "## Saved-output parity and invariance checks",
        "",
        f"Reproduction used {sum(x['races'] for x in parity.values())} variant-races and {sum(x['tickets_checked'] for x in parity.values())} saved canonical ticket rows. The detailed exact-tolerance checks are in `parity_verification.json`.",
        "",
        markdown_table(pd.DataFrame([{
            "variant": variant, "races": item["races"], "ticket_order_exact": item["ticket_order_exact"],
            "max_ticket_probability_abs_diff": item["ticket_probability_max_abs_diff"],
            "max_marginal_abs_diff": item["marginal_max_abs_diff"],
            "saved_tau_rank_mismatch_races": item["scaled_tau_rank_mismatch_races"],
            "saved_tau_rank_mismatch_triples": item["scaled_tau_rank_mismatch_triples"],
            "saved_tau_top6_mismatch_races": item["scaled_tau_top6_mismatch_races"],
            "tau1_rank_mismatch_races": item["tau1_rank_mismatch_races"],
            "tau1_rank_mismatch_triples": item["tau1_rank_mismatch_triples"],
            "tau1_top6_mismatch_races": item["tau1_top6_mismatch_races"],
            "p_score_order_violations_saved_tau": item["p_top3_saved_tau_score_order_violations"],
            "p_score_order_violations_tau1": item["p_top3_tau1_score_order_violations"],
        } for variant, item in parity.items()])),
        "",
        "A positive temperature preserves a model's energy ordering mathematically; any reported rank difference is retained as a floating-point tie/order diagnostic. Tau=1 results are temperature diagnostics, not a new model-performance decision.",
        "",
        "## Race-equal averages by fixed cohort strata",
        "",
        "Losses and rates below are race means. `hit_at_10` and `hit_at_20` are rank diagnostics; only `six_hit` is the six-ticket hit result.",
        "",
        markdown_table(aggregate),
        "",
        "## Six-ticket hit outcomes",
        "",
        markdown_table(status_table),
        "",
        "## Model-specific selected-six union decomposition",
        "",
        "Each U6 is derived from that variant's own six tickets. The partition describes where the realized triple falls under the current selections; U6 is not a fixed candidate pool or a causal diagnosis.",
        "",
        markdown_table(union_table),
        "",
        "## Paired date bootstrap, reliability, and runner-loss contributions",
        "",
        "Paired bootstrap deltas are STYLE6 minus F1, resampling race dates with the contract's fixed seed and 2,000 replicates per metric. Six-mass reliability uses the fixed bins in `six_mass_reliability.csv`.",
        "",
        "Runner contributions divide each outcome-subgroup loss sum by that race's full field size before taking race means. `runner_rows` is the entrant-row denominator count, not a race count.",
        "",
        markdown_table(ticket_cross),
        "",
        markdown_table(contributions),
        "",
        "## Interpretation limits",
        "",
        "The saved-output parity and the listed decompositions are confirmed for this historical cohort. These are retrospective associations, not causal explanations or evidence of future performance. The normalized joint distribution is over unordered exact Top3 sets; it does not recover finish order or exact second/third-place probabilities. Raw score magnitudes are not compared across models. No conclusion that U6 misses identify a horse-evaluation or combination-model cause is supported. Any proposed pair-specific or alternative ticket-selection mechanism remains a future hypothesis requiring a separately approved study.",
        "",
    ]
    return "\n".join(lines)


def run_analysis():
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite existing output directory: {OUT}")
    source_lock = freeze_inputs()
    base, candidate_scores, saved_taus, report_runners, report_races, saved_tickets, f1_tickets = read_saved_inputs()
    triples, races, parity = evaluate_all(base, candidate_scores, saved_taus,
                                          report_runners, report_races, saved_tickets, f1_tickets)

    # Recompute per-race contribution cache from the already validated persisted runner losses.
    contribution_cache = {}
    reports = {variant: group.set_index("api_record_id")
               for variant, group in report_runners.groupby("variant", sort=False)}
    for race_id, group in base.groupby("race_id", sort=False):
        n = len(group)
        y = group.y.to_numpy(dtype=int)
        ids = group.api_record_id.to_numpy()
        for variant in VARIANTS:
            saved = reports[variant].loc[ids]
            ll = saved.log_loss.to_numpy(dtype=float)
            br = saved.brier.to_numpy(dtype=float)
            contribution_cache[(str(race_id), variant)] = {
                "top3_log_loss": float(ll[y == 1].sum() / n),
                "other_log_loss": float(ll[y == 0].sum() / n),
                "top3_brier": float(br[y == 1].sum() / n),
                "other_brier": float(br[y == 0].sum() / n),
            }
    races = attach_loss_contribution_columns(races, contribution_cache)
    ticket_diff = add_ticket_change_and_verify(races)
    reliability = reliability_table(races)
    boot = paired_bootstrap(races)
    contributions = runner_loss_contributions(races)
    ticket_cross = ticket_change_loss_cross(races)

    # Explicit race-equal decomposition: top3 and other contributions sum to total loss.
    for variant in VARIANTS:
        for metric in ("log_loss", "brier"):
            top = races[f"actual_top3_{metric}_contribution"].to_numpy(dtype=float)
            other = races[f"other_runners_{metric}_contribution"].to_numpy(dtype=float)
            total = races[f"top3_marginal_{metric}_saved_tau"].to_numpy(dtype=float)
            mask = races.variant.eq(variant).to_numpy()
            assert np.allclose((top + other)[mask], total[mask], rtol=0, atol=PROB_TOL)

    # Output-only table for ticket overlap and each variant's own U6 state.
    union = races[["race_id", "race_date", "year", "distance_m", "variant", "six_hit",
                   "ticket_overlap_n", "ticket_symmetric_difference_n", "ticket_changed",
                   "ticket_hit_status", "own_six_horse_union_n", "own_six_horse_union_ids",
                   "other_union_overlap_n", "own_only_union_horse_ids", "other_only_union_horse_ids",
                   "all3in_own_union", "union_state"]].copy()
    union = union.rename(columns={
        "ticket_changed": "changed",
        "ticket_hit_status": "hit_both_or_only_or_neither",
    })
    for variant, group in union.groupby("variant", sort=False):
        state_counts = group.union_state.value_counts()
        assert int(state_counts.sum()) == 1779
        assert int(group.all3in_own_union.sum()) == int(
            group.union_state.isin(["hit", "allocation_miss"]).sum())

    results_text = result_summary(races, parity, union, boot, reliability,
                                  contributions, ticket_cross)
    source_lock_after = freeze_inputs()
    if source_lock["source_files"] != source_lock_after["source_files"]:
        raise AssertionError("one or more frozen input hashes changed during analysis")
    if (source_lock["plan_sha256"] != source_lock_after["plan_sha256"] or
            source_lock["data_contract_sha256"] != source_lock_after["data_contract_sha256"]):
        raise AssertionError("approved plan or contract changed during analysis")
    source_lock["input_hashes_unchanged_through_analysis"] = True

    parity_summary = {
        "passed": True,
        "races": 1779,
        "runner_rows_per_variant": 17412,
        "saved_canonical_ticket_rows_total": 21348,
        "probability_absolute_tolerance": PROB_TOL,
        "variants": parity,
        "positive_tau_rank_invariance_checked": True,
        "saved_tau_vs_fixed_tau_1_probability_values_may_change": True,
        "no_model_reload_or_fit": True,
    }

    OUT.mkdir(exist_ok=False)
    write_new_parquet(OUT / "all_triples.parquet", triples)
    write_new_parquet(OUT / "race_diagnostics.parquet", races)
    write_new_csv(OUT / "ticket_and_union_decomposition.csv", union)
    write_new_csv(OUT / "paired_date_bootstrap.csv", boot)
    write_new_csv(OUT / "six_mass_reliability.csv", reliability)
    write_new_csv(OUT / "runner_loss_contributions.csv", contributions)
    write_new_csv(OUT / "ticket_change_loss_cross.csv", ticket_cross)
    write_new_text(OUT / "RESULTS.md", results_text)
    write_new_json(OUT / "parity_verification.json", parity_summary)
    source_lock["analysis_code_sha256"] = sha256(HERE / "analyze.py")
    source_lock["output_contract_sha256"] = sha256(HERE / "data_contract.json")
    source_lock["analysis_parameters"] = {
        "k_values": list(K_VALUES), "saved_tau_and_fixed_tau_1": True,
        "bootstrap_resamples": BOOTSTRAPS, "bootstrap_seed": BOOTSTRAP_SEED,
        "loss_delta_direction": "F1_STYLE6 minus F1",
    }
    write_new_json(OUT / "source_lock.json", source_lock)
    manifest = {
        "status": "complete",
        "study": "20261010_probability_combo_gap_v1",
        "cohort": {"races": 1779, "runner_rows_per_variant": 17412, "race_days": 269,
                   "years": list(YEARS), "partial_year_through": "2026-09-19"},
        "outputs": {path.name: file_record(path) for path in sorted(OUT.iterdir()) if path.is_file()},
        "source_lock_sha256": sha256(OUT / "source_lock.json"),
    }
    write_new_json(OUT / "MANIFEST.json", manifest)
    print(json.dumps({"status": "complete", "outputs": str(OUT),
                      "all_triples_rows": int(len(triples)),
                      "race_diagnostics_rows": int(len(races)),
                      "paired_bootstrap_rows": int(len(boot)),
                      "parity": parity_summary}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("analyze", help="analyze the frozen saved scores and write new outputs")
    args = parser.parse_args()
    if args.command == "analyze":
        run_analysis()
    else:
        parser.error("unknown command")


if __name__ == "__main__":
    main()
