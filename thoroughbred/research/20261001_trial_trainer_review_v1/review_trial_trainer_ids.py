"""Audit missing API20_1 trainer IDs against KRA trial score pages and local RPTs.

The core DuckDB is opened read-only. Source trainer fields are never changed.
Only an exact KRA event header, official program number, official horse ID link,
and actual trainer profile link can produce a supplemental ID for a '-' source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CORE_DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
RAW_DIR = HERE / "raw_official_trainer_scores"
CAPTURE_MANIFEST = HERE / "official_score_page_captures.json"
SEED_MANIFEST = HERE / "official_score_capture_seed.json"
URL = "https://race.kra.co.kr/referee/RacingTrainCheckScoreTable.do"
MAX_RESPONSE_BYTES = 5_000_000
MAX_WORKERS = 2
MIN_REQUEST_START_INTERVAL_SECONDS = 0.4
HORSE_LINK = re.compile(r"goPage1\('([^']+)'\s*,\s*'([^']+)'\s*\)")
TRAINER_LINK = re.compile(r"goPage3\('([^']+)'\s*,\s*'(\d+)'\s*\)")
TIME_VALUE = re.compile(r"^(\d+):(\d{2})\.(\d+)$")
RESULT_STATUSES = {
    "합격", "불합격", "합격유보", "출주취소", "출전취소", "출전제외",
    "연습취소", "연습제외", "심사취소", "검사취소", "연습주행", "주행연습",
}
MEET_TITLE = {1: "서울경마", 3: "영남경마"}

# Reuse the repository's established fixed-host KRA request and table parser.
JOCKEY_AUDIT_DIR = ROOT / "thoroughbred/research/20260930_trial_jockey_gap_audit_v1"
sys.path.insert(0, str(JOCKEY_AUDIT_DIR))
from fetch_official_web_name_conflicts_18 import (  # noqa: E402
    get_score_page,
    seconds_from_time,
)

sys.path.insert(0, str(ROOT / "src"))
from horse_racing.parsers.running_trials import parse_running_trial_report  # noqa: E402

sys.path.insert(0, str(JOCKEY_AUDIT_DIR))
from build_audit import parse_rpt  # noqa: E402

_rate_lock = threading.Lock()
_next_request_start = 0.0


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def capture_key(meet: int, date: str, trial_no: int) -> str:
    return f"{meet}|{date}|{trial_no}"


def capture_path(meet: int, date: str, trial_no: int) -> Path:
    return RAW_DIR / f"meet_{meet}_date_{date}_trial_{trial_no}.html"


def normalize_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


class PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.in_th = False
        self.title_parts: list[str] = []
        self.th_parts: list[str] = []
        self.headers: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self.in_title = True
            self.title_parts = []
        elif tag.lower() == "th":
            self.in_th = True
            self.th_parts = []

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.in_th:
            self.th_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title" and self.in_title:
            self.in_title = False
        elif tag.lower() == "th" and self.in_th:
            self.in_th = False
            self.headers.append(normalize_text("".join(self.th_parts)))


def score_table_rows(payload: bytes, meet: int, date: str, trial_no: int) -> dict[str, Any]:
    if meet not in MEET_TITLE or not re.fullmatch(r"20\d{6}", date) or not 1 <= trial_no <= 20:
        raise ValueError("Unexpected official score request key")
    html = payload.decode("euc-kr", errors="replace")
    page_text = PageTextParser()
    page_text.feed(html)
    title = normalize_text("".join(page_text.title_parts))
    date_label = f"{date[:4]}년 {int(date[4:6]):02d}월 {int(date[6:]):02d}일"
    expected_header = f"{date_label} {trial_no}경주"
    exact_headers = [header for header in page_text.headers if header == expected_header]

    # The import is deliberately local to avoid altering the older audit module.
    from fetch_official_web_name_conflicts_18 import ScoreTableParser

    parser = ScoreTableParser()
    parser.feed(html)
    tables = [table for table in parser.tables if "주행심사결과를 순위" in table["caption"]]
    if len(tables) != 1:
        return {
            "title": title,
            "expected_header": expected_header,
            "matching_header_count": len(exact_headers),
            "table_found": False,
            "rows": [],
        }

    rows = []
    for cells in tables[0]["rows"]:
        if len(cells) < 10 or not cells[1]["text"].isdigit():
            continue
        horse_link_text = " ".join(cells[2]["onclick"])
        trainer_link_text = " ".join(cells[9]["onclick"])
        horse_match = HORSE_LINK.search(horse_link_text)
        trainer_match = TRAINER_LINK.search(trainer_link_text)
        text_values = [cell["text"] for cell in cells]
        time_values = [value for value in text_values if TIME_VALUE.fullmatch(value)]
        status_values = [value for value in text_values if value in RESULT_STATUSES]
        rows.append({
            "official_horse_program_no": int(cells[1]["text"]),
            "official_horse_name": cells[2]["text"] or None,
            "official_horse_id": horse_match.group(1) if horse_match else None,
            "official_horse_profile_link": horse_link_text or None,
            "official_jockey_name": cells[8]["text"] or None,
            "official_trainer_name": cells[9]["text"] or None,
            "official_trainer_id": trainer_match.group(1) if trainer_match else None,
            "official_trainer_profile_meet": int(trainer_match.group(2)) if trainer_match else None,
            "official_trainer_profile_link": trainer_link_text or None,
            "official_finish_time": time_values[0] if time_values else None,
            "official_finish_time_seconds": seconds_from_time(time_values[0]) if time_values else None,
            "official_result_status": status_values[-1] if status_values else None,
            "official_row_text": " ".join(value for value in text_values if value),
        })
    return {
        "title": title,
        "expected_header": expected_header,
        "matching_header_count": len(exact_headers),
        "table_found": True,
        "rows": rows,
    }


def load_capture_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if CAPTURE_MANIFEST.exists():
        data = json.loads(CAPTURE_MANIFEST.read_text(encoding="utf-8"))
        for item in data.get("captures", []):
            index[capture_key(item["meet"], item["date"], item["trial_no"])] = item
    if SEED_MANIFEST.exists():
        item = json.loads(SEED_MANIFEST.read_text(encoding="utf-8"))
        form = item["request_form"]
        index.setdefault(capture_key(int(form["meet"]), form["date"], int(form["trno"])), {
            "meet": int(form["meet"]),
            "date": form["date"],
            "trial_no": int(form["trno"]),
            "source_file": item["raw_file"],
            "raw_sha256": item["raw_sha256"],
            "captured_at_utc": item["captured_at_utc"],
            "request_form": form,
            "capture_source": "official_page_saved_before_script_run",
        })
    return index


def rate_limit() -> None:
    global _next_request_start
    with _rate_lock:
        now = time.monotonic()
        if now < _next_request_start:
            time.sleep(_next_request_start - now)
            now = time.monotonic()
        _next_request_start = now + MIN_REQUEST_START_INTERVAL_SECONDS


def capture_one(meet: int, date: str, trial_no: int,
                prior_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key = capture_key(meet, date, trial_no)
    path = capture_path(meet, date, trial_no)
    existing = prior_index.get(key)
    if path.exists() and existing:
        payload = path.read_bytes()
        digest = sha256_bytes(payload)
        if digest == existing.get("raw_sha256"):
            parsed = score_table_rows(payload, meet, date, trial_no)
            return {
                **existing,
                "source_file": relative(path),
                "raw_sha256": digest,
                "capture_source": existing.get("capture_source", "same_review_capture_cache"),
                "page_title": parsed["title"],
                "page_header": parsed["expected_header"] if parsed["matching_header_count"] == 1 else None,
                "page_header_exact_count": parsed["matching_header_count"],
                "score_table_found": parsed["table_found"],
                "score_rows": len(parsed["rows"]),
            }
        raise ValueError(f"Capture cache hash mismatch for {key}")

    for attempt in range(3):
        try:
            rate_limit()
            captured_at = utc_now()
            payload = get_score_page(meet, date, trial_no)
            parsed = score_table_rows(payload, meet, date, trial_no)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_bytes(payload)
            temp.replace(path)
            return {
                "meet": meet,
                "date": date,
                "trial_no": trial_no,
                "source_file": relative(path),
                "raw_sha256": sha256_bytes(payload),
                "raw_bytes": len(payload),
                "captured_at_utc": captured_at,
                "official_score_url": URL,
                "request_method": "POST",
                "request_form": {"meet": meet, "date": date, "trno": trial_no,
                                 "Act": "06", "Sub": "7"},
                "capture_source": "fetched_from_official_kra_web",
                "page_title": parsed["title"],
                "page_header": parsed["expected_header"] if parsed["matching_header_count"] == 1 else None,
                "page_header_exact_count": parsed["matching_header_count"],
                "score_table_found": parsed["table_found"],
                "score_rows": len(parsed["rows"]),
            }
        except Exception as exc:
            if attempt == 2:
                return {
                    "meet": meet, "date": date, "trial_no": trial_no,
                    "fetch_error_type": type(exc).__name__,
                    "fetch_error": str(exc)[:300],
                    "captured_at_utc": None,
                    "official_score_url": URL,
                    "request_method": "POST",
                    "request_form": {"meet": meet, "date": date, "trno": trial_no,
                                     "Act": "06", "Sub": "7"},
                }
            time.sleep(1 + attempt)
    raise AssertionError("unreachable")


def load_targets(scope: str) -> list[dict[str, Any]]:
    con = duckdb.connect(str(CORE_DB), read_only=True)
    try:
        rows = con.execute("""
            SELECT p.participant_row_id, p.trial_date, p.source_meet_query,
                   p.api_meet_label, p.api_trainDate, p.api_trainNo, p.api_chulNo,
                   p.api_hrNo, p.api_hrName, p.api_trNo, p.api_trName, p.api_rcTime,
                   p.api_passFlag, p.api_nopassReason, p.api_reason, p.api_ord,
                   p.api_trainDays, p.api_daySerial, p.api_track, p.api_weather,
                   p.source_file, p.source_file_sha256, p.source_item_index,
                   p.source_record_json, r.resolved_horse_id, r.resolved_horse_name,
                   r.horse_identity_resolution
            FROM trial_participants AS p
            LEFT JOIN trial_participants_resolved AS r USING (participant_row_id)
            WHERE p.api_trNo IN ('-', '0AAAAA')
            ORDER BY p.api_trainDate, p.source_meet_query,
                     TRY_CAST(p.api_trainNo AS INTEGER), TRY_CAST(p.api_chulNo AS INTEGER),
                     p.participant_row_id
        """).fetchall()
    finally:
        con.close()

    columns = [
        "participant_row_id", "trial_date", "source_meet_query", "api_meet_label",
        "api_trainDate", "api_trainNo", "api_chulNo", "api_hrNo", "api_hrName",
        "api_trNo", "api_trName", "api_rcTime", "api_passFlag", "api_nopassReason",
        "api_reason", "api_ord", "api_trainDays", "api_daySerial", "api_track",
        "api_weather", "source_file", "source_file_sha256", "source_item_index",
        "source_record_json", "resolved_horse_id", "resolved_horse_name",
        "horse_identity_resolution",
    ]
    targets = [dict(zip(columns, row)) for row in rows]
    if len(targets) != 224 or len({row["participant_row_id"] for row in targets}) != 224:
        raise ValueError(f"Expected 224 unique trainer-gap rows; found {len(targets)}")
    if Counter(row["api_trNo"] for row in targets) != Counter({"-": 84, "0AAAAA": 140}):
        raise ValueError("Trainer gap source categories changed from the reviewed 84/140 split")
    if scope == "positive20":
        targets = [row for row in targets if row["api_trNo"] == "-" and api_seconds(row["api_rcTime"]) > 0]
        if len(targets) != 20:
            raise ValueError(f"Expected 20 positive-time '-' rows; found {len(targets)}")
    return targets


def api_seconds(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_rpt_review(meet: int, date: str, trial_no: int, program_no: int,
                    target_horse_name: str | None) -> dict[str, Any]:
    path = ROOT / (
        f"data/raw/kra_text/dacom23/meet={meet}/year={date[:4]}"
        f"/month={int(date[4:6]):02d}/day={int(date[6:]):02d}/{date}dacom23.rpt"
    )
    if not path.exists():
        return {"rpt_source_status": "local_rpt_file_absent"}
    payload = path.read_bytes()
    rpt_hash = sha256_bytes(payload)
    try:
        parsed_days = parse_running_trial_report(payload, meet=meet)
        exact_results = [
            result
            for block in parsed_days
            if block.trial_date.strftime("%Y%m%d") == date
            and block.trial_race_number == trial_no
            for result in block.results
            if result.horse_number == program_no
        ]
        line_rows, _ = parse_rpt(path)
        source_lines = [
            item for item in line_rows
            if item["meet"] == meet and item["date"] == date
            and item["trial_no"] == trial_no and item["horse_number"] == program_no
        ]
    except Exception as exc:
        return {
            "rpt_source_status": "local_rpt_parse_error",
            "rpt_source_file": relative(path),
            "rpt_source_sha256": rpt_hash,
            "rpt_parse_error_type": type(exc).__name__,
        }

    if len(exact_results) != 1 or len(source_lines) != 1:
        return {
            "rpt_source_status": "no_unique_local_rpt_event_program_row",
            "rpt_source_file": relative(path),
            "rpt_source_sha256": rpt_hash,
            "rpt_matching_program_rows": len(exact_results),
            "rpt_event_header_match": any(
                block.trial_date.strftime("%Y%m%d") == date and block.trial_race_number == trial_no
                for block in parsed_days
            ),
            "rpt_exact_program_row_absence_is_not_cause_evidence": True,
        }

    result = exact_results[0]
    source_line = source_lines[0]
    return {
        "rpt_source_status": "exact_event_program_row_name_only_support",
        "rpt_source_file": relative(path),
        "rpt_source_sha256": rpt_hash,
        "rpt_source_line_number": source_line["source_line_number"],
        "rpt_source_line_text": source_line["source_line_text"],
        "rpt_horse_number": result.horse_number,
        "rpt_horse_name": result.horse_name,
        "rpt_horse_name_matches_api": result.horse_name == target_horse_name,
        "rpt_trainer_name": result.trainer_name,
        "rpt_jockey_name": result.jockey_name,
        "rpt_finish_time_seconds": (
            result.finish_time_ms / 1000 if result.finish_time_ms is not None else None
        ),
        "rpt_judgement": result.judgement,
        "rpt_failure_reason": result.failure_reason,
        "rpt_inspection_reason": result.inspection_reason,
        "rpt_program_and_event_match": True,
        "rpt_provides_trainer_id": False,
    }


def load_prior_races() -> dict[str, list[dict[str, str]]]:
    con = duckdb.connect(str(CORE_DB), read_only=True)
    try:
        rows = con.execute("""
            SELECT horse_id_raw, result_date, source_meet, result_race_no,
                   source_file, source_item_index
            FROM confirmed_runners
            WHERE execution_status = 'executed_plan_and_result'
              AND horse_id_raw IS NOT NULL AND horse_id_raw <> ''
        """).fetchall()
    finally:
        con.close()
    prior: dict[str, list[dict[str, str]]] = defaultdict(list)
    for horse_id, date, meet, race_no, source_file, item_index in rows:
        prior[str(horse_id)].append({
            "date": str(date), "meet": str(meet), "race_no": str(race_no),
            "source_file": str(source_file), "source_item_index": str(item_index),
        })
    return prior


def load_core_trainer_roster_ids() -> set[str]:
    con = duckdb.connect(str(CORE_DB), read_only=True)
    try:
        rows = con.execute("""
            SELECT entity_id_official_string
            FROM entity_reference_roster
            WHERE entity_type = 'trainer'
        """).fetchall()
    finally:
        con.close()
    return {str(row[0]) for row in rows if row[0] is not None}


def period_evidence(target: dict[str, Any], prior_races: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    horse_id = target.get("resolved_horse_id") or target.get("api_hrNo")
    trial_date = target.get("api_trainDate")
    candidates = [
        item for item in prior_races.get(str(horse_id), [])
        if item["date"] < str(trial_date)
    ] if horse_id and trial_date else []
    if not candidates:
        return {
            "prior_confirmed_race_date": None,
            "days_since_prior_confirmed_race": None,
            "prior_race_window_status": "no_prior_confirmed_runner_in_core_coverage",
        }
    last_race = max(candidates, key=lambda item: (item["date"], item["meet"], item["race_no"]))
    date_gap = (
        datetime.strptime(str(trial_date), "%Y%m%d").date()
        - datetime.strptime(last_race["date"], "%Y%m%d").date()
    ).days
    return {
        "prior_confirmed_race_date": last_race["date"],
        "days_since_prior_confirmed_race": date_gap,
        "prior_race_meet": last_race["meet"],
        "prior_race_no": last_race["race_no"],
        "prior_race_source_file": last_race["source_file"],
        "prior_race_source_item_index": last_race["source_item_index"],
        "prior_race_window_status": "derived_from_last_earlier_confirmed_runner",
    }


def review_target(target: dict[str, Any], capture: dict[str, Any],
                  prior_races: dict[str, list[dict[str, str]]],
                  core_trainer_ids: set[str], scope: str) -> dict[str, Any]:
    meet = int(target["source_meet_query"])
    date = str(target["api_trainDate"])
    trial_no = int(target["api_trainNo"])
    program_no = int(target["api_chulNo"])
    capture_file = ROOT / capture["source_file"] if capture.get("source_file") else None
    payload = capture_file.read_bytes() if capture_file and capture_file.exists() else None
    parsed = score_table_rows(payload, meet, date, trial_no) if payload else {
        "title": None, "expected_header": None, "matching_header_count": 0,
        "table_found": False, "rows": [],
    }
    expected_meet_title = MEET_TITLE[meet]
    page_title = parsed["title"]
    page_header_exact = parsed["matching_header_count"] == 1
    meet_title_exact = page_title is not None and expected_meet_title in page_title
    event_echo_exact = page_header_exact and meet_title_exact and parsed["table_found"]

    source_api_horse_id = target.get("api_hrNo")
    resolved_horse_id = target.get("resolved_horse_id")
    match_horse_id = resolved_horse_id or source_api_horse_id
    api_resolved_horse_id_consistent = (
        not source_api_horse_id or not resolved_horse_id
        or str(source_api_horse_id) == str(resolved_horse_id)
    )
    same_program_rows = [
        row for row in parsed["rows"] if row["official_horse_program_no"] == program_no
    ]
    exact_horse_rows = [
        row for row in same_program_rows
        if match_horse_id and row["official_horse_id"] == str(match_horse_id)
    ]
    exact_event_row = exact_horse_rows[0] if len(exact_horse_rows) == 1 and event_echo_exact else None
    exact_horse_row_match = exact_event_row is not None and api_resolved_horse_id_consistent

    api_time = api_seconds(target.get("api_rcTime"))
    official_time = exact_event_row.get("official_finish_time_seconds") if exact_event_row else None
    if exact_event_row is None or api_time is None:
        time_match: bool | None = None
    elif api_time > 0:
        time_match = official_time is not None and round(api_time, 1) == round(official_time, 1)
    else:
        time_match = official_time is None or round(official_time, 1) == 0.0
    source_result = target.get("api_passFlag")
    official_result = exact_event_row.get("official_result_status") if exact_event_row else None
    if exact_event_row is None:
        result_status_match = None
    elif source_result in (None, "", "-"):
        result_status_match = None
    else:
        result_status_match = source_result == official_result

    trainer_id = exact_event_row.get("official_trainer_id") if exact_event_row else None
    trainer_name = exact_event_row.get("official_trainer_name") if exact_event_row else None
    trainer_link = exact_event_row.get("official_trainer_profile_link") if exact_event_row else None
    trainer_profile_meet = exact_event_row.get("official_trainer_profile_meet") if exact_event_row else None
    trainer_profile_link_observed = bool(
        trainer_id and trainer_name and trainer_link and trainer_profile_meet is not None
    )
    trainer_profile_link_present = bool(
        trainer_profile_link_observed and trainer_id.isdigit()
        and trainer_id not in {"0", "0AAAAA"} and trainer_name not in {"-", "휴양마"}
    )
    official_time_matches_api = time_match is True

    source_trainer_id = str(target["api_trNo"])
    source_trainer_name = str(target["api_trName"])
    verified_id = None
    verified_name = None
    if source_trainer_id == "-":
        if exact_horse_row_match and official_time_matches_api and trainer_profile_link_present:
            verified_id = trainer_id
            verified_name = trainer_name
            review_status = "verified_supplemental_trainer_id_from_exact_official_event_row"
        elif exact_horse_row_match and not official_time_matches_api:
            review_status = "exact_event_horse_row_api_official_time_conflict"
        elif exact_horse_row_match and trainer_profile_link_observed and trainer_id in {"0", "0AAAAA"}:
            review_status = "official_row_nonperson_sentinel_for_missing_source_id"
        elif exact_horse_row_match:
            review_status = "exact_event_horse_row_has_no_valid_trainer_profile_link"
        elif same_program_rows:
            review_status = "official_program_row_horse_id_does_not_match_source_identity"
        elif capture.get("fetch_error"):
            review_status = "official_page_fetch_error"
        elif event_echo_exact:
            review_status = "official_event_page_has_no_source_program_row"
        else:
            review_status = "official_event_page_echo_or_score_table_unverified"
    else:
        if (exact_horse_row_match and trainer_profile_link_observed
                and trainer_id == source_trainer_id and trainer_name == source_trainer_name):
            review_status = "confirmed_same_nonperson_placeholder"
        elif exact_horse_row_match and official_time_matches_api and trainer_profile_link_present:
            review_status = "source_placeholder_conflicts_with_official_event_person_link"
        elif exact_horse_row_match and not official_time_matches_api:
            review_status = "source_placeholder_exact_event_row_api_official_time_conflict"
        elif exact_horse_row_match and trainer_profile_link_observed:
            review_status = "source_placeholder_conflicts_with_official_link_values_unresolved"
        elif exact_horse_row_match:
            review_status = "source_placeholder_exact_row_has_no_valid_trainer_profile_link"
        elif same_program_rows:
            review_status = "source_placeholder_and_official_program_horse_id_conflict"
        elif capture.get("fetch_error"):
            review_status = "source_placeholder_official_page_fetch_error"
        elif event_echo_exact:
            review_status = "source_placeholder_official_event_row_not_found"
        else:
            review_status = "source_placeholder_event_page_echo_or_table_unverified"

    try:
        source_record = json.loads(target.get("source_record_json") or "{}")
    except json.JSONDecodeError:
        source_record = {}
    raw_id = source_record.get("trNo")
    raw_name = source_record.get("trName")
    raw_source_fields_match = (
        str(raw_id) == source_trainer_id and str(raw_name) == source_trainer_name
    )

    rpt = load_rpt_review(meet, date, trial_no, program_no,
                          target.get("resolved_horse_name") or target.get("api_hrName"))
    row = {
        "participant_row_id": target["participant_row_id"],
        "meet": meet,
        "date": date,
        "trial_no": trial_no,
        "horse_program_no": program_no,
        "api_meet_label": target.get("api_meet_label"),
        "api_horse_id": source_api_horse_id,
        "api_horse_name": target.get("api_hrName"),
        "resolved_horse_id": resolved_horse_id,
        "resolved_horse_name": target.get("resolved_horse_name"),
        "horse_identity_resolution": target.get("horse_identity_resolution"),
        "api_resolved_horse_id_consistent": api_resolved_horse_id_consistent,
        "source_trNo": source_trainer_id,
        "source_trName": source_trainer_name,
        "source_record_json_trainer_fields_match": raw_source_fields_match,
        "source_record_json_sha256": sha256_bytes((target.get("source_record_json") or "").encode("utf-8")),
        "source_api_file": target.get("source_file"),
        "source_api_file_sha256": target.get("source_file_sha256"),
        "source_api_item_index": target.get("source_item_index"),
        "source_api_pointer": f"{target.get('source_file')}#item={target.get('source_item_index')}",
        "api_rcTime": target.get("api_rcTime"),
        "api_passFlag": target.get("api_passFlag"),
        "api_nopassReason": target.get("api_nopassReason"),
        "api_reason": target.get("api_reason"),
        "api_ord": target.get("api_ord"),
        "api_trainDays": target.get("api_trainDays"),
        "api_daySerial": target.get("api_daySerial"),
        "api_track": target.get("api_track"),
        "api_weather": target.get("api_weather"),
        "prior_confirmed_race_date": None,
        "days_since_prior_confirmed_race": None,
        "prior_race_window_status": None,
        "official_page_title": page_title,
        "official_page_header_expected": parsed["expected_header"],
        "official_page_header_exact_count": parsed["matching_header_count"],
        "official_page_meet_title_expected": expected_meet_title,
        "official_event_echo_exact": event_echo_exact,
        "official_score_table_found": parsed["table_found"],
        "official_same_program_rows_count": len(same_program_rows),
        "official_exact_horse_id_row_count": len(exact_horse_rows),
        "official_exact_event_row_match": exact_horse_row_match,
        "official_horse_program_no": exact_event_row.get("official_horse_program_no") if exact_event_row else None,
        "official_horse_id": exact_event_row.get("official_horse_id") if exact_event_row else None,
        "official_horse_name": exact_event_row.get("official_horse_name") if exact_event_row else None,
        "official_horse_profile_link": exact_event_row.get("official_horse_profile_link") if exact_event_row else None,
        "official_trainer_id_observed": trainer_id,
        "official_trainer_name_observed": trainer_name,
        "official_trainer_profile_link": trainer_link,
        "official_trainer_profile_meet": trainer_profile_meet,
        "official_trainer_profile_link_observed": trainer_profile_link_observed,
        "official_trainer_profile_link_present": trainer_profile_link_present,
        "official_trainer_id_in_core_event_roster": trainer_id in core_trainer_ids if trainer_id else None,
        "verified_supplemental_trainer_id": verified_id,
        "verified_supplemental_trainer_name": verified_name,
        "official_time": exact_event_row.get("official_finish_time") if exact_event_row else None,
        "official_time_seconds": official_time,
        "api_official_time_match": time_match,
        "official_result_status": official_result,
        "api_official_result_status_match": result_status_match,
        "official_row_text": exact_event_row.get("official_row_text") if exact_event_row else None,
        "official_program_candidate_rows": [
            {"horse_id": item["official_horse_id"],
             "horse_name": item["official_horse_name"],
             "trainer_name": item["official_trainer_name"],
             "trainer_id": item["official_trainer_id"],
             "row_text": item["official_row_text"]}
            for item in same_program_rows
        ],
        "official_web_source_file": capture.get("source_file"),
        "official_web_source_sha256": capture.get("raw_sha256"),
        "official_web_captured_at_utc": capture.get("captured_at_utc"),
        "official_web_request_method": capture.get("request_method"),
        "official_web_request_form": capture.get("request_form"),
        "official_web_capture_source": capture.get("capture_source"),
        "review_status": review_status,
        "id_fill_rule": "Only '-' source rows with exact official event header + same program number + same resolved horse ID + actual goPage3 trainer link are filled. Preserve goPage3 profile meet separately; it need not equal the event meet. 0AAAAA/휴양마 remain placeholders even if KRA shows a person link.",
        **rpt,
        **period_evidence(target, prior_races),
    }
    return row


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    payload = ("\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                         for row in rows) + ("\n" if rows else "")).encode("utf-8")
    path.write_bytes(payload)
    return sha256_bytes(payload)


def summarize(rows: list[dict[str, Any]], captures: list[dict[str, Any]]) -> dict[str, Any]:
    def distribution(field: str, subset: list[dict[str, Any]]) -> dict[str, int]:
        counts = Counter(str(row.get(field)) for row in subset)
        return dict(sorted(counts.items(), key=lambda item: item[0]))

    minus_rows = [row for row in rows if row["source_trNo"] == "-"]
    placeholder_rows = [row for row in rows if row["source_trNo"] == "0AAAAA"]
    exact_rpt = sum(row.get("rpt_source_status") == "exact_event_program_row_name_only_support" for row in rows)
    return {
        "rows": len(rows),
        "source_trainer_categories": distribution("source_trNo", rows),
        "review_status": distribution("review_status", rows),
        "verified_supplemental_trainer_id_rows": sum(bool(row.get("verified_supplemental_trainer_id")) for row in rows),
        "placeholder_rows_with_official_person_link_but_not_filled": sum(
            row["source_trNo"] == "0AAAAA" and bool(row.get("official_trainer_profile_link_present"))
            for row in rows
        ),
        "placeholder_rows_with_official_link_observed_but_not_filled": sum(
            row["source_trNo"] == "0AAAAA" and bool(row.get("official_trainer_profile_link_observed"))
            for row in rows
        ),
        "placeholder_rows_matching_official_placeholder_link": sum(
            row["source_trNo"] == "0AAAAA"
            and row.get("official_trainer_id_observed") == row.get("source_trNo")
            and row.get("official_trainer_name_observed") == row.get("source_trName")
            and bool(row.get("official_trainer_profile_link_observed"))
            for row in rows
        ),
        "verified_supplemental_trainer_ids_unique": sorted({
            row["verified_supplemental_trainer_id"] for row in rows
            if row.get("verified_supplemental_trainer_id")
        }),
        "verified_supplemental_trainer_ids_not_in_core_event_roster": sorted({
            row["verified_supplemental_trainer_id"] for row in rows
            if row.get("verified_supplemental_trainer_id")
            and row.get("official_trainer_id_in_core_event_roster") is False
        }),
        "exact_official_event_horse_rows": sum(bool(row.get("official_exact_event_row_match")) for row in rows),
        "official_page_echo_and_table_verified_sessions": sum(
            item.get("page_header_exact_count") == 1 and item.get("score_table_found") is True
            and MEET_TITLE[item["meet"]] in str(item.get("page_title"))
            for item in captures
        ),
        "official_page_fetch_errors": sum(bool(item.get("fetch_error")) for item in captures),
        "captured_official_page_sessions": len(captures),
        "local_rpt_exact_event_program_rows": exact_rpt,
        "local_rpt_status": distribution("rpt_source_status", rows),
        "source_reason": distribution("api_reason", rows),
        "source_nopass_reason": distribution("api_nopassReason", rows),
        "source_result_status": distribution("api_passFlag", rows),
        "source_rcTime_raw": distribution("api_rcTime", rows),
        "source_ord_raw": distribution("api_ord", rows),
        "source_trainDays_raw": distribution("api_trainDays", rows),
        "minus84_reason": distribution("api_reason", minus_rows),
        "placeholder140_reason": distribution("api_reason", placeholder_rows),
        "placeholder140_nopass_reason": distribution("api_nopassReason", placeholder_rows),
        "placeholder140_result_status": distribution("api_passFlag", placeholder_rows),
        "placeholder140_rcTime_raw": distribution("api_rcTime", placeholder_rows),
        "placeholder140_ord_raw": distribution("api_ord", placeholder_rows),
        "derived_prior_race_gap_days_summary": {
            "with_prior_confirmed_race": sum(row.get("days_since_prior_confirmed_race") is not None for row in rows),
            "without_prior_confirmed_race_in_core_coverage": sum(row.get("days_since_prior_confirmed_race") is None for row in rows),
            "meaning": "Calendar days from the last earlier confirmed runner in core DB coverage. This is a descriptive gap, not a claim of an official rest period or recovery duration.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=("positive20", "all"), default="all")
    args = parser.parse_args()
    targets = load_targets(args.scope)
    groups: dict[tuple[int, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in targets:
        groups[(int(row["source_meet_query"]), str(row["api_trainDate"]), int(row["api_trainNo"]))].append(row)

    capture_index = load_capture_index()
    event_keys = sorted(groups, key=lambda key: (
        0 if key[0] == 1 else 1, key[1], key[2]
    ))
    print(f"scope={args.scope} targets={len(targets)} sessions={len(event_keys)}", flush=True)
    capture_records: dict[tuple[int, str, int], dict[str, Any]] = {}
    errors = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(capture_one, meet, date, trial_no, capture_index): (meet, date, trial_no)
            for meet, date, trial_no in event_keys
        }
        for done, future in enumerate(as_completed(futures), 1):
            event_key = futures[future]
            try:
                capture = future.result()
            except Exception as exc:
                capture = {
                    "meet": event_key[0], "date": event_key[1], "trial_no": event_key[2],
                    "fetch_error_type": type(exc).__name__, "fetch_error": str(exc)[:300],
                    "captured_at_utc": None,
                    "request_method": "POST",
                    "request_form": {"meet": event_key[0], "date": event_key[1],
                                     "trno": event_key[2], "Act": "06", "Sub": "7"},
                }
            capture_records[event_key] = capture
            if capture.get("fetch_error"):
                errors.append(capture)
            if done % 10 == 0 or done == len(event_keys):
                print(f"sessions={done}/{len(event_keys)} errors={len(errors)}", flush=True)

    captures = [capture_records[key] for key in sorted(capture_records)]
    CAPTURE_MANIFEST.write_text(json.dumps({
        "official_score_url": URL,
        "request_method": "POST",
        "request_parameters": ["meet", "date", "trno", "Act", "Sub"],
        "captures": captures,
        "fetch_errors": errors,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    prior_races = load_prior_races()
    core_trainer_ids = load_core_trainer_roster_ids()
    reviewed = []
    for target in targets:
        key = (int(target["source_meet_query"]), str(target["api_trainDate"]), int(target["api_trainNo"]))
        reviewed.append(review_target(target, capture_records[key], prior_races,
                                      core_trainer_ids, args.scope))
    reviewed.sort(key=lambda row: row["participant_row_id"])
    output_name = "trial_trainer_gap_positive20_review.jsonl" if args.scope == "positive20" else "trial_trainer_gap_review.jsonl"
    output_path = HERE / output_name
    ledger_hash = write_jsonl(output_path, reviewed)
    summary = summarize(reviewed, captures)
    summary["scope"] = args.scope
    summary["ledger"] = relative(output_path)
    summary["ledger_sha256"] = ledger_hash
    summary["capture_manifest"] = relative(CAPTURE_MANIFEST)
    summary["capture_manifest_sha256"] = sha256_bytes(CAPTURE_MANIFEST.read_bytes())
    summary_path = HERE / ("trial_trainer_gap_positive20_summary.json" if args.scope == "positive20" else "trial_trainer_gap_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if errors:
        sys.exit(2)


if __name__ == "__main__":
    main()
