"""Load the frozen API21 starting-exam candidates and 21 API42 profiles.

This loader reads local collection artifacts only. It has no network client and
requires an explicit SQLite path. Source pages and candidate items are checked
against their frozen hashes, attempt manifests, and one-based item indexes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "jeju/research/20261002_starting_exam_db_load"
MIGRATION_PATH = OUTPUT_DIR / "20261002_add_starting_exam_api_rows.sql"
API21_DIR = REPO_ROOT / "jeju/research/20261001_starting_exam_api_collection"
API21_CANDIDATE_PATH = API21_DIR / "api21_verified_native_candidate_rows.jsonl"
API21_SUCCESS_REPORT_PATH = API21_DIR / "api21_successful_collection_report.json"
API21_VERIFICATION_PATH = API21_DIR / "api21_independent_verification.json"
API21_COLLECTION_MANIFEST_PATH = API21_DIR / "collection_manifest.json"
API42_SUMMARY_PATH = API21_DIR / "api42_followup_summary.json"
API42_ATTEMPT_DIR = API21_DIR / "raw/api42_followup/attempts/20261001T151147.863223Z"
EXCLUSIONS_PATH = REPO_ROOT / "jeju/data/horse_exclusions.json"

API21_OPERATION = "startingTestResult_1"
API21_DATASET_ID = "15057405"
API21_DATASET_NAME = "한국마사회 출발심사 결과"
API21_ENDPOINT = "https://apis.data.go.kr/B551015/API21_1/startingTestResult_1"
API42_OPERATION = "totalHorseInfo_1"
API42_DATASET_ID = "15057985"
API42_DATASET_NAME = "한국마사회 마필종합 상세정보"
API42_ENDPOINT = "https://apis.data.go.kr/B551015/API42_1/totalHorseInfo_1"
API21_PARSER_VERSION = "jeju-api21-starting-exam-import-v1"
API42_PARSER_VERSION = "jeju-api42-followup-profile-import-v1"
IMPORT_BATCH_ID = "api21_starting_exam_candidate_load_20261002"
EXPECTED_CANDIDATE_SHA256 = "4965639c7e39c5e1c458bf530106ffb3c9f18f64634444e5720cb1df616a38d1"
EXPECTED_API21_ROWS = 10_664
EXPECTED_HORSES = 4_636
EXPECTED_API42_PROFILES = 21
ANALYSIS_CUTOFF = "2026-09-19"
SMALL_BEAR_ID = "3005648"

API21_FIELDS = (
    "meet", "trainDate", "daySerial", "trainNo", "chulNo", "hrName", "hrNo",
    "name", "sex", "age", "rider", "trName", "trNo", "owName", "owNo",
    "passFlag", "reason", "nopassReason",
)
API21_COLUMN_BY_SOURCE = {
    "meet": "meet_raw",
    "trainDate": "train_date_raw",
    "daySerial": "day_serial_raw",
    "trainNo": "train_no_raw",
    "chulNo": "chul_no_raw",
    "hrName": "hr_name_raw",
    "hrNo": "hr_no_raw",
    "name": "name_raw",
    "sex": "sex_raw",
    "age": "age_raw",
    "rider": "rider_raw",
    "trName": "tr_name_raw",
    "trNo": "tr_no_raw",
    "owName": "ow_name_raw",
    "owNo": "ow_no_raw",
    "passFlag": "pass_flag_raw",
    "reason": "reason_raw",
    "nopassReason": "nopass_reason_raw",
}
API21_ROW_COLUMNS = (
    "api_record_id", "source_artifact_id", "source_row_no", "event_key", "exam_date",
    "horse_id", "meet_raw", "train_date_raw", "day_serial_raw", "train_no_raw",
    "chul_no_raw", "hr_name_raw", "hr_no_raw", "name_raw", "sex_raw", "age_raw",
    "rider_raw", "tr_name_raw", "tr_no_raw", "trainer_id_normalized", "ow_name_raw",
    "ow_no_raw", "pass_flag_raw", "judgment_label_normalized", "judgment_status",
    "reason_raw", "nopass_reason_raw", "raw_key_presence_json", "raw_key_absence_json",
)
EXPECTED_TABLE_COLUMNS = (
    "starting_exam_api_row_id", *API21_ROW_COLUMNS,
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"Expected an object in {path.name}:{line_no}")
        rows.append(value)
    return rows


def iso_now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def raw_text(value: Any) -> str | None:
    return None if value is None else str(value)


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def project_relative(path: Path, repo: Path) -> str:
    return path.resolve(strict=True).relative_to(repo.resolve(strict=True)).as_posix()


def safe_local_path(base: Path, relative: str) -> Path:
    rel = PurePosixPath(relative)
    if not relative or rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError("A frozen source path is not a safe relative path")
    resolved_base = base.resolve(strict=True)
    candidate = base.joinpath(*rel.parts).resolve(strict=True)
    candidate.relative_to(resolved_base)
    if not candidate.is_file():
        raise ValueError("A frozen source path does not name a regular file")
    return candidate


def response_items(payload: Any) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ValueError("Source response root is not an object")
    wrapper = payload.get("response", payload)
    if not isinstance(wrapper, dict):
        raise ValueError("Source response wrapper is not an object")
    header, body = wrapper.get("header"), wrapper.get("body")
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError("Source response header or body is missing")
    item_value = body.get("items")
    if isinstance(item_value, dict):
        item_value = item_value.get("item")
    if item_value is None:
        rows: list[dict[str, Any]] = []
    elif isinstance(item_value, dict):
        rows = [item_value]
    elif isinstance(item_value, list) and all(isinstance(item, dict) for item in item_value):
        rows = item_value
    else:
        raise ValueError("Source response items have an unsupported shape")
    return header, body, rows


def source_page_request_params(url: str) -> dict[str, str]:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "apis.data.go.kr":
        raise ValueError("Source page manifest has an unexpected public endpoint")
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    if any("key" in key.lower() for key in params):
        raise ValueError("A source URL contains an authentication parameter")
    return params


def make_api21_event(raw: dict[str, Any]) -> tuple[str, str, str]:
    required = ("trainDate", "meet", "trainNo", "hrNo")
    if any(key not in raw or raw[key] is None for key in required):
        raise ValueError("An API21 candidate is missing a required event key")
    raw_date = clean(raw["trainDate"])
    if not re.fullmatch(r"\d{8}", raw_date):
        raise ValueError("An API21 trainDate is not an eight-digit date")
    event_date = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8])).isoformat()
    meet = clean(raw["meet"])
    horse_id = clean(raw["hrNo"])
    if not meet or not re.fullmatch(r"\d+", horse_id):
        raise ValueError("An API21 candidate has an invalid venue or official horse ID")
    natural_values = [event_date, meet, clean(raw["trainNo"]), raw_text(raw.get("chulNo")), horse_id]
    event_key = canonical_json(natural_values)
    return event_date, horse_id, event_key


def expected_api21_tuple(source_row: dict[str, Any], artifact_id: int, api_record_id: int) -> tuple[Any, ...]:
    raw = source_row["raw"]
    event_date, horse_id, event_key = make_api21_event(raw)
    present = [field for field in API21_FIELDS if field in raw]
    absent = [field for field in API21_FIELDS if field not in raw]
    pass_raw = clean(raw.get("passFlag"))
    judgment_label = None if not pass_raw or pass_raw == "-" else pass_raw
    judgment_status = "unknown" if judgment_label is None else "observed"
    trainer_name = clean(raw.get("trName"))
    trainer_no = clean(raw.get("trNo"))
    trainer_id = trainer_no if trainer_name != "외부마" and re.fullmatch(r"\d{6}", trainer_no) else None
    fields = {column: raw_text(raw.get(source)) for source, column in API21_COLUMN_BY_SOURCE.items()}
    return (
        api_record_id,
        artifact_id,
        int(source_row["source_row_no"]),
        event_key,
        event_date,
        horse_id,
        fields["meet_raw"],
        fields["train_date_raw"],
        fields["day_serial_raw"],
        fields["train_no_raw"],
        fields["chul_no_raw"],
        fields["hr_name_raw"],
        fields["hr_no_raw"],
        fields["name_raw"],
        fields["sex_raw"],
        fields["age_raw"],
        fields["rider_raw"],
        fields["tr_name_raw"],
        fields["tr_no_raw"],
        trainer_id,
        fields["ow_name_raw"],
        fields["ow_no_raw"],
        fields["pass_flag_raw"],
        judgment_label,
        judgment_status,
        fields["reason_raw"],
        fields["nopass_reason_raw"],
        canonical_json(present),
        canonical_json(absent),
    )


def api42_observed_kst_date(timestamp: str) -> str:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("The API42 batch completion timestamp must include a timezone")
    return parsed.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()


def load_api21_inputs(repo: Path) -> dict[str, Any]:
    collection = repo / "jeju/research/20261001_starting_exam_api_collection"
    candidate_path = collection / "api21_verified_native_candidate_rows.jsonl"
    candidate_bytes = candidate_path.read_bytes()
    candidate_sha = sha256_bytes(candidate_bytes)
    if candidate_sha != EXPECTED_CANDIDATE_SHA256:
        raise ValueError("The API21 candidate JSONL differs from the independently verified frozen SHA-256")
    success = read_json(collection / "api21_successful_collection_report.json")
    verification = read_json(collection / "api21_independent_verification.json")
    if success.get("status") != "complete":
        raise ValueError("The API21 collection report is not complete")
    for report in (success.get("independent_verification", {}), verification):
        if report.get("native_candidate_sha256") != EXPECTED_CANDIDATE_SHA256:
            raise ValueError("The API21 candidate SHA-256 does not match its collection report")
        if report.get("linked_native_rows") != EXPECTED_API21_ROWS or report.get("linked_native_horses") != EXPECTED_HORSES:
            raise ValueError("The API21 collection report counts differ from the approved candidate scope")

    rows = read_jsonl(candidate_path)
    if len(rows) != EXPECTED_API21_ROWS:
        raise ValueError("The API21 candidate row count differs from the approved scope")
    excluded = read_json(repo / "jeju/data/horse_exclusions.json").get("horses", {})
    excluded_ids = {
        str(horse_id) for horse_id, entry in excluded.items()
        if isinstance(entry, dict) and entry.get("reimport_allowed") is False
    }
    candidate_ids = {make_api21_event(row["raw"])[1] for row in rows}
    if len(candidate_ids) != EXPECTED_HORSES:
        raise ValueError("The API21 candidate horse count differs from the approved scope")
    if candidate_ids & excluded_ids or SMALL_BEAR_ID in candidate_ids:
        raise ValueError("An excluded horse appears in the API21 candidate rows; refusing to reimport it")

    page_index: dict[str, dict[str, Any]] = {}
    partition_root = collection / "raw/api21_1/partitions"
    manifest_paths = sorted(partition_root.glob("year_*/attempts/*/attempt_manifest.json"))
    if not manifest_paths:
        raise ValueError("No local API21 page attempt manifests were found")
    for manifest_path in manifest_paths:
        manifest = read_json(manifest_path)
        if manifest.get("status") != "completed_api_response" or manifest.get("operation") != API21_OPERATION:
            continue
        attempt_dir = manifest_path.parent
        for page in manifest.get("source_pages", []):
            if page.get("status") != "completed" or page.get("status_code") != 200 or page.get("api_result_code") not in {"00", "0000"}:
                continue
            source_path = (attempt_dir / str(page["response_file"])).resolve(strict=True)
            source_rel = source_path.relative_to(collection.resolve(strict=True)).as_posix()
            if source_rel in page_index:
                raise ValueError("An API21 raw page is listed by multiple attempt manifests")
            page_bytes = source_path.read_bytes()
            if sha256_bytes(page_bytes) != page.get("response_sha256") or len(page_bytes) != page.get("response_bytes"):
                raise ValueError("An API21 raw page fails its attempt-manifest size or SHA-256 check")
            header, body, source_items = response_items(json.loads(page_bytes))
            if clean(header.get("resultCode")) not in {"00", "0000"}:
                raise ValueError("An API21 raw page does not contain a successful API header")
            if len(source_items) != page.get("actual_rows"):
                raise ValueError("An API21 page item count differs from its attempt manifest")
            request_url = page.get("source_url_without_key")
            if not isinstance(request_url, str):
                raise ValueError("An API21 page manifest is missing its public request URL")
            page_index[source_rel] = {
                "path": source_path,
                "bytes": page_bytes,
                "items": source_items,
                "manifest": manifest,
                "page": page,
                "attempt_id": str(manifest["attempt_id"]),
                "request_params": source_page_request_params(request_url),
                "source_url": request_url,
            }

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_source_items: set[tuple[str, int]] = set()
    for row in rows:
        relative = row.get("source_path")
        source_row_no = row.get("source_row_no")
        if not isinstance(relative, str) or not isinstance(source_row_no, int) or source_row_no < 1:
            raise ValueError("An API21 candidate lacks its source page or one-based item number")
        item_key = (relative, source_row_no)
        if item_key in seen_source_items:
            raise ValueError("The API21 candidate set repeats a source page item")
        seen_source_items.add(item_key)
        page = page_index.get(relative)
        if page is None or source_row_no > len(page["items"]):
            raise ValueError("An API21 candidate points to an unverified raw page or item index")
        if page["items"][source_row_no - 1] != row.get("raw"):
            raise ValueError("An API21 candidate item differs from its indexed source-page object")
        grouped[relative].append(row)

    if len(grouped) != 35:
        raise ValueError("The candidate rows do not resolve to the independently confirmed 35 source pages")
    if any(raw.get("meet") != "제주" for raw in (row["raw"] for row in rows)):
        raise ValueError("An API21 candidate venue is outside the verified Jeju cohort")
    field_absent = Counter(field for row in rows for field in API21_FIELDS if field not in row["raw"])
    if field_absent != Counter({"rider": 5795, "chulNo": 14, "daySerial": 14}):
        raise ValueError(f"Unexpected API21 missing-key counts: {dict(field_absent)}")
    if sum(row["raw"].get("passFlag") == "-" for row in rows) != 4:
        raise ValueError("The API21 dash-judgement count differs from the verified four rows")
    horse_date_counts = Counter((make_api21_event(row["raw"])[0], make_api21_event(row["raw"])[1]) for row in rows)
    repeated_groups = sum(count > 1 for count in horse_date_counts.values())
    repeated_rows = sum(count for count in horse_date_counts.values() if count > 1)
    if (repeated_groups, repeated_rows) != (779, 1558):
        raise ValueError("The API21 same-horse/date multi-round preservation counts differ")

    return {
        "rows": rows,
        "grouped_pages": grouped,
        "page_index": page_index,
        "candidate_sha256": candidate_sha,
        "candidate_ids": candidate_ids,
        "candidate_collection_manifest_sha256": sha256_file(collection / "collection_manifest.json"),
        "candidate_success_report_sha256": sha256_file(collection / "api21_successful_collection_report.json"),
        "candidate_independent_verification_sha256": sha256_file(collection / "api21_independent_verification.json"),
        "candidate_pages": len(grouped),
        "source_page_rows": len(rows),
        "repeated_horse_date_groups": repeated_groups,
        "repeated_horse_date_rows": repeated_rows,
        "field_absent_counts": dict(sorted(field_absent.items())),
        "excluded_candidate_rows": 0,
    }


def load_api42_inputs(repo: Path) -> dict[str, Any]:
    collection = repo / "jeju/research/20261001_starting_exam_api_collection"
    summary = read_json(collection / "api42_followup_summary.json")
    attempt_id = str(summary.get("attempt_id", ""))
    attempt_dir = collection / "raw/api42_followup/attempts" / attempt_id
    manifest_path = attempt_dir / "attempt_manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("attempt_id") != attempt_id or manifest.get("operation") != API42_OPERATION:
        raise ValueError("The API42 follow-up attempt manifest does not match its summary")
    probes = manifest.get("probes", [])
    if summary.get("candidate_unique_ids") != EXPECTED_API42_PROFILES or summary.get("completed") != EXPECTED_API42_PROFILES:
        raise ValueError("The API42 follow-up summary does not confirm 21 successful profiles")
    if summary.get("failed_or_invalid") != 0 or summary.get("exact_profile_match") != EXPECTED_API42_PROFILES:
        raise ValueError("The API42 follow-up summary reports failed or mismatched profiles")
    if len(probes) != EXPECTED_API42_PROFILES:
        raise ValueError("The API42 attempt manifest does not contain 21 profile requests")
    completed_at = manifest.get("completed_at_utc")
    if not isinstance(completed_at, str):
        raise ValueError("The API42 attempt lacks a batch completion timestamp")
    # Individual probe times were not recorded; use only the attempt completion time.
    observed_kst_date = api42_observed_kst_date(completed_at)

    profiles: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for probe in probes:
        horse_id = clean(probe.get("queried_hr_no"))
        if not horse_id or horse_id in seen_ids or probe.get("status") != "completed" or probe.get("http_status") != 200:
            raise ValueError("An API42 follow-up probe is duplicate or unsuccessful")
        seen_ids.add(horse_id)
        relative = probe.get("response_file")
        if not isinstance(relative, str):
            raise ValueError("An API42 follow-up probe lacks its raw response path")
        raw_path = safe_local_path(attempt_dir, relative)
        raw_bytes = raw_path.read_bytes()
        if sha256_bytes(raw_bytes) != probe.get("response_sha256") or len(raw_bytes) != probe.get("response_bytes"):
            raise ValueError(f"An API42 follow-up profile fails its SHA-256 or size check: {horse_id}")
        header, body, items = response_items(json.loads(raw_bytes))
        if clean(header.get("resultCode")) not in {"00", "0000"} or int(body.get("totalCount", -1)) != 1 or len(items) != 1:
            raise ValueError(f"An API42 follow-up response is not a successful single-profile result: {horse_id}")
        profile = items[0]
        if clean(profile.get("hrNo")) != horse_id or len(profile) != 218:
            raise ValueError(f"An API42 follow-up response does not exactly match the requested 218-field profile: {horse_id}")
        if clean(profile.get("breed")) != "제주마":
            raise ValueError(f"An API42 follow-up current-profile breed differs from 제주마: {horse_id}")
        payload_json = canonical_json(profile)
        profiles.append({
            "horse_id": horse_id,
            "probe": probe,
            "raw_path": raw_path,
            "raw_bytes": raw_bytes,
            "raw_relative_path": project_relative(raw_path, repo),
            "request_params": probe.get("public_params", {}),
            "payload_json": payload_json,
            "payload_sha256": sha256_bytes(payload_json.encode("utf-8")),
            "observed_at_utc": completed_at,
            "observed_kst_date": observed_kst_date,
            "normalized": {
                "horse_name_raw": raw_text(profile.get("hrNm")),
                "birth_date_raw": raw_text(profile.get("birthDt")),
                "age_raw": raw_text(profile.get("age")),
                "breed_label_raw": raw_text(profile.get("breed")),
                "sex_raw": raw_text(profile.get("sex")),
                "color_raw": raw_text(profile.get("color")),
                "production_country_raw": raw_text(profile.get("prdCty")),
            },
        })

    if len(seen_ids) != EXPECTED_API42_PROFILES:
        raise ValueError("The API42 follow-up does not contain 21 unique official horse IDs")
    return {
        "profiles": profiles,
        "attempt_id": attempt_id,
        "manifest": manifest,
        "manifest_sha256": sha256_file(manifest_path),
        "summary_sha256": sha256_file(collection / "api42_followup_summary.json"),
        "completed_at_utc": completed_at,
        "observed_kst_date": observed_kst_date,
    }


def artifact_values(item: dict[str, Any], created_at_utc: str) -> tuple[Any, ...]:
    return (
        item["source_family"], item["source_role"], item["public_dataset_id"], item["dataset_name"],
        item["endpoint"], item["operation"], item["attempt_id"], item["request_params_json"],
        item["source_url_without_key"], item["collected_at_utc"], item["http_status_code"],
        item["content_type"], item["raw_relative_path"], item["response_bytes"], item["sha256"],
        item["parser_version"], created_at_utc,
    )


ARTIFACT_COLUMNS = (
    "source_family,source_role,public_dataset_id,dataset_name,endpoint,operation,attempt_id,"
    "request_params_json,source_url_without_key,collected_at_utc,http_status_code,content_type,"
    "raw_relative_path,response_bytes,sha256,parser_version,created_at_utc"
)


def ensure_artifact(conn: sqlite3.Connection, item: dict[str, Any], created_at_utc: str) -> tuple[int, bool]:
    same_path = conn.execute(
        f"SELECT source_artifact_id,{ARTIFACT_COLUMNS} FROM source_artifacts WHERE raw_relative_path=?",
        (item["raw_relative_path"],),
    ).fetchall()
    if len(same_path) > 1:
        raise ValueError("Multiple source artifacts already use the same raw page path")
    if same_path:
        row = same_path[0]
        if row["operation"] != item["operation"] or row["sha256"] != item["sha256"]:
            raise ValueError("An existing source artifact at the same path has a different operation or SHA-256")
        expected = artifact_values(item, row["created_at_utc"])
        if tuple(row[column] for column in (
            "source_family", "source_role", "public_dataset_id", "dataset_name", "endpoint", "operation",
            "attempt_id", "request_params_json", "source_url_without_key", "collected_at_utc",
            "http_status_code", "content_type", "raw_relative_path", "response_bytes", "sha256",
            "parser_version", "created_at_utc",
        )) != expected:
            raise ValueError("An existing source artifact differs from the frozen page metadata")
        return int(row["source_artifact_id"]), False

    values = artifact_values(item, created_at_utc)
    cursor = conn.execute(
        """INSERT INTO source_artifacts(
               source_family,source_role,public_dataset_id,dataset_name,endpoint,operation,attempt_id,
               request_params_json,source_url_without_key,collected_at_utc,http_status_code,content_type,
               raw_relative_path,response_bytes,sha256,parser_version,created_at_utc)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        values,
    )
    return int(cursor.lastrowid), True


def api21_artifact_item(repo: Path, relative: str, page: dict[str, Any]) -> dict[str, Any]:
    page_meta = page["page"]
    return {
        "source_family": "kra_openapi",
        "source_role": "primary",
        "public_dataset_id": API21_DATASET_ID,
        "dataset_name": API21_DATASET_NAME,
        "endpoint": API21_ENDPOINT,
        "operation": API21_OPERATION,
        "attempt_id": page["attempt_id"],
        "request_params_json": canonical_json(page["request_params"]),
        "source_url_without_key": page["source_url"],
        "collected_at_utc": page_meta["retrieved_at_utc"],
        "http_status_code": int(page_meta["status_code"]),
        "content_type": page_meta.get("content_type"),
        "raw_relative_path": project_relative(page["path"], repo),
        "response_bytes": len(page["bytes"]),
        "sha256": sha256_bytes(page["bytes"]),
        "parser_version": API21_PARSER_VERSION,
    }


def api42_artifact_item(profile: dict[str, Any], attempt_id: str) -> dict[str, Any]:
    probe = profile["probe"]
    params = profile["request_params"]
    return {
        "source_family": "kra_openapi",
        "source_role": "primary",
        "public_dataset_id": API42_DATASET_ID,
        "dataset_name": API42_DATASET_NAME,
        "endpoint": API42_ENDPOINT,
        "operation": API42_OPERATION,
        "attempt_id": attempt_id,
        "request_params_json": canonical_json(params),
        "source_url_without_key": API42_ENDPOINT,
        "collected_at_utc": profile["observed_at_utc"],
        "http_status_code": int(probe["http_status"]),
        "content_type": probe.get("content_type") or "application/json;charset=UTF-8",
        "raw_relative_path": profile["raw_relative_path"],
        "response_bytes": len(profile["raw_bytes"]),
        "sha256": sha256_bytes(profile["raw_bytes"]),
        "parser_version": API42_PARSER_VERSION,
    }


def ensure_api_record(
    conn: sqlite3.Connection,
    artifact_id: int,
    record_index: int,
    record_type: str,
    natural_key: str,
    payload_json: str,
    payload_sha256: str,
) -> tuple[int, bool]:
    existing = conn.execute(
        """SELECT api_record_id,record_type,natural_key,payload_json,payload_sha256
           FROM api_records WHERE source_artifact_id=? AND record_index=?""",
        (artifact_id, record_index),
    ).fetchone()
    expected = (record_type, natural_key, payload_json, payload_sha256)
    if existing:
        if tuple(existing[key] for key in ("record_type", "natural_key", "payload_json", "payload_sha256")) != expected:
            raise ValueError("An existing API record at the same source item index differs from frozen input")
        return int(existing["api_record_id"]), False
    cursor = conn.execute(
        """INSERT INTO api_records(
               source_artifact_id,record_index,record_type,natural_key,payload_json,payload_sha256)
           VALUES(?,?,?,?,?,?)""",
        (artifact_id, record_index, record_type, natural_key, payload_json, payload_sha256),
    )
    return int(cursor.lastrowid), True


def ensure_api42_observation(conn: sqlite3.Connection, profile: dict[str, Any], api_record_id: int) -> bool:
    normalized = profile["normalized"]
    expected = (
        api_record_id, profile["horse_id"], profile["observed_at_utc"], profile["observed_kst_date"],
        normalized["horse_name_raw"], normalized["birth_date_raw"], normalized["age_raw"],
        normalized["breed_label_raw"], normalized["sex_raw"], normalized["color_raw"],
        normalized["production_country_raw"],
    )
    existing = conn.execute(
        """SELECT api_record_id,horse_id,observed_at_utc,observed_kst_date,horse_name_raw,birth_date_raw,
                  age_raw,breed_label_raw,sex_raw,color_raw,production_country_raw
           FROM horse_profile_observations WHERE api_record_id=?""",
        (api_record_id,),
    ).fetchone()
    by_time = conn.execute(
        "SELECT api_record_id FROM horse_profile_observations WHERE horse_id=? AND observed_at_utc=?",
        (profile["horse_id"], profile["observed_at_utc"]),
    ).fetchone()
    if existing:
        if tuple(existing) != expected:
            raise ValueError("An existing API42 profile observation differs from the frozen profile")
        if by_time is None or by_time[0] != api_record_id:
            raise ValueError("An existing API42 profile has conflicting horse/time provenance")
        return False
    if by_time is not None:
        raise ValueError("A different API42 record already uses the same horse and observation time")
    conn.execute(
        """INSERT INTO horse_profile_observations(
               api_record_id,horse_id,observed_at_utc,observed_kst_date,horse_name_raw,birth_date_raw,
               age_raw,breed_label_raw,sex_raw,color_raw,production_country_raw)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        expected,
    )
    return True


def ensure_api42_breed_evidence(conn: sqlite3.Connection, profile: dict[str, Any], artifact_id: int, api_record_id: int) -> bool:
    expected = (
        profile["horse_id"], None, profile["normalized"]["breed_label_raw"],
        "API42_1 current profile breed", artifact_id, api_record_id,
        "profile_retrieval_time",
        "Current API42_1 profile breed observed at the follow-up batch completed_at_utc; "
        "the source did not provide an individual request timestamp or a historical effective date.",
    )
    existing = conn.execute(
        """SELECT horse_id,observed_event_date,breed_label_raw,evidence_kind,source_artifact_id,
                  api_record_id,timing_basis,notes
           FROM breed_evidence WHERE api_record_id=?""",
        (api_record_id,),
    ).fetchall()
    if existing:
        if len(existing) != 1 or tuple(existing[0]) != expected:
            raise ValueError("An existing API42 current-breed evidence row differs from the frozen profile")
        return False
    conn.execute(
        """INSERT INTO breed_evidence(
               horse_id,observed_event_date,breed_label_raw,evidence_kind,source_artifact_id,
               api_record_id,timing_basis,notes)
           VALUES(?,?,?,?,?,?,?,?)""",
        expected,
    )
    return True


def ensure_api21_normalized_row(
    conn: sqlite3.Connection, source_row: dict[str, Any], artifact_id: int, api_record_id: int,
) -> bool:
    expected = expected_api21_tuple(source_row, artifact_id, api_record_id)
    existing = conn.execute(
        "SELECT " + ",".join(API21_ROW_COLUMNS) + " FROM starting_exam_api_rows WHERE api_record_id=?",
        (api_record_id,),
    ).fetchone()
    item_match = conn.execute(
        "SELECT api_record_id FROM starting_exam_api_rows WHERE source_artifact_id=? AND source_row_no=?",
        (artifact_id, int(source_row["source_row_no"])),
    ).fetchone()
    if existing:
        if tuple(existing) != expected:
            raise ValueError("An existing normalized API21 row differs from the frozen source item")
        if item_match is None or item_match[0] != api_record_id:
            raise ValueError("An API21 source artifact/item index is linked to a different normalized record")
        return False
    if item_match is not None:
        raise ValueError("An API21 source artifact/item index is already used by a different normalized record")
    conn.execute(
        "INSERT INTO starting_exam_api_rows(" + ",".join(API21_ROW_COLUMNS) + ") VALUES(" + ",".join("?" for _ in API21_ROW_COLUMNS) + ")",
        expected,
    )
    return True


METADATA_CONTRACT = {
    "analysis_cutoff": ANALYSIS_CUTOFF,
    "analysis_view": "starting_exam_api_rows_analysis_2026",
    "api21_exam_date_policy": "Source trainDate is an event date without publication timestamp. For a race-date join, require exam_date < race_date; do not infer availability from source collection time.",
    "automatic_model_input": False,
    "api21_name_field_note": "API21 name_raw is source text (often '한국') and is not a breed label.",
    "api42_profile_timing": "The 21 profile observations use API42 attempt completed_at_utc because individual request timestamps are absent.",
    "profile_breed_timing": "Current profile breed is a retrieval-time observation and is not asserted as the historical breed on exam_date.",
    "raw_field_policy": "Original item values and types remain in api_records.payload_json; raw source pages remain in source_artifacts files with page SHA-256.",
}


def metadata_values(api21: dict[str, Any], api42: dict[str, Any]) -> dict[str, str]:
    return {
        "starting_exam_api21_module_v1": IMPORT_BATCH_ID,
        "starting_exam_api21_contract_v1": canonical_json(METADATA_CONTRACT),
        "starting_exam_api21_candidate_sha256": api21["candidate_sha256"],
        "starting_exam_api21_collection_manifest_sha256": api21["candidate_collection_manifest_sha256"],
        "starting_exam_api21_success_report_sha256": api21["candidate_success_report_sha256"],
        "starting_exam_api21_independent_verification_sha256": api21["candidate_independent_verification_sha256"],
        "starting_exam_api21_source_row_count": str(EXPECTED_API21_ROWS),
        "starting_exam_api21_horse_count": str(EXPECTED_HORSES),
        "starting_exam_api21_analysis_cutoff": ANALYSIS_CUTOFF,
        "starting_exam_api42_followup_attempt_id": api42["attempt_id"],
        "starting_exam_api42_followup_manifest_sha256": api42["manifest_sha256"],
        "starting_exam_api42_followup_summary_sha256": api42["summary_sha256"],
    }


def ensure_metadata(conn: sqlite3.Connection, expected: dict[str, str]) -> int:
    inserted = 0
    for key, value in expected.items():
        existing = conn.execute("SELECT value FROM schema_metadata WHERE key=?", (key,)).fetchone()
        if existing is not None:
            if existing[0] != value:
                raise ValueError(f"A conflicting schema_metadata key exists and will not be overwritten: {key}")
            continue
        conn.execute("INSERT INTO schema_metadata(key,value) VALUES(?,?)", (key, value))
        inserted += 1
    return inserted


def execute_sql_file_in_transaction(conn: sqlite3.Connection, path: Path) -> None:
    statement = ""
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            if statement.strip():
                conn.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("The migration SQL ends with an incomplete statement")


def assert_schema(conn: sqlite3.Connection) -> None:
    columns = tuple(row[1] for row in conn.execute("PRAGMA table_info(starting_exam_api_rows)"))
    if columns != EXPECTED_TABLE_COLUMNS:
        raise ValueError("The starting_exam_api_rows schema differs from the approved migration")
    view = conn.execute("SELECT type FROM sqlite_master WHERE name='starting_exam_api_rows_analysis_2026'").fetchone()
    if view is None or view[0] != "view":
        raise ValueError("The 2026 API21 starting-exam analysis view was not created")


def make_expected_page_artifacts(repo: Path, api21: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for relative, source_rows in api21["grouped_pages"].items():
        page = api21["page_index"][relative]
        item = api21_artifact_item(repo, relative, page)
        item["candidate_rows"] = sorted(source_rows, key=lambda row: int(row["source_row_no"]))
        result[relative] = item
    return result


def import_once(
    conn: sqlite3.Connection,
    repo: Path,
    api21: dict[str, Any],
    api42: dict[str, Any],
    expected_metadata: dict[str, str],
) -> dict[str, Any]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        execute_sql_file_in_transaction(conn, MIGRATION_PATH)
        assert_schema(conn)
        before = {
            "source_artifacts": conn.execute("SELECT count(*) FROM source_artifacts").fetchone()[0],
            "api_records": conn.execute("SELECT count(*) FROM api_records").fetchone()[0],
            "horse_profile_observations": conn.execute("SELECT count(*) FROM horse_profile_observations").fetchone()[0],
            "breed_evidence": conn.execute("SELECT count(*) FROM breed_evidence").fetchone()[0],
            "starting_exam_api_rows": conn.execute("SELECT count(*) FROM starting_exam_api_rows").fetchone()[0],
        }
        artifact_inserted = 0
        api_record_inserted = 0
        profile_inserted = 0
        breed_evidence_inserted = 0
        exam_row_inserted = 0

        current_profile_ids = {row[0] for row in conn.execute("SELECT horse_id FROM horse_profile_latest")}
        missing_candidate_profiles = api21["candidate_ids"] - current_profile_ids
        followup_profile_ids = {profile["horse_id"] for profile in api42["profiles"]}
        if missing_candidate_profiles and missing_candidate_profiles != followup_profile_ids:
            raise ValueError("The 21 API42 follow-up IDs do not exactly match the currently missing candidate profiles")

        for profile in api42["profiles"]:
            artifact, inserted = ensure_artifact(
                conn, api42_artifact_item(profile, api42["attempt_id"]), iso_now_utc(),
            )
            artifact_inserted += int(inserted)
            record_id, inserted = ensure_api_record(
                conn, artifact, 1, "horse_profile", profile["horse_id"], profile["payload_json"], profile["payload_sha256"],
            )
            api_record_inserted += int(inserted)
            profile_inserted += int(ensure_api42_observation(conn, profile, record_id))
            breed_evidence_inserted += int(ensure_api42_breed_evidence(conn, profile, artifact, record_id))

        expected_exam_api_record_ids: list[int] = []
        for relative, page_item in make_expected_page_artifacts(repo, api21).items():
            artifact, inserted = ensure_artifact(conn, page_item, iso_now_utc())
            artifact_inserted += int(inserted)
            for source_row in page_item["candidate_rows"]:
                raw = source_row["raw"]
                event_date, horse_id, event_key = make_api21_event(raw)
                payload_json = canonical_json(raw)
                payload_hash = sha256_bytes(payload_json.encode("utf-8"))
                record_id, inserted = ensure_api_record(
                    conn, artifact, int(source_row["source_row_no"]), "starting_exam", event_key,
                    payload_json, payload_hash,
                )
                api_record_inserted += int(inserted)
                expected_exam_api_record_ids.append(record_id)
                exam_row_inserted += int(ensure_api21_normalized_row(conn, source_row, artifact, record_id))

        metadata_inserted = ensure_metadata(conn, expected_metadata)
        verification = verify_database(conn, api21, api42, expected_exam_api_record_ids)
        after = {
            "source_artifacts": conn.execute("SELECT count(*) FROM source_artifacts").fetchone()[0],
            "api_records": conn.execute("SELECT count(*) FROM api_records").fetchone()[0],
            "horse_profile_observations": conn.execute("SELECT count(*) FROM horse_profile_observations").fetchone()[0],
            "breed_evidence": conn.execute("SELECT count(*) FROM breed_evidence").fetchone()[0],
            "starting_exam_api_rows": conn.execute("SELECT count(*) FROM starting_exam_api_rows").fetchone()[0],
        }
        conn.commit()
        return {
            "before": before,
            "after": after,
            "inserted": {
                "source_artifacts": artifact_inserted,
                "api_records": api_record_inserted,
                "horse_profile_observations": profile_inserted,
                "breed_evidence": breed_evidence_inserted,
                "starting_exam_api_rows": exam_row_inserted,
                "schema_metadata_keys": metadata_inserted,
            },
            "verification": verification,
        }
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def verify_database(
    conn: sqlite3.Connection,
    api21: dict[str, Any],
    api42: dict[str, Any],
    expected_exam_api_record_ids: list[int],
) -> dict[str, Any]:
    if len(expected_exam_api_record_ids) != EXPECTED_API21_ROWS or len(set(expected_exam_api_record_ids)) != EXPECTED_API21_ROWS:
        raise ValueError("The API21 candidate rows do not link to exactly 10,664 unique API records")
    all_exam_count = conn.execute("SELECT count(*) FROM starting_exam_api_rows").fetchone()[0]
    if all_exam_count != EXPECTED_API21_ROWS:
        raise ValueError(f"Expected exactly {EXPECTED_API21_ROWS} normalized API21 rows, found {all_exam_count}")
    actual_candidate_records = conn.execute(
        "SELECT count(*) FROM starting_exam_api_rows WHERE api_record_id IN (" + ",".join("?" for _ in expected_exam_api_record_ids) + ")",
        expected_exam_api_record_ids,
    ).fetchone()[0]
    if actual_candidate_records != EXPECTED_API21_ROWS:
        raise ValueError("The normalized API21 table does not contain every expected source item")
    mismatched_links = conn.execute(
        """SELECT count(*) FROM starting_exam_api_rows se
           JOIN api_records ar ON ar.api_record_id=se.api_record_id
           WHERE se.source_artifact_id != ar.source_artifact_id OR se.source_row_no != ar.record_index"""
    ).fetchone()[0]
    if mismatched_links:
        raise ValueError("API21 source_artifact_id or source_row_no differs from its api_records provenance")

    excluded_profiles = conn.execute(
        "SELECT count(*) FROM horse_profile_observations WHERE horse_id=?", (SMALL_BEAR_ID,),
    ).fetchone()[0]
    excluded_rows = conn.execute(
        "SELECT count(*) FROM starting_exam_api_rows WHERE horse_id=?", (SMALL_BEAR_ID,),
    ).fetchone()[0]
    if excluded_profiles or excluded_rows:
        raise ValueError("The explicitly excluded small bear horse ID is present after the load")

    profile_ids = {row[0] for row in conn.execute("SELECT horse_id FROM horse_profile_latest")}
    missing_horse_ids = sorted(api21["candidate_ids"] - profile_ids)
    if missing_horse_ids:
        raise ValueError(f"API21 candidate IDs are missing current API42 profiles: {len(missing_horse_ids)}")
    profile_batch_paths = [profile["raw_relative_path"] for profile in api42["profiles"]]
    profile_marks = ",".join("?" for _ in profile_batch_paths)
    api42_records = conn.execute(
        f"""SELECT count(*) FROM api_records ar JOIN source_artifacts sa USING(source_artifact_id)
             WHERE sa.raw_relative_path IN ({profile_marks}) AND ar.record_type='horse_profile'""",
        profile_batch_paths,
    ).fetchone()[0]
    api42_observations = conn.execute(
        f"""SELECT count(*) FROM horse_profile_observations hpo JOIN api_records ar USING(api_record_id)
             JOIN source_artifacts sa USING(source_artifact_id)
             WHERE sa.raw_relative_path IN ({profile_marks})""",
        profile_batch_paths,
    ).fetchone()[0]
    if (api42_records, api42_observations) != (EXPECTED_API42_PROFILES, EXPECTED_API42_PROFILES):
        raise ValueError("The 21 API42 follow-up profiles are not fully represented in API records and observations")

    raw_dash_rows = conn.execute(
        "SELECT count(*) FROM starting_exam_api_rows WHERE pass_flag_raw='-' AND judgment_label_normalized IS NULL AND judgment_status='unknown'",
    ).fetchone()[0]
    absent_rider = conn.execute(
        "SELECT count(*) FROM starting_exam_api_rows WHERE json_array('rider') IS NOT NULL AND raw_key_absence_json LIKE '%\"rider\"%'",
    ).fetchone()[0]
    # JSON1 is available in the target SQLite build; the direct count below also
    # verifies the independently preserved missing-key JSON field.
    absent_chul = conn.execute(
        "SELECT count(*) FROM starting_exam_api_rows WHERE raw_key_absence_json LIKE '%\"chulNo\"%'",
    ).fetchone()[0]
    absent_day_serial = conn.execute(
        "SELECT count(*) FROM starting_exam_api_rows WHERE raw_key_absence_json LIKE '%\"daySerial\"%'",
    ).fetchone()[0]
    if (raw_dash_rows, absent_rider, absent_chul, absent_day_serial) != (4, 5795, 14, 14):
        raise ValueError("Normalized API21 dash or absent-key state differs from the frozen source audit")

    external_trainer = conn.execute(
        "SELECT count(*) FROM starting_exam_api_rows WHERE tr_name_raw='외부마' AND tr_no_raw='0BBBBB' AND trainer_id_normalized IS NULL",
    ).fetchone()[0]
    if external_trainer != 1:
        raise ValueError("The external-horse trainer code was not retained and excluded from normalized trainer IDs")

    view_rows = conn.execute("SELECT count(*) FROM starting_exam_api_rows_analysis_2026").fetchone()[0]
    future_rows = conn.execute(
        "SELECT count(*) FROM starting_exam_api_rows WHERE exam_date > ?", (ANALYSIS_CUTOFF,),
    ).fetchone()[0]
    expected_view_rows = conn.execute(
        "SELECT count(*) FROM starting_exam_api_rows WHERE exam_date <= ?", (ANALYSIS_CUTOFF,),
    ).fetchone()[0]
    if (view_rows, future_rows, expected_view_rows) != (10_620, 44, 10_620):
        raise ValueError("The 2026 analysis view did not apply the 2026-09-19 event-date cap")
    wrong_joins = conn.execute(
        """SELECT count(*) FROM starting_exam_api_rows_analysis_2026 v
           LEFT JOIN horse_analysis_2026 ha USING(horse_id)
           JOIN starting_exam_api_rows se USING(starting_exam_api_row_id)
           WHERE ha.horse_id IS NULL OR v.current_horse_name IS NOT ha.horse_name
              OR v.current_horse_age_2026 IS NOT ha.age_2026
              OR v.sex_at_exam_raw IS NOT se.sex_raw
              OR v.sex_current_profile IS NOT ha.sex_current_profile"""
    ).fetchone()[0]
    if wrong_joins:
        raise ValueError("The API21 analysis view does not match current-profile joins or preserve event sex")

    fk_issues = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]
    integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
    if fk_issues or integrity != ["ok"]:
        raise ValueError("SQLite integrity or foreign-key check failed")
    return {
        "api21_normalized_rows": all_exam_count,
        "api21_api_record_item_links": actual_candidate_records,
        "api21_source_artifact_record_index_mismatches": mismatched_links,
        "api21_candidate_unique_horse_ids": len(api21["candidate_ids"]),
        "current_profile_join_missing_horse_ids": missing_horse_ids,
        "api42_followup_profiles": EXPECTED_API42_PROFILES,
        "api42_horse_profile_records": api42_records,
        "api42_horse_profile_observations": api42_observations,
        "excluded_small_bear_profile_rows": excluded_profiles,
        "excluded_small_bear_exam_rows": excluded_rows,
        "api21_field_absence_counts": api21["field_absent_counts"],
        "api21_dash_judgement_rows_normalized_null_unknown": raw_dash_rows,
        "api21_external_trainer_rows_raw_retained_normalized_null": external_trainer,
        "api21_same_horse_date_multi_round_groups": api21["repeated_horse_date_groups"],
        "api21_same_horse_date_multi_round_rows": api21["repeated_horse_date_rows"],
        "analysis_view_name": "starting_exam_api_rows_analysis_2026",
        "analysis_view_event_date_cutoff": ANALYSIS_CUTOFF,
        "analysis_view_rows": view_rows,
        "rows_after_analysis_cutoff_excluded": future_rows,
        "publication_time_available": False,
        "analysis_current_profile_breed_is_historical_claim": False,
        "automatic_model_input": False,
        "foreign_key_issues": fk_issues,
        "integrity_check": integrity,
    }


def open_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)


def make_temporary_backup(database: Path) -> dict[str, Any]:
    temporary_dir = Path(tempfile.mkdtemp(prefix="starting-exam-api21-backup-", dir="/private/tmp" if Path("/private/tmp").is_dir() else None))
    backup_path = temporary_dir / "database.sqlite3"
    source = open_readonly(database)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
        destination.commit()
        check = [row[0] for row in destination.execute("PRAGMA integrity_check")]
        if check != ["ok"]:
            raise ValueError("The pre-load SQLite backup failed integrity_check")
    finally:
        destination.close()
        source.close()
    return {
        "path": str(backup_path),
        "sha256": sha256_file(backup_path),
        "bytes": backup_path.stat().st_size,
        "integrity_check": "ok",
        "temporary": True,
        "temporary_dir": temporary_dir,
    }


def cleanup_temporary_backup(info: dict[str, Any]) -> None:
    shutil.rmtree(info["temporary_dir"], ignore_errors=True)


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def resolve_report_path(repo: Path, raw: str) -> Path:
    requested = Path(raw)
    resolved = (requested if requested.is_absolute() else repo / requested).resolve()
    output_root = OUTPUT_DIR.resolve()
    try:
        resolved.relative_to(output_root)
    except ValueError as exc:
        raise ValueError("--output-report must be inside jeju/research/20261002_starting_exam_db_load/") from exc
    return resolved


def run_load(database: Path, output_report: Path, repo: Path) -> dict[str, Any]:
    api21 = load_api21_inputs(repo)
    api42 = load_api42_inputs(repo)
    expected_metadata = metadata_values(api21, api42)
    backup = make_temporary_backup(database)
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(database, timeout=60.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise ValueError("SQLite foreign-key enforcement could not be enabled")
        first = import_once(conn, repo, api21, api42, expected_metadata)
        replay = import_once(conn, repo, api21, api42, expected_metadata)
        replay_inserted = replay["inserted"]
        if any(replay_inserted.values()):
            raise ValueError(f"Idempotency replay inserted additional rows: {replay_inserted}")
        report = {
            "status": "imported" if any(first["inserted"].values()) else "idempotent_no_insert",
            "generated_at_utc": iso_now_utc(),
            "import_batch_id": IMPORT_BATCH_ID,
            "database_path": str(database),
            "migration_path": project_relative(MIGRATION_PATH, repo),
            "backup": {key: value for key, value in backup.items() if key != "temporary_dir"},
            "source": {
                "api21_collection_dir": project_relative(API21_DIR, repo),
                "api21_candidate_sha256": api21["candidate_sha256"],
                "api21_rows": EXPECTED_API21_ROWS,
                "api21_horse_ids": EXPECTED_HORSES,
                "api21_candidate_pages": api21["candidate_pages"],
                "api21_collection_manifest_sha256": api21["candidate_collection_manifest_sha256"],
                "api21_success_report_sha256": api21["candidate_success_report_sha256"],
                "api21_independent_verification_sha256": api21["candidate_independent_verification_sha256"],
                "api42_followup_attempt_id": api42["attempt_id"],
                "api42_followup_profiles": EXPECTED_API42_PROFILES,
                "api42_followup_manifest_sha256": api42["manifest_sha256"],
                "api42_followup_summary_sha256": api42["summary_sha256"],
                "api42_observed_at_utc": api42["completed_at_utc"],
                "api42_timestamp_basis": "attempt completed_at_utc; individual probe timestamps are absent",
                "api42_profile_raw_field_count": 218,
                "excluded_horse_id": SMALL_BEAR_ID,
            },
            "inserted": first["inserted"],
            "before": first["before"],
            "after": first["after"],
            "verification": first["verification"],
            "idempotency_replay": {
                "inserted": replay_inserted,
                "after": replay["after"],
                "zero_additional_rows": True,
                "verification": replay["verification"],
            },
            "metadata_keys_added": first["inserted"]["schema_metadata_keys"],
            "policy": METADATA_CONTRACT,
        }
        atomic_write_json(output_report, report)
        return report
    finally:
        if conn is not None:
            conn.close()
        cleanup_temporary_backup(backup)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Existing SQLite database to load; no default database is assumed")
    parser.add_argument(
        "--output-report",
        default="jeju/research/20261002_starting_exam_db_load/staging_report.json",
        help="JSON report path, restricted to the new starting-exam DB-load research directory",
    )
    parser.add_argument("--repo", default=str(REPO_ROOT), help="Repository root (defaults to this checkout)")
    args = parser.parse_args()
    repo = Path(args.repo).resolve(strict=True)
    database = Path(args.db).expanduser().resolve(strict=True)
    if not database.is_file():
        raise SystemExit("--db must name an existing SQLite file")
    shared_db = (repo / "data/horse_racing.sqlite3").resolve()
    if database == shared_db:
        raise SystemExit("The shared horse_racing.sqlite3 database is read-only for this loader")
    output_report = resolve_report_path(repo, args.output_report)
    result = run_load(database, output_report, repo)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
