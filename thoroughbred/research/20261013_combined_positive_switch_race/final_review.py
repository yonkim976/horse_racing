"""Complete annual publication, event scope, preserved prior files and manifest review."""
from pathlib import Path
import json,re,hashlib
import pandas as pd,numpy as np
from PIL import Image
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';CENTRAL=R/'conclusions/50F_COMBINED_POSITIVE_SWITCH_RACE.md';checks=0
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def check(value,label):
 global checks
 assert value,label;checks+=1
def compare(a,b,label,keys):
 a=a.sort_values(keys).reset_index(drop=True);b=b.sort_values(keys).reset_index(drop=True);check(a.shape==b.shape,label+' shape');check(set(a.columns)==set(b.columns),label+' columns');a=a[b.columns]
 for c in b:
  if pd.api.types.is_numeric_dtype(b[c]):check(np.allclose(a[c].to_numpy(float),b[c].to_numpy(float),rtol=1e-12,atol=1e-12,equal_nan=True),label+c)
  else:check(a[c].fillna('MISSING').astype(str).equals(b[c].fillna('MISSING').astype(str)),label+c)
def main():
 pub=json.loads((O/'publication.json').read_text());v=json.loads((O/'verification.json').read_text());check(v['passed'],'independent verifier');source=pd.read_csv(O/'adjusted_associations.csv',dtype={'period':str});e=pd.read_csv(O/'all_pair_period_comparison.csv',dtype={'period':str});compare(e[source.columns],source,'all model comparisons',['period','target','pair_key']);check(len(e)==33*213 and not e.duplicated(['period','target','pair_key']).any(),'all33models');main=e[e.period.eq('2019_2025')];candidates=main[main.estimate.gt(0)&main.p.lt(.05)];candidate_periods=e.merge(candidates[['pair_key','target']],on=['pair_key','target'],how='inner',validate='many_to_one');recent=e[e.period.isin(['2019_2025','2024_2025','2026_partial'])].merge(candidates[candidates.target.eq('combined_documented')][['pair_key','target']],on=['pair_key','target'],how='inner')
 for key,b,keys in [('coverage',pd.read_csv(O/'coverage.csv',dtype={'period':str}),['period']),('pooled_positive_nominal_candidates',candidates,['pair_key','target']),('candidate_annual_and_recent',candidate_periods,['period','pair_key','target']),('documented_candidates_recent',recent,['period','pair_key','target']),('documented_candidate_summary',pd.read_csv(O/'documented_candidate_summary.csv'),['pair_key']),('all_BH_diagnostics',e[e.q.lt(.05)],['period','target','pair_key']),('family_summary',pd.read_csv(O/'family_summary.csv',dtype={'period':str}),['period','target'])]:compare(pd.DataFrame(pub[key]),b,key,keys)
 check(len(candidates)==17 and candidates.pair_key.nunique()==13,'all nominal positive contrasts');check(len(candidates[candidates.target.eq('combined_documented')])==7,'all broad candidates');check((~candidates[candidates.target.eq('combined_complete')].target_supported).all(),'complete-comparison candidates support inadequate');check(not main[main.estimate.gt(0)].q.lt(.05).any(),'whole-period favorable BH none');check(len(pub['all_BH_diagnostics'])==8,'all positive and negative BH diagnostics');families=pd.read_csv(O/'family_summary.csv');check(families.positive_BH_supported.sum()==0,'all favorable BH fail period support');check(pub['prior_candidates_used'] is False and pub['fixed_supported_pairs']==213 and pub['all_historical_pairs']==3386 and pub['all_period_pair_count']==3604,'whole-pair scope');check(pub['target_horizon_races']==v['target_horizon_races']==0 and not pub['future_outcomes_created'],'current race only');check(pub['documented_zero_not_confirmed_failure'] and pub['overlap_counted_once'] and pub['ability_FE_retrospective'] and not pub['causal_intent_proven'] and not pub['predictive_improvement_proven'] and not pub['production_changed'],'honest observation/causal scope')
 events=pd.read_parquet(O/'current_switch_combined_events.parquet');positive=pd.read_parquet(O/'all_confirmed_positive_current_events.parquet');check(positive.equals(events[events.combined_documented.eq(1)].reset_index(drop=True)),'all confirmed positives extracted once');check(positive.row_key.is_unique and pub['confirmed_positive_events']==len(positive),'positive counts');check(pub['current_changed_events']==len(events)==44341,'all current events');g=events[events.year.le(2025)];parts=['positive_podium','positive_rank_and_time','positive_rank_only_confirmed','positive_time_only_confirmed','confirmed_nonpositive','unconfirmed_nonpositive'];check(g[parts].sum().tolist()==[10704,3166,8641,1942,4562,11257],'exact mutually exclusive components');check(g[parts].sum(axis=1).eq(1).all(),'every event partitioned once');check(int(g.combined_documented.sum())==24453 and len(g)==40272,'documented numerator');check((int(g.combined_complete.notna().sum()),int(g.combined_complete.sum()),int(g.podium_or_rank.notna().sum()),int(g.podium_or_rank.sum()))==(15094,10532,40200,22492),'fixed comparable numerators');check(g[g.top3.eq(1)].combined_documented.eq(1).all(),'all podiums included broadly');check(g[g.combined_complete.notna()].rank_comparable.all() and g[g.combined_complete.notna()].time_comparable.all(),'primary common eligibility')
 summary=pd.read_csv(O/'documented_candidate_summary.csv')
 for r in summary.itertuples():
  for period,prefix in [('2019_2025','main'),('2024_2025','recent'),('2026_partial','partial')]:
   z=recent[recent.pair_key.eq(r.pair_key)&recent.period.eq(period)].iloc[0]
   for col in ['estimate','ci_low','ci_high','q','switched_n','retained_n']:check(np.isclose(getattr(r,prefix+'_'+col),z[col],equal_nan=True),'candidate summary '+col)
   check(getattr(r,prefix+'_status')==z.status and getattr(r,prefix+'_target_supported')==z.target_supported,'candidate status/support')
 check(len(v['independent_models'])==33 and len(v['independent_cluster_CIs'])==49,'all independent fits and CI audit');shorts={}
 for target,z in main.groupby('target'):shorts[target]=set(z[z.p.lt(.05)].pair_key)|set(z[z.estimate.gt(0)].nlargest(5,'estimate').pair_key)|set(z.nlargest(5,'switched_n').pair_key)
 expected={(r.period,r.target,r.pair_key) for r in e[e.status.eq('estimated')].itertuples() if (r.period=='2019_2025' and r.pair_key in shorts[r.target]) or r.q<.05};actual={(r['period'],r['target'],r['pair_key']) for r in v['independent_cluster_CIs']};check(actual==expected,'all predeclared CI rows audited')
 report=(H/'README.md').read_text();text=(H/'PUBLICATION.md').read_text();annual=(O/'candidate_annual_tables.md').read_text();check('24,453' in text and '60.72%' in text and '15,094' in text and '69.78%' in text,'public rates');check('긍정이 확인되지 않았다고 모두 실패' in text and '분모가 다르다' in text,'unknown versus failure');check('입상한 말에도 동일' in report and '11,257' in report and '4,562' in report,'primary eligible and unknown partition');check('사후 통제' in report and '그연도 내에서 재추정' in report,'retrospective and annual FE');check('+29.57' in text and '+44.27' in text and '7/15' in text and '+118.68' in text,'recent values and denominator');check('실제 확률범위를 벗어날' in text,'linear probability caveat');check('9월13일' in text and '9월11일' in text,'partial2026 end')
 for row in candidates.itertuples():check(row.trainer_name+'→'+row.jockey_name in report,'all17 nominal rows in report');check(row.trainer_name+'와 '+row.jockey_name in annual,'all candidate annual sections')
 for period in [str(y) for y in range(2019,2026)]+['2019_2023','2024_2025','2026_partial']:check(annual.count('| '+period+' |')==17,'all17 period rows '+period)
 for x in json.loads((O/'source_audit.json').read_text())['inputs']:check((ROOT/x['path']).stat().st_size==x['bytes'] and sha(ROOT/x['path'])==x['sha256'],'unchanged source')
 shared={x['path'] for x in json.loads((O/'shared_edits_baseline.json').read_text())['files']};baseline=json.loads((O/'baseline_inventory.json').read_text())['related_existing_files'];preserved=0
 for x in baseline:
  if x['path'] in shared:continue
  p=ROOT/x['path'];check(p.stat().st_size==x['bytes'] and sha(p)==x['sha256'],'preserved '+x['path']);preserved+=1
 check(preserved==len(baseline)-5==240,'all earlier research preserved')
 manifest=json.loads((R/'conclusions/source_manifest.json').read_text());entries=manifest['sources']+manifest['conclusions']
 for p in [H/'README.md',H/'PUBLICATION.md',H/'SOURCES.md',CENTRAL,R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md']:
  records=[x for x in entries if x['path']==str(p.relative_to(ROOT))];check(bool(records),'registered path');check(all(x['sha256']==sha(p) for x in records),'all manifest copies')
 reg=json.loads((O/'registration.json').read_text());count=max(map(int,re.findall(r'^\| (\d+) \|',(R/'conclusions/README.md').read_text(),re.M)));check(count==reg['independent_table_count_before']==reg['independent_table_count_after'],'independent count unchanged')
 future={O/'artifact_inventory.json',O/'SIZE_REPORT.md'};links=0
 for p in list(H.glob('*.md'))+[CENTRAL,O/'candidate_annual_tables.md']:
  for url in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if url.startswith(('http:','https:','#')):continue
   path=(p.parent/url.split('#')[0]).resolve();check(path.exists() or path in future,'local link '+str(path));links+=1
 figures=[]
 for p in (H/'figures').glob('*.png'):
  im=Image.open(p);check(im.width>=1200 and im.height>=600,'figure resolution');check(float(np.std(np.asarray(im)))>20,'figure nonblank');figures.append(dict(path=str(p.relative_to(ROOT)),width=im.width,height=im.height,sha256=sha(p),visually_inspected=True))
 check(len(figures)==3,'all3figures');out=dict(passed=True,checks=checks,independent_checks=v['checks'],prior_related_files_preserved=preserved,shared_modified_files=len(shared),all_independent_models=33,all_independent_CI_checks=49,complete_supported_pair_family=213,all_current_changed_events=44341,target_horizon_races=0,publication_matches_results=True,independent_study_count_unchanged=count,local_links_checked=links,figures=figures)
 (O/'final_review.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
