"""Remove confirmed replayed API4_3 rows from the Jeju result layer.

The immutable api_records rows and archived response page remain for audit.
The deleted normalized rows are exported before the transaction commits.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
OUTPUT = ROOT / "jeju/maintenance/zero_time_cleanup_20260930"
BACKUP = OUTPUT / "deleted_race_result_rows.jsonl"
REPORT = OUTPUT / "cleanup_report.json"
EXPECTED_COUNTS = {"2026-07-07": 40, "2026-08-25": 75, "2026-08-26": 67}
SOURCE_PAGE_SHA256 = "8f60ee195eff36cb2f4bd0620fd4db0e30ac2b17618c0b7bbfc1b144a2eb4006"
DATES = tuple(EXPECTED_COUNTS)
TARGET_SQL = "meet_code=2 AND race_date IN (?,?,?)"


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "race_result_rows": conn.execute("SELECT count(*) FROM race_result_rows").fetchone()[0],
        "candidate_rows": conn.execute("SELECT count(*) FROM jeju_race_population_candidates").fetchone()[0],
        "candidate_races": conn.execute(
            "SELECT count(*) FROM (SELECT race_date,race_number FROM jeju_race_population_candidates GROUP BY 1,2)"
        ).fetchone()[0],
        "api_records": conn.execute("SELECT count(*) FROM api_records").fetchone()[0],
    }


def main() -> None:
    if BACKUP.exists() or REPORT.exists():
        raise FileExistsError("Cleanup snapshot or report already exists; refusing a second deletion")
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        conn.execute("BEGIN IMMEDIATE")
        before = counts(conn)
        rows = conn.execute(
            f"SELECT * FROM race_result_rows WHERE {TARGET_SQL} ORDER BY race_date,race_number,horse_number,api_record_id",
            DATES,
        ).fetchall()
        by_date = Counter(row["race_date"] for row in rows)
        if dict(by_date) != EXPECTED_COUNTS:
            raise ValueError(f"Unexpected target rows: {dict(by_date)}")
        if any((row["finish_time_seconds"] or 0) <= 0 for row in rows if row["race_date"] == "2026-07-07"):
            raise ValueError("July 7 replay rows no longer all have positive finish times")
        if any((row["finish_time_seconds"] or 0) != 0 for row in rows if row["race_date"] != "2026-07-07"):
            raise ValueError("August replay rows no longer all have zero finish times")
        source_rows = conn.execute(
            f"""SELECT count(*) AS n,count(DISTINCT s.sha256) AS sha_count,min(s.sha256) AS sha
                FROM race_result_rows r JOIN api_records a USING(api_record_id)
                JOIN source_artifacts s USING(source_artifact_id)
                WHERE r.{TARGET_SQL}""",
            DATES,
        ).fetchone()
        if tuple(source_rows) != (182, 1, SOURCE_PAGE_SHA256):
            raise ValueError(f"Unexpected source page identity: {tuple(source_rows)}")

        OUTPUT.mkdir(parents=True, exist_ok=True)
        with BACKUP.open("x", encoding="utf-8") as backup:
            for row in rows:
                backup.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")
            backup.flush()
            os.fsync(backup.fileno())
        backup_sha256 = hashlib.sha256(BACKUP.read_bytes()).hexdigest()

        deleted = conn.execute(f"DELETE FROM race_result_rows WHERE {TARGET_SQL}", DATES).rowcount
        if deleted != 182:
            raise ValueError(f"Unexpected deleted row count: {deleted}")
        after = counts(conn)
        if after["race_result_rows"] != before["race_result_rows"] - 182:
            raise ValueError("Race result row count did not decrease by 182")
        if after["candidate_rows"] != before["candidate_rows"] - 182:
            raise ValueError("Candidate row count did not decrease by 182")
        if after["candidate_races"] != before["candidate_races"] - 19:
            raise ValueError("Candidate race count did not decrease by 19")
        if after["api_records"] != before["api_records"]:
            raise ValueError("Immutable API records changed")
        if conn.execute(f"SELECT count(*) FROM race_result_rows WHERE {TARGET_SQL}", DATES).fetchone()[0]:
            raise ValueError("Target result rows remain")
        conn.commit()

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        report = {
            "scope": "Jeju API4_3 normalized race_result_rows only",
            "deleted_by_date": dict(by_date),
            "deleted_rows": deleted,
            "deleted_races": 19,
            "source_page_sha256": SOURCE_PAGE_SHA256,
            "normalized_backup": str(BACKUP.relative_to(ROOT)),
            "normalized_backup_sha256": backup_sha256,
            "before": before,
            "after": after,
            "integrity_check": integrity,
            "foreign_key_issues": len(fk_issues),
            "api_records_and_raw_source_retained": True,
        }
        with REPORT.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
        if integrity != "ok" or fk_issues:
            raise RuntimeError(f"Post-delete database check failed: integrity={integrity}, foreign_keys={len(fk_issues)}")
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
