"""Immediate podium OR nonpodium improvement, with complete and documented observation scopes."""
from pathlib import Path
import importlib.util,json
import numpy as np,pandas as pd
from scipy.stats import false_discovery_control
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';PREV=R/'20261013_all_pair_nonpodium_switch_improvement'
spec=importlib.util.spec_from_file_location('nonpodium',PREV/'analyze.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
TARGETS=['combined_complete','combined_documented','podium_or_rank'];original_controls=base.controls

def prepare():
 d=base.prepare();d['rank_comparable']=d.previous_finish_p.notna()&d.finish_p.notna();d['time_comparable']=d.raw_time_change_same.notna();podium=d.top3.eq(1);rank=d.nonpodium_rank_improved.eq(1);time=d.nonpodium_time_improved.eq(1);positive=podium|rank|time;complete=d.rank_comparable&d.time_comparable
 d['combined_complete']=np.where(complete,positive.astype(float),np.nan);d['combined_documented']=positive.astype(float);d['podium_or_rank']=np.where(d.rank_comparable,(podium|rank).astype(float),np.nan)
 d['positive_podium']=podium.astype(int);d['positive_rank_and_time']=(~podium&rank&time).astype(int);d['positive_rank_only_confirmed']=(~podium&rank&~time).astype(int);d['positive_time_only_confirmed']=(~podium&~rank&time).astype(int);d['confirmed_nonpositive']=(~positive&complete).astype(int);d['unconfirmed_nonpositive']=(~positive&~complete).astype(int)
 assert d[d.normal_outcome][['positive_podium','positive_rank_and_time','positive_rank_only_confirmed','positive_time_only_confirmed','confirmed_nonpositive','unconfirmed_nonpositive']].sum(axis=1).eq(1).all()
 return d

def controls(g):
 c=original_controls(g).copy();c['rank_comparable_flag']=g.rank_comparable.astype(float);c['time_comparable_flag']=g.time_comparable.astype(float);return c

base.controls=controls

def raw_metrics(g,period):
 g=g.copy();g['state']=np.where(g.changed,'switched','retained');columns=dict(n=('row_key','size'),horses=('horse_id','nunique'),races=('source_key','nunique'),top3_events=('top3','sum'),top3_rate=('top3','mean'),nonpodium_n=('nonpodium','sum'),trainer_name=('trainer_name','last'),jockey_name=('jockey_name','last'))
 for target in TARGETS:columns[target+'_n']=(target,'count');columns[target+'_events']=(target,'sum');columns[target+'_rate']=(target,'mean')
 for field in ['positive_podium','positive_rank_and_time','positive_rank_only_confirmed','positive_time_only_confirmed','confirmed_nonpositive','unconfirmed_nonpositive']:columns[field]=(field,'sum')
 out=g.groupby(['pair_key','state']).agg(**columns).reset_index();out['period']=period;return out

def main():
 d=prepare();periods=list(base.periods(d));effects=[];diags=[];supports=[];raw=[];coverage=[]
 for period,g in periods:
  raw.append(raw_metrics(g,period));sw=g[g.changed];coverage.append(dict(period=period,n=len(g),changed=len(sw),pairs=g.pair_key.nunique(),podium=int(sw.positive_podium.sum()),rank_time_both=int(sw.positive_rank_and_time.sum()),rank_only_confirmed=int(sw.positive_rank_only_confirmed.sum()),time_only_confirmed=int(sw.positive_time_only_confirmed.sum()),confirmed_nonpositive=int(sw.confirmed_nonpositive.sum()),unconfirmed_nonpositive=int(sw.unconfirmed_nonpositive.sum()),combined_complete_n=int(sw.combined_complete.notna().sum()),combined_complete_positive=int(sw.combined_complete.sum()),documented_positive=int(sw.combined_documented.sum()),podium_or_rank_n=int(sw.podium_or_rank.notna().sum()),podium_or_rank_positive=int(sw.podium_or_rank.sum())))
 pd.concat(raw,ignore_index=True).to_csv(O/'raw_period_pair_metrics.csv',index=False);pd.DataFrame(coverage).to_csv(O/'coverage.csv',index=False)
 for period,g in periods:
  for target in TARGETS:
   res,diag,support=base.fit(g,target,period,'positive_union');effects+=res;diags.append(diag);supports+=support;pd.DataFrame(effects).to_csv(O/'adjusted_associations.csv',index=False);pd.DataFrame(diags).to_csv(O/'model_diagnostics.csv',index=False)
 e=pd.DataFrame(effects);s=pd.DataFrame(supports);s.to_csv(O/'target_pair_support.csv',index=False)
 for state in ['switched','retained']:
  z=s[s.state.eq(state)].set_index(['period','target','pair_key']);ix=pd.MultiIndex.from_frame(e[['period','target','pair_key']])
  for col in ['n','horses','races']:e[state+'_'+col]=z[col].reindex(ix).fillna(0).to_numpy()
 e['target_supported']=e.switched_n.ge(30)&e.retained_n.ge(30)&e.switched_horses.ge(15)&e.retained_horses.ge(15)&e.switched_races.ge(20)&e.retained_races.ge(20)
 for col in ['q','q_joint_targets','q_all_years','q_all_years_joint_targets']:e[col]=np.nan
 for _,g in e.groupby(['period','target']):e.loc[g.index,'q']=false_discovery_control(g.p.fillna(1).to_numpy())
 for _,g in e.groupby('period'):e.loc[g.index,'q_joint_targets']=false_discovery_control(g.p.fillna(1).to_numpy())
 annual=e[e.period.isin([str(y) for y in range(2019,2026)])]
 for _,g in annual.groupby('target'):e.loc[g.index,'q_all_years']=false_discovery_control(g.p.fillna(1).to_numpy())
 e.loc[annual.index,'q_all_years_joint_targets']=false_discovery_control(annual.p.fillna(1).to_numpy())
 names=pd.read_csv(O/'frozen_213_pairs.csv').set_index('pair_key')
 for col in ['trainer_name','jockey_name','meet']:e[col]=e.pair_key.map(names[col])
 e.to_csv(O/'adjusted_associations.csv',index=False)
 eventcols=list(pd.read_parquet(PREV/'outputs/current_switch_event_cases.parquet').columns)+['rank_comparable','time_comparable']+TARGETS+['positive_podium','positive_rank_and_time','positive_rank_only_confirmed','positive_time_only_confirmed','confirmed_nonpositive','unconfirmed_nonpositive'];events=d[d.primary_eligible&d.year.between(2019,2026)&d.changed];events[eventcols].to_parquet(O/'current_switch_combined_events.parquet',index=False)
 inputs=[base.hist.INPUT,PREV/'analyze.py',PREV/'outputs/frozen_213_pairs.csv',PREV/'outputs/verification.json',PREV/'outputs/current_switch_event_cases.parquet',R/'20261012_historical_planned_pair_switch_race/analyze.py',R/'20261012_jockey_switch_trainer_intent/analyze.py',R/'20261012_planned_jockey_changes_by_stable/outputs/verification.json']
 audit=dict(inputs=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=base.hist.old.sha(p)) for p in inputs],rows=len(d),fixed_pair_family=213,prior_outcome_candidates_used=False,primary_target='combined_complete',primary_period='2019~2025',partial_by_meet={k:str(v.date()) for k,v in d[d.primary_eligible&d.year.eq(2026)].groupby('meet').date.max().items()},event_rows=len(events),target_horizon_races=0,future_outcomes_created=False,ability_FE_retrospective=True,documented_zero_not_confirmed_failure=True,overlap_counted_once=True,first_card_immutability_verified=False,production_changed=False)
 base.hist.old.dump(O/'source_audit.json',audit);print('Finished combined immediate-event study',len(events),flush=True)
if __name__=='__main__':main()
