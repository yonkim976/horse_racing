"""Annual frozen comparisons for rider distance, recent form and trainer partnerships."""
from datetime import date,timedelta
import warnings
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix,hstack
from scipy.stats import norm
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler,OneHotEncoder
from sklearn.linear_model import Ridge,LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from data import HERE,OLD,NUM,CAT,save
from effects import bh
B=4000;SEED=20261009
FORM=[f'r{d}_{c}' for d in [90,180,365] for c in ['time_adv','top3_excess','n']]

def fit_predict(tr,te,nums,cats,year,model):
 imp=SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True);sc=StandardScaler();xn=sc.fit_transform(imp.fit_transform(tr[nums]));tn=sc.transform(imp.transform(te[nums]));enc=OneHotEncoder(handle_unknown='ignore',sparse_output=True)
 X=hstack([csr_matrix(xn),enc.fit_transform(tr[cats].astype(str))],format='csr');T=hstack([csr_matrix(tn),enc.transform(te[cats].astype(str))],format='csr');w=(1/tr.groupby('race_id').api_record_id.transform('size')).to_numpy();w=w/w.mean()
 ridge=Ridge(alpha=20,solver='lsqr',tol=1e-9,max_iter=3000);ridge.fit(X,tr.relative_time,sample_weight=w);raw=ridge.predict(T);ptime=raw-pd.Series(raw,index=te.index).groupby(te.race_id).transform('mean').to_numpy()
 logistic=LogisticRegression(C=.3,solver='lbfgs',max_iter=3000,tol=1e-6)
 with warnings.catch_warnings(record=True) as caught:
  warnings.simplefilter('always',ConvergenceWarning);logistic.fit(X,tr.top3.astype(int),sample_weight=w)
 assert not any(issubclass(v.category,ConvergenceWarning) for v in caught)
 prob=logistic.predict_proba(T)[:,1]
 spec={'year':year,'model':model,'cutoff':(date(year,1,1)-timedelta(days=2)).isoformat(),'numeric_columns':nums,'imputation':imp.statistics_.tolist(),'indicators':imp.indicator_.features_.tolist(),'scaled_columns':imp.get_feature_names_out(nums).tolist(),'mean':sc.mean_.tolist(),'scale':sc.scale_.tolist(),'categorical_columns':cats,'categories':[v.tolist() for v in enc.categories_],'ridge_coef':ridge.coef_.tolist(),'ridge_intercept':float(ridge.intercept_),'logistic_coef':logistic.coef_[0].tolist(),'logistic_intercept':float(logistic.intercept_[0]),'train_rows':len(tr),'train_last':tr.race_date.max(),'eval_rows':len(te),'ridge_iterations':int(ridge.n_iter_[0]),'logistic_iterations':int(logistic.n_iter_[0])}
 return ptime,prob,spec

def form_inputs(a,out):
 past=[];pars=[]
 for year in range(2018,2024):
  cutoff=(date(year,1,1)-timedelta(days=2)).isoformat();tr=a[a.race_date.le(cutoff)];te=a[a.year.eq(year)]
  tm,pr,sp=fit_predict(tr,te,NUM,CAT,year,'H0_history');z=te[['api_record_id','race_id','race_date','year','jockey_id','top3','relative_time']].copy();z['time_prediction']=tm;z['prob_top3']=pr;past.append(z);pars.append(sp)
  print('Historical H0 frozen',year,len(te),flush=True)
 old=pd.read_csv(OLD/'forecast01/predictions.csv',dtype={'jockey_id':str});old=old[old.model.eq('H0')][['api_record_id','race_id','race_date','year','jockey_id','top3','relative_time','time_prediction','prob_top3']]
 p=pd.concat(past+[old],ignore_index=True).sort_values('race_date');p['time_adv']=p.time_prediction-p.relative_time;p['top3_excess']=p.top3-p.prob_top3
 p.to_csv(out/'past_H0_residuals.csv',index=False,encoding='utf-8-sig');save(out/'past_H0_parameters.json',pars)
 rows=[]
 for ds in sorted(a.race_date.unique()):
  cutoff=pd.Timestamp(ds)-pd.Timedelta(days=2)
  for days,minimum in [(90,20),(180,40),(365,80)]:
   lo=(cutoff-pd.Timedelta(days=days-1)).strftime('%Y-%m-%d');hi=cutoff.strftime('%Y-%m-%d')
   g=p[p.race_date.between(lo,hi)].groupby('jockey_id').agg(n=('api_record_id','size'),time_adv=('time_adv','mean'),top3_excess=('top3_excess','mean'),last_date=('race_date','max'))
   for j,r in g.iterrows():rows.append({'race_date':ds,'jockey_id':j,'window':days,'n':int(r.n),'time_adv':r.time_adv*r.n/(r.n+50) if r.n>=minimum else np.nan,'top3_excess':r.top3_excess*r.n/(r.n+50) if r.n>=minimum else np.nan,'window_start':lo,'cutoff':hi,'last_date':r.last_date,'eligible':bool(r.n>=minimum)})
 f=pd.DataFrame(rows);assert f.last_date.le(f.cutoff).all();f.to_csv(out/'form_windows.csv',index=False,encoding='utf-8-sig')
 for days in [90,180,365]:
  z=f[f.window.eq(days)][['race_date','jockey_id','time_adv','top3_excess','n']].rename(columns={c:f'r{days}_{c}' for c in ['time_adv','top3_excess','n']})
  a=a.merge(z,on=['race_date','jockey_id'],how='left',validate='many_to_one');a[f'r{days}_n']=a[f'r{days}_n'].fillna(0)
 a.to_csv(out/'features_with_form.csv',index=False,encoding='utf-8-sig');return a

def interval(g,key):
 w=1/g.groupby('race_id').api_record_id.transform('size');z=pd.DataFrame({'key':g[key],'num':g.delta*w,'den':w}).groupby('key')[['num','den']].sum().to_numpy();rng=np.random.default_rng(SEED);draw=[]
 for start in range(0,B,200):
  weights=rng.multinomial(len(z),np.full(len(z),1/len(z)),size=min(200,B-start));draw.extend((weights@z[:,0])/(weights@z[:,1]))
 lo,hi=np.quantile(draw,[.025,.975]);value=float(z[:,0].sum()/z[:,1].sum());sd=np.std(draw,ddof=1);p=float(2*norm.sf(abs(value/sd))) if sd else 1.
 return value,float(lo),float(hi),p

def main():
 out=HERE/'forecast01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input02/starts.csv',dtype={'horse_id':str,'jockey_id':str,'trainer_id':str},low_memory=False);a=form_inputs(a,out)
 config={'H1':(NUM,CAT+['jockey_id']),'D1':(NUM,CAT+['jockey_id','jockey_distance']),'R1':(NUM+FORM,CAT+['jockey_id']),'H2':(NUM,CAT+['horse_id','jockey_id','trainer_id']),'T1':(NUM,CAT+['horse_id','jockey_id','trainer_id','trainer_jockey'])}
 preds=[];parameters=[]
 for year in [2024,2025,2026]:
  cutoff=(date(year,1,1)-timedelta(days=2)).isoformat();tr=a[a.race_date.le(cutoff)];te=a[a.year.eq(year)]
  for model,(nums,cats) in config.items():
   tm,pr,sp=fit_predict(tr,te,nums,cats,year,model);z=te[['api_record_id','race_id','race_date','horse_id','jockey_id','jockey_display_name','trainer_id','trainer_name','year','race_distance_m','relative_time','top3']].copy();z['model']=model;z['time_prediction']=tm;z['prob_top3']=pr;preds.append(z);parameters.append(sp)
   if model in ['H1','H2']:assert np.allclose(te[model+'_time'],tm,atol=1e-7) and np.allclose(te[model+'_prob'],pr,atol=1e-7)
  print('Context forecast frozen',year,len(te),flush=True)
 p=pd.concat(preds,ignore_index=True);p.to_csv(out/'predictions.csv',index=False,encoding='utf-8-sig');save(out/'parameters.json',parameters)
 p['mae']=(p.time_prediction-p.relative_time).abs();p['mse']=(p.time_prediction-p.relative_time)**2;p['logloss']=-(p.top3*np.log(p.prob_top3)+(1-p.top3)*np.log1p(-p.prob_top3));p['brier']=(p.prob_top3-p.top3)**2
 metrics=[];contrasts=[];cells=[]
 for period,g in [('2024_2025',p[p.year.le(2025)]),('2026',p[p.year.eq(2026)])]:
  for model,z in g.groupby('model'):
   v=z.groupby('race_id')[['mae','mse','logloss','brier']].mean().mean();metrics.append({'period':period,'model':model,'starts':len(z),'races':z.race_id.nunique(),'mae_s':v.mae,'rmse_s':np.sqrt(v.mse),'logloss':v.logloss,'brier':v.brier})
  for before,after in [('H1','D1'),('H1','R1'),('H2','T1')]:
   for metric in ['mae','logloss']:
    z=g[g.model.eq(before)][['api_record_id','race_id','race_date','horse_id',metric]].merge(g[g.model.eq(after)][['api_record_id',metric]],on='api_record_id',validate='one_to_one',suffixes=('_old','_new'));z['delta']=z[metric+'_new']-z[metric+'_old'];value,lo,hi,pv=interval(z,'race_date');_,hl,hh,_=interval(z,'horse_id')
    contrasts.append({'period':period,'comparison':after+'-'+before,'metric':metric,'starts':len(z),'races':z.race_id.nunique(),'delta':value,'date_low':lo,'date_high':hi,'horse_low':hl,'horse_high':hh,'date_p':pv})
  for kind,model,keys in [('distance','H1',['jockey_id','jockey_display_name','race_distance_m']),('trainer_jockey','H2',['trainer_id','trainer_name','jockey_id','jockey_display_name'])]:
   z=g[g.model.eq(model)].copy();z['time_adv']=z.time_prediction-z.relative_time
   for kk,v in z.groupby(keys):cells.append({'period':period,'kind':kind,**dict(zip(keys,kk)),'starts':len(v),'horses':v.horse_id.nunique(),'days':v.race_date.nunique(),'raw_top3':v.top3.mean(),'expected_top3':v.prob_top3.mean(),'time_adv_s':v.time_adv.mean(),'display_support':bool(len(v)>=50 and v.horse_id.nunique()>=15 and v.race_date.nunique()>=10)})
 c=pd.DataFrame(contrasts);c['BH_q']=bh(c.date_p);c['supported_improvement']=c.BH_q.lt(.05)&c.date_high.lt(0)&c.horse_high.lt(0)
 pd.DataFrame(metrics).to_csv(out/'metrics.csv',index=False,encoding='utf-8-sig');c.to_csv(out/'comparisons.csv',index=False,encoding='utf-8-sig');pd.DataFrame(cells).to_csv(out/'distance_and_partnership_cells.csv',index=False,encoding='utf-8-sig')
 print(c.to_string(index=False),flush=True)
if __name__=='__main__':main()
