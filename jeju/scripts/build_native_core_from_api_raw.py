"""Build the Jeju core SQLite ledger from verified KRA API raw attempts.

All API response pages are retained as immutable source artifacts and every
parsed row keeps its original JSON payload. Existing operational and phase2
databases are never opened by this builder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "jeju/data/schema/jeju_native_core.sql"
DEFAULT_DB = REPO_ROOT / "jeju/data/jeju_native_core.sqlite3"
RACE_DATASET_ID = "15058305"
TRIAL_DATASET_ID = "15056974"
RPT_2021_PATH = Path("data/raw/kra_text/dacom23/meet=2/year=2021/month=10/day=21/20211021dacom23.rpt")
RPT_2026_PATH = Path("data/raw/kra_text/dacom23/meet=2/year=2026/month=09/day=16/20260916dacom23.rpt")
PARSER_VERSION = "jeju-api-first-core-v2"
# Confirmed date-shifted/replayed API4_3 rows. Keep their immutable API payloads,
# but do not turn them into race results when the core database is rebuilt.
# See research/20260930_zero_time_cause_audit/README.md.
EXCLUDED_REPLAY_RESULT_ROWS = {
    "2026-07-07": 40,
    "2026-08-25": 75,
    "2026-08-26": 67,
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_items(raw: bytes) -> list[dict]:
    payload = json.loads(raw)
    body = payload.get("response", {}).get("body", {})
    values = (body.get("items") or {}).get("item")
    if values is None:
        return []
    if isinstance(values, dict):
        return [values]
    if isinstance(values, list) and all(isinstance(row, dict) for row in values):
        return values
    raise ValueError("Unexpected KRA API item collection shape")


def int_or_none(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return int(text) if text.isdigit() else None


def float_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def date_iso(value: object) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def id_text(value: object) -> str | None:
    return text_or_none(value)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def query_params_without_key(url: str | None, fallback: dict | None = None) -> str:
    if url:
        values = {
            key: value for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True)
            if key.lower() not in {"servicekey", "service_key"}
        }
        return canonical_json(values)
    return canonical_json(fallback or {})


def safe_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def verify_page(page_path: Path, metadata: dict) -> tuple[bytes, list[dict]]:
    raw = page_path.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    expected_sha = metadata.get("response_sha256")
    if expected_sha and actual_sha != expected_sha:
        raise ValueError(f"SHA-256 mismatch for {page_path}")
    rows = parse_items(raw)
    expected_rows = metadata.get("response_rows", metadata.get("actual_page_rows", metadata.get("upstream_rows")))
    if expected_rows is not None and len(rows) != int(expected_rows):
        raise ValueError(f"Page row count mismatch for {page_path}: {len(rows)}/{expected_rows}")
    return raw, rows


def result_attempts(history_run: Path, attempt_2026: Path) -> list[tuple[int, Path, dict, Path]]:
    attempts: list[tuple[int, Path, dict, Path]] = []
    for year in range(2002, 2026):
        manifest_path = history_run / str(year) / "attempt_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(manifest_path)
        manifest = load_json(manifest_path)
        if manifest.get("status") != "completed":
            raise ValueError(f"Result API year {year} is not complete")
        attempts.append((year, history_run, manifest, manifest_path))
    manifest_path = attempt_2026 / "attempt_manifest.json"
    manifest = load_json(manifest_path)
    if manifest.get("status") != "completed_api_result_rows":
        raise ValueError("2026 result API attempt did not complete with full API result rows")
    attempts.append((2026, attempt_2026, manifest, manifest_path))
    return attempts


def trial_attempts(inventory_path: Path, attempt_2026: Path) -> list[tuple[int, Path, dict, Path]]:
    inventory = load_json(inventory_path)
    states = inventory.get("year_status", {})
    attempts: list[tuple[int, Path, dict, Path]] = []
    for year in range(2000, 2026):
        state = states.get(str(year))
        if not state or state.get("status") != "completed_api_response":
            raise ValueError(f"Trial API year {year} is not complete in inventory")
        manifest_path = inventory_path.parent / state["attempt_manifest"]
        manifest = load_json(manifest_path)
        attempts.append((year, manifest_path.parent, manifest, manifest_path))
    manifest_path = attempt_2026 / "attempt_manifest.json"
    manifest = load_json(manifest_path)
    if manifest.get("status") != "completed_api_response":
        raise ValueError("2026 trial API attempt is not complete")
    attempts.append((2026, attempt_2026, manifest, manifest_path))
    return attempts


def page_metadata(manifest: dict) -> list[dict]:
    pages = manifest.get("source_pages") or []
    if not pages:
        raise ValueError(f"Attempt {manifest.get('attempt_id')} has no source page metadata")
    return pages


def meet_code(row: dict) -> int:
    value = str(row.get("meet") or "")
    codes = {"서울": 1, "제주": 2, "부산경남": 3, "영남": 3, "영천": 4}
    if value not in codes:
        raise ValueError(f"Unrecognized KRA meet label: {value!r}")
    return codes[value]


def add_api_artifact(conn: sqlite3.Connection, *, dataset_id: str, dataset_name: str,
                     operation: str, attempt_id: str, page: dict, raw_path: Path,
                     raw: bytes, fallback_scope: dict, collected_at: str | None) -> int:
    params = query_params_without_key(page.get("source_url_without_key"), fallback_scope)
    cur = conn.execute(
        """INSERT INTO source_artifacts(
               source_family,source_role,public_dataset_id,dataset_name,endpoint,operation,
               attempt_id,request_params_json,source_url_without_key,collected_at_utc,
               http_status_code,content_type,raw_relative_path,response_bytes,sha256,
               parser_version,created_at_utc)
           VALUES('kra_openapi','primary',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (dataset_id, dataset_name, page.get("source_url_without_key", "").split("?")[0],
         operation, attempt_id, params, page.get("source_url_without_key"), collected_at,
         page.get("status_code"), page.get("content_type"), safe_relative(raw_path),
         len(raw), hashlib.sha256(raw).hexdigest(), PARSER_VERSION, datetime.now(UTC).isoformat()),
    )
    return int(cur.lastrowid)


def import_result_attempt(conn: sqlite3.Connection, year: int, root: Path,
                          manifest: dict, manifest_path: Path) -> dict:
    op = "raceResult_3"
    page_rows_total = 0
    page_count = 0
    event_dates: list[str] = []
    rank_counts: Counter[str] = Counter()
    race_keys: set[tuple[str, int]] = set()
    candidate_count = 0
    yearly_counts: set[int] = set()
    excluded_replay_counts: Counter[str] = Counter()
    request_scope = (manifest.get("requested_scope") or {}).get("public_params") or {
        "meet": 2, "rc_year": str(year), "_type": "json"
    }

    for page in page_metadata(manifest):
        page_rel = page.get("response_file")
        page_path = root / page_rel if year == 2026 else root / page_rel
        raw, rows = verify_page(page_path, page)
        count = int(page.get("upstream_total_count", page.get("api_total_count", 0)) or 0)
        yearly_counts.add(count)
        artifact_id = add_api_artifact(
            conn, dataset_id=RACE_DATASET_ID, dataset_name="한국마사회 경주기록 정보",
            operation=op, attempt_id=manifest.get("attempt_id", root.name), page=page,
            raw_path=page_path, raw=raw, fallback_scope=request_scope,
            collected_at=datetime.fromtimestamp((page.get("retrieved_at_ms") or 0) / 1000, UTC).isoformat()
            if page.get("retrieved_at_ms") else manifest.get("completed_at_utc"),
        )
        for idx, row in enumerate(rows, 1):
            event_date = date_iso(row.get("rcDate"))
            if not event_date or int(event_date[:4]) != year or meet_code(row) != 2:
                raise ValueError(f"Unexpected date/meet in results API row: {year}/{idx}")
            race_no = int_or_none(row.get("rcNo"))
            horse_no = int_or_none(row.get("chulNo"))
            horse_id = id_text(row.get("hrNo"))
            if race_no is None or horse_id is None:
                raise ValueError(f"Missing race or official horse ID: {year}/{idx}")
            rank = text_or_none(row.get("rank")) or ""
            rank_counts[rank] += 1
            event_dates.append(event_date)
            natural_key = f"{event_date}|2|{race_no}|{horse_no}|{horse_id}"
            payload = canonical_json(row)
            digest = hashlib.sha256(payload.encode()).hexdigest()
            raw_cur = conn.execute(
                "INSERT INTO api_records(source_artifact_id,record_index,record_type,natural_key,payload_json,payload_sha256) VALUES(?,?,?,?,?,?)",
                (artifact_id, idx, "race_result_entry", natural_key, payload, digest),
            )
            record_id = int(raw_cur.lastrowid)
            if event_date in EXCLUDED_REPLAY_RESULT_ROWS:
                excluded_replay_counts[event_date] += 1
                page_rows_total += 1
                continue
            candidate_count += int(rank.startswith("제"))
            race_keys.add((event_date, race_no))
            if year >= 2023:
                breed_assessment = "program_rule_candidate"
                assessment_note = "2023년 이후 제주마 전면 시행 규칙에 따른 경주 모집단 후보. API 행에는 개별 마종 필드가 없고 rank를 품종으로 사용하지 않는다."
            elif rank.startswith("제"):
                breed_assessment = "rank_class_candidate"
                assessment_note = "rank 원문 접두 후보만 보존. rank 의미를 품종으로 확정하지 않으며 API 말 ID/품종 교차확인 대기."
            else:
                breed_assessment = "unresolved"
                assessment_note = "API 결과에 개별 마종 필드가 없다. 말 ID 기반 공식 API 근거 대기."
            conn.execute(
                """INSERT INTO race_result_rows(
                       api_record_id,race_date,meet_code,race_number,horse_number,horse_id,horse_name,
                       race_distance_m,rank_class_raw,race_name_raw,finish_position,finish_status_raw,
                       finish_time_seconds,carried_weight_kg,body_weight_raw,jockey_id,jockey_name,
                       trainer_id,trainer_name,owner_id,owner_name,track_raw,weather_raw,breed_label_raw,
                       breed_assessment,breed_assessment_note)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record_id,event_date,2,race_no,horse_no,horse_id,text_or_none(row.get("hrName")),
                 int_or_none(row.get("rcDist")),rank,text_or_none(row.get("rcName")),
                 int_or_none(row.get("ord")),text_or_none(row.get("ord")),float_or_none(row.get("rcTime")),
                 float_or_none(row.get("wgBudam")),text_or_none(row.get("wgHr")),id_text(row.get("jkNo")),
                 text_or_none(row.get("jkName")),id_text(row.get("trNo")),text_or_none(row.get("trName")),
                 id_text(row.get("owNo")),text_or_none(row.get("owName")),text_or_none(row.get("track")),
                 text_or_none(row.get("weather")),None,breed_assessment,assessment_note),
            )
            page_rows_total += 1
        page_count += 1

    expected = manifest.get("upstream_total_count", manifest.get("actual_response_rows"))
    if page_count < 1 or len(yearly_counts) != 1 or page_rows_total != int(expected or -1):
        raise ValueError(f"Incomplete result API coverage for {year}: rows={page_rows_total}, expected={expected}, pages={page_count}")
    if year == 2026 and dict(excluded_replay_counts) != EXCLUDED_REPLAY_RESULT_ROWS:
        raise ValueError(f"Unexpected replay-row coverage: {dict(excluded_replay_counts)}")
    return {
        "year": year, "operation": op, "page_count": page_count,
        "api_total_count": int(expected), "response_row_count": page_rows_total,
        "normalized_excluded_replay_rows": sum(excluded_replay_counts.values()),
        "first_event_date": min(event_dates), "last_event_date": max(event_dates),
        "rank_prefix_candidate_count": candidate_count,
        "race_count": len(race_keys), "rank_counts": dict(rank_counts),
    }


def import_trial_attempt(conn: sqlite3.Connection, year: int, root: Path,
                         manifest: dict, manifest_path: Path) -> dict:
    op = "ridingTestResult_1"
    page_rows_total = 0
    page_count = 0
    event_dates: list[str] = []
    label_counts: Counter[str] = Counter()
    trial_keys: set[tuple[str, int]] = set()
    trial_row_counts: Counter[tuple[str, int]] = Counter()
    expected_count = int(manifest.get("upstream_total_count", 0) or 0)
    yearly_counts: set[int] = set()
    request_scope = (manifest.get("requested_scope") or {}).get("public_params") or {
        "meet": 2, "tr_year": str(year), "_type": "json"
    }

    for page in page_metadata(manifest):
        page_path = root / page["response_file"]
        raw, rows = verify_page(page_path, page)
        count = int(page.get("page_total_count", manifest.get("upstream_total_count", 0)) or 0)
        yearly_counts.add(count)
        artifact_id = add_api_artifact(
            conn, dataset_id=TRIAL_DATASET_ID, dataset_name="한국마사회 주행심사 상세결과",
            operation=op, attempt_id=manifest.get("attempt_id", root.name), page=page,
            raw_path=page_path, raw=raw, fallback_scope=request_scope,
            collected_at=datetime.fromtimestamp((page.get("retrieved_at_ms") or 0) / 1000, UTC).isoformat()
            if page.get("retrieved_at_ms") else manifest.get("completed_at_utc"),
        )
        for idx, row in enumerate(rows, 1):
            event_date = date_iso(row.get("trainDate"))
            if not event_date or int(event_date[:4]) != year or meet_code(row) != 2:
                raise ValueError(f"Unexpected date/meet in trial API row: {year}/{idx}")
            trial_no = int_or_none(row.get("trainNo"))
            horse_no = int_or_none(row.get("chulNo"))
            horse_id = id_text(row.get("hrNo"))
            if trial_no is None or horse_id is None:
                raise ValueError(f"Missing trial number or official horse ID: {year}/{idx}")
            event_dates.append(event_date)
            label = text_or_none(row.get("majong"))
            label_counts[label or "(blank)"] += 1
            trial_keys.add((event_date, trial_no))
            trial_row_counts[(event_date, trial_no)] += 1
            natural_key = f"{event_date}|2|{trial_no}|{horse_no}|{horse_id}"
            payload = canonical_json(row)
            raw_cur = conn.execute(
                "INSERT INTO api_records(source_artifact_id,record_index,record_type,natural_key,payload_json,payload_sha256) VALUES(?,?,?,?,?,?)",
                (artifact_id,idx,"running_trial_entry",natural_key,payload,hashlib.sha256(payload.encode()).hexdigest()),
            )
            record_id = int(raw_cur.lastrowid)
            if label == "제주":
                breed_status = "api_native_label"
                breed_note = "API20_1 원문 majong='제주' 관측. 응답 라벨을 그대로 보존하고 코드로 재해석하지 않는다."
            elif label:
                breed_status = "api_non_native_label"
                breed_note = f"API20_1 원문 majong={label!r} 관측. 제주마 정규 행에서 격리한다."
            else:
                breed_status = "unresolved"
                breed_note = "API20_1 원문에 마종 라벨이 비어 있음. 품종 확정 보류."
            section_fields = {key: row[key] for key in row if key.startswith(("s1f", "g1f", "g2f", "g3f", "g4f", "g6f", "g8f", "rcTime", "passtime"))}
            conn.execute(
                """INSERT INTO running_trial_rows(
                       api_record_id,trial_date,meet_code,trial_number,horse_number,horse_id,horse_name,
                       finish_position,finish_status_raw,finish_time_seconds,body_weight_kg,
                       carried_weight_base_kg,jockey_overweight_kg,jockey_id,jockey_name,
                       trainer_id,trainer_name,pass_flag_raw,failure_reason_raw,inspection_reason_raw,
                       section_times_json,breed_label_raw,breed_assessment,breed_assessment_note)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record_id,event_date,2,trial_no,horse_no,horse_id,text_or_none(row.get("hrName")),
                 int_or_none(row.get("ord")),text_or_none(row.get("ord")),float_or_none(row.get("rcTime")),
                 float_or_none(row.get("wgHr")),float_or_none(row.get("wgBudam")),float_or_none(row.get("wgJkAdd")),
                 id_text(row.get("jkNo")),text_or_none(row.get("jkName")),id_text(row.get("trNo")),
                 text_or_none(row.get("trName")),text_or_none(row.get("passFlag")),
                 text_or_none(row.get("nopassReason")),text_or_none(row.get("reason")),
                 canonical_json(section_fields),label,breed_status,breed_note),
            )
            if label:
                conn.execute(
                    """INSERT INTO breed_evidence(
                           horse_id,observed_event_date,breed_label_raw,evidence_kind,source_artifact_id,
                           api_record_id,timing_basis,notes)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (horse_id,event_date,label,"API20_1 majong observation",artifact_id,record_id,
                     "running-trial event date", "Direct KRA API response field; event-date observation, not horse-profile current value."),
                )
            page_rows_total += 1
        page_count += 1

    if page_count < 1 or len(yearly_counts) != 1 or page_rows_total != expected_count:
        raise ValueError(f"Incomplete trial API coverage for {year}: rows={page_rows_total}, expected={expected_count}, pages={page_count}")
    return {
        "year": year, "operation": op, "page_count": page_count,
        "api_total_count": expected_count, "response_row_count": page_rows_total,
        "first_event_date": min(event_dates), "last_event_date": max(event_dates),
        "trial_count": len(trial_keys), "breed_label_counts": dict(label_counts),
    }


def add_text_artifact(conn: sqlite3.Connection, path: Path, *, date: str, operation: str,
                      role: str = "validation_only") -> int:
    raw = path.read_bytes()
    return int(conn.execute(
        """INSERT INTO source_artifacts(
               source_family,source_role,public_dataset_id,dataset_name,endpoint,operation,
               attempt_id,request_params_json,source_url_without_key,collected_at_utc,
               http_status_code,content_type,raw_relative_path,response_bytes,sha256,
               parser_version,created_at_utc)
           VALUES('kra_rpt_txt',?,NULL,'한국마사회 RPT 추가 대조 원문','/RPT',?,?,?,?,?,NULL,'text/plain;charset=cp949',?,?,?,'field-note-v1',?)""",
        (role,operation,f"existing-local-{date}",canonical_json({"meet":2,"date":date}),None,None,
         safe_relative(path),len(raw),hashlib.sha256(raw).hexdigest(),datetime.now(UTC).isoformat()),
    ).lastrowid)


def record_supplemental_examples(conn: sqlite3.Connection) -> dict:
    """Record two field gaps and one real source conflict without overriding API values."""
    summary: dict = {"supplemental_facts": 0, "conflicts": 0}
    path_2021 = REPO_ROOT / RPT_2021_PATH
    if path_2021.exists():
        artifact_id = add_text_artifact(conn,path_2021,date="2021-10-21",operation="dacom23")
        api = conn.execute(
            """SELECT t.api_record_id,t.horse_id,t.breed_label_raw
               FROM running_trial_rows t WHERE t.trial_date='2021-10-21' AND t.trial_number=1
                 AND t.horse_number=1 AND t.horse_id='1019026'"""
        ).fetchone()
        if api is not None and api[2] == "한라":
            fact = conn.execute(
                """INSERT INTO supplemental_facts(entity_type,entity_key,field_name,value_json,
                   source_artifact_id,source_line,api_field_state,notes)
                   VALUES('running_trial',?,'breed_label_rpt','"제"',?,13,'conflicts_with_api',?)""",
                ("2021-10-21|2|1|1|1019026",artifact_id,"RPT line 13 shows literal 마종 '제'; preserve beside API majong='한라', do not replace."),
            )
            summary["supplemental_facts"] += 1
            conn.execute(
                """UPDATE running_trial_rows SET breed_assessment='conflict',
                       breed_assessment_note='API majong=한라 conflicts with RPT literal 마종 제; quarantined.'
                   WHERE api_record_id=?""", (api[0],)
            )
            conn.execute(
                """INSERT INTO provenance_issues(issue_type,severity,status,entity_type,entity_key,
                   api_record_id,supplemental_artifact_id,api_value_json,supplemental_value_json,
                   summary,detail_json,created_at_utc)
                   VALUES('breed_label_conflict','high','quarantined','running_trial',?,?,?,?,?,?,?,?)""",
                ("2021-10-21|2|1|1|1019026",api[0],artifact_id,'"한라"','"제"',
                 "KRA API20_1 majong=한라 conflicts with RPT literal 마종 제 for horse 1019026 (자수정).",
                 canonical_json({"trial_date":"2021-10-21","trial_number":1,"horse_number":1,
                                 "horse_id":"1019026","horse_name":"자수정","api_operation":"ridingTestResult_1",
                                 "rpt_path":safe_relative(path_2021),"rpt_line":13,
                                 "rpt_sha256":hashlib.sha256(path_2021.read_bytes()).hexdigest(),
                                 "policy":"retain API and RPT observations; quarantine breed resolution"}),
                 datetime.now(UTC).isoformat()),
            )
            summary["conflicts"] += 1

    path_2026 = REPO_ROOT / RPT_2026_PATH
    if path_2026.exists():
        artifact_id = add_text_artifact(conn,path_2026,date="2026-09-16",operation="dacom23",role="supplement")
        events = conn.execute(
            "SELECT trial_date,trial_number,count(*) FROM running_trial_rows WHERE trial_date='2026-09-16' GROUP BY trial_date,trial_number"
        ).fetchall()
        text = path_2026.read_bytes().decode("cp949",errors="replace")
        lines = text.splitlines()
        header_lines = {int(match.group(1)): line_no for line_no,line in enumerate(lines,1)
                        if (match := re.search(r"제\s*(\d+)경주\s+(\d+)M",line))}
        for _, trial_no, _count in events:
            distance_match = next((int(m.group(1)) for line in lines
                                   if (m := re.search(rf"제\s*0?{trial_no}경주\s+(\d+)M",line))),None)
            if distance_match is None:
                continue
            conn.execute(
                """INSERT INTO supplemental_facts(entity_type,entity_key,field_name,value_json,
                   source_artifact_id,source_line,api_field_state,notes)
                   VALUES('running_trial',?,'distance_m',?,?,?,'api_field_absent',?)""",
                (f"2026-09-16|2|{trial_no}",json.dumps(distance_match),artifact_id,
                 header_lines.get(trial_no),"API20_1 does not return trial distance; RPT header supplies this supplemental event field."),
            )
            summary["supplemental_facts"] += 1
    return summary


def record_coverage(conn: sqlite3.Connection, family: str, manifest: dict, coverage: dict) -> None:
    conn.execute(
        """INSERT INTO collection_coverage(source_family,operation,year,attempt_id,status,page_count,
           api_total_count,response_row_count,first_event_date,last_event_date,breed_label_counts_json,
           candidate_row_count,notes,created_at_utc)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (family,coverage["operation"],coverage["year"],manifest.get("attempt_id","unknown"),
         manifest.get("status","completed"),coverage["page_count"],coverage["api_total_count"],
         coverage["response_row_count"],coverage.get("first_event_date"),coverage.get("last_event_date"),
         canonical_json(coverage.get("breed_label_counts",{})),coverage.get("rank_prefix_candidate_count"),
         canonical_json({k:v for k,v in coverage.items() if k not in {"rank_counts","breed_label_counts"}}),
         datetime.now(UTC).isoformat()),
    )


def cross_reference_result_breed(conn: sqlite3.Connection) -> None:
    # Event-date inference reads API20 evidence only. API42 profile snapshots
    # use a different raw label and cannot establish a historical event date.
    evidence: dict[str, list[tuple[str,str,int]]] = defaultdict(list)
    for horse_id, label, event_date, record_id in conn.execute(
        """SELECT horse_id,breed_label_raw,observed_event_date,api_record_id
           FROM breed_evidence WHERE evidence_kind='API20_1 majong observation'"""
    ):
        evidence[horse_id].append((label,event_date,record_id))
    for horse_id, observations in evidence.items():
        labels = {row[0] for row in observations}
        if len(labels) > 1:
            detail = canonical_json({"horse_id":horse_id,"observations":[{"label":l,"event_date":d,"api_record_id":r} for l,d,r in observations]})
            exists = conn.execute("SELECT 1 FROM provenance_issues WHERE issue_type='api_breed_observation_conflict' AND entity_key=?",(horse_id,)).fetchone()
            if not exists:
                conn.execute(
                    """INSERT INTO provenance_issues(issue_type,severity,status,entity_type,entity_key,
                       api_record_id,api_value_json,summary,detail_json,created_at_utc)
                   VALUES('api_breed_label_variation','medium','open','horse',?,?,?,?,?,?)""",
                    (horse_id,observations[0][2],canonical_json(sorted(labels)),
                     f"Different dated official API20_1 majong labels were observed for horse ID {horse_id}; retain race candidates and review temporal applicability.",detail,datetime.now(UTC).isoformat()),
                )
            continue
        label = next(iter(labels))
        if label != "제주":
            continue
        conn.execute(
            """UPDATE race_result_rows SET breed_assessment='api_cross_reference_candidate',
                   breed_assessment_note=? WHERE horse_id=? AND race_date >= ?
                   AND breed_assessment IN ('unresolved','rank_class_candidate')""",
            ("Same official horse ID has API20_1 majong='제주' observed on or before this race date. Cross-API candidate evidence only; no breed confirmation is asserted.",horse_id,min(row[1] for row in observations)),
        )

    # A rank-class candidate that also has a non-Jeju API20 observation is a
    # review case. Keep the race row in the candidate population and preserve
    # both dated observations rather than silently excluding it.
    candidates = conn.execute(
        """SELECT DISTINCT r.horse_id
           FROM race_result_rows r JOIN breed_evidence b ON b.horse_id=r.horse_id
           WHERE coalesce(r.rank_class_raw,'') LIKE '제%'
             AND b.evidence_kind='API20_1 majong observation'
             AND b.breed_label_raw IN ('한라','한라(래)')"""
    ).fetchall()
    for (horse_id,) in candidates:
        existing = conn.execute(
            "SELECT 1 FROM provenance_issues WHERE issue_type='rank_candidate_vs_non_native_trial_observation' AND entity_key=?",
            (horse_id,),
        ).fetchone()
        if existing:
            continue
        candidate_scope = conn.execute(
            """SELECT count(*),min(race_date),max(race_date)
               FROM race_result_rows WHERE horse_id=? AND coalesce(rank_class_raw,'') LIKE '제%'""",
            (horse_id,),
        ).fetchone()
        rows = conn.execute(
            """SELECT breed_label_raw,observed_event_date,api_record_id
               FROM breed_evidence WHERE horse_id=? AND breed_label_raw IN ('한라','한라(래)')
                 AND evidence_kind='API20_1 majong observation'
               ORDER BY observed_event_date,api_record_id""",
            (horse_id,),
        ).fetchall()
        conn.execute(
            """INSERT INTO provenance_issues(issue_type,severity,status,entity_type,entity_key,
                   api_record_id,api_value_json,summary,detail_json,created_at_utc)
               VALUES('rank_candidate_vs_non_native_trial_observation','medium','open','horse',?,?,?,?,?,?)""",
            (horse_id,rows[0][2],canonical_json(sorted({r[0] for r in rows})),
             f"A race rank-class candidate horse ID {horse_id} also has dated API20_1 non-Jeju majong observations; retain the candidate and review event-time applicability.",
             canonical_json({"horse_id":horse_id,"rank_candidate_race_rows":candidate_scope[0],
                             "candidate_race_date_range":[candidate_scope[1],candidate_scope[2]],
                             "non_native_api20_observations":[{"label":r[0],"event_date":r[1],"api_record_id":r[2]} for r in rows],
                             "policy":"candidate retained; no automatic exclusion or historical retroactive classification"}),
             datetime.now(UTC).isoformat()),
        )


def cross_reference_summary(conn: sqlite3.Connection) -> dict:
    candidates = conn.execute(
        """SELECT r.api_record_id,r.horse_id,r.race_date,
                  count(DISTINCT CASE WHEN b.breed_label_raw='제주' THEN b.api_record_id END) AS native_observations,
                  count(DISTINCT CASE WHEN b.breed_label_raw='제주' AND b.observed_event_date<=r.race_date THEN b.api_record_id END) AS native_on_or_before,
                  count(DISTINCT CASE WHEN b.breed_label_raw='제주' AND b.observed_event_date>r.race_date THEN b.api_record_id END) AS native_after,
                  count(DISTINCT CASE WHEN b.breed_label_raw IN ('한라','한라(래)') THEN b.api_record_id END) AS non_native_observations,
                  count(DISTINCT b.breed_label_raw) AS distinct_labels
           FROM race_result_rows r LEFT JOIN breed_evidence b ON b.horse_id=r.horse_id
             AND b.evidence_kind='API20_1 majong observation'
           WHERE coalesce(r.rank_class_raw,'') LIKE '제%'
           GROUP BY r.api_record_id,r.horse_id,r.race_date"""
    ).fetchall()
    categories = Counter()
    row_counts = Counter()
    horse_ids: dict[str,set[str]] = defaultdict(set)
    for _record_id,horse_id,_race_date,native,native_before,native_after,nonnative,label_count in candidates:
        if label_count > 1:
            category = "multiple_api20_labels_possible_temporal_or_id_conflict"
        elif native_before:
            category = "api20_jeju_observed_on_or_before_race"
        elif native_after:
            category = "api20_jeju_observed_only_after_race"
        elif nonnative:
            category = "api20_non_jeju_label_only"
        else:
            category = "no_same_id_api20_breed_observation"
        row_counts[category] += 1
        horse_ids[category].add(horse_id)
        if native:
            categories["with_any_api20_jeju_observation_rows"] += 1
            horse_ids["with_any_api20_jeju_observation_rows"].add(horse_id)
        if native_before:
            categories["with_api20_jeju_observation_on_or_before_rows"] += 1
            horse_ids["with_api20_jeju_observation_on_or_before_rows"].add(horse_id)
        if native and not native_before:
            categories["with_api20_jeju_future_only_rows"] += 1
            horse_ids["with_api20_jeju_future_only_rows"].add(horse_id)
        if nonnative:
            categories["with_api20_non_jeju_observation_rows"] += 1
            horse_ids["with_api20_non_jeju_observation_rows"].add(horse_id)
        if native and nonnative:
            categories["with_api20_jeju_and_non_jeju_observations_rows"] += 1
            horse_ids["with_api20_jeju_and_non_jeju_observations_rows"].add(horse_id)
    disjoint = {
        key: {"candidate_rows": value,"distinct_horse_ids":len(horse_ids[key])}
        for key,value in sorted(row_counts.items())
    }
    for key in (
        "multiple_api20_labels_possible_temporal_or_id_conflict",
        "api20_jeju_observed_on_or_before_race",
        "api20_jeju_observed_only_after_race",
        "api20_non_jeju_label_only",
        "no_same_id_api20_breed_observation",
    ):
        disjoint.setdefault(key,{"candidate_rows":0,"distinct_horse_ids":0})
    overlapping = {
        key: {"candidate_rows": value,"distinct_horse_ids":len(horse_ids[key])}
        for key,value in sorted(categories.items())
    }
    for key in (
        "with_any_api20_jeju_observation_rows",
        "with_api20_jeju_observation_on_or_before_rows",
        "with_api20_jeju_future_only_rows",
        "with_api20_non_jeju_observation_rows",
        "with_api20_jeju_and_non_jeju_observations_rows",
    ):
        overlapping.setdefault(key,{"candidate_rows":0,"distinct_horse_ids":0})
    return {
        "candidate_definition":"race_result_rows.rank_class_raw starts with 제; this is an API rank-class candidate, not confirmed breed",
        "candidate_rows":len(candidates),
        "candidate_horse_ids":len({row[1] for row in candidates}),
        "disjoint_event_time_categories":disjoint,
        "overlapping_api20_evidence_counts":overlapping,
        "interpretation":"API20 majong is an event-date observation. Observations after a race are not retroactive proof. Multiple labels and non-Jeju labels are review flags; they do not automatically remove a race candidate.",
    }


def population_candidate_summary(conn: sqlite3.Connection) -> dict:
    def counts(sql: str, params: tuple=()) -> dict:
        row=conn.execute(sql,params).fetchone()
        return {"rows":row[0],"distinct_horse_ids":row[1],"distinct_races":row[2]}
    rank=counts(
        """SELECT count(*),count(DISTINCT horse_id),count(DISTINCT race_date||'|'||race_number)
           FROM race_result_rows WHERE coalesce(rank_class_raw,'') LIKE '제%'"""
    )
    nonrank=counts(
        """SELECT count(*),count(DISTINCT horse_id),count(DISTINCT race_date||'|'||race_number)
           FROM race_result_rows WHERE breed_assessment='api_cross_reference_candidate'
             AND coalesce(rank_class_raw,'') NOT LIKE '제%'"""
    )
    view=counts("SELECT count(*),count(DISTINCT horse_id),count(DISTINCT race_date||'|'||race_number) FROM jeju_race_population_candidates")
    mixed_rows=conn.execute(
        """SELECT count(*),count(DISTINCT r.race_date||'|'||r.race_number)
           FROM race_result_rows r JOIN (
             SELECT DISTINCT race_date,race_number FROM race_result_rows
             WHERE breed_assessment='api_cross_reference_candidate'
               AND coalesce(rank_class_raw,'') NOT LIKE '제%'
           ) x USING(race_date,race_number)"""
    ).fetchone()
    fully_candidate_races=conn.execute(
        """WITH extra_races AS (
               SELECT DISTINCT race_date,race_number FROM race_result_rows
               WHERE breed_assessment='api_cross_reference_candidate'
                 AND coalesce(rank_class_raw,'') NOT LIKE '제%'
           ), per_race AS (
               SELECT r.race_date,r.race_number,count(*) all_entries,
                      sum(CASE WHEN r.breed_assessment='api_cross_reference_candidate'
                                    AND coalesce(r.rank_class_raw,'') NOT LIKE '제%' THEN 1 ELSE 0 END) candidate_entries
               FROM race_result_rows r JOIN extra_races x USING(race_date,race_number)
               GROUP BY r.race_date,r.race_number
           ) SELECT count(*) FROM per_race WHERE all_entries=candidate_entries"""
    ).fetchone()[0]
    non_native=conn.execute(
        """SELECT count(DISTINCT r.api_record_id),count(DISTINCT r.horse_id)
           FROM jeju_race_population_candidates r JOIN breed_evidence b ON b.horse_id=r.horse_id
           WHERE b.evidence_kind='API20_1 majong observation'
             AND b.breed_label_raw IN ('한라','한라(래)')"""
    ).fetchone()
    variation=conn.execute(
        """SELECT count(DISTINCT r.api_record_id),count(DISTINCT r.horse_id)
           FROM jeju_race_population_candidates r JOIN (
              SELECT horse_id FROM breed_evidence
              WHERE evidence_kind='API20_1 majong observation'
              GROUP BY horse_id HAVING count(DISTINCT breed_label_raw)>1
           ) v USING(horse_id)"""
    ).fetchone()
    native_prior=conn.execute(
        """SELECT count(DISTINCT r.api_record_id),count(DISTINCT r.horse_id)
           FROM jeju_race_population_candidates r JOIN breed_evidence b ON b.horse_id=r.horse_id
           WHERE b.evidence_kind='API20_1 majong observation'
             AND b.breed_label_raw='제주' AND b.observed_event_date<=r.race_date"""
    ).fetchone()
    nonrank_years=dict(conn.execute(
        """SELECT substr(race_date,1,4),count(*) FROM race_result_rows
           WHERE breed_assessment='api_cross_reference_candidate'
             AND coalesce(rank_class_raw,'') NOT LIKE '제%'
           GROUP BY substr(race_date,1,4) ORDER BY substr(race_date,1,4)"""
    ).fetchall())
    return {
        "rank_prefix_candidate_population":rank,
        "additional_api20_prior_jeju_cross_reference_rows_without_rank_prefix":nonrank,
        "additional_cross_reference_rows_by_year":nonrank_years,
        "candidate_view_union":view,
        "additional_cross_reference_race_population_detail":{
            "races_with_additional_cross_reference":mixed_rows[1],
            "all_api4_3_entry_rows_inside_those_races":mixed_rows[0],
            "races_where_every_api4_3_entry_is_an_additional_cross_reference_candidate":fully_candidate_races,
            "note":"The added 68 races include mixed/partial entry populations. The 281 added candidate rows do not make all entrants or the full race confirmed Jeju horses.",
        },
        "api20_event_time_support_for_view":{
            "candidate_rows_with_same_id_majong_jeju_observed_on_or_before_race":native_prior[0],
            "distinct_horse_ids":native_prior[1],
            "candidate_rows_with_non_jeju_api20_observation":non_native[0],
            "distinct_horse_ids_with_non_jeju_api20_observation":non_native[1],
            "candidate_rows_with_multiple_api20_labels_for_same_id":variation[0],
            "distinct_horse_ids_with_multiple_api20_labels":variation[1],
            "note":"API20 observations support cross-reference candidates only. They do not alone prove breed validity for every historical race date.",
        },
    }


def summarize(conn: sqlite3.Connection, db_path: Path, source_rows: dict) -> dict:
    race_total = conn.execute("SELECT count(*) FROM race_result_rows").fetchone()[0]
    trial_total = conn.execute("SELECT count(*) FROM running_trial_rows").fetchone()[0]
    race_rank_candidate = conn.execute("SELECT count(*) FROM race_result_rows WHERE coalesce(rank_class_raw,'') LIKE '제%'").fetchone()[0]
    direct_trial = conn.execute("SELECT count(*) FROM running_trial_rows WHERE breed_assessment='api_native_label'").fetchone()[0]
    conflict_count = conn.execute("SELECT count(*) FROM provenance_issues WHERE status='quarantined'").fetchone()[0]
    return {
        "database": safe_relative(db_path),
        "race_result_rows_all_meet_2": race_total,
        "race_rows_rank_prefix_je_candidates_not_confirmed": race_rank_candidate,
        "running_trial_rows_all_meet_2": trial_total,
        "running_trial_rows_api_majong_jeju": direct_trial,
        "quarantined_provenance_issues": conflict_count,
        "source_artifacts": conn.execute("SELECT count(*) FROM source_artifacts").fetchone()[0],
        "api_raw_records": conn.execute("SELECT count(*) FROM api_records").fetchone()[0],
        "coverage_rows": conn.execute("SELECT count(*) FROM collection_coverage").fetchone()[0],
        "by_source_year": source_rows,
        "breed_status_counts": {
            "race_results": dict(conn.execute("SELECT breed_assessment,count(*) FROM race_result_rows GROUP BY breed_assessment")),
            "running_trials": dict(conn.execute("SELECT breed_assessment,count(*) FROM running_trial_rows GROUP BY breed_assessment")),
        },
        "rank_candidate_api20_cross_reference": cross_reference_summary(conn),
        "race_population_candidate_summary": population_candidate_summary(conn),
        "open_provenance_issue_counts": dict(conn.execute("SELECT issue_type,count(*) FROM provenance_issues WHERE status='open' GROUP BY issue_type")),
        "quarantined_issue_counts": dict(conn.execute("SELECT issue_type,count(*) FROM provenance_issues WHERE status='quarantined' GROUP BY issue_type")),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "phase2_or_operational_db_used_as_input": False,
    }


def build(args: argparse.Namespace) -> Path:
    db_path = args.database.resolve()
    db_path.parent.mkdir(parents=True,exist_ok=True)
    if db_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing core database: {db_path}")
    history_root = args.results_history.resolve()
    result_2026 = args.results_2026.resolve()
    trial_inventory = args.trials_inventory.resolve()
    trial_2026 = args.trials_2026.resolve()
    temp_fd,temp_name=tempfile.mkstemp(prefix="jeju_native_core_",suffix=".sqlite3.tmp",dir=db_path.parent)
    os.close(temp_fd)
    temp_path=Path(temp_name)
    conn=sqlite3.connect(temp_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    source_rows={"race_results":{},"running_trials":{}}
    try:
        with conn:
            for year,root,manifest,manifest_path in result_attempts(history_root,result_2026):
                coverage=import_result_attempt(conn,year,root,manifest,manifest_path)
                record_coverage(conn,"kra_openapi",manifest,coverage)
                source_rows["race_results"][str(year)]=coverage["response_row_count"]
            for year,root,manifest,manifest_path in trial_attempts(trial_inventory,trial_2026):
                coverage=import_trial_attempt(conn,year,root,manifest,manifest_path)
                record_coverage(conn,"kra_openapi",manifest,coverage)
                source_rows["running_trials"][str(year)]=coverage["response_row_count"]
            cross_reference_result_breed(conn)
            supplement=record_supplemental_examples(conn)
            conn.execute("INSERT OR REPLACE INTO schema_metadata(key,value) VALUES('supplement_examples',?)",(canonical_json(supplement),))
            report=summarize(conn,db_path,source_rows)
            report_path=db_path.with_suffix(".build_manifest.json")
            conn.execute("INSERT OR REPLACE INTO schema_metadata(key,value) VALUES('build_manifest_path',?)",(safe_relative(report_path),))
        conn.execute("PRAGMA optimize")
        conn.close()
        # Atomic no-overwrite publication: if another build won the race, keep its DB.
        os.link(temp_path,db_path)
        temp_path.unlink()
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        return report_path
    except BaseException:
        try:
            conn.close()
        except Exception:
            pass
        temp_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database",type=Path,default=DEFAULT_DB)
    parser.add_argument("--results-history",type=Path,default=REPO_ROOT/"jeju/research/20260929_api4_3_history_backfill/attempts/20260929T132522.134266Z")
    parser.add_argument("--results-2026",type=Path,default=REPO_ROOT/"jeju/research/20260929_core_collection_inventory/raw/2026/attempts/20260929T132618.518555Z")
    parser.add_argument("--trials-inventory",type=Path,default=REPO_ROOT/"jeju/research/20260929_trial_api_backfill_2003_2025/collection_inventory.json")
    parser.add_argument("--trials-2026",type=Path,default=REPO_ROOT/"jeju/research/20260929_core_collection_inventory/raw/trials/2026/attempts/20260929T132644.423798Z")
    args=parser.parse_args()
    report=build(args)
    print(json.dumps({"database":safe_relative(args.database.resolve()),"build_manifest":safe_relative(report)},ensure_ascii=False))


if __name__ == "__main__":
    main()
