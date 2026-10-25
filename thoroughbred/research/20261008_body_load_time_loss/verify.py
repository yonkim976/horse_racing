"""Independent sparse FE projection with one gauge removed per component and QR fits."""
from pathlib import Path
import hashlib,json
import numpy as np,pandas as pd,duckdb
from scipy import sparse,linalg
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu
from scipy.stats import t,false_discovery_control
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2]
d=pd.read_parquet(H.parent/'20261007_sex_ability_gap/outputs/population.parquet');d['rank']=pd.to_numeric(d.rank_raw);d['age_squared']=d.age**2
r=pd.read_csv(O/'load_contrasts.csv');meta=pd.read_csv(O/'model_diagnostics.csv');checks=[]
def check(name,error,tol=1e-7):
 error=float(error);assert np.isfinite(error) and error<tol,(name,error,tol);checks.append(dict(check=name,error=error,tolerance=tol))
assert len(d)==151074 and d.row_key.nunique()==len(d) and d.source_key.nunique()==13928
assert np.isfinite(d[['body_weight','weight','finish']]).all().all()
check('independent segment sum',abs(d.finish-d[['early','middle1','middle2','late']].sum(axis=1)).max(),.0011)
audit=json.loads((O/'source_and_method.json').read_text())
for name,h in audit['inputs_sha256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h
old=pd.read_parquet(H.parent/'20261005_relative_load1200/outputs/weight_population.parquet');j=d[d.distance_m.eq(1200)].merge(old[['row_key','body_kg','weight']],on='row_key',suffixes=('_new','_old'),validate='one_to_one');assert len(j)==41623
check('prior1200 carried weight',abs(j.weight_new-j.weight_old).max());check('prior1200 body weight',abs(j.body_weight-j.body_kg).max())
con=duckdb.connect();con.register('d',d)
counts=con.sql('SELECT meet,distance_m,count(*) n,count(distinct source_key) races FROM d GROUP BY meet,distance_m').df();saved=pd.read_csv(O/'distance_eligibility.csv');j=counts.merge(saved,on=['meet','distance_m'],suffixes=('_a','_b'))
for c in ['n','races']:check('SQL '+c,abs(j[c+'_a']-j[c+'_b']).max())
assert r[r.supported].lower.notna().all() and r[~r.supported].lower.isna().all()
z=r[r.supported];critical=t.ppf(.975,np.minimum(z.horses,z.dates)-1);check('all CI arithmetic',abs(z.upper-z.difference_seconds-critical*z.se_seconds).max())
z=r[r.modifier_p.notna()];check('independent modifier BH q',abs(false_discovery_control(z.modifier_p.to_numpy())-z.modifier_bh_q).max())
chosen=meta[(meta.window.eq('all')&meta.specification.eq('horse_race_full'))|meta.distance_m.eq(1200)]
form=['rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap'];ind=[]
for row in chosen.itertuples():
 q=d[d.meet.eq(row.meet)&d.distance_m.eq(row.distance_m)].copy()
 if row.window=='complete_2024_2025':q=q[q.year.isin([2024,2025])]
 if row.window=='top5_selected':q=q[q['rank'].le(5)]
 two=row.specification.startswith('horse_race')
 if two:
  while True:
   keep=q.groupby('horse_id').horse_id.transform('size').gt(1)&q.groupby('source_key').source_key.transform('size').gt(1)
   if keep.all():break
   q=q.loc[keep].copy()
 q=q.reset_index(drop=True);assert len(q)==row.n
 w=q.weight.to_numpy()-54;b=(q.body_weight.to_numpy()-480)/50;xx=[w,w*w,b,b*b,w*b]
 if row.specification!='raw':
  q['f']=q.sex.eq('암').astype(float);q['g']=q.sex.eq('거').astype(float)
  for col in ['f','g','age','age_squared']+[x for x in form if not(row.specification.endswith('no_rating') and x.startswith('rating'))]:
   a=q[col].astype(float);missing=a.isna()
   if missing.all():continue
   a=a.fillna(a.median());sd=a.std(ddof=0)
   if sd>1e-10:xx.append(((a-a.mean())/sd).to_numpy())
   if missing.any():xx.append(missing.astype(float).to_numpy())
 else:xx.append(np.ones(len(q)))
 x=np.array(xx).T;y=q[['finish','early','late']].to_numpy(float);xy=np.column_stack([x,y]);n=len(q)
 if row.specification!='raw':
  rc=pd.factorize(q.source_key)[0];nr=rc.max()+1;zrace=sparse.csr_matrix((np.ones(n),(np.arange(n),rc)),shape=(n,nr))
  if two:
   hc=pd.factorize(q.horse_id)[0];nh=hc.max()+1;adj=sparse.csr_matrix((np.ones(2*n),(np.r_[hc,rc+nh],np.r_[rc+nh,hc])),shape=(nh+nr,nh+nr));nc,labels=connected_components(adj,directed=False)
   _,first=np.unique(labels[:nh],return_index=True);keep=np.ones(nh,bool);keep[first]=False;mapping=np.cumsum(keep)-1;mask=keep[hc]
   zhorse=sparse.csr_matrix((np.ones(mask.sum()),(np.arange(n)[mask],mapping[hc[mask]])),shape=(n,int(keep.sum())));zfe=sparse.hstack([zrace,zhorse],format='csr')
  else:zfe=zrace
  assert zfe.shape[1]==row.fe_rank
  lu=splu((zfe.T@zfe).tocsc());dm=xy-zfe@lu.solve(zfe.T@xy)
  check('independent sparse FE orthogonality',abs(zfe.T@dm).max(),2e-7)
 else:dm=xy
 xd=dm[:,:x.shape[1]];yd=dm[:,x.shape[1]:];beta,_,rank,_=linalg.lstsq(xd,yd,cond=1e-10,lapack_driver='gelsy');res=yd-xd@beta;pseudo=linalg.pinv(xd,rtol=1e-10);df=n-row.fe_rank-rank;assert df==row.residual_df,(row.meet,row.distance_m,df,row.residual_df)
 expected=r[r.meet.eq(row.meet)&r.distance_m.eq(row.distance_m)&r.window.eq(row.window)&r.specification.eq(row.specification)]
 if row.distance_m!=1200 or row.window!='all' or row.specification!='horse_race_full':expected=expected[expected.to_load.eq(55)]
 for a in expected.itertuples():
  v=np.zeros(x.shape[1]);dw=a.to_load-a.from_load
  if a.contrast=='light_minus_heavy':v[4]=-1.2
  else:v[0]=dw;v[1]=dw*dw;v[4]=dw*(a.body_kg-480)/50
  j=['finish','early','late'].index(a.part);bhat=float(v@beta[:,j]);score=(v@pseudo)*res[:,j];variances=[]
  for ids in [q.horse_id,q.day_key,pd.MultiIndex.from_frame(q[['horse_id','day_key']])]:
   agg=pd.Series(score).groupby(pd.factorize(ids)[0]).sum();ng=len(agg);variances.append(float(agg.pow(2).sum()*ng/(ng-1)*(n-1)/df))
  se=np.sqrt(max(variances[0],variances[1],variances[0]+variances[1]-variances[2]))
  check(f'{row.meet}/{row.distance_m}/{row.window}/{row.specification}/{a.part}/{a.contrast}/{a.body_kg}/{a.to_load} coefficient',abs(bhat-a.difference_seconds),3e-6)
  check('independent cluster SE',abs(se-a.se_seconds),3e-6)
  points=json.loads(a.support_points);support=True
  for p in points:
   near=q[q.body_weight.between(p['body']-15,p['body']+15)&q.weight.between(p['load']-.5,p['load']+.5)]
   assert len(near)==p['n'] and near.horse_id.nunique()==p['horses'] and near.day_key.nunique()==p['dates'];support &=len(near)>=100 and near.horse_id.nunique()>=30 and near.day_key.nunique()>=20
  assert support==a.supported
  ind.append(dict(meet=row.meet,distance_m=row.distance_m,window=row.window,specification=row.specification,part=a.part,contrast=a.contrast,body_kg=a.body_kg,to_load=a.to_load,difference_seconds=bhat,se_seconds=se,n=n))
 print(row.meet,row.distance_m,row.window,row.specification,'verified',flush=True)
pd.DataFrame(ind).to_csv(O/'independent_model_checks.csv',index=False)
(O/'verification.json').write_text(json.dumps(dict(passed=True,input_n=len(d),source_hashes_verified=len(audit['inputs_sha256']),prior1200_source_rows=41623,independent_model_count=len(chosen),independent_contrast_rows=len(ind),independent_method='sparse FE graph with one horse gauge per connected component, LU projection, QR regression, pandas cluster sums',checks=checks,limitation='Numerical verification cannot establish exogenous weight assignment or causal load loss.'),ensure_ascii=False,indent=2)+'\n');print('PASS',len(checks),'checks',len(ind),'contrasts')
