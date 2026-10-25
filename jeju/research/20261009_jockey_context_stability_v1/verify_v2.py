"""Recompute sources, temporal form windows, FE contrasts and frozen forecasts."""
import json
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix,csr_matrix,hstack
from scipy.special import expit
from scipy.stats import norm
from data import HERE,ROOT,OLD,sha,save
from effects import project,NEGATIVE,PERCENT

def qvalues(p):
 p=np.asarray(p);order=np.argsort(p);q=np.empty(len(p));last=1.
 for j in range(len(p)-1,-1,-1):last=min(last,p[order[j]]*len(p)/(j+1));q[order[j]]=last
 return q
def cov(X,res,bread,key,df):
 scores=pd.DataFrame(X*res[:,None]).groupby(np.asarray(key),sort=True).sum().to_numpy();n=len(scores)
 return bread@scores.T@scores@bread*(n/(n-1)*(len(X)-1)/df)
def replay(g,m,train):
 raw=g[m['numeric_columns']].to_numpy(float);med=np.asarray(m['imputation']);filled=np.where(np.isnan(raw),med,raw);numeric=np.column_stack([filled,np.isnan(raw[:,m['indicators']]).astype(float)])
 numeric=(numeric-np.asarray(m['mean']))/np.asarray(m['scale']);rows=[];cols=[];off=0
 for key,levels in zip(m['categorical_columns'],m['categories']):
  lookup={v:i for i,v in enumerate(levels)};idx=np.array([lookup.get(v,-1) for v in g[key].astype(str)]);valid=idx>=0;rows.extend(np.flatnonzero(valid));cols.extend(idx[valid]+off);off+=len(levels)
 X=hstack([csr_matrix(numeric),coo_matrix((np.ones(len(rows)),(rows,cols)),shape=(len(g),off)).tocsr()],format='csr')
 tm=np.asarray(X@np.asarray(m['ridge_coef'])).ravel()+m['ridge_intercept'];tm-=pd.Series(tm,index=g.index).groupby(g.race_id).transform('mean').to_numpy()
 pr=expit(np.asarray(X@np.asarray(m['logistic_coef'])).ravel()+m['logistic_intercept'])
 assert train.race_date.max()==m['train_last'] and len(train)==m['train_rows'] and train.race_date.le(m['cutoff']).all() and m['cutoff']<g.race_date.min()
 expected=[]
 for c in m['numeric_columns']:
  v=train[c].dropna();expected.append(float(v.median()) if len(v) else 0.)
 assert np.allclose(expected,med)
 tr=train[m['numeric_columns']].to_numpy(float);fill=np.where(np.isnan(tr),med,tr);scaled=np.column_stack([fill,np.isnan(tr[:,m['indicators']]).astype(float)]);sd=scaled.std(axis=0);sd[sd<1e-12]=1.
 assert np.allclose(scaled.mean(axis=0),m['mean']) and np.allclose(sd,m['scale'])
 for key,levels in zip(m['categorical_columns'],m['categories']):assert sorted(train[key].astype(str).unique())==levels
 return tm,pr
def boot(g,key):
 weights=1/g.groupby('race_id').delta.transform('size');tab=pd.DataFrame({'k':g[key],'v':weights*g.delta,'w':weights}).groupby('k')[['v','w']].sum().to_numpy();rng=np.random.default_rng(20261009);vals=[]
 for _ in range(20):
  w=rng.multinomial(len(tab),np.full(len(tab),1/len(tab)),size=200);vals.extend((w@tab[:,0])/(w@tab[:,1]))
 point=float(tab[:,0].sum()/tab[:,1].sum());lo,hi=np.quantile(vals,[.025,.975]);sd=np.std(vals,ddof=1);p=float(2*norm.sf(abs(point/sd))) if sd else 1.
 return point,lo,hi,p

def main():
 out=HERE/'verification02';out.mkdir(exist_ok=False)
 a=pd.read_csv(HERE/'input02/starts.csv',dtype={'horse_id':str,'jockey_id':str,'trainer_id':str},low_memory=False);amap=a.set_index('api_record_id');manifest=json.loads((HERE/'input02/source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'],r['path']
 assert sha(ROOT/'jeju/data/jeju_native_core.sqlite3')==manifest['database_sha256'];assert len(a)==52155 and a.race_id.nunique()==5206 and not a.horse_id.eq('3005648').any()
 assert np.allclose(a.gate_scaled,(a.horse_number-1)/(a.groupby('race_id').horse_number.transform('max')-1))
 assert a.outer.eq(a.gate_scaled.gt(2/3)).all()
 assert np.allclose(a.first_pack,np.where(a.y_s1f_pack3.notna(),a.y_s1f_pack3.eq(0),np.nan),equal_nan=True)
 assert np.allclose(a.front_pack2,np.where(a.y_s1f_pack3.notna(),a.y_s1f_pack3.le(1),np.nan),equal_nan=True)
 leaders=a.style_any.eq('lead').groupby(a.race_id).transform('sum');coverage=a.style_any.ne('unknown').groupby(a.race_id).transform('mean')
 assert np.array_equal(a.rival_leaders,leaders-a.style_any.eq('lead').astype(int)) and np.allclose(a.HIST_coverage,coverage)
 assert a.pace_eligible.eq(coverage.ge(.8-1e-12)).all() and a.pressure.eq(a.rival_leaders.ge(2)).all()
 assert np.allclose(a.fade3,np.where(a.c4_rank_hi.notna(),a.finish_position.ge(a.c4_rank_hi+3),np.nan),equal_nan=True)
 source=pd.read_csv(ROOT/'jeju/research/20261008_gate_region_pace_prediction_v2/features01/features_and_targets.csv').set_index('api_record_id').loc[a.api_record_id]
 assert np.allclose(a.opp_outer_faster_count,source.opp_faster_count-source.opp_inner_faster_count,equal_nan=True)
 assert np.allclose(a.big_slow,np.where(a.H1_time.notna(),(a.relative_time-a.H1_time).gt(1.5),np.nan),equal_nan=True)
 assert np.allclose(a.slow_loss,(a.relative_time-a.H1_time).clip(lower=0),equal_nan=True)
 e=pd.read_csv(HERE/'effects02/jockey_effects.csv',dtype={'jockey_id':str,'period':str});ff=pd.read_csv(HERE/'effects02/fitted.csv',dtype={'period':str,'jockey_id':str},low_memory=False).set_index(['topic','period','target','api_record_id']).sort_index();modelchecks=0;points=0;maxnormal=0.
 for m in json.loads((HERE/'effects02/models.json').read_text()):
  g=amap.loc[m['row_ids']];s=m['spec'];cols={}
  for c in s['columns']:
   if c.startswith('main='):v=g.jockey_id.eq(c[5:]).astype(float)
   elif c.startswith('context='):v=(g.jockey_id.eq(c[8:])&g[s['exposure']]).astype(float)
   else:
    if c.startswith('trainer_'):v=g.trainer_id.eq(c[8:]).astype(float)
    elif c=='prior_unknown':v=g.style_any.eq('unknown').astype(float)
    elif c=='prior_lead':v=g.style_any.eq('lead').astype(float)
    elif c.startswith('pred_d'):v=g.H1_time*g.race_distance_m.eq(int(c[6:]))
    elif c.endswith('_missing'):v=g[c[:-8]].isna().astype(float)
    else:v=g[c].astype(float).fillna(s['nuisance_medians'][c])
    v=(v-s['nuisance_means'][c])/s['nuisance_sd'][c]
   cols[c]=v
  X=pd.DataFrame(cols,index=g.index).to_numpy();z,lu,info=project(g,'horse_distance');xr=X-z@lu.solve(np.asarray(z.T@X));beta=np.asarray(m['beta']);fit=X@beta+z@np.asarray(m['alpha']);res=g[m['target']].to_numpy()-fit
  saved=ff.loc[(m['topic'],m['period'],m['target'])].loc[g.index];assert np.allclose(saved['fit'],fit,atol=1e-7) and np.allclose(saved.residual,res,atol=1e-7)
  nj=len(s['maincols'])+len(s['intercols']);pen=np.r_[np.zeros(nj),np.ones(X.shape[1]-nj)];err=max(np.max(np.abs(z.T@res)),np.max(np.abs(X.T@res-pen*beta)));maxnormal=max(maxnormal,float(err));assert err<1e-5
  bread=np.linalg.inv(xr.T@xr+np.diag(pen));dc=cov(xr,res,bread,g.race_date,m['residual_df']);hc=cov(xr,res,bread,g.horse_id,m['residual_df']);assert np.allclose(dc,m['date_cov'],atol=1e-7) and np.allclose(hc,m['horse_cov'],atol=1e-7)
  ex=s['exposure'];weights=(g[g[ex]] if ex else g).jockey_id.value_counts(normalize=True).reindex(s['levels']).fillna(0).to_numpy();M=np.zeros((len(weights),X.shape[1]));I=M.copy()
  for i,j in enumerate(s['levels']):
   if j in s['maincols']:M[i,s['maincols'].index(j)]=1
   if j in s['intercols']:I[i,len(s['maincols'])+s['intercols'].index(j)]=1
  for contrast,V in ({'context_effect':M+I,'context_specific':I} if ex else {'jockey_effect':M}).items():
   V-=np.average(V,axis=0,weights=weights)
   rr=e[(e.topic==m['topic'])&(e.period==m['period'])&(e.target==m['target'])&(e.contrast==contrast)]
   for r in rr.itertuples():
    vec=V[s['levels'].index(r.jockey_id)]*((-1 if m['target'] in NEGATIVE else 1)*(100 if m['target'] in PERCENT else 1));pt=float(vec@beta);ds=np.sqrt(max(0,vec@dc@vec));hs=np.sqrt(max(0,vec@hc@vec));cr=m['crit']
    assert np.allclose([r.effect,r.date_low,r.date_high,r.horse_low,r.horse_high],[pt,pt-cr*ds,pt+cr*ds,pt-cr*hs,pt+cr*hs],atol=1e-7);points+=1
  modelchecks+=1
 for _,g in e.groupby(['topic',e.period.eq('all')]):assert np.allclose(g.BH_q,qvalues(g.date_p))
 print('FE verified',modelchecks,points,flush=True)
 f=pd.read_csv(HERE/'forecast01/features_with_form.csv',dtype={'horse_id':str,'jockey_id':str,'trainer_id':str},low_memory=False);p=pd.read_csv(HERE/'forecast01/predictions.csv',dtype={'horse_id':str,'jockey_id':str});past=pd.read_csv(HERE/'forecast01/past_H0_residuals.csv',dtype={'jockey_id':str});forecastchecks=0;maxpred=0.
 params=json.loads((HERE/'forecast01/past_H0_parameters.json').read_text())+json.loads((HERE/'forecast01/parameters.json').read_text())
 for m in params:
  g=f[f.year.eq(m['year'])];tr=f[f.race_date.le(m['cutoff'])];tm,pr=replay(g,m,tr)
  saved=p[(p.year==m['year'])&(p.model==m['model'])] if m['model']!='H0_history' else past[past.year.eq(m['year'])]
  saved=saved.set_index('api_record_id').loc[g.api_record_id];err=max(np.max(np.abs(tm-saved.time_prediction)),np.max(np.abs(pr-saved.prob_top3)));maxpred=max(maxpred,float(err));assert err<1e-7;forecastchecks+=2*len(g)
 print('Frozen forecasts replayed',forecastchecks,flush=True)
 old=pd.read_csv(OLD/'forecast01/predictions.csv',dtype={'jockey_id':str});old=old[old.model.eq('H0')].set_index('api_record_id');recent=past[past.year.ge(2024)].set_index('api_record_id').loc[old.index]
 assert np.allclose(recent.time_prediction,old.time_prediction) and np.allclose(recent.prob_top3,old.prob_top3)
 outcome=amap.loc[past.api_record_id];assert np.allclose(past.relative_time,outcome.relative_time) and np.allclose(past.top3,outcome.top3)
 windows=pd.read_csv(HERE/'forecast01/form_windows.csv',dtype={'jockey_id':str})
 assert np.allclose(past.time_adv,past.time_prediction-past.relative_time) and np.allclose(past.top3_excess,past.top3-past.prob_top3)
 for (ds,days),z in windows.groupby(['race_date','window']):
  cut=pd.Timestamp(ds)-pd.Timedelta(days=2);lo=(cut-pd.Timedelta(days=int(days)-1)).strftime('%Y-%m-%d');hi=cut.strftime('%Y-%m-%d');g=past[past.race_date.between(lo,hi)].groupby('jockey_id').agg(n=('api_record_id','size'),time_adv=('time_adv','mean'),top3_excess=('top3_excess','mean'),last_date=('race_date','max'));z=z.set_index('jockey_id').loc[g.index];minimum={90:20,180:40,365:80}[int(days)];eligible=g.n.ge(minimum)
  assert np.array_equal(z.n,g.n) and np.array_equal(z.eligible,eligible) and z.last_date.le(hi).all()
  for key in ['time_adv','top3_excess']:assert np.allclose(z[key],(g[key]*g.n/(g.n+50)).where(eligible),equal_nan=True)
 for days in [90,180,365]:
  z=windows[windows.window.eq(days)].set_index(['race_date','jockey_id']);ix=pd.MultiIndex.from_arrays([f.race_date,f.jockey_id]);z=z.reindex(ix)
  assert np.allclose(f[f'r{days}_n'],z.n.fillna(0))
  for key in ['time_adv','top3_excess']:assert np.allclose(f[f'r{days}_{key}'],z[key],equal_nan=True)
 print('Past-only form windows verified',len(windows),flush=True)
 p['mae']=(p.time_prediction-p.relative_time).abs();p['mse']=(p.time_prediction-p.relative_time)**2;p['logloss']=-(p.top3*np.log(p.prob_top3)+(1-p.top3)*np.log1p(-p.prob_top3));p['brier']=(p.prob_top3-p.top3)**2
 metrics=pd.read_csv(HERE/'forecast01/metrics.csv',dtype={'period':str});c=pd.read_csv(HERE/'forecast01/comparisons.csv',dtype={'period':str})
 for r in metrics.itertuples():
  g=p[(p.year.le(2025) if r.period=='2024_2025' else p.year.eq(2026))&p.model.eq(r.model)];rs=g.groupby('race_id')[['mae','mse','logloss','brier']].mean().mean();assert len(g)==r.starts and g.race_id.nunique()==r.races and np.allclose([r.mae_s,r.rmse_s,r.logloss,r.brier],[rs.mae,np.sqrt(rs.mse),rs.logloss,rs.brier])
 for r in c.itertuples():
  after,before=r.comparison.split('-');g=p[p.year.le(2025) if r.period=='2024_2025' else p.year.eq(2026)];old=g[g.model.eq(before)].set_index('api_record_id');new=g[g.model.eq(after)].set_index('api_record_id').loc[old.index];assert set(old.index)==set(new.index)
  z=old[['race_id','race_date','horse_id']].copy();z['delta']=new[r.metric]-old[r.metric];pt,lo,hi,pv=boot(z,'race_date');_,hl,hh,_=boot(z,'horse_id');assert np.allclose([r.delta,r.date_low,r.date_high,r.horse_low,r.horse_high,r.date_p],[pt,lo,hi,hl,hh,pv],atol=1e-7)
 assert np.allclose(c.BH_q,qvalues(c.date_p))
 raw=pd.read_csv(HERE/'effects02/raw_results.csv',dtype={'jockey_id':str,'period':str})
 for r in raw.itertuples():
  g=a if r.period=='all' else a[a.year.between(2024,2025)] if r.period=='2024_2025' else a[a.year.eq(2026)]
  if r.topic=='pace':g=g[g.pace_eligible]
  if r.topic=='stability':g=g[g.H1_time.notna()]
  if r.subset=='prior_front':g=g[g.own_prior_front.eq(1)]
  if r.subset=='actual_c4_front':g=g[g.c4_zone.eq('front')]
  if r.subset=='coverage100':g=g[g.HIST_coverage.eq(1)]
  g=g[g.jockey_id.eq(r.jockey_id)]
  if r.topic!='stability':g=g[g['outer' if r.topic=='outer' else 'pressure'].eq(r.context)]
  assert len(g)==r.starts
  for target in ['first_pack','front_pack2','fade3','g3f_rank','time','big_slow','slow_loss','absolute_error']:
   if target+'_n' in raw and pd.notna(getattr(r,target+'_n')):
    assert int(g[target].notna().sum())==getattr(r,target+'_n') and np.isclose(g[target].mean(),getattr(r,target+'_mean'),equal_nan=True)
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256']
 assert sha(ROOT/'jeju/data/jeju_native_core.sqlite3')==manifest['database_sha256']
 save(out/'verification.json',{'status':'passed','source_starts':len(a),'source_definitions_recomputed':True,'FE_models_verified':modelchecks,'FE_contrasts_and_cluster_intervals_recomputed':points,'maximum_normal_equation_error':maxnormal,'frozen_outcome_predictions_replayed':forecastchecks,'maximum_prediction_error':maxpred,'past_only_form_windows_recomputed':len(windows),'forecast_metric_rows_recomputed':len(metrics),'forecast_bootstrap_comparisons_recomputed':len(c),'raw_context_rows_recomputed':len(raw),'BH_verified':True,'all_prior_source_hashes_unchanged':True,'database_sha_unchanged':True})
 print('Verification passed',modelchecks,points,forecastchecks,len(windows),flush=True)
if __name__=='__main__':main()
