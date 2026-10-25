"""Make reviewable jockey summaries directly from verified tables."""
import json
import pandas as pd
from data import HERE,load,save
def main():
 out=HERE/'report01';out.mkdir(exist_ok=False);assert json.loads((HERE/'verification02/verification.json').read_text())['status']=='passed'
 e=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'jockey_id':str,'period':str});r=pd.read_csv(HERE/'analysis01/raw_primary.csv',dtype={'jockey_id':str,'period':str});s=pd.read_csv(HERE/'analysis01/support.csv',dtype={'jockey_id':str,'period':str});a,_=load();observed=set(a[a.year.eq(2026)].jockey_id);rows=[]
 for v in s[s.variant.eq('primary')].itertuples():
  d={'period':v.period,'jockey_id':v.jockey_id,'jockey_name':v.jockey_name,'observed_in_frozen_2026_cohort':v.jockey_id in observed,'primary_support':v.support,'support_reason':v.reason,'own_starts':v.positive_starts,'not_own_starts':v.negative_starts,'crossover_horses':v.crossover_horses,'strict_previous100_support':v.strict_previous100_support}
  for own,label in [(True,'own'),(False,'not_own')]:
   q=r[r.period.eq(v.period)&r.jockey_id.eq(v.jockey_id)&r.same_jockey.eq(own)]
   if len(q):d.update({label+'_top3_pct':q.iloc[0].top3_pp_mean,label+'_mean_finish':q.iloc[0].finish_position_mean,label+'_horses':int(q.iloc[0].horses)})
  for target,label in [('relative_time','seconds_faster'),('rank10_quality','rank10_better'),('top3_pp','top3_pp')]:
   q=e[e.variant.eq('primary')&e.period.eq(v.period)&e.jockey_id.eq(v.jockey_id)&e.target.eq(target)]
   if len(q):
    q=q.iloc[0]
    for field in ['effect','date_low','date_high','horse_low','horse_high','BH_q','direction_supported']:d[label+'_'+field]=q[field]
  rows.append(d)
 summary=pd.DataFrame(rows);summary.to_csv(out/'jockey_summary.csv',index=False,encoding='utf-8-sig');v=summary[summary.period.eq('all')&summary.observed_in_frozen_2026_cohort&summary.primary_support].copy();v['raw_top3_difference']=v.own_top3_pct-v.not_own_top3_pct;v=v.sort_values(['raw_top3_difference','jockey_id'],ascending=[False,True]).head(5);v.to_csv(out/'five_raw_improvement_examples.csv',index=False,encoding='utf-8-sig');save(out/'verification.json',{'status':'passed','summary_rows':len(summary),'examples':v.jockey_name.tolist(),'examples_rule':'Top5 raw Top3 improvement among primary-supported jockeys observed in frozen 2026 cohort; display only, not adjusted winners','unsupported_effects_not_filled_with_zero':True});print(v[['jockey_name','own_starts','not_own_starts','not_own_top3_pct','own_top3_pct','top3_pp_effect','top3_pp_date_low','top3_pp_date_high']].to_string(index=False),flush=True)
if __name__=='__main__':main()
