"""Frozen four exploratory pairs: current-switch-race annual and recent contrasts."""
from pathlib import Path
import importlib.util,json,hashlib
import numpy as np,pandas as pd
from scipy.stats import false_discovery_control
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';PREV=R/'20261012_historical_planned_pair_switch_race'
spec=importlib.util.spec_from_file_location('historical',PREV/'analyze.py');hist=importlib.util.module_from_spec(spec);spec.loader.exec_module(hist)
original_design=hist.design
FROZEN=pd.read_csv(O/'frozen_four_pairs.csv',dtype={'trainer_id':str,'jockey_id':str});FOUR=FROZEN.pair_key.tolist();ALL=pd.read_csv(PREV/'outputs/pair_support.csv');ALL=ALL[ALL.model_supported].pair_key.tolist()
MODE=None;PERIODS=None

def bucket(g):
 if MODE=='annual':return g.year.astype(str)
 if MODE=='eras':return pd.Series(np.where(g.year.le(2023),'2019_2023','2024_2025'),index=g.index)
 return pd.Series('2026_partial',index=g.index)

def design(g,pairs):
 x=original_design(g,pairs);x=x.drop(columns=['pair_'+p for p in FOUR]+['switch_'+p for p in FOUR]);b=bucket(g)
 for p in FOUR:
  for period in PERIODS:x['pair_'+p+'@'+period]=(g.pair_key.eq(p)&b.eq(period)).to_numpy(float)
 for p in FOUR:
  for period in PERIODS:x['switch_'+p+'@'+period]=(g.changed&g.pair_key.eq(p)&b.eq(period)).to_numpy(float)
 return x

def terms():
 out=[]
 for p in FOUR:
  for period in PERIODS:out.append((p,period,'pair_total',{'changed':1,'switch_'+p+'@'+period:1}))
 if MODE=='eras':
  for p in FOUR:out.append((p,'recent_minus_earlier','recent_minus_earlier',{'switch_'+p+'@2024_2025':1,'switch_'+p+'@2019_2023':-1}))
 return out

def contrasts(names,retained,pairs):
 positions={names[j]:k for k,j in enumerate(retained) if j<len(names)};rows=[];weights=[]
 for p,period,contrast,w in terms():
  vector=np.zeros(len(retained));status='estimated'
  for key,value in w.items():
   if key not in positions:status='no_within_FE_variation';break
   vector[positions[key]]=value
  rows.append(dict(contrast=contrast,pair_key=p,period=period,status=status));weights.append(vector)
 return rows,np.asarray(weights)

def raw_table(g,periods):
 g=g[g.pair_key.isin(FOUR)].copy();g['period']=bucket(g);g['state']=np.where(g.changed,'switched','retained');agg=hist.aggregate(g,['period','pair_key','state']);grid=pd.MultiIndex.from_product([periods,FOUR,['switched','retained']],names=['period','pair_key','state']);agg=agg.set_index(['period','pair_key','state']).reindex(grid).reset_index()
 for col in ['n','horses','races','dates','top3_events','previous_top3_n','rank_improvement_n','time_n','same_condition_time_n']:agg[col]=agg[col].fillna(0).astype(int)
 for col in ['trainer_name','jockey_name']:agg[col]=agg.pair_key.map(FROZEN.set_index('pair_key')[col])
 agg['state_supported']=agg.n.ge(30)&agg.horses.ge(15)&agg.races.ge(20);return agg

def add_bh(e):
 e=e.copy();e['q_fixed_family']=np.nan;e['q_all_targets_fixed_family']=np.nan
 for _,z in e.groupby(['model','target','contrast']):e.loc[z.index,'q_fixed_family']=false_discovery_control(z.p.fillna(1).to_numpy(),method='bh')
 for _,z in e.groupby(['model','contrast']):e.loc[z.index,'q_all_targets_fixed_family']=false_discovery_control(z.p.fillna(1).to_numpy(),method='bh')
 return e

def main():
 global MODE,PERIODS
 d=hist.prepare();raws=[];effects=[];diags=[];coverage=[]
 fits=[('annual',[str(y) for y in range(2019,2026)],d[d.primary_eligible&d.year.between(2019,2025)]),('eras',['2019_2023','2024_2025'],d[d.primary_eligible&d.year.between(2019,2025)]),('recent_partial',['2026_partial'],d[d.primary_eligible&d.year.eq(2026)])]
 hist.design=design;hist.contrasts=contrasts
 for model,periods,g in fits:
  MODE=model;PERIODS=periods;raw=raw_table(g,periods);raw['model']=model;raws.append(raw);coverage.append(dict(model=model,n=len(g),changed=int(g.changed.sum()),horses=g.horse_id.nunique(),races=g.source_key.nunique(),candidate_changed=int((g.changed&g.pair_key.isin(FOUR)).sum()),start=str(g.date.min().date()),end=str(g.date.max().date())))
  pd.concat(raws,ignore_index=True).to_csv(O/'raw_period_metrics.csv',index=False)
  res,dg=hist.fit(g,ALL,'2019_2025' if model!='recent_partial' else '2026_partial',model);effects+=res;diags+=dg;pd.DataFrame(effects).to_csv(O/'adjusted_period_effects.csv',index=False);pd.DataFrame(diags).to_csv(O/'model_diagnostics.csv',index=False)
 e=add_bh(pd.DataFrame(effects));raw=pd.concat(raws,ignore_index=True)
 for state in ['switched','retained']:
  z=raw[raw.state.eq(state)].set_index(['model','period','pair_key']);idx=pd.MultiIndex.from_frame(e[['model','period','pair_key']])
  for col in ['n','horses','races','top3_events','top3_rate','previous_top3_rate','paired_current_top3_rate']:
   e[state+'_'+col]=z[col].reindex(idx).to_numpy()
 e['pair_period_supported']=e.switched_n.ge(30)&e.switched_horses.ge(15)&e.switched_races.ge(20)&e.retained_n.ge(30)&e.retained_horses.ge(15)&e.retained_races.ge(20)
 for col in ['trainer_name','jockey_name']:e[col]=e.pair_key.map(FROZEN.set_index('pair_key')[col])
 e.to_csv(O/'adjusted_period_effects.csv',index=False);pd.DataFrame(coverage).to_csv(O/'coverage.csv',index=False)
 events=d[d.primary_eligible&d.year.between(2019,2026)&d.changed&d.pair_key.isin(FOUR)].copy();eventcols=list(pd.read_parquet(PREV/'outputs/switch_race_events.parquet').columns);events[eventcols].to_parquet(O/'four_pair_switch_events.parquet',index=False)
 inputs=[hist.INPUT,PREV/'analyze.py',PREV/'outputs/nominal_top3_candidates.csv',PREV/'outputs/pair_support.csv',PREV/'outputs/verification.json',PREV/'outputs/adjusted_associations.csv',R/'20261012_jockey_switch_trainer_intent/analyze.py',R/'20261012_planned_jockey_changes_by_stable/outputs/verification.json']
 audit=dict(inputs=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=hist.old.sha(p)) for p in inputs],rows=len(d),four_pairs=FOUR,original_pair_family=213,selection='original main top3 pair_total positive nominal p<.05; original BH none',primary_period='2019~2025',recent_complete='2024~2025',partial_by_meet={k:str(v.date()) for k,v in d[d.primary_eligible&d.year.eq(2026)].groupby('meet').date.max().items()},event_rows=len(events),target_horizon_races=0,future_outcomes_created=False,ability_FE_retrospective=True,first_card_immutability_verified=False,production_changed=False)
 hist.old.dump(O/'source_audit.json',audit);print('Finished current-race annual study',len(events),flush=True)
if __name__=='__main__':main()
