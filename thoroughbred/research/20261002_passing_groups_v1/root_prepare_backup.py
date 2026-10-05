"""Make and attest an exact APFS clone pair before the passing groups append."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'
BACKUP = CORE / 'backups/20261002_before_passing_groups'
EXPECTED = 'c30202a65a1a82c2927efc8e0ef150c03a0c9950e953ee445beb1b3a7f8c2de6'


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
