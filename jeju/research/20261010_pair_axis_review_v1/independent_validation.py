"""Independent validation of the frozen Jeju pair-axis ticket policies.

This verifier intentionally imports no code from either the A study or the
joint-relationship study. It reads only the immutable files pinned below and
writes only under this independent review directory.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import itertools
import json
import math
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUTPUTS = HERE / "outputs"

SOURCE_HASHES = {
    "jeju/research/20261010_joint_relationship_v1/ARTIFACT_MANIFEST.json":
        "d0d1a749afb6a6f894de1bb4263c9d67dd1e3b2d1a35bf1b5fd38d8948c656b0",
    "jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet":
        "13409e65353c0cb6dab14df97317cce24de913056ae464ee3524520759de681c",
    "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv":
        "0e6a01607164a7cb54fbbb5fb445e975ea9fbadad21d4e7a842adfc915616a09",
    "jeju/research/20261010_joint_relationship_v1/outputs/report/race_metrics.csv":
        "89820acf0dfafc749f394cf9e74a3b58a5ec890e2c746f890ad257eaf32ff115",
    "jeju/research/20261010_joint_relationship_v1/outputs/report/report_receipt.json":
        "5720519b0d8860f5652650b4d2ee3b6f8444a6c6f01421395cd51f4a0251fae4",
    "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet":
        "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
    "jeju/research/20261010_style_history_ablation_v1/CONTRACT.md":
        "c10aac8f6faa6e841afd9ef829bfa0b29ada2dceabcbb5405fdfad9c12536bf9",
}

FROZEN_PLAN_HASHES = {
    "jeju/research/20261010_pair_axis_v1/PLAN.md":
        "fcecdd848f3e4e46cc9c41d9cb4f86b1cf6ae02a0e4ceef196b422b40e102d4a",
    "jeju/research/20261010_pair_axis_v1/INPUT_CONTRACT.md":
        "f2c832f9dcd598031a0f7ada9ac497c45f10cb39f25d85f05a6e673fa8d61bc7",
}
PRECOMPUTE_LOCK_HASH = "34575317c12fc9cbc54f9ecd72444365c238c8d97e8b23bd8097147239c480d8"
A_FROZEN_OUTPUT_HASHES = {
    "jeju/research/20261010_pair_axis_v1/outputs/per_race_metrics.csv":
        "78b75895ddd82a72a406aa2b9d4fa889946d25e6a8d8c8f50069aac286b267c1",
    "jeju/research/20261010_pair_axis_v1/outputs/primary_comparisons.csv":
        "f01fc5a03b5fdad0a6963caf7a9e0cb98ca35ef10859d5885531dfbfc19a8555",
}

RACE_COUNT = 1779
RUNNER_COUNT = 17412
RACE_DAY_COUNT = 269
PERIOD_START = "2024-01-05"
PERIOD_END = "2026-09-19"
ARMS = ("matched_baseline", "candidate")
POLICIES = (
    "unrestricted_top_k",
    "top_two_marginal_pair",
    "maximum_joint_pair",
    "maximum_k_ticket_pair_mass",
    "single_top3_anchor",
)
K_VALUES = (3, 4)
CONFIDENCE_POLICIES = ("maximum_joint_pair", "single_top3_anchor")
PROBABILITY_BINS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0))
CUTOFFS = (0.2, 0.4, 0.6, 0.8)
COVERAGE_FRACTIONS = (0.25, 0.50, 0.75, 1.0)
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20261010
IDENTITY_TOLERANCE = 1e-12


@dataclass(frozen=True)
class Triple:
    race_id: str
    race_date: str
    year: int
    distance_m: float
    arm: str
    triple_index: int
    horses: tuple[int, int, int]
    probability: float
    true_set: bool
    canonical_rank: int
    total_energy: float


@dataclass
class RaceArm:
    race_id: str
    race_date: str
    year: int
    distance_m: float
    arm: str
    roster: tuple[int, ...]
    triples: list[Triple]
    horse_marginals: dict[int, float]
    pair_marginals: dict[tuple[int, int], float]
    true_set: tuple[int, int, int]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_hashes() -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    for rel, expected in {**SOURCE_HASHES, **FROZEN_PLAN_HASHES}.items():
        path = ROOT / rel
        actual = sha256(path)
        require(actual == expected, f"source hash mismatch: {rel}: {actual}")
        receipts[rel] = {"sha256": actual, "bytes": path.stat().st_size, "passed": True}
    lock = json.loads((ROOT / "jeju/research/20261010_pair_axis_v1/PRECOMPUTE_LOCK.json").read_text(encoding="utf-8"))
    require(lock.get("status") == "frozen_before_outcome_computation", "A precompute lock is not frozen")
    for role, expected in FROZEN_PLAN_HASHES.items():
        entry = lock.get("plan" if role.endswith("PLAN.md") else "input_contract", {})
        require(entry.get("path") == role and entry.get("sha256") == expected,
                f"frozen precompute lock mismatch: {role}")
    locked = {item["path"]: item for item in lock.get("inputs", [])}
    lock_path = ROOT / "jeju/research/20261010_pair_axis_v1/PRECOMPUTE_LOCK.json"
    require(sha256(lock_path) == PRECOMPUTE_LOCK_HASH, "A precompute-lock hash mismatch")
    require(set(SOURCE_HASHES).issubset(locked), "A precompute lock omits one or more pinned sources")
    for rel, expected in SOURCE_HASHES.items():
        require(locked[rel].get("sha256") == expected, f"A precompute lock source mismatch: {rel}")
    receipts["jeju/research/20261010_pair_axis_v1/PRECOMPUTE_LOCK.json"] = {
        "sha256": sha256(ROOT / "jeju/research/20261010_pair_axis_v1/PRECOMPUTE_LOCK.json"),
        "bytes": (ROOT / "jeju/research/20261010_pair_axis_v1/PRECOMPUTE_LOCK.json").stat().st_size,
        "passed": True,
    }
    return receipts


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def parse_triple(value: str) -> tuple[int, int, int]:
    items = tuple(int(part) for part in value.split(","))
    require(len(items) == 3 and tuple(sorted(items)) == items and len(set(items)) == 3,
            f"invalid unordered triple key: {value!r}")
    return items  # type: ignore[return-value]


def load_triples() -> dict[tuple[str, str], list[Triple]]:
    rel = "jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet"
    table = pq.read_table(ROOT / rel)
    required = {
        "race_id", "race_date", "evaluation_year", "distance_m", "arm",
        "triple_index", "triple_numbers", "total_energy", "probability",
        "is_true_set", "canonical_rank",
    }
    require(required.issubset(table.column_names), "triple table missing required columns")
    groups: dict[tuple[str, str], list[Triple]] = defaultdict(list)
    keys: set[tuple[str, str, str]] = set()
    for row in table.to_pylist():
        race_id = str(row["race_id"])
        arm = str(row["arm"])
        horses = parse_triple(str(row["triple_numbers"]))
        key = (race_id, arm, str(row["triple_numbers"]))
        require(key not in keys, f"duplicate triple row: {key}")
        keys.add(key)
        probability = float(row["probability"])
        energy = float(row["total_energy"])
        require(math.isfinite(probability) and 0.0 <= probability <= 1.0,
                f"invalid probability: {key}")
        require(math.isfinite(energy), f"non-finite energy: {key}")
        groups[(race_id, arm)].append(Triple(
            race_id=race_id,
            race_date=str(row["race_date"]),
            year=int(row["evaluation_year"]),
            distance_m=float(row["distance_m"]),
            arm=arm,
            triple_index=int(row["triple_index"]),
            horses=horses,
            probability=probability,
            true_set=bool(row["is_true_set"]),
            canonical_rank=int(row["canonical_rank"]),
            total_energy=energy,
        ))
    for values in groups.values():
        values.sort(key=lambda item: item.triple_index)
    return groups


def load_runner_rows() -> tuple[list[dict[str, Any]], dict[str, dict[int, dict[str, Any]]]]:
    rel = "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv"
    raw = read_csv(ROOT / rel)
    required = {
        "api_record_id", "race_id", "race_date", "evaluation_year", "horse_number",
        "y_top3", "baseline_joint_marginal", "candidate_joint_marginal", "saved_y_top3",
    }
    require(raw and required.issubset(raw[0]), "runner marginal CSV missing required columns")
    rows: list[dict[str, Any]] = []
    by_race: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    ids: set[int] = set()
    for source in raw:
        row = {
            "api_record_id": int(source["api_record_id"]),
            "race_id": source["race_id"],
            "race_date": source["race_date"],
            "year": int(source["evaluation_year"]),
            "horse_number": int(source["horse_number"]),
            "y_top3": int(source["y_top3"]),
            "saved_y_top3": int(source["saved_y_top3"]),
            "baseline_joint_marginal": float(source["baseline_joint_marginal"]),
            "candidate_joint_marginal": float(source["candidate_joint_marginal"]),
        }
        require(row["api_record_id"] not in ids, "api_record_id is not unique in runner marginals")
        ids.add(row["api_record_id"])
        require(row["horse_number"] not in by_race[row["race_id"]],
                f"duplicate race/horse-number runner: {row['race_id']} {row['horse_number']}")
        require(row["y_top3"] in (0, 1) and row["saved_y_top3"] in (0, 1),
                "invalid runner Top3 label")
        require(row["y_top3"] == row["saved_y_top3"], "runner Top3 labels disagree")
        by_race[row["race_id"]][row["horse_number"]] = row
        rows.append(row)
    return rows, by_race


def load_feature_identity(runner_rows: list[dict[str, Any]]) -> tuple[dict[int, dict[str, Any]], dict[str, dict[int, dict[str, Any]]]]:
    rel = "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
    table = pq.read_table(ROOT / rel, columns=[
        "api_record_id", "race_id", "race_date", "horse_id", "horse_number",
        "finish_position", "distance_m", "year",
    ])
    runner_ids = {row["api_record_id"] for row in runner_rows}
    by_api: dict[int, dict[str, Any]] = {}
    by_race: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for row in table.to_pylist():
        api_id = int(row["api_record_id"])
        if api_id not in runner_ids:
            continue
        require(api_id not in by_api, f"duplicate api_record_id in feature source: {api_id}")
        feature = {
            "api_record_id": api_id,
            "race_id": str(row["race_id"]),
            "race_date": str(row["race_date"]),
            "horse_id": str(row["horse_id"]),
            "horse_number": int(row["horse_number"]),
            "finish_position": int(row["finish_position"]),
            "distance_m": float(row["distance_m"]),
            "year": int(row["year"]),
        }
        require(feature["horse_number"] not in by_race[feature["race_id"]],
                f"duplicate feature race/horse-number: {feature['race_id']} {feature['horse_number']}")
        by_api[api_id] = feature
        by_race[feature["race_id"]][feature["horse_number"]] = feature
    require(set(by_api) == runner_ids, "runner-to-feature api_record_id join is incomplete")
    return by_api, by_race


def load_race_metrics() -> dict[str, dict[str, Any]]:
    rel = "jeju/research/20261010_joint_relationship_v1/outputs/report/race_metrics.csv"
    rows = read_csv(ROOT / rel)
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        race_id = row["race_id"]
        require(race_id not in result, f"duplicate race metric row: {race_id}")
        result[race_id] = {
            "race_id": race_id,
            "race_date": row["race_date"],
            "year": int(row["evaluation_year"]),
            "distance_m": float(row["distance_m"]),
            "runner_rows": int(row["runner_rows"]),
            "triple_count": int(row["triple_count"]),
            "baseline_hit6": int(row["baseline_hit6"]),
            "candidate_hit6": int(row["candidate_hit6"]),
            "baseline_six_tickets": tuple(ast.literal_eval(row["baseline_six_tickets"])),
            "candidate_six_tickets": tuple(ast.literal_eval(row["candidate_six_tickets"])),
        }
    return result


def load_report_receipt() -> dict[str, Any]:
    rel = "jeju/research/20261010_joint_relationship_v1/outputs/report/report_receipt.json"
    result = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    require(result.get("passed") is True and result.get("study") == "20261010_joint_relationship_v1",
            "saved report receipt is not passing for the expected study")
    require(result.get("all_triples_sha256") == SOURCE_HASHES[
        "jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet"],
        "report receipt triple hash mismatch")
    require(result.get("runner_marginals_sha256") == SOURCE_HASHES[
        "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv"],
        "report receipt runner hash mismatch")
    require(result.get("race_metrics_sha256") == SOURCE_HASHES[
        "jeju/research/20261010_joint_relationship_v1/outputs/report/race_metrics.csv"],
        "report receipt race-metrics hash mismatch")
    return result


def build_race_arms(
    triple_groups: dict[tuple[str, str], list[Triple]],
    runner_by_race: dict[str, dict[int, dict[str, Any]]],
    feature_by_race: dict[str, dict[int, dict[str, Any]]],
    metrics: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], RaceArm]:
    require(set(metrics) == set(runner_by_race), "race-metric and runner race sets differ")
    require(set(triple_groups) == {(race, arm) for race in metrics for arm in ARMS},
            "triple race/arm keys are incomplete or unexpected")
    race_arms: dict[tuple[str, str], RaceArm] = {}
    for race_id in sorted(metrics):
        metric = metrics[race_id]
        runners = runner_by_race[race_id]
        features = feature_by_race.get(race_id, {})
        roster = tuple(sorted(runners))
        require(len(roster) == metric["runner_rows"], f"runner count mismatch: {race_id}")
        require(set(features) == set(roster), f"feature runner roster mismatch: {race_id}")
        official_ids: set[str] = set()
        true_labels: set[int] = set()
        finish_positions: dict[int, int] = {}
        for horse_number, runner in runners.items():
            feature = features[horse_number]
            require(feature["api_record_id"] == runner["api_record_id"],
                    f"api/race/horse identity join mismatch: {race_id} {horse_number}")
            require(feature["race_id"] == runner["race_id"] == race_id,
                    f"race identity mismatch: {race_id} {horse_number}")
            require(feature["horse_number"] == runner["horse_number"] == horse_number,
                    f"horse-number identity mismatch: {race_id} {horse_number}")
            require(feature["race_date"] == runner["race_date"] == metric["race_date"],
                    f"race date mismatch: {race_id} {horse_number}")
            require(feature["year"] == runner["year"] == metric["year"],
                    f"year mismatch: {race_id} {horse_number}")
            require(abs(feature["distance_m"] - metric["distance_m"]) <= IDENTITY_TOLERANCE,
                    f"distance mismatch: {race_id} {horse_number}")
            require(feature["horse_id"] not in official_ids,
                    f"official horse ID repeats within race: {race_id} {feature['horse_id']}")
            official_ids.add(feature["horse_id"])
            finish_positions[horse_number] = feature["finish_position"]
            if runner["y_top3"] == 1:
                true_labels.add(horse_number)
        require(len(true_labels) == 3, f"expected three Top3 labels: {race_id}")
        require(sorted(finish_positions.values()) == list(range(1, len(roster) + 1)),
                f"normal unique finish positions not complete: {race_id}")
        require(sum(pos == 1 for pos in finish_positions.values()) == 1 and
                sum(pos == 2 for pos in finish_positions.values()) == 1,
                f"missing or tied first/second rank: {race_id}")
        feature_top3 = {horse for horse, pos in finish_positions.items() if pos <= 3}
        require(feature_top3 == true_labels, f"Top3 labels differ from finish positions: {race_id}")
        require(len(roster) >= 7 and len(roster) <= 12, f"field size outside locked support: {race_id}")
        require(metric["triple_count"] == math.comb(len(roster), 3),
                f"reported triple count differs from complete roster: {race_id}")
        expected_keys = set(itertools.combinations(roster, 3))
        for arm in ARMS:
            triples = triple_groups[(race_id, arm)]
            require(len(triples) == math.comb(len(roster), 3), f"incomplete triple count: {race_id} {arm}")
            require(tuple(t.triple_index for t in triples) == tuple(range(len(triples))),
                    f"triple_index not contiguous source order: {race_id} {arm}")
            require([t.horses for t in triples] == list(itertools.combinations(roster, 3)),
                    f"triple_index does not follow canonical numeric combination order: {race_id} {arm}")
            require({t.horses for t in triples} == expected_keys,
                    f"triple keys do not match complete roster: {race_id} {arm}")
            require(all(t.race_date == metric["race_date"] and t.year == metric["year"] and
                        abs(t.distance_m - metric["distance_m"]) <= IDENTITY_TOLERANCE
                        for t in triples), f"triple metadata mismatch: {race_id} {arm}")
            total_q = math.fsum(t.probability for t in triples)
            require(abs(total_q - 1.0) <= IDENTITY_TOLERANCE,
                    f"joint probability sum mismatch: {race_id} {arm}: {total_q}")
            true_triples = [t.horses for t in triples if t.true_set]
            require(len(true_triples) == 1, f"expected exactly one true set: {race_id} {arm}")
            require(true_triples[0] == tuple(sorted(true_labels)),
                    f"true triple differs from runner labels: {race_id} {arm}")
            ranks = [t.canonical_rank for t in triples]
            require(sorted(ranks) == list(range(1, len(triples) + 1)),
                    f"canonical ranks are not a unique total order: {race_id} {arm}")
            by_rank = sorted(triples, key=lambda t: t.canonical_rank)
            expected_by_energy = sorted(triples, key=lambda t: (-t.total_energy, t.triple_index))
            require([t.triple_index for t in by_rank] == [t.triple_index for t in expected_by_energy],
                    f"canonical rank differs from energy/canonical numeric order: {race_id} {arm}")
            require(all(a.probability >= b.probability for a, b in zip(by_rank, by_rank[1:])),
                    f"probability rises in canonical rank order: {race_id} {arm}")
            for position, (ranked, energy_ranked) in enumerate(zip(by_rank, expected_by_energy), start=1):
                require(ranked.canonical_rank == position and ranked.triple_index == energy_ranked.triple_index,
                        f"canonical-rank parity error: {race_id} {arm}")

            runner_q: dict[int, list[float]] = {horse: [] for horse in roster}
            pair_q: dict[tuple[int, int], list[float]] = {
                pair: [] for pair in itertools.combinations(roster, 2)
            }
            for triple in triples:
                for horse in triple.horses:
                    runner_q[horse].append(triple.probability)
                for pair in itertools.combinations(triple.horses, 2):
                    pair_q[pair].append(triple.probability)
            horse_marginals = {horse: math.fsum(values) for horse, values in runner_q.items()}
            pair_marginals = {pair: math.fsum(values) for pair, values in pair_q.items()}
            require(abs(math.fsum(horse_marginals.values()) - 3.0) <= IDENTITY_TOLERANCE,
                    f"Top3 marginal mass is not 3: {race_id} {arm}")
            require(abs(math.fsum(pair_marginals.values()) - 3.0) <= IDENTITY_TOLERANCE,
                    f"pair-in-Top3 marginal mass is not 3: {race_id} {arm}")
            for horse in roster:
                runner = runners[horse]
                reference = runner["baseline_joint_marginal"] if arm == "matched_baseline" else runner["candidate_joint_marginal"]
                require(abs(horse_marginals[horse] - reference) <= IDENTITY_TOLERANCE,
                        f"runner marginal mismatch: {race_id} {arm} horse {horse}")
            race_arms[(race_id, arm)] = RaceArm(
                race_id=race_id,
                race_date=metric["race_date"],
                year=metric["year"],
                distance_m=metric["distance_m"],
                arm=arm,
                roster=roster,
                triples=triples,
                horse_marginals=horse_marginals,
                pair_marginals=pair_marginals,
                true_set=tuple(sorted(true_labels)),  # type: ignore[arg-type]
            )
            if arm == "candidate":
                baseline = race_arms[(race_id, "matched_baseline")]
                require(baseline.roster == race_arms[(race_id, arm)].roster,
                        f"cross-arm roster mismatch: {race_id}")
                require(baseline.true_set == race_arms[(race_id, arm)].true_set,
                        f"cross-arm true-set mismatch: {race_id}")
    return race_arms


def verify_cohort_and_saved_top6(
    race_arms: dict[tuple[str, str], RaceArm],
    runner_rows: list[dict[str, Any]],
    metrics: dict[str, dict[str, Any]],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    race_ids = sorted(metrics)
    dates = sorted({metrics[race]["race_date"] for race in race_ids})
    require(len(race_ids) == RACE_COUNT, f"race count mismatch: {len(race_ids)}")
    require(len(runner_rows) == RUNNER_COUNT, f"runner count mismatch: {len(runner_rows)}")
    require(len(dates) == RACE_DAY_COUNT, f"race-day count mismatch: {len(dates)}")
    require(dates[0] == PERIOD_START and dates[-1] == PERIOD_END,
            f"date range mismatch: {dates[0]}..{dates[-1]}")
    size_counts = Counter(len(race_arms[(race, "matched_baseline")].roster) for race in race_ids)
    expected_sizes = {7: 36, 8: 81, 9: 112, 10: 1548, 12: 2}
    require(dict(sorted(size_counts.items())) == expected_sizes,
            f"field-size support differs: {dict(sorted(size_counts.items()))}")
    require(sum(len(race_arms[(race, arm)].triples) for race in race_ids for arm in ARMS) == 402808,
            "total triple row count mismatch")
    require(receipt.get("outcome_metrics_computed_after_fit_artifact") is True,
            "saved report receipt does not certify an outcome report")
    saved_hits: dict[str, int] = {arm: 0 for arm in ARMS}
    per_race_parity = 0
    for race in race_ids:
        metric = metrics[race]
        for arm in ARMS:
            row = race_arms[(race, arm)]
            prefix = "baseline" if arm == "matched_baseline" else "candidate"
            expected_tickets = metric[f"{prefix}_six_tickets"]
            chosen = tuple(",".join(str(horse) for horse in t.horses)
                           for t in sorted(row.triples, key=lambda t: t.canonical_rank)[:6])
            require(chosen == expected_tickets,
                    f"saved six-ticket list mismatch: {race} {arm}: {chosen} != {expected_tickets}")
            hit = int(row.true_set in {t.horses for t in sorted(row.triples, key=lambda t: t.canonical_rank)[:6]})
            expected_hit = metric[f"{prefix}_hit6"]
            require(hit == expected_hit, f"per-race six-ticket hit mismatch: {race} {arm}")
            saved_hits[arm] += hit
        per_race_parity += 1
    require(saved_hits == {"matched_baseline": 407, "candidate": 423},
            f"saved hit totals mismatch: {saved_hits}")
    return {
        "races": len(race_ids), "runners": len(runner_rows), "race_dates": len(dates),
        "start_date": dates[0], "end_date": dates[-1], "partial_2026": True,
        "field_size_counts": dict(sorted(size_counts.items())),
        "triple_rows": 402808, "top6_per_race_parity_rows": per_race_parity * 2,
        "saved_top6_hit_totals": saved_hits,
    }


def select_policies(race: RaceArm, k_values: Iterable[int] = K_VALUES) -> dict[tuple[str, int], tuple[Triple, ...]]:
    """Select solely from roster, saved probabilities, and canonical ranks."""
    by_rank = sorted(race.triples, key=lambda triple: triple.canonical_rank)
    all_pairs = list(itertools.combinations(race.roster, 2))
    by_horse = sorted(race.roster, key=lambda horse: (-race.horse_marginals[horse], horse))
    by_pair_mass = sorted(all_pairs, key=lambda pair: (-race.pair_marginals[pair], pair))
    selected: dict[tuple[str, int], tuple[Triple, ...]] = {}
    for k in k_values:
        require(k in (3, 4), f"unexpected anchored ticket budget: {k}")
        selected[("unrestricted_top_k", k)] = tuple(by_rank[:k])
        two_marginal_pair = tuple(sorted(by_horse[:2]))
        joint_pair = by_pair_mass[0]
        ranked_for_pair = {
            pair: tuple(t for t in by_rank if set(pair).issubset(t.horses))
            for pair in all_pairs
        }
        require(all(len(ranked_for_pair[pair]) >= k for pair in all_pairs),
                f"pair cannot supply K={k}: {race.race_id}")
        selected[("top_two_marginal_pair", k)] = ranked_for_pair[two_marginal_pair][:k]
        selected[("maximum_joint_pair", k)] = ranked_for_pair[joint_pair][:k]
        # Ascending numeric pair is the exact-tie rule: replace only on strict
        # greater mass while visiting pairs in their numeric order.
        best_pair = all_pairs[0]
        best_mass = math.fsum(t.probability for t in ranked_for_pair[best_pair][:k])
        for pair in all_pairs[1:]:
            mass = math.fsum(t.probability for t in ranked_for_pair[pair][:k])
            if mass > best_mass:
                best_pair, best_mass = pair, mass
        selected[("maximum_k_ticket_pair_mass", k)] = ranked_for_pair[best_pair][:k]
        anchor = by_horse[0]
        selected[("single_top3_anchor", k)] = tuple(
            t for t in by_rank if anchor in t.horses
        )[:k]
        for policy in POLICIES:
            tickets = selected[(policy, k)]
            require(len(tickets) == k and len({t.horses for t in tickets}) == k,
                    f"policy failed exact ticket count: {race.race_id} {policy} K={k}")
    return selected


def exact_pair_policy_axis(race: RaceArm, policy: str) -> tuple[int, int] | None:
    if policy == "top_two_marginal_pair":
        horses = sorted(race.roster, key=lambda horse: (-race.horse_marginals[horse], horse))[:2]
        return tuple(sorted(horses))  # type: ignore[return-value]
    if policy == "maximum_joint_pair":
        return min(race.pair_marginals, key=lambda pair: (-race.pair_marginals[pair], pair))
    if policy == "maximum_k_ticket_pair_mass":
        # The K-specific selected pair is recoverable from selected tickets.
        return None
    return None


def identify_pair_for_k(race: RaceArm, policy: str, k: int, tickets: tuple[Triple, ...]) -> tuple[int, int] | None:
    if policy in ("top_two_marginal_pair", "maximum_joint_pair"):
        return exact_pair_policy_axis(race, policy)
    if policy == "maximum_k_ticket_pair_mass":
        common = set(race.roster)
        for ticket in tickets:
            common.intersection_update(ticket.horses)
        require(len(common) == 2, f"K-ticket maximum-mass tickets lack unique shared pair: {race.race_id} K={k}")
        return tuple(sorted(common))  # type: ignore[return-value]
    return None


def identify_single_anchor(race: RaceArm) -> int:
    return min(race.roster, key=lambda horse: (-race.horse_marginals[horse], horse))


def score_policy(
    race: RaceArm,
    policy: str,
    k: int,
    tickets: tuple[Triple, ...],
    feature_by_race: dict[str, dict[int, dict[str, Any]]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    truth = race.true_set
    ticket_hit = truth in {triple.horses for triple in tickets}
    selected_mass = math.fsum(triple.probability for triple in tickets)
    row: dict[str, Any] = {
        "race_id": race.race_id,
        "race_date": race.race_date,
        "year": race.year,
        "distance_m": race.distance_m,
        "arm": race.arm,
        "policy": policy,
        "ticket_budget": k,
        "selected_tickets": [list(ticket.horses) for ticket in tickets],
        "selected_mass": selected_mass,
        "ticket_hit": int(ticket_hit),
        "axis_type": None,
        "axis_horses": None,
        "axis_probability": None,
        "axis_hit": None,
        "completion_hit": None,
        "axis_miss": None,
        "axis_hit_completion_miss": None,
        "exact_top2_pair_hit": None,
    }
    if policy in ("top_two_marginal_pair", "maximum_joint_pair", "maximum_k_ticket_pair_mass"):
        pair = identify_pair_for_k(race, policy, k, tickets)
        require(pair is not None and all(set(pair).issubset(t.horses) for t in tickets),
                f"pair axis does not anchor every ticket: {race.race_id} {policy} {k}")
        axis_hit = set(pair).issubset(truth)
        position_map = {horse: feature["finish_position"]
                        for horse, feature in feature_by_race[race.race_id].items()}
        exact_top2 = {position_map[pair[0]], position_map[pair[1]]} == {1, 2}
        row.update({
            "axis_type": "pair_both_top3",
            "axis_horses": list(pair),
            "axis_probability": race.pair_marginals[pair],
            "axis_hit": int(axis_hit),
            "completion_hit": int(ticket_hit) if axis_hit else None,
            "axis_miss": int(not axis_hit),
            "axis_hit_completion_miss": int(axis_hit and not ticket_hit),
            "exact_top2_pair_hit": int(exact_top2),
        })
    elif policy == "single_top3_anchor":
        anchor = identify_single_anchor(race)
        axis_hit = anchor in truth
        row.update({
            "axis_type": "single_horse_top3",
            "axis_horses": [anchor],
            "axis_probability": race.horse_marginals[anchor],
            "axis_hit": int(axis_hit),
            "completion_hit": int(ticket_hit) if axis_hit else None,
            "axis_miss": int(not axis_hit),
            "axis_hit_completion_miss": int(axis_hit and not ticket_hit),
        })
    else:
        require(policy == "unrestricted_top_k", f"unknown policy {policy}")
    ticket_rows = [{
        "race_id": race.race_id,
        "race_date": race.race_date,
        "year": race.year,
        "arm": race.arm,
        "policy": policy,
        "ticket_budget": k,
        "selection_rank": index + 1,
        "triple": list(ticket.horses),
        "probability": ticket.probability,
        "is_true_set": int(ticket.horses == truth),
    } for index, ticket in enumerate(tickets)]
    return row, ticket_rows


def probability_bin(value: float) -> str:
    require(0.0 <= value <= 1.0, f"probability outside [0,1]: {value}")
    for index, (lower, upper) in enumerate(PROBABILITY_BINS):
        if index == len(PROBABILITY_BINS) - 1:
            if lower <= value <= upper:
                return f"[{lower:.1f},{upper:.1f}]"
        elif lower <= value < upper:
            return f"[{lower:.1f},{upper:.1f})"
    raise AssertionError(f"probability did not fall in a fixed bin: {value}")


def ratio(numerator: int | float, denominator: int | float) -> float | None:
    return None if denominator == 0 else numerator / denominator


def summary_for_policies(policy_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    keys = sorted({(row["arm"], row["policy"], row["ticket_budget"]) for row in policy_rows})
    for arm, policy, budget in keys:
        rows = [row for row in policy_rows if (row["arm"], row["policy"], row["ticket_budget"]) == (arm, policy, budget)]
        total = len(rows)
        hits = sum(row["ticket_hit"] for row in rows)
        masses = math.fsum(row["selected_mass"] for row in rows) / total
        out: dict[str, Any] = {
            "arm": arm, "policy": policy, "ticket_budget": budget,
            "races": total, "ticket_hits": hits, "ticket_hit_rate": hits / total,
            "mean_selected_mass": masses,
        }
        if policy != "unrestricted_top_k":
            axis_hits = sum(row["axis_hit"] for row in rows)
            completion_hits = sum(row["ticket_hit"] for row in rows if row["axis_hit"] == 1)
            axis_false = sum(row["axis_miss"] for row in rows)
            axis_true_completion_false = sum(row["axis_hit_completion_miss"] for row in rows)
            misses = total - hits
            require(axis_false + axis_true_completion_false == misses,
                    f"failure decomposition does not sum: {arm} {policy} K={budget}")
            out.update({
                "axis_hits": axis_hits,
                "axis_hit_rate_all_races": axis_hits / total,
                "conditional_completion_hits": completion_hits,
                "conditional_completion_denominator": axis_hits,
                "conditional_completion_rate": ratio(completion_hits, axis_hits),
                "axis_miss_failures": axis_false,
                "axis_hit_completion_miss_failures": axis_true_completion_false,
                "ticket_misses": misses,
                "failure_decomposition_passed": True,
            })
            if "pair" in policy:
                top2_hits = sum(row["exact_top2_pair_hit"] for row in rows)
                out["exact_top2_pair_hits_secondary"] = top2_hits
                out["exact_top2_pair_rate_secondary"] = top2_hits / total
        summaries.append(out)
    return summaries


def bootstrap_primary_contrasts(
    policy_rows: list[dict[str, Any]],
    race_ids: list[str],
    metrics: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    day_to_indices: dict[str, list[int]] = defaultdict(list)
    race_index = {race_id: index for index, race_id in enumerate(race_ids)}
    for race_id in race_ids:
        day_to_indices[metrics[race_id]["race_date"]].append(race_index[race_id])
    dates = sorted(day_to_indices)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.integers(0, len(dates), size=(BOOTSTRAP_REPLICATES, len(dates)))
    lookup = {(row["race_id"], row["arm"], row["policy"], row["ticket_budget"]): row["ticket_hit"]
              for row in policy_rows}
    contrasts = []
    # The frozen plan names only maximum-joint-pair versus unrestricted top K
    # as the primary contrast. Other policies remain in the complete descriptive
    # table; do not create unplanned inferential comparisons after seeing labels.
    definitions = (("maximum_joint_pair", "unrestricted_top_k"),)
    for arm in ARMS:
        for k in K_VALUES:
            for left_policy, right_policy in definitions:
                race_diffs = np.array([
                    lookup[(race_id, arm, left_policy, k)] - lookup[(race_id, arm, right_policy, k)]
                    for race_id in race_ids
                ], dtype=float)
                estimate = float(np.mean(race_diffs))
                sampled = np.empty(BOOTSTRAP_REPLICATES, dtype=float)
                for replicate, date_draw in enumerate(draws):
                    indexes: list[int] = []
                    for date_idx in date_draw:
                        indexes.extend(day_to_indices[dates[int(date_idx)]])
                    sampled[replicate] = float(np.mean(race_diffs[indexes]))
                low, high = np.quantile(sampled, [0.025, 0.975], method="linear")
                contrasts.append({
                    "arm": arm, "ticket_budget": k,
                    "left_policy": left_policy, "right_policy": right_policy,
                    "difference_definition": "left minus right ticket-hit indicator mean",
                    "estimate": estimate,
                    "ci95_low": float(low), "ci95_high": float(high),
                    "draws": BOOTSTRAP_REPLICATES,
                    "seed": BOOTSTRAP_SEED,
                    "cluster": "race_date",
                    "quantile_method": "numpy linear",
                })
    return contrasts, {
        "date_count": len(dates), "replicates": BOOTSTRAP_REPLICATES,
        "seed": BOOTSTRAP_SEED,
        "rng": "numpy.default_rng PCG64; one shared date-resample matrix for all contrasts",
        "quantile_method": "numpy quantile method=linear at 0.025 and 0.975",
    }


def calibration_summaries(policy_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    axis_bins: list[dict[str, Any]] = []
    axis_overall: list[dict[str, Any]] = []
    ticket_bins: list[dict[str, Any]] = []
    for arm in ARMS:
        for policy in CONFIDENCE_POLICIES:
            axis_rows = [row for row in policy_rows if row["arm"] == arm and row["policy"] == policy and row["ticket_budget"] == 3]
            require(len(axis_rows) == RACE_COUNT, f"axis calibration row count mismatch: {arm} {policy}")
            mean_brier = math.fsum((row["axis_probability"] - row["axis_hit"]) ** 2 for row in axis_rows) / len(axis_rows)
            axis_overall.append({
                "arm": arm, "policy": policy, "races": len(axis_rows),
                "race_level_brier": mean_brier,
                "mean_axis_probability": math.fsum(row["axis_probability"] for row in axis_rows) / len(axis_rows),
                "axis_hit_rate": math.fsum(row["axis_hit"] for row in axis_rows) / len(axis_rows),
            })
            for lower, upper in PROBABILITY_BINS:
                label = f"[{lower:.1f},{upper:.1f}]" if upper == 1.0 else f"[{lower:.1f},{upper:.1f})"
                rows = [row for row in axis_rows if probability_bin(row["axis_probability"]) == label]
                axis_bins.append({
                    "arm": arm, "policy": policy, "probability_bin": label,
                    "races": len(rows),
                    "mean_probability": None if not rows else math.fsum(r["axis_probability"] for r in rows) / len(rows),
                    "observed_axis_hit_rate": None if not rows else math.fsum(r["axis_hit"] for r in rows) / len(rows),
                })
            for k in K_VALUES:
                rows_k = [row for row in policy_rows if row["arm"] == arm and row["policy"] == policy and row["ticket_budget"] == k]
                for lower, upper in PROBABILITY_BINS:
                    label = f"[{lower:.1f},{upper:.1f}]" if upper == 1.0 else f"[{lower:.1f},{upper:.1f})"
                    rows = [row for row in rows_k if probability_bin(row["selected_mass"]) == label]
                    ticket_bins.append({
                        "arm": arm, "policy": policy, "ticket_budget": k,
                        "probability_bin": label, "races": len(rows),
                        "mean_selected_mass": None if not rows else math.fsum(r["selected_mass"] for r in rows) / len(rows),
                        "observed_ticket_hit_rate": None if not rows else math.fsum(r["ticket_hit"] for r in rows) / len(rows),
                    })
    cutoff_rows: list[dict[str, Any]] = []
    for arm in ARMS:
        for policy in CONFIDENCE_POLICIES:
            for cutoff in CUTOFFS:
                # Axis choice is the same across K; attach each budget separately.
                for k in K_VALUES:
                    chosen_k = [row for row in policy_rows
                                if row["arm"] == arm and row["policy"] == policy and row["ticket_budget"] == k
                                and row["axis_probability"] >= cutoff]
                    axis_hits = sum(row["axis_hit"] for row in chosen_k)
                    ticket_hits = sum(row["ticket_hit"] for row in chosen_k)
                    cutoff_rows.append({
                        "arm": arm, "policy": policy, "cutoff": cutoff,
                        "ticket_budget": k, "selected_races": len(chosen_k),
                        "coverage": len(chosen_k) / RACE_COUNT,
                        "axis_successes": axis_hits,
                        "axis_success_rate_selected": ratio(axis_hits, len(chosen_k)),
                        "ticket_hits": ticket_hits,
                        "unconditional_ticket_hit_rate_all_races": ticket_hits / RACE_COUNT,
                        "conditional_completion_hits": ticket_hits,
                        "conditional_completion_denominator": axis_hits,
                        "conditional_completion_rate": ratio(ticket_hits, axis_hits),
                    })
    coverage_rows: list[dict[str, Any]] = []
    for arm in ARMS:
        for policy in CONFIDENCE_POLICIES:
            base = [row for row in policy_rows if row["arm"] == arm and row["policy"] == policy and row["ticket_budget"] == 3]
            ranked = sorted(base, key=lambda row: (-row["axis_probability"], row["race_date"], row["race_id"]))
            for fraction in COVERAGE_FRACTIONS:
                count = math.ceil(fraction * RACE_COUNT)
                selected_ids = {row["race_id"] for row in ranked[:count]}
                for k in K_VALUES:
                    rows = [row for row in policy_rows
                            if row["arm"] == arm and row["policy"] == policy and row["ticket_budget"] == k
                            and row["race_id"] in selected_ids]
                    axis_hits = sum(row["axis_hit"] for row in rows)
                    ticket_hits = sum(row["ticket_hit"] for row in rows)
                    coverage_rows.append({
                        "arm": arm, "policy": policy,
                        "coverage_fraction_target": fraction, "coverage_races": len(rows),
                        "coverage": len(rows) / RACE_COUNT,
                        "ticket_budget": k,
                        "axis_successes": axis_hits,
                        "axis_success_rate_selected": ratio(axis_hits, len(rows)),
                        "ticket_hits": ticket_hits,
                        "unconditional_ticket_hit_rate_all_races": ticket_hits / RACE_COUNT,
                        "conditional_completion_hits": ticket_hits,
                        "conditional_completion_denominator": axis_hits,
                        "conditional_completion_rate": ratio(ticket_hits, axis_hits),
                        "subset_semantics": "retrospective global score rank; no fixed future threshold",
                    })
    return axis_bins, axis_overall, ticket_bins, cutoff_rows, coverage_rows


def selection_invariance_check(race_arms: dict[tuple[str, str], RaceArm]) -> dict[str, Any]:
    """Check selections do not depend on input order or any label values."""
    rng = random.Random(20261010)
    tested = 0
    for key, race in race_arms.items():
        canonical = select_policies(race)
        # Reordering source rows cannot alter the order-preserving canonical-rank
        # selection because the selector receives the same Q-only object values.
        shuffled = list(race.triples)
        rng.shuffle(shuffled)
        shuffled_race = RaceArm(
            race_id=race.race_id, race_date=race.race_date, year=race.year,
            distance_m=race.distance_m, arm=race.arm, roster=race.roster,
            triples=shuffled, horse_marginals=race.horse_marginals,
            pair_marginals=race.pair_marginals, true_set=race.true_set,
        )
        reordered = select_policies(shuffled_race)
        require({k: tuple(t.horses for t in v) for k, v in canonical.items()} ==
                {k: tuple(t.horses for t in v) for k, v in reordered.items()},
                f"row order changed policy selection: {key}")
        # A deliberately altered truth label can affect scoring, but the selector
        # sees only Q, scores, roster, and canonical rank and must remain identical.
        fake_truth = tuple(sorted(race.roster[:3]))
        if fake_truth != race.true_set:
            relabeled = RaceArm(
                race_id=race.race_id, race_date=race.race_date, year=race.year,
                distance_m=race.distance_m, arm=race.arm, roster=race.roster,
                triples=[Triple(**{**t.__dict__, "true_set": t.horses == fake_truth}) for t in race.triples],
                horse_marginals=race.horse_marginals,
                pair_marginals=race.pair_marginals, true_set=fake_truth,
            )
            relabeled_selection = select_policies(relabeled)
            require({k: tuple(t.horses for t in v) for k, v in canonical.items()} ==
                    {k: tuple(t.horses for t in v) for k, v in relabeled_selection.items()},
                    f"label change altered policy selection: {key}")
        tested += 1
    return {"race_arm_cases": tested, "source_order_invariant": True, "truth_label_invariant": True}


def baseline_structure_check(
    race_arms: dict[tuple[str, str], RaceArm],
) -> dict[str, Any]:
    """Record policy duplication implied by the saved additive baseline."""
    race_ids = sorted({race_id for race_id, arm in race_arms if arm == "matched_baseline"})
    pair_axis_equal = 0
    single_k3_equal = 0
    for race_id in race_ids:
        race = race_arms[(race_id, "matched_baseline")]
        selected = select_policies(race)
        max_pair = identify_pair_for_k(
            race, "maximum_joint_pair", 3, selected[("maximum_joint_pair", 3)]
        )
        top_two = identify_pair_for_k(
            race, "top_two_marginal_pair", 3, selected[("top_two_marginal_pair", 3)]
        )
        k3_mass = identify_pair_for_k(
            race, "maximum_k_ticket_pair_mass", 3,
            selected[("maximum_k_ticket_pair_mass", 3)],
        )
        k4_mass = identify_pair_for_k(
            race, "maximum_k_ticket_pair_mass", 4,
            selected[("maximum_k_ticket_pair_mass", 4)],
        )
        require(max_pair == top_two == k3_mass == k4_mass,
                f"baseline pair axes are not duplicated as expected: {race_id}")
        pair_axis_equal += 1
        if selected[("single_top3_anchor", 3)] == selected[("unrestricted_top_k", 3)]:
            single_k3_equal += 1
    require(pair_axis_equal == RACE_COUNT, "baseline duplicated-pair check incomplete")
    require(single_k3_equal == RACE_COUNT, "baseline single-anchor K3 parity check incomplete")
    return {
        "baseline_races": len(race_ids),
        "max_joint_top_two_max_k_mass_axes_equal": pair_axis_equal,
        "single_anchor_k3_unrestricted_ticket_lists_equal": single_k3_equal,
        "interpretation": (
            "saved baseline additive-unary structure yields duplicated selection controls; "
            "these are not independent policy signals"
        ),
    }


def compare_frozen_a_outputs(
    policy_rows: list[dict[str, Any]],
    bootstrap_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare independent results to A's frozen numeric outputs, without importing A."""
    a_per_race_rel = "jeju/research/20261010_pair_axis_v1/outputs/per_race_metrics.csv"
    a_primary_rel = "jeju/research/20261010_pair_axis_v1/outputs/primary_comparisons.csv"
    for rel, expected in A_FROZEN_OUTPUT_HASHES.items():
        require(sha256(ROOT / rel) == expected, f"frozen A output hash mismatch: {rel}")
    a_per_race = read_csv(ROOT / a_per_race_rel)
    a_primary = read_csv(ROOT / a_primary_rel)
    a_lookup = {
        (row["race_id"], row["arm"], row["policy"], int(row["budget_k"])): row
        for row in a_per_race if int(row["budget_k"]) in K_VALUES
    }
    require(len(a_lookup) == len(policy_rows), "A frozen per-race table row count mismatch")
    max_q_mass_delta = 0.0
    max_axis_probability_delta = 0.0
    for row in policy_rows:
        key = (row["race_id"], row["arm"], row["policy"], row["ticket_budget"])
        other = a_lookup.get(key)
        require(other is not None, f"A per-race row missing: {key}")
        require(row["ticket_hit"] == int(other["ticket_hit"]), f"ticket-hit label mismatch: {key}")
        a_tickets = [tuple(map(int, item.split(","))) for item in json.loads(other["tickets"])]
        c_tickets = [tuple(ticket) for ticket in row["selected_tickets"]]
        require(c_tickets == a_tickets, f"selected ticket order mismatch: {key}")
        q_delta = abs(row["selected_mass"] - float(other["selected_q_mass"]))
        max_q_mass_delta = max(max_q_mass_delta, q_delta)
        require(q_delta <= 2e-14, f"selected q mass mismatch: {key}")
        a_axis = tuple(map(int, other["axis_horses"].split(","))) if other["axis_horses"] else None
        c_axis = tuple(row["axis_horses"]) if row["axis_horses"] is not None else None
        require(c_axis == a_axis, f"axis selection mismatch: {key}")
        if row["axis_probability"] is None:
            require(other["axis_probability"] == "", f"unexpected A axis probability: {key}")
        else:
            axis_delta = abs(row["axis_probability"] - float(other["axis_probability"]))
            max_axis_probability_delta = max(max_axis_probability_delta, axis_delta)
            require(axis_delta <= 2e-14, f"axis probability mismatch: {key}")
        if row["axis_hit"] is None:
            require(other["axis_hit"] == "", f"unexpected A axis label: {key}")
        else:
            require(row["axis_hit"] == int(float(other["axis_hit"])), f"axis label mismatch: {key}")
        if row["completion_hit"] is None:
            require(other["conditional_completion"] == "", f"unexpected A conditional label: {key}")
        else:
            require(row["completion_hit"] == int(float(other["conditional_completion"])),
                    f"conditional completion label mismatch: {key}")
        if row["exact_top2_pair_hit"] is None:
            require(other["exact_top2_pair_hit"] == "", f"unexpected A exact-Top2 label: {key}")
        else:
            require(row["exact_top2_pair_hit"] == int(float(other["exact_top2_pair_hit"])),
                    f"secondary exact-Top2 label mismatch: {key}")

    a_primary_lookup = {
        (row["arm"], int(row["budget_k"])): row for row in a_primary
    }
    require(len(a_primary_lookup) == 4, "A primary comparison table should contain four frozen rows")
    max_estimate_delta = 0.0
    max_ci_delta = 0.0
    for row in bootstrap_rows:
        key = (row["arm"], row["ticket_budget"])
        other = a_primary_lookup.get(key)
        require(other is not None, f"A primary comparison missing: {key}")
        expected = ("maximum_joint_pair_minus_unrestricted" if row["left_policy"] == "maximum_joint_pair"
                    else "")
        require(other["comparison"] == expected, f"A primary contrast definition mismatch: {key}")
        est_delta = abs(row["estimate"] - float(other["estimate_hit_rate_delta"]))
        ci_delta = max(abs(row["ci95_low"] - float(other["ci95_low"])),
                       abs(row["ci95_high"] - float(other["ci95_high"])))
        max_estimate_delta = max(max_estimate_delta, est_delta)
        max_ci_delta = max(max_ci_delta, ci_delta)
        require(est_delta <= 2e-15 and ci_delta <= 2e-15,
                f"primary bootstrap result differs from frozen A output: {key}")
    return {
        "a_per_race_rows_compared": len(policy_rows),
        "a_primary_bootstrap_rows_compared": len(bootstrap_rows),
        "selection_order_labels_and_axes_exact_match": True,
        "max_selected_q_mass_absolute_delta": max_q_mass_delta,
        "max_axis_probability_absolute_delta": max_axis_probability_delta,
        "max_primary_estimate_absolute_delta": max_estimate_delta,
        "max_primary_interval_endpoint_absolute_delta": max_ci_delta,
        "a_output_hashes": {
            rel: {"sha256": sha256(ROOT / rel), "bytes": (ROOT / rel).stat().st_size}
            for rel in A_FROZEN_OUTPUT_HASHES
        },
    }


def synthetic_tie_check() -> dict[str, Any]:
    roster = (1, 2, 3, 4, 5, 6)
    triples = []
    for index, horses in enumerate(itertools.combinations(roster, 3)):
        triples.append(Triple(
            race_id="synthetic", race_date="1900-01-01", year=1900,
            distance_m=800.0, arm="candidate", triple_index=index,
            horses=horses, probability=1.0 / math.comb(len(roster), 3), true_set=(index == 0),
            canonical_rank=index + 1, total_energy=0.0,
        ))
    horse_marginals = {horse: math.comb(len(roster) - 1, 2) / math.comb(len(roster), 3)
                       for horse in roster}
    pair_marginals = {pair: (len(roster) - 2) / math.comb(len(roster), 3)
                      for pair in itertools.combinations(roster, 2)}
    race = RaceArm("synthetic", "1900-01-01", 1900, 800.0, "candidate", roster,
                   triples, horse_marginals, pair_marginals, (1, 2, 3))
    selected = select_policies(race)
    expected_pair = (1, 2)
    require(identify_pair_for_k(race, "top_two_marginal_pair", 3, selected[("top_two_marginal_pair", 3)]) == expected_pair,
            "top-two-marginal pair exact tie failed numeric order")
    require(identify_pair_for_k(race, "maximum_joint_pair", 3, selected[("maximum_joint_pair", 3)]) == expected_pair,
            "maximum-joint pair exact tie failed numeric order")
    require(identify_pair_for_k(race, "maximum_k_ticket_pair_mass", 3, selected[("maximum_k_ticket_pair_mass", 3)]) == expected_pair,
            "maximum K-mass pair exact tie failed numeric order")
    require(identify_single_anchor(race) == 1, "single-axis exact tie failed numeric order")
    return {"passed": True, "pair_tie_rule": "ascending numeric pair", "single_tie_rule": "ascending horse number"}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                if isinstance(value, (list, tuple, dict)) else value
                for key, value in row.items()
            })


def main() -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    before_hashes = verify_hashes()
    triple_groups = load_triples()
    runner_rows, runner_by_race = load_runner_rows()
    feature_by_api, feature_by_race = load_feature_identity(runner_rows)
    metrics = load_race_metrics()
    report_receipt = load_report_receipt()
    race_arms = build_race_arms(triple_groups, runner_by_race, feature_by_race, metrics)
    cohort = verify_cohort_and_saved_top6(race_arms, runner_rows, metrics, report_receipt)
    tie_check = synthetic_tie_check()
    invariance = selection_invariance_check(race_arms)
    baseline_structure = baseline_structure_check(race_arms)

    policy_rows: list[dict[str, Any]] = []
    ticket_rows: list[dict[str, Any]] = []
    race_ids = sorted(metrics)
    for race_id in race_ids:
        for arm in ARMS:
            race = race_arms[(race_id, arm)]
            selected = select_policies(race)
            for policy in POLICIES:
                for k in K_VALUES:
                    row, ticket_items = score_policy(
                        race, policy, k, selected[(policy, k)], feature_by_race
                    )
                    policy_rows.append(row)
                    ticket_rows.extend(ticket_items)
            for policy in ("maximum_joint_pair", "single_top3_anchor"):
                for k in K_VALUES:
                    axis = next(
                        row for row in policy_rows
                        if row["race_id"] == race_id and row["arm"] == arm
                        and row["policy"] == policy and row["ticket_budget"] == k
                    )
                    # The first loop already contains all K=3/K=4 rows; this
                    # lookup confirms both budgets share the same selected axis.
                    peer_k = 7 - k
                    peer = next(
                        row for row in policy_rows
                        if row["race_id"] == race_id and row["arm"] == arm
                        and row["policy"] == policy and row["ticket_budget"] == peer_k
                    )
                    require(axis["axis_horses"] == peer["axis_horses"] and
                            axis["axis_probability"] == peer["axis_probability"],
                            f"axis changes with ticket budget: {race_id} {arm} {policy}")

    # Six-ticket reference is reported only as the immutable parity result.
    six_reference = {
        "matched_baseline": {"races": RACE_COUNT, "hits": 407, "hit_rate": 407 / RACE_COUNT},
        "candidate": {"races": RACE_COUNT, "hits": 423, "hit_rate": 423 / RACE_COUNT},
        "source_parity_passed": True,
        "policy_computed": False,
    }
    summaries = summary_for_policies(policy_rows)
    bootstrap, bootstrap_metadata = bootstrap_primary_contrasts(policy_rows, race_ids, metrics)
    a_output_parity = compare_frozen_a_outputs(policy_rows, bootstrap)
    axis_bins, axis_overall, ticket_bins, cutoff_rows, coverage_rows = calibration_summaries(policy_rows)

    after_hashes = verify_hashes()
    require(before_hashes == after_hashes, "source hashes changed during independent validation")
    write_csv(OUTPUTS / "policy_race_results.csv", policy_rows)
    write_csv(OUTPUTS / "selected_tickets.csv", ticket_rows)
    write_csv(OUTPUTS / "policy_summary.csv", summaries)
    write_csv(OUTPUTS / "primary_date_bootstrap.csv", bootstrap)
    write_csv(OUTPUTS / "axis_calibration_bins.csv", axis_bins)
    write_csv(OUTPUTS / "axis_calibration_overall.csv", axis_overall)
    write_csv(OUTPUTS / "ticket_mass_calibration_bins.csv", ticket_bins)
    write_csv(OUTPUTS / "confidence_cutoff_summary.csv", cutoff_rows)
    write_csv(OUTPUTS / "score_ranked_coverage_summary.csv", coverage_rows)

    receipt = {
        "study": "20261010_pair_axis_review_v1",
        "independent_of_a_helpers": True,
        "frozen_plan_sha256": FROZEN_PLAN_HASHES["jeju/research/20261010_pair_axis_v1/PLAN.md"],
        "frozen_input_contract_sha256": FROZEN_PLAN_HASHES["jeju/research/20261010_pair_axis_v1/INPUT_CONTRACT.md"],
        "precompute_lock_sha256": PRECOMPUTE_LOCK_HASH,
        "source_hashes_before": before_hashes,
        "source_hashes_after": after_hashes,
        "cohort": cohort,
        "probability_checks": {
            "per_race_arm_sum_tolerance": IDENTITY_TOLERANCE,
            "top3_marginal_sum": 3.0,
            "pair_in_top3_marginal_sum": 3.0,
            "runner_marginals_and_labels_match": True,
            "one_true_set_per_race_arm": True,
            "complete_triples_match_roster": True,
            "canonical_rank_energy_parity": True,
        },
        "saved_top6_parity": six_reference,
        "policy_count": len(policy_rows),
        "ticket_count": len(ticket_rows),
        "policies": list(POLICIES),
        "ticket_budgets": list(K_VALUES),
        "selection_invariance": invariance,
        "synthetic_exact_tie_check": tie_check,
        "baseline_structure_check": baseline_structure,
        "frozen_a_output_parity": a_output_parity,
        "summaries": summaries,
        "primary_bootstrap": bootstrap,
        "bootstrap_metadata": bootstrap_metadata,
        "artifact_files": [
            "policy_race_results.csv", "selected_tickets.csv", "policy_summary.csv",
            "primary_date_bootstrap.csv", "axis_calibration_bins.csv",
            "axis_calibration_overall.csv", "ticket_mass_calibration_bins.csv",
            "confidence_cutoff_summary.csv", "score_ranked_coverage_summary.csv",
        ],
        "artifact_hashes": {
            path.name: {"sha256": sha256(path), "bytes": path.stat().st_size}
            for path in sorted(OUTPUTS.glob("*.csv"))
        },
        "runtime": {
            "python": sys.version,
            "numpy": np.__version__,
        },
        "validator_sha256": sha256(HERE / "independent_validation.py"),
        "interpretation": "Retrospective development cohort; exact Top2 is an outcome-only secondary label, never a probability from unordered Q.",
    }
    receipt_path = OUTPUTS / "independent_validation_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": True,
        "cohort": cohort,
        "saved_top6_parity": six_reference,
        "policy_rows": len(policy_rows),
        "ticket_rows": len(ticket_rows),
        "bootstrap_contrasts": len(bootstrap),
        "outputs": str(OUTPUTS),
        "receipt_sha256": sha256(receipt_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
