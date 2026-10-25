"""Complete annual publication, event scope, preserved prior files and manifest review."""
from pathlib import Path
import json,re,hashlib
import pandas as pd,numpy as np
from PIL import Image
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';CENTRAL=R/'conclusions/50E_ALL_PAIR_NONPODIUM_SWITCH_IMPROVEMENT.md';checks=0
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
 pub=json.loads((O/'publication.json').read_text());v=json.loads((O/'verification.json').read_text());av=json.loads((O/'conditional_annual_verification.json').read_text());check(v['passed'] and av['passed'],'independent verifiers');base=pd.read_csv(O/'adjusted_associations.csv',dtype={'period':str});extra=pd.read_csv(O/'conditional_annual_associations.csv',dtype={'period':str});core=pd.concat([base,extra],ignore_index=True);e=pd.read_csv(O/'all_adjusted_associations.csv',dtype={'period':str});check(len(e)==44*213 and not e.duplicated(['period','target','pair_key']).any(),'all44models all213pairs');compare(e[core.columns],core,'combined complete coefficients',['period','target','pair_key'])
 main=e[e.period.eq('2019_2025')];favorable=np.where(main.target.str.startswith('nonpodium_'),main.estimate.gt(0),main.estimate.lt(0));candidates=main[favorable&main.p.lt(.05)].copy();candidate_periods=e.merge(candidates[['pair_key','target']],on=['pair_key','target'],how='inner',validate='many_to_one')
 for key,b,keys in [('pooled_favorable_nominal_candidates',candidates,['pair_key','target']),('candidate_annual_and_recent',candidate_periods,['pair_key','target','period']),('all_BH_diagnostics',e[e.q.lt(.05)],['pair_key','target','period']),('family_summary',pd.read_csv(O/'family_summary.csv',dtype={'period':str}),['target','period']),('case_totals',pd.read_csv(O/'case_totals.csv',dtype={'period':str}),['period'])]:compare(pd.DataFrame(pub[key]),b,key,keys)
 check(len(candidates)==10 and len(pub['all_BH_diagnostics'])==19,'all favorable nominal and all BH rows');check(not main[(main.target.str.startswith('nonpodium_')&main.estimate.gt(0))|(~main.target.str.startswith('nonpodium_')&main.estimate.lt(0))].q.lt(.05).any(),'whole-period favorable BH none');families=pd.read_csv(O/'family_summary.csv');check(families.BH_favorable_supported.sum()==0,'all year/recent favorable BH lack sample support');check(pub['prior_four_used_for_selection'] is False and pub['fixed_supported_pairs']==213 and pub['all_observed_historical_pairs']==3386,'whole pair scope');check(pub['target_horizon_races']==v['target_horizon_races']==0 and not pub['future_outcomes_created'],'one current race');check(pub['composite_not_overall_performance_score'] and pub['conditional_current_outcome_selection'] and pub['ability_FE_retrospective'] and not pub['causal_intent_proven'] and not pub['predictive_improvement_proven'] and not pub['production_changed'],'honest estimands')
 events=pd.read_parquet(O/'current_switch_event_cases.parquet');cases=pd.read_parquet(O/'all_observed_nonpodium_improvement_cases.parquet');mask=events.nonpodium_rank_improved.eq(1)|events.nonpodium_time_improved.eq(1)|events.nonpodium_raw_rank_improved.eq(1);check(cases.equals(events[mask].reset_index(drop=True)),'every observed case preserved');check(cases.nonpodium.all() and cases.row_key.is_unique,'no podium/future/duplicate case');check(pub['all_case_extraction_rows']==len(cases),'case extraction count')
 total=pd.read_csv(O/'case_totals.csv',dtype={'period':str})
 for row in total.itertuples():
  g=events[events.year.le(2025)] if row.period=='2019_2025' else events[events.year.between(2024,2025)] if row.period=='2024_2025' else events[events.year.eq(2026)];r=g.nonpodium_rank_improved.eq(1);t=g.nonpodium_time_improved.eq(1);n=g.nonpodium_raw_rank_improved.eq(1)
  check((row.changed,row.nonpodium,row.rank_cases,row.raw_rank_cases,row.time_cases,row.rank_and_time,row.relative_rank_or_time,row.raw_or_relative_rank_or_time)==(len(g),int(g.nonpodium.sum()),int(r.sum()),int(n.sum()),int(t.sum()),int((r&t).sum()),int((r|t).sum()),int((r|n|t).sum())),'case totals '+row.period)
 t=total[total.period.eq('2019_2025')].iloc[0];check((t.nonpodium,t.rank_valid_nonpodium,t.rank_cases,t.raw_rank_cases,t.time_valid_nonpodium,t.time_cases,t.rank_and_time,t.relative_rank_or_time,t.raw_or_relative_rank_or_time)==(29568,29515,11807,11141,11006,5108,3166,13749,14524),'headline exact counts')
 all_pairs=pd.read_csv(O/'all_pair_coverage.csv');check(len(all_pairs)==pub['all_period_pair_count']==3604 and all_pairs.individual_model_frozen_supported.sum()==213,'all pairs including unsupported');check(len(v['independent_models'])+len(av['independent_models'])==44,'44 independent sparse models');check(len(v['independent_cluster_CIs'])==58 and len(av['independent_cluster_CIs'])==5,'all selected CIs verified')
 report=(H/'README.md').read_text();text=(H/'PUBLICATION.md').read_text();annual=(O/'candidate_annual_tables.md').read_text();check('비입상' in text and '현재 결과로 집단을 고른' in text and '전반적 경기력' in text,'selection/composite caveats');check('11,807' in text and '5,108' in text and '3,166' in text and '13,749' in text,'public counts');check('명단을 고정' in report and '해당연도 내에서 재추정' in report,'annual method');check('최초카드불변성미인증' in report and '사후 통제' in report,'limitations');check('14/유지13' in text and '15/유지24' in text,'recent sample size');check('9월13일' in text and '9월11일' in text,'partial-period end')
 for row in candidates.itertuples():
  check(row.trainer_name+'→'+row.jockey_name in text,'all10 nominal candidates published');check(row.trainer_name+'와 '+row.jockey_name in annual,'all candidate annual sections')
 for period in [str(y) for y in range(2019,2026)]+['2019_2023','2024_2025','2026_partial']:check(annual.count('| '+period+' |')==10,'all candidate annual/recent rows '+period)
 for x in json.loads((O/'source_audit.json').read_text())['inputs']:check((ROOT/x['path']).stat().st_size==x['bytes'] and sha(ROOT/x['path'])==x['sha256'],'unchanged source')
 shared={x['path'] for x in json.loads((O/'shared_edits_baseline.json').read_text())['files']};baseline=json.loads((O/'baseline_inventory.json').read_text())['related_existing_files'];preserved=0
 for x in baseline:
  if x['path'] in shared:continue
  p=ROOT/x['path'];check(p.stat().st_size==x['bytes'] and sha(p)==x['sha256'],'preserved '+x['path']);preserved+=1
 check(preserved==len(baseline)-5==194,'all previous studies unchanged')
 manifest=json.loads((R/'conclusions/source_manifest.json').read_text());entries=manifest['sources']+manifest['conclusions']
 for p in [H/'README.md',H/'PUBLICATION.md',H/'SOURCES.md',CENTRAL,R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md']:
  found=[x for x in entries if x['path']==str(p.relative_to(ROOT))];check(bool(found),'registered path');check(all(x['sha256']==sha(p) for x in found),'every manifest copy')
 reg=json.loads((O/'registration.json').read_text());count=max(map(int,re.findall(r'^\| (\d+) \|',(R/'conclusions/README.md').read_text(),re.M)));check(count==reg['independent_table_count_before']==reg['independent_table_count_after'],'independent count unchanged')
 future={O/'artifact_inventory.json',O/'SIZE_REPORT.md'};links=0
 for p in list(H.glob('*.md'))+[CENTRAL,O/'candidate_annual_tables.md']:
  for url in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if url.startswith(('http:','https:','#')):continue
   target=(p.parent/url.split('#')[0]).resolve();check(target.exists() or target in future,'local link '+str(target));links+=1
 figures=[]
 for p in (H/'figures').glob('*.png'):
  im=Image.open(p);check(im.width>=1200 and im.height>=600,'figure resolution');check(float(np.std(np.asarray(im)))>20,'figure nonblank');figures.append(dict(path=str(p.relative_to(ROOT)),width=im.width,height=im.height,sha256=sha(p),visually_inspected=True))
 check(len(figures)==3,'all3 figures');out=dict(passed=True,checks=checks,independent_checks=v['checks']+av['checks'],prior_related_files_preserved=preserved,shared_modified_files=len(shared),all_independent_models=44,all_independent_CI_checks=63,complete_supported_pair_family=213,all_observed_period_pairs=3604,all_current_changed_events=44341,target_horizon_races=0,publication_matches_results=True,independent_study_count_unchanged=count,local_links_checked=links,figures=figures)
 (O/'final_review.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
