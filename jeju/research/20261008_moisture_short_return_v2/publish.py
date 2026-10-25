"""Publish research inventory and Jeju summaries without modifying previous studies."""
from pathlib import Path
import hashlib
import json
import re

H=Path(__file__).resolve().parent;ROOT=H.parents[2];C=H.parent/'conclusions'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
old=json.loads((C/'source_manifest.json').read_text());before={i['path']:i['sha256'] for i in old['files'] if i['role']=='conclusion_or_management'}
for item in old['files']:
    if item['role'].startswith('source'):assert sha(ROOT/item['path'])==item['sha256'],item['path']
prior=H.parent/'20261008_record_normalization_pairs_v3'
for item in json.loads((prior/'artifact_manifest.json').read_text())['files']:
    assert sha(prior/item['path'])==item['sha256']
reg=json.loads((C/'research_register.json').read_text());t=next(t for t in reg['topics'] if t['id']=='environment_correction')
t['prior_joint_source']='../20261008_record_normalization_pairs_v3/README.md'
t.update(latest_source='../'+H.name+'/README.md',status='short_interval_and_return_corroboration_completed_no_fixed_rate_adopted',
         pair_counts_source='../20261008_record_normalization_pairs_v3/README.md',
         latest_followup={'changed_same_month_pairs':{'1000':1892,'1110':1327},'changed_return_triples':{'1000':588,'1110':420},
                          'selected_rate':None,'fixed_rate_selection_performed':False,'month_coefficients_reestimated':False,
                          'finding':'1000_saturated_candidate_not_stable_across_designs_1110_direction_suggestive_but_magnitude_and_period_unstable'})
write(C/'research_register.json',reg)
write(H/'decision.json',{'objective':'moisture_reference_time_normalization_corroboration','top3_used':False,'future_race_time_forecast_test':False,
    'counterfactual_truth_observed':False,'new_rate_selected':None,'nonzero_rate_adopted':False,'operational_change':False,
    'month_coefficients_reestimated':False,'findings':{'1000':'saturated_candidate_not_consistent_across_short_pair_and_return_design',
    '1110':'saturated_faster_direction_suggestive_fullperiod_but_interval_period_and_stable_grade_weight_sensitivity_insufficient'},
    'previous_joint_reference':'../20261008_record_normalization_pairs_v3/README.md','previous_candidates_status':'descriptive_only_not_validated_fixed_display_adjustment'})
files={i['path']:i for i in old['files']}
for path,item in files.items():
    if item['role']=='conclusion_or_management':
        p=ROOT/path;item.update(sha256=sha(p),bytes=p.stat().st_size)
for name in ['README.md','PLAN.json','analyze.py','verify_summarize.py','source_manifest.json','effects.csv','sensitivities.csv',
             'held_checks.csv','held_metric_intervals.csv','dry_saturated_direct_support.csv','decision.json','verification.json','calculation_verification.json']:
    p=H/name;rel=str(p.relative_to(ROOT));files[rel]={'path':rel,'role':'source_moisture_corroboration','sha256':sha(p),'bytes':p.stat().st_size}
links=0
for p in [H/'README.md',C/'02_ENVIRONMENT_CORRECTION.md',C/'README.md',C/'SOURCES.md']:
    for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
        if '://' not in target:
            assert (p.parent/target.split('#')[0]).exists(),(p,target)
            links+=1
old['files']=list(files.values());old['verification'].update(local_links_checked=links,prior_research_sources_unchanged=True,
    moisture_short_return_followup_completed=True,nonzero_time_normalization_rate_adopted=False)
old['managed_files_bytes_excluding_this_manifest']=sum(i['bytes'] for i in files.values() if i['role']=='conclusion_or_management')
write(C/'source_manifest.json',old)
write(H/'publication_receipt.json',{'management_previous_hashes':before,'management_current_hashes':{k:sha(ROOT/k) for k in before},
      'previous_joint_study_artifacts_unchanged':True,'local_links_checked':links,'visual_plot_review':'passed','files_changed_scope':'Jeju new research and topic summaries only'})
art=[]
for p in sorted(H.iterdir()):
    if p.is_file() and p.name!='artifact_manifest.json':art.append({'path':p.name,'sha256':sha(p),'bytes':p.stat().st_size})
write(H/'artifact_manifest.json',{'files':art,'total_bytes_excluding_this_manifest':sum(p['bytes'] for p in art),
      'source_and_previous_studies_unchanged':True,'local_links_checked':links})
print(json.dumps({'files':len(art),'bytes':sum(p['bytes'] for p in art),'links':links},indent=2))
