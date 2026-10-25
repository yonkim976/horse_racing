"""Fixed, prespecified comparisons of confirmed jockey training participation."""
import json
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu
from scipy.stats import t
from data import HERE,BASE,IDS,periods,save
TARGETS=['relative_time','rank10_quality','top3_pp']
VARIANTS=['primary','window7','window28','no_quantity','positive_expanded']
COMPARISONS=['any_vs_nonjockey','same_vs_otherjockey']
def bh(p):
 p=np.asarray(p,float);ix=np.argsort(p);r=np.empty(len(p));r[ix]=np.minimum(1,np.minimum.accumulate((p[ix]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1]);return r
def sample(a,f,variant,comparison):
 w=7 if variant=='window7' else 28 if variant=='window28' else 14
 g=a.merge(f[f.window_days.eq(w)],on='api_record_id',validate='one_to_one')
 if comparison=='any_vs_nonjockey':
  keep=g.role_complete|(g.any_jockey if variant=='positive_expanded' else False);g=g[keep].copy();g['exposed']=g.any_jockey.astype(float)
 else:
  keep=(g.identity_complete&g.any_jockey)|(g.same_jockey if variant=='positive_expanded' else False);g=g[keep].copy();g['exposed']=g.same_jockey.astype(float)
 g['log_gap']=np.log1p(g.gap_days);g['log_training_days']=np.log1p(g.training_days);g['log_training_minutes']=np.log1p(g.training_minutes)
 return g.reset_index(drop=True)
def projection(g):
 r,rv=pd.factorize(g.race_id,sort=True);h,hv=pd.factorize(g.horse_distance,sort=True);nr,nh=len(rv),len(hv);rows=np.arange(len(g));graph=coo_matrix((np.ones(2*len(g)),(np.r_[r,nr+h],np.r_[nr+h,r])),shape=(nr+nh,nr+nh)).tocsr();C,lab=connected_components(graph,directed=False);anchor=pd.Series(np.arange(nh)).groupby(lab[nr:]).min().to_numpy();keep=np.ones(nh,bool);keep[anchor]=False;mp=np.full(nh,-1);mp[keep]=nr+np.arange(keep.sum());ok=keep[h];Z=coo_matrix((np.ones(len(g)+ok.sum()),(np.r_[rows,rows[ok]],np.r_[r,mp[h[ok]]])),shape=(len(g),nr+nh-C)).tocsc()
 return Z,splu((Z.T@Z).tocsc()),{'rank':Z.shape[1],'components':C,'races':nr,'units':nh,'unit':'horse_distance'}
def design(g,variant):
 cols=BASE+([] if variant=='no_quantity' else ['log_training_days','log_training_minutes','duration_missing_rows'])
 raw=g[cols].copy();med=raw.median().fillna(0);n=raw.fillna(med)
 for col in cols:
  if raw[col].isna().any():n[col+'_missing']=raw[col].isna().astype(float)
 n=pd.concat([n,pd.get_dummies(g.jockey_id,prefix='jockey',drop_first=True,dtype=float),pd.get_dummies(g.trainer_id,prefix='trainer',drop_first=True,dtype=float)],axis=1);sd=n.std(ddof=0);n=n.loc[:,sd.gt(1e-12)];mu=n.mean();sd=n.std(ddof=0);n=(n-mu)/sd
 X=pd.concat([g[['exposed']],n],axis=1)
 return X,{'columns':X.columns.tolist(),'num_columns':cols,'medians':med.to_dict(),'means':mu.to_dict(),'sd':sd.to_dict()}
def cluster(x,res,bread,key,df):
 codes,ids=pd.factorize(key);s=np.zeros((len(ids),x.shape[1]));np.add.at(s,codes,x*res[:,None]);return bread@s.T@s@bread*(len(ids)/(len(ids)-1)*(len(x)-1)/df)
def support_meta(g):
 q=g[g.exposed.eq(1)];r=g[g.exposed.eq(0)];both=set(q.horse_distance)&set(r.horse_distance);cross=g[g.horse_distance.isin(both)].horse_id.nunique()
 m={'rows':len(g),'horses':g.horse_id.nunique(),'races':g.race_id.nunique(),'days':g.race_date.nunique(),'positive_starts':len(q),'negative_starts':len(r),'positive_horses':q.horse_id.nunique(),'negative_horses':r.horse_id.nunique(),'positive_days':q.race_date.nunique(),'negative_days':r.race_date.nunique(),'crossover_horses':cross,'first_date':g.race_date.min(),'last_date':g.race_date.max(),'field_min':int(g.field_n.min()),'field_max':int(g.field_n.max())}
 return m,len(q)>=100 and len(r)>=100 and m['positive_horses']>=30 and m['negative_horses']>=30 and m['positive_days']>=20 and m['negative_days']>=20 and cross>=20
def fit(g,period,variant,comparison):
 meta,support=support_meta(g);meta.update(period=period,variant=variant,comparison=comparison)
 if not support:return [],{**meta,'status':'insufficient_group_or_crossover_support'}
 frame,spec=design(g,variant);X=frame.to_numpy();targets=TARGETS+(['H1_time_adv'] if variant=='primary' and period!='all' else []);Y=g[targets].to_numpy();assert np.isfinite(Y).all()
 Z,lu,info=projection(g);V=np.column_stack([Y,X]);R=V-Z@lu.solve(np.asarray(Z.T@V));yr=R[:,:len(targets)];xr=R[:,len(targets):];N=xr[:,1:];d=xr[:,0];remaining=d-N@np.linalg.lstsq(N,d,rcond=1e-10)[0];df=len(g)-info['rank']-np.linalg.matrix_rank(xr,tol=1e-7)
 if np.linalg.norm(remaining)<1e-7 or df<=20:return [],{**meta,'status':'unidentified_or_insufficient_df','residual_df':int(df)}
 pen=np.r_[0.,np.ones(X.shape[1]-1)];bread=np.linalg.inv(xr.T@xr+np.diag(pen));beta=bread@xr.T@yr;crit=float(t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1));deg=min(g.race_date.nunique(),g.horse_id.nunique())-1;rows=[];models=[]
 for k,target in enumerate(targets):
  res=yr[:,k]-xr@beta[:,k];dc=cluster(xr,res,bread,g.race_date,df);hc=cluster(xr,res,bread,g.horse_id,df);sign=-1 if target=='relative_time' else 1;point=float(sign*beta[0,k]);sd=np.sqrt(max(0,dc[0,0]));sh=np.sqrt(max(0,hc[0,0]));rows.append({**meta,'target':target,'support':True,'effect':point,'date_low':point-crit*sd,'date_high':point+crit*sd,'horse_low':point-crit*sh,'horse_high':point+crit*sh,'date_p':float(2*t.sf(abs(point/sd),deg)) if sd else 1.,'units':'seconds_faster' if target in ['relative_time','H1_time_adv'] else '10runner_places_better' if target=='rank10_quality' else 'percentage_points','residual_df':int(df)})
  models.append({'target':target,'beta':beta[:,k].tolist(),'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'crit':crit})
 print('Training fitted',period,variant,comparison,len(g),flush=True)
 return rows,{**meta,'status':'fitted','row_ids':g.api_record_id.astype(int).tolist(),'spec':spec,'FE':info,'residual_df':int(df),'projection_orthogonality':float(np.abs(Z.T@R).max()),'models':models}
def ci(g,col):
 y=g[col].dropna();z=g.loc[y.index];v=y.mean();result={'mean':v,'n':len(y)}
 for label,key in [('date','race_date'),('horse','horse_id')]:
  sums=(y-v).groupby(z[key]).sum();G=len(sums);half=t.ppf(.975,G-1)*np.sqrt((sums*sums).sum()/len(y)**2*G/(G-1)) if G>1 else np.nan;result[label+'_low']=v-half;result[label+'_high']=v+half
 return result
def raw(g):
 r={'starts':len(g),'horses':g.horse_id.nunique(),'races':g.race_id.nunique(),'days':g.race_date.nunique(),'first_date':g.race_date.min(),'last_date':g.race_date.max(),'field_min':int(g.field_n.min()),'field_max':int(g.field_n.max()),'top3_count':int(g.top3.sum()),'win_count':int(g.finish_position.eq(1).sum()),'win_pct':100*g.finish_position.eq(1).mean(),'mean_training_days':g.training_days.mean(),'mean_training_minutes':g.training_minutes.mean(),'mean_prior_rank':g.h_any_finish_rank_mean.mean(),'mean_gap_days':g.gap_days.mean()}
 for col in ['finish_position','top3_pp','relative_time','rank10_quality','H1_time_adv']:
  if g[col].notna().any():r.update({col+'_'+k:v for k,v in ci(g,col).items()})
 return r
def main():
 out=HERE/'analysis01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);f=pd.read_csv(HERE/'input01/features.csv');rows=[];models=[];raws=[];coverage=[];dists=[]
 for period,z in periods(a).items():
  for variant in VARIANTS:
   for comp in COMPARISONS:
    g=sample(z,f,variant,comp)
    if variant=='primary':
     for label,v in g.groupby('exposed'):raws.append({'period':period,'comparison':comp,'exposed':int(label),**raw(v)})
     for (distance,label),v in g.groupby(['race_distance_m','exposed']):dists.append({'period':period,'comparison':comp,'distance':int(distance),'exposed':int(label),**raw(v)})
    r,m=fit(g,period,variant,comp);rows+=r;models.append(m)
  v=z.merge(f[f.window_days.eq(14)],on='api_record_id',validate='one_to_one');v['coverage_group']=np.where(v.training_rows.eq(0),'no_rows',np.where(v.role_complete,'role_complete','unknown_type_present'))
  for label,g in v.groupby('coverage_group'):coverage.append({'period':period,'coverage_group':label,**raw(g)})
 r=pd.DataFrame(rows);r['BH_q']=np.nan
 for ish1 in [False,True]:
  mask=r.variant.eq('primary')&(r.target.eq('H1_time_adv') if ish1 else r.target.ne('H1_time_adv'));r.loc[mask,'BH_q']=bh(r.loc[mask,'date_p'])
 r['direction_supported']=r.variant.eq('primary')&r.BH_q.lt(.05)&((r.date_low.gt(0)&r.horse_low.gt(0))|(r.date_high.lt(0)&r.horse_high.lt(0)));r.to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models)
 for name,data in [('raw_primary.csv',raws),('raw_distance.csv',dists),('raw_coverage.csv',coverage)]:pd.DataFrame(data).to_csv(out/name,index=False,encoding='utf-8-sig')
 repeat=[]
 for (comp,target),g in r[r.variant.eq('primary')&r.period.ne('all')].groupby(['comparison','target']):repeat.append({'comparison':comp,'target':target,'supported_periods_available':len(g),'repeated_supported':len(g)==2 and bool(g.direction_supported.all()) and bool(g.effect.gt(0).all() or g.effect.lt(0).all())})
 pd.DataFrame(repeat).to_csv(out/'repeat_checks.csv',index=False,encoding='utf-8-sig')
 print(r[r.variant.eq('primary')][['period','comparison','target','positive_starts','negative_starts','effect','date_low','date_high','horse_low','horse_high','BH_q','direction_supported']].to_string(index=False),flush=True)
if __name__=='__main__':main()
