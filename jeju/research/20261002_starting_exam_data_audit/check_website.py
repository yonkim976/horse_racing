import hashlib
import importlib.util
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent / 'website_crosscheck'
BASE.mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location('parser', '/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection/website_validation/collect_validation.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
url = 'https://race.kra.co.kr/referee/StartingRacingTrainCheckScoreTable.do'
observations = []
for day in ['20050225', '20091209', '20140706', '20151227', '20170215']:
    params = dict(meet='2', trno='1', date=day, doFlag='결과표', Act='07', Sub='6')
    record = {'date': day, 'round': 1, 'url': url, 'params': params, 'observed_at_utc': datetime.now(timezone.utc).isoformat()}
    try:
        request = urllib.request.Request(url, data=urllib.parse.urlencode(params, encoding='euc-kr').encode('ascii'))
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
            record['http_status'] = response.status
        path = BASE / (day + '_1.html')
        path.write_bytes(data)
        record.update(path=path.name, sha256=hashlib.sha256(data).hexdigest())
        rows = module.parse(data)
        record['horse_rows'] = [r for r in rows if any(re.search(r"goPage1\('(\d+)'", h) for h in r['links'])]
        record['all_nonempty_rows'] = [r for r in rows if r['cells']]
    except Exception as exc:
        record['error_type'] = type(exc).__name__
    observations.append(record)
    print(json.dumps({'date': day, 'http_status': record.get('http_status'), 'horse_rows': record.get('horse_rows'), 'error_type': record.get('error_type')}, ensure_ascii=False))
(BASE / 'observations.json').write_text(json.dumps(observations, ensure_ascii=False, indent=2))
