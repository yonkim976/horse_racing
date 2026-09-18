"""Build the next immutable Jeju-native research database snapshot.

The sealed race/trial database is copied, never edited in place. Confirmed-native
training, start-training, medical and measured-weight rows are then appended with
line-level provenance. All nine Jeju Text archives are inventoried by file and
hash; a document is not described as row-parsed unless that work is complete.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import shutil
import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "data/research/jeju_native_analysis_db_20260915"
BASE_DB = BASE_DIR / "jeju_native_analysis.sqlite3"
OUT = ROOT / "data/research/jeju_native_extended_db_20260915"
DB = OUT / "jeju_native_extended.sqlite3"
TMP = OUT / "jeju_native_extended.sqlite3.tmp"
TRAINING = ROOT / "data/raw/jeju_native_training"
HEALTH_WEIGHT = ROOT / "data/raw/jeju_native_health_weight"
OTHER = ROOT / "data/research/jeju_other_sources_verification_20260915"
TEXT_TYPES = ("dacom01", "dacom12", "dacom13", "dacom23", "dacom55", "dacom71", "dacom72", "db4", "db5")

EXTENDED_SCHEMA = """
CREATE TABLE collection_request (
  id INTEGER PRIMARY KEY,
  request_kind TEXT NOT NULL,
  period TEXT,
  source_artifact_id INTEGER REFERENCES source_artifact(id),
  request_json TEXT,
  request_sha256 TEXT,
  response_sha256 TEXT,
  retrieved_at_ms INTEGER,
  http_status INTEGER,
  response_bytes INTEGER,
  total_count INTEGER,
  UNIQUE(request_kind, period, response_sha256, source_artifact_id)
);
CREATE TABLE daily_training_record (
  id INTEGER PRIMARY KEY,
  source_row_id INTEGER NOT NULL UNIQUE REFERENCES source_row(id),
  hr_no TEXT NOT NULL,
  event_date TEXT NOT NULL,
  horse_name TEXT,
  meet INTEGER NOT NULL CHECK(meet=2),
  training_duration_seconds INTEGER NOT NULL,
  canter_count INTEGER NOT NULL,
  gallop_count INTEGER NOT NULL,
  entry_plan TEXT,
  exercise_person_type TEXT,
  exercise_person_no TEXT,
  part INTEGER,
  part_no INTEGER,
  identity_status TEXT NOT NULL,
  CHECK(length(hr_no)=7 AND hr_no NOT GLOB '*[^0-9]*')
);
CREATE TABLE start_training_record (
  id INTEGER PRIMARY KEY,
  source_row_id INTEGER NOT NULL UNIQUE REFERENCES source_row(id),
  hr_no TEXT NOT NULL,
  event_date TEXT NOT NULL,
  horse_name TEXT,
  meet INTEGER NOT NULL CHECK(meet=2),
  exercise_person_name TEXT,
  remark TEXT,
  part INTEGER,
  part_no INTEGER,
  identity_status TEXT NOT NULL,
  duplicate_status TEXT NOT NULL,
  duplicate_occurrence INTEGER NOT NULL,
  CHECK(length(hr_no)=7 AND hr_no NOT GLOB '*[^0-9]*')
);
CREATE TABLE medical_record (
  id INTEGER PRIMARY KEY,
  source_row_id INTEGER NOT NULL UNIQUE REFERENCES source_row(id),
  hr_no TEXT NOT NULL,
  event_date TEXT NOT NULL,
  horse_name TEXT,
  meet INTEGER NOT NULL CHECK(meet=2),
  hospital_name TEXT,
  diagnosis_1 TEXT,
  diagnosis_2 TEXT,
  has_diagnosis INTEGER NOT NULL CHECK(has_diagnosis IN (0,1)),
  part INTEGER,
  identity_status TEXT NOT NULL,
  duplicate_status TEXT NOT NULL,
  duplicate_occurrence INTEGER NOT NULL,
  CHECK(length(hr_no)=7 AND hr_no NOT GLOB '*[^0-9]*')
);
CREATE TABLE measured_weight_record (
  id INTEGER PRIMARY KEY,
  source_row_id INTEGER NOT NULL UNIQUE REFERENCES source_row(id),
  entry_id INTEGER REFERENCES entry(id),
  hr_no TEXT NOT NULL,
  race_date TEXT NOT NULL,
  race_number INTEGER NOT NULL,
  horse_number INTEGER NOT NULL,
  horse_name TEXT,
  meet INTEGER NOT NULL CHECK(meet=2),
  race_distance_m INTEGER,
  race_name TEXT,
  burden_type TEXT,
  body_weight_kg INTEGER NOT NULL CHECK(body_weight_kg>0),
  body_weight_change_kg INTEGER,
  recent_race_date TEXT,
  recent_race_date_raw TEXT,
  link_status TEXT NOT NULL,
  link_details_json TEXT,
  UNIQUE(race_date, race_number, hr_no)
);
CREATE TABLE source_duplicate_group (
  id INTEGER PRIMARY KEY,
  source_kind TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  occurrences INTEGER NOT NULL,
  excess_occurrences INTEGER NOT NULL,
  representative_source_row_id INTEGER NOT NULL REFERENCES source_row(id),
  status TEXT NOT NULL,
  UNIQUE(source_kind, payload_sha256)
);
CREATE TABLE text_document (
  id INTEGER PRIMARY KEY,
  source_artifact_id INTEGER NOT NULL REFERENCES source_artifact(id),
  text_type TEXT NOT NULL,
  file_date TEXT,
  remote_path TEXT NOT NULL,
  source_url TEXT,
  retrieved_at_ms INTEGER,
  response_bytes INTEGER,
  collection_status TEXT NOT NULL,
  row_parse_status TEXT NOT NULL,
  native_link_status TEXT NOT NULL,
  UNIQUE(text_type, remote_path)
);
CREATE TABLE extended_issue (
  id INTEGER PRIMARY KEY,
  issue_code TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  event_date TEXT,
  event_number INTEGER,
  horse_number INTEGER,
  hr_no TEXT,
  source_row_id INTEGER REFERENCES source_row(id),
  details_json TEXT NOT NULL
);
CREATE TABLE extended_coverage (
  id INTEGER PRIMARY KEY,
  source_kind TEXT NOT NULL,
  dimension TEXT NOT NULL,
  dimension_value TEXT NOT NULL,
  total_rows INTEGER NOT NULL,
  positive_measure_rows INTEGER,
  unique_horses INTEGER,
  linked_entry_rows INTEGER,
  unlinked_entry_rows INTEGER,
  duplicate_excess_rows INTEGER,
  status TEXT NOT NULL,
  UNIQUE(source_kind, dimension, dimension_value)
);
CREATE INDEX ix_daily_training_horse_date ON daily_training_record(hr_no,event_date);
CREATE INDEX ix_start_training_horse_date ON start_training_record(hr_no,event_date);
CREATE INDEX ix_medical_horse_date ON medical_record(hr_no,event_date);
CREATE INDEX ix_weight_race_key ON measured_weight_record(race_date,race_number,horse_number);
CREATE INDEX ix_weight_entry ON measured_weight_record(entry_id);
CREATE INDEX ix_text_document_type_date ON text_document(text_type,file_date);
CREATE INDEX ix_extended_issue_code ON extended_issue(issue_code);
CREATE VIEW analysis_daily_training AS
SELECT * FROM daily_training_record;
CREATE VIEW analysis_start_training_distinct AS
SELECT * FROM start_training_record WHERE duplicate_occurrence=1;
CREATE VIEW analysis_medical_distinct AS
SELECT * FROM medical_record WHERE duplicate_occurrence=1;
CREATE VIEW analysis_measured_weight AS
SELECT w.*,v.event_date,v.event_number,e.horse_name AS entry_horse_name
FROM measured_weight_record w
JOIN entry e ON e.id=w.entry_id
JOIN event v ON v.id=e.event_id
WHERE w.link_status='linked_to_native_entry'
  AND v.population_status='confirmed_native_normal_race'
  AND e.identity_status='official_race_ids_linked';
"""


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_hash(row: dict) -> str:
    return hashlib.sha256(compact(row).encode("utf-8")).hexdigest()


def official_horse_no(value: object) -> str:
    text = str(value or "").strip()
    if not text.isdigit():
        raise ValueError(f"invalid hrNo: {value!r}")
    text = str(int(text)).zfill(7)
    if len(text) != 7:
        raise ValueError(f"invalid hrNo length: {value!r}")
    return text


def official_person_no(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else text


def event_day(value: object) -> str:
    text = str(value or "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid date: {value!r}")
    date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:]}")
    return text


def rows(path: Path) -> Iterator[tuple[int, dict]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                yield line_number, json.loads(line)


def ensure_artifact(
    conn: sqlite3.Connection, path: Path, source_kind: str, row_count: int | None
) -> int:
    relative = path.relative_to(ROOT).as_posix()
    found = conn.execute("SELECT id,sha256,row_count FROM source_artifact WHERE path=?", (relative,)).fetchone()
    actual = digest(path)
    if found:
        if found[1] != actual:
            raise ValueError(f"changed registered artifact: {relative}")
        return int(found[0])
    cursor = conn.execute(
        "INSERT INTO source_artifact(source_kind,path,sha256,row_count) VALUES (?,?,?,?)",
        (source_kind, relative, actual, row_count),
    )
    return int(cursor.lastrowid)


def insert_source_row(
    conn: sqlite3.Connection, artifact_id: int, line_number: int, row: dict
) -> tuple[int, str]:
    normalized = compact(row)
    row_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    cursor = conn.execute(
        "INSERT INTO source_row(source_artifact_id,line_number,row_sha256,normalized_json) VALUES (?,?,?,?)",
        (artifact_id, line_number, row_hash, normalized),
    )
    return int(cursor.lastrowid), row_hash


def load_training(conn: sqlite3.Connection) -> dict:
    output: dict[str, dict] = {}
    for dataset in ("horse_training", "start_training"):
        path = TRAINING / f"{dataset}_confirmed_native.jsonl.gz"
        manifest_path = TRAINING / f"{dataset}_confirmed_native.manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if digest(path) != manifest["output_sha256"]:
            raise ValueError(f"training hash mismatch: {path}")
        ensure_artifact(conn, manifest_path, f"{dataset}_manifest", 1)
        artifact_id = ensure_artifact(conn, path, f"{dataset}_confirmed_native", int(manifest["native_rows"]))
        annual: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        hashes: collections.Counter[str] = collections.Counter()
        representatives: dict[str, int] = {}
        count = 0
        for line_number, row in rows(path):
            source_row_id, row_hash = insert_source_row(conn, artifact_id, line_number, row)
            count += 1
            day = event_day(row["trDate"])
            year = day[:4]
            hr_no = official_horse_no(row["hrNo"])
            if row.get("meet") != "제주":
                raise ValueError(f"non-Jeju training row: {line_number}")
            hashes[row_hash] += 1
            representatives.setdefault(row_hash, source_row_id)
            occurrence = hashes[row_hash]
            annual[year]["rows"] += 1
            annual[year]["unique_horses_placeholder"] = 0
            if dataset == "horse_training":
                duration = int(row.get("trTerm") or 0)
                annual[year]["positive"] += duration > 0
                conn.execute(
                    """INSERT INTO daily_training_record(
                    source_row_id,hr_no,event_date,horse_name,meet,training_duration_seconds,
                    canter_count,gallop_count,entry_plan,exercise_person_type,
                    exercise_person_no,part,part_no,identity_status)
                    VALUES (?,?,?,?,2,?,?,?,?,?,?,?,?,?)""",
                    (
                        source_row_id, hr_no, day, row.get("hrName"), duration,
                        int(row.get("run1Cnt") or 0), int(row.get("run2Cnt") or 0),
                        row.get("chulGubun"), row.get("prGubun"), official_person_no(row.get("prNo")),
                        row.get("part"), row.get("partNo"), "confirmed_native_race_roster",
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO start_training_record(
                    source_row_id,hr_no,event_date,horse_name,meet,exercise_person_name,
                    remark,part,part_no,identity_status,duplicate_status,duplicate_occurrence)
                    VALUES (?,?,?,?,2,?,?,?,?,?,?,?)""",
                    (
                        source_row_id, hr_no, day, row.get("hrName"), row.get("prName"),
                        row.get("remark"), row.get("part"), row.get("partNo"),
                        "confirmed_native_race_roster",
                        "source_exact_duplicate" if occurrence > 1 else "first_occurrence",
                        occurrence,
                    ),
                )
        if count != int(manifest["native_rows"]):
            raise ValueError(f"training count mismatch: {dataset} {count}")
        unique_by_year = dict(conn.execute(
            f"SELECT substr(event_date,1,4),COUNT(DISTINCT hr_no) FROM {'daily_training_record' if dataset == 'horse_training' else 'start_training_record'} GROUP BY 1"
        ))
        for year, values in annual.items():
            duplicate_excess = 0
            if dataset == "start_training":
                duplicate_excess = int(conn.execute(
                    "SELECT COUNT(*) FROM start_training_record WHERE substr(event_date,1,4)=? AND duplicate_occurrence>1", (year,)
                ).fetchone()[0])
            conn.execute(
                """INSERT INTO extended_coverage(source_kind,dimension,dimension_value,total_rows,
                positive_measure_rows,unique_horses,linked_entry_rows,unlinked_entry_rows,
                duplicate_excess_rows,status) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (dataset,"year",year,values["rows"],values.get("positive"),unique_by_year[year],None,None,duplicate_excess,"loaded_verified"),
            )
        duplicate_groups = 0
        duplicate_excess = 0
        for row_hash, occurrences in hashes.items():
            if occurrences <= 1:
                continue
            duplicate_groups += 1
            duplicate_excess += occurrences - 1
            conn.execute(
                "INSERT INTO source_duplicate_group(source_kind,payload_sha256,occurrences,excess_occurrences,representative_source_row_id,status) VALUES (?,?,?,?,?,?)",
                (dataset,row_hash,occurrences,occurrences-1,representatives[row_hash],"source_repetition_unresolved"),
            )
        output[dataset] = {"rows": count, "duplicate_groups": duplicate_groups, "duplicate_excess": duplicate_excess}
    return output


def clean_diagnosis(value: object) -> str | None:
    text = str(value or "").strip()
    return None if text in ("", "-") else text


def load_health_weight(conn: sqlite3.Connection) -> dict:
    output: dict[str, dict] = {}
    entry_lookup: dict[tuple[str, int, str], list[tuple[int, int, str | None]]] = collections.defaultdict(list)
    for row in conn.execute(
        """SELECT e.id,v.event_date,v.event_number,e.hr_no,e.horse_number,e.horse_name
           FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='race' AND e.hr_no IS NOT NULL"""
    ):
        entry_lookup[(row[1], int(row[2]), str(row[3]))].append((int(row[0]), int(row[4]), row[5]))
    for kind in ("medical", "weight"):
        annual: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        payload_counts: collections.Counter[str] = collections.Counter()
        representatives: dict[str, int] = {}
        count = 0
        paths = sorted(HEALTH_WEIGHT.glob(f"{kind}_*.jsonl"))
        for path in paths:
            annual[path.stem.split("_", 1)[1][:4]]
        for path in paths:
            period = path.stem.split("_", 1)[1]
            manifest_path = path.with_suffix(".manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if digest(path) != manifest["native_rows_sha256"]:
                raise ValueError(f"health/weight hash mismatch: {path}")
            ensure_artifact(conn, manifest_path, f"{kind}_manifest", 1)
            artifact_id = ensure_artifact(conn, path, f"{kind}_confirmed_native", int(manifest["native_rows"]))
            for page in manifest["source_pages"]:
                sanitized = page.get("source_url_without_key")
                request_json = compact({"url": sanitized}) if sanitized else None
                conn.execute(
                    """INSERT INTO collection_request(request_kind,period,source_artifact_id,request_json,
                    request_sha256,response_sha256,retrieved_at_ms,http_status,response_bytes,total_count)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (f"{kind}_api",period,artifact_id,request_json,
                     hashlib.sha256(request_json.encode()).hexdigest() if request_json else None,
                     page.get("sha256"),page.get("retrieved_at_ms"),page.get("status_code"),
                     page.get("response_bytes"),page.get("total_count")),
                )
            period_count = 0
            for line_number, row in rows(path):
                source_row_id, row_hash = insert_source_row(conn, artifact_id, line_number, row)
                payload_counts[row_hash] += 1
                representatives.setdefault(row_hash, source_row_id)
                occurrence = payload_counts[row_hash]
                count += 1
                period_count += 1
                hr_no = official_horse_no(row["hrNo"])
                if row.get("meet") != "제주":
                    raise ValueError(f"non-Jeju {kind} row: {path}:{line_number}")
                if kind == "medical":
                    day = event_day(row["clinicDate"])
                    d1, d2 = clean_diagnosis(row.get("illName1")), clean_diagnosis(row.get("illName2"))
                    annual[day[:4]]["rows"] += 1
                    annual[day[:4]]["positive"] += bool(d1 or d2)
                    conn.execute(
                        """INSERT INTO medical_record(source_row_id,hr_no,event_date,horse_name,meet,
                        hospital_name,diagnosis_1,diagnosis_2,has_diagnosis,part,identity_status,
                        duplicate_status,duplicate_occurrence) VALUES (?,?,?,?,2,?,?,?,?,?,?,?,?)""",
                        (source_row_id,hr_no,day,row.get("hrName"),row.get("hospiName"),d1,d2,
                         int(bool(d1 or d2)),row.get("part"),"confirmed_native_race_roster",
                         "source_exact_duplicate" if occurrence > 1 else "first_occurrence",occurrence),
                    )
                else:
                    day = event_day(row["rcDate"])
                    race_no = int(row["rcNo"])
                    horse_number = int(row["chulNo"])
                    candidates = entry_lookup.get((day,race_no,hr_no),[])
                    if len(candidates) == 1 and candidates[0][1] == horse_number:
                        entry_id = candidates[0][0]
                        status = "linked_to_native_entry"
                        details = {"key_match": True, "horse_number_match": True, "horse_name_match": candidates[0][2] == row.get("hrName")}
                    elif len(candidates) == 1:
                        entry_id = None
                        status = "horse_number_conflict"
                        details = {"entry_id": candidates[0][0], "db_horse_number": candidates[0][1], "source_horse_number": horse_number}
                    elif len(candidates) > 1:
                        entry_id = None
                        status = "multiple_native_entries"
                        details = {"candidate_entry_ids": [x[0] for x in candidates]}
                    else:
                        entry_id = None
                        status = "native_entry_absent_from_research_db"
                        details = {"key": [day,race_no,hr_no,horse_number]}
                    annual[day[:4]]["rows"] += 1
                    annual[day[:4]]["positive"] += 1
                    annual[day[:4]]["linked"] += status == "linked_to_native_entry"
                    annual[day[:4]]["unlinked"] += status != "linked_to_native_entry"
                    recent = row.get("recentRcDate")
                    recent_raw = str(recent).strip() if recent is not None else None
                    recent_date = event_day(recent_raw) if recent_raw and len(recent_raw) == 8 and recent_raw.isdigit() else None
                    conn.execute(
                        """INSERT INTO measured_weight_record(source_row_id,entry_id,hr_no,race_date,
                        race_number,horse_number,horse_name,meet,race_distance_m,race_name,burden_type,
                        body_weight_kg,body_weight_change_kg,recent_race_date,recent_race_date_raw,
                        link_status,link_details_json) VALUES (?,?,?,?,?,?,?,2,?,?,?,?,?,?,?,?,?)""",
                        (source_row_id,entry_id,hr_no,day,race_no,horse_number,row.get("hrName"),
                         row.get("rcDist"),row.get("rcName"),row.get("budam"),int(row["wgHr"]),
                         row.get("wgHrDiff"),recent_date,recent_raw,status,compact(details)),
                    )
                    if status != "linked_to_native_entry":
                        conn.execute(
                            "INSERT INTO extended_issue(issue_code,source_kind,event_date,event_number,horse_number,hr_no,source_row_id,details_json) VALUES (?,?,?,?,?,?,?,?)",
                            (status,kind,day,race_no,horse_number,hr_no,source_row_id,compact(details)),
                        )
            if period_count != int(manifest["native_rows"]):
                raise ValueError(f"period count mismatch: {path} {period_count}")
        table = "medical_record" if kind == "medical" else "measured_weight_record"
        unique_by_year = dict(conn.execute(f"SELECT substr({'event_date' if kind == 'medical' else 'race_date'},1,4),COUNT(DISTINCT hr_no) FROM {table} GROUP BY 1"))
        duplicate_by_year: dict[str,int] = {}
        if kind == "medical":
            duplicate_by_year = dict(conn.execute("SELECT substr(event_date,1,4),COUNT(*) FROM medical_record WHERE duplicate_occurrence>1 GROUP BY 1"))
        for year, values in annual.items():
            conn.execute(
                """INSERT INTO extended_coverage(source_kind,dimension,dimension_value,total_rows,
                positive_measure_rows,unique_horses,linked_entry_rows,unlinked_entry_rows,
                duplicate_excess_rows,status) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (kind,"year",year,values["rows"],values["positive"],unique_by_year.get(year,0),
                 values.get("linked"),values.get("unlinked"),duplicate_by_year.get(year,0),"loaded_verified"),
            )
        duplicate_groups = 0
        duplicate_excess = 0
        for row_hash, occurrences in payload_counts.items():
            if occurrences <= 1:
                continue
            duplicate_groups += 1
            duplicate_excess += occurrences - 1
            conn.execute(
                "INSERT INTO source_duplicate_group(source_kind,payload_sha256,occurrences,excess_occurrences,representative_source_row_id,status) VALUES (?,?,?,?,?,?)",
                (kind,row_hash,occurrences,occurrences-1,representatives[row_hash],"source_repetition_unresolved"),
            )
        output[kind] = {"rows":count,"duplicate_groups":duplicate_groups,"duplicate_excess":duplicate_excess}
    return output


def load_other_issues(conn: sqlite3.Connection) -> dict:
    path = OTHER / "issues.jsonl"
    artifact_id = ensure_artifact(conn,path,"other_source_issue_ledger",sum(1 for _ in path.open(encoding="utf-8")))
    counts: collections.Counter[str] = collections.Counter()
    for line_number, row in rows(path):
        source_row_id, _ = insert_source_row(conn,artifact_id,line_number,row)
        issue = str(row["issue"])
        counts[issue] += 1
        key = row.get("key")
        conn.execute(
            "INSERT INTO extended_issue(issue_code,source_kind,event_date,event_number,horse_number,hr_no,source_row_id,details_json) VALUES (?,?,?,?,?,?,?,?)",
            (issue,"other_source_verification",str(row.get("race_date") or (key[0] if key else "")) or None,
             row.get("race_number") or (key[1] if key else None),key[2] if key and len(key)>2 and isinstance(key[2],int) else None,
             row.get("hrNo"),source_row_id,compact(row)),
        )
    verification = OTHER / "verification.json"
    ensure_artifact(conn,verification,"other_source_verification",1)
    return dict(counts)


def final_text_events(manifest: Path) -> dict[str,dict]:
    final: dict[str,dict] = {}
    final_statuses = {"downloaded","skipped_existing","skipped_duplicate_sha256","verified_empty_source"}
    for _, row in rows(manifest):
        if int(row.get("meet") or 0) == 2 and row.get("status") in final_statuses:
            final[str(row["remote_path"])] = row
    return final


def load_text_inventory(conn: sqlite3.Connection) -> dict:
    result = {}
    for text_type in TEXT_TYPES:
        manifest = ROOT / f"data/raw/kra_text/_manifests/{text_type}/manifest.jsonl"
        ensure_artifact(conn,manifest,"text_collection_manifest",sum(1 for _ in manifest.open(encoding="utf-8")))
        events = final_text_events(manifest)
        for remote_path, row in sorted(events.items()):
            local = Path(row["local_path"])
            if not local.is_absolute():
                local = ROOT/local
            artifact_id = ensure_artifact(conn,local,f"text_{text_type}",None)
            if digest(local) != row["sha256"]:
                raise ValueError(f"Text hash mismatch: {local}")
            if text_type == "dacom23":
                parse_status = "native_candidate_rows_loaded_in_base_db"
                native_status = "partial_confirmed_native_linkage"
            elif text_type == "dacom71":
                parse_status = "race_number_name_keys_partially_verified"
                native_status = "content_not_yet_linked"
            else:
                parse_status = "document_hash_verified_unparsed"
                native_status = "content_not_yet_linked"
            conn.execute(
                """INSERT INTO text_document(source_artifact_id,text_type,file_date,remote_path,
                source_url,retrieved_at_ms,response_bytes,collection_status,row_parse_status,native_link_status)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (artifact_id,text_type,row.get("file_date"),remote_path,row.get("source_url"),
                 row.get("retrieved_at_ms"),row.get("response_bytes"),row["status"],parse_status,native_status),
            )
        conn.execute(
            """INSERT INTO extended_coverage(source_kind,dimension,dimension_value,total_rows,
            positive_measure_rows,unique_horses,linked_entry_rows,unlinked_entry_rows,
            duplicate_excess_rows,status) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (f"text_{text_type}","all","all",len(events),None,None,None,None,None,
             "partially_loaded" if text_type in ("dacom23","dacom71") else "document_inventory_only"),
        )
        result[text_type] = len(events)
    return result


def add_total_coverage(conn: sqlite3.Connection) -> None:
    specs = {
        "horse_training": ("daily_training_record","training_duration_seconds>0","event_date"),
        "start_training": ("start_training_record",None,"event_date"),
        "medical": ("medical_record","has_diagnosis=1","event_date"),
        "weight": ("measured_weight_record","body_weight_kg>0","race_date"),
    }
    for kind,(table,positive,date_col) in specs.items():
        total = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        positive_count = int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {positive}").fetchone()[0]) if positive else None
        unique_horses = int(conn.execute(f"SELECT COUNT(DISTINCT hr_no) FROM {table}").fetchone()[0])
        linked = unlinked = None
        if kind == "weight":
            linked = int(conn.execute("SELECT COUNT(*) FROM measured_weight_record WHERE link_status='linked_to_native_entry'").fetchone()[0])
            unlinked = total-linked
        duplicate_excess = int(conn.execute("SELECT COALESCE(SUM(excess_occurrences),0) FROM source_duplicate_group WHERE source_kind=?",(kind,)).fetchone()[0])
        conn.execute(
            """INSERT INTO extended_coverage(source_kind,dimension,dimension_value,total_rows,
            positive_measure_rows,unique_horses,linked_entry_rows,unlinked_entry_rows,
            duplicate_excess_rows,status) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (kind,"all","all",total,positive_count,unique_horses,linked,unlinked,duplicate_excess,"loaded_verified"),
        )


def validate(conn: sqlite3.Connection) -> dict:
    scalar = lambda sql: int(conn.execute(sql).fetchone()[0])
    checks = {
        "base_entries_preserved": scalar("SELECT COUNT(*) FROM entry")==107896,
        "daily_training_rows": scalar("SELECT COUNT(*) FROM daily_training_record")==884383,
        "start_training_rows": scalar("SELECT COUNT(*) FROM start_training_record")==184351,
        "medical_rows": scalar("SELECT COUNT(*) FROM medical_record")==11653,
        "weight_rows": scalar("SELECT COUNT(*) FROM measured_weight_record")==90713,
        "daily_positive_duration": scalar("SELECT COUNT(*) FROM daily_training_record WHERE training_duration_seconds>0")==866457,
        "medical_diagnosed": scalar("SELECT COUNT(*) FROM medical_record WHERE has_diagnosis=1")==10001,
        "start_duplicate_excess": scalar("SELECT COALESCE(SUM(excess_occurrences),0) FROM source_duplicate_group WHERE source_kind='start_training'")==3153,
        "medical_duplicate_excess": scalar("SELECT COALESCE(SUM(excess_occurrences),0) FROM source_duplicate_group WHERE source_kind='medical'")==21,
        "all_ids_text": scalar("SELECT COUNT(*) FROM (SELECT hr_no FROM daily_training_record UNION ALL SELECT hr_no FROM start_training_record UNION ALL SELECT hr_no FROM medical_record UNION ALL SELECT hr_no FROM measured_weight_record) WHERE typeof(hr_no)!='text' OR length(hr_no)!=7 OR hr_no GLOB '*[^0-9]*'")==0,
        "weight_unique": scalar("SELECT COUNT(*) FROM measured_weight_record")==scalar("SELECT COUNT(DISTINCT race_date||':'||race_number||':'||hr_no) FROM measured_weight_record"),
        "text_documents": scalar("SELECT COUNT(*) FROM text_document")==14131,
        "source_row_delta": scalar("SELECT COUNT(*) FROM source_row")==1279932,
        "foreign_keys": not conn.execute("PRAGMA foreign_key_check").fetchall(),
    }
    return {"passed":all(checks.values()),"checks":checks,"counts":{
        "source_artifacts":scalar("SELECT COUNT(*) FROM source_artifact"),
        "source_rows":scalar("SELECT COUNT(*) FROM source_row"),
        "collection_requests":scalar("SELECT COUNT(*) FROM collection_request"),
        "daily_training":scalar("SELECT COUNT(*) FROM daily_training_record"),
        "start_training":scalar("SELECT COUNT(*) FROM start_training_record"),
        "medical":scalar("SELECT COUNT(*) FROM medical_record"),
        "measured_weight":scalar("SELECT COUNT(*) FROM measured_weight_record"),
        "text_documents":scalar("SELECT COUNT(*) FROM text_document"),
        "extended_issues":scalar("SELECT COUNT(*) FROM extended_issue"),
    }}


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force",action="store_true",help="Replace only the extended research snapshot.")
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if DB.exists() and not args.force:
        raise SystemExit(f"refusing to replace existing research DB without --force: {DB}")
    TMP.unlink(missing_ok=True)
    shutil.copy2(BASE_DB,TMP)
    conn=sqlite3.connect(TMP)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.executescript(EXTENDED_SCHEMA)
        training=load_training(conn)
        health_weight=load_health_weight(conn)
        other_issues=load_other_issues(conn)
        text=load_text_inventory(conn)
        add_total_coverage(conn)
        conn.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",("extended_schema_version",compact("1")))
        conn.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",("extended_scope",compact({"phase":"verified_id_sources_and_text_inventory","base_database":str(BASE_DB.relative_to(ROOT)),"operational_db_modified":False})))
        result=validate(conn)
        result["training"]=training
        result["health_weight"]=health_weight
        result["other_issue_counts"]=other_issues
        result["text_documents_by_type"]=text
        if not result["passed"]:
            raise RuntimeError(result)
        conn.execute("PRAGMA optimize")
        conn.commit()
        integrity=conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity!="ok":
            raise RuntimeError(integrity)
    finally:
        conn.close()
    if DB.exists():
        DB.unlink()
    TMP.rename(DB)
    result["integrity_check"]="ok"
    result["database_path"]=str(DB.relative_to(ROOT))
    result["database_bytes"]=DB.stat().st_size
    result["database_sha256"]=digest(DB)
    (OUT/"validation.json").write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    manifest={
        "database":result["database_path"],"database_sha256":result["database_sha256"],
        "base_database":str(BASE_DB.relative_to(ROOT)),"base_database_sha256":digest(BASE_DB),
        "builder":"scripts/build_jeju_native_extended_db.py",
        "verifier":"scripts/verify_jeju_native_extended_db.py",
        "catalog":"data/research/jeju_native_extended_db_20260915/catalog.json",
        "catalog_exporter":"scripts/export_jeju_native_extended_catalog.py",
        "independent_validation":"data/research/jeju_native_extended_db_20260915/independent_validation.json",
        "readme":"data/research/jeju_native_extended_db_20260915/README.md",
        "report":"docs/JEJU_NATIVE_EXTENDED_DB_PHASE1_LOAD_2026-09-15.md",
        "validation":str((OUT/"validation.json").relative_to(ROOT)),
        "existing_operational_database_modified":False,
        "scope_status":"verified_id_sources_loaded_text_documents_inventoried",
    }
    (OUT/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
