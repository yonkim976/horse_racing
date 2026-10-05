import argparse,hashlib,json,sqlite3
from pathlib import Path
from collections import Counter
p=argparse.ArgumentParser();p.add_argument('--database',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
a=p.parse_args(); root=Path('/Users/kimyongjin/Desktop/horse_racing/jeju'); run=root/'research/20261001_starting_training_website_load'
m=json.loads((run/'collection/collection_manifest.json').read_text())
old=json.loads(Path('/private/tmp/jeju_training_db_before.json').read_text())
c=sqlite3.connect(a.database.resolve().as_uri()+'?mode=ro',uri=True)
print('Checking original tables',flush=True)
new_counts={t:c.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0] for t in old['counts']}
assert new_counts==old['counts'],(old['counts'],new_counts)
expected={(d['date'],r['source_row_no']):r for d in m['dates'] for r in d['rows']}
print('Comparing all homepage rows',flush=True)
actual=c.execute('SELECT a.training_date,r.source_row_no,r.horse_id_raw,r.affiliation_raw,r.trainer_no_raw,r.horse_name_raw,r.rider_raw,r.location_raw,r.note_raw FROM starting_training_website_rows r JOIN website_training_artifacts a USING(website_artifact_id) ORDER BY a.training_date,r.source_row_no')
n=0
for row in actual:
    e=expected[(row[0],row[1])]
    assert tuple(row[2:])==tuple(e[k] for k in ['horse_id_raw','affiliation','trainer_no','horse_name','rider','location','note'])
    n+=1
assert n==len(expected)==295470
print('Checking counts and analysis values',flush=True)
artifacts=c.execute('SELECT COUNT(*) FROM website_training_artifacts').fetchone()[0]; assert artifacts==2529
native_count=c.execute('SELECT COUNT(*) FROM starting_training_website_rows_latest').fetchone()[0];assert native_count==190842
analysis_count=c.execute('SELECT COUNT(*) FROM starting_training_website_rows_analysis_2026').fetchone()[0];assert analysis_count==190790
profile_ids=c.execute('SELECT COUNT(DISTINCT horse_id) FROM starting_training_website_rows_latest').fetchone()[0];assert profile_ids==4476
assert c.execute('SELECT COUNT(*) FROM starting_training_website_rows_analysis_2026 WHERE current_horse_age_reference_year<>2026 OR current_horse_age_reference_year IS NULL').fetchone()[0]==0
profile_query = """WITH ranked AS (
    SELECT horse_id,horse_name_raw,birth_date_raw,row_number() OVER(
      PARTITION BY horse_id ORDER BY observed_at_utc DESC,api_record_id DESC) AS profile_rank
    FROM horse_profile_observations)
    SELECT horse_id,horse_name_raw,
      CASE WHEN length(trim(birth_date_raw))>=4
       AND substr(trim(birth_date_raw),1,4) NOT GLOB '*[^0-9]*'
       AND CAST(substr(trim(birth_date_raw),1,4) AS INTEGER) BETWEEN 1 AND 2026
      THEN 2026-CAST(substr(trim(birth_date_raw),1,4) AS INTEGER) ELSE NULL END
    FROM ranked WHERE profile_rank=1"""
expected_profiles={row[0]:(row[1],row[2]) for row in c.execute(profile_query)}
for h,name,age in c.execute('SELECT horse_id,current_horse_name,current_horse_age_2026 FROM starting_training_website_rows_analysis_2026'):
    assert (name,age)==expected_profiles[h]
# Existing table definitions and views must remain exactly unchanged.
for type_,name,sql in old['schema']:
    row=c.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?',(type_,name)).fetchone()
    assert row and row[0]==sql,(type_,name)
checks={}
for h in ['3103304','3102101','3103797']:
    rows=c.execute("SELECT horse_name_raw,location_raw FROM starting_training_website_rows_latest WHERE horse_id=? AND training_date='2024-01-17' ORDER BY source_row_no",(h,)).fetchall()
    assert len(rows)==2 and {r[1] for r in rows}=={'400M 출발지점','800M 출발지점'}
    checks[h]=rows
web_only=c.execute("SELECT COUNT(*) FROM starting_training_website_rows_latest WHERE training_date='2024-01-17' AND json_extract(api_evidence_json,'$.same_horse_date_item_count')=0").fetchone()[0];assert web_only==27
print('Checking database integrity',flush=True)
integrity=c.execute('PRAGMA integrity_check').fetchall();assert integrity==[('ok',)]
foreign_keys=c.execute('PRAGMA foreign_key_check').fetchall();assert not foreign_keys
status=Counter(dict(c.execute('SELECT matching_status,COUNT(*) FROM starting_training_website_rows GROUP BY matching_status').fetchall()))
summary={'database':str(a.database),'original_table_counts_unchanged':True,'original_schema_definitions_unchanged':True,'all_inserted_fields_match_verified_homepage':True,'artifacts':artifacts,'website_rows':n,'native_rows':native_count,'analysis_rows_through_20260919':analysis_count,'native_horses':profile_ids,'latest_name_and_fixed_2026_age_match':True,'january_17_three_horses':checks,'january_17_native_website_only_rows':web_only,'matching_status_counts':dict(status),'integrity_check':'ok','foreign_key_violations':0,'database_sha256':hashlib.sha256(a.database.read_bytes()).hexdigest()}
a.out.write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False,indent=2))
