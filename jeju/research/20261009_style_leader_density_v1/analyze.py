"""Raw conditional rates and cluster-robust explanatory logistic comparisons."""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from scipy.linalg import qr
from math import erfc,sqrt
from features import HERE,ROOT,sha,save
B=4000;SEED=20261009
STYLES=['lead','front','closing']
def ci(x):
 x=x[np.isfinite(x)];return np.quantile(x,[.025,.975]).tolist() if len(x) else [None,None]
def bootstrap(g,key,masks):
 if not len(g):return np.full((B,len(masks)),np.nan)
 keys=g[key].unique();num=np.zeros((len(keys),len(masks)));den=num.copy()
 for j,mask in enumerate(masks):
  z=g.loc[mask].groupby(key).top3.agg(['sum','count']).reindex(keys,fill_value=0)
  num[:,j]=z['sum'];den[:,j]=z['count']
 rng=np.random.default_rng(SEED);r=[]
 for start in range(0,B,200):
  w=rng.multinomial(len(keys),np.full(len(keys),1/len(keys)),size=min(200,B-start));d=w@den
  r.append(np.divide(w@num,d,out=np.full_like(d,np.nan),where=d>0))
 return np.concatenate(r)
def views(a,years=False):
 yield 'all','all',a
 yield 'period','2024_2025',a[a.year.isin([2024,2025])]
 yield 'period','2026',a[a.year.eq(2026)]
 if years:
  for year,g in a.groupby('year'):yield 'year',str(year),g
 for dist,g in a.groupby('race_distance_m'):yield 'distance',str(dist),g

def stats(g,masks,labels,base):
 bd=bootstrap(g,'race_date',masks);bh=bootstrap(g,'horse_id',masks);out=[]
 for j,(label,mask) in enumerate(zip(labels,masks)):
  z=g[mask];n=len(z)
  out.append({**base,'group':label,'starts':n,'top3':int(z.top3.sum()),'rate':float(z.top3.mean()) if n else None,
   'date_low':ci(bd[:,j])[0],'date_high':ci(bd[:,j])[1],'horse_low':ci(bh[:,j])[0],'horse_high':ci(bh[:,j])[1],
   'horses':z.horse_id.nunique(),'races':z.race_id.nunique(),'days':z.race_date.nunique(),
   'first_date':z.race_date.min() if n else None,'last_date':z.race_date.max() if n else None,
   'field_min':int(z.field_n.min()) if n else None,'field_max':int(z.field_n.max()) if n else None,
   'low_support':bool(n<100 or z.race_id.nunique()<30 or z.race_date.nunique()<20)})
 return out,bd,bh
NUM=['exposure','field_n','gate_scaled','moisture','carried_weight_kg','coverage',
 'h_any_finish_rank_mean','h_any_relative_time_mean','h_same_finish_rank_mean','h_same_relative_time_mean',
 'h_any_s1ftime_mean','h_any_g3ftime_mean','h_any_g1ftime_mean','h_any_n','h_same_n','h_any_gap_days',
 'opp_rank_mean','opp_time_mean']
CAT=['race_distance_m','year','month','class_clean']
def design(g):
 raw=g[NUM].copy();med=raw.median();raw=raw.fillna(med).fillna(0)
 for c in NUM:
  if g[c].isna().any():raw[c+'_missing']=g[c].isna().astype(float)
 raw=pd.concat([raw,pd.get_dummies(g[CAT].astype(str),drop_first=True,dtype=float)],axis=1)
 scale=raw.std(ddof=0);kept=scale[scale>1e-10].index.tolist()
 raw=raw[kept];mean=raw.mean();scale=scale[kept]
 z=(raw-mean)/scale;z.insert(0,'intercept',1.)
 _,r,pivot=qr(z.to_numpy(),mode='economic',pivoting=True)
 rank=np.sum(np.abs(np.diag(r))>1e-9);use=sorted(pivot[:rank]);z=z.iloc[:,use]
 assert 'exposure' in z
 return z,{'numeric_medians':{k:float(v) if pd.notna(v) else 0. for k,v in med.items()},
  'raw_kept_columns':kept,'mean':mean.to_dict(),'scale':scale.to_dict(),'model_columns':z.columns.tolist(),
  'collinear_columns_dropped':[c for c in ['intercept']+kept if c not in z.columns]}
def covariance(X,y,p,g,key):
 h=X.T@((p*(1-p))[:,None]*X);bread=np.linalg.pinv(h,rcond=1e-12)
 score=X*(y-p)[:,None];codes,unique=pd.factorize(g[key]);s=np.zeros((len(unique),X.shape[1]));np.add.at(s,codes,score)
 correction=len(unique)/(len(unique)-1)*(len(y)-1)/(len(y)-X.shape[1])
 return bread@(s.T@s)@bread*correction

def fit(g,base):
 if len(g)<100 or min(g.top3.sum(),len(g)-g.top3.sum())<10 or g.exposure.nunique()<2:return None,None,None
 z,params=design(g);X=z.to_numpy();y=g.top3.to_numpy(dtype=float)
 def loss(beta):
  v=X@beta;return float(np.logaddexp(0,v).sum()-y@v),X.T@(expit(v)-y)
 opt=minimize(loss,np.zeros(X.shape[1]),jac=True,method='L-BFGS-B',options={'maxiter':3000,'ftol':1e-13,'gtol':1e-7,'maxls':50})
 scoremax=float(np.abs(loss(opt.x)[1]).max());assert scoremax<.005,(base,opt.message,scoremax)
 beta=opt.x;p=expit(X@beta);j=z.columns.get_loc('exposure');sd=params['scale']['exposure']
 vd=covariance(X,y,p,g,'race_date');vh=covariance(X,y,p,g,'horse_id')
 # Increment only records below the maximum observed count in this subset.
 mask=g.exposure.to_numpy()<g.exposure.max();x0=X[mask];x1=x0.copy();x1[:,j]+=1/sd
 p0=p[mask];p1=expit(x1@beta);effect=float(100*np.mean(p1-p0))
 grad=100*np.mean(p1[:,None]*(1-p1[:,None])*x1-p0[:,None]*(1-p0[:,None])*x0,axis=0)
 out={**base,'starts':len(g),'races':g.race_id.nunique(),'horses':g.horse_id.nunique(),'days':g.race_date.nunique(),
      'parameters':X.shape[1],'score_max_abs':scoremax,'converged':bool(opt.success),'marginal_delta_pp':effect,'increment_support_starts':int(mask.sum()),
      'odds_ratio_per_leader':float(np.exp(beta[j]/sd)),'beta_per_leader':float(beta[j]/sd)}
 for name,v in [('date',vd),('horse',vh)]:
  se=sqrt(max(0,float(grad@v@grad)));bse=sqrt(max(0,float(v[j,j])))/sd
  out.update({name+'_low_pp':effect-1.96*se,name+'_high_pp':effect+1.96*se,
   name+'_OR_low':float(np.exp(beta[j]/sd-1.96*bse)),name+'_OR_high':float(np.exp(beta[j]/sd+1.96*bse)),
   name+'_p':erfc(abs(effect/se)/sqrt(2)) if se else 1.})
 params.update(base);params['beta']=beta.tolist();params['covariance_date']=vd.tolist();params['covariance_horse']=vh.tolist()
 pred=g[['api_record_id','race_id','race_date','horse_id','top3','exposure']].copy()
 for k,v in base.items():pred[k]=v
 pred['p']=p;pred['p_plus1']=np.nan;pred.loc[mask,'p_plus1']=p1
 return out,params,pred

def main():
 out=HERE/'run02';out.mkdir(exist_ok=False)
 a=pd.read_csv(HERE/'features01/start_features.csv',dtype={'horse_id':str},low_memory=False)
 actual=[];strict=[];crowd=[];diffs=[];models=[];params=[];predictions=[];coverage=[]
 for scope in ['any','same']:
  for sty in STYLES:
   for view,key,g in views(a[a['style_'+scope].eq(sty)]):
    if g.empty:continue
    base={'scope':scope,'style':sty,'view':view,'key':key}
    masks=[g.y_s1f_pack3.eq(j) for j in [0,1,2]]+[g.y_s1f_pack3.isna()]
    r,_,_=stats(g,masks,['first','second','farther','unknown'],base);actual+=r
    masks=[g.y_s1f_position4.eq(j) for j in [0,1,2,3]]+[g.y_s1f_position4.isna()]
    r,_,_=stats(g,masks,['definite_lead','definite_front','middle','rear','ambiguous'],base);strict+=r
 configs=[('any80','any','any',.8),('any100','any','any',1.),('same80','same','same',.8),('closing40_any80','any40','any',.8)]
 for name,stycol,scope,cov in configs:
  eligible=a[a['coverage_'+scope].ge(cov-1e-12)].copy();eligible['exposure']=eligible['leaders_'+scope];eligible['coverage']=eligible['coverage_'+scope]
  coverage.append({'configuration':name,'source_starts':len(a),'eligible_starts':len(eligible),'eligible_races':eligible.race_id.nunique(),
   'unknown_starts':int(eligible['style_'+stycol].eq('unknown').sum()),'first_date':eligible.race_date.min(),'last_date':eligible.race_date.max()})
  for sty in STYLES:
   if name=='closing40_any80' and sty!='closing':continue
   subset=eligible[eligible['style_'+stycol].eq(sty)]
   for view,key,g in views(subset,years=name=='any80'):
    if g.empty or (name!='any80' and view not in ['all','period']):continue
    base={'configuration':name,'style':sty,'view':view,'key':key}
    masks=[g.exposure.eq(0),g.exposure.eq(1),g.exposure.eq(2),g.exposure.ge(3),g.exposure.ge(2)]
    r,bd,bh=stats(g,masks,['0','1','2','3plus','2plus'],base);crowd+=r
    if sty!='lead':
     z=g[g.exposure.eq(0)];h=g[g.exposure.ge(2)]
     diffs.append({**base,'contrast':'2plus_minus_0','raw_delta_pp':float(100*(h.top3.mean()-z.top3.mean())) if len(z) and len(h) else None,
      'date_low_pp':ci(100*(bd[:,4]-bd[:,0]))[0],'date_high_pp':ci(100*(bd[:,4]-bd[:,0]))[1],
      'horse_low_pp':ci(100*(bh[:,4]-bh[:,0]))[0],'horse_high_pp':ci(100*(bh[:,4]-bh[:,0]))[1]})
    if view in ['all','period']:
     m,pa,pr=fit(g,base)
     if m:
      m['fit_status']='estimated';models.append(m);params.append(pa);predictions.append(pr)
     else:
      models.append({**base,'starts':len(g),'races':g.race_id.nunique(),'fit_status':'insufficient_frozen_support','date_p':1.})
   print(name,sty,len(subset),'starts',flush=True)
 model=pd.DataFrame(models);model['primary_BH_q']=np.nan
 fam=model[(model.configuration=='any80')&model['style'].isin(['front','closing'])].sort_values('date_p')
 assert len(fam)==6
 q=np.minimum.accumulate((fam.date_p.to_numpy()*6/np.arange(1,7))[::-1])[::-1]
 model.loc[fam.index,'primary_BH_q']=np.minimum(q,1)
 for name,rows in [('actual_pack_rates',actual),('actual_strict_rates',strict),('crowd_rates',crowd),('raw_contrasts',diffs),('coverage',coverage)]:pd.DataFrame(rows).to_csv(out/(name+'.csv'),index=False,encoding='utf-8-sig')
 model.to_csv(out/'adjusted_effects.csv',index=False,encoding='utf-8-sig');save(out/'model_parameters.json',params)
 pd.concat(predictions,ignore_index=True).to_csv(out/'model_predictions.csv',index=False,encoding='utf-8-sig')
 print(model[model.configuration.eq('any80')][['style','view','key','starts','marginal_delta_pp','date_low_pp','date_high_pp','horse_low_pp','horse_high_pp','primary_BH_q']].to_string(index=False),flush=True)
 save(out/'receipt.json',{'status':'completed_pending_verification','bootstrap_draws':B,'models':len(params),'primary_BH_family_size':6,'source_sha256':sha(HERE/'features01/start_features.csv')})
if __name__=='__main__':main()
