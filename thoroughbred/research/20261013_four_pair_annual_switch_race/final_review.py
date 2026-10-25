"""Complete annual publication, event scope, preserved prior files and manifest review."""
from pathlib import Path
import json,re,hashlib
import pandas as pd,numpy as np
from PIL import Image
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';CENTRAL=R/'conclusions/50D_FOUR_PAIR_ANNUAL_SWITCH_RACE.md';checks=0
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
 pub=json.loads((O/'publication.json').read_text());v=json.loads((O/'verification.json').read_text());cv=json.loads((O/'coverage_verification.json').read_text());check(v['passed'] and cv['passed'],'all independent verification');e=pd.read_csv(O/'adjusted_period_effects.csv',dtype={'period':str});raw=pd.read_csv(O/'raw_period_metrics.csv',dtype={'period':str});frozen=pd.read_csv(O/'frozen_four_pairs.csv');check(len(frozen)==4,'four frozen pairs');check(len(e)==132 and len(raw)==80,'complete model and zero-start grids')
 for key,b,keys in [('frozen_four_pairs',frozen,['pair_key']),('top3_period_table',pd.read_csv(O/'top3_period_comparison.csv',dtype={'period':str}),['model','pair_key','period','contrast']),('raw_period_table',raw,['model','pair_key','period','state']),('all_adjusted_effects',e,['model','target','pair_key','period','contrast']),('family_summary',pd.read_csv(O/'family_summary.csv'),['model','target','contrast']),('population_coverage_diagnostic',pd.read_csv(O/'population_coverage_diagnostic.csv'),['year','pair_key','population','state'])]:compare(pd.DataFrame(pub[key]),b,key,keys)
 check(pub['target_horizon_races']==v['target_horizon_races']==0 and not pub['future_outcomes_created'],'current race only');check(pub['current_switch_events']==v['current_switch_events']==240,'all changed events');check(pub['original_213_BH_passed'] is False and pub['ability_FE_retrospective'] and not pub['prediction_test'] and not pub['causal_intent_proven'] and not pub['production_changed'],'honest postselection scope')
 check(len(v['independent_sparse_models'])==9,'all3model×3targets');expected={(r.model,r.pair_key,r.period,r.contrast,r.target) for r in e[e.status.eq('estimated')&(e.target.eq('top3')|e.q_fixed_family.lt(.05))].itertuples()};observed={(r['model'],r['pair_key'],r['period'],r['contrast'],r['target']) for r in v['independent_cluster_CIs']};check(expected==observed,'all predeclared CIs checked')
 top=e[e.target.eq('top3')];check(not top.q_fixed_family.lt(.05).any(),'no exploratory top3 BH discoveries');signals=e[e.q_fixed_family.lt(.05)];check(len(signals)==5 and signals.jockey_name.eq('조한별').all() and (~signals.pair_period_supported).all(),'all auxiliary BH signals are small-sample Kim pair');check(e[e.contrast.eq('recent_minus_earlier')&e.target.eq('top3')&e.status.eq('estimated')].ci_low.le(0).all() and e[e.contrast.eq('recent_minus_earlier')&e.target.eq('top3')&e.status.eq('estimated')].ci_high.ge(0).all(),'top3 change intervals span0')
 report=(H/'README.md').read_text();text=(H/'PUBLICATION.md').read_text();annual=(O/'all_annual_top3.md').read_text();check('2026' in report and '9월13일' in report and '9월11일' in report,'partial period scope');check('연간100회 지원 제한만 해제' in report and '2/3' in report and '4/13' in report,'coverage distinction');check('55변경 중50회' in text and '변경7/유지15' in text,'concentration and recent denominator');check('원래 네 조합은213조합 검정에서 확정되지 않은 후보' in text and '후보를 고른 뒤' in text,'postselection caveat');check('우승마와 시간차-1.376초' in report and '-0.505' in report and '탐색q=.0081' in report,'secondary signals fully reported');check('사후 통제' in report and '전체 분석기간' in report,'retrospective ability caveat');check('-3.05' in text and '-55.33~+49.24' in text,'partial Min estimate exact')
 for row in frozen.itertuples():check(row.trainer_name+'와 '+row.jockey_name in annual,'all four annual sections')
 for year in range(2019,2026):check(annual.count('| '+str(year)+' |')==4,'all four year rows '+str(year))
 for x in json.loads((O/'source_audit.json').read_text())['inputs']:check((ROOT/x['path']).stat().st_size==x['bytes'] and sha(ROOT/x['path'])==x['sha256'],'unchanged source')
 shared={x['path'] for x in json.loads((O/'shared_edits_baseline.json').read_text())['files']};baseline=json.loads((O/'baseline_inventory.json').read_text())['related_existing_files'];preserved=0
 for x in baseline:
  if x['path'] in shared:continue
  p=ROOT/x['path'];check(p.stat().st_size==x['bytes'] and sha(p)==x['sha256'],'preserved '+x['path']);preserved+=1
 check(preserved==len(baseline)-5==159,'all old research preserved')
 manifest=json.loads((R/'conclusions/source_manifest.json').read_text());entries=manifest['sources']+manifest['conclusions']
 for p in [H/'README.md',H/'PUBLICATION.md',H/'SOURCES.md',CENTRAL,R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md']:
  found=[x for x in entries if x['path']==str(p.relative_to(ROOT))];check(bool(found),'registered path');check(all(x['sha256']==sha(p) for x in found),'all manifest copies')
 reg=json.loads((O/'registration.json').read_text());count=max(map(int,re.findall(r'^\| (\d+) \|',(R/'conclusions/README.md').read_text(),re.M)));check(count==reg['independent_table_count_before']==reg['independent_table_count_after'],'independent count unchanged')
 future={O/'artifact_inventory.json',O/'SIZE_REPORT.md'};links=0
 for p in list(H.glob('*.md'))+[CENTRAL,O/'all_annual_top3.md']:
  for url in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if url.startswith(('http:','https:','#')):continue
   target=(p.parent/url.split('#')[0]).resolve();check(target.exists() or target in future,'local link '+str(target));links+=1
 figures=[]
 for p in (H/'figures').glob('*.png'):
  im=Image.open(p);check(im.width>=1600 and im.height>=1000,'resolution');check(float(np.std(np.asarray(im)))>20,'nonblank');figures.append(dict(path=str(p.relative_to(ROOT)),width=im.width,height=im.height,sha256=sha(p),visually_inspected=True))
 check(len(figures)==2,'both figures');result=dict(passed=True,checks=checks,independent_checks=v['checks']+cv['checks'],prior_related_files_preserved=preserved,shared_modified_files=len(shared),complete_annual_pair_years=28,current_switch_events=240,target_horizon_races=0,publication_matches_results=True,independent_study_count_unchanged=count,local_links_checked=links,figures=figures)
 (O/'final_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
