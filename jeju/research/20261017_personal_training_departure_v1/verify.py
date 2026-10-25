"""Independent actual-start SQL, rolling medians and Schur FE validation."""
import importlib.util,json,sqlite3,statistics
from datetime import date,timedelta
import numpy as np
import pandas as pd
from scipy.sparse.linalg import splu
from scipy.stats import t
from data import HERE,ROOT,OLD,LEDGER,LOWER,END,CURRENT,IDS,METRICS,load,baseline_features,sha,save
HELPER=ROOT/'jeju/research/20261017_jockey_training_individual_v1/verify.py';sp=importlib.util.spec_from_file_location('independent_FE',HELPER);HELP=importlib.util.module_from_spec(sp);sp.loader.exec_module(HELP)
def sample(a,f,m):
 w={'window7':7,'window28':28}.get(m['variant'],14);size=10 if m['variant']=='median10' else 5;p='usual'+str(size)+'_';g=a.join(f[f.window_days.eq(w)].drop(columns=['horse_id','race_date']).set_index('api_record_id'),on='api_record_id');g=g[g.known_preparation&g[p+'supported']]
 if m['period']=='2024_2025':g=g[g.year.between(2024,2025)]
 elif m['period']=='2026':g=g[g.year.eq(2026)]
 if m['variant']=='short_gap':g=g[g.gap_days.le(90)]
 g=g.copy();g['days_departure']=(g.day_rate-g[p+'day_rate'])*(g.window_days-1) if m['variant']=='opportunity_rate' else g.training_days-g[p+'training_days'];g['minutes_ratio']=g.minute_rate/g[p+'minute_rate'] if m['variant']=='opportunity_rate' else g.training_minutes/g[p+'training_minutes'];g['daily_minutes_ratio']=g.minutes_per_observed_day/g[p+'minutes_per_observed_day']
 for field,values,low,high in [('days_group',g.days_departure,-2,2),('minutes_group',g.minutes_ratio,.75,1.25),('daily_minutes_group',g.daily_minutes_ratio,.75,1.25)]:g[field]=np.where(values<=low,'decreased',np.where(values>=high,'increased','usual'))
 for c in ['training_days','training_minutes','minutes_per_observed_day','opportunity_days']:g['log_usual_'+c]=np.log1p(g[p+c])
 g['usual_history_n']=g[p+'n'];g['log_gap']=np.log1p(g.gap_days);g['log_current_days']=np.log1p(g.training_days);g['log_current_minutes']=np.log1p(g.training_minutes);g['analysis_unit']=g.horse_distance if m['variant']=='horse_distance' else g.horse_distance+':'+g.jockey_id
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
   if c.startswith('trainer_'):n[c]=g.trainer_id.eq(c[8:]).astype(float)
   elif c.startswith('jockey_'):n[c]=g.jockey_id.eq(c[7:]).astype(float)
   elif c.startswith('control_days_group='):n[c]=g.days_group.eq(c.split('=',1)[1]).astype(float)
   assert np.isclose(n[c].mean(),s['means'][c]) and np.isclose(n[c].std(ddof=0),s['sd'][c]);v=((n[c]-s['means'][c])/s['sd'][c]).to_numpy()
  columns.append(v)
 return np.column_stack(columns)
def medians(items):
 values={'training_days':[r[2] for r in items],'training_minutes':[r[3] for r in items],'minutes_per_observed_day':[r[3]/r[2] for r in items],'opportunity_days':[r[4] for r in items],'day_rate':[r[2]/r[4] for r in items],'minute_rate':[r[3]/r[4] for r in items]}
 return {k:float(statistics.median(v)) for k,v in values.items()}
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False);manifest=json.loads((HERE/'input01/source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 a,f=load();h=pd.read_csv(HERE/'input01/preparation_history.csv',dtype={'horse_id':str});ledger=pd.read_csv(LEDGER,dtype={'horse_id':str});ledger=ledger[ledger.observed_started];tr=pd.read_csv(OLD/'input01/training_rows.csv',dtype={'horse_id':str},low_memory=False);con=sqlite3.connect(':memory:');con.execute('CREATE TABLE starts(id INTEGER,horse TEXT,day TEXT,race INTEGER,distance REAL)');con.executemany('INSERT INTO starts VALUES(?,?,?,?,?)',[(int(r.api_record_id),r.horse_id,r.race_date,int(r.race_number),float(r.race_distance_m)) for r in ledger.itertuples()]);con.execute('CREATE TABLE train(horse TEXT,day TEXT,duration REAL)');con.executemany('INSERT INTO train VALUES(?,?,?)',[(r.horse_id,r.training_date,None if pd.isna(r.duration_seconds) else float(r.duration_seconds)) for r in tr.itertuples()]);con.execute('CREATE INDEX train_window ON train(horse,day)');seq=con.execute('SELECT id,horse,day,distance,LAG(day) OVER(PARTITION BY horse ORDER BY day,race,id) FROM starts').fetchall();hd=h.set_index(['api_record_id','window_days']);expected=set();historychecks=0
 for rid,horse,day,distance,previous in seq:
  if day<'2016-12-18' or day>END or distance not in CURRENT:continue
  for w in [7,14,28]:
   start=max(date.fromisoformat(day)-timedelta(days=w),date.fromisoformat(previous)+timedelta(days=1)) if previous else date.fromisoformat(day)-timedelta(days=w);end=date.fromisoformat(day)-timedelta(days=2);opp=max(0,(end-start).days+1);coverage=str(start)>=LOWER and opp>0;nr,days,secs,missing=con.execute('SELECT COUNT(*),COUNT(DISTINCT day),SUM(COALESCE(duration,0)),SUM(duration IS NULL) FROM train WHERE horse=? AND day BETWEEN ? AND ?',(horse,str(start),str(end))).fetchone();r=hd.loc[(rid,w)];expected.add((rid,w));known=coverage and days>0 and not (missing or 0);assert r.horse_id==horse and r.race_date==day and r.window_start==str(start) and r.window_end==str(end) and r.opportunity_days==opp and r.source_coverage_complete==coverage and r.known_preparation==known
   assert (pd.isna(r.previous_date) and previous is None) or r.previous_date==previous
   if coverage:assert r.training_rows==nr and r.training_days==days and np.isclose(r.training_minutes,(secs or 0)/60) and r.duration_missing_rows==(missing or 0)
   else:assert pd.isna(r.training_days) and pd.isna(r.training_minutes)
   if known:assert r.training_minutes>0 and np.allclose([r.minutes_per_observed_day,r.day_rate,r.minute_rate],[r.training_minutes/days,days/opp,r.training_minutes/opp])
   historychecks+=1
 assert expected==set(hd.index);assert len(f)==156465 and not f.duplicated(['api_record_id','window_days']).any();old=pd.read_csv(OLD/'input01/features.csv').set_index(['api_record_id','window_days']);fd=f.set_index(['api_record_id','window_days']);assert np.allclose(fd.loc[old.index,['training_days','training_minutes','training_rows']].to_numpy(),old[['training_days','training_minutes','training_rows']].to_numpy())
 con.execute('CREATE TABLE prep(id INTEGER,horse TEXT,day TEXT,w INTEGER,days REAL,minutes REAL,opp INTEGER)');valid=h[h.known_preparation];con.executemany('INSERT INTO prep VALUES(?,?,?,?,?,?,?)',[(int(r.api_record_id),r.horse_id,r.race_date,int(r.window_days),float(r.training_days),float(r.training_minutes),int(r.opportunity_days)) for r in valid.itertuples()]);con.execute('CREATE INDEX prep_history ON prep(horse,w,day,id)');baselinechecks=0
 for r in f.itertuples():
  cutoff=date.fromisoformat(r.window_end);items=con.execute('SELECT id,day,days,minutes,opp FROM prep WHERE horse=? AND w=? AND day BETWEEN ? AND ? ORDER BY day DESC,id DESC LIMIT 10',(r.horse_id,int(r.window_days),str(cutoff-timedelta(days=730)),str(cutoff))).fetchall()[::-1]
  for size,minimum in [(5,3),(10,5)]:
   use=items[-size:];prefix='usual'+str(size)+'_';assert getattr(r,prefix+'n')==len(use) and json.loads(getattr(r,prefix+'ids'))==[v[0] for v in use] and getattr(r,prefix+'supported')==(len(use)>=minimum)
   assert all(v[0]!=r.api_record_id and v[1]<=str(cutoff) for v in use)
   if len(use)>=minimum:
    for c,v in medians(use).items():assert np.isclose(getattr(r,prefix+c),v),(r.api_record_id,r.window_days,size,c)
   else:
    for c in METRICS:assert pd.isna(getattr(r,prefix+c))
   baselinechecks+=1
 profiles=pd.read_csv(HERE/'input01/horse_profiles.csv',dtype={'horse_id':str});assert len(profiles)==3*a.horse_id.nunique()
 for r in profiles.itertuples():
  use=con.execute('SELECT id,day,days,minutes,opp FROM prep WHERE horse=? AND w=? AND day BETWEEN ? AND ? ORDER BY day DESC,id DESC LIMIT 5',(r.horse_id,int(r.window_days),str(date.fromisoformat(END)-timedelta(days=730)),END)).fetchall()[::-1];assert r.n==len(use) and r.supported==(len(use)>=3) and json.loads(r.history_ids)==[v[0] for v in use]
  if len(use)>=3:
   for c,v in medians(use).items():assert np.isclose(getattr(r,c),v)
 con.close();print('Actual starts, preparations and personal medians verified',historychecks,baselinechecks,flush=True)
 for r in a.sample(30,random_state=1719).itertuples():
  row=a[a.api_record_id.eq(r.api_record_id)];z=h[h.horse_id.eq(r.horse_id)].copy();before,_=baseline_features(row,z);future=z.race_date.gt(r.history_cutoff);z.loc[future,'training_days']=1.;z.loc[future,'training_minutes']=999.;z.loc[future,'minutes_per_observed_day']=999.;z.loc[future,'day_rate']=.01;z.loc[future,'minute_rate']=999.;changed=row.copy();changed['finish_position']=88;after,_=baseline_features(changed,z);cols=[c for c in before if c.startswith('usual')];pd.testing.assert_frame_equal(before[cols],after[cols])
 ef=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str});raw=pd.read_csv(HERE/'analysis01/raw_primary.csv',dtype={'period':str,'group':str});models=json.loads((HERE/'analysis01/models.json').read_text());mc=0;rc=0;sc=0;maxbeta=0.;maxcov=0.
 for m in models:
  g=sample(a,f,m);assert len(g)==m['rows'];s=m['spec']
  for c in s['contrasts']:
   q=g[g[c['field']].eq(c['positive_group'])];r=g[g[c['field']].eq('usual')];pairs=set(q.analysis_unit)&set(r.analysis_unit);cross=g[g.analysis_unit.isin(pairs)].horse_id.nunique();ok=min(len(q),len(r))>=100 and min(q.horse_id.nunique(),r.horse_id.nunique())>=30 and min(q.race_date.nunique(),r.race_date.nunique())>=20 and cross>=20;assert ok==c['support'] and len(q)==c['positive_starts'] and len(r)==c['reference_starts'] and cross==c['crossover_horses'];sc+=1
  if m['variant']=='primary':
   for rr in raw[raw.period.eq(m['period'])&raw.model.eq(m['model'])].itertuples():
    z=g[g[rr.field].eq(rr.group)];assert len(z)==rr.starts and z.horse_id.nunique()==rr.horses and z.field_n.min()==rr.field_min and z.field_n.max()==rr.field_max and np.allclose([z.finish_position.mean(),z.top3_pp.mean(),z.relative_time.mean()],[rr.finish_position_mean,rr.top3_pp_mean,rr.relative_time_mean]);rc+=1
    for target in ['finish_position','rank10_quality','relative_time','top3_pp','H1_time_adv']:
     v=z[z[target].notna()];y=v[target];point=y.mean()
     if not len(y):continue
     for label,key in [('date','race_date'),('horse','horse_id')]:
      score=(y-point).groupby(v[key]).sum();G=len(score)
      if G<2:continue
      half=t.ppf(.975,G-1)*np.sqrt((score*score).sum()/len(v)**2*G/(G-1));assert np.allclose([point-half,point+half],[getattr(rr,target+'_'+label+'_low'),getattr(rr,target+'_'+label+'_high')])
  assert m['status']=='fitted' and g.api_record_id.astype(int).tolist()==m['row_ids'];X=reconstruct(g,s);Z,C=HELP.fe(g);assert Z.shape[1]==m['FE']['rank'] and C==m['FE']['components'];K=len(s['target_columns']);pen=np.r_[np.zeros(K),np.ones(X.shape[1]-K)];lu=splu((Z.T@Z).tocsc());ZX=np.asarray(Z.T@X);bread=np.linalg.inv(X.T@X-ZX.T@lu.solve(ZX)+np.diag(pen));xr=X-Z@lu.solve(ZX);assert len(g)-Z.shape[1]-np.linalg.matrix_rank(xr,tol=1e-7)==m['residual_df']
  for model in m['models']:
   y=g[model['target']].to_numpy();Zy=np.asarray(Z.T@y).ravel();beta=bread@(X.T@y-ZX.T@lu.solve(Zy));fixed=lu.solve(Zy-ZX@beta);err=float(np.abs(beta-model['beta']).max());assert err<1e-5;maxbeta=max(maxbeta,err);res=y-Z@fixed-X@beta;assert np.abs(Z.T@res).max()<1e-5 and np.abs(X.T@res-pen*beta).max()<1e-5;covs={}
   for label,key in [('date','race_date'),('horse','horse_id')]:
    score=pd.DataFrame(xr*res[:,None]);score['key']=g[key].to_numpy();sm=score.groupby('key').sum().to_numpy();G=len(sm);cov=bread@sm.T@sm@bread*(G/(G-1)*(len(g)-1)/m['residual_df']);err=float(np.abs(cov-np.asarray(model[label+'_cov'])).max());assert err<1e-5;maxcov=max(maxcov,err);covs[label]=cov
   for c in s['contrasts']:
    if not c['support']:continue
    vec=np.zeros(X.shape[1]);sign=-1 if model['target']=='relative_time' else 1
    for col,weight in c['weights'].items():vec[s['columns'].index(col)]=sign*weight
    rr=ef[ef.period.eq(m['period'])&ef.model.eq(m['model'])&ef.variant.eq(m['variant'])&ef.target.eq(model['target'])&ef.comparison.eq(c['comparison'])].iloc[0];crit=t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1);point=vec@beta;sd=np.sqrt(max(0,vec@covs['date']@vec));sh=np.sqrt(max(0,vec@covs['horse']@vec));assert np.allclose([point,point-crit*sd,point+crit*sd,point-crit*sh,point+crit*sh],[rr.effect,rr.date_low,rr.date_high,rr.horse_low,rr.horse_high]);mc+=1
  print('Personal training FE verified',m['period'],m['model'],m['variant'],flush=True)
 for h1 in [False,True]:
  v=ef[ef.variant.eq('primary')&(ef.target.eq('H1_time_adv') if h1 else ef.target.ne('H1_time_adv'))];assert np.allclose(v.BH_q,HELP.adjusted(v.date_p))
 expected=ef.variant.eq('primary')&ef.BH_q.lt(.05)&((ef.date_low.gt(0)&ef.horse_low.gt(0))|(ef.date_high.lt(0)&ef.horse_high.lt(0)));assert np.array_equal(expected,ef.direction_supported);rep=pd.read_csv(HERE/'analysis01/repeat_checks.csv')
 for r in rep.itertuples():
  v=ef[ef.variant.eq('primary')&ef.period.ne('all')&ef.model.eq(r.model)&ef.comparison.eq(r.comparison)&ef.target.eq(r.target)];assert len(v)==r.periods and r.recent_repeated_supported==(len(v)==2 and bool(v.direction_supported.all()) and bool(v.effect.gt(0).all() or v.effect.lt(0).all()))
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 primary=ef[ef.variant.eq('primary')&ef.target.ne('H1_time_adv')];h1=ef[ef.variant.eq('primary')&ef.target.eq('H1_time_adv')];receipt={'status':'passed','actual_start_SQL_LAG_rows':len(seq),'preparation_windows_SQL_recomputed':historychecks,'baseline_5_and10_windows_recomputed':baselinechecks,'latest_profiles_recomputed':len(profiles),'current_future_outcome_perturbations_unchanged':30,'current_windows_match_prior_verified_features':True,'support_cells_recomputed':sc,'raw_cells_and_intervals_recomputed':rc,'effects_and_cluster_covariances_recomputed':mc,'maximum_beta_difference':maxbeta,'maximum_covariance_difference':maxcov,'primary_BH_tests':len(primary),'H1_BH_tests':len(h1),'primary_supported_directions':int(primary.direction_supported.sum()),'H1_supported_directions':int(h1.direction_supported.sum()),'recent_repeated_supported':int(rep.recent_repeated_supported.sum()),'source_hashes_bytes_unchanged':True,'database_opened':False,'operational_change':False};save(out/'verification.json',receipt)
 save(HERE/'decision.json',{'status':'personal_training_departures_completed_no_stable_adjusted_advantage','period_start':'2017-02-03','source_period_start':'2017-01-13','period_end':END,'partial_2026':True,'baseline':'T-2 previous5 complete observed preparations within730days, minimum3','baseline_includes_outcome_unselected_actual_starts':True,'primary_eligible_starts':45021,'primary_eligible_horses':2279,'recent_2024_2025_starts':11280,'recent_2026_starts':4116,'current_unobserved':134,'current_known_insufficient_history':7000,'latest_horse_profiles':len(profiles)//3,'primary_BH_tests':len(primary),'H1_BH_tests':len(h1),'primary_supported_directions':int(primary.direction_supported.sum()),'recent_repeated_supported':int(rep.recent_repeated_supported.sum()),'fixed_personal_training_bonus_adopted':False,'individual_optimal_training_identified':False,'causal_effect_identified':False,'new_predictive_gain_tested':False,'operationally_applied':False,'database_opened':False,'jockey_and_style_pauses_preserved':True});print('Personal training verification passed',mc,flush=True)
if __name__=='__main__':main()
