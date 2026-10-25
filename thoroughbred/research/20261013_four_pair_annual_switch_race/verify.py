"""Independent SQL aggregates, frozen cohort support, full sparse LSQR contrasts and cluster CIs."""
from pathlib import Path
import json,hashlib,math
import pandas as pd,numpy as np,duckdb
from scipy import sparse,stats
from scipy.sparse.linalg import lsqr
from scipy.stats import false_discovery_control
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';checks=0
INPUT=R/'20261012_planned_jockey_changes_by_stable/outputs/classified_starts.parquet'
def eq(a,b,tol=1e-9):
 global checks
 a=np.asarray(a);b=np.asarray(b);assert a.shape==b.shape,(a.shape,b.shape)
 if a.dtype.kind in 'biufc' and b.dtype.kind in 'biufc':assert np.allclose(a,b,rtol=tol,atol=tol,equal_nan=True),np.nanmax(np.abs(a-b))
 else:assert np.array_equal(pd.Series(a.ravel()).fillna('MISSING').astype(str),pd.Series(b.ravel()).fillna('MISSING').astype(str))
 checks+=a.size

def data():
 d=pd.read_parquet(INPUT);d['pair_key']=d.meet+':'+d.trainer_id+':'+d.jockey_id;d['primary_eligible']=d.main_eligible&d.classification.eq('planned_as_card');d['expanded_eligible']=d.normal_outcome&d.identity_supported&d.stable_trainer&d.same_venue&d.gap_days.between(2,180)&d.classification.eq('planned_as_card');return d

def matrix(g,pairs,four,periods,model):
 names=['changed'];columns=[g.changed.to_numpy(float)];jkey=g.meet+':'+g.year.astype(str)+':'+g.jockey_id
 for (meet,year),sg in g.groupby(['meet','year']):
  values=sorted({f'{meet}:{year}:{v}' for v in sg.jockey_id})
  for key in values[1:]:names.append('jockey_year_'+key);columns.append(jkey.eq(key).to_numpy(float))
 tkey=g.meet+':'+g.trainer_id
 for key in sorted(set(tkey)):names.append('trainer_'+key);columns.append(tkey.eq(key).to_numpy(float))
 for key in pairs:
  if key not in four:names.append('pair_'+key);columns.append(g.pair_key.eq(key).to_numpy(float))
 for key in pairs:
  if key not in four:names.append('switch_'+key);columns.append((g.changed&g.pair_key.eq(key)).to_numpy(float))
 period=g.year.astype(str) if model=='annual' else pd.Series(np.where(g.year.le(2023),'2019_2023','2024_2025'),index=g.index) if model=='eras' else pd.Series('2026_partial',index=g.index)
 for key in four:
  for label in periods:names.append('pair_'+key+'@'+label);columns.append((g.pair_key.eq(key)&period.eq(label)).to_numpy(float))
 for key in four:
  for label in periods:names.append('switch_'+key+'@'+label);columns.append((g.changed&g.pair_key.eq(key)&period.eq(label)).to_numpy(float))
 c=[]
 for name in ['finish_p_mean5','finish_p_n5','previous_finish_p','previous_top3','gap_days','distance_change','grade_change','rating','age_current','weight','body_weight','gate_relative','previous_score']:
  v=g[name].to_numpy(float);bad=~np.isfinite(v);v=np.where(bad,0,v);c.append(bad.astype(float));v=np.log1p(v) if name=='gap_days' else v;c.append(v)
  if name in ['rating','age_current','weight','body_weight','finish_p_mean5','previous_finish_p','gap_days','gate_relative']:c.append(v*v)
 c=np.column_stack(c);sd=c.std(axis=0);x=np.column_stack(columns+[v for v in (c[:,sd>1e-12]/sd[sd>1e-12]).T]);race=pd.factorize(g.source_key)[0];horse=pd.factorize(g.horse_id)[0];nr=race.max()+1;nh=horse.max()+1;n=len(g)
 fe=sparse.coo_matrix((np.ones(2*n),(np.r_[np.arange(n),np.arange(n)],np.r_[race,horse+nr])),shape=(n,nr+nh)).tocsr();return sparse.hstack([sparse.csr_matrix(x),fe]).tocsr(),names

def audit():
 d=data();frozen=pd.read_csv(O/'frozen_four_pairs.csv');four=frozen.pair_key.tolist();previous=pd.read_csv(R/'20261012_historical_planned_pair_switch_race/outputs/nominal_top3_candidates.csv');eq(sorted(four),sorted(previous[previous.estimate.gt(0)].pair_key));pairs=pd.read_csv(R/'20261012_historical_planned_pair_switch_race/outputs/pair_support.csv');pairs=pairs[pairs.model_supported].pair_key.tolist();assert len(four)==4 and len(pairs)==213
 con=duckdb.connect();con.register('starts',d)
 previous_slots=con.sql('SELECT row_key,lag(row_key) OVER(PARTITION BY horse_id ORDER BY date) prior_row,lag(jockey_id) OVER(PARTITION BY horse_id ORDER BY date) prior_rider FROM starts ORDER BY row_key').df();ordered=d.sort_values('row_key');eq(ordered.previous_row_key,previous_slots.prior_row);eq(ordered.previous_jockey_id,previous_slots.prior_rider)
 candidate=d[d.primary_eligible&d.year.between(2019,2026)&d.pair_key.isin(four)];con.register('candidates',candidate)
 raw=con.sql('''WITH scope AS (
 SELECT *, 'annual' model,cast(year AS varchar) period FROM candidates WHERE year BETWEEN 2019 AND 2025
 UNION ALL SELECT *, 'eras' model,CASE WHEN year<=2023 THEN '2019_2023' ELSE '2024_2025' END period FROM candidates WHERE year BETWEEN 2019 AND 2025
 UNION ALL SELECT *, 'recent_partial' model,'2026_partial' period FROM candidates WHERE year=2026)
 SELECT model,period,pair_key,CASE WHEN changed THEN 'switched' ELSE 'retained' END state,
 count(*) n,count(distinct horse_id) horses,count(distinct source_key) races,count(distinct date) dates,sum(top3) top3_events,avg(top3) top3_rate,avg(win) win_rate,count(previous_top3) previous_top3_n,avg(previous_top3) previous_top3_rate,avg(CASE WHEN previous_top3 IS NOT NULL THEN top3 END) paired_current_top3_rate,avg(top3-previous_top3) paired_top3_change,avg(raw_finish_rank) rank_mean,avg(finish_p) rank_relative_mean,avg(previous_finish_p) previous_rank_relative_mean,count(rank_improvement) rank_improvement_n,avg(rank_improvement) rank_improvement_mean,avg(finish_p_mean5) past5_rank,count(time_gap) time_n,avg(time_gap) time_gap_mean,count(raw_time_change_same) same_condition_time_n,avg(raw_time_change_same) same_condition_time_change FROM scope GROUP BY model,period,pair_key,state''').df()
 table=pd.read_csv(O/'raw_period_metrics.csv',dtype={'period':str});keys=['model','period','pair_key','state'];full=table[keys].merge(raw,on=keys,how='left',validate='one_to_one')
 for c in ['n','horses','races','dates','top3_events','previous_top3_n','rank_improvement_n','time_n','same_condition_time_n']:full[c]=full[c].fillna(0)
 for c in raw.columns:eq(table[c],full[c])
 assert len(table)==80 and len(raw)<=80;eq(table.state_supported,table.n.ge(30)&table.horses.ge(15)&table.races.ge(20))
 events=pd.read_parquet(O/'four_pair_switch_events.parquet');expected=candidate[candidate.changed]
 assert len(events)==len(expected)==240 and events.row_key.is_unique
 for c in events:eq(events[c],expected[c])
 assert events.classification.eq('planned_as_card').all() and events.jockey_id.ne(events.previous_jockey_id).all();eq(events.jockey_id,events.scheduled_id);assert not any(any(t in c for t in ['future','next_','lead_']) for c in events)
 audit=json.loads((O/'source_audit.json').read_text());assert audit['target_horizon_races']==0 and audit['future_outcomes_created'] is False
 effects=pd.read_csv(O/'adjusted_period_effects.csv',dtype={'period':str});diags=pd.read_csv(O/'model_diagnostics.csv');assert len(effects)==132
 for _,z in effects.groupby(['model','target','contrast']):eq(z.q_fixed_family,false_discovery_control(z.p.fillna(1).to_numpy()))
 for _,z in effects.groupby(['model','contrast']):eq(z.q_all_targets_fixed_family,false_discovery_control(z.p.fillna(1).to_numpy()))
 for c in ['switched','retained']:
  subset=table[table.state.eq(c)].set_index(['model','period','pair_key']);idx=pd.MultiIndex.from_frame(effects[['model','period','pair_key']])
  for col in ['n','horses','races','top3_events','top3_rate','previous_top3_rate','paired_current_top3_rate']:eq(effects[c+'_'+col],subset[col].reindex(idx))
 eq(effects.pair_period_supported,effects.switched_n.ge(30)&effects.switched_horses.ge(15)&effects.switched_races.ge(20)&effects.retained_n.ge(30)&effects.retained_horses.ge(15)&effects.retained_races.ge(20))
 assert diags.normal_equation_max.max()<1e-5 and diags.max_fe_mean.max()<1e-7
 fits=[];cis=[]
 for model,periods,mask in [('annual',[str(y) for y in range(2019,2026)],d.primary_eligible&d.year.between(2019,2025)),('eras',['2019_2023','2024_2025'],d.primary_eligible&d.year.between(2019,2025)),('recent_partial',['2026_partial'],d.primary_eligible&d.year.eq(2026))]:
  for target in ['top3','finish_p','time_gap']:
   g=d[mask&d[target].notna()].copy();full,names=matrix(g,pairs,four,periods,model);norm=np.sqrt(np.asarray(full.power(2).sum(axis=0)).ravel());scale=1/np.where(norm>0,norm,1);scaled=full.multiply(scale).tocsr();y=g[target].to_numpy(float);sol=lsqr(scaled,y,atol=1e-12,btol=1e-12,iter_lim=40000);coef=scale*sol[0];residual=y-full@coef;z=effects[effects.model.eq(model)&effects.target.eq(target)&effects.status.eq('estimated')];values=[];dg=diags[diags.model.eq(model)&diags.target.eq(target)].iloc[0]
   for row in z.itertuples():
    unit=np.zeros(full.shape[1])
    if row.contrast=='pair_total':unit[0]=1;unit[names.index('switch_'+row.pair_key+'@'+row.period)]=1
    else:unit[names.index('switch_'+row.pair_key+'@2024_2025')]=1;unit[names.index('switch_'+row.pair_key+'@2019_2023')]=-1
    value=float(unit@coef);values.append(value)
    if target=='top3' or row.q_fixed_family<.05:
     derivative=lsqr(scaled.T,scale*unit,atol=1e-12,btol=1e-12,iter_lim=40000)[0];score=derivative*residual*np.sqrt(len(g)/dg.residual_df);vs=[];counts=[]
     for fields in [['horse_id'],['date'],['horse_id','date']]:
      a=g[fields].copy();a['score']=score;b=a.groupby(fields).score.sum();k=len(b);counts.append(k);vs.append(float(b@b)*k/(k-1))
     se=np.sqrt(max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2]));critical=stats.t.ppf(.975,min(counts[:2])-1);eq([se,row.estimate-critical*se,row.estimate+critical*se],[row.se,row.ci_low,row.ci_high],tol=3e-6);cis.append(dict(model=model,target=target,pair_key=row.pair_key,period=row.period,contrast=row.contrast,se_error=abs(se-row.se)))
   eq(values,z.estimate,tol=3e-6);fits.append(dict(model=model,target=target,stop=int(sol[1]),iterations=int(sol[2]),contrasts=len(z),max_coefficient_error=float(np.max(np.abs(values-z.estimate))) if len(z) else None));print('Independently verified',model,target,'contrasts',len(z),flush=True)
 for x in audit['inputs']:eq([hashlib.sha256((ROOT/x['path']).read_bytes()).hexdigest()],[x['sha256']])
 out=dict(passed=True,checks=checks,source_rows=len(d),current_switch_events=len(events),target_horizon_races=0,annual_years_complete=7,partial_2026_separate=True,raw_grid_rows=len(table),sql_raw_nonzero_groups=len(raw),frozen_four_verified=True,fixed_BH_with_unidentified_p_one=True,independent_sparse_models=fits,independent_cluster_CIs=cis,input_hashes_preserved=True)
 (O/'verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k!='independent_cluster_CIs'},ensure_ascii=False,indent=2))
if __name__=='__main__':audit()
