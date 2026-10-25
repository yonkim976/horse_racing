#!/usr/bin/env python3
"""Independent streaming verification for the older KRA daily-detail completion.

Collection pages are parsed with BeautifulSoup here, independently of the
collector's stdlib HTMLParser. Every successful day is verified once and gets
an immutable receipt. The full preapply phase binds the frozen combined
outputs and old/new plan to the fixed post-609 snapshot. The postapply phase
checks only planned IDs and guarded current values in SQLite read-only mode.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any, Iterable

from official_daily_detail import ENDPOINT, OfficialPageError, classify_label, parse_page


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
PROJECT = TASK.parents[2]
COLLECTION = TASK / "collection"
SNAPSHOT = COLLECTION / "snapshot_post609"
RUN = COLLECTION / "official_daily_all"
DB = PROJECT / "jeju/data/jeju_native_core.sqlite3"
ROSTER = PROJECT / "data/research/jockey_roster_20261008"
INDEX = HERE / "snapshot_post609_date_index.json"
DAY_REPORTS = HERE / "full_days"
FULL_REPORT = HERE / "full_preapply_verification.json"
POST_REPORT = HERE / "full_postapply_verification.json"
EXPECTED_ROWS = 280351
EXPECTED_DATES = 4122
MAX_OFFICIAL_PAGE_BYTES = 4 * 1024 * 1024
EXPECTED_DB_SHA = "f3700e12c8dcf0b791d497cca1e7b219e32778a3bba322ed5fe9a9b4a201defa"
SOURCE_FIELDS = (
    "daily_training_api_artifact_id", "prGubun_raw", "prNo_raw", "horse_id",
    "training_date", "start_time_local", "end_time_local", "duration_seconds",
)
ASSIGNMENT_FIELDS = (
    "daily_training_api_row_id", "daily_training_api_artifact_id", "prGubun_raw",
    "prNo_raw", "horse_id", "training_date", "start_time_local", "end_time_local",
    "duration_seconds", "rider_type", "type_status", "website_type",
    "website_label_raw", "website_jockey_name", "website_source_path", "website_sha256",
)
CHANGED_FIELDS = (
    "rider_type", "type_status", "website_type", "website_label_raw",
    "website_jockey_name", "website_source_path", "website_sha256",
)


class VerifyError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerifyError(message)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_line(value: Any) -> bytes:
    return (canonical(value) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerifyError(f"Cannot read JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def safe_within(base: Path, path: Path, *, must_exist: bool = True) -> Path:
    resolved = path.resolve(strict=must_exist)
    require(resolved.is_relative_to(base.resolve()), f"Path escapes approved folder: {path}")
    return resolved


def date_key(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise VerifyError(f"Invalid ISO date: {value}") from exc
    require(parsed.isoformat() == value, f"Noncanonical ISO date: {value}")
    return parsed.strftime("%Y%m%d")


def load_snapshot_index() -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    manifest_path = safe_within(COLLECTION, SNAPSHOT / "snapshot_manifest.json")
    manifest = read_json(manifest_path)
    require(manifest.get("database_mode") == "ro" and manifest.get("query_only") is True,
            "Post-609 snapshot was not captured read-only")
    require(manifest.get("row_count") == EXPECTED_ROWS and
            manifest.get("distinct_dates") == EXPECTED_DATES,
            "Post-609 snapshot population differs from the approved scope")
    before = manifest.get("db_artifact_sha256_before", {})
    after = manifest.get("db_artifact_sha256_after", {})
    require(before == after and before.get("database") == EXPECTED_DB_SHA and before.get("wal") is None,
            "Post-609 snapshot database binding differs from the initial 609 apply")
    snapshot_path = safe_within(COLLECTION, SNAPSHOT / "target_rows.jsonl")
    require(manifest.get("snapshot_path") == str(snapshot_path.relative_to(PROJECT)),
            "Snapshot path binding mismatch")

    stat = snapshot_path.stat()
    if INDEX.exists():
        cached = read_json(INDEX)
        require(cached.get("snapshot_sha256") == manifest.get("snapshot_sha256") and
                cached.get("snapshot_size") == stat.st_size and
                cached.get("snapshot_mtime_ns") == stat.st_mtime_ns,
                "Cached snapshot index no longer matches the fixed snapshot artifact")
        by_date = cached.get("dates")
        require(isinstance(by_date, dict) and len(by_date) == EXPECTED_DATES,
                "Cached date index is malformed")
        return manifest, by_date

    # One bounded-memory pass pins the snapshot and builds byte offsets by day.
    digest = hashlib.sha256()
    by_date: dict[str, dict[str, int]] = {}
    row_count = 0
    position = 0
    previous: tuple[str, int] | None = None
    with snapshot_path.open("rb") as stream:
        while True:
            line = stream.readline()
            if not line:
                break
            digest.update(line)
            try:
                row = json.loads(line)
                training_date = row["date"]
                row_id = int(row["row_id"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise VerifyError(f"Invalid snapshot row {row_count + 1}: {exc}") from exc
            require(isinstance(training_date, str), f"Invalid date at snapshot row {row_count + 1}")
            date_key(training_date)
            sort_key = (training_date, row_id)
            require(previous is None or previous < sort_key,
                    f"Snapshot ordering or row-ID uniqueness failed at row {row_count + 1}")
            previous = sort_key
            entry = by_date.setdefault(training_date, {"start": position, "end": 0, "rows": 0})
            entry["end"] = position + len(line)
            entry["rows"] += 1
            position += len(line)
            row_count += 1
    require(row_count == EXPECTED_ROWS and position == stat.st_size,
            "Snapshot row count or byte length differs from manifest")
    snapshot_sha = digest.hexdigest()
    require(snapshot_sha == manifest.get("snapshot_sha256"), "Snapshot JSONL SHA differs from manifest")
    require(sorted(by_date) == manifest.get("dates"), "Snapshot dates differ from manifest")
    counts = manifest.get("date_counts", {})
    require(all(int(counts.get(day, -1)) == info["rows"] for day, info in by_date.items()),
            "Snapshot date row counts differ from the manifest")
    cache = {
        "snapshot_sha256": snapshot_sha,
        "snapshot_size": stat.st_size,
        "snapshot_mtime_ns": stat.st_mtime_ns,
        "row_count": row_count,
        "dates": by_date,
        "method": "single sequential SHA-256 and byte-offset pass; per-day reads thereafter",
    }
    write_json_once(INDEX, cache)
    return manifest, by_date


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists(), f"Refusing to overwrite immutable verification artifact: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    require(not temporary.exists(), f"Refusing to overwrite pending artifact: {temporary}")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def snapshot_rows_for_day(info: dict[str, int]) -> list[dict[str, Any]]:
    path = safe_within(COLLECTION, SNAPSHOT / "target_rows.jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("rb") as stream:
        stream.seek(info["start"])
        remaining = info["end"] - info["start"]
        while remaining:
            line = stream.readline()
            require(bool(line), "Snapshot ended inside a date range")
            remaining -= len(line)
            row = json.loads(line)
            require(row.get("date"), "Snapshot row is missing date")
            rows.append(row)
    require(len(rows) == info["rows"], "Per-date snapshot row count mismatch")
    return rows


def load_jockey_names() -> tuple[set[str], dict[str, Any]]:
    manifest_path = safe_within(PROJECT, ROSTER / "manifest.json")
    manifest = read_json(manifest_path)
    names: set[str] = set()
    files = []
    roster_rows = manifest.get("rows")
    require(isinstance(roster_rows, list), "API307 roster manifest has no rows list")
    for meet in (1, 2, 3):
        path = safe_within(PROJECT, ROSTER / f"api_{meet}.json")
        digest = sha256_file(path)
        meet_entries = [row for row in roster_rows if row.get("meet_code") == meet]
        require(meet_entries and {row.get("api_sha256") for row in meet_entries} == {digest},
                f"API307 meet {meet} source hash does not match its manifest")
        payload = read_json(path)
        try:
            body = payload["response"]["body"]
            items = body["items"]["item"]
            items = [items] if isinstance(items, dict) else items
            total = int(body["totalCount"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VerifyError(f"Malformed API307 meet {meet} JSON: {exc}") from exc
        require(isinstance(items, list) and len(items) == total,
                f"API307 meet {meet} roster page set is incomplete")
        names.update(item["jkName"] for item in items
                     if isinstance(item, dict) and item.get("jkName") not in (None, "", "-"))
        files.append({"meet": meet, "sha256": digest, "rows": total})
    return names, {"manifest_sha256": sha256_file(manifest_path), "files": files}


def api_key(source: dict[str, Any], training_date: str) -> tuple[str, str, str, str, int] | None:
    horse = source.get("horse_id")
    start = source.get("start_time_local")
    end = source.get("end_time_local")
    duration = source.get("duration_seconds")
    if not isinstance(horse, str) or not isinstance(start, str) or not isinstance(end, str):
        return None
    if not isinstance(duration, int) or duration <= 0:
        return None
    pattern = r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:00"
    if re.fullmatch(pattern, start) is None or re.fullmatch(pattern, end) is None:
        return None
    if start[:10] != training_date or end[:10] != training_date:
        return None
    return horse, training_date, start[11:16], end[11:16], duration


def page_key(row: dict[str, Any]) -> tuple[str, str, str, str, int] | None:
    start, end, duration = row.get("start"), row.get("end"), row.get("duration_seconds")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    if not isinstance(duration, int) or duration <= 0:
        return None
    return str(row["horse_id"]), str(row["date"]), start, end, duration


def duplicate_api_keys(snapshot_manifest: dict[str, Any], training_date: str) -> set[tuple[str, str, str, str, int]]:
    name = f"{date_key(training_date)}.jsonl"
    digest = snapshot_manifest.get("duplicate_key_files", {}).get(name)
    path = SNAPSHOT / "api_duplicate_keys" / name
    if digest is None:
        require(not path.exists(), f"Unmanifested duplicate key index exists: {name}")
        return set()
    path = safe_within(COLLECTION, path)
    require(sha256_file(path) == digest, f"Duplicate API key index SHA mismatch: {name}")
    result = set()
    with path.open("r", encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
                count = int(row["api_row_count"])
                start, end = row["start_time_local"], row["end_time_local"]
                require(row["date"] == training_date and count > 1,
                        f"Invalid duplicate index record {name}:{number}")
                require(isinstance(start, str) and isinstance(end, str) and
                        start[:10] == training_date and end[:10] == training_date,
                        f"Duplicate index event date mismatch {name}:{number}")
                result.add((str(row["horse_id"]), training_date, start[11:16], end[11:16],
                            int(row["duration_seconds"])))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise VerifyError(f"Malformed duplicate key index {name}:{number}: {exc}") from exc
    return result


def read_receipt(run_dir: Path, training_date: str) -> tuple[Path, dict[str, Any]] | None:
    path = safe_within(COLLECTION, run_dir / "date_receipts" / f"{date_key(training_date)}.json",
                       must_exist=False)
    if not path.exists():
        return None
    return path, read_json(path)


def verify_page_receipt(run_dir: Path, training_date: str,
                        receipt: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    require(receipt.get("status") == "success" and receipt.get("date") == training_date and
            receipt.get("date_key") == date_key(training_date),
            f"Receipt is not a committed success for {training_date}")
    require(receipt.get("url") == ENDPOINT and receipt.get("form_fields") == {
        "meet": "2", "Act": "10", "Sub": "3", "trDate": training_date.replace("-", "/"),
        "trDateReplace": training_date.replace("-", ""), "trYo": "", "trNo": "", "trName": "",
    }, f"Receipt request binding changed for {training_date}")
    page = receipt.get("page")
    require(isinstance(page, dict), f"Receipt missing page metadata for {training_date}")
    require(page.get("date") == training_date and page.get("url") == ENDPOINT and
            page.get("method") == "POST" and page.get("http_status") == 200 and
            page.get("final_url") == ENDPOINT and
            "text/html" in str(page.get("content_type", "")).lower() and
            page.get("form_fields") == receipt.get("form_fields"),
            f"Official response metadata mismatch for {training_date}")
    rel = Path(str(page.get("source_path", "")))
    require(not rel.is_absolute(), f"Absolute page path in receipt: {rel}")
    page_path = safe_within(COLLECTION, PROJECT / rel)
    require(page_path.is_relative_to(run_dir.resolve()), f"Page path outside this collector run: {rel}")
    require(page_path.stat().st_size <= MAX_OFFICIAL_PAGE_BYTES,
            f"Official page exceeds the collector response limit: {training_date}")
    raw = page_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    require(digest == page.get("sha256") and int(page.get("bytes", -1)) == len(raw),
            f"Official page bytes/hash mismatch for {training_date}")
    parsed = parse_page(raw, training_date)
    require(parsed["row_count"] == page.get("parsed_row_count"),
            f"Independent HTML row count differs from receipt for {training_date}")
    require(parsed["invalid_timing_rows"] == page.get("invalid_timing_rows"),
            f"Independent invalid-timing evidence differs for {training_date}")
    require(page.get("legend_validation") == "passed" and
            page.get("hidden_date_meet_validation") == "passed" and
            page.get("table_header_validation") == "passed",
            f"Collector omitted one page validation for {training_date}")
    return page, parsed


def expected_day_records(training_date: str, rows: list[dict[str, Any]],
                         page: dict[str, Any], parsed: dict[str, Any],
                         duplicates: set[tuple[str, str, str, str, int]],
                         jockey_names: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    page_by_key: dict[tuple[str, str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in parsed["rows"]:
        key = page_key(row)
        if key is not None:
            page_by_key[key].append(row)

    outcomes: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for item in rows:
        source = item.get("source")
        require(isinstance(source, dict) and item.get("assignment") is not None,
                f"Snapshot source/assignment missing for target row {item.get('row_id')}")
        row_id = int(item["row_id"])
        horse_id = str(source["horse_id"])
        key = api_key(source, training_date)
        label: str | None = None
        matched: dict[str, Any] | None = None
        jockey_name: str | None = None
        kind = "미분류"
        if key is None:
            status = "missing_or_invalid_api_timing"
        else:
            matches = page_by_key.get(key, [])
            api_duplicate = key in duplicates
            if api_duplicate or len(matches) > 1:
                if api_duplicate and len(matches) > 1:
                    status = "ambiguous_api_and_website_key"
                elif api_duplicate:
                    status = "ambiguous_api_key"
                else:
                    status = "ambiguous_website_key"
            elif not matches:
                status = "no_exact_website_event_match"
            else:
                matched = matches[0]
                label = str(matched["label"])
                kind, jockey_name = classify_label(label, jockey_names)
                status = "classifiable_exact_match" if kind != "미분류" else "exact_match_label_unresolved"
        outcome = {
            "row_id": row_id, "date": training_date, "horse_id": horse_id,
            "status": status, "label": label, "candidate_type": kind,
            "jockey_name": jockey_name,
        }
        outcomes.append(outcome)
        counts[status] += 1
        if status == "classifiable_exact_match":
            require(matched is not None, f"Classifiable result missing page event: row {row_id}")
            candidates.append({
                "row_id": row_id, "date": training_date, "horse_id": horse_id,
                "label": label, "candidate_type": kind, "jockey_name": jockey_name,
                "start": matched["start"], "end": matched["end"],
                "duration_seconds": matched["duration_seconds"],
                "source_path": page["source_path"], "source_sha256": page["sha256"],
                "url": page["url"], "form_fields": page["form_fields"],
                "method": "unique_exact_horse_date_start_end_duration",
            })
    return outcomes, candidates, counts


def verify_jsonl_exact(path: Path, expected: Iterable[dict[str, Any]], label: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    iterator = iter(expected)
    try:
        with path.open("rb") as stream:
            for number, actual in enumerate(stream, 1):
                wanted = next(iterator, None)
                require(wanted is not None, f"Unexpected extra row in {label} at line {number}")
                expected_bytes = json_line(wanted)
                require(actual == expected_bytes,
                        f"Independent {label} mismatch at line {number} ({path.name})")
                digest.update(actual)
                count += 1
    except OSError as exc:
        raise VerifyError(f"Could not read {label} file {path}: {exc}") from exc
    require(next(iterator, None) is None, f"Missing rows in {label} file {path}")
    return count, digest.hexdigest()


def verify_one_day(training_date: str, snapshot_manifest: dict[str, Any],
                   rows: list[dict[str, Any]], run_dir: Path,
                   jockey_names: set[str], roster_info: dict[str, Any]) -> dict[str, Any] | None:
    receipt_info = read_receipt(run_dir, training_date)
    if receipt_info is None:
        return None
    receipt_path, receipt = receipt_info
    if receipt.get("status") != "success":
        return None
    receipt_sha = sha256_file(receipt_path)
    report_path = DAY_REPORTS / f"{date_key(training_date)}.json"
    if report_path.exists():
        saved = read_json(report_path)
        require(saved.get("status") == "passed" and
                saved.get("receipt_sha256") == receipt_sha and
                saved.get("snapshot_sha256") == snapshot_manifest["snapshot_sha256"],
                f"Existing per-day verification receipt does not bind current artifacts: {training_date}")
        return saved

    page, parsed = verify_page_receipt(run_dir, training_date, receipt)
    duplicates = duplicate_api_keys(snapshot_manifest, training_date)
    outcomes, candidates, counts = expected_day_records(
        training_date, rows, page, parsed, duplicates, jockey_names,
    )
    receipt_files = {entry.get("path"): entry for entry in receipt.get("files", [])
                     if isinstance(entry, dict)}
    reports: dict[str, Any] = {}
    for suffix, expected in (("outcomes", outcomes), ("candidates", candidates)):
        relative = f"day_results/{date_key(training_date)}.{suffix}.jsonl"
        target = safe_within(COLLECTION, run_dir / relative)
        entry = receipt_files.get(relative)
        require(entry is not None and target.is_file() and
                int(entry.get("rows", -1)) == len(expected) and
                sha256_file(target) == entry.get("sha256"),
                f"Committed {suffix} artifact hash/count mismatch for {training_date}")
        count, digest = verify_jsonl_exact(target, expected, f"{training_date} {suffix}")
        reports[suffix] = {"rows": count, "sha256": digest}
    require(receipt.get("counts", {}) == dict(counts),
            f"Outcome counts differ from independent page matching for {training_date}")

    report = {
        "status": "passed",
        "date": training_date,
        "snapshot_sha256": snapshot_manifest["snapshot_sha256"],
        "snapshot_rows": len(rows),
        "receipt_sha256": receipt_sha,
        "page_sha256": page["sha256"],
        "page_bytes": page["bytes"],
        "independent_parser": "BeautifulSoup html.parser (not collector HTMLParser)",
        "page_rows": parsed["row_count"],
        "page_invalid_timing_rows": len(parsed["invalid_timing_rows"]),
        "exact_page_event_keys": sum(1 for row in parsed["rows"] if page_key(row) is not None),
        "duplicate_api_key_groups": len(duplicates),
        "outcomes": reports["outcomes"],
        "candidates": reports["candidates"],
        "outcome_status_counts": dict(counts),
        "api307_roster_manifest_sha256": roster_info["manifest_sha256"],
    }
    write_json_once(report_path, report)
    return report


def all_day_reports(days: list[str], snapshot_sha: str) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for training_date in days:
        path = DAY_REPORTS / f"{date_key(training_date)}.json"
        if not path.is_file():
            continue
        report = read_json(path)
        require(report.get("status") == "passed" and report.get("date") == training_date and
                report.get("snapshot_sha256") == snapshot_sha,
                f"Invalid cached per-day verification receipt: {training_date}")
        reports[training_date] = report
    return reports


def verify_days(limit: int | None, *, quiet: bool = False) -> dict[str, Any]:
    snapshot_manifest, date_index = load_snapshot_index()
    jockey_names, roster_info = load_jockey_names()
    DAY_REPORTS.mkdir(parents=True, exist_ok=True)
    dates = list(snapshot_manifest["dates"])
    processed = 0
    successes = 0
    newly_parsed = 0
    failures = []
    for training_date in dates:
        if limit is not None and successes >= limit:
            break
        info = date_index.get(training_date)
        require(info is not None, f"Missing snapshot index entry: {training_date}")
        receipt_info = read_receipt(RUN, training_date)
        if receipt_info is None or receipt_info[1].get("status") != "success":
            continue
        try:
            rows = snapshot_rows_for_day(info)
            saved_report = DAY_REPORTS / f"{date_key(training_date)}.json"
            was_cached = saved_report.exists()
            report = verify_one_day(training_date, snapshot_manifest, rows, RUN,
                                    jockey_names, roster_info)
            require(report is not None, f"Successful receipt was not verified: {training_date}")
            processed += 1
            successes += 1
            if not was_cached:
                newly_parsed += 1
            if not quiet and newly_parsed and newly_parsed % 10 == 0 and not was_cached:
                print(json.dumps({"new_successful_pages_independently_parsed": newly_parsed,
                                  "all_success_receipts_confirmed": processed,
                                  "last_date": training_date,
                                  "day_rows": report["snapshot_rows"],
                                  "day_candidates": report["candidates"]["rows"]}, ensure_ascii=False),
                      flush=True)
        except Exception as exc:
            failures.append({"date": training_date, "error": f"{type(exc).__name__}: {exc}"})
            break
    report = {
        "status": "passed" if not failures else "failed",
        "mode": "incremental_days",
        "successful_pages_confirmed_this_scan": processed,
        "new_successful_pages_independently_parsed": newly_parsed,
        "requested_successful_page_limit": limit,
        "snapshot_sha256": snapshot_manifest["snapshot_sha256"],
        "total_target_dates": len(dates),
        "roster_manifest_sha256": roster_info["manifest_sha256"],
        "failures": failures,
    }
    if not quiet or failures:
        print(json.dumps(report, ensure_ascii=False), flush=True)
    require(not failures, failures[0]["error"] if failures else "Unexpected verifier failure")
    return report


def count_jsonl(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        for count, line in enumerate(stream, 1):
            digest.update(line)
    return count, digest.hexdigest()


def verify_full_preapply(plan_path: Path, expected_plan_sha: str) -> dict[str, Any]:
    snapshot_manifest, date_index = load_snapshot_index()
    run_manifest_path = safe_within(COLLECTION, RUN / "run_manifest.json")
    run_manifest = read_json(run_manifest_path)
    require(run_manifest.get("frozen_at_utc") and run_manifest.get("state") in
            {"frozen_complete", "frozen_with_failures"},
            "Collector run is not frozen")
    require(run_manifest.get("snapshot_sha256") == snapshot_manifest["snapshot_sha256"] and
            run_manifest.get("target_rows") == EXPECTED_ROWS and
            run_manifest.get("target_dates") == snapshot_manifest["dates"],
            "Frozen collector run is not bound to post-609 snapshot")
    require(run_manifest.get("database_writes") is False,
            "Collector manifest does not attest to read-only database behavior")
    roster_names, roster_info = load_jockey_names()
    collected_roster = run_manifest.get("roster", {})
    collected_artifacts = collected_roster.get("artifacts", []) if isinstance(collected_roster, dict) else []
    collected_hashes = sorted((int(item["meet"]), item["sha256"], int(item["rows"]))
                              for item in collected_artifacts)
    verified_hashes = sorted((int(item["meet"]), item["sha256"], int(item["rows"]))
                             for item in roster_info["files"])
    require(isinstance(collected_roster, dict) and
            collected_roster.get("manifest_sha256") == roster_info["manifest_sha256"] and
            collected_hashes == verified_hashes,
            "Frozen collector API307 manifest/artifacts differ from independently SHA-verified roster")

    dates = list(snapshot_manifest["dates"])
    day_reports = all_day_reports(dates, snapshot_manifest["snapshot_sha256"])
    require(all(report.get("api307_roster_manifest_sha256") == roster_info["manifest_sha256"]
                for report in day_reports.values()),
            "A cached per-day check used a different API307 roster manifest")
    successful = 0
    failed = 0
    failed_dates_verified: list[str] = []
    page_rows_total = 0
    candidate_count = 0
    outcome_count = 0
    outcome_counts: Counter[str] = Counter()
    candidate_counts: Counter[str] = Counter()
    all_candidates_path = safe_within(COLLECTION, RUN / "candidates.jsonl")
    all_outcomes_path = safe_within(COLLECTION, RUN / "outcomes.jsonl")
    require(not FULL_REPORT.exists(), f"Full preapply gate already exists: {FULL_REPORT}")

    # Stream through each frozen day and compare the final concatenated files
    # without retaining whole-page or whole-candidate collections in memory.
    all_candidates = all_candidates_path.open("rb")
    all_outcomes = all_outcomes_path.open("rb")
    combined_candidate_digest = hashlib.sha256()
    combined_outcome_digest = hashlib.sha256()
    try:
        for training_date in dates:
            receipt_info = read_receipt(RUN, training_date)
            require(receipt_info is not None, f"Missing frozen date receipt: {training_date}")
            receipt_path, receipt = receipt_info
            info = date_index[training_date]
            rows = snapshot_rows_for_day(info)
            if receipt.get("status") == "success":
                successful += 1
                require(training_date in day_reports,
                        f"Successful date lacks independent BeautifulSoup verification: {training_date}")
                report = day_reports[training_date]
                page_rows_total += int(report["page_rows"])
                require(report.get("receipt_sha256") == sha256_file(receipt_path),
                        f"Cached day verification no longer binds receipt: {training_date}")
                page_meta = receipt.get("page", {})
                page_rel = Path(str(page_meta.get("source_path", "")))
                require(not page_rel.is_absolute(), f"Absolute page path in receipt: {training_date}")
                raw_page = safe_within(COLLECTION, PROJECT / page_rel)
                require(raw_page.is_relative_to(RUN.resolve()) and raw_page.is_file() and
                        report.get("page_sha256") == page_meta.get("sha256"),
                        f"Cached page evidence path/hash binding changed since independent parse: {training_date}")
                receipt_files = {entry.get("path"): entry for entry in receipt.get("files", [])
                                 if isinstance(entry, dict)}
                candidate_file = safe_within(COLLECTION, RUN / "day_results" /
                                             f"{date_key(training_date)}.candidates.jsonl")
                outcome_file = safe_within(COLLECTION, RUN / "day_results" /
                                           f"{date_key(training_date)}.outcomes.jsonl")
                for suffix, target_stream, expected_hash_key in (
                    ("candidates", all_candidates, "candidates"),
                    ("outcomes", all_outcomes, "outcomes"),
                ):
                    expected_file = candidate_file if suffix == "candidates" else outcome_file
                    relative_file = f"day_results/{date_key(training_date)}.{suffix}.jsonl"
                    receipt_file = receipt_files.get(relative_file)
                    require(receipt_file is not None,
                            f"Date receipt is missing {suffix} metadata: {training_date}")
                    day_digest = hashlib.sha256()
                    day_rows_count = 0
                    with expected_file.open("rb") as day_stream:
                        for number, expected_line in enumerate(day_stream, 1):
                            actual = target_stream.readline()
                            require(actual == expected_line,
                                    f"Frozen combined {suffix} differs at {training_date}:{number}")
                            day_digest.update(expected_line)
                            day_rows_count += 1
                            (combined_candidate_digest if suffix == "candidates" else
                             combined_outcome_digest).update(actual)
                            record = json.loads(expected_line)
                            if suffix == "candidates":
                                candidate_count += 1
                                candidate_counts[record["candidate_type"]] += 1
                            else:
                                outcome_count += 1
                                outcome_counts[record["status"]] += 1
                    require(day_rows_count == report[suffix]["rows"] == int(receipt_file.get("rows", -1)) and
                            day_digest.hexdigest() == report[suffix]["sha256"] == receipt_file.get("sha256"),
                            f"Day {suffix} bytes changed since independent verification: {training_date}")
                require(report["outcomes"]["rows"] == len(rows),
                        f"Verified date outcome count differs from snapshot: {training_date}")
            else:
                require(receipt.get("status") in {"failed_retryable", "failed_terminal"},
                        f"Unexpected frozen receipt status for {training_date}: {receipt.get('status')}")
                failed += 1
                failed_dates_verified.append(training_date)
                attempts = receipt.get("attempts", [])
                error_type = attempts[-1].get("error_type") if attempts else None
                for source_row in rows:
                    record = {
                        "row_id": int(source_row["row_id"]),
                        "date": training_date,
                        "horse_id": str(source_row["source"]["horse_id"]),
                        "status": "official_page_failed",
                        "label": None,
                        "candidate_type": "미분류",
                        "jockey_name": None,
                        "page_error_type": error_type,
                    }
                    actual = all_outcomes.readline()
                    expected_line = json_line(record)
                    require(actual == expected_line,
                            f"Frozen failed-page outcome differs: {training_date}, row {record['row_id']}")
                    combined_outcome_digest.update(actual)
                    outcome_count += 1
                    outcome_counts[record["status"]] += 1
            # Candidate stream contributes zero rows for failed dates.
        require(all_candidates.readline() == b"", "Frozen candidates has unexpected trailing rows")
        require(all_outcomes.readline() == b"", "Frozen outcomes has unexpected trailing rows")
    finally:
        all_candidates.close()
        all_outcomes.close()

    require(successful == run_manifest.get("dates_successful") and
            failed == run_manifest.get("dates_failed") and
            failed == len(run_manifest.get("failed_dates", [])) and
            sorted(failed_dates_verified) == run_manifest.get("failed_dates", []) and
            successful + failed == EXPECTED_DATES and
            run_manifest.get("receipt_date_count") == EXPECTED_DATES,
            "Frozen run date counts differ from verified receipts")
    require(page_rows_total == run_manifest.get("page_rows"),
            "Frozen page row total differs from the independent per-day HTML parses")
    require(outcome_count == EXPECTED_ROWS == run_manifest.get("total_outcome_rows"),
            "Final outcomes do not cover every snapshot target exactly once")
    require(candidate_count == run_manifest.get("total_candidates"),
            "Final candidate row count differs from frozen collector manifest")
    require(dict(candidate_counts) == run_manifest.get("candidate_type_counts") and
            dict(outcome_counts) == run_manifest.get("outcome_status_counts"),
            "Frozen outcome/candidate aggregate counts differ")
    combined_digests = {
        "outcomes.jsonl": combined_outcome_digest.hexdigest(),
        "candidates.jsonl": combined_candidate_digest.hexdigest(),
    }
    for name, path, count in (("outcomes.jsonl", all_outcomes_path, outcome_count),
                              ("candidates.jsonl", all_candidates_path, candidate_count)):
        meta = run_manifest.get("combined_files", {}).get(name)
        require(meta is not None and int(meta.get("rows", -1)) == count and
                combined_digests[name] == meta.get("sha256"),
                f"Frozen combined file binding mismatch: {name}")

    plan_path = safe_within(TASK, plan_path)
    require(re.fullmatch(r"[0-9a-f]{64}", expected_plan_sha) is not None,
            "Expected plan SHA must be 64 lowercase hex characters")
    summary_path = plan_path.with_suffix(".summary.json")
    summary = read_json(summary_path)
    require(summary.get("plan_sha256") == expected_plan_sha and
            summary.get("candidate_rows") == candidate_count and
            summary.get("database_sha256") == EXPECTED_DB_SHA and
            summary.get("input") == str(all_candidates_path.relative_to(PROJECT)) and
            summary.get("input_sha256") == combined_digests["candidates.jsonl"] and
            summary.get("new_type_counts") == dict(candidate_counts),
            "Full plan summary does not bind verified collector outputs and post-609 DB")

    plan_count = 0
    type_counts: Counter[str] = Counter()
    candidate_source_paths: set[str] = set()
    plan_digest = hashlib.sha256()
    plan_stream = plan_path.open("r", encoding="utf-8")
    try:
        # Candidate output is date-sorted. Decode each snapshot date once and
        # hold only that date's source/assignment rows while checking its plan.
        for date_value in dates:
            receipt_info = read_receipt(RUN, date_value)
            require(receipt_info is not None, f"Missing date receipt during plan audit: {date_value}")
            if receipt_info[1].get("status") != "success":
                continue
            day_rows = snapshot_rows_for_day(date_index[date_value])
            old_by_id = {int(item["row_id"]): item for item in day_rows}
            candidate_path = safe_within(COLLECTION, RUN / "day_results" /
                                         f"{date_key(date_value)}.candidates.jsonl")
            with candidate_path.open("r", encoding="utf-8") as candidate_stream:
                for number, line in enumerate(candidate_stream, 1):
                    candidate = json.loads(line)
                    try:
                        planned_line = next(plan_stream)
                    except StopIteration as exc:
                        raise VerifyError(f"Full plan ended before {date_value} candidate {number}") from exc
                    plan_digest.update(planned_line.encode("utf-8"))
                    planned = json.loads(planned_line)
                    row_id = int(candidate["row_id"])
                    old_snapshot = old_by_id.get(row_id)
                    require(old_snapshot is not None,
                            f"Plan candidate absent from date snapshot: {date_value}, row {row_id}")
                    old = old_snapshot.get("assignment")
                    source = old_snapshot.get("source")
                    require(isinstance(old, dict) and isinstance(source, dict),
                            f"Candidate lacks original assignment/source: {row_id}")
                    require(all(old.get(field) == source.get(field) for field in SOURCE_FIELDS),
                            f"Snapshot source and assignment differ: {row_id}")
                    require(old.get("rider_type") == "미분류" and
                            old.get("prGubun_raw") == "-" and date_value < "2026-04-17",
                            f"Candidate is outside preapply unknown scope: row {row_id}")
                    kind, jockey_name = classify_label(str(candidate["label"]), roster_names)
                    require(kind != "미분류" and kind == candidate.get("candidate_type") and
                            jockey_name == candidate.get("jockey_name"),
                            f"Candidate label/name does not independently classify: row {row_id}")
                    require((candidate.get("horse_id"), candidate.get("date"), candidate.get("start"),
                             candidate.get("end"), candidate.get("duration_seconds")) ==
                            (source.get("horse_id"), source.get("training_date"),
                             str(source.get("start_time_local"))[11:16],
                             str(source.get("end_time_local"))[11:16], source.get("duration_seconds")),
                            f"Candidate event key does not match snapshot: row {row_id}")
                    new = dict(old)
                    new.update({
                        "rider_type": kind,
                        "type_status": "website_same_event_type",
                        "website_type": kind,
                        "website_label_raw": candidate["label"],
                        "website_jockey_name": jockey_name,
                        "website_source_path": candidate["source_path"],
                        "website_sha256": candidate["source_sha256"],
                    })
                    expected_flat = {
                        "daily_training_api_row_id": row_id,
                        "old_type": old["rider_type"], "new_type": kind,
                        "old_status": old["type_status"], "new_status": new["type_status"],
                        **{field: old[field] for field in ASSIGNMENT_FIELDS},
                        **{field: new[field] for field in CHANGED_FIELDS},
                        "url": ENDPOINT,
                        "evidence_status": "exact_event_official_website",
                        "old": old, "new": new,
                    }
                    require(planned == expected_flat,
                            f"Full plan old/new or flat field mismatch at row {row_id}")
                    require((kind == "기수") == (jockey_name is not None),
                            f"Guarded jockey name rule violated in plan row {row_id}")
                    candidate_source_paths.add(str(candidate["source_path"]))
                    plan_count += 1
                    type_counts[kind] += 1
                    if plan_count % 50000 == 0:
                        print(json.dumps({"plan_rows_independently_checked": plan_count,
                                          "last_row_id": row_id}, ensure_ascii=False), flush=True)
        require(plan_stream.readline() == "", "Full plan contains rows without collector candidates")
    finally:
        plan_stream.close()
    plan_sha = plan_digest.hexdigest()
    require(plan_sha == expected_plan_sha, "Full plan SHA differs from the pinned SHA")
    require(plan_count == candidate_count and dict(type_counts) == dict(candidate_counts),
            "Full plan candidate coverage/type counts mismatch")
    require(summary.get("source_pages") == len(candidate_source_paths),
            "Full plan summary page count differs from independently checked candidates")

    current_db_sha = sha256_file(DB)
    require(current_db_sha == EXPECTED_DB_SHA,
            "Database is not the unchanged post-609 preapply artifact")
    report = {
        "passed": True,
        "phase": "full_preapply",
        "read_only": True,
        "independent_parser": "BeautifulSoup html.parser (not collector HTMLParser)",
        "snapshot_sha256": snapshot_manifest["snapshot_sha256"],
        "successful_pages_independently_verified": successful,
        "failed_dates_left_unclassified": failed,
        "independently_parsed_official_page_rows": page_rows_total,
        "target_snapshot_rows": EXPECTED_ROWS,
        "outcomes_verified": outcome_count,
        "candidates_verified": candidate_count,
        "plan_rows_verified_full_old_new": plan_count,
        "new_type_counts": dict(type_counts),
        "outcome_status_counts": dict(outcome_counts),
        "api307_roster_manifest_sha256": roster_info["manifest_sha256"],
        "api307_roster_artifacts": roster_info["files"],
        "plan_path": str(plan_path.relative_to(PROJECT)),
        "plan_sha256": plan_sha,
        "plan_summary_sha256": sha256_file(summary_path),
        "database_sha256_before": current_db_sha,
        "database_sha256_after": current_db_sha,
        "database_modified": False,
        "all_jockey_names_null_unless_type_jockey": True,
    }
    write_json_once(FULL_REPORT, report)
    print(json.dumps(report, ensure_ascii=False))
    return report


def connect_readonly() -> sqlite3.Connection:
    path = DB.resolve(strict=True)
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA foreign_keys=ON")
    require(conn.execute("PRAGMA query_only").fetchone()[0] == 1, "SQLite query_only is not enabled")
    require(conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1, "SQLite foreign_keys is not enabled")
    return conn


def verify_postapply(plan_path: Path, expected_plan_sha: str) -> dict[str, Any]:
    plan_path = safe_within(TASK, plan_path)
    conn = connect_readonly()
    checked = 0
    type_counts: Counter[str] = Counter()
    by_id: dict[int, dict[str, Any]] = {}
    plan_digest = hashlib.sha256()
    try:
        # One plan pass, then bounded, parameterized ID batches only. No legacy
        # wide views or repeated profile joins are used here.
        with plan_path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                plan_digest.update(line.encode("utf-8"))
                plan = json.loads(line)
                row_id = int(plan["daily_training_api_row_id"])
                require(row_id not in by_id, f"Duplicate plan ID at line {line_number}: {row_id}")
                by_id[row_id] = {"new": plan["new"], "kind": plan["new_type"],
                                 "status": plan["new_status"]}
                type_counts[plan["new_type"]] += 1
                if len(by_id) >= 400:
                    checked += verify_db_batch(conn, by_id)
                    by_id.clear()
        if by_id:
            checked += verify_db_batch(conn, by_id)
            by_id.clear()
    finally:
        conn.close()
    plan_sha = plan_digest.hexdigest()
    require(plan_sha == expected_plan_sha, "Postapply plan SHA differs from pinned plan")
    require(checked == sum(type_counts.values()), "Postapply batch verification count mismatch")
    report = {
        "passed": True,
        "phase": "full_postapply_candidates_only",
        "read_only": True,
        "database_mode": "SQLite URI mode=ro with query_only=ON",
        "plan_path": str(plan_path.relative_to(PROJECT)),
        "plan_sha256": plan_sha,
        "planned_candidate_rows_checked": checked,
        "stored_assignment_full_rows_exact": checked,
        "guarded_daily_training_rider_type_values_exact": checked,
        "jockey_name_null_for_every_non_jockey": True,
        "new_type_counts": dict(type_counts),
        "database_sha256": sha256_file(DB),
        "legacy_full_views_queried": False,
    }
    write_json_once(POST_REPORT, report)
    print(json.dumps(report, ensure_ascii=False))
    return report


def verify_db_batch(conn: sqlite3.Connection, expected: dict[int, dict[str, Any]]) -> int:
    ids = sorted(expected)
    placeholders = ",".join("?" for _ in ids)
    # Keep the assignment lookup and guarded view lookup separate. A joined
    # view can materialize the whole current-value relation before applying the
    # ID filter, while these two parameterized lookups stay scoped to one batch.
    assignment_query = (
        "SELECT * FROM daily_training_rider_type_assignments "
        f"WHERE daily_training_api_row_id IN ({placeholders})"
    )
    guard_query = (
        "SELECT daily_training_api_row_id, rider_type, rider_type_status, website_jockey_name "
        "FROM daily_training_rider_type_values "
        f"WHERE daily_training_api_row_id IN ({placeholders})"
    )
    assignments: dict[int, dict[str, Any]] = {}
    for row in conn.execute(assignment_query, ids):
        values = dict(row)
        row_id = int(values["daily_training_api_row_id"])
        require(row_id not in assignments, f"Duplicate assignment row from database: {row_id}")
        assignments[row_id] = values
    guards: dict[int, dict[str, Any]] = {}
    for row in conn.execute(guard_query, ids):
        values = dict(row)
        row_id = int(values["daily_training_api_row_id"])
        require(row_id not in guards, f"Duplicate guarded value row from database: {row_id}")
        guards[row_id] = values
    found = 0
    for row_id in ids:
        binding = expected.get(row_id)
        values = assignments.get(row_id)
        require(binding is not None and values is not None,
                f"Database assignment missing or unplanned: row {row_id}")
        actual = {field: values[field] for field in ASSIGNMENT_FIELDS}
        require(actual == binding["new"], f"Stored full assignment differs from plan: row {row_id}")
        guard = guards.get(row_id)
        require(guard is not None and guard["rider_type"] == binding["kind"] and
                guard["rider_type_status"] == binding["status"] and
                guard["website_jockey_name"] == binding["new"]["website_jockey_name"],
                f"Guarded current values differ from plan: row {row_id}")
        if binding["kind"] == "기수":
            require(values["website_jockey_name"] is not None,
                    f"Jockey type has NULL event name: row {row_id}")
        else:
            require(values["website_jockey_name"] is None,
                    f"Non-jockey event leaked website jockey name: row {row_id}")
        found += 1
    require(found == len(ids), f"Postapply assignment batch missing rows: found {found}, wanted {len(ids)}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    days = commands.add_parser("days", help="Verify committed successful pages incrementally")
    days.add_argument("--limit", type=int, help="Maximum successful pages to verify this call")
    days.add_argument("--watch", action="store_true",
                      help="Keep verifying newly committed pages until collector run is frozen")
    days.add_argument("--poll-seconds", type=int, default=30,
                      help="Watch interval, from 5 to 300 seconds (default: 30)")
    preapply = commands.add_parser("preapply", help="Verify frozen run and full plan before DB apply")
    preapply.add_argument("--plan", type=Path, required=True)
    preapply.add_argument("--expected-plan-sha256", required=True)
    postapply = commands.add_parser("postapply", help="Verify planned rows and guards in read-only DB")
    postapply.add_argument("--plan", type=Path, required=True)
    postapply.add_argument("--expected-plan-sha256", required=True)
    args = parser.parse_args()
    if args.command == "days":
        require(args.limit is None or args.limit > 0, "--limit must be a positive number")
        require(5 <= args.poll_seconds <= 300, "--poll-seconds must be between 5 and 300")
        if not args.watch:
            verify_days(args.limit)
        else:
            require(args.limit is None, "--watch scans all available successful receipts")
            while True:
                report = verify_days(None, quiet=True)
                manifest_path = safe_within(COLLECTION, RUN / "run_manifest.json", must_exist=False)
                frozen = manifest_path.exists() and bool(read_json(manifest_path).get("frozen_at_utc"))
                if frozen:
                    print(json.dumps({**report, "collector_frozen": True}, ensure_ascii=False), flush=True)
                    break
                if report["new_successful_pages_independently_parsed"]:
                    print(json.dumps({**report, "collector_frozen": False}, ensure_ascii=False), flush=True)
                time.sleep(args.poll_seconds)
    elif args.command == "preapply":
        verify_full_preapply(args.plan, args.expected_plan_sha256)
    elif args.command == "postapply":
        verify_postapply(args.plan, args.expected_plan_sha256)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerifyError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
