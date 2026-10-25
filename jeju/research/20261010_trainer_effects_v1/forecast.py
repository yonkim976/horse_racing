"""Annual frozen trainer identity ablations, with and without horse identity."""
from datetime import date,timedelta
import warnings
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix,hstack
from scipy.stats import norm,spearmanr
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler,OneHotEncoder
from sklearn.linear_model import Ridge,LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from data import HERE,ROOT,OLD,save,NUM,CAT
from effects import bh
CONFIG={'T1':['jockey_id','trainer_id'],'HJ':['horse_id','jockey_id']}
B=4000;SEED=20261010
def interval(g,key):
 weights=1/g.groupby('race_id').api_record_id.transform('size');z=pd.DataFrame({'key':g[key],'num':g.delta*weights,'den':weights}).groupby('key')[['num','den']].sum().to_numpy()
 rng=np.random.default_rng(SEED);draw=[]
 for start in range(0,B,200):
  w=rng.multinomial(len(z),np.full(len(z),1/len(z)),size=min(200,B-start));draw.extend((w@z[:,0])/(w@z[:,1]))
 val=float(z[:,0].sum()/z[:,1].sum());lo,hi=np.quantile(draw,[.025,.975]);se=float(np.std(draw,ddof=1));p=float(2*norm.sf(abs(val/se))) if se else 1.
 return val,float(lo),float(hi),p
def main():
 out=HERE/'forecast01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/starts.csv',dtype={'horse_id':str,'jockey_id':str,'trainer_id':str},low_memory=False)
 cols=['api_record_id','race_id','race_date','year','horse_id','jockey_id','relative_time','top3','field_n','race_distance_m']
 old=pd.read_csv(OLD/'forecast01/predictions.csv',dtype={'horse_id':str,'jockey_id':str});preds=[old[old.model.isin(['H1','H2'])][cols+['model','time_prediction','prob_top3']].copy()];parameters=[];audit=[]
 for year in [2024,2025,2026]:
  cutoff=(date(year,1,1)-timedelta(days=2)).isoformat();tr=a[a.race_date.le(cutoff)];te=a[a.year.eq(year)].copy()
  imp=SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True);sc=StandardScaler();xnum=sc.fit_transform(imp.fit_transform(tr[NUM]));tnum=sc.transform(imp.transform(te[NUM]))
  w=(1/tr.groupby('race_id').api_record_id.transform('size')).to_numpy();w=w/w.mean()
  for model,ids in CONFIG.items():
   cats=CAT+ids;enc=OneHotEncoder(handle_unknown='ignore',sparse_output=True);xc=enc.fit_transform(tr[cats].astype(str));tc=enc.transform(te[cats].astype(str));X=hstack([csr_matrix(xnum),xc],format='csr');T=hstack([csr_matrix(tnum),tc],format='csr')
   ridge=Ridge(alpha=20,solver='lsqr',tol=1e-9,max_iter=3000);ridge.fit(X,tr.relative_time,sample_weight=w);rawtime=ridge.predict(T);ptime=rawtime-pd.Series(rawtime,index=te.index).groupby(te.race_id).transform('mean').to_numpy()
   lr=LogisticRegression(C=.3,solver='lbfgs',max_iter=3000,tol=1e-6)
   with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter('always',ConvergenceWarning);lr.fit(X,tr.top3.astype(int),sample_weight=w)
   assert not any(issubclass(c.category,ConvergenceWarning) for c in caught)
   prob=lr.predict_proba(T)[:,1];assert np.isfinite(ptime).all() and ((prob>0)&(prob<1)).all()
   z=te[cols].copy();z['model']=model;z['time_prediction']=ptime;z['prob_top3']=prob;preds.append(z)
   parameters.append({'year':year,'model':model,'cutoff':cutoff,'numeric_columns':NUM,'imputation':imp.statistics_.tolist(),'indicators':imp.indicator_.features_.tolist(),'scaled_columns':imp.get_feature_names_out(NUM).tolist(),'mean':sc.mean_.tolist(),'scale':sc.scale_.tolist(),'categorical_columns':cats,'categories':[v.tolist() for v in enc.categories_],'ridge_coef':ridge.coef_.tolist(),'ridge_intercept':float(ridge.intercept_),'logistic_coef':lr.coef_[0].tolist(),'logistic_intercept':float(lr.intercept_[0])})
   audit.append({'year':year,'model':model,'train_rows':len(tr),'train_races':tr.race_id.nunique(),'train_last':tr.race_date.max(),'cutoff':cutoff,'eval_rows':len(te),'eval_races':te.race_id.nunique(),'ridge_iterations':int(ridge.n_iter_[0]),'logistic_iterations':int(lr.n_iter_[0]),'no_convergence_warning':True})
  print('Trainer forecasts fitted',year,len(te),flush=True)
 pr=pd.concat(preds,ignore_index=True);pr.to_csv(out/'predictions.csv',index=False,encoding='utf-8-sig');save(out/'parameters.json',parameters);save(out/'fit_audit.json',audit)
 pr['mae']=(pr.time_prediction-pr.relative_time).abs();pr['mse']=(pr.time_prediction-pr.relative_time)**2;pr['logloss']=-(pr.top3*np.log(pr.prob_top3)+(1-pr.top3)*np.log1p(-pr.prob_top3));pr['brier']=(pr.prob_top3-pr.top3)**2
 metrics=[];contrasts=[]
 for period,z in [('2024_2025',pr[pr.year.le(2025)]),('2026',pr[pr.year.eq(2026)])]:
  for model,g in z.groupby('model'):
   rs=g.groupby('race_id')[['mae','mse','logloss','brier']].mean().mean();metrics.append({'period':period,'model':model,'starts':len(g),'races':g.race_id.nunique(),'days':g.race_date.nunique(),'mae_s':rs.mae,'rmse_s':np.sqrt(rs.mse),'logloss':rs.logloss,'brier':rs.brier})
  for before,after in [('H1','T1'),('HJ','H2')]:
   for metric in ['mae','logloss']:
    g=z[z.model.eq(before)][['api_record_id','race_id','race_date','horse_id',metric]].merge(z[z.model.eq(after)][['api_record_id',metric]],on='api_record_id',suffixes=('_old','_new'),validate='one_to_one');g['delta']=g[metric+'_new']-g[metric+'_old']
    mean,lo,hi,p=interval(g,'race_date');_,hl,hh,_=interval(g,'horse_id');contrasts.append({'period':period,'comparison':after+'-'+before,'metric':metric,'starts':len(g),'races':g.race_id.nunique(),'delta':mean,'date_low':lo,'date_high':hi,'horse_low':hl,'horse_high':hh,'date_p':p})
 comp=pd.DataFrame(contrasts);comp['BH_q']=bh(comp.date_p);comp['supported_improvement']=comp.BH_q.lt(.05)&comp.date_high.lt(0)&comp.horse_high.lt(0)
 pd.DataFrame(metrics).to_csv(out/'metrics.csv',index=False,encoding='utf-8-sig');comp.to_csv(out/'comparisons.csv',index=False,encoding='utf-8-sig')
 assignment=[];relations=[]
 for period,g in [('2024_2025',a[a.year.between(2024,2025)]),('2026',a[a.year.eq(2026)])]:
  j=g.groupby(['trainer_id','trainer_display_name'],as_index=False).agg(starts=('api_record_id','size'),horses=('horse_id','nunique'),raw_top3=('top3','mean'),expected_top3=('H1_prob','mean'),expected_relative_time=('H1_time','mean'),raw_relative_time=('relative_time','mean'),time_advantage=('H1_time_adv','mean'));j['period']=period;assignment.append(j)
  s=j[j.starts.ge(100)];relations.append({'period':period,'trainers100plus':len(s),'pearson_raw_vs_expected_top3':float(s.raw_top3.corr(s.expected_top3)),'spearman_raw_vs_expected_top3':float(spearmanr(s.raw_top3,s.expected_top3).statistic),'caution':'association, not causal share or unbiased trainer value-added'})
 pd.concat(assignment,ignore_index=True).to_csv(out/'assignment.csv',index=False,encoding='utf-8-sig');save(out/'assignment_relations.json',relations)
 print(pd.DataFrame(metrics).to_string(index=False));print(comp.to_string(index=False),flush=True)
if __name__=='__main__':main()
