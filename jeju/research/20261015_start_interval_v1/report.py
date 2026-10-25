"""Reviewable cycle summaries, complete empty cells and research-only decision."""
import json
import numpy as np
import pandas as pd
from data import HERE,IDS,BINS,GROUPS,period_data,save
from analysis import raw_summary
LABELS={'1_7':'1~7일','8_14':'8~14일','15_21':'15~21일','22_28':'22~28일','15_28':'15~28일','29_42':'29~42일','43_60':'43~60일','61_90':'61~90일','91_180':'91~180일','181_plus':'181일 이상'}
def main():
 out=HERE/'report01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);v=a[a.gap_days.notna()];rows=[];complete=[]
 for period,g in period_data(v).items():
  for group in GROUPS:
   z=g[g.gap_group.eq(group)]
   if not len(z):rows.append({'period':period,'gap_group':group,'label':LABELS[group],'starts':0,'status':'no_selected_observations'});continue
   r={'period':period,'gap_group':group,'label':LABELS[group],'status':'observed',**raw_summary(z)};prev=z[z.previous_finish_position.between(1,89)];r['previous_normal_rank_n']=len(prev);r['previous_mean_rank']=prev.previous_finish_position.mean();r['current_mean_rank_paired']=prev.finish_position.mean();rows.append(r)
  for label in BINS:
   z=g[g.gap_bin.eq(label)];complete.append({'period':period,'gap_bin':label,'starts':len(z),'status':'observed' if len(z) else 'no_selected_observations'})
 raw=pd.DataFrame(rows);raw.to_csv(out/'raw_primary_groups.csv',index=False,encoding='utf-8-sig');pd.DataFrame(complete).to_csv(out/'complete_bin_support.csv',index=False,encoding='utf-8-sig')
 ef=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str,'distance':str});rep=pd.read_csv(HERE/'analysis01/repeat_checks.csv',dtype={'distance':str});models=json.loads((HERE/'analysis01/models.json').read_text());pool=ef[ef.distance.eq('pooled')&ef.variant.eq('primary')];pool.to_csv(out/'pooled_primary.csv',index=False,encoding='utf-8-sig');ef[ef.distance.ne('pooled')&ef.variant.eq('primary')&ef.gap_group.eq('8_14')].to_csv(out/'distance_8_14_comparisons.csv',index=False,encoding='utf-8-sig')
 assert sum(raw[raw.period.eq('all')].starts)==50209 and sum(raw[raw.period.eq('2026')].starts)==4482
 assert raw[raw.period.isin(['2024_2025','2026'])&raw.gap_group.eq('1_7')].starts.eq(0).all()
 repeated=rep[rep.repeated_supported];assert len(repeated)==3 and repeated.distance.eq('pooled').all() and repeated.gap_group.eq('8_14').all()
 decision={'status':'observed_interval_associations_completed_8to14_days_recent_repeated_no_fixed_correction','cohort_starts':len(a),'known_interval_starts':len(v),'unknown_prior_starts':int(a.gap_days.isna().sum()),'known_interval_horses':v.horse_id.nunique(),'period_start':a.race_date.min(),'period_end':'2026-09-19','partial_2026':True,'median_gap_days':v.gap_days.median(),'recent_2024_2025_starts':12269,'recent_2026_starts':4482,'pooled_primary_BH_tests':int((ef.variant.eq('primary')&ef.distance.eq('pooled')&ef.support).sum()),'distance_primary_BH_tests':int((ef.variant.eq('primary')&ef.distance.ne('pooled')&ef.support).sum()),'repeated_pooled_interval':'8_14_vs_15_28','repeated_pooled_targets':repeated.target.tolist(),'repeated_distance_targets':0,'no_recent_selected_1to7_day_rows':True,'individual_optimum_identified':False,'causal_recovery_effect_identified':False,'fixed_seconds_or_probability_bonus_adopted':False,'new_predictive_gain_tested':False,'operationally_applied':False,'database_written':False,'jockey_and_style_pauses_preserved':True}
 save(HERE/'decision.json',decision)
 save(out/'verification.json',{'status':'passed','raw_primary_group_period_cells':len(raw),'explicit_bin_support_cells':len(complete),'all_starts_count_reconciled':True,'recent_counts_reconciled':True,'absent_recent_short_interval_not_encoded_as_zero_performance':True,'repeated_targets_match_effect_tables':True,'held_models':[{'period':m['period'],'distance':m['distance'],'status':m['status']} for m in models if m['status']!='fitted']})
 print(raw[raw.period.eq('2026')][['label','starts','previous_mean_rank','finish_position_mean','rank_gain_mean','top3_pp_mean']].to_string(index=False),flush=True)
if __name__=='__main__':main()
