"""Exploratory within-race relative style association, after primary raw results."""
import numpy as np
import pandas as pd
from scipy.linalg import qr
from math import sqrt,erfc
from features import HERE,save
from analyze import NUM,design

def main():
 out=HERE/'relative01';out.mkdir(exist_ok=False)
 a=pd.read_csv(HERE/'features01/start_features.csv',dtype={'horse_id':str},low_memory=False)
 a=a[a.coverage_any.ge(.8-1e-12)&a.style_any.isin(['lead','front','closing'])].copy()
 effects=[];params=[];resids=[]
 for period,g in [('all',a),('2024_2025',a[a.year.isin([2024,2025])]),('2026',a[a.year.eq(2026)])]:
  g=g.copy();g['exposure']=g.leaders_any;g['coverage']=g.coverage_any
  x,dp=design(g);x=x[[c for c in x if c in NUM and c not in ['exposure','field_n','moisture','coverage'] or c.endswith('_missing')]].copy()
  for sty in ['front','closing']:
   x['style_'+sty]=g.style_any.eq(sty).astype(float);x['interaction_'+sty]=g.style_any.eq(sty)*g.leaders_any
  x=x-x.groupby(g.race_id).transform('mean');y=g.top3-g.groupby('race_id').top3.transform('mean')
  _,r,pivot=qr(x.to_numpy(),mode='economic',pivoting=True);rank=np.sum(np.abs(np.diag(r))>1e-9);x=x.iloc[:,sorted(pivot[:rank])]
  X=x.to_numpy();beta=np.linalg.lstsq(X,y.to_numpy(),rcond=1e-12)[0];resid=y.to_numpy()-X@beta;bread=np.linalg.pinv(X.T@X,rcond=1e-12)
  covs={}
  for name,key in [('date','race_date'),('horse','horse_id')]:
   codes,unique=pd.factorize(g[key]);scores=np.zeros((len(unique),len(beta)));np.add.at(scores,codes,X*resid[:,None])
   factor=len(unique)/(len(unique)-1)*(len(g)-1)/(len(g)-g.race_id.nunique()-rank)
   covs[name]=bread@(scores.T@scores)@bread*factor
  for sty in ['front','closing']:
   j=x.columns.get_loc('interaction_'+sty);value=100*beta[j];rec={'period':period,'contrast':sty+'_minus_lead','starts':len(g),'races':g.race_id.nunique(),'style_starts':int(g.style_any.eq(sty).sum()),'relative_delta_pp_per_leader':value,'low_support':bool(g.style_any.eq(sty).sum()<100)}
   for name,c in covs.items():
    se=100*sqrt(max(0,c[j,j]));rec.update({name+'_low_pp':value-1.96*se,name+'_high_pp':value+1.96*se,name+'_p':erfc(abs(value/se)/sqrt(2)) if se else 1.})
   effects.append(rec)
  params.append({'period':period,'columns':x.columns.tolist(),'beta':beta.tolist(),'design':dp,'normal_equation_max_abs':float(np.abs(X.T@resid).max()),'covariance_date':covs['date'].tolist(),'covariance_horse':covs['horse'].tolist()})
  z=g[['api_record_id','race_id','race_date','horse_id','top3','leaders_any','style_any']].copy();z['period']=period;z['demeaned_outcome']=y;z['demeaned_fit']=X@beta;z['residual']=resid;resids.append(z)
 r=pd.DataFrame(effects);ix=r.sort_values('date_p').index;q=np.minimum.accumulate((r.loc[ix,'date_p'].to_numpy()*6/np.arange(1,7))[::-1])[::-1];r.loc[ix,'exploratory_BH_q']=np.minimum(q,1)
 r.to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');save(out/'parameters.json',params);pd.concat(resids,ignore_index=True).to_csv(out/'residuals.csv',index=False,encoding='utf-8-sig');print(r.to_string(index=False))
if __name__=='__main__':main()
