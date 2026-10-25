"""Historical planned switch event, current race only; exact FE plus shared SVD estimation."""
from pathlib import Path
import importlib.util,json,hashlib,math,gc
import numpy as np,pandas as pd
from scipy import linalg,stats
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';INPUT=R/'20261012_planned_jockey_changes_by_stable/outputs/classified_starts.parquet'
spec=importlib.util.spec_from_file_location('study50',R/'20261012_jockey_switch_trainer_intent/analyze.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
def prepare():
 d=pd.read_parquet(INPUT);d['pair_key']=d.meet+':'+d.trainer_id+':'+d.jockey_id;d['primary_eligible']=d.main_eligible&d.classification.eq('planned_as_card');d['expanded_eligible']=d.normal_outcome&d.identity_supported&d.stable_trainer&d.same_venue&d.gap_days.between(2,180)&d.classification.eq('planned_as_card');return d

def aggregate(g,keys):
 g=g.copy();g['paired_current']=g.top3.where(g.previous_top3.notna());g['paired_delta']=g.top3-g.previous_top3
 columns=dict(n=('row_key','size'),horses=('horse_id','nunique'),races=('source_key','nunique'),dates=('date','nunique'),top3_events=('top3','sum'),top3_rate=('top3','mean'),win_rate=('win','mean'),previous_top3_n=('previous_top3','count'),previous_top3_rate=('previous_top3','mean'),paired_current_top3_rate=('paired_current','mean'),paired_top3_change=('paired_delta','mean'),rank_mean=('raw_finish_rank','mean'),rank_relative_mean=('finish_p','mean'),previous_rank_relative_mean=('previous_finish_p','mean'),rank_improvement_n=('rank_improvement','count'),rank_improvement_mean=('rank_improvement','mean'),past5_rank=('finish_p_mean5','mean'),time_n=('time_gap','count'),time_gap_mean=('time_gap','mean'),same_condition_time_n=('raw_time_change_same','count'),same_condition_time_change=('raw_time_change_same','mean'),trainer_name=('trainer_name','last'),jockey_name=('jockey_name','last'))
 return g.groupby(keys,dropna=False).agg(**columns).reset_index()

def design(g,pairs):
 x={'changed':g.changed.to_numpy(float)};jk=g.meet+':'+g.year.astype(str)+':'+g.jockey_id
 for _,v in g.assign(jk=jk).groupby(['meet','year']):
  for key in sorted(set(v.jk))[1:]:x['jockey_year_'+key]=jk.eq(key).to_numpy(float)
 tr=g.meet+':'+g.trainer_id
 for key in sorted(set(tr)):x['trainer_'+key]=tr.eq(key).to_numpy(float)
 for key in pairs:x['pair_'+key]=g.pair_key.eq(key).to_numpy(float)
 for key in pairs:x['switch_'+key]=(g.changed&g.pair_key.eq(key)).to_numpy(float)
 return pd.DataFrame(x,index=g.index)

def contrasts(names,retained,pairs):
 positions={names[j]:k for k,j in enumerate(retained) if j<len(names)};rows=[];weights=[]
 terms=[('general_other_pairs','changed',{'changed':1})]
 for key in pairs:terms.extend([('pair_extra',key,{'switch_'+key:1}),('pair_total',key,{'changed':1,'switch_'+key:1})])
 for contrast,key,w in terms:
  vector=np.zeros(len(retained));status='estimated'
  for name,value in w.items():
   if name not in positions:status='no_within_FE_variation';break
   vector[positions[name]]=value
  rows.append(dict(contrast=contrast,pair_key=key,status=status));weights.append(vector)
 return rows,np.asarray(weights)

def fit(g,pairs,window,model):
 results=[];diagnostics=[]
 for targets in [['top3','finish_p'],['time_gap']]:
  z=g[g[targets].notna().all(axis=1)].copy();des=design(z,pairs);names=list(des);c=old.controls(z).to_numpy(float);sd=c.std(axis=0);c=c[:,sd>1e-12]/sd[sd>1e-12];a=np.column_stack([des.to_numpy(float),c,z[targets].to_numpy(float)]);del des,c;codes=[pd.factorize(z.source_key)[0],pd.factorize(z.horse_id)[0]]
  a,fe_rank=old.demean(a,codes);maxmean=0.
  for code in codes:
   acc=np.zeros((int(code.max())+1,a.shape[1]));np.add.at(acc,code,a);maxmean=max(maxmean,float(np.max(np.abs(acc/np.bincount(code)[:,None]))));del acc
  nc=a.shape[1]-len(targets);keep=a[:,:nc].std(axis=0)>1e-10;retained=np.flatnonzero(keep);x=a[:,:nc][:,keep];y=a[:,nc:].copy();del a;gc.collect();rows,w=contrasts(names,retained,pairs)
  print('SVD start',window,model,targets,len(z),x.shape[1],flush=True)
  u,s,vh=linalg.svd(x,full_matrices=False,check_finite=False);del x;rank=int((s>s[0]*1e-10).sum());ur=u[:,:rank];vr=vh[:rank];sr=s[:rank];coef=vr.T@((ur.T@y)/sr[:,None]);res=y-ur@(ur.T@y);df=len(z)-fe_rank-rank;assert df>0
  ident=np.max(np.abs((w@vr.T)@vr-w),axis=1)<1e-6
  for j,row in enumerate(rows):
   if row['status']=='estimated' and not ident[j]:row['status']='not_identified'
  value=w@coef;factors=(w@vr.T)/sr;cluster_codes=[];counts=[]
  for fields in [['horse_id'],['date'],['horse_id','date']]:
   code=pd.factorize(pd.MultiIndex.from_frame(z[fields]))[0];cluster_codes.append(code);counts.append(int(code.max()+1))
  dfcluster=max(1,min(counts[:2])-1);crit=stats.t.ppf(.975,dfcluster)
  for start in range(0,len(rows),24):
   derivative=factors[start:start+24]@ur.T
   for offset,row in enumerate(rows[start:start+24]):
    i=start+offset
    for ti,target in enumerate(targets):
     out=dict(window=window,model=model,target=target,**row,n=len(z),horses=z.horse_id.nunique(),races=z.source_key.nunique())
     if row['status']=='estimated':
      score=derivative[offset]*res[:,ti]*math.sqrt(len(z)/df);vs=[]
      for code,k in zip(cluster_codes,counts):
       sums=np.bincount(code,weights=score);vs.append(float(sums@sums)*k/max(k-1,1))
      se=math.sqrt(max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2]));est=float(value[i,ti]);out.update(estimate=est,se=se,ci_low=est-crit*se,ci_high=est+crit*se,p=float(2*stats.t.sf(abs(est/se),dfcluster)) if se else 1.,horse_clusters=counts[0],date_clusters=counts[1])
     results.append(out)
  normal=float(np.max(np.abs((vh.T*s)@(u.T@res))))
  for target in targets:diagnostics.append(dict(window=window,model=model,target=target,n=len(z),p=len(retained),rank=rank,fe_rank=int(fe_rank),residual_df=int(df),normal_equation_max=normal,max_fe_mean=maxmean,estimator='exact_race_horse_projection_shared_SVD',design_names=json.dumps(names,ensure_ascii=False)))
  print('Fit complete',window,model,targets,flush=True);del u,vh,ur,vr,coef,res,y,factors,derivative;gc.collect()
 return results,diagnostics

def main():
 d=prepare();metrics=[];coverage=[]
 for window,mask in [('2019_2025',d.year.between(2019,2025)),('2019_2023',d.year.between(2019,2023)),('2024_2025',d.year.between(2024,2025))]:
  allg=d[mask]
  for population,flag in [('primary','primary_eligible'),('expanded_no_annual_minimum','expanded_eligible')]:
   g=allg[allg[flag]].copy();g['state']=np.where(g.changed,'switched','retained');coverage.append(dict(window=window,population=population,n=len(g),changed=int(g.changed.sum()),horses=g.horse_id.nunique(),races=g.source_key.nunique()))
   x=aggregate(g,['pair_key','state']);x['window']=window;x['population']=population;metrics.append(x)
 table=pd.concat(metrics,ignore_index=True);table.to_csv(O/'pair_metrics.csv',index=False);pd.DataFrame(coverage).to_csv(O/'coverage.csv',index=False);primary=table[table.window.eq('2019_2025')&table.population.eq('primary')];rows=[]
 for key,sg in primary.groupby('pair_key'):
  states=sg.set_index('state');sw=states.loc['switched'] if 'switched' in states.index else None;rt=states.loc['retained'] if 'retained' in states.index else None;ss=sw is not None and sw.n>=30 and sw.horses>=15 and sw.races>=20;rs=rt is not None and rt.n>=30 and rt.horses>=15 and rt.races>=20;meet,tid,jid=key.split(':')
  rows.append(dict(pair_key=key,meet=meet,trainer_id=tid,trainer_name=sg.trainer_name.iloc[0],jockey_id=jid,jockey_name=sg.jockey_name.iloc[0],switch_n=0 if sw is None else int(sw.n),retained_n=0 if rt is None else int(rt.n),switch_horses=0 if sw is None else int(sw.horses),retained_horses=0 if rt is None else int(rt.horses),switch_races=0 if sw is None else int(sw.races),retained_races=0 if rt is None else int(rt.races),switch_supported=ss,retained_supported=rs,model_supported=ss and rs,reason='supported' if ss and rs else 'retained_comparator_insufficient' if ss else 'switch_support_insufficient'))
 support=pd.DataFrame(rows);support.to_csv(O/'pair_support.csv',index=False);pairs=support.loc[support.model_supported,'pair_key'].tolist();assert len(pairs)==213
 former=pd.read_csv(R/'20261012_planned_trainer_jockey_pair_effects/outputs/pair_support.csv',dtype={'trainer_id':str,'jockey_id':str});former=former[former.switch_supported].rename(columns={c:'previous_'+c for c in ['switch_n','retained_n','model_supported','reason']});recheck=former[['pair_key','previous_switch_n','previous_retained_n','previous_model_supported','previous_reason']].merge(support,on='pair_key',how='left',validate='one_to_one');recheck.to_csv(O/'previous_37_pairs_recheck.csv',index=False)
 g=d[d.year.between(2019,2025)&d.primary_eligible];fits=[('2019_2025','primary',g),('2019_2025','previous_also_as_card',g[g.previous_classification.eq('planned_as_card')]),('2019_2025','same_owner',g[g.stable_owner]),('2019_2025','expanded_no_annual_minimum',d[d.year.between(2019,2025)&d.expanded_eligible]),('2024_2025','frozen_historical_pairs',d[d.year.between(2024,2025)&d.primary_eligible])];effects=[];diags=[]
 for window,model,g0 in fits:
  res,dg=fit(g0,pairs,window,model);effects+=res;diags+=dg;pd.DataFrame(effects).to_csv(O/'adjusted_associations.csv',index=False);pd.DataFrame(diags).to_csv(O/'model_diagnostics.csv',index=False)
 e=pd.DataFrame(effects);e['q']=np.nan;e['q_all_three_targets']=np.nan
 for _,sg in e[e.status.eq('estimated')].groupby(['window','model','target','contrast']):e.loc[sg.index,'q']=old.bh(sg.assign(family='one'),['family']).q
 for _,sg in e[e.status.eq('estimated')].groupby(['window','model','contrast']):e.loc[sg.index,'q_all_three_targets']=old.bh(sg.assign(family='one'),['family']).q
 e.to_csv(O/'adjusted_associations.csv',index=False)
 annual=d[d.year.between(2019,2025)&d.primary_eligible].copy();annual['state']=np.where(annual.changed,'switched','retained');aggregate(annual,['year','pair_key','state']).to_csv(O/'annual_pair_metrics.csv',index=False)
 d[['row_key','pair_key','primary_eligible','expanded_eligible']].to_parquet(O/'cohort_membership.parquet',index=False)
 events=d[d.year.between(2019,2025)&d.primary_eligible&d.changed].copy();cols=['row_key','source_key','date','year','meet','pair_key','horse_id','horse_name','trainer_id','trainer_name','jockey_id','jockey_name','previous_row_key','previous_date','previous_jockey_id','previous_top3','previous_finish_p','previous_raw_finish_rank','previous_quality_time','top3','win','raw_finish_rank','finish_p','quality_time','time_gap','rank_improvement','raw_time_change_same','gap_days','classification','scheduled_id','card_source_path','card_line_no','source_file','source_item_index'];events[cols].to_parquet(O/'switch_race_events.parquet',index=False)
 inputs=[INPUT,R/'20261012_jockey_switch_trainer_intent/analyze.py',R/'20261012_planned_jockey_changes_by_stable/outputs/verification.json',R/'20261012_planned_trainer_jockey_pair_effects/outputs/pair_support.csv',R/'20261012_planned_trainer_jockey_pair_effects/outputs/verification.json']
 old.dump(O/'source_audit.json',dict(inputs=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=old.sha(p)) for p in inputs],rows=len(d),primary_period='2019~2025',historical_reference='2018',excluded_partial_year='2026',primary_n=len(g),switch_race_events=len(events),supported_switch_pairs=int(support.switch_supported.sum()),supported_with_retained_comparator=len(pairs),previously_insufficient_pairs=int((~recheck.previous_model_supported).sum()),previously_insufficient_now_supported=int(((~recheck.previous_model_supported)&recheck.model_supported).sum()),target_horizon_races=0,future_outcomes_created=False,event_unit='one changed start, current race only',top_jockey_indicator_used=False,first_card_immutability_verified=False,new_prediction_model=False,production_changed=False))
 print('Finished historical pairs',len(pairs),'events',len(events),flush=True)
if __name__=='__main__':main()
