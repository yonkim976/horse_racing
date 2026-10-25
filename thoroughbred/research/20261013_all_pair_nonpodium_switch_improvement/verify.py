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
 for name in ['previous_time_gap','previous_quality_time','previous_moisture','previous_field_size']:
  v=g[name].to_numpy(float);bad=~np.isfinite(v);v=np.where(bad,0,v);c.extend([bad.astype(float),v,v*v])
 c=np.column_stack(c);sd=c.std(axis=0);x=np.column_stack(columns+[v for v in (c[:,sd>1e-12]/sd[sd>1e-12]).T]);race=pd.factorize(g.source_key)[0];horse=pd.factorize(g.horse_id)[0];nr=race.max()+1;nh=horse.max()+1;n=len(g)
 fe=sparse.coo_matrix((np.ones(2*n),(np.r_[np.arange(n),np.arange(n)],np.r_[race,horse+nr])),shape=(n,nr+nh)).tocsr();return sparse.hstack([sparse.csr_matrix(x),fe]).tocsr(),names

def data():
 d=pd.read_parquet(INPUT);d['pair_key']=d.meet+':'+d.trainer_id+':'+d.jockey_id;d['primary_eligible']=d.main_eligible&d.classification.eq('planned_as_card');lookup=d.set_index('row_key')
 for c in ['time_gap','moisture','field_size']:d['previous_'+c]=d.previous_row_key.map(lookup[c])
 d['nonpodium']=d.normal_outcome&d.raw_finish_rank.gt(3);rv=d.previous_finish_p.notna()&d.finish_p.notna();tv=d.raw_time_change_same.notna()
 d['nonpodium_rank_improved']=np.where(rv,(d.nonpodium&(d.previous_finish_p-d.finish_p).gt(1e-12)).astype(float),np.nan);d['nonpodium_time_improved']=np.where(tv,(d.nonpodium&(d.quality_time-d.previous_quality_time).lt(-1e-9)).astype(float),np.nan)
 d['nonpodium_raw_rank_improved']=np.where(rv&d.previous_raw_finish_rank.notna(),(d.nonpodium&d.previous_raw_finish_rank.gt(d.raw_finish_rank)).astype(float),np.nan);d['nonpodium_winner_gap_improved']=np.where(d.same_conditions&d.time_gap.notna()&d.previous_time_gap.notna(),(d.nonpodium&d.time_gap.lt(d.previous_time_gap-1e-9)).astype(float),np.nan)
 d['conditional_finish_p']=d.finish_p.where(d.nonpodium);d['conditional_time_gap']=d.time_gap.where(d.nonpodium);d['rank_nonpodium_comparable']=(d.nonpodium&rv).astype(int);d['time_nonpodium_comparable']=(d.nonpodium&tv).astype(int);d['rank_change_nonpodium']=(d.previous_finish_p-d.finish_p).where(d.nonpodium);d['seconds_change_nonpodium']=(d.quality_time-d.previous_quality_time).where(d.nonpodium&tv);return d

def windows(d):
 yield '2019_2025',d.primary_eligible&d.year.between(2019,2025)
 for y in range(2019,2026):yield str(y),d.primary_eligible&d.year.eq(y)
 yield '2019_2023',d.primary_eligible&d.year.between(2019,2023)
 yield '2024_2025',d.primary_eligible&d.year.between(2024,2025)
 yield '2026_partial',d.primary_eligible&d.year.eq(2026)

def audit():
 d=data();pairs=pd.read_csv(O/'frozen_213_pairs.csv').pair_key.tolist();old=pd.read_csv(R/'20261012_historical_planned_pair_switch_race/outputs/pair_support.csv');eq(pairs,old[old.model_supported].pair_key);assert len(pairs)==213
 con=duckdb.connect();con.register('starts',d)
 lagged=con.sql('SELECT row_key,lag(row_key) OVER(PARTITION BY horse_id ORDER BY date) prior_row,lag(time_gap) OVER(PARTITION BY horse_id ORDER BY date) prior_gap,lag(moisture) OVER(PARTITION BY horse_id ORDER BY date) prior_moisture,lag(field_size) OVER(PARTITION BY horse_id ORDER BY date) prior_field FROM starts ORDER BY row_key').df();z=d.sort_values('row_key')
 for a,b in [('previous_row_key','prior_row'),('previous_time_gap','prior_gap'),('previous_moisture','prior_moisture'),('previous_field_size','prior_field')]:eq(z[a],lagged[b])
 definitions=con.sql('''SELECT row_key,
 CASE WHEN previous_finish_p IS NOT NULL AND finish_p IS NOT NULL THEN cast(normal_outcome AND raw_finish_rank>3 AND previous_finish_p-finish_p>1e-12 AS double) END rank_case,
 CASE WHEN same_conditions AND quality_time IS NOT NULL AND previous_quality_time IS NOT NULL THEN cast(normal_outcome AND raw_finish_rank>3 AND quality_time-previous_quality_time < -1e-9 AS double) END time_case,
 CASE WHEN previous_finish_p IS NOT NULL AND finish_p IS NOT NULL AND previous_raw_finish_rank IS NOT NULL THEN cast(normal_outcome AND raw_finish_rank>3 AND previous_raw_finish_rank>raw_finish_rank AS double) END raw_rank_case FROM starts ORDER BY row_key''').df()
 for a,b in [('nonpodium_rank_improved','rank_case'),('nonpodium_time_improved','time_case'),('nonpodium_raw_rank_improved','raw_rank_case')]:eq(z[a],definitions[b])
 # SQL cases partition all comparable observations into podium / nonpodium improved / other nonpodium.
 assert ((d.nonpodium_rank_improved==1)&d.top3.eq(1)).sum()==0 and ((d.nonpodium_time_improved==1)&d.top3.eq(1)).sum()==0
 events=pd.read_parquet(O/'current_switch_event_cases.parquet');expected=d[d.primary_eligible&d.year.between(2019,2026)&d.changed];assert len(events)==len(expected) and events.row_key.is_unique
 for c in events:eq(events[c],expected[c])
 assert not any(any(token in c for token in ['future','next_','lead_']) for c in events)
 # All raw pair groups, including unsupported pairs; no outcome-based short list.
 chunks=[]
 for label,mask in windows(d):
  g=d[mask].copy();g['period']=label;chunks.append(g)
 scope=pd.concat(chunks,ignore_index=True);con.register('scope',scope)
 raw=con.sql('''SELECT period,pair_key,CASE WHEN changed THEN 'switched' ELSE 'retained' END state,count(*) n,count(distinct horse_id) horses,count(distinct source_key) races,sum(top3) top3_events,avg(top3) top3_rate,sum(cast(nonpodium AS integer)) nonpodium_n,count(nonpodium_rank_improved) rank_comparable_n,sum(rank_nonpodium_comparable) rank_nonpodium_comparable_n,sum(nonpodium_rank_improved) rank_improved_events,avg(nonpodium_rank_improved) rank_case_rate,sum(nonpodium_raw_rank_improved) raw_rank_improved_events,count(nonpodium_time_improved) time_comparable_n,sum(time_nonpodium_comparable) time_nonpodium_comparable_n,sum(nonpodium_time_improved) time_improved_events,avg(nonpodium_time_improved) time_case_rate,sum(nonpodium_winner_gap_improved) winner_gap_improved_events,avg(rank_change_nonpodium) rank_change_nonpodium_mean,avg(seconds_change_nonpodium) seconds_change_nonpodium_mean,avg(conditional_finish_p) conditional_finish_p_mean,count(conditional_time_gap) conditional_time_gap_n,avg(conditional_time_gap) conditional_time_gap_mean FROM scope GROUP BY period,pair_key,state ORDER BY period,pair_key,state''').df()
 table=pd.read_csv(O/'raw_period_pair_metrics.csv',dtype={'period':str}).sort_values(['period','pair_key','state']).reset_index(drop=True);eq(len(table),len(raw))
 for c in ['rank_improved_events','raw_rank_improved_events','time_improved_events','winner_gap_improved_events']:raw[c]=raw[c].fillna(0)
 for c in raw:eq(table[c],raw[c])
 eq(table.rank_case_rate_among_nonpodium,table.rank_improved_events/table.rank_nonpodium_comparable_n.replace(0,np.nan));eq(table.time_case_rate_among_nonpodium,table.time_improved_events/table.time_nonpodium_comparable_n.replace(0,np.nan))
 effects=pd.read_csv(O/'adjusted_associations.csv',dtype={'period':str});diags=pd.read_csv(O/'model_diagnostics.csv',dtype={'period':str});support=pd.read_csv(O/'target_pair_support.csv',dtype={'period':str});assert len(effects)==28*213 and len(diags)==28
 for _,sg in effects.groupby(['period','model','target']):eq(len(sg),213);eq(sorted(sg.pair_key),sorted(pairs));eq(sg.q,false_discovery_control(sg.p.fillna(1).to_numpy()))
 for _,sg in effects.groupby(['period','model']):eq(sg.q_joint_targets,false_discovery_control(sg.p.fillna(1).to_numpy()))
 annual=effects[effects.period.isin([str(y) for y in range(2019,2026)])]
 for _,sg in annual.groupby(['model','target']):eq(sg.q_all_years,false_discovery_control(sg.p.fillna(1).to_numpy()))
 for _,sg in annual.groupby('model'):eq(sg.q_all_years_joint_targets,false_discovery_control(sg.p.fillna(1).to_numpy()))
 assert diags.normal_equation_max.max()<1e-5 and diags.max_fe_mean.max()<1e-7
 # Fixed audit shortlist for main intervals, plus all other-period BH signals.
 short={}
 for target,sg in effects[effects.period.eq('2019_2025')].groupby('target'):
  short[target]=set(sg[sg.p.lt(.05)].pair_key)|set(sg.nlargest(5,'switched_n').pair_key)
  if target.startswith('nonpodium_'):short[target]|=set(sg[sg.estimate.gt(0)].nlargest(5,'estimate').pair_key)
 fits=[];cis=[];independent_support=[]
 for label,mask in windows(d):
  targets=['nonpodium_rank_improved','nonpodium_time_improved']+(['conditional_finish_p','conditional_time_gap'] if label in ['2019_2025','2024_2025','2026_partial'] else [])
  for target in targets:
   g=d[mask&d[target].notna()].copy();model='all_starts_composite' if target.startswith('nonpodium_') else 'conditional_nonpodium'
   for (key,changed),sg in g.groupby(['pair_key','changed']):independent_support.append(dict(period=label,model=model,target=target,pair_key=key,state='switched' if changed else 'retained',n=len(sg),horses=sg.horse_id.nunique(),races=sg.source_key.nunique()))
   full,names=matrix(g,pairs);norm=np.sqrt(np.asarray(full.power(2).sum(axis=0)).ravel());scale=1/np.where(norm>0,norm,1);scaled=full.multiply(scale).tocsr();y=g[target].to_numpy(float);sol=lsqr(scaled,y,atol=1e-12,btol=1e-12,iter_lim=40000);coef=scale*sol[0];res=y-full@coef;sg=effects[effects.period.eq(label)&effects.target.eq(target)&effects.status.eq('estimated')];values=[];diag=diags[diags.period.eq(label)&diags.target.eq(target)].iloc[0]
   for row in sg.itertuples():
    unit=np.zeros(full.shape[1]);unit[0]=1;unit[names.index('switch_'+row.pair_key)]=1;value=float(unit@coef);values.append(value)
    if (label=='2019_2025' and row.pair_key in short[target]) or row.q<.05:
     derivative=lsqr(scaled.T,scale*unit,atol=1e-12,btol=1e-12,iter_lim=40000)[0];score=derivative*res*np.sqrt(len(g)/diag.residual_df);vs=[];counts=[]
     for fields in [['horse_id'],['date'],['horse_id','date']]:
      a=g[fields].copy();a['score']=score;b=a.groupby(fields).score.sum();k=len(b);counts.append(k);vs.append(float(b@b)*k/(k-1))
     se=np.sqrt(max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2]));crit=stats.t.ppf(.975,min(counts[:2])-1);eq([se,value-crit*se,value+crit*se],[row.se,row.ci_low,row.ci_high],tol=3e-6);cis.append(dict(period=label,target=target,pair_key=row.pair_key,se_error=abs(se-row.se)))
   eq(values,sg.estimate,tol=3e-6);fits.append(dict(period=label,target=target,stop=int(sol[1]),iterations=int(sol[2]),contrasts=len(sg),max_coefficient_error=float(np.max(np.abs(values-sg.estimate))) if len(sg) else None));print('Verified model',label,target,'CIs cumulative',len(cis),flush=True)
 independently=pd.DataFrame(independent_support).sort_values(['period','model','target','pair_key','state']).reset_index(drop=True);support=support.sort_values(['period','model','target','pair_key','state']).reset_index(drop=True)
 for c in support:eq(support[c],independently[c])
 for state in ['switched','retained']:
  z=support[support.state.eq(state)].set_index(['period','model','target','pair_key']);ix=pd.MultiIndex.from_frame(effects[['period','model','target','pair_key']])
  for c in ['n','horses','races']:eq(effects[state+'_'+c],z[c].reindex(ix).fillna(0))
 eq(effects.target_supported,effects.switched_n.ge(30)&effects.retained_n.ge(30)&effects.switched_horses.ge(15)&effects.retained_horses.ge(15)&effects.switched_races.ge(20)&effects.retained_races.ge(20))
 audit=json.loads((O/'source_audit.json').read_text());assert audit['target_horizon_races']==0 and not audit['future_outcomes_created'] and not audit['prior_four_used_for_selection']
 for x in audit['inputs']:eq([hashlib.sha256((ROOT/x['path']).read_bytes()).hexdigest()],[x['sha256']])
 out=dict(passed=True,checks=checks,source_rows=len(d),current_switch_events=len(events),all_raw_groups=len(raw),fixed_pairs=213,prior_four_not_used=True,target_horizon_races=0,definitions_independently_verified=True,BH_fixed_families_verified=True,all_target_support_verified=True,independent_models=fits,independent_cluster_CIs=cis,input_hashes_preserved=True)
 (O/'verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k not in ['independent_cluster_CIs','independent_models']},ensure_ascii=False,indent=2))
if __name__=='__main__':audit()
