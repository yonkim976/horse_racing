"""Reuse a verified stage plan with input hashes/profile fingerprint checked again.

This skips recomputing the already-audited aggregate planning pass. The reviewed
loader still rereads/checks every source page and every raw/typed row on apply
or replay. No network, feature changes, or core-table updates.
"""
from pathlib import Path
import argparse,importlib.util,json,sqlite3,sys
HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('reviewed_daily_loader',HERE/'daily_training_api_load.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def run():
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--expected-database-sha256');a=p.parse_args()
 if a.out.exists() or not a.out.parent.is_dir():raise ValueError('Report must be a new file in an existing directory')
 db=a.db.resolve(strict=True);before=m.sha256_file(db)
 if a.expected_database_sha256 and before!=a.expected_database_sha256:raise ValueError('Database changed since verified baseline')
 plan=json.loads(a.plan.read_text());assert plan['schema_version']==m.SCHEMA_VERSION and plan['dataset']=='daily_training' and plan['endpoint']=='/API18_1/dailyTraining_1'
 assert m.read_source_manifest_hashes()==plan['source_manifest_sha256']
 c=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True);profiles,fp=m.load_profiles(c);m.validate_existing_schema(c);c.close();assert fp==plan['profile_snapshot_sha256']
 audit=m.import_audit_reference();selected=next(pages for dataset,pages in audit.pages_for_sources() if dataset=='daily_training');assert len(selected)==len(plan['pages'])==337
 artifacts=[]
 for page,(base,partition,meta) in zip(plan['pages'],selected):
  source=m.resolve_jeju_child(base,meta['response_file'],'verified plan source')
  assert page['source_file_path']==m.safe_relative(source) and page['source_sha256']==meta['response_sha256'] and page['page_no']==meta['page_no']
  expected_key=(meta.get('public_params') or {}).get('tr_date',partition);assert page['source_partition_key']==expected_key and page['artifact_key']==f'daily_training:{expected_key}:page:{meta["page_no"]}'
  assert page['ledger_sha256']==plan['source_manifest_sha256']['daily_training_monthly_ledger'] and page['profile_snapshot_sha256']==fp
  artifacts.append(dict(page,_base=base,_meta=meta,_selector_partition=partition))
 result=m.apply_plan(db,artifacts,audit,profiles,plan)
 after=m.sha256_file(db)
 if result['database_write']=='no-op_exact_replay':assert after==before,'No-op replay changed DB bytes'
 report={**plan,**result,'database_path':str(db),'root_reused_verified_stage_plan':True,'verified_plan_path':str(a.plan.resolve()),'verified_plan_sha256':m.sha256_file(a.plan),'loader_sha256':m.sha256_file(HERE/'daily_training_api_load.py'),'database_sha256_before':before,'database_sha256_after':after,'input_manifest_hashes_rechecked':True,'profile_snapshot_rechecked':True,'source_pages_rechecked_during_apply':True,'summary':plan['source_summary']}
 m.write_report(a.out,report);print(json.dumps({**result,'database_sha256_before':before,'database_sha256_after':after,'report':str(a.out)},ensure_ascii=False,indent=2))
if __name__=='__main__':run()
