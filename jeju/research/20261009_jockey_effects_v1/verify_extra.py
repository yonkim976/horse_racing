"""Independently recalculate rider summaries, effect intervals and pair regressions."""
import json
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,save
from effects import cluster

def main():
 out=HERE/'verification_extra01';out.mkdir(exist_ok=False)
 models=json.loads((HERE/'effects01/models.json').read_text());e=pd.read_csv(HERE/'effects01/jockey_effects.csv',dtype={'jockey_id':str});effectchecks=0
 for m in models:
  ids=m['spec']['jockey_ids'];cols=m['spec']['jockey_columns'];I=np.zeros((len(ids),len(m['beta'])))
  for i,j in enumerate(ids):
   if j!=m['spec']['reference']:I[i,cols.index(j)]=1
  V=I-np.average(I,axis=0,weights=m['weights']);scale=1 if m['target']=='time' else 100;sign=-1 if m['target'] in ['time','g3f_rank'] else 1;V*=scale*sign
  g=e[(e.period==m['period'])&(e.variant==m['variant'])&(e.target==m['target'])].set_index('jockey_id').loc[ids];pt=V@np.array(m['beta']);assert np.allclose(pt,g.effect)
  for label in ['date','horse']:
   cov=np.array(m[label+'_cov']);se=np.sqrt(np.maximum(0,np.einsum('ij,jk,ik->i',V,cov,V)));assert np.allclose(pt-m['crit']*se,g[label+'_low']) and np.allclose(pt+m['crit']*se,g[label+'_high'])
  effectchecks+=len(g)
 pr=pd.read_csv(HERE/'forecast01/predictions.csv',dtype={'jockey_id':str});pr=pr[pr.model.eq('H0')].copy();rank=pr.groupby('race_id').prob_top3.rank(method='average',ascending=False);pr['high']=(3*(rank-1)<=pr.field_n-1).astype(int)
 assignment=pd.read_csv(HERE/'forecast01/assignment.csv',dtype={'jockey_id':str});assignmentchecks=0
 for r in assignment.itertuples():
  g=pr[pr.jockey_id.eq(r.jockey_id)&(pr.year.le(2025) if r.period=='2024_2025' else pr.year.eq(2026))]
  assert len(g)==r.starts and np.allclose([g.top3.mean(),g.prob_top3.mean(),g.high.mean(),(g.time_prediction-g.relative_time).mean()],[r.raw_top3,r.expected_top3,r.high_expected_share,r.time_advantage]);assignmentchecks+=1
 pairs=pd.read_csv(HERE/'pairs01/pairs_and_frozen_scores.csv',dtype={'horse_id':str});effects=pd.read_csv(HERE/'pairs01/effects.csv');pairchecks=0
 for r in effects.itertuples():
  g=pairs[pairs.year.le(2025) if r.period=='2024_2025' else pairs.year.eq(2026)];g=g[g.changed_jockey] if r.variant=='changed_only' else g[g.similar_measured_conditions] if r.variant=='similar_conditions' else g
  cols=['frozen_score_gain','log_gap','grade_change']+[c for c in pairs if c.startswith('delta_')];x=g[cols].copy();x=x.fillna(x.median()).fillna(0);sd=x.std(ddof=0);x=x[sd[sd>1e-12].index];x.insert(0,'intercept',1.)
  X=x.to_numpy();y=g.error_delta.to_numpy();beta=np.linalg.lstsq(X,y,rcond=1e-10)[0];j=x.columns.get_loc('frozen_score_gain');assert len(g)==r.pairs and np.isclose(beta[j],r.slope_s_per_expected_faster_s)
  bread=np.linalg.pinv(X.T@X,rcond=1e-12);df=len(g)-np.linalg.matrix_rank(X);crit=t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1)
  for name,key in [('date','race_date'),('horse','horse_id')]:
   cov=cluster(X,y-X@beta,bread,g[key],df);se=np.sqrt(max(0,cov[j,j]));assert np.allclose([beta[j]-crit*se,beta[j]+crit*se],[getattr(r,name+'_low'),getattr(r,name+'_high')])
  pairchecks+=1
 save(out/'verification.json',{'status':'passed','jockey_effect_points_and_cluster_intervals_recomputed':effectchecks,'assignment_rows_recomputed':assignmentchecks,'frozen_pair_regressions_and_intervals_recomputed':pairchecks})
 print('Additional verification passed',effectchecks,assignmentchecks,pairchecks,flush=True)
if __name__=='__main__':main()
