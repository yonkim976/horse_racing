"""Sequential API78 capture of planned race days missing from saved sources.

Writes research raw artifacts only. Never writes application or core databases.
Credentials are sent only to the fixed official HTTPS endpoint and never logged.
"""
import hashlib
import json
import math
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import duckdb
import httpx
from horse_racing.config import get_settings

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / 'historical_raw'
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'
OLD = ROOT / 'thoroughbred/research/20261001_equipment_unobserved_review_v1'
ENDPOINT = 'https://apis.data.go.kr/B551015/API78/chulmainfo'
KST = ZoneInfo('Asia/Seoul')


def now():
    return datetime.now(KST).isoformat(timespec='milliseconds')


def save(path, obj):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def parse(content, page, meet, day):
    payload = json.loads(content)
    response = payload.get('response', {})
    code = str(response.get('header', {}).get('resultCode', ''))
    if code not in ('00', '0000'):
        raise ValueError('api_error_code_' + code[:8])
    body = response.get('body')
    if not isinstance(body, dict):
        raise ValueError('body_absent')
    if int(body.get('pageNo', 0)) != page or int(body.get('numOfRows', 0)) != 1000:
        raise ValueError('page_metadata_mismatch')
    count = int(body.get('totalCount', 0))
    items = body.get('items') or {}
    if isinstance(items, dict):
        items = items.get('item') or []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise ValueError('items_invalid')
    # Dates in API78 are normally Korean display dates; parse explicitly.
    import re
    for item in items:
        text = str(item.get('raceDt', ''))
        m = re.search(r'(\d{4})\D+(\d{1,2})\D+(\d{1,2})', text)
        actual = ''.join((m[1], m[2].zfill(2), m[3].zfill(2))) if m else ''.join(re.findall(r'\d', text))[:8]
        if actual != day:
            raise ValueError('response_date_mismatch')
    expected = min(1000, max(0, count - (page - 1) * 1000))
    if len(items) != expected:
        raise ValueError('response_page_incomplete')
    return count, items


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(CORE), read_only=True)
    target = {(int(m), d.replace('-', '')) for m, d in con.execute("SELECT DISTINCT meet,date FROM race_plan WHERE meet IN ('1','3','4') AND replace(date,'-','') BETWEEN '20100101' AND '20260929'").fetchall()}
    con.close()
    op = sqlite3.connect((ROOT / 'data/horse_racing.sqlite3').as_uri() + '?mode=ro', uri=True)
    op.execute('PRAGMA query_only=ON'); op.execute('BEGIN')
    saved = set()
    for (params,) in op.execute("SELECT request_params_json FROM source_documents WHERE endpoint='/API78/chulmainfo' AND http_status_code=200"):
        x = json.loads(params or '{}')
        try:
            saved.add((int(x['rccrs_cd']), str(x['race_dt']).replace('-', '')))
        except (KeyError, TypeError, ValueError):
            continue
    op.close()
    wanted = sorted(target - saved, key=lambda x: (x[1], x[0]))
    save(OUT / 'targets.json', {'scope': '20100101..20260929; planned days; meets1/3/4', 'planned_date_meets': len(target), 'already_saved_date_meets': len(target & saved), 'targets': [{'meet': m, 'date': d} for m, d in wanted]})
    prior = json.loads((OLD / 'official_checks.json').read_text())
    reusable = {(int(r['meet']), r['date'].replace('-', '')): r for r in prior['historical_api78_samples'] + prior['live_api78']}
    settings = get_settings()
    key = unquote(settings.data_go_kr_service_key.get_secret_value())
    if not key:
        raise ValueError('api_credential_unavailable')
    records = []; requests = 0
    with httpx.Client(timeout=35, follow_redirects=False) as client:
        for meet, day in wanted:
            pages = []; page = 1; total = None; failure = None
            while total is None or page <= max(1, math.ceil(total / 1000)):
                stem = f'api78_{meet}_{day}_p{page}'
                raw = OUT / (stem + '.json'); metadata = OUT / (stem + '.metadata.json')
                try:
                    if raw.exists() and metadata.exists():
                        meta = json.loads(metadata.read_text()); content = raw.read_bytes()
                        if meta.get('http_status') != 200 or hashlib.sha256(content).hexdigest() != meta.get('sha256'):
                            raise ValueError('saved_capture_hash_mismatch')
                    elif page == 1 and (meet, day) in reusable:
                        source = reusable[(meet, day)]['metadata']
                        path = (ROOT / source['artifact']).resolve()
                        if not path.is_relative_to(OLD / 'official'):
                            raise ValueError('prior_capture_path_invalid')
                        content = path.read_bytes()
                        if hashlib.sha256(content).hexdigest() != source['sha256']:
                            raise ValueError('prior_capture_hash_mismatch')
                        meta = {**source, 'artifact': str(raw.relative_to(ROOT)), 'reused_from': source['artifact']}
                        raw.write_bytes(content); save(metadata, meta)
                    else:
                        time.sleep(1.0)
                        meta = {'source_url': ENDPOINT, 'source': 'API78', 'meet': meet, 'date': day, 'page': page, 'page_size': 1000, 'requested_at_kst': now(), 'artifact': str(raw.relative_to(ROOT))}
                        response = client.get(ENDPOINT, params={'serviceKey': key, 'rccrs_cd': meet, 'race_dt': day, 'pageNo': page, 'numOfRows': 1000, '_type': 'json'})
                        requests += 1
                        meta.update({'retrieved_at_kst': now(), 'retrieved_at_basis': 'timestamp_recorded_after_http_response', 'http_status': response.status_code})
                        content = response.content
                        meta['sha256'] = hashlib.sha256(content).hexdigest()
                        raw.write_bytes(content); save(metadata, meta)
                        if response.status_code != 200:
                            raise ValueError('http_status_' + str(response.status_code))
                    count, items = parse(content, page, meet, day)
                    if total is not None and total != count:
                        raise ValueError('total_count_changed_between_pages')
                    total = count
                    meta.update({'meet': meet, 'date': day, 'page': page, 'page_size': 1000, 'total_count': count, 'item_count': len(items)})
                    save(metadata, meta)
                    pages.append(meta); page += 1
                except Exception as exc:
                    # Never echo HTTP exceptions, which may contain a credential URL.
                    failure = str(exc) if type(exc) is ValueError else type(exc).__name__
                    break
            record = {'meet': meet, 'date': day, 'complete': failure is None, 'total_count': total, 'pages': pages, 'error': failure}
            records.append(record)
            summary = {'checked_at_kst': now(), 'target_date_meets': len(wanted), 'processed_date_meets': len(records), 'complete_date_meets': sum(x['complete'] for x in records), 'request_count_this_run': requests, 'records': records}
            save(OUT / 'capture_manifest.json', summary)
            if len(records) % 20 == 0 or failure:
                print(json.dumps({k: v for k, v in summary.items() if k != 'records'}, ensure_ascii=False), flush=True)
            if failure and any(s in failure for s in ['http_status_403', 'http_status_429', 'api_error_code_22', 'api_error_code_23', 'api_error_code_29']):
                print('Stopped on official API access/rate restriction', flush=True)
                break
    print(json.dumps({k: v for k, v in summary.items() if k != 'records'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
