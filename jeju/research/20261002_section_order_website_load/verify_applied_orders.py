"""Independently verify approved rank overlays and preservation of source objects."""
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def main():
    before = json.loads((OUT / 'root_before_application.json').read_text())
    source = sqlite3.connect((ROOT / 'jeju/data/jeju_native_core.sqlite3').as_uri() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    for name, sql in before['protected_views'].items():
        assert source.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0] == sql
    assert [dict(r) for r in source.execute('SELECT * FROM race_section_time_reviews ORDER BY api_record_id,field_name')] == before['time_review_rows']
    fingerprint = hashlib.sha256()
    for row in source.execute('SELECT api_record_id,source_artifact_id,record_index,payload_sha256 FROM api_records ORDER BY api_record_id'):
        fingerprint.update(json.dumps(tuple(row), separators=(',', ':')).encode() + b'\n')
    assert fingerprint.hexdigest() == before['api_record_fingerprint']
    for table, key in [('api_records', 'api_record_count'), ('race_result_rows', 'race_result_rows'), ('jeju_race_population_candidates', 'candidate_rows')]:
        assert source.execute('SELECT count(*) FROM ' + table).fetchone()[0] == before[key]
    cases = json.loads((ROOT / 'jeju/research/20261002_section_remaining_review/positive_order_website_correction_candidates.json').read_text())
    mapping = {'S1F': ('sjS1fOrd', 's1f_order'), 'G1F': ('sjG1fOrd', 'g1f_order')}
    # Materialize the joined view once; its two aggregate sources otherwise
    # rescan all candidate rows for every individual case lookup.
    fields = '''api_record_id,race_date,race_number,horse_number,horse_id,
        api4_3_sjS1fOrd_raw,api4_3_sjG1fOrd_raw,
        s1f_order,s1f_order_status,c1_order,c2_order,c3_order,c4_order,
        g1f_order,g1f_order_status,g1f_time_seconds,g1f_time_status'''
    selected_rows = [dict(r) for r in source.execute('SELECT ' + fields + ' FROM jeju_race_postrace_sections_reviewed_2026')]
    selected_by_key = {(r['race_date'],r['race_number'],r['horse_number'],r['horse_id']):r for r in selected_rows}
    assert len(selected_rows) == len(selected_by_key) == 92513
    results = []
    for case in cases:
        field, col = mapping[case['point']]
        row = selected_by_key[(case['date'], case['race_no'], case['program_no'], case['horse_id'])]
        assert row[col] == case['website_order'] and row[col + '_status'] == 'website_corrected'
        assert row['api4_3_' + field + '_raw'] == case['api_order']
        record = source.execute('SELECT payload_json,payload_sha256 FROM api_records WHERE api_record_id=?', (row['api_record_id'],)).fetchone()
        assert hashlib.sha256(record[0].encode()).hexdigest() == record[1]
        assert json.loads(record[0])[field] == case['api_order']
        results.append({'api_record_id': row['api_record_id'], 'date': case['date'], 'race_no': case['race_no'], 'horse_id': case['horse_id'], 'program_no': case['program_no'], 'point': case['point'], 'api_order_preserved': case['api_order'], 'selected_order': row[col], 'selected_status': row[col + '_status']})
    gu, = [r for r in selected_rows if r['api_record_id'] == 191451]
    assert gu['horse_id'] == '3016494' and gu['g1f_time_seconds'] is None
    assert gu['g1f_time_status'] == 'unresolved_official_website_anomaly'
    total, unique = len(selected_rows), len({r['api_record_id'] for r in selected_rows})
    assert total == unique == before['candidate_rows'] == 92513
    assert source.execute('SELECT count(*) FROM race_section_order_reviews').fetchone()[0] == 14
    assert not source.execute('PRAGMA foreign_key_check(race_section_order_reviews)').fetchall()
    assert all(r['horse_id'] != '3005648' for r in selected_rows)
    pages = json.loads((OUT / 'fresh_website/evidence.json').read_text())
    roster_comparisons = 0
    for page in pages:
        if (page['date'], page['race_no']) not in {('2025-10-17', 7), ('2026-03-06', 8)}:
            continue
        selected = {r['horse_number']:r for r in selected_rows if (r['race_date'],r['race_number']) == (page['date'],page['race_no'])}
        table = next(t['rows'] for t in page['tables'] if 'S-1F' in t['rows'][0])
        for web in table[1:]:
            num = int(web[1])
            ranks = [v.strip() for v in web[2].split('-')]
            if len(ranks) == 7 and ranks[-1] == '':
                ranks.pop()
            assert len(ranks) == 6
            for i, col in enumerate(['s1f_order', 'c1_order', 'c2_order', 'c3_order', 'c4_order', 'g1f_order']):
                expected = int(ranks[i]) if ranks[i] else None
                assert selected[num][col] == expected, (page['date'], num, col)
                roster_comparisons += 1
    assert roster_comparisons == 120
    result = {'status': 'passed', 'database_opened_read_only': True, 'corrected_order_fields': 14,
              'selected_view_rows': total, 'selected_view_unique_runner_rows': unique,
              'source_fingerprint_unchanged': True, 'protected_views_and_time_reviews_unchanged': True,
              'target_full_roster_six_point_orders_equal_website': roster_comparisons,
              'guanghae_g1f_null_verified': dict(gu), 'excluded_horse_not_reintroduced': True,
              'cases': results}
    (OUT / 'root_independent_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
