"""Independent SQL summaries, explicit sparse FE fits, QR estimates and cluster sums."""
from pathlib import Path
import hashlib,json
import duckdb,numpy as np,pandas as pd
from scipy import linalg,sparse
from scipy.sparse.linalg import lsmr
from scipy.stats import t
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2]
p=H.parent/'20261007_sex_ability_gap/outputs/population.parquet'
r=pd.read_csv(O/'joint_contrasts.csv');s=pd.read_csv(O/'weight_and_population_summary.csv')
d=pd.read_parquet(p);d['distance_group']=np.where(d.distance_m<=1400,'short',np.where(d.distance_m<=1800,'middle','long'))
d['seconds_per_1000m']=d.finish*1000/d.distance_m;d['age_squared']=d.age**2
checks=[]
def check(name,error,tol=1e-7):
    error=float(error);assert np.isfinite(error) and error<tol,(name,error,tol)
    checks.append(dict(check=name,max_absolute_error=error,tolerance=tol))
con=duckdb.connect();con.register('data',d)
a=con.sql('SELECT meet,sex,avg(body_weight) body_weight_mean,avg(weight) weight_mean FROM data GROUP BY meet,sex').df()
b=s[s.scope.eq('venue')].merge(a,on=['meet','sex'],suffixes=('_a','_b'))
for c in ['body_weight','weight']:check('SQL '+c+' means',np.max(abs(b[c+'_mean_a']-b[c+'_mean_b'])))
a=con.sql('SELECT meet,sex,avg(bw) body_weight_horse_equal_mean FROM (SELECT meet,sex,horse_id,avg(body_weight) bw FROM data GROUP BY ALL) GROUP BY ALL').df()
b=s[s.scope.eq('venue')].merge(a,on=['meet','sex'],suffixes=('_a','_b'))
check('SQL equal horse body means',np.max(abs(b.body_weight_horse_equal_mean_a-b.body_weight_horse_equal_mean_b)))
assert len(d)==151074 and d.row_key.nunique()==len(d) and d.source_key.nunique()==13928
assert set(d.sex)=={'암','수','거'} and np.isfinite(d.body_weight).all()
method=json.loads((O/'source_and_method.json').read_text())
for name,h in method['inputs_sha256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h
keys=['scope','meet','specification','window','target','reference','part']
for _,g in r[r.scope.ne('weight')].groupby(keys):
    z=g.set_index('contrast');check('joint contrast identity',abs(z.loc['middle_minus_short','difference']-(z.loc['middle_gap','difference']-z.loc['short_gap','difference'])))
z=r[r.supported];critical=t.ppf(.975,np.minimum(z.horse_clusters,z.date_clusters)-1)
check('all confidence arithmetic',np.max(abs(z.upper-z.difference-critical*z.se)))
load=['weight','body_weight','weight_squared','body_squared'];form=['rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap']
ind=[]
for scope in ['time_joint','race_joint']:
 for meet in ['서울','부산']:
  for target,reference in [('암','수'),('거','수'),('암','거')]:
   q=d[d.meet.eq(meet)&d.sex.isin([target,reference])&d.distance_group.ne('long')].copy()
   if scope=='time_joint':fe=['distance_m','year','month','age','moisture','grade'];cols=load+form;out=['finish','seconds_per_1000m','early','late'];spec='full'
   else:
    q=q[q.mixed_actual&q.complete_retained_race&~q.original_nonstandard&~q.sex_condition.eq('암')].copy()
    fe=['source_key'];cols=['age','age_squared']+load+form;out=['win','top3','finish'];spec='race_full'
   cells=q.groupby(fe,dropna=False).sex.nunique();valid=cells[cells==2].index
   q=q.set_index(fe).loc[valid].reset_index();n=len(q)
   codes=pd.factorize(pd.MultiIndex.from_frame(q[fe]))[0];nc=codes.max()+1
   features=[]
   for c in cols:
    x=q[c].astype(float);miss=x.isna()
    if miss.all():continue
    x=x.fillna(x.median());sd=x.std(ddof=0)
    if sd>1e-10:features.append(((x-x.mean())/sd).to_numpy())
    if miss.any():features.append(miss.astype(float).to_numpy())
   z=np.array(features).T;groups=[q.distance_group.eq(a).to_numpy(float) for a in ['short','middle']]
   sex=q.sex.eq(target).to_numpy(float)
   x=np.column_stack([sex*groups[0],sex*groups[1],z*groups[0][:,None],z*groups[1][:,None]])
   y=q[out].to_numpy(float)
   xy=pd.DataFrame(np.column_stack([x,y]));xy['cell']=codes
   dm=(xy.drop(columns='cell')-xy.groupby('cell').transform('mean')).to_numpy()
   xx=dm[:,:x.shape[1]];yy=dm[:,x.shape[1]:]
   beta,_,rank,_=linalg.lstsq(xx,yy,cond=1e-12,lapack_driver='gelsy');res=yy-xx@beta
   # QR pseudoinverse differs from original normal-equation fit.
   pseudo=linalg.pinv(xx,rtol=1e-12);df=n-nc-rank
   expected=r[r.scope.eq(scope)&r.meet.eq(meet)&r.target.eq(target)&r.reference.eq(reference)&r.specification.eq(spec)&r.window.eq('all')]
   assert expected.common_n.eq(n).all() and expected.fe_groups.eq(nc).all()
   for part in out:
    j=out.index(part);mult=100 if part in ['win','top3'] else 1
    for contrast,v0 in [('short_gap',[1,0]),('middle_gap',[0,1]),('middle_minus_short',[-1,1])]:
     v=np.r_[v0,np.zeros(x.shape[1]-2)];score=(v@pseudo)*res[:,j]
     variances=[]
     for ids in [q.horse_id,q.day_key,pd.MultiIndex.from_frame(q[['horse_id','day_key']])]:
      agg=pd.Series(score).groupby(np.asarray(pd.factorize(ids)[0])).sum();ng=len(agg)
      variances.append(float(agg.pow(2).sum()*ng/(ng-1)*(n-1)/df))
     se=np.sqrt(max(variances[0],variances[1],variances[0]+variances[1]-variances[2]))*mult
     b=float(v@beta[:,j])*mult;row=expected[expected.part.eq(part)&expected.contrast.eq(contrast)].iloc[0]
     check(f'{scope}/{meet}/{target}-{reference}/{part}/{contrast} coefficient',abs(b-row.difference),2e-6)
     check(f'{scope}/{meet}/{target}-{reference}/{part}/{contrast} cluster SE',abs(se-row.se),2e-6)
     ind.append(dict(scope=scope,meet=meet,target=target,reference=reference,part=part,contrast=contrast,n=n,difference=b,se=se))
   if target=='암' and reference=='수':
    dummy=sparse.csr_matrix((np.ones(n),(np.arange(n),codes)),shape=(n,nc))
    full=sparse.hstack([sparse.csr_matrix(x),dummy],format='csr')
    fit=lsmr(full,q.finish.to_numpy(),atol=1e-12,btol=1e-12,maxiter=3000)
    check(f'explicit sparse FE {scope}/{meet}',np.max(abs(fit[0][:2]-beta[:2,out.index('finish')])),2e-5)
    assert fit[1] in [1,2],fit[1]
   print(scope,meet,target,reference,'verified',flush=True)
pd.DataFrame(ind).to_csv(O/'independent_model_checks.csv',index=False)
(O/'verification.json').write_text(json.dumps(dict(passed=True,input_hashes_verified=True,duplicates=0,all_three_pairs_checked=True,checked_primary_model_rows=len(ind),explicit_sparse_fe_fits=4,checks=checks,limitations='QR/sparse checks validate numerical reproduction, not biological causality or external validity; sensitivity estimates are pointwise.'),ensure_ascii=False,indent=2)+'\n')
print('PASS',len(checks),'checks')
