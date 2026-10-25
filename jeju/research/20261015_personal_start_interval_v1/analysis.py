"""Personal departures from rolling usual cycles, beyond absolute interval groups."""
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix,bmat,csc_matrix,diags
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu,spsolve
from scipy.stats import t
from data import HERE,BASE,NUM,IDS,BINS,GROUPS,REF,ABS_GROUPS,period_data,save
TARGETS=['relative_time','rank10_quality','top3_pp']
def bh(p):
 p=np.asarray(p,float);ix=np.argsort(p);r=np.empty(len(p));r[ix]=np.minimum(1,np.minimum.accumulate((p[ix]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1]);return r
def mean_interval(g,col):
 z=g[g[col].notna()];v=z[col];r={'n':len(z),'mean':v.mean() if len(z) else None}
 for label,key in [('date','race_date'),('horse','horse_id')]:
  score=(v-v.mean()).groupby(z[key]).sum();G=len(score)
  half=t.ppf(.975,G-1)*np.sqrt((score**2).sum()/len(z)**2*G/(G-1)) if G>1 else None
  r[label+'_low']=v.mean()-half if half is not None else None;r[label+'_high']=v.mean()+half if half is not None else None
 return r
def raw_summary(g):
 r={'starts':len(g),'horses':g.horse_id.nunique(),'races':g.race_id.nunique(),'days':g.race_date.nunique(),'first_date':g.race_date.min(),'last_date':g.race_date.max(),'field_min':g.field_n.min(),'field_max':g.field_n.max(),'mean_gap_days':g.gap_days.mean(),'median_gap_days':g.gap_days.median(),'top3_count':int(g.top3.sum()),'win_pct':100*g.finish_position.eq(1).mean(),'same_previous_distance_pct':100*g.same_previous_distance.mean(),'small_sample':len(g)<100 or g.horse_id.nunique()<30 or g.race_date.nunique()<20,'prior_history_rank_mean':g.h_any_finish_rank_mean.mean()}
 for col in ['top3_pp','finish_position','rank10_quality','relative_time','rank_gain','rank10_gain']:
  r.update({col+'_'+k:v for k,v in mean_interval(g,col).items()})
 return r
def raw_tables(a,out):
 rows=[];dist=[];year=[];distribution=[]
 for period,g in period_data(a).items():
  distribution.append({'period':period,'known_intervals':len(g),'horses':g.horse_id.nunique(),'mean_days':g.gap_days.mean(),'p25_days':g.gap_days.quantile(.25),'median_days':g.gap_days.median(),'p75_days':g.gap_days.quantile(.75),'p90_days':g.gap_days.quantile(.9),'p95_days':g.gap_days.quantile(.95)})
  for label,z in g.groupby('gap_bin'):rows.append({'period':period,'gap_bin':label,**raw_summary(z)})
  for (d,label),z in g.groupby(['race_distance_m','gap_bin']):dist.append({'period':period,'distance':d,'gap_bin':label,**raw_summary(z)})
 for (y,label),z in a.groupby(['year','gap_bin']):year.append({'year':y,'gap_bin':label,**raw_summary(z)})
 for name,data in [('raw_by_period.csv',rows),('raw_by_distance.csv',dist),('raw_by_year.csv',year),('interval_distribution.csv',distribution)]:pd.DataFrame(data).to_csv(out/name,index=False,encoding='utf-8-sig')
def project(g,unit):
 r,rv=pd.factorize(g.race_id,sort=True);h,hv=pd.factorize(g[unit],sort=True);nr,nh=len(rv),len(hv);rows=np.arange(len(g))
 graph=coo_matrix((np.ones(2*len(g)),(np.r_[r,nr+h],np.r_[nr+h,r])),shape=(nr+nh,nr+nh)).tocsr();components,labels=connected_components(graph,directed=False)
 anchors=pd.Series(np.arange(nh)).groupby(labels[nr:]).min().to_numpy();keep=np.ones(nh,bool);keep[anchors]=False;mapping=np.full(nh,-1);mapping[keep]=np.arange(keep.sum())+nr;mask=keep[h]
 Z=coo_matrix((np.ones(len(g)+mask.sum()),(np.r_[rows,rows[mask]],np.r_[r,mapping[h[mask]]])),shape=(len(g),nr+nh-components)).tocsc();lu=splu((Z.T@Z).tocsc())
 return Z,lu,{'rank':Z.shape[1],'components':components,'unit':unit,'units':nh,'races':nr}
def conditions(g,include_absolute=True,gap_free=False):
 cols=BASE if gap_free else NUM
 n=g[cols].copy();med=n.median().fillna(0);missing=n.isna();n=n.fillna(med)
 for c in cols:
  if missing[c].any():n[c+'_missing']=missing[c].astype(float)
 n=pd.concat([n,pd.get_dummies(g.jockey_id,prefix='jockey',drop_first=True,dtype=float),pd.get_dummies(g.trainer_id,prefix='trainer',drop_first=True,dtype=float)],axis=1)
 if include_absolute and not gap_free:
  for label in ABS_GROUPS:
   if label!='15_28' and g.absolute_gap_group.eq(label).any():n['absolute='+label]=g.absolute_gap_group.eq(label).astype(float)
 sd=n.std(ddof=0);n=n.loc[:,sd.gt(1e-12)];mu=n.mean();sd=n.std(ddof=0);n=(n-mu)/sd
 return n,{'num_columns':cols,'medians':med.to_dict(),'means':mu.to_dict(),'sd':sd.to_dict(),'absolute_gap_adjusted':include_absolute and not gap_free}
def design(g,variant):
 groups=[c for c in GROUPS if c!=REF and g.gap_group.eq(c).any()];D=pd.DataFrame({'interval='+c:g.gap_group.eq(c).astype(float) for c in groups},index=g.index)
 n,spec=conditions(g,include_absolute=variant!='without_absolute');X=pd.concat([D,n],axis=1)
 return X,{'columns':X.columns.tolist(),'groups':groups,'reference':REF,**spec}
def cluster(X,res,bread,key,df):
 codes,ids=pd.factorize(key);score=np.zeros((len(ids),X.shape[1]));np.add.at(score,codes,X*res[:,None]);return bread@score.T@score@bread*(len(ids)/(len(ids)-1)*(len(X)-1)/df)
def fit(g,period,distance,variant):
 meta={'period':period,'distance':distance,'variant':variant,'rows':len(g),'horses':g.horse_id.nunique(),'races':g.race_id.nunique(),'days':g.race_date.nunique()}
 if g.race_id.nunique()<30 or g.horse_id.nunique()<30 or g.race_date.nunique()<20 or not g.gap_group.eq(REF).any():return [],{**meta,'status':'insufficient_population'}
 unit='horse_id' if variant=='horse_only' else 'horse_distance';X,spec=design(g,variant);X=X.to_numpy();Y=g[TARGETS].to_numpy();Z,lu,info=project(g,unit);V=np.column_stack([Y,X]);R=V-Z@lu.solve(np.asarray(Z.T@V));yr=R[:,:3];xr=R[:,3:];K=len(spec['groups']);D=xr[:,:K];N=xr[:,K:];resD=D-N@np.linalg.lstsq(N,D,rcond=1e-10)[0];rank=int(np.linalg.matrix_rank(resD,tol=1e-7));df=len(g)-info['rank']-np.linalg.matrix_rank(xr,tol=1e-7)
 if rank<K or df<=20:return [],{**meta,'status':'unidentified_or_insufficient_df','target_rank':rank,'target_columns':K,'df':int(df)}
 pen=np.r_[np.zeros(K),np.ones(X.shape[1]-K)];bread=np.linalg.inv(xr.T@xr+np.diag(pen));beta=bread@xr.T@yr;orth=float(np.abs(Z.T@R).max());assert orth<1e-6
 deg=min(g.race_date.nunique(),g.horse_id.nunique())-1;crit=float(t.ppf(.975,deg));rows=[];models=[];ref=g[g.gap_group.eq(REF)];reference_units=set(ref[unit]);ref_h=set(ref.horse_id)
 for k,target in enumerate(TARGETS):
  res=yr[:,k]-xr@beta[:,k];dc=cluster(xr,res,bread,g.race_date,df);hc=cluster(xr,res,bread,g.horse_id,df);sign=-1 if target=='relative_time' else 1
  for i,label in enumerate(spec['groups']):
   q=g[g.gap_group.eq(label)];cross=q[q[unit].isin(reference_units)].horse_id.nunique();supported=len(q)>=100 and len(ref)>=100 and q.horse_id.nunique()>=30 and ref.horse_id.nunique()>=30 and q.race_date.nunique()>=20 and ref.race_date.nunique()>=20 and cross>=20
   val=float(sign*beta[i,k]);sd=float(np.sqrt(max(0,dc[i,i])));sh=float(np.sqrt(max(0,hc[i,i])));rows.append({**meta,'target':target,'gap_group':label,'reference':REF,'starts_in_group':len(q),'horses_in_group':q.horse_id.nunique(),'days_in_group':q.race_date.nunique(),'reference_starts':len(ref),'crossover_horses':cross,'support':supported,'effect':val,'date_low':val-crit*sd,'date_high':val+crit*sd,'horse_low':val-crit*sh,'horse_high':val+crit*sh,'date_p':float(2*t.sf(abs(val/sd),deg)) if sd else 1.,'units':'seconds_faster' if target=='relative_time' else '10runner_equivalent_places_better' if target=='rank10_quality' else 'percentage_points','residual_df':int(df),'first_date':g.race_date.min(),'last_date':g.race_date.max(),'field_min':g.field_n.min(),'field_max':g.field_n.max()})
  models.append({'target':target,'beta':beta[:,k].tolist(),'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'crit':crit})
 print('Interval fitted',period,distance,variant,len(g),flush=True)
 return rows,{**meta,'status':'fitted','row_ids':g.api_record_id.astype(int).tolist(),'spec':spec,'FE':info,'residual_df':int(df),'projection_orthogonality':orth,'models':models}
def variant_data(g,variant):
 z=g.copy()
 if variant=='median10':
  z['gap_group']=z.gap_group10;z['gap_bin']=z.gap_group;z['log_typical']=np.log1p(z.typical10);z['typical_n']=z.typical10_n;z['typical_mad_ratio']=z.typical10_mad_ratio
 return z[z.gap_group.notna()]
def main():
 out=HERE/'analysis01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);a=a[a.gap_group.notna()].copy();raw_tables(a,out);rows=[];models=[]
 for period,g in period_data(a).items():
  if period=='past':continue
  for distance,z in [('pooled',g)]+[(str(int(d)),v) for d,v in g.groupby('race_distance_m')]:
   for variant in (['primary','without_absolute','median10'] if distance=='pooled' else ['primary']):
    v=variant_data(z,variant);rr,mm=fit(v,period,distance,variant);rows+=rr;models.append(mm)
 r=pd.DataFrame(rows);r['BH_q']=np.nan
 for pooled in [True,False]:
  mask=r.variant.eq('primary')&r.support&(r.distance.eq('pooled') if pooled else r.distance.ne('pooled'));r.loc[mask,'BH_q']=bh(r.loc[mask,'date_p'])
 r['direction_supported']=r.variant.eq('primary')&r.support&r.BH_q.lt(.05)&((r.date_low.gt(0)&r.horse_low.gt(0))|(r.date_high.lt(0)&r.horse_high.lt(0)))
 r.to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models);repeats=[]
 for (d,target,label),g in r[r.variant.eq('primary')&r.period.ne('all')].groupby(['distance','target','gap_group']):
  repeats.append({'distance':d,'target':target,'gap_group':label,'periods':len(g),'same_direction':len(g)==2 and bool(g.effect.gt(0).all() or g.effect.lt(0).all()),'repeated_supported':len(g)==2 and bool(g.direction_supported.all()) and bool(g.effect.gt(0).all() or g.effect.lt(0).all())})
 pd.DataFrame(repeats).to_csv(out/'repeat_checks.csv',index=False,encoding='utf-8-sig')
 print(r[r.distance.eq('pooled')&r.variant.eq('primary')][['period','target','gap_group','starts_in_group','effect','date_low','date_high','horse_low','horse_high','BH_q','direction_supported']].to_string(index=False),flush=True)
if __name__=='__main__':main()
