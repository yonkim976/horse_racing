"""Read-only training source precheck for the 2010-01-01..2026-09-29 cohort.

This reads the operational SQLite file in one read-only BEGIN snapshot and
the frozen Thoroughbred core DuckDB in read-only mode. It writes only evidence
files beside this script. It makes no API, network, or database write calls.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SQLITE_PATH = ROOT / "data/horse_racing.sqlite3"
CORE_PATH = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
START_DATE = "2010-01-01"
END_DATE = "2026-09-29"
CORE_MEETS = ("1", "3", "4")
SOURCE_TABLES = {
    "daily_training": ("horse_training", "training_date_local", None),
    "start_training": ("horse_start_training", "training_date_local", None),
    "swim_training": ("horse_swim_training", "training_date_local", "kra_horse_id_raw"),
}
MEET_LABELS = {
    1: "서울",
    3: "영남 API 권역; 부산경남·영천 장소 미분리",
    4: "영천 코드; 현재 저장행이 없어도 미시행을 뜻하지 않음",
}
PINNED_REFERENCES = (
    "src/horse_racing/db/models.py",
    "src/horse_racing/parsers/horse_history.py",
    "src/horse_racing/parsers/race_supplemental.py",
    "src/horse_racing/services/horse_history.py",
    "src/horse_racing/services/race_supplemental.py",
    "src/horse_racing/services/special_training.py",
    "scripts/audit_historical_training_monthly.py",
    "scripts/audit_historical_training_overlap.py",
    "scripts/repair_start_training_occurrences.py",
    "research/start_training_repair_20261001/historical_audit.json",
    "research/start_training_repair_20261001/cross_database_verification.json",
    "research/swim_training_refresh_20261002/report.json",
    "thoroughbred/research/20261002_training_source_precheck_v1/operating_chat_latest_reference.json",
    "data/logs/historical_horse_training_monthly_audit_20260914.json",
    "data/logs/historical_horse_training_2015_2024_quality_20260914.json",
    "data/logs/historical_horse_training_2025_db_overlap_20260914.json",
    "data/logs/historical_start_training_monthly_audit_20260914.json",
    "data/raw/kra_api_monthly/horse_training/manifest.jsonl",
    "thoroughbred/research/20260929_source_inventory_v1/inventory.json",
    "thoroughbred/data/core_api_2010_20260929_v1/manifest.json",
    "thoroughbred/research/20260930_next_ingestion_plan_v1/README.md",
    "thoroughbred/research/20261002_training_source_precheck_v1/snapshot.py",
)


def field_null_counts(
    db: sqlite3.Connection, table: str, fields: tuple[str, ...]
) -> dict[str, dict[str, int]]:
    result = {}
    columns = ", ".join(
        f"sum(CASE WHEN {field} IS NULL THEN 1 ELSE 0 END) AS {field}"
        for field in fields
    )
    for row in db.execute(
        f"""SELECT meet_code,count(*) AS rows,{columns} FROM {table}
           WHERE training_date_local BETWEEN ? AND ? AND meet_code IN (1,3,4)
           GROUP BY meet_code ORDER BY meet_code""",
        (START_DATE, END_DATE),
    ).fetchall():
        result[str(row["meet_code"])] = {
            "rows": int(row["rows"]),
            **{field: int(row[field] or 0) for field in fields},
        }
    return result


def parse_kra_clock(value: str | None) -> int | None:
    """Parse KRA HHMMSS, HHMM, or YYYYMMDDHHMMSS to comparable seconds."""
    if value is None:
        return None
    digits = re.sub(r"\s+", "", value)
    if not digits.isdigit() or len(digits) not in (4, 6, 14):
        return None
    date_prefix = None
    if len(digits) == 14:
        date_prefix = digits[:8]
        try:
            event_day = datetime.strptime(date_prefix, "%Y%m%d").date()
        except ValueError:
            return None
        digits = digits[8:]
    if len(digits) == 4:
        hour, minute, second = int(digits[:2]), int(digits[2:]), 0
    else:
        hour, minute, second = int(digits[:2]), int(digits[2:4]), int(digits[4:])
    if hour > 23 or minute > 59 or second > 59:
        return None
    clock_seconds = hour * 3600 + minute * 60 + second
    if date_prefix is not None:
        return event_day.toordinal() * 86_400 + clock_seconds
    return clock_seconds


def raw_kra_date(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\s+", "", value)
    if len(digits) == 14 and digits.isdigit():
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    return None


def confirm_daily_flags_from_archive(
    db: sqlite3.Connection,
) -> dict[str, object]:
    """Match nonpositive duration rows to local API18_1 page archives, read-only."""
    manifest_path = ROOT / "data/raw/kra_api_monthly/horse_training/manifest.jsonl"
    archive_root = (ROOT / "data/raw/kra_api_monthly/horse_training").resolve()
    manifest_by_month: dict[tuple[int, str], list[dict[str, object]]] = defaultdict(list)
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        manifest_by_month[(int(entry["meet"]), str(entry["month"]))].append(entry)
    flagged = db.execute(
        """SELECT t.meet_code,t.training_date_local,h.kra_horse_id,h.name_ko,
                  t.started_at_raw,t.ended_at_raw,t.duration_seconds,
                  t.canter_count,t.gallop_count
           FROM horse_training t JOIN horses h ON h.id=t.horse_id
           WHERE t.training_date_local BETWEEN ? AND ? AND t.meet_code IN (1,3,4)
             AND t.duration_seconds<=0
           ORDER BY t.training_date_local,t.meet_code,h.kra_horse_id""",
        (START_DATE, END_DATE),
    ).fetchall()
    page_cache: dict[Path, tuple[list[dict[str, object]], str, bool]] = {}
    results: list[dict[str, object]] = []
    page_hashes: dict[str, str] = {}
    for row in flagged:
        meet = int(row["meet_code"])
        month = str(row["training_date_local"]).replace("-", "")[:6]
        target = {
            "hrNo": str(row["kra_horse_id"]).strip(),
            "trDate": str(row["training_date_local"]).replace("-", ""),
            "stTime": str(row["started_at_raw"]),
            "spTime": str(row["ended_at_raw"]),
            "trTerm": str(row["duration_seconds"]),
        }
        found = None
        candidate_pages = []
        for entry in manifest_by_month.get((meet, month), []):
            candidate = (ROOT / str(entry["path"])).resolve()
            if not candidate.is_relative_to(archive_root):
                raise ValueError("Training archive manifest path escapes its source folder")
            if not candidate.is_file():
                continue
            candidate_pages.append((candidate, str(entry.get("sha256", ""))))
        for candidate, expected_hash in candidate_pages:
            if candidate not in page_cache:
                page_bytes = candidate.read_bytes()
                actual_hash = hashlib.sha256(page_bytes).hexdigest()
                if expected_hash and actual_hash != expected_hash:
                    raise ValueError(f"Training archive page hash mismatch: {candidate}")
                payload = json.loads(page_bytes)
                items = payload.get("response", {}).get("body", {}).get("items", {}).get("item", [])
                if isinstance(items, dict):
                    items = [items]
                page_cache[candidate] = (items, actual_hash, actual_hash == expected_hash)
            items, actual_hash, hash_verified = page_cache[candidate]
            page_hashes[str(candidate.relative_to(ROOT))] = actual_hash
            for index, item in enumerate(items, start=1):
                observed = {field: str(item.get(field, "")).strip() for field in target}
                if observed == target:
                    found = {
                        "page_path": str(candidate.relative_to(ROOT)),
                        "page_sha256": actual_hash,
                        "manifest_hash_verified": hash_verified,
                        "source_item_row_index_within_page": index,
                        "source_record_fields": {
                            "hrNo": item.get("hrNo"),
                            "hrName": item.get("hrName"),
                            "meet": item.get("meet"),
                            "trDate": item.get("trDate"),
                            "stTime": item.get("stTime"),
                            "spTime": item.get("spTime"),
                            "trTerm": item.get("trTerm"),
                            "run1Cnt": item.get("run1Cnt"),
                            "run2Cnt": item.get("run2Cnt"),
                        },
                    }
                    break
            if found:
                break
        results.append(
            {
                "meet_code": meet,
                "training_date_local": row["training_date_local"],
                "horse_id_official": row["kra_horse_id"],
                "horse_name": row["name_ko"],
                "duration_seconds": row["duration_seconds"],
                "started_at_raw": row["started_at_raw"],
                "ended_at_raw": row["ended_at_raw"],
                "source_archive_exact_match": found is not None,
                "source_archive_match": found,
            }
        )
    return {
        "source": "local API18_1 monthly raw pages; no network calls",
        "manifest_path": str(manifest_path.relative_to(ROOT)),
        "manifest_sha256": sha256_file(manifest_path),
        "flagged_nonpositive_duration_rows": len(results),
        "rows_exactly_matched_to_archived_source": sum(
            bool(item["source_archive_exact_match"]) for item in results
        ),
        "rows_without_archived_source_match": sum(
            not bool(item["source_archive_exact_match"]) for item in results
        ),
        "archive_page_sha256": page_hashes,
        "rows": results,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    opened_at = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    sqlite_uri = f"file:{SQLITE_PATH.resolve()}?mode=ro"
    db = sqlite3.connect(sqlite_uri, uri=True, timeout=60)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    # The first SELECT pins the WAL snapshot used for all following SQLite reads.
    schema_version = db.execute("SELECT schema_version FROM pragma_schema_version").fetchone()[0]
    journal_mode = db.execute("PRAGMA journal_mode").fetchone()[0]

    core = duckdb.connect(str(CORE_PATH.resolve()), read_only=True)
    core.execute("BEGIN TRANSACTION")
    core_horse_ids = {
        str(row[0]).strip()
        for row in core.execute(
            """SELECT DISTINCT horse_id_raw FROM confirmed_runners
               WHERE source_meet IN ('1','3','4')
                 AND result_date BETWEEN ? AND ?
                 AND horse_id_raw IS NOT NULL AND trim(horse_id_raw) <> ''""",
            [START_DATE.replace("-", ""), END_DATE.replace("-", "")],
        ).fetchall()
    }
    core_roster_horse_ids = {
        str(row[0]).strip()
        for row in core.execute(
            """SELECT DISTINCT entity_id_official_string
               FROM entity_reference_roster
               WHERE entity_type='horse' AND entity_id_official_string IS NOT NULL
                 AND trim(entity_id_official_string)<>''"""
        ).fetchall()
    }
    core_trials = core.execute(
        """SELECT source_meet_query, count(*) AS sessions,
                  min(trial_date) AS first_date, max(trial_date) AS last_date
           FROM trial_sessions WHERE trial_date BETWEEN ? AND ?
             AND source_meet_query IN ('1','3','4')
           GROUP BY source_meet_query ORDER BY source_meet_query""",
        [START_DATE, END_DATE],
    ).fetchall()
    core_trial_participants = core.execute(
        """SELECT source_meet_query, count(*) AS participants
           FROM trial_participants WHERE trial_date BETWEEN ? AND ?
             AND source_meet_query IN ('1','3','4')
           GROUP BY source_meet_query ORDER BY source_meet_query""",
        [START_DATE, END_DATE],
    ).fetchall()
    core_tables = {
        str(row[0])
        for row in core.execute(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema='main'"""
        ).fetchall()
    }

    evidence: dict[str, object] = {
        "scope": {
            "event_date_from_inclusive": START_DATE,
            "event_date_through_inclusive": END_DATE,
            "included_meet_codes": {"1": "서울", "3": "영남 API 권역", "4": "영천"},
            "excluded_meet_code": {"2": "제주"},
            "venue_limit": "API meet=3 may mean Yeongnam and does not prove Busan-Gyeongnam vs Yeongcheon.",
        },
        "snapshot": {
            "opened_at_kst": opened_at,
            "sqlite_path": str(SQLITE_PATH.relative_to(ROOT)),
            "sqlite_main_file_bytes": SQLITE_PATH.stat().st_size,
            "sqlite_journal_mode": journal_mode,
            "sqlite_schema_version": schema_version,
            "sqlite_access": "mode=ro; PRAGMA query_only=ON; one BEGIN transaction; no SQLite writes",
            "core_duckdb_path": str(CORE_PATH.relative_to(ROOT)),
            "core_duckdb_access": "read_only=True; read-only transaction",
        },
        "core_linkage": {
            "distinct_official_horse_ids_in_confirmed_runners": len(core_horse_ids),
            "distinct_official_horse_ids_in_entity_reference_roster_type_horse": len(core_roster_horse_ids),
            "runner_ids_also_in_horse_roster": len(core_horse_ids & core_roster_horse_ids),
            "comparison": "Operational horse_id foreign keys refer to the operational horses table. The independent comparisons here use exact official IDs against date/meet-scoped confirmed runners and the core entity_reference_roster (type=horse). Roster presence alone is not a training-event, venue, or full-population link.",
        },
        "core_training_like_tables": sorted(
            table for table in core_tables if "train" in table.lower()
        ),
        "datasets": {},
        "source_evidence_sha256": {},
    }
    evidence["operational_all_date_freshness"] = {}
    for dataset, (table, date_col, _raw_horse_col) in SOURCE_TABLES.items():
        row = db.execute(
            f"SELECT count(*) AS rows,min({date_col}) AS first_date,max({date_col}) AS last_date FROM {table}"
        ).fetchone()
        # The legacy table names do not all follow the descriptive dataset labels.
        run_data_type = {
            "daily_training": "horse_training",
            "start_training": "horse_start_training",
            "swim_training": "horse_swim_training",
        }[dataset]
        latest_run = db.execute(
            """SELECT id,source,status,records_fetched,records_written,
                      started_at_ms,completed_at_ms
               FROM ingestion_runs WHERE data_type=? ORDER BY id DESC LIMIT 1""",
            (run_data_type,),
        ).fetchone()
        latest_doc_count = (
            db.execute(
                "SELECT count(*) FROM source_documents WHERE ingestion_run_id=?",
                (latest_run["id"],),
            ).fetchone()[0]
            if latest_run is not None
            else 0
        )
        evidence["operational_all_date_freshness"][dataset] = {  # type: ignore[index]
            "table": table,
            "rows_all_dates": int(row["rows"]),
            "first_event_date": row["first_date"],
            "last_event_date": row["last_date"],
            "latest_ingestion_run": dict(latest_run) if latest_run is not None else None,
            "source_documents_in_latest_run": int(latest_doc_count),
        }
    hill_row = db.execute(
        """SELECT count(*) AS rows,min(training_date_local) AS first_date,
                  max(training_date_local) AS last_date FROM horse_hill_training"""
    ).fetchone()
    hill_run = db.execute(
        """SELECT id,source,status,records_fetched,records_written,
                  started_at_ms,completed_at_ms
           FROM ingestion_runs WHERE data_type='horse_hill_training'
           ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    evidence["operational_all_date_freshness"]["hill_training"] = {  # type: ignore[index]
        "table": "horse_hill_training",
        "rows_all_dates": int(hill_row["rows"]),
        "first_event_date": hill_row["first_date"],
        "last_event_date": hill_row["last_date"],
        "latest_ingestion_run": dict(hill_run) if hill_run is not None else None,
        "source_documents_in_latest_run": (
            int(db.execute(
                "SELECT count(*) FROM source_documents WHERE ingestion_run_id=?",
                (hill_run["id"],),
            ).fetchone()[0])
            if hill_run is not None
            else 0
        ),
    }
    evidence["source_document_lineage_by_type"] = [
        dict(row)
        for row in db.execute(
            """SELECT ir.data_type,ir.source,count(sd.id) AS source_documents,
                      count(DISTINCT ir.id) AS ingestion_runs,
                      min(sd.retrieved_at_ms) AS first_retrieved_at_ms,
                      max(sd.retrieved_at_ms) AS last_retrieved_at_ms
               FROM ingestion_runs ir LEFT JOIN source_documents sd
                 ON sd.ingestion_run_id=ir.id
               WHERE ir.data_type IN ('horse_training','horse_start_training',
                                      'horse_swim_training','horse_hill_training')
               GROUP BY ir.data_type,ir.source ORDER BY ir.data_type,ir.source"""
        ).fetchall()
    ]
    annual_rows: list[dict[str, object]] = []
    hill_annual_rows: list[dict[str, object]] = []

    for dataset, (table, date_col, raw_horse_col) in SOURCE_TABLES.items():
        official_id_sql = (
            f"COALESCE(h.kra_horse_id, t.{raw_horse_col})"
            if raw_horse_col
            else "h.kra_horse_id"
        )
        meet_summary = []
        annual_lookup: dict[tuple[int, int], dict[str, object]] = {}
        ids_by_meet: dict[int, set[str]] = defaultdict(set)
        for item in db.execute(
            f"""SELECT DISTINCT t.meet_code,{official_id_sql} AS official_id
                FROM {table} AS t LEFT JOIN horses AS h ON h.id=t.horse_id
                WHERE t.{date_col} BETWEEN ? AND ? AND t.meet_code IN (1,3,4)
                  AND {official_id_sql} IS NOT NULL AND trim({official_id_sql})<>''""",
            (START_DATE, END_DATE),
        ).fetchall():
            ids_by_meet[int(item[0])].add(str(item[1]).strip())
        summary_sql = f"""SELECT t.meet_code AS meet_code, count(*) AS rows,
                      count(DISTINCT {official_id_sql}) AS distinct_source_horses,
                      sum(CASE WHEN h.id IS NULL THEN 1 ELSE 0 END) AS unlinked_rows,
                      sum(CASE WHEN t.horse_id=0 THEN 1 ELSE 0 END) AS zero_fk_rows,
                      min(t.{date_col}) AS first_event_date,
                      max(t.{date_col}) AS last_event_date
               FROM {table} AS t LEFT JOIN horses AS h ON h.id=t.horse_id
               WHERE t.{date_col} BETWEEN ? AND ? AND t.meet_code IN (1,3,4)
               GROUP BY t.meet_code ORDER BY t.meet_code"""
        for row in db.execute(summary_sql, (START_DATE, END_DATE)).fetchall():
            meet = int(row["meet_code"])
            meet_ids = ids_by_meet[meet]
            matched = sorted(meet_ids & core_horse_ids)
            meet_summary.append(
                {
                    "meet_code": meet,
                    "meet_label": MEET_LABELS[meet],
                    "rows": int(row["rows"]),
                    "distinct_source_horses": int(row["distinct_source_horses"]),
                    "linked_rows_missing_horse_fk": int(row["unlinked_rows"]),
                    "rows_with_horse_id_zero": int(row["zero_fk_rows"]),
                    "first_event_date": row["first_event_date"],
                    "last_event_date": row["last_event_date"],
                    "distinct_ids_matching_core_runner_ids": len(matched),
                    "distinct_ids_not_in_core_runner_ids": len(meet_ids) - len(matched),
                    "distinct_ids_matching_core_horse_roster": len(meet_ids & core_roster_horse_ids),
                    "distinct_ids_not_in_core_horse_roster": len(meet_ids - core_roster_horse_ids),
                    "unmatched_id_examples": sorted(meet_ids - core_horse_ids)[:10],
                }
            )
        years = db.execute(
            f"""SELECT substr(t.{date_col},1,4) AS year, t.meet_code AS meet_code,
                      count(*) AS rows,
                      count(DISTINCT {official_id_sql}) AS distinct_source_horses,
                      min(t.{date_col}) AS first_event_date,
                      max(t.{date_col}) AS last_event_date
               FROM {table} AS t LEFT JOIN horses AS h ON h.id=t.horse_id
               WHERE t.{date_col} BETWEEN ? AND ? AND t.meet_code IN (1,3,4)
               GROUP BY year,t.meet_code ORDER BY t.meet_code,year""",
            (START_DATE, END_DATE),
        ).fetchall()
        for row in years:
            year, meet = int(row["year"]), int(row["meet_code"])
            annual_lookup[(meet, year)] = {
                "rows": int(row["rows"]),
                "distinct_source_horses": int(row["distinct_source_horses"]),
                "first_event_date": row["first_event_date"],
                "last_event_date": row["last_event_date"],
            }
        for meet in (1, 3, 4):
            for year in range(2010, 2027):
                row = annual_lookup.get((meet, year), {})
                annual_rows.append(
                    {
                        "dataset": dataset,
                        "meet_code": meet,
                        "meet_label": MEET_LABELS[meet],
                        "year": year,
                        "stored_rows": row.get("rows", 0),
                        "distinct_source_horses": row.get("distinct_source_horses", 0),
                        "first_event_date": row.get("first_event_date", ""),
                        "last_event_date": row.get("last_event_date", ""),
                        "zero_rows_mean_no_stored_rows_only": True,
                    }
                )
        field_coverage: dict[str, dict[str, int]] = {}
        if dataset == "daily_training":
            fields = (
                "stable_part", "stable_number", "trainer_name", "rider_type", "rider_id",
                "started_at_raw", "ended_at_raw", "duration_seconds", "canter_count",
                "gallop_count", "entry_plan",
            )
            field_coverage = field_null_counts(db, table, fields)
        elif dataset == "start_training":
            fields = (
                "stable_part", "stable_number", "rider_name", "remark", "source_document_id",
                "source_row_no", "location_raw",
            )
            field_coverage = field_null_counts(db, table, fields)
        elif dataset == "swim_training":
            fields = (
                "horse_id", "source_document_id", "stable_part", "stable_note",
                "trainer_part", "trainer_name",
            )
            field_coverage = field_null_counts(db, table, fields)
        dataset_data: dict[str, object] = {
            "table": table,
            "stored_rows_in_scope": sum(item["rows"] for item in meet_summary),
            "meet_summary": meet_summary,
            "field_null_counts": field_coverage,
        }
        if dataset == "start_training":
            dataset_data["source_kind_counts"] = [
                dict(row)
                for row in db.execute(
                    """SELECT meet_code,source_kind,count(*) AS rows,
                              sum(source_document_id IS NOT NULL) AS rows_with_source_document,
                              sum(source_row_no IS NOT NULL) AS rows_with_source_row_no,
                              sum(location_raw IS NOT NULL) AS rows_with_location
                       FROM horse_start_training
                       WHERE training_date_local BETWEEN ? AND ? AND meet_code IN (1,3,4)
                       GROUP BY meet_code,source_kind ORDER BY meet_code,source_kind""",
                    (START_DATE, END_DATE),
                ).fetchall()
            ]
            dataset_data["occurrence_slot_counts"] = [
                dict(row)
                for row in db.execute(
                    """SELECT meet_code,occurrence_no,count(*) AS rows
                       FROM horse_start_training
                       WHERE training_date_local BETWEEN ? AND ? AND meet_code IN (1,3,4)
                       GROUP BY meet_code,occurrence_no ORDER BY meet_code,occurrence_no""",
                    (START_DATE, END_DATE),
                ).fetchall()
            ]
            dataset_data["multi_occurrence_horse_days"] = [
                dict(row)
                for row in db.execute(
                    """WITH grouped AS (
                           SELECT meet_code,source_kind,horse_id,training_date_local,
                                  count(*) AS rows
                           FROM horse_start_training
                           WHERE training_date_local BETWEEN ? AND ?
                             AND meet_code IN (1,3,4)
                           GROUP BY meet_code,source_kind,horse_id,training_date_local
                           HAVING count(*)>1
                       )
                       SELECT meet_code,source_kind,count(*) AS horse_days,
                              sum(rows) AS stored_rows_in_multi_occurrence_days,
                              sum(rows-1) AS extra_rows_above_one,
                              max(rows) AS max_rows_per_horse_day
                       FROM grouped GROUP BY meet_code,source_kind
                       ORDER BY meet_code,source_kind""",
                    (START_DATE, END_DATE),
                ).fetchall()
            ]
            dataset_data["identical_payload_multiplicity"] = [
                dict(row)
                for row in db.execute(
                    """WITH grouped AS (
                           SELECT meet_code,source_kind,horse_id,training_date_local,
                                  stable_part,stable_number,rider_name,remark,location_raw,
                                  count(*) AS copies
                           FROM horse_start_training
                           WHERE training_date_local BETWEEN ? AND ?
                             AND meet_code IN (1,3,4)
                           GROUP BY meet_code,source_kind,horse_id,training_date_local,
                                    stable_part,stable_number,rider_name,remark,location_raw
                           HAVING count(*)>1
                       )
                       SELECT meet_code,source_kind,count(*) AS repeated_payload_groups,
                              sum(copies) AS rows_in_repeated_payload_groups,
                              sum(copies-1) AS extra_identical_rows
                       FROM grouped GROUP BY meet_code,source_kind
                       ORDER BY meet_code,source_kind""",
                    (START_DATE, END_DATE),
                ).fetchall()
            ]
        if dataset == "swim_training":
            dataset_data["quality_counts"] = [
                dict(row)
                for row in db.execute(
                    """SELECT meet_code,quality_status,count(*) AS rows,
                              sum(swim_count=0) AS zero_count_rows,
                              sum(swim_count<0) AS negative_count_rows,
                              sum(swim_count>=20) AS count_20_or_more_rows,
                              max(swim_count) AS maximum_count
                       FROM horse_swim_training
                       WHERE training_date_local BETWEEN ? AND ? AND meet_code IN (1,3,4)
                       GROUP BY meet_code,quality_status ORDER BY meet_code,quality_status""",
                    (START_DATE, END_DATE),
                ).fetchall()
            ]
            dataset_data["large_count_examples"] = [
                dict(row)
                for row in db.execute(
                    """SELECT kra_horse_id_raw,horse_name_raw,meet_code,
                              training_date_local,swim_count,source_document_id
                       FROM horse_swim_training
                       WHERE training_date_local BETWEEN ? AND ?
                         AND meet_code IN (1,3,4) AND swim_count>=20
                       ORDER BY swim_count DESC,training_date_local DESC,horse_id
                       LIMIT 30""",
                    (START_DATE, END_DATE),
                ).fetchall()
            ]
        if dataset == "daily_training":
            daily_clock = {
                "raw_clock_parse_rule": "4 digits HHMM, 6 digits HHMMSS, or 14 digits YYYYMMDDHHMMSS; valid date and 00-23:00-59:00-59.",
                "rows_checked": 0,
                "rows_with_both_raw_times_and_duration": 0,
                "rows_with_parseable_both_times_and_duration": 0,
                "rows_with_unparseable_nonnull_start": 0,
                "rows_with_unparseable_nonnull_end": 0,
                "rows_with_embedded_start_date_different_from_training_date": 0,
                "rows_with_embedded_end_date_different_from_training_date": 0,
                "rows_with_zero_duration": 0,
                "rows_with_negative_duration": 0,
                "rows_with_end_before_start": 0,
                "duration_matches_elapsed_exactly": 0,
                "duration_mismatch_rows": 0,
                "duration_mismatch_within_5_seconds": 0,
                "duration_mismatch_within_30_seconds": 0,
                "maximum_absolute_duration_mismatch_seconds": 0,
                "duration_delta_counts": {},
                "duration_mismatch_examples": [],
                "nonpositive_duration_examples": [],
            }
            duration_delta_counts: Counter[int] = Counter()
            daily_meet_counts: dict[str, dict[str, int]] = defaultdict(
                lambda: {
                    "rows": 0,
                    "zero_duration_rows": 0,
                    "negative_duration_rows": 0,
                    "end_before_start_rows": 0,
                    "duration_mismatch_rows": 0,
                    "canter_zero_rows": 0,
                    "gallop_zero_rows": 0,
                }
            )
            nonpositive_example_count = 0
            cursor = db.execute(
                """SELECT meet_code,training_date_local,started_at_raw,ended_at_raw,
                          duration_seconds,canter_count,gallop_count
                   FROM horse_training
                   WHERE training_date_local BETWEEN ? AND ? AND meet_code IN (1,3,4)""",
                (START_DATE, END_DATE),
            )
            for batch in iter(lambda: cursor.fetchmany(100_000), []):
                for row in batch:
                    daily_clock["rows_checked"] += 1
                    meet_counts = daily_meet_counts[str(row["meet_code"])]
                    meet_counts["rows"] += 1
                    if row["canter_count"] == 0:
                        meet_counts["canter_zero_rows"] += 1
                    if row["gallop_count"] == 0:
                        meet_counts["gallop_zero_rows"] += 1
                    start_s = parse_kra_clock(row["started_at_raw"])
                    end_s = parse_kra_clock(row["ended_at_raw"])
                    duration = row["duration_seconds"]
                    if row["started_at_raw"] is not None and start_s is None:
                        daily_clock["rows_with_unparseable_nonnull_start"] += 1
                    if row["ended_at_raw"] is not None and end_s is None:
                        daily_clock["rows_with_unparseable_nonnull_end"] += 1
                    start_date = raw_kra_date(row["started_at_raw"])
                    end_date = raw_kra_date(row["ended_at_raw"])
                    if start_date is not None and start_date != str(row["training_date_local"]):
                        daily_clock["rows_with_embedded_start_date_different_from_training_date"] += 1
                    if end_date is not None and end_date != str(row["training_date_local"]):
                        daily_clock["rows_with_embedded_end_date_different_from_training_date"] += 1
                    if duration == 0:
                        daily_clock["rows_with_zero_duration"] += 1
                        meet_counts["zero_duration_rows"] += 1
                    elif duration is not None and duration < 0:
                        daily_clock["rows_with_negative_duration"] += 1
                        meet_counts["negative_duration_rows"] += 1
                    if duration is not None and duration <= 0 and nonpositive_example_count < 20:
                        daily_clock["nonpositive_duration_examples"].append(
                            {
                                "meet_code": row["meet_code"],
                                "training_date_local": row["training_date_local"],
                                "duration_seconds": duration,
                                "started_at_raw": row["started_at_raw"],
                                "ended_at_raw": row["ended_at_raw"],
                                "canter_count": row["canter_count"],
                                "gallop_count": row["gallop_count"],
                            }
                        )
                        nonpositive_example_count += 1
                    if (row["started_at_raw"] is not None and row["ended_at_raw"] is not None
                            and duration is not None):
                        daily_clock["rows_with_both_raw_times_and_duration"] += 1
                    if start_s is not None and end_s is not None and duration is not None:
                        daily_clock["rows_with_parseable_both_times_and_duration"] += 1
                        elapsed = end_s - start_s
                        if elapsed < 0:
                            daily_clock["rows_with_end_before_start"] += 1
                            meet_counts["end_before_start_rows"] += 1
                            continue
                        if elapsed == duration:
                            daily_clock["duration_matches_elapsed_exactly"] += 1
                        else:
                            daily_clock["duration_mismatch_rows"] += 1
                            meet_counts["duration_mismatch_rows"] += 1
                            delta = int(duration - elapsed)
                            duration_delta_counts[delta] += 1
                            abs_delta = abs(delta)
                            daily_clock["maximum_absolute_duration_mismatch_seconds"] = max(
                                daily_clock["maximum_absolute_duration_mismatch_seconds"],
                                abs_delta,
                            )
                            if abs_delta <= 5:
                                daily_clock["duration_mismatch_within_5_seconds"] += 1
                            if abs_delta <= 30:
                                daily_clock["duration_mismatch_within_30_seconds"] += 1
                            if len(daily_clock["duration_mismatch_examples"]) < 20:
                                daily_clock["duration_mismatch_examples"].append(
                                    {
                                        "meet_code": row["meet_code"],
                                        "training_date_local": row["training_date_local"],
                                        "started_at_raw": row["started_at_raw"],
                                        "ended_at_raw": row["ended_at_raw"],
                                        "duration_seconds": duration,
                                        "elapsed_seconds_from_raw_clocks": elapsed,
                                        "duration_minus_elapsed": duration - elapsed,
                                    }
                                )
            daily_count_issues = db.execute(
                """SELECT meet_code,count(*) AS rows,
                          sum(canter_count=0) AS zero_canter_rows,
                          sum(canter_count<0) AS negative_canter_rows,
                          sum(gallop_count=0) AS zero_gallop_rows,
                          sum(gallop_count<0) AS negative_gallop_rows,
                          sum(canter_count IS NULL) AS null_canter_rows,
                          sum(gallop_count IS NULL) AS null_gallop_rows
                   FROM horse_training
                   WHERE training_date_local BETWEEN ? AND ? AND meet_code IN (1,3,4)
                   GROUP BY meet_code ORDER BY meet_code""",
                (START_DATE, END_DATE),
            ).fetchall()
            daily_clock["duration_delta_counts"] = {
                str(delta): count
                for delta, count in sorted(duration_delta_counts.items())
            }
            daily_clock["by_meet"] = daily_meet_counts
            dataset_data["nonpositive_duration_source_archive_check"] = (
                confirm_daily_flags_from_archive(db)
            )
            dataset_data["quality_checks"] = {
                "clock_duration": daily_clock,
                "canter_gallop_counts_by_meet": [dict(row) for row in daily_count_issues],
                "natural_key_collision_evidence": "Normalized table uniqueness is on horse_id/meet/date/start/end. The historical API overlap artifacts show distinct source payloads sharing that key, so operational row counts can be lower than source rows; see pinned 2015-2024 and 2025 overlap reports.",
            }
        evidence["datasets"][dataset] = dataset_data  # type: ignore[index]

    hill_summary = [
        dict(row)
        for row in db.execute(
            """SELECT farm_name,count(*) AS rows,
                      count(DISTINCT kra_horse_id_raw) AS distinct_source_horses,
                      count(DISTINCT horse_id) AS linked_horses,
                      sum(horse_id IS NULL) AS null_horse_id_rows,
                      sum(horse_id=0) AS zero_horse_id_rows,
                      sum(horse_id IS NOT NULL AND NOT EXISTS
                          (SELECT 1 FROM horses h WHERE h.id=horse_hill_training.horse_id))
                          AS dangling_horse_fk_rows,
                      sum(kra_horse_id_raw='0') AS raw_horse_id_zero_rows,
                      min(training_date_local) AS first_event_date,
                      max(training_date_local) AS last_event_date
               FROM horse_hill_training
               WHERE training_date_local BETWEEN ? AND ?
               GROUP BY farm_name ORDER BY farm_name""",
            (START_DATE, END_DATE),
        ).fetchall()
    ]
    hill_quality = dict(
        db.execute(
            """SELECT count(*) AS rows,
                      sum(quality_status='valid') AS valid_rows,
                      sum(quality_status='zero_record') AS zero_rows,
                      sum(quality_status='incomplete') AS incomplete_rows,
                      sum(quality_status='invalid_record') AS invalid_rows,
                      sum(source_document_id IS NULL) AS rows_without_source_document,
                      sum(training_time_local IS NULL) AS rows_without_time,
                      sum(total_seconds IS NULL) AS rows_without_total_time
               FROM horse_hill_training
               WHERE training_date_local BETWEEN ? AND ?""",
            (START_DATE, END_DATE),
        ).fetchone()
    )
    hill_years = db.execute(
        """SELECT substr(training_date_local,1,4) AS year,farm_name,count(*) AS rows,
                  min(training_date_local) AS first_event_date,
                  max(training_date_local) AS last_event_date
           FROM horse_hill_training WHERE training_date_local BETWEEN ? AND ?
           GROUP BY year,farm_name ORDER BY year,farm_name""",
        (START_DATE, END_DATE),
    ).fetchall()
    for row in hill_years:
        hill_annual_rows.append(dict(row))
    hill_raw_ids = {
        str(row[0]).strip()
        for row in db.execute(
            """SELECT DISTINCT kra_horse_id_raw FROM horse_hill_training
               WHERE training_date_local BETWEEN ? AND ?
                 AND kra_horse_id_raw IS NOT NULL AND trim(kra_horse_id_raw)<>''""",
            (START_DATE, END_DATE),
        ).fetchall()
    }
    hill_matched = sorted(hill_raw_ids & core_horse_ids)
    hill_roster_matched = sorted(hill_raw_ids & core_roster_horse_ids)
    evidence["datasets"]["hill_training"] = {  # type: ignore[index]
        "table": "horse_hill_training",
        "venue_or_meet_code": "No meet_code; grouped by named training farm only.",
        "stored_rows_in_scope": int(hill_quality["rows"]),
        "farms": hill_summary,
        "quality_counts": hill_quality,
        "raw_horse_ids_matching_core_runner_ids": len(hill_matched),
        "raw_horse_ids_not_in_core_runner_ids": len(hill_raw_ids) - len(hill_matched),
        "raw_horse_ids_matching_core_horse_roster": len(hill_roster_matched),
        "raw_horse_ids_not_in_core_horse_roster": len(hill_raw_ids) - len(hill_roster_matched),
        "raw_horse_id_zero_rows": int(db.execute(
            """SELECT count(*) FROM horse_hill_training
               WHERE training_date_local BETWEEN ? AND ? AND kra_horse_id_raw='0'""",
            (START_DATE, END_DATE),
        ).fetchone()[0]),
        "unmatched_id_examples": sorted(hill_raw_ids - core_horse_ids)[:10],
    }

    evidence["core_running_trials"] = {  # type: ignore[index]
        "sessions_by_source_meet": [
            {
                "source_meet_query": row[0],
                "sessions": int(row[1]),
                "first_date": row[2],
                "last_date": row[3],
            }
            for row in core_trials
        ],
        "participants_by_source_meet": [
            {"source_meet_query": row[0], "participants": int(row[1])}
            for row in core_trial_participants
        ],
        "note": "Separate event type from daily training and starting training; source_meet=3 may remain Yeongnam without a venue split.",
    }
    evidence["operational_recent_ingestion_runs"] = [
        dict(row)
        for row in db.execute(
            """SELECT id,source,data_type,status,records_fetched,records_written,
                      started_at_ms,completed_at_ms
               FROM ingestion_runs
               WHERE data_type IN ('horse_training','horse_start_training',
                                   'horse_swim_training','horse_hill_training')
               ORDER BY id DESC LIMIT 20"""
        ).fetchall()
    ]

    for rel in PINNED_REFERENCES:
        path = ROOT / rel
        if path.is_file():
            evidence["source_evidence_sha256"][rel] = sha256_file(path)  # type: ignore[index]
    db.rollback()
    core.rollback()
    db.close()
    core.close()

    annual_path = OUT / "annual_coverage.csv"
    with annual_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "dataset", "meet_code", "meet_label", "year", "stored_rows",
                "distinct_source_horses", "first_event_date", "last_event_date",
                "zero_rows_mean_no_stored_rows_only",
            ),
        )
        writer.writeheader()
        writer.writerows(annual_rows)
    hill_path = OUT / "hill_farm_annual_coverage.csv"
    with hill_path.open("w", encoding="utf-8-sig", newline="") as stream:
        fields = ("year", "farm_name", "rows", "first_event_date", "last_event_date")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(hill_annual_rows)
    write_json(OUT / "snapshot_evidence.json", evidence)
    print(
        json.dumps(
            {
                "snapshot": evidence["snapshot"],
                "annual_csv": str(annual_path.relative_to(ROOT)),
                "hill_annual_csv": str(hill_path.relative_to(ROOT)),
                "datasets": {
                    key: value["stored_rows_in_scope"]
                    for key, value in evidence["datasets"].items()
                },
            },
            ensure_ascii=False,
        )
    )
if __name__ == "__main__":
    main()
