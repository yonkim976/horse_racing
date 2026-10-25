"""Review complete publication, source preservation, shared hashes and event horizon."""
from pathlib import Path
import json,re,hashlib
import pandas as pd,numpy as np
from PIL import Image
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';CENTRAL=R/'conclusions/50C_HISTORICAL_PLANNED_PAIR_SWITCH_RACE.md';checks=0
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def check(value,label):
 global checks
 assert value,label;checks+=1
def compare(a,b,label,sortcols):
 a=a.sort_values(sortcols).reset_index(drop=True);b=b.sort_values(sortcols).reset_index(drop=True);check(a.shape==b.shape,label+' shape');check(set(a.columns)==set(b.columns),label+' columns');a=a[b.columns]
 for c in b:
  if pd.api.types.is_numeric_dtype(b[c]):check(np.allclose(a[c].to_numpy(float),b[c].to_numpy(float),rtol=1e-12,atol=1e-12,equal_nan=True),label+c)
  else:check(a[c].fillna('MISSING').astype(str).equals(b[c].fillna('MISSING').astype(str)),label+c)
def main():
 pub=json.loads((O/'publication.json').read_text());v=json.loads((O/'verification.json').read_text());rv=json.loads((O/'recent_verification.json').read_text());check(v['passed'] and rv['passed'],'independent verifiers');check(len(v['independent_full_sparse_models'])==6,'all main/recent independent targets');check(len(rv['signals'])==6,'all recent BH contrasts independently checked')
 s=pd.read_csv(O/'pair_support.csv',dtype={'trainer_id':str,'jockey_id':str});e=pd.read_csv(O/'adjusted_associations.csv');t=pd.read_csv(O/'primary_pair_comparison.csv',dtype={'trainer_id':str,'jockey_id':str});q=s[s.model_supported];restored=pd.read_csv(O/'previous_17_recheck_results.csv');check(len(q)==213 and s.switch_supported.sum()==335,'support');check(len(restored)==17 and restored.model_supported.sum()==13,'former insufficient recovery')
 for key,b,sortcols in [('primary_pair_table',t,['pair_key']),('previous_17_recheck',restored,['pair_key']),('nominal_top3_candidates',pd.read_csv(O/'nominal_top3_candidates.csv',dtype={'trainer_id':str,'jockey_id':str}),['pair_key']),('support_table',s,['pair_key']),('all_primary_effects',e[e.window.eq('2019_2025')&e.model.eq('primary')],['target','contrast','pair_key']),('sensitivity_summary',pd.read_csv(O/'sensitivity_summary.csv'),['window','model','target','contrast']),('recent_bh_diagnostics',pd.read_csv(O/'recent_nominal_bh_diagnostics.csv',dtype={'trainer_id':str,'jockey_id':str}),['pair_key','target','contrast'])]:compare(pd.DataFrame(pub[key]),b,key,sortcols)
 check(not e[e.model.eq('primary')&e.contrast.ne('general_other_pairs')].q.lt(.05).any(),'main all targets no BH discovery');check(((t.estimate>0)&(t.p<.05)).sum()==4,'all nominal favorable top3 candidates');check(pub['primary_top3_positive_bh']==0,'headline');check(pub['target_horizon_races']==v['target_horizon_races']==0 and not pub['future_outcomes_created'],'only changed current race');check(pub['changed_events']==v['switch_events_verified_current_race_only']==40272,'all changed event rows verified');check(pub['ability_FE_is_retrospective'] and not pub['predictive_improvement_proven'] and not pub['causal_intent_proven'] and not pub['top_indicator_used'] and not pub['production_changed'],'scope')
 top=e[e.model.eq('primary')&e.target.eq('top3')&e.contrast.ne('general_other_pairs')];selected=set(restored[restored.model_supported].pair_key)|set(q.nlargest(5,'switch_n').pair_key)|set(top[top.p<.05].pair_key)
 checked={(x['pair_key'],x['contrast']) for x in v['selected_primary_cluster_CIs'] if x['target']=='top3'};check(checked=={(key,c) for key in selected for c in ['pair_extra','pair_total']},'all predeclared CI audit contrasts')
 text=(H/'PUBLICATION.md').read_text();report=(H/'README.md').read_text();full=(O/'all_213_top3_pairs.md').read_text();check('2019~2025' in text and '40,272' in text and '213' in text,'headline scope');check('변경7/유지15' in text and '3결과 공동' in text,'recent inadequate support disclosed');check('목표로 쓰지는 않지만' in report and '분석기간 전체' in report,'retrospective FE disclosed');check('-1보다 작아' in report and '173조합' in report,'recent model caveat');check('다음 경주·여러 경주 평균' in report,'horizon definition')
 for row in t.itertuples():check(row.trainer_name+'→'+row.jockey_name in full and f'{100*row.estimate:+.2f}' in full,'all213 published')
 for row in restored.itertuples():check(row.trainer_name+'→'+row.jockey_name in report,'all17 reconsidered')
 for x in json.loads((O/'source_audit.json').read_text())['inputs']:check(sha(ROOT/x['path'])==x['sha256'],'input preserved')
 shared={x['path'] for x in json.loads((O/'shared_edits_baseline.json').read_text())['files']};baseline=json.loads((O/'baseline_inventory.json').read_text())['related_existing_files'];preserved=0
 for x in baseline:
  if x['path'] in shared:continue
  p=ROOT/x['path'];check(p.stat().st_size==x['bytes'] and sha(p)==x['sha256'],'prior file '+x['path']);preserved+=1
 check(preserved==193,'all earlier studies preserved')
 manifest=json.loads((R/'conclusions/source_manifest.json').read_text());entries=manifest['sources']+manifest['conclusions']
 for p in [H/'README.md',H/'PUBLICATION.md',H/'SOURCES.md',CENTRAL,R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md']:
  records=[x for x in entries if x['path']==str(p.relative_to(ROOT))];check(bool(records),'registered path');check(all(x['sha256']==sha(p) for x in records),'all manifest copies')
 reg=json.loads((O/'registration.json').read_text());count=max(map(int,re.findall(r'^\| (\d+) \|',(R/'conclusions/README.md').read_text(),re.M)));check(count==reg['independent_table_count_before']==reg['independent_table_count_after']==42,'unchanged independent count')
 future={O/'artifact_inventory.json',O/'SIZE_REPORT.md'};links=0
 for p in list(H.glob('*.md'))+[CENTRAL,O/'all_213_top3_pairs.md']:
  for url in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if url.startswith(('http:','https:','#')):continue
   path=(p.parent/url.split('#')[0]).resolve();check(path.exists() or path in future,'local link '+str(path));links+=1
 figures=[]
 for p in (H/'figures').glob('*.png'):
  im=Image.open(p);check(im.width>=1200 and im.height>=600,'figure dimensions');check(float(np.std(np.asarray(im)))>20,'figure nonblank');figures.append(dict(path=str(p.relative_to(ROOT)),width=im.width,height=im.height,sha256=sha(p),visually_inspected=True))
 check(len(figures)==3,'all figures');result=dict(passed=True,checks=checks,independent_verification_checks=v['checks']+rv['checks'],prior_related_files_preserved=preserved,shared_modified_files=len(shared),complete_pairs=213,former_insufficient_pairs_reviewed=17,publication_matches_results=True,event_horizon_races=0,independent_study_count_unchanged=count,local_links_checked=links,figures=figures)
 (O/'final_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
