"""Recompute temporal definitions, normal equations, contrasts and uncertainty."""
import json
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,ROOT,OLD,sha,save
from closing import project

def covariance(X,res,bread,key,df):
 keys=np.unique(key);scores=np.stack([(X[np.asarray(key)==k]*res[np.asarray(key)==k,None]).sum(axis=0) for k in keys])
 return bread@scores.T@scores@bread*(len(keys)/(len(keys)-1)*(len(X)-1)/df)
def qvalues(p):
 p=np.asarray(p);order=np.argsort(p);out=np.empty(len(p));last=1.
 for j in range(len(p)-1,-1,-1):last=min(last,p[order[j]]*len(p)/(j+1));out[order[j]]=last
 return out
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False)
 a=pd.read_csv(HERE/'input01/starts.csv',dtype={'horse_id':str,'jockey_id':str,'trainer_id':str,'owner_id':str,'previous_jockey_id':str,'previous_trainer_id':str,'previous_owner_id':str},low_memory=False)
 manifest=json.loads((HERE/'input01/source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'],r['path']
 assert sha(ROOT/'jeju/data/jeju_native_core.sqlite3')==manifest['database_sha256_after']==manifest['database_sha256_before']
 assert len(a)==52155 and a.race_id.nunique()==5206 and not a.horse_id.eq('3005648').any()
 trace=pd.read_csv(ROOT/'jeju/research/20261008_gate_region_pace_prediction_v2/features01/history_lineage.csv',keep_default_na=False).set_index('api_record_id')
 amap=a.set_index('api_record_id');history_count=0
 for r in a.itertuples():
  ix=[int(v) for v in trace.loc[r.api_record_id,'any_ids'].split('|')] if trace.loc[r.api_record_id,'any_ids'] else []
  h=amap.loc[ix];assert h.race_date.le(r.history_cutoff).all()
  assert int(h.g3f_rank.notna().sum())==r.h_g3f_rank_n
  assert np.isclose(h.g3f_rank.mean(),r.h_g3f_rank_mean,equal_nan=True)
  assert int(h.late_gain.notna().sum())==r.h_any_late_n
  assert np.isclose(h.late_gain.mean(),r.h_any_late_mean,equal_nan=True)
  history_count+=len(ix)
 back=a.h_any_s1f_n.ge(5)&a.h_any_s1f_n.ge(.6*a.h_any_n)&(a.h_any_s1f_middle_mean+a.h_any_s1f_rear_mean).ge(.6-1e-12)
 assert back.eq(a.back).all()
 for threshold,column in [(.6,'style_any'),(.4,'style_any40')]:
  closing=back&a.h_any_late_n.ge(5)&a.h_any_late_mean.ge(threshold-1e-12)
  assert closing.eq(a[column].eq('closing')).all()
 st=pd.read_csv(HERE/'input01/prior365_jockey_stats.csv',dtype={'jockey_id':str})
 for ds,z in st.groupby('race_date'):
  cutoff=pd.Timestamp(ds)-pd.Timedelta(days=2);lo=(cutoff-pd.Timedelta(days=364)).strftime('%Y-%m-%d');hi=cutoff.strftime('%Y-%m-%d')
  h=a[a.race_date.between(lo,hi)].groupby('jockey_id').top3.agg(['count','sum','mean']);z=z.set_index('jockey_id').loc[h.index]
  assert np.array_equal(z.n,h['count']) and np.array_equal(z.top3_count,h['sum']) and np.allclose(z.rate,h['mean'])
  q=h.loc[h['count'].ge(100),'mean'].quantile(.75)
  assert np.allclose(z.top_quartile_cutoff,q,equal_nan=True)
  assert np.array_equal(z.upper,h['count'].ge(100)&h['mean'].ge(q))
  assert z.last_date.le(hi).all()
 stats=st.set_index(['race_date','jockey_id'])
 for side,idcol in [('current','jockey_id'),('previous','previous_jockey_id')]:
  keys=pd.MultiIndex.from_arrays([a.race_date,a[idcol]])
  ref=stats.reindex(keys)
  for c in ['n','rate','top_quartile_cutoff']:assert np.allclose(a[side+'_rider_'+c],ref[c],equal_nan=True)
 ordered=a.sort_values(['horse_id','race_date','api_record_id']);prev=ordered.groupby('horse_id').api_record_id.shift()
 assert np.allclose(ordered.previous_api_record_id,prev,equal_nan=True)
 assert np.allclose(a.gap_days,(pd.to_datetime(a.race_date)-pd.to_datetime(a.previous_race_date)).dt.days,equal_nan=True)
 assert np.array_equal(a.rider_stats_valid,a.current_rider_n.ge(100)&a.previous_rider_n.ge(100))
 for c,th in [('upgrade',.05),('upgrade10',.1)]:
  expected=a.changed_jockey&a.rider_stats_valid&a.current_rider_upper.fillna(False).astype(bool)&(a.current_rider_rate-a.previous_rider_rate).ge(th-1e-12)
  assert expected.eq(a[c]).all()
 assert a.same_relations.eq(a.trainer_id.eq(a.previous_trainer_id)&a.owner_id.eq(a.previous_owner_id)&a.owner_id.ne('unknown')).all()
 sourcepr=pd.read_csv(OLD/'forecast01/predictions.csv').set_index(['model','api_record_id'])
 for model in ['H0','H1']:
  valid=a[model+'_prob'].notna();g=a[valid];p=sourcepr.loc[model].loc[g.api_record_id]
  assert np.allclose(g[model+'_prob'],p.prob_top3) and np.allclose(g[model+'_time'],p.time_prediction)
  assert np.allclose(g[model+'_top3_excess'],100*(g.top3-g[model+'_prob']))
  assert np.allclose(g[model+'_time_adv'],g[model+'_time']-g.relative_time)
  # Changing current outcomes cannot change the inputs or upgrade classification.
  altered=g.copy();altered['top3']=1-g.top3;altered['relative_time']=-g.relative_time
  for c in ['upgrade','upgrade10','back','H0_prob','H1_prob','current_rider_rate','previous_rider_rate']:assert altered[c].equals(g[c])
 effects=pd.read_csv(HERE/'closing01/effects.csv',dtype={'jockey_id':str});fitted=pd.read_csv(HERE/'closing01/fitted.csv').set_index(['period','target','api_record_id']);modelchecks=0;pointchecks=0;maxnormal=0.
 for m in json.loads((HERE/'closing01/models.json').read_text()):
  g=amap.loc[m['row_ids']].copy();cols={}
  for c in m['columns']:
   if c.startswith('main='):v=g.jockey_id.eq(c[5:]).astype(float)
   elif c.startswith('back='):v=(g.jockey_id.eq(c[5:])&g.back).astype(float)
   else:
    if c.startswith('trainer_'):v=g.trainer_id.eq(c[8:]).astype(float)
    elif c.endswith('_missing'):v=g[c[:-8]].isna().astype(float)
    else:v=g[c].astype(float).fillna(m['nuisance_medians'][c])
    v=(v-m['nuisance_means'][c])/m['nuisance_sd'][c]
   cols[c]=v
  X=pd.DataFrame(cols,index=g.index).to_numpy();z,lu,info=project(g,'horse_distance');xr=X-z@lu.solve(np.asarray(z.T@X));beta=np.asarray(m['beta']);y=g[m['target']].to_numpy();fit=X@beta+z@np.asarray(m['alpha']);res=y-fit
  check=fitted.loc[(m['period'],m['target'])].loc[g.index];assert np.allclose(check['fit'],fit,atol=1e-7) and np.allclose(check.residual,res,atol=1e-7)
  nj=len(m['maincols'])+len(m['intercols']);pen=np.r_[np.zeros(nj),np.ones(X.shape[1]-nj)]
  err=max(np.max(np.abs(z.T@res)),np.max(np.abs(X.T@res-pen*beta)));maxnormal=max(maxnormal,float(err));assert err<1e-5
  bread=np.linalg.inv(xr.T@xr+np.diag(pen));dc=covariance(xr,res,bread,g.race_date.to_numpy(),m['residual_df']);hc=covariance(xr,res,bread,g.horse_id.to_numpy(),m['residual_df'])
  assert np.allclose(dc,m['date_cov'],atol=1e-7) and np.allclose(hc,m['horse_cov'],atol=1e-7)
  levels=m['levels'];weights=g[g.back].jockey_id.value_counts(normalize=True).reindex(levels).fillna(0).to_numpy();M=np.zeros((len(levels),X.shape[1]));I=M.copy()
  for i,k in enumerate(levels):
   if k in m['maincols']:M[i,m['maincols'].index(k)]=1
   if k in m['intercols']:I[i,len(m['maincols'])+m['intercols'].index(k)]=1
  for contrast,V in [('back_effect',M+I),('back_specific',I)]:
   V=V-np.average(V,axis=0,weights=weights)
   for r in effects[(effects.period==m['period'])&(effects.target==m['target'])&(effects.contrast==contrast)].itertuples():
    vec=V[levels.index(r.jockey_id)]*((-1 if m['target'] in ['time','g3f_rank'] else 1)*(1 if m['target']=='time' else 100));p=float(vec@beta)
    ds=np.sqrt(max(0,vec@dc@vec));hs=np.sqrt(max(0,vec@hc@vec));cr=m['crit']
    assert np.allclose([r.effect,r.date_low,r.date_high,r.horse_low,r.horse_high],[p,p-cr*ds,p+cr*ds,p-cr*hs,p+cr*hs],atol=1e-7)
    pointchecks+=1
  modelchecks+=1
 for mask in [effects.period.eq('all'),effects.period.ne('all')]:assert np.allclose(effects.loc[mask,'BH_q'],qvalues(effects.loc[mask,'date_p']))
 switch=pd.read_csv(HERE/'switch01/effects.csv');switchchecks=0
 for bundle in json.loads((HERE/'switch01/models.json').read_text()):
  for m in bundle.get('models',[]):
   g=amap.loc[m['row_ids']];s=m['spec'];vals={}
   for c in s['nuisance_medians']:
    if c=='log_gap':v=np.log1p(g.gap_days)
    elif c=='distance_changed':v=g.race_distance_m.ne(g.previous_race_distance_m).astype(float)
    elif c=='grade_changed':v=g.class_clean.ne(g.previous_class_clean).astype(float)
    elif c=='relations_changed':v=(~g.same_relations).astype(float)
    elif c.startswith('delta_'):v=g[c[6:]]-g['previous_'+c[6:]]
    else:v=g[c]
    vals[c]=v.astype(float)
   xx=[]
   for c in s['columns']:
    if c=='intercept':v=np.ones(len(g))
    elif c=='upgrade':v=g[m['upgrade_column']].astype(float)
    elif c in s['nuisance_means']:
     v=vals[c[:-8]].isna().astype(float) if c.endswith('_missing') else vals[c].fillna(s['nuisance_medians'][c])
     v=(v-s['nuisance_means'][c])/s['nuisance_sd'][c]
    else:
     key=next(k for k in ['year','month','race_distance_m','class_clean','trainer_id','owner_id'] if c.startswith(k+'_'));v=g[key].astype(str).eq(c[len(key)+1:]).astype(float)
    xx.append(np.asarray(v))
   X=np.column_stack(xx);y=g[m['target']].to_numpy();pen=np.r_[0.,0.,np.ones(X.shape[1]-2)]
   augmented=np.vstack([X,np.diag(np.sqrt(pen))]);b=np.linalg.lstsq(augmented,np.r_[y,np.zeros(X.shape[1])],rcond=1e-10)[0]
   assert np.allclose(b,m['beta'],atol=1e-7);res=y-X@b;bread=np.linalg.inv(X.T@X+np.diag(pen));r=switch[(switch.period==m['period'])&(switch.variant==m['variant'])&(switch.target==m['target'])].iloc[0]
   for label,key in [('date','race_date'),('horse','horse_id')]:
    cov=covariance(X,res,bread,g[key].to_numpy(),m['residual_df']);se=np.sqrt(max(0,cov[1,1]));assert np.allclose([r[label+'_low'],r[label+'_high']],[b[1]-m['crit']*se,b[1]+m['crit']*se],atol=1e-7)
   switchchecks+=1
 ix=switch.variant.eq('same_relations_changed');assert np.allclose(switch.loc[ix,'BH_q'],qvalues(switch.loc[ix,'date_p']))
 raw=pd.read_csv(HERE/'switch01/raw_results.csv');eligible=pd.read_csv(HERE/'switch01/eligible_pairs.csv')
 for r in raw.itertuples():
  g=eligible[eligible.year.le(2025) if r.period=='2024_2025' else eligible.year.eq(2026)]
  if r.variant=='same_relations':g=g[g.same_relations]
  g=g[g.switch_group.eq(r.group)];assert len(g)==r.starts and int(g.top3.sum())==r.top3_count
  assert np.allclose([r.raw_top3,r.H0_expected_top3,r.H1_expected_top3,r.previous_top3],[g.top3.mean(),g.H0_prob.mean(),g.H1_prob.mean(),g.previous_top3.mean()])
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256']
 save(out/'verification.json',{'status':'passed','source_starts':len(a),'history_edges_recomputed':history_count,'prior365_stats_recomputed':len(st),'previous_selected_start_and_upgrade_definitions_checked':len(a),'closing_FE_models_verified':modelchecks,'closing_contrasts_and_cluster_intervals_recomputed':pointchecks,'maximum_normal_equation_error':maxnormal,'switch_models_verified_by_augmented_least_squares':switchchecks,'switch_raw_rows_recomputed':len(raw),'BH_recomputed':True,'current_outcome_perturbation_preserves_classification':True,'database_sha_unchanged':True,'all_source_hashes_unchanged':True})
 print('Verification passed',modelchecks,pointchecks,switchchecks,flush=True)
if __name__=='__main__':main()
