"""Joint jockey-training interactions with race and horse-distance-jockey effects."""
import importlib.util,json
import numpy as np
import pandas as pd
from scipy.stats import t,f as fdist
from data import HERE,OLD,BASE,load,periods,save
spec=importlib.util.spec_from_file_location('verified_training_common',OLD/'analysis.py');COMMON=importlib.util.module_from_spec(spec);spec.loader.exec_module(COMMON)
VARIANTS=['primary','window7','window28','horse_distance','no_quantity','other_jockey_only','small_support']
TARGETS=['relative_time','rank10_quality','top3_pp']
def sample(a,features,variant):
 w=7 if variant=='window7' else 28 if variant=='window28' else 14;g=a.merge(features[features.window_days.eq(w)],on='api_record_id',validate='one_to_one');g=g[g.identity_complete].copy()
 if variant=='other_jockey_only':g=g[g.any_jockey].copy()
 g['analysis_unit']=g.horse_distance if variant=='horse_distance' else g.horse_distance+':'+g.jockey_id
 g['log_gap']=np.log1p(g.gap_days);g['log_training_days']=np.log1p(g.training_days);g['log_training_minutes']=np.log1p(g.training_minutes)
 return g.reset_index(drop=True)
def individual_support(g,variant):
 rows=[]
 for j,v in g.groupby('jockey_id',sort=True):
  q=v[v.same_jockey];r=v[~v.same_jockey];both=set(q.horse_distance)&set(r.horse_distance);cross=v[v.horse_distance.isin(both)].horse_id.nunique();m={'jockey_id':j,'starts':len(v),'positive_starts':len(q),'negative_starts':len(r),'positive_horses':q.horse_id.nunique(),'negative_horses':r.horse_id.nunique(),'positive_days':q.race_date.nunique(),'negative_days':r.race_date.nunique(),'crossover_horses':cross,'jockey_days':v.race_date.nunique(),'jockey_horses':v.horse_id.nunique()}
  n,h,d,c=(30,10,10,5) if variant=='small_support' else (50,20,15,10);m['support']=min(len(q),len(r))>=n and min(m['positive_horses'],m['negative_horses'])>=h and min(m['positive_days'],m['negative_days'])>=d and cross>=c;m['strict_previous100_support']=min(len(q),len(r))>=100 and min(m['positive_horses'],m['negative_horses'])>=30 and min(m['positive_days'],m['negative_days'])>=20 and cross>=20
  m['reason']='eligible' if m['support'] else ','.join(k for k,vv in [('starts',min(len(q),len(r))>=n),('horses',min(m['positive_horses'],m['negative_horses'])>=h),('days',min(m['positive_days'],m['negative_days'])>=d),('crossover',cross>=c)] if not vv);rows.append(m)
 return pd.DataFrame(rows)
def design(g,support,variant):
 eligible=support.loc[support.support,'jockey_id'].tolist();D=pd.DataFrame({'own='+j:(g.same_jockey&g.jockey_id.eq(j)).astype(float) for j in eligible});cols=BASE+([] if variant=='no_quantity' else ['log_training_days','log_training_minutes','duration_missing_rows']);raw=g[cols].copy();med=raw.median().fillna(0);n=raw.fillna(med)
 for c in cols:
  if raw[c].isna().any():n[c+'_missing']=raw[c].isna().astype(float)
 n=pd.concat([n,pd.get_dummies(g.trainer_id,prefix='trainer',drop_first=True,dtype=float)],axis=1)
 if variant=='horse_distance':n=pd.concat([n,pd.get_dummies(g.jockey_id,prefix='jockey',drop_first=True,dtype=float)],axis=1)
 for j in support.loc[~support.support,'jockey_id']:n['unsupported_own='+j]=(g.same_jockey&g.jockey_id.eq(j)).astype(float)
 sd=n.std(ddof=0);n=n.loc[:,sd.gt(1e-12)];mu=n.mean();sd=n.std(ddof=0);n=(n-mu)/sd;X=pd.concat([D,n],axis=1)
 return X,{'columns':X.columns.tolist(),'eligible_jockeys':eligible,'num_columns':cols,'medians':med.to_dict(),'means':mu.to_dict(),'sd':sd.to_dict()}
def fit(g,support,period,variant):
 meta={'period':period,'variant':variant,'rows':len(g),'horses':g.horse_id.nunique(),'races':g.race_id.nunique(),'days':g.race_date.nunique(),'first_date':g.race_date.min(),'last_date':g.race_date.max(),'field_min':int(g.field_n.min()),'field_max':int(g.field_n.max())};eligible=support.loc[support.support,'jockey_id'].tolist()
 if not eligible:return [],[],{**meta,'status':'no_supported_jockeys'}
 frame,spec=design(g,support,variant);X=frame.to_numpy();targets=TARGETS+(['H1_time_adv'] if variant=='primary' and period!='all' else []);Y=g[targets].to_numpy();assert np.isfinite(Y).all();Z,lu,info=COMMON.projection(g.assign(horse_distance=g.analysis_unit));info['unit']='analysis_unit';V=np.column_stack([Y,X]);R=V-Z@lu.solve(np.asarray(Z.T@V));yr=R[:,:len(targets)];xr=R[:,len(targets):];K=len(eligible);D=xr[:,:K];N=xr[:,K:];remaining=D-N@np.linalg.lstsq(N,D,rcond=1e-10)[0];rank=np.linalg.matrix_rank(remaining,tol=1e-7);df=len(g)-info['rank']-np.linalg.matrix_rank(xr,tol=1e-7)
 if rank<K or df<=20:return [],[],{**meta,'status':'unidentified_or_insufficient_df','target_rank':int(rank),'target_columns':K,'residual_df':int(df)}
 pen=np.r_[np.zeros(K),np.ones(X.shape[1]-K)];bread=np.linalg.inv(xr.T@xr+np.diag(pen));beta=bread@xr.T@yr;rows=[];omnibus=[];models=[];byj=support.set_index('jockey_id')
 for k,target in enumerate(targets):
  res=yr[:,k]-xr@beta[:,k];dc=COMMON.cluster(xr,res,bread,g.race_date,df);hc=COMMON.cluster(xr,res,bread,g.horse_id,df);sign=-1 if target=='relative_time' else 1;critical={}
  for i,j in enumerate(eligible):
   jm=byj.loc[j].to_dict();deg=min(jm['jockey_days'],jm['jockey_horses'])-1;crit=float(t.ppf(.975,deg));critical[j]=crit;point=float(sign*beta[i,k]);sd=np.sqrt(max(0,dc[i,i]));sh=np.sqrt(max(0,hc[i,i]));rows.append({**meta,**jm,'jockey_id':j,'target':target,'effect':point,'date_low':point-crit*sd,'date_high':point+crit*sd,'horse_low':point-crit*sh,'horse_high':point+crit*sh,'date_p':float(2*t.sf(abs(point/sd),deg)) if sd else 1.,'units':'seconds_faster' if target in ['relative_time','H1_time_adv'] else '10runner_places_better' if target=='rank10_quality' else 'percentage_points','residual_df':int(df)})
  if variant=='primary' and target!='H1_time_adv' and K>=2:
   C=np.zeros((K-1,X.shape[1]));C[:,0]=-1
   for i in range(K-1):C[i,i+1]=1
   diff=C@beta[:,k];om={'period':period,'target':target,'eligible_jockeys':K,'numerator_df':K-1}
   for label,cov,key in [('date',dc,'race_date'),('horse',hc,'horse_id')]:
    S=C@cov@C.T;rank=np.linalg.matrix_rank(S,tol=1e-10);stat=float(diff@np.linalg.pinv(S)@diff/(K-1));om[label+'_F']=stat;om[label+'_p']=float(fdist.sf(stat,K-1,g[key].nunique()-1));om[label+'_rank']=int(rank);om[label+'_denominator_df']=g[key].nunique()-1
   omnibus.append(om)
  models.append({'target':target,'beta':beta[:,k].tolist(),'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'crit_by_jockey':critical})
 print('Individual training fitted',period,variant,K,'jockeys',len(g),'background starts',flush=True)
 return rows,omnibus,{**meta,'status':'fitted','row_ids':g.api_record_id.astype(int).tolist(),'spec':spec,'FE':info,'residual_df':int(df),'projection_orthogonality':float(np.abs(Z.T@R).max()),'models':models}
def main():
 out=HERE/'analysis01';out.mkdir(exist_ok=False);a,f=load();names=pd.read_csv(HERE/'input01/jockey_names.csv',dtype={'jockey_id':str}).set_index('jockey_id').jockey_name.to_dict();rows=[];omnibus=[];models=[];supports=[];raw=[]
 for period,z in periods(a).items():
  for variant in VARIANTS:
   g=sample(z,f,variant);s=individual_support(g,variant);supports+=s.assign(period=period,variant=variant).to_dict('records')
   if variant=='primary':
    for (j,own),v in g.groupby(['jockey_id','same_jockey']):raw.append({'period':period,'jockey_id':j,'same_jockey':bool(own),**COMMON.raw(v)})
   r,o,m=fit(g,s,period,variant);rows+=r;omnibus+=o;models.append(m)
 ef=pd.DataFrame(rows);ef['jockey_name']=ef.jockey_id.map(names);ef['BH_q']=np.nan
 for variant,ish1 in [('primary',False),('primary',True),('small_support',False)]:
  mask=ef.variant.eq(variant)&(ef.target.eq('H1_time_adv') if ish1 else ef.target.ne('H1_time_adv'));ef.loc[mask,'BH_q']=COMMON.bh(ef.loc[mask,'date_p'])
 ef['direction_supported']=ef.variant.isin(['primary','small_support'])&ef.BH_q.lt(.05)&((ef.date_low.gt(0)&ef.horse_low.gt(0))|(ef.date_high.lt(0)&ef.horse_high.lt(0)));ef.to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models)
 sf=pd.DataFrame(supports);sf['jockey_name']=sf.jockey_id.map(names);sf.to_csv(out/'support.csv',index=False,encoding='utf-8-sig');rf=pd.DataFrame(raw);rf['jockey_name']=rf.jockey_id.map(names);rf.to_csv(out/'raw_primary.csv',index=False,encoding='utf-8-sig')
 om=pd.DataFrame(omnibus)
 for label in ['date','horse']:om[label+'_BH_q']=COMMON.bh(om[label+'_p'])
 om['difference_supported']=om.date_BH_q.lt(.05)&om.horse_BH_q.lt(.05)&om.date_rank.eq(om.numerator_df)&om.horse_rank.eq(om.numerator_df);om.to_csv(out/'heterogeneity.csv',index=False,encoding='utf-8-sig')
 repeat=[]
 for (j,target),v in ef[ef.variant.eq('primary')&ef.period.ne('all')].groupby(['jockey_id','target']):repeat.append({'jockey_id':j,'jockey_name':names[j],'target':target,'periods_supported':len(v),'positive_recent_repeated':len(v)==2 and bool((v.direction_supported&v.effect.gt(0)).all())})
 pd.DataFrame(repeat).to_csv(out/'repeat_checks.csv',index=False,encoding='utf-8-sig');print('Primary supported directions',flush=True);print(ef[ef.variant.eq('primary')&ef.direction_supported][['period','jockey_id','jockey_name','target','positive_starts','negative_starts','effect','date_low','date_high','horse_low','horse_high','BH_q']].to_string(index=False),flush=True);print('Primary support counts',sf[sf.variant.eq('primary')].groupby('period').support.sum().to_dict(),flush=True)
if __name__=='__main__':main()
