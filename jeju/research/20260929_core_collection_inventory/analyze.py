"""Read-only inventory of existing Jeju-native race and trial source layers."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PHASE2_DB = ROOT / "data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3"
OPERATIONAL_DB = ROOT / "data/horse_racing.sqlite3"
SCORE_DIR = ROOT / "data/research"


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def date_display(value: str | None) -> str | None:
    if value is None:
        return None
    value = str(value)
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 else value


def sqlite_file(path: Path) -> dict:
    stat = path.stat()
    return {"path": str(path.relative_to(ROOT)), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def main() -> None:
    result_years: list[dict] = []
    trial_years: list[dict] = []
    with ro(PHASE2_DB) as conn:
        scope_raw = conn.execute("SELECT value_json FROM metadata WHERE key='scope'").fetchone()[0]
        text_scope_raw = conn.execute(
            "SELECT value_json FROM metadata WHERE key='text_phase2_scope'"
        ).fetchone()[0]
        result_rows = conn.execute(
            """
            SELECT substr(ev.event_date,1,4) AS year,
                   COUNT(DISTINCT ev.id) AS races,
                   COUNT(en.id) AS entries,
                   SUM(en.record_status='normal_completed') AS normal_completed,
                   SUM(en.record_status='non_positive_result_entry') AS non_positive_entry,
                   SUM(en.record_status='quarantined_no_positive_result_race') AS quarantined,
                   MIN(ev.event_date), MAX(ev.event_date)
            FROM event ev LEFT JOIN entry en ON en.event_id=ev.id
            WHERE ev.event_type='race' AND ev.meet=2
            GROUP BY 1 ORDER BY 1
            """
        ).fetchall()
        for row in result_rows:
            result_years.append({
                "year": int(row[0]), "races": row[1], "entries": row[2],
                "normal_completed_entries": row[3] or 0,
                "non_positive_result_entries": row[4] or 0,
                "entries_in_quarantined_no_positive_races": row[5] or 0,
                "first_date": date_display(row[6]), "last_date": date_display(row[7]),
            })
        trial_rows = conn.execute(
            """
            SELECT substr(ev.event_date,1,4) AS year,
                   COUNT(DISTINCT ev.id) AS candidate_trial_events,
                   COUNT(en.id) AS candidate_entries,
                   SUM(en.identity_status='official_trial_hr_tr_linked') AS official_hr_no_linked,
                   SUM(en.identity_status='official_trial_identity_unresolved') AS unresolved_identity,
                   SUM(en.breed_status='native_confirmed') AS native_confirmed_breed,
                   SUM(en.breed_status!='native_confirmed') AS breed_unconfirmed,
                   MIN(ev.event_date), MAX(ev.event_date)
            FROM event ev JOIN entry en ON en.event_id=ev.id
            WHERE ev.event_type='trial' AND ev.meet=2
            GROUP BY 1 ORDER BY 1
            """
        ).fetchall()
        for row in trial_rows:
            trial_years.append({
                "year": int(row[0]), "candidate_trial_events": row[1], "candidate_entries": row[2],
                "official_hr_no_linked": row[3] or 0, "unresolved_identity": row[4] or 0,
                "native_confirmed_breed": row[5] or 0, "breed_unconfirmed": row[6] or 0,
                "first_date": date_display(row[7]), "last_date": date_display(row[8]),
            })
        result_status = dict(conn.execute(
            "SELECT record_status, COUNT(*) FROM entry en JOIN event ev ON ev.id=en.event_id "
            "WHERE ev.event_type='race' AND ev.meet=2 GROUP BY record_status"
        ).fetchall())
        trial_status = dict(conn.execute(
            "SELECT identity_status, COUNT(*) FROM entry en JOIN event ev ON ev.id=en.event_id "
            "WHERE ev.event_type='trial' AND ev.meet=2 GROUP BY identity_status"
        ).fetchall())
        breed_status = dict(conn.execute(
            "SELECT breed_status, COUNT(*) FROM entry en JOIN event ev ON ev.id=en.event_id "
            "WHERE ev.event_type='trial' AND ev.meet=2 GROUP BY breed_status"
        ).fetchall())
        artifact_count = conn.execute("SELECT COUNT(*) FROM source_artifact").fetchone()[0]
        document_counts = conn.execute(
            "SELECT record_type, COUNT(*), MIN(event_date), MAX(event_date) "
            "FROM text_native_record GROUP BY record_type ORDER BY record_type"
        ).fetchall()
        role_and_core_fields = {}
        for field in ("hrNo", "jkNo", "trNo", "owNo", "rcDist", "rank", "budam", "track"):
            total, present = conn.execute(
                f"SELECT COUNT(*), SUM(json_extract(sr.normalized_json,'$.{field}') IS NOT NULL) "
                "FROM entry en JOIN event ev ON ev.id=en.event_id "
                "JOIN source_row sr ON sr.id=en.source_row_id "
                "WHERE ev.event_type='race' AND ev.meet=2"
            ).fetchone()
            role_and_core_fields[field] = {"rows": total, "present": present or 0}

    scorecard_years: list[dict] = []
    for year in range(2017, 2027):
        path = SCORE_DIR / f"jeju_{year}_score_20260925" / f"jeju_{year}.sqlite3"
        with ro(path) as conn:
            row = conn.execute(
                "SELECT COUNT(*), MIN(race_date), MAX(race_date) FROM race"
            ).fetchone()
            entries = conn.execute("SELECT COUNT(*) FROM entry").fetchone()[0]
            scorecard_years.append({
                "year": year, "races": row[0], "entries": entries,
                "first_date": row[1], "last_date": row[2],
                "source": str(path.relative_to(ROOT)),
            })

    with ro(OPERATIONAL_DB) as conn:
        op_jeju = conn.execute(
            "SELECT COUNT(*),MIN(race_date_local),MAX(race_date_local) FROM races WHERE racecourse_id=2"
        ).fetchone()
        op_recent = conn.execute(
            "SELECT COUNT(*),MIN(race_date_local),MAX(race_date_local) FROM races "
            "WHERE racecourse_id=2 AND race_date_local>'2026-09-12' AND race_date_local<='2026-09-19'"
        ).fetchone()
        op_recent_entry_rows = conn.execute(
            "SELECT COUNT(*) FROM race_entries e JOIN races r ON r.id=e.race_id "
            "WHERE r.racecourse_id=2 AND r.race_date_local>'2026-09-12' AND r.race_date_local<='2026-09-19'"
        ).fetchone()[0]

    report = {
        "as_of": "2026-09-29",
        "purpose": "read-only preflight; no ingestion into a new canonical DB, no model fitting, no source modification",
        "phase2_native_base": {
            **sqlite_file(PHASE2_DB),
            "source_artifact_rows": artifact_count,
            "recorded_scope": json.loads(scope_raw),
            "text_scope": json.loads(text_scope_raw),
            "native_race_years": result_years,
            "trial_candidate_years": trial_years,
            "race_record_status_totals": result_status,
            "trial_identity_status_totals": trial_status,
            "trial_breed_status_totals": breed_status,
            "official_result_field_coverage": role_and_core_fields,
            "native_text_record_types": [
                {"type": row[0], "rows": row[1], "first_date": row[2], "last_date": row[3]}
                for row in document_counts
            ],
        },
        "native_scorecard_dbs": scorecard_years,
        "operational_db_context_only": {
            **sqlite_file(OPERATIONAL_DB),
            "all_jeju_course_races": {
                "count": op_jeju[0], "first_date": op_jeju[1], "last_date": op_jeju[2],
                "warning": "meet/course scope only; not itself a Jeju-native filter",
            },
            "post_2026_09_12_to_09_19_course_races": {
                "count": op_recent[0], "entries": op_recent_entry_rows,
                "first_date": op_recent[1], "last_date": op_recent[2],
                "warning": "course-only availability; must reconcile against native scorecards and explicit breed evidence",
            },
        },
        "collection_gaps_to_close": [
            "Reconcile native results after the verified official-result cutoff 2026-09-12 through 2026-09-19.",
            "Reconcile Jeju-native running-trial sources after the saved text cutoff 2026-09-09 through 2026-09-19.",
            "Recover jockey IDs and event-time trainer/owner/jockey relations into a separate link ledger; do not infer identities from names alone.",
            "Keep resultless, non-positive, breed-unconfirmed, and unresolved-ID records with explicit statuses rather than deleting or fabricating labels.",
        ],
        "extension_collection_status": {
            "candidate_manifest": "jeju/research/20260929_core_collection_inventory/candidate_core_extension_20260913_19.manifest.json",
            "direct_official_api_attempt": "failed_dns_resolution; no API result bytes written by this run",
            "candidate_records": "held Jeju scorecard rows for 2026-09-13..2026-09-19 with exact operational entry ID and horse ID cross-check; still pending official reconciliation",
        },
    }
    out = Path(__file__).with_name("source_inventory.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out.relative_to(ROOT))


if __name__ == "__main__":
    main()
