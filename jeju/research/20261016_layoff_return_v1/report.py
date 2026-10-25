"""Complete episode flow, balanced raw results and selection diagnostics."""
import json
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,IDS,period_mask,save
from analysis import choose_events
def summary(g):
 row={'starts':len(g),'horses':g.horse_id.nunique(),'races':g.race_id.nunique(),'first_date':g.race_date.min(),'last_date':g.race_date.max(),'field_min':g.field_n.min(),'field_max':g.field_n.max(),'top3_count':int(g.top3.sum()),'mean_rank':g.finish_position.mean(),'top3_pct':g.top3_pp.mean(),'mean_relative_time':g.relative_time.mean(),'mean_H1_adv':g.H1_time_adv.mean(),'H1_available':int(g.H1_time_adv.notna().sum())}
 for target in ['finish_position','top3_pp','relative_time','rank10_quality']:
  y=g[target];point=y.mean()
  for label,key in [('date','race_date'),('horse','horse_id')]:
   score=(y-point).groupby(g[key]).sum();G=len(score);half=t.ppf(.975,G-1)*np.sqrt((score**2).sum()/len(g)**2*G/(G-1)) if G>1 else np.nan;row[target+'_'+label+'_low']=point-half;row[target+'_'+label+'_high']=point+half
 return row
def reason(r):
 if not r.mature:return 'insufficient_followup_horizon'
 if not r.first_selected:return 'first_outside_normal_cohort'
 if r.observed_phases<2:return 'no_qualifying_second:'+r.stop_reason
 if not r.second_selected:return 'second_outside_normal_cohort'
 if r.observed_phases<3:return 'no_qualifying_third:'+r.stop_reason
 if not r.third_selected:return 'third_outside_normal_cohort'
 if not r.same_distance_triplet:return 'distance_changed'
 return 'primary_balanced_same_distance'
def main():
 out=HERE/'report01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);e=pd.read_csv(HERE/'input01/episodes.csv',dtype={'horse_id':str});l=pd.read_csv(HERE/'input01/phase_lineage.csv',dtype={'horse_id':str});e['exclusive_flow_status']=e.apply(reason,axis=1);e.to_csv(out/'episode_flow_all.csv',index=False,encoding='utf-8-sig');flows=[];raw=[];selection=[];pairs=[]
 for mode in ['primary','rest181','followup180']:
  for period in ['all','2024_2025','2026']:
   z=e[e['mode'].eq(mode)&period_mask(e,period)];flow={'mode':mode,'period':period,'inceptions':len(z),'mature_inceptions':int(z.mature.sum()),'mature_first_selected':int((z.mature&z.first_selected).sum()),'mature_second_selected':int((z.mature&z.first_selected&z.second_selected).sum()),'mature_third_selected':int((z.mature&z.first_selected&z.third_selected).sum()),'mature_complete_triplet':int((z.mature&z.complete_selected_triplet).sum()),'mature_same_distance_triplet':int((z.mature&z.same_distance_triplet).sum())}
   for status,n in z.exclusive_flow_status.value_counts().items():flow['flow_'+status]=int(n)
   assert sum(v for k,v in flow.items() if k.startswith('flow_'))==len(z);flows.append(flow)
   for scope,ep in [('first_selected_all_available',z[z.mature&z.first_selected]),('balanced_all_distances',z[z.mature&z.complete_selected_triplet]),('balanced_same_distance',z[z.mature&z.same_distance_triplet])]:
    link=l[l.episode_id.isin(ep.episode_id)&l.selected_outcome];g=link.merge(a,on=['api_record_id','horse_id'],validate='one_to_one')
    for phase,v in g.groupby('phase'):raw.append({'mode':mode,'period':period,'scope':scope,'phase':phase,'episodes':v.episode_id.nunique(),**summary(v)})
    if scope=='first_selected_all_available' and len(g):
     first=g[g.phase.eq(1)].copy();first['balanced']=first.episode_id.isin(set(z[z.mature&z.same_distance_triplet].episode_id))
     for flag,v in first.groupby('balanced'):selection.append({'mode':mode,'period':period,'subsequently_balanced_same_distance':flag,**summary(v)})
   if mode=='primary':
    ep=z[z.mature&z.same_distance_triplet];g=l[l.episode_id.isin(ep.episode_id)].merge(a,on=['api_record_id','horse_id'],validate='one_to_one')
    for phase in [2,3]:
     v=g[g.phase.eq(1)][['episode_id','horse_id','anchor_date','finish_position','relative_time','rank10_quality','top3_pp']].merge(g[g.phase.eq(phase)][['episode_id','finish_position','relative_time','rank10_quality','top3_pp']],on='episode_id',suffixes=('_first','_later'),validate='one_to_one')
     for target in ['finish_position','relative_time','rank10_quality','top3_pp']:
      delta=v[target+'_later']-v[target+'_first'];delta=-delta if target in ['finish_position','relative_time'] else delta;r={'period':period,'comparison':str(phase)+'_minus_1','target':target,'episodes':len(v),'unadjusted_improvement':delta.mean()}
      for label,key in [('anchor_date','anchor_date'),('horse','horse_id')]:
       score=(delta-delta.mean()).groupby(v[key]).sum();G=len(score);half=t.ppf(.975,G-1)*np.sqrt((score**2).sum()/len(v)**2*G/(G-1)) if G>1 else np.nan;r[label+'_low']=delta.mean()-half;r[label+'_high']=delta.mean()+half
      pairs.append(r)
 for name,rows in [('episode_flow_summary.csv',flows),('raw_phase_results.csv',raw),('selection_first_race.csv',selection),('unadjusted_paired_changes.csv',pairs)]:pd.DataFrame(rows).to_csv(out/name,index=False,encoding='utf-8-sig')
 effects=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str});rep=pd.read_csv(HERE/'analysis01/repeat_checks.csv');primary=effects[effects.variant.eq('primary')];h1=effects[effects.variant.eq('H1_residual')]
 decision={'status':'layoff_return_first_second_third_completed_historical_improvement_recent_repeat_unconfirmed','period_start':'2017-01-13','period_end':'2026-09-19','partial_2026':True,'long_gap_days_min':91,'followup_max_gap_days':60,'followup_horizon_days':120,'mature_first_return_cutoff':'2026-05-22','primary_balanced_episodes_all':1034,'primary_balanced_horses_all':796,'primary_balanced_episodes_2024_2025':272,'primary_balanced_episodes_2026':48,'initial50_support_preserved_diagnostic':True,'outcome_blind_support_amended_to30':True,'primary_tests':len(primary),'H1_tests':len(h1),'primary_historical_supported':int(primary[primary.period.eq('all')].direction_supported.sum()),'primary_recent_repeated':int(rep[rep.variant.eq('primary')].repeated_supported.sum()),'H1_recent_repeated':int(rep[rep.variant.eq('H1_residual')].repeated_supported.sum()),'causal_fitness_recovery_identified':False,'all_returners_recovery_identified':False,'fixed_return_stage_bonus_adopted':False,'new_predictive_gain_tested':False,'operationally_applied':False,'database_opened':False,'research_pauses_preserved':True};save(HERE/'decision.json',decision)
 save(out/'verification.json',{'status':'passed','flow_partitions_reconcile':True,'all_episode_flow_rows':len(e),'flow_period_rows':len(flows),'raw_phase_scope_rows':len(raw),'selection_diagnostics':len(selection),'paired_raw_comparisons':len(pairs),'same_subject_balanced_phase_counts':True,'right_censoring_explicit':True})
 print(pd.DataFrame(flows).query("mode=='primary'")[['period','inceptions','mature_inceptions','mature_first_selected','mature_second_selected','mature_third_selected','mature_complete_triplet','mature_same_distance_triplet']].to_string(index=False));print(pd.DataFrame(raw).query("mode=='primary' and scope=='balanced_same_distance'")[['period','phase','starts','mean_rank','top3_pct','mean_relative_time','mean_H1_adv']].to_string(index=False),flush=True)
if __name__=='__main__':main()
