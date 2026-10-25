"""Context-specific rider contrasts and expected-performance shortfall differences."""
import importlib.util
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,OLD,FE_NUM,ADJUST,save
sp=importlib.util.spec_from_file_location('preserved_effects',OLD/'effects.py');previous=importlib.util.module_from_spec(sp);sp.loader.exec_module(previous)
project=previous.project;cluster=previous.cluster;bh=previous.bh
NEGATIVE=['time','g3f_rank','fade3','big_slow','slow_loss','absolute_error']
PERCENT=['first_pack','front_pack2','g3f_rank','fade3','big_slow']

def design(g,topic):
 exposure={'outer':'outer','pace':'pressure'}.get(topic)
 levels=sorted(g.jockey_id.unique());variable=levels.copy()
 if exposure:
  co=g.groupby('jockey_id')[exposure].agg(['sum','count']);variable=co.index[co['sum'].gt(0)&co['sum'].lt(co['count'])].tolist()
 reference=g[g.jockey_id.isin(variable)].jockey_id.value_counts().idxmax();main=[j for j in levels if j!=reference];interaction=[j for j in variable if j!=reference] if exposure else []
 x=pd.DataFrame({'main='+j:g.jockey_id.eq(j).astype(float) for j in main},index=g.index)
 for j in interaction:x['context='+j]=(g.jockey_id.eq(j)&g[exposure]).astype(float)
 cols=ADJUST+['gate_x_early']+[c for c in g if c.startswith('gate_d')]
 if exposure:cols=cols+[exposure]
 if topic=='stability':cols=cols+['H0_time','H0_prob','H1_time','H1_prob']
 n=g[list(dict.fromkeys(cols))].astype(float).copy();n['prior_unknown']=g.style_any.eq('unknown').astype(float)
 if topic=='stability':
  for d in sorted(g.race_distance_m.unique()):n['pred_d'+str(int(d))]=g.H1_time*g.race_distance_m.eq(d)
 med=n.median();n=n.fillna(med).fillna(0)
 for c in med.index:
  if c in g and g[c].isna().any():n[c+'_missing']=g[c].isna().astype(float)
 n=pd.concat([n,pd.get_dummies(g.trainer_id,prefix='trainer',drop_first=True,dtype=float)],axis=1);sd=n.std(ddof=0);n=n[sd[sd>1e-12].index];mu=n.mean();sd=n.std(ddof=0);n=(n-mu)/sd
 x=pd.concat([x,n],axis=1)
 spec={'columns':x.columns.tolist(),'maincols':main,'intercols':interaction,'levels':levels,'reference':reference,'variable':variable,'exposure':exposure,'nuisance_medians':med.fillna(0).to_dict(),'nuisance_means':mu.to_dict(),'nuisance_sd':sd.to_dict()}
 return x,spec

def fit(g,targets,topic,period):
 x,spec=design(g,topic);X=x.to_numpy();Y=g[targets].to_numpy();z,lu,info=project(g,'horse_distance');v=np.column_stack([Y,X]);rv=v-z@lu.solve(np.asarray(z.T@v));yr=rv[:,:len(targets)];xr=rv[:,len(targets):]
 nj=len(spec['maincols'])+len(spec['intercols']);jj=xr[:,:nj];nn=xr[:,nj:];jres=jj-nn@np.linalg.lstsq(nn,jj,rcond=1e-10)[0];rank=np.linalg.matrix_rank(jres,tol=1e-7)
 assert rank==nj,('unidentified',topic,period,targets,rank,nj)
 df=len(g)-info['rank']-np.linalg.matrix_rank(xr,tol=1e-7);assert df>20
 pen=np.r_[np.zeros(nj),np.ones(X.shape[1]-nj)];bread=np.linalg.inv(xr.T@xr+np.diag(pen));beta=bread@xr.T@yr
 exposure=spec['exposure'];subset=g[g[exposure]] if exposure else g;weights=subset.jockey_id.value_counts(normalize=True).reindex(spec['levels']).fillna(0).to_numpy()
 M=np.zeros((len(weights),X.shape[1]));I=M.copy()
 for i,j in enumerate(spec['levels']):
  if j in spec['maincols']:M[i,spec['maincols'].index(j)]=1
  if j in spec['intercols']:I[i,len(spec['maincols'])+spec['intercols'].index(j)]=1
 vectors={'context_effect':M+I,'context_specific':I} if exposure else {'jockey_effect':M}
 vectors={c:v-np.average(v,axis=0,weights=weights) for c,v in vectors.items()}
 support=g.groupby('jockey_id').agg(starts=('api_record_id','size'),days=('race_date','nunique'),horses=('horse_id','nunique'))
 counts={}
 if exposure:
  for b in [True,False]:counts[b]=g[g[exposure].eq(b)].groupby('jockey_id').agg(n=('api_record_id','size'),days=('race_date','nunique'),horses=('horse_id','nunique'))
 crit=float(t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1));rows=[];models=[];fitted=[]
 for k,target in enumerate(targets):
  res=yr[:,k]-xr@beta[:,k];dc=cluster(xr,res,bread,g.race_date,df);hc=cluster(xr,res,bread,g.horse_id,df);alpha=lu.solve(np.asarray(z.T@(Y[:,k]-X@beta[:,k])));fit=X@beta[:,k]+z@alpha
  assert np.max(np.abs(Y[:,k]-fit-res))<1e-7
  for contrast,vs in vectors.items():
   for i,j in enumerate(spec['levels']):
    if exposure and j not in spec['variable']:continue
    sup=support.loc[j];eligible=sup.starts>=(300 if period=='all' else 100) and sup.days>=20 and sup.horses>=30
    cc={}
    if exposure:
     for b,label in [(True,'context'),(False,'other')]:
      ss=counts[b].loc[j];cc[label+'_starts']=int(ss.n);cc[label+'_days']=int(ss.days);cc[label+'_horses']=int(ss.horses);eligible=eligible and ss.n>=30 and ss.days>=10 and ss.horses>=15
    fac=(-1 if target in NEGATIVE else 1)*(100 if target in PERCENT else 1);vec=vs[i]*fac;point=float(vec@beta[:,k]);ds=float(np.sqrt(max(0,vec@dc@vec)));hs=float(np.sqrt(max(0,vec@hc@vec)))
    rows.append({'topic':topic,'period':period,'target':target,'contrast':contrast,'jockey_id':j,'name':g.loc[g.jockey_id.eq(j),'jockey_display_name'].iloc[0],**sup.astype(int).to_dict(),**cc,'effect':point,'date_low':point-crit*ds,'date_high':point+crit*ds,'horse_low':point-crit*hs,'horse_high':point+crit*hs,'date_p':float(2*t.sf(abs(point/ds),min(g.race_date.nunique(),g.horse_id.nunique())-1)) if ds else 1.,'support':bool(eligible)})
  models.append({'topic':topic,'period':period,'target':target,'spec':spec,'row_ids':g.api_record_id.astype(int).tolist(),'weights':weights.tolist(),'beta':beta[:,k].tolist(),'alpha':alpha.tolist(),'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'crit':crit,'FE':info,'residual_df':int(df)})
  r=g[['api_record_id','jockey_id','horse_id','race_date']].copy();r['topic']=topic;r['period']=period;r['target']=target;r['fit']=fit;r['residual']=res;fitted.append(r)
 print('Fitted',topic,period,targets,len(g),flush=True)
 return rows,models,fitted

def main():
 out=HERE/'effects01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input02/starts.csv',dtype={'horse_id':str,'jockey_id':str,'trainer_id':str},low_memory=False);rows=[];models=[];fitted=[];raw=[]
 for topic,targets in [('outer',['first_pack','front_pack2']),('pace',['fade3','g3f_rank','time','first_pack']),('stability',['big_slow','slow_loss','absolute_error'])]:
  b=a[a.pace_eligible] if topic=='pace' else a[a.H1_time.notna()] if topic=='stability' else a
  periods=[('2024_2025',b[b.year.between(2024,2025)]),('2026',b[b.year.eq(2026)])]
  if topic!='stability':periods=[('all',b)]+periods
  for period,g in periods:
   batches={}
   for target in targets:
    mask=g[target].notna();batches.setdefault(mask.to_numpy().tobytes(),(mask,[]))[1].append(target)
   for mask,tt in batches.values():
    rr,mm,ff=fit(g.loc[mask].copy(),tt,topic,period);rows+=rr;models+=mm;fitted+=ff
   exposure='outer' if topic=='outer' else 'pressure' if topic=='pace' else None
   strata=[('all',g)]
   if topic=='pace':strata += [('prior_front',g[g.own_prior_front.eq(1)]),('actual_c4_front',g[g.c4_zone.eq('front')]),('coverage100',g[g.HIST_coverage.eq(1)])]
   for subset,z in strata:
    for (j,name),v in z.groupby(['jockey_id','jockey_display_name']):
     for label,w in [(True,v[v[exposure]]),(False,v[~v[exposure]])] if exposure else [(True,v)]:
      if not len(w):continue
      row={'topic':topic,'period':period,'subset':subset,'jockey_id':j,'name':name,'context':label,'starts':len(w),'horses':w.horse_id.nunique(),'days':w.race_date.nunique()}
      for target in targets:row[target+'_n']=int(w[target].notna().sum());row[target+'_mean']=w[target].mean()
      if topic=='stability':
       for th in [1.,1.5,2.]:row['slow_gt'+str(th)+'_pct']=100*w.H1_slow_error.gt(th).mean()
      raw.append(row)
 result=pd.DataFrame(rows);result['BH_q']=np.nan
 for _,g in result.groupby(['topic',result.period.eq('all')]):result.loc[g.index,'BH_q']=bh(g.date_p)
 result['direction_supported']=result.support&result.BH_q.lt(.05)&((result.date_low.gt(0)&result.horse_low.gt(0))|(result.date_high.lt(0)&result.horse_high.lt(0)))
 result.to_csv(out/'jockey_effects.csv',index=False,encoding='utf-8-sig');pd.DataFrame(raw).to_csv(out/'raw_results.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models);pd.concat(fitted).to_csv(out/'fitted.csv',index=False,encoding='utf-8-sig')
 print('Recent supported contrasts',result[result.period.ne('all')&result.direction_supported][['topic','period','target','contrast','name','effect','BH_q']].to_string(index=False),flush=True)
if __name__=='__main__':main()
