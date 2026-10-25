"""Recalculate all stored forecasts, FE normal equations, constraints and identities."""
import json
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix,hstack
from scipy.special import expit
from data import HERE,ROOT,sha,save,NUM,CAT
from effects import project,design,bh

def period_data(a,period):
 if period=='all':return a
 if period=='past':return a[a.year.le(2023)]
 if period=='2024_2025':return a[a.year.isin([2024,2025])]
 return a[a.year.eq(2026)]
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False)
 manifest=json.loads((HERE/'input01/source_manifest.json').read_text());assert manifest['database_read_only'] and manifest['database_sha256_before']==manifest['database_sha256_after']
 assert all(sha(ROOT/x['path'])==x['sha256'] for x in manifest['files'])
 a=pd.read_csv(HERE/'input01/starts.csv',dtype={'horse_id':str,'jockey_id':str,'trainer_id':str},low_memory=False)
 assert len(a)==52155 and not a.api_record_id.duplicated().any() and not a.horse_id.eq('3005648').any()
 assert np.array_equal(a.top3,a.finish_position.le(3)) and a.payload_sha256.eq(a.result_payload_sha256).all()
 assert a.groupby('race_id').relative_time.mean().abs().max()<1e-10
 pr=pd.read_csv(HERE/'forecast01/predictions.csv',dtype={'horse_id':str,'jockey_id':str});parameters=json.loads((HERE/'forecast01/parameters.json').read_text());maximum=0.;checks=0
 assert not set(NUM+CAT)&{'top3','time','relative_time','first_pack','late_gain','g3f_rank','finish_position'}
 for par in parameters:
  train=a[a.race_date.le(par['cutoff'])];g=a[a.year.eq(par['year'])]
  assert train.race_date.max()<g.race_date.min()
  raw=train[NUM].to_numpy(dtype=float,copy=True);median=np.nanmedian(raw,axis=0);median=np.nan_to_num(median,nan=0.);assert np.allclose(median,par['imputation'])
  x=g[NUM].to_numpy(dtype=float,copy=True);miss=np.isnan(x);x=np.where(miss,np.array(par['imputation'])[None,:],x)
  if par['indicators']:x=np.column_stack([x,miss[:,par['indicators']].astype(float)])
  x=(x-np.array(par['mean']))/np.array(par['scale']);rr=[];cc=[];offset=0
  for col,categories in zip(par['categorical_columns'],par['categories']):
   lookup={v:i for i,v in enumerate(categories)};values=g[col].astype(str).map(lookup);mask=values.notna().to_numpy();rr.extend(np.flatnonzero(mask));cc.extend((values[mask].astype(int)+offset).tolist());offset+=len(categories)
   assert categories==sorted(train[col].astype(str).unique())
  cats=csr_matrix((np.ones(len(rr)),(rr,cc)),shape=(len(g),offset));X=hstack([csr_matrix(x),cats],format='csr')
  rawtime=np.asarray(X@np.array(par['ridge_coef']))+par['ridge_intercept'];ptime=rawtime-pd.Series(rawtime,index=g.index).groupby(g.race_id).transform('mean').to_numpy();prob=expit(np.asarray(X@np.array(par['logistic_coef']))+par['logistic_intercept'])
  stored=pr[pr.year.eq(par['year'])&pr.model.eq(par['model'])].set_index('api_record_id').loc[g.api_record_id]
  assert np.allclose(ptime,stored.time_prediction,atol=1e-10) and np.allclose(prob,stored.prob_top3,atol=1e-12)
  maximum=max(maximum,float(np.max(np.abs(ptime-stored.time_prediction))),float(np.max(np.abs(prob-stored.prob_top3))))
  pastpairs=train.groupby('horse_jockey').size();assert np.array_equal(g.horse_jockey.map(pastpairs).fillna(0).astype(int),stored.past_pair_n)
  # Current outcomes are not among declared model columns; altering them leaves every input intact.
  altered=g.copy();altered['top3']=1-altered.top3;altered['relative_time']=999;altered['time']=999;altered['first_pack']=1-altered.first_pack;altered['late_gain']=1-altered.late_gain
  assert np.allclose(altered[NUM],g[NUM],equal_nan=True) and altered[par['categorical_columns']].equals(g[par['categorical_columns']])
  checks+=2*len(g)
 print('Annual predictions reconstructed',checks,maximum,flush=True)
 # Check every reported metric from the complete prediction rows.
 p=pr.copy();p['mae']=(p.time_prediction-p.relative_time).abs();p['mse']=(p.time_prediction-p.relative_time)**2;p['logloss']=-(p.top3*np.log(p.prob_top3)+(1-p.top3)*np.log1p(-p.prob_top3));p['brier']=(p.prob_top3-p.top3)**2
 metrics=pd.read_csv(HERE/'forecast01/metrics.csv');metricchecks=0
 for r in metrics.itertuples():
  g=p[p.model.eq(r.model)&(p.year.le(2025) if r.period=='2024_2025' else p.year.eq(2026))];g=g if r.subset=='all' else g[g.past_pair_n.ge(3)];z=g.groupby('race_id')[['mae','mse','logloss','brier']].mean().mean()
  assert len(g)==r.starts and g.race_id.nunique()==r.races
  assert np.allclose([z.mae,np.sqrt(z.mse),z.logloss,z.brier],[r.mae_s,r.rmse_s,r.logloss,r.brier]);metricchecks+=1
 models=json.loads((HERE/'effects01/models.json').read_text());fitted=pd.read_csv(HERE/'effects01/fitted_and_residuals.csv');effects=pd.read_csv(HERE/'effects01/jockey_effects.csv',dtype={'jockey_id':str});key_prev=None;fechecks=0;normmax=0.
 for m in models:
  g=period_data(a,m['period']);g=g[g[m['target']].notna()].copy();key=(m['period'],m['variant'],tuple(g.api_record_id))
  if key!=key_prev:
   x,spec=design(g,m['variant']);X=x.to_numpy();z,lu,info=project(g,'horse_id' if m['variant']=='horse_only' else 'horse_distance');xr=X-z@lu.solve(np.asarray(z.T@X));key_prev=key
  beta=np.array(m['beta']);alpha=np.array(m['alpha']);y=g[m['target']].to_numpy();pred=X@beta+z@alpha;res=y-pred
  penalty=np.r_[np.zeros(m['spec']['n_jockey_columns']),np.ones(X.shape[1]-m['spec']['n_jockey_columns'])]
  zorth=float(np.abs(z.T@res).max());xorth=float(np.abs(X.T@res-penalty*beta).max());assert zorth<1e-5 and xorth<1e-5,(m['period'],m['target'],zorth,xorth);normmax=max(normmax,zorth,xorth)
  q=fitted[(fitted.period==m['period'])&(fitted.variant==m['variant'])&(fitted.target==m['target'])].set_index('api_record_id').loc[g.api_record_id];assert np.allclose(q.fit,pred,atol=1e-9)
  e=effects[(effects.period==m['period'])&(effects.variant==m['variant'])&(effects.target==m['target'])].set_index('jockey_id').loc[m['spec']['jockey_ids']]
  assert abs(np.average(e.effect,weights=m['weights']))<1e-9
  assert np.allclose(e.BH_q,bh(e.date_p))
  fechecks+=len(g)
 print('FE normal equations reconstructed',len(models),normmax,flush=True)
 pairs=pd.read_csv(HERE/'pairs01/pairs_and_frozen_scores.csv',dtype={'jockey_id':str,'previous_jockey_id':str,'horse_id':str});idx=a.set_index('api_record_id');h0=pr[pr.model.eq('H0')].set_index('api_record_id');frozen=effects[(effects.period=='past')&(effects.variant=='primary')&(effects.target=='time')].set_index('jockey_id').effect
 cur=idx.loc[pairs.api_record_id];prev=idx.loc[pairs.previous_api_record_id.astype(int)];assert np.array_equal(cur.horse_id,prev.horse_id) and np.array_equal(cur.race_distance_m,prev.race_distance_m)
 assert (cur.race_date.to_numpy()>prev.race_date.to_numpy()).all()
 assert np.allclose(pairs.frozen_score_gain,pairs.jockey_id.map(frozen)-pairs.previous_jockey_id.map(frozen))
 errors=h0.relative_time-h0.time_prediction;assert np.allclose(pairs.error_delta,errors.loc[pairs.api_record_id].to_numpy()-errors.loc[pairs.previous_api_record_id.astype(int)].to_numpy())
 comp=pd.read_csv(HERE/'forecast01/comparisons.csv')
 for _,g in comp[comp.subset.eq('all')].groupby('comparison'):assert len(g)==4 and np.allclose(g.BH_q,bh(g.date_p))
 save(out/'verification.json',{'status':'passed','source_payload_identities_checked':len(a),'annual_outcome_predictions_recomputed':checks,'maximum_prediction_error':maximum,'all_train_cutoffs_precede_eval':True,
  'metrics_recomputed':metricchecks,'FE_models_normal_equations_verified':len(models),'FE_rows_recomputed':fechecks,'maximum_normal_equation_error':normmax,'FE_weighted_zero_and_BH_verified':True,
  'current_outcome_perturbation_input_invariant':True,'frozen_jockey_change_pairs_recomputed':len(pairs),'all_source_hashes_unchanged':True,'no_database_or_operational_model_writes':True})
 print('Verification passed',flush=True)
if __name__=='__main__':main()
