"""Every stable overview and descriptive paired-change uncertainty, without winner labels."""
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,ID_COLS,period_data,save
def main():
 out=HERE/'report03';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/pairs.csv',dtype={c:str for c in ID_COLS},low_memory=False);s=pd.read_csv(HERE/'input01/support.csv',dtype={'period':str,'trainer_id':str});ef=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str});sa=pd.read_csv(HERE/'supplement02/support.csv',dtype={'period':str,'trainer_id':str});raw=pd.read_csv(HERE/'analysis01/raw_all_cells.csv',dtype={'period':str});intervals=[];overview=[]
 for period in ['all','past','2024_2025','2026']:
  z=period_data(a,period)
  for cell,g in z[z.changed_jockey].groupby('cell'):
   if len(g)<20:continue
   delta=100*(g.top3-g.previous_top3);point=delta.mean();crit=t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1);row={'period':period,'cell':cell,'starts':len(g),'horses':g.horse_id.nunique(),'top3_gain_pp':point}
   for prefix,key in [('date','race_date'),('horse','horse_id')]:
    score=pd.DataFrame({'key':g[key],'res':delta-point}).groupby('key').res.sum();G=len(score);var=(score.pow(2).sum()/len(g)**2)*G/(G-1);se=np.sqrt(var);row[prefix+'_low']=point-crit*se;row[prefix+'_high']=point+crit*se
   intervals.append(row)
  for trainer,g in z.groupby('trainer_id'):
   c=g[g.changed_jockey];v=s[s.period.eq(period)&s.trainer_id.eq(trainer)];w=sa[sa.period.eq(period)&sa.trainer_id.eq(trainer)];fits=ef[ef.period.eq(period)&ef.variant.eq('primary')&ef.cell.str.startswith(trainer+':')]
   overview.append({'period':period,'trainer_id':trainer,'trainer_name':g.trainer_name.iloc[-1],'eligible_pairs':len(g),'changes':len(c),'changed_horses':c.horse_id.nunique(),'destination_riders':c.jockey_id.nunique(),'riders20changes':int(c.groupby('jockey_id').size().ge(20).sum()),'common_qualified_cells':int(v.qualified.sum()),'A_only_eligible_cells':len(w),'fitted_primary_contrasts':len(fits),'supported_positive_primary':int(fits.positive_supported.sum())})
 it=pd.DataFrame(intervals);it.to_csv(out/'raw_paired_top3_intervals.csv',index=False,encoding='utf-8-sig');assert sum(r['A_only_eligible_cells'] for r in overview if r['period']=='2026')==len(sa[sa.period.eq('2026')])
 pd.DataFrame(overview).to_csv(out/'every_trainer_overview.csv',index=False,encoding='utf-8-sig')
 cells=['002029:003089','002029:003080','002034:003089'];examples=raw[raw.cell.isin(cells)&raw.period.isin(['2024_2025','2026'])&raw.changed].merge(it.rename(columns={'top3_gain_pp':'interval_top3_gain_pp'}),on=['period','cell','starts','horses'],validate='one_to_one');assert len(examples)==6 and np.allclose(examples.top3_gain_pp,examples.interval_top3_gain_pp)
 # Join using stable keys after checking rate agreement; float columns are not identities.
 examples.to_csv(out/'descriptive_examples.csv',index=False,encoding='utf-8-sig')
 decision={'status':'stable_specific_switch_comparisons_completed_no_confirmed_intent_proxy','period_start':'2017-01-13','pair_start':'2017-01-20','period_end':'2026-09-19','partial_2026':True,'source_starts':52155,'eligible_same_relations_pairs':43024,'eligible_jockey_changes':18231,'pair_horses':2516,'pair_cells':674,'recent_H1_pairs_2024_2025':9970,'recent_H1_pairs_2026':3702,'primary_common_support_cells_2024_2025':42,'primary_common_support_cells_2026':9,'primary_tests':186,'primary_positive_supported':0,'A_only_tests':156,'A_only_positive_supported':0,'repeat_supported_specific_switch_pairs':0,'intent_directly_observed':False,'switch_reason_observed':False,'pure_causal_switch_effect_identified':False,'new_switch_feature_forecast_gain_tested':False,'fixed_switch_bonus_adopted':False,'operationally_applied':False,'jockey_broad_research_pause_preserved':True,'observational_raw_watchlist':['002029:003089','002034:003089','002029:003080'],'watchlist_posthoc_not_confirmed_or_prospective_rule':True}
 save(HERE/'decision.json',decision);save(out/'verification.json',{'status':'passed','trainer_period_rows':len(overview),'paired_interval_cells':len(it),'descriptive_examples':len(examples),'no_causal_or_intent_labels':True});print('Every trainer tables saved',len(overview),'intervals',len(it),flush=True)
if __name__=='__main__':main()
