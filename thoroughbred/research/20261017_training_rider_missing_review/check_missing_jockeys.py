"""Read official historical day pages for the 43 numberless jockey events."""
import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import httpx
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'official_web'


def main():
    OUT.mkdir(exist_ok=True)
    con = duckdb.connect(str(ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'), read_only=True)
    query = con.execute("""SELECT observation_id,event_date,meet,official_horse_id,
        horse_name_raw,started_at_raw,ended_at_raw,raw_path,raw_sha256
        FROM daily_training_rider_linked
        WHERE rider_identity_status='pr_no_absent' AND rider_type_raw='기수'
        ORDER BY event_date,meet,observation_id""")
    columns = [column[0] for column in query.description]
    rows = [dict(zip(columns, row)) for row in query.fetchall()]
    con.close()
    assert len(rows) == 43
    captures = {}
    with httpx.Client(timeout=25, follow_redirects=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        for date, meet in sorted({(str(row['event_date']), row['meet']) for row in rows}):
            assert meet in ('1', '3')
            name = f'daily_{meet}_{date.replace("-", "")}'
            path, metadata = OUT / (name + '.html'), OUT / (name + '.json')
            if path.exists() and metadata.exists():
                receipt = json.loads(metadata.read_text())
                assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt['sha256']
            else:
                form = {'meet': meet, 'trDate': date.replace('-', '/'),
                        'trDateReplace': date.replace('-', ''), 'trNo': '', 'trName': '', 'Act': '', 'Sub': ''}
                url = 'https://race.kra.co.kr/trainer/dailyAllTrainDetail.do'
                response = client.post(url, data=form)
                data = response.content
                path.write_bytes(data)
                receipt = {'name': name, 'url': url, 'method': 'POST', 'form_or_params': form,
                           'status': response.status_code, 'sha256': hashlib.sha256(data).hexdigest(),
                           'captured_at': datetime.now(timezone.utc).isoformat()}
                metadata.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
                print(json.dumps({'date': date, 'meet': meet, 'status': response.status_code, 'bytes': len(data)}), flush=True)
                if response.status_code in (403, 429):
                    raise RuntimeError('Official site refused the request; collection stopped')
                response.raise_for_status()
                time.sleep(1)
            assert receipt['status'] == 200
            soup = BeautifulSoup(path.read_bytes().decode('cp949'), 'html.parser')
            tables = [table for table in soup.find_all('table') if table.find('caption')
                      and '전체일별상세조교현황' in table.find('caption').get_text()]
            assert len(tables) == 1, (name, len(tables))
            indexed = {}
            for tr in tables[0].find_all('tr'):
                cells = tr.find_all('td', recursive=False)
                if not cells or len(cells) != 13:
                    continue
                anchor = cells[3].find('a')
                match = re.fullmatch(r"javascript:goPage4\('([0-9]+)'\)", anchor.get('href', '')) if anchor else None
                if not match:
                    continue
                values = [cell.get_text(' ', strip=True) for cell in cells]
                key = (match[1], values[7], values[8])
                indexed.setdefault(key, []).append(values)
            captures[(date, meet)] = (receipt, indexed)
    evidence = []
    for row in rows:
        row['event_date'] = str(row['event_date'])
        receipt, indexed = captures[(row['event_date'], row['meet'])]
        hhmm = lambda value: value[-6:-4] + ':' + value[-4:-2]
        matches = indexed.get((row['official_horse_id'], hhmm(row['started_at_raw']), hhmm(row['ended_at_raw'])), [])
        unique = len(matches) == 1 and matches[0][3] == row['horse_name_raw']
        display = matches[0][5] if unique else None
        status = ('exact_event_web_name' if display and display not in ('관', '조', '후', '생', '-')
                  else 'exact_event_no_person_name' if unique else 'no_unique_event_match')
        evidence.append({**row, 'web_display': display, 'status': status,
                         'matching_rows': len(matches), 'web_values': matches if unique else [],
                         'web_capture': receipt})
    report = {'requested_rows': len(rows), 'requested_day_pages': len(captures),
              'status_counts': dict(Counter(row['status'] for row in evidence)),
              'display_counts': dict(Counter(row['web_display'] for row in evidence)), 'database_writes': False,
              'matching_rule': 'date+meet+official horse ID+entry/exit minute, unique match and exact horse name',
              'evidence': evidence}
    (HERE / 'missing_jockey_43_review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != 'evidence'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
