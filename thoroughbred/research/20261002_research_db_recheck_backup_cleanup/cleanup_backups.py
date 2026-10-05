"""Keep verified current/prior research pairs; delete explicitly authorized old pairs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'
BACKUPS = CORE / 'backups'
DB_NAME = 'thoroughbred_core.duckdb'
KEEP_PRIOR = '20261002_before_starting_exam'
EXPECTED = '828942c5b59f4632998c12f142c4e18e4ee2e6316a0e5a56f826f37a68c726a6'
OLDER = (
    '20261001_before_calendar_closure_subtype_review',
    '20261001_before_closure_gap_followup_v4',
    '20261001_before_equipment_score_supplement',
    '20261001_before_remaining_closure_cancel_review_v3',
    '20261001_before_trainer_owner_review',
    '20261001_before_trial_trainer_error_disposition',
    '20261001_before_trial_venue_correction',
    '20261002_before_equipment_api78_full',
    '20261002_before_training_three',
    '20261002_before_training_three_first_attempt',
)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_pair(directory):
    assert directory.parent == BACKUPS and not directory.is_symlink()
    assert directory.resolve() == directory and directory.is_dir()
    assert sorted(p.name for p in directory.iterdir()) == ['manifest.json', DB_NAME]
    assert all(p.is_file() and not p.is_symlink() for p in directory.iterdir())
    manifest = json.loads((directory / 'manifest.json').read_text())
    digest = sha(directory / DB_NAME)
    assert digest == manifest['database_sha256']
    return {'directory':str(directory.relative_to(ROOT)), 'database_sha256':digest,
            'database_bytes':(directory / DB_NAME).stat().st_size,
            'manifest_sha256':sha(directory / 'manifest.json'), 'manifest':manifest}


def save(record):
    target = HERE / 'cleanup_record.json'
    temp = HERE / 'cleanup_record.tmp'
    temp.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+'\n')
    os.replace(temp,target)


def main():
    assert not (HERE / 'cleanup_record.json').exists(), 'Cleanup already recorded'
    assert not list(CORE.glob('*.wal')), 'Active database WAL; refusing cleanup'
    assert {p.name for p in BACKUPS.iterdir()} == set(OLDER) | {KEEP_PRIOR}
    current_manifest_sha = sha(CORE / 'manifest.json')
    manifest = json.loads((CORE / 'manifest.json').read_text())
    assert sha(CORE / DB_NAME) == manifest['database_sha256'] == EXPECTED
    con = duckdb.connect(str(CORE / DB_NAME), read_only=True)
    names = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog=current_database() AND table_schema='main'").fetchall()]
    counts = {name:con.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in names}
    con.close()
    assert len(counts) == 109 and counts['source_manifests'] == 24
    assert all(counts[name] == expected for name,expected in manifest['table_and_view_counts'].items())
    prior = verify_pair(BACKUPS / KEEP_PRIOR)
    old = [verify_pair(BACKUPS / name) for name in OLDER]
    current_dir = BACKUPS / ('20261002_current_verified_' + datetime.now(ZoneInfo('Asia/Seoul')).strftime('%H%M%S'))
    current_dir.mkdir()
    for name in (DB_NAME,'manifest.json'):
        subprocess.run(['/bin/cp','-c',str(CORE / name),str(current_dir / name)],check=True)
    current = verify_pair(current_dir)
    assert current['database_sha256'] == EXPECTED and current['manifest_sha256'] == current_manifest_sha
    assert sha(CORE / DB_NAME) == EXPECTED and sha(CORE / 'manifest.json') == current_manifest_sha
    record = {'started_at_utc':datetime.now(timezone.utc).isoformat(), 'status':'verified_before_cleanup',
              'scope':'Research core backup directory only; keep current and latest prior paired DB/manifest',
              'current_database_sha256':EXPECTED, 'current_manifest_sha256':current_manifest_sha,
              'catalog_object_counts':counts, 'registered_count_mismatches':{},
              'retained':[current,prior], 'planned_deletions':old, 'deleted_directories':[]}
    save(record)
    for item in old:
        directory = ROOT / item['directory']
        verified = verify_pair(directory)
        assert verified['database_sha256'] == item['database_sha256'] and verified['manifest_sha256'] == item['manifest_sha256']
        assert directory.name in OLDER and directory.parent == BACKUPS
        for name in (DB_NAME,'manifest.json'):
            (directory / name).unlink()
        directory.rmdir()
        record['deleted_directories'].append(item['directory'])
        save(record)
    assert {p.name for p in BACKUPS.iterdir()} == {current_dir.name,KEEP_PRIOR}
    assert sha(CORE / DB_NAME) == EXPECTED and sha(CORE / 'manifest.json') == current_manifest_sha
    for directory in (current_dir,BACKUPS / KEEP_PRIOR):
        verify_pair(directory)
    record['status']='complete'
    record['completed_at_utc']=datetime.now(timezone.utc).isoformat()
    record['deleted_database_logical_bytes']=sum(item['database_bytes'] for item in old)
    record['current_database_and_manifest_unchanged']=True
    save(record)
    print(json.dumps({'status':'complete','deleted_backup_pairs':len(old), 'retained_directories':[current_dir.name,KEEP_PRIOR],
                      'objects_checked':len(counts),'database_unchanged':True},ensure_ascii=False))


if __name__ == '__main__':
    main()
