"""Read-only API42 storage completeness and historical entry identity audit."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
PLACEHOLDERS = {'', '-', '0', 'n/a', 'null', 'none', 'unknown'}


def clean(value):
    return '' if value is None else str(value).strip()


def usable(value):
    return clean(value).lower() not in PLACEHOLDERS


def main():
    conn = sqlite3.connect(DB.as_uri()+'?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    profiles = {}
    field_counts = Counter()
    for row in conn.execute('SELECT * FROM horse_profile_latest'):
        payload = json.loads(row['payload_json'])
        if hashlib.sha256(row['payload_json'].encode()).hexdigest() != row['payload_sha256']:
            raise ValueError('Profile item hash differs')
        if clean(payload['hrNo']) != row['horse_id']:
            raise ValueError('Profile returned ID differs')
        if row['horse_id'] in profiles:
            raise ValueError('Duplicate latest profile ID')
        profiles[row['horse_id']] = payload
        field_counts[len(payload)] += 1
    if len(profiles) != 4617 or field_counts != Counter({218:4617}):
        raise ValueError('Expected complete 4,617 x 218 profile objects')

    counts = Counter()
    races = set()
    ids = set()
    comparisons = {'name':Counter(), 'sex':Counter(), 'age_from_profile_birth_year':Counter()}
    mismatches = {key:[] for key in comparisons}
    missing = []
    raw_id_mismatches = []
    for row in conn.execute('''SELECT r.*,a.payload_json FROM jeju_race_population_candidates r
        JOIN api_records a USING(api_record_id) ORDER BY r.race_date,r.race_number,r.horse_number'''):
        counts['candidate_entry_rows'] += 1
        ids.add(row['horse_id'])
        races.add((row['race_date'],row['meet_code'],row['race_number']))
        race = json.loads(row['payload_json'])
        key = {'api_record_id':row['api_record_id'],'race_date':row['race_date'],
               'race_number':row['race_number'],'horse_number':row['horse_number'],
               'horse_id':row['horse_id'],'race_horse_name':row['horse_name']}
        if clean(race['hrNo']) != row['horse_id']:
            raw_id_mismatches.append(key)
        p = profiles.get(row['horse_id'])
        if p is None:
            missing.append(key)
            continue
        counts['matched_candidate_entry_rows'] += 1
        if clean(race.get('hrName')) == clean(p.get('hrNm')):
            comparisons['name']['current_name_exact_match'] += 1
        elif usable(p.get('beforeHrNm')) and clean(race.get('hrName')) == clean(p.get('beforeHrNm')):
            comparisons['name']['matches_profile_previous_name'] += 1
            mismatches['name'].append({**key,'profile_name':p.get('hrNm'),'profile_previous_name':p.get('beforeHrNm'),'category':'matches_profile_previous_name'})
        else:
            comparisons['name']['unexplained_name_difference'] += 1
            mismatches['name'].append({**key,'profile_name':p.get('hrNm'),'profile_previous_name':p.get('beforeHrNm'),'category':'unexplained_name_difference'})
        old_sex,new_sex = clean(race.get('sex')),clean(p.get('sex'))
        if not usable(old_sex) or not usable(new_sex):
            comparisons['sex']['not_comparable'] += 1
        elif old_sex==new_sex:
            comparisons['sex']['exact_match'] += 1
        else:
            category='historical_male_current_gelding' if (old_sex,new_sex)==('수','거') else 'other_sex_difference'
            comparisons['sex'][category] += 1
            mismatches['sex'].append({**key,'race_sex':old_sex,'profile_sex':new_sex,'profile_sex_history':p.get('sexHis'),'category':category})
        race_age=clean(race.get('age'))
        birth_year=clean(p.get('birthYr'))
        if race_age.isdigit() and birth_year.isdigit() and int(race_age)>0:
            expected=int(row['race_date'][:4])-int(birth_year)
            if int(race_age)==expected:
                comparisons['age_from_profile_birth_year']['match'] += 1
            else:
                comparisons['age_from_profile_birth_year']['difference_requires_review'] += 1
                mismatches['age_from_profile_birth_year'].append({**key,'race_age_raw':race.get('age'),'profile_birth_date_raw':p.get('birthDt'),'profile_birth_year_raw':p.get('birthYr'),'year_difference_expected_age':expected})
        else:
            comparisons['age_from_profile_birth_year']['not_comparable'] += 1

    for field, rows in mismatches.items():
        (HERE/(field+'_differences.jsonl')).write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows))
    (HERE/'unmatched_candidates.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in missing))
    trial_ids={row[0] for row in conn.execute('SELECT DISTINCT horse_id FROM running_trial_rows')}
    all_race_ids={row[0] for row in conn.execute('SELECT DISTINCT horse_id FROM race_result_rows')}
    linked_all_race_rows=conn.execute('''SELECT count(*) FROM race_result_rows r
        JOIN horse_profile_latest p ON p.horse_id=r.horse_id''').fetchone()[0]
    result={'database':str(DB.relative_to(ROOT)), 'profile_count':len(profiles),
            'profile_field_counts':dict(field_counts), 'full_profile_item_hashes_valid':True,
            'candidate_entry_rows':counts['candidate_entry_rows'], 'candidate_races':len(races),
            'candidate_horse_ids':len(ids), 'candidate_date_range':list(conn.execute('SELECT min(race_date),max(race_date) FROM jeju_race_population_candidates').fetchone()),
            'matched_candidate_entry_rows':counts['matched_candidate_entry_rows'],
            'unmatched_candidate_entries':len(missing),
            'normalized_vs_raw_race_horse_id_differences':len(raw_id_mismatches),
            'candidate_profile_ids_exactly_same':ids <= set(profiles),
            'profile_ids_with_any_race_results':len(set(profiles)&all_race_ids),
            'all_race_entry_rows_for_profile_ids':linked_all_race_rows,
            'profile_ids_with_any_trials':len(set(profiles)&trial_ids),
            'profile_ids_with_trials_but_no_race_results':len((set(profiles)&trial_ids)-all_race_ids),
            'comparison_counts':{key:dict(value) for key,value in comparisons.items()},
            'difference_horse_counts':{key:len({row['horse_id'] for row in value}) for key,value in mismatches.items()},
            'unexplained_name_horse_ids':sorted({r['horse_id'] for r in mismatches['name'] if r['category']=='unexplained_name_difference'}),
            'other_sex_difference_horse_ids':sorted({r['horse_id'] for r in mismatches['sex'] if r['category']=='other_sex_difference'}),
            'age_difference_horse_ids':sorted({r['horse_id'] for r in mismatches['age_from_profile_birth_year']}),
            'age_comparison_policy':'Calendar race year minus current profile birth year is a consistency check, not a verified historical age convention or a direct birth-date comparison.',
            'writes_to_database':False}
    (HERE/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))
    conn.close()


if __name__=='__main__':
    main()
