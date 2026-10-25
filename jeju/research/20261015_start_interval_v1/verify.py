"""Independent SQL predecessor links and sparse joint fixed-effect normal equations."""
import json,sqlite3
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix,csc_matrix,bmat,diags
from scipy.sparse.linalg import splu
from scipy.stats import t
from data import HERE,ROOT,DB,SOURCE,IDS,REF,sha,save,period_data
def bh(p):
 p=np.asarray(p,float);order=np.argsort(p);q=np.minimum.accumulate((p[order]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1];r=np.empty(len(p));r[order]=np.minimum(q,1);return r
def fe_independent(g,unit):
 races=sorted(g.race_id.unique());horses=sorted(g[unit].unique());r=pd.Categorical(g.race_id,categories=races).codes;h=pd.Categorical(g[unit],categories=horses).codes;nr=len(races);parent=list(range(nr+len(horses)))
 def root(a):
  while parent[a]!=a:parent[a]=parent[parent[a]];a=parent[a]
  return a
 for ri,hi in zip(r,h):
  u,v=root(int(ri)),root(nr+int(hi))
  if u!=v:parent[v]=u
 anchors={}
 for i in range(len(horses)):anchors.setdefault(root(nr+i),i)
 held=set(anchors.values());keep=[i for i in range(len(horses)) if i not in held];mapping={i:nr+k for k,i in enumerate(keep)};rr=list(range(len(g)));cc=list(r);vv=[1.]*len(g)
 for k,i in enumerate(h):
  if i in mapping:rr.append(k);cc.append(mapping[i]);vv.append(1.)
 return coo_matrix((vv,(rr,cc)),shape=(len(g),nr+len(keep))).tocsc(),len(anchors)
def reconstruct(g,spec):
 raw=g[spec['num_columns']].copy();n=raw.fillna(spec['medians'])
 for c in raw:
  assert np.isclose(raw[c].median() if raw[c].notna().any() else 0,spec['medians'][c])
  if raw[c].isna().any():n[c+'_missing']=raw[c].isna().astype(float)
 for c in spec['means']:
  if c.startswith('jockey_'):n[c]=g.jockey_id.eq(c[len('jockey_'):]).astype(float)
  elif c.startswith('trainer_'):n[c]=g.trainer_id.eq(c[len('trainer_'):]).astype(float)
  assert np.isclose(n[c].mean(),spec['means'][c]) and np.isclose(n[c].std(ddof=0),spec['sd'][c])
 cols=[]
 for c in spec['columns']:
  cols.append(g.gap_group.eq(c[len('interval='):]).to_numpy(float) if c.startswith('interval=') else ((n[c]-spec['means'][c])/spec['sd'][c]).to_numpy())
 return np.column_stack(cols)
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False);m=json.loads((HERE/'input01/source_manifest.json').read_text())
 for r in m['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 assert sha(DB)==m['database_sha256_after']==m['database_sha256_before']
 a=pd.read_csv(HERE/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);h=pd.read_csv(HERE/'input01/ledger_rows.csv',dtype={'horse_id':str});src=pd.read_csv(SOURCE,usecols=['api_record_id','horse_id','finish_position','time','field_n','result_payload_sha256'],dtype={'horse_id':str}).set_index('api_record_id')
 assert a.api_record_id.tolist()==src.index.tolist() and len(a)==52155
 for c in ['finish_position','time','field_n']:assert np.allclose(a[c],src.loc[a.api_record_id,c])
 assert a.result_payload_sha256.tolist()==src.loc[a.api_record_id,'result_payload_sha256'].tolist()
 # SQL LAG over frozen ledger rows, independently of pandas groupby.shift.
 con=sqlite3.connect(':memory:');con.execute('CREATE TABLE starts (id INTEGER,horse TEXT,day TEXT,race INTEGER,position REAL)')
 con.executemany('INSERT INTO starts VALUES(?,?,?,?,?)',[(int(r.api_record_id),r.horse_id,r.race_date,int(r.race_number),float(r.finish_position)) for r in h.itertuples()])
 sql=con.execute('SELECT id,LAG(id) OVER (PARTITION BY horse ORDER BY day,race,id),LAG(day) OVER (PARTITION BY horse ORDER BY day,race,id) FROM starts WHERE position BETWEEN 1 AND 89 OR position IN (91,92)').fetchall();con.close();links={r[0]:(r[1],r[2]) for r in sql}
 previous={};byid={}
 for r in h[h.finish_position.between(1,89)|h.finish_position.isin([91,92])].sort_values(['horse_id','race_date','race_number','api_record_id']).itertuples():
  byid[int(r.api_record_id)]=previous.get(r.horse_id);previous[r.horse_id]=(int(r.api_record_id),r.race_date)
 for r in a.itertuples():
  pair=links[int(r.api_record_id)];py=byid[int(r.api_record_id)]
  if py is None:assert pair==(None,None) and pd.isna(r.gap_days)
  else:
   assert py==pair and int(r.previous_api_record_id)==pair[0] and r.previous_race_date==pair[1]
   days=(pd.Timestamp(r.race_date)-pd.Timestamp(pair[1])).days;assert days==r.gap_days>0
   exp='1_7' if days<=7 else '8_14' if days<=14 else '15_21' if days<=21 else '22_28' if days<=28 else '29_42' if days<=42 else '43_60' if days<=60 else '61_90' if days<=90 else '91_180' if days<=180 else '181_plus';assert exp==r.gap_bin
 assert not a.horse_id.eq('3005648').any() and a.history_cutoff.lt(a.race_date).all()
 raw=pd.read_csv(HERE/'analysis01/raw_by_period.csv',dtype={'period':str});valid=a[a.gap_days.notna()];raw_checks=0
 for r in raw.itertuples():
  g=period_data(valid)[r.period];g=g[g.gap_bin.eq(r.gap_bin)];assert len(g)==r.starts and int(g.top3.sum())==r.top3_count
  for col in ['top3_pp','finish_position','rank10_quality','relative_time','rank_gain','rank10_gain']:
   v=g[g[col].notna()];values=v[col].to_numpy();point=values.mean();assert np.isclose(point,getattr(r,col+'_mean'))
   for label,key in [('date','race_date'),('horse','horse_id')]:
    scores={}
    for cl,value in zip(v[key],values):scores[cl]=scores.get(cl,0.)+value-point
    G=len(scores)
    if G>1:
     half=t.ppf(.975,G-1)*np.sqrt(sum(x*x for x in scores.values())/len(values)**2*G/(G-1));assert np.allclose([point-half,point+half],[getattr(r,col+'_'+label+'_low'),getattr(r,col+'_'+label+'_high')])
  raw_checks+=1
 ef=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str,'distance':str});models=json.loads((HERE/'analysis01/models.json').read_text());checked=0;held=0;maxbeta=0.;maxcov=0.;support_checks=0
 for group in models:
  if group['status']!='fitted':held+=1;continue
  g=a.set_index('api_record_id').loc[group['row_ids']];X=reconstruct(g,group['spec']);Z,C=fe_independent(g,group['FE']['unit']);assert C==group['FE']['components'] and Z.shape[1]==group['FE']['rank'];K=len(group['spec']['groups']);pen=np.r_[np.zeros(K),np.ones(X.shape[1]-K)];xs=csc_matrix(X);ZZ=(Z.T@Z).tocsc();zlu=splu(ZZ);system=bmat([[ZZ,Z.T@xs],[xs.T@Z,xs.T@xs+diags(pen)]],format='csc');joint=splu(system);xr=X-Z@zlu.solve(np.asarray(Z.T@X));bread=np.linalg.inv(X.T@X-np.asarray(X.T@Z)@zlu.solve(np.asarray(Z.T@X))+np.diag(pen))
  assert np.max(np.abs(Z.T@xr))<1e-6
  ref=g[g.gap_group.eq(REF)];refunits=set(ref[group['FE']['unit']])
  for model in group['models']:
   y=g[model['target']].to_numpy();coef=joint.solve(np.r_[np.asarray(Z.T@y).ravel(),X.T@y]);beta=coef[Z.shape[1]:];err=float(np.abs(beta-model['beta']).max());assert err<1e-5;maxbeta=max(maxbeta,err);res=y-Z@coef[:Z.shape[1]]-X@beta
   covs={}
   for label,key in [('date','race_date'),('horse','horse_id')]:
    score=pd.DataFrame(xr*res[:,None]);score['key']=g[key].to_numpy();s=score.groupby('key').sum().to_numpy();G=len(s);cov=bread@s.T@s@bread*(G/(G-1)*(len(g)-1)/group['residual_df']);err=float(np.abs(cov-np.array(model[label+'_cov'])).max());assert err<1e-5;maxcov=max(maxcov,err);covs[label]=cov
   for i,label in enumerate(group['spec']['groups']):
    q=ef[(ef.period==group['period'])&(ef.distance==group['distance'])&(ef.variant==group['variant'])&(ef.target==model['target'])&(ef.gap_group==label)];assert len(q)==1;r=q.iloc[0];sign=-1 if model['target']=='relative_time' else 1;point=sign*beta[i];sd=np.sqrt(max(0,covs['date'][i,i]));sh=np.sqrt(max(0,covs['horse'][i,i]));assert np.allclose([r.effect,r.date_low,r.date_high,r.horse_low,r.horse_high],[point,point-model['crit']*sd,point+model['crit']*sd,point-model['crit']*sh,point+model['crit']*sh])
    sub=g[g.gap_group.eq(label)];cross=sub[sub[group['FE']['unit']].isin(refunits)].horse_id.nunique();supported=len(sub)>=100 and len(ref)>=100 and sub.horse_id.nunique()>=30 and ref.horse_id.nunique()>=30 and sub.race_date.nunique()>=20 and ref.race_date.nunique()>=20 and cross>=20;assert supported==r.support and cross==r.crossover_horses;support_checks+=1
   checked+=1
  print('Verified interval model',group['period'],group['distance'],group['variant'],flush=True)
 for pooled in [True,False]:
  z=ef[ef.variant.eq('primary')&ef.support&(ef.distance.eq('pooled') if pooled else ef.distance.ne('pooled'))];assert np.allclose(z.BH_q,bh(z.date_p))
 expected=ef.variant.eq('primary')&ef.support&ef.BH_q.lt(.05)&((ef.date_low.gt(0)&ef.horse_low.gt(0))|(ef.date_high.lt(0)&ef.horse_high.lt(0)));assert np.array_equal(expected,ef.direction_supported)
 rep=pd.read_csv(HERE/'analysis01/repeat_checks.csv',dtype={'distance':str});assert set(rep[rep.repeated_supported].distance)=={'pooled'} and set(rep[rep.repeated_supported].gap_group)=={'8_14'} and len(rep[rep.repeated_supported])==3
 save(out/'verification.json',{'status':'passed','cohort_source_values_payload_ids_verified':len(a),'sql_lag_and_python_predecessor_links_checked':len(a),'known_intervals':len(valid),'raw_period_cells_and_intervals_recomputed':raw_checks,'model_outcomes_reestimated_by_sparse_full_fixed_effect_joint_equations':checked,'held_model_groups':held,'support_effect_rows_recomputed':support_checks,'maximum_beta_difference':maxbeta,'maximum_covariance_difference':maxcov,'BH_families_recomputed':2,'repeated_supported_pooled_targets':3,'repeated_supported_distance_targets':0,'source_files_and_database_unchanged':True,'shared_database_written':False,'operational_change':False})
 print('Interval study verification passed',checked,'outcome models',flush=True)
if __name__=='__main__':main()
