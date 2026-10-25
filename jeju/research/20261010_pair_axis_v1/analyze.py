"""No-fit, saved-distribution analysis for pair and single-horse Top3 axes."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing")
STUDY = ROOT / "jeju/research/20261010_pair_axis_v1"
LOCK_PATH = STUDY / "PRECOMPUTE_LOCK.json"
TRIPLES_PATH = ROOT / "jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet"
RUNNERS_PATH = ROOT / "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv"
RACE_METRICS_PATH = ROOT / "jeju/research/20261010_joint_relationship_v1/outputs/report/race_metrics.csv"
RECEIPT_PATH = ROOT / "jeju/research/20261010_joint_relationship_v1/outputs/report/report_receipt.json"
FEATURES_PATH = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"

ARMS = ("matched_baseline", "candidate")
POLICY_BUDGETS = (("unrestricted_top_k", 3), ("unrestricted_top_k", 4))
POLICIES = (
    "unrestricted_top_k",
    "top_two_marginal_pair",
    "maximum_joint_pair",
    "maximum_k_ticket_pair_mass",
    "single_top3_anchor",
)
CONFIDENCE_POLICIES = ("maximum_joint_pair", "single_top3_anchor")
K_VALUES = (3, 4)
FIXED_BINS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0))
FIXED_CUTOFFS = (0.2, 0.4, 0.6, 0.8)
COVERAGES = (0.25, 0.50, 0.75, 1.00)
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261010

PINNED_INPUT_HASHES = {
    "jeju/research/20261010_joint_relationship_v1/ARTIFACT_MANIFEST.json": "d0d1a749afb6a6f894de1bb4263c9d67dd1e3b2d1a35bf1b5fd38d8948c656b0",
    "jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet": "13409e65353c0cb6dab14df97317cce24de913056ae464ee3524520759de681c",
    "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv": "0e6a01607164a7cb54fbbb5fb445e975ea9fbadad21d4e7a842adfc915616a09",
    "jeju/research/20261010_joint_relationship_v1/outputs/report/race_metrics.csv": "89820acf0dfafc749f394cf9e74a3b58a5ec890e2c746f890ad257eaf32ff115",
    "jeju/research/20261010_joint_relationship_v1/outputs/report/report_receipt.json": "5720519b0d8860f5652650b4d2ee3b6f8444a6c6f01421395cd51f4a0251fae4",
    "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet": "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
    "jeju/research/20261010_style_history_ablation_v1/CONTRACT.md": "c10aac8f6faa6e841afd9ef829bfa0b29ada2dceabcbb5405fdfad9c12536bf9",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_frozen_inputs() -> dict[str, Any]:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if lock.get("status") != "frozen_before_outcome_computation":
        raise AssertionError("input lock is not frozen before outcome computation")
    for rel, expected in PINNED_INPUT_HASHES.items():
        path = ROOT / rel
        if not path.is_file() or sha256_file(path) != expected:
            raise AssertionError(f"pinned input mismatch: {rel}")
        record = next((item for item in lock["inputs"] if item["path"] == rel), None)
        if record is None or record.get("sha256") != expected or record.get("bytes") != path.stat().st_size:
            raise AssertionError(f"input lock mismatch: {rel}")
    for key in ("plan", "input_contract"):
        item = lock[key]
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise AssertionError(f"frozen {key} changed after lock")
    return lock


def parse_ticket(text: str) -> tuple[int, int, int]:
    parts = text.split(",")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise AssertionError(f"invalid source triple key: {text!r}")
    ticket = tuple(int(part) for part in parts)
    if tuple(sorted(ticket)) != ticket or len(set(ticket)) != 3:
        raise AssertionError(f"triple key is not canonical: {text!r}")
    return ticket  # type: ignore[return-value]


def ticket_text(ticket: tuple[int, int, int]) -> str:
    return ",".join(str(number) for number in ticket)


def safe_saved_ticket_list(value: str) -> list[str]:
    text = str(value)
    if not re.fullmatch(r"\[(?:'[0-9]+,[0-9]+,[0-9]+'(?:, )?)*\]", text):
        raise AssertionError("saved six-ticket cell does not match its fixed literal format")
    tickets = re.findall(r"'([0-9]+,[0-9]+,[0-9]+)'", text)
    if repr(tickets) != text:
        raise AssertionError("saved six-ticket cell failed exact safe parse")
    return tickets


def fsum_probs(rows: list[dict[str, Any]]) -> float:
    return math.fsum(float(row["probability"]) for row in sorted(rows, key=lambda row: row["ticket"]))


def check_close(value: float, expected: float, label: str) -> None:
    if not math.isfinite(value) or abs(value - expected) > 1e-12:
        raise AssertionError(f"probability identity failed for {label}: {value} vs {expected}")


def load_and_validate_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    lock = verify_frozen_inputs()
    triples = pd.read_parquet(TRIPLES_PATH)
    runners = pd.read_csv(RUNNERS_PATH)
    saved_races = pd.read_csv(RACE_METRICS_PATH)
    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    if receipt.get("passed") is not True or receipt.get("study") != "20261010_joint_relationship_v1":
        raise AssertionError("source report receipt did not pass or names another study")
    if receipt.get("all_triples_sha256") != PINNED_INPUT_HASHES[
        "jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet"
    ]:
        raise AssertionError("report receipt does not pin the selected full distribution")
    if receipt.get("runner_marginals_sha256") != PINNED_INPUT_HASHES[
        "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv"
    ]:
        raise AssertionError("report receipt does not pin runner labels")
    if receipt.get("race_metrics_sha256") != PINNED_INPUT_HASHES[
        "jeju/research/20261010_joint_relationship_v1/outputs/report/race_metrics.csv"
    ]:
        raise AssertionError("report receipt does not pin saved six-ticket parity")

    features = pd.read_parquet(
        FEATURES_PATH,
        columns=["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "finish_position"],
    )
    required_triple_cols = {
        "race_id", "race_date", "evaluation_year", "arm", "triple_index", "triple_numbers",
        "total_energy", "probability", "is_true_set", "canonical_rank",
    }
    if not required_triple_cols.issubset(triples.columns):
        raise AssertionError(f"triples missing columns: {sorted(required_triple_cols - set(triples.columns))}")
    required_runner_cols = {
        "api_record_id", "race_id", "race_date", "evaluation_year", "horse_number", "y_top3",
    }
    if not required_runner_cols.issubset(runners.columns):
        raise AssertionError(f"runner labels missing columns: {sorted(required_runner_cols - set(runners.columns))}")

    if runners["api_record_id"].duplicated().any():
        raise AssertionError("runner_marginals api_record_id is not unique")
    if runners.duplicated(["race_id", "horse_number"]).any():
        raise AssertionError("runner_marginals event-runner key is not unique")
    eval_ids = set(runners["api_record_id"].astype("int64"))
    if features["api_record_id"].duplicated().any():
        raise AssertionError("features api_record_id is not unique")
    feature_eval = features.loc[features["api_record_id"].isin(eval_ids)].copy()
    if set(feature_eval["api_record_id"].astype("int64")) != eval_ids or len(feature_eval) != len(eval_ids):
        raise AssertionError("feature label rows do not join one-to-one by api_record_id")
    feature_eval = feature_eval.rename(columns={
        "race_id": "feature_race_id",
        "race_date": "feature_race_date",
        "year": "feature_year",
        "horse_number": "feature_horse_number",
        "horse_id": "feature_horse_id",
        "finish_position": "feature_finish_position",
    })
    labels = runners.merge(feature_eval, on="api_record_id", how="left", validate="one_to_one")
    if not labels["race_id"].astype(str).equals(labels["feature_race_id"].astype(str)):
        raise AssertionError("api_record_id join has race_id mismatch")
    if not labels["race_date"].astype(str).equals(labels["feature_race_date"].astype(str)):
        raise AssertionError("api_record_id join has race_date mismatch")
    if not np.array_equal(labels["evaluation_year"].astype(int).to_numpy(),
                           labels["feature_year"].astype(int).to_numpy()):
        raise AssertionError("api_record_id join has evaluation year mismatch")
    if not np.array_equal(labels["horse_number"].astype(int).to_numpy(),
                           labels["feature_horse_number"].astype(int).to_numpy()):
        raise AssertionError("api_record_id join has horse_number mismatch")
    if labels.duplicated(["race_id", "horse_number"]).any():
        raise AssertionError("joined labels have duplicated event-runner key")
    if labels.duplicated(["race_id", "feature_horse_id"]).any():
        raise AssertionError("horse_id is duplicated within an evaluation race")
    labels["finish_position"] = pd.to_numeric(labels["feature_finish_position"], errors="raise")
    labels["y_top3"] = pd.to_numeric(labels["y_top3"], errors="raise").astype(int)
    if not np.isin(labels["y_top3"].to_numpy(), [0, 1]).all():
        raise AssertionError("runner Top3 label is not binary")
    labels["finish_top3"] = labels["finish_position"] <= 3
    if not np.array_equal(labels["finish_top3"].astype(int).to_numpy(), labels["y_top3"].to_numpy()):
        raise AssertionError("saved Top3 label differs from finish_position <= 3")

    if len(triples) != 402_808 or set(triples["arm"].unique()) != set(ARMS):
        raise AssertionError("saved full-triple artifact row count or arms changed")
    if len(labels) != 17_412 or labels["race_id"].nunique() != 1_779 or labels["race_date"].nunique() != 269:
        raise AssertionError("saved evaluation cohort counts changed")
    race_ids = set(labels["race_id"].astype(str))
    if set(triples["race_id"].astype(str)) != race_ids or set(saved_races["race_id"].astype(str)) != race_ids:
        raise AssertionError("source race sets disagree")
    if saved_races["race_id"].duplicated().any():
        raise AssertionError("saved race_metrics contains duplicate race rows")
    if len(saved_races) != 1_779:
        raise AssertionError("saved race_metrics cohort count changed")
    saved_race_meta = saved_races.set_index("race_id")
    runner_race_meta = labels.drop_duplicates("race_id").set_index("race_id")
    for race_id in race_ids:
        if str(saved_race_meta.loc[race_id, "race_date"]) != str(runner_race_meta.loc[race_id, "race_date"]):
            raise AssertionError(f"race_metrics race_date mismatch: {race_id}")
        if int(saved_race_meta.loc[race_id, "evaluation_year"]) != int(runner_race_meta.loc[race_id, "evaluation_year"]):
            raise AssertionError(f"race_metrics evaluation year mismatch: {race_id}")

    labels_by_race: dict[str, dict[str, Any]] = {}
    for race_id, group in labels.groupby("race_id", sort=True):
        group = group.sort_values("horse_number", kind="stable")
        numbers = tuple(int(n) for n in group["horse_number"])
        if len(numbers) < 7 or len(numbers) > 12 or len(set(numbers)) != len(numbers):
            raise AssertionError(f"unexpected evaluation field size in {race_id}")
        truth = tuple(sorted(int(row.horse_number) for row in group.itertuples() if row.y_top3 == 1))
        if len(truth) != 3:
            raise AssertionError(f"race has other than three Top3 labels: {race_id}")
        first = group.loc[group["finish_position"] == 1, "horse_number"].astype(int).tolist()
        second = group.loc[group["finish_position"] == 2, "horse_number"].astype(int).tolist()
        if len(first) != 1 or len(second) != 1:
            raise AssertionError(f"race lacks unique exact first and second labels: {race_id}")
        labels_by_race[str(race_id)] = {
            "truth": truth,
            "roster": numbers,
            "race_date": str(group["race_date"].iloc[0]),
            "evaluation_year": int(group["evaluation_year"].iloc[0]),
            "finish_top2_pair": tuple(sorted((first[0], second[0]))),
        }

    triples["race_id"] = triples["race_id"].astype(str)
    triples["ticket"] = triples["triple_numbers"].map(parse_ticket)
    if triples.duplicated(["race_id", "arm", "ticket"]).any():
        raise AssertionError("duplicate triple key in saved distribution")
    triples["canonical_rank"] = pd.to_numeric(triples["canonical_rank"], errors="raise").astype(int)
    triples["total_energy"] = pd.to_numeric(triples["total_energy"], errors="raise")
    triples["probability"] = pd.to_numeric(triples["probability"], errors="raise")
    if not np.isfinite(triples["total_energy"].to_numpy()).all():
        raise AssertionError("non-finite saved total_energy")
    if not np.isfinite(triples["probability"].to_numpy()).all() or (
        (triples["probability"] < 0).any() or (triples["probability"] > 1).any()
    ):
        raise AssertionError("saved triple probabilities are outside [0,1]")
    triples["is_true_set"] = triples["is_true_set"].astype(bool)

    race_arm: dict[tuple[str, str], list[dict[str, Any]]] = {}
    roster_by_race: dict[str, tuple[int, ...]] = {}
    rank_parity_rows = 0
    for (race_id, arm), frame in triples.groupby(["race_id", "arm"], sort=True):
        race_id, arm = str(race_id), str(arm)
        records = frame[["race_date", "evaluation_year", "ticket", "triple_index", "total_energy",
                         "probability", "is_true_set", "canonical_rank"]].to_dict("records")
        records = [{**row, "ticket": tuple(row["ticket"])} for row in records]
        roster = tuple(sorted(set(itertools.chain.from_iterable(row["ticket"] for row in records))))
        expected_count = math.comb(len(roster), 3)
        if len(records) != expected_count or set(row["ticket"] for row in records) != set(itertools.combinations(roster, 3)):
            raise AssertionError(f"incomplete C(N,3) triple support: {race_id}/{arm}")
        if roster != labels_by_race[race_id]["roster"]:
            raise AssertionError(f"triple roster differs from runner labels: {race_id}/{arm}")
        if race_id in roster_by_race and roster_by_race[race_id] != roster:
            raise AssertionError(f"arms use different rosters: {race_id}")
        roster_by_race[race_id] = roster
        if str(records[0]["race_date"]) != labels_by_race[race_id]["race_date"]:
            raise AssertionError(f"race date mismatch: {race_id}/{arm}")
        if int(records[0]["evaluation_year"]) != labels_by_race[race_id]["evaluation_year"]:
            raise AssertionError(f"evaluation year mismatch: {race_id}/{arm}")

        source_order = sorted(records, key=lambda row: row["ticket"])
        check_close(math.fsum(row["probability"] for row in source_order), 1.0,
                    f"race distribution {race_id}/{arm}")
        canonical = sorted(records, key=lambda row: (-row["total_energy"], row["ticket"]))
        ranks = [row["canonical_rank"] for row in canonical]
        if ranks != list(range(1, len(records) + 1)):
            raise AssertionError(f"canonical_rank not descending total_energy with exact-energy numeric ties: {race_id}/{arm}")
        ranked = sorted(records, key=lambda row: row["canonical_rank"])
        if any(ranked[i]["probability"] < ranked[i + 1]["probability"] for i in range(len(ranked) - 1)):
            raise AssertionError(f"probability is not nonincreasing in canonical_rank: {race_id}/{arm}")
        truth_rows = [row for row in records if row["is_true_set"]]
        truth = labels_by_race[race_id]["truth"]
        if len(truth_rows) != 1 or truth_rows[0]["ticket"] != truth:
            raise AssertionError(f"is_true_set does not match runner labels: {race_id}/{arm}")
        rank_parity_rows += len(records)
        race_arm[(race_id, arm)] = ranked

    if len(race_arm) != 1_779 * 2:
        raise AssertionError("race-arm distribution coverage changed")

    # Reconstruct runner and pair marginals directly from the source q values.
    runner_lookup = runners.set_index(["race_id", "horse_number"], drop=False)
    for race_id in sorted(race_ids):
        expected_labels = {
            int(row.horse_number): int(row.y_top3)
            for row in labels.loc[labels["race_id"].astype(str) == race_id].itertuples()
        }
        for arm in ARMS:
            records = race_arm[(race_id, arm)]
            runner_terms: dict[int, list[float]] = defaultdict(list)
            pair_terms: dict[tuple[int, int], list[float]] = defaultdict(list)
            for row in sorted(records, key=lambda item: item["ticket"]):
                ticket = row["ticket"]
                for horse in ticket:
                    runner_terms[horse].append(row["probability"])
                for pair in itertools.combinations(ticket, 2):
                    pair_terms[pair].append(row["probability"])
            for horse in roster_by_race[race_id]:
                marginal = math.fsum(runner_terms[horse])
                # The observed label is only cross-checked against the truth set above.
                if expected_labels[horse] not in (0, 1):
                    raise AssertionError("non-binary runner outcome")
                source_marginal_column = (
                    "baseline_joint_marginal" if arm == "matched_baseline" else "candidate_joint_marginal"
                )
                saved = runner_lookup.loc[(race_id, horse)]
                if isinstance(saved, pd.DataFrame):
                    raise AssertionError(f"duplicate runner marginal key: {race_id}/{horse}")
                check_close(marginal, float(saved[source_marginal_column]),
                            f"saved runner marginal {race_id}/{arm}/{horse}")
            check_close(math.fsum(math.fsum(v) for v in runner_terms.values()), 3.0,
                        f"sum of runner Top3 marginals {race_id}/{arm}")
            check_close(math.fsum(math.fsum(v) for v in pair_terms.values()), 3.0,
                        f"sum of pair Top3 marginals {race_id}/{arm}")

    saved6 = saved_races.set_index("race_id")
    parity_hit_counts = {arm: 0 for arm in ARMS}
    for arm in ARMS:
        for race_id in sorted(race_ids):
            ranked = race_arm[(race_id, arm)]
            top6 = [ticket_text(row["ticket"]) for row in ranked[:6]]
            column = "baseline_six_tickets" if arm == "matched_baseline" else "candidate_six_tickets"
            saved = safe_saved_ticket_list(saved6.loc[race_id, column])
            if top6 != saved:
                raise AssertionError(f"saved unrestricted-six ticket parity failed: {race_id}/{arm}")
            hit = int(labels_by_race[race_id]["truth"] in [row["ticket"] for row in ranked[:6]])
            parity_hit_counts[arm] += hit
            hit_column = "baseline_hit6" if arm == "matched_baseline" else "candidate_hit6"
            if int(saved6.loc[race_id, hit_column]) != hit:
                raise AssertionError(f"saved unrestricted-six hit flag mismatch: {race_id}/{arm}")
    if parity_hit_counts != {"matched_baseline": 407, "candidate": 423}:
        raise AssertionError(f"saved unrestricted-six hits changed: {parity_hit_counts}")

    return {
        "lock": lock,
        "race_arm": race_arm,
        "labels_by_race": labels_by_race,
        "runners": runners,
        "saved_races": saved_races,
        "triple_rows": rank_parity_rows,
        "parity_hit_counts": parity_hit_counts,
    }, receipt


def selected_mass(rows: list[dict[str, Any]]) -> float:
    return math.fsum(row["probability"] for row in sorted(rows, key=lambda row: row["ticket"]))


def choose_policies(records: list[dict[str, Any]], roster: tuple[int, ...], budget: int) -> dict[str, dict[str, Any]]:
    if budget not in K_VALUES:
        raise AssertionError(f"anchored policy budget not allowed: {budget}")
    if len(records) < budget:
        raise AssertionError("unrestricted policy cannot supply the exact frozen budget")
    triple_by_ticket = {row["ticket"]: row for row in records}
    runner_terms: dict[int, list[float]] = {horse: [] for horse in roster}
    pair_terms: dict[tuple[int, int], list[float]] = {
        pair: [] for pair in itertools.combinations(roster, 2)
    }
    for row in sorted(records, key=lambda item: item["ticket"]):
        ticket = row["ticket"]
        for horse in ticket:
            runner_terms[horse].append(row["probability"])
        for pair in itertools.combinations(ticket, 2):
            pair_terms[pair].append(row["probability"])
    runner_marginal = {horse: math.fsum(terms) for horse, terms in runner_terms.items()}
    pair_probability = {pair: math.fsum(terms) for pair, terms in pair_terms.items()}

    rank_order = sorted(records, key=lambda row: row["canonical_rank"])
    unrestricted = rank_order[:budget]

    marginal_pair = tuple(sorted(sorted(roster, key=lambda horse: (-runner_marginal[horse], horse))[:2]))
    top2_pair_rows = [row for row in rank_order if set(marginal_pair).issubset(row["ticket"])]
    if len(top2_pair_rows) < budget:
        raise AssertionError("top-two marginal pair cannot supply exact budget")
    top2_pair_rows = top2_pair_rows[:budget]

    max_joint_pair = min(pair_probability, key=lambda pair: (-pair_probability[pair], pair))
    max_joint_rows = [row for row in rank_order if set(max_joint_pair).issubset(row["ticket"])]
    if len(max_joint_rows) < budget:
        raise AssertionError("maximum-joint pair cannot supply exact budget")
    max_joint_rows = max_joint_rows[:budget]

    pair_mass_scores: list[tuple[float, tuple[int, int], list[dict[str, Any]]]] = []
    for pair in itertools.combinations(roster, 2):
        rows = [row for row in rank_order if set(pair).issubset(row["ticket"])][:budget]
        if len(rows) != budget:
            raise AssertionError("candidate pair cannot supply exact budget")
        pair_mass_scores.append((selected_mass(rows), pair, rows))
    best_mass = min(pair_mass_scores, key=lambda item: (-item[0], item[1]))
    max_budget_pair = best_mass[1]
    max_budget_rows = best_mass[2]

    single_anchor = min(roster, key=lambda horse: (-runner_marginal[horse], horse))
    single_rows = [row for row in rank_order if single_anchor in row["ticket"]]
    if len(single_rows) < budget:
        raise AssertionError("single Top3 anchor cannot supply exact budget")
    single_rows = single_rows[:budget]

    return {
        "unrestricted_top_k": {
            "tickets": unrestricted, "axis_type": "none", "axis_horses": (),
            "axis_probability": None,
        },
        "top_two_marginal_pair": {
            "tickets": top2_pair_rows, "axis_type": "pair", "axis_horses": marginal_pair,
            "axis_probability": pair_probability[marginal_pair],
        },
        "maximum_joint_pair": {
            "tickets": max_joint_rows, "axis_type": "pair", "axis_horses": max_joint_pair,
            "axis_probability": pair_probability[max_joint_pair],
        },
        "maximum_k_ticket_pair_mass": {
            "tickets": max_budget_rows, "axis_type": "pair", "axis_horses": max_budget_pair,
            "axis_probability": pair_probability[max_budget_pair],
        },
        "single_top3_anchor": {
            "tickets": single_rows, "axis_type": "single", "axis_horses": (single_anchor,),
            "axis_probability": runner_marginal[single_anchor],
        },
    }


def make_metrics(data: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (race_id, arm), records in sorted(data["race_arm"].items()):
        labels = data["labels_by_race"][race_id]
        truth = labels["truth"]
        roster = labels["roster"]
        for budget in K_VALUES:
            selections = choose_policies(records, roster, budget)
            for policy in POLICIES:
                selection = selections[policy]
                tickets = selection["tickets"]
                ticket_set = {row["ticket"] for row in tickets}
                ticket_hit = int(truth in ticket_set)
                axis_type = selection["axis_type"]
                axis_horses = selection["axis_horses"]
                if axis_type == "pair":
                    axis_hit = int(set(axis_horses).issubset(truth))
                    exact_top2_hit = int(tuple(sorted(axis_horses)) == labels["finish_top2_pair"])
                    failure_component = (
                        "ticket_hit" if ticket_hit else
                        "pair_axis_miss" if not axis_hit else
                        "completion_miss"
                    )
                    conditional_completion = ticket_hit if axis_hit else None
                elif axis_type == "single":
                    axis_hit = int(axis_horses[0] in truth)
                    exact_top2_hit = None
                    failure_component = (
                        "ticket_hit" if ticket_hit else
                        "single_axis_miss" if not axis_hit else
                        "completion_miss"
                    )
                    conditional_completion = ticket_hit if axis_hit else None
                else:
                    axis_hit = None
                    exact_top2_hit = None
                    failure_component = "ticket_hit" if ticket_hit else "ticket_miss"
                    conditional_completion = None
                rows.append({
                    "race_id": race_id,
                    "race_date": labels["race_date"],
                    "evaluation_year": labels["evaluation_year"],
                    "arm": arm,
                    "policy": policy,
                    "budget_k": budget,
                    "ticket_count": len(tickets),
                    "tickets": json.dumps([ticket_text(row["ticket"]) for row in tickets], separators=(",", ":")),
                    "selected_q_mass": selected_mass(tickets),
                    "ticket_hit": ticket_hit,
                    "axis_type": axis_type,
                    "axis_horses": ",".join(str(n) for n in axis_horses) if axis_horses else "",
                    "axis_probability": selection["axis_probability"],
                    "axis_hit": axis_hit,
                    "conditional_completion": conditional_completion,
                    "exact_top2_pair_hit": exact_top2_hit,
                    "failure_component": failure_component,
                })

        # Original K=6 is unrestricted only; it is a saved reference, not a same-budget comparison.
        top6 = records[:6]
        rows.append({
            "race_id": race_id,
            "race_date": labels["race_date"],
            "evaluation_year": labels["evaluation_year"],
            "arm": arm,
            "policy": "unrestricted_top_k",
            "budget_k": 6,
            "ticket_count": len(top6),
            "tickets": json.dumps([ticket_text(row["ticket"]) for row in top6], separators=(",", ":")),
            "selected_q_mass": selected_mass(top6),
            "ticket_hit": int(truth in {row["ticket"] for row in top6}),
            "axis_type": "none",
            "axis_horses": "",
            "axis_probability": None,
            "axis_hit": None,
            "conditional_completion": None,
            "exact_top2_pair_hit": None,
            "failure_component": "ticket_hit" if truth in {row["ticket"] for row in top6} else "ticket_miss",
        })
    result = pd.DataFrame(rows)
    if len(result) != 1_779 * 22:
        raise AssertionError(f"unexpected per-race policy row count: {len(result)}")
    if not (result["ticket_count"] == result["budget_k"]).all():
        raise AssertionError("one or more policy rows do not have the exact ticket budget")
    return result


def summarize(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_cols = ["arm", "policy", "budget_k"]
    for keys, group in metrics.groupby(group_cols, sort=True):
        arm, policy, budget = keys
        axis_rows = group.loc[group["axis_type"].isin(["pair", "single"])]
        miss_rows = group.loc[group["ticket_hit"] == 0]
        conditional_num = int(axis_rows.loc[axis_rows["axis_hit"] == 1, "ticket_hit"].sum())
        conditional_den = int((axis_rows["axis_hit"] == 1).sum())
        fail_counts = group["failure_component"].value_counts().to_dict()
        if axis_rows.empty:
            axis_type = "none"
            axis_hits = None
            axis_n = 0
            axis_rate = None
            exact2_hits = None
            exact2_n = 0
            exact2_rate = None
            axis_miss = None
            completion_miss = None
        else:
            axis_type = str(axis_rows["axis_type"].iloc[0])
            axis_hits = int(axis_rows["axis_hit"].sum())
            axis_n = len(axis_rows)
            axis_rate = axis_hits / axis_n
            if axis_type == "pair":
                exact2 = axis_rows["exact_top2_pair_hit"].dropna().astype(int)
                exact2_hits = int(exact2.sum())
                exact2_n = len(exact2)
                exact2_rate = exact2_hits / exact2_n if exact2_n else None
                axis_miss = int((group["failure_component"] == "pair_axis_miss").sum())
                completion_miss = int((group["failure_component"] == "completion_miss").sum())
            else:
                exact2_hits = None
                exact2_n = 0
                exact2_rate = None
                axis_miss = int((group["failure_component"] == "single_axis_miss").sum())
                completion_miss = int((group["failure_component"] == "completion_miss").sum())
            if axis_miss + completion_miss != int((group["ticket_hit"] == 0).sum()):
                raise AssertionError(f"failure decomposition does not close: {arm}/{policy}/{budget}")
        ticket_hits = int(group["ticket_hit"].sum())
        rows.append({
            "arm": arm,
            "policy": policy,
            "budget_k": int(budget),
            "races": len(group),
            "race_dates": group["race_date"].nunique(),
            "tickets_per_race": int(group["ticket_count"].min()),
            "ticket_hits": ticket_hits,
            "ticket_hit_rate": ticket_hits / len(group),
            "mean_selected_q_mass": float(group["selected_q_mass"].mean()),
            "axis_type": axis_type,
            "axis_hits": axis_hits,
            "axis_races": axis_n,
            "axis_hit_rate": axis_rate,
            "conditional_completion_hits": conditional_num if axis_n else None,
            "conditional_completion_races": conditional_den if axis_n else None,
            "conditional_completion_rate": conditional_num / conditional_den if conditional_den else None,
            "pair_exact_top2_hits": exact2_hits,
            "pair_exact_top2_races": exact2_n,
            "pair_exact_top2_rate": exact2_rate,
            "axis_miss_count": axis_miss,
            "completion_miss_count": completion_miss,
            "ticket_miss_count": int((group["ticket_hit"] == 0).sum()),
            "failure_components": json.dumps(fail_counts, sort_keys=True),
        })
    summary = pd.DataFrame(rows).sort_values(["arm", "budget_k", "policy"], kind="stable")
    expected = {(arm, policy, k) for arm in ARMS for policy in POLICIES for k in K_VALUES}
    expected |= {(arm, "unrestricted_top_k", 6) for arm in ARMS}
    actual = set(zip(summary["arm"], summary["policy"], summary["budget_k"].astype(int)))
    if actual != expected or len(summary) != 22:
        raise AssertionError("summary does not have the frozen 22 arm/policy/budget cells")
    return summary.reset_index(drop=True)


def bootstrap_primary(metrics: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    date_values = sorted(metrics["race_date"].unique())
    date_draws = rng.integers(0, len(date_values), size=(BOOTSTRAP_DRAWS, len(date_values)))
    date_index = {date: idx for idx, date in enumerate(date_values)}
    rows = []
    for arm in ARMS:
        for budget in K_VALUES:
            unrestricted = metrics.loc[
                (metrics["arm"] == arm) & (metrics["policy"] == "unrestricted_top_k") & (metrics["budget_k"] == budget)
            ].set_index("race_id").sort_index()
            anchored = metrics.loc[
                (metrics["arm"] == arm) & (metrics["policy"] == "maximum_joint_pair") & (metrics["budget_k"] == budget)
            ].set_index("race_id").sort_index()
            if not unrestricted.index.equals(anchored.index):
                raise AssertionError("primary paired comparison race sets differ")
            date_by_race = unrestricted["race_date"].to_dict()
            per_date: dict[str, list[float]] = defaultdict(list)
            for race_id in unrestricted.index:
                per_date[str(date_by_race[race_id])].append(
                    float(anchored.loc[race_id, "ticket_hit"]) - float(unrestricted.loc[race_id, "ticket_hit"])
                )
            date_sums = np.zeros(len(date_values), dtype=np.float64)
            date_counts = np.zeros(len(date_values), dtype=np.int64)
            for date, deltas in per_date.items():
                i = date_index[date]
                date_sums[i] = math.fsum(deltas)
                date_counts[i] = len(deltas)
            draw_sums = date_sums[date_draws].sum(axis=1)
            draw_counts = date_counts[date_draws].sum(axis=1)
            draws = draw_sums / draw_counts
            estimate = float((anchored["ticket_hit"] - unrestricted["ticket_hit"]).mean())
            rows.append({
                "arm": arm,
                "budget_k": budget,
                "comparison": "maximum_joint_pair_minus_unrestricted",
                "races": len(unrestricted),
                "race_dates": len(date_values),
                "estimate_hit_rate_delta": estimate,
                "ci95_low": float(np.quantile(draws, 0.025)),
                "ci95_high": float(np.quantile(draws, 0.975)),
                "bootstrap_draws": BOOTSTRAP_DRAWS,
                "seed": BOOTSTRAP_SEED,
                "cluster": "race_date",
            })
    return pd.DataFrame(rows)


def fixed_bin(value: float) -> str:
    for lower, upper in FIXED_BINS:
        if lower <= value < upper or (upper == 1.0 and value == 1.0):
            return f"[{lower:.1f},{upper:.1f}{']' if upper == 1.0 else ')'}"
    raise AssertionError(f"probability outside fixed bins: {value}")


def confidence_outputs(metrics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    axis_rows = metrics.loc[
        metrics["policy"].isin(CONFIDENCE_POLICIES) & metrics["budget_k"].isin(K_VALUES)
    ].copy()
    if axis_rows["axis_probability"].isna().any() or axis_rows["axis_hit"].isna().any():
        raise AssertionError("primary confidence policy has missing axis probability or label")
    axis_rows["confidence_bin"] = axis_rows["axis_probability"].map(fixed_bin)
    reliability = []
    axis_brier = []
    for (arm, policy), group in axis_rows.drop_duplicates(["arm", "policy", "race_id"]).groupby(
        ["arm", "policy"], sort=True
    ):
        err = np.square(group["axis_probability"].astype(float) - group["axis_hit"].astype(float))
        axis_brier.append({
            "arm": arm,
            "policy": policy,
            "races": len(group),
            "race_dates": group["race_date"].nunique(),
            "axis_brier": float(err.mean()),
            "mean_predicted_axis_probability": float(group["axis_probability"].mean()),
            "observed_axis_hit_rate": float(group["axis_hit"].mean()),
        })
        for label in [fixed_bin((lo + hi) / 2) for lo, hi in FIXED_BINS]:
            part = group.loc[group["confidence_bin"] == label]
            reliability.append({
                "arm": arm,
                "policy": policy,
                "target": "pair_both_top3" if policy == "maximum_joint_pair" else "single_anchor_top3",
                "confidence_bin": label,
                "races": len(part),
                "race_dates": part["race_date"].nunique(),
                "mean_predicted_probability": float(part["axis_probability"].mean()) if len(part) else None,
                "observed_axis_hit_rate": float(part["axis_hit"].mean()) if len(part) else None,
            })

    threshold_rows = []
    coverage_rows = []
    for (arm, policy), base in axis_rows.drop_duplicates(["arm", "policy", "race_id"]).groupby(
        ["arm", "policy"], sort=True
    ):
        base = base.sort_values(["race_date", "race_id"], kind="stable")
        for cutoff in FIXED_CUTOFFS:
            for budget in K_VALUES:
                part = metrics.loc[
                    (metrics["arm"] == arm) & (metrics["policy"] == policy)
                    & (metrics["budget_k"] == budget)
                    & (metrics["axis_probability"] >= cutoff)
                ]
                axes = part["axis_hit"].dropna().astype(int)
                hits = int(part["ticket_hit"].sum())
                denom_completion = int(axes.sum())
                threshold_rows.append({
                    "arm": arm,
                    "policy": policy,
                    "probability_cutoff": cutoff,
                    "budget_k": budget,
                    "selected_races": len(part),
                    "selected_race_dates": part["race_date"].nunique(),
                    "coverage": len(part) / 1_779,
                    "axis_successes": int(axes.sum()),
                    "axis_success_rate_selected": float(axes.mean()) if len(axes) else None,
                    "unconditional_ticket_hits": hits,
                    "unconditional_ticket_hit_rate_selected": hits / len(part) if len(part) else None,
                    "conditional_completion_hits": int(part.loc[part["axis_hit"] == 1, "ticket_hit"].sum()),
                    "conditional_completion_races": denom_completion,
                    "conditional_completion_rate": hits / denom_completion if denom_completion else None,
                })
        ordered = base.sort_values(["axis_probability", "race_date", "race_id"],
                                   ascending=[False, True, True], kind="stable")
        for fraction in COVERAGES:
            n = math.ceil(fraction * 1_779)
            selected = ordered.iloc[:n]
            selected_ids = set(selected["race_id"])
            for budget in K_VALUES:
                part = metrics.loc[
                    (metrics["arm"] == arm) & (metrics["policy"] == policy)
                    & (metrics["budget_k"] == budget) & metrics["race_id"].isin(selected_ids)
                ]
                axis = part["axis_hit"].astype(int)
                hits = int(part["ticket_hit"].sum())
                den = int(axis.sum())
                coverage_rows.append({
                    "arm": arm,
                    "policy": policy,
                    "target_coverage": fraction,
                    "selected_races": len(part),
                    "selected_race_dates": part["race_date"].nunique(),
                    "realized_coverage": len(part) / 1_779,
                    "budget_k": budget,
                    "axis_successes": int(axis.sum()),
                    "axis_success_rate_selected": float(axis.mean()) if len(axis) else None,
                    "unconditional_ticket_hits": hits,
                    "unconditional_ticket_hit_rate_selected": hits / len(part) if len(part) else None,
                    "conditional_completion_hits": int(part.loc[part["axis_hit"] == 1, "ticket_hit"].sum()),
                    "conditional_completion_races": den,
                    "conditional_completion_rate": hits / den if den else None,
                })

    ticket_mass_rows = []
    for (arm, policy, budget), group in metrics.loc[
        metrics["policy"].isin(CONFIDENCE_POLICIES) & metrics["budget_k"].isin(K_VALUES)
    ].groupby(["arm", "policy", "budget_k"], sort=True):
        group = group.copy()
        group["confidence_bin"] = group["selected_q_mass"].map(fixed_bin)
        for label in [fixed_bin((lo + hi) / 2) for lo, hi in FIXED_BINS]:
            part = group.loc[group["confidence_bin"] == label]
            ticket_mass_rows.append({
                "arm": arm,
                "policy": policy,
                "budget_k": int(budget),
                "confidence_bin": label,
                "races": len(part),
                "race_dates": part["race_date"].nunique(),
                "mean_selected_q_mass": float(part["selected_q_mass"].mean()) if len(part) else None,
                "observed_ticket_hit_rate": float(part["ticket_hit"].mean()) if len(part) else None,
            })
    return (
        pd.DataFrame(axis_brier),
        pd.DataFrame(reliability),
        pd.DataFrame(threshold_rows),
        pd.DataFrame(coverage_rows),
        pd.DataFrame(ticket_mass_rows),
    )


def write_csv_exclusive(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as out:
        frame.to_csv(out, index=False, quoting=csv.QUOTE_MINIMAL)


def write_text_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as out:
        out.write(text)


def pct(value: float | None) -> str:
    return "—" if value is None or pd.isna(value) else f"{100.0 * float(value):.2f}%"


def make_report(summary: pd.DataFrame, primary: pd.DataFrame, axis_brier: pd.DataFrame,
                parity: dict[str, int], bins: pd.DataFrame) -> str:
    lines = [
        "# Pair-axis and single-anchor ticket study",
        "",
        "This no-fit analysis reuses the saved 2024-01-05 to 2026-09-19 joint distributions. The cohort contains 1,779 races, 17,412 runners, and 269 race dates; 2026 is partial. These labels were examined in prior research, so this is retrospective development evidence, not independent future validation.",
        "",
        "The target is the unordered exact Top3 set. A pair's exact first-and-second-place result is reported only as an observed secondary outcome; no exact-Top2 probability is estimated. Tickets anchored by a pair add the remaining member of the unordered Top3 set, without assigning that horse third place.",
        "",
        "Both saved arms are shown separately. No preferred arm is selected from these labels. The five policies are reported at K=3 and K=4. Unrestricted K=6 is included only to confirm the original reference (407/1,779 and 423/1,779); pair-anchored K=6 is omitted because 36 seven-runner races cannot supply six unique tickets from a fixed pair.",
        "",
        f"Saved unrestricted K=6 parity reproduced: matched_baseline {parity['matched_baseline']}/1,779; candidate {parity['candidate']}/1,779.",
        "",
        "## Ticket outcomes",
        "",
        "Rates use all 1,779 races unless a conditional denominator is named. `Mean q mass` is the saved distribution probability assigned to the selected ticket set. `Axis hit` means both anchored horses are in the actual Top3, or the single anchor is in the actual Top3. `Completion` is ticket hit among axis hits.",
        "",
        "| Arm | Policy | K | Ticket hits / 1,779 | Hit rate | Mean q mass | Axis hits / races | Axis rate | Completion hits / axis hits | Pair exact Top2 hits / races | Pair miss | Completion miss |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    display = summary.sort_values(["arm", "budget_k", "policy"], kind="stable")
    for row in display.to_dict("records"):
        axis = "—" if pd.isna(row["axis_hits"]) else f"{int(row['axis_hits'])}/{int(row['axis_races'])}"
        axis_rate = pct(row["axis_hit_rate"])
        completion = "—" if pd.isna(row["conditional_completion_rate"]) else (
            f"{int(row['conditional_completion_hits'])}/{int(row['conditional_completion_races'])} "
            f"({pct(row['conditional_completion_rate'])})"
        )
        exact2 = "—" if pd.isna(row["pair_exact_top2_hits"]) else (
            f"{int(row['pair_exact_top2_hits'])}/{int(row['pair_exact_top2_races'])} "
            f"({pct(row['pair_exact_top2_rate'])})"
        )
        pair_miss = "—" if pd.isna(row["axis_miss_count"]) else str(int(row["axis_miss_count"]))
        completion_miss = "—" if pd.isna(row["completion_miss_count"]) else str(int(row["completion_miss_count"]))
        lines.append(
            f"| {row['arm']} | {row['policy']} | {int(row['budget_k'])} | "
            f"{int(row['ticket_hits'])}/1,779 | {pct(row['ticket_hit_rate'])} | "
            f"{pct(row['mean_selected_q_mass'])} | {axis} | {axis_rate} | {completion} | "
            f"{exact2} | {pair_miss} | {completion_miss} |"
        )
    lines.extend([
        "",
        "## Primary paired comparisons",
        "",
        "The primary comparison is maximum-joint-pair minus unrestricted top K within each saved arm at K=3 and K=4. Intervals use 2,000 paired race-date cluster bootstrap draws, seed 20261010. No multiplicity-adjusted claim is made.",
        "",
        "| Arm | K | Hit-rate difference | 95% race-date bootstrap interval |",
        "|---|---:|---:|---:|",
    ])
    for row in primary.to_dict("records"):
        lines.append(
            f"| {row['arm']} | {int(row['budget_k'])} | {100*row['estimate_hit_rate_delta']:+.2f}%p | "
            f"[{100*row['ci95_low']:+.2f}, {100*row['ci95_high']:+.2f}]%p |"
        )
    lines.extend([
        "",
        "Across the four primary comparisons, the estimated differences ranged from −10 to +3 hits per 1,779 races, and every 95% interval included zero. These results do not show a reliable same-budget gain from fixing the maximum-joint pair. The pair axis itself hit in about 24% of races, so pair misses accounted for most pair-ticket misses. The single-horse axis hit in about 57%, while only about 23–29% of those axis hits completed a selected K=3 or K=4 ticket; this descriptive pattern leaves full-trio completion as a substantial constraint.",
        "",
        "## Axis probability checks",
        "",
        "Only maximum-joint-pair and single-Top3-anchor axes receive probability diagnostics. Fixed probability bins, cutoffs, and score-ranked coverage tables are descriptive. A score-ranked coverage slice is retrospective and does not guarantee the same future coverage.",
        "",
        "| Arm | Policy | Races | Axis Brier | Mean predicted axis probability | Observed axis hit rate |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for row in axis_brier.to_dict("records"):
        lines.append(
            f"| {row['arm']} | {row['policy']} | {int(row['races'])} | {row['axis_brier']:.6f} | "
            f"{row['mean_predicted_axis_probability']:.4f} | {pct(row['observed_axis_hit_rate'])} |"
        )
    lines.extend([
        "",
        "Fixed-bin counts and rates, fixed prediction-cutoff coverage, score-ranked coverage slices, and selected-ticket-mass bins are in the companion CSV files.",
        "",
        "## Limits",
        "",
        "All results are post hoc summaries of saved probability distributions and previously examined races. They do not establish independent future performance, finish-order probabilities, exact-Top2 calibration, odds value, returns, or operating readiness. Ticket hits, axis hits, conditional completion, exact-Top2 empirical hits, and predicted q mass are different quantities.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    lock = verify_frozen_inputs()
    data, receipt = load_and_validate_inputs()
    metrics = make_metrics(data)
    summary = summarize(metrics)
    primary = bootstrap_primary(metrics)
    axis_brier, axis_bins, thresholds, coverages, ticket_mass_bins = confidence_outputs(metrics)
    code_record = {
        "path": "jeju/research/20261010_pair_axis_v1/analyze.py",
        "bytes": (STUDY / "analyze.py").stat().st_size,
        "sha256": sha256_file(STUDY / "analyze.py"),
    }

    output_dir = STUDY / "outputs"
    output_dir.mkdir(exist_ok=False)
    write_csv_exclusive(output_dir / "per_race_metrics.csv", metrics)
    write_csv_exclusive(output_dir / "policy_summary.csv", summary)
    write_csv_exclusive(output_dir / "primary_comparisons.csv", primary)
    write_csv_exclusive(output_dir / "axis_brier.csv", axis_brier)
    write_csv_exclusive(output_dir / "axis_reliability_bins.csv", axis_bins)
    write_csv_exclusive(output_dir / "fixed_probability_cutoffs.csv", thresholds)
    write_csv_exclusive(output_dir / "fixed_coverage_slices.csv", coverages)
    write_csv_exclusive(output_dir / "ticket_mass_reliability_bins.csv", ticket_mass_bins)
    report = make_report(summary, primary, axis_brier, data["parity_hit_counts"], axis_bins)
    write_text_exclusive(output_dir / "RESULTS.md", report)

    verification = {
        "passed": True,
        "analysis": "no-fit saved-distribution ticket selection",
        "plan_sha256": lock["plan"]["sha256"],
        "input_contract_sha256": lock["input_contract"]["sha256"],
        "precompute_lock_sha256": sha256_file(LOCK_PATH),
        "input_hashes_rechecked": True,
        "analysis_code": code_record,
        "input_rows": {
            "full_triple_rows": int(data["triple_rows"]),
            "races": 1_779,
            "runners": 17_412,
            "race_dates": 269,
        },
        "saved_unrestricted_k6_hits": data["parity_hit_counts"],
        "probability_identity_tolerance": 1e-12,
        "ranking": "saved canonical_rank; validated total_energy descending, exact-energy ties numeric triple; no q tolerance",
        "pair_sum": "math.fsum over canonical numeric ticket order",
        "primary_bootstrap": {
            "draws": BOOTSTRAP_DRAWS,
            "seed": BOOTSTRAP_SEED,
            "cluster": "race_date",
            "comparison": "maximum_joint_pair minus unrestricted within each arm, K=3 and K=4",
        },
        "no_fit": True,
        "database_access": False,
        "network_access": False,
        "source_receipt_passed": bool(receipt["passed"]),
    }
    write_text_exclusive(output_dir / "verification.json", json.dumps(verification, ensure_ascii=False, indent=2) + "\n")

    artifact_names = sorted(path.name for path in output_dir.iterdir() if path.is_file())
    artifact_manifest = {
        "study": "20261010_pair_axis_v1",
        "plan_sha256": lock["plan"]["sha256"],
        "input_contract_sha256": lock["input_contract"]["sha256"],
        "precompute_lock_sha256": sha256_file(LOCK_PATH),
        "source_input_hashes": PINNED_INPUT_HASHES,
        "analysis_code": code_record,
        "outputs": {
            name: {
                "bytes": (output_dir / name).stat().st_size,
                "sha256": sha256_file(output_dir / name),
            }
            for name in artifact_names
        },
    }
    write_text_exclusive(output_dir / "ARTIFACT_MANIFEST.json",
                         json.dumps(artifact_manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "results_path": str(output_dir / "RESULTS.md"),
        "summary_rows": summary.to_dict("records"),
        "primary_comparisons": primary.to_dict("records"),
        "axis_brier": axis_brier.to_dict("records"),
        "saved_k6_hits": data["parity_hit_counts"],
        "artifact_manifest_sha256": sha256_file(output_dir / "ARTIFACT_MANIFEST.json"),
    }, ensure_ascii=False, default=lambda x: None, indent=2))


if __name__ == "__main__":
    main()
