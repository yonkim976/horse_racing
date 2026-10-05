"""Independent literal source-to-Parquet medical observation verification."""
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
START, END = date(2010, 1, 1), date(2026, 9, 29)
LABELS = {'서울': 1, '1': 1, '영남': 3, '부산경남': 3, '부경': 3, '3': 3}


def safe(value):
    path = (ROOT / value).resolve()
    assert path.is_relative_to(ROOT) and path.is_file(), value
    return path


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@lru_cache(maxsize=8)
def raw(path_text):
    payload = safe(path_text).read_bytes()
    return payload, hashlib.sha256(payload).hexdigest()


@lru_cache(maxsize=8)
def text_lines(path_text):
    return raw(path_text)[0].decode('cp949').splitlines()


@lru_cache(maxsize=8)
def api_items(path_text):
    obj = json.loads(raw(path_text)[0])['response']
    assert str(obj['header']['resultCode']) in ('00', '0000')
    body = obj['body']
    items = body.get('items') or {}
    rows = items.get('item') or [] if isinstance(items, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    assert isinstance(rows, list)
    return body, rows


def string(value):
    return None if value is None else str(value)


def main():
    inventory = json.loads((HERE / 'root_text_inventory.json').read_text())
    expected_text = {r['raw_path']: r for r in inventory['files']}
    capture_times = {}
    for line in (ROOT / 'data/raw/kra_text/_manifests/dacom72/manifest.jsonl').read_text().splitlines():
        item = json.loads(line)
        if item.get('status') == 'downloaded' and item.get('local_path') and item.get('sha256') and item.get('retrieved_at_ms'):
            key = (item['local_path'], item['sha256'])
            capture_times.setdefault(key, set()).add(datetime.fromtimestamp(item['retrieved_at_ms'] / 1000, timezone.utc))
    counts, text_counts, api_counts, ids, cohort_counts = Counter(), Counter(), Counter(), set(), Counter()
    text_years = Counter()
    empty_names = []
    rows_total = 0
    inputs = [HERE / 'source' / name for name in ('api16_current_annual_observations.parquet', 'api16_archived_daily_observations.parquet', 'dacom72_observations.parquet')]
    batches = (batch for path in inputs for batch in pq.ParquetFile(path).iter_batches(batch_size=8192))
    for batch in batches:
        for row in batch.to_pylist():
            rows_total += 1
            kind, path = row['source_kind'], row['source_path']
            payload, hash_value = raw(path)
            assert hash_value == row['source_sha256']
            event = date.fromisoformat(row['event_date'])
            assert START <= event <= END and row['meet_code'] in (1, 3)
            cohort_counts[row.get('source_cohort', 'unspecified')] += 1
            counts[kind] += 1
            page, number, line_number = row['page_no'], row['row_no'], row['line_no']
            locator = f"{kind}\0{path}\0{page or ''}\0{number or ''}\0{line_number or ''}"
            assert hashlib.sha256(locator.encode()).hexdigest() == row['source_row_hash']
            assert row['source_row_hash'] not in ids
            ids.add(row['source_row_hash'])
            if kind == 'dacom72':
                assert path in expected_text
                source = expected_text[path]
                assert source['raw_sha256'] == hash_value
                assert row['hr_no_raw'] is None and row['ill_name1_raw'] is None and row['ill_name2_raw'] is None
                assert row['raw_payload_json'] is None and page is None and number is None
                line = text_lines(path)[line_number - 1]
                assert row['raw_line'] == line
                encoded = line.encode('cp949')
                assert len(encoded) == 145 and all(encoded[n:n+1] == b' ' for n in (10, 31, 44))
                day, name, stable, hospital, diagnosis = [encoded[a:b].decode('cp949').strip()
                    for a, b in ((0, 10), (11, 29), (29, 31), (32, 44), (45, 145))]
                assert date.fromisoformat(day.replace('.', '-').replace('/', '-')) == event
                assert row['meet_code'] == int(source['meet'])
                assert row['horse_name_raw'] in (name.strip(), None if not name.strip() else name.strip())
                assert row['stable_no_raw'] == stable and row['hospital_name_raw'] == hospital
                assert row['diagnosis_rpt_raw'] == diagnosis
                assert row['decode_has_replacement'] is False
                assert row['source_captured_at_utc'] is not None
                assert datetime.fromisoformat(row['source_captured_at_utc']) in capture_times[(path, hash_value)]
                assert 'manifest' in row['capture_timestamp_basis']
                text_counts[path] += 1
                text_years[(source['meet'], event.year)] += 1
                if not name.strip():
                    empty_names.append({'path': path, 'line': line_number, 'event_date': str(event)})
            else:
                assert kind.startswith('api16'), kind
                body, items = api_items(path)
                assert int(body['pageNo']) == page
                original = items[number - 1]
                assert json.loads(row['raw_payload_json']) == original
                assert date.fromisoformat(str(original['clinicDate'])) == event
                assert LABELS[str(original['meet'])] == row['meet_code']
                for dest, source in [('horse_name_raw', 'hrName'), ('hr_no_raw', 'hrNo'), ('part_raw', 'part'),
                                     ('hospital_name_raw', 'hospiName'), ('ill_name1_raw', 'illName1'), ('ill_name2_raw', 'illName2')]:
                    assert row[dest] == string(original.get(source)), (dest, path, number)
                assert row['raw_line'] is None and line_number is None and row['diagnosis_rpt_raw'] is None
                api_counts[path] += 1
    assert sum(text_counts.values()) == inventory['scoped_dated_lines']
    for path, source in expected_text.items():
        assert text_counts[path] == source['scoped_dated_lines'], path
    assert len(empty_names) == 2
    expected_api = {}
    api_roots = [HERE / 'source/raw/api16', ROOT / 'data/raw/kra/horse_medical']
    for base in api_roots:
        for path in base.rglob('*.json'):
            if base == api_roots[1] and not any(x in ('meet_1', 'meet_3') for x in path.parts):
                continue
            relative = str(path.relative_to(ROOT))
            _, items = api_items(relative)
            expected_api[relative] = sum(START <= date.fromisoformat(str(r['clinicDate'])) <= END for r in items)
    for path, expected in expected_api.items():
        assert api_counts[path] == expected, path
    assert set(api_counts) <= set(expected_api)
    assert counts == Counter({'api16': 243411, 'api16_archived': 238591, 'dacom72': 1619071})
    result = {'all_passed': True, 'raw_rows_checked': rows_total, 'source_counts': dict(counts),
              'cohort_counts': dict(cohort_counts), 'text_files_checked': len(expected_text),
              'text_rows_checked': sum(text_counts.values()), 'unique_observation_ids': len(ids),
              'empty_text_horse_names': empty_names, 'verification_script_sha256': sha(Path(__file__))}
    result['api_source_files_checked'] = len(expected_api)
    result['input_sha256'] = {str(path.relative_to(ROOT)): sha(path) for path in inputs}
    (HERE / 'root_input_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
