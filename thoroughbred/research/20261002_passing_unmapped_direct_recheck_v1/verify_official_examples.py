"""Compare newly captured KRA example pages with preserved RPT and API literals."""
import hashlib
import json
import re
from pathlib import Path

import pyarrow.parquet as pq
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIOR = ROOT / 'thoroughbred/research/20261002_passing_groups_v1'
WEB = HERE / 'official_web'
LABELS = {'S-1F': 'S1F', '1코너': '1C', '2코너': '2C', '3코너': '3C', '4코너': '4C', 'G-1F': 'G1F'}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    receipts = [json.loads(line) for line in (WEB / 'capture_manifest.jsonl').read_text(encoding='utf-8').splitlines()]
    api = pq.read_table(PRIOR / 'api_source/api_observations.parquet').to_pylist()
    rpt = pq.read_table(PRIOR / 'rpt_mapping/rpt_point_observations.parquet').to_pylist()
    result = []
    for capture in receipts:
        date, race = capture['date'], int(capture['race_no'])
        iso = f'{date[:4]}-{date[4:6]}-{date[6:]}'
        raw_path = Path(capture['raw_file']).resolve()
        assert raw_path.is_relative_to(WEB.resolve())
        assert sha(raw_path) == capture['sha256']
        soup = BeautifulSoup(raw_path.read_bytes().decode(capture['decoded_encoding']), 'html.parser')
        text = soup.get_text(' ', strip=True)
        assert f'{date[:4]}년 {date[4:6]}월 {date[6:]}일' in text and f'제{race}경주 서울' in text
        tables = [table for table in soup.find_all('table') if table.find('caption') and '각 코너별 통과순위' in table.find('caption').get_text()]
        assert len(tables) == 1
        web_points = {}
        for cell in tables[0].find_all('td'):
            literal = cell.get_text(' ', strip=True)
            if ':' not in literal:
                continue
            label, value = literal.split(':', 1)
            if label in LABELS:
                # Normalize HTML formatting whitespace for the displayed comparison only.
                web_points[LABELS[label]] = re.sub(r'\s+', '', value)
        rpt_rows = [row for row in rpt if row['actual_meet_code'] == 1 and row['event_date'] == iso and row['race_no'] == race]
        rpt_points = {}
        source_paths = set()
        for row in rpt_rows:
            point = row['canonical_point_code']
            value = row['notation_raw'].strip(' ')
            if value in ('', '-', 'X'):
                continue
            path = (ROOT / row['source_path']).resolve()
            assert path.is_relative_to(ROOT.resolve()) and sha(path) == row['source_sha256']
            physical_line = path.read_bytes().splitlines(keepends=True)[row['source_line_no'] - 1]
            assert physical_line.hex() == row['raw_line_bytes_hex']
            assert point not in rpt_points
            rpt_points[point] = re.sub(r'\s+', '', value)
            source_paths.add(row['source_path'])
        nonempty_web = {key: value for key, value in web_points.items() if value not in ('', '-', 'X')}
        assert nonempty_web == rpt_points
        api_rows = [row for row in api if row['actual_meet_code'] == 1 and row['race_date_iso'] == iso and row['rcNo'] == race]
        assert len(api_rows) == 1
        row = api_rows[0]
        api_path = (PRIOR / 'api_source' / row['source_path']).resolve()
        assert api_path.is_relative_to((PRIOR / 'api_source').resolve())
        assert sha(api_path) == row['page_sha256']
        api_response = json.loads(api_path.read_text(encoding='utf-8'))
        api_items = api_response['response']['body']['items']['item']
        if isinstance(api_items, dict):
            api_items = [api_items]
        assert sum(item == json.loads(row['raw_item_json']) for item in api_items) == 1
        api_values = {key: value for key, value in row.items() if key.startswith('corner_') and value not in (None, '', '-', 'X')}
        result.append({'event_date': iso, 'race_no': race, 'official_url': capture['url'], 'official_html_sha256': capture['sha256'],
                       'web_points_display_whitespace_normalized': web_points, 'rpt_points_display_whitespace_normalized': rpt_points,
                       'web_RPT_nonempty_point_comparison': 'identical', 'api_fields_literal': api_values,
                       'rpt_source_paths': sorted(source_paths), 'api_source_page': row['source_path'],
                       'API_page_sha256_verified': row['page_sha256'], 'API_original_response_item_verified': True})
    report = {'status': 'PASS', 'newly_fetched_official_web_races': len(result), 'all_259_races_fetched_online': False,
              'comparison_scope': 'official HTML examples versus preserved source RPT and API literals; full 414-slot local audit is separate',
              'examples': result}
    (HERE / 'official_examples_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
