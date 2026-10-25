"""Fixed chronological probability experiments and matched grade diagnostics."""
from pathlib import Path
import json,hashlib,math,warnings
import numpy as np,pandas as pd,lightgbm as lgb
from scipy.stats import t,false_discovery_control
from sklearn.metrics import roc_auc_score,average_precision_score
import data
warnings.filterwarnings('ignore',category=pd.errors.PerformanceWarning)
H=data.H;O=data.O;M=data.M;PARAMS=dict(learning_rate=.04,num_leaves=15,min_data_in_leaf=150,lambda_l2=10.,verbosity=-1,num_threads=1,seed=42,deterministic=True,force_col_wise=True)
def dump(p,x):data.dump(p,x)
def variance(q,score):
 vals=[];counts=[]
 for ids in [q.horse_id,q.date.dt.strftime('%Y-%m-%d'),q.horse_id+':'+q.date.dt.strftime('%Y-%m-%d')]:
  code=pd.factorize(ids)[0];n=int(code.max()+1);s=np.bincount(code,weights=score);vals.append(float(s@s)*n/(n-1));counts.append(n)
 return math.sqrt(max(0,vals[0],vals[1],vals[0]+vals[1]-vals[2])),float(t.ppf(.975,min(counts[:2])-1))
def mean_ci(q,v):
 v=np.asarray(v,float);est=float(v.mean());se,crit=variance(q,(v-est)/len(q));return dict(estimate=est,se=se,lower=est-crit*se,upper=est+crit*se,n=len(q),horses=q.horse_id.nunique(),dates=q.date.nunique(),races=q.source_key.nunique())
def fit(q,x,cols,target,year,name):
 mask=q.year.lt(year)&(q.role4.ge(0) if target=='early' else q[target].notna());y=q.loc[mask,'role4' if target=='early' else target].to_numpy();params=PARAMS|dict(objective='multiclass' if target=='early' else 'binary');params.update(num_class=4) if target=='early' else None
 model=lgb.train(params,lgb.Dataset(x.loc[mask,cols],label=y,free_raw_data=True),num_boost_round=180);filename=f'{year}_{target}_{name}';model.save_model(str(M/(filename+'.txt')))
 meta=dict(year=year,target=target,feature_group=name,features=cols,n=int(mask.sum()),train_end=str(q.loc[mask,'date'].max().date()),params=params,iterations=180,training_row_keys_sha256=hashlib.sha256('\n'.join(q.loc[mask,'row_key']).encode()).hexdigest());dump(M/(filename+'.json'),meta);print('fit',filename,int(mask.sum()),len(cols),flush=True);return model
def baseline(train,test):
 globalp=np.bincount(train.role4,minlength=4)/len(train);dist={key:np.bincount(g.role4,minlength=4)/len(g) for key,g in train.groupby(['meet','distance_m'])};fields={key:np.bincount(g.role4,minlength=4) for key,g in train.groupby(['meet','distance_m','field_size'])};out=[]
 for row in test.itertuples():
  b=dist.get((row.meet,row.distance_m),globalp);c=fields.get((row.meet,row.distance_m,row.field_size),np.zeros(4));out.append((c+20*b)/(sum(c)+20))
 return np.asarray(out)
def predictions(q,x,groups):
 early=[];binary=[];models2026={}
 for year in [2024,2025,2026]:
  te=q.year.eq(year);basecols=['row_key','source_key','horse_id','horse_name','meet','date','year','distance_m','grade_normalized','grade_bucket','grade_num','age_current','gate','field_size','role4','supported5','strong5','mode5','past_total','group_mean_relative','finish_p']
  r=q.loc[te,basecols].copy();observed=r.role4.ge(0);base=baseline(q[q.year.lt(year)&q.role4.ge(0)],r);hist=q.loc[te,[f'count5_{j}' for j in range(4)]].to_numpy();hp=(hist+3*base)/(q.loc[te,'valid_position5'].to_numpy()[:,None]+3)
  for name,probs in [('B',base),('H',hp)]:
   for j in range(4):r[name+'_p'+str(j)]=probs[:,j]
  for name in (['P','S','F','J'] if year<2026 else ['S','J']):
   model=fit(q,x,groups[name],'early',year,name);probs=model.predict(x.loc[te,groups[name]],num_threads=1)
   for j in range(4):r[name+'_p'+str(j)]=probs[:,j]
   if year==2026:models2026['early_'+name]=model
  early.append(r[observed] if year<2026 else r)
  for target in ['recovery','fade']:
   z=q.loc[te,basecols].copy();z['target']=q.loc[te,target];z['task']=target
   for name in (['P','J'] if year<2026 else ['J']):
    model=fit(q,x,groups[name],target,year,name);z['p_'+name]=model.predict(x.loc[te,groups[name]],num_threads=1)
    if year==2026:models2026[target+'_'+name]=model
   binary.append(z[z.target.notna()] if year<2026 else z)
 earlyp=pd.concat(early[:2],ignore_index=True);earlyp.to_parquet(O/'early_predictions.parquet',index=False);binaryp=pd.concat([g for g in binary if g.year.iloc[0]<2026],ignore_index=True);binaryp.to_parquet(O/'late_predictions.parquet',index=False)
 # Last actual card on each venue's last source date; no selection by predicted or realized success.
 end=q.groupby('meet').date.max();chosen=[]
 for meet,date in end.items():
  keys=q[q.meet.eq(meet)&q.date.eq(date)].source_key.unique();key=max(keys,key=lambda s:int(s.rsplit(':',1)[1]));chosen.append(key)
 e=early[-1];cards=e[e.source_key.isin(chosen)].copy();z2026=pd.concat([g for g in binary if g.year.iloc[0]==2026],ignore_index=True)
 for target in ['recovery','fade']:
  z=z2026[z2026.task.eq(target)];cards[target+'_p']=cards.row_key.map(z.set_index('row_key').p_J);cards[target+'_actual']=cards.row_key.map(z.set_index('row_key').target)
 contextcols=['row_key','jockey_name','trainer_name','jockey_lead_rate','trainer_lead_rate','jockey_conditional_front','trainer_conditional_front','early_mean5','early_adv_mean5','last600_adv_mean5','late_cond_adv_mean5','valid_position5','early_n5','field_lead_sum_other','field_strong_front_other','field_gap_fastest_raw','field_coverage_early_mean5']
 cards=cards.merge(q[contextcols],on='row_key',validate='one_to_one').sort_values(['source_key','gate']);cards.to_csv(O/'example_cards.csv',index=False);dump(O/'example_selection.json',dict(rule='Last race number on each venue last available date; no outcome selection',races=chosen,model_train_year_max=2025,main_evaluation=False,actually_published_prerace=False));return earlyp,binaryp
def early_metrics(p):
 rows=[];differences=[];cal=[];race_rows=[]
 for window in ['2024','2025','2024_2025']:
  z=p if window=='2024_2025' else p[p.year.eq(int(window))]
  for scope in ['all','supported5']:
   q=z[z.supported5] if scope=='supported5' else z;y=np.eye(4)[q.role4.to_numpy()];loss={}
   for name in ['B','H','P','S','F','J']:
    pred=q[[name+'_p'+str(j) for j in range(4)]].to_numpy();assert np.isfinite(pred).all() and np.min(pred)>=0;np.testing.assert_allclose(pred.sum(axis=1),1,atol=1e-12);brier=((pred-y)**2).sum(axis=1);loss[name]=brier
    rows.append(dict(window=window,scope=scope,model=name,n=len(q),horses=q.horse_id.nunique(),races=q.source_key.nunique(),accuracy=float((pred.argmax(axis=1)==q.role4).mean()),brier=float(brier.mean()),logloss=float(-np.log(pred[np.arange(len(q)),q.role4]).mean())))
   for ext,base in [('S','P'),('F','S'),('J','F'),('J','S')]:differences.append(dict(window=window,scope=scope,comparison=ext+'-'+base)|mean_ci(q,loss[ext]-loss[base]))
  if window=='2024_2025':
   for grade,g in z.groupby('grade_bucket'):
    yy=np.eye(4)[g.role4.to_numpy()];losses={}
    for name in ['H','S','J']:
     probs=g[[name+'_p'+str(j) for j in range(4)]].to_numpy();losses[name]=((probs-yy)**2).sum(axis=1);rows.append(dict(window='grade:'+grade,scope='all',model=name,n=len(g),horses=g.horse_id.nunique(),races=g.source_key.nunique(),accuracy=float((probs.argmax(axis=1)==g.role4).mean()),brier=float(losses[name].mean()),logloss=float(-np.log(probs[np.arange(len(g)),g.role4]).mean())))
    differences.append(dict(window='grade:'+grade,scope='all',comparison='J-S')|mean_ci(g,losses['J']-losses['S']))
   for name in ['H','S','J']:
    for j in range(4):
     probs=z[name+'_p'+str(j)];bins=np.minimum((probs*10).astype(int),9)
     for bn,g in z.groupby(bins):cal.append(dict(task='early',model=name,class_id=j,bin=int(bn),n=len(g),predicted=float(g[name+'_p'+str(j)].mean()),actual=float(g.role4.eq(j).mean())))
 for name in ['H','P','S','F','J']:
  for key,g in p.groupby('source_key'):
   # Race-level targets require every starter's observed early group. Incomplete races
   # remain in per-horse metrics, but cannot supply an observed total leader count.
   if len(g)!=g.field_size.iloc[0]:continue
   best=g.sort_values([name+'_p0','gate'],ascending=[False,True]).iloc[0];race_rows.append(dict(model=name,source_key=key,meet=g.meet.iloc[0],date=str(g.date.iloc[0].date()),field_size=len(g),top_horse=best.horse_id,top_in_first_group=bool(best.role4==0),predicted_leader_count=float(g[name+'_p0'].sum()),actual_leader_count=int(g.role4.eq(0).sum())))
 df=pd.DataFrame(differences);mask=df.window.eq('2024_2025')&df.scope.eq('all');pv=2*t.sf(abs(df.loc[mask,'estimate']/df.loc[mask,'se']),df.loc[mask,'dates']-1);df.loc[mask,'bh_q_four_comparisons']=false_discovery_control(pv)
 pd.DataFrame(rows).to_csv(O/'early_metrics.csv',index=False);df.to_csv(O/'early_comparisons.csv',index=False);pd.DataFrame(cal).to_csv(O/'early_calibration.csv',index=False);rr=pd.DataFrame(race_rows);rr.to_parquet(O/'race_predictions.parquet',index=False);rr.groupby('model').agg(races=('source_key','size'),top_first_group_hit=('top_in_first_group','mean'),leader_count_mae=('predicted_leader_count',lambda x:float(np.nan))).reset_index().drop(columns='leader_count_mae').merge(rr.assign(error=abs(rr.predicted_leader_count-rr.actual_leader_count)).groupby('model').error.mean().rename('leader_count_mae').reset_index(),on='model').to_csv(O/'race_metrics.csv',index=False)
def late_metrics(p):
 rows=[];diff=[];cal=[]
 for task,pp in p.groupby('task'):
  for window in ['2024','2025','2024_2025']:
   q=pp if window=='2024_2025' else pp[pp.year.eq(int(window))];y=q.target.to_numpy()
   for name in ['P','J']:
    pred=q['p_'+name].to_numpy();lo,hi=np.quantile(pred,[.2,.8]);low=pred<=lo;high=pred>=hi;rows.append(dict(task=task,window=window,model=name,n=len(q),horses=q.horse_id.nunique(),prevalence=float(y.mean()),brier=float(np.mean((pred-y)**2)),auc=float(roc_auc_score(y,pred)),average_precision=float(average_precision_score(y,pred)),low20_n=int(low.sum()),low20_rate=float(y[low].mean()),high20_n=int(high.sum()),high20_rate=float(y[high].mean())))
    if window=='2024_2025':
     for bn,g in q.groupby(np.minimum((q['p_'+name]*10).astype(int),9)):cal.append(dict(task=task,model=name,bin=int(bn),n=len(g),predicted=float(g['p_'+name].mean()),actual=float(g.target.mean())))
   diff.append(dict(task=task,window=window,comparison='J-P')|mean_ci(q,(q.p_J-q.target)**2-(q.p_P-q.target)**2))
 pd.DataFrame(rows).to_csv(O/'late_metrics.csv',index=False);pd.DataFrame(diff).to_csv(O/'late_comparisons.csv',index=False);pd.DataFrame(cal).to_csv(O/'late_calibration.csv',index=False)
def grade_diagnostics(q,p):
 z=q[q.year.isin([2024,2025])&q.group_observed&q.supported5].copy();z['repeat']=z.role4.eq(z.mode5);z['entropy5']=0.
 for j in range(4):
  rate=z['rate5_'+str(j)];z['entropy5']-=np.where(rate>0,rate*np.log(np.maximum(rate,1e-12)),0)
 z.groupby('grade_bucket').agg(n=('row_key','size'),horses=('horse_id','nunique'),strong5_rate=('strong5','mean'),mode_repeat=('repeat','mean'),entropy5=('entropy5','mean'),past_total=('past_total','mean')).reset_index().to_csv(O/'grade_repeatability.csv',index=False)
 z=z[z.grade_num.isin([1,2,5,6])].copy();z['high']=z.grade_num.le(2);z['experience_bin']=pd.cut(z.past_total,[4,9,19,np.inf],labels=['5_9','10_19','20plus']).astype(str);z['age_bin']=np.where(z.age_current.le(3),'2_3','4plus');cols=['meet','distance_m','year','experience_bin','age_bin'];counts=z.groupby(cols+['high']).size().unstack(fill_value=0);valid=counts[(counts[True]>=20)&(counts[False]>=20)].copy();valid['overlap_weight']=2*valid[True]*valid[False]/(valid[True]+valid[False]);valid=valid.reset_index();valid.to_csv(O/'grade_matched_cells.csv',index=False);z=z.merge(valid[cols+['overlap_weight']],on=cols,validate='many_to_one');cellweight=z.overlap_weight/valid.overlap_weight.sum();n=z.groupby(cols+['high']).row_key.transform('size');z['contrast_weight']=np.where(z.high,1.,-1.)*cellweight/n;results=[]
 for target in ['strong5','repeat']:
  v=z[target].astype(float);w=z.contrast_weight;est=float(w@v);hi=float((w[z.high]*v[z.high]).sum());lo=float((-w[~z.high]*v[~z.high]).sum());se,crit=variance(z,w*(v-np.where(z.high,hi,lo)));results.append(dict(target=target,cells=len(valid),high_mean=hi,low_mean=lo,estimate=est,se=se,lower=est-crit*se,upper=est+crit*se,n=len(z),high_n=int(z.high.sum()),low_n=int((~z.high).sum()),horses=z.horse_id.nunique(),dates=z.date.nunique()))
 result=pd.DataFrame(results);result['bh_q_two_comparisons']=false_discovery_control(2*t.sf(abs(result.estimate/result.se),result.dates-1));result.to_csv(O/'grade_matched_comparisons.csv',index=False);z.to_parquet(O/'grade_matched_rows.parquet',index=False)
def main():
 assert not (O/'early_predictions.parquet').exists(),'Refusing to overwrite completed predictions'
 q=pd.read_parquet(O/'feature_context.parquet');x=pd.read_parquet(O/'feature_frame.parquet');_,groups=data.features(q);dump(O/'feature_groups.json',groups);ep,lp=predictions(q,x,groups);early_metrics(ep);late_metrics(lp);grade_diagnostics(q,ep);print('Completed field probability experiments',flush=True)
if __name__=='__main__':main()
