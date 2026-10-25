"""Sensitivity to the rich historical controls in exploratory within-race results."""
import pandas as pd
import numpy as np
from scipy.linalg import qr
from math import sqrt
from features import HERE,save
from analyze import bootstrap,ci

def main():
 out=HERE/'relative02';out.mkdir(exist_ok=False)
 a=pd.read_csv(HERE/'features01/start_features.csv',dtype={'horse_id':str},low_memory=False);a=a[a.coverage_any.ge(.8-1e-12)&a.style_any.isin(['lead','front','closing'])].copy();results=[];pairs=[];summaries=[]
 for period,g in [('all',a),('2024_2025',a[a.year.isin([2024,2025])]),('2026',a[a.year.eq(2026)])]:
  x=g[['gate_scaled','carried_weight_kg']].copy();x=x.fillna(x.median())
  for sty in ['front','closing']:
   x['style_'+sty]=g.style_any.eq(sty).astype(float);x['interaction_'+sty]=g.style_any.eq(sty)*g.leaders_any
  x=x-x.groupby(g.race_id).transform('mean');y=g.top3-g.groupby('race_id').top3.transform('mean')
  X=x.to_numpy();beta=np.linalg.lstsq(X,y.to_numpy(),rcond=1e-12)[0];res=y-X@beta;bread=np.linalg.pinv(X.T@X,rcond=1e-12)
  covs={}
  for name,key in [('date','race_date'),('horse','horse_id')]:
   codes,unique=pd.factorize(g[key]);score=np.zeros((len(unique),len(beta)));np.add.at(score,codes,X*res.to_numpy()[:,None]);factor=len(unique)/(len(unique)-1)*(len(g)-1)/(len(g)-g.race_id.nunique()-X.shape[1]);covs[name]=bread@(score.T@score)@bread*factor
  for sty in ['front','closing']:
   j=x.columns.get_loc('interaction_'+sty);rec={'period':period,'contrast':sty+'_minus_lead','relative_delta_pp_per_leader':100*beta[j]}
   for name,v in covs.items():
    se=100*sqrt(max(0,v[j,j]));rec[name+'_low_pp']=100*beta[j]-1.96*se;rec[name+'_high_pp']=100*beta[j]+1.96*se
   results.append(rec)
  # Race-equal raw front minus lead success differences in co-occurring races.
  q=g.groupby(['race_id','race_date','leaders_any','style_any']).top3.mean().unstack('style_any').reset_index();q=q[q['lead'].notna()&q['front'].notna()].copy();q['delta']=q['front']-q['lead'];q['period']=period;pairs.append(q)
  for label,mask in [('1',q.leaders_any.eq(1)),('2',q.leaders_any.eq(2)),('3plus',q.leaders_any.ge(3))]:
   z=q[mask];summaries.append({'period':period,'leaders':label,'paired_races':len(z),'race_mean_front_minus_lead_pp':100*z.delta.mean() if len(z) else None})
 pd.DataFrame(results).to_csv(out/'minimal_adjustment.csv',index=False,encoding='utf-8-sig');pd.DataFrame(summaries).to_csv(out/'paired_raw_summary.csv',index=False,encoding='utf-8-sig');pd.concat(pairs,ignore_index=True).to_csv(out/'paired_races.csv',index=False,encoding='utf-8-sig');print(pd.DataFrame(results).to_string(index=False));print(pd.DataFrame(summaries).to_string(index=False))
if __name__=='__main__':main()
