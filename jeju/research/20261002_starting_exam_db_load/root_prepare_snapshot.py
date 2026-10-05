"""Back up the authorized local DB and record the pre-load state."""
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
BACKUP = HERE / 'before_load.sqlite3'
STAGE = Path('/private/tmp/jeju_api21_load_stage_20261002.sqlite3')


def hash_file(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    assert not BACKUP.exists() and not STAGE.exists(), 'Do not overwrite a backup or stage.'
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    schema = {r['name']: {'type': r['type'], 'sql': r['sql']} for r in conn.execute(
        "SELECT name,type,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}
    assert 'starting_exam_api_rows' not in schema
    tables = [n for n, obj in schema.items() if obj['type'] == 'table']
    assert all(n.replace('_', '').isalnum() for n in tables)
    counts = {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in tables}
    profiles = [dict(r) for r in conn.execute('SELECT * FROM horse_profile_observations ORDER BY horse_profile_observation_id')]
    source_artifacts = [dict(r) for r in conn.execute('SELECT * FROM source_artifacts ORDER BY source_artifact_id')]
    metadata = [dict(r) for r in conn.execute('SELECT * FROM schema_metadata ORDER BY key')]
    assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    backup = sqlite3.connect(BACKUP)
    conn.backup(backup)
    backup.close()
    conn.close()
    sha = hash_file(BACKUP)
    shutil.copy2(BACKUP, STAGE)
    assert hash_file(STAGE) == sha
    report = {'database': str(DB), 'backup_path': BACKUP.name, 'backup_sha256': sha,
              'stage_path': str(STAGE), 'table_counts': counts, 'schema': schema,
              'profiles': profiles, 'source_artifacts': source_artifacts, 'metadata': metadata,
              'initial_foreign_key_violations': 0}
    (HERE / 'root_before_load.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'backup_sha256': sha, 'stage_path': str(STAGE), 'existing_tables': len(tables),
                      'profiles_before': counts['horse_profile_observations']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
