"""Independent read-only API21/raw/input/core and baseline preservation audit."""
import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'
FIELDS = ('dataset', 'observation_id', 'event_date', 'meet', 'official_horse_id', 'raw_name',
          'raw_path', 'raw_sha256', 'source_page_no', 'source_row_no', 'source_captured_at',
          'capture_basis', 'endpoint', 'raw_payload_json', 'typed_fields_json', 'link_status',
          'linked_core_horse_id', 'qa_flags_json', 'capture_id')
START, END = date(2010, 1, 1), date(2026, 9, 29)
LABELS = {'1': '1', '서울': '1', '3': '3', '부산경남': '3', '부경': '3', '영남': '3'}


def safe_path(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Path escapes workspace')
    return path


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def qi(value):
    return '"' + value.replace('"', '""') + '"'


def digest(columns):
    return 'sha256(to_json(struct_pack(' + ','.join(qi(c) + ':=' + qi(c) for c in columns) + ')))'


@lru_cache(maxsize=4)
def page(path_text):
    obj = json.loads(safe_path(path_text).read_bytes())['response']
    assert str(obj['header']['resultCode']) in ('00', '0000')
    body = obj['body']
    items = body.get('items') or {}
    rows = items.get('item') or [] if isinstance(items, dict) else items
    if isinstance(rows, dict):
        rows = [rows]
    assert isinstance(rows, list)
    return rows, int(body['pageNo']), int(body['totalCount']), int(body['numOfRows'])


def compare(con, left, right, columns):
    expression = digest(columns)
    plus = con.execute(f'SELECT count(*) FROM (SELECT {expression} FROM {left} EXCEPT ALL SELECT {expression} FROM {right})').fetchone()[0]
    minus = con.execute(f'SELECT count(*) FROM (SELECT {expression} FROM {right} EXCEPT ALL SELECT {expression} FROM {left})').fetchone()[0]
    return {'added': plus, 'lost': minus}


def verify_capture():
    manifest = json.loads((HERE / 'raw/capture_manifest.json').read_text())
    coverage = json.loads((HERE / 'raw/coverage_summary.json').read_text())
    assert manifest['dataset'] == 'starting_exam' and manifest['endpoint'] == 'API21_1'
    assert sha(safe_path(manifest['parquet_path'])) == manifest['parquet_sha256']
    sources = {s['raw_path']: s for s in manifest['source_files'] if s.get('is_selected', True)}
    assert len(sources) == len(manifest['source_files'])
    assert {(p['year'], p['meet']) for p in coverage['partitions']} == {(y,m) for y in range(2010,2027) for m in ('1','3')}
    assert len(coverage['partitions']) == 34
    scoped, outside, pass_flags, dates, source_refs = Counter(), Counter(), Counter(), Counter(), set()
    for partition in coverage['partitions']:
        assert partition['status'] in ('complete', 'zero') and not partition.get('failure_class')
        paths = partition['source_files']
        expected = partition['total_count']
        size = partition['page_size']
        assert len(paths) == max(1, math.ceil(expected / size)) == partition['page_count']
        total = 0
        for index, path in enumerate(paths, 1):
            source = sources[path]
            assert source['year'] == partition['year'] and source['meet'] == partition['meet']
            assert sha(safe_path(path)) == source['raw_sha256']
            rows, page_no, page_total, page_size = page(path)
            assert page_no == index == source['source_page_no'] and page_total == expected and page_size == size
            assert len(rows) == min(size,max(0,expected-(index-1)*size)) == source['source_row_count']
            total += len(rows)
            for row_no, raw in enumerate(rows,1):
                event_date = date.fromisoformat(str(raw['trainDate']))
                assert event_date.year == partition['year']
                assert LABELS[str(raw['meet']).strip()] == partition['meet']
                if START <= event_date <= END:
                    scoped[partition['meet']] += 1
                    dates[(event_date,partition['meet'])] += 1
                    pass_flags[str(raw.get('passFlag'))] += 1
                    source_refs.add((path,index,row_no))
                else:
                    outside[partition['meet']] += 1
        assert total == expected == partition['observed_row_count']
        assert (expected == 0) == (partition['status'] == 'zero')
    assert sum(scoped.values()) == manifest['row_count']
    return {'partition_count':34,'raw_page_count':len(sources),'scoped_rows_by_meet':dict(scoped),
            'outside_scope_rows_by_meet':dict(outside),'raw_pass_flags':dict(pass_flags)}, source_refs, dates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True)
    args = parser.parse_args()
    baseline = safe_path(args.baseline)
    assert baseline.is_relative_to(CORE / 'backups') and baseline.is_file()
    con = duckdb.connect(str(CORE / 'thoroughbred_core.duckdb'), read_only=True)
    con.execute("SET memory_limit='2GB'")
    con.execute('SET threads=2')
    con.execute('SET preserve_insertion_order=false')
    scratch = HERE / 'verification_scratch'
    scratch.mkdir(exist_ok=True)
    con.execute('SET temp_directory=' + "'" + str(scratch).replace("'", "''") + "'")
    con.execute("ATTACH '" + str(baseline).replace("'", "''") + "' AS prior (READ_ONLY)")
    roster = {r[0] for r in con.execute("SELECT entity_id_official_string FROM entity_reference_roster WHERE entity_type='horse'").fetchall()}
    capture_report, expected_refs, expected_dates = verify_capture()
    capture_manifest = json.loads((HERE / 'raw/capture_manifest.json').read_text())
    sources = {s['raw_path']: s for s in capture_manifest['source_files']}
    observed_refs, observation_ids = set(), set()
    qa_flags, natural_keys, horse_ids = Counter(), {}, set()
    raw_stats, dates, pass_flags, links, hashes = Counter(), Counter(), Counter(), Counter(), {}
    parquet = HERE / 'input/starting_exam.parquet'
    for batch in pq.ParquetFile(parquet).iter_batches(batch_size=8192):
        for row in batch.to_pylist():
            assert row['dataset'] == 'starting_exam' and row['endpoint'] == 'API21_1'
            assert START <= row['event_date'] <= END and row['meet'] in ('1', '3')
            path = row['raw_path']
            if path not in hashes:
                hashes[path] = sha(safe_path(path))
            assert hashes[path] == row['raw_sha256']
            rows, page_no, _, page_size = page(path)
            assert page_no == row['source_page_no'] and len(rows) <= page_size
            assert 1 <= row['source_row_no'] <= len(rows)
            raw = json.loads(row['raw_payload_json'])
            assert raw == rows[row['source_row_no'] - 1]
            assert json.loads(row['typed_fields_json']) == raw
            assert date.fromisoformat(str(raw['trainDate'])) == row['event_date']
            assert LABELS[str(raw['meet']).strip()] == row['meet']
            expected_id = None if raw.get('hrNo') in (None, '', '-') else str(raw['hrNo'])
            assert row['official_horse_id'] == expected_id
            assert row['raw_name'] == (None if raw.get('hrName') is None else str(raw['hrName']))
            assert row['capture_id'] == sources[path]['capture_id']
            assert row['source_captured_at'] == datetime.fromisoformat(sources[path]['retrieved_at_utc']).astimezone(timezone.utc).replace(tzinfo=None)
            expected_link = expected_id if expected_id in roster else None
            assert row['linked_core_horse_id'] == expected_link
            expected_status = 'exact_core_roster_match' if expected_link is not None else ('missing_official_id' if expected_id is None else 'unmatched_official_id')
            assert row['link_status'] == expected_status
            assert row['observation_id'] not in observation_ids
            observation_ids.add(row['observation_id'])
            observed_refs.add((path,page_no,row['source_row_no']))
            flags = json.loads(row['qa_flags_json'])
            assert isinstance(flags,list) and all(isinstance(f,str) for f in flags)
            qa_flags.update(flags)
            key_values = [raw['trainDate'],row['meet'],raw.get('daySerial'),raw.get('trainNo'),raw.get('chulNo'),raw.get('hrNo')]
            if any(v in (None,'','-') for v in key_values):
                assert 'natural_key_has_missing_component' in flags
            else:
                key = tuple(str(v) for v in key_values)
                natural_keys.setdefault(key,[]).append((hashlib.sha256(row['raw_payload_json'].encode()).hexdigest(),flags))
            if expected_id is not None:
                horse_ids.add(expected_id)
            links[row['link_status']] += 1
            pass_flags[str(raw.get('passFlag'))] += 1
            dates[(row['event_date'], row['meet'])] += 1
            raw_stats['rows'] += 1
    assert observed_refs == expected_refs and raw_stats['rows'] == len(expected_refs)
    assert dates == expected_dates
    assert pass_flags == Counter(capture_report['raw_pass_flags'])
    for values in natural_keys.values():
        if len(values)>1:
            expected_flag = 'exact_natural_key_payload_repeat' if len({v[0] for v in values})==1 else 'natural_key_payload_variant'
            assert all(expected_flag in v[1] for v in values)
        else:
            assert not any(f in ('exact_natural_key_payload_repeat','natural_key_payload_variant') for f in values[0][1])
    assert con.execute("SELECT count(*) FROM starting_exam_observations WHERE historical_prerace_eligibility_verified OR availability_status NOT LIKE '%not_verified_pre_race%' OR physical_venue_status IS NULL").fetchone()[0] == 0
    assert con.execute('SELECT count(*) FROM starting_exam_results').fetchone()[0] == raw_stats['rows']
    assert con.execute('SELECT count(*) FROM starting_exam_qa').fetchone()[0] == raw_stats['rows']
    calendar = con.execute('SELECT event_date,meet,observed_rows,coverage_status FROM starting_exam_date_coverage').fetchall()
    assert len(calendar) == ((END-START).days+1)*2
    assert len({(r[0],r[1]) for r in calendar}) == len(calendar)
    for event_date, meet, rows, status in calendar:
        assert START <= event_date <= END and meet in ('1','3')
        assert rows == dates[(event_date,meet)]
        assert status == ('complete_rows' if rows else 'complete_zero_rows')
    part_rows = con.execute('SELECT capture_year,meet,coverage_status,expected_rows,observed_rows,page_count FROM starting_exam_partition_coverage').fetchall()
    coverage_doc = json.loads((HERE / 'raw/coverage_summary.json').read_text())
    assert set(part_rows) == {(p['year'],p['meet'],p['status'],p['total_count'],p['observed_row_count'],p['page_count']) for p in coverage_doc['partitions']}
    file_rows = con.execute('SELECT raw_path,raw_sha256,source_row_count,page_total_count,page_item_count,page_size,is_selected,hash_check_status FROM starting_exam_source_files').fetchall()
    assert len(file_rows) == len(sources)
    for path, hash_value, rows, total, item_size, size, selected, checked in file_rows:
        source = sources[path]
        assert (hash_value,rows,total,item_size,size,selected,checked) == (source['raw_sha256'],source['source_row_count'],source['page_total_count'],source['page_item_count'],source['page_size'],True,'verified')
    role_rosters = {}
    for role, identifier in con.execute('SELECT entity_type,entity_id_official_string FROM entity_reference_roster').fetchall():
        role_rosters.setdefault(role,set()).add(identifier)
    role_counts = Counter()
    for role, source_name, source_id, status, linked in con.execute('SELECT entity_role,source_name,source_official_id,link_status,linked_core_official_id FROM starting_exam_entity_links').fetchall():
        assert role in ('horse','trainer','owner')
        if source_id in (None,''):
            expected = 'missing_official_id'
        elif role == 'trainer' and (source_id in ('-','0AAAAA') or source_name == '휴양마'):
            expected = 'placeholder_source_value'
        elif role == 'owner' and (source_id == '-' or source_name == '-'):
            expected = 'placeholder_source_value'
        else:
            expected = 'exact_core_roster_match' if source_id in role_rosters[role] else 'unmatched_official_id'
        assert status == expected and linked == (source_id if expected == 'exact_core_roster_match' else None)
        role_counts[(role,status)] += 1
    assert sum(role_counts.values()) == raw_stats['rows']*3
    print(json.dumps({'stage':'independent_raw_check_passed','rows':raw_stats['rows']}), flush=True)
    parity = compare(con, 'starting_exam_observations', "read_parquet('" + str(parquet).replace("'", "''") + "')", FIELDS)
    assert parity == {'added':0, 'lost':0}
    print(json.dumps({'stage':'core_input_row_digest_parity_passed'}), flush=True)
    preserved = {}
    prior_objects = con.execute("SELECT table_name,table_type FROM information_schema.tables WHERE table_catalog='prior' AND table_schema='main'").fetchall()
    current_views = dict(con.execute("SELECT view_name,sql FROM duckdb_views() WHERE database_name=current_database() AND schema_name='main'").fetchall())
    prior_views = dict(con.execute("SELECT view_name,sql FROM duckdb_views() WHERE database_name='prior' AND schema_name='main'").fetchall())
    for name, kind in prior_objects:
        if name == 'source_manifests':
            continue
        schema_ok = con.execute('DESCRIBE main.' + qi(name)).fetchall() == con.execute('DESCRIBE prior.main.' + qi(name)).fetchall()
        if kind == 'VIEW':
            result = {'definition_equal':current_views[name] == prior_views[name]}
        else:
            cols = [r[0] for r in con.execute('DESCRIBE prior.main.' + qi(name)).fetchall()]
            result = compare(con, 'main.' + qi(name), 'prior.main.' + qi(name), cols)
        result['schema_equal'] = schema_ok
        preserved[name] = result
        assert schema_ok and (result.get('definition_equal', True)) and result.get('added',0) == result.get('lost',0) == 0, name
        print(json.dumps({'stage':'baseline_preserved','object':name,'kind':kind}), flush=True)
    delta = con.execute('SELECT count(*) FROM (SELECT * FROM source_manifests EXCEPT ALL SELECT * FROM prior.main.source_manifests)').fetchone()[0]
    lost = con.execute('SELECT count(*) FROM (SELECT * FROM prior.main.source_manifests EXCEPT ALL SELECT * FROM source_manifests)').fetchone()[0]
    assert (delta,lost) == (1,0)
    manifest = json.loads((CORE / 'manifest.json').read_text())
    old_manifest = json.loads(baseline.with_name('manifest.json').read_text())
    for key in set(old_manifest) - {'database_sha256','input_files','table_and_view_counts','supplement_loads'}:
        assert manifest[key] == old_manifest[key], key
    assert manifest['input_files'][:len(old_manifest['input_files'])] == old_manifest['input_files']
    assert manifest['supplement_loads'][:len(old_manifest['supplement_loads'])] == old_manifest['supplement_loads']
    for key,value in old_manifest['table_and_view_counts'].items():
        if key != 'source_manifests':
            assert manifest['table_and_view_counts'][key] == value
    con.close()
    assert sha(CORE / 'thoroughbred_core.duckdb') == manifest['database_sha256']
    report = {'all_passed':True,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
              'raw_capture':capture_report,'raw_rows':raw_stats['rows'],'source_files_with_observations':len(hashes),'pass_flags':dict(pass_flags),
              'role_link_counts':{':'.join(k):v for k,v in role_counts.items()},'date_coverage_cells':len(calendar),
              'qa_flag_counts':dict(qa_flags),'distinct_official_horse_ids':len(horse_ids),
              'link_status_counts':dict(links),'observed_date_meet_count':len(dates),'core_input_row_digest_parity':parity,
              'original_objects_preserved':preserved,'source_manifest_append':delta,'source_manifest_lost':lost,
              'comparison_method':'SHA-256 of all typed table columns; exact schemas/view definitions; unchanged underlying tables prove old view data unchanged',
              'database_sha256':manifest['database_sha256'],'verification_script_sha256':sha(Path(__file__))}
    (HERE / 'root_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'original_objects_preserved'},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
