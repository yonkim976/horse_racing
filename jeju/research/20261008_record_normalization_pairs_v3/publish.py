"""Update only Jeju research summaries and inventory preserved artifacts."""
from pathlib import Path
import json
import hashlib
import re

H=Path(__file__).resolve().parent;ROOT=H.parents[2];C=H.parent/'conclusions'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
reg=json.loads((C/'research_register.json').read_text())
t=next(t for t in reg['topics'] if t['id']=='environment_correction')
t.update(latest_source='../'+H.name+'/README.md',status='time_normalization_study_completed_descriptive_candidates_only',
         current_selected_rates={'1000':{'moisture':0,'month':0},'1110':{'moisture':0,'month':0}},
         selected_rates_interpretation='prespecified_time_proxy_gate_fallback_not_proof_of_true_optimal_zero',
         new_normalization_validation_completed=True,nonzero_normalization_rate_adopted=False,
         descriptive_candidate_rates={'moisture':1,'month':1},period_start='2017-01-01',period_end='2026-09-19',
         pair_counts={'1000':9447,'1110':6415},counterfactual_accuracy_directly_observed=False)
write(C/'research_register.json',reg)
old=json.loads((C/'source_manifest.json').read_text())
for item in old['files']:
    if item['role'].startswith('source'):assert sha(ROOT/item['path'])==item['sha256'],item['path']
files={i['path']:i for i in old['files']}
for path,item in files.items():
    if item['role']=='conclusion_or_management':
        p=ROOT/path;item.update(sha256=sha(p),bytes=p.stat().st_size)
new_sources=['README.md','PLAN.json','analyze.py','verify_and_plot.py','latest_coefficients.csv','latest_joint_reference.csv',
             'joint_cell_support.csv','confirmation_comparisons.csv','decision.json','verification.json',
             'independent_calculation_verification.json','selection_locked_before_confirmation.json','source_manifest.json']
for name in new_sources:
    p=H/name;rel=str(p.relative_to(ROOT));files[rel]={'path':rel,'role':'source_time_normalization','sha256':sha(p),'bytes':p.stat().st_size}
links=0
for p in [H/'README.md',C/'02_ENVIRONMENT_CORRECTION.md',C/'README.md',C/'SOURCES.md']:
    for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
        if '://' not in target:
            assert (p.parent/target.split('#')[0]).exists(),(p,target)
            links+=1
old['files']=list(files.values());old['verification'].update(local_links_checked=links,
    prior_research_sources_unchanged=True,new_normalization_rates_not_selected=False,
    time_normalization_validation_completed=True,nonzero_time_normalization_rate_adopted=False)
old['managed_files_bytes_excluding_this_manifest']=sum(i['bytes'] for i in files.values() if i['role']=='conclusion_or_management')
write(C/'source_manifest.json',old)
all_files=[]
for p in sorted(H.iterdir()):
    if p.is_file() and p.name!='artifact_manifest.json':
        all_files.append({'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)})
write(H/'artifact_manifest.json',{'files':all_files,'total_bytes_excluding_this_manifest':sum(p['bytes'] for p in all_files),
      'prior_source_hashes_verified':True,'local_links_checked':links,'visual_plot_review':'passed_2026-10-08'})
print(json.dumps({'files':len(all_files),'study_bytes':sum(p['bytes'] for p in all_files),'links_checked':links},indent=2))
