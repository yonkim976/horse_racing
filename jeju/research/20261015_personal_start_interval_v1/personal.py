"""Past-only candidate cycles and fixed-candidate subsequent expected-performance checks."""
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,IDS,BASE,save
from analysis import conditions,project,cluster,bh
CLASSES=['1_7','8_14','15_28','29_42','43_90','91_plus']
def discovery(a,cutoff,snapshot,names):
 g=a[a.race_date.le(cutoff)&a.gap_group.notna()].copy();n,spec=conditions(g,include_absolute=False,gap_free=True);X=n.to_numpy();y=g.relative_time.to_numpy();Z,lu,info=project(g,'horse_distance');xr=X-Z@lu.solve(np.asarray(Z.T@X));yr=y-Z@lu.solve(np.asarray(Z.T@y));pen=np.ones(X.shape[1]);beta=np.linalg.solve(xr.T@xr+np.diag(pen),xr.T@yr);alpha=lu.solve(np.asarray(Z.T@(y-X@beta)));res=y-X@beta-Z@alpha
 r=g[['api_record_id','horse_id','race_date','race_distance_m','preference_gap_group','gap_days']].copy();r['advantage_residual']=-res;r['snapshot']=snapshot
 summary=r.groupby(['horse_id','preference_gap_group']).agg(starts=('api_record_id','size'),mean_advantage=('advantage_residual','mean'),gap_min=('gap_days','min'),gap_max=('gap_days','max')).reset_index();rows=[]
 for horse,name in names.items():
  z=summary[summary.horse_id.eq(horse)];total=int(z.starts.sum());v=z[z.starts.ge(5)].sort_values(['mean_advantage','preference_gap_group'],ascending=[False,True]);ok=total>=20 and len(v)>=2
  row={'snapshot':snapshot,'cutoff':cutoff,'horse_id':horse,'horse_name':name,'training_starts':total,'supported_gap_groups':len(v),'status':'historical_candidate_only' if ok else 'insufficient_discovery_support','best_gap_group':None,'second_gap_group':None,'best_starts':0,'second_starts':0,'best_advantage':None,'second_advantage':None,'best_minus_second':None}
  if ok:
   best,second=v.iloc[0],v.iloc[1];row.update(best_gap_group=best.preference_gap_group,second_gap_group=second.preference_gap_group,best_starts=int(best.starts),second_starts=int(second.starts),best_advantage=float(best.mean_advantage),second_advantage=float(second.mean_advantage),best_minus_second=float(best.mean_advantage-second.mean_advantage))
  rows.append(row)
 model={'snapshot':snapshot,'cutoff':cutoff,'row_ids':g.api_record_id.astype(int).tolist(),'spec':{'columns':n.columns.tolist(),**spec},'beta':beta.tolist(),'alpha':alpha.tolist(),'FE':info,'gap_variables_used':False}
 return pd.DataFrame(rows),r,summary.assign(snapshot=snapshot),model
def individual(g,period,snapshot,horse,name,preferred):
 tr=g.preference_gap_group.eq(preferred);meta={'period':period,'snapshot':snapshot,'horse_id':horse,'horse_name':name,'preferred_gap_group':preferred,'starts':len(g),'matched':int(tr.sum()),'other':int((~tr).sum()),'days':g.race_date.nunique()}
 if len(g)<20 or min(tr.sum(),(~tr).sum())<5 or g.race_date.nunique()<10:return {**meta,'status':'insufficient_future_support'},None
 X=pd.concat([pd.DataFrame({'intercept':1.,'preferred':tr.astype(float)},index=g.index),pd.get_dummies(g[['race_distance_m','year']].astype(str),drop_first=True,dtype=float)],axis=1).to_numpy();rank=np.linalg.matrix_rank(X,tol=1e-8);df=len(g)-rank;N=np.delete(X,1,axis=1);ident=np.linalg.norm(X[:,1]-N@np.linalg.lstsq(N,X[:,1],rcond=1e-12)[0])
 if df<=5 or ident<1e-6:return {**meta,'status':'unidentified_or_insufficient_df','df':int(df)},None
 y=g.H1_time_adv.to_numpy();beta=np.linalg.lstsq(X,y,rcond=1e-12)[0];bread=np.linalg.pinv(X.T@X,rcond=1e-12);res=y-X@beta;dc=cluster(X,res,bread,g.race_date,df);sd=np.sqrt(max(0,dc[1,1]));crit=float(t.ppf(.975,g.race_date.nunique()-1));point=float(beta[1]);row={**meta,'status':'fitted','effect':point,'date_low':point-crit*sd,'date_high':point+crit*sd,'date_p':float(2*t.sf(abs(point/sd),g.race_date.nunique()-1)) if sd else 1.,'residual_df':int(df),'raw_matched_H1_adv':g.loc[tr,'H1_time_adv'].mean(),'raw_other_H1_adv':g.loc[~tr,'H1_time_adv'].mean(),'units':'seconds_faster_than_H1_expectation'}
 return row,{**meta,'row_ids':g.api_record_id.astype(int).tolist(),'columns':X.shape[1],'beta':beta.tolist(),'date_cov':dc.tolist(),'residual_df':int(df),'crit':crit}
def pooled(g,period):
 tr=g.preferred.astype(float);meta={'period':period,'rows':len(g),'matched':int(tr.sum()),'other':int(len(g)-tr.sum()),'horses':g.horse_id.nunique(),'days':g.race_date.nunique()}
 cross=g.assign(flag=tr).groupby('horse_distance').flag.nunique();units=set(cross[cross.eq(2)].index);horses=g[g.horse_distance.isin(units)].horse_id.nunique()
 if min(tr.sum(),len(g)-tr.sum())<100 or g.horse_id.nunique()<30 or g.race_date.nunique()<20 or horses<20:return {**meta,'status':'insufficient_support'},None
 n,spec=conditions(g,include_absolute=True);X=np.column_stack([tr,n.to_numpy()]);y=g.H1_time_adv.to_numpy();Z,lu,info=project(g,'horse_distance');xr=X-Z@lu.solve(np.asarray(Z.T@X));yr=y-Z@lu.solve(np.asarray(Z.T@y));df=len(g)-info['rank']-np.linalg.matrix_rank(xr,tol=1e-7);N=xr[:,1:];ident=np.linalg.norm(xr[:,0]-N@np.linalg.lstsq(N,xr[:,0],rcond=1e-10)[0])
 if df<=20 or ident<1e-6:return {**meta,'status':'unidentified_or_insufficient_df'},None
 pen=np.r_[0.,np.ones(X.shape[1]-1)];bread=np.linalg.inv(xr.T@xr+np.diag(pen));beta=bread@xr.T@yr;res=yr-xr@beta;dc=cluster(xr,res,bread,g.race_date,df);hc=cluster(xr,res,bread,g.horse_id,df);sd=np.sqrt(max(0,dc[0,0]));sh=np.sqrt(max(0,hc[0,0]));deg=min(g.race_date.nunique(),g.horse_id.nunique())-1;crit=float(t.ppf(.975,deg));point=float(beta[0]);row={**meta,'status':'fitted','crossover_horses_hd':horses,'effect':point,'date_low':point-crit*sd,'date_high':point+crit*sd,'horse_low':point-crit*sh,'horse_high':point+crit*sh,'date_p':float(2*t.sf(abs(point/sd),deg)) if sd else 1.,'units':'seconds_faster_than_H1_expectation'}
 return row,{**meta,'row_ids':g.api_record_id.astype(int).tolist(),'spec':{'columns':['preferred']+n.columns.tolist(),**spec},'beta':beta.tolist(),'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'FE':info,'residual_df':int(df),'crit':crit}
def main():
 out=HERE/'personal01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);names=a.groupby('horse_id').horse_name.last().to_dict();profiles=[];resids=[];summaries=[];discovery_models=[]
 for snapshot,cutoff in [('2024_fixed','2023-12-30'),('2026_updated','2025-12-30')]:
  p,r,s,m=discovery(a,cutoff,snapshot,names);profiles.append(p);resids.append(r);summaries.append(s);discovery_models.append(m);print('Personal candidate snapshot',snapshot,p.status.value_counts().to_dict(),flush=True)
 profiles=pd.concat(profiles,ignore_index=True);profiles.to_csv(out/'profiles.csv',index=False,encoding='utf-8-sig');pd.concat(resids).to_csv(out/'discovery_residuals.csv',index=False,encoding='utf-8-sig');pd.concat(summaries).to_csv(out/'discovery_group_means.csv',index=False,encoding='utf-8-sig');save(out/'discovery_models.json',discovery_models)
 rows=[];models=[];pooled_rows=[];pooled_models=[]
 for snapshot,period in [('2024_fixed','2024_2025'),('2024_fixed','2026'),('2026_updated','2026')]:
  p=profiles[profiles.snapshot.eq(snapshot)&profiles.status.eq('historical_candidate_only')];mapping=p.set_index('horse_id').best_gap_group.to_dict();z=a[a.year.between(2024,2025)] if period=='2024_2025' else a[a.year.eq(2026)];z=z[z.gap_group.notna()&z.H1_time_adv.notna()&z.horse_id.isin(mapping)].copy();z['preferred']=z.preference_gap_group.eq(z.horse_id.map(mapping))
  for horse,g in z.groupby('horse_id'):
   r,m=individual(g,period,snapshot,horse,names[horse],mapping[horse]);rows.append(r)
   if m:models.append(m)
  if snapshot=='2024_fixed':
   r,m=pooled(z,period);pooled_rows.append(r)
   if m:pooled_models.append(m)
 r=pd.DataFrame(rows);r['BH_q']=np.nan
 for snapshot in ['2024_fixed','2026_updated']:
  mask=r.snapshot.eq(snapshot)&r.status.eq('fitted')
  if mask.any():r.loc[mask,'BH_q']=bh(r.loc[mask,'date_p'])
 r['positive_supported']=r.status.eq('fitted')&r.BH_q.lt(.05)&r.date_low.gt(0)
 r.to_csv(out/'individual_validation.csv',index=False,encoding='utf-8-sig');save(out/'individual_models.json',models)
 p=pd.DataFrame(pooled_rows);p['BH_q']=np.nan;mask=p.status.eq('fitted')
 if mask.any():p.loc[mask,'BH_q']=bh(p.loc[mask,'date_p'])
 p['positive_supported']=p.status.eq('fitted')&p.BH_q.lt(.05)&p.date_low.gt(0)&p.horse_low.gt(0);p.to_csv(out/'pooled_validation.csv',index=False,encoding='utf-8-sig');save(out/'pooled_models.json',pooled_models)
 repeats=[]
 for horse,g in r[r.snapshot.eq('2024_fixed')].groupby('horse_id'):
  repeats.append({'horse_id':horse,'horse_name':names[horse],'periods_observed':len(g),'periods_fitted':int(g.status.eq('fitted').sum()),'repeated_positive_supported':len(g)==2 and bool(g.positive_supported.all()),'preferred_gap_group':g.preferred_gap_group.iloc[0]})
 pd.DataFrame(repeats).to_csv(out/'repeat_checks.csv',index=False,encoding='utf-8-sig')
 print('Individual fits',r[r.status.eq('fitted')].groupby(['snapshot','period']).size().to_dict(),'positive',r.positive_supported.sum(),'repeat',sum(v['repeated_positive_supported'] for v in repeats),flush=True);print(p.to_string(index=False),flush=True)
if __name__=='__main__':main()
