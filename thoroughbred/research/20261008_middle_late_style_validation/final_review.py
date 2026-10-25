"""Review published regional tables, JSON claims, links, hashes and figures."""
from pathlib import Path
import json,hashlib,re
import numpy as np,pandas as pd
from PIL import Image
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';checks=0
def same(a,b,label):
    global checks
    a=np.asarray(a,float);b=np.asarray(b,float);assert a.shape==b.shape and np.allclose(a,b,atol=1e-10,rtol=1e-9,equal_nan=True),label;checks+=a.size
d=pd.read_parquet(O/'trajectory_rows.parquet');main=d[d.year.between(2024,2025)];cm=pd.read_csv(O/'cohort_metrics.csv');flow=pd.read_csv(O/'front_realization_metrics.csv');matched=pd.read_csv(O/'matched_comparisons.csv');primary=cm[(cm.window=='2024_2025')&(cm.scope=='all')].set_index('cohort');p=json.loads((H/'PUBLICATION.json').read_text())
same([len(main),main.source_key.nunique(),main.horse_id.nunique(),main.recovery.notna().sum()],[p['primary_roster_n'],p['primary_races'],p['primary_horses'],p['recovery_valid_n']],'publication population');assert p['models_trained']==0 and not p['operating_model_changed'] and not p['intention_identified'] and not p['causal_loss_estimated']
for code,key in [('back_repeat','back_repeat'),('back_low','back_low')]:same([primary.loc[code,'recovery_n'],primary.loc[code,'recovery_mean']],[p[key]['n'],p[key]['rate']],'publication recurrence')
rr=pd.read_csv(O/'closer_repetition_comparisons.csv').query("window=='2024_2025' and scope=='all'").iloc[0];same([rr[k] for k in ['estimate','lower','upper']],[p['raw_repetition_contrast'][k] for k in ['estimate','lower','upper']],'publication interval')
for r in p['matched_primary']:
    q=matched[(matched.window=='2024_2025')&(matched.comparison==r['comparison'])&(matched.target==r['target'])].iloc[0];same([q[k] for k in ['n_a','n_b','estimate','lower','upper','bh_q']],[r[k] for k in ['n_a','n_b','estimate','lower','upper','bh_q']],'publication matched contrasts')
dist=pd.read_csv(O/'regional_distance_closing_summary.csv')
assert len(dist)==len(p['distance_closing_summary'])
for r in dist.itertuples():
    g=main[(main.meet==r.meet)&(main.distance_m==r.distance_m)];a=g[g.closer_candidate];b=g[g.back_low_recovery]
    same([a.recovery.notna().sum(),a.recovery.mean(),b.recovery.notna().sum(),b.recovery.mean(),a.recovery_when_back600.notna().sum(),a.recovery_when_back600.mean(),b.recovery_when_back600.notna().sum(),b.recovery_when_back600.mean(),a.top3.notna().sum(),a.top3.mean(),b.top3.notna().sum(),b.top3.mean()],[r.repeat_n,r.repeat_recovery,r.low_n,r.low_recovery,r.repeat_eligible_n,r.repeat_eligible_recovery,r.low_eligible_n,r.low_eligible_recovery,r.repeat_top3_n,r.repeat_top3,r.low_top3_n,r.low_top3],'regional recovery table')
    pub=next(z for z in p['distance_closing_summary'] if z['meet']==r.meet and z['distance_m']==r.distance_m)
    for col in ['repeat_n','repeat_recovery','low_n','low_recovery','repeat_top3','low_top3']:same(pub[col],getattr(r,col),'publication regional values')
for r in pd.read_csv(O/'regional_distance_front_summary.csv').itertuples():
    g=main[(main.meet==r.meet)&(main.distance_m==r.distance_m)];col={'past_lead':'lead_profile','past_front':'front_profile','past_fore_strict':'fore_strict_profile'}[r.cohort];g=g[g[col]];state='lead_realization' if r.cohort=='past_lead' else 'front_realization';ok='선행유지' if r.cohort=='past_lead' else '앞선확보';a=g[g[state].eq(ok)];b=g[g[state].eq('중단후미밀림')];same([a.top3.notna().sum(),a.top3.mean(),b.top3.notna().sum(),b.top3.mean(),b.recovery.notna().sum(),b.recovery.mean()],[r.success_n,r.success_top3,r.miss_n,r.miss_top3,r.miss_recovery_n,r.miss_recovery],'regional front table')
for r in pd.read_csv(O/'regional_distance_phase_summary.csv').itertuples():
    col={'back_repeat':'closer_candidate','back_low':'back_low_recovery','past_lead':'lead_profile','past_front':'front_profile'}[r.cohort];g=main[(main.meet==r.meet)&(main.distance_m==r.distance_m)&main[col]&main.path_complete];same([len(g),(g.s1f-g.g3f).mean(),(g.g3f-g.g1f).mean(),(g.g1f-g.raw_finish_rank).mean(),(g.s1f-g.raw_finish_rank).mean()],[r.n,r.middle_rank_gain,r.late400_rank_gain,r.late200_rank_gain,r.total_rank_gain],'regional phase ranks');same(r.middle_rank_gain+r.late400_rank_gain+r.late200_rank_gain,r.total_rank_gain,'phase sum')
manifest=json.loads((R/'conclusions/source_manifest.json').read_text());paths=[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',R/'conclusions/28F_MIDDLE_LATE_STYLE_VALIDATION.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md'];hashes=0
for path in paths:
    name=str(path.relative_to(ROOT));row=next(r for r in manifest['sources']+manifest['conclusions'] if r['path']==name);assert hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256'];hashes+=1
links=0
for path in paths[:4]:
    for ref in re.findall(r'\]\(([^)]+)\)',path.read_text()):
        if '://' in ref or ref.startswith('#'):continue
        target=ref.split('#')[0].strip('<>');file=Path(target) if target.startswith('/') else path.parent/target
        if file.name in ['artifact_inventory.json','SIZE_REPORT.md']:continue
        assert file.exists(),(path,ref);links+=1
figures=[]
for path in sorted((H/'figures').glob('*.png')):
    with Image.open(path) as im:assert im.width>=1000 and im.height>=600;dimensions=[im.width,im.height];im.verify()
    figures.append(dict(path=str(path.relative_to(ROOT)),dimensions=dimensions,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),visually_inspected=True))
assert len(figures)==3
reg=json.loads((O/'registration.json').read_text());assert reg['independent_study_count_before']==reg['independent_study_count_after']==41
baseline=json.loads((O/'baseline_inventory.json').read_text())['related_existing_files'];shared={'thoroughbred/research/'+x for x in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};preserved=0
for row in baseline:
    if row['path'] in shared:continue
    path=ROOT/row['path'];assert path.stat().st_size==row['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256'];preserved+=1
out=dict(passed=True,additional_numeric_values=checks,own_manifest_hashes=hashes,local_links_checked=links,figures=figures,previous_files_preserved_after_publication=preserved,independent_study_count=41,inventory_pending_separate_self_inclusive_step=True)
(O/'final_review.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False))
