"""Post-primary small-sample exploration; no confirmed-optimum labels."""
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,IDS,save
from analysis import cluster,bh
def individual_small(g,period,snapshot,horse,name,preferred):
 tr=g.preference_gap_group.eq(preferred);meta={'period':period,'snapshot':snapshot,'horse_id':horse,'horse_name':name,'preferred_gap_group':preferred,'starts':len(g),'matched':int(tr.sum()),'other':int((~tr).sum()),'days':g.race_date.nunique()}
 if len(g)<10 or min(tr.sum(),(~tr).sum())<3 or g.race_date.nunique()<8:return {**meta,'status':'insufficient_future_support'},None
 X=pd.concat([pd.DataFrame({'intercept':1.,'preferred':tr.astype(float)},index=g.index),pd.get_dummies(g[['race_distance_m','year']].astype(str),drop_first=True,dtype=float)],axis=1).to_numpy();rank=np.linalg.matrix_rank(X,tol=1e-8);df=len(g)-rank;N=np.delete(X,1,axis=1);ident=np.linalg.norm(X[:,1]-N@np.linalg.lstsq(N,X[:,1],rcond=1e-12)[0])
 if df<=3 or ident<1e-6:return {**meta,'status':'unidentified_or_insufficient_df','df':int(df)},None
 y=g.H1_time_adv.to_numpy();beta=np.linalg.lstsq(X,y,rcond=1e-12)[0];bread=np.linalg.pinv(X.T@X,rcond=1e-12);res=y-X@beta;dc=cluster(X,res,bread,g.race_date,df);sd=np.sqrt(max(0,dc[1,1]));crit=float(t.ppf(.975,g.race_date.nunique()-1));point=float(beta[1]);row={**meta,'status':'fitted','effect':point,'date_low':point-crit*sd,'date_high':point+crit*sd,'date_p':float(2*t.sf(abs(point/sd),g.race_date.nunique()-1)) if sd else 1.,'residual_df':int(df),'raw_matched_H1_adv':g.loc[tr,'H1_time_adv'].mean(),'raw_other_H1_adv':g.loc[~tr,'H1_time_adv'].mean(),'units':'seconds_faster_than_H1_expectation'}
 return row,{**meta,'row_ids':g.api_record_id.astype(int).tolist(),'columns':X.shape[1],'beta':beta.tolist(),'date_cov':dc.tolist(),'residual_df':int(df),'crit':crit}
def main():
 out=HERE/'small_sample01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);profiles=pd.read_csv(HERE/'personal01/profiles.csv',dtype={'horse_id':str});names=a.groupby('horse_id').horse_name.last().to_dict();rows=[];models=[]
 for snapshot,period in [('2024_fixed','2024_2025'),('2024_fixed','2026'),('2026_updated','2026')]:
  p=profiles[profiles.snapshot.eq(snapshot)&profiles.status.eq('historical_candidate_only')];mapping=p.set_index('horse_id').best_gap_group.to_dict();z=a[a.year.between(2024,2025)] if period=='2024_2025' else a[a.year.eq(2026)];z=z[z.gap_group.notna()&z.H1_time_adv.notna()&z.horse_id.isin(mapping)]
  for horse,g in z.groupby('horse_id'):
   r,m=individual_small(g,period,snapshot,horse,names[horse],mapping[horse]);rows.append(r)
   if m:models.append(m)
 r=pd.DataFrame(rows);r['BH_q']=np.nan
 for snapshot in ['2024_fixed','2026_updated']:
  mask=r.snapshot.eq(snapshot)&r.status.eq('fitted')
  if mask.any():r.loc[mask,'BH_q']=bh(r.loc[mask,'date_p'])
 r['exploratory_positive_supported']=r.status.eq('fitted')&r.BH_q.lt(.05)&r.date_low.gt(0);r.to_csv(out/'individual_validation.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models)
 print('Exploratory small-sample fits',r[r.status.eq('fitted')].groupby(['snapshot','period']).size().to_dict(),'positive',int(r.exploratory_positive_supported.sum()),flush=True)
 print(r[r.exploratory_positive_supported][['snapshot','period','horse_id','horse_name','preferred_gap_group','starts','matched','other','effect','date_low','date_high','BH_q']].to_string(index=False),flush=True)
if __name__=='__main__':main()
