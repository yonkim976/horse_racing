#!/usr/bin/env python3
"""Read-only E1 audit of pre-race field evidence and post-race outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from horse_racing.analysis.dataset import apply_label_policy
from horse_racing.analysis.pre_race_field_contract import RunnerOutcome, classify_outcome

MAX_RESEARCH_DATE = "2026-05-31"
DEFAULT_START_DATE = "2025-01-04"
DEFAULT_MEET = 1
FROZEN_COUNTS = {
    "races": 1488,
    "entries": 15846,
    "normal_finish": 15531,
    "started_dnf": 47,
    "disqualified": 1,
    "did_not_start": 267,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows(connection: sqlite3.Connection, query: str, params: dict[str, object]) -> list[dict]:
    return [dict(row) for row in connection.execute(query, params)]


TARGET_QUERY = """
SELECT
    r.id AS race_id,
    e.id AS race_entry_id,
    e.horse_id,
    r.race_date_local,
    r.race_number,
    r.scheduled_at_ms,
    r.scheduled_at_ms - 1800000 AS cutoff_at_ms,
    e.horse_number,
    e.scratched AS scratched_current,
    rr.id AS result_id,
    rr.finish_position,
    rr.finish_time_ms,
    rr.rank_remark,
    rr.disqualified,
    (
        SELECT MIN(rs.observed_at_ms)
        FROM race_scratches AS rs
        WHERE rs.meet_code = :meet
          AND rs.race_date_local = r.race_date_local
          AND rs.race_number = r.race_number
          AND rs.horse_id = e.horse_id
          AND rs.race_date_local BETWEEN :start_date AND :end_date
    ) AS scratch_observed_at_ms
FROM races AS r
JOIN racecourses AS rc ON rc.id = r.racecourse_id
JOIN race_entries AS e ON e.race_id = r.id
LEFT JOIN race_results AS rr ON rr.race_entry_id = e.id
WHERE r.race_date_local BETWEEN :start_date AND :end_date
  AND rc.kra_meet_code = :meet
  AND r.status = 'completed'
ORDER BY r.race_date_local, r.race_number, e.horse_number
"""


SOURCE_DOCUMENT_QUERY = """
SELECT
    sd.id,
    ir.data_type,
    sd.operation,
    sd.request_params_json,
    sd.requested_at_ms,
    sd.retrieved_at_ms,
    sd.local_path,
    sd.sha256,
    COALESCE(
        json_extract(sd.request_params_json, '$.rc_date'),
        json_extract(sd.request_params_json, '$.race_dt')
    ) AS source_date
FROM source_documents AS sd
JOIN ingestion_runs AS ir ON ir.id = sd.ingestion_run_id
WHERE ir.data_type IN (
    'entry_sheet',
    'gate_entry_sheet',
    'race_scratches',
    'ai_race_result',
    'detailed_race_result'
)
  AND COALESCE(
        json_extract(sd.request_params_json, '$.rc_date'),
        json_extract(sd.request_params_json, '$.race_dt')
      ) BETWEEN :start_compact AND :end_compact
  AND CAST(COALESCE(
        json_extract(sd.request_params_json, '$.meet'),
        json_extract(sd.request_params_json, '$.rccrs_cd')
      ) AS INTEGER) = :meet
ORDER BY sd.retrieved_at_ms, sd.id
"""


def _source_summary(documents: list[dict], races: list[dict]) -> tuple[dict, list[dict]]:
    docs_by_type: dict[str, list[dict]] = defaultdict(list)
    for document in documents:
        docs_by_type[str(document["data_type"])].append(document)
    race_dates = {str(row["race_date_local"]).replace("-", "") for row in races}
    entry_documents = docs_by_type.get("entry_sheet", [])
    entry_by_date: dict[str, list[dict]] = defaultdict(list)
    for document in entry_documents:
        entry_by_date[str(document["source_date"])].append(document)

    races_with_document = 0
    races_with_pre_cutoff_document = 0
    for race in races:
        date_key = str(race["race_date_local"]).replace("-", "")
        matching = entry_by_date.get(date_key, [])
        races_with_document += bool(matching)
        races_with_pre_cutoff_document += any(
            int(document["retrieved_at_ms"]) <= int(race["cutoff_at_ms"]) for document in matching
        )

    by_type = {}
    samples = []
    for data_type, values in sorted(docs_by_type.items()):
        by_type[data_type] = {
            "documents": len(values),
            "covered_race_dates": len({str(value["source_date"]) for value in values} & race_dates),
            "earliest_retrieved_at_ms": min(int(value["retrieved_at_ms"]) for value in values),
            "latest_retrieved_at_ms": max(int(value["retrieved_at_ms"]) for value in values),
        }
        for value in (values[0], values[-1]):
            samples.append(
                {
                    "data_type": data_type,
                    "source_document_id": value["id"],
                    "source_date": value["source_date"],
                    "requested_at_ms": value["requested_at_ms"],
                    "retrieved_at_ms": value["retrieved_at_ms"],
                    "local_path": value["local_path"],
                    "sha256": value["sha256"],
                }
            )
    return (
        {
            "by_type": by_type,
            "entry_sheet_races_with_any_post_or_pre_event_document": races_with_document,
            "entry_sheet_races_with_document_retrieved_by_t_minus_30m": (
                races_with_pre_cutoff_document
            ),
            "timestamp_semantics": {
                "requested_at_ms": "collector request time",
                "retrieved_at_ms": "collector response time",
                "published_at": "not stored for entry/scratch source payloads",
                "event_or_effective_at": "not stored for scratch status",
                "race_date": "event date; not a publication timestamp",
            },
        },
        samples,
    )


def _raw_entry_sheet_comparison(
    documents: list[dict], target_rows: list[dict], project_root: Path
) -> dict[str, int | bool]:
    earliest_by_date: dict[str, dict] = {}
    for document in documents:
        if document["data_type"] == "entry_sheet":
            earliest_by_date.setdefault(str(document["source_date"]), document)
    raw_keys: list[tuple[str, int, int]] = []
    missing_files = 0
    hash_mismatches = 0
    for source_date, document in earliest_by_date.items():
        path = project_root / str(document["local_path"])
        if not path.is_file():
            missing_files += 1
            continue
        hash_mismatches += _sha256(path) != document["sha256"]
        payload = json.loads(path.read_text())
        items = payload["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            items = [items]
        raw_keys.extend((source_date, int(item["rcNo"]), int(item["chulNo"])) for item in items)
    database_keys = [
        (
            str(row["race_date_local"]).replace("-", ""),
            int(row["race_number"]),
            int(row["horse_number"]),
        )
        for row in target_rows
    ]
    return {
        "selected_daily_documents": len(earliest_by_date),
        "raw_entry_keys": len(raw_keys),
        "database_entry_keys": len(database_keys),
        "raw_duplicate_keys": len(raw_keys) - len(set(raw_keys)),
        "database_duplicate_keys": len(database_keys) - len(set(database_keys)),
        "missing_from_raw": len(set(database_keys) - set(raw_keys)),
        "extra_in_raw": len(set(raw_keys) - set(database_keys)),
        "missing_raw_files": missing_files,
        "raw_file_hash_mismatches": hash_mismatches,
        "exact_current_post_event_key_match": set(raw_keys) == set(database_keys),
        "proves_t_minus_30m_membership": False,
    }


def _ties(rows: list[dict]) -> dict[str, int]:
    grouped: Counter[tuple[int, int]] = Counter()
    for row in rows:
        position = row["finish_position"]
        if position is not None and 1 <= int(position) <= 89:
            grouped[(int(row["race_id"]), int(position))] += 1
    ties = {key: count for key, count in grouped.items() if count > 1}
    return {
        "groups": len(ties),
        "races": len({race_id for race_id, _ in ties}),
        "runner_rows": sum(ties.values()),
        "winner_tie_groups": sum(position == 1 for _, position in ties),
    }


def _build_evidence(rows: list[dict]) -> tuple[pl.DataFrame, Counter[str]]:
    evidence = []
    counts: Counter[str] = Counter()
    for row in rows:
        outcome = RunnerOutcome(
            race_id=int(row["race_id"]),
            race_entry_id=int(row["race_entry_id"]),
            finish_position=row["finish_position"],
            rank_remark=row["rank_remark"],
            scratched=bool(row["scratched_current"]),
            disqualified=bool(row["disqualified"]),
        )
        state = classify_outcome(outcome).value
        counts[state] += 1
        evidence.append(
            {
                **row,
                "outcome_state_e1": state,
                "actual_started_confirmed": state
                in {"normal_finish", "started_dnf", "disqualified"},
                "existing_dataset_included": state == "normal_finish",
                "f_t_evidence_level": "assumption_dependent",
                "f_t_exactly_reconstructable": False,
                "f_t_reason": (
                    "entry/scratch payload was retrieved after T-30m and has no "
                    "published/effective timestamp"
                ),
            }
        )
    return pl.DataFrame(evidence, infer_schema_length=None), counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/horse_racing.sqlite3"))
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=MAX_RESEARCH_DATE)
    parser.add_argument("--meet", type=int, default=DEFAULT_MEET)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/logs/pre_race_field_dnf_audit_e1_v2_20260911.json"),
    )
    parser.add_argument(
        "--evidence-output",
        type=Path,
        default=Path("data/logs/pre_race_field_dnf_evidence_e1_v2_20260911.parquet"),
    )
    args = parser.parse_args()
    if (
        args.start_date != DEFAULT_START_DATE
        or args.end_date != MAX_RESEARCH_DATE
        or args.meet != DEFAULT_MEET
    ):
        raise SystemExit("fixed E1 scope only: meet=1, start=2025-01-04, end=2026-05-31")

    connection = sqlite3.connect(f"file:{args.db.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    params = {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "start_compact": args.start_date.replace("-", ""),
        "end_compact": args.end_date.replace("-", ""),
        "meet": args.meet,
    }
    try:
        target_rows = _rows(connection, TARGET_QUERY, params)
        source_documents = _rows(connection, SOURCE_DOCUMENT_QUERY, params)
        live_ledger = connection.execute(
            """
            SELECT COUNT(DISTINCT pr.id) AS runs,
                   COUNT(DISTINCT mp.race_id) AS races,
                   COUNT(mp.id) AS entries
            FROM prediction_runs AS pr
            JOIN model_predictions AS mp ON mp.prediction_run_id = pr.id
            JOIN races AS r ON r.id = mp.race_id
            JOIN racecourses AS rc ON rc.id = r.racecourse_id
            WHERE pr.race_date_local BETWEEN :start_date AND :end_date
              AND pr.publication_mode = 'live'
              AND rc.kra_meet_code = :meet
            """,
            params,
        ).fetchone()
    finally:
        connection.close()
    if not target_rows:
        raise SystemExit("no target rows")

    entry_keys = [(row["race_id"], row["race_entry_id"]) for row in target_rows]
    duplicate_keys = len(entry_keys) - len(set(entry_keys))
    race_rows = list({row["race_id"]: row for row in target_rows}.values())
    evidence, outcome_counts = _build_evidence(target_rows)
    source_summary, source_samples = _source_summary(source_documents, race_rows)

    label_input = pl.DataFrame(target_rows, infer_schema_length=None).rename(
        {"scratched_current": "scratched"}
    )
    labeled, exclusions = apply_label_policy(label_input)
    scratch_rows = [row for row in target_rows if row["scratch_observed_at_ms"] is not None]
    scratches_observed_by_cutoff = sum(
        int(row["scratch_observed_at_ms"]) <= int(row["cutoff_at_ms"]) for row in scratch_rows
    )
    races_with_nonstarters = len(
        {row["race_id"] for row in target_rows if bool(row["scratched_current"])}
    )
    races_with_started_special = len(
        {row["race_id"] for row in target_rows if row["finish_position"] in {91, 92}}
    )

    project_root = Path(__file__).resolve().parents[1]
    raw_entry_comparison = _raw_entry_sheet_comparison(source_documents, target_rows, project_root)
    dataset_manifest = project_root / (
        "data/datasets/section_canonical_seoul_v2_review/start_minus_30m/manifest.json"
    )
    manifest_payload = json.loads(dataset_manifest.read_text())
    dataset_path = dataset_manifest.parent / "dataset.parquet"
    dataset = pl.read_parquet(dataset_path, columns=["race_id", "race_entry_id"])
    dataset_keys = set(dataset.iter_rows())
    normal_finish_keys = {
        (int(row["race_id"]), int(row["race_entry_id"]))
        for row in target_rows
        if classify_outcome(
            RunnerOutcome(
                race_id=int(row["race_id"]),
                race_entry_id=int(row["race_entry_id"]),
                finish_position=row["finish_position"],
                rank_remark=row["rank_remark"],
                scratched=bool(row["scratched_current"]),
                disqualified=bool(row["disqualified"]),
            )
        ).value
        == "normal_finish"
    }
    dataset_key_comparison = {
        "dataset_keys": len(dataset_keys),
        "normal_finish_keys": len(normal_finish_keys),
        "missing_from_dataset": len(normal_finish_keys - dataset_keys),
        "extra_in_dataset": len(dataset_keys - normal_finish_keys),
        "exact_match": dataset_keys == normal_finish_keys,
    }
    observed_counts = {
        "races": len(race_rows),
        "entries": len(target_rows),
        **{name: int(outcome_counts[name]) for name in outcome_counts},
    }
    frozen_mismatches = {
        name: {"expected": expected, "observed": observed_counts.get(name, 0)}
        for name, expected in FROZEN_COUNTS.items()
        if observed_counts.get(name, 0) != expected
    }
    invariant_failures = {
        "frozen_count_mismatches": frozen_mismatches,
        "duplicate_race_entry_keys": duplicate_keys,
        "scratch_rows_observed_by_t_minus_30m": scratches_observed_by_cutoff,
        "entry_sheet_races_with_document_retrieved_by_t_minus_30m": source_summary[
            "entry_sheet_races_with_document_retrieved_by_t_minus_30m"
        ],
        "raw_entry_sheet_exact_key_match": raw_entry_comparison[
            "exact_current_post_event_key_match"
        ],
        "dataset_normal_finish_exact_key_match": dataset_key_comparison["exact_match"],
    }
    if (
        frozen_mismatches
        or duplicate_keys
        or scratches_observed_by_cutoff
        or source_summary["entry_sheet_races_with_document_retrieved_by_t_minus_30m"]
        or not raw_entry_comparison["exact_current_post_event_key_match"]
        or not dataset_key_comparison["exact_match"]
    ):
        raise SystemExit(f"fixed E1 data invariants failed: {invariant_failures}")

    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_parquet(args.evidence_output)
    code_paths = [
        Path(__file__).resolve(),
        project_root / "src/horse_racing/analysis/pre_race_field_contract.py",
        project_root / "src/horse_racing/analysis/dataset.py",
        project_root / "src/horse_racing/analysis/prediction_frame.py",
        project_root / "src/horse_racing/services/prediction_ledger.py",
        dataset_manifest,
    ]
    artifact = {
        "audit": "E1 pre-race field and DNF contract",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "read_only": True,
        "scope": {
            "meet_code": args.meet,
            "race_date_start": args.start_date,
            "race_date_end": args.end_date,
            "research_date_ceiling": MAX_RESEARCH_DATE,
            "target_race_status": "completed",
            "prediction_time": "scheduled_at_ms - 30 minutes",
        },
        "query_contract": {
            "auditor_scope_mode": "fixed_e1_seoul_sample",
            "non_default_scope_rejected_before_database_open": True,
            "date_bound_applied_in_sql_before_materialization": True,
            "post_2026_05_31_actual_results_queried": False,
            "target_query_sha256": hashlib.sha256(TARGET_QUERY.encode()).hexdigest(),
            "source_document_query_sha256": hashlib.sha256(
                SOURCE_DOCUMENT_QUERY.encode()
            ).hexdigest(),
        },
        "denominators": {
            "candidate_completed_races": len(race_rows),
            "current_post_event_entry_rows": len(target_rows),
            "current_scratched_rows": sum(bool(row["scratched_current"]) for row in target_rows),
            "confirmed_actual_starter_rows": (
                outcome_counts["normal_finish"]
                + outcome_counts["started_dnf"]
                + outcome_counts["disqualified"]
            ),
            "normal_finish_rows": outcome_counts["normal_finish"],
            "existing_dataset_rows_after_policy": labeled.height,
            "existing_dataset_races_after_policy": labeled["race_id"].n_unique(),
            "duplicate_race_entry_keys": duplicate_keys,
        },
        "existing_dataset_manifest": {
            "path": str(dataset_manifest.relative_to(project_root)),
            "version": manifest_payload["version"],
            "as_of_policy": manifest_payload["as_of_policy"],
            "rows": manifest_payload["row_count"],
            "races": manifest_payload["race_count"],
            "date_range": manifest_payload["date_range"],
            "exclusions": manifest_payload["exclusions"],
            "sha256": _sha256(dataset_manifest),
            "dataset_sha256": _sha256(dataset_path),
            "independent_key_comparison": dataset_key_comparison,
        },
        "set_differences": {
            "current_post_event_entries_minus_existing_dataset": len(target_rows) - labeled.height,
            "confirmed_actual_starters_minus_existing_dataset": (
                outcome_counts["started_dnf"] + outcome_counts["disqualified"]
            ),
            "current_live_query_rows_if_replayed_after_results": (
                len(target_rows) - sum(bool(row["scratched_current"]) for row in target_rows)
            ),
            "current_live_query_minus_existing_dataset": (
                outcome_counts["started_dnf"] + outcome_counts["disqualified"]
            ),
            "nonstarters_removed_by_current_scratched_state": outcome_counts["did_not_start"],
            "races_with_nonstarters": races_with_nonstarters,
            "races_with_started_dnf_or_disqualification": races_with_started_special,
            "f_t_minus_other_sets": None,
            "f_t_difference_reason": "historical T-30m field is not exactly reconstructable",
        },
        "existing_label_policy_filter_order": {
            "scratched": exclusions.scratched,
            "special_finish_code_after_scratched": exclusions.special_finish_code,
            "missing_result_row_after_prior_filters": exclusions.missing_result_row,
            "missing_finish_position_after_prior_filters": exclusions.missing_finish_position,
            "small_field_rows": exclusions.small_field_rows,
            "no_winner_rows": exclusions.no_winner_rows,
        },
        "outcome_states": dict(sorted(outcome_counts.items())),
        "observed_special_combinations": [
            {
                "finish_position": position,
                "rank_remark": remark,
                "scratched": scratched,
                "rows": count,
            }
            for (position, remark, scratched), count in sorted(
                Counter(
                    (
                        int(row["finish_position"]),
                        str(row["rank_remark"]),
                        bool(row["scratched_current"]),
                    )
                    for row in target_rows
                    if row["finish_position"] is not None and int(row["finish_position"]) >= 90
                ).items()
            )
        ],
        "official_dead_heats": _ties(target_rows),
        "field_reconstruction": {
            "sufficient_races": 0,
            "assumption_dependent_races": len(race_rows),
            "unrecoverable_without_assumption_races": len(race_rows),
            "post_event_current_state_is_not_f_t": True,
            "current_scratched_boolean_has_history": False,
            "scratch_observation_aggregation": "MIN(first observed), not MAX",
            "scratch_rows": len(scratch_rows),
            "scratch_rows_observed_by_t_minus_30m": scratches_observed_by_cutoff,
            **source_summary,
            "post_event_raw_entry_sheet_key_comparison": raw_entry_comparison,
            "fixed_scope_data_invariants": invariant_failures,
        },
        "live_prediction_ledger_in_scope": {
            "runs": int(live_ledger["runs"] or 0),
            "races": int(live_ledger["races"] or 0),
            "entries": int(live_ledger["entries"] or 0),
            "meaning": "immutable predicted members could evidence F_t; none exist in scope",
        },
        "source_document_samples": source_samples,
        "evidence": {
            "path": str(args.evidence_output),
            "rows": evidence.height,
            "sha256": _sha256(args.evidence_output),
        },
        "source_hashes": {
            str(path.relative_to(project_root)): _sha256(path)
            for path in code_paths
            if path.is_file()
        },
        "database_source": {
            "path": str(args.db),
            "bytes": args.db.stat().st_size,
            "sha256": _sha256(args.db),
        },
        "conclusions": [
            "No target race has an entry-sheet document retrieved by T-30m.",
            "All exact historical F_t sets remain unrecoverable without an unsupported assumption.",
            "The existing dataset conditions on normal finishers and omits 48 confirmed starters.",
            "Special finish codes are state-specific and must not all be called DNF.",
            "No model was trained; existing datasets, runs, comparisons, and DB were unchanged.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    print(args.output)
    print(args.evidence_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
