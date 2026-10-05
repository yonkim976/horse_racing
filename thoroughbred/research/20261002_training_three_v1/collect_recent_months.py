"""Capture four recent monthly training batches; research artifacts only."""
import hashlib
import json
import math
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx
from horse_racing.config import get_settings

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / 'recent_raw'
HOST = 'https://apis.data.go.kr/B551015'
ENDPOINTS = {'daily': '/API18_1/dailyTraining_1', 'start': '/API22_1/startingTranning_1'}
KST = ZoneInfo('Asia/Seoul')


def now():
    return datetime.now(KST).isoformat(timespec='milliseconds')


def save(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    key = get_settings().data_go_kr_service_key
    if key is None:
        raise ValueError('api_credential_unavailable')
    credential = unquote(key.get_secret_value())
    records = []
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        for dataset, endpoint in ENDPOINTS.items():
            for meet in (1, 3):
                batch = {'dataset': dataset, 'endpoint': endpoint, 'meet': meet, 'month': '202609', 'complete': False, 'pages': []}
                page = 1
                total = None
                while total is None or page <= max(1, math.ceil(total / 20000)):
                    path = OUT / f'{dataset}_{meet}_202609_p{page}.json'
                    meta_path = path.with_suffix('.metadata.json')
                    if path.exists() and meta_path.exists():
                        meta = json.loads(meta_path.read_text())
                        content = path.read_bytes()
                        if meta['sha256'] != hashlib.sha256(content).hexdigest():
                            raise ValueError('saved_capture_hash_mismatch')
                    else:
                        time.sleep(1)
                        meta = {'dataset': dataset, 'endpoint': endpoint, 'meet': meet, 'month': '202609', 'page': page, 'requested_at_kst': now(), 'path': str(path.relative_to(ROOT))}
                        try:
                            response = client.get(HOST + endpoint, params={'ServiceKey': credential, 'meet': meet, 'tr_month': '202609', 'pageNo': page, 'numOfRows': 20000, '_type': 'json'})
                        except httpx.HTTPError as exc:
                            raise RuntimeError(type(exc).__name__) from None
                        meta.update({'retrieved_at_kst': now(), 'retrieved_at_basis': 'timestamp_recorded_after_http_response', 'http_status': response.status_code, 'response_bytes': len(response.content)})
                        content = response.content
                        meta['sha256'] = hashlib.sha256(content).hexdigest()
                        path.write_bytes(content)
                        save(meta_path, meta)
                    if meta['http_status'] != 200:
                        raise ValueError('http_status_not_200')
                    payload = json.loads(content)['response']
                    code = str(payload['header']['resultCode'])
                    if code not in {'00', '0000'}:
                        raise ValueError('api_error_' + code[:8])
                    body = payload['body']
                    new_total = int(body['totalCount'])
                    if total is not None and new_total != total:
                        raise ValueError('changing_page_total')
                    total = new_total
                    if int(body['pageNo']) != page or int(body['numOfRows']) != 20000:
                        raise ValueError('pagination_disagrees')
                    items = body.get('items') or {}
                    items = items.get('item') or [] if isinstance(items, dict) else items
                    if isinstance(items, dict):
                        items = [items]
                    if not isinstance(items, list) or len(items) != min(20000, max(0, total - (page - 1) * 20000)):
                        raise ValueError('incomplete_page')
                    for item in items:
                        if not str(item.get('trDate', '')).startswith('202609'):
                            raise ValueError('wrong_month')
                        actual = str(item.get('meet', '')).strip()
                        allowed = {'1', '서울'} if meet == 1 else {'3', '부산경남', '영남'}
                        if actual not in allowed:
                            raise ValueError('wrong_meet')
                    meta.update({'page_size': 20000, 'total_count': total, 'item_count': len(items)})
                    save(meta_path, meta)
                    batch['pages'].append(meta)
                    page += 1
                batch['complete'] = True
                batch['total_count'] = total
                records.append(batch)
                save(OUT / 'capture_manifest.json', {'scope': '20100101..20260929; recent month refresh may include later raw rows, trim at export', 'checked_at_kst': now(), 'records': records})
                print(json.dumps({'dataset': dataset, 'meet': meet, 'month': '202609', 'rows': total, 'pages': len(batch['pages']), 'complete': True}), flush=True)


if __name__ == '__main__':
    main()
