"""Validate report arithmetic, then inventory study and update Jeju summaries only."""
from pathlib import Path
import json
import re
import hashlib
import numpy as np
import pandas as pd

H=Path(__file__).resolve().parent;ROOT=H.parents[2];C=H.parent/'conclusions'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
num=pd.read_csv(H/'number_seconds.csv');lat=pd.read_csv(H/'lateral_seconds.csv');trial=pd.read_csv(H/'illustrative_half_group_table.csv')
assert np.allclose(trial.trial_adjustment_s,trial.adjustment_s*.5)
assert np.allclose(trial.trial_lo,trial.adjustment_lo*.5) and np.allclose(trial.trial_hi,trial.adjustment_hi*.5)
for _,g in trial.groupby('distance'):
    assert abs(sum(g.set_index('contrast').trial_adjustment_s*pd.Series({'inner':3,'middle':4,'outer':3})))<1e-10
text=(H/'README.md').read_text();section=text.split('| 번호 | 800m |')[1].split('단위는 초다.')[0]
rows=[line for line in section.splitlines() if re.match(r'\| \d+ \|',line)]
assert len(rows)==10
for line in rows:
    cells=[c.strip() for c in line.strip('|').split('|')];k=int(cells[0])
    for distance,value in zip([800,900,1000,1110,1200],cells[1:]):
        actual=num[(num.period=='full')&(num.variant=='primary')&(num.distance==distance)&(num.number==k)].adjustment_s.iloc[0]
        assert abs(float(value.replace('−','-'))-actual)<=.00501,(k,distance,value,actual)
rate=pd.read_csv(H/'frozen_rate_checks.csv');section=text.split('| 거리 | 무보정 번호 편차 RMS |')[1].split('800m의50%')[0]
rows=[line for line in section.splitlines() if re.match(r'\| \d+m \|',line)]
for line in rows:
    cells=[c.strip() for c in line.strip('|').split('|')];distance=int(cells[0][:-1]);g=rate[(rate.distance==distance)&(rate.period=='confirmation')].set_index('rate')
    expected=[g.loc[0,'baseline_gate_bias_RMS_s'],g.loc[.5,'corrected_gate_bias_RMS_s'],g.loc[1,'corrected_gate_bias_RMS_s']]
    for value,actual in zip(cells[1:],expected):assert abs(float(value.replace('초',''))-actual)<=.00051
assert not num[(num.period=='full')&(num.variant=='primary')].q_BH.lt(.05).any()
old=json.loads((C/'source_manifest.json').read_text());before={i['path']:i['sha256'] for i in old['files'] if i['role']=='conclusion_or_management'}
for item in old['files']:
    if item['role'].startswith('source'):assert sha(ROOT/item['path'])==item['sha256'],item['path']
prior=H.parent/'20261008_gate_2017_2026_v1'
prior_manifest=json.loads((prior/'artifact_manifest.json').read_text())
for item in prior_manifest if isinstance(prior_manifest,list) else prior_manifest['files']:assert sha(prior/item['path'])==item['sha256']
reg=json.loads((C/'research_register.json').read_text());topic=next(t for t in reg['topics'] if t['id']=='gate_lateral')
topic.update(latest_source='../'+H.name+'/README.md',previous_top3_source='../20261008_gate_2017_2026_v1/report.html',
    status='record_seconds_study_completed_trial_group_proposal_no_adoption',correction_adopted=False,operationally_applied=False,
    record_normalization={'reference':'uniform_mean_of10gates_zero_per_distance','corroborated_individual_gate_cells':0,
    'trial_example':{'distance_m':800,'field_n':10,'groups':{'1_3':.10,'4_7':0.,'8_10':-.10},'rate':.5,'status':'illustrative_policy_not_optimal_or_adopted'},
    'latest_2026_800m_ten_runner_races':3,'group_compression_diagnostic':'post_primary_exploratory','selected_optimal_rate':None})
write(C/'research_register.json',reg)
write(H/'decision.json',{'objective':'gate_record_normalization_seconds','Top3_used':False,'future_finish_time_forecast_test':False,
    'counterfactual_truth_observed':False,'corroborated_individual_gate_cells':0,'fixed_rate_selected':None,'fixed_correction_adopted':False,'operational_change':False,
    'strongest_group_association':{'distance_m':800,'inner_minus_outer_full_s':float(lat[(lat.period=='full')&(lat.variant=='primary')&(lat.distance==800)&(lat.contrast=='inner_minus_outer')].effect_s.iloc[0]),
    'confirmation_s':float(lat[(lat.period=='confirmation')&(lat.variant=='primary')&(lat.distance==800)&(lat.contrast=='inner_minus_outer')].effect_s.iloc[0])},
    'illustrative_trial_table':{'distance_m':800,'field_n':10,'inner_1to3_adjustment_s':.1,'middle_4to7_adjustment_s':0.,'outer_8to10_adjustment_s':-.1,'interpretation':'rounded_half_latest_full_group_effect_not_optimal_rate'},
    'group_confirmation_status':'exploratory_after_primary_results; past-only unrounded coefficients evaluated, latest rounded table not directly validated',
    'other_distances_status':'fixed_additional_correction_withheld; sparse1300/1400,1610not_estimated'})
files={i['path']:i for i in old['files']}
for path,item in files.items():
    if item['role']=='conclusion_or_management':
        p=ROOT/path;item.update(sha256=sha(p),bytes=p.stat().st_size)
for name in ['README.md','PLAN.json','GROUP_DIAGNOSTIC.json','analyze.py','verify_plot.py','group_diagnostic.py','source_manifest.json',
             'number_seconds.csv','lateral_seconds.csv','support.csv','frozen_rate_checks.csv','exploratory_group_rate_checks.csv','illustrative_half_group_table.csv',
             'candidate_status.csv','verification.json','calculation_verification.json','decision.json']:
    p=H/name;rel=str(p.relative_to(ROOT));files[rel]={'path':rel,'role':'source_gate_seconds_normalization','sha256':sha(p),'bytes':p.stat().st_size}
links=0
for p in [H/'README.md',C/'01_GATE_LATERAL.md',C/'README.md',C/'SOURCES.md']:
    for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
        if '://' not in target:
            assert (p.parent/target.split('#')[0]).exists(),(p,target)
            links+=1
old['files']=list(files.values());old['verification'].update(local_links_checked=links,prior_research_sources_unchanged=True,
    gate_record_seconds_completed=True,gate_trial_table_is_not_adopted=True)
old['managed_files_bytes_excluding_this_manifest']=sum(i['bytes'] for i in files.values() if i['role']=='conclusion_or_management');write(C/'source_manifest.json',old)
write(H/'publication_verification.json',{'status':'passed','local_links_checked':links,'report_gate_and_RMS_tables_checked':True,
    'trial_group_scaling_mean_zero_checked':True,'previous_gate_artifacts_unchanged':True,'visual_plot_review':'passed',
    'management_previous_hashes':before,'management_current_hashes':{k:sha(ROOT/k) for k in before}})
art=[]
for p in sorted(H.iterdir()):
    if p.is_file() and p.name!='artifact_manifest.json':art.append({'path':p.name,'sha256':sha(p),'bytes':p.stat().st_size})
write(H/'artifact_manifest.json',{'files':art,'total_bytes_excluding_this_manifest':sum(i['bytes'] for i in art),'local_links_checked':links,'previous_sources_unchanged':True})
print(json.dumps({'files':len(art),'bytes':sum(i['bytes'] for i in art),'links':links},indent=2))
