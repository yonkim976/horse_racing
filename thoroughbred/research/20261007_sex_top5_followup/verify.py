"""Independent rank/SQL checks, prior-result reproduction, QR and sparse FE verification."""
from pathlib import Path
import hashlib,json
import duckdb,numpy as np,pandas as pd
from scipy import linalg,sparse
from scipy.sparse.linalg import lsmr
from scipy.stats import t
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs';source=H.parent/'20261007_sex_ability_gap/outputs/population.parquet'
r=pd.read_csv(O/'contrasts.csv');s=pd.read_csv(O/'descriptives.csv');d=pd.read_parquet(source)
d['rank']=pd.to_numeric(d.rank_raw,errors='raise');d['top5']=d['rank'].between(1,5).astype(float)
d['distance_group']=np.where(d.distance_m<=1400,'short',np.where(d.distance_m<=1800,'middle','long'));d['seconds_per_1000m']=d.finish*1000/d.distance_m;d['age_squared']=d.age**2
checks=[]
def check(name,error,tol=1e-7):
 error=float(error);assert np.isfinite(error) and error<tol,(name,error,tol);checks.append(dict(check=name,error=error,tolerance=tol))
assert len(d)==151074 and d.row_key.nunique()==len(d) and d.source_key.nunique()==13928
assert set(d.sex)=={'암','수','거'} and d['rank'].notna().all() and d['rank'].ge(1).all()
assert d.groupby('source_key').top5.sum().le(5).all();assert int(d.top5.sum())==69639
assert (d[d.complete_retained_race].groupby('source_key').top5.sum()==5).all()
check('win indicator',abs(d.win-d['rank'].eq(1)).max());check('top3 indicator',abs(d.top3-d['rank'].le(3)).max())
check('independent segment sum',abs(d.finish-d[['early','middle1','middle2','late']].sum(axis=1)).max(),.0011)
for name,h in json.loads((O/'source_and_method.json').read_text())['inputs_sha256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h
ledger=pd.read_parquet(H.parent/'20261007_sex_ability_gap/outputs/selection_ledger.parquet')
missing_keys=d.groupby('source_key').top5.sum().loc[lambda x:x.lt(5)].index
missing=ledger[ledger.source_key.isin(missing_keys)&ledger['rank'].between(1,5)&~ledger.selected]
assert len(missing)==1 and missing.sex_raw.eq('수').all() and missing.selection_reason.eq('section_quality_or_distance_parent').all()
con=duckdb.connect();con.register('data',d)
a=con.sql('SELECT meet,sex,count(*) n,avg(body_weight) body_weight_mean,avg(weight) weight_mean FROM data WHERE rank<=5 GROUP BY meet,sex').df()
b=s[s.cohort.eq('top5')&s.scope.eq('venue')].merge(a,on=['meet','sex'],suffixes=('_a','_b'))
for c in ['n','body_weight_mean','weight_mean']:check('SQL top5 '+c,abs(b[c+'_a']-b[c+'_b']).max())
a=con.sql('SELECT meet,sex,avg(bw) body_weight_horse_equal_mean FROM (SELECT meet,sex,horse_id,avg(body_weight) bw FROM data WHERE rank<=5 GROUP BY ALL) GROUP BY ALL').df()
b=s[s.cohort.eq('top5')&s.scope.eq('venue')].merge(a,on=['meet','sex'],suffixes=('_a','_b'))
check('SQL top5 horse equal means',abs(b.body_weight_horse_equal_mean_a-b.body_weight_horse_equal_mean_b).max())
# All-starter time and win/top3 estimates must reproduce frozen previous follow-up.
old=pd.read_csv(H.parent/'20261007_sex_weight_distance_followup/outputs/joint_contrasts.csv')
old=old[old.scope.isin(['time_joint','race_joint'])&old.specification.isin(['grade','full','race','race_full'])].copy()
old['scope']=old.scope.map({'time_joint':'time','race_joint':'race_outcome'})
new=r[r.cohort.eq('all')&r.scope.isin(['time','race_outcome'])&r.window.isin(['all','complete_2024_2025'])]
keys=['scope','meet','specification','window','target','reference','part','contrast']
j=new.merge(old,on=keys,suffixes=('_new','_old'));assert len(j)==432
for c in ['difference','se','lower','upper','common_n']:check('prior reproduction '+c,np.nanmax(abs(j[c+'_new']-j[c+'_old'])))
for k,g in r[r.scope.ne('weight')].groupby(['scope','cohort','meet','specification','window','target','reference','part']):
 z=g.set_index('contrast');check('joint contrast identity',abs(z.loc['middle_minus_short','difference']-z.loc['middle_gap','difference']+z.loc['short_gap','difference']))
z=r[r.supported];critical=t.ppf(.975,np.minimum(z.horse_clusters,z.date_clusters)-1);check('all CI arithmetic',abs(z.upper-z.difference-critical*z.se).max())
assert r[r.part.eq('top5')].unit.eq('percentage_points').all()
fe=['distance_m','year','month','age','moisture','grade'];load=['weight','body_weight','weight_squared','body_squared'];form=['rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap']
ind=[];sparsefits=0
for scope,cohort in [('time','top5'),('time','all_in_top5_common_cells'),('race_outcome','all'),('race_selected_time','top5')]:
 for meet in ['서울','부산']:
  for target,reference in [('암','수'),('거','수'),('암','거')]:
   q=d[d.meet.eq(meet)&d.sex.isin([target,reference])&d.distance_group.ne('long')].copy()
   if scope=='time':
    keys=fe;cols=load+form;out=['finish','seconds_per_1000m','early','late'];spec='full'
    selected=q[q.top5.eq(1)]
    if cohort=='top5':q=selected
    else:
     c=selected.groupby(fe,dropna=False).sex.nunique();valid=c[c.eq(2)].index;q=q.set_index(fe).loc[valid].reset_index()
   else:
    q=q[q.mixed_actual&q.complete_retained_race&~q.original_nonstandard&~q.sex_condition.eq('암')].copy()
    if cohort=='top5':q=q[q.top5.eq(1)]
    keys=['source_key'];cols=['age','age_squared']+load+form;out=['top5','top3','win'] if scope=='race_outcome' else ['finish','early','late'];spec='race_full'
   cells=q.groupby(keys,dropna=False).sex.nunique();valid=cells[cells.eq(2)].index;q=q.set_index(keys).loc[valid].reset_index();n=len(q)
   codes=pd.factorize(pd.MultiIndex.from_frame(q[keys]))[0];nc=codes.max()+1;features=[]
   for col in cols:
    a=q[col].astype(float);miss=a.isna()
    if miss.all():continue
    a=a.fillna(a.median());sd=a.std(ddof=0)
    if sd>1e-10:features.append(((a-a.mean())/sd).to_numpy())
    if miss.any():features.append(miss.astype(float).to_numpy())
   z=np.array(features).T;groups=[q.distance_group.eq(a).to_numpy(float) for a in ['short','middle']];sex=q.sex.eq(target).to_numpy(float)
   x=np.column_stack([sex*groups[0],sex*groups[1],z*groups[0][:,None],z*groups[1][:,None]]);y=q[out].to_numpy(float)
   xy=pd.DataFrame(np.column_stack([x,y]));xy['cell']=codes;dm=(xy.drop(columns='cell')-xy.groupby('cell').transform('mean')).to_numpy();xx=dm[:,:x.shape[1]];yy=dm[:,x.shape[1]:]
   beta,_,rank,_=linalg.lstsq(xx,yy,cond=1e-12,lapack_driver='gelsy');res=yy-xx@beta;pseudo=linalg.pinv(xx,rtol=1e-12);df=n-nc-rank
   expected=r[r.scope.eq(scope)&r.cohort.eq(cohort)&r.meet.eq(meet)&r.target.eq(target)&r.reference.eq(reference)&r.specification.eq(spec)&r.window.eq('all')]
   assert expected.common_n.eq(n).all() and expected.fe_groups.eq(nc).all()
   for part in out:
    j=out.index(part);mult=100 if part in ['win','top3','top5'] else 1
    for contrast,v0 in [('short_gap',[1,0]),('middle_gap',[0,1]),('middle_minus_short',[-1,1])]:
     v=np.r_[v0,np.zeros(x.shape[1]-2)];score=(v@pseudo)*res[:,j];variances=[]
     for ids in [q.horse_id,q.day_key,pd.MultiIndex.from_frame(q[['horse_id','day_key']])]:
      agg=pd.Series(score).groupby(np.asarray(pd.factorize(ids)[0])).sum();ng=len(agg);variances.append(float(agg.pow(2).sum()*ng/(ng-1)*(n-1)/df))
     se=np.sqrt(max(variances[0],variances[1],variances[0]+variances[1]-variances[2]))*mult;b=float(v@beta[:,j])*mult;row=expected[expected.part.eq(part)&expected.contrast.eq(contrast)].iloc[0]
     check(f'{scope}/{cohort}/{meet}/{target}-{reference}/{part}/{contrast} coefficient',abs(b-row.difference),2e-6)
     check(f'{scope}/{cohort}/{meet}/{target}-{reference}/{part}/{contrast} cluster SE',abs(se-row.se),2e-6)
     ind.append(dict(scope=scope,cohort=cohort,meet=meet,target=target,reference=reference,part=part,contrast=contrast,n=n,difference=b,se=se))
   if target=='암' and reference=='수' and ((scope=='time' and cohort=='top5') or scope=='race_outcome'):
    dummy=sparse.csr_matrix((np.ones(n),(np.arange(n),codes)),shape=(n,nc));full=sparse.hstack([sparse.csr_matrix(x),dummy],format='csr');part='top5' if scope=='race_outcome' else 'finish';fit=lsmr(full,q[part].to_numpy(),atol=1e-12,btol=1e-12,maxiter=3000)
    check(f'explicit sparse FE {scope}/{meet}',np.max(abs(fit[0][:2]-beta[:2,out.index(part)])),2e-5);assert fit[1] in [1,2],fit[1];sparsefits+=1
   print(scope,cohort,meet,target,reference,'verified',flush=True)
pd.DataFrame(ind).to_csv(O/'independent_model_checks.csv',index=False)
obj=dict(passed=True,top5_n=69639,original_races=13928,missing_top5_retained_rows_vs_five_per_race=int(5*13928-d.top5.sum()),source_hashes_verified=True,prior_results_reproduced=432,independent_model_rows=len(ind),explicit_sparse_fe_fits=sparsefits,checks=checks,limitation='Numerical validation does not remove outcome selection, confounding or establish prospective prediction.')
(O/'verification.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');print('PASS',len(checks),'checks, independent rows',len(ind))
