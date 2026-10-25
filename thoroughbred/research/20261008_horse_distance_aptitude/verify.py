"""Independent sparse matrix, LSMR fit, chronology, metrics and candidate reconstruction."""
from pathlib import Path
import gzip,hashlib,json,math
import numpy as np,pandas as pd
from scipy import sparse
from scipy.sparse.linalg import LinearOperator,lsmr
from scipy.stats import t
H=Path(__file__).resolve().parent;O=H/'outputs';M=O/'models';ROOT=H.parents[2];checks=[];models=[];cache={}
def check(name,error,tol=6e-6):
 error=float(error);assert np.isfinite(error) and error<tol,(name,error,tol);checks.append(dict(check=name,error=error,tolerance=tol))
d=pd.read_parquet(H.parent/'20261007_sex_ability_gap/outputs/population.parquet');assert len(d)==151074 and d.row_key.is_unique;d=d[d.distance_m.between(1000,1800)].copy();d['age_squared']=d.age*d.age;d['horse_key']=d.meet+':'+d.horse_id;d['hd_key']=d.horse_key+':'+d.distance_m.astype(str);d['stratum']=d.meet+':'+d.distance_m.astype(str);d['time1000']=d.finish/d.distance_m*1000;d['day_key']=d.date.dt.strftime('%Y-%m-%d');assert len(d)==148126 and (d.last_history_date.isna()|d.last_history_date.lt(d.date)).all();assert not d.duplicated(['horse_id','date']).any();assert d.groupby('source_key').size().ge(2).all()
audit=json.loads((O/'source_audit.json').read_text());hashes=audit['input_sha256']|json.loads((O/'name_source_hashes.json').read_text())
for name,h in hashes.items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h
raw_n=0;latest_names={}
for name,q in d.groupby('source_file'):
 with gzip.open(ROOT/name,'rt') as f:items=json.load(f)['response']['body']['items']['item']
 for a in q.itertuples():
  r=items[a.source_item_index];assert str(r['hrNo']).zfill(7)==a.horse_id and str(r['rcDate'])==a.date.strftime('%Y%m%d') and int(r['rcDist'])==a.distance_m;assert abs(float(r['rcTime'])-a.finish)<1e-9;raw_n+=1
  if a.horse_key not in latest_names or a.date>=latest_names[a.horse_key][0]:latest_names[a.horse_key]=(a.date,str(r.get('hrName','')))
def design(q,sp):
 n=len(q);form=sp['form'];k=2*len(form);strata=sp['strata'];blocks=[];scale=np.zeros(n)
 for key in strata:
  st=sp['statistics'][key];mask=q.stratum.eq(key).to_numpy();rows=np.flatnonzero(mask);g=q.loc[mask];cols=[];miss=[]
  for j,col in enumerate(form):
   value=g[col].to_numpy(float);missing=~np.isfinite(value);cols.append(np.where(missing,st['medians'][j],value));miss.append(missing.astype(float))
  v=(np.column_stack(cols+miss)-np.asarray(st['means']))/np.asarray(st['sds']);blocks.append(sparse.csr_matrix((v.ravel(),(np.repeat(rows,k),np.tile(np.arange(k),len(rows)))),shape=(n,k)));scale[mask]=st['scale']
 hc=pd.Index(sp['horses']).get_indexer(q.horse_key);known=hc>=0;horse=sparse.csr_matrix((np.ones(known.sum()),(np.flatnonzero(known),hc[known])),shape=(n,len(sp['horses'])));blocks.append(horse)
 if sp['horse_distances']:
  dc=pd.Index(sp['horse_distances']).get_indexer(q.hd_key);known=dc>=0;dist=sparse.csr_matrix((np.ones(known.sum()),(np.flatnonzero(known),dc[known])),shape=(n,len(sp['horse_distances'])));w=sparse.csr_matrix((sp['hd_weight'],(sp['hd_owner'],np.arange(len(sp['hd_weight'])))),shape=(len(sp['horses']),len(sp['hd_weight'])));blocks.append(dist-sparse.diags(known.astype(float))@horse@w)
 x=sparse.hstack(blocks,format='csr');return x,scale
def projection(q):
 code=pd.factorize(q.source_key)[0];count=np.bincount(code);op=sparse.csr_matrix((1/count[code],(code,np.arange(len(q)))),shape=(len(count),len(q)))
 return lambda z:z-(op@z)[code]
for path in sorted(M.glob('*.json')):
 sp=json.loads(path.read_text());q=d[d.year.le(sp['train_year_max'])].copy().reset_index(drop=True);assert len(q)==sp['n'] and str(q.date.max().date())==sp['train_end'];name=sp['name'];z=np.load(path.with_suffix('.npz'));b=z['beta'];pen=z['penalty'];x,scale=design(q,sp);proj=projection(q);y=proj(-q.time1000.to_numpy()/scale);n,p=x.shape
 # Verify scale, imputation and normalization against the training slice only.
 within=projection(q)(q.time1000.to_numpy())
 for key,st in sp['statistics'].items():
  g=q[q.stratum.eq(key)];mask=q.stratum.eq(key);check('training-only scale',abs(np.std(within[mask])-st['scale']));cols=[];missing=[]
  for j,col in enumerate(sp['form']):
   s=g[col].astype(float);median=float(s.median()) if s.notna().any() else 0.;check('training-only median',abs(median-st['medians'][j]));cols.append(s.fillna(median).to_numpy());missing.append(s.isna().to_numpy(float))
  vals=np.column_stack(cols+missing);check('training-only means',max(abs(vals.mean(axis=0)-st['means'])));sd=vals.std(axis=0);sd=np.where(sd>1e-8,sd,1.);check('training-only SD',max(abs(sd-st['sds'])))
 diagonal=np.asarray(x.power(2).sum(axis=0)).ravel()+pen;pre=np.sqrt(diagonal);sqrtpen=np.sqrt(pen)
 op=LinearOperator((n+p,p),matvec=lambda z:np.r_[proj(x@(z/pre)),sqrtpen*z/pre],rmatvec=lambda z:(x.T@proj(z[:n])+sqrtpen*z[n:])/pre,dtype=float)
 independent=lsmr(op,np.r_[y,np.zeros(p)],atol=1e-11,btol=1e-11,maxiter=4000);assert independent[1] in [1,2],(name,independent[1]);ib=independent[0]/pre;error=max(abs(ib-b));check('CG versus independent LSMR coefficients',error,2e-5);check('normal equation gradient',max(abs(x.T@proj(x@b-y)+pen*b)),2e-5);check('independent training predictions',max(abs(x@(ib-b))),2e-5);models.append(dict(name=name,n=n,columns=p,lsmr_iterations=independent[2],max_beta_error=error))
 if name.startswith('eval') or name.startswith('tune'):
  year=2023 if name.startswith('tune') else int(name[4:8]);test=d[d.year.eq(year)].copy().reset_index(drop=True);assert q.date.max()<test.date.min();tx,tscale=design(test,sp);pred=projection(test)(tx@b);actual=projection(test)(-test.time1000.to_numpy()/tscale);cache[name]=(test,pred,actual,tscale,sp,b)
  altered=test.copy();altered['finish']=altered.finish*2+17;altered['rank_raw']=99;xx,ss=design(altered,sp);check('current outcome cannot enter predictor',max(abs((xx-tx).data)) if (xx-tx).nnz else 0.,1e-12)
 if sp['horse_distances']:
  counts=q.hd_key.value_counts();hn=q.horse_key.value_counts();owners=pd.Series(sp['horse_distances']).str.rsplit(':',n=1).str[0];check('distance weights count-based',max(abs(np.array([counts[key]/hn[horse] for key,horse in zip(sp['horse_distances'],owners)])-sp['hd_weight'])));theta=b[sp['control_columns']+sp['horse_columns']:];mu=pd.DataFrame({'owner':sp['hd_owner'],'value':theta*np.array(sp['hd_weight'])}).groupby('owner').value.sum();g=theta-mu.loc[sp['hd_owner']].to_numpy();check('weighted distance effect zero within horse',abs(pd.DataFrame({'owner':sp['hd_owner'],'v':g*np.array(sp['hd_weight'])}).groupby('owner').v.sum()).max())
 print('independent fit verified',name,error,flush=True)
for path in list(O.glob('tune2023_lambda*_predictions.parquet'))+list(O.glob('eval*_predictions.parquet')):
 r=pd.read_parquet(path);key=path.stem.replace('_predictions','');test,pred,actual,scale,_,_=cache[key if key.startswith('tune') else key+'_distance'];base=cache['tune2023_baseline' if key.startswith('tune') else key+'_baseline'];assert test.row_key.tolist()==r.row_key.tolist();check('saved future distance predictions',max(abs(pred-r.distance_model)));check('saved future baseline predictions',max(abs(base[1]-r.baseline)));check('saved future outcome reference',max(abs(actual-r.actual)));check('saved scale',max(abs(scale-r.scale)));check('paired MAE difference',max(abs(abs(actual-pred)-abs(actual-base[1])-r.error_difference)))
 # Independent support counts exclude all current/future starts.
 train=d[d.year.lt(int(test.year.iloc[0]))];hn=train.horse_key.value_counts();dn=train.hd_key.value_counts();ct=train.groupby(['horse_key','distance_m']).size().reset_index(name='n');ns=ct[ct.n.ge(3)].groupby('horse_key').size();supported=r.horse_key.map(hn).fillna(0).ge(12)&r.hd_key.map(dn).fillna(0).ge(3)&r.horse_key.map(ns).fillna(0).ge(2);assert supported.equals(r.supported)
def verify_metric(q,a):
 values=(q.actual-q.distance_model).abs()-(q.actual-q.baseline).abs();estimate=values.mean();check('metric mean',abs(estimate-a.estimate));score=(values-estimate)/len(q);vs=[]
 for labels in [q.horse_id,q.day_key,pd.MultiIndex.from_frame(q[['horse_id','day_key']])]:
  sums=pd.Series(score.to_numpy()).groupby(pd.factorize(labels)[0]).sum();ng=len(sums);vs.append(float(sums@sums)*ng/(ng-1))
 se=math.sqrt(max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2]));crit=t.ppf(.975,min(q.horse_id.nunique(),q.day_key.nunique())-1);check('metric clustered SE',abs(se-a.se));check('metric CI',abs(estimate+crit*se-a.upper));check('baseline MAE',abs(abs(q.actual-q.baseline).mean()-a.baseline_mae));check('distance MAE',abs(abs(q.actual-q.distance_model).mean()-a.distance_mae));assert len(q)==a.n
p24=pd.read_parquet(O/'eval2024_predictions.parquet');p25=pd.read_parquet(O/'eval2025_predictions.parquet');allp=pd.concat([p24,p25],ignore_index=True)
for a in pd.read_csv(O/'evaluation_metrics.csv').itertuples():
 q=allp if a.window=='2024_2025' else p24 if a.window=='2024' else p25
 if a.meet!='전체':q=q[q.meet.eq(a.meet)]
 if a.scope=='supported':q=q[q.supported]
 verify_metric(q,a)
tune=pd.read_csv(O/'tuning.csv');selected=json.loads((O/'selected_model.json').read_text());assert selected['lambda_distance']==float(tune.sort_values(['mae','lambda_distance'],ascending=[True,False]).iloc[0].lambda_distance)==100.;assert selected['locked_before_2024_2025_evaluation']
profiles=pd.read_parquet(O/'horse_distance_profiles.parquet');candidates=pd.read_csv(O/'horse_candidates.csv',dtype={'horse_id':str});assert len(profiles)==profiles.hd_key.nunique();counts=d.groupby('hd_key').size();assert profiles.n.equals(profiles.hd_key.map(counts).rename('n'))
for a in candidates.itertuples():
 g=profiles[profiles.horse_key.eq(a.horse_key)];good=g[g.n.ge(5)].sort_values(['aptitude_effect','distance_m'],ascending=[False,True]);valid=int(g.n.sum())>=15 and len(good)>=2;assert valid==a.comparison_supported;assert a.horse_name==latest_names[a.horse_key][1]
 if valid:assert a.best_distance_m==good.distance_m.iloc[0] and a.runner_up_distance_m==good.distance_m.iloc[1];check('profile gap',abs(a.preference_gap-good.aptitude_effect.iloc[0]+good.aptitude_effect.iloc[1]))
 else:assert pd.isna(a.best_distance_m)
summary=json.loads((O/'profile_summary.json').read_text());assert summary['comparison_supported']==int(candidates.comparison_supported.sum()) and summary['recent_supported']==int((candidates.comparison_supported&candidates.recently_observed).sum());assert not summary['individual_confidence_intervals'] and not summary['unobserved_distances_inferred']
for year,r in [(2024,p24),(2025,p25)]:
 rep=pd.read_csv(O/(str(year)+'_replication.csv'));counts=r.groupby('source_key').row_key.transform('size');target=(r.actual-r.baseline)*counts/(counts-1);look=dict(zip(r.row_key,target));test=d[d.year.eq(year)].copy();sp,b=cache['eval'+str(year)+'_distance'][4:];nh=sp['horse_columns'];theta=b[sp['control_columns']+nh:];weight=np.array(sp['hd_weight']);mu=np.bincount(sp['hd_owner'],weights=weight*theta,minlength=nh);g=pd.DataFrame({'hd_key':sp['horse_distances'],'effect':theta-mu[np.array(sp['hd_owner'])]});g['horse_key']=g.hd_key.str.rsplit(':',n=1).str[0];g['dist']=g.hd_key.str.rsplit(':',n=1).str[1].astype(int);train=d[d.year.lt(year)];g['n']=g.hd_key.map(train.hd_key.value_counts());g=g[g.n.ge(3)&g.horse_key.map(train.horse_key.value_counts()).ge(12)];g=g[g.groupby('horse_key').hd_key.transform('size').ge(2)];best=g.sort_values(['horse_key','effect','dist'],ascending=[True,False,True]).drop_duplicates('horse_key').set_index('horse_key').dist;test=test[test.hd_key.isin(set(g.hd_key))];test=test[test.groupby(['horse_key','distance_m']).row_key.transform('size').ge(2)].copy();test['target']=test.row_key.map(look)
 for a in rep.itertuples():
  qq=test[test.horse_key.eq(a.horse_key)];chosen=int(best[a.horse_key]);a0=qq[qq.distance_m.eq(chosen)];a1=qq[qq.distance_m.ne(chosen)];assert chosen==a.best_distance and len(a0)==a.chosen_n and len(a1)==a.other_n;check('future candidate-minus-other',abs(a0.target.mean()-a1.target.mean()-a.difference));means=qq.groupby('distance_m').target.mean();assert int(means.idxmax())==a.observed_best_distance
 s=next(a for a in summary['replication'] if a['window']==str(year));check('replication mean',abs(rep.difference.mean()-s['candidate_minus_other']));check('replication agreement',abs(rep.agreement.mean()-s['agreement']))
pd.DataFrame(models).to_csv(O/'independent_fit_checks.csv',index=False);dump=dict(passed=True,input_hashes_verified=len(hashes),raw_identity_and_finish_checks=raw_n,independent_models=len(models),future_prediction_files=6,profile_rows=len(profiles),candidate_rows=len(candidates),chronological_splits_verified=True,current_outcome_mutation_verified=True,independent_method='independent sparse control/horse/centered distance matrix; sparse race averaging projection; preconditioned LSMR versus CG; pandas cluster sums; profile and future candidate reconstruction',checks=checks,causal=False);(O/'verification.json').write_text(json.dumps(dump,ensure_ascii=False,indent=2)+'\n');print('PASS',len(models),len(checks),'checks')
