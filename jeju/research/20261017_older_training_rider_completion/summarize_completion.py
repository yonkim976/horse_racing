"""Summarize the frozen comparison and actual applied local SQLite state."""
from pathlib import Path
from collections import Counter,defaultdict
import importlib.util,json
HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('loader',HERE/'apply_older_types.py');l=importlib.util.module_from_spec(s);s.loader.exec_module(l)
run=HERE/'collection/official_daily_all';manifest=json.loads((run/'run_manifest.json').read_text())
l.require(manifest['state'] in ('frozen_complete','frozen_with_failures'),'Collection not frozen')
receipt=json.loads((HERE/'full.application_manifest.json').read_text());native=json.loads((HERE/'verification/full_preservation.json').read_text())
l.require(native['passed'] and native['database_sha256']==receipt['database_sha256_after']==l.sha(l.DB),'Final DB verification mismatch')
post=json.loads((HERE/'verification/full_postapply_verification.json').read_text())
l.require(post['passed'] and post['plan_sha256']==receipt['plan_sha256'] and post['database_sha256']==native['database_sha256'],'Independent postapply gate mismatch')
reasons=Counter();labels=Counter();byyear=defaultdict(Counter);unresolved=0;total=0
for r in l.records(run/'outcomes.jsonl'):
 total+=1;reasons[r['status']]+=1
 if r['status']!='classifiable_exact_match':
  unresolved+=1;byyear[r['date'][:4]][r['status']]+=1
  if r.get('label') is not None: labels[r['label']]+=1
l.require(total==280351 and unresolved==native['remaining_older_unknown'],'Outcome remainder mismatch')
c=l.connect();dbbyyear=[dict(r) for r in c.execute("SELECT substr(training_date,1,4) year,count(*) rows FROM daily_training_rider_type_assignments WHERE rider_type='미분류' AND training_date<'2026-04-17' GROUP BY 1 ORDER BY 1")];c.close()
initial=json.loads((HERE/'initial609.application_manifest.json').read_text())
result={'status':'complete','target_older_unknown_before':280960,'initial_confirmed_applied':initial['updated_rows'],
 'full_comparison_target':total,'full_additional_applied':receipt['updated_rows'],
 'total_applied_this_task':initial['updated_rows']+receipt['updated_rows'],
 'official_dates_attempted':manifest['receipt_date_count'],'official_dates_successful':manifest['dates_successful'],
 'official_dates_failed':manifest['dates_failed'],'full_additional_type_counts':manifest['candidate_type_counts'],
 'full_outcome_counts':dict(reasons),'remaining_older_unknown':unresolved,'remaining_recent_unknown':native['remaining_recent_unknown'],
 'remaining_total_unknown':native['type_counts']['미분류'],'remaining_older_unknown_labels':dict(labels),
 'remaining_older_unknown_by_year':dbbyyear,'remaining_older_reasons_by_year':{k:dict(v) for k,v in sorted(byyear.items())},
 'final_type_counts':native['type_counts'],'daily_training_rows':912913,'database_sha256':native['database_sha256'],
 'preservation_verified_tables':native['tables_checked'],'preservation_verified_rows':native['rows_checked'],
 'source_rows_unchanged':True,'schema_unchanged':True,'integrity_check':'ok','foreign_key_violations':0}
l.write(HERE/'completion_summary.json',result);print(json.dumps(result,ensure_ascii=False))
