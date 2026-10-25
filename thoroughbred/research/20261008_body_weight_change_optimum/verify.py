"""Independent raw extraction, sparse FE projection, QR regression and cluster sums."""
from pathlib import Path
import gzip,hashlib,json,re,math
import numpy as np,pandas as pd
from scipy import sparse,linalg
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu
from scipy.stats import t,false_discovery_control
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2]
d=pd.read_parquet(H.parent/'20261007_sex_ability_gap/outputs/population.parquet');f=pd.read_parquet(O/'body_features.parquet');d=d.merge(f,on='row_key',validate='one_to_one');d['age_squared']=d.age**2;d['day_key']=d.date.dt.strftime('%Y-%m-%d');checks=[];ind=[];cache={}
def check(name,error,tol=4e-6):
 error=float(error);assert np.isfinite(error) and error<tol,(name,error,tol);checks.append(dict(check=name,error=error,tolerance=tol))
audit=json.loads((O/'source_audit.json').read_text());assert len(d)==151074 and d.row_key.is_unique
for name,expected in audit['inputs_sha256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==expected,name
raw_count=0
for name,g in d.groupby('source_file'):
 with gzip.open(ROOT/name,'rt') as handle:items=json.load(handle)['response']['body']['items']['item']
 for a in g.itertuples():
  row=items[a.source_item_index];weight,change=str(row['wgHr']).split('(');change=change.rstrip(')').strip();actual=float(change) if change else np.nan
  assert str(row['hrNo']).zfill(7)==a.horse_id and int(row['rcDate'])==int(a.date.strftime('%Y%m%d'))
  assert float(weight)==a.body_weight and ((np.isnan(actual) and np.isnan(a.raw_reported_change)) or actual==a.raw_reported_change);raw_count+=1
check('usual mean independently grouped',abs(d.usual_body-d.groupby('horse_id').body_weight.transform('mean')).max());check('relative-body identity',abs(d.relative_body-d.body_weight+d.usual_body).max());check('segment identity',abs(d.finish-d[['early','middle1','middle2','late']].sum(axis=1)).max(),.0011)
ledger=pd.read_parquet(H.parent/'20261007_sex_ability_gap/outputs/selection_ledger.parquet').sort_values(['horse_id','date']);lag=ledger.groupby('horse_id').body_weight.shift();lookup=dict(zip(ledger.row_key,lag));check('independent previous body',abs(d.previous_body_weight-d.row_key.map(lookup)).dropna().max())
assert (d.previous_date.dropna()<d.loc[d.previous_date.notna(),'date']).all()
zero=d.raw_reported_change.isna()&d.observed_change.eq(0)&d.previous_date.eq(d.last_history_date);assert int(zero.sum())==audit['verified_zero_changes'];assert d.loc[zero,'body_change'].eq(0).all();assert d.loc[d.raw_reported_change.isna()&~zero,'body_change'].isna().all()
past=ledger.groupby('horse_id').body_weight.transform(lambda s:s.shift(1).rolling(5,min_periods=3).mean());past_lookup=dict(zip(ledger.row_key,past));check('strictly prior rolling body mean',abs(d.past_body_mean-d.row_key.map(past_lookup)).dropna().max())
m=pd.read_csv(O/'diagnostics.csv');models=pd.read_csv(O/'models.csv');terms=pd.read_csv(O/'terms.csv');contrasts=pd.read_csv(O/'contrasts.csv')
chosen=m[m.specification.eq('main')|m.distance_m.eq(1200)]
form=['weight','weight_squared','age_squared','rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap'];labels=['≤−15','−14~−6','−5~−1','0','+1~+5','+6~+14','≥+15']
for a in chosen.itertuples():
 q=d[d.meet.eq(a.meet)&d.distance_m.eq(a.distance_m)].copy()
 if a.window=='complete_2024_2025':q=q[q.year.isin([2024,2025])]
 elif a.window=='age4plus':q=q[q.age.ge(4)]
 elif a.window=='exclude_one_history_conflict':q=q[~(q.previous_date.eq(q.last_history_date)&q.body_change.notna()&q.observed_change.ne(q.body_change))]
 col={'change':'body_change','absolute':'body_weight','relative':'relative_body','past_relative':'past_relative_body','change_bins':'body_change'}[a.metric];q=q[q[col].notna()]
 while True:
  keep=q.groupby('horse_id').horse_id.transform('size').ge(2)&q.groupby('source_key').source_key.transform('size').ge(2)
  if keep.all():break
  q=q[keep].copy()
 q=q.reset_index(drop=True);n=len(q);assert n==a.n
 if a.metric=='change_bins':
  q['change_bin']=pd.cut(q.body_change,[-np.inf,-15,-6,-1,0,5,14,np.inf],labels=labels);xx=[q.change_bin.eq(band).to_numpy(float) for band in labels if band!='0']
 else:
  xx0=(q[col].to_numpy()-(480 if a.metric=='absolute' else 0))/10;xx=[xx0,xx0**2]
 k=len(xx);zz=[]
 for name in ([] if a.specification=='fe_only' else form):
  s=q[name].astype(float);miss=s.isna()
  if miss.all():continue
  s=s.fillna(s.median());sd=s.std(ddof=0)
  if sd>1e-10:zz.append(((s-s.mean())/sd).to_numpy())
  if miss.any():zz.append(miss.astype(float).to_numpy())
 xy=np.column_stack(xx+[q.finish.to_numpy()*1000/a.distance_m]+zz)
 hc=pd.factorize(q.horse_id)[0];rc=pd.factorize(q.source_key)[0];nh=hc.max()+1;nr=rc.max()+1
 adj=sparse.csr_matrix((np.ones(2*n),(np.r_[hc,rc+nh],np.r_[rc+nh,hc])),shape=(nh+nr,nh+nr));nc,lab=connected_components(adj,directed=False);_,first=np.unique(lab[:nh],return_index=True);keep=np.ones(nh,bool);keep[first]=False;mapping=np.cumsum(keep)-1;mask=keep[hc]
 zfe=sparse.hstack([sparse.csr_matrix((np.ones(n),(np.arange(n),rc)),shape=(n,nr)),sparse.csr_matrix((np.ones(mask.sum()),(np.arange(n)[mask],mapping[hc[mask]])),shape=(n,int(keep.sum())))],format='csr');assert zfe.shape[1]==a.fe_rank and nc==a.fe_components
 lu=splu((zfe.T@zfe).tocsc());dm=xy-zfe@lu.solve(zfe.T@xy);check('independent FE orthogonality',abs(zfe.T@dm).max(),2e-6)
 if zz:
  beta,_,rank,_=linalg.lstsq(dm[:,k+1:],dm[:,:k+1],cond=1e-10,lapack_driver='gelsy');r=dm[:,:k+1]-dm[:,k+1:]@beta
 else:rank=0;r=dm[:,:k+1]
 assert rank==a.nuisance_rank
 cache.setdefault((a.meet,a.window,a.specification,a.metric),[]).append((q,r[:,:k],r[:,k],a.fe_rank+rank))
 beta,_,_,_=linalg.lstsq(r[:,:k],r[:,k],cond=1e-10,lapack_driver='gelsy');expected=terms[(terms.meet==a.meet)&(terms.window==a.window)&(terms.specification==a.specification)&(terms.metric==a.metric)&(terms.distance_m==a.distance_m)].sort_values('term')
 check('independent distance coefficients',abs(beta-expected.coefficient.to_numpy()).max());ind.append(dict(meet=a.meet,distance_m=a.distance_m,window=a.window,specification=a.specification,metric=a.metric,n=n,max_coefficient_error=float(abs(beta-expected.coefficient.to_numpy()).max())))
keys=list(cache)
for window,spec,metric in sorted(set((w,s,t) for meet,w,s,t in keys if s=='main')):cache[('전체',window,spec,metric)]=[p for key in keys if key[1:]==(window,spec,metric) for p in cache[key]]
pool_count=0
for (meet,window,spec,metric),pp in cache.items():
 if spec!='main':continue
 q=pd.concat([p[0] for p in pp],ignore_index=True);x=np.vstack([p[1] for p in pp]);y=np.concatenate([p[2] for p in pp]);rank=sum(p[3] for p in pp);k=x.shape[1];n=len(q)
 beta,_,xr,_=linalg.lstsq(x,y,cond=1e-10,lapack_driver='gelsy');pseudo=linalg.pinv(x,rtol=1e-10);res=y-x@beta;df=n-rank-xr;assert xr==k;score=pseudo.T*res[:,None];cov=[]
 for ids in [q.horse_id,q.day_key,pd.MultiIndex.from_frame(q[['horse_id','day_key']])]:
  agg=pd.DataFrame(score).groupby(pd.factorize(ids)[0]).sum().to_numpy();ng=len(agg);cov.append(agg.T@agg*ng/(ng-1)*(n-1)/df)
 cov=[cov[0],cov[1],cov[0]+cov[1]-cov[2]];crit=t.ppf(.975,min(q.horse_id.nunique(),q.day_key.nunique())-1)
 expected=terms[(terms.meet==meet)&terms.distance_m.eq(0)&terms.window.eq(window)&terms.specification.eq(spec)&terms.metric.eq(metric)].sort_values('term');assert len(expected)==k
 check('independent pooled coefficients',abs(beta-expected.coefficient.to_numpy()).max())
 for j,a in enumerate(expected.itertuples()):
  vv=np.eye(k)[j];err=math.sqrt(max(float(vv@c@vv) for c in cov));check('cross-distance clustered SE',abs(err-a.se))
 target=models[(models.meet==meet)&models.distance_m.eq(0)&models.window.eq(window)&models.specification.eq(spec)&models.metric.eq(metric)].iloc[0];assert target.residual_df==df and target.n==n
 if metric!='change_bins' and beta[1]>0:check('pooled U vertex',abs((480 if metric=='absolute' else 0)-10*beta[0]/(2*beta[1])-target.vertex_kg),.001)
 cc=contrasts[(contrasts.meet==meet)&contrasts.distance_m.eq(0)&contrasts.window.eq(window)&contrasts.specification.eq(spec)&contrasts.metric.eq(metric)]
 for a in cc.itertuples():
  if metric=='change_bins':vv=np.eye(k)[[z for z in labels if z!='0'].index(a.target_kg)]
  else:z=(float(a.target_kg)-float(a.reference_kg))/10;vv=np.array([z,z*z])
  err=math.sqrt(max(float(vv@c@vv) for c in cov));check('pooled contrast',abs(vv@beta-a.difference_per1000m));check('pooled contrast SE',abs(err-a.se));check('pooled CI',abs(a.upper-a.difference_per1000m-crit*err))
 ind.append(dict(meet=meet,distance_m=0,window=window,specification=spec,metric=metric,n=n,max_coefficient_error=float(abs(beta-expected.coefficient.to_numpy()).max())));pool_count+=1
for metric in ['change','absolute','relative','past_relative']:
 q=models[models.metric.eq(metric)&models.window.eq('all')&models.specification.eq('main')&models.distance_m.gt(0)];p=2*t.sf(abs(q.beta_quadratic/q.quadratic_se),np.minimum(q.horses,q.dates)-1);check('independent curvature BH',abs(false_discovery_control(p)-q.curvature_bh_q.to_numpy()).max())
personal=pd.read_csv(O/'individual_curves.csv');summary=json.loads((O/'individual_summary.json').read_text())
for prefix in ['full','train']:
 q=personal[personal[prefix+'_estimable'].eq(True)];check('individual BH',abs(false_discovery_control(q[prefix+'_curvature_p'].to_numpy())-q[prefix+'_bh_q'].to_numpy()).max())
assert int(personal.full_candidate.fillna(False).sum())==summary['full_candidate_groups'];assert int(personal.repeat_within10kg.eq(True).sum())==summary['repeat_groups']
# Independently reconstruct personal full curves and HC3; include all nominal candidates.
e=pd.read_csv(O/'eligibility.csv');dd=d.merge(e[e.eligible][['meet','distance_m']],on=['meet','distance_m'],validate='many_to_one');means=dd.groupby('source_key').finish.transform('mean');size=dd.groupby('source_key').row_key.transform('size');dd['relative_time']=(dd.finish-means)*size/(size-1)*1000/dd.distance_m
selected=personal[personal.full_estimable.eq(True)].head(20);selected=pd.concat([selected,personal[personal.full_candidate.eq(True)|personal.train_candidate.eq(True)]]).drop_duplicates(['meet','distance_m','horse_id']);n_personal=0
for a in selected.itertuples():
 q=dd[dd.meet.eq(a.meet)&dd.distance_m.eq(a.distance_m)&dd.horse_id.eq(str(a.horse_id).zfill(7))].sort_values('date');b=(q.body_weight.to_numpy()-q.body_weight.mean())/10;xx=[np.ones(len(q)),b,b*b]
 for col,val in [('elapsed',(q.date-q.date.min()).dt.days/365.25),('load',q.weight-54),('rating',q.rating/10),('form',q.prior_finish)]:
  miss=val.isna()
  if miss.all():continue
  val=val.fillna(val.median());sd=val.std(ddof=0)
  if sd>1e-10:xx.append(((val-val.mean())/sd).to_numpy())
  if miss.any():xx.append(miss.to_numpy(float))
 x=np.column_stack(xx);beta,_,rank,_=linalg.lstsq(x,q.relative_time.to_numpy(),cond=1e-10,lapack_driver='gelsy');pinv=linalg.pinv(x,rtol=1e-10);res=q.relative_time.to_numpy()-x@beta;lev=np.einsum('ij,ji->i',x,pinv);hc=pinv*(res/(1-lev))[None,:];err=math.sqrt((hc@hc.T)[2,2]);assert rank==a.full_rank
 check('personal QR linear',abs(beta[1]-a.full_beta_linear));check('personal QR curvature',abs(beta[2]-a.full_beta_quadratic));check('personal independent HC3',abs(err-a.full_quadratic_se));n_personal+=1
pd.DataFrame(ind).to_csv(O/'independent_checks.csv',index=False)
(O/'verification.json').write_text(json.dumps(dict(passed=True,raw_body_and_change_checks=raw_count,input_hashes_verified=len(audit['inputs_sha256']),independent_distance_models=len(chosen),independent_pooled_models=pool_count,independent_individual_models=n_personal,method='independent string split of raw body text; sparse FE graph and LU projection; QR nuisance/exposure regressions; pandas clustered cross-distance covariance; personal QR and HC3',checks=checks,causality_established=False,forecast_validation=False),ensure_ascii=False,indent=2)+'\n');print('PASS',len(chosen),'distance',pool_count,'pooled',n_personal,'personal',len(checks),'numeric checks',flush=True)
