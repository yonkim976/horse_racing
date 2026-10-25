"""Independent sparse FE/QR check, pooled horse-date covariance and frozen-time diagnostics."""
from pathlib import Path
import hashlib,json,math
import numpy as np,pandas as pd
from scipy import sparse,linalg
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu
from scipy.stats import t
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2]
d=pd.read_parquet(H.parent/'20261007_sex_ability_gap/outputs/population.parquet');d['age_squared']=d.age**2;d['day_key']=pd.to_datetime(d.date).dt.strftime('%Y-%m-%d')
r=pd.read_csv(O/'coefficients.csv');m=pd.read_csv(O/'diagnostics.csv');checks=[];verified=[];cache={}
def check(name,error,tol=3e-6):
 error=float(error);assert np.isfinite(error) and error<tol,(name,error,tol);checks.append(dict(check=name,error=error,tolerance=tol))
a=json.loads((O/'source_and_method.json').read_text());assert hashlib.sha256((ROOT/a['input_path']).read_bytes()).hexdigest()==a['input_sha256']
assert len(d)==151074 and d.row_key.is_unique and d.source_key.nunique()==13928
assert not a['sex_features'] and not a['body_features_main'] and not any('sex' in x for x in a['nuisance'])
check('finish equals disjoint segments',abs(d.finish-d[['early','middle1','middle2','late']].sum(axis=1)).max(),.0011)
check('all interval arithmetic',abs(r.upper-r.coefficient-t.ppf(.975,np.minimum(r.horses,r.dates)-1)*r.se).max())
chosen=m[m.specification.eq('main')|m.distance_m.eq(1200)]
for row in chosen.itertuples():
 q=d[d.meet.eq(row.meet)&d.distance_m.eq(row.distance_m)].copy()
 if row.window=='complete_2024_2025':q=q[q.year.isin([2024,2025])]
 elif row.window.startswith('train_'):q=q[q.year.lt(int(row.window.split('_')[2]))&q.month.le(8)]
 elif row.window.startswith('test_'):q=q[q.year.eq(int(row.window.split('_')[1]))&q.month.le(8)]
 while True:
  keep=q.groupby('horse_id').horse_id.transform('size').gt(1)&q.groupby('source_key').source_key.transform('size').gt(1)
  if keep.all():break
  q=q[keep].copy()
 q=q.reset_index(drop=True);n=len(q);assert n==row.n
 cols=[] if row.specification=='fe_only' else ['age_squared','rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap']
 if row.specification=='body_direct':cols+=['body_weight','body_squared']
 zz=[]
 for col in cols:
  z=q[col].astype(float);miss=z.isna()
  if miss.all():continue
  z=z.fillna(z.median());sd=z.std(ddof=0)
  if sd>1e-10:zz.append(((z-z.mean())/sd).to_numpy())
  if miss.any():zz.append(miss.astype(float).to_numpy())
 xy=np.column_stack([q.weight.to_numpy()-54,q.finish.to_numpy()*1000/row.distance_m]+zz)
 rc=pd.factorize(q.source_key)[0];hc=pd.factorize(q.horse_id)[0];nr=rc.max()+1;nh=hc.max()+1
 adj=sparse.csr_matrix((np.ones(2*n),(np.r_[hc,rc+nh],np.r_[rc+nh,hc])),shape=(nh+nr,nh+nr));nc,lab=connected_components(adj,directed=False)
 _,first=np.unique(lab[:nh],return_index=True);keep=np.ones(nh,bool);keep[first]=False;mapping=np.cumsum(keep)-1;mask=keep[hc]
 zf=sparse.hstack([sparse.csr_matrix((np.ones(n),(np.arange(n),rc)),shape=(n,nr)),sparse.csr_matrix((np.ones(mask.sum()),(np.arange(n)[mask],mapping[hc[mask]])),shape=(n,int(keep.sum())))],format='csr')
 assert zf.shape[1]==row.fe_rank and nc==row.fe_components
 lu=splu((zf.T@zf).tocsc());dm=xy-zf@lu.solve(zf.T@xy);check('sparse FE orthogonality',abs(zf.T@dm).max(),3e-7)
 if zz:
  coef,_,rank,_=linalg.lstsq(dm[:,2:],dm[:,:2],cond=1e-10,lapack_driver='gelsy');res=dm[:,:2]-dm[:,2:]@coef
 else:rank=0;res=dm[:,:2]
 assert rank==row.nuisance_rank
 key=(row.meet,row.window,row.specification);cache.setdefault(key,[]).append((q,res,row.fe_rank+rank))
 b=float(res[:,0]@res[:,1]/(res[:,0]@res[:,0]));expected=r[(r.meet==row.meet)&(r.window==row.window)&(r.specification==row.specification)&(r.distance_m==row.distance_m)].iloc[0]
 check('independent distance coefficient',abs(b-expected.coefficient));verified.append(dict(meet=row.meet,distance_m=row.distance_m,window=row.window,specification=row.specification,coefficient=b,n=n))
for window in r.window.unique():
 parts=[p for (meet,ww,spec),pp in list(cache.items()) if ww==window and spec=='main' for p in pp]
 cache[('전체',window,'main')]=parts
for (meet,window,spec),parts in cache.items():
 if spec!='main':continue
 q=pd.concat([p[0] for p in parts],ignore_index=True);res=np.vstack([p[1] for p in parts]);rank=sum(p[2] for p in parts);w,y=res.T;den=w@w;b=float(w@y/den);score=w*(y-b*w)/den;df=len(q)-rank-1;vv=[]
 for ids in [q.horse_id,q.day_key,pd.MultiIndex.from_frame(q[['horse_id','day_key']])]:
  agg=pd.Series(score).groupby(pd.factorize(ids)[0]).sum();ng=len(agg);vv.append(float(agg.pow(2).sum()*ng/(ng-1)*(len(q)-1)/df))
 se=math.sqrt(max(vv[0],vv[1],vv[0]+vv[1]-vv[2]));expected=r[(r.meet==meet)&(r.window==window)&(r.specification==spec)&(r.distance_m==0)].iloc[0]
 assert expected.residual_df==df and expected.n==len(q)
 check('independent pooled coefficient',abs(b-expected.coefficient));check('cross-distance horse/date SE',abs(se-expected.se))
 verified.append(dict(meet=meet,distance_m=0,window=window,specification=spec,coefficient=b,se=se,n=len(q)))
 if window.startswith('test_'):
  year=int(window.split('_')[1]);tr=r[(r.meet==meet)&(r.distance_m==0)&r.window.eq(f'train_before_{year}_jan_aug')&r.specification.eq('main')].iloc[0]
  v=pd.read_csv(O/'temporal_validation.csv');v=v[(v.meet==meet)&(v.test_year==year)].iloc[0]
  assert pd.Timestamp(v.train_end)<pd.Timestamp(v.test_start)
  check('frozen train coefficient',abs(tr.coefficient-v.train_coefficient));check('heldout remaining slope',abs(b-tr.coefficient-v.remaining_slope));check('heldout baseline RMSE',abs(math.sqrt(np.mean(y*y))-v.baseline_rmse));check('heldout corrected RMSE',abs(math.sqrt(np.mean((y-tr.coefficient*w)**2))-v.corrected_rmse));check('heldout corrected MAE',abs(np.mean(abs(y-tr.coefficient*w))-v.corrected_mae))
c=pd.read_csv(O/'candidates.csv');lookup=pd.read_csv(O/'correction_lookup.csv')
for a in c.itertuples():
 ok=a.full_lower>0 and a.recent_lower>0;assert ok==a.positive_full_and_recent_ci
 val=math.floor((min(a.full_coefficient,a.recent_coefficient)*.5+1e-12)/.005)*.005 if ok else 0
 check('candidate policy',abs(val-a.conservative_candidate));z=lookup[lookup.meet.eq(a.meet)]
 check('54kg correction formula',abs(z.time_to_add_for_54kg+val*(z.carried_kg-54)*z.distance_m/1000).max());assert (z[z.carried_kg.eq(54)].time_to_add_for_54kg==0).all()
pd.DataFrame(verified).to_csv(O/'independent_checks.csv',index=False)
(O/'verification.json').write_text(json.dumps(dict(passed=True,independent_distance_models=len(chosen),independent_pooled_models=sum(x['distance_m']==0 for x in verified),independent_method='Sparse race/horse design with one horse omitted per graph component; LU orthogonal projection, QR nuisance fits and pandas horse/date/intersection cluster sums including cross-distance covariance',checks=checks,causality_established=False,forecast_validation=False),ensure_ascii=False,indent=2)+'\n');print('PASS',len(chosen),'distance models',len(checks),'checks',flush=True)
