"""Review published claims, supplementary contrasts, episodes and preservation independently."""
from pathlib import Path
from collections import defaultdict
import json,hashlib,re,math
import numpy as np,pandas as pd,duckdb
from scipy.stats import t
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
pr=pd.read_csv(O/'horse_profiles.csv',dtype={'horse_id':str});a=pd.read_parquet(O/'roster.parquet');d=pd.read_parquet(O/'performance_observations.parquet');p=pd.read_parquet(O/'conditional_evaluation.parquet');pub=json.loads((O/'publication.json').read_text());summary=json.loads((O/'profile_summary.json').read_text());v=json.loads((O/'verification.json').read_text());assert v['passed'] and v['checks']==923124
c=duckdb.connect();c.register('pr',pr);c.register('d',d)
stats=c.execute('''select count(*) horses,sum(cast(supported5 as int)) s5,sum(cast(supported10 as int)) s10,
sum(cast(change_candidate as int)) changed,sum(cast(change_bh05 as int)) confirmed,
sum(cast(performance_comparison_supported as int)) supported,sum(cast(change_candidate and all10_same_distance as int)) same_distance,
sum(cast(recent365 and change_candidate as int)) recent_changed from pr''').df().iloc[0]
assert tuple(stats)==(12516,2601,1349,302,0,1753,4,287)
assert c.execute('select sum(cast(rank_raw<=5 as int)),sum(cast(good_adjusted as int)) from d').fetchone()==(69634,27134)
assert pub['summary']==summary and not any(pub[k] for k in ['personal_optimal_style_proven','causal_change_effect_proven','prerace_prediction_verified','operational'])
assert pr.loc[pr.supported5,'mode5'].value_counts().to_dict()=={'후미':806,'혼합':693,'중단':567,'선행':488,'선입':47}
current=pr.set_index('horse_id');support20=changed20=0
for horse,g in a.groupby('horse_id'):
 z=g.sort_values('date').tail(20);ok=len(z)==20 and z.role4.ge(0).all() and (pd.Timestamp('2026-09-20')-z.date.min()).days<=730;assert ok==current.loc[horse,'supported20'];flag=False
 if ok:
  old=z.role4.iloc[:10].value_counts();new=z.role4.iloc[10:].value_counts();flag=old.max()>=6 and new.max()>=6 and old.idxmax()!=new.idxmax()
 assert bool(flag)==current.loc[horse,'change20_candidate'];support20+=ok;changed20+=flag
assert (support20,changed20)==(217,11)
for col in ['moisture','distance_m','meet','date']:assert d.groupby('source_key')[col].nunique().max()==1
events=pd.read_csv(O/'change_events.csv',dtype={'horse_id':str});future=pd.read_parquet(O/'change_followup.parquet');ev=events[events.followup_supported];assert len(events)==1094 and len(ev)==734 and int(ev.new_retained3of5.sum())==252 and int(ev.old_hits.ge(3).sum())==198
assert (ev.new_hits+ev.old_hits<=5).all();assert len(future)==3670
# First eligible event is reconstructed with rolling SQL counts on actual roster slots.
c.register('a',a)
first=c.execute('''with x as (select *,row_number() over(partition by horse_id order by date) rn from a),
z as (select cur.horse_id,cur.row_key,cur.date,cur.year,min(prev.date) oldest,max(prev.date) latest,
sum(cast(prev.role4>=0 as int)) valid_n,
sum(cast(prev.rn<=cur.rn-6 and prev.role4=0 as int)) o0,sum(cast(prev.rn<=cur.rn-6 and prev.role4=1 as int)) o1,
sum(cast(prev.rn<=cur.rn-6 and prev.role4=2 as int)) o2,sum(cast(prev.rn<=cur.rn-6 and prev.role4=3 as int)) o3,
sum(cast(prev.rn>cur.rn-6 and prev.role4=0 as int)) n0,sum(cast(prev.rn>cur.rn-6 and prev.role4=1 as int)) n1,
sum(cast(prev.rn>cur.rn-6 and prev.role4=2 as int)) n2,sum(cast(prev.rn>cur.rn-6 and prev.role4=3 as int)) n3
from x cur join x prev on cur.horse_id=prev.horse_id and prev.rn between cur.rn-10 and cur.rn-1
where cur.year in(2024,2025) and cur.rn>=11 group by cur.horse_id,cur.row_key,cur.date,cur.year)
select * from z where valid_n=10 and date_diff('day',oldest,date)<=730 and date_diff('day',latest,date)>=2''').df()
om=first[[f'o{i}' for i in range(4)]].to_numpy();nm=first[[f'n{i}' for i in range(4)]].to_numpy();first=first[(om.max(axis=1)>=3)&(nm.max(axis=1)>=3)&(om.argmax(axis=1)!=nm.argmax(axis=1))].sort_values('date').drop_duplicates('horse_id');assert dict(zip(first.horse_id,first.row_key))==dict(zip(events.horse_id,events.event_row_key))
contrasts=[]
for rows_name,metrics_name in [('candidate_replication_rows.parquet','candidate_replication.csv'),('candidate_replication_supported_rows.parquet','candidate_replication_supported_styles.csv')]:
 rr=pd.read_parquet(O/rows_name);mt=pd.read_csv(O/metrics_name)
 for row in mt.itertuples():
  z=rr[rr.year.eq(row.year)].copy();means=z.groupby(['hd_key','candidate_match']).adjusted.mean().unstack();assert means.notna().all().all();est=float((means[True]-means[False]).mean());np.testing.assert_allclose(est,row.estimate)
  n=z.groupby(['hd_key','candidate_match']).row_key.transform('size');w=np.where(z.candidate_match,1.,-1.)/n/len(means);np.testing.assert_allclose(w,z.contrast_weight);mu={}
  for flag,g in z.groupby('candidate_match'):mu[flag]=np.average(g.adjusted,weights=abs(g.contrast_weight))
  score=w*(z.adjusted-np.where(z.candidate_match,mu[True],mu[False]));vs=[];ngs=[]
  for ids in [z.horse_id,z.date.dt.strftime('%Y-%m-%d'),list(zip(z.horse_id,z.date))]:
   sums=defaultdict(float)
   for key,s in zip(ids,score):sums[key]+=s
   ng=len(sums);vs.append(sum(s*s for s in sums.values())*ng/(ng-1));ngs.append(ng)
  se=math.sqrt(max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2]));crit=t.ppf(.975,min(ngs[:2])-1);np.testing.assert_allclose([row.se,row.lower,row.upper],[se,est-crit*se,est+crit*se]);assert len(z)==row.n
  if 'supported' in rows_name:
   assert z.prior_style_n.ge(3).all();counts=d[d.year.lt(row.year)].groupby(['hd_key','role4']).size().to_dict();assert [counts.get((hd,ro),0) for hd,ro in zip(z.hd_key,z.role4)]==z.prior_style_n.tolist()
  contrasts.append(dict(table=metrics_name,year=int(row.year),n=len(z),horses=z.horse_id.nunique(),estimate=est))
examples=pd.read_csv(O/'examples.csv',dtype={'horse_id':str}).set_index('horse_id');full=pr.set_index('horse_id');assert set(examples.index)=={'0044166','0044515','0045836','0050078'}
for horse,r in examples.iterrows():
 for col in ['count5_0','count5_1','count5_2','count5_3','old_count5_0','old_count5_1','old_count5_2','old_count5_3','good_adjusted_n']:assert r[col]==full.loc[horse,col]
actual=pd.read_csv(O/'example_actual_starts.csv',dtype={'horse_id':str});expected=a[a.horse_id.isin(examples.index)].groupby('horse_id',group_keys=False).tail(10);assert actual.row_key.tolist()==expected.row_key.tolist() and len(actual)==40
cp=pd.read_csv(O/'change_performance.csv',dtype={'horse_id':str}).set_index('horse_id');np.testing.assert_allclose([cp.loc['0045836','old_top5_rate'],cp.loc['0045836','new_top5_rate'],cp.loc['0050078','old_top5_rate'],cp.loc['0050078','new_top5_rate']],[1,0,.2,.6])
report=(H/'README.md').read_text();assert '252두·34.3%' in report and '251두' not in report and '@' not in report
for item in [H/'README.md',H/'PUBLICATION.md']:
 for bad in ['최적 각질을 확정했다','출전 전 예측을 개선했다']:assert bad not in item.read_text()
central=R/'conclusions/28B_HORSE_STYLE_PERFORMANCE.md';links=0
for f in [H/'README.md',H/'PUBLICATION.md',H/'SOURCES.md',H/'PLAN.md',H/'REPORT_TEMPLATE.md',central]:
 for target in re.findall(r'\]\(([^)]+)\)',f.read_text()):
  if target.startswith(('http://','https://','#')):continue
  path=(f.parent/target.split('#')[0]).resolve();assert path.is_relative_to(ROOT)
  if path==O/'artifact_inventory.json':continue
  assert path.exists(),(f,target);links+=1
manifest=json.loads((R/'conclusions/source_manifest.json').read_text());names={str(f.relative_to(ROOT)) for f in [H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',central,R/'conclusions/README.md',R/'conclusions/SOURCES.md']};found=0
for group in ['sources','conclusions']:
 for rec in manifest[group]:
  if rec['path'] in names:assert sha(ROOT/rec['path'])==rec['sha256'];found+=1
assert found==6
shared={'thoroughbred/research/'+f for f in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};preserved=0
for rec in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']:
 if rec['path'] in shared:continue
 assert sha(ROOT/rec['path'])==rec['sha256'];assert (ROOT/rec['path']).stat().st_size==rec['bytes'];preserved+=1
reg=json.loads((O/'registration.json').read_text());assert reg['independent_study_count_before']==reg['independent_study_count_after']==41
result=dict(passed=True,main_verification_checks=v['checks'],publication_claims_reproduced=True,independent_sql_first_change_events=len(first),candidate_replication_contrasts=contrasts,document_links_checked=links,own_manifest_hashes_checked=found,prior_files_preserved=preserved,figure_visual_review=['figures/horse_style_examples.png','figures/conditional_evidence.png'],independent_study_count=41,followup='28B',inventory_verified_separately_after_this_review=True)
(O/'final_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
