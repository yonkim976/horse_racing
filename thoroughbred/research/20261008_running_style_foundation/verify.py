"""Independent raw, SQL coverage, pandas rolling and scalar-statistics checks."""
from pathlib import Path
import gzip,hashlib,json,math
import duckdb,numpy as np,pandas as pd
from scipy.stats import t
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2]
checks=0
def check(ok,message):
 global checks
 assert bool(ok),message;checks+=1
def close(a,b,message):
 global checks
 np.testing.assert_allclose(a,b,atol=1e-11,rtol=1e-10,equal_nan=True,err_msg=message);checks+=1
def verify():
 d=pd.read_parquet(O/'observed_styles.parquet');p=pd.read_parquet(O/'temporal_evaluation.parquet');audit=json.loads((O/'source_audit.json').read_text())
 for name,expected in audit['input_sha256'].items():
  path=(ROOT/name).resolve();check(path.is_relative_to(ROOT),'source containment');check(hashlib.sha256(path.read_bytes()).hexdigest()==expected,'input SHA')
 for name,q in d.groupby('source_file'):
  raw=json.load(gzip.open(ROOT/name,'rt'))['response']['body']['items']['item'];prefix='sj' if q.meet.iloc[0]=='서울' else 'bu'
  for r in q.itertuples():
   a=raw[r.source_item_index];check(str(a['hrNo']).zfill(7)==r.horse_id and int(a['rcDate'])==int(r.date.strftime('%Y%m%d')) and f"{r.meet}:{a['rcDate']}:{a['rcNo']}"==r.source_key,'raw identity')
   close([a[prefix+'S1fOrd'],a[prefix+'G3fOrd'],a[prefix+'G1fOrd'],a['ord'],a['chulNo']],[r.s1f,r.g3f,r.g1f,r.raw_finish_rank,r.gate],'official ranks/gate')
 check(d.row_key.is_unique and not d.duplicated(['horse_id','date']).any(),'keys')
 check(not d.raw_finish_rank.isin([93,94,95]).any(),'scratch excluded')
 con=duckdb.connect();con.register('d',d)
 for point in ['s1f','g3f','g1f']:
  q=con.execute(f'SELECT source_key, count(*)=max(field_size) AND count(DISTINCT {point})=max(field_size) AND min({point})=1 AND max({point})=max(field_size) AS ok FROM d GROUP BY source_key').df().set_index('source_key')
  check(np.array_equal(d[point+'_complete'],d.source_key.map(q.ok)),'SQL complete '+point)
  pp=(d[point]-1)/(d.field_size-1);expected=np.full(len(d),-1,int);valid=d[point+'_complete'];expected[valid&d[point].eq(1)]=0;expected[valid&d[point].ne(1)&pp.le(1/3)]=1;expected[valid&pp.gt(1/3)&pp.le(2/3)]=2;expected[valid&pp.gt(2/3)]=3
  check(np.array_equal(d[point+'_class'],expected),'boundary '+point)
 # Actual-start gaps allow an independent shift/rolling calculation of the T-2 window.
 gap=d.groupby('horse_id').date.diff().dt.days;check(gap.dropna().ge(2).all(),'actual horse starts separated >=2 days')
 for keys,prefix in [(['horse_id'],'prior'),(['horse_id','meet','distance_m'],'same')]:
  grouped=d.groupby(keys,sort=False)
  n=grouped.cumcount().clip(upper=5)
  valid=d.s1f_class.ge(0).astype(int)
  observed=valid.groupby([d[k] for k in keys],sort=False).transform(lambda s:s.shift(1).rolling(5,min_periods=1).sum()).fillna(0)
  close(n,d[prefix+'_n'],'history actual n '+prefix);close(observed,d[prefix+'_valid_n'],'history valid n '+prefix)
  for i in range(4):
   x=d.s1f_class.eq(i).astype(int);count=x.groupby([d[k] for k in keys],sort=False).transform(lambda s:s.shift(1).rolling(5,min_periods=1).sum()).fillna(0);close(count,d[prefix+'_count_'+str(i)],'rolling count '+prefix+str(i))
  last=grouped.date.shift(1);oldest=grouped.date.transform(lambda s:s.shift(5).fillna(s.iloc[0]))
  check((last==d[prefix+'_last']).fillna(last.isna()&d[prefix+'_last'].isna()).all() or np.array_equal(last.fillna(pd.Timestamp('1900-01-01')),d[prefix+'_last'].fillna(pd.Timestamp('1900-01-01'))),'last history '+prefix)
  support=n.eq(5)&observed.eq(5)&(d.date-oldest).dt.days.le(730);check(np.array_equal(support,d['history_supported' if prefix=='prior' else 'same_supported']),'supported '+prefix)
  check((d[prefix+'_last'].isna()|(d[prefix+'_last']<=d.date-pd.Timedelta(days=2))).all(),'T-2 '+prefix)
 for year in [2024,2025]:
  train=d[d.year.lt(year)&d.s1f_complete];test=p[p.year.eq(year)];tot=train.s1f_class.value_counts().reindex(range(4),fill_value=0).to_numpy()/len(train)
  ct=train.groupby(['meet','distance_m','s1f_class']).size().unstack(fill_value=0).reindex(columns=range(4),fill_value=0);ct=ct.div(ct.sum(axis=1),axis=0)
  ft=train.groupby(['meet','distance_m','field_size','s1f_class']).size().unstack(fill_value=0).reindex(columns=range(4),fill_value=0)
  base=[]
  for r in test.itertuples():
   k=(r.meet,r.distance_m);kk=(*k,r.field_size);b=ct.loc[k].to_numpy() if k in ct.index else tot;c=ft.loc[kk].to_numpy() if kk in ft.index else np.zeros(4);base.append((c+20*b)/(sum(c)+20))
  base=np.array(base);close(base,test[['baseline_p_'+str(i) for i in range(4)]],'independent baseline')
  cnt=test[['prior_count_'+str(i) for i in range(4)]].to_numpy();hist=(cnt+3*base)/8;close(hist,test[['history_p_'+str(i) for i in range(4)]],'prior probability')
  target=np.eye(4)[test.s1f_class];close(((target-base)**2).sum(axis=1),test.baseline_brier,'base Brier');close(((target-hist)**2).sum(axis=1),test.history_brier_3,'horse Brier')
  check(train.date.max()<pd.Timestamp(f'{year}-01-01'),'baseline trained before year')
  # Mutation: only current and later observations are altered. The frozen five earlier rows
  # and the baseline learned before this year must produce the same current prediction.
  samples=test.iloc[np.linspace(0,len(test)-1,12,dtype=int)]
  for r in samples.itertuples():
   hh=d[d.horse_id.eq(r.horse_id)].copy();prior=hh[hh.date.le(r.date-pd.Timedelta(days=2))].tail(5)
   expected=np.bincount(prior.s1f_class,minlength=4);hh.loc[hh.date.ge(r.date),['s1f_class','g3f_class','rank','finish_p']]=999
   again=hh[hh.date.le(r.date-pd.Timedelta(days=2))].tail(5);close(expected,np.bincount(again.s1f_class,minlength=4),'current/future mutation')
   close(expected,[getattr(r,'prior_count_'+str(i)) for i in range(4)],'mutation input match')
 # Recompute all reported intervals with scalar group aggregation, including race weights.
 metrics=pd.read_csv(O/'evaluation_metrics.csv',dtype={'window':str})
 for r in metrics.itertuples():
  q=p if r.window=='2024_2025' else p[p.window.eq(r.window)]
  if r.meet!='전체':q=q[q.meet.eq(r.meet)]
  w=pd.Series(1.,index=q.index) if r.weighting=='start' else 1/q.source_key.map(q.source_key.value_counts());v=q.brier_difference;est=float((w*v).sum()/w.sum());score=w*(v-est)/w.sum();vv=[];ng=[]
  for ids in [q.horse_id,q.day_key,q.horse_id+':'+q.day_key]:
   sums=score.groupby(ids).sum();g=len(sums);vv.append(float(sums.pow(2).sum())*g/(g-1));ng.append(g)
  se=math.sqrt(max(0,vv[0],vv[1],vv[0]+vv[1]-vv[2]));crit=t.ppf(.975,min(ng[:2])-1);close([est,se,est-crit*se,est+crit*se],[r.estimate,r.se,r.lower,r.upper],'cluster interval')
  close(np.average(q.baseline_brier,weights=w),r.baseline_brier,'reported Brier baseline');close(np.average(q.history_brier_3,weights=w),r.history_brier,'reported Brier horse')
 pr=pd.read_csv(O/'horse_style_profiles.csv',dtype={'horse_id':str});check(len(pr)==d.horse_id.nunique(),'profile unique horse coverage')
 for r in pr.itertuples():
  hh=d[d.horse_id.eq(r.horse_id)].tail(5);cc=hh.s1f_class.value_counts().reindex(range(4),fill_value=0);close(cc,[getattr(r,'window5_count_'+str(i)) for i in range(4)],'profile last5')
 baseline=json.loads((O/'baseline_inventory.json').read_text());shared={'README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md'};unchanged=0
 for rec in baseline['related_existing_files']:
  rel=Path(rec['path']);suffix=str(rel.relative_to('thoroughbred/research')) if str(rel).startswith('thoroughbred/research/') else ''
  if suffix in shared:continue
  path=ROOT/rel;check(path.stat().st_size==rec['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==rec['sha256'],'prior artifact unchanged');unchanged+=1
 result=dict(passed=True,checks=checks,raw_rows_checked=len(d),inputs_checked=len(audit['input_sha256']),prior_files_unchanged=unchanged,history_method='Independent shifted pandas rolling on actual starts; minimum observed start gap >=2d verified',complete_race_method='Independent SQL distinct/min/max/count',evaluation_method='Independent frequency tables and scalar clustered intervals',mutation_samples=24,causal_or_optimal_style_proven=False,production_changes=False)
 (O/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':verify()
