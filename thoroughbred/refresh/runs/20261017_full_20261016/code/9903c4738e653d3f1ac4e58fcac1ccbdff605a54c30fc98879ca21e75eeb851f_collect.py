"""Collect official source bundles; database application is a separate phase."""
from __future__ import annotations
import argparse,json,sys
from collections import Counter
from pathlib import Path
from common import ROOT,Collector,save_json,canonical,sha,now
import races,auxiliary

def main():
 p=argparse.ArgumentParser();p.add_argument('--start',required=True);p.add_argument('--end',required=True);p.add_argument('--run-id',required=True);p.add_argument('--families',nargs='*');p.add_argument('--public-through');p.add_argument('--max-calls',type=int,default=1200);args=p.parse_args()
 if not args.run_id.replace('_','').replace('-','').isalnum():raise ValueError('invalid_run_id')
 run=ROOT/'thoroughbred/refresh/runs'/args.run_id;run.mkdir(parents=True,exist_ok=True)
 race_jobs=races.build_requests(args.start,args.public_through or args.end)
 jobs=[(r,races) for r in race_jobs]+[(r,auxiliary) for r in auxiliary.build_requests(args.start,args.end)]
 if args.families:jobs=[(r,m) for r,m in jobs if r['family'] in args.families]
 client=Collector(run,max_calls=args.max_calls);bundles=[];counts=Counter();plan_dates=set();plan_ok=True
 manifest={'run_id':args.run_id,'start':args.start,'end':args.end,'public_through':args.public_through or args.end,'started_at_utc':now(),'bundles':bundles,'status':'collecting','models_retrained':False}
 for request,module in jobs:
  family=request['family']
  if family in {'public_cards','entry_sheets','body_weights'} and str(request['params'].get('race_dt',request['params'].get('rc_date')))<=args.end.replace('-','') and plan_ok and plan_dates and (str(request['meet']),str(request['params'].get('race_dt',request['params'].get('rc_date')))) not in plan_dates:
   counts[family+'_nonplanned_day_requests_skipped']+=1;continue
  b=client.bundle(request);bundles.append(b);records=[];errors=[];outscope=0
  if not b['complete']:
   counts['failed_bundles']+=1
   if family=='race_schedule':plan_ok=False
  else:
   for item,ctx in client.rows(b):
    try:
     record=module.transform(family,item,ctx)
     if record is None:outscope+=1;continue
     day=record['event_date'];meet=str(record['meet'])
     if meet not in {'1','3','4'}:raise ValueError('non_thoroughbred_normalized_meet')
     family_end=args.public_through if family in {'race_schedule','public_cards','entry_sheets','body_weights'} and args.public_through else args.end
     if not family.endswith('_profile') and not (args.start<=day<=family_end):outscope+=1;continue
     request_day=ctx.get('requested_date')
     if family in {'public_cards','entry_sheets','body_weights','swim_training'} and request_day and day.replace('-','')!=str(request_day).replace('-',''):raise ValueError('returned_date_disagrees_with_daily_query')
     if family=='race_schedule':plan_dates.add((meet,day.replace('-','')))
     records.append({**record,'source_file':ctx['source_file'],'source_sha256':ctx['source_sha256'],'source_row_no':ctx['source_row_no'],'captured_at_utc':ctx['captured_at_utc']})
    except (ValueError,KeyError,TypeError) as exc:
     errors.append({'error':type(exc).__name__,'source_file':ctx['source_file'],'source_row_no':ctx['source_row_no'],'payload':item})
   b['normalization_errors']=len(errors);b['filtered_rows']=outscope;b['normalized_rows']=len(records);b['loadable']=not errors
   normalized=run/'normalized'/family/(Path(b['receipt_file']).parent.name+'.jsonl');normalized.parent.mkdir(parents=True,exist_ok=True)
   normalized.write_text(''.join(canonical(r)+'\n' for r in records),encoding='utf-8')
   b['normalized_file']=normalized.relative_to(ROOT).as_posix();b['normalized_sha256']=sha(normalized)
   if errors:save_json(normalized.with_suffix('.errors.json'),errors);counts['normalization_failed_bundles']+=1
   else:counts['successful_bundles']+=1;counts[family+'_rows']+=len(records)
  save_json(run/'collection.json',manifest)
  print(canonical({'family':family,'meet':b['meet'],'params':b['params'],'complete':b['complete'],'loadable':b.get('loadable',False),'rows':b.get('normalized_rows',0),'error':b.get('error'),'normalization_errors':b.get('normalization_errors',0),'calls':client.calls}),flush=True)
 client.close();manifest.update(status='collected',finished_at_utc=now(),counts=dict(counts),official_calls=client.calls)
 save_json(run/'collection.json',manifest)
 print(canonical({'status':'collected','counts':dict(counts),'calls':client.calls}),flush=True)
 return 0
if __name__=='__main__':sys.exit(main())
