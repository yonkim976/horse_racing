"""Independent label checks, SQL rates and joint FE normal equations."""
import json,sqlite3
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.stats import t
from analysis import HERE,ROOT,load,sha,save,COLS,STYLES
def labels(a,config):
 scope='any' if config.startswith('any') else 'same';threshold=.4 if config=='any40' else .6;p='h_'+scope+'_';result=[]
 for r in a.to_dict('records'):
  if not(r[p+'s1f_n']>=5 and r[p+'s1f_n']>=.6*r[p+'n']):v='unknown'
  elif r[p+'s1f_front_mean']>=.6-1e-12:v='lead' if r[p+'s1f_first_mean']>=.6-1e-12 else 'front'
  elif r[p+'s1f_middle_mean']+r[p+'s1f_rear_mean']>=.6-1e-12 and r[p+'late_n']>=5 and r[p+'late_mean']>=threshold-1e-12:v='closing'
  else:v='other'
  result.append(v)
 return result
def adjusted(p):
 p=np.array(p,float);ix=np.argsort(p);q=np.empty(len(p));last=1.
 for i in range(len(p)-1,-1,-1):last=min(last,p[ix[i]]*len(p)/(i+1));q[ix[i]]=last
 return q
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False);manifest=json.loads((HERE/'source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 a=load();con=sqlite3.connect(':memory:');con.execute('CREATE TABLE obs(id INTEGER, horse TEXT, day TEXT, year INTEGER, distance INTEGER, top3 INTEGER, config TEXT, style TEXT)')
 labelchecks=0
 for config in ['any','same','any40']:
  values=labels(a,config);assert values==a['style_'+config].tolist();labelchecks+=len(values)
  con.executemany('INSERT INTO obs VALUES(?,?,?,?,?,?,?,?)',[(int(r.api_record_id),r.horse_id,r.race_date,int(r.year),int(r.race_distance_m),int(r.top3),config,v) for r,v in zip(a.itertuples(),values)])
 altered=a.copy();altered['top3']=~altered.top3;altered['finish_position']=99;altered['y_s1f_pack3']=99
 assert labels(altered,'any')==a.style_any.tolist()
 rates=pd.read_csv(HERE/'run02/rates.csv',dtype={'distance':str,'period':str});ef=pd.read_csv(HERE/'run02/adjusted_effects.csv',dtype={'period':str});models=json.loads((HERE/'run02/models.json').read_text());rc=mc=sc=0;maxbeta=maxcov=0.
 for r in rates.itertuples():
  lo,hi=(2024,2025) if r.period=='2024_2025' else (2026,2026) if r.period=='2026' else (0,9999)
  sql='SELECT COUNT(*),COALESCE(SUM(top3),0),COUNT(DISTINCT horse),COUNT(DISTINCT day),MIN(day),MAX(day) FROM obs WHERE config=? AND style=? AND year BETWEEN ? AND ?';params=[r.configuration,r.style,lo,hi]
  if r.distance!='all':sql+=' AND distance=?';params.append(int(r.distance))
  n,k,h,days,first,last=con.execute(sql,params).fetchone();assert (n,k,h,days)==(r.starts,r.top3,r.horses,r.days)
  if not n:assert pd.isna(r.rate_pp);rc+=1;continue
  assert np.isclose(100*k/n,r.rate_pp) and first==r.first_date and last==r.last_date
  g=a[a['style_'+r.configuration].eq(r.style)&a.year.between(lo,hi)]
  if r.distance!='all':g=g[g.race_distance_m.eq(int(r.distance))]
  for label,key in [('date','race_date'),('horse','horse_id')]:
   z=g.groupby(key).top3.agg(['sum','count']);G=len(z)
   if G<=1:continue
   scores=100*z['sum']-r.rate_pp*z['count'];half=t.ppf(.975,G-1)*np.sqrt(float(scores@scores)/n**2*G/(G-1));assert np.allclose([r.rate_pp-half,r.rate_pp+half],[getattr(r,label+'_low'),getattr(r,label+'_high')])
  rc+=1
 con.close()
 for m in models:
  config,period=m['configuration'],m['period'];g=a[a['style_'+config].isin(STYLES)].copy()
  if period=='2024_2025':g=g[g.year.between(2024,2025)]
  elif period=='2026':g=g[g.year.eq(2026)]
  g=g.reset_index(drop=True);style=g['style_'+config]
  for c in m['contrasts']:
   q=g[style.eq(c['positive'])];r=g[style.eq(c['reference'])];co=len(set(q.race_id)&set(r.race_id));ok=min(len(q),len(r))>=100 and min(q.horse_id.nunique(),r.horse_id.nunique())>=30 and min(q.race_date.nunique(),r.race_date.nunique())>=20 and co>=30;assert ok==c['support'] and len(q)==c['positive_starts'] and len(r)==c['reference_starts'] and co==c['cooccurring_races'];sc+=1
  assert m['status']=='fitted' and g.api_record_id.astype(int).tolist()==m['row_ids'];s=m['spec'];raw=g[COLS];med=raw.median().fillna(0);assert all(np.isclose(med[c],s['numeric_medians'][c]) for c in COLS);n=raw.fillna(med)
  for c in COLS:
   if raw[c].isna().any():n[c+'_missing']=raw[c].isna().astype(float)
  columns=[]
  for c in s['columns']:
   if c in ['front','closing']:v=style.eq(c).to_numpy(float)
   else:assert np.isclose(n[c].mean(),s['means'][c]) and np.isclose(n[c].std(ddof=0),s['sd'][c]);v=((n[c]-s['means'][c])/s['sd'][c]).to_numpy()
   columns.append(v)
  X=np.column_stack(columns);codes,races=pd.factorize(g.race_id,sort=True);Z=coo_matrix((np.ones(len(g)),(np.arange(len(g)),codes)),shape=(len(g),len(races))).tocsc();counts=np.asarray(Z.sum(axis=0)).ravel();ZX=np.asarray(Z.T@X);y=100*g.top3.astype(float).to_numpy();Zy=np.asarray(Z.T@y).ravel();bread=np.linalg.inv(X.T@X-ZX.T@(ZX/counts[:,None]));beta=bread@(X.T@y-ZX.T@(Zy/counts));fixed=(Zy-ZX@beta)/counts;res=y-X@beta-Z@fixed;xr=X-Z@(ZX/counts[:,None]);df=len(g)-len(races)-X.shape[1]
  assert df==m['df'] and np.linalg.matrix_rank(xr,tol=1e-9)==X.shape[1];assert np.abs(X.T@res).max()<1e-4 and np.abs(Z.T@res).max()<1e-4
  err=float(np.abs(beta-m['beta']).max());assert err<1e-5;maxbeta=max(maxbeta,err);covs={}
  for label,key in [('date','race_date'),('horse','horse_id')]:
   score=pd.DataFrame(xr*res[:,None]);score['key']=g[key].to_numpy();sm=score.groupby('key').sum().to_numpy();G=len(sm);C=bread@sm.T@sm@bread*(G/(G-1)*(len(g)-1)/df);err=float(np.abs(C-np.array(m[label+'_cov'])).max());assert err<1e-4;maxcov=max(maxcov,err);covs[label]=C
  for c in m['contrasts']:
   rr=ef[ef.configuration.eq(config)&ef.period.eq(period)&ef.comparison.eq(c['comparison'])].iloc[0]
   if not c['support']:assert rr.date_p==1 and pd.isna(rr.effect_pp);continue
   v=np.zeros(X.shape[1])
   if c['positive']!='lead':v[s['columns'].index(c['positive'])]+=1
   if c['reference']!='lead':v[s['columns'].index(c['reference'])]-=1
   point=v@beta;deg=min(g.race_date.nunique(),g.horse_id.nunique())-1;critical=t.ppf(.975,deg)
   for label,C in covs.items():
    se=np.sqrt(max(0,v@C@v));assert np.allclose([point,point-critical*se,point+critical*se],[rr.effect_pp,rr[label+'_low'],rr[label+'_high']])
    if label=='date':assert np.isclose(2*t.sf(abs(point/se),deg) if se else 1,rr.date_p)
   mc+=1
  print('Style comparison independently verified',config,period,flush=True)
 primary=ef[ef.configuration.eq('any')];assert len(primary)==9 and np.allclose(primary.BH_q,adjusted(primary.date_p));expected=ef.configuration.eq('any')&ef.support&ef.BH_q.lt(.05)&((ef.date_low.gt(0)&ef.horse_low.gt(0))|(ef.date_high.lt(0)&ef.horse_high.lt(0)));assert np.array_equal(expected,ef.direction_supported)
 repeat=[]
 for comp,g in primary[primary.period.ne('all')].groupby('comparison'):repeat.append({'comparison':comp,'recent_repeated_supported':bool(g.direction_supported.all()) and bool(g.effect_pp.gt(0).all() or g.effect_pp.lt(0).all())})
 save(out/'recent_repeat.json',repeat)
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 save(out/'verification.json',{'status':'passed','past_only_historical_lineage_verification_reused':True,'labels_recomputed':labelchecks,'current_outcome_perturbation_label_invariant':True,'SQL_raw_cells_and_cluster_intervals':rc,'support_cells':sc,'supported_effects_and_covariances_recomputed':mc,'models_recomputed':len(models),'maximum_beta_difference':maxbeta,'maximum_covariance_difference':maxcov,'primary_BH_family_including_unavailable':9,'primary_supported_directions':int(primary.direction_supported.sum()),'recent_repeated_supported':sum(r['recent_repeated_supported'] for r in repeat),'sources_hashes_bytes_unchanged':True,'database_opened':False,'operationally_applied':False})
 print('Verification passed',flush=True)
if __name__=='__main__':main()
