"""Independent sparse FE/LU, QR fits and pandas cluster aggregation."""
from pathlib import Path
import gzip,hashlib,json,math
import numpy as np,pandas as pd
from scipy import sparse,linalg
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu
from scipy.stats import t,false_discovery_control
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2];checks=[];cache={};ind=[]
def check(name,err,tol=4e-6):
 err=float(err);assert np.isfinite(err) and err<tol,(name,err,tol);checks.append(dict(check=name,error=err,tolerance=tol))
d=pd.read_parquet(H.parent/'20261007_sex_ability_gap/outputs/population.parquet').merge(pd.read_parquet(H.parent/'20261008_body_weight_change_optimum/outputs/body_features.parquet')[['row_key','past_relative_body','past_body_mean','previous_date']],on='row_key',validate='one_to_one');d['day_key']=d.date.dt.strftime('%Y-%m-%d');d['age_squared']=d.age*d.age;d['finish1000']=d.finish/d.distance_m*1000;d['fade']=d.late-(d.last600-d.late)/2
expected=json.loads((H.parent/'20261008_body_weight_change_optimum/outputs/source_audit.json').read_text())['inputs_sha256'];expected.update(json.loads((O/'source_audit.json').read_text())['inputs_sha256'])
for name,h in expected.items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h,name
assert len(d)==151074 and d.row_key.is_unique and not d.duplicated(['horse_id','date']).any()
check('disjoint segment sum',abs(d.finish-d[['early','middle1','middle2','late']].sum(axis=1)).max());check('last600 identity',abs(d.last600-d.middle2-d.late).max());assert d.loc[d.meet.eq('서울'),'last400'].isna().all()
raw_count=0
for name,g in d.groupby('source_file'):
 with gzip.open(ROOT/name,'rt') as f:items=json.load(f)['response']['body']['items']['item']
 for a in g.itertuples():
  r=items[a.source_item_index];assert str(r['hrNo']).zfill(7)==a.horse_id and str(r['rcDate'])==a.date.strftime('%Y%m%d');assert float(str(r['wgHr']).split('(')[0])==a.body_weight
  finish=float(r['rcTime']);late=finish-float(r['seG1fAccTime']) if a.meet=='서울' else float(r['bu_1fGTime']);last600=finish-float(r['seG3fAccTime']) if a.meet=='서울' else float(r['bu_3fGTime']);assert max(abs(finish-a.finish),abs(late-a.late),abs(last600-a.last600))<1e-9;raw_count+=1
ledger=pd.read_parquet(H.parent/'20261007_sex_ability_gap/outputs/selection_ledger.parquet').sort_values(['horse_id','date']);past=ledger.groupby('horse_id').body_weight.transform(lambda s:s.shift().rolling(5,min_periods=3).mean());lookup=dict(zip(ledger.row_key,past));actual=d.row_key.map(lookup);assert actual.isna().equals(d.past_body_mean.isna());check('past five excludes current/future',abs(actual-d.past_body_mean).dropna().max());check('past relative identity',abs(d.body_weight-actual-d.past_relative_body).dropna().max());assert (d.previous_date.dropna()<d.loc[d.previous_date.notna(),'date']).all()
diag=pd.read_csv(O/'diagnostics.csv');models=pd.read_csv(O/'models.csv');contr=pd.read_csv(O/'contrasts.csv');form=['weight','weight_squared','age','age_squared','rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap'];outcomes=['finish1000','late','last600','fade']
def independent_cov(q,x,y,rank):
 b,_,xr,_=linalg.lstsq(x,y,cond=1e-10,lapack_driver='gelsy');assert xr==x.shape[1];res=y-x@b;score=linalg.pinv(x,rtol=1e-10).T*res[:,None];df=len(q)-rank-xr;vs=[]
 for ids in [q.horse_id,q.day_key,pd.MultiIndex.from_frame(q[['horse_id','day_key']])]:
  sums=pd.DataFrame(score).groupby(pd.factorize(ids)[0]).sum().to_numpy();ng=len(sums);vs.append(sums.T@sums*ng/(ng-1)*(len(q)-1)/df)
 return b,[vs[0],vs[1],vs[0]+vs[1]-vs[2]],df
for key,records in diag.groupby(['window','metric','meet','distance_m']):
 window,metric,meet,dist=key;q=d[d.meet.eq(meet)&d.distance_m.eq(dist)].copy()
 if window=='complete_2024_2025':q=q[q.year.isin([2024,2025])]
 elif window=='age4plus':q=q[q.age.ge(4)]
 col='body_weight' if metric=='absolute' else 'past_relative_body';q=q[q[col].notna()]
 while True:
  keep=q.groupby('source_key').row_key.transform('size').ge(2)
  if metric!='absolute':keep &=q.groupby('horse_id').row_key.transform('size').ge(2)
  if keep.all():break
  q=q[keep]
 q=q.reset_index(drop=True);n=len(q);assert records.n.eq(n).all()
 for name in ['early','middle1','middle2']:q[name+'_squared']=q[name]*q[name]
 names=[];z=[]
 for name in form+['early','early_squared','middle1','middle1_squared','middle2','middle2_squared']:
  s=q[name].astype(float);miss=s.isna()
  if miss.all():continue
  s=s.fillna(s.median());sd=s.std(ddof=0)
  if sd>1e-10:z.append(((s-s.mean())/sd).to_numpy());names.append(name)
  if miss.any():z.append(miss.to_numpy(float));names.append(name+'_missing')
 for sex in ['암','거']:z.append(q.sex.eq(sex).to_numpy(float));names.append('sex_'+sex)
 u=(q[col].to_numpy()-(480 if metric=='absolute' else 0))/10;xy=np.column_stack([u,u*u]+[q[name].to_numpy() for name in outcomes]+z);rc=pd.factorize(q.source_key)[0];nr=rc.max()+1;zfe=sparse.csr_matrix((np.ones(n),(np.arange(n),rc)),shape=(n,nr))
 if metric!='absolute':
  hc=pd.factorize(q.horse_id)[0];nh=hc.max()+1;adj=sparse.csr_matrix((np.ones(2*n),(np.r_[hc,rc+nh],np.r_[rc+nh,hc])),shape=(nh+nr,nh+nr));nc,lab=connected_components(adj,directed=False);_,first=np.unique(lab[:nh],return_index=True);keep=np.ones(nh,bool);keep[first]=False;mapping=np.cumsum(keep)-1;mask=keep[hc];zfe=sparse.hstack([zfe,sparse.csr_matrix((np.ones(mask.sum()),(np.arange(n)[mask],mapping[hc[mask]])),shape=(n,keep.sum()))],format='csr')
 assert records.fe_rank.eq(zfe.shape[1]).all();lu=splu((zfe.T@zfe).tocsc());dm=xy-zfe@lu.solve(zfe.T@xy);check('sparse projection orthogonality',abs(zfe.T@dm).max(),2e-6)
 for a in records.itertuples():
  ix=[names.index(name) for name in a.nuisance_names.split('|')];zz=dm[:,6+np.array(ix)];j=outcomes.index(a.outcome);xy=dm[:,[0,1,2+j]];coef,_,rank,_=linalg.lstsq(zz,xy,cond=1e-10,lapack_driver='gelsy');r=xy-zz@coef;assert rank==a.nuisance_rank;b,_,_,_=linalg.lstsq(r[:,:2],r[:,2],cond=1e-10,lapack_driver='gelsy');target=models[(models.window==window)&(models.metric==metric)&(models.meet==meet)&(models.distance_m==dist)&(models.specification==a.specification)&(models.outcome==a.outcome)].iloc[0];err=max(abs(b[0]-target.beta_linear),abs(b[1]-target.beta_quadratic));check('independent distance beta',err);ind.append(dict(window=window,metric=metric,meet=meet,distance_m=dist,specification=a.specification,outcome=a.outcome,n=n,max_beta_error=err));cache.setdefault((window,metric,a.specification,a.outcome),[]).append((q,r[:,:2],r[:,2],zfe.shape[1]+rank))
 print('verified',window,metric,meet,dist,flush=True)
joint_count=0;group_count=0
for (window,metric,spec,outcome),parts in cache.items():
 for meet in ['서울','부산','전체']:
  pp=[p for p in parts if meet=='전체' or p[0].meet.iloc[0]==meet];q=pd.concat([p[0] for p in pp],ignore_index=True);x=np.vstack([p[1] for p in pp]);y=np.concatenate([p[2] for p in pp]);rank=sum(p[3] for p in pp);long=q.distance_m.ge(1600).to_numpy();xx=np.column_stack([x*(~long)[:,None],x*long[:,None]]);b,vs,df=independent_cov(q,xx,y,rank);cc=contr[(contr.window==window)&(contr.metric==metric)&(contr.specification==spec)&(contr.outcome==outcome)&(contr.meet==meet)&contr.scope.eq('joint')]
  for a in cc.itertuples():
   z=(a.target_kg-a.reference_kg)/10;v0=np.array([z,z*z]);v={'short':np.r_[v0,0,0],'long':np.r_[0,0,v0],'short_minus_long':np.r_[v0,-v0],'long_minus_short':np.r_[-v0,v0]}[a.comparison];err=math.sqrt(max(0,max(float(v@c@v) for c in vs)));crit=t.ppf(.975,min(q.horse_id.nunique(),q.day_key.nunique())-1);check('joint contrast estimate',abs(v@b-a.estimate));check('joint shared-horse/date SE',abs(err-a.se));check('joint CI',abs(a.upper-a.estimate-crit*err))
  joint_count+=1
  for group,mask in [('short',~long),('long',long)]:
   rr=sum(p[3] for p in pp if (p[0].distance_m.iloc[0]>=1600)==(group=='long'));bb,vv,dd=independent_cov(q[mask],x[mask],y[mask],rr);target=models[(models.window==window)&(models.metric==metric)&(models.specification==spec)&(models.outcome==outcome)&(models.meet==meet)&models.scope.eq(group)].iloc[0];check('group pooled beta',max(abs(bb[0]-target.beta_linear),abs(bb[1]-target.beta_quadratic)));assert dd==target.residual_df and mask.sum()==target.n;group_count+=1
ix=contr.primary&contr.meet.eq('전체');assert ix.sum()==8;check('eight test BH',abs(false_discovery_control(contr.loc[ix,'p'].to_numpy())-contr.loc[ix,'bh_q'].to_numpy()).max())
pd.DataFrame(ind).to_csv(O/'independent_checks.csv',index=False);(O/'verification.json').write_text(json.dumps(dict(passed=True,raw_body_and_finish_section_checks=raw_count,input_hashes_verified=len(expected),independent_distance_models=len(ind),independent_group_models=group_count,independent_joint_models=joint_count,method='raw cumulative last200/600 extraction; separate sparse FE graph/LU; QR exposure/nuisance regression; pandas cluster sums; joint distance contrasts and BH',checks=checks,causal=False),ensure_ascii=False,indent=2)+'\n');print('PASS',len(ind),group_count,joint_count,len(checks))
