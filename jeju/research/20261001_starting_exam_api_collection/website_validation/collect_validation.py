"""Archive official result pages for independent API comparison."""
import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIST_URL = 'https://race.kra.co.kr/referee/StartingRacingTrainCheckList.do?Act=07&Sub=6&meet=2'
DETAIL_URL = 'https://race.kra.co.kr/referee/StartingRacingTrainCheckScoreTable.do'


class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.cells = None
        self.cell = None
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.cells = []
            self.hrefs = []
        elif tag == 'td' and self.cells is not None:
            self.cell = []
        elif tag == 'a' and self.cells is not None:
            self.hrefs.extend(v for k, v in attrs if k in ('href', 'onclick'))

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == 'td' and self.cell is not None:
            self.cells.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.cells is not None:
            self.rows.append({'cells': self.cells, 'links': self.hrefs})
            self.cells = None
            self.cell = None


def parse(b):
    p = Rows()
    p.feed(b.decode('euc-kr'))
    return p.rows


def main():
    now = datetime.now(timezone.utc).isoformat()
    raw = urllib.request.urlopen(LIST_URL, timeout=25).read()
    (HERE / 'list.html').write_bytes(raw)
    days = []
    for r in parse(raw):
        c = r['cells']
        if len(c) != 7 or not re.fullmatch(r'\d{4}/\d{2}/\d{2}', c[2]):
            continue
        days.append({'date': c[2].replace('/', ''), 'type': c[1], 'rows': int(c[4]),
                     'passed': int(c[5]), 'rounds': [int(m.group(1)) for h in r['links']
                     if (m := re.search(r'goPage1\("(\d+)"', h))]})
    artifacts = [{'path': 'list.html', 'sha256': hashlib.sha256(raw).hexdigest(), 'url': LIST_URL, 'observed_at_utc': now}]
    result = []
    for d in days:
        if d['date'] not in {'20260930', '20260927', '20260920', '20260916', '20260913'} or d['type'] != '결과표':
            continue
        for n in d['rounds']:
            params = {'meet': '2', 'trno': str(n), 'date': d['date'], 'doFlag': '결과표', 'Act': '07', 'Sub': '6'}
            stamp = datetime.now(timezone.utc).isoformat()
            b = urllib.request.urlopen(DETAIL_URL, data=urllib.parse.urlencode(params, encoding='euc-kr').encode('ascii'), timeout=25).read()
            name = f"{d['date']}_{n}.html"
            (HERE / name).write_bytes(b)
            artifacts.append({'path': name, 'sha256': hashlib.sha256(b).hexdigest(), 'url': DETAIL_URL, 'params': params, 'observed_at_utc': stamp})
            for r in parse(b):
                ids = [m.group(1) for h in r['links'] if (m := re.search(r"goPage1\('(\d+)'", h))]
                if not ids:
                    continue
                assert len(ids) == 1 and len(r['cells']) == 10, r
                c = r['cells']
                result.append(dict(zip(['horse_number', 'horse_name', 'inspection_reason', 'sex', 'age', 'rider', 'trainer', 'owner', 'judgement', 'failure_reason'], c), date=d['date'], round=n, horse_id=ids[0], source_path=name))
    output = {'artifacts': artifacts, 'listing': days, 'rows': result}
    (HERE / 'website_observations.json').write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps({'pages': len(artifacts), 'rows': len(result), 'listing': days}, ensure_ascii=False))


if __name__ == '__main__':
    main()
