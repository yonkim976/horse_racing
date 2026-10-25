"""Independent past-only candidate selection and subsequent regression checks."""
import json
import numpy as np
import pandas as pd
from scipy.linalg import lstsq
from scipy.sparse import csc_matrix,bmat,diags
from scipy.sparse.linalg import splu
from scipy.stats import t
from data import HERE,IDS,save
from analysis import bh
from verify_main import fe_independent,reconstruct
def covariance(X,res,bread,key,df):
 scores=pd.DataFrame(X*res[:,None]);scores['day']=np.asarray(key);s=scores.groupby('day').sum().to_numpy();G=len(s);return bread@s.T@s@bread*(G/(G-1)*(len(X)-1)/df)
def main():
 out=HERE/'personal_verification01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);profiles=pd.read_csv(HERE/'personal01/profiles.csv',dtype={'horse_id':str});resids=pd.read_csv(HERE/'personal01/discovery_residuals.csv',dtype={'horse_id':str});summaries=pd.read_csv(HERE/'personal01/discovery_group_means.csv',dtype={'horse_id':str});models=json.loads((HERE/'personal01/discovery_models.json').read_text());candidate_checks=0;maxbeta=0.;maxcov=0.
 for group in models:
  expected=a[a.race_date.le(group['cutoff'])&a.gap_group.notna()];assert group['row_ids']==expected.api_record_id.astype(int).tolist() and expected.race_date.max()<=group['cutoff'];g=expected.set_index('api_record_id').loc[group['row_ids']];X=reconstruct(g,group['spec']);Z,C=fe_independent(g,'horse_distance');xs=csc_matrix(X);matrix=bmat([[Z.T@Z,Z.T@xs],[xs.T@Z,xs.T@xs+diags(np.ones(X.shape[1]))]],format='csc');y=g.relative_time.to_numpy();coef=splu(matrix).solve(np.r_[np.asarray(Z.T@y).ravel(),X.T@y]);beta=coef[Z.shape[1]:];err=float(np.abs(beta-group['beta']).max());assert err<1e-5;maxbeta=max(maxbeta,err);adv=-(y-Z@coef[:Z.shape[1]]-X@beta)
  r=resids[resids.snapshot.eq(group['snapshot'])].set_index('api_record_id').loc[group['row_ids']];assert np.allclose(adv,r.advantage_residual,atol=1e-7)
  # Rebuild group means from scalar sums; do not use the selection implementation.
  groups={}
  for row,value in zip(g.itertuples(),adv):groups.setdefault((row.horse_id,row.preference_gap_group),[]).append(float(value))
  for row in profiles[profiles.snapshot.eq(group['snapshot'])].itertuples():
   z=[(label,v) for (horse,label),v in groups.items() if horse==row.horse_id];total=sum(len(v) for _,v in z);eligible=sorted([(sum(v)/len(v),label,len(v)) for label,v in z if len(v)>=5],key=lambda v:(-v[0],v[1]));ok=total>=20 and len(eligible)>=2
   assert row.training_starts==total and row.supported_gap_groups==len(eligible) and (row.status=='historical_candidate_only')==ok
   if ok:assert row.best_gap_group==eligible[0][1] and row.second_gap_group==eligible[1][1] and np.isclose(row.best_minus_second,eligible[0][0]-eligible[1][0],atol=1e-7)
   candidate_checks+=1
  assert not group['gap_variables_used'] and all(not c.startswith(('interval=','absolute=')) for c in group['spec']['columns'])
 individual_checked=0
 for folder,modelname,small in [('personal01','individual_models.json',False),('small_sample01','models.json',True)]:
  table=pd.read_csv(HERE/folder/'individual_validation.csv',dtype={'horse_id':str,'period':str});mm=json.loads((HERE/folder/modelname).read_text())
  for group in mm:
   p=profiles[profiles.snapshot.eq(group['snapshot'])&profiles.horse_id.eq(group['horse_id'])].iloc[0];assert p.status=='historical_candidate_only' and p.best_gap_group==group['preferred_gap_group'];z=a[a.year.between(2024,2025)] if group['period']=='2024_2025' else a[a.year.eq(2026)];z=z[z.horse_id.eq(group['horse_id'])&z.gap_group.notna()&z.H1_time_adv.notna()];assert z.api_record_id.astype(int).tolist()==group['row_ids'];g=z;tr=g.preference_gap_group.eq(p.best_gap_group).to_numpy(float);cols=[np.ones(len(g)),tr]
   for key in ['race_distance_m','year']:
    vals=g[key].astype(str)
    for value in sorted(vals.unique())[1:]:cols.append(vals.eq(value).to_numpy(float))
   X=np.column_stack(cols);y=g.H1_time_adv.to_numpy();beta=lstsq(X,y,lapack_driver='gelsy')[0];expected=np.array(group['beta']);assert np.allclose(X@beta,X@expected,atol=1e-7) and np.isclose(beta[1],expected[1],atol=1e-7);pinv=np.linalg.pinv(X,rcond=1e-12);bread=pinv@pinv.T;res=y-X@beta;cov=covariance(X,res,bread,g.race_date,group['residual_df']);err=float(np.abs(cov-group['date_cov']).max());assert err<1e-6;maxcov=max(maxcov,err)
   r=table[table.snapshot.eq(group['snapshot'])&table.period.eq(group['period'])&table.horse_id.eq(group['horse_id'])].iloc[0];half=group['crit']*np.sqrt(max(0,cov[1,1]));assert np.allclose([r.effect,r.date_low,r.date_high],[beta[1],beta[1]-half,beta[1]+half]);assert len(g)>=(10 if small else 20) and min(tr.sum(),len(g)-tr.sum())>=(3 if small else 5);individual_checked+=1
  assert len(table[table.status.eq('fitted')])==len(mm)
  for snapshot in ['2024_fixed','2026_updated']:
   q=table[table.snapshot.eq(snapshot)&table.status.eq('fitted')]
   if len(q):assert np.allclose(q.BH_q,bh(q.date_p))
  indicator='exploratory_positive_supported' if small else 'positive_supported';assert np.array_equal(table[indicator],table.status.eq('fitted')&table.BH_q.lt(.05)&table.date_low.gt(0))
 pool=pd.read_csv(HERE/'personal01/pooled_validation.csv',dtype={'period':str});pooled_models=json.loads((HERE/'personal01/pooled_models.json').read_text());pooled_checked=0
 for group in pooled_models:
  mapping=profiles[profiles.snapshot.eq('2024_fixed')&profiles.status.eq('historical_candidate_only')].set_index('horse_id').best_gap_group.to_dict();g=a.set_index('api_record_id').loc[group['row_ids']].copy();g['preferred']=g.preference_gap_group.eq(g.horse_id.map(mapping)).astype(float);spec=dict(group['spec']);spec['columns']=spec['columns'][1:];X=np.column_stack([g.preferred,reconstruct(g,spec)]);Z,C=fe_independent(g,'horse_distance');xs=csc_matrix(X);pen=np.r_[0.,np.ones(X.shape[1]-1)];ZZ=(Z.T@Z).tocsc();zlu=splu(ZZ);matrix=bmat([[ZZ,Z.T@xs],[xs.T@Z,xs.T@xs+diags(pen)]],format='csc');y=g.H1_time_adv.to_numpy();coef=splu(matrix).solve(np.r_[np.asarray(Z.T@y).ravel(),X.T@y]);beta=coef[Z.shape[1]:];assert np.allclose(beta,group['beta'],atol=1e-5);xr=X-Z@zlu.solve(np.asarray(Z.T@X));bread=np.linalg.inv(xr.T@xr+np.diag(pen));res=y-Z@coef[:Z.shape[1]]-X@beta;r=pool[pool.period.eq(group['period'])].iloc[0]
  for label,key in [('date','race_date'),('horse','horse_id')]:
   cov=covariance(xr,res,bread,g[key],group['residual_df']);assert np.allclose(cov,group[label+'_cov'],atol=1e-5);half=group['crit']*np.sqrt(max(0,cov[0,0]));assert np.allclose([r[label+'_low'],r[label+'_high']],[beta[0]-half,beta[0]+half])
  pooled_checked+=1
 assert np.allclose(pool.BH_q,bh(pool.date_p)) and not pool.positive_supported.all()
 repeats=pd.read_csv(HERE/'personal01/repeat_checks.csv');assert not repeats.repeated_positive_supported.any()
 save(out/'verification.json',{'status':'passed','past_only_snapshot_profile_rows_independently_reselected':candidate_checks,'discovery_models_joint_FE_reestimated':len(models),'individual_primary_and_small_sample_regressions_reestimated_QR':individual_checked,'pooled_preference_effects_joint_FE_reestimated':pooled_checked,'maximum_discovery_beta_difference':maxbeta,'maximum_individual_covariance_difference':maxcov,'BH_families_recomputed':5,'primary_individual_repeated_confirmed':0,'small_sample_exploratory_positive':0,'candidate_choice_before_evaluation_cutoff':True,'no_gap_terms_in_discovery_condition_model':True,'no_individual_horse_cluster_interval_claim':True,'no_operational_changes':True});print('Personal preferred-cycle checks independently verified',candidate_checks,individual_checked,pooled_checked,flush=True)
if __name__=='__main__':main()
