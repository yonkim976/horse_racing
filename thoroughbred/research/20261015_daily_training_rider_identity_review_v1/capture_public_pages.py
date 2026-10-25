"""Capture a bounded selection of public KRA pages; no credentials or DB writes."""
import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT = HERE / 'official_web'
PAGES = {
    'api18_description': 'https://www.data.go.kr/data/15058782/openapi.do',
    'seoul_daily_list': 'https://race.kra.co.kr/trainer/dailyDayTrainListSelect.do?meet=1',
    'yeongnam_daily_list': 'https://race.kra.co.kr/trainer/dailyDayTrainListSelect.do?meet=3',
    'seoul_daily_groups_20260928': 'https://race.kra.co.kr/trainer/dailyGroupTrainList.do?meet=1&trDate=2026%2F09%2F28&trYo=%EC%9B%94',
    'yeongnam_daily_groups_20260928': 'https://race.kra.co.kr/trainer/dailyGroupTrainList.do?meet=3&trDate=2026%2F09%2F28&trYo=%EC%9B%94',
    'api234_description': 'https://www.data.go.kr/data/15089697/openapi.do',
    'seoul_daily_all_20260928': 'https://race.kra.co.kr/trainer/dailyAllTrainDetail.do?meet=1&trDate=2026%2F09%2F28&trYo=%EC%9B%94&trDateReplace=20260928',
    'yeongnam_daily_all_20260928': 'https://race.kra.co.kr/trainer/dailyAllTrainDetail.do?meet=3&trDate=2026%2F09%2F28&trYo=%EC%9B%94&trDateReplace=20260928',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pages', nargs='+', choices=sorted(PAGES))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    ledger = OUT / 'capture_manifest.jsonl'
    captured = {json.loads(line)['name'] for line in ledger.read_text(encoding='utf-8').splitlines()} if ledger.exists() else set()
    with httpx.Client(timeout=35, follow_redirects=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        for name in args.pages:
            if name in captured:
                print(json.dumps({'name': name, 'status': 'already_captured'}), flush=True)
                continue
            url = PAGES[name]
            assert urlsplit(url).scheme == 'https' and urlsplit(url).hostname in ('race.kra.co.kr', 'www.data.go.kr')
            parts = urlsplit(url)
            if parts.path in ('/trainer/dailyGroupTrainList.do', '/trainer/dailyAllTrainDetail.do'):
                # Submit the public list's actual POST form, using its document encoding.
                params = {key: value[0] for key, value in parse_qs(parts.query).items()}
                body = {'nTotPageRest': '2', 'pageIndex': '1', 'Act': '', 'Sub': '', 'trNo': '', 'trName': '', **params}
                response = client.post('https://race.kra.co.kr' + parts.path,
                                       content=urlencode(body, encoding='cp949').encode('ascii'),
                                       headers={'Content-Type': 'application/x-www-form-urlencoded',
                                                'Referer': f"https://race.kra.co.kr/trainer/dailyDayTrainListSelect.do?meet={params['meet']}"})
            else:
                response = client.get(url)
            response.raise_for_status()
            data = response.content
            path = OUT / f'{name}.html'
            path.write_bytes(data)
            try:
                html = data.decode('utf-8')
                encoding = 'utf-8'
            except UnicodeDecodeError:
                html = data.decode('cp949')
                encoding = 'cp949'
            soup = BeautifulSoup(html, 'html.parser')
            (OUT / f'{name}.txt').write_text(soup.get_text(' ', strip=True), encoding='utf-8')
            receipt = {'name': name, 'url': url, 'http_status': response.status_code, 'method': response.request.method,
                       'captured_at_utc': datetime.now(timezone.utc).isoformat(), 'sha256': hashlib.sha256(data).hexdigest(),
                       'raw_file': path.relative_to(HERE).as_posix(), 'encoding': encoding, 'bytes': len(data)}
            with ledger.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(receipt, ensure_ascii=False) + '\n')
            print(json.dumps(receipt, ensure_ascii=False), flush=True)
            time.sleep(1)


if __name__ == '__main__':
    main()
