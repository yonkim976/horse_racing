"""Append validated current API42_1 horse profiles to the Jeju SQLite store.

The importer reads only the frozen local collection and writes only the
Jeju-specific SQLite database. Raw API response bytes remain immutable files;
each parsed horse object is retained in api_records and linked to a
retrieval-time observation. No historical race or trial row is updated.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = REPO_ROOT / "jeju/data/jeju_native_core.sqlite3"
COLLECTION_DIR = REPO_ROOT / "jeju/research/20260930_api42_horse_breed_collection"
IMPORT_DIR = REPO_ROOT / "jeju/research/20261001_api42_profile_db_import"
BACKUP_PATH = IMPORT_DIR / "backups/jeju_native_core_before_api42_20261001.sqlite3"
MIGRATION_PATH = REPO_ROOT / "jeju/data/schema/migrations/20261001_add_api42_horse_profiles.sql"
TARGET_MANIFEST_PATH = COLLECTION_DIR / "target_manifest.json"
TARGET_IDS_PATH = COLLECTION_DIR / "target_ids.jsonl"
CROSSWALK_PATH = COLLECTION_DIR / "api20_crosswalk.jsonl"
LEDGER_PATH = COLLECTION_DIR / "request_ledger.jsonl"
COLLECTION_SUMMARY_PATH = COLLECTION_DIR / "collection_summary.json"
INDEPENDENT_VERIFICATION_PATH = REPO_ROOT / "jeju/research/20261001_api42_collection_verification/verification.json"
DB_BASELINE_PATH = REPO_ROOT / "jeju/research/20261001_api42_collection_verification/db_before_import.json"
IMPORT_MANIFEST_PATH = IMPORT_DIR / "import_manifest.json"
FIRST_IMPORT_MANIFEST_PATH = IMPORT_DIR / "first_import_manifest.json"
IDEMPOTENCY_REPORT_PATH = IMPORT_DIR / "idempotency_check.json"

OPERATION = "totalHorseInfo_1"
DATASET_ID = "15057985"
DATASET_NAME = "한국마사회 마필종합 상세정보"
ENDPOINT = "https://apis.data.go.kr/B551015/API42_1/totalHorseInfo_1"
IMPORT_BATCH_ID = "api42_current_profile_observations_20261001"
ATTEMPT_PREFIX = f"{IMPORT_BATCH_ID}:"
PARSER_VERSION = "jeju-api42-current-profile-import-v1"
BREED_EVIDENCE_KIND = "API42_1 current profile breed"
TIMING_BASIS = "profile_retrieval_time"
API_SUCCESS_CODES = {"00", "0000"}
PLACEHOLDER_BREEDS = {"", "-", "--", "—", "–", "0", "n/a", "na", "null", "none", "unknown", "미상"}
OFFICIAL_NORMALIZED_FIELDS = {
    "horse_name_raw": "hrNm",
    "birth_date_raw": "birthDt",
    "age_raw": "age",
    "breed_label_raw": "breed",
    "sex_raw": "sex",
    "color_raw": "color",
    "production_country_raw": "prdCty",
}


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


def raw_text(value: Any) -> str | None:
    return None if value is None else str(value)


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def iso_now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"Expected JSON object at {path.name}:{line_number}")
        rows.append(value)
    return rows


def project_relative(path: Path) -> str:
    resolved = path.resolve(strict=True)
    return resolved.relative_to(REPO_ROOT.resolve()).as_posix()


def resolve_raw_path(raw_relative_path: Any) -> tuple[Path, str]:
    if not isinstance(raw_relative_path, str) or not raw_relative_path:
        raise ValueError("Validated event is missing raw_response_file")
    relative = PurePosixPath(raw_relative_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("Raw response path is not a safe relative path")
    candidate = COLLECTION_DIR.joinpath(*relative.parts)
    resolved = candidate.resolve(strict=True)
    resolved.relative_to(COLLECTION_DIR.resolve(strict=True))
    return resolved, project_relative(resolved)


def extract_profile(raw: bytes) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("API42 response root is not an object")
    response = payload.get("response")
    if not isinstance(response, dict):
        raise ValueError("API42 response wrapper is missing")
    header = response.get("header")
    body = response.get("body")
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError("API42 header or body is missing")
    items = body.get("items")
    if isinstance(items, dict):
        items = items.get("item")
    if isinstance(items, dict):
        rows = [items]
    elif isinstance(items, list) and all(isinstance(row, dict) for row in items):
        rows = items
    else:
        rows = []
    if len(rows) != 1:
        raise ValueError(f"Expected exactly one API42 profile item; found {len(rows)}")
    return header, body, rows[0]


def ensure_kst_date(timestamp: str, expected_date: str) -> str:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Observation timestamp must include a timezone")
    kst_date = parsed.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()
    if kst_date != expected_date:
        raise ValueError("Ledger KST date does not match retrieval timestamp")
    return kst_date


def load_expected_profiles() -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    target_manifest = read_json(TARGET_MANIFEST_PATH)
    target_bytes = TARGET_IDS_PATH.read_bytes()
    crosswalk_bytes = CROSSWALK_PATH.read_bytes()
    target_hash = sha256_bytes(target_bytes)
    crosswalk_hash = sha256_bytes(crosswalk_bytes)
    if target_hash != target_manifest.get("target_ids_sha256"):
        raise ValueError("Frozen target ID SHA-256 does not match target manifest")
    if crosswalk_hash != target_manifest.get("api20_crosswalk_sha256"):
        raise ValueError("Frozen API20 crosswalk SHA-256 does not match target manifest")

    verification = read_json(INDEPENDENT_VERIFICATION_PATH)
    ledger_bytes = LEDGER_PATH.read_bytes()
    ledger_hash = sha256_bytes(ledger_bytes)
    if ledger_hash != verification.get("request_ledger_sha256"):
        raise ValueError("Request ledger SHA-256 differs from independent verification")
    if verification.get("target_ids") != target_manifest.get("target_count"):
        raise ValueError("Independent verification target count does not match manifest")
    if verification.get("validated_unique_ids") != target_manifest.get("target_count"):
        raise ValueError("Independent verification does not show complete unique-ID coverage")
    if verification.get("remaining_ids") != []:
        raise ValueError("Independent verification reports remaining target IDs")
    if verification.get("api42_vs_api20_breed_conflict_ids") != []:
        raise ValueError("Independent verification reports API42/API20 breed conflicts")

    targets = read_jsonl(TARGET_IDS_PATH)
    target_group: dict[str, str] = {}
    for row in targets:
        horse_id = clean(row.get("hrNo"))
        group = row.get("priority_group")
        if not horse_id or group not in {"race_result_candidate", "api20_jeju_supplement"}:
            raise ValueError("Frozen target has a missing ID or unsupported group")
        if horse_id in target_group:
            raise ValueError("Frozen target list contains duplicate horse IDs")
        target_group[horse_id] = group
    if len(target_group) != target_manifest.get("target_count"):
        raise ValueError("Frozen target ID count does not match manifest")
    group_counts = Counter(target_group.values())
    if group_counts != Counter({"race_result_candidate": 4006, "api20_jeju_supplement": 611}):
        raise ValueError(f"Unexpected frozen target group counts: {dict(group_counts)}")

    ledger = read_jsonl(LEDGER_PATH)
    successful_by_id: dict[str, list[dict[str, Any]]] = {}
    for event in ledger:
        if event.get("validation_status") != "validated":
            continue
        horse_id = clean(event.get("hrNo"))
        if horse_id not in target_group:
            raise ValueError("Validated request ledger row contains an ID outside the frozen target set")
        if event.get("priority_group") != target_group[horse_id]:
            raise ValueError("Validated request ledger group does not match frozen target group")
        successful_by_id.setdefault(horse_id, []).append(event)

    if set(successful_by_id) != set(target_group):
        raise ValueError("Validated request ledger IDs do not exactly cover the frozen target set")
    duplicate_successes = {horse_id: len(events) for horse_id, events in successful_by_id.items() if len(events) != 1}
    if duplicate_successes:
        raise ValueError("Expected exactly one successful observation per target ID; duplicate successful rows found")

    summary = read_json(COLLECTION_SUMMARY_PATH)
    if summary.get("validated_profile_count") != len(target_group):
        raise ValueError("Collection summary does not confirm all target profiles")
    if summary.get("remaining_total_count") != 0:
        raise ValueError("Collection summary reports uncollected targets")
    if summary.get("api42_current_breed_distribution_validated_only") != {"제주마": len(target_group)}:
        raise ValueError("Collection summary breed distribution does not match the validated Jeju profiles")

    expected: list[dict[str, Any]] = []
    for horse_id in sorted(target_group):
        event = successful_by_id[horse_id][0]
        if event.get("http_status") != 200 or event.get("api_result_code") not in API_SUCCESS_CODES:
            raise ValueError(f"Validated profile has a non-success HTTP/API status: {horse_id}")
        if event.get("api_total_count") != 1 or event.get("actual_item_count") != 1:
            raise ValueError(f"Validated profile does not have exactly one result item: {horse_id}")
        if event.get("returned_hrNo_values") != [horse_id]:
            raise ValueError(f"Validated profile returned a different official horse ID: {horse_id}")
        if event.get("response_sha256_verified") is not True:
            raise ValueError(f"Validated profile raw response was not marked SHA-verified: {horse_id}")

        raw_path, raw_project_path = resolve_raw_path(event.get("raw_response_file"))
        raw = raw_path.read_bytes()
        response_sha256 = sha256_bytes(raw)
        if response_sha256 != event.get("response_sha256"):
            raise ValueError(f"Raw response SHA-256 differs from request ledger: {horse_id}")
        if len(raw) != event.get("response_bytes"):
            raise ValueError(f"Raw response byte size differs from request ledger: {horse_id}")

        header, body, profile = extract_profile(raw)
        response_code = clean(header.get("resultCode"))
        if response_code not in API_SUCCESS_CODES or response_code != event.get("api_result_code"):
            raise ValueError(f"Raw API result code differs from validated ledger: {horse_id}")
        if int(body.get("totalCount", -1)) != 1:
            raise ValueError(f"Raw API totalCount is not one: {horse_id}")
        profile_id = clean(profile.get("hrNo"))
        if profile_id != horse_id:
            raise ValueError(f"Raw profile hrNo does not match requested horse ID: {horse_id}")
        breed = raw_text(profile.get("breed"))
        if clean(breed) in PLACEHOLDER_BREEDS or clean(breed) != event.get("breed_raw"):
            raise ValueError(f"Raw profile breed is empty, placeholder, or differs from ledger: {horse_id}")
        if clean(breed) != "제주마":
            raise ValueError(f"Unexpected current profile breed in this frozen Jeju target batch: {horse_id}")
        profile_name = raw_text(profile.get("hrNm"))
        if clean(profile_name) != clean(event.get("profile_name")):
            raise ValueError(f"Raw profile hrNm differs from validated ledger: {horse_id}")

        retrieved_at_utc = event.get("retrieved_at_utc")
        if not isinstance(retrieved_at_utc, str):
            raise ValueError(f"Validated profile is missing retrieval timestamp: {horse_id}")
        observed_kst_date = ensure_kst_date(retrieved_at_utc, clean(event.get("kst_date")))
        attempt_number = event.get("attempt_no")
        run_id = event.get("run_id")
        if not isinstance(attempt_number, int) or attempt_number < 1 or not isinstance(run_id, str) or not run_id:
            raise ValueError(f"Validated profile has malformed request attempt identity: {horse_id}")
        params = event.get("public_params")
        if not isinstance(params, dict) or clean(params.get("hr_no")) != horse_id:
            raise ValueError(f"Validated profile public request parameters do not match horse ID: {horse_id}")
        if set(params) != {"_type", "pageNo", "numOfRows", "hr_no"}:
            raise ValueError("Request ledger public parameters contain unexpected fields")
        if params.get("_type") != "json" or params.get("pageNo") != 1 or params.get("numOfRows") != 1000:
            raise ValueError(f"Validated profile request parameters do not match collection contract: {horse_id}")

        payload_json = canonical_json(profile)
        payload_sha256 = sha256_bytes(payload_json.encode("utf-8"))
        attempt_id = f"{ATTEMPT_PREFIX}{horse_id}:{run_id}:{attempt_number}"
        expected.append({
            "horse_id": horse_id,
            "priority_group": target_group[horse_id],
            "event": event,
            "profile": profile,
            "raw_path": raw_path,
            "raw_project_path": raw_project_path,
            "raw": raw,
            "response_sha256": response_sha256,
            "retrieved_at_utc": retrieved_at_utc,
            "observed_kst_date": observed_kst_date,
            "attempt_id": attempt_id,
            "request_params_json": canonical_json(params),
            "payload_json": payload_json,
            "payload_sha256": payload_sha256,
            "normalized": {
                column: raw_text(profile.get(field))
                for column, field in OFFICIAL_NORMALIZED_FIELDS.items()
            },
        })

    ledger_day_counts = Counter(event.get("kst_date") for event in ledger)
    if ledger_day_counts != Counter({"2026-09-30": 3000, "2026-10-01": 1718}):
        raise ValueError(f"Unexpected date-specific API42 request counts: {dict(ledger_day_counts)}")
    if verification.get("request_attempts") != len(ledger):
        raise ValueError("Independent verification ledger attempt count differs")
    return expected, target_group, {
        "target_manifest": target_manifest,
        "target_ids_sha256": target_hash,
        "api20_crosswalk_sha256": crosswalk_hash,
        "request_ledger_sha256": ledger_hash,
        "verification": verification,
        "group_counts": dict(group_counts),
        "summary": summary,
    }


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def verify_pristine_backup(path: Path, baseline: dict[str, Any]) -> None:
    conn = open_readonly(path)
    try:
        table_names = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if table_names != set(baseline["tables"]):
            raise ValueError("Existing backup is not the pre-import database snapshot")
        for table, old in baseline["tables"].items():
            current_count = conn.execute("SELECT count(*) FROM " + quote_identifier(table)).fetchone()[0]
            if current_count != old["rows"]:
                raise ValueError(f"Existing backup row count differs from pre-import baseline: {table}")
        current_views = dict(conn.execute("SELECT name,sql FROM sqlite_master WHERE type='view' ORDER BY name"))
        if current_views != baseline["existing_views"]:
            raise ValueError("Existing backup views differ from pre-import baseline")
        integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise ValueError("SQLite backup failed integrity_check")
    finally:
        conn.close()


def create_or_validate_backup(baseline: dict[str, Any]) -> dict[str, Any]:
    BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if BACKUP_PATH.exists():
        verify_pristine_backup(BACKUP_PATH, baseline)
        return {
            "path": project_relative(BACKUP_PATH),
            "sha256": sha256_file(BACKUP_PATH),
            "bytes": BACKUP_PATH.stat().st_size,
            "reused_existing_verified_backup": True,
        }

    db_size = DATABASE_PATH.stat().st_size
    free_bytes = shutil.disk_usage(BACKUP_PATH.parent).free
    if free_bytes < db_size + (32 * 1024 * 1024):
        raise OSError("Insufficient free space to preserve a full SQLite backup")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".api42-db-backup-", suffix=".sqlite3", dir=BACKUP_PATH.parent, delete=False) as stream:
            temp_path = Path(stream.name)
        source = open_readonly(DATABASE_PATH)
        destination = sqlite3.connect(temp_path)
        try:
            source.backup(destination)
            destination.commit()
            integrity = [row[0] for row in destination.execute("PRAGMA integrity_check")]
            if integrity != ["ok"]:
                raise ValueError("SQLite backup failed integrity_check")
        finally:
            destination.close()
            source.close()
        verify_pristine_backup(temp_path, baseline)
        with temp_path.open("rb+") as stream:
            os.fsync(stream.fileno())
        os.link(temp_path, BACKUP_PATH)
        temp_path.unlink(missing_ok=True)
        temp_path = None
        return {
            "path": project_relative(BACKUP_PATH),
            "sha256": sha256_file(BACKUP_PATH),
            "bytes": BACKUP_PATH.stat().st_size,
            "reused_existing_verified_backup": False,
        }
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def apply_migration(conn: sqlite3.Connection) -> None:
    migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
    try:
        conn.executescript("BEGIN IMMEDIATE;\n" + migration_sql + "\nCOMMIT;")
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def metadata_values(source_info: dict[str, Any]) -> dict[str, str]:
    return {
        "api42_profile_import_batch_id": IMPORT_BATCH_ID,
        "api42_profile_target_ids_sha256": source_info["target_ids_sha256"],
        "api42_profile_request_ledger_sha256": source_info["request_ledger_sha256"],
        "api42_profile_observation_count": "4617",
    }


def find_batch_artifacts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT source_artifact_id,attempt_id FROM source_artifacts "
        "WHERE operation=? AND attempt_id LIKE ? ORDER BY attempt_id",
        (OPERATION, ATTEMPT_PREFIX + "%"),
    ).fetchall()


def expected_artifact_values(item: dict[str, Any], created_at_utc: str) -> tuple[Any, ...]:
    event = item["event"]
    return (
        "kra_openapi", "primary", DATASET_ID, DATASET_NAME, ENDPOINT, OPERATION,
        item["attempt_id"], item["request_params_json"], ENDPOINT,
        item["retrieved_at_utc"], 200, event.get("content_type"), item["raw_project_path"],
        len(item["raw"]), item["response_sha256"], PARSER_VERSION, created_at_utc,
    )


def expected_observation_values(item: dict[str, Any], api_record_id: int) -> tuple[Any, ...]:
    n = item["normalized"]
    return (
        api_record_id, item["horse_id"], item["retrieved_at_utc"], item["observed_kst_date"],
        n["horse_name_raw"], n["birth_date_raw"], n["age_raw"], n["breed_label_raw"],
        n["sex_raw"], n["color_raw"], n["production_country_raw"],
    )


def existing_batch_matches(conn: sqlite3.Connection, expected: list[dict[str, Any]], source_info: dict[str, Any]) -> bool:
    artifacts = find_batch_artifacts(conn)
    if not artifacts:
        return False
    expected_by_attempt = {item["attempt_id"]: item for item in expected}
    if len(artifacts) != len(expected_by_attempt) or {row["attempt_id"] for row in artifacts} != set(expected_by_attempt):
        raise ValueError("A partial or unexpected API42 import batch already exists")

    artifact_columns = (
        "source_family,source_role,public_dataset_id,dataset_name,endpoint,operation,attempt_id,"
        "request_params_json,source_url_without_key,collected_at_utc,http_status_code,content_type,"
        "raw_relative_path,response_bytes,sha256,parser_version,created_at_utc"
    )
    for artifact_row in artifacts:
        item = expected_by_attempt[artifact_row["attempt_id"]]
        artifact_id = artifact_row["source_artifact_id"]
        artifact = conn.execute(
            f"SELECT {artifact_columns} FROM source_artifacts WHERE source_artifact_id=?",
            (artifact_id,),
        ).fetchone()
        if artifact is None:
            raise ValueError("API42 source artifact disappeared during idempotency check")
        expected_static = expected_artifact_values(item, artifact["created_at_utc"])
        if tuple(artifact) != expected_static:
            raise ValueError(f"Existing API42 source artifact differs from frozen input: {item['horse_id']}")

        api_rows = conn.execute(
            "SELECT api_record_id,record_index,record_type,natural_key,payload_json,payload_sha256 "
            "FROM api_records WHERE source_artifact_id=? ORDER BY record_index",
            (artifact_id,),
        ).fetchall()
        if len(api_rows) != 1:
            raise ValueError(f"Existing API42 source artifact has unexpected API record count: {item['horse_id']}")
        api_row = api_rows[0]
        if tuple(api_row[1:]) != (1, "horse_profile", item["horse_id"], item["payload_json"], item["payload_sha256"]):
            raise ValueError(f"Existing API42 API record differs from frozen response: {item['horse_id']}")
        api_record_id = api_row[0]
        observation = conn.execute(
            "SELECT api_record_id,horse_id,observed_at_utc,observed_kst_date,horse_name_raw,birth_date_raw,"
            "age_raw,breed_label_raw,sex_raw,color_raw,production_country_raw "
            "FROM horse_profile_observations WHERE api_record_id=?",
            (api_record_id,),
        ).fetchone()
        if observation is None or tuple(observation) != expected_observation_values(item, api_record_id):
            raise ValueError(f"Existing normalized API42 observation differs from frozen response: {item['horse_id']}")
        evidence = conn.execute(
            "SELECT horse_id,observed_event_date,breed_label_raw,evidence_kind,source_artifact_id,api_record_id,"
            "timing_basis,notes FROM breed_evidence WHERE api_record_id=?",
            (api_record_id,),
        ).fetchall()
        expected_evidence = (
            item["horse_id"], None, item["normalized"]["breed_label_raw"], BREED_EVIDENCE_KIND,
            artifact_id, api_record_id, TIMING_BASIS,
            "Current API42_1 profile breed observed at retrieved_at_utc; no historical event date or effective period asserted.",
        )
        if len(evidence) != 1 or tuple(evidence[0]) != expected_evidence:
            raise ValueError(f"Existing API42 breed evidence differs from retrieval-time observation: {item['horse_id']}")

    expected_metadata = metadata_values(source_info)
    for key, expected_value in expected_metadata.items():
        row = conn.execute("SELECT value FROM schema_metadata WHERE key=?", (key,)).fetchone()
        if row is None or row[0] != expected_value:
            raise ValueError(f"Existing API42 import metadata is missing or inconsistent: {key}")
    return True


def insert_import_batch(conn: sqlite3.Connection, expected: list[dict[str, Any]], source_info: dict[str, Any]) -> dict[str, Any]:
    if find_batch_artifacts(conn):
        raise ValueError("API42 import artifacts exist but were not accepted as an exact idempotent import")
    if conn.execute("SELECT count(*) FROM horse_profile_observations").fetchone()[0] != 0:
        raise ValueError("Horse profile observations already exist outside this import batch")
    existing_api42_evidence = conn.execute(
        "SELECT count(*) FROM breed_evidence WHERE evidence_kind=? AND timing_basis=?",
        (BREED_EVIDENCE_KIND, TIMING_BASIS),
    ).fetchone()[0]
    if existing_api42_evidence:
        raise ValueError("Retrieval-time API42 breed evidence already exists outside this import batch")

    expected_metadata = metadata_values(source_info)
    for key, expected_value in expected_metadata.items():
        row = conn.execute("SELECT value FROM schema_metadata WHERE key=?", (key,)).fetchone()
        if row is not None and row[0] != expected_value:
            raise ValueError(f"Conflicting schema_metadata key exists and will not be overwritten: {key}")

    created_at_utc = iso_now_utc()
    inserted_artifacts = 0
    inserted_api_records = 0
    inserted_observations = 0
    inserted_evidence = 0
    for item in expected:
        event = item["event"]
        artifact_values = expected_artifact_values(item, created_at_utc)
        artifact_cursor = conn.execute(
            """INSERT INTO source_artifacts(
                   source_family,source_role,public_dataset_id,dataset_name,endpoint,operation,
                   attempt_id,request_params_json,source_url_without_key,collected_at_utc,
                   http_status_code,content_type,raw_relative_path,response_bytes,sha256,
                   parser_version,created_at_utc)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            artifact_values,
        )
        artifact_id = int(artifact_cursor.lastrowid)
        inserted_artifacts += 1

        api_cursor = conn.execute(
            """INSERT INTO api_records(
                   source_artifact_id,record_index,record_type,natural_key,payload_json,payload_sha256)
               VALUES(?,1,'horse_profile',?,?,?)""",
            (artifact_id, item["horse_id"], item["payload_json"], item["payload_sha256"]),
        )
        api_record_id = int(api_cursor.lastrowid)
        inserted_api_records += 1

        observation_values = expected_observation_values(item, api_record_id)
        conn.execute(
            """INSERT INTO horse_profile_observations(
                   api_record_id,horse_id,observed_at_utc,observed_kst_date,
                   horse_name_raw,birth_date_raw,age_raw,breed_label_raw,sex_raw,color_raw,production_country_raw)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            observation_values,
        )
        inserted_observations += 1

        evidence_notes = (
            "Current API42_1 profile breed observed at retrieved_at_utc; "
            "no historical event date or effective period asserted."
        )
        conn.execute(
            """INSERT INTO breed_evidence(
                   horse_id,observed_event_date,breed_label_raw,evidence_kind,source_artifact_id,
                   api_record_id,timing_basis,notes)
               VALUES(?,NULL,?,?,?,?,?,?)""",
            (
                item["horse_id"], item["normalized"]["breed_label_raw"], BREED_EVIDENCE_KIND,
                artifact_id, api_record_id, TIMING_BASIS, evidence_notes,
            ),
        )
        inserted_evidence += 1

    for key, value in expected_metadata.items():
        conn.execute(
            "INSERT OR IGNORE INTO schema_metadata(key,value) VALUES(?,?)",
            (key, value),
        )
    return {
        "source_artifacts_inserted": inserted_artifacts,
        "api_records_inserted": inserted_api_records,
        "horse_profile_observations_inserted": inserted_observations,
        "breed_evidence_inserted": inserted_evidence,
        "schema_metadata_keys_added": len(expected_metadata),
        "created_at_utc": created_at_utc,
    }


def verify_imported_batch(conn: sqlite3.Connection, expected: list[dict[str, Any]], target_group: dict[str, str]) -> dict[str, Any]:
    source_count = conn.execute(
        "SELECT count(*) FROM source_artifacts WHERE operation=? AND attempt_id LIKE ?",
        (OPERATION, ATTEMPT_PREFIX + "%"),
    ).fetchone()[0]
    api_count = conn.execute(
        """SELECT count(*) FROM api_records a JOIN source_artifacts sa USING(source_artifact_id)
           WHERE sa.operation=? AND sa.attempt_id LIKE ?""",
        (OPERATION, ATTEMPT_PREFIX + "%"),
    ).fetchone()[0]
    observation_count = conn.execute(
        """SELECT count(*) FROM horse_profile_observations hpo
           JOIN api_records a USING(api_record_id)
           JOIN source_artifacts sa USING(source_artifact_id)
           WHERE sa.operation=? AND sa.attempt_id LIKE ?""",
        (OPERATION, ATTEMPT_PREFIX + "%"),
    ).fetchone()[0]
    evidence_count = conn.execute(
        """SELECT count(*) FROM breed_evidence be
           JOIN source_artifacts sa USING(source_artifact_id)
           WHERE sa.operation=? AND sa.attempt_id LIKE ? AND be.evidence_kind=? AND be.timing_basis=?""",
        (OPERATION, ATTEMPT_PREFIX + "%", BREED_EVIDENCE_KIND, TIMING_BASIS),
    ).fetchone()[0]
    if (source_count, api_count, observation_count, evidence_count) != (4617, 4617, 4617, 4617):
        raise ValueError("Imported source, API record, observation, or evidence count is incomplete")

    profile_rows = conn.execute(
        "SELECT horse_id,observed_at_utc,observed_kst_date,breed_label_raw FROM horse_profile_latest"
    ).fetchall()
    profiles_by_id = {row["horse_id"]: row for row in profile_rows}
    if len(profiles_by_id) != len(profile_rows):
        raise ValueError("Latest horse profile view returned duplicate horse IDs")
    missing_ids = set(target_group) - set(profiles_by_id)
    if missing_ids:
        raise ValueError(f"Latest horse profile view is missing target IDs: {len(missing_ids)}")
    for item in expected:
        row = profiles_by_id[item["horse_id"]]
        if (row["observed_at_utc"], row["observed_kst_date"], row["breed_label_raw"]) != (
            item["retrieved_at_utc"], item["observed_kst_date"], item["normalized"]["breed_label_raw"],
        ):
            raise ValueError(f"Latest horse profile view does not match imported response: {item['horse_id']}")

    candidate_ids = {horse_id for horse_id, group in target_group.items() if group == "race_result_candidate"}
    supplement_ids = {horse_id for horse_id, group in target_group.items() if group == "api20_jeju_supplement"}
    candidate_coverage = len(candidate_ids & set(profiles_by_id))
    supplement_coverage = len(supplement_ids & set(profiles_by_id))
    if (candidate_coverage, supplement_coverage) != (4006, 611):
        raise ValueError("Horse profile view coverage does not match frozen candidate and supplement cohorts")

    evidence_with_event_date = conn.execute(
        """SELECT count(*) FROM breed_evidence be
           JOIN source_artifacts sa USING(source_artifact_id)
           WHERE sa.operation=? AND sa.attempt_id LIKE ? AND be.observed_event_date IS NOT NULL""",
        (OPERATION, ATTEMPT_PREFIX + "%"),
    ).fetchone()[0]
    if evidence_with_event_date:
        raise ValueError("API42 retrieval-time breed evidence was assigned a historical event date")

    foreign_key_violations = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]
    integrity_check = [row[0] for row in conn.execute("PRAGMA integrity_check")]
    if foreign_key_violations or integrity_check != ["ok"]:
        raise ValueError("SQLite integrity or foreign-key check failed")
    return {
        "source_artifact_count": source_count,
        "api_record_count": api_count,
        "horse_profile_observation_count": observation_count,
        "breed_evidence_count": evidence_count,
        "candidate_join_coverage": {"covered": candidate_coverage, "target": 4006},
        "supplement_join_coverage": {"covered": supplement_coverage, "target": 611},
        "latest_profile_unique_horse_count": len(profiles_by_id),
        "latest_breed_distribution": dict(sorted(Counter(row["breed_label_raw"] for row in profile_rows).items())),
        "api42_breed_evidence_with_event_date": evidence_with_event_date,
        "integrity_check": integrity_check,
        "foreign_key_violations": foreign_key_violations,
    }


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def run_import() -> dict[str, Any]:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    expected, target_group, source_info = load_expected_profiles()
    baseline = read_json(DB_BASELINE_PATH)
    backup_info = create_or_validate_backup(baseline)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        apply_migration(conn)
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise ValueError("SQLite foreign-key enforcement is not enabled")
        conn.execute("BEGIN IMMEDIATE")
        try:
            no_insert = existing_batch_matches(conn, expected, source_info)
            if no_insert:
                inserted = {
                    "source_artifacts_inserted": 0,
                    "api_records_inserted": 0,
                    "horse_profile_observations_inserted": 0,
                    "breed_evidence_inserted": 0,
                    "schema_metadata_keys_added": 0,
                    "created_at_utc": None,
                }
            else:
                inserted = insert_import_batch(conn, expected, source_info)
            verification = verify_imported_batch(conn, expected, target_group)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

    report = {
        "status": "idempotent_no_insert" if no_insert else "imported",
        "generated_at_utc": iso_now_utc(),
        "import_batch_id": IMPORT_BATCH_ID,
        "database_path": project_relative(DATABASE_PATH),
        "migration_path": project_relative(MIGRATION_PATH),
        "backup": backup_info,
        "source": {
            "collection_dir": project_relative(COLLECTION_DIR),
            "target_count": len(expected),
            "target_ids_sha256": source_info["target_ids_sha256"],
            "api20_crosswalk_sha256": source_info["api20_crosswalk_sha256"],
            "request_ledger_sha256": source_info["request_ledger_sha256"],
            "request_attempt_count": source_info["verification"]["request_attempts"],
            "collection_dates_kst": source_info["verification"]["validated_profile_observation_dates_kst"],
            "groups": source_info["group_counts"],
            "normalized_official_fields": OFFICIAL_NORMALIZED_FIELDS,
            "raw_response_field_count_in_payload_json": 218,
            "profile_observation_timing": "retrieval-time observation; not backdated to any race or trial date",
        },
        "inserted": inserted,
        "verification": verification,
        "idempotency_verified": False if not no_insert else True,
    }

    if no_insert:
        idempotency = {
            "verified_at_utc": report["generated_at_utc"],
            "import_batch_id": IMPORT_BATCH_ID,
            "second_run_inserted_rows": 0,
            "matched_existing_source_artifacts": verification["source_artifact_count"],
            "matched_existing_api_records": verification["api_record_count"],
            "matched_existing_profile_observations": verification["horse_profile_observation_count"],
            "matched_existing_breed_evidence": verification["breed_evidence_count"],
            "result": "exact idempotent rerun; no inserts or updates",
        }
        atomic_write_json(IDEMPOTENCY_REPORT_PATH, idempotency)
        existing_report = read_json(IMPORT_MANIFEST_PATH) if IMPORT_MANIFEST_PATH.exists() else {}
        if existing_report and existing_report.get("backup", {}).get("sha256") != backup_info["sha256"]:
            raise ValueError("Existing import manifest backup hash differs from verified backup")
        report["idempotency_verified"] = True
        report["idempotency_check_path"] = project_relative(IDEMPOTENCY_REPORT_PATH)
    if not no_insert:
        # Preserve the first successful insertion report separately so a
        # later no-insert rerun cannot erase the original insert counts/time.
        atomic_write_json(FIRST_IMPORT_MANIFEST_PATH, report)
    elif IMPORT_MANIFEST_PATH.exists() and not FIRST_IMPORT_MANIFEST_PATH.exists():
        prior_report = read_json(IMPORT_MANIFEST_PATH)
        if prior_report.get("status") == "imported":
            atomic_write_json(FIRST_IMPORT_MANIFEST_PATH, prior_report)
    atomic_write_json(IMPORT_MANIFEST_PATH, report)
    return report


if __name__ == "__main__":
    result = run_import()
    print(json.dumps({
        "status": result["status"],
        "database_path": result["database_path"],
        "backup_path": result["backup"]["path"],
        "backup_sha256": result["backup"]["sha256"],
        "target_count": result["source"]["target_count"],
        "inserted": result["inserted"],
        "verification": {
            "source_artifact_count": result["verification"]["source_artifact_count"],
            "api_record_count": result["verification"]["api_record_count"],
            "horse_profile_observation_count": result["verification"]["horse_profile_observation_count"],
            "breed_evidence_count": result["verification"]["breed_evidence_count"],
            "candidate_join_coverage": result["verification"]["candidate_join_coverage"],
            "supplement_join_coverage": result["verification"]["supplement_join_coverage"],
            "latest_breed_distribution": result["verification"]["latest_breed_distribution"],
            "integrity_check": result["verification"]["integrity_check"],
            "foreign_key_violation_count": len(result["verification"]["foreign_key_violations"]),
        },
        "idempotency_verified": result["idempotency_verified"],
    }, ensure_ascii=False))
