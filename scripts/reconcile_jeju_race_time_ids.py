"""Build an isolated, race-time KRA ID evidence ledger for confirmed Jeju-native races.

Only rows whose official result rank starts with 제 are persisted. Annual API
responses can contain other horse types; only their hashes and aggregate counts
survive. The operational database and its model artifacts are read only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from horse_racing.collectors.kra_api import (
    RACE_RESULT_WITH_SECTIONS_ENDPOINT,
    RACE_RESULT_WITH_SECTIONS_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings

FIRST = 20020728
LAST = 20260912


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def official_id(value: object, width: int) -> str | None:
    """The API sometimes JSON-encodes six-digit IDs as numbers, losing zeros."""
    if value is None or str(value).strip() in {"", "0", "-"}:
        return None
    token = str(value).strip()
    if not token.isdecimal() or len(token) > width:
        return None
    return token.zfill(width)


def source_item(row: dict, evidence: dict) -> dict:
    race_date = int(row["rcDate"])
    return {
        "meet": 2,
        "race_date": f"{race_date:08d}",
        "race_number": int(row["rcNo"]),
        "rank": str(row["rank"]),
        "horse_id": official_id(row.get("hrNo"), 7),
        "horse_number": int(row["chulNo"]) if str(row.get("chulNo") or "").isdigit() else None,
        "hrNo": official_id(row.get("hrNo"), 7),
        "trNo": official_id(row.get("trNo"), 6),
        "owNo": official_id(row.get("owNo"), 6),
        "raw_ids": {key: row.get(key) for key in ("hrNo", "trNo", "owNo")},
        "names": {key: row.get(key) for key in ("hrName", "trName", "owName")},
        "evidence": evidence,
    }


def old_sources(root: Path) -> tuple[list[dict], list[dict]]:
    items, checks = [], []
    for year in range(2002, 2015):
        path = root / f"native_results_{year}.jsonl"
        manifest_path = root / f"native_results_{year}.manifest.json"
        blob = path.read_bytes()
        manifest = json.loads(manifest_path.read_text())
        file_hash = digest(blob)
        if file_hash != manifest["native_rows_sha256"]:
            raise ValueError(f"Old source hash mismatch: {path}")
        for line_no, line in enumerate(blob.splitlines(), 1):
            row = json.loads(line)
            if not str(row.get("rank") or "").startswith("제") or row.get("meet") != "제주":
                raise ValueError(f"Non-native old row: {path}:{line_no}")
            items.append(source_item(row, {"kind": "archived_api_row", "path": str(path),
                                           "line": line_no, "filtered_file_sha256": file_hash,
                                           "original_response_sha256": [p["sha256"] for p in manifest["source_pages"]]}))
        checks.append({"year": year, "path": str(path), "sha256": file_hash,
                       "rows": len(blob.splitlines()), "source_pages": manifest["source_pages"]})
    return items, checks


def new_sources(output: Path) -> tuple[list[dict], list[dict]]:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("KRA service key unavailable")
    all_items, checks = [], []
    with KraApiClient(settings.data_go_kr_service_key.get_secret_value(),
                      base_url=settings.kra_api_base_url, timeout_seconds=90) as client:
        for year in range(2015, 2027):
            native, pages = [], []
            mixed_count = 0
            for page in client.iter_pages(
                endpoint=RACE_RESULT_WITH_SECTIONS_ENDPOINT,
                operation=RACE_RESULT_WITH_SECTIONS_OPERATION,
                public_params={"meet": 2, "rc_year": str(year), "_type": "json"},
                page_size=20_000, service_key_parameter="ServiceKey",
            ):
                body = response_body(page.payload)
                wrapped = body.get("items") or {}
                rows = wrapped.get("item") if isinstance(wrapped, dict) else None
                rows = [] if rows is None else [rows] if isinstance(rows, dict) else rows
                if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                    raise ValueError(f"Invalid API item structure {year}")
                mixed_count += len(rows)
                page_hash = digest(page.body)
                pages.append({"source_url_without_key": page.source_url, "sha256": page_hash,
                              "response_bytes": len(page.body), "status_code": page.status_code,
                              "requested_at_ms": page.requested_at_ms,
                              "retrieved_at_ms": page.retrieved_at_ms,
                              "total_count": int(body.get("totalCount") or 0), "returned_rows": len(rows)})
                for row in rows:
                    if not str(row.get("rank") or "").startswith("제"):
                        continue
                    race_date = int(row["rcDate"])
                    if race_date // 10000 != year or row.get("meet") != "제주":
                        raise ValueError(f"API ignored requested year/meet: {year}, {race_date}")
                    if race_date <= LAST:
                        native.append(row)
            if pages and mixed_count != pages[0]["total_count"]:
                raise ValueError(f"API row/total mismatch {year}: {mixed_count}")
            filtered_path = output / f"official_native_results_{year}.jsonl"
            write_jsonl(filtered_path, native)
            filtered_hash = digest(filtered_path.read_bytes())
            for line_no, row in enumerate(native, 1):
                all_items.append(source_item(row, {"kind": "new_api_row", "path": str(filtered_path),
                                                  "line": line_no, "filtered_file_sha256": filtered_hash,
                                                  "original_response_sha256": [p["sha256"] for p in pages]}))
            checks.append({"year": year, "filtered_path": str(filtered_path),
                           "filtered_sha256": filtered_hash, "native_rows": len(native),
                           "mixed_response_rows_not_persisted": mixed_count - len(native),
                           "source_pages": pages})
            print(json.dumps({"year": year, "native_rows": len(native), "response_rows": mixed_count}), flush=True)
    return all_items, checks


def db_entries(path: Path) -> list[dict]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    query = """SELECT r.id AS race_db_id, e.id AS entry_db_id, r.race_date_local,
               r.race_number, r.grade, e.horse_number, h.kra_horse_id,
               t.kra_trainer_id, o.kra_owner_id
        FROM race_entries e JOIN races r ON r.id=e.race_id
        JOIN racecourses c ON c.id=r.racecourse_id
        JOIN horses h ON h.id=e.horse_id
        LEFT JOIN trainers t ON t.id=e.trainer_id
        LEFT JOIN owners o ON o.id=e.owner_id
        WHERE c.kra_meet_code=2 AND r.race_date_local BETWEEN '2015-01-01' AND '2026-09-12'"""
    rows = [dict(row) for row in connection.execute(query)]
    connection.close()
    for row in rows:
        row["race_date"] = row.pop("race_date_local").replace("-", "")
        row["horse_id"] = row.pop("kra_horse_id")
        row["db_trNo"] = row.pop("kra_trainer_id")
        row["db_owNo"] = row.pop("kra_owner_id")
    return rows


def key(row: dict) -> tuple:
    return (2, row["race_date"], row["race_number"], row["horse_id"])


def race_key(row: dict) -> tuple:
    return (2, row["race_date"], row["race_number"])


def reconcile(sources: list[dict], db: list[dict]) -> tuple[list[dict], list[dict], list[dict], dict]:
    api_by_key, db_by_key = defaultdict(list), defaultdict(list)
    api_races, db_races = defaultdict(list), defaultdict(list)
    for row in sources:
        api_by_key[key(row)].append(row)
        api_races[race_key(row)].append(row)
    for row in db:
        db_by_key[key(row)].append(row)
        db_races[race_key(row)].append(row)
    joined, unresolved, excluded = [], [], []
    for natural_key in sorted(api_by_key):
        candidates = api_by_key[natural_key]
        db_candidates = db_by_key.get(natural_key, [])
        api = candidates[0]
        record = {k: api[k] for k in ("meet", "race_date", "race_number", "rank", "horse_id", "horse_number", "raw_ids", "names", "evidence")}
        record["db_entry_id"] = db_candidates[0]["entry_db_id"] if len(db_candidates) == 1 else None
        record["db_values"] = {k: db_candidates[0][k] for k in ("grade", "horse_number", "horse_id", "db_trNo", "db_owNo")} if len(db_candidates) == 1 else None
        issues = []
        if len(candidates) != 1:
            issues.append("duplicate_official_key")
            record["all_official_candidates"] = [
                {"raw_ids": a["raw_ids"], "evidence": a["evidence"]} for a in candidates]
        if len(db_candidates) > 1:
            issues.append("duplicate_db_key")
        if api["horse_id"] is None:
            issues.append("missing_official_horse_id")
        if api["horse_number"] is None:
            issues.append("missing_official_horse_number")
        if len(db_candidates) == 0 and int(api["race_date"][:4]) >= 2015:
            issues.append("official_row_absent_from_db")
        if len(db_candidates) == 1 and api["horse_number"] != db_candidates[0]["horse_number"]:
            issues.append("horse_number_mismatch")
        official = {field: api[field] for field in ("hrNo", "trNo", "owNo")}
        if len(candidates) != 1 or len(db_candidates) > 1 or "horse_number_mismatch" in issues:
            official = {field: None for field in official}
        else:
            for field in ("hrNo", "trNo", "owNo"):
                if official[field] is None:
                    issues.append(f"missing_official_{field}")
            if len(db_candidates) == 1:
                for field, db_field in (("trNo", "db_trNo"), ("owNo", "db_owNo")):
                    value = db_candidates[0][db_field]
                    if value and not value.startswith("text:") and official[field] and value != official[field]:
                        issues.append(f"conflicting_{field}")
                        official[field] = None
        record["linked_official_ids"] = official
        record["issues"] = issues
        record["status"] = "linked_full" if all(official.values()) and not issues else "unresolved" if issues else "linked_partial"
        joined.append(record)
        if issues or not all(official.values()):
            unresolved.append(record)
    for natural_key in sorted(db_by_key.keys() - api_by_key.keys()):
        for row in db_by_key[natural_key]:
            if race_key(row) in api_races:
                reason = "db_row_absent_from_official_native_race"
            elif str(row["grade"]).startswith("제"):
                reason = "db_native_grade_race_absent_from_official_native_api"
            else:
                reason = "db_horse_type_unconfirmed"
            entry = {"meet": 2, "race_date": row["race_date"], "race_number": row["race_number"],
                     "horse_id": row["horse_id"], "horse_number": row["horse_number"],
                     "db_entry_id": row["entry_db_id"], "db_grade": row["grade"],
                     "db_trNo": row["db_trNo"], "db_owNo": row["db_owNo"], "issue": reason,
                     "official_same_number_candidates": [
                         {"horse_id": a["horse_id"], "evidence": a["evidence"]}
                         for a in api_races.get(race_key(row), []) if a["horse_number"] == row["horse_number"]]}
            if reason == "db_horse_type_unconfirmed":
                excluded.append(entry)
            else:
                unresolved.append(entry)
    metrics = {
        "source_rows": len(sources), "source_races": len(api_races), "db_rows": len(db),
        "db_races": len(db_races), "joined_rows": len(joined),
        "matched_db_rows": sum(bool(r["db_entry_id"]) for r in joined),
        "linked_full_rows": sum(r["status"] == "linked_full" for r in joined),
        "linked_partial_rows": sum(r["status"] == "linked_partial" for r in joined),
        "unresolved_source_rows": sum(r["status"] == "unresolved" for r in joined),
        "excluded_unconfirmed_db_rows": len(excluded),
        "issue_counts": dict(Counter(issue for row in joined for issue in row["issues"]) +
                             Counter(row["issue"] for row in unresolved if "issue" in row)),
    }
    return joined, unresolved, excluded, metrics


def coverage(joined: list[dict], db: list[dict]) -> list[dict]:
    by_year = defaultdict(list)
    for row in joined:
        by_year[int(row["race_date"][:4])].append(row)
    db_by_year = defaultdict(list)
    for row in db:
        db_by_year[int(row["race_date"][:4])].append(row)
    result = []
    for year in range(2002, 2027):
        rows, db_rows = by_year[year], db_by_year[year]
        matched = [r for r in rows if r["db_entry_id"] is not None]
        full = [r for r in rows if r["status"] == "linked_full"]
        result.append({"year": year, "confirmed_native_races": len({race_key(r) for r in rows}),
                       "confirmed_native_rows": len(rows), "three_official_ids_linked": len(full),
                       "official_id_link_rate": round(len(full) / len(rows), 6) if rows else None,
                       "db_races": len({race_key(r) for r in db_rows}), "db_rows": len(db_rows),
                       "matched_race_keys": len({race_key(r) for r in rows} & {race_key(r) for r in db_rows}),
                       "matched_entry_keys": len(matched),
                       "db_entry_key_coverage": round(len(matched) / len(db_rows), 6) if db_rows else None,
                       "confirmed_race_key_coverage": round(len({race_key(r) for r in rows} & {race_key(r) for r in db_rows}) /
                                                            len({race_key(r) for r in rows}), 6) if rows and db_rows else None})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("data/horse_racing.sqlite3"))
    parser.add_argument("--old-source", type=Path, default=Path("data/raw/jeju_native_results"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    old, old_checks = old_sources(args.old_source)
    new, new_checks = new_sources(args.output)
    db = db_entries(args.database)
    joined, unresolved, excluded, metrics = reconcile(old + new, db)
    write_jsonl(args.output / "race_time_official_id_links.jsonl", joined)
    write_jsonl(args.output / "unresolved_rows.jsonl", unresolved)
    write_jsonl(args.output / "unconfirmed_db_rows.jsonl", excluded)
    write_json(args.output / "annual_coverage.json", coverage(joined, db))
    write_json(args.output / "source_requests_and_hashes.json", {"old_sources": old_checks, "new_api_requests": new_checks})
    checks = {"period": {"first": FIRST, "last": LAST}, "metrics": metrics,
              "input_database": {"path": str(args.database), "sha256": digest(args.database.read_bytes())},
              "outputs": {p.name: digest(p.read_bytes()) for p in args.output.iterdir() if p.is_file()},
              "rules": ["Only official rank beginning 제 is retained", "No name-based ID inference",
                        "No current-profile trainer or owner backfill", "Source row identity is meet/date/race/horse ID; horse number is checked"]}
    write_json(args.output / "validation.json", checks)
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
