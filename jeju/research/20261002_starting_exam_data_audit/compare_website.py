import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection')
entries = [json.loads(l) for l in (SOURCE / 'api21_verified_native_candidate_rows.jsonl').read_text().splitlines()]
index = {(str(e['raw']['trainDate']), str(e['raw']['trainNo']), str(e['raw']['hrNo'])): e for e in entries}
observations = json.loads((ROOT / 'website_crosscheck/observations.json').read_text())
fields = ['chulNo', 'hrName', 'reason', 'sex', 'age', 'rider', 'trName', 'owName', 'passFlag', 'nopassReason']
compared = []
counts = Counter()
for page in observations:
    for row in page.get('horse_rows', []):
        ids = [m.group(1) for link in row['links'] if (m := re.search(r"goPage1\('(\d+)'", link))]
        assert len(ids) == 1 and len(row['cells']) == 10
        entry = index.get((page['date'], str(page['round']), ids[0]))
        if not entry:
            continue
        raw = entry['raw']
        diffs = {}
        for key, site in zip(fields, row['cells']):
            api = str(raw.get(key, '')).strip()
            if api == '-' and site == '':
                api = ''
            if api != site:
                diffs[key] = {'api_raw': raw.get(key), 'website_raw': site}
                counts[key] += 1
        compared.append({'horse_id': ids[0], 'date': page['date'], 'round': page['round'], 'api_source_path': entry['source_path'], 'api_source_row_no': entry['source_row_no'], 'website_source_path': page['path'], 'differences': diffs, 'api_judgement_raw': raw['passFlag'], 'website_judgement_raw': row['cells'][8], 'api_failure_reason_raw': raw['nopassReason'], 'website_failure_reason_raw': row['cells'][9]})
report = {'pages_fetched': len(observations), 'candidate_rows_compared': len(compared), 'field_difference_counts': dict(counts), 'rows': compared, 'comparison_normalization': "Only '-' versus website blank normalized for comparison; original values retained.", 'interpretation': 'Blank judgement/failure reasons are also present on website. Website ages can differ from API21 completed-year age. Missing API rider can be available on website. This comparison does not infer cancellation or fabricate a result.'}
(ROOT / 'website_crosscheck/comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False))
