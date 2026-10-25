"""Preservation, independent coverage and replication CIs, claims and link review."""
from pathlib import Path
import hashlib,json,re,math
import numpy as np,pandas as pd,duckdb
from scipy.stats import t
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2];R=H.parent;sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
b=json.loads((O/'baseline_inventory.json').read_text());unchanged=[]
for a in b['related_existing_files']:
 if a['path'] not in b['shared_paths']:
  p=ROOT/a['path'];assert p.stat().st_size==a['bytes'] and sha(p)==a['sha256'],a['path'];unchanged.append(a['path'])
v=json.loads((O/'verification.json').read_text());assert v['passed'] and (v['input_hashes_verified'],v['raw_identity_and_finish_checks'],v['independent_models'],len(v['checks']))==(19,148126,10,4882)
metrics=pd.read_csv(O/'evaluation_metrics.csv');main=metrics[metrics.window.eq('2024_2025')&metrics.meet.eq('전체')&metrics.scope.eq('supported')].iloc[0];assert main.n==6180 and main.horses==1022 and main.lower<0<main.upper;assert .024<(main.baseline_mae-main.distance_mae)/main.baseline_mae*100<.026
profiles=pd.read_parquet(O/'horse_distance_profiles.parquet');c=pd.read_csv(O/'horse_candidates.csv',dtype={'horse_id':str});s=json.loads((O/'profile_summary.json').read_text());assert (s['unique_horses'],s['horse_venue_groups'],s['comparison_supported'],s['recent_supported'],s['small_gap'],s['larger_gap'])==(12428,12874,2634,760,2625,9);assert not s['individual_confidence_intervals'] and not s['unobserved_distances_inferred'];assert c.loc[~c.comparison_supported,'best_distance_m'].isna().all();recent=pd.read_csv(O/'recent_horse_candidates.csv');assert len(recent)==760
# Independent SQL coverage rather than the production Python horse loop.
d=pd.read_parquet(H.parent/'20261007_sex_ability_gap/outputs/population.parquet');d=d[d.distance_m.between(1000,1800)];con=duckdb.connect();con.register('d',d);raw=con.execute('select meet,horse_id,count(*) n,count(distinct distance_m) distances from d group by all order by meet,horse_id').df();saved=pd.read_csv(O/'horse_coverage.csv',dtype={'horse_id':str}).sort_values(['meet','horse_id']).reset_index(drop=True);assert raw[['meet','horse_id']].equals(saved[['meet','horse_id']]);np.testing.assert_array_equal(raw[['n','distances']],saved[['n','distances']])
rep_checks=[]
for year in [2024,2025]:
 r=pd.read_parquet(O/f'eval{year}_predictions.parquet');field=r.groupby('source_key').row_key.transform('size');r['target']=(r.actual-r.baseline)*field/(field-1);rep=pd.read_csv(O/f'{year}_replication.csv');chosen=rep.set_index('horse_key').best_distance;r=r[r.supported&r.horse_key.isin(chosen.index)].copy();r=r[r.groupby(['horse_key','distance_m']).row_key.transform('size').ge(2)];r['chosen']=r.distance_m.eq(r.horse_key.map(chosen));assert len(r)==next(z['n_starts'] for z in s['replication'] if z['window']==str(year));count=r.groupby(['horse_key','chosen']).row_key.transform('size');weight=np.where(r.chosen,1.,-1.)/count/len(rep);aa=float((weight[r.chosen]*r.loc[r.chosen,'target']).sum());bb=float((-weight[~r.chosen]*r.loc[~r.chosen,'target']).sum());scores=weight*(r.target-np.where(r.chosen,aa,bb));cov=[]
 for ids in [r.horse_id,r.day_key,pd.MultiIndex.from_frame(r[['horse_id','day_key']])]:
  sums=pd.Series(scores.to_numpy()).groupby(pd.factorize(ids)[0]).sum();ng=len(sums);cov.append(float(sums@sums)*ng/(ng-1))
 se=math.sqrt(max(0,cov[0],cov[1],cov[0]+cov[1]-cov[2]));crit=t.ppf(.975,min(r.horse_id.nunique(),r.day_key.nunique())-1);expected=next(z for z in s['replication'] if z['window']==str(year));assert max(abs(se-expected['se']),abs(aa-bb-expected['candidate_minus_other']),abs(aa-bb+crit*se-expected['upper']))<1e-10;rep_checks.append(dict(year=year,n=len(r),horses=len(rep),se=se,passed=True))
pub=json.loads((O/'publication_summary.json').read_text(),parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)));assert not pub['individual_optimum_confirmed'] and not pub['causal'] and not pub['operational'] and not pub['individual_confidence_intervals'];assert pub['lambda_distance']==100 and pub['comparison_supported_horses']==2634
central=R/'conclusions/27_HORSE_DISTANCE_APTITUDE.md';manifest=json.loads((R/'conclusions/source_manifest.json').read_text());entries=[]
for key in ['sources','conclusions']:
 for a in manifest[key]:
  if H.name in a['path'] or a['path'] in [str(central.relative_to(ROOT)),'thoroughbred/research/conclusions/README.md','thoroughbred/research/conclusions/SOURCES.md']:assert sha(ROOT/a['path'])==a['sha256'];entries.append(a['path'])
assert len(entries)==6;links=[];pending=[]
for p in list(H.glob('*.md'))+[central]:
 for dest in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if '://' in dest or dest.startswith('#'):continue
  q=(p.parent/dest.split('#')[0]).resolve()
  if not q.exists():assert q==O/'artifact_inventory.json',q;pending.append(str(q))
  else:links.append(str(q))
text=(H/'README.md').read_text()
for phrase in ['2,634','760','0.025%','6,180','1,022','55.0%','49.6%','개인 신뢰구간','생리적 최적값','미경험 거리','2026년','정상 완주자 선택 모집단','관측기간 평균적 선호']:assert phrase in text,phrase
record=dict(passed=True,prior_related_files_unchanged=len(unchanged),unchanged_paths=unchanged,SQL_coverage_horse_venue_groups=len(raw),individual_profile_rows=len(profiles),candidates_supported=2634,recent_candidates=760,independent_models=10,numeric_checks=4882,replication_cluster_CI_independently_checked=rep_checks,manifest_entries_verified=entries,local_links_checked=len(links),pending_inventory_links=len(pending),figures_visually_inspected=['figures/future_validation.png','figures/individual_distance_examples.png'],claim_review='discrete observed distance candidates, not continuous optimum; training-only scales/medians/nuisance;2023 tuning separate from2024/2025 evaluation; future race outcomes for target reference only; same horse/date across venue clusters; conditioning and stable career effect;5/15 and0.10 display rules not inferential confidence; minor nonsignificant gain; selected normal finishers; replication small and nonrandom distance assignment; no operating model or database changes')
(O/'final_review.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n');print('Final review PASS',len(unchanged),'prior files;',len(raw),'coverage groups;',len(links),'links')
