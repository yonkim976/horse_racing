"""Read-only independent comparison of loaded daily rows to archived API items."""
import argparse,hashlib,json,re,sqlite3
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
RUN=Path(__file__).resolve().parent
RAW_KEYS=('chulGubun','hrName','hrNo','meet','part','partNo','prGubun','prNo','run1Cnt','run2Cnt','spTime','stTime','trDate','trName','trTerm')
def sha(p):
 d=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):d.update(b)
 return d.hexdigest()
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def identifier(key):return key+'_raw'
def moment(v):
 if v is None:return None
 s=str(v)
 return s[:4]+'-'+s[4:6]+'-'+s[6:8]+' '+s[8:10]+':'+s[10:12]+':'+s[12:14]
def run():
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists(),a.out
 c=sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
 baseline=json.loads((RUN/'database_before.json').read_text());source=json.loads((RUN/'independent_source_pages.json').read_text())
 monthly=ROOT/'research/20260929_api_monthly_history';ledger=json.loads((monthly/'ledger.json').read_text());expected_metadata={}
 for partition in ledger['partitions'].values():
  if partition.get('dataset')!='daily_training':continue
  pages=partition.get('pages',[])
  if partition.get('date_fallback'):pages=[p for d in partition['date_fallback']['dates'].values() for p in d['pages']]
  for meta in pages:
   key=(meta.get('public_params') or {}).get('tr_date',partition['month'])
   kind='daily_date_fallback' if len(key)==8 else 'sibling_month_archive' if meta['response_file'].startswith('../') else 'monthly_archive'
   expected_metadata[(monthly/meta['response_file']).resolve().relative_to(ROOT).as_posix()]=(key,kind,meta)
 print('Verifying original core and starting-training tables/schema',flush=True)
 for t,count in baseline['counts'].items():assert c.execute('SELECT COUNT(*) FROM "'+t.replace('"','""')+'"').fetchone()[0]==count,t
 for typ,n,sql in baseline['schema']:
  r=c.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?',(typ,n)).fetchone();assert r and r[0]==sql,(typ,n)
 profiles={r['horse_id']:dict(r) for r in c.execute('''WITH ranked AS(SELECT *,row_number() OVER(PARTITION BY horse_id ORDER BY observed_at_utc DESC,api_record_id DESC) profile_rank FROM horse_profile_observations) SELECT * FROM ranked WHERE profile_rank=1''')}
 assert len(profiles)==4617 and all(p['breed_label_raw']=='제주마' for p in profiles.values())
 artifacts={r['source_file_path']:dict(r) for r in c.execute('SELECT * FROM daily_training_api_artifacts')};assert len(artifacts)==len(source)==337
 cols={r['name'] for r in c.execute('PRAGMA table_info(daily_training_api_rows)')};rawmap={k:identifier(k) for k in RAW_KEYS};assert set(rawmap.values())<=cols,(rawmap,cols)
 required={'start_time_local','end_time_local','duration_seconds','duration_status','start_time_status','end_time_status','time_order_status','run1_count','run2_count','run1_count_status','run2_count_status'};assert required<=cols,('expected schema columns',required-cols,cols)
 n=0;states=Counter();after=0;horses=set();duration_valid=0;duration_null=0
 for pi,page in enumerate(source,1):
  path=ROOT/page['source_file'];assert sha(path)==page['sha256'];art=artifacts[page['source_file']];assert art['source_sha256']==page['sha256']
  data=json.loads(path.read_bytes())['response']['body'];items=data.get('items');items=items.get('item',[]) if isinstance(items,dict) else []
  if isinstance(items,dict):items=[items]
  expect=[(i,r,str(r['hrNo'])) for i,r in enumerate(items,1) if str(r.get('hrNo')) in profiles]
  assert len(items)==page['all_rows'] and len(expect)==page['native_rows']
  assert art['raw_item_count']==len(items) and art['profile_matched_row_count']==len(expect)
  assert art['excluded_nonprofile_row_count']==len(items)-len(expect)
  invalid=sum(re.fullmatch('[0-9]+',str(r.get('hrNo'))) is None for r in items)
  assert art['quarantined_invalid_id_count']==invalid
  assert art['page_no']==page['page_no'] and art['status_code']==200 and art['api_result_code']=='00'
  expected_partition,expected_kind,meta=expected_metadata[page['source_file']]
  assert art['source_partition_key']==expected_partition
  assert art['source_page_kind']==expected_kind
  assert art['requested_at_ms']==meta.get('requested_at_ms') and art['retrieved_at_ms']==meta.get('retrieved_at_ms')
  rows=c.execute('SELECT * FROM daily_training_api_rows WHERE daily_training_api_artifact_id=? ORDER BY source_row_index',(art['daily_training_api_artifact_id'],)).fetchall();assert len(rows)==len(expect)
  for stored,(i,raw,h) in zip(rows,expect):
   assert stored['source_row_index']==i and stored['horse_id']==h
   assert stored['raw_row_json']==canonical(raw),(page['source_file'],i,'JSON')
   for k,col in rawmap.items():assert stored[col]==(None if k not in raw or raw[k] is None else str(raw[k])),(page['source_file'],i,k)
   assert stored['horse_profile_observation_id']==profiles[h]['horse_profile_observation_id']
   d=str(raw['trDate']);date=d[:4]+'-'+d[4:6]+'-'+d[6:8];assert stored['training_date']==date
   assert stored['start_time_local']==moment(raw.get('stTime')) and stored['end_time_local']==moment(raw.get('spTime'))
   term=raw['trTerm'];valid=term>0
   assert stored['duration_seconds']==(term if valid else None)
   assert stored['duration_status']==('positive_matches_valid_times' if valid else 'raw_zero_unavailable')
   assert stored['start_time_status']==stored['end_time_status']==('valid_same_event_date' if valid else 'missing')
   assert stored['time_order_status']==('ordered' if valid else 'unavailable')
   assert stored['run1_count'] is None and stored['run2_count'] is None and stored['run1_count_status']==stored['run2_count_status']=='all_zero_unavailable'
   duration_valid+=valid;duration_null+=not valid;horses.add(h);after+=date>'2026-09-19';states[stored['duration_status']]+=1;n+=1
  if pi%50==0:print('Compared source pages',pi,'native rows',n,flush=True)
 assert n==908316 and len(horses)==4545 and after==927 and duration_valid==890288 and duration_null==18028
 assert c.execute('SELECT COUNT(*) FROM daily_training_api_rows').fetchone()[0]==n
 assert c.execute('SELECT SUM(quarantined_invalid_id_count) FROM daily_training_api_artifacts').fetchone()[0]==3
 assert c.execute('SELECT COUNT(*) FROM (SELECT horse_id,training_date FROM daily_training_api_rows GROUP BY horse_id,training_date HAVING COUNT(*)>1)').fetchone()[0]==0
 print('Verifying latest-name/fixed-2026-age view',flush=True)
 v=c.execute('SELECT horse_id,current_horse_name,current_horse_age_2026,current_horse_age_reference_year,training_date FROM daily_training_api_rows_analysis_2026');count=0
 for h,name,age,year,date in v:
  pr=profiles[h];birth=(pr['birth_date_raw'] or '').strip();expectage=2026-int(birth[:4]) if len(birth)>=4 and re.fullmatch('[0-9]{4}',birth[:4]) and 1<=int(birth[:4])<=2026 else None
  assert name==pr['horse_name_raw'] and age==expectage and year==2026 and date<='2026-09-19';count+=1
 assert count==907389
 sample=dict(c.execute("SELECT * FROM daily_training_api_rows_analysis_2026 WHERE horse_id=? AND training_date=?",('3107491','2026-09-16')).fetchone())
 assert sample['start_time_local']=='2026-09-16 06:09:00' and sample['end_time_local']=='2026-09-16 06:30:00' and sample['duration_seconds']==1260 and sample['duration_minutes']==21.0
 assert sample['prNo_raw']=='003086' and sample['trName_raw']=='문성호'
 assert c.execute("SELECT COUNT(*) FROM daily_training_api_rows WHERE horse_id=? AND training_date=?",('3107491','2026-09-18')).fetchone()[0]==0
 print('Checking SQLite integrity and foreign keys',flush=True);assert [tuple(x) for x in c.execute('PRAGMA integrity_check')]==[('ok',)];assert not c.execute('PRAGMA foreign_key_check').fetchall();c.close()
 out={'created_at_utc':datetime.now(timezone.utc).isoformat(),'database':str(a.db.resolve()),'database_sha256':sha(a.db),'original_table_counts_unchanged':True,'original_schema_definitions_unchanged':True,'all_loaded_fields_match_api_raw':True,'source_pages':337,'raw_api_rows':1444319,'native_rows':n,'native_horses':len(horses),'analysis_rows_through_20260919':count,'after_cutoff_rows_retained':after,'duration_status_counts':dict(states),'same_horse_date_repeats':0,'latest_name_and_fixed_2026_age_match':True,'screenshot_sample_matches':True,'race_day_placeholder_not_synthesized':True,'integrity_check':'ok','foreign_key_violations':0}
 a.out.write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':run()
