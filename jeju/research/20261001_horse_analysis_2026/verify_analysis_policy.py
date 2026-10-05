"""Independent read-only verification of analysis views and source preservation."""
import hashlib
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
conn = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
baseline = json.loads((HERE / 'before_snapshot.json').read_text())

def ident(name):
    return '"' + name.replace('"', '""') + '"'

preservation = {}
for table, before in baseline['tables'].items():
    digest = hashlib.sha256()
    old_count = 0
    for row in conn.execute('SELECT * FROM ' + ident(table) + ' ORDER BY rowid LIMIT ?', (before['rows'],)):
        old_count += 1
        digest.update((json.dumps(tuple(row), ensure_ascii=False, separators=(',', ':')) + '\n').encode())
    assert old_count == before['rows'] and digest.hexdigest() == before['ordered_rows_sha256'], table
    current_count = conn.execute('SELECT count(*) FROM ' + ident(table)).fetchone()[0]
    if table not in {'schema_metadata', 'provenance_issues'}:
        assert current_count == before['rows'], table
    preservation[table] = {'existing_rows_preserved': True, 'before_count': before['rows'], 'after_count': current_count}
for name, sql in baseline['views'].items():
    assert conn.execute('SELECT sql FROM sqlite_master WHERE name=? AND type=?', (name, 'view')).fetchone()[0] == sql, name

profiles = {row['horse_id']: json.loads(row['payload_json']) for row in conn.execute('SELECT horse_id,payload_json FROM horse_profile_latest')}
horse_rows = list(conn.execute('SELECT * FROM horse_analysis_2026'))
assert len(horse_rows) == len(profiles) == 4617
for row in horse_rows:
    profile = profiles[row['horse_id']]
    assert row['horse_name'] == profile['hrNm']
    assert row['age'] == row['age_2026'] == 2026-int(profile['birthYr'])
    assert isinstance(row['age'], int) and row['age_reference_year'] == 2026

checks = {}
cases = {}
for view, source, historic_age in [
    ('jeju_race_analysis_2026', 'jeju_race_candidate_passing_with_corner_rank', 'age_at_race_raw'),
    ('jeju_trial_analysis_2026', 'api_explicit_jeju_trial_rows', 'age_at_trial_raw'),
]:
    cols = [row[1] for row in conn.execute('PRAGMA table_info(' + ident(source) + ')')]
    raw_cols = ','.join('s.' + ident(col) + ' AS ' + ident('source_' + str(i)) for i,col in enumerate(cols))
    query = ('SELECT n.*,' + raw_cols + ',a.payload_json AS source_payload_json FROM ' + ident(view) +
             ' n JOIN ' + ident(source) + ' s ON s.api_record_id=n.api_record_id '
             'JOIN api_records a ON a.api_record_id=n.api_record_id ORDER BY n.api_record_id')
    ids = set()
    n = 0
    for row in conn.execute(query):
        n += 1
        assert row['api_record_id'] not in ids
        ids.add(row['api_record_id'])
        profile = profiles[row['horse_id']]
        payload = json.loads(row['source_payload_json'])
        assert row['horse_name'] == profile['hrNm']
        assert row['age'] == row['age_2026'] == 2026-int(profile['birthYr'])
        assert isinstance(row['age'], int) and row['age_reference_year'] == 2026
        assert row[historic_age] == payload['age']
        assert row['sex'] == payload['sex']
        assert row['sex_current_profile'] == profile['sex']
        for i,col in enumerate(cols):
            expected = row['source_' + str(i)]
            actual = row['historical_horse_name_raw'] if col == 'horse_name' else row[col]
            assert actual == expected, (view,row['api_record_id'],col)
        if row['horse_id'] in {'3107458','3005897','3009880','3014439'}:
            cases.setdefault(row['horse_id'], []).append({k:row[k] for k in ['api_record_id','horse_id','horse_name','historical_horse_name_raw','age','age_2026','age_reference_year',historic_age,'sex','sex_current_profile']})
    expected_ids = {row[0] for row in conn.execute('SELECT api_record_id FROM ' + ident(source))}
    assert ids == expected_ids
    assert conn.execute('SELECT count(*) FROM ' + ident(view)).fetchone()[0] == n
    checks[view] = {'rows':n,'all_ids_preserved':True,'no_duplicates':True,'latest_names_and_fixed_2026_ages_match':True,
                    'source_sex_and_event_age_preserved':True,'all_original_columns_preserved':True}

assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
assert not list(conn.execute('PRAGMA foreign_key_check'))
issues = [dict(row) for row in conn.execute('SELECT * FROM provenance_issues WHERE api_record_id=?', (326,))]
assert issues, 'Torjong sex source conflict must be recorded'
result = {'database_read_only':True,'existing_views_unchanged':True,'source_preservation':preservation,
          'horse_analysis_rows':len(horse_rows),'views':checks,'case_samples':cases,
          'torjong_conflict_records':issues,'integrity_check':'ok','foreign_key_violations':0}
(HERE/'root_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in {'case_samples','torjong_conflict_records','source_preservation'}},ensure_ascii=False))
