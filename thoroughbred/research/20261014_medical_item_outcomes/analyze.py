"""Within-horse adjusted associations, full follow-up risk sets and joint label adjustment."""
from pathlib import Path
import importlib.util,json,math
import numpy as np,pandas as pd
from scipy import linalg,stats,sparse
from scipy.sparse.linalg import lsqr
from scipy.stats import false_discovery_control

H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2]
spec=importlib.util.spec_from_file_location('prior_fe',H.parent/'20261012_jockey_switch_trainer_intent/analyze.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
LABELS=json.loads((O/'family_definitions.json').read_text())['labels'];FAMS=list(LABELS)
CONTROLS=['elapsed','prev_rank','prev_top3','prev_time','mean5_rank','mean5_top3','mean5_time',
 'prior_age','prior_rating','prior_weight','prior_body_weight','prior_grade','prior_distance',
 'prior_gap','prior_starts','prior_trainer_level','prior_jockey_level','observed_history_days']

def design(g,horizon,variant):
 gap=7 if variant=='episode7' else 14
 names=[];cols=[]
 for state in ['new','ongoing']:
  for fam in FAMS:
   name=state+str(gap)+'_'+fam;names.append(name);cols.append(g[name].to_numpy(float))
 fields=CONTROLS+['missing_diagnosis_week']
 if horizon:
  fields=fields+[x+str(horizon) for x in ['weight_','gate_','distance_change_','grade_change_','jockey_level_','trainer_level_']]
  if variant=='interval_body':fields+=['interval_'+str(horizon),'body_'+str(horizon)]
 for name in fields:
  v=g[name].to_numpy(float);missing=~np.isfinite(v);v=np.where(missing,0,v)
  if name in ['elapsed','prior_gap','prior_starts','observed_history_days'] or name.startswith('interval_'):v=np.log1p(v)
  for suffix,a in [('',v),('_missing',missing.astype(float))]:
   sd=a.std()
   if sd>1e-12:names.append(name+suffix);cols.append(a/sd)
  if name in ['elapsed','prev_rank','mean5_rank','prior_age','prior_rating']:
   a=v*v;sd=a.std()
   if sd>1e-12:names.append(name+'_sq');cols.append(a/sd)
 return names,np.column_stack(cols)

def cluster_codes(g,horizon):
 fields=[['horse_id'],['index_date'],['horse_id','index_date']]
 if horizon:fields+=[['race'+str(horizon)],['horse_id','race'+str(horizon)]]
 return [pd.factorize(pd.MultiIndex.from_frame(g[f]))[0] for f in fields]

def fit(g,targets,period,variant,horizon,mid):
 print('start',mid,period,variant,horizon,'|'.join(targets),flush=True)
 z=g[g[targets].notna().all(axis=1)].reset_index(drop=True)
 names,x=design(z,horizon,variant);y=z[targets].to_numpy(float)
 f1=pd.factorize(z['race'+str(horizon)] if horizon else z.index_week)[0]
 f2=pd.factorize(z.horse_id)[0];a,ferank=old.demean(np.column_stack([x,y]),[f1,f2])
 nc=x.shape[1];keep=a[:,:nc].std(axis=0)>1e-10;retained=np.flatnonzero(keep)
 xx=a[:,:nc][:,keep];yy=a[:,nc:];u,s,vh=linalg.svd(xx,full_matrices=False,check_finite=False)
 rank=int((s>s[0]*1e-10).sum());ur=u[:,:rank];vr=vh[:rank];sr=s[:rank]
 beta=vr.T@((ur.T@yy)/sr[:,None]);res=yy-xx@beta
 df=len(z)-ferank-rank;assert df>0
 inverse=(vr.T/sr)@ur.T
 cc=cluster_codes(z,horizon);counts=[int(v.max())+1 for v in cc]
 dfc=max(1,min([counts[0],counts[1]]+([counts[3]] if horizon else []))-1)
 crit=stats.t.ppf(.975,dfc);out=[];gap=7 if variant=='episode7' else 14
 for j,original in enumerate(retained):
  name=names[original]
  if not name.startswith(('new7_','new14_','ongoing7_','ongoing14_')):continue
  state='new' if name.startswith('new') else 'ongoing';fam=name.split('_',1)[1]
  w=np.zeros(len(retained));w[j]=1
  identified=np.max(np.abs(vr.T@(vr@w)-w))<1e-6
  exposed=z[name].eq(1);neither=z['new'+str(gap)+'_'+fam].eq(0)&z['ongoing'+str(gap)+'_'+fam].eq(0)
  eh=set(z.loc[exposed,'horse_id']);nh=set(z.loc[neither,'horse_id']);within=len(eh&nh)
  supported=int(exposed.sum())>=30 and len(eh)>=20 and within>=20
  for ti,target in enumerate(targets):
   influence=inverse[j]*res[:,ti]*math.sqrt(len(z)/df);vs=[]
   for code,k in zip(cc,counts):
    ss=np.bincount(code,weights=influence);vs.append(float(ss@ss)*k/max(k-1,1))
   var=max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2])
   if horizon:var=max(var,vs[3],vs[0]+vs[3]-vs[4])
   se=math.sqrt(var);b=float(beta[j,ti]);p=float(2*stats.t.sf(abs(b/se),dfc)) if se else 1.
   out.append(dict(model_id=mid,period=period,variant=variant,horizon=horizon,target=target,
    family=fam,label=LABELS[fam],state=state,n=len(z),horses=z.horse_id.nunique(),
    exposed_rows=int(exposed.sum()),exposed_horses=len(eh),within_horses=within,
    identified=identified,supported=supported,estimate=b,se=se,ci_low=b-crit*se,ci_high=b+crit*se,p=p,
    raw_exposed_mean=float(z.loc[exposed,target].mean()),raw_neither_mean=float(z.loc[neither,target].mean())))
 present={(row['state'],row['family'],row['target']) for row in out}
 for state in ['new','ongoing']:
  for fam in FAMS:
   for target in targets:
    if (state,fam,target) not in present:
     out.append(dict(model_id=mid,period=period,variant=variant,horizon=horizon,target=target,
      family=fam,label=LABELS[fam],state=state,n=len(z),horses=z.horse_id.nunique(),
      exposed_rows=int(z[state+str(gap)+'_'+fam].sum()),exposed_horses=0,within_horses=0,
      identified=False,supported=False,estimate=np.nan,se=np.nan,ci_low=np.nan,ci_high=np.nan,p=1.,
      raw_exposed_mean=np.nan,raw_neither_mean=np.nan))
 # Sparse full-design fit is independent of the FE normal projection and dense SVD.
 rows=np.arange(len(z));n1=int(f1.max()+1);n2=int(f2.max()+1)
 fe=sparse.coo_matrix((np.ones(2*len(z)),(np.r_[rows,rows],np.r_[f1,n1+f2])),shape=(len(z),n1+n2)).tocsr()
 full=sparse.hstack([sparse.csr_matrix(x),fe],format='csr');errors=[];normal=[]
 norms=np.sqrt(np.asarray(full.power(2).sum(axis=0)).ravel());norms[norms==0]=1
 scaled=full@sparse.diags(1/norms);coefficient_errors=[]
 for ti in range(len(targets)):
  ys=max(float(y[:,ti].std()),1e-8)
  sol=lsqr(scaled,y[:,ti]/ys,atol=1e-13,btol=1e-13,conlim=1e12,iter_lim=20000)
  fitted=(scaled@sol[0])*ys;model_fit=y[:,ti]-res[:,ti]
  errors.append(float(np.max(np.abs(fitted-model_fit))))
  normal.append(float(np.max(np.abs(full.T@(y[:,ti]-fitted)))))
  independent_beta=sol[0][:len(names)]*ys/norms[:len(names)]
  err=[]
  for row in out:
   if row['target']==targets[ti] and row['identified']:
    col=names.index(row['state']+str(gap)+'_'+row['family'])
    err.append(abs(independent_beta[col]-row['estimate']))
  coefficient_errors.append(max(err,default=0))
  assert sol[1] in [1,2],(mid,sol[1])
  assert errors[-1]<2e-5,(mid,errors[-1])
  assert coefficient_errors[-1]<2e-5,(mid,coefficient_errors[-1])
 diag=dict(model_id=mid,period=period,variant=variant,horizon=horizon,targets='|'.join(targets),
  n=len(z),p=len(names),retained=len(retained),rank=rank,fe_rank=int(ferank),residual_df=int(df),
  max_abs_normal=float(np.max(np.abs(xx.T@res))),independent_fitted_error=max(errors),
  independent_coefficient_error=max(coefficient_errors),
  independent_normal_max=max(normal),cluster_counts=json.dumps(counts))
 (O/'models').mkdir(exist_ok=True)
 np.savez_compressed(O/'models'/f'{mid}.npz',row_ids=z.row_id.to_numpy(),names=np.asarray(names),
  retained=retained,beta=beta,targets=np.asarray(targets),residuals=res)
 print('model',mid,period,variant,horizon,len(z),'verified error',max(errors),flush=True)
 return out,diag

def main():
 d=pd.read_parquet(O/'landmark_rows.parquet');effects=[];diags=[];mid=0
 jobs=[]
 for period,mask in [('2024_2025',d.year.le(2025)),('2024',d.year.eq(2024)),('2025',d.year.eq(2025)),('2026_partial',d.year.eq(2026))]:
  jobs.append((period,'primary',d[mask]))
 jobs += [('2024_2025','episode7',d[d.year.le(2025)]),('2024_2025','interval_body',d[d.year.le(2025)])]
 for period,variant,g in jobs:
  if variant!='interval_body':
   ts=['no_start_30','no_start_60','no_start_90','no_start_180','restricted_wait_180']+['no_top3_at_'+str(h)+'_by180' for h in [1,2,3]]
   res,dg=fit(g,ts,period,variant,0,mid);effects+=res;diags.append(dg);mid+=1
  for h in [1,2,3]:
   for ts in [['top3_'+str(h),'rank_'+str(h)],['time_'+str(h)]]:
    res,dg=fit(g,ts,period,variant,h,mid);effects+=res;diags.append(dg);mid+=1
   pd.DataFrame(effects).to_csv(O/'adjusted_associations.csv',index=False);pd.DataFrame(diags).to_csv(O/'model_diagnostics.csv',index=False)
 e=pd.DataFrame(effects);e['q_joint']=np.nan;e['q_endpoint']=np.nan
 for _,g in e.groupby(['period','variant','state']):
  # All prespecified labels stay in the family, even where estimated support is small.
  p=np.where(g.identified,g.p.fillna(1),1)
  e.loc[g.index,'q_joint']=false_discovery_control(p)
 for _,g in e.groupby(['period','variant','state','target']):
  e.loc[g.index,'q_endpoint']=false_discovery_control(np.where(g.identified,g.p.fillna(1),1))
 annual=e[e.variant.eq('primary')&e.period.ne('2024_2025')]
 e['q_all_annual']=np.nan
 for _,g in annual.groupby('state'):e.loc[g.index,'q_all_annual']=false_discovery_control(np.where(g.identified,g.p.fillna(1),1))
 # Additional conservative sensitivity: do not let numerous gap signals drive performance FDR.
 e['domain']=np.where(e.target.str.startswith('no_top3'),'joint_nonreturn_nonpodium',np.where(e.horizon.eq(0),'return_gap','conditional_performance'))
 e['q_domain']=np.nan
 for _,g in e.groupby(['period','variant','state','domain']):
  e.loc[g.index,'q_domain']=false_discovery_control(np.where(g.identified,g.p.fillna(1),1))
 e.to_csv(O/'adjusted_associations.csv',index=False)
 cov=[]
 for period,z in [('2024_2025',d[d.year.le(2025)]),('2024',d[d.year.eq(2024)]),('2025',d[d.year.eq(2025)]),('2026_partial',d[d.year.eq(2026)])]:
  row=dict(period=period,rows=len(z),horses=z.horse_id.nunique(),first_date=z.index_date.min(),last_date=z.index_date.max())
  for h in [1,2,3]:
   row['return'+str(h)]=int(z['top3_'+str(h)].notna().sum());row['time'+str(h)]=int(z['time_'+str(h)].notna().sum())
  cov.append(row)
 pd.DataFrame(cov).to_csv(O/'followup_coverage.csv',index=False)
 print('finished',mid,'models',len(e),'coefficients',flush=True)
if __name__=='__main__':main()
