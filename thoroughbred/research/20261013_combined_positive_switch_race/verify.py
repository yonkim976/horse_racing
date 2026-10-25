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
 c.extend([g.rank_comparable.to_numpy(float),g.time_comparable.to_numpy(float)])
 c=np.column_stack(c);sd=c.std(axis=0);x=np.column_stack(columns+[v for v in (c[:,sd>1e-12]/sd[sd>1e-12]).T]);race=pd.factorize(g.source_key)[0];horse=pd.factorize(g.horse_id)[0];nr=race.max()+1;nh=horse.max()+1;n=len(g)
 fe=sparse.coo_matrix((np.ones(2*n),(np.r_[np.arange(n),np.arange(n)],np.r_[race,horse+nr])),shape=(n,nr+nh)).tocsr();return sparse.hstack([sparse.csr_matrix(x),fe]).tocsr(),names

def data():
 d=pd.read_parquet(INPUT);d['pair_key']=d.meet+':'+d.trainer_id+':'+d.jockey_id;d['primary_eligible']=d.main_eligible&d.classification.eq('planned_as_card');lookup=d.set_index('row_key')
 for c in ['time_gap','moisture','field_size']:d['previous_'+c]=d.previous_row_key.map(lookup[c])
 d['nonpodium']=d.normal_outcome&d.raw_finish_rank.gt(3);rv=d.previous_finish_p.notna()&d.finish_p.notna();tv=d.raw_time_change_same.notna()
 d['nonpodium_rank_improved']=np.where(rv,(d.nonpodium&(d.previous_finish_p-d.finish_p).gt(1e-12)).astype(float),np.nan);d['nonpodium_time_improved']=np.where(tv,(d.nonpodium&(d.quality_time-d.previous_quality_time).lt(-1e-9)).astype(float),np.nan)
 d['nonpodium_raw_rank_improved']=np.where(rv&d.previous_raw_finish_rank.notna(),(d.nonpodium&d.previous_raw_finish_rank.gt(d.raw_finish_rank)).astype(float),np.nan);d['nonpodium_winner_gap_improved']=np.where(d.same_conditions&d.time_gap.notna()&d.previous_time_gap.notna(),(d.nonpodium&d.time_gap.lt(d.previous_time_gap-1e-9)).astype(float),np.nan)
 d['conditional_finish_p']=d.finish_p.where(d.nonpodium);d['conditional_time_gap']=d.time_gap.where(d.nonpodium);d['rank_nonpodium_comparable']=(d.nonpodium&rv).astype(int);d['time_nonpodium_comparable']=(d.nonpodium&tv).astype(int);d['rank_change_nonpodium']=(d.previous_finish_p-d.finish_p).where(d.nonpodium);d['seconds_change_nonpodium']=(d.quality_time-d.previous_quality_time).where(d.nonpodium&tv)
 d['rank_comparable']=d.previous_finish_p.notna()&d.finish_p.notna();d['time_comparable']=d.same_conditions&d.quality_time.notna()&d.previous_quality_time.notna();podium=d.top3.eq(1);r=d.nonpodium_rank_improved.eq(1);t=d.nonpodium_time_improved.eq(1);complete=d.rank_comparable&d.time_comparable;positive=podium|r|t
 d['combined_complete']=np.where(complete,positive.astype(float),np.nan);d['combined_documented']=positive.astype(float);d['podium_or_rank']=np.where(d.rank_comparable,(podium|r).astype(float),np.nan)
 d['positive_podium']=podium.astype(int);d['positive_rank_and_time']=(~podium&r&t).astype(int);d['positive_rank_only_confirmed']=(~podium&r&~t).astype(int);d['positive_time_only_confirmed']=(~podium&~r&t).astype(int);d['confirmed_nonpositive']=(~positive&complete).astype(int);d['unconfirmed_nonpositive']=(~positive&~complete).astype(int)
 return d

def windows(d):
 yield '2019_2025',d.primary_eligible&d.year.between(2019,2025)
 for y in range(2019,2026):yield str(y),d.primary_eligible&d.year.eq(y)
 yield '2019_2023',d.primary_eligible&d.year.between(2019,2023)
 yield '2024_2025',d.primary_eligible&d.year.between(2024,2025)
 yield '2026_partial',d.primary_eligible&d.year.eq(2026)

def audit():
 d=data();pairs=pd.read_csv(O/'frozen_213_pairs.csv').pair_key.tolist();prev=pd.read_csv(R/'20261013_all_pair_nonpodium_switch_improvement/outputs/frozen_213_pairs.csv');eq(pairs,prev.pair_key);assert len(pairs)==213
 con=duckdb.connect();con.register('starts',d)
 actual=con.sql('SELECT row_key,lag(row_key) OVER(PARTITION BY horse_id ORDER BY date) prior_row,lag(time_gap) OVER(PARTITION BY horse_id ORDER BY date) prior_gap,lag(moisture) OVER(PARTITION BY horse_id ORDER BY date) prior_moisture,lag(field_size) OVER(PARTITION BY horse_id ORDER BY date) prior_field FROM starts ORDER BY row_key').df();ordered=d.sort_values('row_key')
 for a,b in [('previous_row_key','prior_row'),('previous_time_gap','prior_gap'),('previous_moisture','prior_moisture'),('previous_field_size','prior_field')]:eq(ordered[a],actual[b])
 definitions=con.sql('''WITH flags AS (SELECT *,top3=1 podium,previous_finish_p IS NOT NULL AND finish_p IS NOT NULL rv,coalesce(same_venue AND distance_m=previous_distance_m AND grade_bucket=previous_grade_bucket AND quality_time IS NOT NULL AND previous_quality_time IS NOT NULL,false) tv,
 coalesce(top3=0 AND previous_finish_p-finish_p>1e-12,false) r,coalesce(top3=0 AND same_venue AND distance_m=previous_distance_m AND grade_bucket=previous_grade_bucket AND quality_time-previous_quality_time < -1e-9,false) t FROM starts)
 SELECT row_key,rv rank_comparable,tv time_comparable,
 CASE WHEN rv AND tv THEN cast(coalesce(podium,false) OR r OR t AS double) END combined_complete,
 cast(coalesce(podium,false) OR r OR t AS double) combined_documented,
 CASE WHEN rv THEN cast(coalesce(podium,false) OR r AS double) END podium_or_rank FROM flags ORDER BY row_key''').df()
 for c in definitions:
  if c!='row_key':eq(ordered[c],definitions[c])
 assert d[d.normal_outcome][['positive_podium','positive_rank_and_time','positive_rank_only_confirmed','positive_time_only_confirmed','confirmed_nonpositive','unconfirmed_nonpositive']].sum(axis=1).eq(1).all()
 events=pd.read_parquet(O/'current_switch_combined_events.parquet');expected=d[d.primary_eligible&d.year.between(2019,2026)&d.changed];assert len(events)==len(expected)==44341 and events.row_key.is_unique
 for c in events:eq(events[c],expected[c])
 previous_events=pd.read_parquet(R/'20261013_all_pair_nonpodium_switch_improvement/outputs/current_switch_event_cases.parquet')
 for c in previous_events:eq(events[c],previous_events[c])
 assert not any(any(token in c for token in ['future','next_','lead_']) for c in events)
 targets=['combined_complete','combined_documented','podium_or_rank'];partitions=['positive_podium','positive_rank_and_time','positive_rank_only_confirmed','positive_time_only_confirmed','confirmed_nonpositive','unconfirmed_nonpositive'];chunks=[];coverage=[]
 for period,mask in windows(d):
  g=d[mask].copy();g['period']=period;chunks.append(g);sw=g[g.changed];coverage.append(dict(period=period,n=len(g),changed=len(sw),pairs=g.pair_key.nunique(),podium=int(sw.positive_podium.sum()),rank_time_both=int(sw.positive_rank_and_time.sum()),rank_only_confirmed=int(sw.positive_rank_only_confirmed.sum()),time_only_confirmed=int(sw.positive_time_only_confirmed.sum()),confirmed_nonpositive=int(sw.confirmed_nonpositive.sum()),unconfirmed_nonpositive=int(sw.unconfirmed_nonpositive.sum()),combined_complete_n=int(sw.combined_complete.notna().sum()),combined_complete_positive=int(sw.combined_complete.sum()),documented_positive=int(sw.combined_documented.sum()),podium_or_rank_n=int(sw.podium_or_rank.notna().sum()),podium_or_rank_positive=int(sw.podium_or_rank.sum())))
 cov=pd.read_csv(O/'coverage.csv',dtype={'period':str});indcov=pd.DataFrame(coverage)
 for c in cov:eq(cov[c],indcov[c])
 scope=pd.concat(chunks,ignore_index=True);con.register('scope',scope)
 raw=con.sql('''SELECT period,pair_key,CASE WHEN changed THEN 'switched' ELSE 'retained' END state,count(*) n,count(distinct horse_id) horses,count(distinct source_key) races,sum(top3) top3_events,avg(top3) top3_rate,sum(cast(nonpodium AS integer)) nonpodium_n,
 count(combined_complete) combined_complete_n,coalesce(sum(combined_complete),0) combined_complete_events,avg(combined_complete) combined_complete_rate,
 count(combined_documented) combined_documented_n,sum(combined_documented) combined_documented_events,avg(combined_documented) combined_documented_rate,
 count(podium_or_rank) podium_or_rank_n,coalesce(sum(podium_or_rank),0) podium_or_rank_events,avg(podium_or_rank) podium_or_rank_rate,
 sum(positive_podium) positive_podium,sum(positive_rank_and_time) positive_rank_and_time,sum(positive_rank_only_confirmed) positive_rank_only_confirmed,sum(positive_time_only_confirmed) positive_time_only_confirmed,sum(confirmed_nonpositive) confirmed_nonpositive,sum(unconfirmed_nonpositive) unconfirmed_nonpositive FROM scope GROUP BY period,pair_key,state ORDER BY period,pair_key,state''').df()
 table=pd.read_csv(O/'raw_period_pair_metrics.csv',dtype={'period':str}).sort_values(['period','pair_key','state']).reset_index(drop=True);eq(len(table),len(raw))
 for c in raw:eq(table[c],raw[c])
 eq(table[partitions].sum(axis=1),table.n);eq(table[['positive_podium','positive_rank_and_time','positive_rank_only_confirmed','positive_time_only_confirmed']].sum(axis=1),table.combined_documented_events)
 e=pd.read_csv(O/'adjusted_associations.csv',dtype={'period':str});diags=pd.read_csv(O/'model_diagnostics.csv',dtype={'period':str});support=pd.read_csv(O/'target_pair_support.csv',dtype={'period':str});assert len(e)==33*213 and len(diags)==33
 for _,g in e.groupby(['period','target']):eq(len(g),213);eq(sorted(g.pair_key),sorted(pairs));eq(g.q,false_discovery_control(g.p.fillna(1).to_numpy()))
 for _,g in e.groupby('period'):eq(g.q_joint_targets,false_discovery_control(g.p.fillna(1).to_numpy()))
 annual=e[e.period.isin([str(y) for y in range(2019,2026)])]
 for _,g in annual.groupby('target'):eq(g.q_all_years,false_discovery_control(g.p.fillna(1).to_numpy()))
 eq(annual.q_all_years_joint_targets,false_discovery_control(annual.p.fillna(1).to_numpy()));assert diags.normal_equation_max.max()<1e-5 and diags.max_fe_mean.max()<1e-7
 shorts={}
 for target,g in e[e.period.eq('2019_2025')].groupby('target'):shorts[target]=set(g[g.p.lt(.05)].pair_key)|set(g[g.estimate.gt(0)].nlargest(5,'estimate').pair_key)|set(g.nlargest(5,'switched_n').pair_key)
 fits=[];cis=[];support_rows=[]
 for period,mask in windows(d):
  for target in targets:
   g=d[mask&d[target].notna()].copy();full,names=matrix(g,pairs);norm=np.sqrt(np.asarray(full.power(2).sum(axis=0)).ravel());scale=1/np.where(norm>0,norm,1);scaled=full.multiply(scale).tocsr();y=g[target].to_numpy(float);sol=lsqr(scaled,y,atol=1e-12,btol=1e-12,iter_lim=40000);coef=scale*sol[0];res=y-full@coef;z=e[e.period.eq(period)&e.target.eq(target)&e.status.eq('estimated')];diag=diags[diags.period.eq(period)&diags.target.eq(target)].iloc[0];values=[]
   for (key,changed),sg in g.groupby(['pair_key','changed']):support_rows.append(dict(period=period,model='positive_union',target=target,pair_key=key,state='switched' if changed else 'retained',n=len(sg),horses=sg.horse_id.nunique(),races=sg.source_key.nunique()))
   for row in z.itertuples():
    unit=np.zeros(full.shape[1]);unit[0]=1;unit[names.index('switch_'+row.pair_key)]=1;value=float(unit@coef);values.append(value)
    if (period=='2019_2025' and row.pair_key in shorts[target]) or row.q<.05:
     der=lsqr(scaled.T,scale*unit,atol=1e-12,btol=1e-12,iter_lim=40000)[0];score=der*res*np.sqrt(len(g)/diag.residual_df);vs=[];counts=[]
     for fields in [['horse_id'],['date'],['horse_id','date']]:
      a=g[fields].copy();a['score']=score;b=a.groupby(fields).score.sum();k=len(b);counts.append(k);vs.append(float(b@b)*k/(k-1))
     se=np.sqrt(max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2]));crit=stats.t.ppf(.975,min(counts[:2])-1);eq([se,value-crit*se,value+crit*se],[row.se,row.ci_low,row.ci_high],tol=3e-6);cis.append(dict(period=period,target=target,pair_key=row.pair_key,se_error=abs(se-row.se)))
   eq(values,z.estimate,tol=3e-6);fits.append(dict(period=period,target=target,contrasts=len(z),iterations=int(sol[2]),max_coefficient_error=float(np.max(np.abs(values-z.estimate))) if len(z) else None));print('Verified combined model',period,target,'CIs',len(cis),flush=True)
 keys=['period','model','target','pair_key','state'];ind=pd.DataFrame(support_rows).sort_values(keys).reset_index(drop=True);support=support.sort_values(keys).reset_index(drop=True)
 for c in support:eq(support[c],ind[c])
 for state in ['switched','retained']:
  z=support[support.state.eq(state)].set_index(['period','target','pair_key']);ix=pd.MultiIndex.from_frame(e[['period','target','pair_key']])
  for c in ['n','horses','races']:eq(e[state+'_'+c],z[c].reindex(ix).fillna(0))
 eq(e.target_supported,e.switched_n.ge(30)&e.retained_n.ge(30)&e.switched_horses.ge(15)&e.retained_horses.ge(15)&e.switched_races.ge(20)&e.retained_races.ge(20))
 audit=json.loads((O/'source_audit.json').read_text());assert audit['target_horizon_races']==0 and not audit['future_outcomes_created'] and not audit['prior_outcome_candidates_used']
 for x in audit['inputs']:eq([hashlib.sha256((ROOT/x['path']).read_bytes()).hexdigest()],[x['sha256']])
 result=dict(passed=True,checks=checks,source_rows=len(d),current_switch_events=len(events),target_horizon_races=0,fixed_pair_family=213,all_raw_groups=len(raw),OR_missingness_and_overlap_independently_verified=True,all_target_support_verified=True,fixed_BH_verified=True,independent_models=fits,independent_cluster_CIs=cis,input_hashes_preserved=True)
 (O/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['independent_models','independent_cluster_CIs']},ensure_ascii=False,indent=2))
if __name__=='__main__':audit()
