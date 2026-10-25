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

def matrix(g,pairs):
 names=['changed'];columns=[g.changed.to_numpy(float)];jkey=g.meet+':'+g.year.astype(str)+':'+g.jockey_id
 for (meet,year),sg in g.groupby(['meet','year']):
  values=sorted({f'{meet}:{year}:{v}' for v in sg.jockey_id})
  for key in values[1:]:names.append('jockey_year_'+key);columns.append(jkey.eq(key).to_numpy(float))
 tkey=g.meet+':'+g.trainer_id
 for key in sorted(set(tkey)):names.append('trainer_'+key);columns.append(tkey.eq(key).to_numpy(float))
 for key in pairs:names.append('pair_'+key);columns.append(g.pair_key.eq(key).to_numpy(float))
 for key in pairs:names.append('switch_'+key);columns.append((g.changed&g.pair_key.eq(key)).to_numpy(float))
 c=[]
 for name in ['finish_p_mean5','finish_p_n5','previous_finish_p','previous_top3','gap_days','distance_change','grade_change','rating','age_current','weight','body_weight','gate_relative','previous_score']:
  v=g[name].to_numpy(float);bad=~np.isfinite(v);v=np.where(bad,0,v);c.append(bad.astype(float));v=np.log1p(v) if name=='gap_days' else v;c.append(v)
  if name in ['rating','age_current','weight','body_weight','finish_p_mean5','previous_finish_p','gap_days','gate_relative']:c.append(v*v)
 c=np.column_stack(c);sd=c.std(axis=0);x=np.column_stack(columns+[v for v in (c[:,sd>1e-12]/sd[sd>1e-12]).T]);race=pd.factorize(g.source_key)[0];horse=pd.factorize(g.horse_id)[0];nr=race.max()+1;nh=horse.max()+1;n=len(g)
 fe=sparse.coo_matrix((np.ones(2*n),(np.r_[np.arange(n),np.arange(n)],np.r_[race,horse+nr])),shape=(n,nr+nh)).tocsr();return sparse.hstack([sparse.csr_matrix(x),fe]).tocsr(),names

def audit():
 d=data();m=pd.read_parquet(O/'cohort_membership.parquet')
 for c in m:eq(m[c],d[c])
 con=duckdb.connect();con.register('starts',d)
 base=con.sql("SELECT row_key, lag(classification) OVER (PARTITION BY horse_id ORDER BY date) pc,lag(jockey_id) OVER(PARTITION BY horse_id ORDER BY date) pj FROM starts ORDER BY row_key").df();s=d.sort_values('row_key');eq(s.previous_classification,base.pc);eq(s.previous_jockey_id,base.pj)
 raw=con.sql('''WITH scope AS (
 SELECT *,CASE WHEN year IN(2024,2025) THEN '2024_2025' ELSE '2026_partial' END window_label,
 CASE WHEN changed THEN 'switched' ELSE 'retained' END state FROM starts WHERE year BETWEEN 2024 AND 2026),
 pops AS (SELECT *, 'primary' population FROM scope WHERE primary_eligible UNION ALL SELECT *, 'expanded_no_annual_minimum' population FROM scope WHERE expanded_eligible)
 SELECT window_label,population,pair_key,coalesce(state,'all') state,count(*) n,count(distinct horse_id) horses,count(distinct source_key) races,count(distinct date) dates,sum(top3) top3_events,
 avg(top3) top3_rate,avg(win) win_rate,count(previous_top3) previous_top3_n,avg(previous_top3) previous_top3_rate,
 avg(CASE WHEN previous_top3 IS NOT NULL THEN top3 END) paired_current_top3_rate,avg(top3-previous_top3) paired_top3_change,
 avg(raw_finish_rank) rank_mean,avg(finish_p) rank_relative_mean,avg(previous_finish_p) previous_rank_relative_mean,
 count(rank_improvement) rank_improvement_n,avg(rank_improvement) rank_improvement_mean,avg(finish_p_mean5) past5_rank,
 count(time_gap) time_n,avg(time_gap) time_gap_mean,count(raw_time_change_same) same_condition_time_n,avg(raw_time_change_same) same_condition_time_change
 FROM pops GROUP BY GROUPING SETS ((window_label,population,pair_key,state),(window_label,population,pair_key)) ORDER BY window_label,population,pair_key,state''').df().rename(columns={'window_label':'window'})
 metrics=pd.read_csv(O/'pair_metrics.csv').sort_values(['window','population','pair_key','state']).reset_index(drop=True);eq(len(metrics),len(raw))
 for c in raw:eq(metrics[c],raw[c])
 support=pd.read_csv(O/'pair_support.csv',dtype={'trainer_id':str,'jockey_id':str});prim=raw[raw.window.eq('2024_2025')&raw.population.eq('primary')]
 for row in support.itertuples():
  st=prim[prim.pair_key.eq(row.pair_key)].set_index('state');sw=st.loc['switched'] if 'switched' in st.index else None;ret=st.loc['retained'] if 'retained' in st.index else None
  ns=0 if sw is None else int(sw.n);nr=0 if ret is None else int(ret.n);eq([row.switch_n,row.retained_n],[ns,nr]);ss=sw is not None and sw.n>=30 and sw.horses>=15 and sw.races>=20;rs=ret is not None and ret.n>=30 and ret.horses>=15 and ret.races>=20;eq([row.switch_supported,row.retained_supported,row.model_supported],[ss,rs,ss and rs])
 # No primary switch-supported pair from50A silently lost.
 prev=pd.read_csv(R/'20261012_planned_jockey_changes_by_stable/outputs/stable_destination_jockey_metrics.csv',dtype={'trainer_id':str,'jockey_id':str});prev=prev[prev.window.eq('2024_2025')&prev.report_supported];expected=set(prev.meet+':'+prev.trainer_id+':'+prev.jockey_id);assert expected==set(support[support.switch_supported].pair_key)
 pairs=support[support.model_supported].pair_key.tolist();effects=pd.read_csv(O/'adjusted_associations.csv');diags=pd.read_csv(O/'model_diagnostics.csv')
 for _,g in effects[effects.status.eq('estimated')].groupby(['window','model','target','contrast']):eq(g.q,false_discovery_control(g.p.to_numpy(),method='bh'))
 for (_,_,_),g in effects.groupby(['window','model','target']):eq(len(g),1+2*len(pairs));assert set(g[g.contrast.ne('general_other_pairs')].pair_key)==set(pairs)
 assert diags.normal_equation_max.max()<1e-5 and diags.max_fe_mean.max()<1e-7
 # Independently fit primary and partial-period full matrix, without exact-FE projection or analysis import.
 fits=[];ci_checks=[]
 for window,model,mask in [('2024_2025','primary',d.year.between(2024,2025)&d.primary_eligible),('2026_partial','frozen_pairs',d.year.eq(2026)&d.primary_eligible)]:
  for target in ['top3','finish_p','time_gap']:
   g=d[mask&d[target].notna()].copy();full,names=matrix(g,pairs);y=g[target].to_numpy(float);sol=lsqr(full,y,atol=1e-12,btol=1e-12,iter_lim=40000);expected=effects[effects.window.eq(window)&effects.model.eq(model)&effects.target.eq(target)&effects.status.eq('estimated')];coef=[]
   for row in expected.itertuples():
    value=sol[0][0] if row.contrast=='general_other_pairs' else sol[0][names.index('switch_'+row.pair_key)]+(sol[0][0] if row.contrast=='pair_total' else 0);coef.append(value)
   eq(coef,expected.estimate,tol=3e-6)
   if window=='2024_2025' and target=='top3':
    dg=diags[diags.window.eq(window)&diags.model.eq(model)&diags.target.eq(target)].iloc[0]
    # All supported primary pair contrasts, rather than only any significant discoveries.
    for row in expected[expected.contrast.ne('general_other_pairs')].itertuples():
     unit=np.zeros(full.shape[1]);unit[names.index('switch_'+row.pair_key)]=1
     if row.contrast=='pair_total':unit[0]=1
     influence=lsqr(full.T,unit,atol=1e-12,btol=1e-12,iter_lim=40000)[0]*(y-full@sol[0])*np.sqrt(len(g)/dg.residual_df);vars_=[];counts=[]
     for fields in [['horse_id'],['date'],['horse_id','date']]:
      z=g[fields].copy();z['score']=influence;v=z.groupby(fields).score.sum();k=len(v);counts.append(k);vars_.append(np.sum(v.to_numpy()**2)*k/(k-1))
     se=np.sqrt(max(0,vars_[0],vars_[1],vars_[0]+vars_[1]-vars_[2]));crit=stats.t.ppf(.975,min(counts[:2])-1);eq([se,row.estimate-crit*se,row.estimate+crit*se],[row.se,row.ci_low,row.ci_high],tol=3e-6);ci_checks.append(dict(pair_key=row.pair_key,contrast=row.contrast,se_error=float(abs(se-row.se))))
   fits.append(dict(window=window,target=target,stop_code=int(sol[1]),iterations=int(sol[2]),contrasts=len(expected),max_coefficient_error=float(np.max(np.abs(np.asarray(coef)-expected.estimate)))))
   print('Verified independent model',window,target,flush=True)
 for x in json.loads((O/'source_audit.json').read_text())['inputs']:eq([hashlib.sha256((ROOT/x['path']).read_bytes()).hexdigest()],[x['sha256']])
 result=dict(passed=True,checks=checks,cohort_rows=len(d),sql_actual_previous_slots=len(d),raw_groups_independently_aggregated=len(raw),all_previously_supported_pairs_preserved=37,primary_pair_models=len(pairs),bh_verified=True,independent_full_sparse_models=fits,all_primary_top3_pair_cluster_CIs=ci_checks,input_hashes_preserved=True)
 (O/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='all_primary_top3_pair_cluster_CIs'},ensure_ascii=False,indent=2))
if __name__=='__main__':audit()
