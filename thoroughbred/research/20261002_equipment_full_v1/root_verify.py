"""Independent, read-only checks of the full API78 equipment ingestion."""
import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'
INVENTORY = HERE / 'inventory'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def safe_path(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Input path outside workspace')
    return path


def name_key(value):
    text = unicodedata.normalize('NFKC', str(value or '').strip())
    text = text.removeprefix('★').strip()
    text = re.sub(r'^\[[^]]+\]\s*', '', text).removeprefix('★').strip()
    return ''.join(text.split()).casefold()


def date_key(value):
    parts = re.search(r'(\d{4})\D*(\d{1,2})\D*(\d{1,2})', str(value))
    if not parts:
        raise ValueError('Malformed source date')
    year, month, day = map(int, parts.groups())
    return datetime(year, month, day).strftime('%Y%m%d')


def number(value):
    return str(int(re.search(r'\d+', str(value)).group()))


def rows_dict(con, query):
    result = con.execute(query)
    fields = [x[0] for x in result.description]
    return [dict(zip(fields, row)) for row in result.fetchall()]


def read_csv(name):
    with (INVENTORY / name).open(newline='') as stream:
        return list(csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True)
    args = parser.parse_args()
    baseline = safe_path(args.baseline)
    if not baseline.is_relative_to(CORE / 'backups') or not baseline.is_file():
        raise ValueError('Baseline must be an existing saved core backup')
    for row in read_csv('frozen_export_manifest.csv'):
        path = INVENTORY / row['file_name']
        assert digest(path) == row['sha256']
        with path.open(newline='') as stream:
            assert sum(1 for _ in csv.DictReader(stream)) == int(row['row_count'])
    snapshot = json.loads((INVENTORY / 'snapshot_summary.json').read_text())
    for stem in ('historical_capture_manifest', 'historical_targets_manifest'):
        assert digest(safe_path(snapshot[stem + '_snapshot_path'])) == snapshot[stem + '_snapshot_sha256']
    con = duckdb.connect(str(CORE / 'thoroughbred_core.duckdb'), read_only=True)
    con.execute("ATTACH '" + str(baseline).replace("'", "''") + "' AS prior (READ_ONLY)")
    preserved = {}
    for name, kind in con.execute("SELECT table_name,table_type FROM information_schema.tables WHERE table_catalog='prior' AND table_schema='main'").fetchall():
        if name == 'source_manifests':
            continue
        q = quote(name)
        plus = con.execute(f'SELECT count(*) FROM (SELECT * FROM main.{q} EXCEPT ALL SELECT * FROM prior.main.{q})').fetchone()[0]
        minus = con.execute(f'SELECT count(*) FROM (SELECT * FROM prior.main.{q} EXCEPT ALL SELECT * FROM main.{q})').fetchone()[0]
        same_schema = con.execute(f'DESCRIBE main.{q}').fetchall() == con.execute(f'DESCRIBE prior.main.{q}').fetchall()
        preserved[name] = {'kind': kind, 'added': plus, 'lost': minus, 'schema_equal': same_schema}
    old_sources = con.execute('SELECT count(*) FROM (SELECT * FROM prior.main.source_manifests EXCEPT ALL SELECT * FROM main.source_manifests)').fetchone()[0]
    new_sources = con.execute('SELECT count(*) FROM (SELECT * FROM main.source_manifests EXCEPT ALL SELECT * FROM prior.main.source_manifests)').fetchone()[0]
    core_rows = con.execute('SELECT source_meet,result_date,result_race_no,horse_program_no_raw,horse_id_raw,horse_name_raw FROM confirmed_runners').fetchall()
    core = {tuple(row[:5]): name_key(row[5]) for row in core_rows}
    assert len(core) == len(core_rows) == 330465

    observations = rows_dict(con, 'SELECT * FROM equipment_api78_card_observations')
    by_id = {row['observation_id']: row for row in observations}
    by_page = defaultdict(list)
    by_batch = defaultdict(list)
    expected_tokens = []
    linked = []
    for row in observations:
        assert row['meet'] in {'1', '3', '4'}
        assert '20100101' <= row['event_date'] <= '20260929'
        assert row['physical_wear_status'] == 'unknown'
        assert row['source_endpoint'].endswith('/API78/chulmainfo')
        assert row['api_horse_name_normalized'] == name_key(row['api_horse_name_raw'])
        by_page[row['source_document_ref']].append(row)
        by_batch[row['batch_id']].append(row)
        if row['linked_core_horse_id']:
            key = tuple(row[col] for col in ('linked_core_meet', 'linked_core_event_date', 'linked_core_race_no', 'linked_core_horse_no', 'linked_core_horse_id'))
            assert key in core and core[key] == row['api_horse_name_normalized']
            assert key[:4] == tuple(row[col] for col in ('meet', 'event_date', 'race_no', 'horse_no'))
            assert row['link_status'] in {'linked_op_id_corroborated', 'linked_core_key_name_only'}
            assert row['core_key_candidate_count'] == row['core_key_name_match_count'] == 1
            if row['link_status'] == 'linked_op_id_corroborated':
                assert row['operational_horse_id_candidate'] == key[-1]
            linked.append(key)
        else:
            assert row['link_status'] == 'unresolved'
        raw = row['equipment_raw']
        if raw is None:
            assert row['equipment_value_state'] in {'field_missing', 'null'}
        elif raw.strip():
            for pos, token in enumerate(raw.split(','), 1):
                token_raw = token
                token = token.strip()
                if not token or token in {'-', '+'}:
                    continue
                match = re.fullmatch(r'(.+?)\s*([+-])\s*', token)
                equipment = match.group(1).strip() if match else token
                mark = ('new' if match.group(2) == '+' else 'removed') if match else 'unmarked'
                expected_tokens.append((row['observation_id'], pos, token_raw, equipment, mark))
        if raw is not None and raw.strip() == '-':
            assert row['equipment_field_state'] == 'dash_placeholder'
    assert len(set(linked)) == len(linked)
    linked_keys = set(linked)
    actual_tokens = con.execute('SELECT observation_id,token_position,token_raw,equipment_name_raw,mark_status FROM equipment_api78_card_tokens').fetchall()
    token_exact = Counter(actual_tokens) == Counter(expected_tokens)

    pages = rows_dict(con, 'SELECT * FROM equipment_api78_capture_pages')
    batch_pages = defaultdict(list)
    raw_rows_checked = 0
    for page in pages:
        path = safe_path(page['raw_path'])
        assert digest(path) == page['raw_sha256']
        assert path.stat().st_size == page['response_bytes']
        payload = json.loads(path.read_text())['response']
        assert str(payload['header']['resultCode']) == '00'
        body = payload['body']
        items = body.get('items')
        if isinstance(items, dict):
            items = items.get('item', [])
        if not items:
            items = []
        if isinstance(items, dict):
            items = [items]
        assert isinstance(items, list)
        assert int(body['pageNo']) == page['page_no']
        assert int(body['totalCount']) == page['total_count']
        assert len(items) == page['item_count']
        size = int(body['numOfRows'])
        assert size > 0 and len(items) <= size
        obs = sorted(by_page[page['source_document_ref']], key=lambda x: x['source_index_in_batch'])
        assert len(obs) == len(items)
        for source, stored in zip(items, obs):
            assert date_key(source['raceDt']) == page['event_date']
            assert stored['event_date'] == page['event_date'] and stored['meet'] == page['meet']
            assert number(source['raceNo']) == stored['race_no']
            assert number(source['gtno']) == stored['horse_no']
            assert str(source.get('hrnm') or '').strip() == stored['api_horse_name_raw']
            assert ('equipCrs' in source) == stored['equipment_field_present']
            assert ('equipCrs' in source and source['equipCrs'] is None) == stored['equipment_is_null']
            assert source.get('equipCrs') == stored['equipment_raw']
            assert stored['source_document_path'] == page['raw_path']
            assert stored['source_sha256'] == page['raw_sha256']
            assert stored['capture_retrieved_at_ms'] == page['retrieved_at_ms']
            assert stored['observed_time_basis'] == page['observed_time_basis']
        raw_rows_checked += len(items)
        batch_pages[page['batch_id']].append((page['page_no'], int(body['totalCount']), size, len(items)))
    for batch, batch_rows in batch_pages.items():
        batch_rows.sort()
        total = batch_rows[0][1]
        assert len({row[1] for row in batch_rows}) == 1
        assert sum(row[3] for row in batch_rows) == total
        assert [row[0] for row in batch_rows] == list(range(1, max(1, (total + batch_rows[0][2] - 1) // batch_rows[0][2]) + 1))
        assert len(by_batch[batch]) == total
        assert sorted(row['source_index_in_batch'] for row in by_batch[batch]) == list(range(1, total + 1))

    # Frozen CSVs independently match the stored event payload and core ledger.
    export = read_csv('api78_runner_records.csv')
    assert len(export) == len(observations)
    for row in export:
        stored = by_id[row['observation_id']]
        for field in ('batch_id', 'source_document_ref', 'source_sha256', 'event_date', 'meet', 'race_no', 'horse_no', 'api_horse_name_raw', 'equipment_value_state', 'link_status', 'link_method', 'link_reason', 'linked_core_horse_id'):
            assert row[field] == ('' if stored[field] is None else str(stored[field])), field
        assert row['equipment_raw'] == (stored['equipment_raw'] or '')
    ledger = read_csv('api78_core_runner_ledger.csv')
    actual_ledger = rows_dict(con, 'SELECT * FROM equipment_api78_core_runner_ledger')
    fields = list(ledger[0])
    ledger_equal = Counter(tuple(row[field] for field in fields) for row in ledger) == Counter(tuple('' if row[field] is None else str(row[field]) for field in fields) for row in actual_ledger)
    coverage = rows_dict(con, 'SELECT * FROM equipment_core_coverage')
    coverage_keys = [tuple(row[field] for field in ('meet', 'result_date', 'race_no', 'horse_no', 'horse_id')) for row in coverage]
    coverage_exact = len(coverage) == len(set(coverage_keys)) == len(core) and set(coverage_keys) == set(core)
    fallback_keys = {tuple(row) for row in con.execute('SELECT meet,result_date,race_no,horse_no,horse_id FROM equipment_score_supplement').fetchall()}
    for row in coverage:
        key = tuple(row[field] for field in ('meet', 'result_date', 'race_no', 'horse_no', 'horse_id'))
        if row['api78_observation_id']:
            assert row['selected_source'] == 'API78'
            assert row['selected_equipment_raw'] == by_id[row['api78_observation_id']]['equipment_raw']
        elif key in fallback_keys:
            assert row['selected_source'] == 'KRA_official_score_html'
    union = rows_dict(con, 'SELECT * FROM equipment_declared_union_fallback')
    assert all(row['mark_status'] in {'new', 'unmarked'} for row in union)
    expected_union = Counter()
    for oid, pos, token, equipment, mark in expected_tokens:
        o = by_id[oid]
        if mark != 'removed' and o['linked_core_horse_id']:
            expected_union[('API78', o['meet'], o['event_date'], o['race_no'], o['horse_no'], o['linked_core_horse_id'], pos, token, equipment, mark)] += 1
    for row in rows_dict(con, 'SELECT * FROM equipment_score_supplement_active_declared'):
        key = tuple(row[field] for field in ('meet', 'result_date', 'race_no', 'horse_no', 'horse_id'))
        if key not in linked_keys:
            expected_union[('KRA_official_score_html', *key, row['token_position'], row['token_raw'], row['equipment_name_raw'], row['mark_status'])] += 1
    union_exact = Counter(tuple(row[field] for field in ('source', 'meet', 'result_date', 'race_no', 'horse_no', 'horse_id', 'token_position', 'token_raw', 'equipment_name_raw', 'mark_status')) for row in union) == expected_union

    manifest = json.loads((CORE / 'manifest.json').read_text())
    old_manifest = json.loads(baseline.with_name('manifest.json').read_text())
    stable = set(old_manifest) - {'database_sha256', 'input_files', 'table_and_view_counts', 'supplement_loads'}
    checks = {
        'all_original_objects_content_preserved': all(x['added'] == x['lost'] == 0 for x in preserved.values()),
        'all_original_schemas_preserved': all(x['schema_equal'] for x in preserved.values()),
        'old_source_rows_preserved_one_added': old_sources == 0 and new_sources == 1,
        'all_selected_raw_pages_hash_date_pagination_and_payload_checked': raw_rows_checked == len(observations),
        'all_csv_observations_match_stored_payload': True,
        'all_tokens_reconstructed_from_raw_equipment_exactly': token_exact,
        'all_linked_core_keys_unique_and_name_verified': True,
        'full_core_ledger_matches_frozen_csv': ledger_equal,
        'coverage_exactly_all_core_keys_once': coverage_exact,
        'active_union_exact_with_api78_priority_and_removed_excluded': union_exact,
        'prior_manifest_metadata_and_inputs_preserved': all(manifest[k] == old_manifest[k] for k in stable) and manifest['input_files'][:len(old_manifest['input_files'])] == old_manifest['input_files'] and manifest['supplement_loads'][:len(old_manifest['supplement_loads'])] == old_manifest['supplement_loads'],
        'prior_object_counts_preserved': all(manifest['table_and_view_counts'][k] == v for k, v in old_manifest['table_and_view_counts'].items() if k != 'source_manifests'),
        'database_hash_matches_manifest': digest(CORE / 'thoroughbred_core.duckdb') == manifest['database_sha256'],
    }
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'baseline': str(baseline.relative_to(ROOT)), 'checks': checks, 'all_passed': all(checks.values()), 'counts': {'raw_pages': len(pages), 'raw_rows': len(observations), 'tokens': len(actual_tokens), 'linked_rows': len(linked), 'coverage_rows': len(coverage), 'union_tokens': len(union)}, 'coverage_status_counts': dict(Counter(row['coverage_status'] for row in coverage)), 'token_marks': dict(Counter(row[4] for row in actual_tokens)), 'preserved_objects': preserved}
    con.close()
    (HERE / 'root_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'preserved_objects'}, ensure_ascii=False, indent=2))
    if not report['all_passed']:
        raise RuntimeError('Independent equipment verification failed')


if __name__ == '__main__':
    main()
