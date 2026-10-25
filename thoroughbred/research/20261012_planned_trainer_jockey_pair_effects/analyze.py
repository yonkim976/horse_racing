"""Joint planned-switch interactions; current jockey ability and baseline partnership controlled."""
from pathlib import Path
import importlib.util,json,hashlib,math
import pandas as pd,numpy as np
from scipy import linalg
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs'
spec=importlib.util.spec_from_file_location('study50',R/'20261012_jockey_switch_trainer_intent/analyze.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
INPUT=R/'20261012_planned_jockey_changes_by_stable/outputs/classified_starts.parquet'
def prepare():
 d=pd.read_parquet(INPUT);d['pair_key']=d.meet+':'+d.trainer_id+':'+d.jockey_id
 d['expanded_eligible']=d.normal_outcome&d.identity_supported&d.stable_trainer&d.same_venue&d.gap_days.between(2,180)&d.classification.eq('planned_as_card');d['primary_eligible']=d.main_eligible&d.classification.eq('planned_as_card')
 return d

def design(g,pairs):
 x={'changed':g.changed.to_numpy(float)}
 jk=g.meet+':'+g.year.astype(str)+':'+g.jockey_id
 # Reference rider per venue/year is omitted; race FE already includes venue/year intercepts.
 for _,v in g.assign(jk=jk).groupby(['meet','year']):
  for key in sorted(set(v.jk))[1:]:x['jockey_year_'+key]=jk.eq(key).to_numpy(float)
 trainers=g.meet+':'+g.trainer_id
 for key in sorted(set(trainers)):x['trainer_'+key]=trainers.eq(key).to_numpy(float)
 for key in pairs:x['pair_'+key]=g.pair_key.eq(key).to_numpy(float)
 for key in pairs:x['switch_'+key]=(g.changed&g.pair_key.eq(key)).to_numpy(float)
 return pd.DataFrame(x,index=g.index)

def fit(g,pairs,window,model):
 output=[];diags=[]
 for target in ['top3','finish_p','time_gap']:
  z=g[g[target].notna()].copy();des=design(z,pairs);names=list(des);c=old.controls(z).to_numpy(float);scale=c.std(axis=0);c=c[:,scale>1e-12]/scale[scale>1e-12];a=np.column_stack([des.to_numpy(float),c,z[target].to_numpy(float)]);codes=[pd.factorize(z.source_key)[0],pd.factorize(z.horse_id)[0]];a,fe_rank=old.demean(a,codes);keep=np.std(a[:,:-1],axis=0)>1e-10;retained=np.flatnonzero(keep);x=a[:,:-1][:,keep];y=a[:,-1];beta,_,rank,_=linalg.lstsq(x,y,cond=1e-10);inverse=linalg.pinv(x,rtol=1e-10);res=y-x@beta;df=len(z)-fe_rank-rank;assert df>0;proj=inverse@x;positions={names[j]:k for k,j in enumerate(retained) if j<len(names)}
  terms=[('general_other_pairs','changed',None)]
  for key in pairs:terms.extend([('pair_extra',key,{'switch_'+key:1}),('pair_total',key,{'changed':1,'switch_'+key:1})])
  for contrast,key,weights in terms:
   weights=weights or {'changed':1};w=np.zeros(len(beta));status='estimated'
   for name,value in weights.items():
    if name not in positions:status='no_within_FE_variation';break
    w[positions[name]]=value
   if status=='estimated' and np.max(np.abs(w@proj-w))>=1e-6:status='not_identified'
   row=dict(window=window,model=model,target=target,contrast=contrast,pair_key=key,status=status,n=len(z),horses=z.horse_id.nunique(),races=z.source_key.nunique())
   if status=='estimated':row.update(old.cluster_ci(z,(w@inverse)*res*math.sqrt(len(z)/df),w@beta))
   output.append(row)
  diags.append(dict(window=window,model=model,target=target,n=len(z),p=x.shape[1],rank=int(rank),fe_rank=int(fe_rank),residual_df=int(df),normal_equation_max=float(np.max(np.abs(x.T@res))),max_fe_mean=max(float(np.max(np.abs(pd.DataFrame(a).groupby(code).mean().to_numpy()))) for code in codes),design_names=json.dumps(names,ensure_ascii=False)))
  print(window,model,target,len(z),flush=True)
 return output,diags

def main():
 d=prepare();metrics=[];coverage=[]
 for window,allg in [('2024_2025',d[d.year.between(2024,2025)]),('2026_partial',d[d.year.eq(2026)])]:
  for pop,mask in [('primary',allg.primary_eligible),('expanded_no_annual_minimum',allg.expanded_eligible)]:
   g=allg[mask];coverage.append(dict(window=window,population=pop,n=len(g),changed=int(g.changed.sum()),horses=g.horse_id.nunique(),races=g.source_key.nunique()))
   for key,sg in g.groupby('pair_key'):
    for state,sub in [('all',sg),('switched',sg[sg.changed]),('retained',sg[~sg.changed])]:
     if not len(sub):continue
     metrics.append(dict(window=window,population=pop,pair_key=key,meet=sg.meet.iloc[0],trainer_id=sg.trainer_id.iloc[0],trainer_name=sg.trainer_name.iloc[-1],jockey_id=sg.jockey_id.iloc[0],jockey_name=sg.jockey_name.iloc[-1],state=state,**old.metrics(sub)))
 table=pd.DataFrame(metrics);primary=table[table.window.eq('2024_2025')&table.population.eq('primary')];rows=[]
 for key,sg in primary.groupby('pair_key'):
  states=sg.set_index('state');sw=states.loc['switched'] if 'switched' in states.index else None;ret=states.loc['retained'] if 'retained' in states.index else None
  support_switch=sw is not None and sw.n>=30 and sw.horses>=15 and sw.races>=20
  support_retained=ret is not None and ret.n>=30 and ret.horses>=15 and ret.races>=20
  rows.append(dict(pair_key=key,meet=sg.meet.iloc[0],trainer_id=sg.trainer_id.iloc[0],trainer_name=sg.trainer_name.iloc[0],jockey_id=sg.jockey_id.iloc[0],jockey_name=sg.jockey_name.iloc[0],switch_n=0 if sw is None else int(sw.n),retained_n=0 if ret is None else int(ret.n),switch_horses=0 if sw is None else int(sw.horses),retained_horses=0 if ret is None else int(ret.horses),switch_races=0 if sw is None else int(sw.races),retained_races=0 if ret is None else int(ret.races),switch_supported=support_switch,retained_supported=support_retained,model_supported=support_switch and support_retained,reason='supported' if support_switch and support_retained else 'retained_comparator_insufficient' if support_switch else 'switch_support_insufficient'))
 support=pd.DataFrame(rows);pairs=support.loc[support.model_supported,'pair_key'].tolist();assert pairs
 support.to_csv(O/'pair_support.csv',index=False);table.to_csv(O/'pair_metrics.csv',index=False);pd.DataFrame(coverage).to_csv(O/'coverage.csv',index=False)
 main=d[d.year.between(2024,2025)&d.primary_eligible];fits=[('2024_2025','primary',main),('2024_2025','previous_also_as_card',main[main.previous_classification.eq('planned_as_card')]),('2024_2025','same_owner',main[main.stable_owner]),('2024_2025','expanded_no_annual_minimum',d[d.year.between(2024,2025)&d.expanded_eligible]),('2026_partial','frozen_pairs',d[d.year.eq(2026)&d.primary_eligible])];effects=[];diags=[]
 for window,label,g in fits:
  res,dg=fit(g,pairs,window,label);effects+=res;diags+=dg
 e=pd.DataFrame(effects);e['q']=np.nan
 for _,sg in e[e.status.eq('estimated')].groupby(['window','model','target','contrast']):e.loc[sg.index,'q']=old.bh(sg.assign(family='one'),['family']).q
 e.to_csv(O/'adjusted_associations.csv',index=False);pd.DataFrame(diags).to_csv(O/'model_diagnostics.csv',index=False)
 annual=[]
 for (year,key,changed),g in d[d.year.ge(2024)&d.primary_eligible&d.pair_key.isin(pairs)].groupby(['year','pair_key','changed']):annual.append(dict(year=year,pair_key=key,state='switched' if changed else 'retained',**old.metrics(g)))
 pd.DataFrame(annual).to_csv(O/'annual_pair_metrics.csv',index=False)
 # Row membership proof; outcomes remain in the immutable input rather than duplicated.
 d[['row_key','pair_key','primary_eligible','expanded_eligible']].to_parquet(O/'cohort_membership.parquet',index=False)
 inputs=[INPUT,R/'20261012_jockey_switch_trainer_intent/analyze.py',R/'20261012_planned_jockey_changes_by_stable/outputs/verification.json',R/'20261012_planned_jockey_changes_by_stable/outputs/source_audit.json',R/'20261012_planned_jockey_changes_by_stable/outputs/stable_destination_jockey_metrics.csv']
 old.dump(O/'source_audit.json',dict(inputs=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=old.sha(p)) for p in inputs],rows=len(d),primary_period='2024~2025',confirmation='2026 partial',supported_switch_pairs=int(support.switch_supported.sum()),supported_with_retained_comparator=len(pairs),planned_first_post_immutability_verified=False,top_jockey_indicator_used=False,current_jockey_venue_year_FE=True,pair_baseline_FE=True,unchanged_base=True,new_prediction_model=False,production_changed=False,data_end_by_meet={m:str(g.date.max().date()) for m,g in d.groupby('meet')},card_end='2026-09-13'))
 print('Supported switch pairs',int(support.switch_supported.sum()),'with retained comparator',len(pairs))
if __name__=='__main__':main()
