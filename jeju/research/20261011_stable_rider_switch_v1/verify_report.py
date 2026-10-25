"""Recalculate every stable support join and descriptive paired interval from source rows."""
import json
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,ID_COLS,period_data,save
def main():
 output=HERE/'report_verification.json';assert not output.exists();a=pd.read_csv(HERE/'input01/pairs.csv',dtype={c:str for c in ID_COLS},low_memory=False);it=pd.read_csv(HERE/'report03/raw_paired_top3_intervals.csv',dtype={'period':str});ov=pd.read_csv(HERE/'report03/every_trainer_overview.csv',dtype={'period':str,'trainer_id':str});sa=pd.read_csv(HERE/'supplement02/support.csv',dtype={'period':str,'trainer_id':str,'jockey_id':str});common=pd.read_csv(HERE/'input01/support.csv',dtype={'period':str,'trainer_id':str});raw=pd.read_csv(HERE/'analysis01/raw_all_cells.csv',dtype={'period':str})
 current=1-(a.finish_position-1)/(a.field_n-1);previous=1-(a.previous_finish_position-1)/(a.previous_field_n-1);assert np.allclose(current,a.rank_quality) and np.allclose(previous,a.previous_rank_quality) and np.array_equal(current.gt(previous+1e-10),a.rank_improved)
 for prefix in ['current','previous']:
  mask=a[prefix+'_rider_cutoff'].notna();assert (pd.to_datetime(a.loc[mask,'race_date'])-pd.to_datetime(a.loc[mask,prefix+'_rider_cutoff'])).dt.days.eq(2).all()
 for r in it.itertuples():
  g=period_data(a,r.period);g=g[g.cell.eq(r.cell)&g.changed_jockey];d=100*(g.top3-g.previous_top3);crit=t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1);assert len(g)==r.starts and g.horse_id.nunique()==r.horses and np.isclose(d.mean(),r.top3_gain_pp)
  for label,key in [('date','race_date'),('horse','horse_id')]:
   score={}
   for k,v in zip(g[key],d-d.mean()):score[k]=score.get(k,0.)+v
   G=len(score);se=np.sqrt(np.sum(np.array(list(score.values()))**2)*G/(G-1)/len(g)**2);assert np.allclose([getattr(r,label+'_low'),getattr(r,label+'_high')],[d.mean()-crit*se,d.mean()+crit*se])
 for r in ov.itertuples():
  g=period_data(a,r.period);g=g[g.trainer_id.eq(r.trainer_id)];assert len(g)==r.eligible_pairs and int(g.changed_jockey.sum())==r.changes
  s=sa[sa.period.eq(r.period)&sa.trainer_id.eq(r.trainer_id)];assert len(s)==r.A_only_eligible_cells
  v=common[common.period.eq(r.period)&common.trainer_id.eq(r.trainer_id)];assert int(v.qualified.sum())==r.common_qualified_cells
 assert ov[ov.period.eq('2026')].A_only_eligible_cells.sum()==14
 examples=pd.read_csv(HERE/'report03/descriptive_examples.csv',dtype={'period':str})
 for r in examples.itertuples():
  g=raw[raw.period.eq(r.period)&raw.cell.eq(r.cell)&raw.changed];assert len(g)==1;assert np.allclose([g.iloc[0].previous_top3,g.iloc[0].current_top3,g.iloc[0].H1_time_gain],[r.previous_top3,r.current_top3,r.H1_time_gain])
 assert json.loads((HERE/'supplement01/additional_models.json').read_text())==json.loads((HERE/'supplement02/additional_models.json').read_text())
 save(output,{'status':'passed','stable_period_support_joins_recomputed':len(ov),'paired_top3_intervals_recomputed':len(it),'descriptive_examples_verified':len(examples),'supplement_ID_correction_model_estimates_identical':True,'official_ID_leading_zeros_preserved':True,'T_minus2_rider_stat_cutoffs_verified':True,'rank_improvement_recomputed_from_finish_and_field_sizes':True})
 print('Report interval and stable support verification passed',flush=True)
if __name__=='__main__':main()
