"""Rebuild past-only late counts, independent labels, rates and model probabilities."""
import json
from datetime import date,timedelta
import numpy as np
import pandas as pd
from scipy.special import expit
from features import HERE,ROOT,PRE,OUT,sha,save,classify
from analyze import design

def subview(a,view,key):
 if view=='all':return a
 if view=='period':return a[a.year.isin([2024,2025])] if key=='2024_2025' else a[a.year.eq(2026)]
 if view=='year':return a[a.year.eq(int(key))]
 return a[a.race_distance_m.eq(int(key))]
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False)
 manifest=json.loads((HERE/'features01/source_manifest.json').read_text())
 assert all(sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'] for r in manifest['files'])
 a=pd.read_csv(HERE/'features01/start_features.csv',dtype={'horse_id':str},low_memory=False)
 src=pd.read_csv(OUT,dtype={'horse_id':str},usecols=['api_record_id','horse_id','race_id','race_date','race_distance_m','c4_rank_lo','g1f_rank_hi','finish_position'])
 src=src.set_index('api_record_id');trace=pd.read_csv(PRE/'history_lineage.csv',keep_default_na=False).set_index('api_record_id').loc[a.api_record_id]
 idx=a.set_index('api_record_id');windows=0;records=0
 for row in a.itertuples():
  cut=(date.fromisoformat(row.race_date)-timedelta(days=2)).isoformat();lower=(date.fromisoformat(row.race_date)-timedelta(days=730)).isoformat()
  for scope in ['any','same']:
   ids=[int(x) for x in trace.loc[row.api_record_id,scope+'_ids'].split('|') if x]
   h=src.loc[ids];assert len(h)<=10 and row.api_record_id not in ids
   assert h.horse_id.eq(row.horse_id).all() and h.race_date.between(lower,cut).all()
   if scope=='same':assert h.race_distance_m.eq(row.race_distance_m).all()
   valid=h.c4_rank_lo.notna()&h.g1f_rank_hi.notna();gain=(h.c4_rank_lo-h.g1f_rank_hi>=2)&valid
   p='h_'+scope+'_';assert idx.loc[row.api_record_id,p+'late_n']==valid.sum()
   assert idx.loc[row.api_record_id,p+'late_gain2']==gain.sum()
   assert np.isclose(idx.loc[row.api_record_id,p+'late_mean'],gain.sum()/valid.sum() if valid.any() else np.nan,equal_nan=True)
   windows+=1;records+=len(h)
 print('Late history counts verified',windows,flush=True)
 for scope in ['any','same']:
  p='h_'+scope+'_';e=a[p+'s1f_n'].ge(5)&a[p+'s1f_n'].ge(.6*a[p+'n'])
  front=a[p+'s1f_front_mean'].ge(.6-1e-12);first=a[p+'s1f_first_mean'].ge(.6-1e-12)
  for suffix,t in [('',.6),('40',.4)]:
   late=a[p+'late_n'].ge(5)&a[p+'late_gain2'].ge((t-1e-12)*a[p+'late_n'])
   back=(a[p+'s1f_middle_mean']+a[p+'s1f_rear_mean']).ge(.6-1e-12)
   expected=np.full(len(a),'other',dtype=object);expected[back&late]='closing';expected[front]='front';expected[front&first]='lead';expected[~e]='unknown'
   assert np.array_equal(expected,a['style_'+scope+suffix])
  leaders=a['style_'+scope].eq('lead').groupby(a.race_id).transform('sum');cover=e.groupby(a.race_id).transform('mean')
  assert np.array_equal(leaders,a['leaders_'+scope]) and np.allclose(cover,a['coverage_'+scope])
 prior=pd.read_csv(ROOT/'jeju/research/20261009_leading_style_position_top3_v1/run01/start_labels_and_outcomes.csv',usecols=['api_record_id','style_same60','style_any60']).set_index('api_record_id').loc[a.api_record_id]
 assert np.array_equal(a.style_same.eq('lead'),prior.style_same60) and np.array_equal(a.style_any.eq('lead'),prior.style_any60)
 assert np.array_equal(a.top3,src.loc[a.api_record_id].finish_position.le(3))
 changed=a.copy()
 for c in ['top3','finish_position','y_s1f_pack3','y_s1f_position4','c4_rank_lo','g1f_rank_hi']:changed[c]=np.nan
 for scope in ['any','same']:assert np.array_equal(classify(changed,scope),a['style_'+scope])
 checks=0
 configs={'any80':('any','any',.8),'any100':('any','any',1.),'same80':('same','same',.8),'closing40_any80':('any40','any',.8)}
 for file in ['actual_pack_rates','actual_strict_rates','crowd_rates']:
  rr=pd.read_csv(HERE/'run02'/(file+'.csv'),dtype={'key':str,'group':str})
  for r in rr.itertuples():
   if file=='crowd_rates':
    sty,scope,cov=configs[r.configuration];g=subview(a,r.view,r.key);g=g[g['coverage_'+scope].ge(cov-1e-12)&g['style_'+sty].eq(r.style)]
    exposure=g['leaders_'+scope];mask=exposure.ge(3) if r.group=='3plus' else exposure.ge(2) if r.group=='2plus' else exposure.eq(int(r.group))
   else:
    g=subview(a,r.view,r.key);g=g[g['style_'+r.scope].eq(r.style)]
    col='y_s1f_pack3' if file=='actual_pack_rates' else 'y_s1f_position4'
    mapval={'first':0,'second':1,'farther':2,'definite_lead':0,'definite_front':1,'middle':2,'rear':3}
    mask=g[col].eq(mapval[r.group]) if r.group in mapval else g[col].isna()
   h=g[mask];assert len(h)==r.starts and h.top3.sum()==r.top3
   assert not len(h) or np.isclose(h.top3.mean(),r.rate)
   checks+=1
 print('All output rate counts verified',checks,flush=True)
 preds=pd.read_csv(HERE/'run02/model_predictions.csv',dtype={'key':str,'horse_id':str});params=json.loads((HERE/'run02/model_parameters.json').read_text());models=0;maxerr=0.
 for par in params:
  sty,scope,cov=configs[par['configuration']];g=subview(a,par['view'],par['key']);g=g[g['coverage_'+scope].ge(cov-1e-12)&g['style_'+sty].eq(par['style'])].copy()
  g['exposure']=g['leaders_'+scope];g['coverage']=g['coverage_'+scope];X,designparams=design(g)
  assert X.columns.tolist()==par['model_columns'];beta=np.array(par['beta']);p=expit(X.to_numpy()@beta)
  pr=preds[(preds.configuration==par['configuration'])&(preds['style']==par['style'])&(preds.view==par['view'])&(preds.key==par['key'])].set_index('api_record_id').loc[g.api_record_id]
  assert np.allclose(p,pr.p,atol=1e-12);maxerr=max(maxerr,float(np.max(np.abs(p-pr.p))))
  assert np.abs(X.to_numpy().T@(g.top3.to_numpy()-p)).max()<.005
  mask=g.exposure.lt(g.exposure.max());xp=X.loc[mask].to_numpy(copy=True);j=X.columns.get_loc('exposure');xp[:,j]+=1/par['scale']['exposure']
  assert np.allclose(expit(xp@beta),pr.loc[g.loc[mask].api_record_id].p_plus1,atol=1e-12)
  models+=1
 effects=pd.read_csv(HERE/'run02/adjusted_effects.csv');fam=effects[(effects.configuration=='any80')&effects['style'].isin(['front','closing'])].sort_values('date_p')
 assert len(fam)==6
 q=np.minimum.accumulate((fam.date_p.to_numpy()*6/np.arange(1,7))[::-1])[::-1];assert np.allclose(np.minimum(q,1),fam.primary_BH_q)
 assert not a.horse_id.eq('3005648').any()
 assert all(sha(ROOT/r['path'])==r['sha256'] for r in manifest['files'])
 save(out/'verification.json',{'status':'passed','late_history_windows_recomputed':windows,'historical_records_checked':records,'rates_recomputed':checks,
   'model_probabilities_recomputed':len(preds),'models_verified':models,'maximum_probability_error':maxerr,'BH_family_including_unavailable':6,
   'same_and_any_leading_labels_match_previous_study':True,'current_outcome_perturbation_style_invariant':True,'source_hashes_unchanged':True,'database_opened':False})
 print('Independent verification passed',flush=True)
if __name__=='__main__':main()
