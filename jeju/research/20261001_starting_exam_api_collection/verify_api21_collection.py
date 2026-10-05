"""Independently verify archived annual starting-exam responses and website keys."""
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT.parents[1] / 'data' / 'jeju_native_core.sqlite3'
EXCLUSIONS = ROOT.parents[1] / 'data' / 'horse_exclusions.json'


def main():
    registry = json.loads(EXCLUSIONS.read_text()) if EXCLUSIONS.exists() else {'horses': {}}
    excluded_ids = {h for h, decision in registry['horses'].items()
                    if decision.get('reimport_allowed') is False}
    db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    native = {str(r[0]) for r in db.execute("SELECT horse_id FROM horse_profile_observations WHERE breed_label_raw='제주마'")}
    followup = json.loads((ROOT / 'api42_followup_summary.json').read_text())
    manifest_path = ROOT / followup['manifest']
    for p in json.loads(manifest_path.read_text())['probes']:
        if p.get('status') == 'completed':
            raw = (manifest_path.parent / p['response_file']).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == p['response_sha256']
            item = json.loads(raw)['response']['body']['items']['item']
            items = item if isinstance(item, list) else [item]
            for i in items:
                if str(i['hrNo']) == p['queried_hr_no'] and i.get('breed') == '제주마':
                    native.add(str(i['hrNo']))
    years, rows = [], []
    for year in range(2000, 2027):
        base = ROOT / 'raw/api21_1/partitions' / f'year_{year}' / 'attempts'
        valid = []
        for f in sorted(base.glob('*/attempt_manifest.json')):
            m = json.loads(f.read_text())
            if m.get('status') == 'completed_api_response':
                valid.append((f, m))
        if not valid:
            years.append({'year': year, 'status': 'not_completed'})
            continue
        path, m = valid[-1]
        actual, totals, page_nos = 0, set(), []
        for p in m['source_pages']:
            f = (path.parent / p['response_file']).resolve()
            assert f.is_relative_to(path.parent.resolve())
            raw = f.read_bytes()
            assert hashlib.sha256(raw).hexdigest() == p['response_sha256']
            response = json.loads(raw)['response']
            assert response['header']['resultCode'] in ('00', '0000')
            body = response['body']
            value = (body.get('items') or {}).get('item')
            items = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
            totals.add(int(body['totalCount']))
            page_nos.append(int(body['pageNo']))
            actual += len(items)
            for n, item in enumerate(items, 1):
                assert str(item['trainDate']).startswith(str(year))
                assert item['meet'] == '제주'
                rows.append({'source_path': f.relative_to(ROOT).as_posix(), 'source_row_no': n, 'raw': item})
        assert len(totals) == 1 and actual == next(iter(totals))
        assert page_nos == list(range(1, len(page_nos) + 1))
        years.append({'year': year, 'status': 'verified', 'rows': actual, 'pages': len(page_nos), 'manifest': path.relative_to(ROOT).as_posix()})
    website = json.loads((ROOT / 'website_validation/website_observations.json').read_text())['rows']
    by_key = defaultdict(list)
    for r in rows:
        i = r['raw']
        by_key[(str(i['trainDate']), int(i['trainNo']), str(i.get('chulNo')) if 'chulNo' in i else None, str(i['hrNo']))].append(i)
    discrepancies = []
    field_map = {'hrName': 'horse_name', 'sex': 'sex', 'age': 'age', 'trName': 'trainer', 'owName': 'owner', 'passFlag': 'judgement', 'reason': 'inspection_reason', 'nopassReason': 'failure_reason'}
    for r in website:
        key = (r['date'], r['round'], r['horse_number'], r['horse_id'])
        candidates = by_key[key]
        if len(candidates) != 1:
            discrepancies.append({'key': key, 'api_matches': len(candidates)})
            continue
        i = candidates[0]
        for a, w in field_map.items():
            value = str(i[a])
            if a == 'nopassReason' and value == '-':
                value = ''
            if value != str(r[w]):
                discrepancies.append({'key': key, 'field': a, 'api': value, 'website': r[w]})
    native -= excluded_ids
    linked = [r for r in rows if str(r['raw']['hrNo']) in native]
    user_excluded = [r for r in rows if str(r['raw']['hrNo']) in excluded_ids]
    unlinked = [r for r in rows if str(r['raw']['hrNo']) not in native | excluded_ids]
    output = ROOT / 'api21_verified_native_candidate_rows.jsonl'
    output.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in linked))
    report = {'annual_partitions': years, 'complete_annual_partitions': sum(y['status'] == 'verified' for y in years), 'all_annual_partitions_complete': all(y['status'] == 'verified' for y in years),
              'raw_rows': len(rows), 'raw_date_min': min((str(r['raw']['trainDate']) for r in rows), default=None), 'raw_date_max': max((str(r['raw']['trainDate']) for r in rows), default=None),
              'judgement_counts': dict(Counter(r['raw']['passFlag'] for r in rows)), 'linked_native_rows': len(linked), 'linked_native_horses': len({str(r['raw']['hrNo']) for r in linked}),
              'linked_native_date_min': min((str(r['raw']['trainDate']) for r in linked), default=None), 'linked_native_date_max': max((str(r['raw']['trainDate']) for r in linked), default=None),
              'linked_native_date_round_groups': len({(str(r['raw']['trainDate']), str(r['raw']['trainNo'])) for r in linked}),
              'linked_native_judgement_counts': dict(Counter(r['raw']['passFlag'] for r in linked)),
              'linked_native_field_absence_counts': {f: sum(f not in r['raw'] for r in linked) for f in ('chulNo', 'daySerial', 'rider')},
              'unlinked_rows': len(unlinked), 'unlinked_horse_ids': len({str(r['raw']['hrNo']) for r in unlinked}),
              'user_excluded_rows': len(user_excluded), 'user_excluded_horse_ids': sorted({str(r['raw']['hrNo']) for r in user_excluded}),
              'exclusion_registry': str(EXCLUSIONS.relative_to(ROOT.parents[1])),
              'repeated_date_round_entry_horse_keys': sum(len(v) - 1 for v in by_key.values() if len(v) > 1), 'duplicates_removed': 0, 'website_rows_compared': len(website), 'website_discrepancies': discrepancies,
              'field_absence_counts': {f: sum(f not in r['raw'] for r in rows) for f in ('chulNo', 'daySerial', 'rider', 'hrNo', 'trainDate', 'trainNo', 'passFlag')},
              'website_comparison_note': "Compare 9 identity/result fields; API nopassReason '-' maps to blank only for this comparison. Rider suffix formatting is preserved in source and excluded from exact text comparison.",
              'native_candidate_output': output.name, 'native_candidate_sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'database_write_performed': False}
    (ROOT / 'api21_independent_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'annual_partitions'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
