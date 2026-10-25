"""Past-performance rider upgrades and outcomes beyond frozen H0/H1 expectations."""
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,save
from closing import cluster,bh

def design(g,upgrade):
 x=pd.DataFrame({'intercept':1.,'upgrade':g[upgrade].astype(float)},index=g.index)
 n=g[['H0_prob','H0_time','h_any_finish_rank_mean','h_any_relative_time_mean','h_any_n','previous_top3','previous_relative_time',
      'previous_H0_prob','previous_H0_time_adv','previous_H0_top3_excess','body_kg','carried_weight_kg','moisture','gate_scaled','field_n']].copy()
 n['log_gap']=np.log1p(g.gap_days)
 n['distance_changed']=g.race_distance_m.ne(g.previous_race_distance_m).astype(float)
 n['grade_changed']=g.class_clean.ne(g.previous_class_clean).astype(float)
 n['relations_changed']=(~g.same_relations).astype(float)
 for c in ['body_kg','carried_weight_kg','moisture','gate_scaled','h_any_relative_time_mean','h_any_finish_rank_mean']:
  n['delta_'+c]=g[c]-g['previous_'+c]
 med=n.median();n=n.fillna(med).fillna(0)
 for c in med.index:
  if c in g and g[c].isna().any():n[c+'_missing']=g[c].isna().astype(float)
  elif c.startswith('delta_'):
   q=c[6:];mask=g[q].isna()|g['previous_'+q].isna()
   if mask.any():n[c+'_missing']=mask.astype(float)
 sd=n.std(ddof=0);n=n[sd[sd>1e-12].index];mu=n.mean();sd=n.std(ddof=0);n=(n-mu)/sd
 cat=pd.get_dummies(g[['year','month','race_distance_m','class_clean','trainer_id','owner_id']].astype(str),drop_first=True,dtype=float)
 x=pd.concat([x,n,cat],axis=1)
 return x,{'nuisance_medians':med.fillna(0).to_dict(),'nuisance_means':mu.to_dict(),'nuisance_sd':sd.to_dict(),'columns':x.columns.tolist()}

def fit(g,period,variant,upgrade):
 counts=g[upgrade].value_counts();good=len(g)>=100 and counts.get(True,0)>=30 and counts.get(False,0)>=30 and g.race_date.nunique()>=20
 if not good:return [],{'period':period,'variant':variant,'status':'insufficient_support','starts':len(g),'upgrades':int(g[upgrade].sum())}
 x,spec=design(g,upgrade);X=x.to_numpy();j=1;rank=np.linalg.matrix_rank(X,tol=1e-8);df=len(g)-rank;assert df>20
 uj=X[:,j]-X[:,np.arange(X.shape[1])!=j]@np.linalg.lstsq(X[:,np.arange(X.shape[1])!=j],X[:,j],rcond=1e-10)[0]
 assert np.linalg.norm(uj)>1e-6
 penalty=np.r_[0.,0.,np.ones(X.shape[1]-2)];bread=np.linalg.inv(X.T@X+np.diag(penalty));crit=float(t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1));rows=[];models=[]
 for target in ['H0_top3_excess','H1_top3_excess','H0_time_adv','H1_time_adv']:
  y=g[target].to_numpy();assert np.isfinite(y).all();beta=bread@X.T@y;res=y-X@beta
  row={'period':period,'variant':variant,'target':target,'starts':len(g),'upgrades':int(g[upgrade].sum()),'others':int((~g[upgrade]).sum()),'horses':g.horse_id.nunique(),'days':g.race_date.nunique(),'effect':float(beta[j])}
  for name,key in [('date','race_date'),('horse','horse_id')]:
   cov=cluster(X,res,bread,g[key],df);se=float(np.sqrt(max(0,cov[j,j])));row[name+'_low']=float(beta[j]-crit*se);row[name+'_high']=float(beta[j]+crit*se)
   if name=='date':row['date_p']=float(2*t.sf(abs(beta[j]/se),min(g.race_date.nunique(),g.horse_id.nunique())-1)) if se else 1.
  rows.append(row);models.append({'period':period,'variant':variant,'target':target,'row_ids':g.api_record_id.astype(int).tolist(),'upgrade_column':upgrade,'spec':spec,'beta':beta.tolist(),'residual_df':int(df),'crit':crit})
 return rows,{'period':period,'variant':variant,'status':'fitted','starts':len(g),'upgrades':int(g[upgrade].sum()),'models':models}

def main():
 out=HERE/'switch01';out.mkdir(exist_ok=False)
 a=pd.read_csv(HERE/'input01/starts.csv',dtype={'horse_id':str,'jockey_id':str,'trainer_id':str,'owner_id':str},low_memory=False)
 a=a[a.year.ge(2024)&a.gap_days.between(2,90)&a.rider_stats_valid&a.H0_prob.notna()&a.H1_prob.notna()].copy()
 a.to_csv(out/'eligible_pairs.csv',index=False,encoding='utf-8-sig');raw=[];rows=[];models=[];relations=[]
 for period,g in [('2024_2025',a[a.year.le(2025)]),('2026',a[a.year.eq(2026)])]:
  for variant,z in [('same_relations',g[g.same_relations]),('all_relations',g)]:
   for label,v in z.groupby('switch_group'):
    raw.append({'period':period,'variant':variant,'group':label,'starts':len(v),'horses':v.horse_id.nunique(),'top3_count':int(v.top3.sum()),'raw_top3':v.top3.mean(),'H0_expected_top3':v.H0_prob.mean(),'H1_expected_top3':v.H1_prob.mean(),'H0_top3_excess_pp':v.H0_top3_excess.mean(),'H1_top3_excess_pp':v.H1_top3_excess.mean(),'H0_time_adv_s':v.H0_time_adv.mean(),'H1_time_adv_s':v.H1_time_adv.mean(),'previous_top3':v.previous_top3.mean(),'mean_rate_gain':v.rider_rate_gain.mean()})
  variants=[('same_relations_changed',g[g.same_relations&g.changed_jockey],'upgrade'),('all_relations_changed',g[g.changed_jockey],'upgrade'),
   ('same_relations_changed_upgrade10',g[g.same_relations&g.changed_jockey],'upgrade10'),('same_relations_vs_retained',g[g.same_relations&(g.upgrade|~g.changed_jockey)],'upgrade')]
  for variant,z,upgrade in variants:
   rr,mm=fit(z.copy(),period,variant,upgrade);rows+=rr;models.append(mm)
  for role in ['trainer','owner']:
   z=g[g.same_relations&g.changed_jockey]
   for identity,v in z.groupby(role+'_id'):
    r={'period':period,'role':role,'identity_id':identity,'event_name':v.sort_values('race_date')[role+'_name'].iloc[-1], 'changed_starts':len(v),'upgrades':int(v.upgrade.sum()),'display_support':bool(len(v)>=30 and v.upgrade.sum()>=10)}
    for label,zz in [('upgrade',v[v.upgrade]),('other',v[~v.upgrade])]:
     r[label+'_n']=len(zz);r[label+'_raw_top3']=zz.top3.mean();r[label+'_H1_top3_excess_pp']=zz.H1_top3_excess.mean()
    relations.append(r)
 result=pd.DataFrame(rows);result['BH_q']=np.nan
 ix=result.variant.eq('same_relations_changed');assert ix.sum()==8;result.loc[ix,'BH_q']=bh(result.loc[ix,'date_p'])
 result['supported']=ix&result.BH_q.lt(.05)&((result.date_low.gt(0)&result.horse_low.gt(0))|(result.date_high.lt(0)&result.horse_high.lt(0)))
 result.to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');pd.DataFrame(raw).to_csv(out/'raw_results.csv',index=False,encoding='utf-8-sig');pd.DataFrame(relations).to_csv(out/'relation_groups.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models)
 print(result[ix].to_string(index=False),flush=True)
if __name__=='__main__':main()
