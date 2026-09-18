"""Build one integration-ready Busan research SQLite snapshot.

The source databases are opened read-only.  The output is built at a temporary
path and atomically installed, so a failed run cannot leave a partial database.
No operating database, model, registry, prediction, or betting path is changed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = ROOT / "data/research/busan_history_20260915"
TRIAL_DIR = ROOT / "data/research/busan_trial_linkage_20260915"
LEGACY_DIR = ROOT / "data/research/busan_temp_id_linkage_20260915"
HISTORY_DB = HISTORY_DIR / "history.sqlite3"
TRIAL_DB = TRIAL_DIR / "trials.sqlite3"
LEGACY_DB = LEGACY_DIR / "linkage.sqlite3"
DEFAULT_OUTPUT = ROOT / "data/research/busan_complete_db_20260916"


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def copy_base_database(source: Path, destination: Path) -> None:
    source_db = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    destination_db = sqlite3.connect(destination)
    try:
        source_db.backup(destination_db, pages=16384)
    finally:
        destination_db.close()
        source_db.close()


def create_extension_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
      CREATE TABLE trial(
        meet INTEGER NOT NULL CHECK(meet=3),trial_date TEXT NOT NULL,
        trial_no INTEGER NOT NULL,trial_round INTEGER,trial_kind TEXT NOT NULL,
        distance_m INTEGER,distance_provenance TEXT NOT NULL,weather_raw TEXT,
        track_raw TEXT,track_moisture_percent REAL,source_path TEXT NOT NULL,
        label_scope TEXT NOT NULL CHECK(label_scope='trial_only'),
        PRIMARY KEY(meet,trial_date,trial_no));
      CREATE TABLE trial_entry(
        meet INTEGER NOT NULL CHECK(meet=3),trial_date TEXT NOT NULL,
        trial_no INTEGER NOT NULL,chul_no INTEGER NOT NULL,horse_name_raw TEXT NOT NULL,
        origin_raw TEXT,sex_raw TEXT,age_raw INTEGER,jockey_name_raw TEXT,
        trainer_name_raw TEXT,finish_raw TEXT,finish_position INTEGER,
        judgement_raw TEXT,inspection_reason_raw TEXT,body_weight_kg INTEGER,
        finish_time_ms INTEGER,section_json TEXT NOT NULL,hr_no TEXT,
        link_status TEXT NOT NULL,link_method TEXT NOT NULL,
        candidate_hr_nos_json TEXT NOT NULL,link_evidence_json TEXT NOT NULL,
        source_path TEXT NOT NULL,source_line INTEGER NOT NULL,source_line_raw TEXT NOT NULL,
        availability_status TEXT NOT NULL,
        PRIMARY KEY(meet,trial_date,trial_no,chul_no),
        FOREIGN KEY(meet,trial_date,trial_no) REFERENCES trial(meet,trial_date,trial_no));
      CREATE INDEX trial_entry_horse_date ON trial_entry(hr_no,trial_date);
      CREATE TABLE trial_candidate(
        meet INTEGER NOT NULL,trial_date TEXT NOT NULL,trial_no INTEGER NOT NULL,
        chul_no INTEGER NOT NULL,hr_no TEXT NOT NULL,profile_name TEXT,
        profile_sex TEXT,profile_birth TEXT,profile_meet INTEGER,
        age_relation TEXT NOT NULL,sex_relation TEXT NOT NULL,
        training_month_support INTEGER NOT NULL,race_date_support TEXT,
        race_trainer_agrees INTEGER NOT NULL,modern_direct INTEGER NOT NULL,
        official_api_direct INTEGER NOT NULL,
        PRIMARY KEY(meet,trial_date,trial_no,chul_no,hr_no));
      CREATE TABLE trial_api_entry(
        meet INTEGER NOT NULL CHECK(meet=3),trial_date TEXT NOT NULL,
        trial_no INTEGER NOT NULL,chul_no INTEGER NOT NULL,api_meet_raw TEXT NOT NULL,
        hr_no TEXT,horse_name_raw TEXT,jockey_no TEXT,jockey_name_raw TEXT,
        trainer_no TEXT NOT NULL,trainer_name_raw TEXT,pass_flag_raw TEXT,
        reason_raw TEXT,nopass_reason_raw TEXT,raw_json TEXT NOT NULL,
        source_path TEXT NOT NULL,source_row INTEGER NOT NULL,
        PRIMARY KEY(meet,trial_date,trial_no,chul_no));
      CREATE TABLE race_entry_trial_history(
        meet INTEGER NOT NULL CHECK(meet=3),race_date TEXT NOT NULL,
        race_no INTEGER NOT NULL,hr_no TEXT NOT NULL,
        prior_confirmed_trial_count INTEGER NOT NULL,
        prior_confirmed_pass_count INTEGER NOT NULL,
        last_confirmed_trial_date TEXT,last_confirmed_judgement TEXT,
        unresolved_prior_same_name_count INTEGER NOT NULL,
        availability_status TEXT NOT NULL,
        PRIMARY KEY(meet,race_date,race_no,hr_no));
      CREATE TABLE trial_source_file(
        path TEXT PRIMARY KEY,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,
        trial_count INTEGER NOT NULL,entry_count INTEGER NOT NULL,
        filename_header_date_disagrees INTEGER NOT NULL);
      CREATE TABLE trial_input_manifest(
        path TEXT PRIMARY KEY,role TEXT NOT NULL,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL);

      CREATE TABLE legacy_entry_actor_linkage(
        old_entry_id INTEGER NOT NULL,actor_type TEXT NOT NULL,
        temporary_id TEXT NOT NULL,temporary_actor_rowid INTEGER NOT NULL,
        temporary_actor_name TEXT NOT NULL,meet INTEGER NOT NULL CHECK(meet=3),
        race_date TEXT NOT NULL,race_no INTEGER NOT NULL,hr_no TEXT NOT NULL,
        chul_no INTEGER NOT NULL,old_horse_name TEXT NOT NULL,
        official_horse_name TEXT NOT NULL,official_id TEXT NOT NULL,
        official_name TEXT,official_id_raw_json TEXT NOT NULL,
        official_actor_rowid INTEGER,name_agrees INTEGER NOT NULL,
        horse_name_relation TEXT NOT NULL,relationship_status TEXT NOT NULL,
        official_source_path TEXT NOT NULL,official_source_row INTEGER NOT NULL,
        PRIMARY KEY(old_entry_id,actor_type));
      CREATE INDEX legacy_entry_actor_temp
        ON legacy_entry_actor_linkage(actor_type,temporary_id);
      CREATE TABLE legacy_temporary_id_link(
        actor_type TEXT NOT NULL,temporary_id TEXT NOT NULL,
        temporary_actor_rowid INTEGER NOT NULL,temporary_actor_name TEXT NOT NULL,
        observed_official_id TEXT,candidate_count INTEGER NOT NULL,
        evidence_rows INTEGER NOT NULL,name_agree_rows INTEGER NOT NULL,
        name_disagree_rows INTEGER NOT NULL,first_race_date TEXT NOT NULL,
        last_race_date TEXT NOT NULL,identity_status TEXT NOT NULL,
        candidate_ids_json TEXT NOT NULL,PRIMARY KEY(actor_type,temporary_id));
      CREATE TABLE legacy_candidate_evidence(
        actor_type TEXT NOT NULL,temporary_id TEXT NOT NULL,official_id TEXT NOT NULL,
        official_names_json TEXT NOT NULL,evidence_rows INTEGER NOT NULL,
        name_agree_rows INTEGER NOT NULL,first_race_date TEXT NOT NULL,
        last_race_date TEXT NOT NULL,sample_old_entry_id INTEGER NOT NULL,
        sample_source_path TEXT NOT NULL,sample_source_row INTEGER NOT NULL,
        PRIMARY KEY(actor_type,temporary_id,official_id));
      CREATE TABLE legacy_input_manifest(
        path TEXT PRIMARY KEY,role TEXT NOT NULL,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL);

      CREATE TABLE venue_dimension(
        venue_code TEXT PRIMARY KEY,canonical_meet INTEGER NOT NULL UNIQUE,
        region_code TEXT NOT NULL,venue_name_ko TEXT NOT NULL,
        api_request_meet INTEGER NOT NULL,notes TEXT NOT NULL);
      CREATE TABLE unified_event(
        event_id TEXT PRIMARY KEY,event_kind TEXT NOT NULL,
        venue_code TEXT NOT NULL,event_date TEXT NOT NULL,event_no INTEGER NOT NULL,
        label_scope TEXT NOT NULL,source_meet_raw TEXT NOT NULL,
        source_meet_label TEXT,venue_resolution_status TEXT NOT NULL,
        venue_resolution_method TEXT NOT NULL,source_namespace TEXT NOT NULL,
        source_path TEXT NOT NULL,
        UNIQUE(venue_code,event_kind,event_date,event_no),
        FOREIGN KEY(venue_code) REFERENCES venue_dimension(venue_code));
      CREATE INDEX unified_event_date ON unified_event(event_date,event_kind);
      CREATE TABLE unified_event_entry(
        event_id TEXT NOT NULL,participant_no INTEGER NOT NULL,hr_no TEXT,
        horse_name TEXT,jockey_no TEXT,trainer_no TEXT,owner_no TEXT,
        linkage_status TEXT NOT NULL,source_namespace TEXT NOT NULL,
        source_table TEXT NOT NULL,source_pk_json TEXT NOT NULL,
        PRIMARY KEY(event_id,participant_no),
        FOREIGN KEY(event_id) REFERENCES unified_event(event_id));
      CREATE INDEX unified_event_entry_horse ON unified_event_entry(hr_no,event_id);
      CREATE TABLE unified_event_result(
        event_id TEXT NOT NULL,participant_no INTEGER NOT NULL,finish_raw TEXT,
        finish_position INTEGER,result_status TEXT,finish_time_ms INTEGER,
        source_namespace TEXT NOT NULL,source_path TEXT NOT NULL,source_row INTEGER NOT NULL,
        PRIMARY KEY(event_id,participant_no),
        FOREIGN KEY(event_id,participant_no)
          REFERENCES unified_event_entry(event_id,participant_no));

      CREATE TABLE dataset_metadata(
        key TEXT PRIMARY KEY,value_json TEXT NOT NULL,description TEXT NOT NULL);
      CREATE TABLE source_artifact(
        source_group TEXT NOT NULL,path TEXT NOT NULL,role TEXT NOT NULL,
        sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,path_exists INTEGER NOT NULL,
        PRIMARY KEY(source_group,path));
      CREATE TABLE source_request(
        request_id TEXT PRIMARY KEY,source_group TEXT NOT NULL,source_name TEXT,
        status TEXT,scope_json TEXT,page INTEGER,total_count INTEGER,response_rows INTEGER,
        collected_at_utc TEXT,source_retrieved_at_ms INTEGER,
        source_url_without_key TEXT,response_path TEXT,response_sha256 TEXT,
        raw_event_json TEXT NOT NULL,key_redacted INTEGER NOT NULL);
      CREATE TABLE coverage_record(
        coverage_name TEXT NOT NULL,source_row INTEGER NOT NULL,
        dimensions_json TEXT NOT NULL,metrics_json TEXT NOT NULL,source_path TEXT NOT NULL,
        PRIMARY KEY(coverage_name,source_row));
      CREATE TABLE issue_summary(
        issue_type TEXT PRIMARY KEY,row_count INTEGER NOT NULL,
        disposition TEXT NOT NULL,detail TEXT NOT NULL);
    """)


def copy_attached_tables(db: sqlite3.Connection) -> None:
    db.execute(f"ATTACH DATABASE {q(str(TRIAL_DB.resolve()))} AS trial_src")
    db.execute(f"ATTACH DATABASE {q(str(LEGACY_DB.resolve()))} AS legacy_src")
    copies = (
        ("trial", "trial_src", "trial"),
        ("trial_entry", "trial_src", "trial_entry"),
        ("trial_candidate", "trial_src", "candidate"),
        ("trial_api_entry", "trial_src", "official_trial_api_entry"),
        ("race_entry_trial_history", "trial_src", "race_entry_trial_history"),
        ("trial_source_file", "trial_src", "source_file"),
        ("trial_input_manifest", "trial_src", "input_manifest"),
        ("legacy_entry_actor_linkage", "legacy_src", "entry_linkage"),
        ("legacy_temporary_id_link", "legacy_src", "temporary_id_link"),
        ("legacy_candidate_evidence", "legacy_src", "candidate_evidence"),
        ("legacy_input_manifest", "legacy_src", "input_manifest"),
    )
    for destination, source_db, source_table in copies:
        db.execute(f"INSERT INTO {destination} SELECT * FROM {source_db}.{source_table}")
    db.commit()
    db.execute("DETACH DATABASE trial_src")
    db.execute("DETACH DATABASE legacy_src")


def event_id(kind: str, venue: str, day: str, number: int) -> str:
    return f"{kind}:{venue}:{day.replace('-', '')}:{number:02d}"


def populate_unified_tables(db: sqlite3.Connection) -> None:
    db.execute("INSERT INTO venue_dimension VALUES(?,?,?,?,?,?)", (
        "BUSAN", 3, "YEONGNAM", "부산경남", 3,
        "경주 API는 부산경남을 meet=3으로 반환한다. 주행심사 API의 meet=3/영남은 "
        "향후 부산경남과 영천을 합칠 수 있어 venue_resolution_method를 함께 사용한다."))

    races = db.execute("SELECT meet,race_date,race_no,label_scope,source_path FROM race")
    db.executemany("INSERT INTO unified_event VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
        (event_id("RACE", "BUSAN", day, no), "race", "BUSAN", day, no, scope,
         "3", "부산경남", "confirmed",
         "official_race_api_response_meet_label_busan", "busan_history", path)
        for _, day, no, scope, path in races))

    trials = db.execute("SELECT meet,trial_date,trial_no,label_scope,source_path FROM trial")
    trial_events = []
    for _, day, no, scope, path in trials:
        from_text = "/kra_text/dacom23/meet=3/" in path
        trial_events.append((
            event_id("TRIAL", "BUSAN", day, no), "trial", "BUSAN", day, no, scope,
            "3", "영남", "confirmed",
            ("archived_busan_text_exact_event_key" if from_text else
             "historical_2019_api_only_card_before_yeongcheon_split"),
            "busan_trial_linkage", path))
    db.executemany("INSERT INTO unified_event VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", trial_events)

    db.execute("""
      INSERT INTO unified_event_entry
      SELECT 'RACE:BUSAN:'||replace(e.race_date,'-','')||':'||printf('%02d',e.race_no),
        e.chul_no,e.hr_no,e.horse_name,e.jockey_no,e.trainer_no,e.owner_no,
        'confirmed_official_race_result','busan_history','entry',
        json_object('meet',e.meet,'race_date',e.race_date,'race_no',e.race_no,'hr_no',e.hr_no)
      FROM entry e""")
    db.execute("""
      INSERT INTO unified_event_entry
      SELECT 'TRIAL:BUSAN:'||replace(t.trial_date,'-','')||':'||printf('%02d',t.trial_no),
        t.chul_no,t.hr_no,t.horse_name_raw,a.jockey_no,a.trainer_no,NULL,t.link_status,
        'busan_trial_linkage','trial_entry',
        json_object('meet',t.meet,'trial_date',t.trial_date,'trial_no',t.trial_no,'chul_no',t.chul_no)
      FROM trial_entry t LEFT JOIN trial_api_entry a USING(meet,trial_date,trial_no,chul_no)""")
    db.execute("""
      INSERT INTO unified_event_result
      SELECT 'RACE:BUSAN:'||replace(e.race_date,'-','')||':'||printf('%02d',e.race_no),
        e.chul_no,r.finish_raw,r.finish_order,r.result_status,
        CASE WHEN r.race_time_s IS NULL THEN NULL ELSE round(r.race_time_s*1000) END,
        'busan_history',r.source_path,r.source_row
      FROM entry e JOIN result r USING(meet,race_date,race_no,hr_no)""")
    db.execute("""
      INSERT INTO unified_event_result
      SELECT 'TRIAL:BUSAN:'||replace(trial_date,'-','')||':'||printf('%02d',trial_no),
        chul_no,finish_raw,finish_position,judgement_raw,finish_time_ms,
        'busan_trial_linkage',source_path,source_line
      FROM trial_entry""")

    db.executescript("""
      CREATE VIEW analysis_race_entry_history AS
      SELECT r.*,s.prior_api_medical_28d,s.prior_text_medical_28d,
        t.prior_confirmed_trial_count,t.prior_confirmed_pass_count,
        t.last_confirmed_trial_date,t.last_confirmed_judgement,
        t.unresolved_prior_same_name_count,
        CASE WHEN r.availability_status='retrospective_only'
               OR s.availability_status='retrospective_only'
               OR t.availability_status='retrospective_only'
             THEN 'retrospective_only' ELSE 'availability_unverified' END
          AS combined_availability_status
      FROM research_entry r
      JOIN research_source_features s USING(meet,race_date,race_no,hr_no)
      LEFT JOIN race_entry_trial_history t USING(meet,race_date,race_no,hr_no);

      CREATE VIEW analysis_trial_entry AS
      SELECT t.*,a.jockey_no,a.trainer_no,a.api_meet_raw,a.horse_name_raw AS api_horse_name_raw
      FROM trial_entry t LEFT JOIN trial_api_entry a
        USING(meet,trial_date,trial_no,chul_no)
      WHERE t.link_status='confirmed';

      CREATE VIEW analysis_unified_event_entry AS
      SELECT ev.event_kind,ev.venue_code,ev.event_date,ev.event_no,ev.label_scope,
        en.participant_no,en.hr_no,en.horse_name,en.jockey_no,en.trainer_no,en.owner_no,
        en.linkage_status,re.finish_raw,re.finish_position,re.result_status,
        re.finish_time_ms,ev.venue_resolution_status,ev.venue_resolution_method
      FROM unified_event ev JOIN unified_event_entry en USING(event_id)
      LEFT JOIN unified_event_result re USING(event_id,participant_no);

      CREATE VIEW quarantined_trial_entry AS
        SELECT * FROM trial_entry WHERE link_status!='confirmed';
      CREATE VIEW quarantined_medical_text AS
        SELECT * FROM medical_event WHERE link_status!='confirmed';
      CREATE VIEW quarantined_race_notice AS
        SELECT * FROM race_notice_text WHERE link_status!='confirmed';
      CREATE VIEW quarantined_race_day_weight AS
        SELECT * FROM race_day_weight WHERE link_status!='confirmed';
      CREATE VIEW quarantined_legacy_identity AS
        SELECT * FROM legacy_temporary_id_link
        WHERE identity_status NOT IN ('single_candidate_name_agrees');
    """)


def insert_metadata(db: sqlite3.Connection) -> None:
    generated = datetime.now(timezone.utc).isoformat()
    values = {
        "dataset_name": "Busan complete historical research database",
        "dataset_version": "2026-09-16",
        "generated_at_utc": generated,
        "canonical_venue_code": "BUSAN",
        "canonical_meet": 3,
        "regional_api_meet_note": (
            "Running-trial API meet=3 is raw region YEONGNAM and may combine Busan and "
            "Yeongcheon after Yeongcheon begins; canonical venue is separately resolved."),
        "target_scope": "official races from 2006 onward",
        "warmup_scope": "official races from 2005-09-30 through 2005-12-23",
        "availability_policy": "retrospective_only unless separately proven",
        "operating_database_modified": False,
        "legacy_trial_result_text_policy": (
            "trial_result_text has 5,413 early-parser rows and is provenance-only; use trial_entry."),
    }
    db.executemany("INSERT INTO dataset_metadata VALUES(?,?,?)", (
        (key, json.dumps(value, ensure_ascii=False), "integration metadata")
        for key, value in values.items()))


def add_artifact(db: sqlite3.Connection, group: str, path_text: str, role: str,
                 expected_hash: str, expected_bytes: int) -> None:
    path = Path(path_text)
    if not path.is_absolute():
        path = ROOT / path
    exists = path.is_file()
    db.execute("INSERT OR REPLACE INTO source_artifact VALUES(?,?,?,?,?,?)",
               (group, path_text, role, expected_hash, expected_bytes, int(exists)))


def load_artifacts(db: sqlite3.Connection) -> None:
    with (HISTORY_DIR / "sha256_manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            add_artifact(db, "busan_history", row["path"], row["role"],
                         row["sha256"], int(row["bytes"]))
    for path, role, expected, size in db.execute(
            "SELECT path,role,sha256,bytes FROM trial_input_manifest").fetchall():
        add_artifact(db, "busan_trial_linkage", path, role, expected, size)
    for path, expected, size in db.execute(
            "SELECT path,sha256,bytes FROM trial_source_file").fetchall():
        add_artifact(db, "busan_trial_text", path, "trial_text_source", expected, size)
    for path, role, expected, size in db.execute(
            "SELECT path,role,sha256,bytes FROM legacy_input_manifest").fetchall():
        add_artifact(db, "busan_legacy_id_linkage", path, role, expected, size)
    for group, path in (("input_snapshot", HISTORY_DB), ("input_snapshot", TRIAL_DB),
                        ("input_snapshot", LEGACY_DB),
                        ("build_code", Path(__file__)),
                        ("build_code", ROOT / "scripts/verify_busan_complete_db.py")):
        if path.is_file():
            add_artifact(db, group, str(path), "integration_input", sha256(path), path.stat().st_size)


def load_requests(db: sqlite3.Connection) -> None:
    ledgers = (
        ("race_result_api", HISTORY_DIR / "request_ledger.jsonl"),
        ("medical_api", HISTORY_DIR / "medical_request_ledger.jsonl"),
        ("trial_api", TRIAL_DIR / "api_raw/request_ledger.jsonl"),
        ("trial_api_catalog", TRIAL_DIR / "api_raw/catalog_request_ledger.jsonl"),
    )
    for group, path in ledgers:
        if not path.is_file():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            event = json.loads(line)
            serialized = json.dumps(event, ensure_ascii=False, sort_keys=True)
            lower = serialized.lower()
            redacted = "servicekey=" not in lower and "service_key=" not in lower
            if not redacted:
                raise ValueError(f"Authenticated URL found in request ledger: {path}:{line_no}")
            request_id = hashlib.sha256(
                f"{group}:{path}:{line_no}:{serialized}".encode()).hexdigest()
            scope = event.get("scope")
            db.execute("INSERT INTO source_request VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                request_id, group, event.get("source"), event.get("status"),
                json.dumps(scope, ensure_ascii=False, sort_keys=True) if scope is not None else None,
                event.get("page"), event.get("total_count"), event.get("response_rows"),
                event.get("collected_at_utc"), event.get("source_retrieved_at_ms"),
                event.get("source_url_without_key"), event.get("path") or event.get("response_path"),
                event.get("sha256") or event.get("response_sha256"), serialized, int(redacted)))


def load_coverage(db: sqlite3.Connection) -> None:
    inputs = (
        ("race_year_source", HISTORY_DIR / "coverage_year_source.csv"),
        ("event_coverage", HISTORY_DIR / "event_coverage.csv"),
        ("source_link_coverage", HISTORY_DIR / "source_link_coverage.csv"),
        ("race_year_quality", HISTORY_DIR / "year_quality.csv"),
        ("race_regime_year", HISTORY_DIR / "race_regime_year.csv"),
        ("trial_year", TRIAL_DIR / "coverage_year.csv"),
    )
    for name, path in inputs:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row_no, row in enumerate(csv.DictReader(stream), 1):
                dimensions = {key: value for key, value in row.items()
                              if key in {"year", "source", "source_type"}}
                metrics = {key: value for key, value in row.items() if key not in dimensions}
                db.execute("INSERT INTO coverage_record VALUES(?,?,?,?,?)", (
                    name, row_no, json.dumps(dimensions, ensure_ascii=False, sort_keys=True),
                    json.dumps(metrics, ensure_ascii=False, sort_keys=True), str(path)))


def populate_issue_summary(db: sqlite3.Connection) -> None:
    issues = (
        ("trial_identity_unresolved",
         "SELECT count(*) FROM trial_entry WHERE link_status!='confirmed'",
         "quarantined", "Official trial API lacks a usable hrNo for these rows."),
        ("medical_text_not_confirmed",
         "SELECT count(*) FROM medical_event WHERE link_status!='confirmed'",
         "quarantined", "Name/stable/date evidence does not uniquely establish a horse."),
        ("race_notice_not_confirmed",
         "SELECT count(*) FROM race_notice_text WHERE link_status!='confirmed'",
         "quarantined", "Notice does not uniquely agree with an official entry."),
        ("race_day_weight_not_confirmed",
         "SELECT count(*) FROM race_day_weight WHERE link_status!='confirmed'",
         "quarantined", "Text weight row is not linked to an official entry."),
        ("legacy_identity_not_globally_resolved",
         "SELECT count(*) FROM legacy_temporary_id_link WHERE identity_status!='single_candidate_name_agrees'",
         "relationship_only", "Race-time official relationship is retained; global person merge is withheld."),
        ("race_entry_missing_trainer_id",
         "SELECT count(*) FROM entry WHERE trainer_no IS NULL OR trainer_no=''",
         "source_missing", "Official race-result source has no trainer ID."),
        ("race_entry_missing_owner_id",
         "SELECT count(*) FROM entry WHERE owner_no IS NULL OR owner_no=''",
         "source_missing", "Official race-result source has no owner ID."),
    )
    for issue_type, sql, disposition, detail in issues:
        count = db.execute(sql).fetchone()[0]
        db.execute("INSERT INTO issue_summary VALUES(?,?,?,?)",
                   (issue_type, count, disposition, detail))


def export_catalog(db_path: Path, output_dir: Path) -> None:
    db = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    objects = []
    for obj_type, name, sql in db.execute("""
      SELECT type,name,sql FROM sqlite_master
      WHERE name NOT LIKE 'sqlite_%' AND type IN ('table','view')
      ORDER BY type,name"""):
        columns = [dict(zip(("cid", "name", "type", "notnull", "default", "pk"), row))
                   for row in db.execute(f"PRAGMA table_info({json.dumps(name)})")]
        row_count = db.execute(f"SELECT count(*) FROM {json.dumps(name)}").fetchone()[0]
        objects.append({"type": obj_type, "name": name, "row_count": row_count,
                        "columns": columns, "sql": sql})
    db.close()
    (output_dir / "catalog.json").write_text(json.dumps({
        "database": str(db_path), "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "objects": objects,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def build(output_dir: Path, force: bool) -> Path:
    for path in (HISTORY_DB, TRIAL_DB, LEGACY_DB):
        if not path.is_file():
            raise FileNotFoundError(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    final = output_dir / "busan_complete.sqlite3"
    temp = output_dir / ".busan_complete.sqlite3.tmp"
    if final.exists() and not force:
        raise FileExistsError(f"Output exists; pass --force to replace: {final}")
    if temp.exists():
        temp.unlink()
    copy_base_database(HISTORY_DB, temp)
    db = sqlite3.connect(temp)
    try:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("BEGIN")
        create_extension_schema(db)
        db.commit()
        copy_attached_tables(db)
        db.execute("BEGIN")
        populate_unified_tables(db)
        insert_metadata(db)
        load_artifacts(db)
        load_requests(db)
        load_coverage(db)
        populate_issue_summary(db)
        db.commit()
        db.execute("PRAGMA foreign_keys=ON")
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise ValueError(f"Foreign-key violations: {violations[:5]}")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity_check failed")
        db.execute("PRAGMA optimize")
    finally:
        db.close()
    os.replace(temp, final)
    export_catalog(final, output_dir)
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = build(args.output_dir, args.force)
    print(result)
