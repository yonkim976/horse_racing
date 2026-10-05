"""Independent, read-only preservation audit after the medical append."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'
BASE = CORE / 'backups/20261002_before_medical'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def qi(text):
    return '"' + text.replace('"', '""') + '"'


def compare(con, name):
    cols = [r[0] for r in con.execute('DESCRIBE prior.main.' + qi(name)).fetchall()]
    expr = 'sha256(to_json(struct_pack(' + ','.join(qi(c) + ':=' + qi(c) for c in cols) + ')))'
    a, b = 'main.' + qi(name), 'prior.main.' + qi(name)
    added = con.execute(f'SELECT count(*) FROM (SELECT {expr} FROM {a} EXCEPT ALL SELECT {expr} FROM {b})').fetchone()[0]
    lost = con.execute(f'SELECT count(*) FROM (SELECT {expr} FROM {b} EXCEPT ALL SELECT {expr} FROM {a})').fetchone()[0]
    return {'added': added, 'lost': lost}


def main():
    manifest = json.loads((CORE / 'manifest.json').read_text())
    old = json.loads((BASE / 'manifest.json').read_text())
    assert old['database_sha256'] == '828942c5b59f4632998c12f142c4e18e4ee2e6316a0e5a56f826f37a68c726a6'
    assert sha(BASE / 'thoroughbred_core.duckdb') == old['database_sha256']
    con = duckdb.connect(str(CORE / 'thoroughbred_core.duckdb'), read_only=True)
    con.execute("SET memory_limit='2GB'")
    con.execute('SET threads=2')
    con.execute('SET preserve_insertion_order=false')
    scratch = HERE / 'verification_scratch'
    scratch.mkdir(exist_ok=True)
    con.execute('SET temp_directory=' + "'" + str(scratch).replace("'", "''") + "'")
    con.execute("ATTACH '" + str(BASE / 'thoroughbred_core.duckdb').replace("'", "''") + "' AS prior (READ_ONLY)")
    prior = con.execute("SELECT table_name,table_type FROM information_schema.tables WHERE table_catalog='prior' AND table_schema='main'").fetchall()
    assert len(prior) == 109
    views = dict(con.execute("SELECT view_name,sql FROM duckdb_views() WHERE database_name=current_database() AND schema_name='main'").fetchall())
    oldviews = dict(con.execute("SELECT view_name,sql FROM duckdb_views() WHERE database_name='prior' AND schema_name='main'").fetchall())
    preserved = {}
    for name, kind in prior:
        if name == 'source_manifests':
            continue
        assert con.execute('DESCRIBE main.' + qi(name)).fetchall() == con.execute('DESCRIBE prior.main.' + qi(name)).fetchall(), name
        result = {'definition_equal': views[name] == oldviews[name]} if kind == 'VIEW' else compare(con, name)
        assert result.get('definition_equal', True) and result.get('added', 0) == result.get('lost', 0) == 0, name
        preserved[name] = result
        print(json.dumps({'stage': 'preserved', 'object': name}), flush=True)
    lost = con.execute('SELECT count(*) FROM (SELECT * FROM prior.main.source_manifests EXCEPT ALL SELECT * FROM source_manifests)').fetchone()[0]
    added = con.execute('SELECT count(*) FROM (SELECT * FROM source_manifests EXCEPT ALL SELECT * FROM prior.main.source_manifests)').fetchone()[0]
    assert lost == 0 and added >= 1
    for key in set(old) - {'database_sha256', 'input_files', 'table_and_view_counts', 'supplement_loads'}:
        assert manifest[key] == old[key], key
    assert manifest['input_files'][:len(old['input_files'])] == old['input_files']
    assert manifest['supplement_loads'][:len(old['supplement_loads'])] == old['supplement_loads']
    counts = manifest['table_and_view_counts']
    for name, expected in counts.items():
        assert con.execute('SELECT count(*) FROM ' + qi(name)).fetchone()[0] == expected, name
    for name, expected in old['table_and_view_counts'].items():
        if name != 'source_manifests':
            assert counts[name] == expected, name
    current_objects = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_catalog=current_database() AND table_schema='main'").fetchone()[0]
    con.close()
    assert sha(CORE / 'thoroughbred_core.duckdb') == manifest['database_sha256']
    report = {'all_passed': True, 'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'original_objects': 109,
              'preserved': preserved, 'source_manifests_added': added, 'source_manifests_lost': lost,
              'current_objects': current_objects, 'manifest_count_entries_checked': len(counts),
              'database_sha256': manifest['database_sha256'], 'verification_script_sha256': sha(Path(__file__))}
    (HERE / 'root_preservation_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'preserved'}), flush=True)


if __name__ == '__main__':
    main()
