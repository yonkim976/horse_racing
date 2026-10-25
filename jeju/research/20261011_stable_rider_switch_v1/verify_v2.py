"""Independent stacked least-squares, cluster covariance, identities and all raw cells."""
import json
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,ROOT,OLD,ID_COLS,BASE,DELTA,CAT,sha,save,period_data
def bh(p):
 p=np.asarray(p,float);order=np.argsort(p);adj=np.minimum.accumulate((len(p)*p[order]/np.arange(1,len(p)+1))[::-1])[::-1];out=np.empty(len(p));out[order]=np.minimum(adj,1);return out
def reconstruct(g,treatment,spec):
 raw=g[BASE].copy();raw['log_gap']=np.log1p(g.gap_days);raw['distance_changed']=g.race_distance_m.ne(g.previous_race_distance_m).astype(float);raw['grade_changed']=g.class_clean.ne(g.previous_class_clean).astype(float)
 for c in DELTA:raw['delta_'+c]=g[c]-g['previous_'+c]
 assert all(np.isclose(raw[c].median() if raw[c].notna().any() else 0,v) for c,v in spec['medians'].items())
 n=raw.fillna(spec['medians'])
 for c in raw:
  if raw[c].isna().any():n[c+'_missing']=raw[c].isna().astype(float)
 columns=[]
 for c in spec['columns']:
  if c=='intercept':v=np.ones(len(g))
  elif c=='comparison':v=np.asarray(treatment,float)
  elif c in spec['means']:
   assert np.isclose(n[c].mean(),spec['means'][c]) and np.isclose(n[c].std(ddof=0),spec['sd'][c]);v=(n[c]-spec['means'][c])/spec['sd'][c]
  else:
   key=next(k for k in CAT if c.startswith(k+'_'));label=c[len(key)+1:];v=g[key].astype(str).eq(label).astype(float)
  columns.append(np.asarray(v))
 return np.column_stack(columns)
def cov_independent(X,res,bread,key,df):
 scores=pd.DataFrame(X*res[:,None]);scores['cluster']=np.asarray(key);s=scores.groupby('cluster').sum().to_numpy();G=len(s);return bread@s.T@s@bread*(G/(G-1)*(len(X)-1)/df)
def main():
 out=HERE/'verification02';out.mkdir(exist_ok=False);manifest=json.loads((HERE/'input01/source_manifest.json').read_text())
 for r in manifest['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 assert manifest['database_sha256']==sha(ROOT/'jeju/data/jeju_native_core.sqlite3')
 dtype={c:str for c in ID_COLS};a=pd.read_csv(HERE/'input01/pairs.csv',dtype=dtype,low_memory=False);src=pd.read_csv(OLD/'input01/starts.csv',dtype=dtype,low_memory=False).set_index('api_record_id');expected=src[src.same_relations&src.gap_days.between(2,90)&src.previous_api_record_id.notna()].sort_values(['race_date','race_id','horse_number'])
 assert a.api_record_id.tolist()==expected.index.tolist() and len(a)==43024 and a.changed_jockey.sum()==18231 and not a.horse_id.eq('3005648').any()
 cur=src.loc[a.api_record_id];prev=src.loc[a.previous_api_record_id.astype(int)];assert cur.horse_id.tolist()==prev.horse_id.tolist() and cur.trainer_id.tolist()==prev.trainer_id.tolist() and cur.owner_id.tolist()==prev.owner_id.tolist();assert (cur.race_date.to_numpy()>prev.race_date.to_numpy()).all()
 assert np.array_equal(a.changed_jockey,cur.jockey_id.to_numpy()!=prev.jockey_id.to_numpy())
 for c in ['H1_time_adv','H1_top3_excess','H1_time','H1_prob','relative_time','top3','field_n','finish_position']:
  assert np.allclose(a[c],cur[c],equal_nan=True),c
  if 'previous_'+c in a:assert np.allclose(a['previous_'+c],prev[c],equal_nan=True),c
 assert np.allclose(a.top3_excess_gain,a.H1_top3_excess-a.previous_H1_top3_excess,equal_nan=True)
 assert np.allclose(a.time_gain,a.H1_time_adv-a.previous_H1_time_adv,equal_nan=True)
 assert np.allclose(a.H1_top3_excess,100*(a.top3-a.H1_prob),equal_nan=True)
 for prefix in ['current','previous']:
  q=a[a[prefix+'_rider_last_date'].notna()];assert q[prefix+'_rider_last_date'].le(q[prefix+'_rider_cutoff']).all()
 assert a.history_cutoff.lt(a.race_date).all()
 support=pd.read_csv(HERE/'input01/support.csv',dtype={'period':str})
 for r in support.itertuples():
  z=period_data(a,r.period);z=z[z.recent_eligible] if r.period in ['2024_2025','2026'] else z;g=z[z.cell.eq(r.cell)];c=g[g.changed_jockey];other=z[z.trainer_id.eq(r.trainer_id)&z.changed_jockey&z.cell.ne(r.cell)]
  # Read ID strings from cell; support CSV ID inference must not affect selection.
  other=z[z.trainer_id.eq(r.cell.split(':')[0])&z.changed_jockey&z.cell.ne(r.cell)]
  assert len(g)==r.starts and len(c)==r.changes and len(g)-len(c)==r.retained and len(other)==r.other_changes_same_stable
  ok=len(c)>=20 and len(g)-len(c)>=20 and g.horse_id.nunique()>=15 and g.race_date.nunique()>=15 and c.horse_id.nunique()>=10 and c.race_date.nunique()>=10 and len(other)>=30;assert ok==r.qualified
 raw=pd.read_csv(HERE/'analysis01/raw_all_cells.csv',dtype={'period':str});rawchecks=0
 for r in raw.itertuples():
  g=period_data(a,r.period);g=g[g.cell.eq(r.cell)&g.changed_jockey.eq(r.changed)];assert len(g)==r.starts and g.horse_id.nunique()==r.horses;assert int(g.top3.sum())==r.current_top3_count and int(g.previous_top3.sum())==r.previous_top3_count
  assert np.allclose([g.top3.mean(),g.previous_top3.mean(),100*(g.top3-g.previous_top3).mean(),g.time_gain.mean(),g.rank_improved.mean()],[r.current_top3,r.previous_top3,r.top3_gain_pp,r.H1_time_gain,r.rank_improved],equal_nan=True);rawchecks+=1
 ef=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str});sup=pd.read_csv(HERE/'supplement02/effects_all_A.csv',dtype={'period':str});supp_support=pd.read_csv(HERE/'supplement02/support.csv',dtype={'trainer_id':str,'jockey_id':str,'period':str});assert supp_support.trainer_id.eq(supp_support.cell.str.split(':').str[0]).all() and supp_support.jockey_id.eq(supp_support.cell.str.split(':').str[1]).all();groups=json.loads((HERE/'analysis01/models.json').read_text())+json.loads((HERE/'supplement02/additional_models.json').read_text());checks=0;maxbeta=0.;maxcov=0.;held=0
 for group in groups:
  if group['status']!='fitted':held+=1;continue
  g=a.set_index('api_record_id').loc[group['row_ids']].copy();tr=np.array(group['treatment']);assert len(g)==group['rows'] and tr.sum()==group['treated']
  assert np.array_equal(tr,g.cell.eq(group['cell']) if group['comparison']=='other_switches' else g.changed_jockey)
  for model in group['models']:
   X=reconstruct(g,tr,model['spec']);y=g[model['target']].to_numpy();pen=np.r_[0.,0.,np.ones(X.shape[1]-2)];augX=np.vstack([X,np.diag(np.sqrt(pen))]);augy=np.r_[y,np.zeros(X.shape[1])];beta=np.linalg.lstsq(augX,augy,rcond=1e-12)[0];err=float(np.max(np.abs(beta-model['beta'])));assert err<1e-6;maxbeta=max(maxbeta,err)
   res=y-X@beta;assert np.max(np.abs(X.T@res-pen*beta))<1e-5;bread=np.linalg.inv(X.T@X+np.diag(pen));dc=cov_independent(X,res,bread,g.race_date,model['residual_df']);hc=cov_independent(X,res,bread,g.horse_id,model['residual_df']);err=max(float(np.abs(dc-model['date_cov']).max()),float(np.abs(hc-model['horse_cov']).max()));assert err<1e-7;maxcov=max(maxcov,err)
   table=ef if group['variant']!='A_only_supplement' else sup;q=table[(table.period==group['period'])&(table.cell==group['cell'])&(table.comparison==group['comparison'])&(table.variant==group['variant'])&(table.target==model['target'])];assert len(q)==1;r=q.iloc[0];sd=np.sqrt(max(0,dc[1,1]));sh=np.sqrt(max(0,hc[1,1]));assert np.allclose([r.effect,r.date_low,r.date_high,r.horse_low,r.horse_high],[beta[1],beta[1]-model['crit']*sd,beta[1]+model['crit']*sd,beta[1]-model['crit']*sh,beta[1]+model['crit']*sh]);checks+=1
 print('Models independently reconstructed',checks,flush=True)
 main=ef[ef.variant.eq('primary')];assert len(main)==186 and np.allclose(main.BH_q,bh(main.date_p));assert np.allclose(sup.supplement_BH_q,bh(sup.date_p))
 assert np.array_equal(main.positive_supported,main.BH_q.lt(.05)&main.date_low.gt(0)&main.horse_low.gt(0));assert not main.positive_supported.any() and not sup.exploratory_positive_supported.any()
 repeats=pd.read_csv(HERE/'analysis01/repeat_checks.csv');assert not repeats.repeat_positive.any()
 save(out/'verification.json',{'status':'passed','eligible_rows_source_checked':len(a),'source_previous_edges_checked':len(a),'changes':int(a.changed_jockey.sum()),'support_rows_recomputed':len(support),'raw_rows_recomputed':rawchecks,'model_outcome_contrasts_reestimated_by_augmented_least_squares':checks,'held_model_groups_preserved':held,'maximum_beta_difference':maxbeta,'maximum_covariance_difference':maxcov,'primary_tests_BH_recomputed':len(main),'supplement_tests_BH_recomputed':len(sup),'positive_supported_primary':int(main.positive_supported.sum()),'positive_supported_supplement':int(sup.exploratory_positive_supported.sum()),'repeated_positive_primary':int(repeats.repeat_positive.sum()),'top3_excess_units_percentage_points':True,'source_cutoffs_verified':True,'all_pinned_source_hashes_and_bytes_unchanged':True,'database_hash_unchanged':True,'no_operational_change':True})
 print('Stable rider switch verification passed',flush=True)
if __name__=='__main__':main()
