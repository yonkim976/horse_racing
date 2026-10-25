"""Personal training departure beyond usual levels and available preparation days."""
import importlib.util
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,OLD,BASE,starts,periods,classify,save
sp=importlib.util.spec_from_file_location('verified_training_common',OLD/'analysis.py');COMMON=importlib.util.module_from_spec(sp);sp.loader.exec_module(COMMON)
VARIANTS=['primary','window7','window28','median10','opportunity_rate','absolute_quantity','horse_distance','short_gap']
DEFS={'joint':['days_group','minutes_group'],'daily_time':['daily_minutes_group'],'days_only':['days_group'],'minutes_only':['minutes_group']}
TARGETS=['relative_time','rank10_quality','top3_pp']
def sample(a,f,model,variant):
 w=7 if variant=='window7' else 28 if variant=='window28' else 14;size=10 if variant=='median10' else 5;z=f[f.window_days.eq(w)].drop(columns=['horse_id','race_date']);g=a.merge(z,on='api_record_id',validate='one_to_one');g=g[g.known_preparation&g['usual'+str(size)+'_supported']].copy()
 if variant=='short_gap':g=g[g.gap_days.le(90)].copy()
 g=classify(g,size,variant=='opportunity_rate');prefix='usual'+str(size)+'_'
 for c in ['training_days','training_minutes','minutes_per_observed_day','opportunity_days']:g['log_usual_'+c]=np.log1p(g[prefix+c])
 g['usual_history_n']=g[prefix+'n'];g['log_gap']=np.log1p(g.gap_days);g['log_current_days']=np.log1p(g.training_days);g['log_current_minutes']=np.log1p(g.training_minutes);g['analysis_unit']=g.horse_distance if variant=='horse_distance' else g.horse_distance+':'+g.jockey_id
 return g.reset_index(drop=True)
def design(g,model,variant):
 fields=DEFS[model];D=pd.DataFrame(index=g.index);contrasts=[]
 for field in fields:
  for label in ['decreased','increased']:
   col=field+'='+label
   if g[field].eq(label).any():D[col]=g[field].eq(label).astype(float)
   q=g[g[field].eq(label)];r=g[g[field].eq('usual')];pairs=set(q.analysis_unit)&set(r.analysis_unit);cross=g[g.analysis_unit.isin(pairs)].horse_id.nunique();ok=min(len(q),len(r))>=100 and min(q.horse_id.nunique(),r.horse_id.nunique())>=30 and min(q.race_date.nunique(),r.race_date.nunique())>=20 and cross>=20 and col in D
   contrasts.append({'comparison':field+':'+label+'_vs_usual','field':field,'positive_group':label,'reference_group':'usual','weights':{col:1.},'support':ok,'positive_starts':len(q),'reference_starts':len(r),'positive_horses':q.horse_id.nunique(),'reference_horses':r.horse_id.nunique(),'positive_days':q.race_date.nunique(),'reference_days':r.race_date.nunique(),'crossover_horses':cross,'reason':'eligible' if ok else 'group_or_crossover_support'})
 cols=BASE+['log_usual_training_days','log_usual_training_minutes','log_usual_minutes_per_observed_day','log_usual_opportunity_days','opportunity_days','usual_history_n']
 if variant=='absolute_quantity':cols+=['log_current_days','log_current_minutes']
 raw=g[cols].copy();med=raw.median().fillna(0);n=raw.fillna(med)
 for c in cols:
  if raw[c].isna().any():n[c+'_missing']=raw[c].isna().astype(float)
 if model=='daily_time':
  for label in ['decreased','increased']:n['control_days_group='+label]=g.days_group.eq(label).astype(float)
 n=pd.concat([n,pd.get_dummies(g.trainer_id,prefix='trainer',drop_first=True,dtype=float)],axis=1)
 if variant=='horse_distance':n=pd.concat([n,pd.get_dummies(g.jockey_id,prefix='jockey',drop_first=True,dtype=float)],axis=1)
 sd=n.std(ddof=0);n=n.loc[:,sd.gt(1e-12)];mu=n.mean();sd=n.std(ddof=0);n=(n-mu)/sd;X=pd.concat([D,n],axis=1)
 return X,{'columns':X.columns.tolist(),'target_columns':D.columns.tolist(),'num_columns':cols,'medians':med.to_dict(),'means':mu.to_dict(),'sd':sd.to_dict(),'contrasts':contrasts}
def fit(g,period,model,variant):
 frame,spec=design(g,model,variant);meta={'period':period,'model':model,'variant':variant,'rows':len(g),'horses':g.horse_id.nunique(),'races':g.race_id.nunique(),'days':g.race_date.nunique(),'first_date':g.race_date.min(),'last_date':g.race_date.max(),'field_min':int(g.field_n.min()),'field_max':int(g.field_n.max())};K=len(spec['target_columns'])
 if K==0:return [],{**meta,'status':'no_target_columns','spec':spec}
 X=frame.to_numpy();targets=TARGETS+(['H1_time_adv'] if variant=='primary' and period!='all' and model in ['joint','daily_time'] else []);Y=g[targets].to_numpy();assert np.isfinite(Y).all();Z,lu,info=COMMON.projection(g.assign(horse_distance=g.analysis_unit));info['unit']='analysis_unit';V=np.column_stack([Y,X]);R=V-Z@lu.solve(np.asarray(Z.T@V));yr=R[:,:len(targets)];xr=R[:,len(targets):];N=xr[:,K:];remaining=xr[:,:K]-N@np.linalg.lstsq(N,xr[:,:K],rcond=1e-10)[0];rank=np.linalg.matrix_rank(remaining,tol=1e-7);df=len(g)-info['rank']-np.linalg.matrix_rank(xr,tol=1e-7)
 if rank<K or df<=20:return [],{**meta,'status':'unidentified_or_insufficient_df','spec':spec,'target_rank':int(rank),'residual_df':int(df)}
 pen=np.r_[np.zeros(K),np.ones(X.shape[1]-K)];bread=np.linalg.inv(xr.T@xr+np.diag(pen));beta=bread@xr.T@yr;rows=[];models=[];deg=min(g.race_date.nunique(),g.horse_id.nunique())-1;crit=float(t.ppf(.975,deg))
 for k,target in enumerate(targets):
  res=yr[:,k]-xr@beta[:,k];dc=COMMON.cluster(xr,res,bread,g.race_date,df);hc=COMMON.cluster(xr,res,bread,g.horse_id,df);sign=-1 if target=='relative_time' else 1
  for c in spec['contrasts']:
   if not c['support']:continue
   vec=np.zeros(X.shape[1])
   for col,weight in c['weights'].items():vec[spec['columns'].index(col)]=sign*weight
   point=float(vec@beta[:,k]);sd=np.sqrt(max(0,vec@dc@vec));sh=np.sqrt(max(0,vec@hc@vec));rows.append({**meta,**{key:value for key,value in c.items() if key!='weights'},'target':target,'effect':point,'date_low':point-crit*sd,'date_high':point+crit*sd,'horse_low':point-crit*sh,'horse_high':point+crit*sh,'date_p':float(2*t.sf(abs(point/sd),deg)) if sd else 1.,'units':'seconds_faster' if target in ['relative_time','H1_time_adv'] else '10runner_places_better' if target=='rank10_quality' else 'percentage_points','residual_df':int(df)})
  models.append({'target':target,'beta':beta[:,k].tolist(),'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'critical':crit})
 print('Personal training fitted',period,model,variant,len(g),flush=True)
 return rows,{**meta,'status':'fitted','row_ids':g.api_record_id.astype(int).tolist(),'spec':spec,'FE':info,'residual_df':int(df),'projection_orthogonality':float(np.abs(Z.T@R).max()),'models':models}
def main():
 out=HERE/'analysis01';out.mkdir(exist_ok=False);a=starts();f=pd.read_csv(HERE/'input01/features.csv',dtype={'horse_id':str});rows=[];models=[];raw=[]
 for period,z in periods(a).items():
  for model in ['joint','daily_time']:
   for variant in VARIANTS:
    if model=='daily_time' and variant=='opportunity_rate':continue
    g=sample(z,f,model,variant);r,m=fit(g,period,model,variant);rows+=r;models.append(m)
    if variant=='primary':
     for field in DEFS[model]:
      for label,v in g.groupby(field):raw.append({'period':period,'model':model,'field':field,'group':label,**COMMON.raw(v),'mean_days_departure':v.days_departure.mean(),'mean_minutes_ratio':v.minutes_ratio.mean(),'mean_daily_minutes_ratio':v.daily_minutes_ratio.mean(),'mean_opportunity_days':v.opportunity_days.mean(),'mean_usual_days':v.usual5_training_days.mean(),'mean_usual_minutes':v.usual5_training_minutes.mean()})
  for model in ['days_only','minutes_only']:
   g=sample(z,f,model,'separate');r,m=fit(g,period,model,'separate');rows+=r;models.append(m)
 ef=pd.DataFrame(rows);ef['BH_q']=np.nan
 for h1 in [False,True]:
  mask=ef.variant.eq('primary')&(ef.target.eq('H1_time_adv') if h1 else ef.target.ne('H1_time_adv'));ef.loc[mask,'BH_q']=COMMON.bh(ef.loc[mask,'date_p'])
 ef['direction_supported']=ef.variant.eq('primary')&ef.BH_q.lt(.05)&((ef.date_low.gt(0)&ef.horse_low.gt(0))|(ef.date_high.lt(0)&ef.horse_high.lt(0)));ef.to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models);pd.DataFrame(raw).to_csv(out/'raw_primary.csv',index=False,encoding='utf-8-sig');rep=[]
 for (model,comp,target),v in ef[ef.variant.eq('primary')&ef.period.ne('all')].groupby(['model','comparison','target']):rep.append({'model':model,'comparison':comp,'target':target,'periods':len(v),'recent_repeated_supported':len(v)==2 and bool(v.direction_supported.all()) and bool(v.effect.gt(0).all() or v.effect.lt(0).all())})
 pd.DataFrame(rep).to_csv(out/'repeat_checks.csv',index=False,encoding='utf-8-sig');print('Supported primary effects',flush=True);print(ef[ef.direction_supported][['period','model','comparison','target','effect','date_low','date_high','horse_low','horse_high','BH_q']].to_string(index=False),flush=True)
if __name__=='__main__':main()
