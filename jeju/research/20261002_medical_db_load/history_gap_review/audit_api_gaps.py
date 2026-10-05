from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO = Path('/Users/kimyongjin/Desktop/horse_racing')
OUT = Path('/private/tmp/jeju_medical_20261002/history_gap_review')
API_ROOT = OUT / 'api_recheck'
MANIFEST_PATH = API_ROOT / 'api_gap_recheck_manifest.json'
BASE_URL = 'https://apis.data.go.kr/B551015'
ENDPOINT = '/API16_1/raceHorseClinic_1'
OPERATION = 'raceHorseClinic_1'
GAP_YEARS = (2002, 2003, 2004, 2005, 2006, 2007, 2009, 2010, 2011)
MEET = 2
PAGE_SIZE = 1000
MAX_ATTEMPTS = 3  # One initial request plus at most two transient retries.
MIN_REQUEST_GAP_SECONDS = 1.2
CUTOFF = '20260919'

sys.path.insert(0, str(REPO / 'src'))
sys.path.insert(0, str(REPO / 'jeju/research/20260929_api_detail_sources'))
from horse_racing.collectors.kra_api import (  # noqa: E402
    KraApiClient,
    KraApiRateLimitError,
    KraApiTransientError,
    RACE_HORSE_CLINIC_ENDPOINT,
    RACE_HORSE_CLINIC_OPERATION,
    response_body,
)
from horse_racing.config import get_settings  # noqa: E402
from collect_annual_clinic_judgement_start_training import (  # noqa: E402
    contains_key,
    extract_rows,
    fetch_once_without_client_retries,
    safe_exception_diagnostics,
)


def read_manifest() -> dict[str, Any]:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    return {
        'source': 'KRA official OpenAPI via data.go.kr/B551015',
        'endpoint': ENDPOINT,
        'operation': OPERATION,
        'meet': MEET,
        'filter_field': 'clinic_year',
        'row_date_field': 'clinicDate',
        'requested_years': list(GAP_YEARS),
        'page_size': PAGE_SIZE,
        'credential_recorded': False,
        'retry_policy': {
            'max_transient_retries': MAX_ATTEMPTS - 1,
            'min_interval_seconds_between_requests': MIN_REQUEST_GAP_SECONDS,
            'rate_limit_retry': False,
        },
        'years': {},
    }


def write_manifest(manifest: dict[str, Any]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, MANIFEST_PATH)


def prior_last_request_ms(manifest: dict[str, Any]) -> int | None:
    values: list[int] = []
    for year in manifest.get('years', {}).values():
        for attempt in year.get('attempts', []):
            v = attempt.get('completed_at_ms')
            if isinstance(v, int):
                values.append(v)
        for page in year.get('pages', []):
            v = page.get('retrieved_at_ms')
            if isinstance(v, int):
                values.append(v)
    return max(values) if values else None


def wait_for_request_gap(last_ms: int | None) -> None:
    if last_ms is None:
        return
    elapsed = (time.time_ns() // 1_000_000 - last_ms) / 1000
    if elapsed < MIN_REQUEST_GAP_SECONDS:
        time.sleep(MIN_REQUEST_GAP_SECONDS - elapsed)


def current_header(payload: dict[str, Any]) -> dict[str, Any]:
    root = payload.get('response', payload)
    if not isinstance(root, dict):
        return {}
    header = root.get('header') or {}
    return header if isinstance(header, dict) else {}


def row_date(row: dict[str, Any]) -> str:
    value = str(row.get('clinicDate') or '').strip()
    digits = ''.join(ch for ch in value if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ''


def page_metadata(year: int, page_no: int, fetched: Any, attempts_used: int, service_key: str) -> dict[str, Any]:
    if contains_key(fetched.body, service_key):
        raise RuntimeError('credential_echo_in_response')
    if not fetched.source_url.startswith(BASE_URL + ENDPOINT + '?'):
        raise RuntimeError('unexpected_redacted_source_origin')
    payload = fetched.payload
    body = response_body(payload)
    rows = extract_rows(payload)
    total = int(body.get('totalCount') or 0)
    size = int(body.get('numOfRows') or PAGE_SIZE)
    returned_page = int(body.get('pageNo') or page_no)
    if returned_page != page_no:
        raise RuntimeError('returned_page_number_mismatch')
    dates = [row_date(r) for r in rows]
    valid = [d for d in dates if d]
    expected_pages = max(1, math.ceil(total / max(size, 1)))
    page_rel = Path('raw') / 'clinic' / f'year={year}' / f'page_{page_no:04d}.json'
    page_path = API_ROOT / page_rel
    page_path.parent.mkdir(parents=True, exist_ok=True)
    with page_path.open('xb') as stream:
        stream.write(fetched.body)
        stream.flush()
        os.fsync(stream.fileno())
    header = current_header(payload)
    return {
        'page_no': page_no,
        'http_status': fetched.status_code,
        'content_type': fetched.content_type,
        'requested_at_ms': fetched.requested_at_ms,
        'retrieved_at_ms': fetched.retrieved_at_ms,
        'public_params': {
            'meet': MEET,
            'clinic_year': str(year),
            '_type': 'json',
            'pageNo': page_no,
            'numOfRows': PAGE_SIZE,
        },
        'api_result_code': str(header.get('resultCode') or ''),
        'api_total_count': total,
        'api_page_size': size,
        'api_reported_page_no': returned_page,
        'actual_page_rows': len(rows),
        'expected_page_count': expected_pages,
        'rows_matching_requested_year': sum(d.startswith(str(year)) for d in valid),
        'rows_with_unparseable_date': len(dates) - len(valid),
        'rows_after_cutoff': sum(d > CUTOFF for d in valid),
        'date_min': min(valid) if valid else None,
        'date_max': max(valid) if valid else None,
        'response_bytes': len(fetched.body),
        'response_sha256': hashlib.sha256(fetched.body).hexdigest(),
        'response_file': str(page_rel),
        'attempts_used': attempts_used,
        'sample_rows': [
            {key: row.get(key) for key in ('clinicDate', 'hrNo', 'hrName', 'hospiName', 'illName1', 'illName2', 'meet', 'part')}
            for row in rows[:3]
        ],
    }


def make_client(service_key: str, timeout_seconds: float) -> KraApiClient:
    client = KraApiClient(service_key, base_url=BASE_URL, timeout_seconds=timeout_seconds)
    client._client.close()
    # Keep certificate verification enabled and prevent a redirect from carrying the key elsewhere.
    client._client = httpx.Client(
        base_url=BASE_URL,
        timeout=timeout_seconds,
        follow_redirects=False,
    )
    return client


def fetch_page(client: KraApiClient, year: int, page_no: int, service_key: str, last_ms: int | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int | None, str | None, bool]:
    params = {
        'meet': MEET,
        'clinic_year': str(year),
        '_type': 'json',
        'pageNo': page_no,
        'numOfRows': PAGE_SIZE,
    }
    attempts: list[dict[str, Any]] = []
    for attempt_no in range(1, MAX_ATTEMPTS + 1):
        wait_for_request_gap(last_ms)
        try:
            fetched = fetch_once_without_client_retries(
                client,
                RACE_HORSE_CLINIC_ENDPOINT,
                RACE_HORSE_CLINIC_OPERATION,
                params,
            )
            last_ms = time.time_ns() // 1_000_000
            attempts.append({'attempt_no': attempt_no, 'outcome': 'http_response', 'completed_at_ms': last_ms})
            record = page_metadata(year, page_no, fetched, attempt_no, service_key)
            return record, attempts, last_ms, None, False
        except KraApiRateLimitError:
            last_ms = time.time_ns() // 1_000_000
            attempts.append({'attempt_no': attempt_no, 'outcome': 'rate_limit_stop', 'exception_type': 'KraApiRateLimitError', 'completed_at_ms': last_ms})
            return None, attempts, last_ms, 'rate_limit_stop', True
        except KraApiTransientError as exc:
            last_ms = time.time_ns() // 1_000_000
            attempts.append({
                'attempt_no': attempt_no,
                'outcome': 'transient_error',
                'exception_type': type(exc).__name__,
                'diagnostics': safe_exception_diagnostics(exc),
                'completed_at_ms': last_ms,
            })
            if attempt_no == MAX_ATTEMPTS:
                return None, attempts, last_ms, 'transient_error_exhausted', False
        except Exception as exc:
            last_ms = time.time_ns() // 1_000_000
            attempts.append({'attempt_no': attempt_no, 'outcome': 'nonretryable_error', 'exception_type': type(exc).__name__, 'completed_at_ms': last_ms})
            return None, attempts, last_ms, 'nonretryable_error', False
    return None, attempts, last_ms, 'unknown_error', False


def update_year_summary(entry: dict[str, Any]) -> None:
    pages = sorted(entry.get('pages', []), key=lambda p: int(p['page_no']))
    total = pages[0]['api_total_count'] if pages else None
    expected = pages[0]['expected_page_count'] if pages else None
    actual = sum(int(p['actual_page_rows']) for p in pages)
    page_ids = [int(p['page_no']) for p in pages]
    entry['api_total_count'] = total
    entry['expected_page_count'] = expected
    entry['actual_page_count'] = len(pages)
    entry['actual_total_rows'] = actual
    if total == 0 and page_ids == [1] and actual == 0:
        entry['status'] = 'query_complete_zero_rows'
    elif total and expected == len(pages) and page_ids == list(range(1, expected + 1)) and actual == total:
        entry['status'] = 'query_complete_positive_rows'
    elif pages:
        entry['status'] = 'positive_or_partial_pages_pending'
    else:
        entry.setdefault('status', 'pending_or_failed')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume-after-positive', action='store_true', help='After the initial positive page has been reported, collect its remaining pages and then remaining requested years.')
    parser.add_argument('--output-dir', type=Path, help='Use a fresh staging directory for a separate collection run.')
    args = parser.parse_args()
    if args.output_dir is not None:
        global API_ROOT, MANIFEST_PATH
        API_ROOT = args.output_dir
        MANIFEST_PATH = API_ROOT / 'api_gap_recheck_manifest.json'

    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({'status': 'credential_unavailable'}))
        return 2
    base = settings.kra_api_base_url.rstrip('/')
    if base != BASE_URL:
        print(json.dumps({'status': 'unexpected_api_base_url'}))
        return 2
    service_key = secret.get_secret_value()
    manifest = read_manifest()
    last_ms = prior_last_request_ms(manifest)
    timeout = min(float(settings.http_timeout_seconds), 25.0)
    API_ROOT.mkdir(parents=True, exist_ok=True)

    positive_found = False
    rate_limited = False
    with make_client(service_key, timeout) as client:
        for year in GAP_YEARS:
            entry = manifest['years'].setdefault(str(year), {'year': year, 'attempts': [], 'pages': [], 'status': 'pending'})
            entry.setdefault('attempts', [])
            entry.setdefault('pages', [])
            existing_pages = {int(p['page_no']): p for p in entry['pages']}
            expected = entry.get('expected_page_count')

            if entry.get('status') == 'query_complete_zero_rows':
                continue
            if entry.get('status') == 'query_complete_positive_rows' and not args.resume_after_positive:
                continue
            if entry.get('status') == 'positive_or_partial_pages_pending' and not args.resume_after_positive:
                positive_found = True
                break

            page_numbers: list[int]
            if existing_pages and args.resume_after_positive and expected:
                page_numbers = [p for p in range(1, int(expected) + 1) if p not in existing_pages]
            elif existing_pages:
                continue
            else:
                page_numbers = [1]

            for page_no in page_numbers:
                page, attempts, last_ms, failure, was_rate_limited = fetch_page(client, year, page_no, service_key, last_ms)
                entry['attempts'].extend(attempts)
                if failure:
                    entry['status'] = failure
                    entry['failure'] = {'type': failure, 'attempt_count': len(attempts)}
                    write_manifest(manifest)
                    print(json.dumps({'year': year, 'status': failure, 'attempts': len(attempts)}), flush=True)
                    if was_rate_limited:
                        rate_limited = True
                        break
                    if failure == 'nonretryable_error':
                        return 1
                    break
                entry['pages'].append(page)
                update_year_summary(entry)
                write_manifest(manifest)
                print(json.dumps({
                    'year': year,
                    'status': entry['status'],
                    'page_no': page['page_no'],
                    'http_status': page['http_status'],
                    'api_result_code': page['api_result_code'],
                    'api_total_count': page['api_total_count'],
                    'actual_page_rows': page['actual_page_rows'],
                    'expected_page_count': page['expected_page_count'],
                    'response_sha256': page['response_sha256'],
                    'sample_rows': page['sample_rows'] if page['actual_page_rows'] else [],
                }, ensure_ascii=False), flush=True)

                if page['api_total_count'] > 0:
                    positive_found = True
                    if not args.resume_after_positive:
                        break
            if positive_found and not args.resume_after_positive:
                break
            if rate_limited:
                break

    manifest['last_run_finished_at_utc'] = datetime.now(UTC).isoformat()
    statuses = [manifest.get('years', {}).get(str(y), {}).get('status') for y in GAP_YEARS]
    complete_statuses = {'query_complete_zero_rows', 'query_complete_positive_rows'}
    if rate_limited:
        manifest['run_status'] = 'rate_limited'
    elif positive_found:
        manifest['run_status'] = 'positive_found_needs_review'
    elif all(status in complete_statuses for status in statuses):
        manifest['run_status'] = 'completed_all_requested_years'
    elif any(status not in {None, 'pending'} for status in statuses):
        manifest['run_status'] = 'completed_with_failures_or_pending_pages'
    else:
        manifest['run_status'] = 'incomplete'
    write_manifest(manifest)
    print(json.dumps({'run_status': manifest['run_status'], 'years_recorded': sorted(manifest['years'].keys())}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
