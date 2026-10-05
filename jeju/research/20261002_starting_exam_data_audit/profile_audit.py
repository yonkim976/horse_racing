import json
import hashlib
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path('/Users/kimyongjin/Desktop/horse_racing')
SOURCE = REPO / 'jeju/research/20261001_starting_exam_api_collection'
OUTPUT = Path(__file__).resolve().parent
DB = REPO / 'jeju/data/jeju_native_core.sqlite3'


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    profiles = {}
    for r in con.execute('SELECT * FROM horse_profile_observations ORDER BY observed_at_utc,api_record_id'):
        profiles[r['horse_id']] = {'name': r['horse_name_raw'], 'sex': r['sex_raw'], 'birth': r['birth_date_raw'], 'breed': r['breed_label_raw'], 'source': f"DB profile observation {r['horse_profile_observation_id']}"}
    follow = json.loads((SOURCE / 'api42_followup_summary.json').read_text())
    manifest = SOURCE / follow['manifest']
    for r in json.loads(manifest.read_text())['probes']:
        if r['status'] != 'completed':
            continue
        p = (manifest.parent / r['response_file']).resolve()
        assert p.is_relative_to(manifest.parent.resolve())
        raw = p.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == r['response_sha256']
        item = json.loads(raw)['response']['body']['items']['item']
        for i in item if isinstance(item, list) else [item]:
            if str(i['hrNo']) == r['queried_hr_no']:
                profiles[str(i['hrNo'])] = {'name': i.get('hrNm'), 'sex': i.get('sex'), 'birth': i.get('birthDt'), 'breed': i.get('breed'), 'source': str(p.relative_to(SOURCE))}
    entries = [json.loads(l) for l in (SOURCE / 'api21_verified_native_candidate_rows.jsonl').read_text().splitlines()]
    differences = defaultdict(list)
    summaries = Counter()
    for e in entries:
        i = e['raw']
        h = str(i['hrNo'])
        p = profiles[h]
        assert p['breed'] == '제주마'
        a = {'horse_id': h, 'date': str(i['trainDate']), 'round': i['trainNo'], 'horse_name_raw': i['hrName'], 'current_name': p['name'], 'sex_raw': i['sex'], 'current_sex': p['sex'], 'age_raw': i['age'], 'birth_date_current_raw': p['birth'], 'judgement_raw': i['passFlag'], 'source_path': e['source_path'], 'source_row_no': e['source_row_no']}
        if str(i['hrName']).strip() != str(p['name']).strip():
            differences['name_differs_from_current'].append(a)
        if i['sex'] != p['sex']:
            differences['sex_differs_from_current'].append(a)
            summaries[f"sex_transition_{i['sex']}_to_{p['sex']}"] += 1
        try:
            birth = datetime.strptime(str(p['birth']).strip(), '%Y%m%d').date()
            date = datetime.strptime(str(i['trainDate']), '%Y%m%d').date()
        except ValueError:
            differences['invalid_date_or_profile_birth'].append(a)
            continue
        if date < birth:
            differences['exam_before_current_profile_birth'].append(a)
        expected_age = date.year - birth.year
        expected_full_year_age = expected_age - ((date.month, date.day) < (birth.month, birth.day))
        if int(i['age']) != expected_full_year_age:
            differences['age_differs_from_completed_years_at_exam'].append(dict(a, expected_completed_year_age=expected_full_year_age))
        else:
            summaries['age_matches_completed_years_at_exam'] += 1
        if int(i['age']) != expected_age:
            differences['age_differs_from_current_birth_year'].append(dict(a, expected_calendar_age=expected_age, age_delta=int(i['age']) - expected_age))
    horse_ids = {str(e['raw']['hrNo']) for e in entries}
    histories = defaultdict(list)
    for table, date_field in [('race_result_rows', 'race_date'), ('running_trial_rows', 'trial_date')]:
        for r in con.execute(f'SELECT horse_id,{date_field},horse_name FROM {table}'):
            if r['horse_id'] in horse_ids:
                histories[r['horse_id']].append((r[date_field].replace('-', ''), r['horse_name'], table))
    for row in differences['name_differs_from_current']:
        matches = [r for r in histories[row['horse_id']] if r[1] == row['horse_name_raw']]
        row['historical_name_also_observed_in_race_or_trial'] = bool(matches)
        row['example_supporting_history'] = matches[:3]
    for kind, rs in differences.items():
        (OUTPUT / f'{kind}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rs))
    report = {'candidate_rows': len(entries), 'candidate_horse_ids': len(horse_ids), 'profile_population_horse_ids': len(profiles), 'comparison_counts': {k: {'rows': len(v), 'horse_ids': len({r['horse_id'] for r in v})} for k, v in differences.items()}, 'observation_counts': dict(summaries), 'interpretation': 'Differences from current profiles are observations for review; they do not by themselves establish an incorrect historical exam or identity. API21 age matches completed years since birth in all candidate rows; this observed match does not assert the official age rule beyond this dataset. API21 observed names, sex, and age are kept. Age reference for analysis remains 2026 minus current profile birth year.', 'database_write_performed': False}
    (OUTPUT / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
