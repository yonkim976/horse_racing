"""Build an isolated Jeju-native race/trial analysis SQLite database.

The operational database and archived sources are read-only. Official source
checkpoints and derived consecutive sections are stored separately so that an
approximate corner location is never mistaken for an observed exact distance.
"""

from __future__ import annotations

import collections
import glob
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/jeju_native_analysis_db_20260915"
DB = OUT / "jeju_native_analysis.sqlite3"
TMP = OUT / "jeju_native_analysis.sqlite3.tmp"
RACE_LINKS = ROOT / "data/research/jeju_confirmed_race_time_ids_20260914"
RACE_SOURCE = ROOT / "data/research/jeju_race_time_official_ids_20260914"
TRIAL_SOURCE = ROOT / "data/research/jeju_native_running_trial_links_20260915"
READINESS = ROOT / "data/research/jeju_native_200m_readiness_20260915"

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE metadata (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL
);
CREATE TABLE source_artifact (
  id INTEGER PRIMARY KEY,
  source_kind TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL,
  row_count INTEGER
);
CREATE TABLE source_request (
  id INTEGER PRIMARY KEY,
  request_kind TEXT NOT NULL,
  event_date TEXT,
  event_number INTEGER,
  request_json TEXT,
  request_sha256 TEXT,
  response_sha256 TEXT,
  http_status INTEGER,
  response_bytes INTEGER,
  UNIQUE(request_kind, event_date, event_number, request_sha256, response_sha256)
);
CREATE TABLE event (
  id INTEGER PRIMARY KEY,
  event_type TEXT NOT NULL CHECK(event_type IN ('race','trial')),
  meet INTEGER NOT NULL CHECK(meet=2),
  event_date TEXT NOT NULL,
  event_number INTEGER NOT NULL,
  trial_round INTEGER,
  distance_m INTEGER,
  grade TEXT,
  event_name TEXT,
  weather TEXT,
  track_condition TEXT,
  track_moisture_percent REAL,
  population_status TEXT NOT NULL,
  UNIQUE(event_type, meet, event_date, event_number)
);
CREATE TABLE source_row (
  id INTEGER PRIMARY KEY,
  source_artifact_id INTEGER NOT NULL REFERENCES source_artifact(id),
  line_number INTEGER,
  row_sha256 TEXT NOT NULL,
  normalized_json TEXT NOT NULL,
  UNIQUE(source_artifact_id, line_number, row_sha256)
);
CREATE TABLE entry (
  id INTEGER PRIMARY KEY,
  event_id INTEGER NOT NULL REFERENCES event(id),
  horse_number INTEGER NOT NULL,
  horse_name TEXT,
  hr_no TEXT,
  tr_no TEXT,
  ow_no TEXT,
  breed_status TEXT NOT NULL,
  breed_evidence TEXT,
  identity_status TEXT NOT NULL,
  record_status TEXT NOT NULL,
  finish_position INTEGER,
  finish_time_ms INTEGER,
  segment_quality TEXT NOT NULL,
  time_analysis_eligible INTEGER NOT NULL CHECK(time_analysis_eligible IN (0,1)),
  official_evidence_json TEXT,
  source_row_id INTEGER NOT NULL REFERENCES source_row(id),
  UNIQUE(event_id, horse_number)
);
CREATE TABLE section_checkpoint (
  id INTEGER PRIMARY KEY,
  entry_id INTEGER NOT NULL REFERENCES entry(id),
  section_code TEXT NOT NULL,
  source_value_ms INTEGER NOT NULL,
  elapsed_from_start_ms INTEGER NOT NULL,
  time_basis TEXT NOT NULL CHECK(time_basis IN ('cumulative','closing')),
  distance_from_start_m INTEGER NOT NULL,
  distance_is_approximate INTEGER NOT NULL CHECK(distance_is_approximate IN (0,1)),
  source_kind TEXT NOT NULL,
  source_response_sha256 TEXT,
  UNIQUE(entry_id, section_code, source_kind)
);
CREATE TABLE derived_segment (
  id INTEGER PRIMARY KEY,
  entry_id INTEGER NOT NULL REFERENCES entry(id),
  segment_sequence INTEGER NOT NULL,
  from_codes TEXT NOT NULL,
  to_codes TEXT NOT NULL,
  start_distance_m INTEGER NOT NULL,
  end_distance_m INTEGER NOT NULL,
  distance_m INTEGER NOT NULL,
  distance_is_approximate INTEGER NOT NULL CHECK(distance_is_approximate IN (0,1)),
  elapsed_ms INTEGER NOT NULL CHECK(elapsed_ms>0),
  derivation TEXT NOT NULL,
  UNIQUE(entry_id, segment_sequence)
);
CREATE TABLE resolution_issue (
  id INTEGER PRIMARY KEY,
  entry_id INTEGER REFERENCES entry(id),
  event_type TEXT NOT NULL,
  event_date TEXT NOT NULL,
  event_number INTEGER NOT NULL,
  horse_number INTEGER,
  issue_code TEXT NOT NULL,
  details_json TEXT NOT NULL
);
CREATE TABLE exclusion_summary (
  id INTEGER PRIMARY KEY,
  source_code TEXT NOT NULL UNIQUE,
  row_count INTEGER NOT NULL,
  exclusion_status TEXT NOT NULL,
  evidence_json TEXT NOT NULL
);
CREATE TABLE coverage (
  id INTEGER PRIMARY KEY,
  event_type TEXT NOT NULL,
  dimension TEXT NOT NULL,
  dimension_value TEXT NOT NULL,
  total_rows INTEGER NOT NULL,
  positive_finish_rows INTEGER NOT NULL,
  usable_segment_rows INTEGER NOT NULL,
  missing_segment_rows INTEGER NOT NULL,
  inconsistent_segment_rows INTEGER NOT NULL,
  UNIQUE(event_type, dimension, dimension_value)
);
CREATE INDEX ix_event_date ON event(event_type, event_date, event_number);
CREATE INDEX ix_entry_hr_no ON entry(hr_no, event_id);
CREATE INDEX ix_entry_quality ON entry(segment_quality, time_analysis_eligible);
CREATE INDEX ix_checkpoint_entry ON section_checkpoint(entry_id, distance_from_start_m);
CREATE INDEX ix_segment_entry ON derived_segment(entry_id, segment_sequence);
CREATE INDEX ix_issue_code ON resolution_issue(issue_code);
CREATE VIEW analysis_race_segments AS
SELECT v.event_date,v.event_number,v.distance_m,e.horse_number,e.horse_name,
       e.hr_no,e.tr_no,e.ow_no,e.finish_position,e.finish_time_ms,
       s.segment_sequence,s.from_codes,s.to_codes,s.start_distance_m,
       s.end_distance_m,s.distance_m AS segment_distance_m,
       s.distance_is_approximate,s.elapsed_ms,s.derivation
FROM derived_segment s JOIN entry e ON e.id=s.entry_id JOIN event v ON v.id=e.event_id
WHERE v.event_type='race' AND e.segment_quality='usable'
  AND e.identity_status='official_race_ids_linked';
CREATE VIEW analysis_trial_segments AS
SELECT v.event_date,v.event_number,v.trial_round,v.distance_m,e.horse_number,
       e.horse_name,e.hr_no,e.tr_no,e.finish_position,e.finish_time_ms,
       s.segment_sequence,s.from_codes,s.to_codes,s.start_distance_m,
       s.end_distance_m,s.distance_m AS segment_distance_m,
       s.distance_is_approximate,s.elapsed_ms,s.derivation
FROM derived_segment s JOIN entry e ON e.id=s.entry_id JOIN event v ON v.id=e.event_id
WHERE v.event_type='trial' AND e.segment_quality='usable'
  AND e.identity_status='official_trial_hr_tr_linked';
CREATE VIEW quarantined_entries AS
SELECT v.event_type,v.event_date,v.event_number,v.distance_m,e.*
FROM entry e JOIN event v ON v.id=e.event_id
WHERE e.segment_quality!='usable'
   OR e.identity_status IN ('official_race_id_unresolved','official_trial_identity_unresolved')
   OR v.population_status='explicit_je_no_positive_result';
"""


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def positive_ms(value: Any, *, seconds: bool = False) -> int | None:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return round(number * 1000) if seconds else round(number)


def official_id(value: Any, width: int) -> str | None:
    text = str(value or "").strip()
    if not text or not text.isdigit():
        return None
    return text.zfill(width)


def artifact(conn: sqlite3.Connection, cache: dict[str, int], path: Path, kind: str, rows: int | None = None) -> int:
    relative = str(path.relative_to(ROOT))
    if relative in cache:
        return cache[relative]
    cursor = conn.execute(
        "INSERT INTO source_artifact(source_kind,path,sha256,row_count) VALUES (?,?,?,?)",
        (kind, relative, file_sha(path), rows),
    )
    cache[relative] = int(cursor.lastrowid)
    return cache[relative]


def source_row(conn: sqlite3.Connection, artifact_id: int, line_number: int | None, payload: dict) -> int:
    raw = compact(payload)
    cursor = conn.execute(
        "INSERT INTO source_row(source_artifact_id,line_number,row_sha256,normalized_json) VALUES (?,?,?,?)",
        (artifact_id, line_number, sha_bytes(raw.encode()), raw),
    )
    return int(cursor.lastrowid)


def checkpoint_rows(values: dict[str, int | None], distance: int, source_kind: str, response_sha: str | None) -> list[dict]:
    finish = values.get("FIN")
    early = 210 if distance in (1110, 1610) else 200
    positions = {
        "S1F": (early, False), "1C": (distance-1400, True),
        "2C": (distance-1200, True), "3C": (distance-600, True),
        "G3F": (distance-600, False), "4C": (distance-400, True),
        "G1F": (distance-200, False), "FIN": (distance, False),
    }
    result = []
    for code, source_value in values.items():
        if source_value is None or code not in positions:
            continue
        point, approximate = positions[code]
        if not 0 < point <= distance:
            continue
        basis = "closing" if code in {"G3F", "G1F"} else "cumulative"
        elapsed = finish-source_value if basis == "closing" and finish is not None else source_value
        if elapsed is None or elapsed <= 0:
            continue
        result.append({"code": code, "source_value": source_value, "elapsed": elapsed,
                       "basis": basis, "point": point, "approximate": approximate,
                       "source_kind": source_kind, "response_sha": response_sha})
    return result


def derive(checkpoints: list[dict], distance: int, positive_finish: bool) -> tuple[str, list[dict]]:
    if not positive_finish:
        return "not_applicable", []
    by_code = {row["code"]: row for row in checkpoints}
    if distance == 400:
        required = {"S1F", "G1F", "FIN"}
    else:
        required = {"S1F", "3C", "G3F", "4C", "G1F", "FIN"}
    if not required.issubset(by_code):
        return "missing", []
    grouped: dict[int, list[dict]] = collections.defaultdict(list)
    for row in checkpoints:
        grouped[row["point"]].append(row)
    points = [(0, [{"code": "START", "elapsed": 0, "approximate": False}])]
    for point, rows in sorted(grouped.items()):
        if max(r["elapsed"] for r in rows)-min(r["elapsed"] for r in rows) > 200:
            return "inconsistent", []
        points.append((point, rows))
    if points[-1][0] != distance or not any(r["code"] == "FIN" for r in points[-1][1]):
        return "missing", []
    priority = {code: index for index, code in enumerate(("S1F","1C","2C","3C","G3F","4C","G1F","FIN"))}
    selected = []
    for point, rows in points:
        pick = min(rows, key=lambda r: priority.get(r["code"], 99))
        selected.append((point, rows, pick["elapsed"]))
    segments = []
    for seq, ((start, left_rows, left_time), (end, right_rows, right_time)) in enumerate(zip(selected, selected[1:]), 1):
        if end <= start or right_time <= left_time:
            return "inconsistent", []
        segments.append({
            "seq": seq,
            "from_codes": "/".join(r["code"] for r in sorted(left_rows, key=lambda x: priority.get(x["code"],99))),
            "to_codes": "/".join(r["code"] for r in sorted(right_rows, key=lambda x: priority.get(x["code"],99))),
            "start": start, "end": end, "distance": end-start,
            "approximate": any(r.get("approximate") for r in left_rows+right_rows),
            "elapsed": right_time-left_time,
        })
    return "usable", segments


def insert_requests(conn: sqlite3.Connection) -> None:
    race = json.loads((RACE_SOURCE / "source_requests_and_hashes.json").read_text())
    for group in (race["old_sources"], race["new_api_requests"]):
        for item in group:
            for page in item["source_pages"]:
                conn.execute(
                    "INSERT OR IGNORE INTO source_request(request_kind,event_date,request_json,response_sha256,http_status,response_bytes) VALUES (?,?,?,?,?,?)",
                    ("race_result_api_year", str(item["year"]), compact({"url": page["source_url_without_key"]}), page["sha256"], page.get("status_code"), page.get("response_bytes")),
                )
    for row in map(json.loads, (TRIAL_SOURCE / "official_request_manifest.jsonl").open()):
        conn.execute(
            "INSERT OR IGNORE INTO source_request(request_kind,event_date,event_number,request_json,request_sha256,response_sha256,http_status,response_bytes) VALUES (?,?,?,?,?,?,?,?)",
            ("trial_official_identity", row["date"], row["race_number"], compact({"method":row.get("method"),"url":row.get("url"),"form":row.get("form")}), row.get("request_sha256"), row.get("response_sha256"), row.get("http_status"), row.get("response_bytes")),
        )
    for row in map(json.loads, (TRIAL_SOURCE / "older_trial_section_audit_cache.jsonl").open()):
        conn.execute(
            "INSERT OR IGNORE INTO source_request(request_kind,event_date,event_number,request_json,request_sha256,response_sha256,http_status,response_bytes) VALUES (?,?,?,?,?,?,?,?)",
            ("trial_official_sections", row["date"], row["race_number"], compact({"method":row.get("method"),"url":row.get("url"),"form":row.get("form")}), row.get("request_sha256"), row.get("response_sha256"), row.get("http_status"), row.get("response_bytes")),
        )
    for row in map(json.loads, (TRIAL_SOURCE / "profile_request_manifest.jsonl").open()):
        conn.execute(
            "INSERT OR IGNORE INTO source_request(request_kind,request_json,request_sha256,response_sha256,http_status,response_bytes) VALUES (?,?,?,?,?,?)",
            ("trial_breed_profile",compact({"method":row.get("method"),"url":row.get("url"),"meet":row.get("meet"),"hrNo":row.get("hrNo")}),row.get("request_sha256"),row.get("response_sha256"),row.get("http_status"),row.get("response_bytes")),
        )
    inspection=json.loads((READINESS/"inspection_exclusion_audit.json").read_text())
    for row in inspection["official_request_hashes"]:
        conn.execute(
            "INSERT OR IGNORE INTO source_request(request_kind,event_date,event_number,request_sha256,response_sha256) VALUES (?,?,?,?,?)",
            ("trial_inspection_exclusion_page",row["date"],row["race_number"],row.get("request_sha256"),row.get("response_sha256")),
        )
    for row in inspection["profile_request_hashes"]:
        conn.execute(
            "INSERT OR IGNORE INTO source_request(request_kind,request_sha256,response_sha256,request_json) VALUES (?,?,?,?)",
            ("trial_inspection_exclusion_profile",row.get("request_sha256"),row.get("response_sha256"),compact({"breed":row.get("breed")})),
        )
    geometry=json.loads((READINESS/"checkpoint_geometry_source.json").read_text())
    conn.execute(
        "INSERT INTO source_request(request_kind,request_json,response_sha256) VALUES (?,?,?)",
        ("official_checkpoint_definition",compact({"url":geometry["source_url"],"retrieved_date":geometry["retrieved_date"]}),geometry["response_sha256"]),
    )


def register_control_artifacts(conn: sqlite3.Connection, artifacts: dict[str,int]) -> None:
    paths=(
        RACE_LINKS/"linked_official_ids.jsonl",RACE_LINKS/"unresolved_29.jsonl",
        RACE_SOURCE/"source_requests_and_hashes.json",
        TRIAL_SOURCE/"linked_native_trials_final.jsonl",TRIAL_SOURCE/"unresolved_trials_final.jsonl",
        TRIAL_SOURCE/"older_trial_section_audit_native_only.jsonl",
        TRIAL_SOURCE/"official_request_manifest.jsonl",TRIAL_SOURCE/"profile_request_manifest.jsonl",
        READINESS/"inspection_exclusion_audit.json",READINESS/"checkpoint_geometry_source.json",
    )
    for path in paths:
        artifact(conn,artifacts,path,"control_ledger_or_manifest",None)


def insert_event(conn: sqlite3.Connection, cache: dict[tuple, int], key: tuple, values: tuple) -> int:
    if key in cache:
        return cache[key]
    cursor = conn.execute(
        "INSERT INTO event(event_type,meet,event_date,event_number,trial_round,distance_m,grade,event_name,weather,track_condition,track_moisture_percent,population_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        values,
    )
    cache[key] = int(cursor.lastrowid)
    return cache[key]


def insert_checkpoints_and_segments(conn: sqlite3.Connection, entry_id: int, checkpoints: list[dict], segments: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO section_checkpoint(entry_id,section_code,source_value_ms,elapsed_from_start_ms,time_basis,distance_from_start_m,distance_is_approximate,source_kind,source_response_sha256) VALUES (?,?,?,?,?,?,?,?,?)",
        [(entry_id,r["code"],r["source_value"],r["elapsed"],r["basis"],r["point"],int(r["approximate"]),r["source_kind"],r["response_sha"]) for r in checkpoints],
    )
    conn.executemany(
        "INSERT INTO derived_segment(entry_id,segment_sequence,from_codes,to_codes,start_distance_m,end_distance_m,distance_m,distance_is_approximate,elapsed_ms,derivation) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(entry_id,s["seq"],s["from_codes"],s["to_codes"],s["start"],s["end"],s["distance"],int(s["approximate"]),s["elapsed"],"difference_of_normalized_official_checkpoints") for s in segments],
    )


def build_races(conn: sqlite3.Connection, artifacts: dict[str, int], events: dict[tuple, int]) -> None:
    linked = {(r["race_date"],r["race_number"],r["horse_number"]):r for r in map(json.loads,(RACE_LINKS/"linked_official_ids.jsonl").open())}
    unresolved = {(r["race_date"],r["race_number"],r["horse_number"]):r for r in map(json.loads,(RACE_LINKS/"unresolved_29.jsonl").open())}
    confirmed_races = {(d,n) for d,n,_ in linked} | {(d,n) for d,n,_ in unresolved}
    paths = sorted(Path(x) for x in glob.glob(str(ROOT/"data/raw/jeju_native_results/native_results_*.jsonl")) + glob.glob(str(RACE_SOURCE/"official_native_results_*.jsonl")))
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        art_id = artifact(conn, artifacts, path, "race_result_native_filtered_jsonl", len(lines))
        for line_no, line in enumerate(lines, 1):
            row = json.loads(line)
            date, number, horse_number = str(row["rcDate"]), int(row["rcNo"]), int(row["chulNo"])
            key = (date, number, horse_number)
            race_key = (date, number)
            normal_race = race_key in confirmed_races
            event_id = insert_event(conn, events, ("race",date,number), (
                "race",2,date,number,None,int(row["rcDist"]),str(row.get("rank") or ""),row.get("rcName"),row.get("weather"),row.get("track"),None,
                "confirmed_native_normal_race" if normal_race else "explicit_je_no_positive_result",
            ))
            link = linked.get(key) or unresolved.get(key)
            if normal_race and link is None:
                raise RuntimeError(f"normal race row lacks identity ledger: {key}")
            if key in linked:
                identity = "official_race_ids_linked"
                hr_no, tr_no, ow_no = link["hrNo"], link["trNo"], link["owNo"]
            elif key in unresolved:
                identity = "official_race_id_unresolved"
                hr_no, tr_no, ow_no = link.get("hrNo"), link.get("trNo"), link.get("owNo")
            else:
                identity = "official_source_ids_unvalidated_quarantine"
                hr_no, tr_no, ow_no = official_id(row.get("hrNo"),7), official_id(row.get("trNo"),6), official_id(row.get("owNo"),6)
            finish = positive_ms(row.get("rcTime"), seconds=True)
            values = {"S1F":positive_ms(row.get("jeS1fTime"),seconds=True),"1C":positive_ms(row.get("je_1cTime"),seconds=True),"2C":positive_ms(row.get("je_2cTime"),seconds=True),"3C":positive_ms(row.get("je_3cTime"),seconds=True),"G3F":positive_ms(row.get("jeG3fTime"),seconds=True),"4C":positive_ms(row.get("je_4cTime"),seconds=True),"G1F":positive_ms(row.get("jeG1fTime"),seconds=True),"FIN":finish}
            response_sha = next(iter((link or {}).get("official_result_evidence",{}).get("original_response_sha256",[])),None)
            checkpoints = checkpoint_rows(values,int(row["rcDist"]),"race_result",response_sha)
            quality, segments = derive(checkpoints,int(row["rcDist"]),bool(finish and normal_race))
            if not normal_race:
                quality, segments = "not_applicable", []
            record_status = "quarantined_no_positive_result_race" if not normal_race else "normal_completed" if finish else "non_positive_result_entry"
            source_id = source_row(conn,art_id,line_no,row)
            cursor = conn.execute(
                "INSERT INTO entry(event_id,horse_number,horse_name,hr_no,tr_no,ow_no,breed_status,breed_evidence,identity_status,record_status,finish_position,finish_time_ms,segment_quality,time_analysis_eligible,official_evidence_json,source_row_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (event_id,horse_number,row.get("hrName"),hr_no,tr_no,ow_no,"native_confirmed","official_result_rank_explicit_je",identity,record_status,int(row["ord"]) if str(row.get("ord") or "").isdigit() else None,finish,quality,int(quality=="usable"),compact((link or {}).get("official_result_evidence")),source_id),
            )
            entry_id=int(cursor.lastrowid)
            insert_checkpoints_and_segments(conn,entry_id,checkpoints,segments)
            if key in unresolved:
                for issue in unresolved[key]["issues"]:
                    conn.execute("INSERT INTO resolution_issue(entry_id,event_type,event_date,event_number,horse_number,issue_code,details_json) VALUES (?,?,?,?,?,?,?)",(entry_id,"race",date,number,horse_number,issue,compact(unresolved[key])))
            if not normal_race:
                conn.execute("INSERT INTO resolution_issue(entry_id,event_type,event_date,event_number,horse_number,issue_code,details_json) VALUES (?,?,?,?,?,?,?)",(entry_id,"race",date,number,horse_number,"no_positive_result_race",compact({"rank":row.get("rank"),"finish_time_ms":finish})))
            elif quality in {"missing","inconsistent"}:
                conn.execute("INSERT INTO resolution_issue(entry_id,event_type,event_date,event_number,horse_number,issue_code,details_json) VALUES (?,?,?,?,?,?,?)",(entry_id,"race",date,number,horse_number,"segment_"+quality,compact({"distance_m":row["rcDist"],"finish_time_ms":finish,"source_path":str(path.relative_to(ROOT)),"source_line":line_no})))


def build_trials(conn: sqlite3.Connection, artifacts: dict[str, int], events: dict[tuple, int]) -> None:
    linked_rows=list(map(json.loads,(TRIAL_SOURCE/"linked_native_trials_final.jsonl").open()))
    unresolved_rows=list(map(json.loads,(TRIAL_SOURCE/"unresolved_trials_final.jsonl").open()))
    supplement={(r["trial_date"],r["trial_race_number"],r["horse_number"]):r for r in map(json.loads,(TRIAL_SOURCE/"older_trial_section_audit_native_only.jsonl").open())}
    for row, linked in [(r,True) for r in linked_rows]+[(r,False) for r in unresolved_rows]:
        date,number,horse_number=row["trial_date"],int(row["trial_race_number"]),int(row["horse_number"])
        key=(date,number,horse_number)
        result=row["trial_result"]
        path=ROOT/row["text_source"]
        art_id=artifact(conn,artifacts,path,"trial_archived_text_report",None)
        event_id=insert_event(conn,events,("trial",date,number),(
            "trial",2,date,number,row.get("trial_round"),int(row["distance_m"]),None,None,row.get("weather"),row.get("track_condition"),row.get("track_moisture_percent"),
            "native_confirmed_trial" if linked else "native_candidate_identity_unresolved",
        ))
        source_id=source_row(conn,art_id,None,{"trial_key":[date,number,horse_number],"trial_result":result})
        extra=supplement.get(key)
        selected=extra["section"] if extra and extra["status"]=="four_corner_proxy_segments_consistent" else result
        finish=positive_ms(selected.get("finish_time_ms")) or positive_ms(result.get("finish_time_ms"))
        values={"S1F":positive_ms(selected.get("s1f_ms")),"3C":positive_ms(selected.get("corner_3_ms")),"G3F":positive_ms(selected.get("g3f_ms")),"4C":positive_ms(selected.get("corner_4_ms")),"G1F":positive_ms(selected.get("g1f_ms")),"FIN":finish}
        source_kind="trial_official_web_supplement" if selected is not result else "trial_archived_text"
        response_sha=extra.get("official_response_sha256") if selected is not result else row.get("official_response_sha256")
        checkpoints=checkpoint_rows(values,int(row["distance_m"]),source_kind,response_sha)
        quality,segments=derive(checkpoints,int(row["distance_m"]),bool(finish and linked))
        if not linked: quality,segments="identity_unresolved",[]
        identity="official_trial_hr_tr_linked" if linked else "official_trial_identity_unresolved"
        breed_status="native_confirmed" if linked or row.get("text_breed")=="제" else "native_candidate_breed_unconfirmed"
        cursor=conn.execute(
            "INSERT INTO entry(event_id,horse_number,horse_name,hr_no,tr_no,ow_no,breed_status,breed_evidence,identity_status,record_status,finish_position,finish_time_ms,segment_quality,time_analysis_eligible,official_evidence_json,source_row_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id,horse_number,row.get("horse_name"),row.get("hrNo") if linked else None,row.get("official_trNo") if linked else None,None,breed_status,row.get("breed_evidence") or ("text_explicit_je" if row.get("text_breed")=="제" else "unresolved"),identity,"normal_completed" if finish else "non_positive_result_entry",result.get("finish_position"),finish,quality,int(quality=="usable"),compact({"official_response_sha256":row.get("official_response_sha256"),"supplement_response_sha256":extra.get("official_response_sha256") if extra else None}),source_id),
        )
        entry_id=int(cursor.lastrowid)
        insert_checkpoints_and_segments(conn,entry_id,checkpoints,segments)
        if not linked:
            conn.execute("INSERT INTO resolution_issue(entry_id,event_type,event_date,event_number,horse_number,issue_code,details_json) VALUES (?,?,?,?,?,?,?)",(entry_id,"trial",date,number,horse_number,row["reason"],compact(row)))
        elif quality in {"missing","inconsistent"}:
            conn.execute("INSERT INTO resolution_issue(entry_id,event_type,event_date,event_number,horse_number,issue_code,details_json) VALUES (?,?,?,?,?,?,?)",(entry_id,"trial",date,number,horse_number,"segment_"+quality,compact({"distance_m":row["distance_m"],"finish_time_ms":finish,"section_source":source_kind})))


def insert_exclusions(conn: sqlite3.Connection) -> None:
    inspection=json.loads((READINESS/"inspection_exclusion_audit.json").read_text())
    rows=[
        ("한",7338,"confirmed_non_native_from_text_code",{"label":"한라마"}),
        ("래",818,"confirmed_non_native_from_text_code",{"label":"한라마(래)"}),
        ("산",6016,"excluded_from_native_breed_unconfirmed",{"reason":"Text code does not positively establish Jeju-native breed"}),
        ("검",29,"confirmed_non_native_official_profile",inspection),
    ]
    conn.executemany("INSERT INTO exclusion_summary(source_code,row_count,exclusion_status,evidence_json) VALUES (?,?,?,?)",[(a,b,c,compact(d)) for a,b,c,d in rows])


def insert_coverage(conn: sqlite3.Connection) -> None:
    for event_type in ("race","trial"):
        for dimension, expression in (("all","'all'"),("year","substr(v.event_date,1,4)"),("distance_m","CAST(v.distance_m AS TEXT)")):
            conn.execute(f"""
              INSERT INTO coverage(event_type,dimension,dimension_value,total_rows,positive_finish_rows,usable_segment_rows,missing_segment_rows,inconsistent_segment_rows)
              SELECT ?, ?, {expression}, COUNT(*),
                     SUM(v.finish_time_ms IS NOT NULL), SUM(v.segment_quality='usable'),
                     SUM(v.segment_quality='missing'), SUM(v.segment_quality='inconsistent')
              FROM (SELECT e.*, ev.event_date, ev.distance_m FROM entry e JOIN event ev ON ev.id=e.event_id WHERE ev.event_type=?) v
              GROUP BY {expression}
            """,(event_type,dimension,event_type))


def validate(conn: sqlite3.Connection) -> dict:
    scalar=lambda sql: int(conn.execute(sql).fetchone()[0])
    checks={
        "race_source_rows": scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='race'")==92208,
        "race_events": scalar("SELECT COUNT(*) FROM event WHERE event_type='race'")==9423,
        "race_confirmed_rows": scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='race' AND v.population_status='confirmed_native_normal_race'")==90892,
        "race_time_usable": scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='race' AND e.segment_quality='usable'")==90086,
        "race_identity_unresolved": scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='race' AND e.identity_status='official_race_id_unresolved'")==29,
        "race_quarantine_rows": scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='race' AND v.population_status='explicit_je_no_positive_result'")==1316,
        "trial_candidate_rows": scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='trial'")==15688,
        "trial_linked_rows": scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='trial' AND e.identity_status='official_trial_hr_tr_linked'")==15633,
        "trial_unresolved_rows": scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='trial' AND e.identity_status='official_trial_identity_unresolved'")==55,
        "trial_time_usable": scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='trial' AND e.segment_quality='usable'")==11671,
        "trial_supplement_entries": scalar("SELECT COUNT(DISTINCT entry_id) FROM section_checkpoint WHERE source_kind='trial_official_web_supplement'")==2981,
        "orphan_checkpoints": scalar("SELECT COUNT(*) FROM section_checkpoint c LEFT JOIN entry e ON e.id=c.entry_id WHERE e.id IS NULL")==0,
        "orphan_segments": scalar("SELECT COUNT(*) FROM derived_segment s LEFT JOIN entry e ON e.id=s.entry_id WHERE e.id IS NULL")==0,
        "nonpositive_derived_segments": scalar("SELECT COUNT(*) FROM derived_segment WHERE elapsed_ms<=0 OR distance_m<=0")==0,
        "excluded_text_rows_not_materialized": scalar("SELECT COUNT(*) FROM entry WHERE breed_status='confirmed_non_native'")==0,
        "race_analysis_view_excludes_unresolved": scalar("SELECT COUNT(DISTINCT event_date||':'||event_number||':'||horse_number) FROM analysis_race_segments")==90082,
        "trial_analysis_view_entries": scalar("SELECT COUNT(DISTINCT event_date||':'||event_number||':'||horse_number) FROM analysis_trial_segments")==11671,
    }
    return {"passed":all(checks.values()),"checks":checks,"counts":{
        "events":scalar("SELECT COUNT(*) FROM event"),"entries":scalar("SELECT COUNT(*) FROM entry"),
        "checkpoints":scalar("SELECT COUNT(*) FROM section_checkpoint"),"derived_segments":scalar("SELECT COUNT(*) FROM derived_segment"),
        "issues":scalar("SELECT COUNT(*) FROM resolution_issue"),"source_artifacts":scalar("SELECT COUNT(*) FROM source_artifact"),
        "source_requests":scalar("SELECT COUNT(*) FROM source_request"),
    }}


def main() -> dict:
    OUT.mkdir(parents=True,exist_ok=True)
    TMP.unlink(missing_ok=True)
    conn=sqlite3.connect(TMP)
    try:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        artifacts:dict[str,int]={};events:dict[tuple,int]={}
        register_control_artifacts(conn,artifacts)
        insert_requests(conn)
        build_races(conn,artifacts,events)
        build_trials(conn,artifacts,events)
        insert_exclusions(conn)
        insert_coverage(conn)
        conn.execute("INSERT INTO metadata VALUES (?,?)",("schema_version",compact("1")))
        conn.execute("INSERT INTO metadata VALUES (?,?)",("scope",compact({"meet":2,"race_dates":["20020728","20260912"],"trial_dates":["20030711","20260909"],"purpose":"research_only","operational_db_modified":False})))
        result=validate(conn)
        if not result["passed"]: raise RuntimeError(result)
        conn.execute("PRAGMA optimize")
        conn.commit()
        integrity=conn.execute("PRAGMA integrity_check").fetchone()[0]
        result["integrity_check"]=integrity
    finally:
        conn.close()
    if integrity!="ok": raise RuntimeError(integrity)
    DB.unlink(missing_ok=True)
    TMP.rename(DB)
    result["database_path"]=str(DB.relative_to(ROOT))
    result["database_bytes"]=DB.stat().st_size
    result["database_sha256"]=file_sha(DB)
    (OUT/"validation.json").write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    manifest={"database":result["database_path"],"database_sha256":result["database_sha256"],"validation":"data/research/jeju_native_analysis_db_20260915/validation.json","independent_validation":"data/research/jeju_native_analysis_db_20260915/independent_validation.json","catalog":"data/research/jeju_native_analysis_db_20260915/catalog.json","readme":"data/research/jeju_native_analysis_db_20260915/README.md","report":"docs/JEJU_NATIVE_ANALYSIS_DB_LOAD_2026-09-15.md","verification_guide":"docs/JEJU_NATIVE_DATA_CATALOG_AND_INDEPENDENT_VERIFICATION_2026-09-15.md","builder":"scripts/build_jeju_native_analysis_db.py","verifier":"scripts/verify_jeju_native_analysis_db.py","catalog_exporter":"scripts/export_jeju_data_catalog.py","existing_operational_database_modified":False}
    (OUT/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=="__main__":
    main()
