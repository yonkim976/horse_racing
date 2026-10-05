"""Verify the worker's public response bytes independently of its parser."""
import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parent
OLD = OUT.parent / '20261002_section_remaining_review'
LABELS = {'S-1F': 'S1F', '1코너': '1C', '2코너': '2C', '3코너': '3C', '4코너': '4C', 'G-1F': 'G1F'}
POINTS = list(LABELS.values())


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def groups(s):
    s = re.sub(r'\s+', '', s)
    require(re.fullmatch(r'[0-9(),^=≡\-]+', s) is not None, 'Unsupported group grammar')
    pos, end, bounds = 1, 0, {}
    for match in re.finditer(r'\([^()]+\)|\^?\d+', s):
        require(not s[end:match.start()] or re.fullmatch(r'[,=≡\-]+', s[end:match.start()]), 'Unsupported separator')
        item = match.group()
        require(not item.startswith('(') or re.fullmatch(r'\(\^?\d+(?:,\^?\d+)*\)', item), 'Malformed group')
        nums = [int(v) for v in re.findall(r'\d+', item)]
        require(len(set(nums)) == len(nums) and not set(nums).intersection(bounds), 'Duplicate member')
        for n in nums:
            bounds[n] = (pos, pos + len(nums) - 1)
        pos += len(nums)
        end = match.end()
    require(end == len(s), 'Group not fully parsed')
    return bounds


def main():
    manifest = OUT / 'official_recheck/manifest.json'
    records = json.loads(manifest.read_text())
    cases = json.loads((OLD / 'remaining_website_internal_order_conflicts.json').read_text())
    keys = {(r['date'], int(r['race_no'])) for r in cases}
    require(len(records) == len(keys) == 19, 'Expected 19 pages')
    pages = {}
    for record in records:
        key = (record['date'], int(record['race_no']))
        require(key in keys and key not in pages and record['http_status'] == 200, 'Unexpected response')
        path = (manifest.parent / record['raw_path']).resolve()
        require(path.is_relative_to(manifest.parent.resolve()), 'Invalid raw path')
        blob = path.read_bytes()
        require(hashlib.sha256(blob).hexdigest() == record['sha256'] and len(blob) == record.get('bytes', record.get('body_bytes')), 'Response bytes changed')
        soup = BeautifulSoup(blob, 'html.parser')
        require('제주' in soup.title.get_text(), 'Wrong venue title')
        tables = []
        for table in soup.find_all('table'):
            rows = [[re.sub(r'\s+', ' ', cell.get_text(' ', strip=True)).strip() for cell in tr.find_all(['th', 'td'], recursive=False)] for tr in table.find_all('tr')]
            tables.append([row for row in rows if row])
        heading_text = ' '.join(cell for rows in tables for row in rows for cell in row)
        identity = re.search(r'(\d{4})년\s+(\d{2})월\s+(\d{2})일.*?제(\d+)경주\s+제주', heading_text)
        require(identity and '-'.join(identity.group(i) for i in (1, 2, 3)) == key[0] and int(identity[4]) == key[1], 'Wrong event heading')
        times = next(rows for rows in tables if rows and 'S-1F' in rows[0] and '경주기록' in rows[0])
        main_table = next(rows for rows in tables if rows and '마명' in rows[0] and '마번' in rows[0])
        ids = {}
        for a in soup.find_all('a', href=True):
            match = re.fullmatch(r"javascript:goHorse\('(\d+)','2'\)", a['href'])
            if match:
                ids[a.get_text(strip=True)] = match[1]
        roster = {}
        for row in main_table[1:]:
            if len(row) > 2 and row[1].isdigit():
                require(row[2] in ids, 'Horse ID missing')
                roster[int(row[1])] = ids[row[2]]
        ranks = {}
        for row in times[1:]:
            num = int(row[1])
            items = [x.strip() for x in row[2].split('-')]
            if len(items) == 7 and items[-1] == '':
                items.pop()
            require(len(items) == 6 and num in roster, 'Wrong point path')
            ranks[num] = [int(x) if x else None for x in items]
        require(set(ranks) == set(roster), 'Incomplete roster')
        point_groups = {}
        group_table = next(rows for rows in tables if rows and '통과순위' in rows[0])
        for row in group_table:
            for cell in row:
                for label, point in LABELS.items():
                    if cell.startswith(label + ':'):
                        point_groups[point] = cell.split(':', 1)[1].strip()
        pages[key] = {'ids': roster, 'ranks': ranks, 'groups': point_groups}
    checked = []
    seen_points = set()
    for case in cases:
        key = (case['date'], int(case['race_no']))
        page = pages[key]
        num, point = int(case['program_no']), case['point']
        require(page['ids'][num] == case['horse_id'], 'Horse ID changed')
        rank = page['ranks'][num][POINTS.index(point)]
        group = page['groups'][point]
        require(rank == case['website_order'], 'Website rank changed')
        require(re.sub(r'\s+', '', group) == re.sub(r'\s+', '', case['website_group_raw']), 'Website group changed')
        lo, hi = groups(group)[num]
        require(not lo <= rank <= hi, 'Conflict no longer exists')
        seen_points.add((*key, point))
        checked.append({'date': key[0], 'race_no': key[1], 'horse_id': case['horse_id'], 'program_no': num, 'point': point, 'website_order': rank, 'group_bounds': [lo, hi], 'conflict_still_present': True})
    require(len(checked) == 70 and len(seen_points) == 20, 'Unexpected conflict scope')
    api_run = OUT / 'api4_recheck/20261002T155808.237358Z'
    api_records = json.loads((api_run / 'manifest.json').read_text())
    api_checks = []
    for record in api_records:
        blob = (api_run / record['raw_file']).read_bytes()
        require(record['http_status'] == 200 and record['status'] == 'complete' and hashlib.sha256(blob).hexdigest() == record['sha256'], 'API response mismatch')
        response = json.loads(blob)['response']
        require(response['header']['resultCode'] == '00', 'API result unsuccessful')
        payload = response['body']
        items = payload['items']['item']
        items = [items] if isinstance(items, dict) else items
        require(len(items) == int(payload['totalCount']), 'API page incomplete')
        for case in [r for r in cases if r['date'] == record['date']]:
            found = [r for r in items if int(r['rcNo']) == int(case['race_no']) and int(r['chulNo']) == int(case['program_no']) and str(r['hrNo']) == case['horse_id']]
            require(len(found) == 1, 'API identity changed')
            field = {'S1F': 'sjS1fOrd', '3C': 'sj_3cOrd', '4C': 'sj_4cOrd', 'G1F': 'sjG1fOrd'}[case['point']]
            require(found[0][field] == int(case['api4_order']), 'API order changed')
            api_checks.append((*case.values(),))
    require(len(api_records) == 19 and len(api_checks) == 70, 'API scope incomplete')
    result = {'status': 'passed', 'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(), 'website_pages': 19, 'conflict_order_fields': 70, 'conflict_points': 20, 'conflict_races': 19, 'website_rank_and_group_changed': False, 'api4_dates_checked': 19, 'api4_order_fields_checked': 70, 'api4_order_changed': False, 'database_modified': False, 'checks': checked}
    (OUT / 'root_fresh_evidence_check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'checks'}))


if __name__ == '__main__':
    main()
