"""Reaggregate every descriptive table and preserve the decision state."""
import json
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,IDS,save
def main():
 out=HERE/'report_verification01';out.mkdir(exist_ok=False)
 a=pd.read_csv(HERE/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);f=pd.read_csv(HERE/'input01/features.csv');g=a.join(f[f.window_days.eq(14)].set_index('api_record_id'),on='api_record_id');cells=0;cis=0
 for filename in ['raw_primary.csv','raw_distance.csv','raw_coverage.csv']:
  report=pd.read_csv(HERE/'analysis01'/filename,dtype={'period':str})
  for r in report.itertuples():
   z=g if r.period=='all' else g[g.year.between(2024,2025)] if r.period=='2024_2025' else g[g.year.eq(2026)]
   if filename=='raw_coverage.csv':
    z=z[z.training_rows.eq(0)] if r.coverage_group=='no_rows' else z[z.role_complete] if r.coverage_group=='role_complete' else z[z.unknown_type_rows.gt(0)]
   else:
    if r.comparison=='any_vs_nonjockey':z=z[z.role_complete&z.any_jockey.eq(bool(r.exposed))]
    else:z=z[z.identity_complete&z.any_jockey&z.same_jockey.eq(bool(r.exposed))]
    if filename=='raw_distance.csv':z=z[z.race_distance_m.eq(r.distance)]
   assert len(z)==r.starts and z.horse_id.nunique()==r.horses and z.race_id.nunique()==r.races and z.race_date.nunique()==r.days
   assert int(z.top3.sum())==r.top3_count and int(z.finish_position.eq(1).sum())==r.win_count and z.field_n.min()==r.field_min and z.field_n.max()==r.field_max
   for target in ['finish_position','top3_pp','relative_time','rank10_quality','H1_time_adv']:
    v=z[z[target].notna()];y=v[target];point=y.mean()
    if not len(v):continue
    assert np.isclose(point,getattr(r,target+'_mean'))
    for label,key in [('date','race_date'),('horse','horse_id')]:
     sums=(y-point).groupby(v[key]).sum();G=len(sums)
     if G<2:continue
     se=np.sqrt(np.square(sums).sum()*G/(G-1))/len(v);half=t.ppf(.975,G-1)*se;assert np.allclose([point-half,point+half],[getattr(r,target+'_'+label+'_low'),getattr(r,target+'_'+label+'_high')]);cis+=1
   cells+=1
  if filename=='raw_distance.csv':
   agg=report.groupby(['period','comparison','exposed']).starts.sum().sort_index();primary=pd.read_csv(HERE/'analysis01/raw_primary.csv').set_index(['period','comparison','exposed']).starts.sort_index();assert agg.equals(primary)
  if filename=='raw_coverage.csv':assert report.groupby('period').starts.sum().to_dict()=={'all':52155,'2024_2025':12739,'2026':4673}
 v=json.loads((HERE/'verification02/verification.json').read_text());assert v['status']=='passed'
 save(out/'verification.json',{'status':'passed','descriptive_cells_recomputed':cells,'cluster_intervals_recomputed':cis,'distance_totals_match_primary':True,'coverage_totals_match_all_starts':True})
 decision={'status':'jockey_direct_training_association_completed_no_stable_adjusted_advantage','period_start':'2017-01-13','period_end':'2026-09-19','partial_2026':True,'cohort_starts':52155,'training_rows':641228,'primary_complete_window_starts':34490,'primary_window_days':14,'cutoff':'T-2 after previous observed actual start','primary_any_positive':21414,'primary_any_negative':13076,'primary_same_positive':18492,'primary_other_jockey_negative':2922,'recent_2024_2025_complete':4730,'recent_2026_complete':1766,'recent_2026_unknown_type_windows':2907,'planned_primary_tests':18,'supported_primary_tests':v['primary_supported_tests'],'supported_H1_tests':v['H1_supported_tests'],'primary_direction_supported':v['primary_direction_supported'],'recent_repeated_supported':0,'same_vs_other_2026_held_negative_starts':77,'causal_training_effect_identified':False,'absence_of_all_jockey_training_proven':False,'new_predictive_gain_tested':False,'fixed_training_bonus_adopted':False,'operationally_applied':False,'database_written':False,'existing_jockey_and_style_revisit_later_preserved':True}
 save(HERE/'decision.json',decision);print('All descriptive tables verified',cells,cis,flush=True)
if __name__=='__main__':main()
