#!/usr/bin/env python3
"""Independently reconstruct gain/loss hit groups from the frozen report CSVs.

Uses only Python's standard library and writes one receipt inside this review
folder. It does not import the analysis agent's code or touch source artifacts.
"""
from __future__ import annotations

import ast
import csv
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[3]
REVIEW = ROOT / "jeju/research/20261010_joint_gain_loss_review_v1"
SOURCE = ROOT / "jeju/research/20261010_joint_relationship_v1"
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1"
EXPECTED_JOINT_MANIFEST = "d0d1a749afb6a6f894de1bb4263c9d67dd1e3b2d1a35bf1b5fd38d8948c656b0"
INPUTS = {
    "joint_manifest": SOURCE / "ARTIFACT_MANIFEST.json",
    "race_metrics": SOURCE / "outputs/report/race_metrics.csv",
    "runner_marginals": SOURCE / "outputs/report/runner_marginals.csv",
    "all_triples": SOURCE / "outputs/report/all_triples.parquet",
    "fit_parameters": SOURCE / "outputs/fit_parameters.json",
    "style_features": STYLE / "outputs/features.parquet",
}


def digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError(f"missing CSV header: {path}")
        return list(reader)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def parse_tickets(raw: str, *, race_id: str, field: str) -> list[frozenset[int]]:
    value = ast.literal_eval(raw)
    require(isinstance(value, list) and len(value) == 6,
            f"{race_id}: {field} does not contain six tickets")
    tickets = []
    for item in value:
        require(isinstance(item, str), f"{race_id}: {field} ticket is not a string")
        ticket = frozenset(int(part.strip()) for part in item.split(","))
        require(len(ticket) == 3, f"{race_id}: {field} ticket is not a 3-horse set")
        tickets.append(ticket)
    require(len(set(tickets)) == 6, f"{race_id}: {field} has duplicate tickets")
    return tickets


def main() -> None:
    resolved_review = REVIEW.resolve(strict=True)
    require(resolved_review == REVIEW, "review directory path unexpectedly resolves elsewhere")

    hashes = {name: digest(path) for name, path in INPUTS.items()}
    require(hashes["joint_manifest"] == EXPECTED_JOINT_MANIFEST,
            "joint relationship artifact manifest SHA-256 changed")
    joint_manifest = json.loads(INPUTS["joint_manifest"].read_text(encoding="utf-8"))
    for name in ("race_metrics", "runner_marginals", "all_triples", "fit_parameters"):
        rel = str(INPUTS[name].relative_to(SOURCE))
        expected = joint_manifest["files"][rel]["sha256"]
        require(hashes[name] == expected, f"manifest hash mismatch: {rel}")
    style_manifest_path = STYLE / "ARTIFACT_MANIFEST.json"
    style_manifest_hash = digest(style_manifest_path)
    style_manifest = json.loads(style_manifest_path.read_text(encoding="utf-8"))
    style_rel = str(INPUTS["style_features"].relative_to(ROOT))
    require(hashes["style_features"] == style_manifest["study_artifacts"][style_rel]["sha256"],
            "style feature table hash mismatch")
    fit_parameters = json.loads(INPUTS["fit_parameters"].read_text(encoding="utf-8"))
    require(fit_parameters["source_hashes_before_fit"].get(str(style_manifest_path.relative_to(ROOT)))
            == style_manifest_hash,
            "style history artifact manifest differs from fit-time locked source hash")

    races = read_csv(INPUTS["race_metrics"])
    runners = read_csv(INPUTS["runner_marginals"])
    require(len(races) == 1779, "unexpected race metric row count")
    require(len(runners) == 17412, "unexpected runner marginal row count")
    required_race = {
        "race_id", "race_date", "evaluation_year", "distance_m", "runner_rows",
        "baseline_hit6", "candidate_hit6", "baseline_six_tickets", "candidate_six_tickets",
    }
    required_runner = {"race_id", "race_date", "evaluation_year", "horse_number", "y_top3"}
    require(required_race <= set(races[0]), "race metrics schema is incomplete")
    require(required_runner <= set(runners[0]), "runner marginal schema is incomplete")

    race_by_id: dict[str, dict[str, str]] = {}
    for row in races:
        race_id = row["race_id"]
        require(race_id not in race_by_id, f"duplicate race metric key: {race_id}")
        race_by_id[race_id] = row

    runner_by_race: dict[str, list[dict[str, str]]] = defaultdict(list)
    runner_keys = set()
    truth_by_race: dict[str, set[int]] = defaultdict(set)
    for row in runners:
        race_id = row["race_id"]
        require(race_id in race_by_id, f"runner key has no race metric row: {race_id}")
        horse_number = int(row["horse_number"])
        key = (race_id, horse_number)
        require(key not in runner_keys, f"duplicate runner key: {key}")
        runner_keys.add(key)
        runner_by_race[race_id].append(row)
        require(row["race_date"] == race_by_id[race_id]["race_date"],
                f"race date mismatch for {race_id}")
        require(row["evaluation_year"] == race_by_id[race_id]["evaluation_year"],
                f"evaluation year mismatch for {race_id}")
        if int(row["y_top3"]) == 1:
            truth_by_race[race_id].add(horse_number)

    require(set(race_by_id) == set(runner_by_race), "race and runner key coverage differs")
    counts = Counter()
    by_year: dict[str, Counter] = defaultdict(Counter)
    by_distance: dict[str, Counter] = defaultdict(Counter)
    by_year_distance: dict[tuple[str, str], Counter] = defaultdict(Counter)
    changed_unordered = 0
    same_unordered = 0
    changed_ranked = 0
    same_ranked = 0
    gained_ids: list[str] = []
    lost_ids: list[str] = []
    race_days = set()

    for race_id, row in race_by_id.items():
        roster = runner_by_race[race_id]
        roster_numbers = {int(r["horse_number"]) for r in roster}
        truth = frozenset(truth_by_race[race_id])
        require(len(roster) == int(row["runner_rows"]), f"roster size mismatch for {race_id}")
        require(len(roster_numbers) == len(roster), f"duplicate horse number for {race_id}")
        require(len(truth) == 3 and truth <= roster_numbers,
                f"actual top-3 set is incomplete or outside roster for {race_id}")

        baseline = parse_tickets(row["baseline_six_tickets"], race_id=race_id,
                                 field="baseline_six_tickets")
        candidate = parse_tickets(row["candidate_six_tickets"], race_id=race_id,
                                  field="candidate_six_tickets")
        require(all(ticket <= roster_numbers for ticket in baseline + candidate),
                f"selected ticket is outside roster for {race_id}")
        baseline_hit = int(truth in baseline)
        candidate_hit = int(truth in candidate)
        require(baseline_hit == int(row["baseline_hit6"]),
                f"independent baseline hit mismatch for {race_id}")
        require(candidate_hit == int(row["candidate_hit6"]),
                f"independent candidate hit mismatch for {race_id}")

        if candidate_hit and not baseline_hit:
            group = "gained"
            gained_ids.append(race_id)
        elif baseline_hit and not candidate_hit:
            group = "lost"
            lost_ids.append(race_id)
        elif baseline_hit and candidate_hit:
            group = "bothhit"
        else:
            group = "bothmiss"
        counts[group] += 1
        year = str(int(row["evaluation_year"]))
        distance_value = float(row["distance_m"])
        require(distance_value.is_integer(), f"non-integer race distance for {race_id}")
        distance = str(int(distance_value))
        by_year[year][group] += 1
        by_distance[distance][group] += 1
        by_year_distance[(year, distance)][group] += 1
        race_days.add(row["race_date"])

        baseline_set, candidate_set = set(baseline), set(candidate)
        if baseline_set == candidate_set:
            same_unordered += 1
        else:
            changed_unordered += 1
        if baseline == candidate:
            same_ranked += 1
        else:
            changed_ranked += 1

    require(counts == Counter({"gained": 50, "lost": 34, "bothhit": 373, "bothmiss": 1322}),
            f"unexpected hit-group counts: {dict(counts)}")
    require((changed_unordered, same_unordered) == (1077, 702),
            "unordered ticket set change counts differ")
    require((changed_ranked, same_ranked) == (1535, 244),
            "ranked ticket list change counts differ")

    def sorted_counter(counter: Counter) -> dict[str, int]:
        return {key: int(counter.get(key, 0)) for key in
                ("gained", "lost", "bothhit", "bothmiss")}

    receipt = {
        "status": "PASS",
        "scope": "Independent reconstruction of the full-cohort 6-ticket hit groups from frozen report CSVs; no A analysis helper imported.",
        "source_manifest_sha256": hashes["joint_manifest"],
        "source_hashes": {
            "race_metrics.csv": hashes["race_metrics"],
            "runner_marginals.csv": hashes["runner_marginals"],
            "all_triples.parquet": hashes["all_triples"],
            "fit_parameters.json": hashes["fit_parameters"],
            "style_history_ablation_manifest.json": style_manifest_hash,
            "features.parquet": hashes["style_features"],
        },
        "method": {
            "cohort_key": "race_id",
            "runner_key": ["race_id", "horse_number"],
            "actual_set": "horse_number where frozen runner_marginals.y_top3 == 1; exactly 3 per race",
            "hit_definition": "actual unordered Top3 set is an element of that arm's six saved ticket sets",
            "groups": {
                "gained": "candidate hit and baseline miss",
                "lost": "baseline hit and candidate miss",
                "bothhit": "both hit",
                "bothmiss": "both miss",
            },
            "duplicate_race_expansion": "none; race_metrics must have one unique race_id row and runner keys must be unique",
            "null_to_zero": "not applied; y_top3 is read as the explicit frozen binary label, and missing/invalid values fail closed",
        },
        "cohort": {
            "races": len(races),
            "runners": len(runners),
            "race_days": len(race_days),
            "year_counts": {year: int(sum(by_year[year].values())) for year in sorted(by_year)},
            "all_ticket_sets_valid": True,
            "all_actual_top3_sets_have_three_runners": True,
        },
        "groups": sorted_counter(counts),
        "hit_counts": {
            "baseline": int(sum(int(r["baseline_hit6"]) for r in races)),
            "candidate": int(sum(int(r["candidate_hit6"]) for r in races)),
            "net": int(sum(int(r["candidate_hit6"]) - int(r["baseline_hit6"]) for r in races)),
        },
        "ticket_list_change_counts": {
            "unordered_same": same_unordered,
            "unordered_changed": changed_unordered,
            "ranked_same": same_ranked,
            "ranked_changed": changed_ranked,
        },
        "by_evaluation_year": {year: sorted_counter(by_year[year]) for year in sorted(by_year)},
        "by_distance_m": {distance: sorted_counter(by_distance[distance])
                          for distance in sorted(by_distance, key=int)},
        "by_evaluation_year_and_distance_m": {
            f"{year}_{distance}": sorted_counter(by_year_distance[(year, distance)])
            for year, distance in sorted(by_year_distance, key=lambda key: (int(key[0]), int(key[1])))
        },
        "gained_race_ids": sorted(gained_ids),
        "lost_race_ids": sorted(lost_ids),
        "limitations": [
            "The 84 cases are selected using the evaluation outcome and the two arms' hit states; their condition distributions are post hoc diagnostics, not a deployable pre-race selection rule.",
            "The cohort is repeatedly reused historical development data, and year/distance or other subgroup comparisons have small samples and multiplicity risk.",
            "This receipt does not yet validate the analysis agent's condition ledger, rank/energy diagnostics, beta decomposition, bootstrap intervals, or boundary margins.",
        ],
    }
    output = REVIEW / "outputs/core_reconstruction_receipt.json"
    output.resolve().relative_to(REVIEW.resolve())
    temp = output.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temp, output)
    print(json.dumps({"status": receipt["status"], "output": str(output.relative_to(ROOT)),
                      "groups": receipt["groups"], "hit_counts": receipt["hit_counts"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
