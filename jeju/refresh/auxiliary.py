"""Incrementally load API18, API16, and API21 refresh observations.

The module consumes only locally archived JSON responses.  It does not open a
database, begin or commit a transaction, make network requests, or write a
production database.  The caller owns the connection and transaction.
"""

from __future__ import annotations

from jeju.refresh.core import profile_relation

import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


FAMILIES = {"daily_training", "medical", "starting_exam"}
API = {
    "daily_training": {
        "dataset_id": "15058782",
        "dataset_name": "일별훈련 상세정보",
        "endpoint": "https://apis.data.go.kr/B551015/API18_1/dailyTraining_1",
        "operation": "dailyTraining_1",
        "record_type": "daily_training_api18",
    },
    "medical": {
        "dataset_id": "15057799",
        "dataset_name": "마필진료 정보",
        "endpoint": "https://apis.data.go.kr/B551015/API16_1/raceHorseClinic_1",
        "operation": "raceHorseClinic_1",
        "record_type": "medical_api16_clinic",
    },
    "starting_exam": {
        "dataset_id": "15057405",
        "dataset_name": "한국마사회 출발심사 결과",
        "endpoint": "https://apis.data.go.kr/B551015/API21_1/startingTestResult_1",
        "operation": "startingTestResult_1",
        "record_type": "starting_exam",
    },
}

API18_FIELDS = (
    "hrNo", "hrName", "meet", "trDate", "trTerm", "stTime", "spTime",
    "run1Cnt", "run2Cnt", "prGubun", "prNo", "part", "partNo",
    "trName", "chulGubun",
)
API16_FIELDS = (
    "meet", "clinicDate", "hrName", "hrNo", "hospiName", "illName1",
    "illName2", "part",
)
API21_FIELDS = (
    "meet", "trainDate", "daySerial", "trainNo", "chulNo", "hrName", "hrNo",
    "name", "sex", "age", "rider", "trName", "trNo", "owName", "owNo",
    "passFlag", "reason", "nopassReason",
)
API21_COLUMN_BY_SOURCE = {
    "meet": "meet_raw", "trainDate": "train_date_raw", "daySerial": "day_serial_raw",
    "trainNo": "train_no_raw", "chulNo": "chul_no_raw", "hrName": "hr_name_raw",
    "hrNo": "hr_no_raw", "name": "name_raw", "sex": "sex_raw", "age": "age_raw",
    "rider": "rider_raw", "trName": "tr_name_raw", "trNo": "tr_no_raw",
    "owName": "ow_name_raw", "owNo": "ow_no_raw", "passFlag": "pass_flag_raw",
    "reason": "reason_raw", "nopassReason": "nopass_reason_raw",
}
API18_RIDER_TYPES = {"기수", "조교사", "조교보", "조교승인", "기수후보생"}
UTC = timezone.utc


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise ValueError(f"Unsupported JSON value type: {type(value).__name__}")


def raw_text(value: Any) -> str | None:
    return None if value is None else str(value)


def api18_text(value: Any) -> str | None:
    """Match the API18 loader's scalar-to-text conversion."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    raise ValueError("API18 known raw field is not a JSON scalar")


def official_horse_id(value: Any) -> str | None:
    """Use official decimal spelling; strings are not trimmed or zero-stripped."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, str) and value.isascii() and re.fullmatch(r"[0-9]+", value):
        return value if value != "0" else None
    return None


def parse_api_date(value: Any, field: str) -> tuple[str, str]:
    raw = api18_text(value)
    if raw is None or not re.fullmatch(r"[0-9]{8}", raw, flags=re.ASCII):
        raise ValueError(f"{field} is not an eight-digit API date")
    try:
        parsed = datetime.strptime(raw, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid calendar date") from exc
    return raw, parsed.isoformat()


def parse_medical_date(value: Any) -> tuple[str, str]:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("API16 clinicDate has an unsupported JSON type")
    raw = str(value)
    if not re.fullmatch(r"[0-9]{8}", raw):
        raise ValueError("API16 clinicDate is not an eight-digit date")
    try:
        parsed = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError as exc:
        raise ValueError("API16 clinicDate is not a valid calendar date") from exc
    return raw, parsed.isoformat()


def parse_api_time(value: Any, event_date: str) -> tuple[str | None, str]:
    raw = api18_text(value)
    if raw is None or raw in ("", "-"):
        return None, "missing"
    if not re.fullmatch(r"[0-9]{14}", raw, flags=re.ASCII):
        return None, "invalid_format_or_calendar"
    try:
        parsed = datetime.strptime(raw, "%Y%m%d%H%M%S")
    except ValueError:
        return None, "invalid_format_or_calendar"
    if raw[:8] != event_date:
        return None, "date_mismatch"
    return parsed.strftime("%Y-%m-%d %H:%M:%S"), "valid_same_event_date"


def parse_integer_raw(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value, flags=re.ASCII):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _response_items(payload: Any) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ValueError("Raw API response root is not an object")
    wrapper = payload.get("response", payload)
    if not isinstance(wrapper, dict):
        raise ValueError("Raw API response wrapper is not an object")
    header, body = wrapper.get("header"), wrapper.get("body")
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError("Raw API response header or body is missing")
    value = body.get("items")
    if isinstance(value, dict):
        value = value.get("item")
    if value is None or value == "":
        items: list[dict[str, Any]] = []
    elif isinstance(value, dict):
        items = [value]
    elif isinstance(value, list) and all(isinstance(item, dict) for item in value):
        items = value
    else:
        raise ValueError("Raw API items use an unsupported shape")
    return header, body, items


def _safe_relative_file(repo_root: Path, relative: Any, label: str) -> tuple[Path, str]:
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"{label} must be a nonempty repository-relative path")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
        raise ValueError(f"{label} is not a safe repository-relative path")
    root = repo_root.resolve(strict=True)
    path = (root / Path(*posix.parts)).resolve(strict=True)
    path.relative_to(root)
    if not path.is_file():
        raise ValueError(f"{label} does not name a regular file")
    normalized = path.relative_to(root).as_posix()
    return path, normalized


def _safe_source_url(value: Any, endpoint: str, params: Mapping[str, str]) -> str:
    if value is None:
        return endpoint + ("?" + urlencode(sorted(params.items())) if params else "")
    if not isinstance(value, str):
        raise ValueError("source_url_without_key must be text")
    parts = urlsplit(value)
    expected = urlsplit(endpoint)
    if (parts.scheme, parts.netloc, parts.path) != (expected.scheme, expected.netloc, expected.path):
        raise ValueError("Source URL does not match the fixed public API endpoint")
    query = parse_qsl(parts.query, keep_blank_values=True)
    if any("key" in key.lower() or "token" in key.lower() for key, _ in query):
        raise ValueError("Source URL contains an authentication parameter")
    if len(dict(query)) != len(query):
        raise ValueError("Source URL contains duplicate query parameters")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _parse_collected_at(value: Any) -> tuple[str, int]:
    if not isinstance(value, str) or not value:
        raise ValueError("collected_at_utc is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("collected_at_utc is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("collected_at_utc must include a timezone")
    utc = parsed.astimezone(UTC)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"), int(utc.timestamp() * 1000)


def _int_field(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        parsed = int(value.strip())
    else:
        raise ValueError(f"{name} must be an integer")
    if parsed < minimum:
        raise ValueError(f"{name} is outside its valid range")
    return parsed


def _prepare_page(page: Mapping[str, Any], repo_root: Path, run_id: str) -> dict[str, Any]:
    family = page.get("family")
    if family not in FAMILIES:
        raise ValueError(f"Unsupported auxiliary page family: {family!r}")
    raw_path, relative_path = _safe_relative_file(repo_root, page.get("path"), "page path")
    response_bytes = raw_path.read_bytes()
    digest = sha256_bytes(response_bytes)
    if page.get("sha256") != digest:
        raise ValueError(f"Raw page SHA-256 differs from the collector envelope: {relative_path}")
    try:
        payload = json.loads(response_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Raw page is not UTF-8 JSON: {relative_path}") from exc
    header, body, items = _response_items(payload)
    code = str(header.get("resultCode", "")).strip()
    if code not in {"00", "0000"}:
        raise ValueError(f"Raw API page has unsuccessful resultCode {code!r}: {relative_path}")
    status = _int_field(page.get("status_code", page.get("http_status", 200)), "status_code", minimum=100)
    if status != 200:
        raise ValueError(f"Raw API page has non-200 HTTP status: {relative_path}")
    params_value = page.get("params")
    if not isinstance(params_value, Mapping) or not all(
        isinstance(key, str) and isinstance(value, (str, int)) and not isinstance(value, bool)
        for key, value in params_value.items()
    ):
        raise ValueError("params must be a mapping of simple public parameter values")
    params = {str(key): str(value) for key, value in params_value.items()}
    if any("key" in key.lower() or "token" in key.lower() for key in params):
        raise ValueError("Collector params contain a possible authentication parameter")
    if params.get("meet") not in {None, "2", "제주"}:
        raise ValueError(f"API page is not restricted to Jeju meet: {relative_path}")
    page_no = _int_field(page.get("page_no"), "page_no", minimum=1)
    total_value = page.get("total_count", body.get("totalCount"))
    total_count = _int_field(total_value, "total_count", minimum=0)
    body_total = body.get("totalCount")
    if body_total is not None and _int_field(body_total, "response totalCount", minimum=0) != total_count:
        raise ValueError(f"total_count differs from response body: {relative_path}")
    body_page = body.get("pageNo")
    if body_page is not None and _int_field(body_page, "response pageNo", minimum=1) != page_no:
        raise ValueError(f"page_no differs from response body: {relative_path}")
    param_page = params.get("pageNo")
    if param_page is not None and _int_field(param_page, "request pageNo", minimum=1) != page_no:
        raise ValueError(f"page_no differs from request parameters: {relative_path}")
    page_size_value = params.get("numOfRows", body.get("numOfRows"))
    if page_size_value is not None:
        page_size = _int_field(page_size_value, "numOfRows", minimum=1)
        expected_rows = max(0, min(page_size, total_count - (page_no - 1) * page_size))
        if len(items) != expected_rows:
            raise ValueError(
                f"Page item count {len(items)} differs from pagination expectation {expected_rows}: {relative_path}"
            )
    if page.get("item_count") is not None and _int_field(page["item_count"], "item_count") != len(items):
        raise ValueError(f"item_count differs from raw response: {relative_path}")
    collected_at, retrieved_ms = _parse_collected_at(page.get("collected_at_utc"))
    api_info = API[family]
    source_url = _safe_source_url(page.get("source_url_without_key"), api_info["endpoint"], params)

    manifest_path = None
    manifest_sha = None
    if page.get("source_manifest_path") is not None:
        manifest_file, manifest_path = _safe_relative_file(
            repo_root, page["source_manifest_path"], "source manifest path",
        )
        manifest_bytes = manifest_file.read_bytes()
        manifest_sha = sha256_bytes(manifest_bytes)
        if page.get("source_manifest_sha256") != manifest_sha:
            raise ValueError(f"Source manifest SHA-256 differs: {manifest_path}")
    elif page.get("source_manifest_sha256") is not None:
        raise ValueError("source_manifest_sha256 requires source_manifest_path")

    page_context = {
        "family": family,
        "path": relative_path,
        "sha256": digest,
        "params": params,
        "page_no": page_no,
        "total_count": total_count,
        "item_count": len(items),
        "collected_at_utc": collected_at,
        "source_manifest_path": manifest_path,
        "source_manifest_sha256": manifest_sha,
        "status_code": status,
        "api_result_code": code,
        "source_url_without_key": source_url,
        "attempt_id": str(page.get("attempt_id") or run_id),
        "content_type": str(page.get("content_type") or "application/json;charset=UTF-8"),
        "requested_at_ms": page.get("requested_at_ms"),
        "items": items,
        "retrieved_at_ms": retrieved_ms,
        "raw_bytes": len(response_bytes),
    }
    if not page_context["attempt_id"] or len(page_context["attempt_id"]) > 200:
        raise ValueError("attempt_id must be a nonempty string of at most 200 characters")
    if page_context["requested_at_ms"] is not None:
        page_context["requested_at_ms"] = _int_field(
            page_context["requested_at_ms"], "requested_at_ms", minimum=0,
        )
    start_date, end_date = page.get("start_date"), page.get("end_date")
    if not isinstance(start_date, str) or not isinstance(end_date, str):
        raise ValueError("Every refresh page must declare its inclusive start_date and end_date scope")
    try:
        scope_start = date.fromisoformat(start_date)
        scope_end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("Refresh page date scope must use ISO dates") from exc
    if scope_start.isoformat() != start_date or scope_end.isoformat() != end_date or scope_start > scope_end:
        raise ValueError("Refresh page date scope is not a valid inclusive range")
    page_context["start_date"] = start_date
    page_context["end_date"] = end_date
    return page_context


def _profiles_and_exclusions(
    conn: sqlite3.Connection, repo_root: Path,
) -> tuple[dict[str, int], set[str], str, str]:
    required = {"horse_profile_latest", "horse_exclusions.json"}
    objects = {
        str(row[0]) for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    if "horse_profile_latest" not in objects:
        raise ValueError("horse_profile_latest is required for exact-ID cohort linking")
    columns = {str(row[1]) for row in conn.execute('PRAGMA table_info("horse_profile_latest")')}
    needed = {
        "horse_id", "horse_profile_observation_id", "breed_label_raw", "payload_sha256",
        "source_response_sha256",
    }
    if not needed.issubset(columns):
        raise ValueError("horse_profile_latest lacks required exact-ID profile columns")
    rows = conn.execute(
        "SELECT horse_id,horse_profile_observation_id,breed_label_raw,payload_sha256,source_response_sha256 "
        "FROM " + profile_relation(conn) + " WHERE breed_label_raw='제주마'"
    ).fetchall()
    profiles: dict[str, int] = {}
    for row in rows:
        horse_id = str(row[0])
        if not re.fullmatch(r"[0-9]+", horse_id) or int(horse_id) <= 0:
            continue
        if row[2] != "제주마":
            raise ValueError("horse_profile_latest returned a non-Jeju breed in its exact-breed filter")
        profiles[horse_id] = int(row[1])
    exclusions_path = repo_root / "jeju/data/horse_exclusions.json"
    try:
        exclusions = json.loads(exclusions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Could not read the Jeju horse exclusion registry") from exc
    horses = exclusions.get("horses") if isinstance(exclusions, dict) else None
    if not isinstance(horses, dict):
        raise ValueError("Jeju horse exclusion registry has an unsupported shape")
    excluded = {
        str(horse_id) for horse_id, item in horses.items()
        if isinstance(item, dict) and item.get("reimport_allowed") is False
    }
    profiles = {horse_id: obs_id for horse_id, obs_id in profiles.items() if horse_id not in excluded}
    snapshot = []
    profile_rows = {str(row[0]): tuple(row) for row in rows}
    for horse_id, obs_id in sorted(profiles.items()):
        row = profile_rows[horse_id]
        snapshot.append((horse_id, obs_id, row[2], row[3], row[4]))
    snapshot_json = canonical_json(snapshot)
    return profiles, excluded, sha256_bytes(snapshot_json.encode("utf-8")), snapshot_json


def _validate_required_schema(conn: sqlite3.Connection, families: set[str]) -> None:
    objects = {
        str(row[0]): str(row[1]) for row in conn.execute(
            "SELECT name,type FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    common = {
        "source_artifacts": "table", "api_records": "table", "horse_profile_latest": "view",
        "research_refresh_observations": "table", "research_refresh_holds": "table",
    }
    for name, kind in common.items():
        if objects.get(name) != kind:
            raise ValueError(f"Required source object {name} is missing or has the wrong type")
    required = {
        "daily_training": {"daily_training_api_artifacts": "table", "daily_training_api_rows": "table"},
        "medical": {"medical_api_rows": "table", "medical_api_diagnosis_slots": "table"},
        "starting_exam": {"starting_exam_api_rows": "table"},
    }
    for family in families:
        for name, kind in required[family].items():
            if objects.get(name) != kind:
                raise ValueError(f"Required normalized object {name} is missing or has the wrong type")
    assignment = objects.get("daily_training_rider_type_assignments")
    if "daily_training" in families and assignment != "table":
        raise ValueError("daily_training_rider_type_assignments table is required for new API18 rows")


def _ensure_source_artifact(conn: sqlite3.Connection, page: dict[str, Any], run_id: str) -> tuple[int, bool]:
    info = API[page["family"]]
    values = {
        "source_family": "kra_openapi",
        "source_role": "primary",
        "public_dataset_id": info["dataset_id"],
        "dataset_name": info["dataset_name"],
        "endpoint": info["endpoint"],
        "operation": info["operation"],
        "attempt_id": page["attempt_id"] or run_id,
        "request_params_json": canonical_json(page["params"]),
        "source_url_without_key": page["source_url_without_key"],
        "collected_at_utc": page["collected_at_utc"],
        "http_status_code": page["status_code"],
        "content_type": page["content_type"],
        "raw_relative_path": page["path"],
        "response_bytes": page["raw_bytes"],
        "sha256": page["sha256"],
        "parser_version": "jeju-auxiliary-incremental-v1",
    }
    columns = tuple(values)
    existing = conn.execute(
        "SELECT source_artifact_id,source_family,source_role,public_dataset_id,dataset_name,endpoint,operation,"
        "request_params_json,source_url_without_key,raw_relative_path,response_bytes,sha256 "
        "FROM source_artifacts WHERE raw_relative_path=? AND sha256=?",
        (page["path"], page["sha256"]),
    ).fetchall()
    if len(existing) > 1:
        raise ValueError(f"Multiple source_artifacts rows use the same frozen page {page['path']}")
    if existing:
        expected = (
            "kra_openapi", "primary", info["dataset_id"], info["dataset_name"],
            info["endpoint"], info["operation"],
            canonical_json(page["params"]), page["source_url_without_key"], page["path"],
            page["raw_bytes"], page["sha256"],
        )
        if tuple(existing[0][1:]) != expected:
            raise ValueError(f"Existing source artifact metadata conflicts with frozen page {page['path']}")
        return int(existing[0][0]), False
    values["created_at_utc"] = page["collected_at_utc"]
    insert_columns = (*columns, "created_at_utc")
    cursor = conn.execute(
        "INSERT INTO source_artifacts(" + ",".join(insert_columns) + ") VALUES(" +
        ",".join("?" for _ in insert_columns) + ")",
        tuple(values[name] for name in insert_columns),
    )
    return int(cursor.lastrowid), True


def _ensure_api_record(
    conn: sqlite3.Connection, artifact_id: int, row_index: int,
    record_type: str, natural_key: str | None, payload_json: str,
) -> tuple[int, bool]:
    digest = sha256_bytes(payload_json.encode("utf-8"))
    existing = conn.execute(
        "SELECT api_record_id,record_type,natural_key,payload_json,payload_sha256 "
        "FROM api_records WHERE source_artifact_id=? AND record_index=?",
        (artifact_id, row_index),
    ).fetchone()
    expected = (record_type, natural_key, payload_json, digest)
    if existing:
        observed = tuple(existing[1:])
        if observed != expected:
            raise ValueError("An existing API record at the same artifact/item index changed")
        return int(existing[0]), False
    cursor = conn.execute(
        "INSERT INTO api_records(source_artifact_id,record_index,record_type,natural_key,payload_json,payload_sha256) "
        "VALUES(?,?,?,?,?,?)",
        (artifact_id, row_index, record_type, natural_key, payload_json, digest),
    )
    return int(cursor.lastrowid), True


def _ensure_refresh_observation(
    conn: sqlite3.Connection, run_id: str, source_artifact_id: int, item_index: int,
    item: dict[str, Any], decision: str, notes: str | None,
) -> bool:
    stored_decision = {"new": "inserted", "unchanged": "unchanged", "held": "held"}[decision]
    expected = (
        item["family"], item["event_key"], item["payload_sha256"], item["payload_json"],
        item["event_date"],
    )
    existing = conn.execute(
        "SELECT observation_id,family,natural_key,payload_sha256,payload_json,event_date "
        "FROM research_refresh_observations WHERE source_artifact_id=? AND source_row_no=?",
        (source_artifact_id, item_index),
    ).fetchone()
    if existing:
        if tuple(existing[1:]) != expected:
            raise ValueError("An existing refresh observation changed at the same artifact/item position")
        return False
    conn.execute(
        "INSERT INTO research_refresh_observations(run_id,family,natural_key,source_artifact_id,"
        "source_row_no,payload_sha256,payload_json,event_date,decision,notes) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (run_id, *expected[:2], source_artifact_id, item_index, *expected[2:], stored_decision, notes),
    )
    return True


def _ensure_refresh_hold(
    conn: sqlite3.Connection, run_id: str, source_path: str, item: dict[str, Any], reason: str,
) -> bool:
    cursor = conn.execute(
        "INSERT OR IGNORE INTO research_refresh_holds(run_id,family,natural_key,payload_sha256,"
        "payload_json,source_path,reason) VALUES(?,?,?,?,?,?,?)",
        (run_id, item["family"], item["event_key"], item["payload_sha256"],
         item["payload_json"], source_path, reason),
    )
    return cursor.rowcount == 1


def _daily_time_fields(raw: dict[str, Any], event_date_raw: str) -> dict[str, Any]:
    start_local, start_status = parse_api_time(raw.get("stTime"), event_date_raw)
    end_local, end_status = parse_api_time(raw.get("spTime"), event_date_raw)
    start_dt = datetime.strptime(start_local, "%Y-%m-%d %H:%M:%S") if start_local else None
    end_dt = datetime.strptime(end_local, "%Y-%m-%d %H:%M:%S") if end_local else None
    if start_dt is None or end_dt is None:
        order_status = "unavailable"
    elif end_dt < start_dt:
        order_status = "reversed"
    else:
        order_status = "ordered"
    term = parse_integer_raw(raw.get("trTerm"))
    duration = None
    if term == 0:
        duration_status = "raw_zero_unavailable"
    elif term is None or term < 0:
        duration_status = "missing_or_invalid_raw"
    elif start_dt is None or end_dt is None or order_status != "ordered":
        duration_status = "positive_without_valid_times"
    else:
        seconds = int((end_dt - start_dt).total_seconds())
        if seconds == term and seconds > 0:
            duration, duration_status = term, "positive_matches_valid_times"
        else:
            duration_status = "positive_time_mismatch"
    run1 = parse_integer_raw(raw.get("run1Cnt"))
    run2 = parse_integer_raw(raw.get("run2Cnt"))
    return {
        "start_time_local": start_local,
        "start_time_status": start_status,
        "end_time_local": end_local,
        "end_time_status": end_status,
        "time_order_status": order_status,
        "duration_seconds": duration,
        "duration_status": duration_status,
        "run1_count": None,
        "run1_count_status": "all_zero_unavailable" if run1 == 0 else "unvalidated_null",
        "run2_count": None,
        "run2_count_status": "all_zero_unavailable" if run2 == 0 else "unvalidated_null",
    }


def _prepare_item(family: str, raw: dict[str, Any], profiles: dict[str, int], params: dict[str, str]) -> dict[str, Any]:
    if family == "daily_training":
        if raw.get("meet") != "제주":
            raise ValueError("API18 item does not declare the Jeju meet")
        raw_date, event_date = parse_api_date(raw.get("trDate"), "API18 trDate")
        month = params.get("tr_month")
        event_day = params.get("tr_date")
        if month is not None and (not re.fullmatch(r"[0-9]{6}", month) or raw_date[:6] != month):
            raise ValueError("API18 trDate differs from its tr_month request")
        if event_day is not None and (not re.fullmatch(r"[0-9]{8}", event_day) or raw_date != event_day):
            raise ValueError("API18 trDate differs from its tr_date request")
        if month is None and event_day is None:
            raise ValueError("API18 request must name tr_month or tr_date")
        horse_id = official_horse_id(raw.get("hrNo"))
        eligible = horse_id in profiles if horse_id else False
        daily_metrics = _daily_time_fields(raw, raw_date)
        quality = {
            f"start_time:{parse_api_time(raw.get('stTime'), raw_date)[1]}": 1,
            f"end_time:{parse_api_time(raw.get('spTime'), raw_date)[1]}": 1,
            f"time_order:{daily_metrics['time_order_status']}": 1,
            f"duration:{daily_metrics['duration_status']}": 1,
            f"run1_count:{daily_metrics['run1_count_status']}": 1,
            f"run2_count:{daily_metrics['run2_count_status']}": 1,
        }
        if horse_id is None:
            id_status = "invalid_raw_horse_id_format"
        elif eligible:
            id_status = "verified_jeju_profile_id"
        else:
            id_status = "profile_not_found"
        payload_json = canonical_json(raw)
        event_key = canonical_json([horse_id, event_date]) if eligible else None
        normalized = None
        if eligible:
            normalized = {
                "source_row_index": None,
                **{f"{field}_raw": api18_text(raw.get(field)) for field in API18_FIELDS},
                "raw_row_json": payload_json,
                "horse_id": horse_id,
                "horse_profile_observation_id": profiles[horse_id],
                "profile_match_status": "verified_jeju_profile_id",
                "training_date": event_date,
                **_daily_time_fields(raw, raw_date),
            }
        return {
            "eligible": eligible, "horse_id": horse_id, "event_date": event_date,
            "event_date_raw": raw_date, "event_key": event_key, "payload_json": payload_json,
            "payload_sha256": sha256_bytes(payload_json.encode("utf-8")),
            "id_status": id_status, "quality": quality, "normalized": normalized,
        }

    if family == "medical":
        if raw.get("meet") != "제주":
            raise ValueError("API16 item does not declare the Jeju meet")
        raw_date, event_date = parse_medical_date(raw.get("clinicDate"))
        horse_id = official_horse_id(raw.get("hrNo"))
        eligible = horse_id in profiles if horse_id else False
        present = sorted(raw.keys())
        absent = sorted(field for field in API16_FIELDS if field not in raw)
        types = {key: json_type(raw[key]) for key in sorted(raw)}
        payload_json = canonical_json(raw)
        event_key = canonical_json([horse_id, event_date, raw_text(raw.get("hospiName"))]) if eligible else None
        normalized = None
        if eligible:
            normalized = {
                "clinic_date": event_date,
                "horse_id": horse_id,
                "meet_raw": raw_text(raw.get("meet")),
                "clinic_date_raw": raw_date,
                "hr_name_raw": raw_text(raw.get("hrName")),
                "hr_no_raw": raw_text(raw.get("hrNo")),
                "hospi_name_raw": raw_text(raw.get("hospiName")),
                "ill_name1_raw": raw_text(raw.get("illName1")),
                "ill_name2_raw": raw_text(raw.get("illName2")),
                "part_raw": raw_text(raw.get("part")),
                "raw_key_presence_json": canonical_json(present),
                "raw_key_absence_json": canonical_json(absent),
                "raw_field_types_json": canonical_json(types),
            }
        return {
            "eligible": eligible, "horse_id": horse_id, "event_date": event_date,
            "event_date_raw": raw_date, "event_key": event_key, "payload_json": payload_json,
            "payload_sha256": sha256_bytes(payload_json.encode("utf-8")),
            "id_status": "invalid_raw_horse_id_format" if horse_id is None else
                         "verified_jeju_profile_id" if eligible else "profile_not_found",
            "quality": {}, "normalized": normalized,
        }

    if raw.get("meet") != "제주":
        raise ValueError("API21 item does not declare the Jeju meet")
    raw_date, event_date = parse_api_date(raw.get("trainDate"), "API21 trainDate")
    horse_id = official_horse_id(raw.get("hrNo"))
    eligible = horse_id in profiles if horse_id else False
    event_key = None
    if eligible:
        event_key = canonical_json([
            event_date,
            "" if raw.get("meet") is None else str(raw.get("meet")).strip(),
            "" if raw.get("trainNo") is None else str(raw.get("trainNo")).strip(),
            raw_text(raw.get("chulNo")), horse_id,
        ])
    payload_json = canonical_json(raw)
    normalized = None
    if eligible:
        pass_raw = "" if raw.get("passFlag") is None else str(raw.get("passFlag")).strip()
        judgment_label = None if not pass_raw or pass_raw == "-" else pass_raw
        trainer_name = "" if raw.get("trName") is None else str(raw.get("trName")).strip()
        trainer_no = "" if raw.get("trNo") is None else str(raw.get("trNo")).strip()
        trainer_id = trainer_no if trainer_name != "외부마" and re.fullmatch(r"[0-9]{6}", trainer_no) else None
        normalized = {
            "event_key": event_key,
            "exam_date": event_date,
            "horse_id": horse_id,
            **{API21_COLUMN_BY_SOURCE[field]: raw_text(raw.get(field)) for field in API21_FIELDS},
            "trainer_id_normalized": trainer_id,
            "judgment_label_normalized": judgment_label,
            "judgment_status": "unknown" if judgment_label is None else "observed",
            "raw_key_presence_json": canonical_json([field for field in API21_FIELDS if field in raw]),
            "raw_key_absence_json": canonical_json([field for field in API21_FIELDS if field not in raw]),
        }
    return {
        "eligible": eligible, "horse_id": horse_id, "event_date": event_date,
        "event_date_raw": raw_date, "event_key": event_key, "payload_json": payload_json,
        "payload_sha256": sha256_bytes(payload_json.encode("utf-8")),
        "id_status": "invalid_raw_horse_id_format" if horse_id is None else
                     "verified_jeju_profile_id" if eligible else "profile_not_found",
        "quality": {}, "normalized": normalized,
    }


def _daily_artifact_data(
    conn: sqlite3.Connection, page: dict[str, Any], items: list[dict[str, Any]],
    profiles_sha: str, module_sha: str,
) -> dict[str, Any]:
    params = page["params"]
    partition = params.get("tr_month") or params.get("tr_date")
    if params.get("tr_month"):
        page_kind = "monthly_archive"
        if not re.fullmatch(r"[0-9]{6}", partition):
            raise ValueError("API18 tr_month partition is invalid")
    elif params.get("tr_date"):
        page_kind = "daily_date_fallback"
        if not re.fullmatch(r"[0-9]{8}", partition):
            raise ValueError("API18 tr_date partition is invalid")
    else:
        raise ValueError("API18 source partition is missing")
    params_sha = sha256_bytes(canonical_json(params).encode("utf-8"))
    manifest_ref = page["source_manifest_sha256"] or "no-manifest"
    manifest_path_sha = sha256_bytes((page["source_manifest_path"] or "").encode("utf-8"))
    path_sha = sha256_bytes(page["path"].encode("utf-8"))
    capture_sha = sha256_bytes(page["collected_at_utc"].encode("utf-8"))
    source_partition = (
        f"refresh:{page['sha256']}:{params_sha}:{manifest_ref}:{manifest_path_sha}:"
        f"{profiles_sha}:{module_sha}:{path_sha}:{capture_sha}"
    )
    artifact_key = f"api18-refresh:{source_partition}:{page['page_no']}"
    raw_dates = sorted(item["event_date_raw"] for item in items)
    linked = sum(bool(item["eligible"]) for item in items)
    id_counts = Counter(item["id_status"] for item in items)
    quality_counts: Counter[str] = Counter()
    for item in items:
        quality_counts.update(item["quality"])
    summary = {
        "family": "daily_training", "page_sha256": page["sha256"],
        "page_path": page["path"], "params": params,
        "page_no": page["page_no"], "total_count": page["total_count"],
        "start_date": page["start_date"], "end_date": page["end_date"],
        "source_manifest_path": page["source_manifest_path"],
        "source_manifest_sha256": page["source_manifest_sha256"],
        "profile_snapshot_sha256": profiles_sha,
        "raw_item_count": len(items), "profile_matched_row_count": linked,
        "excluded_nonprofile_row_count": len(items) - linked,
        "in_scope_profile_rows": sum(bool(item["eligible"] and item["in_scope"]) for item in items),
        "out_of_scope_profile_rows": sum(bool(item["eligible"] and not item["in_scope"]) for item in items),
        "quarantined_invalid_id_count": id_counts["invalid_raw_horse_id_format"],
        "id_status_counts": dict(sorted(id_counts.items())),
        "quality_status_counts": dict(sorted(quality_counts.items())),
        "event_date_min": min(raw_dates) if raw_dates else None,
        "event_date_max": max(raw_dates) if raw_dates else None,
    }
    summary_sha = sha256_bytes(canonical_json(summary).encode("utf-8"))
    ledger_sha = page["source_manifest_sha256"] or sha256_bytes(canonical_json({
        "page_path": page["path"], "source_sha256": page["sha256"], "params": params,
        "page_no": page["page_no"], "total_count": page["total_count"],
        "start_date": page["start_date"], "end_date": page["end_date"],
        "collected_at_utc": page["collected_at_utc"],
    }).encode("utf-8"))
    archive_path = page["source_manifest_path"]
    archive_sha = page["source_manifest_sha256"]
    return {
        "artifact_key": artifact_key,
        "source_partition_key": source_partition,
        "source_page_kind": page_kind,
        "page_no": page["page_no"],
        "source_file_path": page["path"],
        "source_sha256": page["sha256"],
        "ledger_sha256": ledger_sha,
        "audit_script_sha256": module_sha,
        "audit_summary_sha256": summary_sha,
        "archive_manifest_path": archive_path,
        "archive_manifest_sha256": archive_sha,
        "profile_snapshot_sha256": profiles_sha,
        "source_url_without_key": page["source_url_without_key"],
        "requested_at_ms": page["requested_at_ms"],
        "retrieved_at_ms": page["retrieved_at_ms"],
        "status_code": page["status_code"],
        "api_result_code": page["api_result_code"],
        "raw_item_count": len(items),
        "profile_matched_row_count": linked,
        "excluded_nonprofile_row_count": len(items) - linked,
        "quarantined_invalid_id_count": id_counts["invalid_raw_horse_id_format"],
        "id_status_counts_json": canonical_json(dict(sorted(id_counts.items()))),
        "quality_status_counts_json": canonical_json(dict(sorted(quality_counts.items()))),
        "event_date_min": min(raw_dates) if raw_dates else None,
        "event_date_max": max(raw_dates) if raw_dates else None,
        "_summary": summary,
    }


DAILY_ARTIFACT_FIELDS = (
    "artifact_key", "source_partition_key", "source_page_kind", "page_no", "source_file_path",
    "source_sha256", "ledger_sha256", "audit_script_sha256", "audit_summary_sha256",
    "archive_manifest_path", "archive_manifest_sha256", "profile_snapshot_sha256",
    "source_url_without_key", "requested_at_ms", "retrieved_at_ms", "status_code",
    "api_result_code", "raw_item_count", "profile_matched_row_count",
    "excluded_nonprofile_row_count", "quarantined_invalid_id_count", "id_status_counts_json",
    "quality_status_counts_json", "event_date_min", "event_date_max",
)


def _ensure_daily_artifact(conn: sqlite3.Connection, artifact: dict[str, Any], now: str) -> tuple[int, bool]:
    existing = conn.execute(
        "SELECT daily_training_api_artifact_id," + ",".join(DAILY_ARTIFACT_FIELDS) +
        " FROM daily_training_api_artifacts WHERE artifact_key=?",
        (artifact["artifact_key"],),
    ).fetchone()
    expected = tuple(artifact[field] for field in DAILY_ARTIFACT_FIELDS)
    if existing:
        observed = tuple(existing[1:])
        if observed != expected:
            raise ValueError(f"Existing API18 refresh artifact differs: {artifact['artifact_key']}")
        return int(existing[0]), False
    columns = (*DAILY_ARTIFACT_FIELDS, "inserted_at_utc")
    cursor = conn.execute(
        "INSERT INTO daily_training_api_artifacts(" + ",".join(columns) + ") VALUES(" +
        ",".join("?" for _ in columns) + ")",
        tuple(artifact[field] for field in DAILY_ARTIFACT_FIELDS) + (now,),
    )
    return int(cursor.lastrowid), True


def _load_event_counts(conn: sqlite3.Connection, candidates: list[dict[str, Any]]) -> dict[str, Counter[str]]:
    """Load counts for only incoming event keys, avoiding a full-row Python scan."""
    if not candidates:
        return {family: Counter() for family in FAMILIES}
    conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS _jeju_aux_event_targets(" 
        "family TEXT NOT NULL, event_key TEXT NOT NULL, horse_id TEXT NOT NULL, event_date TEXT NOT NULL, "
        "hospital TEXT, PRIMARY KEY(family,event_key))"
    )
    conn.execute("DELETE FROM temp._jeju_aux_event_targets")
    unique = {
        (item["family"], item["event_key"], item["horse_id"], item["event_date"], item.get("hospital"))
        for item in candidates if item["event_key"] is not None
    }
    conn.executemany(
        "INSERT OR IGNORE INTO temp._jeju_aux_event_targets(family,event_key,horse_id,event_date,hospital) "
        "VALUES(?,?,?,?,?)", sorted(unique),
    )
    result = {family: Counter() for family in FAMILIES}
    queries = {
        "daily_training": """SELECT t.event_key,r.raw_row_json FROM daily_training_api_rows r
            JOIN temp._jeju_aux_event_targets t ON t.family='daily_training'
             AND t.horse_id=r.horse_id AND t.event_date=r.training_date""",
        "medical": """SELECT t.event_key,a.payload_json FROM medical_api_rows r
            JOIN api_records a ON a.api_record_id=r.api_record_id
            JOIN temp._jeju_aux_event_targets t ON t.family='medical'
             AND t.horse_id=r.horse_id AND t.event_date=r.clinic_date
             AND t.hospital IS r.hospi_name_raw""",
        "starting_exam": """SELECT t.event_key,a.payload_json FROM starting_exam_api_rows r
            JOIN api_records a ON a.api_record_id=r.api_record_id
            JOIN temp._jeju_aux_event_targets t ON t.family='starting_exam'
             AND t.event_key=r.event_key""",
    }
    target_families = {item["family"] for item in candidates}
    for family in target_families:
        for event_key, payload_json in conn.execute(queries[family]):
            payload_hash = sha256_bytes(str(payload_json).encode("utf-8"))
            result[family][f"{event_key}\x1f{payload_hash}"] += 1
            result[family][f"{event_key}\x1f*"] += 1
    return result


def _decide_item(
    item: dict[str, Any], baseline: Counter[str], seen: Counter[str],
) -> tuple[str, str | None]:
    event_key = item["event_key"]
    payload_key = f"{event_key}\x1f{item['payload_sha256']}"
    baseline_payload_count = baseline[payload_key]
    seen_payload_count = seen[payload_key]
    if seen_payload_count < baseline_payload_count:
        seen[payload_key] += 1
        seen[f"{event_key}\x1f*"] += 1
        return "unchanged", "matching_event_payload_already_observed"
    if baseline[f"{event_key}\x1f*"] == 0:
        seen[payload_key] += 1
        seen[f"{event_key}\x1f*"] += 1
        return "new", "additional_source_item_occurrence" if seen[f"{event_key}\x1f*"] > 1 else None
    if baseline_payload_count > 0:
        seen[payload_key] += 1
        seen[f"{event_key}\x1f*"] += 1
        return "new", "additional_source_item_occurrence"
    seen[payload_key] += 1
    seen[f"{event_key}\x1f*"] += 1
    return "held", "event_key_exists_with_different_payload_or_ambiguous_identity"


def _insert_daily_row(
    conn: sqlite3.Connection, artifact_id: int, item_index: int, normalized: dict[str, Any],
) -> int:
    values = {"daily_training_api_artifact_id": artifact_id, **normalized, "source_row_index": item_index}
    columns = (
        "daily_training_api_artifact_id", "source_row_index", *(f"{field}_raw" for field in API18_FIELDS),
        "raw_row_json", "horse_id", "horse_profile_observation_id", "profile_match_status",
        "training_date", "start_time_local", "start_time_status", "end_time_local", "end_time_status",
        "time_order_status", "duration_seconds", "duration_status", "run1_count", "run1_count_status",
        "run2_count", "run2_count_status",
    )
    exists = conn.execute(
        "SELECT daily_training_api_row_id," + ",".join(columns) +
        " FROM daily_training_api_rows WHERE daily_training_api_artifact_id=? AND source_row_index=?",
        (artifact_id, item_index),
    ).fetchone()
    expected = tuple(values.get(column) for column in columns)
    if exists:
        if tuple(exists[1:]) != expected:
            raise ValueError("Existing API18 normalized row differs at the same artifact/item position")
        return int(exists[0])
    cursor = conn.execute(
        "INSERT INTO daily_training_api_rows(" + ",".join(columns) + ") VALUES(" +
        ",".join("?" for _ in columns) + ")",
        expected,
    )
    return int(cursor.lastrowid)


def _ensure_daily_type_assignment(
    conn: sqlite3.Connection, row_id: int, artifact_id: int, normalized: dict[str, Any],
    *, allow_insert: bool = True,
) -> bool:
    raw_kind = normalized.get("prGubun_raw")
    kind = raw_kind if raw_kind in API18_RIDER_TYPES else "미분류"
    status = "api_explicit_type" if kind != "미분류" else "api_type_not_explicit"
    values = (
        row_id, artifact_id, raw_kind, normalized.get("prNo_raw"), normalized.get("horse_id"),
        normalized["training_date"], normalized.get("start_time_local"),
        normalized.get("end_time_local"), normalized.get("duration_seconds"),
        kind, status, None, None, None, None, None,
    )
    columns = (
        "daily_training_api_row_id", "daily_training_api_artifact_id", "prGubun_raw", "prNo_raw",
        "horse_id", "training_date", "start_time_local", "end_time_local", "duration_seconds",
        "rider_type", "type_status", "website_type", "website_label_raw", "website_jockey_name",
        "website_source_path", "website_sha256",
    )
    existing = conn.execute(
        "SELECT " + ",".join(columns) +
        " FROM daily_training_rider_type_assignments WHERE daily_training_api_row_id=?",
        (row_id,),
    ).fetchone()
    if existing:
        if tuple(existing) != values:
            raise ValueError("Existing API18 rider type assignment differs from its source row")
        return False
    if not allow_insert:
        raise ValueError("Existing API18 row is missing its rider type assignment")
    conn.execute(
        "INSERT INTO daily_training_rider_type_assignments(" + ",".join(columns) + ") VALUES(" +
        ",".join("?" for _ in columns) + ")", values,
    )
    return True


def _insert_medical_row(
    conn: sqlite3.Connection, artifact_id: int, item_index: int, api_record_id: int,
    normalized: dict[str, Any],
) -> int:
    columns = (
        "api_record_id", "source_artifact_id", "source_row_no", "clinic_date", "horse_id",
        "meet_raw", "clinic_date_raw", "hr_name_raw", "hr_no_raw", "hospi_name_raw",
        "ill_name1_raw", "ill_name2_raw", "part_raw", "raw_key_presence_json",
        "raw_key_absence_json", "raw_field_types_json",
    )
    values = (api_record_id, artifact_id, item_index, *(normalized[column] for column in columns[3:]))
    existing = conn.execute(
        "SELECT medical_api_row_id," + ",".join(columns) +
        " FROM medical_api_rows WHERE source_artifact_id=? AND source_row_no=?",
        (artifact_id, item_index),
    ).fetchone()
    if existing:
        if tuple(existing[1:]) != values:
            raise ValueError("Existing API16 normalized row differs at the same artifact/item position")
        return int(existing[0])
    cursor = conn.execute(
        "INSERT INTO medical_api_rows(" + ",".join(columns) + ") VALUES(" +
        ",".join("?" for _ in columns) + ")", values,
    )
    return int(cursor.lastrowid)


def _insert_medical_slots(
    conn: sqlite3.Connection, row_id: int, api_record_id: int, artifact_id: int,
    item_index: int, normalized: dict[str, Any], *, allow_insert: bool = True,
) -> int:
    inserted = 0
    for ordinal, (kind, raw) in enumerate((
        ("illName1", normalized["ill_name1_raw"]),
        ("illName2", normalized["ill_name2_raw"]),
    ), 1):
        digest = sha256_bytes(raw.encode("utf-8")) if raw is not None else None
        values = (
            row_id, api_record_id, artifact_id, item_index, normalized["horse_id"],
            normalized["clinic_date"], ordinal, kind, raw,
            None if raw is None or raw in {"", "-"} else raw, digest,
        )
        columns = (
            "medical_api_row_id", "api_record_id", "source_artifact_id", "source_row_no", "horse_id",
            "clinic_date", "source_slot_ordinal", "source_slot_kind", "raw_diagnosis_text",
            "normalized_diagnosis_text", "raw_text_sha256",
        )
        existing = conn.execute(
            "SELECT " + ",".join(columns) +
            " FROM medical_api_diagnosis_slots WHERE api_record_id=? AND source_slot_ordinal=?",
            (api_record_id, ordinal),
        ).fetchone()
        if existing:
            if tuple(existing) != values:
                raise ValueError("Existing API16 diagnosis slot differs from its source row")
            continue
        if not allow_insert:
            raise ValueError("Existing API16 row is missing a diagnosis slot")
        conn.execute(
            "INSERT INTO medical_api_diagnosis_slots(" + ",".join(columns) + ") VALUES(" +
            ",".join("?" for _ in columns) + ")", values,
        )
        inserted += 1
    return inserted


def _normalized_location_exists(
    conn: sqlite3.Connection, family: str, artifact_id: int, item_index: int,
) -> bool:
    if family == "daily_training":
        query = "SELECT 1 FROM daily_training_api_rows WHERE daily_training_api_artifact_id=? AND source_row_index=?"
    elif family == "medical":
        query = "SELECT 1 FROM medical_api_rows WHERE source_artifact_id=? AND source_row_no=?"
    else:
        query = "SELECT 1 FROM starting_exam_api_rows WHERE source_artifact_id=? AND source_row_no=?"
    return conn.execute(query, (artifact_id, item_index)).fetchone() is not None


def _insert_starting_exam_row(
    conn: sqlite3.Connection, artifact_id: int, item_index: int, api_record_id: int,
    normalized: dict[str, Any],
) -> bool:
    columns = (
        "api_record_id", "source_artifact_id", "source_row_no", "event_key", "exam_date", "horse_id",
        "meet_raw", "train_date_raw", "day_serial_raw", "train_no_raw", "chul_no_raw", "hr_name_raw",
        "hr_no_raw", "name_raw", "sex_raw", "age_raw", "rider_raw", "tr_name_raw", "tr_no_raw",
        "trainer_id_normalized", "ow_name_raw", "ow_no_raw", "pass_flag_raw", "judgment_label_normalized",
        "judgment_status", "reason_raw", "nopass_reason_raw", "raw_key_presence_json", "raw_key_absence_json",
    )
    values = (
        api_record_id, artifact_id, item_index, normalized["event_key"], normalized["exam_date"],
        normalized["horse_id"], *(normalized[column] for column in columns[6:]),
    )
    existing = conn.execute(
        "SELECT starting_exam_api_row_id," + ",".join(columns) +
        " FROM starting_exam_api_rows WHERE source_artifact_id=? AND source_row_no=?",
        (artifact_id, item_index),
    ).fetchone()
    if existing:
        if tuple(existing[1:]) != values:
            raise ValueError("Existing API21 normalized row differs at the same artifact/item position")
        return False
    conn.execute(
        "INSERT INTO starting_exam_api_rows(" + ",".join(columns) + ") VALUES(" +
        ",".join("?" for _ in columns) + ")", values,
    )
    return True


def apply_auxiliary(
    conn: sqlite3.Connection,
    pages: Iterable[Mapping[str, Any]],
    repo_root: str | Path,
    run_id: str,
) -> dict[str, Any]:
    """Apply validated API18/API16/API21 pages to an existing SQLite connection.

    Each page is a mapping with `family`, repository-relative `path`, `sha256`,
    `collected_at_utc`, public `params`, `total_count`, and `page_no`. Optional
    fields include the collector manifest path/hash, status, URL, attempt ID,
    content type, requested timestamp, and item count. The function does not
    commit; the caller owns rollback and commit.
    """
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be an open sqlite3.Connection")
    if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 200:
        raise ValueError("run_id must be a nonempty string of at most 200 characters")
    root = Path(repo_root)
    if not root.is_dir():
        raise ValueError("repo_root must name an existing directory")
    page_values = list(pages)
    prepared = [_prepare_page(page, root, run_id) for page in page_values]
    if len({page["path"] for page in prepared}) != len(prepared):
        raise ValueError("pages repeats a raw page path within one refresh")
    families = {page["family"] for page in prepared}
    _validate_required_schema(conn, families)
    profiles, excluded_ids, profile_snapshot_sha, profile_snapshot_json = _profiles_and_exclusions(conn, root)
    module_path = Path(__file__).resolve(strict=True)
    module_sha = sha256_bytes(module_path.read_bytes())

    prepared_items: list[dict[str, Any]] = []
    pages_rows: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for page in prepared:
        built: list[dict[str, Any]] = []
        for index, raw in enumerate(page["items"], 1):
            item = _prepare_item(page["family"], raw, profiles, page["params"])
            item.update({"family": page["family"], "source_row_no": index, "raw": raw, "page": page})
            item["in_scope"] = page["start_date"] <= item["event_date"] <= page["end_date"]
            item["excluded_by_registry"] = item["horse_id"] in excluded_ids if item["horse_id"] else False
            if item["excluded_by_registry"]:
                item["id_status"] = "excluded_reimport_blocked"
            if item["eligible"] and item["in_scope"]:
                prepared_items.append(item)
            built.append(item)
        pages_rows.append((page, built))

    candidates = [
        {"family": item["family"], "event_key": item["event_key"], "horse_id": item["horse_id"],
         "event_date": item["event_date"],
         "hospital": item["normalized"].get("hospi_name_raw") if item["family"] == "medical" else None}
        for item in prepared_items
    ]
    baseline_by_family = _load_event_counts(conn, candidates)
    seen_by_family = {family: Counter() for family in FAMILIES}
    for item in prepared_items:
        item["action"], item["reason"] = _decide_item(
            item, baseline_by_family[item["family"]], seen_by_family[item["family"]],
        )
    counts: dict[str, Any] = {
        "run_id": run_id, "pages_seen": len(prepared), "source_artifacts_added": 0,
        "daily_artifacts_added": 0, "api_records_added": 0, "rows_added": 0,
        "rows_unchanged": 0, "rows_held": 0, "excluded_nonprofile": 0,
        "invalid_id": 0, "excluded_reimport": 0, "out_of_scope": 0, "medical_slots_added": 0,
        "by_family": {family: {"pages": 0, "items": 0, "linked": 0, "added": 0,
                               "unchanged": 0, "held": 0, "excluded": 0, "invalid_id": 0,
                               "out_of_scope": 0, "excluded_reimport": 0}
                       for family in sorted(FAMILIES)},
        "held_observations": [],
        "audit_evidence_by_page": [],
        "profile_cohort_count": len(profiles),
        "profile_snapshot_sha256": profile_snapshot_sha,
        "profile_snapshot_canonical_json": profile_snapshot_json,
    }

    for page, page_items in pages_rows:
        family = page["family"]
        family_counts = counts["by_family"][family]
        family_counts["pages"] += 1
        family_counts["items"] += len(page_items)
        source_artifact_id, source_added = _ensure_source_artifact(conn, page, run_id)
        counts["source_artifacts_added"] += int(source_added)
        daily_artifact_id = None
        daily_artifact = None
        if family == "daily_training":
            daily_artifact = _daily_artifact_data(conn, page, page_items, profile_snapshot_sha, module_sha)
            daily_artifact_id, daily_added = _ensure_daily_artifact(
                conn, daily_artifact, page["collected_at_utc"],
            )
            counts["daily_artifacts_added"] += int(daily_added)
            audit_summary = daily_artifact["_summary"]
        else:
            id_counts = Counter(item["id_status"] for item in page_items)
            audit_summary = {
                "family": family,
                "page_path": page["path"],
                "page_sha256": page["sha256"],
                "params": page["params"],
                "page_no": page["page_no"],
                "total_count": page["total_count"],
                "raw_item_count": len(page_items),
                "start_date": page["start_date"],
                "end_date": page["end_date"],
                "source_manifest_path": page["source_manifest_path"],
                "source_manifest_sha256": page["source_manifest_sha256"],
                "profile_snapshot_sha256": profile_snapshot_sha,
                "profile_cohort_count": len(profiles),
                "profile_matched_row_count": sum(bool(item["eligible"]) for item in page_items),
                "excluded_nonprofile_row_count": sum(not item["eligible"] for item in page_items),
                "out_of_scope_profile_rows": sum(bool(item["eligible"] and not item["in_scope"]) for item in page_items),
                "excluded_reimport_blocked_count": id_counts["excluded_reimport_blocked"],
                "invalid_id_count": id_counts["invalid_raw_horse_id_format"],
                "id_status_counts": dict(sorted(id_counts.items())),
                "decision_counts": dict(sorted(Counter(
                    item["action"] for item in page_items if item["eligible"] and item["in_scope"]
                ).items())),
            }
        audit_summary_json = canonical_json(audit_summary)
        audit_summary_sha = sha256_bytes(audit_summary_json.encode("utf-8"))
        counts["audit_evidence_by_page"].append({
            "family": family,
            "page_path": page["path"],
            "page_sha256": page["sha256"],
            "source_manifest_path": page["source_manifest_path"],
            "source_manifest_sha256": page["source_manifest_sha256"],
            "profile_snapshot_sha256": profile_snapshot_sha,
            "validation_summary_json": audit_summary_json,
            "validation_summary_sha256": audit_summary_sha,
        })
        
        for item in page_items:
            if not item["eligible"]:
                counts["excluded_nonprofile"] += 1
                family_counts["excluded"] += 1
                if item["id_status"] == "invalid_raw_horse_id_format":
                    counts["invalid_id"] += 1
                    family_counts["invalid_id"] += 1
                if item["excluded_by_registry"]:
                    counts["excluded_reimport"] += 1
                    family_counts["excluded_reimport"] += 1
                continue
            if not item["in_scope"]:
                counts["out_of_scope"] += 1
                family_counts["excluded"] += 1
                family_counts["out_of_scope"] += 1
                continue
            counts["by_family"][family]["linked"] += 1
            api_natural_key = item["event_key"] if family == "starting_exam" else None
            record_id, record_added = _ensure_api_record(
                conn, source_artifact_id, item["source_row_no"], API[family]["record_type"],
                api_natural_key, item["payload_json"],
            )
            counts["api_records_added"] += int(record_added)
            action, reason = item["action"], item["reason"]
            normalized = item["normalized"]
            normalized_artifact_id = int(daily_artifact_id) if family == "daily_training" else source_artifact_id
            if _normalized_location_exists(
                conn, family, normalized_artifact_id, item["source_row_no"],
            ):
                if family == "daily_training":
                    row_id = _insert_daily_row(
                        conn, normalized_artifact_id, item["source_row_no"], normalized,
                    )
                    _ensure_daily_type_assignment(
                        conn, row_id, normalized_artifact_id, normalized, allow_insert=False,
                    )
                elif family == "medical":
                    row_id = _insert_medical_row(
                        conn, source_artifact_id, item["source_row_no"], record_id, normalized,
                    )
                    _insert_medical_slots(
                        conn, row_id, record_id, source_artifact_id, item["source_row_no"],
                        normalized, allow_insert=False,
                    )
                else:
                    _insert_starting_exam_row(
                        conn, source_artifact_id, item["source_row_no"], record_id, normalized,
                    )
                _ensure_refresh_observation(
                    conn, run_id, source_artifact_id, item["source_row_no"], item,
                    "unchanged", "normalized_source_position_already_present",
                )
                counts["rows_unchanged"] += 1
                family_counts["unchanged"] += 1
                continue
            if action == "unchanged":
                _ensure_refresh_observation(
                    conn, run_id, source_artifact_id, item["source_row_no"], item,
                    "unchanged", reason,
                )
                counts["rows_unchanged"] += 1
                family_counts["unchanged"] += 1
                continue
            if action == "held":
                _ensure_refresh_observation(
                    conn, run_id, source_artifact_id, item["source_row_no"], item,
                    "held", reason,
                )
                _ensure_refresh_hold(conn, run_id, page["path"], item, reason or "event_payload_conflict")
                counts["rows_held"] += 1
                family_counts["held"] += 1
                counts["held_observations"].append({
                    "family": family, "path": page["path"], "source_row_no": item["source_row_no"],
                    "horse_id": item["horse_id"], "event_date": item["event_date"],
                    "event_key": item["event_key"], "payload_sha256": item["payload_sha256"],
                    "reason": reason,
                })
                continue

            if family == "daily_training":
                row_id = _insert_daily_row(conn, normalized_artifact_id, item["source_row_no"], normalized)
                _ensure_daily_type_assignment(conn, row_id, normalized_artifact_id, normalized)
            elif family == "medical":
                row_id = _insert_medical_row(
                    conn, source_artifact_id, item["source_row_no"], record_id, normalized,
                )
                counts["medical_slots_added"] += _insert_medical_slots(
                    conn, row_id, record_id, source_artifact_id, item["source_row_no"], normalized,
                )
            else:
                _insert_starting_exam_row(
                    conn, source_artifact_id, item["source_row_no"], record_id, normalized,
                )
            _ensure_refresh_observation(
                conn, run_id, source_artifact_id, item["source_row_no"], item,
                "new", reason,
            )
            counts["rows_added"] += 1
            family_counts["added"] += 1
    return counts

