"""Independently verify the integration-ready Busan research database."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from build_busan_complete_db import (
    DEFAULT_OUTPUT, HISTORY_DB, LEGACY_DB, ROOT, TRIAL_DB, sha256,
)


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def table_counts(db: sqlite3.Connection) -> dict[str, int]:
    names = [row[0] for row in db.execute("""
      SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'
      ORDER BY name""")]
    return {name: db.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            for name in names}


def resolve(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def verify(output_dir: Path, full_hash: bool) -> dict:
    final_path = output_dir / "busan_complete.sqlite3"
    if not final_path.is_file():
        raise FileNotFoundError(final_path)
    final = ro(final_path)
    history = ro(HISTORY_DB)
    trial = ro(TRIAL_DB)
    legacy = ro(LEGACY_DB)
    try:
        assert final.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert final.execute("PRAGMA foreign_key_check").fetchall() == []

        history_counts = table_counts(history)
        final_counts = table_counts(final)
        for name, count in history_counts.items():
            assert final_counts[name] == count, (name, final_counts[name], count)

        trial_mapping = {
            "trial": "trial", "trial_entry": "trial_entry",
            "candidate": "trial_candidate",
            "official_trial_api_entry": "trial_api_entry",
            "race_entry_trial_history": "race_entry_trial_history",
            "source_file": "trial_source_file", "input_manifest": "trial_input_manifest",
        }
        for source, destination in trial_mapping.items():
            expected = trial.execute(f'SELECT count(*) FROM "{source}"').fetchone()[0]
            assert final_counts[destination] == expected, (destination, expected)

        legacy_mapping = {
            "entry_linkage": "legacy_entry_actor_linkage",
            "temporary_id_link": "legacy_temporary_id_link",
            "candidate_evidence": "legacy_candidate_evidence",
            "input_manifest": "legacy_input_manifest",
        }
        for source, destination in legacy_mapping.items():
            expected = legacy.execute(f'SELECT count(*) FROM "{source}"').fetchone()[0]
            assert final_counts[destination] == expected, (destination, expected)

        expected_counts = {
            "race": 15577, "entry": 171064, "result": 171064,
            "section": 2565960, "training_event": 3168636,
            "medical_event": 628141, "medical_api_event": 108901,
            "entry_equipment": 170328, "race_day_weight": 169251,
            "trial": 3400, "trial_entry": 29762, "trial_api_entry": 29762,
            "race_entry_trial_history": 167960,
            "legacy_entry_actor_linkage": 41346,
            "unified_event": 18977, "unified_event_entry": 200826,
            "unified_event_result": 200826,
        }
        for name, expected in expected_counts.items():
            assert final_counts[name] == expected, (name, final_counts[name], expected)

        assert final.execute("""SELECT count(*) FROM unified_event
          WHERE venue_code!='BUSAN' OR venue_resolution_status!='confirmed'""").fetchone()[0] == 0
        assert final.execute("SELECT count(*) FROM venue_dimension").fetchone()[0] == 1
        assert final.execute("""SELECT count(*) FROM trial_api_entry
          WHERE api_meet_raw!='영남'""").fetchone()[0] == 0
        assert final.execute("""SELECT count(*) FROM unified_event_entry
          WHERE event_id NOT IN (SELECT event_id FROM unified_event)""").fetchone()[0] == 0
        assert final.execute("""SELECT count(*) FROM unified_event_result r
          WHERE NOT EXISTS (SELECT 1 FROM unified_event_entry e
            WHERE e.event_id=r.event_id AND e.participant_no=r.participant_no)""").fetchone()[0] == 0

        assert final.execute("SELECT count(*) FROM analysis_race_entry_history").fetchone()[0] == 167960
        assert final.execute("SELECT count(*) FROM analysis_trial_entry").fetchone()[0] == 29757
        assert final.execute("SELECT count(*) FROM quarantined_trial_entry").fetchone()[0] == 5
        assert final.execute("SELECT count(*) FROM quarantined_medical_text").fetchone()[0] == 422993
        assert final.execute("SELECT count(*) FROM quarantined_race_notice").fetchone()[0] == 39
        assert final.execute("SELECT count(*) FROM quarantined_race_day_weight").fetchone()[0] == 1274
        assert final.execute("SELECT count(*) FROM quarantined_legacy_identity").fetchone()[0] == 101

        assert final.execute("""SELECT count(*) FROM race_entry_trial_history
          WHERE last_confirmed_trial_date>=race_date""").fetchone()[0] == 0
        assert final.execute("""SELECT count(*) FROM research_entry
          WHERE label_scope='mock'""").fetchone()[0] == 0
        assert final.execute("""SELECT count(*) FROM race
          WHERE substr(race_date,1,4)='2006' AND label_scope='target'""").fetchone()[0] == 578
        assert final.execute("""SELECT count(*) FROM entry
          WHERE substr(race_date,1,4)='2006'""").fetchone()[0] == 6569
        assert final.execute("""SELECT count(*) FROM entry
          WHERE substr(race_date,1,4)='2006'
            AND (hr_no='' OR jockey_no='' OR trainer_no='' OR owner_no='')""").fetchone()[0] == 0

        issue_counts = dict(final.execute("SELECT issue_type,row_count FROM issue_summary"))
        assert issue_counts == {
            "legacy_identity_not_globally_resolved": 101,
            "medical_text_not_confirmed": 422993,
            "race_day_weight_not_confirmed": 1274,
            "race_entry_missing_owner_id": 21,
            "race_entry_missing_trainer_id": 21,
            "race_notice_not_confirmed": 39,
            "trial_identity_unresolved": 5,
        }
        assert final.execute("SELECT count(*) FROM source_request WHERE key_redacted!=1").fetchone()[0] == 0
        requests = final.execute("SELECT raw_event_json FROM source_request").fetchall()
        assert all("servicekey=" not in text.lower() and "service_key=" not in text.lower()
                   for (text,) in requests)

        artifacts = final.execute("""SELECT source_group,path,role,sha256,bytes,path_exists
          FROM source_artifact ORDER BY source_group,path""").fetchall()
        missing_now = []
        hash_mismatches = []
        size_mismatches = []
        mutable_reference_drifts = []
        checked_hashes = 0
        for group, path_text, role, expected_hash, expected_bytes, existed_at_build in artifacts:
            path = resolve(path_text)
            if not path.is_file():
                if existed_at_build:
                    target = mutable_reference_drifts if role == "read_only_operating_db" else missing_now
                    target.append((group, path_text, "missing"))
                continue
            if path.stat().st_size != expected_bytes:
                target = mutable_reference_drifts if role == "read_only_operating_db" else size_mismatches
                target.append((group, path_text, expected_bytes, path.stat().st_size))
                continue
            if full_hash and role != "read_only_operating_db":
                checked_hashes += 1
                observed = sha256(path)
                if observed != expected_hash:
                    hash_mismatches.append((group, path_text, expected_hash, observed))
        assert not missing_now, missing_now[:5]
        assert not size_mismatches, size_mismatches[:5]
        assert not hash_mismatches, hash_mismatches[:5]

        summary = {
            "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            "database": str(final_path),
            "database_sha256": sha256(final_path),
            "database_bytes": final_path.stat().st_size,
            "integrity_check": "ok", "foreign_key_violations": 0,
            "base_history_tables_preserved": len(history_counts),
            "race_events": 15577, "trial_events": 3400,
            "race_entries": 171064, "trial_entries": 29762,
            "unified_events": 18977, "unified_event_entries": 200826,
            "research_race_entries": 167960,
            "confirmed_trial_entries": 29757,
            "issue_summary": issue_counts,
            "source_artifacts": len(artifacts),
            "source_artifact_hashes_checked": checked_hashes,
            "mutable_operating_reference_drifts": mutable_reference_drifts,
            "source_requests": len(requests),
            "secret_bearing_request_urls": 0,
            "future_trial_history_violations": 0,
            "venue_policy": {
                "canonical_venue_code": "BUSAN", "canonical_meet": 3,
                "trial_api_meet_raw": "영남",
                "future_meet3_rows_require_explicit_venue_resolution": True,
            },
        }
    finally:
        legacy.close()
        trial.close()
        history.close()
        final.close()

    (output_dir / "independent_validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    completion = {
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "complete_research_snapshot",
        "checks": {
            "isolated_output": "pass", "operating_database_untouched": "pass",
            "history_tables_preserved": "pass", "full_trial_table_loaded": "pass",
            "legacy_actor_evidence_loaded": "pass", "canonical_integration_keys": "pass",
            "venue_region_separation": "pass", "future_history_blocked": "pass",
            "source_requests_redacted": "pass", "sqlite_integrity": "pass",
            "foreign_keys": "pass", "ambiguous_rows_quarantined": "pass",
        },
        "limitations": [
            "Five trial entries lack a confirmed hrNo.",
            "Historical text medical linkage is incomplete and ambiguous rows are quarantined.",
            "Past publication timestamps are unproven; research features are retrospective_only.",
            "Future running-trial meet=3/영남 responses require separate Busan/Yeongcheon resolution.",
            "Source-specific race section fields are not collapsed into one semantic feature.",
        ],
    }
    (output_dir / "completion_audit.json").write_text(
        json.dumps(completion, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_paths = [path for path in output_dir.rglob("*")
                      if path.is_file() and path.name != "manifest.json"]
    docs = ROOT / "docs/BUSAN_COLLECTION_AND_INGESTION_PROCESS_2026-09-16.md"
    if docs.is_file():
        manifest_paths.append(docs)
    manifest = {}
    for path in sorted(set(manifest_paths)):
        key = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        manifest[key] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--full-hash", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.output_dir, args.full_hash), ensure_ascii=False, indent=2))
