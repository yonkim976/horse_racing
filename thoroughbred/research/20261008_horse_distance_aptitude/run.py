"""Chronological distance aptitude experiment with race FE and centered ridge effects."""
from pathlib import Path
import hashlib,json,gzip,math,sys
import numpy as np,pandas as pd
from scipy import sparse
from scipy.sparse.linalg import LinearOperator,cg
from scipy.stats import t
H=Path(__file__).resolve().parent;O=H/'outputs';M=O/'models';M.mkdir(exist_ok=True);ROOT=H.parents[2];P=H.parent/'20261007_sex_ability_gap/outputs/population.parquet'
FORM=['weight','weight_squared','age','age_squared','rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap'];EXTRA=[n+'_missing' for n in FORM];NAMES=FORM+EXTRA;FITS=[]
def dump(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def prepare():
 d=pd.read_parquet(P);assert len(d)==151074 and d.row_key.is_unique and not d.duplicated(['horse_id','date']).any();assert (d.last_history_date.isna()|d.last_history_date.lt(d.date)).all();d=d[d.distance_m.between(1000,1800)].copy();d['age_squared']=d.age**2;d['horse_key']=d.meet+':'+d.horse_id;d['hd_key']=d.horse_key+':'+d.distance_m.astype(str);d['stratum']=d.meet+':'+d.distance_m.astype(str);d['day_key']=d.date.dt.strftime('%Y-%m-%d');d['time1000']=d.finish*1000/d.distance_m;assert len(d)==148126
 rows=[]
 for (meet,horse),q in d.groupby(['meet','horse_id']):
  counts=q.distance_m.value_counts();rows.append(dict(meet=meet,horse_id=horse,n=len(q),distances=len(counts),distances_ge3=int(counts.ge(3).sum()),distances_ge5=int(counts.ge(5).sum()),distances_ge8=int(counts.ge(8).sum()),first_date=str(q.date.min().date()),last_date=str(q.date.max().date())))
 pd.DataFrame(rows).to_csv(O/'horse_coverage.csv',index=False);d.groupby(['meet','distance_m','year']).size().rename('n').reset_index().to_csv(O/'distance_year_coverage.csv',index=False)
 dump(O/'source_audit.json',dict(population_n=151074,eligible_n=len(d),horses=d.horse_id.nunique(),races=d.source_key.nunique(),input_sha256={str(P.relative_to(ROOT)):sha(P)},source_start=d.groupby('meet').date.min().astype(str).to_dict(),source_end=d.groupby('meet').date.max().astype(str).to_dict(),causal=False,operational=False,uses_track_speed=False))
 return d
def center(v,code):
 counts=np.bincount(code)
 if v.ndim==1:return v-np.bincount(code,weights=v)[code]/counts[code]
 means=np.column_stack([np.bincount(code,weights=v[:,j])/counts for j in range(v.shape[1])]);return v-means[code]
def specification(q,lam,name):
 stats={};strata=sorted(q.stratum.unique());rc=pd.factorize(q.source_key)[0];within=center(q.time1000.to_numpy(),rc)
 for key in strata:
  mask=q.stratum.eq(key);qq=q[mask];cols=[];med=[];means=[];sds=[]
  for col in FORM:
   a=qq[col].to_numpy(float);miss=~np.isfinite(a);median=float(np.nanmedian(a)) if not miss.all() else 0.;a=np.where(miss,median,a);med.append(median);cols.append(a)
  cols +=[(~np.isfinite(qq[col].to_numpy(float))).astype(float) for col in FORM];a=np.column_stack(cols);means=a.mean(axis=0);sds=a.std(axis=0);sds=np.where(sds>1e-8,sds,1.)
  scale=float(np.std(within[mask]));assert scale>0 and len(qq)>=200
  stats[key]=dict(medians=med,means=means.tolist(),sds=sds.tolist(),scale=scale,n=len(qq))
 horses=sorted(q.horse_key.unique());hd=sorted(q.hd_key.unique()) if lam is not None else [];hc=pd.Index(horses).get_indexer(q.horse_key);dc=pd.Index(hd).get_indexer(q.hd_key) if hd else np.array([],int);weights=[];owners=[]
 if hd:
  counts=np.bincount(dc,minlength=len(hd));hn=np.bincount(hc,minlength=len(horses));owners=pd.Index(horses).get_indexer(pd.Series(hd).str.rsplit(':',n=1).str[0]).tolist();weights=(counts/hn[owners]).tolist()
 return dict(name=name,train_end=str(q.date.max().date()),train_year_max=int(q.year.max()),n=len(q),strata=strata,statistics=stats,form=FORM,names=NAMES,horses=horses,horse_distances=hd,hd_owner=owners,hd_weight=weights,lambda_horse=10.,lambda_control=1.,lambda_distance=lam,relative_scale='within-race time1000 SD, training-only')
def matrix(q,sp):
 n=len(q);k=len(NAMES);ns=len(sp['strata']);hc=pd.Index(sp['horses']).get_indexer(q.horse_key);sc=pd.Index(sp['strata']).get_indexer(q.stratum);assert (sc>=0).all();a=np.zeros((n,k));scale=np.zeros(n)
 for i,key in enumerate(sp['strata']):
  mask=sc==i;qq=q.loc[mask];st=sp['statistics'][key];values=[]
  for j,col in enumerate(FORM):
   v=qq[col].to_numpy(float);values.append(np.where(np.isfinite(v),v,st['medians'][j]))
  values +=[(~np.isfinite(qq[col].to_numpy(float))).astype(float) for col in FORM];a[mask]=(np.column_stack(values)-st['means'])/st['sds'];scale[mask]=st['scale']
 cx=sparse.csr_matrix((a.ravel(),(np.repeat(np.arange(n),k),np.repeat(sc*k,k)+np.tile(np.arange(k),n))),shape=(n,ns*k));mask=hc>=0;bx=sparse.csr_matrix((np.ones(mask.sum()),(np.arange(n)[mask],hc[mask])),shape=(n,len(sp['horses'])));blocks=[cx,bx]
 if sp['horse_distances']:
  dc=pd.Index(sp['horse_distances']).get_indexer(q.hd_key);known=dc>=0;dx=sparse.csr_matrix((np.ones(known.sum()),(np.arange(n)[known],dc[known])),shape=(n,len(sp['horse_distances'])));w=sparse.csr_matrix((sp['hd_weight'],(sp['hd_owner'],np.arange(len(sp['horse_distances'])))),shape=(len(sp['horses']),len(sp['horse_distances'])));known_b=bx.multiply(known[:,None]);blocks.append(dx-known_b@w)
 x=sparse.hstack(blocks,format='csr');x.eliminate_zeros();return x,scale
def fit(q,lam,name):
 if '--resume' in sys.argv and (M/(name+'.json')).exists() and (M/(name+'.npz')).exists():
  sp=json.loads((M/(name+'.json')).read_text());b=np.load(M/(name+'.npz'))['beta'];assert sp['n']==len(q) and sp['lambda_distance']==lam and sp['train_end']==str(q.date.max().date());FITS.append(dict(name=name,train_end=sp['train_end'],train_n=len(q),lambda_distance=lam,columns=sp['columns'],iterations=sp['iterations'],gradient_max=sp['gradient_max']));print('resumed',name,flush=True);return sp,b
 q=q.reset_index(drop=True);sp=specification(q,lam,name);x,scale=matrix(q,sp);code=pd.factorize(q.source_key)[0];y=center(-q.time1000.to_numpy()/scale,code);p=x.shape[1];nc=len(sp['strata'])*len(NAMES);nh=len(sp['horses']);penalty=np.r_[np.ones(nc),np.full(nh,10.),np.full(p-nc-nh,lam if lam is not None else 0.)];rhs=x.T@y
 op=LinearOperator((p,p),matvec=lambda b:x.T@center(x@b,code)+penalty*b,dtype=float);diag=np.asarray(x.power(2).sum(axis=0)).ravel()+penalty;pre=LinearOperator((p,p),matvec=lambda b:b/diag,dtype=float);iterations=[0]
 def callback(_):iterations[0]+=1
 b,info=cg(op,rhs,M=pre,rtol=1e-10,atol=1e-10,maxiter=4000,callback=callback);assert info==0,(name,info);grad=np.max(abs(op@b-rhs));assert grad<1e-5,(name,grad)
 sp.update(columns=p,control_columns=nc,horse_columns=nh,iterations=iterations[0],gradient_max=float(grad));dump(M/(name+'.json'),sp);np.savez_compressed(M/(name+'.npz'),beta=b,penalty=penalty);FITS.append(dict(name=name,train_end=sp['train_end'],train_n=len(q),lambda_distance=lam,columns=p,iterations=iterations[0],gradient_max=grad));print('fit',name,len(q),p,iterations[0],flush=True);return sp,b
def predict(q,obj):
 sp,b=obj;x,scale=matrix(q,sp);pred=x@b;code=pd.factorize(q.source_key)[0];actual=center(-q.time1000.to_numpy()/scale,code);pred=center(pred,code);return pred,actual,scale
def counts_lookup(train,test):
 hc=train.groupby('horse_key').size();dc=train.groupby('hd_key').size();good=train.groupby(['horse_key','distance_m']).size().rename('n').reset_index();ng=good[good.n.ge(3)].groupby('horse_key').size();return pd.DataFrame(dict(train_n=test.horse_key.map(hc).fillna(0).astype(int),distance_train_n=test.hd_key.map(dc).fillna(0).astype(int),supported_distances=test.horse_key.map(ng).fillna(0).astype(int)),index=test.index)
def evaluate(train,test,base,ext,label):
 test=test.reset_index(drop=True);p0,y,scale=predict(test,base);p1,yy,scale1=predict(test,ext);np.testing.assert_allclose(y,yy,atol=1e-12);np.testing.assert_allclose(scale,scale1,atol=1e-12);r=test[['row_key','source_key','horse_key','hd_key','horse_id','meet','date','day_key','distance_m']].copy();r=r.join(counts_lookup(train,test));r['supported']=r.train_n.ge(12)&r.distance_train_n.ge(3)&r.supported_distances.ge(2);r['actual']=y;r['baseline']=p0;r['distance_model']=p1;r['baseline_absolute_error']=abs(y-p0);r['distance_absolute_error']=abs(y-p1);r['error_difference']=r.distance_absolute_error-r.baseline_absolute_error;r['scale']=scale;r['baseline_seconds_error']=r.baseline_absolute_error*scale*r.distance_m/1000;r['distance_seconds_error']=r.distance_absolute_error*scale*r.distance_m/1000;r['window']=label;r.to_parquet(O/(label+'_predictions.parquet'),index=False);return r
def cluster_mean(q,values,weights=None):
 values=np.asarray(values);w=np.ones(len(q)) if weights is None else np.asarray(weights);est=float(w@values/w.sum());scores=w*(values-est)/w.sum();vs=[];ngs=[]
 for ids in [q.horse_id,q.day_key,q.horse_id+':'+q.day_key]:
  code=pd.factorize(ids)[0];ng=code.max()+1;s=np.bincount(code,weights=scores);vs.append(float(s@s)*ng/(ng-1));ngs.append(ng)
 var=max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2]);se=math.sqrt(var);crit=t.ppf(.975,min(ngs[:2])-1);return dict(estimate=est,se=se,lower=est-crit*se,upper=est+crit*se,n=len(q),horses=q.horse_id.nunique(),dates=q.day_key.nunique())
def metrics(predictions):
 rows=[]
 for label,q0 in [('2024',predictions[0]),('2025',predictions[1]),('2024_2025',pd.concat(predictions,ignore_index=True))]:
  for meet in ['서울','부산','전체']:
   for scope in ['all','supported']:
    q=q0[q0.meet.eq(meet)] if meet!='전체' else q0;q=q[q.supported] if scope=='supported' else q
    if not len(q):continue
    rows.append(dict(window=label,meet=meet,scope=scope,baseline_mae=q.baseline_absolute_error.mean(),distance_mae=q.distance_absolute_error.mean(),baseline_rmse=np.sqrt(np.mean((q.actual-q.baseline)**2)),distance_rmse=np.sqrt(np.mean((q.actual-q.distance_model)**2)),baseline_mae_seconds=q.baseline_seconds_error.mean(),distance_mae_seconds=q.distance_seconds_error.mean())|cluster_mean(q,q.error_difference))
 pd.DataFrame(rows).to_csv(O/'evaluation_metrics.csv',index=False)
def profile_rows(q,obj):
 sp,b=obj;nc=sp['control_columns'];nh=sp['horse_columns'];theta=b[nc+nh:];owners=np.array(sp['hd_owner']);mu=np.bincount(owners,weights=np.array(sp['hd_weight'])*theta,minlength=nh);count=q.groupby('hd_key').size();last=q.groupby('hd_key').date.max();first=q.groupby('hd_key').date.min();hd=pd.Series(sp['horse_distances']);hk=hd.str.rsplit(':',n=1).str[0];dist=hd.str.rsplit(':',n=1).str[1].astype(int);r=pd.DataFrame(dict(hd_key=hd,horse_key=hk,meet=hk.str.split(':').str[0],horse_id=hk.str.split(':').str[1],distance_m=dist,aptitude_effect=theta-mu[owners],horse_base=b[nc:nc+nh][owners]));r['n']=r.hd_key.map(count).astype(int);r['first_date']=r.hd_key.map(first);r['last_date']=r.hd_key.map(last);return r
def replication(train,test,obj,base,label):
 pr=profile_rows(train,obj);counts=train.groupby('horse_key').size();pr=pr[pr.n.ge(3)&pr.horse_key.map(counts).ge(12)].copy();ng=pr.groupby('horse_key').hd_key.transform('size');pr=pr[ng.ge(2)];best=pr.sort_values(['horse_key','aptitude_effect','distance_m'],ascending=[True,False,True]).drop_duplicates('horse_key');allowed=set(pr.hd_key);qq=test[test.hd_key.isin(allowed)].copy().reset_index(drop=True)
 # Outcome-only evaluation reference: leave-one-out peers after training-only controls/base.
 sp,b=base;x,scale=matrix(test.reset_index(drop=True),sp);raw=-test.time1000.to_numpy()/scale;fitted=x@b;res=raw-fitted;codes=pd.factorize(test.source_key)[0];size=np.bincount(codes);mean=np.bincount(codes,weights=res)[codes]/size[codes];target=(res-mean)*size[codes]/(size[codes]-1);lookup=dict(zip(test.row_key,target));qq['outcome_adjusted']=qq.row_key.map(lookup);qq['best_distance']=qq.horse_key.map(best.set_index('horse_key').distance_m);qq['chosen']=qq.distance_m.eq(qq.best_distance);qq=qq[qq.groupby(['horse_key','distance_m']).row_key.transform('size').ge(2)].copy();summ=qq.groupby(['horse_key','chosen']).agg(n=('row_key','size'),mean=('outcome_adjusted','mean')).unstack('chosen');valid=summ.dropna();valid=valid[(valid[('n',True)]>=2)&(valid[('n',False)]>=2)];qq=qq[qq.horse_key.isin(valid.index)].copy();r=[]
 for hk,g in qq.groupby('horse_key'):
  by=g.groupby('distance_m').outcome_adjusted.agg(['mean','size']);by=by[by['size'].ge(2)];chosen=int(g.best_distance.iloc[0]);empirical=int(by['mean'].idxmax());diff=float(g[g.chosen].outcome_adjusted.mean()-g[~g.chosen].outcome_adjusted.mean());r.append(dict(window=label,horse_key=hk,best_distance=chosen,observed_best_distance=empirical,agreement=chosen==empirical,difference=diff,chosen_n=int(g.chosen.sum()),other_n=int((~g.chosen).sum())))
 rr=pd.DataFrame(r);rr.to_csv(O/(label+'_replication.csv'),index=False)
 if len(rr)>1:
  nmap=qq.groupby(['horse_key','chosen']).row_key.transform('size');weights=np.where(qq.chosen,1.,-1.)/nmap/len(rr);est=float(weights@qq.outcome_adjusted);aa=float((weights[qq.chosen]*qq.loc[qq.chosen,'outcome_adjusted']).sum());bb=float((-weights[~qq.chosen]*qq.loc[~qq.chosen,'outcome_adjusted']).sum());scores=weights*(qq.outcome_adjusted-np.where(qq.chosen,aa,bb));vs=[]
  for ids in [qq.horse_id,qq.day_key,qq.horse_id+':'+qq.day_key]:
   code=pd.factorize(ids)[0];ng=code.max()+1;agg=np.bincount(code,weights=scores);vs.append(float(agg@agg)*ng/(ng-1))
  se=math.sqrt(max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2]));crit=t.ppf(.975,min(qq.horse_id.nunique(),qq.day_key.nunique())-1);return dict(window=label,n_horses=len(rr),unique_horses=qq.horse_id.nunique(),n_starts=len(qq),agreement=float(rr.agreement.mean()),candidate_minus_other=est,se=se,lower=est-crit*se,upper=est+crit*se,exploratory=True)
 return dict(window=label,n_horses=len(rr),n_starts=len(qq),agreement=None,exploratory=True)
def final_profiles(d,obj,rep):
 pr=profile_rows(d,obj);pr['supported_distance']=pr.n.ge(5);horse=[];coverage=pd.read_csv(O/'horse_coverage.csv',dtype={'horse_id':str});coverage['horse_key']=coverage.meet+':'+coverage.horse_id
 for hk,g in pr.groupby('horse_key'):
  good=g[g.n.ge(5)].sort_values(['aptitude_effect','distance_m'],ascending=[False,True]);total=int(g.n.sum());last=g.last_date.max();can=total>=15 and len(good)>=2;best=good.iloc[0] if can else None;gap=float(good.aptitude_effect.iloc[0]-good.aptitude_effect.iloc[1]) if can else None
  horse.append(dict(horse_key=hk,meet=g.meet.iloc[0],horse_id=g.horse_id.iloc[0],n=total,observed_distances=len(g),distances_ge5=len(good),comparison_supported=can,best_distance_m=int(best.distance_m) if can else None,runner_up_distance_m=int(good.distance_m.iloc[1]) if can else None,preference_gap=gap,distinguishable_display=bool(can and gap>=.10),near_candidates=','.join(str(v) for v in good[good.aptitude_effect.ge(best.aptitude_effect-.10)].distance_m) if can else '',last_date=str(last.date()),recently_observed=last>=pd.Timestamp('2025-09-21'),status=('candidate_difference_small' if gap<.10 else 'provisional_distance_candidate') if can else 'insufficient_comparison'))
 horses=pd.DataFrame(horse);raw_names={};raw_inputs={}
 for name,q in d.groupby('source_file'):
  p=(ROOT/name).resolve();assert ROOT in p.parents;raw_inputs[name]=sha(p)
  with gzip.open(p,'rt') as f:items=json.load(f)['response']['body']['items']['item']
  for a in q.sort_values('date').itertuples():
   r=items[a.source_item_index];assert str(r['hrNo']).zfill(7)==a.horse_id and str(r['rcDate'])==a.date.strftime('%Y%m%d');nameval=str(r.get('hrName',''));key=a.horse_key
   if key not in raw_names or a.date>=raw_names[key][0]:raw_names[key]=(a.date,nameval)
 name_lookup={key:v[1] for key,v in raw_names.items()};horses['horse_name']=horses.horse_key.map(name_lookup);pr['horse_name']=pr.horse_key.map(name_lookup);pr.to_parquet(O/'horse_distance_profiles.parquet',index=False);horses.to_csv(O/'horse_candidates.csv',index=False);horses[horses.comparison_supported&horses.recently_observed].to_csv(O/'recent_horse_candidates.csv',index=False);dump(O/'name_source_hashes.json',raw_inputs)
 summary=dict(horse_venue_groups=len(horses),unique_horses=horses.horse_id.nunique(),comparison_supported=int(horses.comparison_supported.sum()),supported_unique_horses=horses.loc[horses.comparison_supported,'horse_id'].nunique(),recent_supported=int((horses.comparison_supported&horses.recently_observed).sum()),small_gap=int((horses.comparison_supported&~horses.distinguishable_display).sum()),larger_gap=int(horses.distinguishable_display.sum()),insufficient=int((~horses.comparison_supported).sum()),final_asof_by_meet=d.groupby('meet').date.max().astype(str).to_dict(),replication=rep,individual_confidence_intervals=False,unobserved_distances_inferred=False,causal=False,operational=False)
 dump(O/'profile_summary.json',summary);print('profiles',summary,flush=True)
def main():
 d=prepare();train=d[d.year.le(2022)].copy();test=d[d.year.eq(2023)].copy();base=fit(train,None,'tune2023_baseline');tune=[]
 for lam in [3.,10.,30.,100.]:
  ext=fit(train,lam,'tune2023_lambda'+str(int(lam)));q=evaluate(train,test,base,ext,'tune2023_lambda'+str(int(lam)));r=q[q.supported];tune.append(dict(lambda_distance=lam,n=len(r),mae=r.distance_absolute_error.mean(),baseline_mae=r.baseline_absolute_error.mean()))
 tune=pd.DataFrame(tune);tune.to_csv(O/'tuning.csv',index=False);chosen=float(tune.sort_values(['mae','lambda_distance'],ascending=[True,False]).iloc[0].lambda_distance);dump(O/'selected_model.json',dict(lambda_distance=chosen,tuning_train_end='2022-12-31',tuning_test_year=2023,locked_before_2024_2025_evaluation=True))
 preds=[];rep=[]
 for year in [2024,2025]:
  train=d[d.year.lt(year)].copy();test=d[d.year.eq(year)].copy();base=fit(train,None,'eval'+str(year)+'_baseline');ext=fit(train,chosen,'eval'+str(year)+'_distance');preds.append(evaluate(train,test,base,ext,'eval'+str(year)));rep.append(replication(train,test,ext,base,str(year)))
 metrics(preds);final=fit(d,chosen,'final_distance');final_profiles(d,final,rep);pd.DataFrame(FITS).to_csv(O/'fit_diagnostics.csv',index=False);print('SELECTED',chosen,flush=True)
if __name__=='__main__':main()
