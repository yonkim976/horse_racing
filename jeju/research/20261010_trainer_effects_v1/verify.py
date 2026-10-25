"""Reconstruct predictions, estimating equations, clustered intervals and pair units."""
import json
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix,hstack
from scipy.special import expit
from scipy.stats import norm
from data import HERE,ROOT,OLD,NUM,CAT,sha,save
from effects import project,design,bh
def period_data(a,p):
 return a if p=='all' else a[a.year.le(2023)] if p=='past' else a[a.year.le(2025)&a.year.ge(2024)] if p=='2024_2025' else a[a.year.eq(2026)]
def boot(g,key,target,race_weight=False):
 w=1/g.groupby('race_id').api_record_id.transform('size') if race_weight else np.ones(len(g))
 z=pd.DataFrame({'key':g[key],'n':g[target]*w,'d':w}).groupby('key')[['n','d']].sum().to_numpy();rng=np.random.default_rng(20261010);draw=[]
 for i in range(20):
  counts=rng.multinomial(len(z),np.ones(len(z))/len(z),size=200);draw.extend((counts@z[:,0])/(counts@z[:,1]))
 point=z[:,0].sum()/z[:,1].sum();lo,hi=np.quantile(draw,[.025,.975]);se=np.std(draw,ddof=1);pv=2*norm.sf(abs(point/se)) if se else 1
 return np.array([point,lo,hi,pv])
def covariance(x,res,bread,key,df):
 scores=pd.DataFrame(x*res[:,None]);scores['cluster_key']=np.asarray(key);s=scores.groupby('cluster_key',sort=True).sum().to_numpy();G=len(s)
 return bread@(s.T@s)@bread*(G/(G-1)*(len(x)-1)/df)
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False);manifest=json.loads((HERE/'input01/source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 assert sha(ROOT/'jeju/data/jeju_native_core.sqlite3')==manifest['database_sha256']
 dtype={k:str for k in ['horse_id','jockey_id','trainer_id','owner_id','previous_jockey_id','previous_trainer_id','previous_owner_id']}
 a=pd.read_csv(HERE/'input01/starts.csv',dtype=dtype,low_memory=False);src=pd.read_csv(ROOT/'jeju/research/20261009_jockey_closing_switch_v1/input01/starts.csv',dtype=dtype,low_memory=False).set_index('api_record_id').loc[a.api_record_id]
 assert len(a)==52155 and not a.api_record_id.duplicated().any() and not a.horse_id.eq('3005648').any()
 for c in a.columns:
  if c in src:
   if pd.api.types.is_numeric_dtype(a[c]):assert np.allclose(a[c],src[c],equal_nan=True),c
   else:assert a[c].fillna('').tolist()==src[c].fillna('').tolist(),c
 assert np.allclose(a.top3,a.finish_position.le(3)) and a.groupby('race_id').relative_time.mean().abs().max()<1e-10
 assert a.history_cutoff.lt(a.race_date).all()
 idx=a.set_index('api_record_id');mask=a.previous_api_record_id.notna();cur=a[mask];prev=idx.loc[cur.previous_api_record_id.astype(int)]
 assert cur.horse_id.tolist()==prev.horse_id.tolist() and (cur.race_date.to_numpy()>prev.race_date.to_numpy()).all()
 for c in ['trainer_id','jockey_id','owner_id','race_distance_m','H1_time','H1_prob','H1_time_adv','H1_top3_excess']:
  x=cur['previous_'+c];y=prev[c]
  assert np.allclose(x,y,equal_nan=True) if pd.api.types.is_numeric_dtype(x) else x.fillna('').tolist()==y.fillna('').tolist(),c
 assert np.allclose(a.H1_top3_excess,100*(a.top3-a.H1_prob),equal_nan=True)
 pr=pd.read_csv(HERE/'forecast01/predictions.csv',dtype={'horse_id':str,'jockey_id':str});pars=json.loads((HERE/'forecast01/parameters.json').read_text())+[p for p in json.loads((OLD/'forecast01/parameters.json').read_text()) if p['model'] in ['H1','H2']];nforecast=0;errmax=0
 assert not set(NUM+CAT)&{'top3','time','relative_time','first_pack','late_gain','g3f_rank','finish_position'}
 for par in pars:
  tr=a[a.race_date.le(par['cutoff'])];g=a[a.year.eq(par['year'])];assert tr.race_date.max()<g.race_date.min()
  raw=tr[NUM].to_numpy(float);med=np.nan_to_num(np.nanmedian(raw,axis=0),nan=0.);assert np.allclose(med,par['imputation'])
  train=np.where(np.isnan(raw),med[None,:],raw)
  if par['indicators']:train=np.column_stack([train,np.isnan(raw)[:,par['indicators']]])
  assert np.allclose(train.mean(axis=0),par['mean']);sd=train.std(axis=0);sd=np.where(sd==0,1,sd);assert np.allclose(sd,par['scale'])
  raw=g[NUM].to_numpy(float);x=np.where(np.isnan(raw),med[None,:],raw)
  if par['indicators']:x=np.column_stack([x,np.isnan(raw)[:,par['indicators']]])
  x=(x-np.array(par['mean']))/np.array(par['scale']);rr=[];cc=[];offset=0
  for c,levels in zip(par['categorical_columns'],par['categories']):
   assert levels==sorted(tr[c].astype(str).unique());codes=g[c].astype(str).map({v:i for i,v in enumerate(levels)});known=codes.notna();rr.extend(np.flatnonzero(known));cc.extend((codes[known].astype(int)+offset).tolist());offset+=len(levels)
  X=hstack([csr_matrix(x),csr_matrix((np.ones(len(rr)),(rr,cc)),shape=(len(g),offset))],format='csr')
  rawtime=np.asarray(X@np.array(par['ridge_coef']))+par['ridge_intercept'];pt=rawtime-pd.Series(rawtime,index=g.index).groupby(g.race_id).transform('mean').to_numpy();pp=expit(np.asarray(X@np.array(par['logistic_coef']))+par['logistic_intercept'])
  q=pr[pr.model.eq(par['model'])&pr.year.eq(par['year'])].set_index('api_record_id').loc[g.api_record_id]
  assert np.allclose(pt,q.time_prediction,atol=1e-10) and np.allclose(pp,q.prob_top3,atol=1e-12);errmax=max(errmax,float(np.max(np.abs(pt-q.time_prediction))),float(np.max(np.abs(pp-q.prob_top3))));nforecast+=2*len(g)
 print('Predictions replayed',nforecast,flush=True)
 pr['mae']=(pr.time_prediction-pr.relative_time).abs();pr['mse']=(pr.time_prediction-pr.relative_time)**2;pr['logloss']=-(pr.top3*np.log(pr.prob_top3)+(1-pr.top3)*np.log1p(-pr.prob_top3));pr['brier']=(pr.prob_top3-pr.top3)**2
 metrics=pd.read_csv(HERE/'forecast01/metrics.csv')
 for r in metrics.itertuples():
  g=period_data(pr,r.period);g=g[g.model.eq(r.model)];z=g.groupby('race_id')[['mae','mse','logloss','brier']].mean().mean();assert len(g)==r.starts and g.race_id.nunique()==r.races;assert np.allclose([z.mae,np.sqrt(z.mse),z.logloss,z.brier],[r.mae_s,r.rmse_s,r.logloss,r.brier])
 comp=pd.read_csv(HERE/'forecast01/comparisons.csv')
 for r in comp.itertuples():
  after,before=r.comparison.split('-');g=period_data(pr,r.period);v=g[g.model.eq(before)][['api_record_id','race_id','race_date','horse_id',r.metric]].merge(g[g.model.eq(after)][['api_record_id',r.metric]],on='api_record_id',suffixes=('_old','_new'),validate='one_to_one');v['delta']=v[r.metric+'_new']-v[r.metric+'_old'];d=boot(v,'race_date','delta',True);h=boot(v,'horse_id','delta',True);assert np.allclose(d,[r.delta,r.date_low,r.date_high,r.date_p]) and np.allclose(h[1:3],[r.horse_low,r.horse_high])
 assert np.allclose(comp.BH_q,bh(comp.date_p))
 effects=pd.read_csv(HERE/'effects01/trainer_effects.csv',dtype={'trainer_id':str});models=json.loads((HERE/'effects01/models.json').read_text());stored=pd.read_csv(HERE/'effects01/fitted_and_residuals.csv');fechecks=0;maxnormal=0.;maxcov=0.;cache={}
 # Match the original execution's nuisance-ID parser; leading-zero spelling has no design influence.
 aa=a.copy();aa['jockey_id']=aa.jockey_id.astype(int)
 for m in models:
  g=period_data(aa,m['period']);g=g[g[m['target']].notna()].copy();key=(m['period'],m['variant'],tuple(g.api_record_id))
  if key not in cache:
   x,spec=design(g,m['variant']);X=x.to_numpy();z,lu,info=project(g,'horse_id' if m['variant']=='horse_only' else 'horse_distance');xr=X-z@lu.solve(np.asarray(z.T@X));cache[key]=(X,xr,z)
  X,xr,z=cache[key];beta=np.array(m['beta']);alpha=np.array(m['alpha']);y=g[m['target']].to_numpy();pred=X@beta+z@alpha;res=y-pred;nj=m['spec']['n_trainer_columns'];pen=np.r_[np.zeros(nj),np.ones(X.shape[1]-nj)];normal=max(float(np.abs(z.T@res).max()),float(np.abs(X.T@res-pen*beta).max()));assert normal<1e-5;maxnormal=max(maxnormal,normal)
  fitted=stored[(stored.period==m['period'])&(stored.variant==m['variant'])&(stored.target==m['target'])].set_index('api_record_id').loc[g.api_record_id];assert np.allclose(pred,fitted.fit) and np.allclose(res,fitted.residual)
  bread=np.linalg.inv(xr.T@xr+np.diag(pen));dc=covariance(xr,res,bread,g.race_date,m['residual_df']);hc=covariance(xr,res,bread,g.horse_id,m['residual_df']);assert np.allclose(dc,m['date_cov'],atol=1e-8) and np.allclose(hc,m['horse_cov'],atol=1e-8);maxcov=max(maxcov,float(np.max(np.abs(dc-m['date_cov']))),float(np.max(np.abs(hc-m['horse_cov']))))
  eye=np.zeros((len(m['weights']),X.shape[1]));ids=m['spec']['trainer_ids']
  for i,k in enumerate(ids):
   if k!=m['spec']['reference']:eye[i,m['spec']['trainer_columns'].index(k)]=1
  contrast=eye-np.average(eye,axis=0,weights=m['weights']);sign=-1 if m['target'] in ['time','g3f_rank'] else 1;scale=1 if m['target']=='time' else 100;contrast*=sign*scale;point=contrast@beta;dse=np.sqrt(np.maximum(0,np.einsum('ij,jk,ik->i',contrast,dc,contrast)));hse=np.sqrt(np.maximum(0,np.einsum('ij,jk,ik->i',contrast,hc,contrast)))
  e=effects[(effects.period==m['period'])&(effects.variant==m['variant'])&(effects.target==m['target'])].set_index('trainer_id').loc[ids]
  assert np.allclose(e.effect,point) and np.allclose(e.date_low,point-m['crit']*dse) and np.allclose(e.date_high,point+m['crit']*dse) and np.allclose(e.horse_low,point-m['crit']*hse) and np.allclose(e.horse_high,point+m['crit']*hse) and np.allclose(e.BH_q,bh(e.date_p));assert abs(np.average(e.effect,weights=m['weights']))<1e-9;fechecks+=len(e)
 print('FE estimates and CIs replayed',len(models),fechecks,flush=True)
 pairs=pd.read_csv(HERE/'switch02/pairs.csv',dtype=dtype,low_memory=False);expected=a[a.year.ge(2024)&a.H1_time.notna()&a.previous_H1_time.notna()&a.race_distance_m.eq(a.previous_race_distance_m)&a.owner_id.eq(a.previous_owner_id)&a.gap_days.between(2,120)]
 assert pairs.api_record_id.tolist()==expected.api_record_id.tolist();assert np.allclose(pairs.time_gain,pairs.H1_time_adv-pairs.previous_H1_time_adv);assert np.allclose(pairs.top3_excess_gain,pairs.H1_top3_excess-pairs.previous_H1_top3_excess)
 summary=pd.read_csv(HERE/'switch02/summary.csv',dtype={'trainer_id':str})
 for r in summary.itertuples():
  g=period_data(pairs,r.period);g=g if r.subset=='all' else g[g.same_jockey];g=g[g.changed_trainer.eq(r.changed_trainer)];g=g if pd.isna(r.trainer_id) else g[g.trainer_id.eq(r.trainer_id)];assert len(g)==r.pairs and g.horse_id.nunique()==r.horses;d=boot(g,'race_date',r.target);h=boot(g,'horse_id',r.target);assert np.allclose(d,[r.mean,r.date_low,r.date_high,r.date_p]) and np.allclose(h[1:3],[r.horse_low,r.horse_high])
 for _,g in summary[summary.trainer_id.notna()].groupby(['period','subset']):assert np.allclose(g.BH_q,bh(g.date_p))
 save(out/'verification.json',{'status':'passed','input_rows_checked_against_frozen_source':len(a),'previous_selected_edges_verified':int(mask.sum()),'forecast_outcome_values_replayed':nforecast,'maximum_forecast_error':errmax,'metrics_recalculated':len(metrics),'date_and_horse_bootstrap_forecast_comparisons':len(comp),'FE_models_normal_equations_covariances_and_contrasts':len(models),'FE_contrasts_and_CIs_recalculated':fechecks,'maximum_normal_equation_error':maxnormal,'maximum_covariance_error':maxcov,'eligible_pair_rows_verified':len(pairs),'pair_bootstrap_rows_verified':len(summary),'top3_excess_units_percentage_points_verified':True,'all_pinned_source_hashes_and_sizes_unchanged':True,'database_hash_unchanged':True,'operational_changes':False})
 print('Trainer verification passed',flush=True)
if __name__=='__main__':main()
