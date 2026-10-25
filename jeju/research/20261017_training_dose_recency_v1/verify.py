"""Independent SQL extension and Schur normal-equation verification."""
import importlib.util,json,sqlite3
from datetime import date,timedelta
import numpy as np
import pandas as pd
from scipy.sparse.linalg import splu
from scipy.stats import t
from data import HERE,ROOT,OLD,IDS,load,extend,sha,save
HELPER=ROOT/'jeju/research/20261017_jockey_training_individual_v1/verify.py';sp=importlib.util.spec_from_file_location('independent_joint_fe_helper',HELPER);HELP=importlib.util.module_from_spec(sp);sp.loader.exec_module(HELP)
def sample(a,f,m):
 w={'window7':7,'window28':28}.get(m['variant'],14);g=a.join(f[f.window_days.eq(w)].set_index('api_record_id'),on='api_record_id')
 if m['period']=='2024_2025':g=g[g.year.between(2024,2025)]
 elif m['period']=='2026':g=g[g.year.eq(2026)]
 if m['model']=='total':g=g[g.training_rows.gt(0)&g.duration_missing_rows.eq(0)]
 else:
  g=g[g.identity_complete]
  if m['model'] in ['recency','own_time','individual']:g=g[g.same_jockey]
  if m['model'] in ['own_time','individual']:g=g[g.own_duration_missing_rows.eq(0)]
 g=g.copy()
 if m['variant']=='distinct_days':g['count_group']=g.days_group
 g['analysis_unit']=g.horse_distance if m['variant']=='horse_distance' else g.horse_distance+':'+g.jockey_id;g['log_gap']=np.log1p(g.gap_days);g['log_training_days']=np.log1p(g.training_days);g['log_training_minutes']=np.log1p(g.training_minutes);g['log_own_minutes']=np.log1p(g.own_minutes);g['own_days_per3']=g.same_jockey_days/3;g['own_nearer_per3']=-g.own_lag_days/3
 return g.reset_index(drop=True)
def reconstruct(g,s):
 raw=g[s['num_columns']].copy();n=raw.fillna(s['medians'])
 for c in raw:
  assert np.isclose(raw[c].median() if raw[c].notna().any() else 0,s['medians'][c])
  if raw[c].isna().any():n[c+'_missing']=raw[c].isna().astype(float)
 columns=[]
 for c in s['columns']:
  if c in s['target_columns']:
   if c.startswith('individual='):j,feature=c[len('individual='):].split(':');v=g.jockey_id.eq(j).to_numpy(float)*g[feature].to_numpy()
   else:field,label=c.split('=',1);v=g[field].eq(label).to_numpy(float)
  else:
   if c.startswith('trainer_'):n[c]=g.trainer_id.eq(c[8:]).astype(float)
   elif c.startswith('jockey_'):n[c]=g.jockey_id.eq(c[7:]).astype(float)
   elif c.startswith('control_own_days='):n[c]=g.own_days_group.eq(c.split('=',1)[1]).astype(float)
   elif c.startswith('unsupported_individual='):j,feature=c[len('unsupported_individual='):].split(':');n[c]=g.jockey_id.eq(j).astype(float)*g[feature]
   assert np.isclose(n[c].mean(),s['means'][c]) and np.isclose(n[c].std(ddof=0),s['sd'][c]);v=((n[c]-s['means'][c])/s['sd'][c]).to_numpy()
  columns.append(v)
 return np.column_stack(columns)
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False);manifest=json.loads((HERE/'input01/source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 save(out/'helper_source.json',{'path':str(HELPER.relative_to(ROOT)),'sha256':sha(HELPER),'functions_used':['fe','adjusted']})
 a,f=load();old=pd.read_csv(OLD/'input01/features.csv');pd.testing.assert_frame_equal(f[old.columns],old);assert len(f)==156465
 tr=pd.read_csv(OLD/'input01/training_rows.csv',dtype={'horse_id':str,'prNo_raw':str},low_memory=False);con=sqlite3.connect(':memory:');con.execute('CREATE TABLE train(horse TEXT,day TEXT,kind TEXT,person TEXT,duration REAL)');con.executemany('INSERT INTO train VALUES(?,?,?,?,?)',[(r.horse_id,r.training_date,r.rider_type,r.prNo_raw if pd.notna(r.prNo_raw) else '',None if pd.isna(r.duration_seconds) else float(r.duration_seconds)) for r in tr.itertuples()]);con.execute('CREATE INDEX train_own_window ON train(horse,person,day)');fd=f.set_index(['api_record_id','window_days']);checks=0
 for r in a.itertuples():
  race=date.fromisoformat(r.race_date);end=race-timedelta(days=2);prev=date.fromisoformat(r.previous_race_date) if pd.notna(r.previous_race_date) else None
  for w in [7,14,28]:
   start=max(race-timedelta(days=w),prev+timedelta(days=1)) if prev else race-timedelta(days=w);last,days,seconds,missing=con.execute('SELECT MAX(day),COUNT(DISTINCT day),SUM(COALESCE(duration,0)),SUM(duration IS NULL) FROM train WHERE horse=? AND person=? AND kind=? AND day BETWEEN ? AND ?',(r.horse_id,r.jockey_id,'기수',str(start),str(end))).fetchone();q=fd.loc[(r.api_record_id,w)];lag=(race-date.fromisoformat(last)).days if last else np.nan
   assert q.same_jockey_days==days and np.isclose(q.own_minutes,(seconds or 0)/60) and q.own_duration_missing_rows==(missing or 0)
   assert (pd.isna(q.own_last_date) and last is None) or q.own_last_date==last;assert (pd.isna(q.own_lag_days) and last is None) or q.own_lag_days==lag
   dg='0' if days==0 else '1' if days==1 else '2_3' if days<=3 else '4plus';rg='none' if last is None else '2_3' if lag<=3 else '4_7' if lag<=7 else '8plus';tg='none' if days==0 else 'le30' if q.own_minutes<=30 else '30_60' if q.own_minutes<=60 else 'gt60';assert q.own_days_group==dg and q.own_recency_group==rg and q.own_time_group==tg
   assert q.count_group==('1_4' if q.training_rows<=4 else '5_8' if q.training_rows<=8 else '9plus') and q.time_group==('le60' if q.training_minutes<=60 else '60_120' if q.training_minutes<=120 else 'gt120');checks+=1
 con.close();print('Independent dose SQL windows verified',checks,flush=True);byhorse={h:g for h,g in tr.groupby('horse_id')}
 for r in a.sample(20,random_state=1718).itertuples():
  row=a[a.api_record_id.eq(r.api_record_id)];z=byhorse[r.horse_id].copy();before=extend(row,z);future=z.training_date.gt(r.history_cutoff);z.loc[future,'rider_type']='기수';z.loc[future,'prNo_raw']=r.jockey_id;z.loc[future,'duration_seconds']=1000000;extra=z.iloc[[0]].copy();extra['training_date']=str(date.fromisoformat(r.race_date)-timedelta(days=1));extra['rider_type']='기수';extra['prNo_raw']=r.jockey_id;after=extend(row,pd.concat([z,extra],ignore_index=True));pd.testing.assert_frame_equal(before,after)
 ef=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'jockey_id':str,'period':str});raw=pd.read_csv(HERE/'analysis01/raw_primary.csv',dtype={'period':str,'group':str});ind=pd.read_csv(HERE/'analysis01/individual_support.csv',dtype={'jockey_id':str,'period':str});models=json.loads((HERE/'analysis01/models.json').read_text());mc=0;rc=0;sc=0;maxbeta=0.;maxcov=0.;held=0
 for m in models:
  g=sample(a,f,m);assert len(g)==m['rows'];s=m['spec']
  if m['model']=='individual':
   ss=ind[ind.period.eq(m['period'])]
   for r in ss.itertuples():
    z=g[g.jockey_id.eq(r.jockey_id)];vary=z.groupby('analysis_unit')[r.feature].nunique();pairs=set(vary[vary.gt(1)].index);cross=z[z.analysis_unit.isin(pairs)].horse_id.nunique();ok=len(z)>=100 and z.horse_id.nunique()>=30 and z.race_date.nunique()>=20 and z[r.feature].nunique()>=3 and cross>=10;assert ok==r.support and cross==r.varying_pair_horses;sc+=1
   assert set(s['target_columns'])=={'individual='+r.jockey_id+':'+r.feature for r in ss[ss.support].itertuples()}
  else:
   for c in s['contrasts']:
    q=g[g[c['field']].eq(c['positive_group'])];r=g[g[c['field']].eq(c['reference_group'])];pairs=set(q.analysis_unit)&set(r.analysis_unit);cross=g[g.analysis_unit.isin(pairs)].horse_id.nunique();ok=min(len(q),len(r))>=100 and min(q.horse_id.nunique(),r.horse_id.nunique())>=30 and min(q.race_date.nunique(),r.race_date.nunique())>=20 and cross>=20 and all(k in s['target_columns'] for k in c['weights']);assert ok==c['support'] and len(q)==c['positive_starts'] and len(r)==c['reference_starts'] and cross==c['crossover_horses'];sc+=1
  if m['variant']=='primary' and m['model']!='individual':
   for rr in raw[raw.period.eq(m['period'])&raw.model.eq(m['model'])].itertuples():
    z=g[g[rr.field].eq(rr.group)];assert len(z)==rr.starts and z.horse_id.nunique()==rr.horses and z.field_n.min()==rr.field_min and z.field_n.max()==rr.field_max and np.allclose([z.finish_position.mean(),z.top3_pp.mean(),z.relative_time.mean()],[rr.finish_position_mean,rr.top3_pp_mean,rr.relative_time_mean]);rc+=1
    for target in ['finish_position','rank10_quality','relative_time','top3_pp','H1_time_adv']:
     v=z[z[target].notna()];y=v[target];point=y.mean()
     if not len(y):continue
     for label,key in [('date','race_date'),('horse','horse_id')]:
      score=(y-point).groupby(v[key]).sum();G=len(score)
      if G<2:continue
      half=t.ppf(.975,G-1)*np.sqrt((score*score).sum()/len(v)**2*G/(G-1));assert np.allclose([point-half,point+half],[getattr(rr,target+'_'+label+'_low'),getattr(rr,target+'_'+label+'_high')])
  if m['status']!='fitted':assert not s['target_columns'];held+=1;continue
  assert g.api_record_id.astype(int).tolist()==m['row_ids'];X=reconstruct(g,s);Z,C=HELP.fe(g);assert Z.shape[1]==m['FE']['rank'] and C==m['FE']['components'];K=len(s['target_columns']);pen=np.r_[np.zeros(K),np.ones(X.shape[1]-K)];lu=splu((Z.T@Z).tocsc());ZX=np.asarray(Z.T@X);bread=np.linalg.inv(X.T@X-ZX.T@lu.solve(ZX)+np.diag(pen));xr=X-Z@lu.solve(ZX);assert len(g)-Z.shape[1]-np.linalg.matrix_rank(xr,tol=1e-7)==m['residual_df']
  for model in m['models']:
   y=g[model['target']].to_numpy();Zy=np.asarray(Z.T@y).ravel();beta=bread@(X.T@y-ZX.T@lu.solve(Zy));fixed=lu.solve(Zy-ZX@beta);err=float(np.abs(beta-model['beta']).max());assert err<1e-5;maxbeta=max(maxbeta,err);res=y-Z@fixed-X@beta;assert np.abs(Z.T@res).max()<1e-5 and np.abs(X.T@res-pen*beta).max()<1e-5;covs={}
   for label,key in [('date','race_date'),('horse','horse_id')]:
    score=pd.DataFrame(xr*res[:,None]);score['key']=g[key].to_numpy();sm=score.groupby('key').sum().to_numpy();G=len(sm);cov=bread@sm.T@sm@bread*(G/(G-1)*(len(g)-1)/m['residual_df']);err=float(np.abs(cov-np.asarray(model[label+'_cov'])).max());assert err<1e-5;maxcov=max(maxcov,err);covs[label]=cov
   for c in s['contrasts']:
    if not c['support']:continue
    vec=np.zeros(X.shape[1]);sign=-1 if model['target']=='relative_time' else 1
    for col,weight in c['weights'].items():vec[s['columns'].index(col)]=sign*weight
    rr=ef[ef.period.eq(m['period'])&ef.model.eq(m['model'])&ef.variant.eq(m['variant'])&ef.target.eq(model['target'])&ef.comparison.eq(c['comparison'])&ef.jockey_id.eq(c['jockey_id'])].iloc[0];v=g if c['jockey_id']=='pooled' else g[g.jockey_id.eq(c['jockey_id'])];crit=t.ppf(.975,min(v.race_date.nunique(),v.horse_id.nunique())-1);point=vec@beta;sd=np.sqrt(max(0,vec@covs['date']@vec));sh=np.sqrt(max(0,vec@covs['horse']@vec));assert np.allclose([point,point-crit*sd,point+crit*sd,point-crit*sh,point+crit*sh],[rr.effect,rr.date_low,rr.date_high,rr.horse_low,rr.horse_high]);mc+=1
  print('Dose FE independently verified',m['period'],m['model'],m['variant'],flush=True)
 for individual,h1 in [(False,False),(False,True),(True,False)]:
  mask=ef.variant.eq('primary')&(ef.model.eq('individual') if individual else ef.model.ne('individual'))&(ef.target.eq('H1_time_adv') if h1 else ef.target.ne('H1_time_adv'));v=ef[mask];assert np.allclose(v.BH_q,HELP.adjusted(v.date_p))
 expected=ef.variant.eq('primary')&ef.BH_q.lt(.05)&((ef.date_low.gt(0)&ef.horse_low.gt(0))|(ef.date_high.lt(0)&ef.horse_high.lt(0)));assert np.array_equal(expected,ef.direction_supported);rep=pd.read_csv(HERE/'analysis01/repeat_checks.csv',dtype={'jockey_id':str})
 for r in rep.itertuples():
  v=ef[ef.variant.eq('primary')&ef.period.ne('all')&ef.model.eq(r.model)&ef.comparison.eq(r.comparison)&ef.jockey_id.eq(r.jockey_id)&ef.target.eq(r.target)];assert len(v)==r.periods and r.recent_repeated_supported==(len(v)==2 and bool(v.direction_supported.all()) and bool(v.effect.gt(0).all() or v.effect.lt(0).all()))
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 primary=ef[ef.variant.eq('primary')&ef.model.ne('individual')&ef.target.ne('H1_time_adv')];h1=ef[ef.variant.eq('primary')&ef.target.eq('H1_time_adv')];individual=ef[ef.model.eq('individual')]
 receipt={'status':'passed','SQL_windows_recomputed':checks,'future_Tminus1_perturbations_unchanged':20,'old_window_features_identical':True,'support_cells_recomputed':sc,'raw_cells_and_intervals_recomputed':rc,'effects_and_cluster_covariances_recomputed':mc,'held_model_groups':held,'maximum_beta_difference':maxbeta,'maximum_covariance_difference':maxcov,'primary_BH_tests':len(primary),'H1_BH_tests':len(h1),'individual_BH_tests':len(individual),'primary_supported_directions':int(primary.direction_supported.sum()),'H1_supported_directions':int(h1.direction_supported.sum()),'individual_supported_directions':int(individual.direction_supported.sum()),'recent_repeated_supported':int(rep.recent_repeated_supported.sum()),'source_hashes_bytes_unchanged':True,'database_opened':False,'operational_change':False};save(out/'verification.json',receipt)
 save(HERE/'decision.json',{'status':'training_own_days_recency_quantity_duration_completed_no_stable_adjusted_advantage','period_start':'2017-01-13','period_end':'2026-09-19','partial_2026':True,'source_starts':52155,'primary_role_complete':34490,'primary_own_positive':18492,'primary_total_duration_complete':52021,'primary_window_days':14,'actual_training_count_identified':False,'rows_are_observed_records':True,'primary_BH_tests':len(primary),'H1_BH_tests':len(h1),'individual_BH_tests':len(individual),'primary_supported_directions':int(primary.direction_supported.sum()),'individual_supported_directions':int(individual.direction_supported.sum()),'recent_repeated_supported':int(rep.recent_repeated_supported.sum()),'fixed_training_bonus_adopted':False,'causal_effect_identified':False,'new_predictive_gain_tested':False,'operationally_applied':False,'database_opened':False,'jockey_and_style_pauses_preserved':True});print('Training dose verification passed',mc,flush=True)
if __name__=='__main__':main()
