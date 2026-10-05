"""Make and attest an exact APFS clone pair before the steward reports append."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'
BACKUP = CORE / 'backups/20261002_before_steward_reports'
EXPECTED = '616aa6111242cfbcee4b87bc2e77251644e5c3780fc8c978319f69e7b1c4c8f7'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    db, manifest = CORE / 'thoroughbred_core.duckdb', CORE / 'manifest.json'
    assert not db.with_suffix(db.suffix + '.wal').exists()
    assert sha(db) == EXPECTED == json.loads(manifest.read_text())['database_sha256']
    manifest_sha = sha(manifest)
    BACKUP.mkdir(exist_ok=False)
    for path in (db, manifest):
        subprocess.run(['/bin/cp', '-c', str(path), str(BACKUP / path.name)], check=True)
        assert sha(path) == sha(BACKUP / path.name)
    assert sha(db) == EXPECTED and sha(manifest) == manifest_sha
    report = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'method': 'APFS clone /bin/cp -c',
              'baseline_db_sha256': EXPECTED, 'baseline_manifest_sha256': manifest_sha,
              'backup_db_sha256': sha(BACKUP / db.name), 'backup_manifest_sha256': sha(BACKUP / manifest.name),
              'source_db_path': str(db), 'source_manifest_path': str(manifest),
              'backup_db_path': str(BACKUP / db.name), 'backup_manifest_path': str(BACKUP / manifest.name),
              'backup_dir': str(BACKUP), 'verified_equal': True}
    (BACKUP / 'backup_pair_attestation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (HERE / 'root_backup_attestation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
