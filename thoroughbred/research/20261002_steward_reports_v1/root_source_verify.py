"""Independent raw API pages -> staged observations and research coverage audit."""
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = HERE / 'source'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    rows = pq.read_table(SOURCE / 'api_observations.parquet').to_pylist()
    pages = pq.read_table(SOURCE / 'api_page_ledger.parquet').to_pylist()
    exclusions = pq.read_table(SOURCE / 'api_exclusions.parquet').to_pylist()
    by_page = defaultdict(list)
    for row in rows:
        by_page[row['source_path']].append(row)
    partition = defaultdict(list)
    checked = 0
    for page in pages:
        path = SOURCE / page['raw_page_path']
        assert path.resolve().is_relative_to(SOURCE.resolve())
        assert path.stat().st_size == page['response_body_bytes']
        assert sha(path) == page['response_body_sha256']
        response = json.loads(path.read_bytes())['response']
        assert str(response['header']['resultCode']) == '00'
        body = response['body']
        items = body.get('items') or {}
        items = items.get('item') or []
        if isinstance(items, dict):
            items = [items]
        observed = sorted(by_page[page['raw_page_path']], key=lambda r: r['row_no'])
        assert len(items) == len(observed) == page['returned_item_count']
        assert page['http_status'] == 200
        assert int(body['totalCount']) == page['total_count']
        assert int(body['pageNo']) == page['reported_page_no']
        assert int(body['numOfRows']) == page['requested_num_of_rows'] == 1000
        params = json.loads(page['request_public_params_json'])
        assert not any('key' in k.lower() for k in params)
        assert params['meet'] == page['requested_meet']
        assert int(params['rc_year']) == page['requested_year']
        assert params['pageNo'] == page['reported_page_no']
        partition[page['dataset'], page['requested_year'], page['requested_meet']].append(page)
        for i, (raw, row) in enumerate(zip(items, observed), 1):
            assert json.loads(row['raw_item_json']) == raw
            assert row['row_no'] == i
            assert json.loads(row['source_fields_present_json']) == sorted(raw)
            assert json.loads(row['source_field_types_json']) == {k: type(v).__name__ for k, v in raw.items()}
            assert hashlib.sha256(row['raw_item_json'].encode()).hexdigest() == row['source_row_sha256']
            assert row['page_sha256'] == page['response_body_sha256']
            assert row['source_captured_at_ms'] == page['retrieved_at_ms'] >= page['requested_at_ms']
            for field in ('judgement', 'addJudgement', 'jkChange', 'prNo', 'prName', 'gubun', 'kind', 'reason'):
                if isinstance(raw.get(field), str):
                    assert row[field] == raw[field], (field, row['source_location'])
            assert row['actual_meet_code'] == {'서울': 1, '부경': 3, '부산': 3, '부산경남': 3, '영천': 4}.get(raw.get('meet'))
            assert str(row['rcDate']) == str(raw['rcDate'])
            assert str(row['rcNo']) == str(raw['rcNo'])
            if row['row_scope_status'] == 'included':
                assert '2010-01-01' <= row['race_date_iso'] <= '2026-09-29'
                assert row['actual_meet_code'] == row['requested_meet'] in (1, 3, 4)
                assert int(row['race_date_iso'][:4]) == row['requested_year']
            else:
                assert json.loads(row['exclusion_reasons_json'])
            checked += 1
    assert checked == len(rows)
    expected_partitions = {(dataset, year, meet) for dataset in ('api215_judge_report', 'api180_1_sanction_history') for year in range(2010, 2027) for meet in (1, 3)}
    expected_partitions |= {(dataset, 2026, 4) for dataset in ('api215_judge_report', 'api180_1_sanction_history')}
    assert set(partition) == expected_partitions
    summary = []
    for key, records in sorted(partition.items()):
        total = records[0]['total_count']
        assert len({p['total_count'] for p in records}) == 1
        assert len(records) == max(1, math.ceil(total / 1000))
        assert sorted(p['reported_page_no'] for p in records) == list(range(1, len(records) + 1))
        assert sum(p['returned_item_count'] for p in records) == total
        summary.append({'dataset': key[0], 'year': key[1], 'meet': key[2], 'pages': len(records), 'rows': total})
    def row_hash(row):
        return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert Counter(map(row_hash, exclusions)) == Counter(row_hash(r) for r in rows if r['row_scope_status'] != 'included')
    con = duckdb.connect(str(ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'), read_only=True)
    confirmed = {f'{m}:{d.isoformat()}:{int(n)}' for m, d, n in con.execute('SELECT source_meet,race_date,result_race_no_key FROM confirmed_races').fetchall()}
    report_keys = {r['race_key'] for r in rows if r['dataset'] == 'api215_judge_report' and r['row_scope_status'] == 'included'}
    con.close()
    report = {'all_passed': True, 'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'raw_pages_checked': len(pages),
              'exact_source_rows_checked': checked, 'partition_count': len(partition), 'partitions': summary,
              'excluded_rows': len(exclusions), 'rows_by_dataset': dict(Counter(r['dataset'] for r in rows)),
              'report_keys': len(report_keys), 'confirmed_report_keys': len(confirmed & report_keys),
              'confirmed_report_gaps': len(confirmed - report_keys), 'report_keys_outside_confirmed': len(report_keys - confirmed),
              'input_sha256': {p.name: sha(p) for p in SOURCE.glob('*.parquet')}}
    (HERE / 'root_source_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('partitions', 'input_sha256')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
