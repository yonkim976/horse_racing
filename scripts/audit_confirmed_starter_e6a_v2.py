#!/usr/bin/env python3
"""Read-only, dated all-track E6-A v2 predecessor and provenance audit."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

import polars as pl

from horse_racing.analysis.confirmed_starter_e6a_v2 import (
    adapt_history_outcomes,
    build_carried_weight_features_v2,
)
from horse_racing.collectors.kra_api import response_body
from horse_racing.parsers.entry_sheet import parse_entry_sheet_page
from horse_racing.parsers.race_day import AiRaceResultItem, DetailedRaceResultItem, parse_items

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/experiments/confirmed_starter_e6a_v2_20260913_attempt4"
H1 = ROOT / (
    "data/datasets/confirmed_starter_e2_h1_remediation_retrospective/"
    "start_minus_30m/dataset.parquet"
)
OLD = ROOT / (
    "data/experiments/confirmed_starter_e6a_20260912_attempt4/"
    "confirmed_starter_e6a_carried_weight_features.parquet"
)
REVIEW = ROOT / "data/logs/confirmed_starter_e6a_independent_review_20260912.json"
DB = ROOT / "data/horse_racing.sqlite3"
BOUND = "2026-05-31"
OPERATIONS = ("entrySheet_2", "raceResult", "raceRsutDtl")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, payload: Any) -> None:
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def db_history(connection: sqlite3.Connection) -> pl.DataFrame:
    rows = connection.execute(
        """
        SELECT r.race_date_local, r.id AS race_id, r.race_number,
               c.kra_meet_code AS meet_code, r.status AS race_status,
               e.id AS race_entry_id, e.horse_id, h.kra_horse_id,
               e.horse_number, e.carried_weight_kg, e.scratched,
               rr.finish_position, rr.rank_remark, rr.disqualified
        FROM race_entries e
        JOIN races r ON r.id=e.race_id
        JOIN racecourses c ON c.id=r.racecourse_id
        JOIN horses h ON h.id=e.horse_id
        LEFT JOIN race_results rr ON rr.race_entry_id=e.id
        WHERE r.race_date_local <= ?
        ORDER BY r.race_date_local,r.id,e.id
        """,
        (BOUND,),
    ).fetchall()
    names = [
        "race_date_local",
        "race_id",
        "race_number",
        "meet_code",
        "race_status",
        "race_entry_id",
        "horse_id",
        "kra_horse_id",
        "horse_number",
        "carried_weight_kg",
        "scratched",
        "finish_position",
        "rank_remark",
        "disqualified",
    ]
    return adapt_history_outcomes(
        pl.DataFrame(rows, schema=names, orient="row", infer_schema_length=None)
    )


def raw_weight_evidence(
    connection: sqlite3.Connection, selected: pl.DataFrame
) -> dict[int, dict[str, Any]]:
    """Only parse documents for selected cross-track predecessors at/before bound."""
    keys = {
        (row["meet_code"], row["race_date_local"], row["race_number"], row["horse_number"]): row
        for row in selected.iter_rows(named=True)
    }
    relevant_dates = {(key[0], key[1].replace("-", "")) for key in keys}
    evidence: dict[int, dict[str, Any]] = {
        int(row["race_entry_id"]): {
            "race_entry_id": int(row["race_entry_id"]),
            "horse_id": int(row["horse_id"]),
            "kra_horse_id": str(row["kra_horse_id"]),
            "meet_code": int(row["meet_code"]),
            "race_date_local": row["race_date_local"],
            "race_number": int(row["race_number"]),
            "horse_number": int(row["horse_number"]),
            "db_weight_kg": row["carried_weight_kg"],
            "start_state": row["start_state"],
        }
        for row in selected.iter_rows(named=True)
    }
    for operation in OPERATIONS:
        meet_field = "$.meet" if operation == "entrySheet_2" else "$.rccrs_cd"
        date_field = "$.rc_date" if operation == "entrySheet_2" else "$.race_dt"
        docs = connection.execute(
            f"""
            SELECT local_path,sha256,retrieved_at_ms,
                   json_extract(request_params_json,'{meet_field}'),
                   json_extract(request_params_json,'{date_field}')
            FROM source_documents
            WHERE operation=?
              AND json_extract(request_params_json,'{date_field}') <= '20260531'
            ORDER BY retrieved_at_ms,id
            """,
            (operation,),
        ).fetchall()
        for path, declared_hash, observed_ms, meet, source_date in docs:
            if (int(meet), source_date) not in relevant_dates:
                continue
            source_path = ROOT / path
            if sha(source_path) != declared_hash:
                raise ValueError(f"source hash mismatch: {path}")
            raw = json.loads(source_path.read_text())
            raw_items = (response_body(raw).get("items") or {}).get("item", [])
            if isinstance(raw_items, dict):
                raw_items = [raw_items]
            if operation == "entrySheet_2":
                items = parse_entry_sheet_page(raw).items
                raw_field = "wgBudam"
            elif operation == "raceResult":
                items = parse_items(raw, AiRaceResultItem)
                raw_field = "burdWgt"
            else:
                items = parse_items(raw, DetailedRaceResultItem)
                raw_field = "pthrBurdWgt"
            for item, raw_item in zip(items, raw_items, strict=True):
                key = (
                    int(meet),
                    item.race_date.isoformat(),
                    int(item.race_number),
                    int(item.horse_number),
                )
                match = keys.get(key)
                if match is None:
                    continue
                entry_id = int(match["race_entry_id"])
                evidence[entry_id][operation] = {
                    "parsed_weight_kg": item.carried_weight_kg,
                    "raw_horse_id": str(item.horse_id),
                    "horse_id_matches_db": str(item.horse_id) == str(match["kra_horse_id"]),
                    "source_sha256": declared_hash,
                    "retrieved_at_ms": observed_ms,
                    "raw_field": raw_field,
                    "raw_value": raw_item.get(raw_field),
                }
    for item in evidence.values():
        matches = [
            operation in item
            and item[operation]["horse_id_matches_db"]
            and item[operation]["parsed_weight_kg"] == item["db_weight_kg"]
            for operation in OPERATIONS
        ]
        item["source_qualified"] = all(matches)
        item["available_source_count"] = sum(operation in item for operation in OPERATIONS)
        item["availability_status"] = (
            "retrospective_source_qualified_live_unverified"
            if item["source_qualified"]
            else "historical_weight_source_unverified"
        )
    return evidence


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"refusing to overwrite {OUT}")
    OUT.mkdir(parents=True)
    frozen = json.loads(
        (
            ROOT / "data/experiments/confirmed_starter_e6a_20260912_attempt4/artifact_manifest.json"
        ).read_text()
    )["files"]
    before = {name: sha(ROOT / name) for name in frozen}
    if before != frozen:
        raise ValueError("sealed E6-A manifest mismatch")
    h1 = pl.read_parquet(H1)
    old = pl.read_parquet(OLD)
    review = json.loads(REVIEW.read_text())
    if (
        h1.height != 15579
        or h1["race_id"].n_unique() != 1488
        or h1["race_date_local"].max() > BOUND
    ):
        raise ValueError("H1 scope mismatch")
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    all_history = db_history(connection)
    target_ids = set(h1["race_entry_id"].to_list())
    targets = h1.select(
        "race_id", "race_entry_id", "race_date_local", "horse_id", "carried_weight_kg", "is_debut"
    )
    h1_keys = set(targets.select("race_id", "race_entry_id").iter_rows())
    if len(h1_keys) != h1.height:
        raise ValueError("duplicate H1 keys")
    comparison = all_history.filter(pl.col("race_entry_id").is_in(target_ids)).select(
        "race_id", "race_entry_id", pl.col("carried_weight_kg").alias("db_weight")
    )
    if comparison.height != h1.height:
        raise ValueError("DB target coverage")
    if (
        targets.join(comparison, on=["race_id", "race_entry_id"], validate="1:1")
        .filter(~pl.col("carried_weight_kg").eq_missing(pl.col("db_weight")))
        .height
    ):
        raise ValueError("DB-H1 current weight mismatch")
    db_reference = build_carried_weight_features_v2(
        targets, all_history, history_start_date=all_history["race_date_local"].min()
    )
    joined = db_reference.join(
        old.select(
            "race_id",
            "race_entry_id",
            pl.col("previous_actual_start_entry_id").alias("old_prior_id"),
            pl.col("condition_carried_weight_delta_prev_start").alias("old_delta"),
        ),
        on=["race_id", "race_entry_id"],
        validate="1:1",
    )
    changed_db = joined.filter(
        ~pl.col("previous_actual_start_entry_id").eq_missing(pl.col("old_prior_id"))
    )
    cross_prior_ids = changed_db["previous_actual_start_entry_id"].drop_nulls().unique().to_list()
    selected = all_history.filter(pl.col("race_entry_id").is_in(cross_prior_ids))
    raw = raw_weight_evidence(connection, selected)
    qualified = {entry_id for entry_id, item in raw.items() if item["source_qualified"]}
    qualified_history = all_history.with_columns(
        pl.when(
            pl.col("race_entry_id").is_in(cross_prior_ids)
            & ~pl.col("race_entry_id").is_in(list(qualified))
        )
        .then(None)
        .otherwise(pl.col("carried_weight_kg"))
        .alias("carried_weight_kg"),
        pl.when(
            pl.col("race_entry_id").is_in(cross_prior_ids)
            & ~pl.col("race_entry_id").is_in(list(qualified))
        )
        .then(pl.lit("unverified"))
        .when(pl.col("race_entry_id").is_in(list(qualified)))
        .then(pl.lit("retrospective_source_qualified"))
        .otherwise(pl.lit("DB_weight_not_newly_cross_track"))
        .alias("weight_provenance_status"),
    )
    final = build_carried_weight_features_v2(
        targets, qualified_history, history_start_date=all_history["race_date_local"].min()
    )
    old_features = old.sort("race_id", "race_entry_id")
    final = final.sort("race_id", "race_entry_id")
    if set(final.select("race_id", "race_entry_id").iter_rows()) != h1_keys:
        raise ValueError("final key set mismatch")
    if (
        final.select("condition_carried_weight_kg", "condition_carried_weight_rel_A").equals(
            old_features.select("condition_carried_weight_kg", "condition_carried_weight_rel_A")
        )
        is False
    ):
        raise ValueError("current or relative feature changed")
    change = final.join(
        old.select(
            "race_id",
            "race_entry_id",
            *[
                pl.col(column).alias(f"old_{column}")
                for column in [
                    "condition_carried_weight_delta_prev_start",
                    "previous_actual_start_entry_id",
                    "previous_actual_start_date",
                    "previous_actual_start_weight_kg",
                    "previous_start_history_status",
                ]
            ],
        ),
        on=["race_id", "race_entry_id"],
        validate="1:1",
    ).join(
        db_reference.select(
            "race_id",
            "race_entry_id",
            pl.col("condition_carried_weight_delta_prev_start").alias("db_reference_delta"),
            pl.col("previous_actual_start_entry_id").alias("db_reference_prior_id"),
        ),
        on=["race_id", "race_entry_id"],
        validate="1:1",
    )
    changed_key_mask = ~change["previous_actual_start_entry_id"].eq_missing(
        change["old_previous_actual_start_entry_id"]
    )
    changed_delta_mask = ~change["db_reference_delta"].eq_missing(
        change["old_condition_carried_weight_delta_prev_start"]
    )
    source_unverified = change.filter(
        pl.col("previous_start_history_status") == "previous_actual_start_weight_unverified"
    ).height
    changed_rows = change.filter(changed_key_mask)
    if changed_rows.height != 167 or change.filter(changed_delta_mask).height != 119:
        raise ValueError("review DB-reference counts not reproduced")
    example = {
        str(entry_id): change.filter(pl.col("race_entry_id") == entry_id).row(0, named=True)
        for entry_id in (18703, 23224)
    }
    if (
        example["18703"]["db_reference_delta"] != 1.5
        or example["23224"]["db_reference_delta"] != 4.0
    ):
        raise ValueError("review example mismatch")
    if review["cross_track_detail"]["cross_track_latest_rows"] != changed_rows.height:
        raise ValueError("independent review mismatch")
    if change.filter(
        ~changed_key_mask
        & (
            ~pl.col("condition_carried_weight_delta_prev_start").eq_missing(
                pl.col("old_condition_carried_weight_delta_prev_start")
            )
        )
    ).height:
        raise ValueError("unaffected delta changed")
    final.write_parquet(OUT / "confirmed_starter_e6a_v2_features.parquet")
    change.write_parquet(OUT / "confirmed_starter_e6a_v2_cell_changes.parquet")
    pl.DataFrame(list(raw.values())).write_parquet(
        OUT / "confirmed_starter_e6a_v2_previous_source_evidence.parquet"
    )
    audit = {
        "target_scope": {"rows": h1.height, "races": h1["race_id"].n_unique(), "max_date": BOUND},
        "all_track_history": {
            "rows": all_history.height,
            "start_date": all_history["race_date_local"].min(),
            "max_date": all_history["race_date_local"].max(),
            "meet_state_counts": {
                str(meet): dict(Counter(rows["start_state"].to_list()))
                for meet, rows in all_history.group_by("meet_code")
            },
            "read_only_database": True,
        },
        "db_reference": {
            "changed_prior_keys": changed_rows.height,
            "changed_delta_null_aware": change.filter(changed_delta_mask).height,
            "examples": example,
        },
        "source_qualification": {
            "new_cross_track_prior_keys": len(raw),
            "qualified_keys": len(qualified),
            "unverified_target_rows": source_unverified,
            "rule": (
                "all three raw parser values, horse identity and DB weight must agree; "
                "otherwise selected prior remains but weight/delta null"
            ),
        },
        "feature_status_counts": dict(Counter(final["previous_start_history_status"].to_list())),
        "prior_count_with_no_db_actual": final.filter(
            pl.col("previous_actual_start_entry_id").is_null()
            & ~pl.col("previous_start_history_status").is_in(
                ["previous_actual_start_weight_unverified", "newer_previous_start_unresolved"]
            )
        ).height,
        "old_left_truncation_41_with_cross_track_prior": change.filter(
            (pl.col("old_previous_start_history_status") == "history_left_truncated_or_unobserved")
            & pl.col("db_reference_prior_id").is_not_null()
        ).height,
        "current_and_relative_unchanged": True,
        "unaffected_delta_changed": 0,
        "actual_tree_fit_count": 0,
        "actual_performance_evaluation_count": 0,
        "post_bound_actual_rows_accessed": False,
    }
    write("confirmed_starter_e6a_v2_audit.json", audit)
    after = {name: sha(ROOT / name) for name in frozen}
    if before != after:
        raise ValueError("sealed E6-A changed")
    write("preservation.json", {"before": before, "after": after, "unchanged": True})
    print(OUT)


if __name__ == "__main__":
    main()
