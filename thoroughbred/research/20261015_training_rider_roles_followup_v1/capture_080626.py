"""Read a small fixed set of public KRA pages for an unresolved rider number."""
import hashlib
import json
import argparse
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT = HERE / 'official_web'
PAGES = {
    'yeongnam_jockey_profile_080626': ('/jockey/ProfilePersonItem.do', {'meet': '3', 'Act': '06', 'Sub': '7', 'hrNo': '', 'jkNo': '080626', 'trNo': '', 'retireYn': ''}),
    'control_seoul_jockey_profile_080405': ('/jockey/ProfilePersonItem.do', {'meet': '1', 'Act': '06', 'Sub': '7', 'hrNo': '', 'jkNo': '080405', 'trNo': '', 'retireYn': ''}),
    'yeongnam_jockey_profile_080584': ('/jockey/ProfilePersonItem.do', {'meet': '3', 'Act': '06', 'Sub': '7', 'hrNo': '', 'jkNo': '080584', 'trNo': '', 'retireYn': ''}),
    'yeongnam_daily_20260905': ('/trainer/dailyAllTrainDetail.do', {'meet': '3', 'trDate': '2026/09/05', 'trDateReplace': '20260905', 'trYo': '토', 'trNo': '', 'trName': '', 'Act': '', 'Sub': ''}),
    'yeongnam_daily_20260906': ('/trainer/dailyAllTrainDetail.do', {'meet': '3', 'trDate': '2026/09/06', 'trDateReplace': '20260906', 'trYo': '일', 'trNo': '', 'trName': '', 'Act': '', 'Sub': ''}),
    'yeongnam_daily_20260909': ('/trainer/dailyAllTrainDetail.do', {'meet': '3', 'trDate': '2026/09/09', 'trDateReplace': '20260909', 'trYo': '수', 'trNo': '', 'trName': '', 'Act': '', 'Sub': ''}),
    'yeongnam_daily_20260904': ('/trainer/dailyAllTrainDetail.do', {'meet': '3', 'trDate': '2026/09/04', 'trDateReplace': '20260904', 'trYo': '금', 'trNo': '', 'trName': '', 'Act': '', 'Sub': ''}),
    'yeongnam_daily_20260910': ('/trainer/dailyAllTrainDetail.do', {'meet': '3', 'trDate': '2026/09/10', 'trDateReplace': '20260910', 'trYo': '목', 'trNo': '', 'trName': '', 'Act': '', 'Sub': ''}),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pages', nargs='*', choices=list(PAGES), default=['yeongnam_jockey_profile_080626'])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    ledger = OUT / 'capture_manifest.jsonl'
    captured = {json.loads(line)['name'] for line in ledger.read_text(encoding='utf-8').splitlines()} if ledger.exists() else set()
    with httpx.Client(timeout=35, follow_redirects=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        for name in args.pages:
            if name in captured:
                print(name, 'already captured', flush=True)
                continue
            endpoint, form = PAGES[name]
            url = 'https://race.kra.co.kr' + endpoint
            response = client.post(url, content=urlencode(form, encoding='cp949').encode('ascii'), headers={'Content-Type': 'application/x-www-form-urlencoded'})
            response.raise_for_status()
            data = response.content
            path = OUT / f'{name}.html'
            path.write_bytes(data)
            soup = BeautifulSoup(data.decode('cp949'), 'html.parser')
            text = soup.get_text(' ', strip=True)
            (OUT / f'{name}.txt').write_text(text, encoding='utf-8')
            receipt = {'name': name, 'url': url, 'method': 'POST', 'request_form': form, 'status': response.status_code,
               'captured_at_utc': datetime.now(timezone.utc).isoformat(), 'sha256': hashlib.sha256(data).hexdigest(),
               'file': path.relative_to(HERE).as_posix(), 'encoding': 'cp949'}
            with ledger.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(receipt, ensure_ascii=False) + '\n')
            print(json.dumps(receipt, ensure_ascii=False), flush=True)
            if 'profile' in name:
                position = text.find('성명')
                print(text[max(0,position-80):position+450], flush=True)
                print('hidden fields', [(tag.get('name'),tag.get('value')) for tag in soup.find_all('input') if tag.get('name') in ('meet','jkNo')], flush=True)
            else:
                print('tables', [(table.find('caption').get_text(' ', strip=True) if table.find('caption') else '', len(table.find_all('tr'))) for table in soup.find_all('table')], flush=True)
            time.sleep(1)


if __name__ == '__main__':
    main()
