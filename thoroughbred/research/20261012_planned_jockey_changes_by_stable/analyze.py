"""Frozen study50 identities and methods, stratified by documented card/change status."""
from pathlib import Path
import importlib.util,json
import pandas as pd,numpy as np
H=Path(__file__).resolve().parent;R=H.parent;O=H/'outputs'
spec=importlib.util.spec_from_file_location('study50',R/'20261012_jockey_switch_trainer_intent/analyze.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
def save(name,rows):pd.DataFrame(rows).to_csv(O/name,index=False)
def main():
 d=pd.read_parquet(O/'classified_starts.parquet');rank=pd.read_csv(R/'20261012_jockey_switch_trainer_intent/outputs/annual_jockey_rankings.csv',dtype={'jockey_id':str})
 lookup=rank.rename(columns={'evaluation_year':'year','jockey_id':'scheduled_id'})[['year','meet','scheduled_id','score','eligible','top']].rename(columns={c:'scheduled_'+c for c in ['score','eligible','top']});d=d.merge(lookup,on=['year','meet','scheduled_id'],how='left',validate='many_to_one')
 d['scheduled_quality_delta']=d.current_score-d.scheduled_score
 metrics=[];stable=[];pairs=[];late=[];effects=[];diags=[]
 for window,allg in old.period(d):
  valid=allg[allg.main_eligible];planned=valid[valid.classification.eq('planned_as_card')]
  for meet,g in [('전체',planned)]+list(planned.groupby('meet')):
   for cat,s in g.groupby('category'):metrics.append(dict(window=window,meet=meet,category=cat,**old.metrics(s)))
  for (meet,tid),g in planned.groupby(['meet','trainer_id']):
   for cat,s in [('all',g)]+list(g.groupby('category')):
    stable.append(dict(window=window,meet=meet,trainer_id=tid,trainer_name=g.trainer_name.iloc[-1],category=cat,**old.metrics(s)))
  for (meet,tid,jid),g in planned[planned.changed].groupby(['meet','trainer_id','jockey_id']):
   pairs.append(dict(window=window,meet=meet,trainer_id=tid,trainer_name=g.trainer_name.iloc[-1],jockey_id=jid,jockey_name=g.jockey_name.iloc[-1],report_supported=len(g)>=30 and g.horse_id.nunique()>=15 and g.source_key.nunique()>=20,**old.metrics(g)))
  for population,g0 in [('all_normal',allg[allg.normal_outcome]),('same_stable_comparable',valid)]:
   g=g0[g0.classification.eq('post_card_change')]
   for meet,mg in [('전체',g)]+list(g.groupby('meet')):
    for reason,s in [('all',mg)]+list(mg.groupby('reason_class')):
     if len(s):late.append(dict(window=window,population=population,meet=meet,reason_class=reason,planned_switch_before_replacement=int(s.scheduled_differs_previous.eq(True).sum()),scheduled_quality_supported=int(s.scheduled_eligible.eq(True).sum()),scheduled_to_actual_score_delta=s.scheduled_quality_delta.mean(),**old.metrics(s)))
  for (meet,tid),g in allg[allg.normal_outcome&allg.classification.eq('post_card_change')].groupby(['meet','trainer_id']):
   stable.append(dict(window=window,meet=meet,trainer_id=tid,trainer_name=g.trainer_name.iloc[-1],category='post_card_all_normal',**old.metrics(g)))
  groups=[('primary',planned),('previous_also_as_card',planned[planned.previous_classification.eq('planned_as_card')]),('same_owner',planned[planned.stable_owner])]
  if window=='2024_2025':groups+= [('venue_'+m,g) for m,g in planned.groupby('meet')]
  for label,g in groups:
   if len(g)<500:continue
   res,dg=old.fit(g,old.category_design(g),horse=True)
   effects.extend(dict(window=window,model=label,**v) for v in res);diags.extend(dict(window=window,model=label,**v) for v in dg)
   print(window,label,len(g),flush=True)
  # Stable-specific ordinary-to-top associations, compared against retained ordinary within the shared model.
  if window=='2024_2025':
   qualified=[]
   for (meet,tid),g in planned.groupby(['meet','trainer_id']):
    if len(g)>=200 and g.horse_id.nunique()>=30 and g.source_key.nunique()>=30 and g.category.eq('ordinary_to_top').sum()>=30 and g.category.eq('retained_ordinary').sum()>=50:qualified.append((meet,tid))
   des=old.category_design(planned).drop(columns='ordinary_to_top');keys=planned.meet+':'+planned.trainer_id;qualified_keys=[m+':'+t for m,t in qualified];extra={}
   for key in sorted(set(keys)):extra['stable_'+key]=keys.eq(key).astype(float)
   upgrade=planned.category.eq('ordinary_to_top');extra['upgrade_other']=(upgrade&~keys.isin(qualified_keys)).astype(float)
   for key in qualified_keys:extra['upgrade_'+key]=(upgrade&keys.eq(key)).astype(float)
   des=pd.concat([des,pd.DataFrame(extra,index=planned.index)],axis=1)
   res,dg=old.fit(planned,des,horse=True);effects.extend(dict(window=window,model='stable_joint',**v) for v in res if v['term'].startswith('upgrade_'));diags.extend(dict(window=window,model='stable_joint',**v) for v in dg)
   save('stable_model_support.csv',[dict(meet=m,trainer_id=t,trainer_name=planned.loc[planned.meet.eq(m)&planned.trainer_id.eq(t),'trainer_name'].iloc[-1],term='upgrade_'+m+':'+t) for m,t in qualified]);print('stable joint',len(qualified),flush=True)
  # Compare unexpected replacement with planned riding, controlling actual category AND scheduled rider quality.
  g=valid[valid.classification.isin(['planned_as_card','post_card_change'])].copy();design=old.category_design(g);design['post_card_change']=g.classification.eq('post_card_change').astype(float);design['scheduled_score']=g.scheduled_score.fillna(0);design['scheduled_score_missing']=g.scheduled_score.isna().astype(float)
  res,dg=old.fit(g,design,horse=True);effects.extend(dict(window=window,model='post_card_comparison',**v) for v in res);diags.extend(dict(window=window,model='post_card_comparison',**v) for v in dg)
 eff=pd.DataFrame(effects);eff['family']=eff.model;eff.loc[eff.model.eq('stable_joint')&eff.term.eq('upgrade_other'),'family']='stable_other';eff=old.bh(eff,['window','family','target']);eff.to_csv(O/'adjusted_associations.csv',index=False)
 save('category_metrics.csv',metrics);save('stable_metrics.csv',stable);save('stable_destination_jockey_metrics.csv',pairs);save('late_change_metrics.csv',late);save('model_diagnostics.csv',diags)
 d[d.classification.eq('post_card_change')][['row_key','source_key','date','year','meet','horse_id','horse_name','trainer_id','trainer_name','previous_jockey_id','scheduled_id','scheduled_name','jockey_id','jockey_name','reason','reason_class','scheduled_differs_previous','main_eligible','top3','raw_finish_rank','finish_p','rank_improvement','time_gap','scheduled_quality_delta','card_source_path','card_line_no']].to_csv(O/'late_change_events.csv',index=False)
 summary=dict(primary_planned_n=int((d.year.between(2024,2025)&d.main_eligible&d.classification.eq('planned_as_card')).sum()),primary_late_comparable_n=int((d.year.between(2024,2025)&d.main_eligible&d.classification.eq('post_card_change')).sum()),top_definition='Previous calendar year venue smoothed top3; >=100 mounts, top ceil(20% eligible)',interpretation='Conditional observational associations; booking/intent and causal effects not identified',production_changes=False,model_trained=False)
 old.dump(O/'analysis_summary.json',summary);print(summary)
if __name__=='__main__':main()
