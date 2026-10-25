"""Sex-pooled linear carried-load slopes; observational normalization diagnostics."""
from pathlib import Path
import hashlib,json,math
import numpy as np,pandas as pd
from scipy.stats import t
from model import prune,absorb,fe_rank,cluster
H=Path(__file__).resolve().parent;O=H/'outputs';SOURCE=H.parent/'20261007_sex_ability_gap/outputs/population.parquet'
FORM=['age_squared','rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap']
ROWS=[];DIAG=[];SKIP=[];HOLD=[]

def load():
 d=pd.read_parquet(SOURCE);d['age_squared']=d.age**2;d['day_key']=pd.to_datetime(d.date).dt.strftime('%Y-%m-%d')
 assert len(d)==151074 and d.row_key.is_unique
 assert (pd.to_datetime(d.last_history_date.dropna())<pd.to_datetime(d.loc[d.last_history_date.notna(),'date'])).all()
 return d

def nuisance(g,spec):
 cols=[] if spec=='fe_only' else FORM.copy()
 if spec=='body_direct':cols+=['body_weight','body_squared']
 xs=[];names=[]
 for col in cols:
  v=g[col].to_numpy(float);miss=~np.isfinite(v)
  if miss.all():continue
  v=np.where(miss,np.median(v[~miss]),v)
  if v.std()>1e-10:xs.append((v-v.mean())/v.std());names.append(col)
  if miss.any():xs.append(miss.astype(float));names.append(col+'_missing')
 return np.column_stack(xs) if xs else np.empty((len(g),0)),names

def uncertainty(q,w,y,rank):
 n=len(w);den=w@w;b=float(w@y/den);res=y-b*w;df=n-rank-1
 assert df>0 and den>1e-6
 score=w*res/den;cor=(n-1)/df
 vh,nh=cluster(score,q.horse_id,cor);vd,nd=cluster(score,q.day_key,cor);vi,_=cluster(score,q.horse_id+':'+q.day_key,cor)
 se=math.sqrt(max(vh,vd,vh+vd-vi,0));crit=t.ppf(.975,min(nh,nd)-1)
 changing=q.groupby(['distance_m','horse_id']).weight.agg(['min','max']);changing=(changing['max']-changing['min']).ge(.5)
 ok=int(changing.sum())>=100 and nd>=100
 return dict(n=n,horses=nh,dates=nd,races=q.source_key.nunique(),rank_controls=int(rank),residual_df=int(df),coefficient=b,se=se,lower=b-crit*se,upper=b+crit*se,supported=ok,residual_load_variance=den/n,changing_horse_distance_pairs=int(changing.sum()),variance_horse=vh,variance_date=vd,variance_two_way=vh+vd-vi,load_min=float(q.weight.min()),load_max=float(q.weight.max()),date_min=str(q.date.min()),date_max=str(q.date.max()))

def residualize(g,meta):
 q,it=prune(g)
 if len(q)<300:
  SKIP.append(meta|dict(input_n=len(g),n=len(q),reason='fewer than300 rows after iterative singleton removal'));return None
 z,names=nuisance(q,meta['specification']);w=q.weight.to_numpy()-54;y=q.finish.to_numpy()*1000/meta['distance_m']
 a,its,err=absorb(np.column_stack([w,y,z]),[q.source_key,q.horse_id]);zd=a[:,2:]
 if zd.shape[1]:
  s=np.linalg.svd(zd,compute_uv=False);rank=int((s>s[0]*1e-10).sum());v=np.linalg.pinv(zd,rcond=1e-10)@a[:,:2];r=a[:,:2]-zd@v
 else:rank=0;r=a[:,:2]
 fr,nc=fe_rank(q,True)
 if r[:,0]@r[:,0]<1e-6:
  SKIP.append(meta|dict(input_n=len(g),n=len(q),reason='load not estimable'));return None
 result=uncertainty(q,r[:,0],r[:,1],fr+rank)
 ROWS.append(meta|result|dict(seconds_per_kg=result['coefficient']*meta['distance_m']/1000,lower_seconds_per_kg=result['lower']*meta['distance_m']/1000,upper_seconds_per_kg=result['upper']*meta['distance_m']/1000))
 DIAG.append(meta|dict(input_n=len(g),n=len(q),excluded_n=len(g)-len(q),prune_iterations=it,fe_rank=fr,fe_components=nc,nuisance_rank=rank,nuisance_names='|'.join(names),absorb_iterations=its,max_group_mean=err))
 return q,r[:,0],r[:,1],fr+rank

def fit_window(d,eligible,window,spec):
 pooled={};parts={}
 for a in eligible.itertuples():
  g=d[d.meet.eq(a.meet)&d.distance_m.eq(a.distance_m)]
  obj=residualize(g,dict(meet=a.meet,distance_m=int(a.distance_m),window=window,specification=spec))
  if obj is not None:parts.setdefault(a.meet,[]).append(obj)
 parts['전체']=[p for pp in list(parts.values()) for p in pp]
 for meet,pp in parts.items():
  q=pd.concat([p[0] for p in pp]);w=np.concatenate([p[1] for p in pp]);y=np.concatenate([p[2] for p in pp]);rank=sum(p[3] for p in pp)
  result=uncertainty(q,w,y,rank);ROWS.append(dict(meet=meet,distance_m=0,window=window,specification=spec)|result|dict(seconds_per_kg=np.nan,lower_seconds_per_kg=np.nan,upper_seconds_per_kg=np.nan))
  pooled[meet]=(q,w,y,rank,result)
 print(window,spec,'done',flush=True);return pooled

def main():
 O.mkdir(exist_ok=True);d=load()
 e=d.groupby(['meet','distance_m']).agg(n=('row_key','size'),dates=('day_key','nunique')).reset_index();e['eligible']=e.n.ge(2000)&e.dates.ge(100)&e.distance_m.between(1000,1800);e.to_csv(O/'eligibility.csv',index=False);e=e[e.eligible]
 for window,dd in [('all',d),('complete_2024_2025',d[d.year.isin([2024,2025])])]:
  for spec in ['main','fe_only','body_direct']:fit_window(dd,e,window,spec)
 for year in [2024,2025,2026]:
  train=fit_window(d[d.year.lt(year)&d.month.le(8)],e,f'train_before_{year}_jan_aug','main')
  test=fit_window(d[d.year.eq(year)&d.month.le(8)],e,f'test_{year}_jan_aug','main')
  for meet,(q,w,y,rank,est) in test.items():
   if meet not in train:continue
   coefficient=train[meet][-1]['coefficient'];corrected=y-coefficient*w
   HOLD.append(dict(meet=meet,test_year=year,train_n=train[meet][-1]['n'],test_n=len(q),train_end=train[meet][-1]['date_max'],test_start=est['date_min'],test_end=est['date_max'],train_coefficient=coefficient,test_coefficient=est['coefficient'],test_lower=est['lower'],test_upper=est['upper'],remaining_slope=est['coefficient']-coefficient,baseline_rmse=float(np.sqrt(np.mean(y*y))),corrected_rmse=float(np.sqrt(np.mean(corrected**2))),baseline_mae=float(np.mean(abs(y))),corrected_mae=float(np.mean(abs(corrected))),conditional_not_forecast=True))
 rows=pd.DataFrame(ROWS);rows.to_csv(O/'coefficients.csv',index=False);pd.DataFrame(DIAG).to_csv(O/'diagnostics.csv',index=False);pd.DataFrame(SKIP).to_csv(O/'skipped.csv',index=False);pd.DataFrame(HOLD).to_csv(O/'temporal_validation.csv',index=False)
 candidates=[];lookup=[]
 for meet in sorted(d.meet.unique())+['전체']:
  a=rows[(rows.meet==meet)&(rows.distance_m==0)&(rows.window=='all')&(rows.specification=='main')].iloc[0]
  r=rows[(rows.meet==meet)&(rows.distance_m==0)&(rows.window=='complete_2024_2025')&(rows.specification=='main')].iloc[0]
  ok=bool(a.supported and r.supported and a.lower>0 and r.lower>0)
  value=math.floor((.5*min(a.coefficient,r.coefficient)+1e-12)/.005)*.005 if ok else 0.
  candidates.append(dict(meet=meet,full_coefficient=a.coefficient,full_lower=a.lower,full_upper=a.upper,recent_coefficient=r.coefficient,recent_lower=r.lower,recent_upper=r.upper,positive_full_and_recent_ci=ok,conservative_candidate=value,candidate_policy='50% of smaller positive point, floor to0.005; require positive full/recent95%CI',operational_adoption=False))
  for dist in [1200,1400,1800]:
   for burden in range(52,58):lookup.append(dict(meet=meet,distance_m=dist,carried_kg=burden,reference_kg=54,candidate_seconds_per_kg=value*dist/1000,estimated_loss_vs54=value*(burden-54)*dist/1000,time_to_add_for_54kg=-value*(burden-54)*dist/1000))
 pd.DataFrame(candidates).to_csv(O/'candidates.csv',index=False);pd.DataFrame(lookup).to_csv(O/'correction_lookup.csv',index=False)
 raw=[]
 for window,dd in [('all',d),('complete_2024_2025',d[d.year.isin([2024,2025])])]:
  pp=dd.merge(e[['meet','distance_m']],on=['meet','distance_m'],validate='many_to_one').copy();pp['ynorm']=pp.finish*1000/pp.distance_m
  for meet,qq in list(pp.groupby('meet'))+[('전체',pp)]:
   w=qq.weight-qq.groupby(['meet','distance_m']).weight.transform('mean');y=qq.ynorm-qq.groupby(['meet','distance_m']).ynorm.transform('mean')
   raw.append(dict(meet=meet,window=window,n=len(qq),coefficient=float(w@y/(w@w)),only_venue_distance_intercepts=True))
 pd.DataFrame(raw).to_csv(O/'unadjusted_associations.csv',index=False)
 source=dict(input_path=str(SOURCE.relative_to(H.parents[2])),input_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),input_n=len(d),input_races=d.source_key.nunique(),input_horses=d.horse_id.nunique(),source_end=d.groupby('meet').date.max().astype(str).to_dict(),formula='finish*1000/distance ~ (carried-54) + nuisance + venue_horse_by_exact_distance + race',nuisance=FORM,sex_features=False,body_features_main=False,causal=False,operational=False,holdout='Previously trained coefficient applied to outcome/load residualized on heldout nuisance and FE; conditional stability, NOT next-race forecasting',models=len(rows),pooled_models=int(rows.distance_m.eq(0).sum()),skipped_models=len(SKIP))
 (O/'source_and_method.json').write_text(json.dumps(source,ensure_ascii=False,indent=2)+'\n');print(pd.DataFrame(candidates).to_string(index=False),flush=True);print(pd.DataFrame(HOLD).to_string(index=False),flush=True)
if __name__=='__main__':main()
