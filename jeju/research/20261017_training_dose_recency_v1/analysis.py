"""Conditional training dose/recency associations; fixed targets and contrasts."""
import importlib.util
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,ROOT,OLD,BASE,starts,periods,save
spec=importlib.util.spec_from_file_location('verified_training_common',OLD/'analysis.py');COMMON=importlib.util.module_from_spec(spec);spec.loader.exec_module(COMMON)
MODELS={'own_days':[('own_days_group','0',['1','2_3','4plus'])],'recency':[('own_recency_group','4_7',['2_3','8plus'])],'own_time':[('own_time_group','30_60',['le30','gt60'])],'total':[('count_group','5_8',['1_4','9plus']),('time_group','60_120',['le60','gt120'])]}
VARIANTS=['primary','window7','window28','horse_distance'];TARGETS=['relative_time','rank10_quality','top3_pp']
def sample(a,f,model,variant):
 w=7 if variant=='window7' else 28 if variant=='window28' else 14;g=a.merge(f[f.window_days.eq(w)],on='api_record_id',validate='one_to_one')
 if model=='total':g=g[g.training_rows.gt(0)&g.duration_missing_rows.eq(0)].copy()
 else:
  g=g[g.identity_complete].copy()
  if model in ['recency','own_time','individual']:g=g[g.same_jockey].copy()
  if model in ['own_time','individual']:g=g[g.own_duration_missing_rows.eq(0)].copy()
 if variant=='distinct_days':g['count_group']=g.days_group
 g['analysis_unit']=g.horse_distance if variant=='horse_distance' else g.horse_distance+':'+g.jockey_id
 g['log_gap']=np.log1p(g.gap_days);g['log_training_days']=np.log1p(g.training_days);g['log_training_minutes']=np.log1p(g.training_minutes);g['log_own_minutes']=np.log1p(g.own_minutes);g['own_days_per3']=g.same_jockey_days/3;g['own_nearer_per3']=-g.own_lag_days/3
 return g.reset_index(drop=True)
def individual_support(g):
 rows=[]
 for j,v in g.groupby('jockey_id'):
  for feature in ['own_days_per3','own_nearer_per3']:
   varying=v.groupby('analysis_unit')[feature].nunique();ids=set(varying[varying.gt(1)].index);cross=v[v.analysis_unit.isin(ids)].horse_id.nunique();ok=len(v)>=100 and v.horse_id.nunique()>=30 and v.race_date.nunique()>=20 and v[feature].nunique()>=3 and cross>=10
   rows.append({'jockey_id':j,'feature':feature,'support':ok,'starts':len(v),'horses':v.horse_id.nunique(),'days':v.race_date.nunique(),'feature_values':v[feature].nunique(),'varying_pair_horses':cross})
 return pd.DataFrame(rows)
def conditions(g,model,variant):
 cols=BASE.copy()
 if model!='total':cols+=['log_training_days','log_training_minutes']
 if model in ['recency','individual']:cols+=['log_own_minutes','own_duration_missing_rows']
 raw=g[cols].copy();med=raw.median().fillna(0);n=raw.fillna(med)
 for c in cols:
  if raw[c].isna().any():n[c+'_missing']=raw[c].isna().astype(float)
 if model in ['recency','own_time']:
  for label in ['2_3','4plus']:n['control_own_days='+label]=g.own_days_group.eq(label).astype(float)
 n=pd.concat([n,pd.get_dummies(g.trainer_id,prefix='trainer',drop_first=True,dtype=float)],axis=1)
 if variant=='horse_distance':n=pd.concat([n,pd.get_dummies(g.jockey_id,prefix='jockey',drop_first=True,dtype=float)],axis=1)
 return n,cols,med
def design(g,model,variant):
 n,cols,med=conditions(g,model,variant);D=pd.DataFrame(index=g.index);contrasts=[];support=None
 if model=='individual':
  support=individual_support(g)
  for r in support.itertuples():
   col='individual='+r.jockey_id+':'+r.feature;v=g.jockey_id.eq(r.jockey_id).astype(float)*g[r.feature]
   if r.support:
    D[col]=v;contrasts.append({'comparison':r.feature,'jockey_id':r.jockey_id,'weights':{col:1.},'support':True,'positive_starts':r.starts,'reference_starts':r.starts,'crossover_horses':r.varying_pair_horses,'reason':'eligible'})
   else:n['unsupported_'+col]=v
 else:
  definitions=MODELS[model]
  for field,ref,labels in definitions:
   for label in labels:
    col=field+'='+label
    if g[field].eq(label).any():D[col]=g[field].eq(label).astype(float)
    contrasts.append({'comparison':field+':'+label+'_vs_'+ref,'jockey_id':'pooled','weights':{col:1.},'field':field,'positive_group':label,'reference_group':ref})
  if model=='own_days':
   for label in ['2_3','4plus']:contrasts.append({'comparison':'own_days_group:'+label+'_vs_1','jockey_id':'pooled','weights':{'own_days_group='+label:1.,'own_days_group=1':-1.},'field':'own_days_group','positive_group':label,'reference_group':'1'})
  for c in contrasts:
   q=g[g[c['field']].eq(c['positive_group'])];r=g[g[c['field']].eq(c['reference_group'])];units=set(q.analysis_unit)&set(r.analysis_unit);cross=g[g.analysis_unit.isin(units)].horse_id.nunique();ok=min(len(q),len(r))>=100 and min(q.horse_id.nunique(),r.horse_id.nunique())>=30 and min(q.race_date.nunique(),r.race_date.nunique())>=20 and cross>=20 and all(k in D for k in c['weights']);c.update(support=ok,positive_starts=len(q),reference_starts=len(r),positive_horses=q.horse_id.nunique(),reference_horses=r.horse_id.nunique(),positive_days=q.race_date.nunique(),reference_days=r.race_date.nunique(),crossover_horses=cross,reason='eligible' if ok else 'group_or_crossover_support')
 sd=n.std(ddof=0);n=n.loc[:,sd.gt(1e-12)];mu=n.mean();sd=n.std(ddof=0);n=(n-mu)/sd;X=pd.concat([D,n],axis=1)
 return X,{'columns':X.columns.tolist(),'target_columns':D.columns.tolist(),'num_columns':cols,'medians':med.to_dict(),'means':mu.to_dict(),'sd':sd.to_dict(),'contrasts':contrasts},support
def fit(g,period,model,variant):
 frame,spec,support=design(g,model,variant);meta={'period':period,'model':model,'variant':variant,'rows':len(g),'horses':g.horse_id.nunique(),'races':g.race_id.nunique(),'days':g.race_date.nunique(),'first_date':g.race_date.min(),'last_date':g.race_date.max(),'field_min':int(g.field_n.min()),'field_max':int(g.field_n.max())};K=len(spec['target_columns'])
 if K==0:return [],{**meta,'status':'no_supported_target','spec':spec},support
 X=frame.to_numpy();targets=TARGETS+(['H1_time_adv'] if variant=='primary' and period!='all' and model!='individual' else []);Y=g[targets].to_numpy();assert np.isfinite(Y).all();Z,lu,info=COMMON.projection(g.assign(horse_distance=g.analysis_unit));info['unit']='analysis_unit';V=np.column_stack([Y,X]);R=V-Z@lu.solve(np.asarray(Z.T@V));yr=R[:,:len(targets)];xr=R[:,len(targets):];N=xr[:,K:];remaining=xr[:,:K]-N@np.linalg.lstsq(N,xr[:,:K],rcond=1e-10)[0];rank=np.linalg.matrix_rank(remaining,tol=1e-7);df=len(g)-info['rank']-np.linalg.matrix_rank(xr,tol=1e-7)
 if rank<K or df<=20:return [],{**meta,'status':'unidentified_or_insufficient_df','spec':spec,'target_rank':int(rank),'residual_df':int(df)},support
 pen=np.r_[np.zeros(K),np.ones(X.shape[1]-K)];bread=np.linalg.inv(xr.T@xr+np.diag(pen));beta=bread@xr.T@yr;rows=[];models=[]
 for k,target in enumerate(targets):
  res=yr[:,k]-xr@beta[:,k];dc=COMMON.cluster(xr,res,bread,g.race_date,df);hc=COMMON.cluster(xr,res,bread,g.horse_id,df);critical={}
  for c in spec['contrasts']:
   if not c['support']:continue
   j=c['jockey_id'];v=g if j=='pooled' else g[g.jockey_id.eq(j)];deg=min(v.race_date.nunique(),v.horse_id.nunique())-1;crit=float(t.ppf(.975,deg));critical[c['comparison']+':'+j]=crit;vec=np.zeros(X.shape[1]);sign=-1 if target=='relative_time' else 1
   for col,weight in c['weights'].items():vec[spec['columns'].index(col)]=sign*weight
   point=float(vec@beta[:,k]);sd=np.sqrt(max(0,vec@dc@vec));sh=np.sqrt(max(0,vec@hc@vec));rows.append({**meta,**{key:value for key,value in c.items() if key!='weights'},'target':target,'effect':point,'date_low':point-crit*sd,'date_high':point+crit*sd,'horse_low':point-crit*sh,'horse_high':point+crit*sh,'date_p':float(2*t.sf(abs(point/sd),deg)) if sd else 1.,'units':'seconds_faster' if target in ['relative_time','H1_time_adv'] else '10runner_places_better' if target=='rank10_quality' else 'percentage_points','residual_df':int(df)})
  models.append({'target':target,'beta':beta[:,k].tolist(),'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'critical':critical})
 print('Training dose fitted',period,model,variant,len(g),'rows',len(rows),'effects',flush=True)
 return rows,{**meta,'status':'fitted','row_ids':g.api_record_id.astype(int).tolist(),'spec':spec,'FE':info,'residual_df':int(df),'projection_orthogonality':float(np.abs(Z.T@R).max()),'models':models},support
def main():
 out=HERE/'analysis01';out.mkdir(exist_ok=False);a=starts();f=pd.read_csv(HERE/'input01/features.csv');rows=[];models=[];raw=[];individual=[]
 for period,z in periods(a).items():
  for model in MODELS:
   for variant in VARIANTS+(['distinct_days'] if model=='total' else []):
    g=sample(z,f,model,variant);r,m,_=fit(g,period,model,variant);rows+=r;models.append(m)
    if variant=='primary':
     for field,ref,labels in MODELS[model]:
      for label,v in g.groupby(field):raw.append({'period':period,'model':model,'field':field,'group':label,**COMMON.raw(v),'mean_own_days':v.same_jockey_days.mean(),'mean_own_minutes':v.own_minutes.mean(),'mean_own_lag':v.own_lag_days.mean()})
  g=sample(z,f,'individual','primary');r,m,s=fit(g,period,'individual','primary');rows+=r;models.append(m);individual+=s.assign(period=period).to_dict('records')
 ef=pd.DataFrame(rows);ef['BH_q']=np.nan
 for individual_family,h1 in [(False,False),(False,True),(True,False)]:
  mask=ef.variant.eq('primary')&(ef.model.eq('individual') if individual_family else ef.model.ne('individual'))&(ef.target.eq('H1_time_adv') if h1 else ef.target.ne('H1_time_adv'));ef.loc[mask,'BH_q']=COMMON.bh(ef.loc[mask,'date_p'])
 ef['direction_supported']=ef.variant.eq('primary')&ef.BH_q.lt(.05)&((ef.date_low.gt(0)&ef.horse_low.gt(0))|(ef.date_high.lt(0)&ef.horse_high.lt(0)));names=pd.read_csv(ROOT/'jeju/research/20261017_jockey_training_individual_v1/input01/jockey_names.csv',dtype={'jockey_id':str}).set_index('jockey_id').jockey_name.to_dict();ef['jockey_name']=ef.jockey_id.map(names).fillna('전체');ef.to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models);pd.DataFrame(raw).to_csv(out/'raw_primary.csv',index=False,encoding='utf-8-sig');sf=pd.DataFrame(individual);sf['jockey_name']=sf.jockey_id.map(names);sf.to_csv(out/'individual_support.csv',index=False,encoding='utf-8-sig')
 rep=[]
 for (model,comp,j,target),v in ef[ef.variant.eq('primary')&ef.period.ne('all')].groupby(['model','comparison','jockey_id','target']):rep.append({'model':model,'comparison':comp,'jockey_id':j,'target':target,'periods':len(v),'recent_repeated_supported':len(v)==2 and bool(v.direction_supported.all()) and bool(v.effect.gt(0).all() or v.effect.lt(0).all())})
 pd.DataFrame(rep).to_csv(out/'repeat_checks.csv',index=False,encoding='utf-8-sig');print('Supported primary effects',flush=True);print(ef[ef.direction_supported][['period','model','comparison','jockey_name','target','effect','date_low','date_high','horse_low','horse_high','BH_q']].to_string(index=False),flush=True)
if __name__=='__main__':main()
