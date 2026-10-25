"""Read-only exact-event comparison of API training rows and official displayed riders."""
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'
EVENT_DATE = '2026-09-28'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    captures = {item['name']: item for item in [json.loads(line) for line in (HERE / 'official_web/capture_manifest.jsonl').read_text(encoding='utf-8').splitlines()]}
    con = duckdb.connect(str(DB), read_only=True)
    con.execute('SET threads=2')
    cursor = con.execute("SELECT observation_id,meet,official_horse_id,horse_name_raw,training_date_raw,stable_part_raw,stable_number_raw,trainer_name_raw,rider_type_raw,rider_id_raw,started_at_raw,ended_at_raw,duration_seconds_raw,raw_path,raw_sha256,source_row_no FROM daily_training_raw WHERE event_date=?", [EVENT_DATE])
    columns = [item[0] for item in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    profiles = defaultdict(set)
    for number, name in con.execute("SELECT official_id_raw_string,name_snapshot FROM person_reference_profile_snapshots WHERE entity_type='jockey'").fetchall():
        profiles[number].add(name)
    con.close()
    indexed = defaultdict(list)
    for row in rows:
        start = row['started_at_raw'][-6:-4] + ':' + row['started_at_raw'][-4:-2]
        end = row['ended_at_raw'][-6:-4] + ':' + row['ended_at_raw'][-4:-2]
        indexed[(row['meet'], row['official_horse_id'], start, end)].append(row)
    evidence = []
    issues = []
    summaries = {}
    referenced_paths = {}
    role_labels = {'관', '조', '보', '승', '후', '-', ''}
    for prefix, meet in [('seoul', '1'), ('yeongnam', '3')]:
        capture = captures[f'{prefix}_daily_all_20260928']
        path = (HERE / capture['raw_file']).resolve()
        assert path.is_relative_to(HERE.resolve()) and sha(path) == capture['sha256']
        soup = BeautifulSoup(path.read_bytes().decode(capture['encoding']), 'html.parser')
        assert '2026/09/28' in soup.get_text(' ', strip=True)
        tables = [table for table in soup.find_all('table') if table.find('caption') and '전체일별상세조교현황' in table.find('caption').get_text()]
        assert len(tables) == 1
        counts = Counter()
        for tr in tables[0].find_all('tr'):
            cells = tr.find_all('td', recursive=False)
            if not cells:
                continue
            values = [cell.get_text(' ', strip=True) for cell in cells]
            assert len(values) == 13
            horse_link = cells[3].find('a')
            match = re.fullmatch(r"javascript:goPage4\('([0-9]+)'\)", horse_link['href'])
            assert match
            horse_id = match[1]
            key = (meet, horse_id, values[7], values[8])
            candidates = indexed.get(key, [])
            counts['web_rows'] += 1
            if len(candidates) != 1:
                issues.append({'key': key, 'matching_API_rows': len(candidates)})
                continue
            row = candidates[0]
            rider_display = values[5]
            has_person_name = rider_display not in role_labels
            known_names = sorted(profiles.get(row['rider_id_raw'], set()))
            name_matches_profile = has_person_name and rider_display in known_names
            # A display suffix is retained as raw text, not used to invent a new person ID or role.
            suffix_only = has_person_name and rider_display.endswith('(트)') and rider_display[:-3] in known_names
            counts['exact_event_matched_rows'] += 1
            counts['web_person_name_rows' if has_person_name else 'web_role_only_rows'] += 1
            if has_person_name:
                category = 'web_name_matches_profile' if name_matches_profile else 'web_name_suffix_only_variation' if suffix_only else 'web_name_not_in_profile_candidates'
                counts[category] += 1
            stable_difference = (values[1].removesuffix('조'), values[2]) != (row['stable_part_raw'], row['stable_number_raw'])
            if stable_difference:
                issues.append({'key': key, 'type': 'stable_metadata_differs', 'API_stable': [row['stable_part_raw'], row['stable_number_raw']], 'web_stable': [values[1], values[2]]})
            if values[3] != row['horse_name_raw']:
                issues.append({'key': key, 'type': 'horse_name_disagrees', 'API': row['horse_name_raw'], 'web': values[3]})
            raw_path = (ROOT / row['raw_path']).resolve()
            assert raw_path.is_relative_to(ROOT.resolve())
            if row['raw_path'] not in referenced_paths:
                actual = sha(raw_path)
                assert actual == row['raw_sha256']
                referenced_paths[row['raw_path']] = actual
            evidence.append({**row, 'event_date': EVENT_DATE, 'web_row_no': values[0], 'web_rider_display_raw': rider_display,
                             'web_person_name_present': has_person_name, 'profile_name_candidates_by_exact_prNo': known_names,
                             'web_name_in_profile_exact_ID_candidates': name_matches_profile,
                             'web_name_differs_only_by_literal_suffix': suffix_only, 'web_display_suffix_raw': '(트)' if suffix_only else None,
                             'web_stable_raw': [values[1], values[2]], 'stable_metadata_differs': stable_difference,
                             'source_HTML_sha256': capture['sha256'], 'matching_rule': 'meet+date+horse_official_ID+start_minute+end_minute; stable metadata compared separately',
                             'time_precision_note': 'web shows HH:MM; source retains all seconds; unique candidate required'})
        assert counts['web_rows'] == sum(row['meet'] == meet for row in rows)
        summaries[meet] = dict(counts)
    # Same person ID may have historical spelling variants; verify observed names, do not erase them.
    name_conflicts = [row for row in evidence if row['web_person_name_present'] and row['profile_name_candidates_by_exact_prNo'] and not row['web_name_in_profile_exact_ID_candidates'] and not row['web_name_differs_only_by_literal_suffix']]
    for row in name_conflicts:
        issues.append({'observation_id': row['observation_id'], 'type': 'web_person_name_vs_exact_ID_profile_conflict', 'web': row['web_rider_display_raw'], 'profile_names': row['profile_name_candidates_by_exact_prNo']})
    web_labels = Counter(row['web_rider_display_raw'] for row in evidence if not row['web_person_name_present'])
    (HERE / 'web_API_exact_event_rows.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in evidence), encoding='utf-8')
    report = {'status': 'PASS' if not issues else 'REVIEW', 'event_date': EVENT_DATE, 'venues': summaries,
              'exact_event_rows': len(evidence), 'issues': issues, 'role_only_display_counts': dict(web_labels),
              'original_API_page_sha256_verified': referenced_paths, 'database_mode': 'read_only', 'database_writes': False,
              'example_rows': [row for row in evidence if row['horse_name_raw'] in ('무빙볼케이노', '선돌풍', '벌마의거인', '토함산소닉')]}
    (HERE / 'web_API_exact_event_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in ('example_rows', 'original_API_page_sha256_verified')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
