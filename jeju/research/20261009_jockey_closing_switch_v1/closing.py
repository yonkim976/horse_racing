"""Joint rider main effects and prior back-position interactions, with fixed effects."""
import importlib.util
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,OLD,FE_NUM,save
spec=importlib.util.spec_from_file_location('previous_effects',OLD/'effects.py');previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
project=previous.project;cluster=previous.cluster;bh=previous.bh

def fit(g,targets,period):
 levels=sorted(g.jockey_id.unique());counts=g.groupby('jockey_id').back.agg(['sum','count'])
 variable=counts.index[(counts['sum']>0)&(counts['sum']<counts['count'])].tolist()
 reference=g[g.jockey_id.isin(variable)].jockey_id.value_counts().idxmax()
 maincols=[j for j in levels if j!=reference];intercols=[j for j in variable if j!=reference]
 j=pd.DataFrame({'main='+k:g.jockey_id.eq(k).astype(float) for k in maincols},index=g.index)
 for k in intercols:j['back='+k]=(g.jockey_id.eq(k)&g.back).astype(float)
 n=g[FE_NUM+['back','back_prop','h_any_late_n','h_any_late_mean','h_g3f_rank_n','h_g3f_rank_mean']].astype(float).copy();med=n.median();n=n.fillna(med).fillna(0)
 for c in med.index:
  if g[c].isna().any():n[c+'_missing']=g[c].isna().astype(float)
 n=pd.concat([n,pd.get_dummies(g.trainer_id,prefix='trainer',drop_first=True,dtype=float)],axis=1)
 sd=n.std(ddof=0);n=n[sd[sd>1e-12].index];mu=n.mean();sd=n.std(ddof=0);n=(n-mu)/sd
 x=pd.concat([j,n],axis=1);X=x.to_numpy();Y=g[targets].to_numpy();z,lu,info=project(g,'horse_distance')
 rv=np.column_stack([Y,X]);rv=rv-z@lu.solve(np.asarray(z.T@rv));yr=rv[:,:len(targets)];xr=rv[:,len(targets):]
 nj=j.shape[1];jj=xr[:,:nj];nn=xr[:,nj:];jres=jj-nn@np.linalg.lstsq(nn,jj,rcond=1e-10)[0]
 rank=np.linalg.matrix_rank(jres,tol=1e-7);assert rank==nj,('unidentified',period,targets,rank,nj)
 df=len(g)-info['rank']-np.linalg.matrix_rank(xr,tol=1e-7);assert df>20
 pen=np.r_[np.zeros(nj),np.ones(X.shape[1]-nj)];bread=np.linalg.inv(xr.T@xr+np.diag(pen));beta=bread@xr.T@yr
 weights=g[g.back].jockey_id.value_counts(normalize=True).reindex(levels).fillna(0).to_numpy()
 M=np.zeros((len(levels),X.shape[1]));I=M.copy()
 for i,k in enumerate(levels):
  if k!=reference:M[i,maincols.index(k)]=1
  if k in intercols:I[i,len(maincols)+intercols.index(k)]=1
 vectors={'back_effect':M+I-np.average(M+I,axis=0,weights=weights),'back_specific':I-np.average(I,axis=0,weights=weights)}
 sup=g.groupby('jockey_id').agg(starts=('api_record_id','size'),horses=('horse_id','nunique'),days=('race_date','nunique'))
 backsup=g[g.back].groupby('jockey_id').agg(back_starts=('api_record_id','size'),back_horses=('horse_id','nunique'),back_days=('race_date','nunique'))
 crit=float(t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1));rows=[];models=[];resids=[]
 for k,target in enumerate(targets):
  res=yr[:,k]-xr@beta[:,k];dc=cluster(xr,res,bread,g.race_date,df);hc=cluster(xr,res,bread,g.horse_id,df)
  alpha=lu.solve(np.asarray(z.T@(Y[:,k]-X@beta[:,k])));fit=X@beta[:,k]+z@alpha
  assert np.max(np.abs(Y[:,k]-fit-res))<1e-7
  factor=(-1 if target in ['time','g3f_rank'] else 1)*(1 if target=='time' else 100)
  for contrast,vs in vectors.items():
   for i,kid in enumerate(levels):
    if kid not in variable:continue
    v=vs[i]*factor;point=float(v@beta[:,k]);ds=float(np.sqrt(max(0,v@dc@v)));hs=float(np.sqrt(max(0,v@hc@v)))
    b=backsup.loc[kid];s=sup.loc[kid];eligible=s.starts>=100 and s.days>=20 and s.horses>=30 and b.back_starts>=30 and b.back_days>=10 and b.back_horses>=15
    rows.append({'period':period,'target':target,'contrast':contrast,'jockey_id':kid,'name':g.loc[g.jockey_id.eq(kid),'jockey_display_name'].iloc[0],**s.astype(int).to_dict(),**b.astype(int).to_dict(),
     'effect':point,'date_low':point-crit*ds,'date_high':point+crit*ds,'horse_low':point-crit*hs,'horse_high':point+crit*hs,'date_p':float(2*t.sf(abs(point/ds),min(g.race_date.nunique(),g.horse_id.nunique())-1)) if ds else 1.,'support':bool(eligible)})
  models.append({'period':period,'target':target,'row_ids':g.api_record_id.astype(int).tolist(),'columns':x.columns.tolist(),'maincols':maincols,'intercols':intercols,'levels':levels,'reference':reference,'variable':variable,'weights':weights.tolist(),
   'nuisance_medians':med.fillna(0).to_dict(),'nuisance_means':mu.to_dict(),'nuisance_sd':sd.to_dict(),'beta':beta[:,k].tolist(),'alpha':alpha.tolist(),'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'crit':crit,'FE':info,'residual_df':int(df)})
  r=g[['api_record_id','jockey_id','horse_id','race_date']].copy();r['period']=period;r['target']=target;r['fit']=fit;r['residual']=res;resids.append(r)
 print('Closing FE',period,targets,len(g),'back',int(g.back.sum()),flush=True)
 return rows,models,resids

def main():
 out=HERE/'closing01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/starts.csv',dtype={'horse_id':str,'jockey_id':str,'trainer_id':str,'owner_id':str},low_memory=False)
 rows=[];models=[];resids=[];raw=[]
 for period,g in [('all',a),('2024_2025',a[a.year.between(2024,2025)]),('2026',a[a.year.eq(2026)])]:
  batches={}
  for target in ['time','top3','late_gain','g3f_rank']:
   mask=g[target].notna();batches.setdefault(mask.to_numpy().tobytes(),(mask,[]))[1].append(target)
  for mask,targets in batches.values():
   rr,mm,ss=fit(g.loc[mask].copy(),targets,period);rows+=rr;models+=mm;resids+=ss
  for label,mask in [('back',g.back),('closing_strict',g.style_any.eq('closing')),('closing40',g.style_any40.eq('closing'))]:
   for (kid,name),v in g[mask].groupby(['jockey_id','jockey_display_name']):raw.append({'period':period,'definition':label,'jockey_id':kid,'name':name,'starts':len(v),'horses':v.horse_id.nunique(),'top3_count':int(v.top3.sum()),'top3_rate':v.top3.mean(),'late_n':int(v.late_gain.notna().sum()),'late_gain_rate':v.late_gain.mean(),'g3f_rank_n':int(v.g3f_rank.notna().sum()),'mean_g3f_rank_fraction':v.g3f_rank.mean()})
 result=pd.DataFrame(rows);result['BH_q']=np.nan
 for mask in [result.period.eq('all'),~result.period.eq('all')]:result.loc[mask,'BH_q']=bh(result.loc[mask,'date_p'])
 result['direction_supported']=result.support&result.BH_q.lt(.05)&((result.date_low.gt(0)&result.horse_low.gt(0))|(result.date_high.lt(0)&result.horse_high.lt(0)))
 result.to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');pd.DataFrame(raw).to_csv(out/'raw_style_results.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models);pd.concat(resids).to_csv(out/'fitted.csv',index=False,encoding='utf-8-sig')
 print(result[(result.period=='2026')&result.support][['target','contrast','name','back_starts','effect','BH_q','direction_supported']].to_string(index=False),flush=True)
if __name__=='__main__':main()
