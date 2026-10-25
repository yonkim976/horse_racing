"""Independent SQL feature windows and joint sparse fixed-effect estimation."""
import json,sqlite3
from datetime import date,timedelta
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix,csc_matrix,bmat,diags
from scipy.sparse.linalg import splu
from scipy.stats import t
from data import HERE,ROOT,DB,IDS,WINDOWS,sha,save,features

def independent_fe(g):
 races=sorted(g.race_id.unique());horses=sorted(g.horse_distance.unique());r=pd.Categorical(g.race_id,categories=races).codes;h=pd.Categorical(g.horse_distance,categories=horses).codes;nr=len(races);parent=list(range(nr+len(horses)))
 def root(k):
  while parent[k]!=k:parent[k]=parent[parent[k]];k=parent[k]
  return k
 for ri,hi in zip(r,h):
  u,v=root(int(ri)),root(nr+int(hi))
  if u!=v:parent[v]=u
 held={}
 for i in range(len(horses)):held.setdefault(root(nr+i),i)
 keep=[i for i in range(len(horses)) if i not in set(held.values())];mapping={i:nr+k for k,i in enumerate(keep)};rr=list(range(len(g)));cc=list(r);vv=[1.]*len(g)
 for k,i in enumerate(h):
  if i in mapping:rr.append(k);cc.append(mapping[i]);vv.append(1.)
 return coo_matrix((vv,(rr,cc)),shape=(len(g),nr+len(keep))).tocsc(),len(held)
def reconstruct(g,spec):
 raw=g[spec['num_columns']].copy();n=raw.fillna(spec['medians'])
 for c in raw:
  assert np.isclose(raw[c].median() if raw[c].notna().any() else 0,spec['medians'][c])
  if raw[c].isna().any():n[c+'_missing']=raw[c].isna().astype(float)
 columns=[]
 for c in spec['columns']:
  if c=='exposed':v=g.exposed.to_numpy(float)
  else:
   if c.startswith('jockey_'):n[c]=g.jockey_id.eq(c[7:]).astype(float)
   if c.startswith('trainer_'):n[c]=g.trainer_id.eq(c[8:]).astype(float)
   assert np.isclose(n[c].mean(),spec['means'][c]) and np.isclose(n[c].std(ddof=0),spec['sd'][c]);v=((n[c]-spec['means'][c])/spec['sd'][c]).to_numpy()
  columns.append(v)
 return np.column_stack(columns)
def independent_sample(a,f,m):
 w={'window7':7,'window28':28}.get(m['variant'],14);g=a.join(f[f.window_days.eq(w)].set_index('api_record_id'),on='api_record_id')
 if m['comparison']=='any_vs_nonjockey':
  take=g.role_complete|(g.any_jockey if m['variant']=='positive_expanded' else False);g=g[take].copy();g['exposed']=g.any_jockey.astype(float)
 else:
  take=(g.identity_complete&g.any_jockey)|(g.same_jockey if m['variant']=='positive_expanded' else False);g=g[take].copy();g['exposed']=g.same_jockey.astype(float)
 if m['period']=='2024_2025':g=g[g.year.between(2024,2025)]
 elif m['period']=='2026':g=g[g.year.eq(2026)]
 g['log_gap']=np.log1p(g.gap_days);g['log_training_days']=np.log1p(g.training_days);g['log_training_minutes']=np.log1p(g.training_minutes)
 return g.reset_index(drop=True)
def main():
 out=HERE/'verification02';out.mkdir(exist_ok=False);manifest=json.loads((HERE/'input01/source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 assert sha(DB)==manifest['database_sha256_before']==manifest['database_sha256_after']
 guardpath=ROOT/'jeju/research/20261017_training_rider_unclassified/guard_view_audit.json';guard=json.loads(guardpath.read_text());assert guard['database']['sha256']==sha(DB) and guard['assignment_guard']['type_review_not_applied']==0 and guard['assignment_guard']['type_source_fields_changed']==0
 refreshpath=ROOT/'jeju/research/20261017_core_refresh/verification/production_verification_completed.json';refresh=json.loads(refreshpath.read_text());failures=[r for r in refresh['checks'] if not r['ok']]
 assert refresh['failure_count']==1 and len(failures)==1 and failures[0]['name']=='database_bytes_after_matches_final_manifest'
 assert refresh['database_sha256_after']==sha(DB) and failures[0]['detail']['database_sha256_still_matches'] and failures[0]['detail']['actual_bytes']==DB.stat().st_size==manifest['database_bytes']
 save(out/'current_source_context.json',{'database_sha256':sha(DB),'current_classification_guard_report':{'path':str(guardpath.relative_to(ROOT)),'sha256':sha(guardpath)},'current_database_refresh_verification':{'path':str(refreshpath.relative_to(ROOT)),'sha256':sha(refreshpath),'overall_ok':refresh['ok'],'known_manifest_bytes_only_failure_retained':failures},'current_analysis_view_rows':guard['effective_views']['daily_training_rider_types_analysis_2026']['rows'],'fixed_race_cohort_upper':'2026-09-19','newer_training_rows_after_race_upper_excluded':True})
 a=pd.read_csv(HERE/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);tr=pd.read_csv(HERE/'input01/training_rows.csv',dtype={'horse_id':str,'prNo_raw':str},low_memory=False);f=pd.read_csv(HERE/'input01/features.csv');l=pd.read_csv(HERE/'input01/lineage.csv');fd=f.set_index(['api_record_id','window_days']);ld=l.groupby(['api_record_id','window_days'],sort=False).daily_training_api_row_id.apply(list).to_dict()
 assert len(a)==52155 and a.api_record_id.is_unique and tr.daily_training_api_row_id.is_unique and not l.duplicated().any() and not a.horse_id.eq('3005648').any()
 valid=tr.prNo_raw.fillna('').str.fullmatch(r'\d{6}');assert tr.loc[tr.rider_type.eq('기수')&valid,'jockey_name'].notna().all()
 con=sqlite3.connect(':memory:');con.execute('CREATE TABLE train(id INTEGER PRIMARY KEY,horse TEXT,day TEXT,kind TEXT,person TEXT,minutes REAL)');con.executemany('INSERT INTO train VALUES(?,?,?,?,?,?)',[(int(r.daily_training_api_row_id),r.horse_id,r.training_date,r.rider_type,r.prNo_raw if pd.notna(r.prNo_raw) else '',None if pd.isna(r.duration_seconds) else float(r.duration_seconds)/60) for r in tr.itertuples()]);con.execute('CREATE INDEX train_window ON train(horse,day,id)');checked=0
 for r in a.itertuples():
  day=date.fromisoformat(r.race_date);end=day-timedelta(days=2);assert str(end)==r.history_cutoff;previous=date.fromisoformat(r.previous_race_date) if pd.notna(r.previous_race_date) else None
  for w in WINDOWS:
   start=max(day-timedelta(days=w),previous+timedelta(days=1)) if previous else day-timedelta(days=w);items=con.execute('SELECT id,day,kind,person,minutes FROM train WHERE horse=? AND day BETWEEN ? AND ? ORDER BY day,id',(r.horse_id,str(start),str(end))).fetchall();expected_ids=[v[0] for v in items];assert expected_ids==ld.get((r.api_record_id,w),[])
   q=fd.loc[(r.api_record_id,w)];j=[v for v in items if v[2]=='기수'];unknown=[v for v in items if v[2]=='미분류'];bad=[v for v in j if not (len(v[3])==6 and v[3].isdigit())];same=[v for v in j if v[3]==r.jockey_id and len(v[3])==6 and v[3].isdigit()];complete=bool(items) and not unknown;identity=complete and not bad
   expected={'training_rows':len(items),'training_days':len({v[1] for v in items}),'unknown_type_rows':len(unknown),'known_jockey_rows':len(j),'known_jockey_days':len({v[1] for v in j}),'invalid_jockey_id_rows':len(bad),'same_jockey_rows':len(same),'same_jockey_days':len({v[1] for v in same}),'duration_known_rows':sum(v[4] is not None for v in items),'duration_missing_rows':sum(v[4] is None for v in items)}
   for k,v in expected.items():assert q[k]==v,(r.api_record_id,w,k)
   assert np.isclose(q.training_minutes,sum(v[4] or 0. for v in items)) and q.role_complete==complete and q.identity_complete==identity and q.any_jockey==bool(j) and q.same_jockey==bool(same) and q.window_start==str(start) and q.window_end==str(end)
   group='no_rows' if not items else 'same_jockey' if same else 'other_jockey_only' if j and identity else 'non_jockey_only' if complete and not j else 'uncertain';assert q.observed_group==group;checked+=1
 con.close();print('Independent SQL windows verified',checked,flush=True)
 perturbations=0;groups={h:g for h,g in tr.groupby('horse_id')}
 for r in a.sample(n=50,random_state=1710).itertuples():
  row=a[a.api_record_id.eq(r.api_record_id)];z=groups[r.horse_id].copy();original,_=features(row,z);future=z.training_date.gt(r.history_cutoff);z.loc[future,'rider_type']='기수';z.loc[future,'prNo_raw']=r.jockey_id;z.loc[future,'duration_seconds']=1000000
  extra=z.iloc[[0]].copy();extra['training_date']=str(date.fromisoformat(r.race_date)-timedelta(days=1));extra['daily_training_api_row_id']=int(tr.daily_training_api_row_id.max())+1;extra['rider_type']='기수';extra['prNo_raw']=r.jockey_id;changed,_=features(row,pd.concat([z,extra],ignore_index=True));pd.testing.assert_frame_equal(original,changed);perturbations+=1
 raw=pd.read_csv(HERE/'analysis01/raw_primary.csv',dtype={'period':str});rawchecks=0;models=json.loads((HERE/'analysis01/models.json').read_text());ef=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str});maxbeta=0.;maxcov=0.;modelchecks=0;held=0
 for m in models:
  g=independent_sample(a,f,m);q=g[g.exposed.eq(1)];r=g[g.exposed.eq(0)];both=set(q.horse_distance)&set(r.horse_distance);cross=g[g.horse_distance.isin(both)].horse_id.nunique();support=min(len(q),len(r))>=100 and min(q.horse_id.nunique(),r.horse_id.nunique())>=30 and min(q.race_date.nunique(),r.race_date.nunique())>=20 and cross>=20
  assert len(g)==m['rows'] and len(q)==m['positive_starts'] and len(r)==m['negative_starts'] and cross==m['crossover_horses']
  if m['variant']=='primary':
   for label,z in g.groupby('exposed'):
    rr=raw[(raw.period==m['period'])&(raw.comparison==m['comparison'])&raw.exposed.eq(label)].iloc[0];assert len(z)==rr.starts and np.allclose([z.finish_position.mean(),z.top3_pp.mean(),z.relative_time.mean()],[rr.finish_position_mean,rr.top3_pp_mean,rr.relative_time_mean]);rawchecks+=1
    for target in ['finish_position','top3_pp','relative_time','rank10_quality','H1_time_adv']:
     zz=z[z[target].notna()];y=zz[target];point=y.mean()
     if not len(y):continue
     for lab,key in [('date','race_date'),('horse','horse_id')]:
      sums=(y-point).groupby(zz[key]).sum();G=len(sums);half=t.ppf(.975,G-1)*np.sqrt((sums*sums).sum()/len(y)**2*G/(G-1));assert np.allclose([point-half,point+half],[rr[target+'_'+lab+'_low'],rr[target+'_'+lab+'_high']])
  if m['status']!='fitted':assert not support;held+=1;continue
  assert support and g.api_record_id.astype(int).tolist()==m['row_ids'];X=reconstruct(g,m['spec']);Z,C=independent_fe(g);assert Z.shape[1]==m['FE']['rank'] and C==m['FE']['components'];xs=csc_matrix(X);ZZ=(Z.T@Z).tocsc();zlu=splu(ZZ);pen=np.r_[0.,np.ones(X.shape[1]-1)];joint=splu(bmat([[ZZ,Z.T@xs],[xs.T@Z,xs.T@xs+diags(pen)]],format='csc'));xr=X-Z@zlu.solve(np.asarray(Z.T@X));bread=np.linalg.inv(X.T@X-np.asarray(X.T@Z)@zlu.solve(np.asarray(Z.T@X))+np.diag(pen))
  for model in m['models']:
   y=g[model['target']].to_numpy();coef=joint.solve(np.r_[np.asarray(Z.T@y).ravel(),X.T@y]);beta=coef[Z.shape[1]:];err=float(np.abs(beta-model['beta']).max());assert err<1e-5;maxbeta=max(maxbeta,err);res=y-Z@coef[:Z.shape[1]]-X@beta;covs={}
   for lab,key in [('date','race_date'),('horse','horse_id')]:
    score=pd.DataFrame(xr*res[:,None]);score['key']=g[key].to_numpy();s=score.groupby('key').sum().to_numpy();G=len(s);cov=bread@s.T@s@bread*(G/(G-1)*(len(g)-1)/m['residual_df']);err=float(np.abs(cov-np.asarray(model[lab+'_cov'])).max());assert err<1e-5;maxcov=max(maxcov,err);covs[lab]=cov
   rr=ef[(ef.period==m['period'])&(ef.variant==m['variant'])&(ef.comparison==m['comparison'])&(ef.target==model['target'])].iloc[0];sign=-1 if model['target']=='relative_time' else 1;point=sign*beta[0];sd=np.sqrt(max(0,covs['date'][0,0]));sh=np.sqrt(max(0,covs['horse'][0,0]));crit=model['crit'];assert np.allclose([point,point-crit*sd,point+crit*sd,point-crit*sh,point+crit*sh],[rr.effect,rr.date_low,rr.date_high,rr.horse_low,rr.horse_high]);modelchecks+=1
  print('Independent training FE verified',m['period'],m['variant'],m['comparison'],flush=True)
 for ish1 in [False,True]:
  v=ef[ef.variant.eq('primary')&(ef.target.eq('H1_time_adv') if ish1 else ef.target.ne('H1_time_adv'))];order=np.argsort(v.date_p.to_numpy());p=v.date_p.to_numpy()[order];adjusted=np.empty(len(p));running=1.
  for k in range(len(p)-1,-1,-1):running=min(running,p[k]*len(p)/(k+1));adjusted[k]=running
  assert np.allclose(v.BH_q.to_numpy()[order],adjusted)
 expected=ef.variant.eq('primary')&ef.BH_q.lt(.05)&((ef.date_low.gt(0)&ef.horse_low.gt(0))|(ef.date_high.lt(0)&ef.horse_high.lt(0)));assert np.array_equal(expected,ef.direction_supported);rep=pd.read_csv(HERE/'analysis01/repeat_checks.csv');assert not rep.repeated_supported.any()
 H=a[a.H1_time.notna()];assert np.allclose(H.H1_time_adv,H.H1_time-H.relative_time)
 audit=json.loads((ROOT/'jeju/research/20261009_jockey_effects_v1/forecast01/fit_audit.json').read_text())
 for r in audit:assert r['train_last']<=r['cutoff']<str(r['year'])+'-01-01'
 assert sha(DB)==manifest['database_sha256_after']
 save(out/'verification.json',{'status':'passed','training_input_rows':len(tr),'SQL_windows_independently_recomputed':checked,'training_ID_lineage_links':len(l),'future_Tminus1_perturbations_unchanged':perturbations,'raw_primary_cells_and_cluster_intervals':rawchecks,'model_outcomes_joint_FE_reestimated':modelchecks,'held_model_groups':held,'maximum_beta_difference':maxbeta,'maximum_covariance_difference':maxcov,'primary_supported_tests':int((ef.variant.eq('primary')&ef.target.ne('H1_time_adv')).sum()),'H1_supported_tests':int((ef.variant.eq('primary')&ef.target.eq('H1_time_adv')).sum()),'primary_direction_supported':int(ef.direction_supported.sum()),'recent_repeated_supported':0,'source_hashes_bytes_unchanged':True,'current_training_guard_and_database_refresh_verified':True,'database_hash_unchanged':True,'database_written':False,'operational_change':False});print('Jockey training verification passed',modelchecks,flush=True)
if __name__=='__main__':main()
