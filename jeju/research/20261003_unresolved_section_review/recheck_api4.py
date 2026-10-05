"""Read current API4 results for the fixed unresolved race dates; no DB writes."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, quote_plus

from horse_racing.config import get_settings
from horse_racing.collectors.kra_api import KraApiClient, response_body

OUT = Path(__file__).resolve().parent
CASES = OUT.parent / '20261002_section_remaining_review/remaining_website_internal_order_conflicts.json'
MAP = {'S1F': 'sjS1fOrd', '1C': 'sj_1cOrd', '2C': 'sj_2cOrd',
       '3C': 'sj_3cOrd', '4C': 'sj_4cOrd', 'G1F': 'sjG1fOrd'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    secret = get_settings().data_go_kr_service_key
    if not secret or not secret.get_secret_value().strip():
        print(json.dumps({'status': 'credential_unavailable'}))
        return
    key = secret.get_secret_value()
    variants = [v.encode() for v in (key, quote(key, safe=''), quote_plus(key))]
    cases = json.loads(CASES.read_text())
    dates = sorted({r['date'] for r in cases})
    if args.probe:
        dates = dates[:1]
    run = OUT / 'api4_recheck' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    run.mkdir(parents=True, exist_ok=False)
    records = []
    with KraApiClient(key, base_url='https://apis.data.go.kr/B551015', timeout_seconds=15) as client:
        for date in dates:
            params = {'meet': 2, 'rc_date': date.replace('-', ''), 'pageNo': 1, 'numOfRows': 1000, '_type': 'json'}
            meta = {'date': date, 'public_params': params, 'retrieved_at_utc': datetime.now(timezone.utc).isoformat(), 'operation': 'API4_3/raceResult_3'}
            try:
                page = client._fetch_json('/API4_3/raceResult_3', 'raceResult_3', params)
                if any(v in page.body for v in variants):
                    raise RuntimeError('Secret echoed')
                body = response_body(page.payload)
                items = body.get('items') or {}
                rows = items.get('item', []) if isinstance(items, dict) else []
                rows = [rows] if isinstance(rows, dict) else rows
                if len(rows) != int(body['totalCount']) or not all(str(r['rcDate']) == date.replace('-', '') for r in rows):
                    raise RuntimeError('Incomplete or incorrect date response')
                name = date.replace('-', '') + '.json'
                (run / name).write_bytes(page.body)
                checks = []
                for case in cases:
                    if case['date'] != date:
                        continue
                    found = [r for r in rows if int(r['rcNo']) == int(case['race_no']) and int(r['chulNo']) == int(case['program_no']) and str(r['hrNo']) == case['horse_id']]
                    if len(found) != 1:
                        raise RuntimeError('Horse identity absent or repeated')
                    value = found[0].get(MAP[case['point']])
                    checks.append({'date': date, 'race_no': int(case['race_no']), 'horse_id': case['horse_id'], 'program_no': int(case['program_no']), 'point': case['point'], 'old_api_order': int(case['api4_order']), 'fresh_api_order': value, 'unchanged': value == int(case['api4_order'])})
                meta.update(status='complete', http_status=page.status_code, raw_file=name, sha256=hashlib.sha256(page.body).hexdigest(), bytes=len(page.body), date_rows=len(rows), checks=checks)
            except Exception as exc:
                # Never print exception text: HTTP client errors may contain service keys.
                meta.update(status='failed', error_type=type(exc).__name__)
            records.append(meta)
            (run / 'manifest.json').write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps({k: v for k, v in meta.items() if k not in ('checks', 'public_params')}, ensure_ascii=False), flush=True)
    summary = {'manifest': str((run / 'manifest.json').relative_to(OUT)), 'complete_dates': sum(r['status'] == 'complete' for r in records), 'failed_dates': sum(r['status'] != 'complete' for r in records), 'checked_fields': sum(len(r.get('checks', [])) for r in records), 'changed_fields': sum(not x['unchanged'] for r in records for x in r.get('checks', [])), 'database_modified': False}
    (run / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
