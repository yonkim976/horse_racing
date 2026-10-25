"""Apply the user-approved historical jockey-role supplement without editing raw roles."""
import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from apply_display_rule import CORE, DB, MANIFEST, ROOT, domain_lock, recover_pending, save, sha
from role_supplement_v2 import create_table_sql, populate_table_sql, create_display_view_sql

HERE = Path(__file__).resolve().parent
NAME = 'daily_training_rider_role_supplement_v2'
TABLE = 'daily_training_rider_role_supplements'
ELIGIBLE = 'inferred_jockey_by_official_id_and_profile_period'
HOLD = 'profile_period_boundary_hold'


def raw_signature(con):
    return con.execute("SELECT COUNT(*),BIT_XOR(HASH(observation_id,raw_payload_json,typed_fields_json,rider_type_raw,rider_id_raw)) FROM daily_training_raw").fetchone()


def main(apply):
    with domain_lock():
        recover_pending()
        manifest = json.loads(MANIFEST.read_text())
        c = duckdb.connect(str(DB), read_only=True)
        if c.execute('SELECT COUNT(*) FROM source_manifests WHERE name=?', [NAME]).fetchone()[0]:
            assert c.execute('SELECT COUNT(*) FROM daily_training_rider_role_supplements').fetchone()[0] == 293211
            c.close()
            assert sha(DB) == manifest['database_sha256']
            print(json.dumps({'status': 'already_applied', 'database_sha256': manifest['database_sha256']}))
            return
        tables = c.execute("SELECT table_name,sql FROM duckdb_tables() WHERE schema_name='main' ORDER BY 1").fetchall()
        views = dict(c.execute("SELECT view_name,sql FROM duckdb_views() WHERE schema_name='main' AND NOT internal").fetchall())
        source_rows = c.execute('SELECT name,json_text FROM source_manifests ORDER BY 1,2').fetchall()
        raw_before = raw_signature(c)
        c.close()
        original_db_sha, original_manifest_sha = sha(DB), sha(MANIFEST)
        assert manifest['database_sha256'] == original_db_sha
        stage, stage_manifest = HERE / 'role_v2_staged.duckdb', HERE / 'role_v2_staged_manifest.json'
        stage.unlink(missing_ok=True)
        subprocess.run(['/bin/cp', '-c', str(DB), str(stage)], check=True)
        original_view = views['daily_training_rider_display']
        before_sql_file = HERE / 'display_before_role_v2.sql'
        before_sql_file.write_text(original_view + '\n')
        sql = '\n\n'.join((create_table_sql(), populate_table_sql(), create_display_view_sql(original_view)))
        sql_file = HERE / 'role_supplement_v2.sql'
        sql_file.write_text(sql + '\n')
        policy = {'name': NAME, 'authorized_eligible_rows': 293200, 'authorized_hold_rows': 11,
                  'raw_role_unchanged': True, 'supplement_is_inferred_not_original': True,
                  'scope': 'Existing 293211 observations with raw role -, exact API307 identity link, and nonempty linked name',
                  'period_rule': 'event_date >= profile start and (profile end is NULL or event_date <= profile end)',
                  'unknown_role_date_boundary_records_remain_unconfirmed': True}
        policy_file = HERE / 'role_supplement_v2_policy.json'
        save(policy_file, policy)
        inputs = [{'table': NAME, 'path': path.relative_to(ROOT).as_posix(), 'sha256': sha(path), 'rows': None}
                  for path in (Path(__file__), HERE / 'role_supplement_v2.py', before_sql_file, sql_file, policy_file)]
        c = duckdb.connect(str(stage))
        try:
            c.execute('BEGIN')
            c.execute(create_table_sql())
            c.execute(populate_table_sql())
            partition = dict(c.execute('SELECT role_supplement_status,COUNT(*) FROM daily_training_rider_role_supplements GROUP BY 1').fetchall())
            assert partition == {ELIGIBLE: 293200, HOLD: 11}, partition
            assert c.execute("SELECT COUNT(*) FROM daily_training_rider_role_supplements s JOIN daily_training_rider_linked d USING(observation_id) WHERE d.rider_type_raw<>'-' OR d.rider_identity_status<>'exact_official_profile_id_name_link' OR d.rider_name_linked IS NULL").fetchone()[0] == 0
            assert c.execute("SELECT COUNT(*) FROM daily_training_rider_role_supplements WHERE role_supplement_status=? AND role_supplement<>'기수'", [ELIGIBLE]).fetchone()[0] == 0
            assert c.execute("SELECT COUNT(*) FROM daily_training_rider_role_supplements WHERE role_supplement_status=? AND role_supplement IS NOT NULL", [HOLD]).fetchone()[0] == 0
            c.execute(create_display_view_sql(original_view))
            counts = dict(c.execute('SELECT rider_display_kind,COUNT(*) FROM daily_training_rider_display GROUP BY 1').fetchall())
            assert counts == {'person_name': 1599307, 'role': 1955322, 'unknown': 1618404}, counts
            assert c.execute("SELECT COUNT(*) FROM daily_training_rider_display WHERE rider_role_supplement_status=? AND rider_type_raw='-' AND rider_type_effective='기수' AND rider_display_value=rider_name_linked AND rider_display_kind='person_name'", [ELIGIBLE]).fetchone()[0] == 293200
            assert c.execute("SELECT COUNT(*) FROM daily_training_rider_display WHERE rider_role_supplement_status=? AND rider_type_raw='-' AND rider_display_kind='unknown' AND rider_role_supplement IS NULL AND rider_type_effective IS NULL", [HOLD]).fetchone()[0] == 11
            assert c.execute("SELECT COUNT(*) FROM daily_training_rider_display WHERE rider_identity_status='source_conflict_hold' AND rider_name_linked IS NULL AND rider_display_value='기수'").fetchone()[0] == 1
            assert c.execute("SELECT COUNT(*) FROM daily_training_rider_display WHERE rider_id_raw='080626' AND rider_display_value='다비드' AND rider_role_supplement_status IS NULL").fetchone()[0] == 31
            assert c.execute('SELECT COUNT(*) FROM rider_unmatched_ids').fetchone()[0] == 70
            assert c.execute("SELECT COUNT(*) FROM daily_training_rider_display WHERE meet NOT IN ('1','3','4')").fetchone()[0] == 0
            assert raw_signature(c) == raw_before
            new_tables = dict(c.execute("SELECT table_name,sql FROM duckdb_tables() WHERE schema_name='main'").fetchall())
            assert set(new_tables) == {name for name, _ in tables} | {TABLE}
            assert all(new_tables[name] == definition for name, definition in tables)
            new_views = dict(c.execute("SELECT view_name,sql FROM duckdb_views() WHERE schema_name='main' AND NOT internal").fetchall())
            assert set(new_views) == set(views)
            assert all(new_views[name] == definition for name, definition in views.items() if name != 'daily_training_rider_display')
            assert c.execute('SELECT name,json_text FROM source_manifests ORDER BY 1,2').fetchall() == source_rows
            proof_json = c.execute('SELECT DISTINCT profile_evidence_json FROM daily_training_rider_role_supplements').fetchall()
            verified_profile_files = {}
            for (value,) in proof_json:
                evidence = json.loads(value)
                if isinstance(evidence, dict):
                    evidence = [evidence]
                for profile in evidence:
                    relative = profile['source_file']
                    target = (ROOT / relative).resolve()
                    assert target.is_relative_to(ROOT)
                    if relative not in verified_profile_files:
                        assert sha(target) == profile['source_sha256']
                        verified_profile_files[relative] = profile['source_sha256']
            held = c.execute("SELECT d.observation_id,d.event_date,d.rider_id_raw,d.rider_name_linked,d.horse_name_raw,s.profile_start_date,s.profile_end_date FROM daily_training_rider_display d JOIN daily_training_rider_role_supplements s USING(observation_id) WHERE s.role_supplement_status=? ORDER BY d.event_date,d.observation_id", [HOLD]).fetchall()
            source = policy | {'applied_at_utc': datetime.now(timezone.utc).isoformat(), 'baseline_database_sha256': original_db_sha,
                               'input_files': inputs, 'verified_profile_files': verified_profile_files, 'display_counts': counts}
            c.execute('INSERT INTO source_manifests VALUES (?,?)', [NAME, json.dumps(source, ensure_ascii=False, sort_keys=True)])
            c.execute('COMMIT')
        except Exception:
            c.execute('ROLLBACK')
            raise
        finally:
            c.close()
        after_sha = sha(stage)
        backup = CORE / 'backups/20261017_before_rider_role_supplement'
        manifest['database_sha256'] = after_sha
        manifest['input_files'].extend(inputs)
        manifest['table_and_view_counts'].update({TABLE: 293211, 'daily_training_rider_display': 5173033, 'source_manifests': len(source_rows) + 1})
        manifest['checks']['daily_training_rider_role_supplement_v2_verified'] = True
        manifest['supplement_loads'].append({'name': NAME, 'applied_at_utc': source['applied_at_utc'],
            'baseline_database_sha256': original_db_sha, 'database_sha256_after': after_sha,
            'backup_database': (backup / DB.name).relative_to(ROOT).as_posix(),
            'backup_manifest': (backup / MANIFEST.name).relative_to(ROOT).as_posix(),
            'source_manifest_name': NAME, 'supplement_rows': 293200, 'held_rows': 11})
        save(stage_manifest, manifest)
        report = {'status': 'dry_run_passed', 'active_database_written': False, 'supplement_rows': 293200,
                  'held_rows': 11, 'display_counts': counts, 'raw_rows_and_values_preserved': True,
                  'all_existing_tables_and_other_views_preserved': True, 'profile_files_verified': len(verified_profile_files),
                  'baseline_database_sha256': original_db_sha, 'baseline_manifest_sha256': original_manifest_sha,
                  'database_sha256_after': after_sha, 'held_observations': held, 'backup': backup.relative_to(ROOT).as_posix()}
        if apply:
            assert sha(DB) == original_db_sha and sha(MANIFEST) == original_manifest_sha
            backup.mkdir(exist_ok=True)
            for path, digest in ((DB, original_db_sha), (MANIFEST, original_manifest_sha)):
                target = backup / path.name
                if not target.exists():
                    subprocess.run(['/bin/cp', '-c', str(path), str(target)], check=True)
                assert sha(target) == digest
            save(backup / 'attestation.json', {'status': 'verified_equal', 'database_sha256': original_db_sha, 'manifest_sha256': original_manifest_sha})
            expected_manifest_sha = sha(stage_manifest)
            save(CORE / 'refresh_apply_pending.json', {'run_id': NAME, 'baseline_database_sha256': original_db_sha,
                 'database_sha256_after': after_sha, 'manifest_sha256_after': expected_manifest_sha,
                 'staged_database': stage.relative_to(ROOT).as_posix(), 'staged_manifest': stage_manifest.relative_to(ROOT).as_posix(),
                 'backup': backup.relative_to(ROOT).as_posix()})
            os.replace(stage, DB)
            os.replace(stage_manifest, MANIFEST)
            assert sha(DB) == after_sha and sha(MANIFEST) == expected_manifest_sha
            assert json.loads(MANIFEST.read_text())['database_sha256'] == after_sha
            (CORE / 'refresh_apply_pending.json').unlink()
            report.update(status='applied_and_verified', active_database_written=True, manifest_sha256_after=sha(MANIFEST))
        save(HERE / ('role_v2_apply_report.json' if apply else 'role_v2_dry_run_report.json'), report)
        print(json.dumps({key: value for key, value in report.items() if key != 'held_observations'}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--apply', action='store_true')
    modes.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    main(args.apply)
