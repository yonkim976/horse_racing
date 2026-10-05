import hashlib
import importlib.util
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection')
BASE = ROOT / 'extreme_age_crosscheck'
BASE.mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location('parser', SOURCE / 'website_validation/collect_validation.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
entries = [json.loads(l) for l in (SOURCE / 'api21_verified_native_candidate_rows.jsonl').read_text().splitlines()]
focus = [e for e in entries if e['raw']['age'] >= 16]
(BASE / 'candidate_rows.json').write_text(json.dumps(focus, ensure_ascii=False, indent=2) + '\n')
pages = sorted({(str(e['raw']['trainDate']), str(e['raw']['trainNo'])) for e in focus})
url = 'https://race.kra.co.kr/referee/StartingRacingTrainCheckScoreTable.do'
observations = []
for day, number in pages:
    params = dict(meet='2', trno=number, date=day, doFlag='결과표', Act='07', Sub='6')
    record = {'date': day, 'round': number, 'url': url, 'params': params, 'observed_at_utc': datetime.now(timezone.utc).isoformat()}
    try:
        request = urllib.request.Request(url, data=urllib.parse.urlencode(params, encoding='euc-kr').encode('ascii'))
        with urllib.request.urlopen(request, timeout=25) as response:
            data = response.read()
            record['http_status'] = response.status
        path = BASE / (day + '_' + number + '.html')
        path.write_bytes(data)
        record.update(path=path.name, sha256=hashlib.sha256(data).hexdigest())
        rows = module.parse(data)
        targets = {str(e['raw']['hrNo']) for e in focus if str(e['raw']['trainDate']) == day and str(e['raw']['trainNo']) == number}
        record['focus_rows'] = [r for r in rows if any((m := re.search(r"goPage1\('(\d+)'", h)) and m.group(1) in targets for h in r['links'])]
    except Exception as exc:
        record['error_type'] = type(exc).__name__
    observations.append(record)
    (BASE / 'observations.json').write_text(json.dumps(observations, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'date': day, 'round': number, 'http_status': record.get('http_status'), 'focus_rows': record.get('focus_rows'), 'error_type': record.get('error_type')}, ensure_ascii=False), flush=True)
