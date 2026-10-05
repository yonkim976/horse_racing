"""Fetch four public KRA pages once; save evidence, never mutate a database."""
from pathlib import Path
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx
from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parent / 'public_examples'
CASES = [(3, '20260918', 4), (4, '20260920', 3)]

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for meet, day, race in CASES:
            for kind in ('card', 'score'):
                if kind == 'card':
                    url = 'https://race.kra.co.kr/chulmainfo/chulmaDetailInfoChulmapyo.do'
                    params = {'Act':'02', 'Sub':'1', 'meet':str(meet), 'rcDate':day, 'rcNo':str(race)}
                else:
                    url = 'https://race.kra.co.kr/raceScore/ScoretableDetailList.do'
                    params = {'Act':'04', 'Sub':'1', 'meet':str(meet), 'realRcDate':day, 'realRcNo':str(race)}
                record = {'kind':kind, 'meet':meet, 'date':day, 'race':race, 'url':str(httpx.URL(url, params=params))}
                try:
                    response = client.get(url, params=params)
                    record['status'] = response.status_code
                    record['retrieved_kst'] = datetime.now(ZoneInfo('Asia/Seoul')).isoformat()
                    record['sha256'] = hashlib.sha256(response.content).hexdigest()
                    name = f'{meet}_{day}_{race}_{kind}'
                    (OUT / (name+'.html')).write_bytes(response.content)
                    response.encoding = 'cp949'
                    soup = BeautifulSoup(response.text, 'html.parser')
                    lines = []
                    for tr in soup.select('tr'):
                        line = ' | '.join(x.get_text(' ', strip=True) for x in tr.select('th,td'))
                        if line:
                            lines.append(line)
                    text = soup.get_text(' ', strip=True)
                    (OUT / (name+'.txt')).write_text('\n'.join(lines)+'\n\n'+text, encoding='utf-8')
                    record['target_rows'] = [x for x in lines if any(n in x for n in ('플라잉스카이', '아처하트'))]
                    record['equipment_legend_fragments'] = [text[max(0,i-50):i+150] for term in ('신규', '해지', '장구') if (i:=text.find(term))>=0]
                except httpx.HTTPError as error:
                    record['error_type'] = type(error).__name__
                results.append(record)
    (OUT/'evidence.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
