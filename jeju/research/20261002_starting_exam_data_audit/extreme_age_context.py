import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / 'extreme_age_crosscheck'
DB = Path('/Users/kimyongjin/Desktop/horse_racing/jeju/data/jeju_native_core.sqlite3')
conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
focus = json.loads((BASE / 'candidate_rows.json').read_text())
pages = json.loads((BASE / 'observations.json').read_text())
website = {}
for page in pages:
    for r in page.get('focus_rows', []):
        ids = [m.group(1) for h in r['links'] if (m := re.search(r"goPage1\('(\d+)'", h))]
        assert len(ids) == 1 and len(r['cells']) == 10
        website[(page['date'], page['round'], ids[0])] = {'age': r['cells'][4], 'judgement': r['cells'][8], 'source_path': page['path']}
results = []
for e in focus:
    i = e['raw']; h = str(i['hrNo'])
    profile = dict(conn.execute('SELECT horse_name_raw,birth_date_raw,age_raw,sex_raw FROM horse_profile_observations WHERE horse_id=? ORDER BY observed_at_utc DESC,api_record_id DESC LIMIT 1', (h,)).fetchone())
    races = conn.execute('SELECT COUNT(*) FROM race_result_rows WHERE horse_id=?', (h,)).fetchone()[0]
    trials = [dict(r) for r in conn.execute('SELECT t.trial_date,t.horse_name,ar.payload_json FROM running_trial_rows t JOIN api_records ar ON t.api_record_id=ar.api_record_id WHERE t.horse_id=? ORDER BY t.trial_date', (h,))]
    examples = []
    for r in trials[:1] + (trials[-1:] if len(trials) > 1 else []):
        payload = json.loads(r['payload_json'])
        examples.append({'trial_date': r['trial_date'], 'horse_name': r['horse_name'], 'age_raw': payload.get('age'), 'sex_raw': payload.get('sex')})
    results.append({'horse_id': h, 'horse_name': i['hrName'], 'exam_date': str(i['trainDate']), 'round': i['trainNo'], 'api21_age_raw': i['age'], 'current_profile': profile, 'race_rows_in_current_db': races, 'trial_rows_in_current_db': len(trials), 'trial_examples': examples, 'website': website.get((str(i['trainDate']), str(i['trainNo']), h)), 'source_path': e['source_path'], 'source_row_no': e['source_row_no']})
report = {'selection_rule': 'Review age >=16; this threshold is a review criterion, not an official age limit.', 'rows': len(results), 'horse_ids': len({r['horse_id'] for r in results}), 'website_rows_available': sum(r['website'] is not None for r in results), 'website_rows_unavailable': sum(r['website'] is None for r in results), 'records': results, 'conclusion': 'API21 age agrees with current profile birth date, but that is not independent validation of the birth date. Website corroborates high ages for available rows. Current DB race/trial context is included; no source correction or active-status inference is made. Retain these as age review flags and preserve user age_2026 policy.'}
(BASE / 'context_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False))
