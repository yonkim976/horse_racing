"""Independent, read-only verification of raw daily/start/swim training loads."""
import argparse
import ast
import hashlib
import json
import xml.etree.ElementTree as XML
from collections import Counter
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'
DATASETS = ('daily_training', 'start_training', 'swim_training')
ENDPOINTS = {'daily_training': 'API18_1', 'start_training': 'API22_1', 'swim_training': 'API216'}
FIELDS = ('dataset', 'observation_id', 'event_date', 'meet', 'official_horse_id', 'raw_name', 'raw_path', 'raw_sha256', 'source_page_no', 'source_row_no', 'source_captured_at', 'capture_basis', 'endpoint', 'raw_payload_json', 'typed_fields_json', 'link_status', 'linked_core_horse_id', 'qa_flags_json', 'capture_id')


def safe(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Path outside workspace')
    return path


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ident(value):
    return '"' + value.replace('"', '""') + '"'


@lru_cache(maxsize=4)
def page_items(path_text):
    path = safe(path_text)
    if path.suffix == '.xml':
        text = path.read_bytes().decode('utf-8-sig')
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise ValueError('DTD and custom entities are not permitted')
        root = XML.fromstring(text)
        assert root.findtext('.//resultCode') in ('00', '0000')
        items = [{child.tag: child.text or '' for child in item} for item in root.findall('.//items/item')]
        return items, int(root.findtext('.//pageNo')), int(root.findtext('.//totalCount')), int(root.findtext('.//numOfRows'))
    payload = json.loads(path.read_bytes())['response']
    assert str(payload['header']['resultCode']) in ('00', '0000')
    body = payload['body']
    items = body.get('items') or {}
    items = items.get('item') or [] if isinstance(items, dict) else items
    if isinstance(items, dict):
        items = [items]
    assert isinstance(items, list)
    return items, int(body['pageNo']), int(body['totalCount']), int(body['numOfRows'])


def clock_seconds(value):
    text = str(value or '')
    if len(text) != 14 or not text.isdigit():
        return None
    hour, minute, second = int(text[8:10]), int(text[10:12]), int(text[12:14])
    if hour > 23 or minute > 59 or second > 59:
        return None
    return hour * 3600 + minute * 60 + second


def raw_check(dataset, parquet, roster):
    stats = Counter()
    link_stats = Counter()
    qa_stats = Counter()
    date_counts = Counter()
    hashes = {}
    for batch_no, batch in enumerate(pq.ParquetFile(parquet).iter_batches(batch_size=32768), 1):
        for row in batch.to_pylist():
            assert row['dataset'] == dataset and row['meet'] in ('1', '3')
            assert date(2010, 1, 1) <= row['event_date'] <= date(2026, 9, 29)
            assert row['endpoint'] == ENDPOINTS[dataset]
            assert row['source_page_no'] >= 1 and row['source_row_no'] >= 1
            assert row['capture_basis'] and row['capture_id']
            path = row['raw_path']
            if path not in hashes:
                hashes[path] = sha(safe(path))
            assert hashes[path] == row['raw_sha256']
            source_items, page_no, _, size = page_items(path)
            assert page_no == row['source_page_no'] and len(source_items) <= size
            source = source_items[row['source_row_no'] - 1]
            raw = json.loads(row['raw_payload_json'])
            typed = json.loads(row['typed_fields_json'])
            assert raw == source
            assert str(raw['trDate']) == row['event_date'].strftime('%Y%m%d')
            source_meet = str(raw['meet']).strip()
            assert source_meet in ({'1', '서울'} if row['meet'] == '1' else {'3', '부산경남', '부경', '영남'})
            expected_id = None if raw.get('hrNo') is None or not str(raw['hrNo']).strip() else str(raw['hrNo'])
            expected_name = None if raw.get('hrName') is None else str(raw['hrName'])
            assert expected_id == row['official_horse_id']
            assert expected_name == row['raw_name']
            for field in raw:
                assert field in typed and typed[field] == raw[field], (dataset, field)
            if row['official_horse_id'] in roster:
                assert row['linked_core_horse_id'] == row['official_horse_id']
            else:
                assert row['linked_core_horse_id'] is None
            link_stats[row['link_status']] += 1
            flags = json.loads(row['qa_flags_json'])
            if isinstance(flags, list):
                qa_stats.update(flags)
            elif isinstance(flags, dict):
                qa_stats.update(k for k, v in flags.items() if v)
            else:
                raise ValueError('Invalid QA flags')
            date_counts[(dataset, row['event_date'], row['meet'])] += 1
            stats['rows'] += 1
            if dataset == 'daily_training':
                duration = raw.get('trTerm')
                if duration is not None:
                    duration = int(duration)
                    stats['negative_duration'] += duration < 0
                    stats['zero_duration'] += duration == 0
                    started, ended = clock_seconds(raw.get('stTime')), clock_seconds(raw.get('spTime'))
                    if started is not None and ended is not None:
                        stats['end_before_start'] += ended < started
                        stats['duration_differs_from_clocks'] += duration != ended - started
            if dataset == 'swim_training' and raw.get('cnt') is not None:
                stats['zero_count'] += int(raw['cnt']) == 0
                stats['negative_count'] += int(raw['cnt']) < 0
        if batch_no % 30 == 0:
            print(json.dumps({'stage': 'raw_verification', 'dataset': dataset, 'rows': stats['rows']}), flush=True)
    return {'counts': dict(stats), 'link_status_counts': dict(link_stats), 'qa_flag_counts': dict(qa_stats), 'verified_raw_files': len(hashes)}, date_counts


def cached_raw_check(dataset, parquet, roster):
    cache_path = HERE / (dataset + '_root_raw_check.json')
    initial = HERE / 'root_verify_initial.py'
    initial_ast = ast.parse(initial.read_text())
    current_ast = ast.parse(Path(__file__).read_text())
    raw_functions = {'safe', 'sha', 'page_items', 'clock_seconds', 'raw_check'}
    def raw_code(tree):
        return [ast.dump(node, include_attributes=False) for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in raw_functions]
    assert raw_code(initial_ast) == raw_code(current_ast), 'Raw verifier changed since cached checks'
    pins = {'parquet_sha256': sha(parquet), 'script_sha256': sha(initial),
            'roster_sha256': hashlib.sha256(json.dumps(sorted(roster)).encode()).hexdigest()}
    if cache_path.is_file():
        cache = json.loads(cache_path.read_text())
        if cache.get('pins') == pins:
            counts = Counter({(dataset, date.fromisoformat(day), meet): count
                              for day, meet, count in cache['date_counts']})
            print(json.dumps({'stage': 'reuse_pinned_raw_verification', 'dataset': dataset}), flush=True)
            return cache['report'], counts
    report, counts = raw_check(dataset, parquet, roster)
    cache = {'pins': pins, 'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'report': report,
             'date_counts': [[day.isoformat(), meet, count] for (_, day, meet), count in sorted(counts.items())]}
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + '\n')
    return report, counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True)
    args = parser.parse_args()
    baseline = safe(args.baseline)
    assert baseline.is_file() and baseline.is_relative_to(CORE / 'backups')
    con = duckdb.connect(str(CORE / 'thoroughbred_core.duckdb'), read_only=True)
    scratch = HERE / 'verification_scratch'
    scratch.mkdir(exist_ok=True)
    con.execute("SET memory_limit='2GB'")
    con.execute('SET threads=2')
    con.execute("SET temp_directory='" + str(scratch).replace("'", "''") + "'")
    con.execute("ATTACH '" + str(baseline).replace("'", "''") + "' AS prior (READ_ONLY)")
    preserved = {}
    for name, kind in con.execute("SELECT table_name,table_type FROM information_schema.tables WHERE table_catalog='prior' AND table_schema='main'").fetchall():
        if name == 'source_manifests':
            continue
        q = ident(name)
        plus = con.execute(f'SELECT count(*) FROM (SELECT * FROM main.{q} EXCEPT ALL SELECT * FROM prior.main.{q})').fetchone()[0]
        minus = con.execute(f'SELECT count(*) FROM (SELECT * FROM prior.main.{q} EXCEPT ALL SELECT * FROM main.{q})').fetchone()[0]
        same_schema = con.execute(f'DESCRIBE main.{q}').fetchall() == con.execute(f'DESCRIBE prior.main.{q}').fetchall()
        preserved[name] = {'kind': kind, 'added': plus, 'lost': minus, 'schema_equal': same_schema}
    roster = {str(row[0]) for row in con.execute("SELECT DISTINCT entity_id_official_string FROM entity_reference_roster WHERE entity_type='horse'").fetchall()}
    raw_reports = {}
    all_dates = Counter()
    payload_parity = {}
    columns = 'sha256(to_json(struct_pack(' + ','.join(ident(field) + ':=' + ident(field) for field in FIELDS) + '))) AS row_digest'
    for dataset in DATASETS:
        parquet = HERE / 'loader/input' / (dataset + '.parquet')
        raw_reports[dataset], counts = cached_raw_check(dataset, parquet, roster)
        all_dates.update(counts)
        query = f'SELECT {columns} FROM training_raw_observations WHERE dataset=? EXCEPT ALL SELECT {columns} FROM read_parquet(?)'
        added = con.execute('SELECT count(*) FROM (' + query + ')', [dataset, str(parquet)]).fetchone()[0]
        query = f'SELECT {columns} FROM read_parquet(?) EXCEPT ALL SELECT {columns} FROM training_raw_observations WHERE dataset=?'
        lost = con.execute('SELECT count(*) FROM (' + query + ')', [str(parquet), dataset]).fetchone()[0]
        payload_parity[dataset] = {'added': added, 'lost': lost}
    coverage = con.execute('SELECT dataset,event_date,meet,coverage_status,selected_capture_id,observed_rows FROM training_capture_coverage').fetchall()
    expected_days = (date(2026, 9, 29) - date(2010, 1, 1)).days + 1
    keys = [tuple(row[:3]) for row in coverage]
    assert len(keys) == len(set(keys)) == expected_days * 2 * 3
    for dataset, event_date, meet, status, capture, observed in coverage:
        assert dataset in DATASETS and meet in ('1', '3')
        assert date(2010, 1, 1) <= event_date <= date(2026, 9, 29)
        assert observed == all_dates[(dataset, event_date, meet)]
        assert status == ('complete_rows' if observed else 'complete_zero_rows') and capture
    source_files = con.execute('SELECT raw_path,raw_sha256,source_page_no,source_row_count,hash_check_status,is_selected FROM training_source_files').fetchall()
    source_hashes = {}
    for path, expected, page_no, row_count, status, selected in source_files:
        if path not in source_hashes:
            source_hashes[path] = sha(safe(path))
        assert source_hashes[path] == expected
        if selected:
            items, actual_page, _, _ = page_items(path)
            assert actual_page == page_no and len(items) == row_count
    manifest = json.loads((CORE / 'manifest.json').read_text())
    prior = json.loads(baseline.with_name('manifest.json').read_text())
    stable = set(prior) - {'database_sha256', 'input_files', 'table_and_view_counts', 'supplement_loads'}
    source_plus = con.execute('SELECT count(*) FROM (SELECT * FROM main.source_manifests EXCEPT ALL SELECT * FROM prior.main.source_manifests)').fetchone()[0]
    source_minus = con.execute('SELECT count(*) FROM (SELECT * FROM prior.main.source_manifests EXCEPT ALL SELECT * FROM main.source_manifests)').fetchone()[0]
    bad_status = con.execute("SELECT count(*) FROM training_raw_observations WHERE availability_status<>'retrospective_training_observation_not_verified_pre_race' OR historical_prerace_eligibility_verified OR physical_venue_status<>'raw_venue_not_adjudicated'").fetchone()[0]
    duplicate_ids = con.execute('SELECT count(*) FROM (SELECT dataset,observation_id,count(*) n FROM training_raw_observations GROUP BY dataset,observation_id HAVING count(*)>1)').fetchone()[0]
    orphan_sources = con.execute('''SELECT count(*) FROM training_raw_observations o WHERE NOT EXISTS (
        SELECT 1 FROM training_source_files s WHERE s.dataset=o.dataset AND s.raw_path=o.raw_path
        AND s.raw_sha256=o.raw_sha256 AND s.capture_id=o.capture_id AND s.source_page_no=o.source_page_no)''').fetchone()[0]
    orphan_coverage = con.execute('''SELECT count(*) FROM training_capture_coverage c WHERE NOT EXISTS (
        SELECT 1 FROM training_source_files s WHERE s.dataset=c.dataset AND s.capture_id=c.selected_capture_id)''').fetchone()[0]
    checks = {
        'all_original_objects_content_preserved': all(r['added'] == r['lost'] == 0 for r in preserved.values()),
        'all_original_schemas_preserved': all(r['schema_equal'] for r in preserved.values()),
        'old_source_manifest_rows_preserved_one_added': source_plus == 1 and source_minus == 0,
        'raw_payload_source_date_meet_id_name_hash_all_checked': True,
        'stored_payload_exactly_matches_all_three_parquets': all(r['added'] == r['lost'] == 0 for r in payload_parity.values()),
        'complete_date_meet_inventory_counts_match_all_raw_rows': True,
        'all_registered_source_hash_page_row_counts_verified': True,
        'retrospective_availability_and_unknown_venue_flags_exact': bad_status == 0,
        'observation_ids_unique_without_discarding_source_rows': duplicate_ids == 0,
        'all_observations_and_date_coverage_trace_to_registered_sources': orphan_sources == orphan_coverage == 0,
        'old_manifest_metadata_inputs_and_loads_preserved': all(manifest[k] == prior[k] for k in stable) and manifest['input_files'][:len(prior['input_files'])] == prior['input_files'] and manifest['supplement_loads'][:len(prior['supplement_loads'])] == prior['supplement_loads'],
        'old_object_counts_preserved': all(manifest['table_and_view_counts'][k] == value for k, value in prior['table_and_view_counts'].items() if k != 'source_manifests'),
        'database_hash_matches_manifest': sha(CORE / 'thoroughbred_core.duckdb') == manifest['database_sha256'],
    }
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'baseline': str(baseline.relative_to(ROOT)), 'checks': checks, 'all_passed': all(checks.values()), 'raw_reports': raw_reports, 'payload_parity': payload_parity, 'coverage_rows': len(coverage), 'source_file_entries': len(source_files), 'preserved_objects': preserved, 'verification_script_sha256': sha(Path(__file__))}
    con.close()
    (HERE / 'root_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'preserved_objects'}, ensure_ascii=False, indent=2))
    assert report['all_passed']


if __name__ == '__main__':
    main()
