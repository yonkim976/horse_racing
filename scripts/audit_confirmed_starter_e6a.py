#!/usr/bin/env python3
"""Audit E6-A carried-weight sources and build isolated retrospective features."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import polars as pl

from horse_racing.analysis.confirmed_starter_e3 import sha256_file
from horse_racing.analysis.confirmed_starter_e6a import build_carried_weight_features
from horse_racing.parsers.entry_sheet import parse_entry_sheet_page
from horse_racing.parsers.race_day import (
    AiRaceResultItem,
    DetailedRaceResultItem,
    parse_items,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / (
    "data/datasets/confirmed_starter_e2_h1_remediation_retrospective/"
    "start_minus_30m/dataset.parquet"
)
H1_MANIFEST = DATASET.with_name("manifest.json")
DATABASE = ROOT / "data/horse_racing.sqlite3"
OUTPUT = ROOT / "data/experiments/confirmed_starter_e6a_20260912_attempt4"
BOUND = "2026-05-31"
HISTORY_START = "2015-01-03"
EXPECTED_DATASET_HASH = "9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7"
EXPECTED_MANIFEST_HASH = "f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801"
FROZEN = [
    DATASET,
    H1_MANIFEST,
    ROOT / "data/experiments/confirmed_starter_e3_20260911/artifact_manifest.json",
    ROOT / "data/experiments/confirmed_starter_e4_diagnostic_20260911/artifact_manifest.json",
    ROOT / "data/experiments/confirmed_starter_e5a_20260912/artifact_manifest.json",
    ROOT / "data/experiments/confirmed_starter_e5a_r3_r4_20260912/artifact_manifest.json",
    ROOT / "docs/CONFIRMED_STARTER_E5B_2026-09-12.md",
    ROOT / "data/experiments/confirmed_starter_e5b_race_objective_20260912/artifact_manifest.json",
    ROOT / "data/experiments/model_runs.jsonl",
]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def frozen_hashes() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): sha256_file(path) for path in FROZEN}


def git_state() -> dict[str, Any]:
    status = subprocess.run(
        ["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.splitlines()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    return {"head": head, "dirty": bool(status), "status_short": status}


def json_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def source_documents(connection: sqlite3.Connection, operation: str) -> list[dict[str, Any]]:
    if operation == "entrySheet_2":
        meet_expression, date_expression = "$.meet", "$.rc_date"
    else:
        meet_expression, date_expression = "$.rccrs_cd", "$.race_dt"
    rows = connection.execute(
        f"""
        SELECT local_path, sha256, requested_at_ms, retrieved_at_ms,
               json_extract(request_params_json, '{date_expression}') AS source_date
        FROM source_documents
        WHERE operation = ?
          AND json_extract(request_params_json, '{meet_expression}') = 1
          AND json_extract(request_params_json, '{date_expression}')
              BETWEEN '20250104' AND '20260531'
        ORDER BY requested_at_ms, id
        """,
        (operation,),
    ).fetchall()
    return [
        {
            "local_path": row[0],
            "sha256": row[1],
            "requested_at_ms": row[2],
            "retrieved_at_ms": row[3],
            "source_date": row[4],
        }
        for row in rows
    ]


def parse_source(
    operation: str, documents: list[dict[str, Any]]
) -> tuple[dict[Any, Any], dict[Any, str]]:
    weights: dict[tuple[str, int, int], float | None] = {}
    hashes: dict[tuple[str, int, int], str] = {}
    unique = {document["sha256"]: document for document in documents}
    for document in unique.values():
        payload = json_payload(ROOT / document["local_path"])
        if operation == "entrySheet_2":
            items = parse_entry_sheet_page(payload).items
        elif operation == "raceResult":
            items = parse_items(payload, AiRaceResultItem)
        else:
            items = parse_items(payload, DetailedRaceResultItem)
        for item in items:
            key = (item.race_date.isoformat(), int(item.race_number), int(item.horse_number))
            if key in weights:
                raise ValueError(f"{operation}: duplicate parsed source key {key}")
            weights[key] = item.carried_weight_kg
            hashes[key] = document["sha256"]
    return weights, hashes


def _equal_weight(left: float | None, right: float | None) -> bool:
    return (left is None and right is None) or (
        left is not None and right is not None and abs(left - right) <= 1e-12
    )


def db_frames(connection: sqlite3.Connection) -> tuple[pl.DataFrame, pl.DataFrame]:
    rows = connection.execute(
        """
        SELECT r.race_date_local, r.id AS race_id, r.race_number,
               e.id AS race_entry_id, e.horse_id, e.horse_number,
               e.carried_weight_kg, e.scratched, rr.finish_position
        FROM race_entries e
        JOIN races r ON r.id = e.race_id
        JOIN racecourses c ON c.id = r.racecourse_id
        LEFT JOIN race_results rr ON rr.race_entry_id = e.id
        WHERE c.kra_meet_code = 1 AND r.race_date_local <= ?
        ORDER BY r.race_date_local, r.id, e.id
        """,
        (BOUND,),
    ).fetchall()
    frame = pl.DataFrame(
        rows,
        schema=[
            "race_date_local",
            "race_id",
            "race_number",
            "race_entry_id",
            "horse_id",
            "horse_number",
            "carried_weight_kg",
            "scratched",
            "finish_position",
        ],
        orient="row",
    )
    history = frame.with_columns(
        pl.when(
            (~pl.col("scratched").cast(pl.Boolean))
            & pl.col("finish_position").is_not_null()
            & (
                pl.col("finish_position").is_between(1, 89)
                | pl.col("finish_position").is_in([91, 92])
            )
        )
        .then(
            pl.when(pl.col("finish_position") == 91)
            .then(pl.lit("disqualified"))
            .when(pl.col("finish_position") == 92)
            .then(pl.lit("started_dnf"))
            .otherwise(pl.lit("normal_finish"))
        )
        .when(pl.col("scratched").cast(pl.Boolean) | pl.col("finish_position").is_in([93, 94, 95]))
        .then(pl.lit("not_started"))
        .otherwise(pl.lit("unresolved"))
        .alias("start_state")
    )
    return frame, history


def independent_features(targets: pl.DataFrame, history: pl.DataFrame) -> pl.DataFrame:
    relative = targets.select("race_id", "race_entry_id", "carried_weight_kg").with_columns(
        (pl.col("carried_weight_kg") - pl.col("carried_weight_kg").mean().over("race_id")).alias(
            "independent_relative"
        )
    )
    actual = (
        history.filter(
            pl.col("start_state").is_in(["normal_finish", "started_dnf", "disqualified"])
        )
        .sort("horse_id", "race_date_local", "race_id", "race_entry_id")
        .select(
            "horse_id",
            pl.col("race_date_local").alias("prior_date"),
            pl.col("race_entry_id").alias("prior_entry_id"),
            pl.col("carried_weight_kg").alias("prior_weight"),
        )
    )
    target_ordered = targets.sort("horse_id", "race_date_local", "race_id", "race_entry_id")
    prior = target_ordered.join_asof(
        actual,
        left_on="race_date_local",
        right_on="prior_date",
        by="horse_id",
        strategy="backward",
        allow_exact_matches=False,
    ).select(
        "race_id",
        "race_entry_id",
        "prior_entry_id",
        "prior_weight",
        (pl.col("carried_weight_kg") - pl.col("prior_weight")).alias("independent_delta"),
    )
    return relative.join(prior, on=["race_id", "race_entry_id"], validate="1:1")


def frame_hash(frame: pl.DataFrame) -> str:
    return hashlib.sha256(frame.write_json().encode()).hexdigest()


def main() -> int:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite E6-A output: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    before = frozen_hashes()
    if before[str(DATASET.relative_to(ROOT))] != EXPECTED_DATASET_HASH:
        raise ValueError("H1 dataset hash mismatch")
    if before[str(H1_MANIFEST.relative_to(ROOT))] != EXPECTED_MANIFEST_HASH:
        raise ValueError("H1 manifest hash mismatch")
    h1 = pl.read_parquet(DATASET)
    if h1.height != 15579 or h1["race_id"].n_unique() != 1488:
        raise ValueError("H1 denominator mismatch")
    if h1.filter(pl.col("race_date_local") > BOUND).height:
        raise ValueError("post-bound H1 row")

    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    db, history = db_frames(connection)
    target_db = db.filter(pl.col("race_entry_id").is_in(h1["race_entry_id"].implode()))
    if target_db.height != h1.height:
        raise ValueError("DB target key coverage mismatch")
    db_join = h1.select(
        "race_id",
        "race_entry_id",
        pl.col("carried_weight_kg").alias("h1_weight"),
    ).join(
        target_db.select(
            "race_id",
            "race_entry_id",
            pl.col("carried_weight_kg").alias("db_weight"),
        ),
        on=["race_id", "race_entry_id"],
        validate="1:1",
    )
    db_mismatches = sum(
        not _equal_weight(row[0], row[1])
        for row in db_join.select("h1_weight", "db_weight").iter_rows()
    )
    if db_mismatches:
        raise ValueError(f"H1-vs-DB weight mismatches={db_mismatches}")

    operations = ("entrySheet_2", "raceResult", "raceRsutDtl")
    document_inventory: dict[str, Any] = {}
    source_values: dict[str, dict[Any, Any]] = {}
    source_hashes: dict[str, dict[Any, str]] = {}
    for operation in operations:
        documents = source_documents(connection, operation)
        values, hashes = parse_source(operation, documents)
        source_values[operation] = values
        source_hashes[operation] = hashes
        document_inventory[operation] = {
            "documents": len(documents),
            "unique_payloads": len({item["sha256"] for item in documents}),
            "dates": len({item["source_date"] for item in documents}),
            "requested_at_ms_min": min(item["requested_at_ms"] for item in documents),
            "requested_at_ms_max": max(item["requested_at_ms"] for item in documents),
            "retrieved_at_ms_min": min(item["retrieved_at_ms"] for item in documents),
            "retrieved_at_ms_max": max(item["retrieved_at_ms"] for item in documents),
            "all_collected_after_event": True,
            "source_rows": len(values),
        }

    evidence_rows = []
    for row in h1.select(
        "race_date_local",
        "race_number",
        "race_id",
        "race_entry_id",
        "horse_id",
        "horse_number",
        "carried_weight_kg",
    ).iter_rows(named=True):
        key = (row["race_date_local"], int(row["race_number"]), int(row["horse_number"]))
        evidence = {**row, "availability_status": "retrospective_only / availability_unverified"}
        for operation in operations:
            evidence[f"{operation}_weight_kg"] = source_values[operation].get(key)
            evidence[f"{operation}_source_sha256"] = source_hashes[operation].get(key)
            evidence[f"{operation}_matches_h1"] = _equal_weight(
                row["carried_weight_kg"], source_values[operation].get(key)
            )
        evidence_rows.append(evidence)
    evidence_frame = pl.DataFrame(evidence_rows).sort("race_id", "race_entry_id")
    for operation in operations:
        if evidence_frame[f"{operation}_source_sha256"].null_count():
            raise ValueError(f"{operation}: missing source evidence")
        if not evidence_frame[f"{operation}_matches_h1"].all():
            raise ValueError(f"{operation}: source mismatch")

    targets = h1.select(
        "race_id",
        "race_entry_id",
        "race_date_local",
        "horse_id",
        "carried_weight_kg",
        "is_debut",
        "win",
        "outcome_state",
    )
    features = build_carried_weight_features(
        targets, history, history_start_date=HISTORY_START
    ).sort("race_id", "race_entry_id")
    independent = independent_features(targets, history)
    checked = features.join(independent, on=["race_id", "race_entry_id"], validate="1:1")
    relative_mismatch = checked.filter(
        ~(pl.col("condition_carried_weight_rel_A").eq_missing(pl.col("independent_relative")))
    ).height
    delta_mismatch = checked.filter(
        ~(
            pl.col("condition_carried_weight_delta_prev_start").eq_missing(
                pl.col("independent_delta")
            )
        )
    ).height
    prior_key_mismatch = checked.filter(
        ~(pl.col("previous_actual_start_entry_id").eq_missing(pl.col("prior_entry_id")))
    ).height
    if relative_mismatch or delta_mismatch or prior_key_mismatch:
        raise ValueError("independent feature aggregate mismatch")

    baseline_hash = frame_hash(features)
    mutation_frames = {
        "target_results_changed": targets.with_columns(
            (1 - pl.col("win")).alias("win"), pl.lit("disqualified").alias("outcome_state")
        ),
        "target_results_deleted": targets.drop("win", "outcome_state"),
        "row_order_reversed": targets.reverse(),
    }
    invariance = {}
    for name, mutated in mutation_frames.items():
        candidate = build_carried_weight_features(
            mutated, history.reverse(), history_start_date=HISTORY_START
        ).sort("race_id", "race_entry_id")
        invariance[name] = {
            "feature_hash": frame_hash(candidate),
            "matches_baseline": candidate.equals(features),
        }
        if not candidate.equals(features):
            raise ValueError(f"mutation invariance failed: {name}")
    same_day_violation = (
        features.join(
            targets.select(
                "race_id",
                "race_entry_id",
                pl.col("race_date_local").alias("target_race_date_local"),
            ),
            on=["race_id", "race_entry_id"],
            validate="1:1",
        )
        .filter(
            pl.col("previous_actual_start_date").is_not_null()
            & (pl.col("previous_actual_start_date") >= pl.col("target_race_date_local"))
        )
        .height
    )
    if same_day_violation:
        raise ValueError("same-day result entered previous-start feature")
    invariance["same_day_results_excluded_by_strict_date"] = {
        "violations": same_day_violation,
        "matches_contract": True,
    }
    future = pl.DataFrame(
        {
            "race_date_local": ["2026-06-01"],
            "race_id": [-1],
            "race_number": [1],
            "race_entry_id": [-1],
            "horse_id": [int(targets["horse_id"][0])],
            "horse_number": [1],
            "carried_weight_kg": [1.0],
            "scratched": [False],
            "finish_position": [1],
            "start_state": ["normal_finish"],
        }
    )
    with_future = build_carried_weight_features(
        targets,
        pl.concat([history, future], how="diagonal_relaxed"),
        history_start_date=HISTORY_START,
    ).sort("race_id", "race_entry_id")
    invariance["synthetic_future_row"] = {
        "feature_hash": frame_hash(with_future),
        "matches_baseline": with_future.equals(features),
    }
    if not with_future.equals(features):
        raise ValueError("synthetic future row changed features")

    features.write_parquet(OUTPUT / "confirmed_starter_e6a_carried_weight_features.parquet")
    evidence_frame.write_parquet(OUTPUT / "confirmed_starter_e6a_carried_weight_evidence.parquet")
    status_counts = dict(Counter(features["previous_start_history_status"].to_list()))
    source_comparison = {}
    h1_key_set = {
        (row[0], int(row[1]), int(row[2]))
        for row in h1.select("race_date_local", "race_number", "horse_number").iter_rows()
    }
    for operation in operations:
        source_key_set = set(source_values[operation])
        source_comparison[operation] = {
            "h1_keys": len(h1_key_set),
            "source_keys": len(source_key_set),
            "common": len(h1_key_set & source_key_set),
            "missing_h1_keys": len(h1_key_set - source_key_set),
            "additional_post_event_nonstarter_keys": len(source_key_set - h1_key_set),
            "weight_mismatches_on_common": 0,
        }
    valid_weights = features["condition_carried_weight_kg"].drop_nulls()
    deltas = features["condition_carried_weight_delta_prev_start"].drop_nulls()
    audit = {
        "study": "E6-A carried-weight source and time-contract audit",
        "scope": {
            "meet": "Seoul",
            "population": "retrospective actual-starter conditional A",
            "rows": h1.height,
            "races": h1["race_id"].n_unique(),
            "dates": [h1["race_date_local"].min(), h1["race_date_local"].max()],
            "actual_result_upper_bound": BOUND,
        },
        "source_path": {
            "raw_fields": {
                "entrySheet_2": "wgBudam",
                "raceResult": "burdWgt",
                "raceRsutDtl": "pthrBurdWgt",
            },
            "parsers": {
                "entrySheet_2": "parsers/entry_sheet.py EntrySheetItem.parse_float",
                "raceResult": "parsers/race_day.py AiRaceResultItem.parse_float",
                "raceRsutDtl": "parsers/race_day.py DetailedRaceResultItem.parse_float",
            },
            "db": (
                "race_entries.carried_weight_kg "
                "(mutable, no field-level observed/effective timestamp)"
            ),
            "dataset": "confirmed_starter_dataset.py BASE_QUERY -> H1 non-selected column",
            "unit": "kg",
            "parser_rule": (
                "trim, remove comma where applicable, float; blank/dash/unparseable -> null"
            ),
            "research_validity_rule": (
                "finite 45.0..80.0 kg; invalid values are null/fail, not clipped"
            ),
        },
        "documents": document_inventory,
        "time_contract": {
            "event_time": "race scheduled/start date-time; not weight publication time",
            "observed_time": (
                "SourceDocument requested_at_ms/retrieved_at_ms; all target docs post-event"
            ),
            "published_time": "not stored",
            "effective_time": "not stored for carried-weight changes/corrections",
            "revision_history": "not stored as field-level immutable revisions",
            "entry_weight_vs_final_weight": (
                "entrySheet, AI result, detailed result agree on all H1 keys, but all copies were "
                "retrieved post-event and do not prove T-30 state"
            ),
            "classification": "retrospective_only / availability_unverified",
        },
        "source_comparison": source_comparison,
        "db_comparison": {"rows": target_db.height, "h1_weight_mismatches": db_mismatches},
        "features": {
            "condition_carried_weight_kg": {
                "formula": "H1 carried_weight_kg",
                "non_null": len(valid_weights),
                "missing": features["condition_carried_weight_kg"].null_count(),
                "missing_rate": features["condition_carried_weight_kg"].null_count() / h1.height,
                "min": valid_weights.min(),
                "max": valid_weights.max(),
                "audit_status": "retrospective_pass; live_availability_unverified",
            },
            "condition_carried_weight_rel_A": {
                "formula": "own weight minus mean of finite weights in retrospective A race",
                "denominator": "finite valid A weights only",
                "minimum_valid_observations": 2,
                "target_missing_policy": "null",
                "all_missing_policy": "null with all_missing status",
                "missing": features["condition_carried_weight_rel_A"].null_count(),
                "independent_mismatches": relative_mismatch,
                "audit_status": "retrospective_A_only; live_F_t_unavailable",
            },
            "condition_carried_weight_delta_prev_start": {
                "formula": (
                    "target weight minus immediately previous strictly earlier actual start weight"
                ),
                "actual_start_states": ["normal_finish", "started_dnf", "disqualified"],
                "excluded_states": ["not_started", "unresolved"],
                "missing_prior_weight_policy": "null; do not skip to older non-null start",
                "history_start": HISTORY_START,
                "history_end_bound": BOUND,
                "history_status_counts": status_counts,
                "non_null": len(deltas),
                "missing": features["condition_carried_weight_delta_prev_start"].null_count(),
                "min": deltas.min(),
                "max": deltas.max(),
                "independent_delta_mismatches": delta_mismatch,
                "independent_prior_key_mismatches": prior_key_mismatch,
                "audit_status": "retrospective_pass_with_left_truncation_flag",
            },
        },
        "result_invariance": {
            "baseline_feature_hash": baseline_hash,
            "fixed_population": "H1 A keys; result mutations do not redefine population",
            "fixed_observation_rule": (
                f"history race_date_local <= {BOUND}; prior date strictly less"
            ),
            "checks": invariance,
        },
        "candidate_decision": {
            "all_three_saved_as_isolated_auxiliary_features": True,
            "added_to_136_predictors": False,
            "causal_effect_claimed": False,
            "live_PIT_passed": False,
            "reason": (
                "post-event raw sources agree retrospectively; publication/effective history absent"
            ),
        },
        "git": git_state(),
        "code_sha256": {
            "scripts/audit_confirmed_starter_e6a.py": sha256_file(Path(__file__)),
            "src/horse_racing/analysis/confirmed_starter_e6a.py": sha256_file(
                ROOT / "src/horse_racing/analysis/confirmed_starter_e6a.py"
            ),
        },
        "database": {
            "path": "data/horse_racing.sqlite3",
            "sha256": sha256_file(DATABASE),
            "read_only_uri": True,
            "queries_bounded_at": BOUND,
        },
    }
    write_json(OUTPUT / "confirmed_starter_e6a_carried_weight_audit.json", audit)
    after = frozen_hashes()
    if before != after:
        raise ValueError("frozen artifact changed")
    write_json(
        OUTPUT / "preservation.json",
        {
            "before": before,
            "after": after,
            "unchanged": True,
            "actual_tree_fit_count": 0,
            "post_2026_05_31_actual_rows_accessed": False,
            "operating_registry_modified": False,
        },
    )
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
