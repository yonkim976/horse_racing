#!/usr/bin/env python3
"""Apply the approved fixed-2026 Jeju analysis views to the local SQLite DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
MIGRATION = ROOT / "jeju/data/schema/migrations/20261001_add_horse_analysis_2026.sql"
MAIN_SCHEMA = ROOT / "jeju/data/schema/jeju_native_core.sql"
OUT = ROOT / "jeju/research/20261001_horse_analysis_2026"
BACKUP = OUT / "backups/jeju_native_core_before_horse_analysis_20261001.sqlite3"
MANIFEST = OUT / "application_manifest.json"
VIEWS = ("horse_analysis_2026", "jeju_race_analysis_2026", "jeju_trial_analysis_2026")
ISSUE_TYPE = "current_profile_vs_historical_race_sex_conflict"
ISSUE_SUMMARY = (
    "Preserve the API4 historical race sex (수) alongside the current API42 profile "
    "and pre-race API20 trial sex (암); do not harmonize the event record."
)
ISSUE_POLICY = "Preserve event and current-profile observations as source-specific values; do not correct either source."
POLICIES = {
    "analysis_horse_name_policy": (
        "Use the latest API42 horse name by horse_id in 2026 analysis views; preserve each historical event name "
        "in historical_horse_name_raw and use it only when no profile name is available."
    ),
    "analysis_age_policy": (
        "The fixed reference year is 2026. age and age_2026 equal 2026 minus a validated four-digit profile "
        "birth year in 1..2026; invalid or missing years yield NULL. Preserve event ages in age_at_race_raw "
        "and age_at_trial_raw."
    ),
    "analysis_sex_policy": (
        "Preserve API4 race sex and API20 trial sex in source-specific raw columns; expose API42 current-profile "
        "sex separately. Never overwrite event-source sex."
    ),
    "analysis_profile_selection_policy": (
        "Select the latest API42 profile observation by observed_at_utc descending, then api_record_id descending; "
        "apply current profile name and fixed 2026 age only in the named analysis views."
    ),
}
EXPECTED_COUNTS = {
    "horse_profile_latest": 4617,
    "jeju_race_candidate_passing_with_corner_rank": 92513,
    "api_explicit_jeju_trial_rows": 15738,
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(path: Path, *, exists: bool) -> Path:
    resolved = path.resolve(strict=exists)
    try:
        resolved.relative_to(ROOT.resolve(strict=True))
    except ValueError as exc:
        raise RuntimeError(f"Path is outside the repository: {path}") from exc
    return resolved


def readonly(path: Path) -> sqlite3.Connection:
    resolved = safe_path(path, exists=True)
    uri = f"file:{quote(resolved.as_posix(), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def split_sql(sql: str) -> list[str]:
    statements: list[str] = []
    pending: list[str] = []
    for line in sql.splitlines(keepends=True):
        pending.append(line)
        candidate = "".join(pending)
        if sqlite3.complete_statement(candidate):
            if candidate.strip():
                statements.append(candidate.strip())
            pending.clear()
    if "".join(pending).strip():
        raise RuntimeError("Migration contains an incomplete SQL statement")
    return statements


def normalize_sql(sql: str) -> str:
    sql = re.sub(r"\bIF\s+NOT\s+EXISTS\b", "", sql, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", sql).strip().rstrip(";").casefold()


def view_sql(sql: str) -> dict[str, str]:
    pattern = re.compile(
        r"CREATE\s+VIEW\s+IF\s+NOT\s+EXISTS\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\s+.*?;",
        re.IGNORECASE | re.DOTALL,
    )
    found = {m.group(1): m.group(0) for m in pattern.finditer(sql)}
    if set(found) != set(VIEWS):
        raise RuntimeError(f"Migration must define exactly {VIEWS}; found {tuple(found)}")
    return found


def check_files() -> str:
    migration = safe_path(MIGRATION, exists=True).read_text(encoding="utf-8").rstrip()
    main_schema = safe_path(MAIN_SCHEMA, exists=True).read_text(encoding="utf-8").rstrip()
    if not main_schema.endswith(migration):
        raise RuntimeError("Main schema does not end with the identical migration SQL")
    split_sql(migration)
    view_sql(migration)
    return migration


def issue_evidence(conn: sqlite3.Connection) -> tuple[dict, dict]:
    race_rows = conn.execute(
        """SELECT rr.api_record_id, rr.race_date, rr.race_number, rr.horse_number,
                  a.payload_json, a.payload_sha256, sa.raw_relative_path
           FROM race_result_rows rr
           JOIN api_records a ON a.api_record_id=rr.api_record_id
           JOIN source_artifacts sa ON sa.source_artifact_id=a.source_artifact_id
           WHERE rr.race_date=? AND rr.race_number=? AND rr.horse_number=? AND rr.horse_id=?""",
        ("2002-12-14", 3, 2, "3005897"),
    ).fetchall()
    profile_rows = conn.execute(
        """SELECT api_record_id, sex_raw, observed_at_utc, payload_sha256,
                  source_response_sha256, raw_relative_path
           FROM horse_profile_latest WHERE horse_id=?""", ("3005897",)
    ).fetchall()
    trial_rows = conn.execute(
        """SELECT t.api_record_id, t.trial_date, a.payload_json, a.payload_sha256,
                  sa.raw_relative_path
           FROM api_explicit_jeju_trial_rows t
           JOIN api_records a ON a.api_record_id=t.api_record_id
           JOIN source_artifacts sa ON sa.source_artifact_id=a.source_artifact_id
           WHERE t.horse_id=? AND t.trial_date=?""", ("3005897", "2002-11-22")
    ).fetchall()
    if len(race_rows) != 1 or len(profile_rows) != 1 or len(trial_rows) != 1:
        raise RuntimeError("Expected unique API4/API42/API20 rows for horse 3005897")
    race, profile, trial = map(dict, (race_rows[0], profile_rows[0], trial_rows[0]))
    race_payload = json.loads(race.pop("payload_json"))
    trial_payload = json.loads(trial.pop("payload_json"))
    race.update(sex_raw=race_payload.get("sex"), age_raw=race_payload.get("age"))
    trial["sex_raw"] = trial_payload.get("sex")
    if (race["api_record_id"], race["sex_raw"], race["age_raw"], profile["sex_raw"], trial["sex_raw"]) != (
        326, "수", 8, "암", "암"
    ):
        raise RuntimeError("Horse 3005897 no longer matches the approved source evidence")
    api_value = {key: race[key] for key in ("race_date", "race_number", "horse_number", "sex_raw", "age_raw")}
    detail = {
        "historical_api4_race": {
            key: race[key] for key in (
                "api_record_id", "race_date", "race_number", "horse_number", "sex_raw", "age_raw",
                "payload_sha256", "raw_relative_path"
            )
        },
        "current_api42_profile": profile,
        "pre_race_api20_trial": trial,
        "user_decision": "retain_existing_record_without_correction",
        "decision_date": "2026-10-01",
        "cause_status": "unconfirmed",
        "policy": ISSUE_POLICY,
    }
    return api_value, detail


def state(conn: sqlite3.Connection, migration: str) -> tuple[bool, dict, dict]:
    expected = view_sql(migration)
    rows = conn.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='view' AND name IN (?,?,?)", VIEWS
    ).fetchall()
    existing = {row["name"]: row["sql"] or "" for row in rows}
    for name, sql in existing.items():
        if normalize_sql(sql) != normalize_sql(expected[name]):
            raise RuntimeError(f"Existing view {name} does not match the migration")
    keys = tuple(POLICIES)
    marks = ",".join("?" for _ in keys)
    metadata = {
        row["key"]: row["value"]
        for row in conn.execute(f"SELECT key,value FROM schema_metadata WHERE key IN ({marks})", keys)
    }
    for key, value in metadata.items():
        if value != POLICIES[key]:
            raise RuntimeError(f"Existing policy metadata {key} conflicts with the migration")

    counts = {
        name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        for name in EXPECTED_COUNTS
    }
    if counts != EXPECTED_COUNTS:
        raise RuntimeError(f"Source view counts differ from the approved baseline: {counts}")
    api_value, detail = issue_evidence(conn)
    issues = conn.execute(
        "SELECT * FROM provenance_issues WHERE issue_type=? AND entity_key=?",
        (ISSUE_TYPE, "3005897"),
    ).fetchall()
    if len(issues) > 1:
        raise RuntimeError("Duplicate 3005897 source-conflict provenance rows already exist")
    issue_exists = bool(issues)
    if issue_exists:
        issue = issues[0]
        if (
            issue["severity"] != "medium" or issue["status"] != "open"
            or issue["entity_type"] != "horse" or issue["api_record_id"] != 326
            or issue["supplemental_artifact_id"] is not None
            or issue["summary"] != ISSUE_SUMMARY
            or json.loads(issue["api_value_json"] or "null") != api_value
            or json.loads(issue["detail_json"] or "null") != detail
        ):
            raise RuntimeError("Existing 3005897 provenance row conflicts with approved source evidence")
    complete = set(existing) == set(VIEWS) and set(metadata) == set(POLICIES) and issue_exists
    absent = not existing and not metadata and not issue_exists
    if not complete and not absent:
        raise RuntimeError("Migration is partially present; refusing to overwrite or repair mixed state")
    return complete, {"source_counts": counts}, {"api_value": api_value, "detail": detail}


def make_backup() -> dict:
    safe_path(DB, exists=True)
    parent = safe_path(BACKUP.parent, exists=False)
    parent.mkdir(parents=True, exist_ok=True)
    safe_path(parent, exists=True)
    if BACKUP.exists() or BACKUP.is_symlink():
        raise RuntimeError(f"Refusing to overwrite backup {BACKUP}")
    fd = os.open(BACKUP, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    source = readonly(DB)
    target = sqlite3.connect(BACKUP, timeout=20)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    check = readonly(BACKUP)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = check.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        check.close()
    if integrity != "ok" or foreign_keys:
        raise RuntimeError("Backup integrity check failed")
    return {
        "path": BACKUP.relative_to(ROOT).as_posix(),
        "bytes": BACKUP.stat().st_size,
        "sha256": sha256(BACKUP),
        "integrity_check": integrity,
        "foreign_key_violations": 0,
        "created_at_utc": utc_now(),
    }


def write_manifest(payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    safe_path(OUT, exists=True)
    if MANIFEST.is_symlink():
        raise RuntimeError("Refusing to replace a symlinked application manifest")
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=OUT, prefix=".manifest-", suffix=".tmp", delete=False
    ) as stream:
        temp_path = Path(stream.name)
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    safe_path(temp_path, exists=True)
    os.replace(temp_path, MANIFEST)


def read_manifest() -> dict | None:
    if MANIFEST.is_symlink():
        raise RuntimeError("Refusing to read a symlinked application manifest")
    if not MANIFEST.exists():
        return None
    try:
        value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Application manifest is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Application manifest must be a JSON object")
    return value


def apply_sql(conn: sqlite3.Connection, migration: str, evidence: dict) -> dict:
    conn.execute("BEGIN IMMEDIATE")
    try:
        already_complete, _, fresh_evidence = state(conn, migration)
        if already_complete or fresh_evidence != evidence:
            raise RuntimeError("Database state changed after preflight; refusing to apply")
        for statement in split_sql(migration):
            conn.execute(statement)
        verified = basic_verify(conn, fresh_evidence)
        conn.commit()
        return verified
    except Exception:
        conn.rollback()
        raise


def basic_verify(conn: sqlite3.Connection, evidence: dict) -> dict:
    counts = {name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in VIEWS}
    if counts != {
        "horse_analysis_2026": 4617,
        "jeju_race_analysis_2026": 92513,
        "jeju_trial_analysis_2026": 15738,
    }:
        raise RuntimeError(f"Analysis views did not preserve expected input rows: {counts}")
    event = conn.execute(
        """SELECT horse_id, horse_name, age, age_2026, age_reference_year,
                  age_at_race_raw, sex, sex_at_race_raw, sex_current_profile
           FROM jeju_race_analysis_2026 WHERE api_record_id=326"""
    ).fetchone()
    if not event or tuple(event) != ("3005897", "토종등극", 32, 32, 2026, 8, "수", "수", "암"):
        raise RuntimeError("The user-directed 3005897 analysis values were not preserved")
    trial_id = evidence["detail"]["pre_race_api20_trial"]["api_record_id"]
    trial = conn.execute(
        """SELECT age, age_2026, age_reference_year, age_at_trial_raw,
                  sex, sex_at_trial_raw, sex_current_profile
           FROM jeju_trial_analysis_2026 WHERE api_record_id=?""", (trial_id,)
    ).fetchone()
    if not trial or tuple(trial) != (32, 32, 2026, 8, "암", "암", "암"):
        raise RuntimeError("The user-directed 3005897 trial values were not preserved")
    issue = conn.execute(
        """SELECT count(*) FROM provenance_issues
           WHERE issue_type=? AND entity_key='3005897' AND api_record_id=326 AND status='open'""",
        (ISSUE_TYPE,),
    ).fetchone()[0]
    if issue != 1:
        raise RuntimeError("Expected one open source-conflict provenance row")
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    if integrity != "ok" or foreign_keys:
        raise RuntimeError("SQLite integrity or foreign-key check failed")
    return {"view_counts": counts, "integrity_check": integrity, "foreign_key_violations": len(foreign_keys)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Back up and apply the migration.")
    args = parser.parse_args()
    if not args.apply:
        parser.error("No changes made. Use --apply after explicit authorization.")

    migration = check_files()
    safe_path(DB, exists=True)
    OUT.mkdir(parents=True, exist_ok=True)
    safe_path(OUT, exists=True)
    prior = read_manifest()

    conn = readonly(DB)
    try:
        complete, base_result, evidence = state(conn, migration)
    finally:
        conn.close()

    migration_hash = hashlib.sha256(migration.encode("utf-8")).hexdigest()
    if complete:
        if prior is None or prior.get("migration_sha256") != migration_hash:
            raise RuntimeError("Analysis views already exist without a matching application manifest")
        backup_info = prior.get("backup")
        if not isinstance(backup_info, dict):
            raise RuntimeError("Application manifest lacks the original SQLite backup")
        backup_path = safe_path(ROOT / backup_info["path"], exists=True)
        if sha256(backup_path) != backup_info.get("sha256"):
            raise RuntimeError("Preserved backup SHA-256 does not match the application manifest")
        conn = readonly(DB)
        try:
            verified = basic_verify(conn, evidence)
        finally:
            conn.close()
        run = {"mode": "idempotency_verified", "checked_at_utc": utc_now(), "database_changed": False}
        payload = prior
        payload["status"] = "idempotency_verified"
        payload["last_check"] = run
        payload["verification"] = verified
        payload.setdefault("runs", []).append(run)
    else:
        if prior is not None and prior.get("status") not in {"prepared_not_applied"}:
            raise RuntimeError("An application manifest exists while the database migration is absent")
        backup_info = make_backup()
        conn = sqlite3.connect(DB, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=15000")
            verified = apply_sql(conn, migration, evidence)
        finally:
            conn.close()
        run = {"mode": "applied", "checked_at_utc": utc_now(), "database_changed": True}
        payload = {
            "status": "applied",
            "database_path": DB.relative_to(ROOT).as_posix(),
            "migration_path": MIGRATION.relative_to(ROOT).as_posix(),
            "migration_sha256": migration_hash,
            "applied_at_utc": run["checked_at_utc"],
            "backup": backup_info,
            "source_counts_before_apply": base_result["source_counts"],
            "verification": verified,
            "runs": [],
        }
        payload["runs"].append(run)
    write_manifest(payload)
    print(json.dumps({"status": payload["status"], "backup": backup_info, "verification": payload["verification"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
