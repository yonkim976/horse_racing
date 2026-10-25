#!/usr/bin/env python3
"""Read-only independent checks for the daily training rider identity migration.

The verifier compares the preserved pre-migration SQLite copy with the target
database. It opens both databases with SQLite URI mode=ro and enables
query_only. Existing table contents are compared row-for-row through sorted
SHA-256 row digests, so row order does not affect the result while repeated
rows remain significant.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import struct
import sys
import re
from html.parser import HTMLParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[4]
RESEARCH_ROOT = PROJECT_ROOT / "jeju/research/20261015_training_rider_identity"
DEFAULT_BASELINE = RESEARCH_ROOT / "root/before_rider_identity.sqlite3"
DEFAULT_TARGET = PROJECT_ROOT / "jeju/data/jeju_native_core.sqlite3"
DEFAULT_REPORT = RESEARCH_ROOT / "verification/baseline_preservation_report.json"
VERIFICATION_ROOT = RESEARCH_ROOT / "verification"
JOCKEY_ROSTER_DIR = PROJECT_ROOT / "data/research/jockey_roster_20261008"

EXPECTED_NEW_OBJECTS = {
    "daily_training_riders": "view",
    "daily_training_riders_analysis_2026": "view",
    "training_rider_identity_reviews": "table",
    "training_rider_website_observations": "table",
}
EXPECTED_SOURCE_ROWS = 908_316
EXPECTED_ANALYSIS_ROWS = 907_389
EXPECTED_MISSING_EMPLOYEE_ROWS = 92_165
EXPECTED_ROSTER_JEJU_JOCKEYS = 92
VALID_EMPLOYEE_NUMBER = re.compile(r"[0-9]{6}\Z")


class KRAProfileHTMLParser(HTMLParser):
    """Extract table-cell text and input values from archived KRA HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.inputs: dict[str, str] = {}
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag == "input" and attr.get("name") and attr.get("value") is not None:
            self.inputs[str(attr["name"])] = str(attr["value"])
        elif tag in ("td", "th") and self._row is not None:
            self._cell_parts = []
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._row is not None and self._cell_parts is not None:
            text = re.sub(r"\s+", " ", " ".join(self._cell_parts)).strip()
            self._row.append(text)
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell_parts = None


def parse_kra_profile_page(raw: bytes) -> KRAProfileHTMLParser:
    parser = KRAProfileHTMLParser()
    parser.feed(raw.decode("euc-kr"))
    parser.close()
    return parser


def quote_identifier(identifier: str) -> str:
    """Quote a SQLite identifier obtained from sqlite_master/PRAGMA metadata."""
    return '"' + identifier.replace('"', '""') + '"'


def readonly_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {path}")
    # Path.as_uri percent-encodes path characters and avoids URI option injection.
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = None
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
        connection.close()
        raise RuntimeError(f"SQLite query_only could not be enabled: {path}")
    connection.execute("BEGIN")
    return connection


def schema_objects(connection: sqlite3.Connection) -> dict[tuple[str, str], str | None]:
    rows = connection.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE type IN ('table','index','view','trigger') "
        "ORDER BY type, name"
    )
    return {(kind, name): sql for kind, name, sql in rows}


def table_names(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    return [row[0] for row in rows]


def row_digest(row: Iterable[Any]) -> bytes:
    """Return a type-aware digest for a row, preserving NULL/empty/type details."""
    hasher = hashlib.sha256()
    for value in row:
        if value is None:
            tag, encoded = b"N", b""
        elif isinstance(value, int):
            tag, encoded = b"I", str(value).encode("ascii")
        elif isinstance(value, float):
            tag, encoded = b"F", struct.pack(">d", value)
        elif isinstance(value, str):
            tag, encoded = b"T", value.encode("utf-8")
        elif isinstance(value, bytes):
            tag, encoded = b"B", value
        else:
            raise TypeError(f"Unexpected SQLite value type: {type(value).__name__}")
        hasher.update(tag)
        hasher.update(struct.pack(">Q", len(encoded)))
        hasher.update(encoded)
    return hasher.digest()


def table_fingerprint(connection: sqlite3.Connection, table: str) -> dict[str, Any]:
    identifier = quote_identifier(table)
    columns = [
        row[1]
        for row in connection.execute(f"PRAGMA table_info({identifier})")
    ]
    if not columns:
        raise RuntimeError(f"No columns found for table {table!r}")

    count = connection.execute(f"SELECT COUNT(*) FROM {identifier}").fetchone()[0]
    row_hashes: list[bytes] = []
    cursor = connection.execute(f"SELECT * FROM {identifier}")
    while rows := cursor.fetchmany(8192):
        row_hashes.extend(row_digest(row) for row in rows)
    row_hashes.sort()
    table_hash = hashlib.sha256()
    for digest in row_hashes:
        table_hash.update(digest)
    if len(row_hashes) != count:
        raise RuntimeError(
            f"Row count changed during fingerprinting of {table}: "
            f"COUNT(*)={count}, iterated={len(row_hashes)}"
        )
    return {
        "row_count": count,
        "columns": columns,
        "rows_sha256_unordered": table_hash.hexdigest(),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def official_jockey_roster_check() -> dict[str, Any]:
    manifest_path = JOCKEY_ROSTER_DIR / "manifest.json"
    api_path = JOCKEY_ROSTER_DIR / "api_2.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_sha = sha256_file(api_path)
    declared_shas = {
        row["api_sha256"]
        for row in manifest["rows"]
        if row["meet_code"] == 2
    }
    if declared_shas != {actual_sha}:
        raise RuntimeError("API307 meet=2 archive SHA does not match its manifest")

    payload = json.loads(api_path.read_text(encoding="utf-8"))
    response = payload["response"]
    if str(response["header"]["resultCode"]) not in ("00", "0"):
        raise RuntimeError("API307 meet=2 source has a non-success response")
    body = response["body"]
    items = body["items"]["item"]
    if isinstance(items, dict):
        items = [items]
    total_count = int(body["totalCount"])
    pairs = [
        (str(item.get("jkNo")), str(item.get("jkName")))
        for item in items
        if VALID_EMPLOYEE_NUMBER.fullmatch(str(item.get("jkNo")))
        and item.get("jkName") not in (None, "", "-")
    ]
    id_count = len({number for number, _ in pairs})
    pair_count = len(set(pairs))
    return {
        "path": str(api_path.relative_to(PROJECT_ROOT)),
        "sha256": actual_sha,
        "observed_at": manifest.get("observed_at"),
        "api_total_count": total_count,
        "valid_six_digit_jockey_ids": len(pairs),
        "distinct_jockey_ids": id_count,
        "distinct_id_name_pairs": pair_count,
        "expected_jeju_jockey_count": EXPECTED_ROSTER_JEJU_JOCKEYS,
        "status": (
            "ok"
            if total_count == EXPECTED_ROSTER_JEJU_JOCKEYS
            and len(pairs) == EXPECTED_ROSTER_JEJU_JOCKEYS
            and id_count == EXPECTED_ROSTER_JEJU_JOCKEYS
            and pair_count == EXPECTED_ROSTER_JEJU_JOCKEYS
            else "failed"
        ),
    }


def official_database_identity_maps(
    connection: sqlite3.Connection,
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, Any]]:
    """Read independent jockey/trainer name sets from archived API4/API20 rows."""
    query = """
        SELECT 'jockey' AS person_kind, jockey_id AS person_id,
               jockey_name AS person_name, api_record_id
        FROM race_result_rows
        UNION ALL
        SELECT 'jockey', jockey_id, jockey_name, api_record_id
        FROM running_trial_rows
        UNION ALL
        SELECT 'trainer', trainer_id, trainer_name, api_record_id
        FROM race_result_rows
        UNION ALL
        SELECT 'trainer', trainer_id, trainer_name, api_record_id
        FROM running_trial_rows
    """
    jockey_names: dict[str, set[str]] = {}
    trainer_names: dict[str, set[str]] = {}
    witness_count = 0
    malformed: list[dict[str, Any]] = []
    endpoints: set[str] = set()
    seen_pairs: set[tuple[str, str, str]] = set()
    for kind, person_id, person_name, record_id in connection.execute(query):
        if not VALID_EMPLOYEE_NUMBER.fullmatch(str(person_id)) or person_name in (None, "", "-"):
            continue
        person_id = str(person_id)
        person_name = str(person_name)
        dest = jockey_names if kind == "jockey" else trainer_names
        dest.setdefault(person_id, set()).add(person_name)
        pair = (kind, person_id, person_name)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        record = connection.execute(
            "SELECT a.payload_json, a.payload_sha256, s.endpoint, s.operation "
            "FROM api_records a JOIN source_artifacts s USING(source_artifact_id) "
            "WHERE a.api_record_id=?",
            (record_id,),
        ).fetchone()
        if record is None:
            malformed.append({"kind": kind, "id": person_id, "name": person_name, "reason": "missing api_record"})
            continue
        payload_json, payload_sha, endpoint, operation = record
        expected_endpoint = (
            "https://apis.data.go.kr/B551015/API4_3/raceResult_3"
            if operation == "raceResult_3"
            else "https://apis.data.go.kr/B551015/API20_1/ridingTestResult_1"
            if operation == "ridingTestResult_1"
            else None
        )
        payload = json.loads(payload_json)
        id_key, name_key = ("jkNo", "jkName") if kind == "jockey" else ("trNo", "trName")
        if (
            expected_endpoint is None
            or endpoint != expected_endpoint
            or str(payload.get(id_key)) != person_id
            or payload.get(name_key) != person_name
            or hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest() != payload_sha
        ):
            malformed.append(
                {"kind": kind, "id": person_id, "name": person_name, "record_id": record_id,
                 "reason": "API4/API20 witness differs from normalized DB identity"}
            )
        else:
            witness_count += 1
            endpoints.add(endpoint)
    details = {
        "distinct_jockey_id_name_pairs": sum(len(names) for names in jockey_names.values()),
        "distinct_jockey_ids": len(jockey_names),
        "distinct_trainer_id_name_pairs": sum(len(names) for names in trainer_names.values()),
        "distinct_trainer_ids": len(trainer_names),
        "verified_api4_api20_witness_pairs": witness_count,
        "verified_endpoints": sorted(endpoints),
        "malformed_or_missing_witnesses": malformed,
        "status": "ok" if not malformed and witness_count == len(seen_pairs) else "failed",
    }
    return jockey_names, trainer_names, details


def review_reference_checks(
    baseline: sqlite3.Connection,
    target: sqlite3.Connection,
) -> dict[str, Any]:
    """Check every review identity against raw role/ID groups and source evidence."""
    group_rows = {
        (role, number): (count, first_date, last_date)
        for role, number, count, first_date, last_date in baseline.execute(
            "SELECT prGubun_raw, prNo_raw, COUNT(*), MIN(training_date), MAX(training_date) "
            "FROM daily_training_api_rows GROUP BY prGubun_raw, prNo_raw"
        )
    }
    table = target.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='training_rider_identity_reviews'"
    ).fetchone()
    if not table:
        return {"status": "failed", "error": "training_rider_identity_reviews is missing"}

    roster_manifest = json.loads((JOCKEY_ROSTER_DIR / "manifest.json").read_text(encoding="utf-8"))
    jockey_names, trainer_names, historical = official_database_identity_maps(baseline)
    jockey_names = {key: set(values) for key, values in jockey_names.items()}
    roster_ids_by_meet: dict[str, set[str]] = {}
    roster_pairs_by_meet: dict[str, set[tuple[str, str]]] = {}
    for meet in (1, 2, 3):
        roster_path = JOCKEY_ROSTER_DIR / f"api_{meet}.json"
        roster_sha = sha256_file(roster_path)
        declared = {
            row["api_sha256"] for row in roster_manifest["rows"]
            if str(row["meet_code"]) == str(meet)
        }
        if declared != {roster_sha}:
            raise RuntimeError(f"API307 meet={meet} archive SHA does not match its manifest")
        roster_payload = json.loads(roster_path.read_text(encoding="utf-8"))
        if str(roster_payload["response"]["header"]["resultCode"]) not in ("00", "0"):
            raise RuntimeError(f"API307 meet={meet} response is unsuccessful")
        roster_rows = roster_payload["response"]["body"]["items"]["item"]
        if isinstance(roster_rows, dict):
            roster_rows = [roster_rows]
        pairs: set[tuple[str, str]] = set()
        for item in roster_rows:
            number, name = str(item.get("jkNo")), item.get("jkName")
            if VALID_EMPLOYEE_NUMBER.fullmatch(number) and name not in (None, "", "-"):
                pairs.add((number, str(name)))
                jockey_names.setdefault(number, set()).add(str(name))
        roster_ids_by_meet[str(meet)] = {number for number, _ in pairs}
        roster_pairs_by_meet[str(meet)] = pairs

    ledger_path = RESEARCH_ROOT / "source_review/staff_website_identity_evidence.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    web_names: dict[str, set[str]] = {}
    web_event_ids: set[int] = set()
    web_personless_ids: set[str] = set()
    ledger_items: dict[int, dict[str, Any]] = {}
    for item in ledger.get("evidence", []) + ledger.get("unresolved_observations", []):
        event_id = int(item["training_row_id"])
        previous = ledger_items.get(event_id)
        if previous is not None and previous != item:
            raise RuntimeError(f"Conflicting duplicate ledger event {event_id}")
        ledger_items[event_id] = item
        web_event_ids.add(event_id)
        if item.get("person_name"):
            web_names.setdefault(str(item["employee_number"]), set()).add(str(item["person_name"]))
        else:
            web_personless_ids.add(str(item["employee_number"]))

    rows = target.execute(
        "SELECT rider_category_raw, employee_number_raw, rider_name, reference_person_kind, "
        "identity_status, training_rows, first_training_date, last_training_date, "
        "witness_api_record_id, witness_payload_sha256, evidence_json "
        "FROM training_rider_identity_reviews"
    ).fetchall()
    actual = {(row[0], row[1]): row[2:] for row in rows}
    duplicate_key_count = len(rows) - len(actual)
    missing_groups = sorted(set(group_rows) - set(actual))
    extra_groups = sorted(set(actual) - set(group_rows))
    structural_mismatches = []
    identity_mismatches = []
    forbidden_trname_evidence = []
    allowed_web_roles = {"-", "조교보", "조교승인"}

    for key in sorted(set(group_rows) & set(actual)):
        role, number = key
        count, first_date, last_date = group_rows[key]
        (name, kind, status, stored_count, stored_first, stored_last,
         witness_id, witness_sha, evidence_json) = actual[key]
        if (stored_count, stored_first, stored_last) != (count, first_date, last_date):
            structural_mismatches.append({
                "role": role, "employee_number": number,
                "expected": [count, first_date, last_date],
                "actual": [stored_count, stored_first, stored_last],
            })

        expected_kind = None
        expected_status = "unresolved_employee_number"
        if number in ("", "-"):
            expected_status = "missing_employee_number"
        elif not VALID_EMPLOYEE_NUMBER.fullmatch(str(number)):
            expected_status = "invalid_employee_number"
        else:
            known = [candidate for candidate, mapping in (("기수", jockey_names), ("조교사", trainer_names)) if number in mapping]
            if role in ("기수", "기수후보생"):
                if "기수" in known:
                    expected_kind = "기수"
                    expected_status = "matched_jockey_id" if role == "기수" else "matched_jockey_id_candidate_role"
                elif known:
                    expected_status = "role_number_conflict"
            elif role == "조교사":
                if "조교사" in known:
                    expected_kind, expected_status = "조교사", "matched_trainer_id"
                elif known:
                    expected_status = "role_number_conflict"
            elif role == "-":
                if len(known) == 1:
                    expected_kind, expected_status = known[0], "matched_id_role_not_provided"
                elif len(known) > 1:
                    expected_status = "ambiguous_person_role"
            if expected_kind is None and expected_status == "unresolved_employee_number" and role in allowed_web_roles and number in web_names:
                expected_kind = "홈페이지기승자"
                expected_status = "matched_employee_number_website_reference"
            elif expected_kind is None and expected_status == "unresolved_employee_number" and number in web_personless_ids:
                expected_status = "website_person_name_not_provided"

        source_names: set[str] = set()
        if expected_kind == "기수":
            source_names = jockey_names.get(str(number), set())
        elif expected_kind == "조교사":
            source_names = trainer_names.get(str(number), set())
        elif expected_kind == "홈페이지기승자":
            source_names = web_names.get(str(number), set())
        if expected_kind is not None and len(source_names) == 1:
            expected_name = next(iter(source_names))
        else:
            expected_name = None
            if expected_kind is not None and len(source_names) > 1:
                expected_status = "ambiguous_reference_names"
                expected_kind = None

        try:
            evidence = json.loads(evidence_json)
        except (TypeError, json.JSONDecodeError):
            evidence = None
        if not isinstance(evidence, list):
            identity_mismatches.append({"role": role, "employee_number": number, "reason": "evidence_json is not a JSON list"})
            evidence = []
        evidence_names: set[str] = set()
        evidence_types: set[str] = set()
        for evidence_row in evidence:
            if not isinstance(evidence_row, dict):
                continue
            evidence_type = evidence_row.get("type")
            evidence_types.add(str(evidence_type))
            if evidence_type == "api307":
                payload = evidence_row.get("payload") or {}
                if str(payload.get("jkNo")) == str(number) and payload.get("jkName"):
                    evidence_names.add(str(payload["jkName"]))
            elif evidence_type == "historical_official_api":
                record_id = evidence_row.get("api_record_id")
                record = baseline.execute(
                    "SELECT a.payload_json, a.payload_sha256, s.operation "
                    "FROM api_records a JOIN source_artifacts s USING(source_artifact_id) "
                    "WHERE a.api_record_id=?", (record_id,),
                ).fetchone()
                if record:
                    payload_json, payload_sha, operation = record
                    payload = json.loads(payload_json)
                    field = "jkNo" if expected_kind == "기수" else "trNo"
                    name_field = "jkName" if expected_kind == "기수" else "trName"
                    if str(payload.get(field)) == str(number) and payload.get(name_field):
                        evidence_names.add(str(payload[name_field]))
                    if hashlib.sha256(
                        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest() != payload_sha:
                        identity_mismatches.append({"role": role, "employee_number": number, "reason": "historical evidence payload SHA mismatch"})
                    if operation not in ("raceResult_3", "ridingTestResult_1"):
                        identity_mismatches.append({"role": role, "employee_number": number, "reason": "unexpected historical endpoint"})
            elif evidence_type == "official_daily_training_website":
                if evidence_row.get("employee_number") == number and evidence_row.get("person_name"):
                    evidence_names.add(str(evidence_row["person_name"]))
                    if int(evidence_row.get("training_row_id", -1)) not in web_event_ids:
                        identity_mismatches.append({"role": role, "employee_number": number, "reason": "website evidence row absent from source ledger"})
            if evidence_row.get("trName") or evidence_row.get("trName_raw"):
                forbidden_trname_evidence.append({"role": role, "employee_number": number})

        actual_identity = (name, kind, status)
        expected_identity = (expected_name, expected_kind, expected_status)
        if actual_identity != expected_identity:
            identity_mismatches.append({
                "role": role, "employee_number": number,
                "expected": list(expected_identity), "actual": list(actual_identity),
            })
        if name is not None and (name not in evidence_names or not evidence_types):
            identity_mismatches.append({"role": role, "employee_number": number, "reason": "assigned name lacks matching source name in evidence_json"})
        if name is None and status.startswith("matched_"):
            identity_mismatches.append({"role": role, "employee_number": number, "reason": "matched status has no assigned name"})
        if name is not None and number in ("", "-"):
            identity_mismatches.append({"role": role, "employee_number": number, "reason": "missing employee-number sentinel has assigned name"})
        if witness_id is not None:
            w = baseline.execute(
                "SELECT payload_sha256 FROM api_records WHERE api_record_id=?", (witness_id,)
            ).fetchone()
            if not w or w[0] != witness_sha:
                identity_mismatches.append({"role": role, "employee_number": number, "reason": "witness record SHA does not match baseline"})

    # A personless website marker is retained for review but must never become a rider name.
    personless_rows = target.execute(
        "SELECT COUNT(*) FROM training_rider_website_observations WHERE person_name IS NULL"
    ).fetchone()[0] if target.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='training_rider_website_observations'"
    ).fetchone() else None
    review_status_counts = {
        status: {"groups": groups, "training_rows": training_rows}
        for status, groups, training_rows in target.execute(
            "SELECT identity_status, COUNT(*), SUM(training_rows) "
            "FROM training_rider_identity_reviews GROUP BY identity_status ORDER BY identity_status"
        )
    }
    return {
        "raw_role_number_groups": len(group_rows),
        "review_rows": len(rows),
        "duplicate_review_keys": duplicate_key_count,
        "missing_review_groups": missing_groups,
        "extra_review_groups": extra_groups,
        "group_count_or_date_mismatches": structural_mismatches,
        "official_api4_api20_identity_sources": historical,
        "website_named_employee_ids": len(web_names),
        "website_named_events": sum(1 for item in ledger_items.values() if item.get("person_name")),
        "website_personless_events": sum(1 for item in ledger_items.values() if not item.get("person_name")),
        "website_personless_employee_ids": sorted(web_personless_ids),
        "api307_all_meet_roster": {
            meet: {"ids": len(ids), "id_name_pairs": len(roster_pairs_by_meet[meet])}
            for meet, ids in roster_ids_by_meet.items()
        },
        "website_personless_observation_rows_loaded": personless_rows,
        "named_training_rows_from_review_groups": sum(
            row[5] for row in rows if row[2] is not None
        ),
        "unresolved_training_rows_from_review_groups": sum(
            row[5] for row in rows if row[2] is None
        ),
        "review_group_status_counts": review_status_counts,
        "unresolved_groups_with_empty_evidence_json": sum(
            1 for row in rows if row[2] is None and row[10] in (None, "", "[]")
        ),
        "identity_or_evidence_mismatches": identity_mismatches,
        "evidence_mentions_trainer_name_field": forbidden_trname_evidence,
        "status": (
            "ok"
            if len(rows) == len(group_rows)
            and duplicate_key_count == 0
            and not missing_groups
            and not extra_groups
            and not structural_mismatches
            and historical["status"] == "ok"
            and not identity_mismatches
            and not forbidden_trname_evidence
            and personless_rows == sum(1 for item in ledger_items.values() if not item.get("person_name"))
            else "failed"
        ),
    }


def unresolved_reason_artifact_checks(target: sqlite3.Connection) -> dict[str, Any]:
    """Ensure every unresolved valid role/employee pair has a reviewed CSV reason."""
    review_exists = target.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='training_rider_identity_reviews'"
    ).fetchone()
    if not review_exists:
        return {"status": "failed", "error": "training_rider_identity_reviews is missing"}
    csv_path = RESEARCH_ROOT / "audit/results/unresolved_employee_ids.csv"
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required_columns = {
            "prGubun_raw", "prNo_raw", "training_rows", "official_role_candidates_json",
            "jockey_names_raw_json", "trainer_names_raw_json", "identity_mapping_status",
        }
        if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
            return {
                "status": "failed",
                "error": "unresolved_employee_ids.csv is missing required reason columns",
                "columns": reader.fieldnames,
            }
        csv_rows = list(reader)
    csv_by_key = {
        (row["prGubun_raw"], row["prNo_raw"]): row
        for row in csv_rows
    }
    unresolved_groups = target.execute(
        "SELECT rider_category_raw, employee_number_raw, training_rows "
        "FROM training_rider_identity_reviews "
        "WHERE rider_name IS NULL AND length(employee_number_raw)=6 "
        "AND employee_number_raw GLOB '[0-9][0-9][0-9][0-9][0-9][0-9]'"
    ).fetchall()
    missing = []
    reasonless = []
    count_mismatches = []
    invalid_reason_json = []
    for role, number, training_rows in unresolved_groups:
        row = csv_by_key.get((role, number))
        if row is None:
            missing.append({"role": role, "employee_number": number})
            continue
        if not row.get("identity_mapping_status", "").strip():
            reasonless.append({"role": role, "employee_number": number})
        try:
            for column in (
                "official_role_candidates_json", "jockey_names_raw_json", "trainer_names_raw_json"
            ):
                decoded = json.loads(row[column])
                if not isinstance(decoded, (dict, list)):
                    raise ValueError(f"{column} is not an object/list")
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            invalid_reason_json.append({
                "role": role, "employee_number": number, "error": str(exc)
            })
        try:
            csv_count = int(row["training_rows"])
        except (TypeError, ValueError):
            csv_count = None
        if csv_count != training_rows:
            count_mismatches.append({
                "role": role, "employee_number": number,
                "review_training_rows": training_rows, "csv_training_rows": csv_count,
            })
    duplicate_csv_keys = len(csv_rows) - len(csv_by_key)
    return {
        "path": str(csv_path.relative_to(PROJECT_ROOT)),
        "csv_review_rows": len(csv_rows),
        "unresolved_valid_employee_groups": len(unresolved_groups),
        "unresolved_groups_covered_by_csv": len(unresolved_groups) - len(missing),
        "missing_csv_reason_groups": missing,
        "groups_without_status_reason": reasonless,
        "invalid_reason_json_fields": invalid_reason_json,
        "training_row_count_mismatches": count_mismatches,
        "duplicate_csv_role_number_keys": duplicate_csv_keys,
        "status": (
            "ok"
            if not missing and not reasonless and not invalid_reason_json
            and not count_mismatches and duplicate_csv_keys == 0
            else "failed"
        ),
    }


def baseline_source_aggregates(connection: sqlite3.Connection) -> dict[str, Any]:
    source_rows = connection.execute(
        "SELECT COUNT(*) FROM daily_training_api_rows"
    ).fetchone()[0]
    analysis_rows = connection.execute(
        "SELECT COUNT(*) FROM daily_training_api_rows_analysis_2026"
    ).fetchone()[0]
    missing_rows = connection.execute(
        "SELECT COUNT(*) FROM daily_training_api_rows "
        "WHERE prNo_raw IN ('', '-')"
    ).fetchone()[0]
    null_role_or_number_rows = connection.execute(
        "SELECT COUNT(*) FROM daily_training_api_rows "
        "WHERE prGubun_raw IS NULL OR prNo_raw IS NULL"
    ).fetchone()[0]
    role_counts = {
        role: rows
        for role, rows in connection.execute(
            "SELECT prGubun_raw, COUNT(*) "
            "FROM daily_training_api_rows GROUP BY prGubun_raw ORDER BY prGubun_raw"
        )
    }
    role_missing_counts = {
        role: rows
        for role, rows in connection.execute(
            "SELECT prGubun_raw, COUNT(*) "
            "FROM daily_training_api_rows WHERE prNo_raw IN ('', '-') "
            "GROUP BY prGubun_raw ORDER BY prGubun_raw"
        )
    }
    return {
        "daily_training_api_rows": source_rows,
        "daily_training_api_rows_analysis_2026": analysis_rows,
        "rows_without_employee_number": missing_rows,
        "rows_with_null_role_or_number": null_role_or_number_rows,
        "rows_by_raw_role": role_counts,
        "missing_number_rows_by_raw_role": role_missing_counts,
        "status": (
            "ok"
            if source_rows == EXPECTED_SOURCE_ROWS
            and analysis_rows == EXPECTED_ANALYSIS_ROWS
            and missing_rows == EXPECTED_MISSING_EMPLOYEE_ROWS
            and null_role_or_number_rows == 0
            else "failed"
        ),
    }


def compare_existing_data(
    baseline: sqlite3.Connection, target: sqlite3.Connection
) -> dict[str, Any]:
    baseline_tables = table_names(baseline)
    target_table_set = set(table_names(target))
    results: dict[str, Any] = {}
    for table in baseline_tables:
        if table not in target_table_set:
            results[table] = {"status": "missing_from_target"}
            continue
        before = table_fingerprint(baseline, table)
        after = table_fingerprint(target, table)
        results[table] = {
            "status": "unchanged" if before == after else "changed",
            "baseline": before,
            "target": after,
        }
    return results


def compare_existing_schema(
    baseline: sqlite3.Connection, target: sqlite3.Connection
) -> dict[str, Any]:
    before = schema_objects(baseline)
    after = schema_objects(target)
    missing = []
    changed = []
    for key, sql in before.items():
        if key not in after:
            missing.append({"type": key[0], "name": key[1]})
        elif after[key] != sql:
            changed.append(
                {
                    "type": key[0],
                    "name": key[1],
                    "baseline_sql": sql,
                    "target_sql": after[key],
                }
            )
    added = [
        {"type": kind, "name": name}
        for kind, name in sorted(after.keys() - before.keys())
    ]
    return {
        "baseline_object_count": len(before),
        "target_object_count": len(after),
        "missing_existing_objects": missing,
        "changed_existing_objects": changed,
        "added_objects": added,
        "status": "unchanged" if not missing and not changed else "changed",
    }


def object_count(connection: sqlite3.Connection, object_name: str) -> int:
    return connection.execute(
        f"SELECT COUNT(*) FROM {quote_identifier(object_name)}"
    ).fetchone()[0]


def website_evidence_checks(connection: sqlite3.Connection) -> dict[str, Any]:
    evidence_path = RESEARCH_ROOT / "source_review/staff_website_identity_evidence.json"
    collection_path = RESEARCH_ROOT / "source_review/http_collection_manifest.json"
    ledger = json.loads(evidence_path.read_text(encoding="utf-8"))
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    pages = {row["horse_id"]: row for row in collection["pages"]}
    evidence_by_event: dict[int, dict[str, Any]] = {}
    parsed_pages: dict[Path, KRAProfileHTMLParser] = {}

    # unresolved_observations is a review index over personless rows that are
    # already present in evidence. The observation table must preserve one row
    # per event, including the raw "외" marker with NULL person_name.
    for item in ledger["evidence"] + ledger.get("unresolved_observations", []):
        event_id = int(item["training_row_id"])
        previous = evidence_by_event.get(event_id)
        if previous is not None:
            if previous != item:
                raise RuntimeError(f"Conflicting duplicate website ledger event {event_id}")
            continue
        evidence_by_event[event_id] = item

    for event_id, item in evidence_by_event.items():
        source_path = (PROJECT_ROOT / item["source_path"]).resolve(strict=True)
        if not source_path.is_relative_to((RESEARCH_ROOT / "source_review").resolve()):
            raise RuntimeError("Website evidence source path escapes source_review")
        page = pages.get(str(item["horse_id"]))
        if page is None:
            raise RuntimeError("Website evidence has no matching collection manifest page")
        if (
            page["source_path"] != item["source_path"]
            or page["sha256"] != item["source_sha256"]
            or page["url"] != item["url"]
            or page["http_status"] != 200
        ):
            raise RuntimeError("Website evidence metadata differs from page manifest")
        if sha256_file(source_path) != item["source_sha256"]:
            raise RuntimeError("Website HTML SHA-256 does not match evidence ledger")

        parsed_url = urlsplit(item["url"])
        query = parse_qs(parsed_url.query)
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname != "race.kra.co.kr"
            or parsed_url.path != "/racehorse/profileTrainState.do"
            or query.get("meet") != ["2"]
            or query.get("hrNo") != [str(item["horse_id"])]
        ):
            raise RuntimeError("Website evidence URL is not the official Jeju horse page")

        training = connection.execute(
            "SELECT prNo_raw, prGubun_raw, horse_id, training_date, "
            "start_time_local, end_time_local, duration_seconds "
            "FROM daily_training_api_rows WHERE daily_training_api_row_id=?",
            (event_id,),
        ).fetchone()
        if training is None:
            raise RuntimeError(f"Website evidence points to missing source row {event_id}")
        source_fields = {
            "employee_number": training[0],
            "category_raw": training[1],
            "horse_id": training[2],
            "date": training[3],
        }
        if any(item[key] != value for key, value in source_fields.items()):
            raise RuntimeError(f"Website evidence key differs from API row {event_id}")
        for item_key, training_value in (
            ("start_time_local", training[4]),
            ("end_time_local", training[5]),
        ):
            clock_text = training_value[11:16] if len(training_value) >= 16 else training_value
            if item[item_key] not in (clock_text, training_value):
                raise RuntimeError(f"Website time differs from API row {event_id}: {item_key}")
        if not re.fullmatch(r"[0-9]{6}", str(item["employee_number"])):
            raise RuntimeError(f"Website evidence has invalid employee number at row {event_id}")
        if not training[4] or not training[5] or training[6] is None:
            raise RuntimeError(f"Website evidence lacks an exact API18 time at row {event_id}")
        if item.get("api18_duration_seconds") is not None and item["api18_duration_seconds"] != training[6]:
            raise RuntimeError(f"Website evidence duration differs from API row {event_id}")

        if source_path not in parsed_pages:
            parsed_pages[source_path] = parse_kra_profile_page(source_path.read_bytes())
            if parsed_pages[source_path].inputs.get("hrNo") != str(item["horse_id"]):
                raise RuntimeError("Official HTML form horse ID differs from evidence")

        date_text = str(item["date"]).replace("-", "/")
        expected_start = training[4][11:16]
        expected_end = training[5][11:16]
        expected_duration = f"{training[6] // 60}분"
        matching = [
            row
            for row in parsed_pages[source_path].rows
            if len(row) == 7
            and row[1].startswith(date_text)
            and row[2] == item["website_name_raw"]
            and row[3] == expected_start
            and row[4] == expected_end
            and row[5] == expected_duration
        ]
        if len(matching) != 1:
            raise RuntimeError(
                f"Website event match is not unique for API row {event_id}: {len(matching)}"
            )
        if item.get("person_name") is None:
            if (
                item.get("website_name_raw") != "외"
                or not item.get("unresolved_reason")
                or "no person name" not in item["unresolved_reason"]
            ):
                raise RuntimeError(f"Personless website marker has no explicit unresolved reason at API row {event_id}")
        else:
            extracted_name = re.sub(r"\((?:관|조|생|트)\)$", "", item["website_name_raw"]).strip()
            if extracted_name != item["person_name"] or extracted_name in ("", "-", "관", "조", "생", "경주일", "외"):
                raise RuntimeError(f"Website rider label extraction differs at API row {event_id}")

    table_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='training_rider_website_observations'"
    ).fetchone()
    if not table_exists:
        return {
            "ledger_evidence_rows": len(ledger["evidence"]),
            "status": "failed",
            "error": "training_rider_website_observations table is missing",
        }
    stored_rows = connection.execute(
        "SELECT daily_training_api_row_id, employee_number_raw, rider_category_raw, "
        "person_name, rider_name_raw, source_path, source_sha256, source_url "
        "FROM training_rider_website_observations"
    ).fetchall()
    stored_by_event = {row[0]: row[1:] for row in stored_rows}
    expected_by_event: dict[int, tuple[Any, ...]] = {}
    for event_id, item in evidence_by_event.items():
        expected_by_event[event_id] = (
            item["employee_number"],
            item["category_raw"],
            item["person_name"],
            item["website_name_raw"],
            item["source_path"],
            item["source_sha256"],
            item["url"],
        )
    if stored_by_event != expected_by_event:
        raise RuntimeError("Website evidence ledger and SQLite observation rows differ")

    view_results = {}
    for view_name in ("daily_training_riders", "daily_training_riders_analysis_2026"):
        view_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='view' AND name=?", (view_name,)
        ).fetchone()
        if not view_exists:
            view_results[view_name] = {"status": "missing"}
            continue
        quoted_view = quote_identifier(view_name)
        scope = "WHERE d.training_date <= '2026-09-19'" if view_name.endswith("_2026") else ""
        total, marked, flag_mismatches, content_mismatches = connection.execute(
            f"SELECT COUNT(*), "
            f"SUM(v.rider_name_same_event_website_verified=1), "
            f"SUM(v.rider_name_same_event_website_verified != "
            f"CASE WHEN w.person_name IS NOT NULL THEN 1 ELSE 0 END), "
            f"SUM(v.rider_name_on_website IS NOT w.person_name OR "
            f"v.rider_label_on_website_raw IS NOT "
            f"CASE WHEN w.daily_training_api_row_id IS NULL THEN NULL ELSE w.rider_name_raw END) "
            f"FROM daily_training_api_rows d "
            f"JOIN {quoted_view} v USING (daily_training_api_row_id) "
            "LEFT JOIN training_rider_website_observations w "
            "USING (daily_training_api_row_id) "
            f"{scope}"
        ).fetchone()
        view_results[view_name] = {
            "rows": total,
            "website_verified_rows": marked or 0,
            "expected_website_verified_rows": sum(
                1 for event_id, evidence in evidence_by_event.items()
                if evidence.get("person_name") is not None
                if view_name != "daily_training_riders_analysis_2026"
                or connection.execute(
                    "SELECT 1 FROM daily_training_api_rows "
                    "WHERE daily_training_api_row_id=? AND training_date <= '2026-09-19'",
                    (event_id,),
                ).fetchone()
            ),
            "event_flag_mismatches": flag_mismatches or 0,
            "website_name_value_mismatches": content_mismatches or 0,
            "status": (
                "ok"
                if (flag_mismatches or 0) == 0 and (content_mismatches or 0) == 0
                else "failed"
            ),
        }
        personless_mismatches = connection.execute(
            f"SELECT COUNT(*) FROM {quoted_view} v "
            "JOIN training_rider_website_observations w USING (daily_training_api_row_id) "
            "WHERE w.person_name IS NULL AND w.rider_name_raw='외' "
            "AND (v.rider_name IS NOT NULL OR v.rider_name_on_website IS NOT NULL "
            "OR v.rider_label_on_website_raw IS NOT '외' "
            "OR v.rider_name_same_event_website_verified != 0)"
        ).fetchone()[0]
        view_results[view_name]["personless_marker_mismatches"] = personless_mismatches
        if personless_mismatches:
            view_results[view_name]["status"] = "failed"
    return {
        "ledger_pages": len(pages),
        "ledger_evidence_rows": len(ledger["evidence"]),
        "ledger_unresolved_index_rows": len(ledger.get("unresolved_observations", [])),
        "unique_api18_event_rows": len(evidence_by_event),
        "personless_raw_marker_rows": sum(
            item.get("person_name") is None for item in evidence_by_event.values()
        ),
        "event_rows_with_person_name": sum(
            item.get("person_name") is not None for item in evidence_by_event.values()
        ),
        "stored_observation_rows": len(stored_rows),
        "raw_html_pages_rechecked": len(parsed_pages),
        "personless_observation_reasons": sorted({
            item.get("unresolved_reason") for item in evidence_by_event.values()
            if item.get("person_name") is None
        }),
        "views": view_results,
        "status": "ok" if all(row.get("status") == "ok" for row in view_results.values()) else "failed",
    }


def new_object_checks(connection: sqlite3.Connection) -> dict[str, Any]:
    objects = schema_objects(connection)
    by_name = {name: kind for (kind, name) in objects}
    checks: dict[str, Any] = {}
    for name, expected_type in EXPECTED_NEW_OBJECTS.items():
        actual_type = by_name.get(name)
        checks[name] = {
            "expected_type": expected_type,
            "actual_type": actual_type,
            "status": "ok" if actual_type == expected_type else "failed",
        }

    for name, expected_count in (
        ("daily_training_riders", EXPECTED_SOURCE_ROWS),
        ("daily_training_riders_analysis_2026", EXPECTED_ANALYSIS_ROWS),
    ):
        if by_name.get(name) != "view":
            continue
        count = object_count(connection, name)
        checks[name]["row_count"] = count
        checks[name]["expected_row_count"] = expected_count
        checks[name]["status"] = "ok" if count == expected_count else "failed"

    if by_name.get("training_rider_identity_reviews") == "table":
        review_count = object_count(connection, "training_rider_identity_reviews")
        source_group_count = connection.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM daily_training_api_rows "
            "GROUP BY prGubun_raw, prNo_raw)"
        ).fetchone()[0]
        invalid_review_keys, named_missing_numbers = connection.execute(
            "SELECT "
            "SUM(rider_category_raw IS NULL OR employee_number_raw IS NULL), "
            "SUM(employee_number_raw IN ('', '-') AND rider_name IS NOT NULL) "
            "FROM training_rider_identity_reviews"
        ).fetchone()
        checks["training_rider_identity_reviews_integrity"] = {
            "review_rows": review_count,
            "source_role_number_groups": source_group_count,
            "invalid_review_keys": invalid_review_keys or 0,
            "missing_number_rows_with_name": named_missing_numbers or 0,
            "status": (
                "ok"
                if review_count == source_group_count
                and (invalid_review_keys or 0) == 0
                and (named_missing_numbers or 0) == 0
                else "failed"
            ),
        }

    # The rider views must retain every raw source item exactly once and keep
    # its role, employee number (including leading zeroes), and trainer name.
    for view_name in ("daily_training_riders", "daily_training_riders_analysis_2026"):
        if by_name.get(view_name) != "view":
            continue
        quoted_view = quote_identifier(view_name)
        source_scope = (
            "WHERE d.training_date <= '2026-09-19'"
            if view_name == "daily_training_riders_analysis_2026"
            else ""
        )
        view_count, distinct_ids = connection.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT daily_training_api_row_id) "
            f"FROM {quoted_view}"
        ).fetchone()
        missing_source_rows, changed_raw_rows = connection.execute(
            f"SELECT "
            f"SUM(v.daily_training_api_row_id IS NULL), "
            f"SUM(v.daily_training_api_row_id IS NOT NULL AND ("
            f"d.prGubun_raw IS NOT v.prGubun_raw OR "
            f"d.prNo_raw IS NOT v.prNo_raw OR "
            f"d.trName_raw IS NOT v.trName_raw OR "
            f"d.raw_row_json IS NOT v.raw_row_json)) "
            f"FROM daily_training_api_rows d "
            f"LEFT JOIN {quoted_view} v "
            f"USING (daily_training_api_row_id) {source_scope}"
        ).fetchone()
        changed_employee_numbers, changed_reference_kinds = connection.execute(
            f"SELECT "
            f"SUM(v.rider_employee_number IS NOT CASE "
            f"WHEN d.prNo_raw NOT IN ('', '-') THEN d.prNo_raw END), "
            f"SUM(v.rider_reference_person_kind IS NOT r.reference_person_kind) "
            f"FROM daily_training_api_rows d "
            f"JOIN {quoted_view} v USING (daily_training_api_row_id) "
            "LEFT JOIN training_rider_identity_reviews r "
            "ON r.rider_category_raw=d.prGubun_raw AND r.employee_number_raw=d.prNo_raw "
            f"{source_scope}"
        ).fetchone()
        changed_rider_names = connection.execute(
            f"SELECT COUNT(*) FROM daily_training_api_rows d "
            f"JOIN {quoted_view} v USING (daily_training_api_row_id) "
            "LEFT JOIN training_rider_identity_reviews r "
            "ON r.rider_category_raw=d.prGubun_raw AND r.employee_number_raw=d.prNo_raw "
            "LEFT JOIN api_records a ON a.api_record_id=r.witness_api_record_id "
            "WHERE v.rider_name IS NOT CASE "
            "WHEN r.employee_number_raw IS NULL THEN NULL "
            "WHEN r.witness_api_record_id IS NOT NULL "
            "AND a.payload_sha256 IS NOT r.witness_payload_sha256 THEN NULL "
            "ELSE r.rider_name END"
        ).fetchone()[0]
        missing_number_named_rows = connection.execute(
            f"SELECT COUNT(*) FROM {quoted_view} "
            "WHERE prNo_raw IN ('', '-') AND rider_name IS NOT NULL"
        ).fetchone()[0]
        key = f"{view_name}_raw_preservation"
        checks[key] = {
            "row_count": view_count,
            "distinct_source_row_ids": distinct_ids,
            "duplicate_source_row_ids": view_count - distinct_ids,
            "missing_source_rows": missing_source_rows or 0,
            "changed_raw_role_number_trainer_or_json_rows": changed_raw_rows or 0,
            "changed_leading_zero_preserving_employee_numbers": changed_employee_numbers or 0,
            "changed_reference_person_kinds": changed_reference_kinds or 0,
            "view_rider_names_not_equal_to_exact_role_number_review": changed_rider_names,
            "missing_number_rows_with_name": missing_number_named_rows,
            "status": (
                "ok"
                if view_count == distinct_ids
                and (missing_source_rows or 0) == 0
                and (changed_raw_rows or 0) == 0
                and (changed_employee_numbers or 0) == 0
                and (changed_reference_kinds or 0) == 0
                and changed_rider_names == 0
                and missing_number_named_rows == 0
                else "failed"
            ),
        }
    return checks


def verify(baseline_path: Path, target_path: Path) -> dict[str, Any]:
    baseline = readonly_connection(baseline_path)
    target = readonly_connection(target_path)
    try:
        schema = compare_existing_schema(baseline, target)
        data = compare_existing_data(baseline, target)
        baseline_aggregates = baseline_source_aggregates(baseline)
        expected = new_object_checks(target)
        website = website_evidence_checks(target)
        identity_references = review_reference_checks(baseline, target)
        unresolved_reasons = unresolved_reason_artifact_checks(target)
    finally:
        baseline.close()
        target.close()
    jockey_roster = official_jockey_roster_check()

    changed_tables = [
        table for table, result in data.items() if result["status"] != "unchanged"
    ]
    failed_new_objects = [
        name for name, result in expected.items() if result["status"] != "ok"
    ]
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline": str(baseline_path.resolve()),
        "target": str(target_path.resolve()),
        "sqlite_read_only": True,
        "existing_schema": schema,
        "existing_tables": data,
        "baseline_source_aggregates": baseline_aggregates,
        "official_api307_meet_2_roster": jockey_roster,
        "new_object_checks": expected,
        "official_website_event_evidence": website,
        "identity_reference_checks": identity_references,
        "unresolved_reason_artifact_checks": unresolved_reasons,
        "status": (
            "ok"
            if schema["status"] == "unchanged"
            and baseline_aggregates["status"] == "ok"
            and jockey_roster["status"] == "ok"
            and not changed_tables
            and not failed_new_objects
            and website["status"] == "ok"
            and identity_references["status"] == "ok"
            and unresolved_reasons["status"] == "ok"
            else "failed"
        ),
        "failures": {
            "changed_or_missing_existing_tables": changed_tables,
            "changed_or_missing_existing_schema_objects": (
                schema["missing_existing_objects"]
                + schema["changed_existing_objects"]
            ),
            "failed_new_object_checks": failed_new_objects,
            "official_website_event_evidence": (
                website if website["status"] != "ok" else None
            ),
            "identity_reference_checks": (
                identity_references if identity_references["status"] != "ok" else None
            ),
            "unresolved_reason_artifact_checks": (
                unresolved_reasons if unresolved_reasons["status"] != "ok" else None
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--report-out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    report_path = args.report_out.resolve()
    if not report_path.is_relative_to(VERIFICATION_ROOT.resolve()):
        parser.error("--report-out must stay inside the verification folder")

    try:
        report = verify(args.baseline, args.target)
    except (OSError, sqlite3.Error, RuntimeError, TypeError) as exc:
        report = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "baseline": str(args.baseline),
            "target": str(args.target),
            "sqlite_read_only": True,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    compact = {
        "status": report["status"],
        "report": str(report_path),
        "existing_tables_checked": len(report["existing_tables"]),
        "new_object_checks": report["new_object_checks"],
        "identity_reference_checks": report["identity_reference_checks"],
        "unresolved_reason_artifact_checks": report["unresolved_reason_artifact_checks"],
        "failures": report["failures"],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
