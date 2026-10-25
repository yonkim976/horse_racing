"""All supported pairs: immediate nonpodium improvement cases, annual and recent."""
from pathlib import Path
import importlib.util,json,math,gc
import pandas as pd,numpy as np
from scipy import linalg,stats
from scipy.stats import false_discovery_control
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';PREV=R/'20261012_historical_planned_pair_switch_race'
spec=importlib.util.spec_from_file_location('historical',PREV/'analyze.py');hist=importlib.util.module_from_spec(spec);spec.loader.exec_module(hist)
PAIRS=pd.read_csv(O/'frozen_213_pairs.csv').pair_key.tolist();PRIMARY=['nonpodium_rank_improved','nonpodium_time_improved'];AUX=['conditional_finish_p','conditional_time_gap'];EXTRA=['previous_time_gap','previous_quality_time','previous_moisture','previous_field_size']

def prepare():
 d=hist.prepare();lookup=d.set_index('row_key')
 for col in ['time_gap','moisture','field_size']:d['previous_'+col]=d.previous_row_key.map(lookup[col])
 d['nonpodium']=d.normal_outcome&d.raw_finish_rank.gt(3);rv=d.previous_finish_p.notna()&d.finish_p.notna();tv=d.raw_time_change_same.notna()
 d['nonpodium_rank_improved']=np.where(rv,(d.nonpodium&d.rank_improvement.gt(1e-12)).astype(float),np.nan)
 d['nonpodium_time_improved']=np.where(tv,(d.nonpodium&d.raw_time_change_same.lt(-1e-9)).astype(float),np.nan)
 d['nonpodium_raw_rank_improved']=np.where(rv&d.previous_raw_finish_rank.notna(),(d.nonpodium&d.previous_raw_finish_rank.gt(d.raw_finish_rank)).astype(float),np.nan)
 d['nonpodium_winner_gap_improved']=np.where(d.same_conditions&d.time_gap.notna()&d.previous_time_gap.notna(),(d.nonpodium&d.time_gap.lt(d.previous_time_gap-1e-9)).astype(float),np.nan)
 d['conditional_finish_p']=d.finish_p.where(d.nonpodium);d['conditional_time_gap']=d.time_gap.where(d.nonpodium)
 d['rank_nonpodium_comparable']=(d.nonpodium&rv).astype(int);d['time_nonpodium_comparable']=(d.nonpodium&tv).astype(int)
 d['rank_change_nonpodium']=d.rank_improvement.where(d.nonpodium);d['seconds_change_nonpodium']=d.raw_time_change_same.where(d.nonpodium)
 return d

def controls(g):
 x=hist.old.controls(g).copy()
 for col in EXTRA:
  v=g[col].to_numpy(float);bad=~np.isfinite(v);v=np.where(bad,0,v);x[col+'_missing']=bad.astype(float);x[col]=v;x[col+'_sq']=v*v
 return x

def weights(names,retained):
 positions={names[j]:k for k,j in enumerate(retained) if j<len(names)};rows=[];ws=[]
 for p in PAIRS:
  w=np.zeros(len(retained));status='estimated'
  for term in ['changed','switch_'+p]:
   if term not in positions:status='no_within_FE_variation';break
   w[positions[term]]=1
  rows.append(dict(pair_key=p,status=status));ws.append(w)
 return rows,np.asarray(ws)

def fit(g,target,period,model):
 z=g[g[target].notna()].copy();design=hist.design(z,PAIRS);names=list(design);c=controls(z).to_numpy(float);sd=c.std(axis=0);c=c[:,sd>1e-12]/sd[sd>1e-12];a=np.column_stack([design.to_numpy(float),c,z[target].to_numpy(float)]);del design,c
 codes=[pd.factorize(z.source_key)[0],pd.factorize(z.horse_id)[0]];a,fe_rank=hist.old.demean(a,codes);max_fe_mean=0.
 for code in codes:
  sums=np.zeros((int(code.max()+1),a.shape[1]));np.add.at(sums,code,a);max_fe_mean=max(max_fe_mean,float(np.max(np.abs(sums/np.bincount(code)[:,None]))));del sums
 keep=a[:,:-1].std(axis=0)>1e-10;retained=np.flatnonzero(keep);x=a[:,:-1][:,keep];y=a[:,-1].copy();del a;gc.collect();rows,w=weights(names,retained);print('SVD',period,target,len(z),x.shape[1],flush=True)
 u,s,vh=linalg.svd(x,full_matrices=False,check_finite=False);del x;rank=int((s>s[0]*1e-10).sum());ur=u[:,:rank];vr=vh[:rank];sr=s[:rank];b=vr.T@((ur.T@y)/sr);res=y-ur@(ur.T@y);df=len(z)-fe_rank-rank;assert df>0
 identifiable=np.max(np.abs((w@vr.T)@vr-w),axis=1)<1e-6
 for i,row in enumerate(rows):
  if row['status']=='estimated' and not identifiable[i]:row['status']='not_identified'
 estimate=w@b;factor=(w@vr.T)/sr;cluster_codes=[];counts=[]
 for fields in [['horse_id'],['date'],['horse_id','date']]:
  code=pd.factorize(pd.MultiIndex.from_frame(z[fields]))[0];cluster_codes.append(code);counts.append(int(code.max()+1))
 dfcluster=min(counts[:2])-1;crit=stats.t.ppf(.975,dfcluster);outputs=[]
 for start in range(0,len(rows),24):
  derivatives=factor[start:start+24]@ur.T
  for j,row in enumerate(rows[start:start+24]):
   i=start+j;out=dict(period=period,model=model,target=target,contrast='pair_total',**row,n=len(z),horses=z.horse_id.nunique(),races=z.source_key.nunique())
   if row['status']=='estimated':
    score=derivatives[j]*res*math.sqrt(len(z)/df);vs=[]
    for code,k in zip(cluster_codes,counts):sums=np.bincount(code,weights=score);vs.append(float(sums@sums)*k/max(k-1,1))
    se=math.sqrt(max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2]));value=float(estimate[i]);out.update(estimate=value,se=se,ci_low=value-crit*se,ci_high=value+crit*se,p=float(2*stats.t.sf(abs(value/se),dfcluster)) if se else 1.,horse_clusters=counts[0],date_clusters=counts[1])
   outputs.append(out)
 normal=float(np.max(np.abs((vh.T*s)@(u.T@res))));diag=dict(period=period,model=model,target=target,n=len(z),p=len(retained),rank=rank,fe_rank=int(fe_rank),residual_df=int(df),normal_equation_max=normal,max_fe_mean=max_fe_mean,estimator='exact_race_horse_FE_SVD',design_names=json.dumps(names,ensure_ascii=False))
 counts_rows=[]
 for (p,changed),sg in z.groupby(['pair_key','changed']):counts_rows.append(dict(period=period,model=model,target=target,pair_key=p,state='switched' if changed else 'retained',n=len(sg),horses=sg.horse_id.nunique(),races=sg.source_key.nunique()))
 print('Fit complete',period,target,flush=True);return outputs,diag,counts_rows

def periods(d):
 yield '2019_2025',d[d.primary_eligible&d.year.between(2019,2025)]
 for year in range(2019,2026):yield str(year),d[d.primary_eligible&d.year.eq(year)]
 yield '2019_2023',d[d.primary_eligible&d.year.between(2019,2023)]
 yield '2024_2025',d[d.primary_eligible&d.year.between(2024,2025)]
 yield '2026_partial',d[d.primary_eligible&d.year.eq(2026)]

def raw_metrics(g,label):
 g=g.copy();g['state']=np.where(g.changed,'switched','retained')
 columns=dict(n=('row_key','size'),horses=('horse_id','nunique'),races=('source_key','nunique'),top3_events=('top3','sum'),top3_rate=('top3','mean'),nonpodium_n=('nonpodium','sum'),rank_comparable_n=('nonpodium_rank_improved','count'),rank_nonpodium_comparable_n=('rank_nonpodium_comparable','sum'),rank_improved_events=('nonpodium_rank_improved','sum'),rank_case_rate=('nonpodium_rank_improved','mean'),raw_rank_improved_events=('nonpodium_raw_rank_improved','sum'),time_comparable_n=('nonpodium_time_improved','count'),time_nonpodium_comparable_n=('time_nonpodium_comparable','sum'),time_improved_events=('nonpodium_time_improved','sum'),time_case_rate=('nonpodium_time_improved','mean'),winner_gap_improved_events=('nonpodium_winner_gap_improved','sum'),rank_change_nonpodium_mean=('rank_change_nonpodium','mean'),seconds_change_nonpodium_mean=('seconds_change_nonpodium','mean'),conditional_finish_p_mean=('conditional_finish_p','mean'),conditional_time_gap_n=('conditional_time_gap','count'),conditional_time_gap_mean=('conditional_time_gap','mean'),trainer_name=('trainer_name','last'),jockey_name=('jockey_name','last'))
 out=g.groupby(['pair_key','state']).agg(**columns).reset_index();out['period']=label;out['rank_case_rate_among_nonpodium']=out.rank_improved_events/out.rank_nonpodium_comparable_n.replace(0,np.nan);out['time_case_rate_among_nonpodium']=out.time_improved_events/out.time_nonpodium_comparable_n.replace(0,np.nan);return out

def main():
 d=prepare();effects=[];diags=[];supports=[];raw=[];coverage=[]
 allperiods=list(periods(d))
 for label,g in allperiods:
  raw.append(raw_metrics(g,label));coverage.append(dict(period=label,n=len(g),changed=int(g.changed.sum()),nonpodium_changed=int((g.nonpodium&g.changed).sum()),pairs=g.pair_key.nunique(),rank_comparable_changed=int((g.changed&g.nonpodium_rank_improved.notna()).sum()),time_comparable_changed=int((g.changed&g.nonpodium_time_improved.notna()).sum())))
 pd.concat(raw,ignore_index=True).to_csv(O/'raw_period_pair_metrics.csv',index=False);pd.DataFrame(coverage).to_csv(O/'coverage.csv',index=False)
 for label,g in allperiods:
  for target in PRIMARY+(AUX if label in ['2019_2025','2024_2025','2026_partial'] else []):
   model='all_starts_composite' if target in PRIMARY else 'conditional_nonpodium';res,diag,support=fit(g,target,label,model);effects+=res;diags.append(diag);supports+=support;pd.DataFrame(effects).to_csv(O/'adjusted_associations.csv',index=False);pd.DataFrame(diags).to_csv(O/'model_diagnostics.csv',index=False)
 e=pd.DataFrame(effects);support=pd.DataFrame(supports);support.to_csv(O/'target_pair_support.csv',index=False)
 for state in ['switched','retained']:
  z=support[support.state.eq(state)].set_index(['period','model','target','pair_key']);idx=pd.MultiIndex.from_frame(e[['period','model','target','pair_key']])
  for col in ['n','horses','races']:e[state+'_'+col]=z[col].reindex(idx).fillna(0).to_numpy()
 e['target_supported']=e.switched_n.ge(30)&e.retained_n.ge(30)&e.switched_horses.ge(15)&e.retained_horses.ge(15)&e.switched_races.ge(20)&e.retained_races.ge(20)
 for col in ['q','q_joint_targets','q_all_years','q_all_years_joint_targets']:e[col]=np.nan
 for _,sg in e.groupby(['period','model','target']):e.loc[sg.index,'q']=false_discovery_control(sg.p.fillna(1).to_numpy())
 for _,sg in e.groupby(['period','model']):e.loc[sg.index,'q_joint_targets']=false_discovery_control(sg.p.fillna(1).to_numpy())
 annual=e[e.period.isin([str(y) for y in range(2019,2026)])]
 for _,sg in annual.groupby(['model','target']):e.loc[sg.index,'q_all_years']=false_discovery_control(sg.p.fillna(1).to_numpy())
 for _,sg in annual.groupby('model'):e.loc[sg.index,'q_all_years_joint_targets']=false_discovery_control(sg.p.fillna(1).to_numpy())
 names=pd.read_csv(O/'frozen_213_pairs.csv').set_index('pair_key')
 for col in ['trainer_name','jockey_name','meet']:e[col]=e.pair_key.map(names[col])
 e.to_csv(O/'adjusted_associations.csv',index=False)
 events=d[d.primary_eligible&d.year.between(2019,2026)&d.changed].copy();cols=list(pd.read_parquet(PREV/'outputs/switch_race_events.parquet').columns)+['field_size','previous_distance_m','previous_grade_bucket','same_conditions','previous_time_gap','previous_moisture','previous_field_size','nonpodium','nonpodium_rank_improved','nonpodium_time_improved','nonpodium_raw_rank_improved','nonpodium_winner_gap_improved'];events[cols].to_parquet(O/'current_switch_event_cases.parquet',index=False)
 inputs=[hist.INPUT,PREV/'analyze.py',R/'20261012_jockey_switch_trainer_intent/analyze.py',PREV/'outputs/pair_support.csv',PREV/'outputs/verification.json',R/'20261012_planned_jockey_changes_by_stable/outputs/verification.json']
 audit=dict(inputs=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=hist.old.sha(p)) for p in inputs],rows=len(d),fixed_pair_family=213,prior_four_used_for_selection=False,primary_period='2019~2025',partial_by_meet={k:str(v.date()) for k,v in d[d.primary_eligible&d.year.eq(2026)].groupby('meet').date.max().items()},event_rows=len(events),target_horizon_races=0,future_outcomes_created=False,ability_FE_retrospective=True,composite_events_are_not_overall_performance_scores=True,conditional_models_selected_on_current_outcome=True,first_card_immutability_verified=False,production_changed=False)
 hist.old.dump(O/'source_audit.json',audit);print('Finished all-pair nonpodium study',len(events),flush=True)
if __name__=='__main__':main()
