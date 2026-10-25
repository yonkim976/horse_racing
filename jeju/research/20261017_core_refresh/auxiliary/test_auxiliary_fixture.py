"""Exercise the incremental auxiliary loader using isolated SQLite fixtures."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from jeju.refresh.auxiliary import apply_auxiliary, canonical_json
from jeju.refresh.core import schema as core_schema


COLLECTION = ROOT / "jeju/research/20261017_core_refresh/collection"
FIXTURE_ROOT = Path(__file__).resolve().parent
START_DATE = "2026-09-13"
END_DATE = "2026-10-16"


SCHEMA = """
CREATE TABLE source_artifacts(source_artifact_id INTEGER PRIMARY KEY,source_family TEXT NOT NULL,
 source_role TEXT NOT NULL,public_dataset_id TEXT,dataset_name TEXT NOT NULL,endpoint TEXT NOT NULL,
 operation TEXT NOT NULL,attempt_id TEXT NOT NULL,request_params_json TEXT NOT NULL,
 source_url_without_key TEXT,collected_at_utc TEXT,http_status_code INTEGER,content_type TEXT,
 raw_relative_path TEXT NOT NULL,response_bytes INTEGER NOT NULL,sha256 TEXT NOT NULL,
 parser_version TEXT,created_at_utc TEXT NOT NULL);
CREATE TABLE api_records(api_record_id INTEGER PRIMARY KEY,source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts,
 record_index INTEGER NOT NULL,record_type TEXT NOT NULL,natural_key TEXT,payload_json TEXT NOT NULL,
 payload_sha256 TEXT NOT NULL,UNIQUE(source_artifact_id,record_index));
CREATE TABLE horse_profile_observations(horse_profile_observation_id INTEGER PRIMARY KEY,horse_id TEXT NOT NULL,
 breed_label_raw TEXT NOT NULL,payload_sha256 TEXT NOT NULL,source_response_sha256 TEXT NOT NULL);
CREATE VIEW horse_profile_latest AS SELECT horse_id,horse_profile_observation_id,breed_label_raw,
 payload_sha256,source_response_sha256 FROM horse_profile_observations;
CREATE TABLE daily_training_api_artifacts(daily_training_api_artifact_id INTEGER PRIMARY KEY,
 artifact_key TEXT NOT NULL UNIQUE,source_partition_key TEXT NOT NULL,source_page_kind TEXT NOT NULL,
 page_no INTEGER NOT NULL,source_file_path TEXT NOT NULL,source_sha256 TEXT NOT NULL,ledger_sha256 TEXT NOT NULL,
 audit_script_sha256 TEXT NOT NULL,audit_summary_sha256 TEXT NOT NULL,archive_manifest_path TEXT,
 archive_manifest_sha256 TEXT,profile_snapshot_sha256 TEXT NOT NULL,source_url_without_key TEXT,
 requested_at_ms INTEGER,retrieved_at_ms INTEGER,status_code INTEGER,api_result_code TEXT NOT NULL,
 raw_item_count INTEGER NOT NULL,profile_matched_row_count INTEGER NOT NULL,
 excluded_nonprofile_row_count INTEGER NOT NULL,quarantined_invalid_id_count INTEGER NOT NULL,
 id_status_counts_json TEXT NOT NULL,quality_status_counts_json TEXT NOT NULL,event_date_min TEXT,event_date_max TEXT,
 inserted_at_utc TEXT NOT NULL,UNIQUE(source_partition_key,page_no),
 CHECK(raw_item_count=profile_matched_row_count+excluded_nonprofile_row_count),
 CHECK((archive_manifest_path IS NULL AND archive_manifest_sha256 IS NULL) OR
       (archive_manifest_path IS NOT NULL AND length(archive_manifest_sha256)=64)));
CREATE TABLE daily_training_api_rows(daily_training_api_row_id INTEGER PRIMARY KEY,
 daily_training_api_artifact_id INTEGER NOT NULL REFERENCES daily_training_api_artifacts,
 source_row_index INTEGER NOT NULL,hrNo_raw TEXT,hrName_raw TEXT,meet_raw TEXT,trDate_raw TEXT,trTerm_raw TEXT,
 stTime_raw TEXT,spTime_raw TEXT,run1Cnt_raw TEXT,run2Cnt_raw TEXT,prGubun_raw TEXT,prNo_raw TEXT,part_raw TEXT,
 partNo_raw TEXT,trName_raw TEXT,chulGubun_raw TEXT,raw_row_json TEXT NOT NULL,horse_id TEXT NOT NULL,
 horse_profile_observation_id INTEGER NOT NULL REFERENCES horse_profile_observations,
 profile_match_status TEXT NOT NULL,training_date TEXT NOT NULL,start_time_local TEXT,start_time_status TEXT NOT NULL,
 end_time_local TEXT,end_time_status TEXT NOT NULL,time_order_status TEXT NOT NULL,duration_seconds INTEGER,
 duration_status TEXT NOT NULL,run1_count INTEGER,run1_count_status TEXT NOT NULL,run2_count INTEGER,
 run2_count_status TEXT NOT NULL,UNIQUE(daily_training_api_artifact_id,source_row_index),
 CHECK(run1_count IS NULL AND run2_count IS NULL));
CREATE TABLE daily_training_rider_type_assignments(daily_training_api_row_id INTEGER PRIMARY KEY
 REFERENCES daily_training_api_rows,daily_training_api_artifact_id INTEGER NOT NULL REFERENCES daily_training_api_artifacts,
 prGubun_raw TEXT,prNo_raw TEXT,horse_id TEXT,training_date TEXT NOT NULL,start_time_local TEXT,end_time_local TEXT,
 duration_seconds INTEGER,rider_type TEXT NOT NULL,type_status TEXT NOT NULL,website_type TEXT,website_label_raw TEXT,
 website_jockey_name TEXT,website_source_path TEXT,website_sha256 TEXT);
CREATE TABLE medical_api_rows(medical_api_row_id INTEGER PRIMARY KEY,api_record_id INTEGER NOT NULL UNIQUE REFERENCES api_records,
 source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts,source_row_no INTEGER NOT NULL,clinic_date TEXT NOT NULL,
 horse_id TEXT NOT NULL,meet_raw TEXT,clinic_date_raw TEXT,hr_name_raw TEXT,hr_no_raw TEXT,hospi_name_raw TEXT,
 ill_name1_raw TEXT,ill_name2_raw TEXT,part_raw TEXT,raw_key_presence_json TEXT NOT NULL,
 raw_key_absence_json TEXT NOT NULL,raw_field_types_json TEXT NOT NULL,UNIQUE(source_artifact_id,source_row_no));
CREATE TABLE medical_api_diagnosis_slots(medical_api_diagnosis_slot_id INTEGER PRIMARY KEY,
 medical_api_row_id INTEGER NOT NULL REFERENCES medical_api_rows,api_record_id INTEGER NOT NULL REFERENCES api_records,
 source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts,source_row_no INTEGER NOT NULL,horse_id TEXT NOT NULL,
 clinic_date TEXT NOT NULL,source_slot_ordinal INTEGER NOT NULL,source_slot_kind TEXT NOT NULL,raw_diagnosis_text TEXT,
 normalized_diagnosis_text TEXT,raw_text_sha256 TEXT,UNIQUE(api_record_id,source_slot_ordinal));
CREATE TABLE starting_exam_api_rows(starting_exam_api_row_id INTEGER PRIMARY KEY,
 api_record_id INTEGER NOT NULL UNIQUE REFERENCES api_records,source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts,
 source_row_no INTEGER NOT NULL,event_key TEXT NOT NULL,exam_date TEXT NOT NULL,horse_id TEXT NOT NULL,meet_raw TEXT,
 train_date_raw TEXT,day_serial_raw TEXT,train_no_raw TEXT,chul_no_raw TEXT,hr_name_raw TEXT,hr_no_raw TEXT,name_raw TEXT,
 sex_raw TEXT,age_raw TEXT,rider_raw TEXT,tr_name_raw TEXT,tr_no_raw TEXT,trainer_id_normalized TEXT,ow_name_raw TEXT,
 ow_no_raw TEXT,pass_flag_raw TEXT,judgment_label_normalized TEXT,judgment_status TEXT NOT NULL,reason_raw TEXT,
 nopass_reason_raw TEXT,raw_key_presence_json TEXT NOT NULL,raw_key_absence_json TEXT NOT NULL,
 UNIQUE(source_artifact_id,source_row_no));
"""


def _api_body(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    body = document.get("response", document)["body"]
    item = body.get("items")
    item = item.get("item") if isinstance(item, dict) else item
    if isinstance(item, dict):
        return [item]
    return item or []


def _iso_api_date(value: Any) -> str:
    raw = str(value)
    return datetime.strptime(raw, "%Y%m%d").date().isoformat()


def _fixture_page(family: str, path: Path, rows: list[dict[str, Any]], params: dict[str, str], stamp: str) -> dict[str, Any]:
    size = int(params["numOfRows"])
    document = {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "items": {"item": rows}, "totalCount": len(rows), "pageNo": 1, "numOfRows": size,
            },
        }
    }
    raw = (json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return {
        "family": family,
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "collected_at_utc": stamp,
        "params": params,
        "total_count": len(rows),
        "page_no": 1,
        "item_count": len(rows),
        "http_status": 200,
        "start_date": START_DATE,
        "end_date": END_DATE,
    }


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    exclusions = json.loads((ROOT / "jeju/data/horse_exclusions.json").read_text(encoding="utf-8"))["horses"]
    excluded_ids = {str(key) for key, value in exclusions.items() if not value["reimport_allowed"]}
    profile_paths = sorted((COLLECTION / "raw/horse_profile").glob("**/page_*.json"))
    for profile_no, path in enumerate(profile_paths, 1):
        response_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        for row in _api_body(path):
            horse_id = str(row.get("hrNo"))
            if horse_id in excluded_ids:
                continue
            conn.execute(
                "INSERT INTO horse_profile_observations VALUES(?,?,?,?,?)",
                (profile_no, horse_id, str(row.get("breed") or ""),
                 hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest(), response_sha),
            )
    core_schema(conn)
    conn.commit()
    return conn


def run_fixture() -> dict[str, Any]:
    manifest = json.loads((COLLECTION / "source_manifest.json").read_text(encoding="utf-8"))
    exclusions = json.loads((ROOT / "jeju/data/horse_exclusions.json").read_text(encoding="utf-8"))["horses"]
    blocked = {str(key) for key, value in exclusions.items() if not value["reimport_allowed"]}
    profile_ids = set()
    for path in (COLLECTION / "raw/horse_profile").glob("**/page_*.json"):
        for row in _api_body(path):
            if row.get("breed") == "제주마" and str(row.get("hrNo")) not in blocked:
                profile_ids.add(str(row.get("hrNo")))

    family_spec = {
        "daily_training": ("trDate", "training_10"),
        "medical": ("clinicDate", "medical"),
        "starting_exam": ("trainDate", "starting_exams"),
    }
    selected_rows: dict[str, tuple[dict[str, Any], str]] = {}
    for family, (date_field, partition_hint) in family_spec.items():
        source_page = next(
            page for page in manifest["pages"]
            if page["family"] == family and partition_hint in page["path"]
        )
        for row in _api_body(ROOT / source_page["path"]):
            horse_id = str(row.get("hrNo"))
            event_date = _iso_api_date(row.get(date_field))
            if horse_id in profile_ids and START_DATE <= event_date <= END_DATE:
                selected_rows[family] = (row, event_date)
                break
        assert family in selected_rows, f"no exact-profile in-scope item for {family}"

    conn = _connection()
    with tempfile.TemporaryDirectory(prefix="aux-fixture-", dir=FIXTURE_ROOT) as temp_dir:
        temp = Path(temp_dir)
        initial_pages = []
        initial_rows: dict[str, dict[str, Any]] = {}
        for i, (family, (source_row, event_date)) in enumerate(selected_rows.items(), 1):
            row = dict(source_row)
            initial_rows[family] = row
            params = {"meet": "2", "pageNo": "1", "numOfRows": "1"}
            if family == "daily_training":
                params["tr_month"] = event_date[:7].replace("-", "")
            elif family == "medical":
                params["clinic_year"] = event_date[:4]
            else:
                params["tr_year"] = event_date[:4]
            initial_pages.append(_fixture_page(
                family, temp / f"initial_{family}.json", [row], params,
                f"2026-10-17T00:00:0{i}.000Z",
            ))

        conn.execute("BEGIN IMMEDIATE")
        first_started = time.perf_counter()
        first = apply_auxiliary(conn, initial_pages, ROOT, "aux-fixture-first")
        first_seconds = time.perf_counter() - first_started
        assert first["rows_added"] == 3 and first["rows_held"] == 0, first
        assert first["medical_slots_added"] == 2, first
        assert conn.in_transaction, "the loader must leave transaction ownership with its caller"
        initial_counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "daily_training_api_rows", "medical_api_rows", "medical_api_diagnosis_slots",
                "starting_exam_api_rows", "research_refresh_observations", "research_refresh_holds",
            )
        }
        conn.commit()

        changed_pages = []
        for i, (family, row) in enumerate(initial_rows.items(), 4):
            changed = dict(row)
            if family == "daily_training":
                changed["trTerm"] = int(changed.get("trTerm") or 0) + 1
            elif family == "medical":
                changed["illName1"] = "fixture changed diagnosis"
            else:
                changed["reason"] = "fixture changed judgment note"
            original_date = selected_rows[family][1]
            params = {"meet": "2", "pageNo": "1", "numOfRows": "1"}
            if family == "daily_training":
                params["tr_month"] = original_date[:7].replace("-", "")
            elif family == "medical":
                params["clinic_year"] = original_date[:4]
            else:
                params["tr_year"] = original_date[:4]
            changed_pages.append(_fixture_page(
                family, temp / f"changed_{family}.json", [changed], params,
                f"2026-10-17T00:00:0{i}.000Z",
            ))

        conn.execute("BEGIN IMMEDIATE")
        held = apply_auxiliary(conn, changed_pages, ROOT, "aux-fixture-held")
        assert held["rows_added"] == 0 and held["rows_held"] == 3, held
        assert conn.execute("SELECT count(*) FROM research_refresh_holds").fetchone()[0] == 3
        decisions = Counter(row[0] for row in conn.execute("SELECT decision FROM research_refresh_observations"))
        assert decisions["held"] == 3 and decisions["inserted"] == 3, decisions
        changed_counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("daily_training_api_rows", "medical_api_rows", "starting_exam_api_rows")
        }
        assert changed_counts == {"daily_training_api_rows": 1, "medical_api_rows": 1, "starting_exam_api_rows": 1}
        conn.commit()

        conn.execute("BEGIN IMMEDIATE")
        held_replay = apply_auxiliary(conn, changed_pages, ROOT, "aux-fixture-held-replay")
        assert held_replay["source_artifacts_added"] == 0
        assert held_replay["api_records_added"] == 0
        assert conn.execute("SELECT count(*) FROM research_refresh_holds").fetchone()[0] == 3
        conn.commit()

        daily = initial_rows["daily_training"]
        original_date = selected_rows["daily_training"][1]
        from datetime import date, timedelta
        event_day = date.fromisoformat(original_date)
        duplicate_iso = next(
            (event_day + timedelta(days=offset)).isoformat()
            for offset in range(1, 35)
            if START_DATE <= (event_day + timedelta(days=offset)).isoformat() <= END_DATE
            and conn.execute(
                "SELECT 1 FROM daily_training_api_rows WHERE horse_id=? AND training_date=?",
                (str(daily["hrNo"]), (event_day + timedelta(days=offset)).isoformat()),
            ).fetchone() is None
        )
        duplicate_raw = dict(daily)
        duplicate_raw["trDate"] = duplicate_iso.replace("-", "")
        for field in ("stTime", "spTime"):
            value = duplicate_raw.get(field)
            if isinstance(value, str) and len(value) == 14 and value[:8].isdigit():
                duplicate_raw[field] = duplicate_iso.replace("-", "") + value[8:]
            elif isinstance(value, int) and len(str(value)) == 14:
                duplicate_raw[field] = int(duplicate_iso.replace("-", "") + str(value)[8:])
        duplicate_params = {"meet": "2", "pageNo": "1", "numOfRows": "2", "tr_month": duplicate_iso[:7].replace("-", "")}
        duplicate_page = _fixture_page(
            "daily_training", temp / "repeated_daily_item.json", [duplicate_raw, duplicate_raw],
            duplicate_params, "2026-10-17T00:01:00.000Z",
        )
        conn.execute("BEGIN IMMEDIATE")
        repeated = apply_auxiliary(conn, [duplicate_page], ROOT, "aux-fixture-repeat")
        assert repeated["rows_added"] == 2 and repeated["rows_held"] == 0, repeated
        repeated_count = conn.execute(
            "SELECT count(*) FROM daily_training_api_rows WHERE horse_id=? AND training_date=? AND raw_row_json=?",
            (str(daily["hrNo"]), duplicate_iso, canonical_json(duplicate_raw)),
        ).fetchone()[0]
        assert repeated_count == 2, repeated_count
        assert conn.execute("SELECT count(*) FROM medical_api_diagnosis_slots").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM daily_training_api_rows WHERE run1_count IS NOT NULL OR run2_count IS NOT NULL").fetchone()[0] == 0
        conn.commit()

        return {
            "first_apply_seconds": round(first_seconds, 4),
            "first_rows_added": first["rows_added"],
            "initial_table_counts": initial_counts,
            "changed_rows_held": held["rows_held"],
            "holds_after_changed_payloads": conn.execute("SELECT count(*) FROM research_refresh_holds").fetchone()[0],
            "held_replay_api_records_added": held_replay["api_records_added"],
            "identical_occurrences_preserved": repeated_count,
            "final_table_counts": {
                table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in (
                    "daily_training_api_rows", "medical_api_rows", "medical_api_diagnosis_slots",
                    "starting_exam_api_rows", "research_refresh_observations", "research_refresh_holds",
                )
            },
        }


if __name__ == "__main__":
    print(json.dumps(run_fixture(), ensure_ascii=False, sort_keys=True))
