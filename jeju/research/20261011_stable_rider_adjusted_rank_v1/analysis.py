"""Conditional rank gains: switch versus retained, all supported stable/rider cells."""
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,BASE,DELTA,CAT,ID_COLS,TARGETS,save
def bh(p):
 p=np.asarray(p,float);order=np.argsort(p);q=np.minimum.accumulate((p[order]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1];r=np.empty(len(p));r[order]=np.minimum(q,1);return r
def design(g,tr):
 n=g[BASE].copy();n['log_gap']=np.log1p(g.gap_days);n['distance_changed']=(~g.same_distance).astype(float);n['grade_changed']=g.class_clean.ne(g.previous_class_clean).astype(float)
 for c in DELTA:n['delta_'+c]=g[c]-g['previous_'+c]
 med=n.median().fillna(0);missing=n.isna();n=n.fillna(med)
 for c in med.index:
  if missing[c].any():n[c+'_missing']=missing[c].astype(float)
 sd=n.std(ddof=0);n=n.loc[:,sd.gt(1e-12)];mu=n.mean();sd=n.std(ddof=0);n=(n-mu)/sd
 x=pd.concat([pd.DataFrame({'intercept':1.,'comparison':tr.astype(float)},index=g.index),n,pd.get_dummies(g[CAT].astype(str),drop_first=True,dtype=float)],axis=1)
 return x,{'columns':x.columns.tolist(),'medians':med.to_dict(),'means':mu.to_dict(),'sd':sd.to_dict()}
def demean(X,key):
 codes,ids=pd.factorize(key);tot=np.zeros((len(ids),X.shape[1]));np.add.at(tot,codes,X);cnt=np.bincount(codes)
 return X-tot[codes]/cnt[codes,None],len(ids)
def variance(X,res,bread,key,df,k):
 codes,ids=pd.factorize(key);score=np.zeros((len(ids),X.shape[1]));np.add.at(score,codes,X*res[:,None]);v=bread[k]@score.T
 return float(v@v*len(ids)/(len(ids)-1)*(len(X)-1)/df)
def fit(g,tr,period,cell,variant,comparison):
 meta={'period':period,'cell':cell,'variant':variant,'comparison':comparison,'rows':len(g),'treated':int(tr.sum()),'controls':int((~tr).sum()),'horses':g.horse_id.nunique(),'days':g.race_date.nunique()}
 c=g[tr];v=g[~tr]
 if len(c)<20 or len(v)<(30 if comparison=='other_switches' else 20) or min(c.horse_id.nunique(),v.horse_id.nunique(),c.race_date.nunique(),v.race_date.nunique())<10 or g.horse_id.nunique()<15 or g.race_date.nunique()<15:return [],{**meta,'status':'insufficient_subset_support'}
 x,spec=design(g,tr);X=x.to_numpy();fe=variant=='horse_fe'
 mixed=int(g.assign(t=tr).groupby('horse_id').t.nunique().eq(2).sum())
 if fe and mixed<10:return [],{**meta,'status':'insufficient_crossover_horses','crossover_horses':mixed}
 if fe:X,H=demean(X[:,1:],g.horse_id);k=0
 else:H=0;k=1
 rank=int(np.linalg.matrix_rank(X,tol=1e-8));df=len(g)-rank-H
 if df<=15:return [],{**meta,'status':'insufficient_residual_df','df':df,'crossover_horses':mixed}
 nuisance=np.delete(X,k,axis=1);resid=X[:,k]-nuisance@np.linalg.lstsq(nuisance,X[:,k],rcond=1e-10)[0];ident=float(np.linalg.norm(resid))
 if ident<1e-6:return [],{**meta,'status':'comparison_unidentified','ident_norm':ident}
 pen=np.ones(X.shape[1]);pen[k]=0
 if not fe:pen[0]=0
 bread=np.linalg.inv(X.T@X+np.diag(pen));degrees=min(g.race_date.nunique(),g.horse_id.nunique())-1;crit=float(t.ppf(.975,degrees));rows=[];models=[]
 for target in TARGETS:
  y=g[target].to_numpy()
  if fe:y=demean(y[:,None],g.horse_id)[0][:,0]
  beta=bread@X.T@y;res=y-X@beta;dv=variance(X,res,bread,g.race_date,df,k);hv=variance(X,res,bread,g.horse_id,df,k);sd=np.sqrt(max(0,dv));sh=np.sqrt(max(0,hv));effect=float(beta[k])
  rows.append({**meta,'target':target,'trainer_name':g.trainer_name.iloc[-1],'jockey_name':g.loc[g.cell.eq(cell),'jockey_display_name'].iloc[-1],'effect':effect,'date_low':effect-crit*sd,'date_high':effect+crit*sd,'horse_low':effect-crit*sh,'horse_high':effect+crit*sh,'date_p':float(2*t.sf(abs(effect/sd),degrees)) if sd else 1.,'horse_p':float(2*t.sf(abs(effect/sh),degrees)) if sh else 1.,'residual_df':df,'ident_norm':ident,'crossover_horses':mixed,'changed_raw_mean_gain':c[target].mean(),'control_raw_mean_gain':v[target].mean(),'unadjusted_gain_difference':c[target].mean()-v[target].mean(),'units':'10runner_equivalent_places' if target=='normalized10_gain' else 'actual_places'})
  models.append({'target':target,'beta':beta.tolist(),'date_variance':dv,'horse_variance':hv,'comparison_index':k,'crit':crit,'residual_df':df})
 return rows,{**meta,'status':'fitted','row_ids':g.api_record_id.astype(int).tolist(),'treatment':tr.astype(int).tolist(),'horse_fe':fe,'spec':spec,'models':models}
def main():
 out=HERE/'analysis01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/pairs.csv',dtype={c:str for c in ID_COLS},low_memory=False)
 support=[];rows=[];models=[]
 for period,z in [('2024_2025',a[a.year.le(2025)]),('2026',a[a.year.eq(2026)])]:
  for cell,g in z.groupby('cell'):
   tr=g.changed_jockey;c=g[tr];v=g[~tr]
   ok=len(c)>=20 and len(v)>=20 and g.horse_id.nunique()>=15 and g.race_date.nunique()>=15 and min(c.horse_id.nunique(),v.horse_id.nunique(),c.race_date.nunique(),v.race_date.nunique())>=10
   support.append({'period':period,'cell':cell,'trainer_id':g.trainer_id.iloc[0],'trainer_name':g.trainer_name.iloc[-1],'jockey_id':g.jockey_id.iloc[0],'jockey_name':g.jockey_display_name.iloc[-1],'changes':len(c),'retained':len(v),'horses':g.horse_id.nunique(),'days':g.race_date.nunique(),'changed_horses':c.horse_id.nunique(),'retained_horses':v.horse_id.nunique(),'changed_days':c.race_date.nunique(),'retained_days':v.race_date.nunique(),'qualified':ok,'crossover_horses':int(g.assign(t=tr).groupby('horse_id').t.nunique().eq(2).sum())})
   if not ok:continue
   for variant,subset in [('primary',g),('same_distance',g[g.same_distance]),('horse_fe',g)]:
    rr,mm=fit(subset,subset.changed_jockey,period,cell,variant,'same_pair_retained');rows+=rr;models.append(mm)
   other=z[z.trainer_id.eq(g.trainer_id.iloc[0])&z.changed_jockey]
   rr,mm=fit(other,other.cell.eq(cell),period,cell,'other_switches','other_switches');rows+=rr;models.append(mm)
  print('Conditional rank period fitted',period,len(z),'pairs',flush=True)
 r=pd.DataFrame(rows);r['BH_q']=np.nan;primary=r.variant.eq('primary');r.loc[primary,'BH_q']=bh(r.loc[primary,'date_p']);r['positive_supported']=primary&r.BH_q.lt(.05)&r.date_low.gt(0)&r.horse_low.gt(0);r['negative_supported']=primary&r.BH_q.lt(.05)&r.date_high.lt(0)&r.horse_high.lt(0)
 r.to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');pd.DataFrame(support).to_csv(out/'support.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models)
 repeats=[]
 for (cell,target),g in r[primary].groupby(['cell','target']):
  repeats.append({'cell':cell,'target':target,'periods':len(g),'trainer_name':g.trainer_name.iloc[-1],'jockey_name':g.jockey_name.iloc[-1],'positive_points_both':len(g)==2 and bool(g.effect.gt(0).all()),'supported_both':len(g)==2 and bool(g.positive_supported.all())})
 pd.DataFrame(repeats).to_csv(out/'repeat_checks.csv',index=False,encoding='utf-8-sig')
 print('PRIMARY TESTS',int(primary.sum()),'POSITIVE',int(r.positive_supported.sum()),'REPEATED',sum(x['supported_both'] for x in repeats),flush=True)
 print(r[primary&r.target.eq('normalized10_gain')].sort_values(['period','effect'],ascending=[True,False])[['period','cell','trainer_name','jockey_name','treated','controls','effect','date_low','date_high','horse_low','horse_high','BH_q','positive_supported']].to_string(index=False),flush=True)
if __name__=='__main__':main()
