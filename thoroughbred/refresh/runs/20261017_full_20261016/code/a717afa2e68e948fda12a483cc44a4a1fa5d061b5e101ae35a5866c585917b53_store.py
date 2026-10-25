"""Append-only research refresh with immutable baseline, correction holds and staged commit."""
from __future__ import annotations
import argparse,csv,json,os,subprocess,sys
from collections import Counter,defaultdict
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import duckdb
import pyarrow as pa
from common import ROOT,canonical,digest,sha,save_json,now,domain_lock
import races,auxiliary
CORE=ROOT/'thoroughbred/data/core_api_2010_20260929_v1'
DB=CORE/'thoroughbred_core.duckdb';MANIFEST=CORE/'manifest.json'
FIXED=CORE/'backups/20261017_before_incremental_refresh'
SCHEMA='''
CREATE TABLE IF NOT EXISTS refresh_baseline_keys(family VARCHAR,key_json VARCHAR,payload_sha256 VARCHAR,occurrence_no INTEGER,locator_json VARCHAR,baseline_record_id VARCHAR,source_file VARCHAR,source_sha256 VARCHAR,semantic_sha256 VARCHAR,PRIMARY KEY(family,key_json,payload_sha256,occurrence_no));
CREATE TABLE IF NOT EXISTS refresh_event_records(record_id VARCHAR PRIMARY KEY,family VARCHAR NOT NULL,key_json VARCHAR NOT NULL,event_date DATE NOT NULL,meet VARCHAR NOT NULL CHECK(meet IN ('1','3','4')),horse_id VARCHAR,race_no VARCHAR,payload_json VARCHAR NOT NULL,fields_json VARCHAR NOT NULL,payload_sha256 VARCHAR NOT NULL,occurrence_no INTEGER NOT NULL CHECK(occurrence_no>0),source_file VARCHAR NOT NULL,source_sha256 VARCHAR NOT NULL,source_row_no INTEGER,captured_at_utc VARCHAR NOT NULL,availability_status VARCHAR NOT NULL,run_id VARCHAR NOT NULL,disposition VARCHAR NOT NULL CHECK(disposition IN ('accepted','correction_hold','excluded')),locator_json VARCHAR,disposition_reason VARCHAR);
CREATE TABLE IF NOT EXISTS refresh_runs(run_id VARCHAR PRIMARY KEY,applied_at_utc VARCHAR,window_start DATE,window_end DATE,collection_file VARCHAR,collection_sha256 VARCHAR,report_json VARCHAR);
CREATE TABLE IF NOT EXISTS refresh_partition_checks(run_id VARCHAR,request_id VARCHAR,family VARCHAR,request_meet VARCHAR,params_json VARCHAR,complete BOOLEAN,loadable BOOLEAN,raw_rows BIGINT,normalized_rows BIGINT,error VARCHAR,captured_at_utc VARCHAR,PRIMARY KEY(run_id,request_id));
CREATE TABLE IF NOT EXISTS refresh_missing_candidates(run_id VARCHAR,family VARCHAR,key_json VARCHAR,payload_sha256 VARCHAR,occurrence_no INTEGER,reason VARCHAR,PRIMARY KEY(run_id,family,key_json,payload_sha256,occurrence_no));
CREATE TABLE IF NOT EXISTS refresh_link_review(run_id VARCHAR,record_id VARCHAR,reason VARCHAR,PRIMARY KEY(run_id,record_id,reason));
'''

def semantic_payload(value):
 if isinstance(value,dict):return {k:semantic_payload(v) for k,v in value.items()}
 if isinstance(value,list):return [semantic_payload(v) for v in value]
 if isinstance(value,(int,float)) and not isinstance(value,bool):return str(value)
 return value
def semantic_hash(payload,family):
 # API180 etlTime is its response-processing clock ('HH:MM 현재'), not
 # a sanction event attribute. Its raw text remains in both source captures.
 if family=='sanctions':payload={k:v for k,v in payload.items() if k!='etlTime'}
 return digest(canonical(semantic_payload(payload)).encode())
def exists(c,name):return bool(c.execute('SELECT count(*) FROM information_schema.tables WHERE table_name=?',[name]).fetchone()[0])
def locator(row):
 f=row['family'];p=row['payload'];a=row.get('fields',{});common=[str(row['meet']),row['event_date']]
 if f in {'race_schedule','passing_groups','steward_reports'}:return canonical(common+[row.get('race_no')])
 if f in {'race_results','entry_sheets','body_weights','public_cards'}:return canonical(common+[row.get('race_no'),str(a.get('horse_no_raw') or a.get('horse_no') or '')])
 if f=='trial_results':return canonical(common+[str(p.get('trainNo','')),str(p.get('chulNo',''))])
 if f=='daily_training':return canonical(common+[row.get('horse_id')])
 if f=='starting_exam':return canonical(common+[str(p.get('trainNo','')),str(p.get('chulNo',''))])
 if f in {'start_training','swim_training','medical'}:return canonical(common+[row.get('horse_id')])
 return canonical(row.get('key') or json.loads(row['key_json']))
def excluded_races():
 keys=set();folder=ROOT/'thoroughbred/research/20260929_calendar_api_v1'
 for name in ('planless_positive_result_review.csv','result_only_nonfinish_anomaly_review.csv'):
  with (folder/name).open(encoding='utf-8',newline='') as f:
   for row in csv.DictReader(f):keys.add((str(row['meet']),row['date'].replace('-',''),str(int(row['race_no']))))
 if len(keys)!=72:raise ValueError('reviewed_ghost_race_policy_changed')
 return keys

def prepare(run):
 collection=run/'collection.json';meta=json.loads(collection.read_text());start,end=meta['start'],meta['end']
 if meta.get('status')!='collected':raise ValueError('collection_not_finished')
 baseline_db_hash=sha(DB);baseline_manifest_hash=sha(MANIFEST)
 if json.loads(MANIFEST.read_text())['database_sha256']!=baseline_db_hash:raise ValueError('baseline_manifest_DB_mismatch')
 c=duckdb.connect(str(DB),read_only=True);c.execute('SET threads=2')
 if exists(c,'refresh_runs') and c.execute('SELECT count(*) FROM refresh_runs WHERE run_id=?',[meta['run_id']]).fetchone()[0]:
  c.close();return {'status':'already_applied','run_id':meta['run_id'],'database_sha256':baseline_db_hash}
 seed=[];seedcounts=Counter();seen=set();counts_by_payload=Counter();known_payloads=defaultdict(set);known_locators=set();known_record_ids=set();prior_payload_values=defaultdict(list)
 baseline_fingerprints=Counter();semantic_counts=Counter();baseline_semantics={};distances=defaultdict(set)
 if exists(c,'refresh_baseline_keys'):
  for f,k,h,o,loc,rid,sf,sh,sem in c.execute('SELECT * FROM refresh_baseline_keys').fetchall():
   seen.add((f,k,h,o));semantic_counts[(f,loc,sem)]+=1;baseline_semantics[(f,k,h)]=(loc,sem);counts_by_payload[(f,k,h)]=max(counts_by_payload[(f,k,h)],o);known_payloads[(f,k)].add(h);known_locators.add((f,loc))
 if exists(c,'refresh_event_records'):
  for rid,f,k,h,o,loc,disp,payload in c.execute('SELECT record_id,family,key_json,payload_sha256,occurrence_no,locator_json,disposition,payload_json FROM refresh_event_records').fetchall():
   known_record_ids.add(rid)
   if disp=='accepted':prior_payload_values[(f,k)].append(json.loads(payload));semantic_counts[(f,loc,semantic_hash(json.loads(payload),f))]+=1;known_payloads[(f,k)].add(h);known_locators.add((f,loc))
 for module in (races,auxiliary):
  for row in module.iter_baseline_rows(c,start,end):
   f=row['family'];k=canonical(row.get('key') or json.loads(row['key_json']));p=canonical(row['payload']);h=digest(p.encode());loc=locator(row)
   prior_payload_values[(f,k)].append(row['payload'])
   sem=semantic_hash(row['payload'],f);baseline_semantics[(f,k,h)]=(loc,sem)
   if f=='race_schedule' and row.get('fields',{}).get('distance_m'):distances[(row['meet'],row['event_date'],str(row.get('race_no')))].add(row['fields']['distance_m'])
   baseline_fingerprints[(f,k,h)]+=1;o=baseline_fingerprints[(f,k,h)]
   if (f,k,h,o) not in seen:
    seed.append([f,k,h,o,loc,digest(canonical([f,k,h,o]).encode()),row.get('source_file'),row.get('source_sha256'),sem]);semantic_counts[(f,loc,sem)]+=1;seen.add((f,k,h,o));seedcounts[f]+=1
   counts_by_payload[(f,k,h)]=max(counts_by_payload[(f,k,h)],o);known_payloads[(f,k)].add(h);known_locators.add((f,loc))
 c.close()
 # Snapshot prior locators. Distinct same-day source occurrences in this fresh batch
 # remain distinct; only collisions with already-held research history need review.
 prior_locators=set(known_locators);prior_payloads={k:set(v) for k,v in known_payloads.items()}
 freshcounts=Counter();fresh_sem_counts=Counter();records=[];stats=defaultdict(Counter);bundles=[];sources={};policy=excluded_races();fresh_seen=set();family_complete=defaultdict(lambda:True)
 for b in meta['bundles']:
  f=b['family'];request_id=digest(canonical([f,b['endpoint'],b['params']]).encode())
  ok=bool(b.get('complete') and b.get('loadable'));family_complete[f]&=ok
  bundles.append([meta['run_id'],request_id,f,b['meet'],canonical(b['params']),b['complete'],ok,b.get('total_count'),b.get('normalized_rows'),b.get('error') or ('normalization_errors' if b.get('normalization_errors') else None),b.get('captured_at_utc')])
  for page in b.get('pages',[]):
   path=ROOT/page['source_file']
   if not path.resolve().is_relative_to(ROOT/'thoroughbred'):raise ValueError('source_outside_domain')
   if sha(path)!=page['source_sha256']:raise ValueError('source_hash_mismatch')
   sources[page['source_file']]=page['source_sha256']
  if not ok:stats[f]['failed_bundles']+=1;continue
  normalized=(ROOT/b['normalized_file']).resolve()
  if not normalized.is_relative_to(ROOT/'thoroughbred'):raise ValueError('normalized_outside_domain')
  if sha(normalized)!=b['normalized_sha256']:raise ValueError('normalized_hash_mismatch')
  sources[b['normalized_file']]=b['normalized_sha256']
  for line in normalized.read_text(encoding='utf-8').splitlines():
   row=json.loads(line)
   if f in {spec['family'] for spec in races.FAMILY_SPECS}:
    fresh=races.transform(f,row['payload'],{'meet':row['meet'],'captured_at_utc':row['captured_at_utc'],'request_params':b['params'],'requested_date':b['params'].get('race_dt') or b['params'].get('rc_date')});row.update(fresh)
   if f=='race_schedule' and row.get('fields',{}).get('distance_m'):distances[(row['meet'],row['event_date'],str(row.get('race_no')))].add(row['fields']['distance_m'])
   if hasattr(races,'enrich_row') and f in {'race_results','passing_groups','body_weights'}:
    ds=distances.get((row['meet'],row['event_date'],str(row.get('race_no'))),set());row=races.enrich_row(row,distance_m=next(iter(ds)) if len(ds)==1 else None)
   k=canonical(row.get('key') or json.loads(row['key_json']));payload=canonical(row['payload']);h=digest(payload.encode());loc=locator(row);freshcounts[(f,k,h)]+=1;o=freshcounts[(f,k,h)];rid=digest(canonical([f,k,h,o]).encode());fresh_seen.add((f,k,h,o))
   sem=semantic_hash(row['payload'],f);fresh_sem_counts[(f,loc,sem)]+=1
   stats[f]['observed_rows']+=1
   if rid in known_record_ids:stats[f]['already_observed_refresh_rows']+=1;continue
   if o<=counts_by_payload[(f,k,h)]:stats[f]['existing_baseline_rows']+=1;continue
   if fresh_sem_counts[(f,loc,sem)]<=semantic_counts[(f,loc,sem)]:stats[f]['verified_format_equivalent_rows']+=1;continue
   disp='accepted';reason='new_source_observation'
   capture_day=datetime.fromisoformat(row['captured_at_utc']).astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
   live_snapshot=f in {'race_schedule','public_cards','entry_sheets','body_weights'} and row['event_date']>=capture_day
   delayed_weight_fill=False
   if f=='body_weights' and row.get('fields',{}).get('horse_weight_kg'):
    for old in prior_payload_values.get((f,k),[]):
     old_weight=old.get('wgHr');nonweight=set(old)|set(row['payload']);nonweight-= {'wgHr','wgHrDiff'}
     if old_weight in {0,'0',None,'','-'} and all(semantic_payload(old.get(x))==semantic_payload(row['payload'].get(x)) for x in nonweight):delayed_weight_fill=True
   if live_snapshot:reason='official_current_or_future_snapshot_version'
   elif delayed_weight_fill:reason='first_published_positive_weight_after_placeholder'
   racekey=(str(row['meet']),row['event_date'].replace('-',''),str(row.get('race_no') or ''))
   if f in {'race_results','race_schedule','passing_groups','public_cards','entry_sheets','body_weights','steward_reports'} and racekey in policy:disp='excluded';reason='previously_confirmed_ghost_race'
   elif not f.endswith('_profile') and not live_snapshot and not delayed_weight_fill and prior_payloads.get((f,k)) and h not in prior_payloads[(f,k)]:disp='correction_hold';reason='same_natural_key_changed_payload'
   elif not f.endswith('_profile') and not live_snapshot and not delayed_weight_fill and (f,loc) in prior_locators and (f,k) not in prior_payloads:disp='correction_hold';reason='same_event_locator_new_identity_or_descriptor'
   values=[rid,f,k,row['event_date'],str(row['meet']),row.get('horse_id'),row.get('race_no'),payload,canonical(row['fields']),h,o,row['source_file'],row['source_sha256'],row['source_row_no'],row['captured_at_utc'],'observed_at_capture_only',meta['run_id'],disp,loc,reason]
   records.append(values);stats[f][disp+'_new_rows']+=1
   known_record_ids.add(rid)
 missing=[]
 for (f,k,h),n in counts_by_payload.items():
  if f not in family_complete or not family_complete[f] or f.endswith('_profile'):continue
  # Baseline seeding is window-limited. Missing rows never delete an old value.
  loc,sem=baseline_semantics.get((f,k,h),(None,None))
  if loc is not None and fresh_sem_counts[(f,loc,sem)]>=semantic_counts[(f,loc,sem)]:continue
  if freshcounts[(f,k,h)]<n:
   for o in range(freshcounts[(f,k,h)]+1,n+1):missing.append([meta['run_id'],f,k,h,o,'not_returned_by_complete_requery; preserve_existing_record'])
 dependencies=[ROOT/x for x in ('src/horse_racing/parsers/horse_history.py','src/horse_racing/parsers/race_supplemental.py','src/horse_racing/parsers/race_day.py','src/horse_racing/config.py','pyproject.toml','uv.lock','thoroughbred/refresh/run.py') if (ROOT/x).is_file()]
 for path in [*dependencies,collection,*[Path(m.__file__) for m in (races,auxiliary)],Path(__file__),Path(__file__).with_name('common.py'),Path(__file__).with_name('collect.py')]:sources[path.relative_to(ROOT).as_posix()]=sha(path)
 try:
  import views
  sources[Path(views.__file__).relative_to(ROOT).as_posix()]=sha(views.__file__)
 except ImportError:pass
 prepared={'status':'prepared','run_id':meta['run_id'],'start':start,'end':end,'public_through':meta.get('public_through',end),'baseline_database_sha256':baseline_db_hash,'baseline_manifest_sha256':baseline_manifest_hash,'collection_file':collection.relative_to(ROOT).as_posix(),'collection_sha256':sha(collection),'stats':{f:dict(v) for f,v in stats.items()},'seed_rows':seed,'event_rows':records,'partitions':bundles,'missing_candidates':missing,'seed_counts':dict(seedcounts),'sources':sources,'prepared_at_utc':now()}
 save_json(run/'prepared.json',prepared)
 save_json(run/'prepare_report.json',{k:v for k,v in prepared.items() if k not in {'seed_rows','event_rows','partitions','missing_candidates','sources'}}|{'event_rows':len(records),'missing_candidates':len(missing),'source_files':len(sources)})
 print(canonical({'status':'prepared','stats':prepared['stats'],'seed_rows':len(seed),'event_rows':len(records),'missing_candidates':len(missing)}),flush=True)
 return prepared

def install_stage(run,prepared):
 import views
 stage=run/'staged_core.duckdb'
 if stage.exists():stage.unlink()
 subprocess.run(['/bin/cp','-c',str(DB),str(stage)],check=True)
 c=duckdb.connect(str(stage));c.execute('SET threads=2');c.execute("SET memory_limit='2GB'")
 old_tables=dict(c.execute("select table_name,sql from duckdb_tables() where not internal").fetchall());old_views=dict(c.execute("select view_name,sql from duckdb_views() where not internal").fetchall())
 c.execute('BEGIN')
 try:
  c.execute(SCHEMA)
  if prepared['seed_rows']:
   names=[r[0] for r in c.execute('describe refresh_baseline_keys').fetchall()];c.register('_seed_input',pa.Table.from_pylist([dict(zip(names,row)) for row in prepared['seed_rows']]))
   c.execute('INSERT INTO refresh_baseline_keys SELECT * FROM _seed_input ON CONFLICT DO NOTHING');c.unregister('_seed_input')
  if prepared['event_rows']:
   names=[r[0] for r in c.execute('describe refresh_event_records').fetchall()];c.register('_event_input',pa.Table.from_pylist([dict(zip(names,row)) for row in prepared['event_rows']]))
   c.execute('INSERT INTO refresh_event_records SELECT * FROM _event_input ON CONFLICT DO NOTHING');c.unregister('_event_input')
  c.executemany('INSERT INTO refresh_partition_checks VALUES (?,?,?,?,?,?,?,?,?,?,?)',prepared['partitions'])
  if prepared['missing_candidates']:c.executemany('INSERT INTO refresh_missing_candidates VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING',prepared['missing_candidates'])
  views.install_current_views(c)
  check=validate_stage(c,prepared,old_tables,old_views)
  report={k:v for k,v in prepared.items() if k not in {'event_rows','seed_rows','partitions','missing_candidates','sources'}}|{'status':'applied','validation':check,'new_event_rows':len(prepared['event_rows']),'new_seed_rows':len(prepared['seed_rows']),'missing_candidates':len(prepared['missing_candidates'])}
  c.execute('INSERT INTO refresh_runs VALUES (?,?,?,?,?,?,?)',[prepared['run_id'],now(),prepared['start'],prepared['end'],prepared['collection_file'],prepared['collection_sha256'],canonical(report)])
  registered_sources={}
  for path,h in prepared['sources'].items():
   if path.endswith('.py') or path in {'pyproject.toml','uv.lock','thoroughbred/refresh/run.py'}:
    copy=run/'code'/(h+'_'+Path(path).name);copy.parent.mkdir(exist_ok=True);copy.write_bytes((ROOT/path).read_bytes());assert sha(copy)==h;registered_sources[str(copy.relative_to(ROOT))]=h
   else:registered_sources[path]=h
  source={'name':'refresh_'+prepared['run_id'],'window':{'start':prepared['start'],'end':prepared['end'],'public_through':prepared['public_through']},'sources':[{'path':k,'sha256':v} for k,v in registered_sources.items()],'summary':report,'availability_rule':'events, capture and availability are distinct; source publication times not inferred','fixed_evaluation_snapshot':str(FIXED.relative_to(ROOT))}
  c.execute('INSERT INTO source_manifests VALUES (?,?)',[source['name'],canonical(source)])
  c.execute('COMMIT')
 except Exception:c.execute('ROLLBACK');c.close();raise
 counts={name:c.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in views.current_view_catalog().values()}
 newtables=[name for name, in c.execute('select table_name from duckdb_tables() where not internal').fetchall() if name not in old_tables]
 tablecounts={name:c.execute('SELECT count(*) FROM "'+name+'"').fetchone()[0] for name in newtables}
 totalobjects=c.execute('select count(*) from information_schema.tables where table_schema=\'main\'').fetchone()[0]
 sourcecount=c.execute('select count(*) from source_manifests').fetchone()[0]
 c.close()
 report.update(current_view_counts=counts,new_table_counts=tablecounts,source_manifests_after=sourcecount,objects_after=totalobjects,staged_database_sha256=sha(stage),database_bytes_before=DB.stat().st_size,database_bytes_after=stage.stat().st_size)
 manifest=json.loads(MANIFEST.read_text());manifest['database_sha256']=report['staged_database_sha256'];manifest['current_views']=views.current_view_catalog();manifest['fixed_evaluation_snapshot']={'database':str((FIXED/DB.name).relative_to(ROOT)),'manifest':str((FIXED/MANIFEST.name).relative_to(ROOT)),'database_sha256':json.loads((FIXED/'attestation.json').read_text())['baseline_database_sha256']}
 manifest['table_and_view_counts'].update(counts|tablecounts|{'source_manifests':sourcecount})
 known={x['path']:x['sha256'] for x in manifest['input_files']}
 for path,h in registered_sources.items():
  if path in known and known[path]!=h:
   # Reusable code evolves; retain original source pins and register versioned
   # copies below, rather than silently changing a prior manifest entry.
   copy=run/'code'/Path(path).name;copy.parent.mkdir(exist_ok=True);copy.write_bytes((ROOT/path).read_bytes());path=str(copy.relative_to(ROOT));h=sha(copy)
  if path not in known:manifest['input_files'].append({'table':'refresh_'+prepared['run_id'],'path':path,'sha256':h,'rows':None});known[path]=h
 manifest['supplement_loads'].append({'name':'refresh_'+prepared['run_id'],'applied_at_utc':now(),'baseline_database_sha256':prepared['baseline_database_sha256'],'database_sha256_after':report['staged_database_sha256'],'report':str((run/'apply_report.json').relative_to(ROOT)),'fixed_evaluation_snapshot':str(FIXED.relative_to(ROOT)),'current_view_counts':counts,'new_event_rows':len(prepared['event_rows'])})
 save_json(run/'staged_manifest.json',manifest);save_json(run/'staging_report.json',report)
 return report

def validate_stage(c,p,old_tables,old_views):
 tables=dict(c.execute('select table_name,sql from duckdb_tables() where not internal').fetchall());v=dict(c.execute('select view_name,sql from duckdb_views() where not internal').fetchall())
 assert all(tables[n]==s for n,s in old_tables.items()),'baseline_table_schema_changed'
 assert all(v[n]==s for n,s in old_views.items() if not n.startswith('research_current_')),'baseline_view_changed'
 n=c.execute('select count(*) from refresh_event_records where run_id=?',[p['run_id']]).fetchone()[0];assert n==len(p['event_rows'])
 assert c.execute("select count(*) from refresh_event_records where meet not in ('1','3','4') or event_date is null or json_valid(payload_json)=false").fetchone()[0]==0
 assert c.execute("select count(*) from refresh_event_records where family='daily_training' and json_extract_string(fields_json,'$.rider_name') is not null and disposition='accepted'").fetchone()[0]==0,'inferred_daily_rider_names'
 assert c.execute("select count(*) from daily_training_rider_event_name_links where rider_id_raw='080626' and event_name='다비드'").fetchone()[0]==31
 assert c.execute('select count(*) from rider_identity_conflict_holds').fetchone()[0]==1
 assert c.execute('select count(*) from rider_unmatched_ids').fetchone()[0]==70
 # New records remain traceable even when entity or race linkage is unavailable.
 racekeys=set(c.execute("select meet,CAST(event_date AS VARCHAR),race_no from research_current_race_schedule").fetchall())
 issues=[]
 for rid,f,d,m,r,h in c.execute("select record_id,family,event_date::varchar,meet,race_no,horse_id from refresh_event_records where run_id=? and disposition='accepted'",[p['run_id']]).fetchall():
  if f in {'race_results','passing_groups','steward_reports','public_cards','entry_sheets','body_weights'} and r and (m,d,r) not in racekeys:issues.append([p['run_id'],rid,'race_schedule_not_linked'])
  if f in {'race_results','trial_results','daily_training','start_training','swim_training','medical','starting_exam'} and not h:issues.append([p['run_id'],rid,'official_horse_id_absent'])
 if issues:c.executemany('INSERT INTO refresh_link_review VALUES (?,?,?) ON CONFLICT DO NOTHING',issues)
 return {'original_table_schemas_preserved':True,'original_views_preserved':True,'new_record_count':n,'non_thoroughbred_rows':0,'rider_decisions_preserved':True,'link_review_rows':len(issues)}

def apply(run,prepared,dry_run=False):
 if prepared['status']=='already_applied':return prepared
 if sha(DB)!=prepared['baseline_database_sha256'] or sha(MANIFEST)!=prepared['baseline_manifest_sha256']:raise ValueError('core_changed_after_prepare')
 for path,h in prepared['sources'].items():
  resolved=(ROOT/path).resolve()
  if not resolved.is_relative_to(ROOT):raise ValueError('input_path_outside_repository')
  if sha(resolved)!=h:raise ValueError('input_changed_after_prepare')
 report=install_stage(run,prepared)
 if dry_run:return report|{'status':'dry_run_passed','active_database_written':False}
 # Recheck the active pair after staging so a competing writer cannot be replaced.
 if sha(DB)!=prepared['baseline_database_sha256'] or sha(MANIFEST)!=prepared['baseline_manifest_sha256']:raise ValueError('core_changed_while_staging')
 if prepared['baseline_database_sha256']==json.loads((FIXED/'attestation.json').read_text())['baseline_database_sha256']:backup=FIXED
 else:
  backup=CORE/'backups'/('refresh_'+prepared['run_id']);backup.mkdir(exist_ok=True)
  for src in (DB,MANIFEST):
   target=backup/src.name
   if not target.exists():subprocess.run(['/bin/cp','-c',str(src),str(target)],check=True)
   assert sha(target)==sha(src)
  save_json(backup/'attestation.json',{'status':'verified_equal','database_sha256':sha(DB),'manifest_sha256':sha(MANIFEST)})
 journal={'run_id':prepared['run_id'],'baseline_database_sha256':prepared['baseline_database_sha256'],'database_sha256_after':report['staged_database_sha256'],'manifest_sha256_after':sha(run/'staged_manifest.json'),'staged_database':str((run/'staged_core.duckdb').relative_to(ROOT)),'staged_manifest':str((run/'staged_manifest.json').relative_to(ROOT)),'backup':str(backup.relative_to(ROOT))}
 save_json(CORE/'refresh_apply_pending.json',journal)
 os.replace(run/'staged_core.duckdb',DB);os.replace(run/'staged_manifest.json',MANIFEST)
 assert sha(DB)==report['staged_database_sha256'] and json.loads(MANIFEST.read_text())['database_sha256']==sha(DB)
 (CORE/'refresh_apply_pending.json').unlink()
 report.update(status='applied_and_verified',active_database_written=True,backup=str(backup.relative_to(ROOT)),database_sha256_after=sha(DB),manifest_sha256_after=sha(MANIFEST))
 save_json(run/'apply_report.json',report)
 return report

def recover_pending():
 pending=CORE/'refresh_apply_pending.json'
 if not pending.exists():return
 j=json.loads(pending.read_text());stage=ROOT/j['staged_database'];stagem=ROOT/j['staged_manifest']
 for p in (stage,stagem):assert p.resolve().is_relative_to(ROOT/'thoroughbred')
 current=sha(DB)
 if current==j['baseline_database_sha256'] and stage.exists() and sha(stage)==j['database_sha256_after']:os.replace(stage,DB);current=j['database_sha256_after']
 if current!=j['database_sha256_after']:raise ValueError('pending_apply_requires_review')
 if stagem.exists() and sha(stagem)==j['manifest_sha256_after']:os.replace(stagem,MANIFEST)
 if sha(MANIFEST)!=j['manifest_sha256_after']:raise ValueError('pending_manifest_requires_review')
 pending.unlink()

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);modes=parser.add_mutually_exclusive_group(required=True);modes.add_argument('--prepare',action='store_true');modes.add_argument('--dry-run',action='store_true');modes.add_argument('--apply',action='store_true');args=parser.parse_args()
 assert args.run_id.replace('_','').replace('-','').isalnum()
 run=ROOT/'thoroughbred/refresh/runs'/args.run_id
 with domain_lock():
  recover_pending()
  if args.prepare:result=prepare(run)
  else:
   c=duckdb.connect(str(DB),read_only=True);already=exists(c,'refresh_runs') and bool(c.execute('select count(*) from refresh_runs where run_id=?',[args.run_id]).fetchone()[0]);c.close()
   result={'status':'already_applied','run_id':args.run_id} if already else apply(run,json.loads((run/'prepared.json').read_text()),dry_run=args.dry_run)
 print(canonical({k:v for k,v in result.items() if k not in {'sources','seed_rows','event_rows','partitions','missing_candidates'}}))
