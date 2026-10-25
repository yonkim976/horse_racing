"""Race and horse-distance-jockey adjusted extreme departure comparisons."""
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,OLD,BASE,LABELS,ULTRA,load,periods,sample,module,save
COMMON=module('frozen_training_math',OLD/'analysis.py')
VARIANTS=['primary','window7','window28','median10','opportunity_rate','absolute_quantity','horse_distance','short_gap','baseline_floor']
DEFS={'joint':['days_group','minutes_group'],'days_only':['days_group'],'minutes_only':['minutes_group'],'ultra':['days_group','minutes_group'],'daily_time':['daily_minutes_group'],'combo':['combo_group']}
TARGETS=['relative_time','rank10_quality','top3_pp']
def support(g,field,label,ref):
 q=g[g[field].eq(label)];r=g[g[field].eq(ref)];pairs=set(q.analysis_unit)&set(r.analysis_unit);cross=g[g.analysis_unit.isin(pairs)].horse_id.nunique()
 ok=min(len(q),len(r))>=100 and min(q.horse_id.nunique(),r.horse_id.nunique())>=30 and min(q.race_date.nunique(),r.race_date.nunique())>=20 and cross>=20
 return {'support':ok,'positive_starts':len(q),'reference_starts':len(r),'positive_horses':q.horse_id.nunique(),'reference_horses':r.horse_id.nunique(),'positive_days':q.race_date.nunique(),'reference_days':r.race_date.nunique(),'crossover_horses':cross,'reason':'eligible' if ok else 'group_or_crossover_support'}
def design(g,model,variant):
 D=pd.DataFrame(index=g.index);contrasts=[]
 for field in DEFS[model]:
  labels=ULTRA if model=='ultra' else ['usual','big_decrease','big_increase','other'] if model=='combo' else LABELS
  for label in labels:
   if label!='usual' and g[field].eq(label).any():D[field+'='+label]=g[field].eq(label).astype(float)
  tested=['extreme_decrease','extreme_increase'] if model=='ultra' else ['big_decrease','big_increase'] if model=='combo' else [v for v in labels if v!='usual']
  pairs=[(v,'usual','level') for v in tested]
  if model=='joint' and variant=='primary':pairs += [('big_decrease','moderate_decrease','gradient'),('big_increase','moderate_increase','gradient')]
  for label,ref,kind in pairs:
   weights={field+'='+label:1.}
   if ref!='usual':weights[field+'='+ref]=-1.
   meta=support(g,field,label,ref)
   if not set(weights)<=set(D):meta.update(support=False,reason='absent_target_group')
   contrasts.append({'comparison':field+':'+label+'_vs_'+ref,'field':field,'positive_group':label,'reference_group':ref,'contrast_kind':kind,'weights':weights,**meta})
 cols=BASE+['log_usual_training_days','log_usual_training_minutes','log_usual_minutes_per_observed_day','log_usual_opportunity_days','opportunity_days','usual_history_n']
 if variant=='absolute_quantity':cols+=['log_current_days','log_current_minutes']
 raw=g[cols].copy();med=raw.median().fillna(0);n=raw.fillna(med)
 for c in cols:
  if raw[c].isna().any():n[c+'_missing']=raw[c].isna().astype(float)
 if model=='daily_time':
  for label in LABELS:
   if label!='usual':n['control_days_group='+label]=g.days_group.eq(label).astype(float)
 n=pd.concat([n,pd.get_dummies(g.trainer_id,prefix='trainer',drop_first=True,dtype=float)],axis=1)
 if variant=='horse_distance':n=pd.concat([n,pd.get_dummies(g.jockey_id,prefix='jockey',drop_first=True,dtype=float)],axis=1)
 sd=n.std(ddof=0);n=n.loc[:,sd.gt(1e-12)];mu=n.mean();sd=n.std(ddof=0);n=(n-mu)/sd;X=pd.concat([D,n],axis=1)
 return X,{'columns':X.columns.tolist(),'target_columns':D.columns.tolist(),'num_columns':cols,'medians':med.to_dict(),'means':mu.to_dict(),'sd':sd.to_dict(),'contrasts':contrasts}
def family(model,variant,kind,target):
 if model=='joint' and variant=='primary':return 'H1' if target=='H1_time_adv' else 'gradient' if kind=='gradient' else 'primary'
 if model in ['ultra','daily_time','combo']:return 'secondary'
 return 'sensitivity'
def fit(g,period,model,variant):
 frame,spec=design(g,model,variant);meta={'period':period,'model':model,'variant':variant,'rows':len(g),'horses':g.horse_id.nunique(),'races':g.race_id.nunique(),'days':g.race_date.nunique(),'first_date':g.race_date.min(),'last_date':g.race_date.max(),'field_min':int(g.field_n.min()),'field_max':int(g.field_n.max())}
 K=len(spec['target_columns'])
 if not K:return [],{**meta,'status':'no_target_columns','spec':spec}
 X=frame.to_numpy();targets=TARGETS+(['H1_time_adv'] if model=='joint' and variant=='primary' and period!='all' else []);Y=g[targets].to_numpy();assert np.isfinite(Y).all()
 Z,lu,info=COMMON.projection(g.assign(horse_distance=g.analysis_unit));info['unit']='analysis_unit';V=np.column_stack([Y,X]);R=V-Z@lu.solve(np.asarray(Z.T@V));yr=R[:,:len(targets)];xr=R[:,len(targets):];N=xr[:,K:];remaining=xr[:,:K]-N@np.linalg.lstsq(N,xr[:,:K],rcond=1e-10)[0];rank=np.linalg.matrix_rank(remaining,tol=1e-7);df=len(g)-info['rank']-np.linalg.matrix_rank(xr,tol=1e-7)
 if rank<K or df<=20:return [],{**meta,'status':'unidentified_or_insufficient_df','spec':spec,'target_rank':int(rank),'residual_df':int(df)}
 pen=np.r_[np.zeros(K),np.ones(X.shape[1]-K)];bread=np.linalg.inv(xr.T@xr+np.diag(pen));beta=bread@xr.T@yr;deg=min(g.race_date.nunique(),g.horse_id.nunique())-1;crit=float(t.ppf(.975,deg));rows=[];models=[]
 for k,target in enumerate(targets):
  res=yr[:,k]-xr@beta[:,k];dc=COMMON.cluster(xr,res,bread,g.race_date,df);hc=COMMON.cluster(xr,res,bread,g.horse_id,df)
  for c in spec['contrasts']:
   if not c['support'] or (c['contrast_kind']=='gradient' and target=='H1_time_adv'):continue
   vec=np.zeros(X.shape[1]);sign=-1 if target=='relative_time' else 1
   for col,weight in c['weights'].items():vec[spec['columns'].index(col)]=sign*weight
   point=float(vec@beta[:,k]);sd=np.sqrt(max(0,vec@dc@vec));sh=np.sqrt(max(0,vec@hc@vec))
   rows.append({**meta,**{key:value for key,value in c.items() if key!='weights'},'family':family(model,variant,c['contrast_kind'],target),'target':target,'effect':point,'date_low':point-crit*sd,'date_high':point+crit*sd,'horse_low':point-crit*sh,'horse_high':point+crit*sh,'date_p':float(2*t.sf(abs(point/sd),deg)) if sd else 1.,'units':'seconds_faster' if target in ['relative_time','H1_time_adv'] else '10runner_places_better' if target=='rank10_quality' else 'percentage_points','residual_df':int(df)})
  models.append({'target':target,'beta':beta[:,k].tolist(),'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'critical':crit})
 print('Extreme training fitted',period,model,variant,len(g),flush=True)
 return rows,{**meta,'status':'fitted','row_ids':g.api_record_id.astype(int).tolist(),'spec':spec,'FE':info,'residual_df':int(df),'projection_orthogonality':float(np.abs(Z.T@R).max()),'models':models}
def main():
 out=HERE/'analysis01';out.mkdir(exist_ok=False);a,f=load();rows=[];models=[];raw=[];cross=[]
 for period,z in periods(a).items():
  configs=[('joint',v) for v in VARIANTS]+[(v,'primary') for v in ['ultra','daily_time','combo']]+[('days_only','separate'),('minutes_only','separate')]
  for model,variant in configs:
   g=sample(z,f,model,variant);r,m=fit(g,period,model,variant);rows+=r;models.append(m)
   if variant=='primary':
    for field in DEFS[model]:
     for label,v in g.groupby(field):raw.append({'period':period,'model':model,'field':field,'group':label,**COMMON.raw(v),'mean_days_departure':v.days_departure.mean(),'mean_minutes_ratio':v.minutes_ratio.mean(),'mean_opportunity_days':v.opportunity_days.mean(),'mean_usual_days':v.usual5_training_days.mean(),'mean_usual_minutes':v.usual5_training_minutes.mean()})
    if model=='joint':
     for (d,tim),v in g.groupby(['days_group','minutes_group']):cross.append({'period':period,'days_group':d,'minutes_group':tim,'starts':len(v),'horses':v.horse_id.nunique(),'top3_pp':v.top3_pp.mean(),'mean_gap_days':v.gap_days.mean()})
 ef=pd.DataFrame(rows);ef['BH_q']=np.nan
 for fam in ['primary','gradient','H1','secondary']:
  mask=ef.family.eq(fam);ef.loc[mask,'BH_q']=COMMON.bh(ef.loc[mask,'date_p'])
 ef['direction_supported']=ef.family.ne('sensitivity')&ef.BH_q.lt(.05)&((ef.date_low.gt(0)&ef.horse_low.gt(0))|(ef.date_high.lt(0)&ef.horse_high.lt(0)))
 ef.to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models);pd.DataFrame(raw).to_csv(out/'raw_primary.csv',index=False,encoding='utf-8-sig');pd.DataFrame(cross).to_csv(out/'joint_group_counts.csv',index=False,encoding='utf-8-sig')
 rep=[]
 for (fam,model,comp,target),v in ef[ef.family.ne('sensitivity')&ef.period.ne('all')].groupby(['family','model','comparison','target']):rep.append({'family':fam,'model':model,'comparison':comp,'target':target,'periods':len(v),'recent_repeated_supported':len(v)==2 and bool(v.direction_supported.all()) and bool(v.effect.gt(0).all() or v.effect.lt(0).all())})
 pd.DataFrame(rep).to_csv(out/'repeat_checks.csv',index=False,encoding='utf-8-sig')
 print('Supported comparisons',flush=True);print(ef[ef.direction_supported][['period','model','variant','family','comparison','target','effect','date_low','date_high','horse_low','horse_high','BH_q']].to_string(index=False),flush=True)
if __name__=='__main__':main()
