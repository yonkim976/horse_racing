"""Capture a small, fixed set of public KRA score tables for direct review."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT = HERE / 'official_web'
EVENTS = [('20200104', '1'), ('20200104', '8'), ('20210108', '1'), ('20200711', '12'), ('20211009', '4')]
ENDPOINT = 'https://race.kra.co.kr/raceScore/ScoretableDetailList.do'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    receipts = []
    manifest = OUT / 'capture_manifest.jsonl'
    prior = [json.loads(line) for line in manifest.read_text(encoding='utf-8').splitlines()] if manifest.exists() else []
    already_captured = {(item['date'], item['race_no']) for item in prior}
    with httpx.Client(timeout=35, follow_redirects=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        for date, race in EVENTS:
            path = OUT / f'seoul_{date}_race_{race}.html'
            if (date, race) in already_captured:
                continue
            response = client.get(ENDPOINT, params={'meet': '1', 'realRcDate': date, 'realRcNo': race})
            response.raise_for_status()
            data = response.content
            path.write_bytes(data)
            try:
                html = data.decode('utf-8', errors='strict')
                encoding = 'utf-8'
            except UnicodeDecodeError:
                html = data.decode('cp949', errors='strict')
                encoding = 'cp949'
            soup = BeautifulSoup(html, 'html.parser')
            text = soup.get_text(' ', strip=True)
            (OUT / f'seoul_{date}_race_{race}.txt').write_text(text, encoding='utf-8')
            receipt = {'date': date, 'race_no': race, 'url': str(response.url), 'status': response.status_code,
                       'captured_at_utc': datetime.now(timezone.utc).isoformat(), 'sha256': hashlib.sha256(data).hexdigest(),
                       'raw_file': str(path), 'content_type': response.headers.get('content-type'), 'decoded_encoding': encoding,
                       'title': soup.title.get_text(strip=True) if soup.title else None}
            receipts.append(receipt)
            print(json.dumps(receipt, ensure_ascii=False), flush=True)
            for table in soup.find_all('table'):
                if table.find('caption') and '각 코너별' in table.find('caption').get_text():
                    print(table.get_text(' | ', strip=True), flush=True)
    if receipts:
        with (OUT / 'capture_manifest.jsonl').open('a', encoding='utf-8') as stream:
            for receipt in receipts:
                stream.write(json.dumps(receipt, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
