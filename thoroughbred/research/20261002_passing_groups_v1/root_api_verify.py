"""Independent full API303 page and literal observation verification."""
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'api_source'
LABELS = {'서울': 1, '부산': 3, '부경': 3, '부산경남': 3, '영천': 4}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    manifest = json.loads((SOURCE / 'source_manifest.json').read_text())
    for relative, digest in manifest['artifact_sha256'].items():
        assert sha(SOURCE / relative) == digest, relative
    pages = pq.read_table(SOURCE / 'api_page_ledger.parquet').to_pylist()
    observations = pq.read_table(SOURCE / 'api_observations.parquet').to_pylist()
    excluded = pq.read_table(SOURCE / 'api_exclusions.parquet').to_pylist()
    by_page = defaultdict(list)
    for row in observations:
        by_page[row['source_path']].append(row)
    partitions = defaultdict(list)
    seen = set()
    for page in pages:
        path = (SOURCE / page['raw_page_path']).resolve()
        assert path.is_relative_to(SOURCE.resolve())
        raw = path.read_bytes()
        assert len(raw) == page['response_body_bytes']
        assert hashlib.sha256(raw).hexdigest() == page['response_body_sha256']
        obj = json.loads(raw)['response']
        body = obj['body']
        assert page['http_status'] == 200 and str(obj['header']['resultCode']) in ('00', '0000')
        params = json.loads(page['request_public_params_json'])
        assert not any('key' in key.lower() for key in params)
        assert params['meet'] == page['requested_meet']
        assert int(params['rc_year']) == page['requested_year']
        assert int(body['pageNo']) == int(params['pageNo']) == page['reported_page_no']
        assert int(body['numOfRows']) == 1000 == int(params['numOfRows'])
        assert int(body['totalCount']) == page['total_count']
        container = body.get('items') or {}
        items = container.get('item') or [] if isinstance(container, dict) else []
        if isinstance(items, dict):
            items = [items]
        rows = sorted(by_page[page['raw_page_path']], key=lambda row: row['row_no'])
        assert len(items) == page['returned_item_count'] == len(rows)
        assert [row['row_no'] for row in rows] == list(range(1, len(items) + 1))
        for row, original in zip(rows, items):
            locator = (row['source_path'], row['page_no'], row['row_no'])
            assert locator not in seen
            seen.add(locator)
            assert json.loads(row['raw_item_json']) == original
            assert hashlib.sha256(row['raw_item_json'].encode()).hexdigest() == row['source_row_sha256']
            assert json.loads(row['source_fields_present_json']) == list(original)
            assert json.loads(row['source_field_types_json']) == {key: type(value).__name__ for key, value in original.items()}
            assert row['page_sha256'] == page['response_body_sha256']
            assert row['source_captured_at_ms'] == page['retrieved_at_ms']
            assert datetime.fromisoformat(row['source_captured_at_utc']) == datetime.fromtimestamp(page['retrieved_at_ms']/1000, timezone.utc)
            for field in ['meet', *[f'corner_{n}' for n in range(1, 10)], 'passtime_3f', 'passtime_4f', 'tempo']:
                value = original.get(field)
                expected = value if isinstance(value, str) or value is None else json.dumps(value, ensure_ascii=False, separators=(',', ':'))
                assert row[field] == expected, (field, locator)
            assert row['actual_meet_code'] == LABELS.get(str(original.get('meet')).strip())
            for dest, field in [('rc_date_raw_json', 'rcDate'), ('rc_no_raw_json', 'rcNo')]:
                assert (None if row[dest] is None else json.loads(row[dest])) == original.get(field)
            event = date.fromisoformat(row['race_date_iso'])
            assert event.strftime('%Y%m%d') == str(original['rcDate'])
            assert row['rcNo'] == int(original['rcNo']) and row['rcDate'] == int(original['rcDate'])
            assert row['row_scope_status'] == ('in_scope' if date(2010, 1, 1) <= event <= date(2026, 9, 29) and event.year == row['requested_year'] and row['actual_meet_code'] == row['requested_meet'] and row['rcNo'] > 0 else 'excluded')
        partitions[(page['requested_year'], page['requested_meet'])].append(page)
    assert len(partitions) == 35
    assert set(partitions) == {(year, meet) for year in range(2010, 2027) for meet in (1, 3)} | {(2026, 4)}
    for key, part in partitions.items():
        totals = {row['total_count'] for row in part}
        assert len(totals) == 1, key
        total = totals.pop()
        assert sum(row['returned_item_count'] for row in part) == total
        assert sorted(row['reported_page_no'] for row in part) == list(range(1, max(1, (total + 999)//1000) + 1))
    assert excluded == [row for row in observations if row['row_scope_status'] == 'excluded']
    assert sum(len(rows) for rows in by_page.values()) == len(observations)
    keys = Counter((row['actual_meet_code'], row['race_date_iso'], row['rcNo']) for row in observations if row['row_scope_status'] == 'in_scope')
    expected = json.loads((HERE / 'root_expected_confirmed_races.json').read_text())
    corekeys = {(row['meet'], row['event_date'], row['race_no']) for row in expected}
    dispositions = json.loads((HERE / 'root_expected_noncore_keys.json').read_text())
    prior_nonexecution = {(row['meet'], row['event_date'], row['race_no']) for row in dispositions['adjudicated_nonexecution']}
    prior_errors = {(row['meet'], row['event_date'], row['race_no']) for row in dispositions['confirmed_errors']}
    noncore = set(keys)-corekeys
    result = {'all_passed': True, 'raw_pages_checked': len(pages), 'raw_items_checked': len(observations), 'excluded_items_checked': len(excluded),
              'partitions_checked': len(partitions), 'confirmed_keys_present': len(corekeys & set(keys)),
              'confirmed_keys_missing': sorted(corekeys-set(keys)), 'noncore_keys': sorted(set(keys)-corekeys),
              'duplicate_scoped_keys': [list(key)+[count] for key,count in keys.items() if count>1], 'verification_script_sha256': sha(Path(__file__))}
    result['noncore_dispositions'] = {'adjudicated_nonexecution': len(noncore & prior_nonexecution), 'confirmed_error': len(noncore & prior_errors), 'unknown_keys': sorted(noncore-prior_nonexecution-prior_errors)}
    (HERE / 'root_api_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
