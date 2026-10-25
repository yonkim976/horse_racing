"""Independent full dummy least squares, variance, field proxies and support audit."""
import json
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,ROOT,SOURCE,PRED,ID_COLS,BASE,DELTA,CAT,EXTRA,sha,save
def reconstruct(g,tr,spec):
 raw=g[BASE].copy();raw['log_gap']=np.log1p(g.gap_days);raw['distance_changed']=g.race_distance_m.ne(g.previous_race_distance_m).astype(float);raw['grade_changed']=g.class_clean.ne(g.previous_class_clean).astype(float)
 for c in DELTA:raw['delta_'+c]=g[c]-g['previous_'+c]
 n=raw.fillna(spec['medians'])
 for c in raw:
  assert np.isclose(raw[c].median() if raw[c].notna().any() else 0,spec['medians'][c])
  if raw[c].isna().any():n[c+'_missing']=raw[c].isna().astype(float)
 cols=[]
 for c in spec['columns']:
  if c=='intercept':v=np.ones(len(g))
  elif c=='comparison':v=tr
  elif c in spec['means']:
   assert np.isclose(n[c].mean(),spec['means'][c]) and np.isclose(n[c].std(ddof=0),spec['sd'][c]);v=(n[c]-spec['means'][c])/spec['sd'][c]
  else:
   key=next(k for k in CAT if c.startswith(k+'_'));v=g[key].astype(str).eq(c[len(key)+1:]).astype(float)
  cols.append(np.asarray(v,float))
 return np.column_stack(cols)
def variance(X,res,bread,key,df,k):
 s=pd.DataFrame(X*res[:,None]);s['cluster']=np.asarray(key);score=s.groupby('cluster').sum().to_numpy();G=len(score)
 cov=bread@score.T@score@bread*(G/(G-1)*(len(X)-1)/df)
 return float(cov[k,k])
def bh(p):
 p=np.asarray(p);ix=np.argsort(p);r=np.empty(len(p));r[ix]=np.minimum(1,np.minimum.accumulate((p[ix]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1]);return r
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False);m=json.loads((HERE/'input01/source_manifest.json').read_text())
 for r in m['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 a=pd.read_csv(HERE/'input01/pairs.csv',dtype={c:str for c in ID_COLS},low_memory=False)
 pred=pd.read_csv(PRED);p=pred[pred.model.eq('H1')].copy();p['predicted_rank']=p.groupby('race_id').time_prediction.rank(method='average',ascending=True);p['predicted_rank10']=1+9*(p.predicted_rank-1)/(p.field_n-1);p=p.set_index('api_record_id')
 source=pd.read_csv(SOURCE,usecols=['api_record_id','race_id','h_any_finish_rank_mean','h_any_relative_time_mean','field_n','finish_position']+EXTRA,low_memory=False).set_index('api_record_id')
 for short,c in [('rank','h_any_finish_rank_mean'),('time','h_any_relative_time_mean')]:
  den=source[c].notna().groupby(source.race_id).transform('sum')-source[c].notna().astype(int);num=source[c].fillna(0).groupby(source.race_id).transform('sum')-source[c].fillna(0)
  assert np.allclose(source['opp_'+short+'_mean'],num/den.where(den>0),equal_nan=True)
 for prefix,key in [('', 'api_record_id'),('previous_','previous_api_record_id')]:
  for c in ['predicted_rank','predicted_rank10']:assert np.allclose(a[prefix+c],a[key].map(p[c]))
  assert np.allclose(a[prefix+'H1_time'],a[key].map(p.time_prediction))
  for c in EXTRA+['field_n','finish_position']:assert np.allclose(a[prefix+c],a[key].map(source[c]),equal_nan=True)
 assert np.allclose(a.raw_rank_gain,a.previous_finish_position-a.finish_position)
 assert np.allclose(a.normalized10_gain,9*((a.previous_finish_position-1)/(a.previous_field_n-1)-(a.finish_position-1)/(a.field_n-1)))
 audit=json.loads((ROOT/'jeju/research/20261009_jockey_effects_v1/forecast01/fit_audit.json').read_text())
 for r in audit:assert r['train_last']<=r['cutoff']<str(r['year'])+'-01-01'
 assert a.history_cutoff.lt(a.race_date).all()
 support=pd.read_csv(HERE/'analysis01/support.csv',dtype={'period':str});count=0
 for r in support.itertuples():
  z=a[a.year.le(2025)] if r.period=='2024_2025' else a[a.year.eq(2026)];g=z[z.cell.eq(r.cell)];c=g[g.changed_jockey];v=g[~g.changed_jockey]
  assert (len(c),len(v),g.horse_id.nunique(),g.race_date.nunique())==(r.changes,r.retained,r.horses,r.days)
  ok=len(c)>=20 and len(v)>=20 and g.horse_id.nunique()>=15 and g.race_date.nunique()>=15 and min(c.horse_id.nunique(),v.horse_id.nunique(),c.race_date.nunique(),v.race_date.nunique())>=10
  assert ok==r.qualified;count+=1
 effects=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str});groups=json.loads((HERE/'analysis01/models.json').read_text());checked=0;held={};maxbeta=0.;maxvar=0.
 for group in groups:
  if group['status']!='fitted':held[group['status']]=held.get(group['status'],0)+1;continue
  g=a.set_index('api_record_id').loc[group['row_ids']];tr=np.array(group['treatment']);assert np.array_equal(tr,g.cell.eq(group['cell']) if group['comparison']=='other_switches' else g.changed_jockey)
  X=reconstruct(g,tr,group['spec']);k=1;pen=np.r_[0.,0.,np.ones(X.shape[1]-2)]
  if group['horse_fe']:
   # Full unpenalized horse dummies, independently of the fitting code's demeaning.
   D=pd.get_dummies(g.horse_id,dtype=float).to_numpy();X=np.column_stack([X[:,1:],D]);pen=np.r_[0.,np.ones(X.shape[1]-D.shape[1]-1),np.zeros(D.shape[1])];k=0
  bread=np.linalg.inv(X.T@X+np.diag(pen))
  for model in group['models']:
   y=g[model['target']].to_numpy();AX=np.vstack([X,np.diag(np.sqrt(pen))]);ay=np.r_[y,np.zeros(X.shape[1])];beta=np.linalg.lstsq(AX,ay,rcond=1e-12)[0]
   expected=np.asarray(model['beta']);actual=beta[:len(expected)] if group['horse_fe'] else beta;err=float(np.max(np.abs(actual-expected)));assert err<1e-6;maxbeta=max(maxbeta,err)
   res=y-X@beta;assert np.max(np.abs(X.T@res-pen*beta))<1e-5
   dv=variance(X,res,bread,g.race_date,model['residual_df'],k);hv=variance(X,res,bread,g.horse_id,model['residual_df'],k);err=max(abs(dv-model['date_variance']),abs(hv-model['horse_variance']));assert err<1e-6;maxvar=max(maxvar,err)
   r=effects[(effects.period==group['period'])&(effects.cell==group['cell'])&(effects.variant==group['variant'])&(effects.target==model['target'])];assert len(r)==1;r=r.iloc[0]
   assert np.allclose([r.effect,r.date_low,r.date_high,r.horse_low,r.horse_high],[beta[k],beta[k]-model['crit']*np.sqrt(dv),beta[k]+model['crit']*np.sqrt(dv),beta[k]-model['crit']*np.sqrt(hv),beta[k]+model['crit']*np.sqrt(hv)])
   checked+=1
 primary=effects[effects.variant.eq('primary')];assert np.allclose(primary.BH_q,bh(primary.date_p))
 assert np.array_equal(primary.positive_supported,primary.BH_q.lt(.05)&primary.date_low.gt(0)&primary.horse_low.gt(0))
 repeats=pd.read_csv(HERE/'analysis01/repeat_checks.csv');assert not repeats.supported_both.any()
 save(out/'verification.json',{'status':'passed','input_pairs':len(a),'expected_rank_current_and_previous_reconstructed_from_original_H1_predictions':len(a)*2,'opponent_proxies_reconstructed_full_field':len(source)*2,'support_cells_recomputed':count,'all_model_outcomes_reestimated_full_dummy_augmented_least_squares':checked,'held_model_groups':held,'maximum_beta_difference':maxbeta,'maximum_variance_difference':maxvar,'primary_BH_tests_recomputed':len(primary),'primary_supported_positive':int(primary.positive_supported.sum()),'primary_supported_negative':int(primary.negative_supported.sum()),'repeated_supported_positive':int(repeats.supported_both.sum()),'source_hashes_bytes_unchanged':True,'annual_cutoffs_and_history_dates_verified':True,'database_opened':False,'operational_change':False})
 print('Adjusted rank verification passed',checked,'model outcomes',held,flush=True)
if __name__=='__main__':main()
