"""Compare age conventions without changing the database or source values."""
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
conn = sqlite3.connect((ROOT / 'jeju/data/jeju_native_core.sqlite3').as_uri() + '?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
profiles = {r['horse_id']: json.loads(r['payload_json']) for r in conn.execute('select horse_id,payload_json from horse_profile_latest')}
counts = Counter({label + '_matches': 0 for label in ['calendar_year', 'korean_counting', 'completed_birthday', 'birth_half_year']})
by_year = defaultdict(Counter)
differences = []
history = defaultdict(list)
for row in conn.execute('''select r.*,a.payload_json from jeju_race_population_candidates r
                          join api_records a using(api_record_id) order by race_date,race_number,horse_number'''):
    p = profiles[row['horse_id']]
    event = json.loads(row['payload_json'])
    birth = str(p['birthDt'])
    date = row['race_date'].replace('-', '')
    year = int(date[:4])
    calendar = year - int(birth[:4])
    full_age = calendar - (date[4:] < birth[4:])
    half_year = calendar - (birth[4:] >= '0701' and date[4:] < '0701')
    age = int(event['age'])
    formulas = {'calendar_year': calendar, 'korean_counting': calendar + 1,
                'completed_birthday': full_age, 'birth_half_year': half_year}
    counts['rows'] += 1
    by_year[str(year)]['rows'] += 1
    for label, expected in formulas.items():
        if age == expected:
            counts[label + '_matches'] += 1
            by_year[str(year)][label + '_matches'] += 1
    info = {'api_record_id': row['api_record_id'], 'horse_id': row['horse_id'],
            'name': row['horse_name'], 'race_date': row['race_date'], 'race_number': row['race_number'],
            'birth_date_current_profile': birth, 'race_age_raw': age, 'expected': formulas}
    history[row['horse_id']].append(info)
    if age != calendar:
        info['half_year_pattern_matches'] = age == half_year
        differences.append(info)
transitions = []
for horse_id, events in history.items():
    for prev, curr in zip(events, events[1:]):
        if (prev['race_date'][:4] == curr['race_date'][:4]
            and prev['race_date'][5:] < '07-01' <= curr['race_date'][5:]
            and prev['race_age_raw'] + 1 == curr['race_age_raw']):
            transitions.append({'horse_id': horse_id, 'before': prev, 'after': curr})
result = {'database_read_only': True, 'profile_rows': len(profiles),
          'current_profile_calendar_formula_matches': sum(int(p['age']) == 2026-int(p['birthYr']) for p in profiles.values()),
          'formula_match_counts': dict(counts), 'by_year': {y:dict(v) for y,v in sorted(by_year.items())},
          'calendar_discrepancies': len(differences),
          'calendar_discrepancies_matching_half_year_pattern': sum(r['half_year_pattern_matches'] for r in differences),
          'calendar_discrepancies_not_matching_half_year_pattern': [r for r in differences if not r['half_year_pattern_matches']],
          'within_year_july_age_increment_pairs': len(transitions),
          'within_year_july_age_increment_horses': len({r['horse_id'] for r in transitions}),
          'historical_rule_status': 'Observed half-year pattern; historical official rule and effective dates not yet verified. Modern 2026 official Jeju plan says January 1.',
          'policy': 'Formula matches are overlapping comparisons, not mutually exclusive classifications. Do not overwrite source age.'}
(HERE/'age_convention_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
(HERE/'july_age_increment_pairs.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in transitions))
(HERE/'age_formula_differences.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in differences))
print(json.dumps({k:v for k,v in result.items() if k not in {'by_year','calendar_discrepancies_not_matching_half_year_pattern'}},ensure_ascii=False))
