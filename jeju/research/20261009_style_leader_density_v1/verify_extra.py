"""Verify additional exploratory aggregations and within-race normal equations."""
import json
import pandas as pd
import numpy as np
from features import HERE,save
from analyze import NUM,design

def main():
 out=HERE/'verification_extra01';out.mkdir(exist_ok=False)
 a=pd.read_csv(HERE/'features01/start_features.csv',dtype={'horse_id':str},low_memory=False);a=a[a.coverage_any.ge(.8-1e-12)].copy()
 races=pd.read_csv(HERE/'explore01/race_diagnostic.csv');summary=pd.read_csv(HERE/'explore01/summary.csv',dtype={'period':str,'leaders':str});lookup=a.groupby('race_id')
 for r in races.itertuples():
  g=lookup.get_group(r.race_id);assert r.first_leaders==int((g.style_any.eq('lead')&g.y_s1f_pack3.eq(0)).sum());assert r.all_actual_known==g.y_s1f_pack3.notna().all()
 for r in summary.itertuples():
  g=races if r.period=='all' else races[races.year.isin([2024,2025])] if r.period=='2024_2025' else races[races.year.eq(2026)]
  g=g[g.all_actual_known];g=g[g.leaders.ge(3) if r.leaders=='3plus' else g.leaders.eq(int(r.leaders))]
  assert len(g)==r.races and g.first_leaders.ge(2).sum()==r.two_or_more_prior_leaders_in_actual_first_pack
 a=a[a.style_any.isin(['lead','front','closing'])]
 params=json.loads((HERE/'relative01/parameters.json').read_text());rr=pd.read_csv(HERE/'relative01/residuals.csv',dtype={'period':str});effects=pd.read_csv(HERE/'relative01/effects.csv',dtype={'period':str})
 for par in params:
  period=par['period'];g=a if period=='all' else a[a.year.isin([2024,2025])] if period=='2024_2025' else a[a.year.eq(2026)]
  g=g.copy();g['exposure']=g.leaders_any;g['coverage']=g.coverage_any;x,dp=design(g)
  x=x[[c for c in x if c in NUM and c not in ['exposure','field_n','moisture','coverage'] or c.endswith('_missing')]].copy()
  for sty in ['front','closing']:x['style_'+sty]=g.style_any.eq(sty).astype(float);x['interaction_'+sty]=g.style_any.eq(sty)*g.leaders_any
  x=x-x.groupby(g.race_id).transform('mean');x=x[par['columns']];y=g.top3-g.groupby('race_id').top3.transform('mean');pred=x.to_numpy()@np.array(par['beta']);res=y.to_numpy()-pred
  stored=rr[rr.period.eq(period)].set_index('api_record_id').loc[g.api_record_id]
  assert np.allclose(pred,stored.demeaned_fit) and np.allclose(res,stored.residual)
  assert np.abs(x.to_numpy().T@res).max()<1e-7
  for sty in ['front','closing']:
   e=effects[effects.period.eq(period)&effects.contrast.eq(sty+'_minus_lead')].iloc[0];j=x.columns.get_loc('interaction_'+sty)
   assert np.isclose(e.relative_delta_pp_per_leader,100*par['beta'][j])
 fam=effects.sort_values('date_p');q=np.minimum.accumulate((fam.date_p.to_numpy()*6/np.arange(1,7))[::-1])[::-1];assert np.allclose(np.minimum(q,1),fam.exploratory_BH_q)
 paired=pd.read_csv(HERE/'relative02/paired_races.csv',dtype={'period':str});pairsummary=pd.read_csv(HERE/'relative02/paired_raw_summary.csv',dtype={'period':str,'leaders':str})
 for r in pairsummary.itertuples():
  g=paired[paired.period.eq(r.period)];g=g[g.leaders_any.ge(3) if r.leaders=='3plus' else g.leaders_any.eq(int(r.leaders))]
  assert len(g)==r.paired_races and np.isclose(100*g.delta.mean(),r.race_mean_front_minus_lead_pp)
 minimal=pd.read_csv(HERE/'relative02/minimal_adjustment.csv',dtype={'period':str})
 for period,g in [('all',a),('2024_2025',a[a.year.isin([2024,2025])]),('2026',a[a.year.eq(2026)])]:
  x=g[['gate_scaled','carried_weight_kg']].copy();x=x.fillna(x.median())
  for sty in ['front','closing']:x['style_'+sty]=g.style_any.eq(sty).astype(float);x['interaction_'+sty]=g.style_any.eq(sty)*g.leaders_any
  x=x-x.groupby(g.race_id).transform('mean');y=g.top3-g.groupby('race_id').top3.transform('mean');beta=np.linalg.lstsq(x.to_numpy(),y.to_numpy(),rcond=1e-12)[0]
  for sty in ['front','closing']:
   row=minimal[minimal.period.eq(period)&minimal.contrast.eq(sty+'_minus_lead')].iloc[0]
   assert np.isclose(100*beta[x.columns.get_loc('interaction_'+sty)],row.relative_delta_pp_per_leader)
 save(out/'verification.json',{'status':'passed','exploratory_races_recomputed':len(races),'relative_models_normal_equations_verified':len(params),
   'relative_model_rows_recomputed':len(rr),'exploratory_BH_verified':True,'minimal_model_coefficients_verified':True,
   'paired_race_summaries_recomputed':len(pairsummary),'explicit_post_primary_exploration':True})
 print('Exploratory verification passed',flush=True)
if __name__=='__main__':main()
