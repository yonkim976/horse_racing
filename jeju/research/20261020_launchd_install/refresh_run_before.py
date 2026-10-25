"""Bounded manual/scheduled refresh of the Jeju research SQLite core."""
from __future__ import annotations
import argparse,fcntl,hashlib,json,os,sqlite3,sys,uuid,shutil
from pathlib import Path
from datetime import datetime,UTC,timedelta
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from jeju.refresh.core import apply_core,add_website_evidence,schema,CANON
from jeju.refresh.auxiliary import apply_auxiliary
from jeju.refresh.current_views import apply_current_views
from jeju.refresh.website_load import apply_website
DB=ROOT/'jeju/data/jeju_native_core.sqlite3'
HOME=ROOT/'jeju/research/20261017_core_refresh'
DATE_FIELDS={'race_result_rows':'race_date','running_trial_rows':'trial_date','api303_corner_rank_rows':'race_date','daily_training_api_rows':'training_date','website_training_artifacts':'training_date','medical_api_rows':'clinic_date','starting_exam_api_rows':'exam_date','horse_profile_observations':'observed_kst_date','refresh_section_records':'race_date','refresh_starting_training_api':'training_date'}
CURRENT={'daily_training_api_rows_current':'training_date','daily_training_riders_current':'training_date','medical_api_rows_current':'clinic_date','starting_exam_api_rows_current':'exam_date','starting_training_website_rows_current':'training_date','horse_profile_refresh_current':'observed_kst_date','race_current':'race_date','trial_current':'trial_date','training_current':'training_date','starting_training_current':'training_date','medical_current':'clinic_date','exam_current':'exam_date','sections_current':'race_date','starting_training_api_current':'training_date','api6_section_records_current':'race_date'}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4194304),b''):h.update(b)
 return h.hexdigest()
def write(p,v):
 tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n');os.replace(tmp,p)
def snapshot(c,dates=DATE_FIELDS):
 names={r[0] for r in c.execute("select name from sqlite_master where type in ('table','view')")}
 return {name:dict(zip(('rows','first','latest'),c.execute('select count(*),min('+field+'),max('+field+') from '+name).fetchone())) for name,field in dates.items() if name in names}
def connect(p,readonly=False):
 c=sqlite3.connect(p.as_uri()+('?mode=ro' if readonly else ''),uri=True,timeout=10)
 c.execute('pragma foreign_keys=ON');c.execute('pragma busy_timeout=10000');c.execute('pragma cache_size=-65536');return c
def backup_pair(db,out):
 out.mkdir(parents=True,exist_ok=True);target=out/'jeju_native_core.sqlite3'
 if not target.exists():
  s=connect(db,True);d=sqlite3.connect(target);s.backup(d,pages=4096);d.close();s.close()
 old=ROOT/'jeju/data/jeju_native_core.build_manifest.json'
 if old.exists() and not (out/old.name).exists():shutil.copyfile(old,out/old.name)
 current=ROOT/'jeju/data/jeju_native_core.refresh_manifest.json'
 if current.exists() and not (out/current.name).exists():shutil.copyfile(current,out/current.name)
 meta={'db_sha256':sha(target),'source_database_sha256':sha(db),'prior_refresh_manifest_sha256':sha(out/current.name) if (out/current.name).exists() else None,'bytes':target.stat().st_size,'build_manifest_sha256':sha(out/old.name) if (out/old.name).exists() else None,'captured_at_utc':datetime.now(UTC).isoformat(),'managed_by':'jeju_research_refresh_v1'}
 write(out/'pair_manifest.json',meta);return meta

def apply(c,pages,run_id,start,end,manifest,website_manifest=None):
 schema(c)
 if c.execute('select 1 from research_refresh_runs where run_id=?',(run_id,)).fetchone():return {'already_applied':True}
 c.execute('insert into research_refresh_runs values(?,?,?,?,?,?,?)',(run_id,datetime.now(UTC).isoformat(),None,start,end,str(manifest.relative_to(ROOT)),'applying'))
 views=apply_current_views(c)
 core=apply_core(c,pages,ROOT,run_id,start,end)
 auxiliary=apply_auxiliary(c,[p for p in pages if p['family'] in ('daily_training','medical','starting_exam')],ROOT,run_id)
 website=apply_website(c,website_manifest,ROOT,run_id)
 views+=apply_current_views(c);web=add_website_evidence(c,ROOT)
 c.execute('update research_refresh_runs set completed_at_utc=?,status=? where run_id=?',(datetime.now(UTC).isoformat(),'applied',run_id))
 return {'core':core,'auxiliary':auxiliary,'views_created':views,'website_evidence_added':web,'starting_training_website':website}

def check(c,baseline_views):
 fk=c.execute('pragma foreign_key_check').fetchall();assert not fk, fk[:3]
 integrity=c.execute('pragma integrity_check').fetchone()[0];assert integrity=='ok',integrity
 actual=dict(c.execute("select name,sql from sqlite_master where type='view'"))
 assert all(actual.get(k)==v for k,v in baseline_views.items()),'Existing view definition changed'
 for table in ('race_result_rows','running_trial_rows','daily_training_api_rows','medical_api_rows','starting_exam_api_rows','horse_profile_observations'):
  assert c.execute('select count(*) from '+table+' where horse_id=?',('3005648',)).fetchone()[0]==0,'Excluded horse reintroduced'
  return {'foreign_key_errors':0,'integrity_check':integrity,'existing_view_definitions_preserved':True,'excluded_horse_absent':True,'current_views':snapshot(c,CURRENT)}

def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--apply',action='store_true');a.add_argument('--manifest',type=Path);a.add_argument('--website-manifest',type=Path);a.add_argument('--initial',action='store_true');a.add_argument('--start');a.add_argument('--end');a.add_argument('--weekly',action='store_true');a.add_argument('--output',type=Path);args=a.parse_args()
 HOME.mkdir(exist_ok=True,parents=True)
 with (HOME/'refresh.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print('{"status":"already_running"}');return
  now=datetime.now(ZoneInfo('Asia/Seoul'));end=args.end or (now.date() if now.hour>=21 else now.date()-timedelta(days=1)).isoformat()
  weekly=args.weekly or now.weekday()==6
  start=args.start or ('2026-09-13' if args.initial else (datetime.fromisoformat(end).date()-timedelta(days=59 if weekly else 13)).isoformat())
  assert start<=end<=now.date().isoformat()
  run_id=now.strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8];out=(args.output or HOME/'runs'/run_id).resolve();out.relative_to(HOME.resolve());out.mkdir(parents=True,exist_ok=False)
  try:
   if args.manifest:
    manifest=args.manifest.resolve();manifest.relative_to((ROOT/'jeju').resolve());doc=json.loads(manifest.read_text());pages=doc['pages']
   else:
    if not args.apply:write(out/'plan.json',{'start':start,'end':end,'weekly':weekly,'db':str(DB),'network_called':False});print(CANON({'status':'plan_only','output':str(out)}));return
    from jeju.refresh.collect import collect_range
    pages=collect_range(out/'collection',start,end,reuse_snapshot=False);manifest=out/'collection/source_manifest.json';doc=json.loads(manifest.read_text())
   usable=[p for p in pages if p.get('path') and p.get('sha256') and p.get('pagination_complete',True) and p.get('http_status',200)==200]
   for p in usable:p.update(start_date=start,end_date=end,source_manifest_path=str(manifest.relative_to(ROOT)),source_manifest_sha256=sha(manifest))
   assert usable,'No complete validated source partition available'
   write(out/'source_selection.json',{'manifest':str(manifest.relative_to(ROOT)),'manifest_sha256':sha(manifest),'requested_start':start,'requested_end':end,'usable_pages':len(usable),'not_applied_pages':len(pages)-len(usable)})
   if not args.apply:print(CANON({'status':'validated_plan','pages':len(usable),'output':str(out)}));return
   from jeju.refresh.website import collect_starting_training_website
   website_manifest=args.website_manifest.resolve() if args.website_manifest else collect_starting_training_website(out/'website',start.replace('-',''),end.replace('-',''))
   website_manifest.relative_to((ROOT/'jeju').resolve())
   before_sha=sha(DB);c=connect(DB,True);before=snapshot(c);before_views=dict(c.execute("select name,sql from sqlite_master where type='view'"));c.close()
   baseline=HOME/'baseline' if args.initial else HOME/'rolling_backups'/run_id
   pair=backup_pair(DB,baseline)
   stage=out/'staging.sqlite3';s=connect(DB,True);t=sqlite3.connect(stage);s.backup(t,pages=4096);t.close();s.close()
   st=connect(stage);st.execute('BEGIN IMMEDIATE');summary=apply(st,usable,run_id,start,end,manifest,website_manifest);stage_checks=check(st,before_views);st.commit()
   stage_counts=snapshot(st);st.execute('BEGIN');replay=apply(st,usable,run_id,start,end,manifest,website_manifest);assert replay=={'already_applied':True};st.rollback();st.close()
   assert sha(DB)==before_sha,'Production DB changed since baseline'
   prod=connect(DB);prod.execute('BEGIN IMMEDIATE')
   try:
    actual=apply(prod,usable,run_id,start,end,manifest,website_manifest);assert actual==summary,(actual,summary)
    checks=check(prod,before_views);assert snapshot(prod)==stage_counts;prod.commit()
   except Exception:prod.rollback();raise
   after=snapshot(prod);prod.close()
   result={'run_id':run_id,'status':'applied_verified','start':start,'end':end,'weekly_60_day_audit':weekly,'source_manifest':str(manifest.relative_to(ROOT)),'source_manifest_sha256':sha(manifest),'source_family_coverage':doc.get('family_coverage',{}),'before':before,'after':after,'summary':summary,'checks':checks,'staging_checks':stage_checks,'idempotent_replay':True,'backup_pair':pair,'database_bytes_before':pair['bytes'],'database_bytes_after':DB.stat().st_size,'database_sha256_after':sha(DB),'fixed_evaluation_snapshot':str((HOME/'baseline').relative_to(ROOT)),'source_failures':doc.get('unavailable_cache_or_failures',[]),'website_manifest':str(website_manifest.relative_to(ROOT)),'starting_training_website_status':json.loads(website_manifest.read_text())['collection_status']}
   write(out/'application_manifest.json',result)
   # Sidecar points to the immutable application receipt; original build manifest preserved.
   write(ROOT/'jeju/data/jeju_native_core.refresh_manifest.json',{'latest_run_id':run_id,'application_manifest':str((out/'application_manifest.json').relative_to(ROOT)),'sha256':sha(out/'application_manifest.json'),'database_sha256':result['database_sha256_after']})
   files=[p for p in out.rglob('*') if p.is_file()];write(out/'artifact_inventory.json',{'file_count_before_inventory':len(files),'bytes_before_inventory':sum(p.stat().st_size for p in files),'raw_file_count':sum(p.suffix=='.json' and '/raw/' in str(p) for p in files),'staging_bytes':stage.stat().st_size,'staging_sha256':sha(stage),'backup_bytes':pair['bytes']})
   stage.unlink() # temporary test DB only; durable before-image and receipts are retained
   if not args.initial:
    write(baseline/'successful_run.json',{'run_id':run_id,'receipt':str((out/'application_manifest.json').relative_to(ROOT))})
    owned=[]
    for candidate in (HOME/'rolling_backups').iterdir():
     marker=candidate/'pair_manifest.json'
     if marker.is_file() and (candidate/'successful_run.json').is_file() and json.loads(marker.read_text()).get('managed_by')=='jeju_research_refresh_v1':owned.append(candidate)
    for old in sorted(owned,reverse=True)[2:]:
     allowed={'jeju_native_core.sqlite3','jeju_native_core.build_manifest.json','jeju_native_core.refresh_manifest.json','pair_manifest.json','successful_run.json'}
     if {p.name for p in old.iterdir()}<=allowed:shutil.rmtree(old) # task-owned rolling backups only; frozen baseline never pruned
   write(HOME/'latest_run.json',{'run_id':run_id,'manifest':str((out/'application_manifest.json').relative_to(ROOT)),'status':result['status']})
   print(CANON({'status':result['status'],'manifest':str(out/'application_manifest.json'),'before':before,'after':after,'inserted':{f:v.get('inserted',0) for f,v in summary['core'].items()},'auxiliary':summary['auxiliary']['by_family'],'website':summary['starting_training_website'],'current':checks['current_views']}))
  except Exception as exc:
   write(out/'failure.json',{'status':'failed','error_type':type(exc).__name__,'error_message':str(exc)[:500] if not any(x in str(exc).lower() for x in ('servicekey','token','password')) else 'redacted','run_id':run_id,'at_utc':datetime.now(UTC).isoformat()})
   print(CANON({'status':'failed','error_type':type(exc).__name__,'failure_manifest':str(out/'failure.json')}));raise
if __name__=='__main__':main()
