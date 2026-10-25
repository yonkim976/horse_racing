"""Stage and safely register the approved rider display rule in the research DB."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'
DB, MANIFEST = CORE / 'thoroughbred_core.duckdb', CORE / 'manifest.json'
sys.path.insert(0, str(ROOT / 'thoroughbred/refresh'))
from common import domain_lock
from store import recover_pending
from display_rule import create_view_sql

NAME = 'daily_training_rider_display_v1'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def main(apply):
    with domain_lock():
        recover_pending()
        before = json.loads(MANIFEST.read_text())
        con = duckdb.connect(str(DB), read_only=True)
        already = con.execute('SELECT COUNT(*) FROM source_manifests WHERE name=?', [NAME]).fetchone()[0]
        if already:
            assert con.execute("SELECT COUNT(*) FROM duckdb_views() WHERE view_name='daily_training_rider_display'").fetchone()[0] == 1
            con.close()
            assert before['database_sha256'] == sha(DB)
            print(json.dumps({'status': 'already_applied', 'database_sha256': before['database_sha256']}))
            return
        old_tables = con.execute("SELECT table_name,sql FROM duckdb_tables() WHERE schema_name='main' ORDER BY 1").fetchall()
        old_views = con.execute("SELECT view_name,sql FROM duckdb_views() WHERE schema_name='main' AND NOT internal ORDER BY 1").fetchall()
        source_rows = con.execute('SELECT name,json_text FROM source_manifests ORDER BY 1,2').fetchall()
        con.close()
        baseline_sha, baseline_manifest_sha = sha(DB), sha(MANIFEST)
        assert before['database_sha256'] == baseline_sha
        stage, staged_manifest = HERE / 'display_staged.duckdb', HERE / 'display_staged_manifest.json'
        stage.unlink(missing_ok=True)
        subprocess.run(['/bin/cp', '-c', str(DB), str(stage)], check=True)
        sql = create_view_sql()
        sql_file = HERE / 'display_rule.sql'
        sql_file.write_text(sql + '\n')
        policy = {'name': NAME, 'policy': 'Only confirmed names with raw role 기수 are person-name displays; otherwise retain the raw role; unknown roles display 기승자 미상.',
                  'original_identity_columns_preserved': True, 'new_view': 'daily_training_rider_display',
                  'display_column': 'rider_display_value'}
        policy_file = HERE / 'display_policy.json'
        save(policy_file, policy)
        inputs = [{'table': NAME, 'path': path.relative_to(ROOT).as_posix(), 'sha256': sha(path), 'rows': None}
                  for path in (Path(__file__), HERE / 'display_rule.py', sql_file, policy_file)]
        captured_at = datetime.now(timezone.utc).isoformat()
        source = policy | {'applied_at_utc': captured_at, 'baseline_database_sha256': baseline_sha, 'input_files': inputs}
        con = duckdb.connect(str(stage))
        try:
            con.execute('BEGIN')
            con.execute(sql)
            counts = con.execute('SELECT rider_display_kind,COUNT(*) FROM daily_training_rider_display GROUP BY 1 ORDER BY 1').fetchall()
            total = sum(row[1] for row in counts)
            assert total == con.execute('SELECT COUNT(*) FROM daily_training_rider_linked').fetchone()[0]
            assert con.execute("SELECT COUNT(*) FROM daily_training_rider_display WHERE rider_display_kind='person_name' AND (rider_type_raw<>'기수' OR rider_name_linked IS NULL OR rider_identity_status NOT IN ('exact_official_profile_id_name_link','exact_event_web_name_link') OR rider_display_value<>rider_name_linked)").fetchone()[0] == 0
            assert con.execute("SELECT COUNT(*) FROM daily_training_rider_display WHERE rider_display_kind='role' AND rider_display_value<>rider_type_raw").fetchone()[0] == 0
            assert con.execute("SELECT COUNT(*) FROM daily_training_rider_display WHERE rider_type_raw='기수' AND rider_identity_status IN ('exact_official_profile_id_name_link','exact_event_web_name_link') AND rider_name_linked IS NOT NULL AND rider_display_value<>rider_name_linked").fetchone()[0] == 0
            assert con.execute("SELECT COUNT(*) FROM daily_training_rider_display WHERE rider_id_raw='080626' AND rider_display_value='다비드'").fetchone()[0] == 31
            assert con.execute("SELECT COUNT(*) FROM daily_training_rider_display WHERE rider_identity_status='source_conflict_hold' AND rider_name_linked IS NULL AND rider_display_kind<>'person_name'").fetchone()[0] == 1
            assert con.execute('SELECT COUNT(*) FROM rider_unmatched_ids').fetchone()[0] == 70
            assert con.execute("SELECT COUNT(*) FROM daily_training_rider_display WHERE meet NOT IN ('1','3','4')").fetchone()[0] == 0
            assert con.execute("SELECT table_name,sql FROM duckdb_tables() WHERE schema_name='main' ORDER BY 1").fetchall() == old_tables
            new_views = dict(con.execute("SELECT view_name,sql FROM duckdb_views() WHERE schema_name='main' AND NOT internal").fetchall())
            assert all(new_views[name] == value for name, value in old_views)
            assert set(new_views) == {name for name, _ in old_views} | {'daily_training_rider_display'}
            assert con.execute('SELECT name,json_text FROM source_manifests ORDER BY 1,2').fetchall() == source_rows
            source['validated_display_counts'] = dict(counts)
            con.execute('INSERT INTO source_manifests VALUES (?,?)', [NAME, json.dumps(source, ensure_ascii=False, sort_keys=True)])
            con.execute('COMMIT')
        except Exception:
            con.execute('ROLLBACK')
            raise
        finally:
            con.close()
        after_sha = sha(stage)
        backup = CORE / 'backups/20261017_before_rider_display'
        before['database_sha256'] = after_sha
        before['input_files'].extend(inputs)
        before['table_and_view_counts']['daily_training_rider_display'] = total
        before['table_and_view_counts']['source_manifests'] = len(source_rows) + 1
        before['supplement_loads'].append({'name': NAME, 'applied_at_utc': captured_at,
            'baseline_database_sha256': baseline_sha, 'database_sha256_after': after_sha,
            'backup_database': (backup / DB.name).relative_to(ROOT).as_posix(),
            'backup_manifest': (backup / MANIFEST.name).relative_to(ROOT).as_posix(),
            'source_manifest_name': NAME, 'display_counts': dict(counts)})
        before['checks']['daily_training_rider_display_policy_verified'] = True
        save(staged_manifest, before)
        report = {'status': 'dry_run_passed', 'rows': total, 'display_counts': dict(counts),
                  'original_tables_and_views_preserved': True, 'baseline_database_sha256': baseline_sha,
                  'baseline_manifest_sha256': baseline_manifest_sha, 'database_sha256_after': after_sha,
                  'backup': backup.relative_to(ROOT).as_posix(), 'active_database_written': False}
        if apply:
            assert sha(DB) == baseline_sha and sha(MANIFEST) == baseline_manifest_sha
            backup.mkdir(exist_ok=True)
            for path, digest in ((DB, baseline_sha), (MANIFEST, baseline_manifest_sha)):
                target = backup / path.name
                if not target.exists():
                    subprocess.run(['/bin/cp', '-c', str(path), str(target)], check=True)
                assert sha(target) == digest
            save(backup / 'attestation.json', {'status': 'verified_equal', 'database_sha256': baseline_sha, 'manifest_sha256': baseline_manifest_sha})
            save(CORE / 'refresh_apply_pending.json', {'run_id': NAME,
                 'baseline_database_sha256': baseline_sha, 'database_sha256_after': after_sha,
                 'manifest_sha256_after': sha(staged_manifest), 'staged_database': stage.relative_to(ROOT).as_posix(),
                 'staged_manifest': staged_manifest.relative_to(ROOT).as_posix(), 'backup': backup.relative_to(ROOT).as_posix()})
            os.replace(stage, DB)
            os.replace(staged_manifest, MANIFEST)
            assert sha(DB) == after_sha and json.loads(MANIFEST.read_text())['database_sha256'] == after_sha
            (CORE / 'refresh_apply_pending.json').unlink()
            report.update(status='applied_and_verified', active_database_written=True, manifest_sha256_after=sha(MANIFEST))
        save(HERE / ('display_apply_report.json' if apply else 'display_dry_run_report.json'), report)
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--apply', action='store_true')
    modes.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    main(args.apply)
