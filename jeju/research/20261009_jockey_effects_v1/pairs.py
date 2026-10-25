"""Future same-horse-distance contrasts using rider effects frozen before 2024."""
import json
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,ROOT,save
from effects import cluster

def main():
 out=HERE/'pairs01';out.mkdir(exist_ok=False)
 a=pd.read_csv(HERE/'input01/starts.csv',dtype={'horse_id':str,'jockey_id':str,'trainer_id':str},low_memory=False).set_index('api_record_id')
 scores=pd.read_csv(HERE/'effects01/jockey_effects.csv',dtype={'jockey_id':str});scores=scores[(scores.period=='past')&(scores.variant=='primary')&(scores.target=='time')].set_index('jockey_id').effect
 pr=pd.read_csv(HERE/'forecast01/predictions.csv',dtype={'horse_id':str,'jockey_id':str});pr=pr[pr.model.eq('H0')].set_index('api_record_id');pr['error']=pr.relative_time-pr.time_prediction
 pairs=pd.read_csv(ROOT/'jeju/research/20261009_jockey_research_feasibility_v1/audit01/same_horse_distance_pairs.csv',dtype={'horse_id':str,'jockey_id':str,'previous_jockey_id':str});pairs.previous_api_record_id=pairs.previous_api_record_id.astype(int)
 keep=pairs.api_record_id.isin(pr.index)&pairs.previous_api_record_id.isin(pr.index)&pairs.jockey_id.isin(scores.index)&pairs.previous_jockey_id.isin(scores.index)
 d=pairs[keep].copy();cur=a.loc[d.api_record_id].reset_index(drop=True);prev=a.loc[d.previous_api_record_id].reset_index(drop=True);d=d.reset_index(drop=True)
 d['frozen_score_gain']=d.jockey_id.map(scores)-d.previous_jockey_id.map(scores)
 d['error_delta']=pr.loc[d.api_record_id,'error'].to_numpy()-pr.loc[d.previous_api_record_id,'error'].to_numpy()
 for c in ['carried_weight_kg','body_kg','moisture','h_any_finish_rank_mean','h_any_relative_time_mean','h_same_relative_time_mean','gate_scaled']:
  d['delta_'+c]=cur[c]-prev[c]
 d['log_gap']=np.log1p(d.gap_days);d['grade_change']=cur.class_clean.ne(prev.class_clean).astype(float)
 d['score_group']=np.select([d.frozen_score_gain.ge(.15),d.frozen_score_gain.le(-.15)],['expected_faster','expected_slower'],default='within_0.15s')
 d.to_csv(out/'pairs_and_frozen_scores.csv',index=False,encoding='utf-8-sig');effects=[];groups=[]
 for period,g0 in [('2024_2025',d[d.year.le(2025)]),('2026',d[d.year.eq(2026)])]:
  for variant,g in [('all',g0),('changed_only',g0[g0.changed_jockey]),('similar_conditions',g0[g0.similar_measured_conditions])]:
   cols=['frozen_score_gain','log_gap','grade_change']+[c for c in d if c.startswith('delta_')];x=g[cols].copy()
   x=x.fillna(x.median()).fillna(0);sd=x.std(ddof=0);x=x[sd[sd>1e-12].index];x.insert(0,'intercept',1.)
   X=x.to_numpy();y=g.error_delta.to_numpy();beta=np.linalg.lstsq(X,y,rcond=1e-10)[0];bread=np.linalg.pinv(X.T@X,rcond=1e-12);res=y-X@beta;j=x.columns.get_loc('frozen_score_gain');df=len(g)-np.linalg.matrix_rank(X);crit=float(t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1))
   r={'period':period,'variant':variant,'pairs':len(g),'changed_pairs':int(g.changed_jockey.sum()),'horses':g.horse_id.nunique(),'days':g.race_date.nunique(),'slope_s_per_expected_faster_s':float(beta[j]),'meaning':'negative means prior estimated better rider aligns with better future relative-time residual change'}
   for name,key in [('date','race_date'),('horse','horse_id')]:
    v=cluster(X,res,bread,g[key],df);se=np.sqrt(max(0,v[j,j]));r[name+'_low']=float(beta[j]-crit*se);r[name+'_high']=float(beta[j]+crit*se)
   effects.append(r)
   for label,z in g.groupby('score_group'):groups.append({'period':period,'variant':variant,'group':label,'pairs':len(z),'mean_frozen_gain_s':z.frozen_score_gain.mean(),'mean_error_delta_s':z.error_delta.mean()})
 pd.DataFrame(effects).to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');pd.DataFrame(groups).to_csv(out/'score_groups.csv',index=False,encoding='utf-8-sig')
 save(out/'support.json',{'available_source_pairs':len(pairs),'pairs_with_both_annual_forecasts_and_past_known_jockeys':len(d),'past_rider_scores_cutoff':'2023-12-31','frozen_score_training_rows':34743,'warning':'frozen descriptive associations and nonrandom switching, not random treatment'})
 print(pd.DataFrame(effects).to_string(index=False),flush=True)
if __name__=='__main__':main()
