"""Independent conditional-model and completed-interval window verification."""
import json,statistics
from datetime import date,timedelta
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix,csc_matrix,bmat,diags
from scipy.sparse.linalg import splu
from scipy.stats import t
from data import HERE,ROOT,OLD,IDS,REF,BASE,NUM,sha,save,baseline
from analysis import bh,variant_data
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
  elif c.startswith('absolute='):n[c]=g.absolute_gap_group.eq(c[len('absolute='):]).astype(float)
  assert np.isclose(n[c].mean(),spec['means'][c]) and np.isclose(n[c].std(ddof=0),spec['sd'][c])
 cols=[]
 for c in spec['columns']:
  cols.append(g.gap_group.eq(c[len('interval='):]).to_numpy(float) if c.startswith('interval=') else ((n[c]-spec['means'][c])/spec['sd'][c]).to_numpy())
 return np.column_stack(cols)
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False);manifest=json.loads((HERE/'input01/source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 a=pd.read_csv(HERE/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);h=pd.read_csv(OLD/'input01/ledger_rows.csv',dtype={'horse_id':str});h=h[h.observed_started].sort_values(['horse_id','race_date','race_number','api_record_id']);hist={};previous={}
 for r in h.itertuples():
  d=date.fromisoformat(r.race_date);p=previous.get(r.horse_id)
  if p is not None:hist.setdefault(r.horse_id,[]).append((int(r.api_record_id),d,(d-p).days))
  previous[r.horse_id]=d
 lineage=pd.read_csv(HERE/'input01/history_lineage.csv',dtype={'horse_id':str});ids=lineage.groupby('api_record_id').history_end_api_record_id.apply(list).to_dict();window_checks=0;mutation_checks=0
 for j,r in enumerate(a.itertuples()):
  cutoff=date.fromisoformat(r.race_date)-timedelta(days=2);past=[v for v in hist.get(r.horse_id,[]) if cutoff-timedelta(days=730)<=v[1]<=cutoff]
  assert r.typical_cutoff==cutoff.isoformat()
  for n in [5,10]:
   chosen=past[-n:];expected_ids=[v[0] for v in chosen];assert expected_ids==json.loads(getattr(r,'typical'+str(n)+'_ids')) and len(chosen)==getattr(r,'typical'+str(n)+'_n')
   med=getattr(r,'typical'+str(n))
   if len(chosen)<3:assert pd.isna(med)
   else:
    value=statistics.median([v[2] for v in chosen]);assert value==med
    assert np.isclose(statistics.median([abs(v[2]-value) for v in chosen])/value,getattr(r,'typical'+str(n)+'_mad_ratio'))
    ratio=r.gap_days/value;label='short' if ratio<.75 else 'usual' if ratio<=1.25 else 'long' if ratio<=2 else 'very_long';assert getattr(r,'gap_group' if n==5 else 'gap_group10')==label
   if n==10:assert ids.get(int(r.api_record_id),[])==expected_ids
   window_checks+=1
  if j%250==0:
   raw=hist.get(r.horse_id,[]);history={'days':[pd.Timestamp(v[1]) for v in raw],'gaps':[v[2] for v in raw],'ids':[v[0] for v in raw]};before=baseline(history,pd.Timestamp(cutoff),5)[0]
   altered={'days':[d for d in history['days'] if d<=pd.Timestamp(cutoff)]+[pd.Timestamp(cutoff)+pd.Timedelta(days=1),pd.Timestamp(cutoff)+pd.Timedelta(days=10000)],'gaps':[v for d,v in zip(history['days'],history['gaps']) if d<=pd.Timestamp(cutoff)]+[99999,88888],'ids':[v for d,v in zip(history['days'],history['ids']) if d<=pd.Timestamp(cutoff)]+[-1,-2]}
   assert before==baseline(altered,pd.Timestamp(cutoff),5)[0];mutation_checks+=1
 assert a.gap_group.notna().sum()==44720 and a.typical_cutoff.lt(a.race_date).all()
 raw=pd.read_csv(HERE/'analysis01/raw_by_period.csv',dtype={'period':str});v=a[a.gap_group.notna()];rawchecks=0
 for r in raw.itertuples():
  g=v if r.period=='all' else v[v.year<=2023] if r.period=='past' else v[v.year.between(2024,2025)] if r.period=='2024_2025' else v[v.year==2026];g=g[g.gap_group.eq(r.gap_bin)]
  assert len(g)==r.starts and int(g.top3.sum())==r.top3_count
  for col in ['top3_pp','finish_position','relative_time','rank_gain']:
   z=g[g[col].notna()];values=z[col].to_numpy();point=values.mean();assert np.isclose(point,getattr(r,col+'_mean'))
   for label,key in [('date','race_date'),('horse','horse_id')]:
    scores={}
    for k,value in zip(z[key],values):scores[k]=scores.get(k,0)+value-point
    G=len(scores);half=t.ppf(.975,G-1)*np.sqrt(sum(x*x for x in scores.values())/len(values)**2*G/(G-1));assert np.allclose([point-half,point+half],[getattr(r,col+'_'+label+'_low'),getattr(r,col+'_'+label+'_high')])
  rawchecks+=1
 ef=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str,'distance':str});models=json.loads((HERE/'analysis01/models.json').read_text());checked=0;held=0;maxbeta=0.;maxcov=0.;supportchecks=0
 for group in models:
  if group['status']!='fitted':held+=1;continue
  g=a.set_index('api_record_id').loc[group['row_ids']];g=variant_data(g,group['variant']);X=reconstruct(g,group['spec']);Z,C=fe_independent(g,group['FE']['unit']);assert C==group['FE']['components'] and Z.shape[1]==group['FE']['rank'];K=len(group['spec']['groups']);pen=np.r_[np.zeros(K),np.ones(X.shape[1]-K)];xs=csc_matrix(X);ZZ=(Z.T@Z).tocsc();zlu=splu(ZZ);system=bmat([[ZZ,Z.T@xs],[xs.T@Z,xs.T@xs+diags(pen)]],format='csc');joint=splu(system);xr=X-Z@zlu.solve(np.asarray(Z.T@X));bread=np.linalg.inv(X.T@X-np.asarray(X.T@Z)@zlu.solve(np.asarray(Z.T@X))+np.diag(pen));ref=g[g.gap_group.eq(REF)];refunits=set(ref[group['FE']['unit']])
  for model in group['models']:
   y=g[model['target']].to_numpy();coef=joint.solve(np.r_[np.asarray(Z.T@y).ravel(),X.T@y]);beta=coef[Z.shape[1]:];err=float(np.abs(beta-model['beta']).max());assert err<1e-5;maxbeta=max(maxbeta,err);res=y-Z@coef[:Z.shape[1]]-X@beta;covs={}
   for label,key in [('date','race_date'),('horse','horse_id')]:
    score=pd.DataFrame(xr*res[:,None]);score['key']=g[key].to_numpy();s=score.groupby('key').sum().to_numpy();G=len(s);cov=bread@s.T@s@bread*(G/(G-1)*(len(g)-1)/group['residual_df']);err=float(np.abs(cov-np.array(model[label+'_cov'])).max());assert err<1e-5;maxcov=max(maxcov,err);covs[label]=cov
   for i,label in enumerate(group['spec']['groups']):
    q=ef[(ef.period==group['period'])&(ef.distance==group['distance'])&(ef.variant==group['variant'])&(ef.target==model['target'])&(ef.gap_group==label)];assert len(q)==1;r=q.iloc[0];point=(-1 if model['target']=='relative_time' else 1)*beta[i];sd=np.sqrt(max(0,covs['date'][i,i]));sh=np.sqrt(max(0,covs['horse'][i,i]));assert np.allclose([r.effect,r.date_low,r.date_high,r.horse_low,r.horse_high],[point,point-model['crit']*sd,point+model['crit']*sd,point-model['crit']*sh,point+model['crit']*sh])
    sub=g[g.gap_group.eq(label)];cross=sub[sub[group['FE']['unit']].isin(refunits)].horse_id.nunique();supported=len(sub)>=100 and len(ref)>=100 and sub.horse_id.nunique()>=30 and ref.horse_id.nunique()>=30 and sub.race_date.nunique()>=20 and ref.race_date.nunique()>=20 and cross>=20;assert supported==r.support;supportchecks+=1
   checked+=1
  print('Personal-cycle model independently verified',group['period'],group['distance'],group['variant'],flush=True)
 for pooled in [True,False]:
  q=ef[ef.variant.eq('primary')&ef.support&(ef.distance.eq('pooled') if pooled else ef.distance.ne('pooled'))];assert np.allclose(q.BH_q,bh(q.date_p))
 rep=pd.read_csv(HERE/'analysis01/repeat_checks.csv');assert not rep.repeated_supported.any()
 save(out/'verification.json',{'status':'passed','personal_baseline_windows_independently_rebuilt':window_checks,'history_lineage_rows_reconciled':len(lineage),'future_current_interval_mutation_checks':mutation_checks,'eligible_personal_starts':len(v),'raw_period_cells_and_intervals_recomputed':rawchecks,'model_outcomes_reestimated_joint_FE':checked,'held_model_groups':held,'support_rows_recomputed':supportchecks,'maximum_beta_difference':maxbeta,'maximum_covariance_difference':maxcov,'BH_families_recomputed':2,'recent_repeated_supported':0,'sources_hashes_bytes_unchanged':True,'database_opened':False,'operational_change':False});print('Personal-cycle verification passed',checked,flush=True)
if __name__=='__main__':main()
