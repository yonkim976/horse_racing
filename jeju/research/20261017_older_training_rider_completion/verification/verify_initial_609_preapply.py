#!/usr/bin/env python3
"""Lightweight read-only gate for the independently verified initial 609 rows."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
PROJECT = TASK.parents[2]
SOURCE = PROJECT / "jeju/research/20261017_older_training_rider_sources"
DB_DEFAULT = PROJECT / "jeju/data/jeju_native_core.sqlite3"
SAMPLE_DEFAULT = SOURCE / "sample_verification.json"
MATCHES_DEFAULT = SOURCE / "daily_sample_matches.json"
ASSIGNMENT_FIELDS = (
    "daily_training_api_row_id", "daily_training_api_artifact_id", "prGubun_raw", "prNo_raw", "horse_id",
    "training_date", "start_time_local", "end_time_local", "duration_seconds",
    "rider_type", "type_status", "website_type", "website_label_raw",
    "website_jockey_name", "website_source_path", "website_sha256",
)
SOURCE_FIELDS = (
    "daily_training_api_artifact_id", "prGubun_raw", "prNo_raw", "horse_id",
    "training_date", "start_time_local", "end_time_local", "duration_seconds",
)
CHANGED_FIELDS = (
    "rider_type", "type_status", "website_type", "website_label_raw",
    "website_jockey_name", "website_source_path", "website_sha256",
)


class GateError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise GateError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_task_file(path: Path, *, must_exist: bool) -> Path:
    resolved = path.resolve(strict=must_exist)
    require(resolved.is_relative_to(TASK.resolve()), f"Path outside task folder: {path}")
    return resolved


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    result = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise GateError(f"Invalid plan JSONL at line {line_number}: {exc}") from exc
            require(isinstance(row, dict), f"Plan line {line_number} is not an object")
            result.append(row)
    return result


def connect_readonly(path: Path) -> sqlite3.Connection:
    resolved = path.resolve(strict=True)
    connection = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA foreign_keys=ON")
    require(connection.execute("PRAGMA query_only").fetchone()[0] == 1,
            "SQLite query_only did not enable")
    require(connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1,
            "SQLite foreign_keys did not enable")
    return connection


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_DEFAULT)
    parser.add_argument("--sample", type=Path, default=SAMPLE_DEFAULT)
    parser.add_argument("--matches", type=Path, default=MATCHES_DEFAULT)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--output", type=Path,
                        default=HERE / "initial_609_preapply_verification.json")
    args = parser.parse_args()

    db_path = args.db.resolve(strict=True)
    sample_path = args.sample.resolve(strict=True)
    matches_path = args.matches.resolve(strict=True)
    plan_path = safe_task_file(args.plan, must_exist=True)
    output_path = safe_task_file(args.output, must_exist=False)
    require(not output_path.exists(), f"Refusing to overwrite report: {output_path}")
    require(sample_path == SAMPLE_DEFAULT.resolve(strict=True),
            "Sample evidence must be the preserved project verification JSON")
    require(matches_path == MATCHES_DEFAULT.resolve(strict=True),
            "Candidate evidence must be the preserved project daily-sample match JSON")
    require(re.fullmatch(r"[0-9a-f]{64}", args.expected_plan_sha256) is not None,
            "Expected plan SHA-256 must be 64 lowercase hex characters")
    plan_sha = sha256_file(plan_path)
    require(plan_sha == args.expected_plan_sha256,
            f"Plan SHA mismatch: expected {args.expected_plan_sha256}, found {plan_sha}")

    sample = read_json(sample_path)
    require(sample.get("verification_status") == "passed" and
            sample.get("database_modified") is False and
            sample.get("database_access", {}).get("query_only") is True and
            sample.get("database_access", {}).get("mode") == "SQLite URI mode=ro" and
            sample.get("parser") == "html.parser.HTMLParser (no BeautifulSoup)",
            "Preserved independent sample verification is not a read-only PASS")
    require(sample.get("source_pages_verified") == 6 and
            sample.get("exact_api_event_matches_verified") == 805 and
            sample.get("classifiable_as_jeju_track_training") == 609 and
            sample.get("ambiguous_exact_keys_excluded") == 1,
            "Sample verification counts differ from the recorded 6-page result")
    all_verified = sample.get("verified_event_rows")
    require(isinstance(all_verified, list) and len(all_verified) == 805,
            "Expected 805 independently verified exact sample events")
    candidates_from_parse = [row for row in all_verified
                             if row.get("candidate_type") == "주로조교"]
    require(len(candidates_from_parse) == 609,
            "Expected 609 explicit `관` rows among the 805 independently verified exact events")
    matches = read_json(matches_path)
    candidates = matches.get("evidence")
    require(matches.get("database_modified") is False and
            matches.get("total_new_classifiable_samples") == 609 and
            isinstance(candidates, list) and len(candidates) == 609,
            "Daily sample match evidence does not record exactly 609 candidates")
    parsed_by_id = {row["row_id"]: row for row in candidates_from_parse}
    require(len(parsed_by_id) == len(candidates_from_parse),
            "Duplicate row IDs in independent sample parser output")
    for candidate in candidates:
        parsed = parsed_by_id.get(candidate.get("row_id"))
        require(parsed is not None, f"Candidate absent from independent sample parse: {candidate.get('row_id')}")
        for field in ("horse_id", "date", "start", "end", "duration_seconds", "label",
                      "source_path", "source_sha256", "candidate_type"):
            require(candidate.get(field) == parsed.get(field),
                    f"Sample candidate/parser mismatch ({field}): row {candidate.get('row_id')}")

    source_pages = {}
    for sample_date, details in sample["samples"].items():
        source_path = Path(details["source_path"])
        page_path = (PROJECT / source_path).resolve(strict=True)
        require(page_path.is_relative_to(SOURCE.resolve()),
                f"Sample HTML outside official-source folder: {source_path}")
        manifest_path = page_path.parent / "manifest.json"
        manifest = read_json(manifest_path)
        require(isinstance(manifest, list) and len(manifest) == 1,
                f"Expected one preserved source manifest: {manifest_path}")
        entry = manifest[0]
        require(entry.get("http_status") == 200 and
                entry.get("url") == "https://race.kra.co.kr/trainer/dailyAllTrainDetail.do" and
                entry.get("method") == "POST" and
                entry.get("form_fields", {}).get("meet") == "2" and
                entry.get("form_fields", {}).get("trDate", "").replace("/", "-") == sample_date and
                entry.get("source_path") == str(source_path) and
                entry.get("sha256") == details.get("source_sha256"),
                f"Official source manifest differs from sample evidence: {manifest_path}")
        source_pages[sample_date] = {
            "source_path": str(source_path), "sha256": details["source_sha256"],
        }

    plan = read_jsonl(plan_path)
    plan_summary_path = plan_path.with_suffix(".summary.json")
    require(plan_summary_path.is_file(), f"Plan summary missing: {plan_summary_path}")
    plan_summary = read_json(plan_summary_path)
    require(plan_summary.get("plan_sha256") == plan_sha and
            plan_summary.get("candidate_rows") == 609 and
            plan_summary.get("new_type_counts") == {"주로조교": 609} and
            plan_summary.get("source_pages") == 5 and
            plan_summary.get("input_sha256") == sha256_file(matches_path) and
            plan_summary.get("input") == str(matches_path.relative_to(PROJECT)),
            "Initial plan summary does not match the pinned 609-row evidence input")
    plan_by_id = {}
    for row in plan:
        row_id = row.get("daily_training_api_row_id", row.get("row_id"))
        require(isinstance(row_id, int) and row_id > 0, "Plan row lacks a positive API row ID")
        require(row_id not in plan_by_id, f"Duplicate plan row ID: {row_id}")
        plan_by_id[row_id] = row
    evidence_by_id = {}
    for candidate in candidates:
        row_id = candidate.get("row_id")
        require(isinstance(row_id, int) and row_id > 0, "Sample evidence row lacks row_id")
        require(row_id not in evidence_by_id, f"Duplicate sample evidence row ID: {row_id}")
        require(candidate.get("candidate_type") == "주로조교" and
                (candidate.get("label") == "관" or candidate.get("label", "").endswith("(관)")),
                f"Sample evidence has unexpected classifiable label: row {row_id}")
        page = source_pages.get(candidate.get("date"))
        require(page is not None and candidate.get("source_path") == page["source_path"] and
                candidate.get("source_sha256") == page["sha256"],
                f"Sample source identity differs: row {row_id}")
        evidence_by_id[row_id] = candidate
    require(set(plan_by_id) == set(evidence_by_id),
            f"Initial plan IDs differ from verified evidence: plan={len(plan_by_id)}, evidence={len(evidence_by_id)}")

    connection = connect_readonly(db_path)
    before_sha = sha256_file(db_path)
    require(plan_summary.get("database_sha256") == before_sha,
            "Database SHA differs from the initial plan's read-only source snapshot")
    row_ids = sorted(evidence_by_id)
    expected_source = {}
    expected_old = {}
    for offset in range(0, len(row_ids), 400):
        part = row_ids[offset:offset + 400]
        placeholders = ",".join("?" for _ in part)
        query = (
            "SELECT d.daily_training_api_row_id AS row_id, " +
            ",".join(f'd."{field}" AS d_{field}' for field in SOURCE_FIELDS) + "," +
            ",".join(f'a."{field}" AS a_{field}' for field in ASSIGNMENT_FIELDS) +
            " FROM daily_training_api_rows d JOIN daily_training_rider_type_assignments a "
            "USING(daily_training_api_row_id) WHERE d.daily_training_api_row_id IN (" +
            placeholders + ")"
        )
        for fetched in connection.execute(query, part):
            record = dict(fetched)
            row_id = record["row_id"]
            expected_source[row_id] = {field: record[f"d_{field}"] for field in SOURCE_FIELDS}
            expected_old[row_id] = {field: record[f"a_{field}"] for field in ASSIGNMENT_FIELDS}
    require(set(expected_source) == set(row_ids) and set(expected_old) == set(row_ids),
            "Read-only database source or assignment rows are incomplete")

    for row_id, candidate in evidence_by_id.items():
        old = expected_old[row_id]
        source = expected_source[row_id]
        date_text = candidate["date"]
        source_page = source_pages[date_text]
        require(old["rider_type"] == "미분류" and old["prGubun_raw"] == "-",
                f"Initial candidate is no longer eligible: {row_id}")
        require(all(source[field] == old[field] for field in SOURCE_FIELDS),
                f"Source snapshot differs from assignment: {row_id}")
        require(source["training_date"] == date_text and
                source["horse_id"] == str(candidate["horse_id"]) and
                source["start_time_local"] == date_text + " " + candidate["start"] + ":00" and
                source["end_time_local"] == date_text + " " + candidate["end"] + ":00" and
                source["duration_seconds"] == candidate["duration_seconds"],
                f"Sample event identity differs from source database: {row_id}")
        new = dict(old)
        new.update({
            "rider_type": "주로조교", "type_status": "website_same_event_type",
            "website_type": "주로조교", "website_label_raw": candidate["label"],
            "website_jockey_name": None,
            "website_source_path": source_page["source_path"],
            "website_sha256": source_page["sha256"],
        })
        plan_row = plan_by_id[row_id]
        require(plan_row.get("old") == old and plan_row.get("new") == new,
                f"Full assignment old/new mismatch: row {row_id}")
        require(plan_row.get("old_type") == old["rider_type"] and
                plan_row.get("new_type") == "주로조교" and
                plan_row.get("old_status") == old["type_status"] and
                plan_row.get("new_status") == "website_same_event_type",
                f"Flat assignment type/status mismatch: row {row_id}")
        for field in SOURCE_FIELDS:
            require(plan_row.get(field) == old[field],
                    f"Flat source field mismatch ({field}): row {row_id}")
        for field in CHANGED_FIELDS:
            require(plan_row.get(field) == new[field],
                    f"Flat new assignment field mismatch ({field}): row {row_id}")

    connection.close()
    after_sha = sha256_file(db_path)
    require(before_sha == after_sha, "Database file changed during read-only gate")
    report = {
        "passed": True,
        "phase": "initial_609_preapply",
        "read_only": True,
        "database_mode": "SQLite URI mode=ro with query_only=ON",
        "database_sha256_before": before_sha,
        "database_sha256_after": after_sha,
        "plan_path": str(plan_path.relative_to(PROJECT)),
        "plan_sha256": plan_sha,
        "sample_verification_sha256": sha256_file(sample_path),
        "sample_match_evidence_sha256": sha256_file(matches_path),
        "sample_gate": {
            "status": "passed", "official_pages": 6,
            "exact_event_matches": 805, "candidate_rows": 609,
            "ambiguous_keys_excluded": 1,
            "prior_independent_parser": sample["parser"],
            "html_reparsed": False,
        },
        "plan_rows_verified_full_old_new": len(plan_by_id),
        "source_and_assignment_snapshots_checked": len(row_ids),
        "database_modified": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as exc:
        print(f"PREAPPLY_GATE_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(2)
