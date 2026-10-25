"""Supported locked refresh entrypoint; daily 14-day replay and weekly 60-day audit."""
from __future__ import annotations
import argparse,json,subprocess,sys
from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from common import ROOT,domain_lock,save_json,now,sha
import store
STATE=ROOT/'thoroughbred/refresh/state.json'
def main():
 p=argparse.ArgumentParser();p.add_argument('--as-of');p.add_argument('--run-id');p.add_argument('--window',type=int,choices=[14,60]);p.add_argument('--public-through');p.add_argument('--reuse-capture',action='store_true');p.add_argument('--apply',action='store_true');p.add_argument('--dry-run',action='store_true');args=p.parse_args()
 if args.apply==args.dry_run:p.error('choose exactly one of --apply or --dry-run')
 today=datetime.now(ZoneInfo('Asia/Seoul')).date();end=date.fromisoformat(args.as_of) if args.as_of else today
 if end>today:p.error('confirmed history cannot have a future cutoff')
 state=json.loads(STATE.read_text()) if STATE.exists() else {}
 weekly_last=state.get('last_60_day_audit_date');weekly_due=weekly_last is None or (today-date.fromisoformat(weekly_last)).days>=7
 window=args.window or (60 if weekly_due else 14);start=end-timedelta(days=window-1)
 public_end=date.fromisoformat(args.public_through) if args.public_through else today+timedelta(days=7)
 rid=args.run_id or datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%dT%H%M%S')
 if not rid.replace('_','').replace('-','').isalnum():p.error('invalid run id')
 run=ROOT/'thoroughbred/refresh/runs'/rid;run.mkdir(parents=True,exist_ok=True)
 with domain_lock():
  store.recover_pending()
  c=store.duckdb.connect(str(store.DB),read_only=True);already=store.exists(c,'refresh_runs') and bool(c.execute('SELECT count(*) FROM refresh_runs WHERE run_id=?',[rid]).fetchone()[0]);c.close()
  if already:
   print(json.dumps({'status':'already_applied','run_id':rid,'database_written':False}));return 0
  if not args.reuse_capture:
   cmd=[sys.executable,str(Path(__file__).with_name('collect.py')),'--start',start.isoformat(),'--end',end.isoformat(),'--public-through',public_end.isoformat(),'--run-id',rid]
   with (run/'collection_console.log').open('w') as output:
    result=subprocess.run(cmd,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
   if result.returncode:raise RuntimeError('collection_process_failed; inspect domain run log')
  p=store.prepare(run);report=store.apply(run,p,dry_run=args.dry_run)
  collection=json.loads((run/'collection.json').read_text())
  failures=sum(1 for b in collection['bundles'] if not b.get('complete') or not b.get('loadable'))
  if args.apply:
   state.update(last_run_id=rid,last_success_at_utc=now(),last_history_cutoff=end.isoformat(),current_views_manifest=str(store.MANIFEST.relative_to(ROOT)))
   if window==60 and not failures:state['last_60_day_audit_date']=today.isoformat()
   save_json(STATE,state)
  report.update(failed_bundles=failures,window_days=window,history_cutoff=end.isoformat(),public_through=public_end.isoformat())
  save_json(run/'run_report.json',report)
  summary={k:v for k,v in report.items() if k in {'status','run_id','stats','database_sha256_after','failed_bundles','window_days','history_cutoff','public_through'}}
  print(json.dumps(summary,ensure_ascii=False,indent=2))
  return 2 if failures else 0
if __name__=='__main__':sys.exit(main())
