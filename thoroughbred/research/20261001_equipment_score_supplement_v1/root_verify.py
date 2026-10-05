"""Independent read-only verification of the 104-row equipment supplement."""
import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'
INPUT = ROOT / 'thoroughbred/research/20261001_equipment_unobserved_review_v1'


def ident(value):
    return '"' + value.replace('"', '""') + '"'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True)
    args = parser.parse_args()
    baseline = (ROOT / args.baseline).resolve()
    if not baseline.is_relative_to(CORE / 'backups') or not baseline.is_file():
        raise ValueError('Baseline must be a saved core backup')
    sys.path.insert(0, str(INPUT))
    from check_official import score_table, name_key
    candidates = list(csv.DictReader((INPUT / 'score_supplement_candidates.csv').open()))
    tokens = list(csv.DictReader((INPUT / 'score_supplement_tokens.csv').open()))
    expected_tokens = []
    con = duckdb.connect(str(CORE / 'thoroughbred_core.duckdb'), read_only=True)
    # ATTACH requires a SQL literal; strictly confined path and SQL escaping.
    literal = "'" + str(baseline).replace("'", "''") + "'"
    con.execute(f'ATTACH {literal} AS prior (READ_ONLY)')
    preserved = {}
    for name, kind in con.execute("SELECT table_name,table_type FROM information_schema.tables WHERE table_catalog='prior' AND table_schema='main'").fetchall():
        if name == 'source_manifests':
            continue
        q = ident(name)
        added = con.execute(f'SELECT count(*) FROM (SELECT * FROM main.{q} EXCEPT ALL SELECT * FROM prior.main.{q})').fetchone()[0]
        lost = con.execute(f'SELECT count(*) FROM (SELECT * FROM prior.main.{q} EXCEPT ALL SELECT * FROM main.{q})').fetchone()[0]
        schema_equal = con.execute(f'DESCRIBE main.{q}').fetchall() == con.execute(f'DESCRIBE prior.main.{q}').fetchall()
        preserved[name] = {'kind': kind, 'added': added, 'lost': lost, 'schema_equal': schema_equal}
    for x in candidates:
        raw = (ROOT / x['raw_path']).resolve()
        assert raw.is_relative_to(INPUT / 'official')
        assert digest(raw) == x['sha256']
        score = score_table(raw.read_bytes())[int(x['horse_no'])]
        assert score['horse_id'] == x['horse_id']
        assert name_key(score['name']) == name_key(x['horse_name'])
        assert score['equipment_raw'] == x['equipment_raw']
        matches = con.execute('SELECT horse_name_raw,result_rank_raw FROM confirmed_runners WHERE source_meet=? AND result_date=? AND result_race_no=? AND horse_program_no_raw=? AND horse_id_raw=?', [x['meet'], x['date'].replace('-', ''), x['race_no'], x['horse_no'], x['horse_id']]).fetchall()
        assert len(matches) == 1 and name_key(matches[0][0]) == name_key(x['horse_name'])
        assert matches[0][1] == str(score['rank'])
        for position, token in enumerate(x['equipment_raw'].split(','), 1):
            token = token.strip()
            if not token:
                continue
            m = re.fullmatch(r'(.+?)\s*([+-])\s*', token)
            expected_tokens.append({**x, 'position': str(position), 'equipment_name_raw': m.group(1).strip() if m else token, 'mark': ('new' if m.group(2) == '+' else 'removed') if m else 'unmarked', 'token_raw': token})
    assert tokens == expected_tokens
    payload_equal = {}
    field_map = {'meet': 'meet', 'date': 'result_date', 'race_no': 'race_no',
                 'horse_no': 'horse_no', 'horse_id': 'horse_id', 'horse_name': 'horse_name_raw',
                 'equipment_raw': 'equipment_raw', 'source': 'source', 'source_url': 'source_url',
                 'retrieved_at_kst': 'observed_at_kst', 'retrieved_at_basis': 'observed_at_basis',
                 'raw_path': 'raw_path', 'sha256': 'raw_sha256',
                 'availability_status': 'availability_status', 'api78_status': 'api78_status',
                 'position': 'token_position', 'equipment_name_raw': 'equipment_name_raw',
                 'mark': 'mark_status', 'token_raw': 'token_raw'}
    for table, rows in [('equipment_score_supplement', candidates), ('equipment_score_supplement_tokens', tokens)]:
        available = {r[0] for r in con.execute('DESCRIBE ' + ident(table)).fetchall()}
        fields = [k for k, v in field_map.items() if k in rows[0] and v in available]
        assert len(fields) == (15 if table == 'equipment_score_supplement' else 17), (table, fields)
        columns = ','.join(ident(field_map[k]) for k in fields)
        actual = con.execute(f'SELECT {columns} FROM {ident(table)}').fetchall()
        expected = [tuple(x[k].replace('-', '') if k == 'date' else x[k] for k in fields) for x in rows]
        payload_equal[table] = Counter(tuple(str(v) for v in row) for row in actual) == Counter(expected)
    declared_exact = con.execute("SELECT NOT EXISTS(SELECT * FROM equipment_score_supplement_active_declared EXCEPT ALL SELECT * FROM equipment_score_supplement_tokens WHERE mark_status IN ('unmarked','new')) AND NOT EXISTS(SELECT * FROM equipment_score_supplement_tokens WHERE mark_status IN ('unmarked','new') EXCEPT ALL SELECT * FROM equipment_score_supplement_active_declared) AND (SELECT count(*) FROM equipment_score_supplement_active_declared)=166").fetchone()[0]
    ranks_exact = con.execute('SELECT count(*) FROM equipment_score_supplement e JOIN confirmed_runners c ON e.meet=c.source_meet AND e.result_date=c.result_date AND e.race_no=c.result_race_no AND e.horse_no=c.horse_program_no_raw AND e.horse_id=c.horse_id_raw WHERE e.normalrank=c.result_rank_raw').fetchone()[0] == 104
    old_source_preserved = con.execute('SELECT count(*) FROM (SELECT * FROM prior.main.source_manifests EXCEPT ALL SELECT * FROM main.source_manifests)').fetchone()[0] == 0
    new_source_count = con.execute('SELECT count(*) FROM (SELECT * FROM main.source_manifests EXCEPT ALL SELECT * FROM prior.main.source_manifests)').fetchone()[0]
    manifest = json.loads((CORE / 'manifest.json').read_text())
    old_manifest = json.loads(baseline.with_name('manifest.json').read_text())
    stable_keys = set(old_manifest) - {'database_sha256', 'input_files', 'table_and_view_counts', 'supplement_loads'}
    input_preserved = manifest['input_files'][:len(old_manifest['input_files'])] == old_manifest['input_files']
    counts_preserved = all(manifest['table_and_view_counts'].get(k) == v for k, v in old_manifest['table_and_view_counts'].items() if k != 'source_manifests')
    checks = {
        'all_original_tables_views_content_unchanged': all(x['added'] == x['lost'] == 0 for x in preserved.values()),
        'all_original_object_schemas_unchanged': all(x['schema_equal'] for x in preserved.values()),
        'all_previous_source_manifest_rows_preserved': old_source_preserved,
        'exactly_one_new_source_manifest': new_source_count == 1,
        '104_source_rows_exact': len(candidates) == 104 and payload_equal['equipment_score_supplement'],
        '170_ordered_tokens_exact': len(tokens) == 170 and payload_equal['equipment_score_supplement_tokens'],
        'token_marks_163_3_4': Counter(x['mark'] for x in tokens) == {'unmarked': 163, 'new': 3, 'removed': 4},
        'active_declared_view_exact_166_tokens_excludes_removed': declared_exact,
        'stored_normalrank_matches_all_104_core_rows': ranks_exact,
        'prior_manifest_metadata_and_input_pins_preserved': input_preserved and all(manifest[k] == old_manifest[k] for k in stable_keys),
        'original_manifest_object_counts_preserved': counts_preserved,
        'all_104_raw_hash_id_name_rank_equipment_and_core_matches': True,
        'current_database_hash_matches_manifest': digest(CORE / 'thoroughbred_core.duckdb') == manifest['database_sha256'],
    }
    con.close()
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'baseline': str(baseline.relative_to(ROOT)), 'checks': checks, 'all_passed': all(checks.values()), 'preserved_objects': preserved, 'payload_equal': payload_equal}
    (HERE / 'root_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'preserved_objects'}, ensure_ascii=False, indent=2))
    if not report['all_passed']:
        raise RuntimeError('Independent supplement verification failed')


if __name__ == '__main__':
    main()
