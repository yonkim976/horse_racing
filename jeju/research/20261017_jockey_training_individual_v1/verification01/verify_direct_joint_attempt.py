"""Independent reconstruction of individual support, joint FE and multiplicity."""
import json
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix,csc_matrix,bmat,diags
from scipy.sparse.linalg import splu
from scipy.stats import t,f as fdist
from data import HERE,ROOT,OLD,IDS,load,sha,save
def fe(g):
 races=sorted(g.race_id.unique());units=sorted(g.analysis_unit.unique());r=pd.Categorical(g.race_id,categories=races).codes;h=pd.Categorical(g.analysis_unit,categories=units).codes;nr=len(races);parent=list(range(nr+len(units)))
 def root(k):
  while parent[k]!=k:parent[k]=parent[parent[k]];k=parent[k]
  return k
 for ri,hi in zip(r,h):
  u,v=root(int(ri)),root(nr+int(hi))
  if u!=v:parent[v]=u
 anchors={}
 for i in range(len(units)):anchors.setdefault(root(nr+i),i)
 held=set(anchors.values());mapping={i:nr+k for k,i in enumerate(i for i in range(len(units)) if i not in held)};rr=list(range(len(g)));cc=list(r);vv=[1.]*len(g)
 for k,i in enumerate(h):
  if i in mapping:rr.append(k);cc.append(mapping[i]);vv.append(1.)
 return coo_matrix((vv,(rr,cc)),shape=(len(g),nr+len(mapping))).tocsc(),len(held)
def sample(a,f,m):
 w={'window7':7,'window28':28}.get(m['variant'],14);g=a.join(f[f.window_days.eq(w)].set_index('api_record_id'),on='api_record_id');g=g[g.identity_complete]
 if m['period']=='2024_2025':g=g[g.year.between(2024,2025)]
 elif m['period']=='2026':g=g[g.year.eq(2026)]
 if m['variant']=='other_jockey_only':g=g[g.any_jockey]
 g=g.copy();g['analysis_unit']=g.horse_distance if m['variant']=='horse_distance' else g.horse_distance+':'+g.jockey_id;g['log_gap']=np.log1p(g.gap_days);g['log_training_days']=np.log1p(g.training_days);g['log_training_minutes']=np.log1p(g.training_minutes)
 return g.reset_index(drop=True)
def reconstruct(g,s):
 raw=g[s['num_columns']].copy();n=raw.fillna(s['medians'])
 for c in raw:
  assert np.isclose(raw[c].median() if raw[c].notna().any() else 0,s['medians'][c])
  if raw[c].isna().any():n[c+'_missing']=raw[c].isna().astype(float)
 columns=[]
 for c in s['columns']:
  if c.startswith('own='):v=(g.same_jockey&g.jockey_id.eq(c[4:])).to_numpy(float)
  else:
   if c.startswith('trainer_'):n[c]=g.trainer_id.eq(c[8:]).astype(float)
   elif c.startswith('jockey_'):n[c]=g.jockey_id.eq(c[7:]).astype(float)
   elif c.startswith('unsupported_own='):n[c]=(g.same_jockey&g.jockey_id.eq(c[len('unsupported_own='):])).astype(float)
   assert np.isclose(n[c].mean(),s['means'][c]) and np.isclose(n[c].std(ddof=0),s['sd'][c]);v=((n[c]-s['means'][c])/s['sd'][c]).to_numpy()
  columns.append(v)
 return np.column_stack(columns)
def adjusted(p):
 p=np.asarray(p,float);ix=np.argsort(p);result=np.empty(len(p));running=1.
 for k in range(len(p)-1,-1,-1):running=min(running,p[ix[k]]*len(p)/(k+1));result[ix[k]]=running
 return result
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False);manifest=json.loads((HERE/'input01/source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 assert json.loads((OLD/'verification02/verification.json').read_text())['status']=='passed'
 a,f=load();supports=pd.read_csv(HERE/'analysis01/support.csv',dtype={'jockey_id':str,'period':str});ef=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'jockey_id':str,'period':str});raw=pd.read_csv(HERE/'analysis01/raw_primary.csv',dtype={'jockey_id':str,'period':str});om=pd.read_csv(HERE/'analysis01/heterogeneity.csv',dtype={'period':str});models=json.loads((HERE/'analysis01/models.json').read_text());maxbeta=0.;maxcov=0.;checked=0;supportchecks=0;rawchecks=0;held=0
 for m in models:
  g=sample(a,f,m);ss=supports[(supports.period==m['period'])&(supports.variant==m['variant'])];assert set(ss.jockey_id)==set(g.jockey_id);eligible=[]
  for row in ss.itertuples():
   v=g[g.jockey_id.eq(row.jockey_id)];q=v[v.same_jockey];r=v[~v.same_jockey];both=set(q.horse_distance)&set(r.horse_distance);cross=v[v.horse_distance.isin(both)].horse_id.nunique();n,h,d,c=(30,10,10,5) if m['variant']=='small_support' else (50,20,15,10);ok=min(len(q),len(r))>=n and min(q.horse_id.nunique(),r.horse_id.nunique())>=h and min(q.race_date.nunique(),r.race_date.nunique())>=d and cross>=c
   strict=min(len(q),len(r))>=100 and min(q.horse_id.nunique(),r.horse_id.nunique())>=30 and min(q.race_date.nunique(),r.race_date.nunique())>=20 and cross>=20
   assert row.support==ok and row.strict_previous100_support==strict and row.positive_starts==len(q) and row.negative_starts==len(r) and row.crossover_horses==cross;supportchecks+=1
   if ok:eligible.append(row.jockey_id)
   if m['variant']=='primary':
    for own,z in [(True,q),(False,r)]:
     if not len(z):continue
     rr=raw[(raw.period==m['period'])&raw.jockey_id.eq(row.jockey_id)&raw.same_jockey.eq(own)].iloc[0];assert len(z)==rr.starts and z.horse_id.nunique()==rr.horses and int(z.top3.sum())==rr.top3_count and np.allclose([z.finish_position.mean(),z.top3_pp.mean(),z.relative_time.mean()],[rr.finish_position_mean,rr.top3_pp_mean,rr.relative_time_mean]);rawchecks+=1
     for target in ['finish_position','top3_pp','rank10_quality','relative_time','H1_time_adv']:
      zz=z[z[target].notna()];y=zz[target];point=y.mean()
      if not len(y):continue
      for label,key in [('date','race_date'),('horse','horse_id')]:
       sums=(y-point).groupby(zz[key]).sum();G=len(sums)
       if G<2:continue
       half=t.ppf(.975,G-1)*np.sqrt((sums*sums).sum()/len(y)**2*G/(G-1));assert np.allclose([point-half,point+half],[rr[target+'_'+label+'_low'],rr[target+'_'+label+'_high']])
  if m['status']!='fitted':assert not eligible;held+=1;continue
  assert eligible==m['spec']['eligible_jockeys'] and g.api_record_id.astype(int).tolist()==m['row_ids'];X=reconstruct(g,m['spec']);Z,C=fe(g);assert Z.shape[1]==m['FE']['rank'] and C==m['FE']['components'];K=len(eligible);pen=np.r_[np.zeros(K),np.ones(X.shape[1]-K)];xs=csc_matrix(X);ZZ=(Z.T@Z).tocsc();lu=splu(ZZ);joint=splu(bmat([[ZZ,Z.T@xs],[xs.T@Z,xs.T@xs+diags(pen)]],format='csc'));xr=X-Z@lu.solve(np.asarray(Z.T@X));bread=np.linalg.inv(X.T@X-np.asarray(X.T@Z)@lu.solve(np.asarray(Z.T@X))+np.diag(pen));assert len(g)-Z.shape[1]-np.linalg.matrix_rank(xr,tol=1e-7)==m['residual_df']
  for model in m['models']:
   y=g[model['target']].to_numpy();coef=joint.solve(np.r_[np.asarray(Z.T@y).ravel(),X.T@y]);beta=coef[Z.shape[1]:];err=float(np.abs(beta-model['beta']).max());assert err<1e-5;maxbeta=max(maxbeta,err);res=y-Z@coef[:Z.shape[1]]-X@beta;covs={}
   for label,key in [('date','race_date'),('horse','horse_id')]:
    score=pd.DataFrame(xr*res[:,None]);score['key']=g[key].to_numpy();s=score.groupby('key').sum().to_numpy();G=len(s);cov=bread@s.T@s@bread*(G/(G-1)*(len(g)-1)/m['residual_df']);err=float(np.abs(cov-np.asarray(model[label+'_cov'])).max());assert err<1e-5;maxcov=max(maxcov,err);covs[label]=cov
   for i,j in enumerate(eligible):
    rr=ef[(ef.period==m['period'])&(ef.variant==m['variant'])&(ef.target==model['target'])&ef.jockey_id.eq(j)].iloc[0];sign=-1 if model['target']=='relative_time' else 1;point=sign*beta[i];sd=np.sqrt(max(0,covs['date'][i,i]));sh=np.sqrt(max(0,covs['horse'][i,i]));v=g[g.jockey_id.eq(j)];crit=t.ppf(.975,min(v.race_date.nunique(),v.horse_id.nunique())-1);assert np.isclose(crit,model['crit_by_jockey'][j]);assert np.allclose([point,point-crit*sd,point+crit*sd,point-crit*sh,point+crit*sh],[rr.effect,rr.date_low,rr.date_high,rr.horse_low,rr.horse_high]);checked+=1
   if m['variant']=='primary' and model['target']!='H1_time_adv' and K>=2:
    rr=om[(om.period==m['period'])&(om.target==model['target'])].iloc[0];contrast=np.zeros((K-1,len(beta)));contrast[:,0]=-1
    for i in range(K-1):contrast[i,i+1]=1
    diff=contrast@beta
    for label,key in [('date','race_date'),('horse','horse_id')]:
     S=contrast@covs[label]@contrast.T;stat=diff@np.linalg.pinv(S)@diff/(K-1);p=fdist.sf(stat,K-1,g[key].nunique()-1);assert np.allclose([stat,p],[rr[label+'_F'],rr[label+'_p']])
  print('Individual joint FE independently verified',m['period'],m['variant'],len(eligible),flush=True)
 for variant,ish1 in [('primary',False),('primary',True),('small_support',False)]:
  v=ef[ef.variant.eq(variant)&(ef.target.eq('H1_time_adv') if ish1 else ef.target.ne('H1_time_adv'))];assert np.allclose(v.BH_q,adjusted(v.date_p))
 expected=ef.variant.isin(['primary','small_support'])&ef.BH_q.lt(.05)&((ef.date_low.gt(0)&ef.horse_low.gt(0))|(ef.date_high.lt(0)&ef.horse_high.lt(0)));assert np.array_equal(expected,ef.direction_supported)
 for label in ['date','horse']:assert np.allclose(om[label+'_BH_q'],adjusted(om[label+'_p']))
 rep=pd.read_csv(HERE/'analysis01/repeat_checks.csv',dtype={'jockey_id':str})
 for r in rep.itertuples():
  v=ef[ef.variant.eq('primary')&ef.period.ne('all')&ef.jockey_id.eq(r.jockey_id)&ef.target.eq(r.target)];assert len(v)==r.periods_supported and r.positive_recent_repeated==(len(v)==2 and bool((v.direction_supported&v.effect.gt(0)).all()))
 names=pd.read_csv(HERE/'input01/jockey_names.csv',dtype={'jockey_id':str});assert names.jockey_id.is_unique and set(names.jockey_id)==set(a.jockey_id)
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 primary=ef[ef.variant.eq('primary')&ef.target.ne('H1_time_adv')];h1=ef[ef.variant.eq('primary')&ef.target.eq('H1_time_adv')];pos=primary[primary.direction_supported&primary.effect.gt(0)];neg=primary[primary.direction_supported&primary.effect.lt(0)]
 receipt={'status':'passed','support_cells_recomputed':supportchecks,'raw_cells_and_intervals_recomputed':rawchecks,'individual_effects_and_cluster_intervals_recomputed':checked,'held_model_groups':held,'maximum_beta_difference':maxbeta,'maximum_covariance_difference':maxcov,'primary_BH_tests':len(primary),'H1_BH_tests':len(h1),'small_support_BH_tests':int(ef.variant.eq('small_support').sum()),'primary_positive_supported':len(pos),'primary_negative_supported':len(neg),'positive_recent_repeated':int(rep.positive_recent_repeated.sum()),'heterogeneity_tests_recomputed':len(om),'sources_hashes_bytes_unchanged':True,'database_opened':False,'operational_change':False};save(out/'verification.json',receipt)
 save(HERE/'decision.json',{'status':'individual_jockey_direct_training_completed','period_start':'2017-01-13','period_end':'2026-09-19','partial_2026':True,'primary_unit':'horse_distance_jockey_and_race_FE','primary_window_days':14,'support_each_group_starts':50,'support_each_group_horses':20,'support_each_group_dates':15,'support_crossover_horses':10,'primary_supported_jockeys_by_period':supports[supports.variant.eq('primary')].groupby('period').support.sum().astype(int).to_dict(),'primary_BH_tests':len(primary),'H1_BH_tests':len(h1),'primary_positive_supported_rows':len(pos),'primary_negative_supported_rows':len(neg),'primary_positive_supported_jockeys':sorted(pos.jockey_id.unique().tolist()),'positive_recent_repeated':int(rep.positive_recent_repeated.sum()),'fixed_jockey_training_bonus_adopted':False,'causal_effect_identified':False,'new_predictive_gain_tested':False,'operationally_applied':False,'database_opened':False,'jockey_and_style_pauses_preserved':True});print('Individual jockey training verification passed',checked,flush=True)
if __name__=='__main__':main()
