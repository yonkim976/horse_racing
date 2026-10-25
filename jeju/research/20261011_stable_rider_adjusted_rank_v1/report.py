"""Readable complete comparisons with explicit support and model failures."""
import json
import numpy as np
import pandas as pd
from data import HERE,save
def main():
 out=HERE/'report01';out.mkdir(exist_ok=False)
 s=pd.read_csv(HERE/'analysis01/support.csv',dtype={'period':str,'trainer_id':str,'jockey_id':str});a=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str});b=pd.read_csv(HERE/'supplement01/effects.csv',dtype={'period':str});models=json.loads((HERE/'analysis01/models.json').read_text())
 rows=s.copy();rows['primary_status']='insufficient_cohort_support'
 for m in models:
  if m['variant']=='primary':rows.loc[rows.period.eq(m['period'])&rows.cell.eq(m['cell']),'primary_status']=m['status']
 for label,df in [('individual',a[a.variant.eq('primary')]),('shared',b)]:
  for target in ['normalized10_gain','raw_rank_gain']:
   keep=['period','cell','effect','date_low','date_high','horse_low','horse_high','BH_q'];v=df[df.target.eq(target)][keep].rename(columns={k:label+'_'+target+'_'+k for k in keep if k not in ['period','cell']});rows=rows.merge(v,on=['period','cell'],how='left',validate='one_to_one')
 assert len(rows)==615 and rows.shared_normalized10_gain_effect.notna().sum()==52 and rows.individual_normalized10_gain_effect.notna().sum()==38
 rows.to_csv(out/'all_cells_with_support_and_comparisons.csv',index=False,encoding='utf-8-sig')
 cells=['002029:003089','002029:003080','002034:003089','002033:003082','002031:003087','002023:003096','002026:003080','002042:003094','002028:003095']
 examples=rows[rows.cell.isin(cells)];examples.to_csv(out/'previously_discussed_combinations.csv',index=False,encoding='utf-8-sig')
 repeat=pd.read_csv(HERE/'analysis01/repeat_checks.csv');decision={'status':'adjusted_rank_switch_vs_retained_completed_no_confirmed_advantage','eligible_recent_pairs':13672,'pairs_2024_2025':9970,'pairs_2026':3702,'period_end':'2026-09-19','partial_2026':True,'support_cells_2024_2025':41,'support_cells_2026':11,'individual_fitted_cells_2024_2025':30,'individual_fitted_cells_2026':8,'individual_primary_tests':76,'individual_positive_supported':int(a.positive_supported.sum()),'repeated_primary_positive':int(repeat.supported_both.sum()),'shared_slope_tests':len(b),'shared_exploratory_positive_supported':int(b.exploratory_positive_supported.sum()),'pure_causal_effect_identified':False,'intent_observed':False,'new_feature_forecast_gain_tested':False,'operationally_applied':False,'fixed_switch_bonus_adopted':False,'existing_research_pauses_preserved':True}
 save(HERE/'decision.json',decision)
 assert not a.positive_supported.any() and not b.exploratory_positive_supported.any()
 for r in rows[rows.shared_normalized10_gain_effect.notna()].itertuples():
  q=b[(b.period==r.period)&(b.cell==r.cell)&b.target.eq('normalized10_gain')];assert len(q)==1 and np.isclose(q.iloc[0].effect,r.shared_normalized10_gain_effect)
 save(out/'verification.json',{'status':'passed','all_cell_periods':len(rows),'discussed_cell_periods':len(examples),'individual_normalized_rows':38,'shared_normalized_rows':52,'unavailable_cells_explicit':True,'official_id_strings_preserved':True,'source_counts_effects_joined_by_period_cell_only':True})
 print('Adjusted rank reports saved',len(rows),len(examples),flush=True)
if __name__=='__main__':main()
