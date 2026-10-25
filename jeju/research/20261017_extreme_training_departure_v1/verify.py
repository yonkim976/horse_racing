"""Independent bins, support, union-find fixed effects, Schur and cluster verification."""
import json
import numpy as np
import pandas as pd
from scipy.sparse.linalg import splu
from scipy.stats import t
from data import HERE,ROOT,PREVIOUS,HELPER,load,module,sha,save
HELP=module('independent_union_find_FE',HELPER)
def day_group(v,ultra=False):
 if ultra and v<=-6:return 'extreme_decrease'
 if v<=-4:return 'big_decrease'
 if v<=-2:return 'moderate_decrease'
 if v<2:return 'usual'
 if v<4:return 'moderate_increase'
 if not ultra or v<6:return 'big_increase'
 return 'extreme_increase'
def time_group(v,ultra=False):
 if ultra and v<=.25:return 'extreme_decrease'
 if v<=.5:return 'big_decrease'
 if v<=.75:return 'moderate_decrease'
 if v<1.25:return 'usual'
 if v<1.5:return 'moderate_increase'
 if not ultra or v<2:return 'big_increase'
 return 'extreme_increase'
def sample(a,f,m):
 variant=m['variant'];w=7 if variant=='window7' else 28 if variant=='window28' else 14;p='usual10_' if variant=='median10' else 'usual5_'
 g=a.join(f[f.window_days.eq(w)].drop(columns=['horse_id','race_date']).set_index('api_record_id'),on='api_record_id')
 g=g[g.known_preparation&g[p+'supported']]
 if m['period']=='2024_2025':g=g[g.year.between(2024,2025)]
 elif m['period']=='2026':g=g[g.year.eq(2026)]
 if variant=='short_gap':g=g[g.gap_days<=90]
 if variant=='baseline_floor':g=g[(g[p+'training_days']>=4)&(g[p+'training_minutes']>=60)]
 g=g.copy()
 if variant=='opportunity_rate':g['days_departure']=(w-1)*(g.day_rate-g[p+'day_rate']);g['minutes_ratio']=g.minute_rate/g[p+'minute_rate']
 else:g['days_departure']=g.training_days-g[p+'training_days'];g['minutes_ratio']=g.training_minutes/g[p+'training_minutes']
 g['daily_minutes_ratio']=(g.training_minutes/g.training_days)/g[p+'minutes_per_observed_day']
 ultra=m['model']=='ultra';g['days_group']=[day_group(v,ultra) for v in g.days_departure];g['minutes_group']=[time_group(v,ultra) for v in g.minutes_ratio];g['daily_minutes_group']=[time_group(v) for v in g.daily_minutes_ratio]
 g['combo_group']=[x if x==y and x in ['usual','big_decrease','big_increase'] else 'other' for x,y in zip(g.days_group,g.minutes_group)]
 for c in ['training_days','training_minutes','minutes_per_observed_day','opportunity_days']:g['log_usual_'+c]=np.log1p(g[p+c])
 g['usual_history_n']=g[p+'n'];g['log_gap']=np.log1p(g.gap_days);g['log_current_days']=np.log1p(g.training_days);g['log_current_minutes']=np.log1p(g.training_minutes);g['analysis_unit']=g.horse_distance if variant=='horse_distance' else g.horse_distance+':'+g.jockey_id
 return g.reset_index(drop=True)
def reconstruct(g,s):
 raw=g[s['num_columns']].copy();n=raw.fillna(s['medians'])
 for c in raw:
  assert np.isclose(raw[c].median() if raw[c].notna().any() else 0,s['medians'][c])
  if raw[c].isna().any():n[c+'_missing']=raw[c].isna().astype(float)
 columns=[]
 for c in s['columns']:
  if c in s['target_columns']:field,label=c.split('=',1);v=g[field].eq(label).to_numpy(float)
  else:
   if c.startswith('trainer_'):n[c]=g.trainer_id.eq(c[len('trainer_'):]).astype(float)
   elif c.startswith('jockey_'):n[c]=g.jockey_id.eq(c[len('jockey_'):]).astype(float)
   elif c.startswith('control_days_group='):n[c]=g.days_group.eq(c.split('=',1)[1]).astype(float)
   assert np.isclose(n[c].mean(),s['means'][c]) and np.isclose(n[c].std(ddof=0),s['sd'][c]);v=((n[c]-s['means'][c])/s['sd'][c]).to_numpy()
  columns.append(v)
 return np.column_stack(columns)
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False);manifest=json.loads((HERE/'input01/source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 prior=json.loads((PREVIOUS/'verification01/verification.json').read_text());assert prior['status']=='passed' and prior['preparation_windows_SQL_recomputed']==170142 and prior['baseline_5_and10_windows_recomputed']==312930
 # Boundaries are checked against independently specified expected labels.
 from data import groups
 cases=[('days',False,[-6,-4,-3,-2,-1,0,1,2,3,4,6],['big_decrease','big_decrease','moderate_decrease','moderate_decrease','usual','usual','usual','moderate_increase','moderate_increase','big_increase','big_increase']),('minutes',False,[.25,.5,.6,.75,1,1.25,1.49,1.5,2],['big_decrease','big_decrease','moderate_decrease','moderate_decrease','usual','moderate_increase','moderate_increase','big_increase','big_increase']),('days',True,[-6,-5,-4,-3,-2,0,2,4,6],['extreme_decrease','big_decrease','big_decrease','moderate_decrease','moderate_decrease','usual','moderate_increase','big_increase','extreme_increase']),('minutes',True,[.25,.3,.5,.6,.75,1,1.25,1.5,2],['extreme_decrease','big_decrease','big_decrease','moderate_decrease','moderate_decrease','usual','moderate_increase','big_increase','extreme_increase'])]
 for kind,ultra,values,expected in cases:
  assert groups(pd.Series(values),kind,ultra).tolist()==expected
  assert [day_group(v,ultra) if kind=='days' else time_group(v,ultra) for v in values]==expected
 a,f=load();ef=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str});raw=pd.read_csv(HERE/'analysis01/raw_primary.csv',dtype={'period':str,'group':str});models=json.loads((HERE/'analysis01/models.json').read_text());classified=pd.read_csv(HERE/'input01/primary_groups.csv',dtype={'horse_id':str});counts=pd.read_csv(HERE/'analysis01/joint_group_counts.csv',dtype={'period':str});census=json.loads((HERE/'input01/denominator_census.json').read_text())
 mc=rc=sc=0;maxbeta=maxcov=0.;support_rows=[];group_checks=0
 for m in models:
  g=sample(a,f,m);assert len(g)==m['rows'] and g.horse_id.nunique()==m['horses'];s=m['spec'];group_checks+=len(g)*len([c for c in ['days_group','minutes_group','daily_minutes_group','combo_group'] if c in g])
  if m['model']=='joint' and m['variant']=='primary':
   cr=next(r for r in census if r['period']==m['period']);assert len(g)==cr['eligible']
   for field in ['days','minutes','daily_minutes','combo']:assert g[field+'_group'].value_counts().to_dict()==cr[field+'_groups']
   if m['period']=='all':
    assert g.api_record_id.tolist()==classified.api_record_id.tolist()
    for field in ['days_group','minutes_group','daily_minutes_group','combo_group']:assert g[field].tolist()==classified[field].tolist()
    assert all(json.loads(ids) and rid not in json.loads(ids) for ids,rid in zip(g.usual5_ids,g.api_record_id))
   for row in counts[counts.period.eq(m['period'])].itertuples():
    v=g[g.days_group.eq(row.days_group)&g.minutes_group.eq(row.minutes_group)];assert len(v)==row.starts and v.horse_id.nunique()==row.horses and np.allclose([v.top3_pp.mean(),v.gap_days.mean()],[row.top3_pp,row.mean_gap_days])
  for c in s['contrasts']:
   q=g[g[c['field']].eq(c['positive_group'])];r=g[g[c['field']].eq(c['reference_group'])];pairs=set(q.analysis_unit)&set(r.analysis_unit);cross=g[g.analysis_unit.isin(pairs)].horse_id.nunique();ok=min(len(q),len(r))>=100 and min(q.horse_id.nunique(),r.horse_id.nunique())>=30 and min(q.race_date.nunique(),r.race_date.nunique())>=20 and cross>=20 and set(c['weights'])<=set(s['target_columns'])
   assert ok==c['support'] and len(q)==c['positive_starts'] and len(r)==c['reference_starts'] and cross==c['crossover_horses']
   support_rows.append({**{key:m[key] for key in ['period','model','variant','status']},**{key:v for key,v in c.items() if key!='weights'}});sc+=1
  if m['variant']=='primary':
   for rr in raw[raw.period.eq(m['period'])&raw.model.eq(m['model'])].itertuples():
    z=g[g[rr.field].eq(rr.group)];assert len(z)==rr.starts and z.horse_id.nunique()==rr.horses and int(z.top3.sum())==rr.top3_count and np.allclose([z.finish_position.mean(),z.top3_pp.mean(),z.relative_time.mean(),z.days_departure.mean(),z.minutes_ratio.mean(),z.gap_days.mean()],[rr.finish_position_mean,rr.top3_pp_mean,rr.relative_time_mean,rr.mean_days_departure,rr.mean_minutes_ratio,rr.mean_gap_days]);rc+=1
    for target in ['finish_position','rank10_quality','relative_time','top3_pp','H1_time_adv']:
     v=z[z[target].notna()];y=v[target];point=y.mean()
     if not len(y):continue
     for label,key in [('date','race_date'),('horse','horse_id')]:
      score=(y-point).groupby(v[key]).sum();G=len(score)
      if G<2:continue
      half=t.ppf(.975,G-1)*np.sqrt((score*score).sum()/len(v)**2*G/(G-1));assert np.allclose([point-half,point+half],[getattr(rr,target+'_'+label+'_low'),getattr(rr,target+'_'+label+'_high')])
  if m['status']!='fitted':continue
  assert g.api_record_id.astype(int).tolist()==m['row_ids'];X=reconstruct(g,s);Z,C=HELP.fe(g);assert Z.shape[1]==m['FE']['rank'] and C==m['FE']['components'];K=len(s['target_columns']);pen=np.r_[np.zeros(K),np.ones(X.shape[1]-K)];lu=splu((Z.T@Z).tocsc());ZX=np.asarray(Z.T@X);bread=np.linalg.inv(X.T@X-ZX.T@lu.solve(ZX)+np.diag(pen));xr=X-Z@lu.solve(ZX);assert len(g)-Z.shape[1]-np.linalg.matrix_rank(xr,tol=1e-7)==m['residual_df']
  for model in m['models']:
   y=g[model['target']].to_numpy();Zy=np.asarray(Z.T@y).ravel();beta=bread@(X.T@y-ZX.T@lu.solve(Zy));fixed=lu.solve(Zy-ZX@beta);err=float(np.abs(beta-model['beta']).max());assert err<1e-5;maxbeta=max(maxbeta,err);res=y-Z@fixed-X@beta;assert np.abs(Z.T@res).max()<1e-5 and np.abs(X.T@res-pen*beta).max()<1e-5;covs={}
   for label,key in [('date','race_date'),('horse','horse_id')]:
    score=pd.DataFrame(xr*res[:,None]);score['key']=g[key].to_numpy();sm=score.groupby('key').sum().to_numpy();G=len(sm);cov=bread@sm.T@sm@bread*(G/(G-1)*(len(g)-1)/m['residual_df']);err=float(np.abs(cov-np.asarray(model[label+'_cov'])).max());assert err<1e-5;maxcov=max(maxcov,err);covs[label]=cov
   for c in s['contrasts']:
    if not c['support'] or (c['contrast_kind']=='gradient' and model['target']=='H1_time_adv'):continue
    vec=np.zeros(X.shape[1]);sign=-1 if model['target']=='relative_time' else 1
    for col,weight in c['weights'].items():vec[s['columns'].index(col)]=sign*weight
    rr=ef[ef.period.eq(m['period'])&ef.model.eq(m['model'])&ef.variant.eq(m['variant'])&ef.target.eq(model['target'])&ef.comparison.eq(c['comparison'])].iloc[0];crit=t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1);point=vec@beta;sd=np.sqrt(max(0,vec@covs['date']@vec));sh=np.sqrt(max(0,vec@covs['horse']@vec));pvalue=2*t.sf(abs(point/sd),min(g.race_date.nunique(),g.horse_id.nunique())-1) if sd else 1.
    assert np.allclose([point,point-crit*sd,point+crit*sd,point-crit*sh,point+crit*sh,pvalue],[rr.effect,rr.date_low,rr.date_high,rr.horse_low,rr.horse_high,rr.date_p]);mc+=1
  print('Extreme training independently verified',m['period'],m['model'],m['variant'],flush=True)
 for fam in ['primary','gradient','H1','secondary']:
  v=ef[ef.family.eq(fam)];assert np.allclose(v.BH_q,HELP.adjusted(v.date_p))
 expected=ef.family.ne('sensitivity')&ef.BH_q.lt(.05)&((ef.date_low.gt(0)&ef.horse_low.gt(0))|(ef.date_high.lt(0)&ef.horse_high.lt(0)));assert np.array_equal(expected,ef.direction_supported)
 rep=pd.read_csv(HERE/'analysis01/repeat_checks.csv',dtype={'period':str})
 for r in rep.itertuples():
  v=ef[ef.family.eq(r.family)&ef.period.ne('all')&ef.model.eq(r.model)&ef.comparison.eq(r.comparison)&ef.target.eq(r.target)];assert len(v)==r.periods and r.recent_repeated_supported==(len(v)==2 and bool(v.direction_supported.all()) and bool(v.effect.gt(0).all() or v.effect.lt(0).all()))
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 pd.DataFrame(support_rows).to_csv(out/'support.csv',index=False,encoding='utf-8-sig')
 primary=ef[ef.family.eq('primary')];pcount=int(primary.direction_supported.sum());repeated=int(rep.recent_repeated_supported.sum())
 tests=ef[ef.family.ne('sensitivity')].groupby('family').size().astype(int).to_dict();supported=ef[ef.family.ne('sensitivity')].groupby('family').direction_supported.sum().astype(int).to_dict()
 save(out/'verification.json',{'status':'passed','prior_frozen_SQL_preparation_and_baseline_verification_reused':True,'boundary_cases_recomputed':sum(len(v) for _,_,v,_ in cases),'row_group_assignments_recomputed':group_checks,'primary_classified_rows_matched':len(classified),'support_cells_recomputed':sc,'raw_cells_and_intervals_recomputed':rc,'effects_and_cluster_covariances_recomputed':mc,'maximum_beta_difference':maxbeta,'maximum_covariance_difference':maxcov,'BH_tests_by_family':tests,'supported_directions_by_family':supported,'recent_repeated_supported':repeated,'source_hashes_bytes_unchanged':True,'database_opened':False,'operationally_applied':False})
 save(HERE/'decision.json',{'status':'extreme_personal_training_completed_'+('supported_associations_observed' if pcount else 'no_stable_primary_adjusted_advantage'),'period_start':'2017-02-03','period_end':'2026-09-19','partial_2026':True,'eligible_starts':45021,'eligible_horses':2279,'large_days_change':4,'large_minutes_decrease_ratio':.5,'large_minutes_increase_ratio':1.5,'ultra_days_change':6,'ultra_minutes_decrease_ratio':.25,'ultra_minutes_increase_ratio':2,'BH_tests_by_family':tests,'supported_directions_by_family':supported,'recent_repeated_supported':repeated,'fixed_training_adjustment_adopted':False,'causal_effect_identified':False,'individual_optimum_identified':False,'new_predictive_gain_tested':False,'operationally_applied':False,'database_opened':False,'jockey_and_style_pauses_preserved':True})
 print('Extreme training verification passed',mc,flush=True)
if __name__=='__main__':main()
