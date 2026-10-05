"""Read-only inventory and provenance audit of the pre-report research core."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/backups/20261002_before_steward_reports'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def qi(name):
    return '"' + name.replace('"', '""') + '"'


def main():
    db = BASE / 'thoroughbred_core.duckdb'
    manifest_path = BASE / 'manifest.json'
    m = json.loads(manifest_path.read_text())
    db_sha, manifest_sha = sha(db), sha(manifest_path)
    assert db_sha == m['database_sha256'] == '616aa6111242cfbcee4b87bc2e77251644e5c3780fc8c978319f69e7b1c4c8f7'
    assert manifest_sha == '6aa4d2870fbd087afa81973d5fc8f3966cfc00fd7896c656cb4fedaef2ef1697'
    input_checks, input_issues = [], []
    for item in m['input_files']:
        relative = item['path']
        path = (ROOT / relative).resolve()
        assert path.is_relative_to(ROOT.resolve()), relative
        result = {'path': relative, 'exists': path.is_file(), 'expected_sha256': item['sha256'],
                  'table': item.get('table'), 'loaded_to_database': item.get('loaded_to_database')}
        result['actual_sha256'] = sha(path) if path.is_file() else None
        result['matches'] = result['actual_sha256'] == result['expected_sha256']
        input_checks.append(result)
        if not result['matches']:
            input_issues.append(result)
    print(json.dumps({'stage': 'input_hashes', 'checked': len(input_checks), 'issues': input_issues}), flush=True)
    con = duckdb.connect(str(db), read_only=True)
    con.execute("SET memory_limit='2GB'")
    con.execute('SET threads=2')
    con.execute('SET preserve_insertion_order=false')
    names = con.execute("SELECT table_name,table_type FROM information_schema.tables WHERE table_schema='main' AND table_catalog=current_database() ORDER BY table_name").fetchall()
    assert len(names) == 180
    assert not any(name.startswith('steward_') or name == 'horse_steward_history' for name, _ in names)
    actual_counts, mismatches = {}, {}
    for name, kind in names:
        count = con.execute('SELECT count(*) FROM ' + qi(name)).fetchone()[0]
        actual_counts[name] = count
        expected = m['table_and_view_counts'].get(name)
        if expected is not None and expected != count:
            mismatches[name] = {'expected': expected, 'actual': count}
        print(json.dumps({'stage': 'object_count', 'name': name, 'count': count}), flush=True)
    assert actual_counts['source_manifests'] == 26
    con.close()
    unchanged = sha(db) == db_sha and sha(manifest_path) == manifest_sha
    result = {'all_passed': not input_issues and not mismatches and unchanged,
              'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'read_only': True,
              'baseline_database': db.relative_to(ROOT).as_posix(), 'database_sha256': db_sha,
              'manifest_sha256': manifest_sha, 'database_and_manifest_unchanged': unchanged,
              'checked_objects': len(names), 'registered_counts_checked': len(m['table_and_view_counts']),
              'all_object_counts': actual_counts, 'registered_count_mismatches': mismatches,
              'input_files_checked': len(input_checks), 'input_hash_checks': input_checks,
              'input_hash_issues': input_issues, 'steward_report_objects_present': False}
    (HERE / 'root_manifest_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('input_hash_checks','all_object_counts')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
