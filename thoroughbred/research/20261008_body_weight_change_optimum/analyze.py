"""Body-mass changes, within-horse deviations and conditional quadratic minima."""
from pathlib import Path
import gzip,hashlib,json,re,math,sys
import numpy as np,pandas as pd
from scipy.stats import t,false_discovery_control
from model import prune,absorb,fe_rank
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2];SOURCE=H.parent/'20261007_sex_ability_gap/outputs/population.parquet';LEDGER=SOURCE.parent/'selection_ledger.parquet'
FORM=['weight','weight_squared','age_squared','rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap']
MODELS=[];CONTRASTS=[];DIAG=[];SKIP=[];TERMS=[]
BINLABEL=['≤−15','−14~−6','−5~−1','0','+1~+5','+6~+14','≥+15'];EDGES=[-np.inf,-15,-6,-1,0,5,14,np.inf]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def prepare():
 d=pd.read_parquet(SOURCE).sort_values(['horse_id','date','row_key']).reset_index(drop=True);d['age_squared']=d.age**2;d['day_key']=d.date.dt.strftime('%Y-%m-%d')
 assert len(d)==151074 and d.row_key.is_unique and not d.duplicated(['horse_id','date']).any()
 delta=pd.Series(np.nan,index=d.index);raw_text=pd.Series('',index=d.index,dtype=str);inputs={str(SOURCE.relative_to(ROOT)):sha(SOURCE),str(LEDGER.relative_to(ROOT)):sha(LEDGER)}
 for name,g in d.groupby('source_file'):
  p=(ROOT/name).resolve();assert ROOT in p.parents;inputs[name]=sha(p)
  with gzip.open(p,'rt') as f:items=json.load(f)['response']['body']['items']['item']
  for a in g.itertuples():
   row=items[int(a.source_item_index)];assert str(row['hrNo']).zfill(7)==a.horse_id and int(row['rcDate'])==int(a.date.strftime('%Y%m%d')) and int(row['rcDist'])==a.distance_m
   s=str(row['wgHr']);m=re.fullmatch(r'\s*(\d+)\(([-+]?\d*)\)\s*',s);assert m and float(m[1])==a.body_weight,(a.row_key,s)
   raw_text.loc[a.Index]=s
   if m[2] not in ['','+','-']:delta.loc[a.Index]=float(m[2])
  print('raw body verified',name.split('/')[-2:],flush=True)
 d['raw_reported_change']=delta;d['body_change']=delta;d['usual_body']=d.groupby('horse_id').body_weight.transform('mean');d['relative_body']=d.body_weight-d.usual_body
 ledger=pd.read_parquet(LEDGER).sort_values(['horse_id','date','row_key']);assert ledger.row_key.is_unique and not ledger.duplicated(['horse_id','date']).any()
 for col in ['row_key','date','body_weight','distance_m']:ledger['previous_'+col]=ledger.groupby('horse_id')[col].shift()
 ledger['past_body_mean']=ledger.groupby('horse_id').body_weight.transform(lambda v:v.shift().rolling(5,min_periods=3).mean())
 d=d.merge(ledger[['row_key','previous_row_key','previous_date','previous_body_weight','previous_distance_m','past_body_mean']],on='row_key',validate='one_to_one');d['observed_change']=d.body_weight-d.previous_body_weight;d['observed_gap']=(d.date-d.previous_date).dt.days;d['past_relative_body']=d.body_weight-d.past_body_mean
 zero=d.raw_reported_change.isna()&d.observed_change.eq(0)&d.previous_date.eq(d.last_history_date)
 d.loc[zero,'body_change']=0.;d['change_origin']=np.where(zero,'verified_zero',np.where(d.raw_reported_change.notna(),'raw_reported','unresolved_missing'))
 same=d.previous_date.eq(d.last_history_date)&d.body_change.notna();compared=d.previous_date.notna()&d.body_change.notna();match=(d.body_change-d.observed_change).abs().lt(1e-8)
 audit=dict(input_n=len(d),races=d.source_key.nunique(),horses=d.horse_id.nunique(),raw_files=d.source_file.nunique(),raw_body_checks=len(d),raw_reported_change_observed=int(d.raw_reported_change.notna().sum()),raw_reported_change_missing=int(d.raw_reported_change.isna().sum()),verified_zero_changes=int(zero.sum()),effective_change_observed=int(d.body_change.notna().sum()),effective_change_missing=int(d.body_change.isna().sum()),reported_change_min=float(d.body_change.min()),reported_change_max=float(d.body_change.max()),previous_observation_comparable=int(compared.sum()),previous_observation_matches=int((compared&match).sum()),history_date_matches=int(same.sum()),history_date_and_change_matches=int((same&match).sum()),previous_observation_not_proven_complete_history=True,inputs_sha256=inputs,source_start=d.groupby('meet').date.min().astype(str).to_dict(),source_end=d.groupby('meet').date.max().astype(str).to_dict(),sex_features=False,causal=False,operational=False)
 features=d[['row_key','raw_reported_change','body_change','change_origin','usual_body','relative_body','past_body_mean','past_relative_body','previous_row_key','previous_date','previous_body_weight','previous_distance_m','observed_change','observed_gap']].copy();features.to_parquet(O/'body_features.parquet',index=False)
 d[compared&~match][['row_key','date','body_weight','body_change','previous_row_key','previous_date','previous_body_weight','observed_change','last_history_date']].to_csv(O/'reported_vs_observed_mismatches.csv',index=False)
 (O/'source_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
 prev=d[['row_key','finish','distance_m','date']].rename(columns={'row_key':'previous_row_key','finish':'previous_finish','distance_m':'previous_valid_distance','date':'previous_valid_date'})
 d=d.merge(prev,on='previous_row_key',how='left',validate='many_to_one');d['paired_time_change']=np.where(d.distance_m.eq(d.previous_valid_distance),d.finish-d.previous_finish,np.nan)
 d['change_bin']=pd.cut(d.body_change,EDGES,labels=BINLABEL)
 rows=[]
 for (meet,dist,band),g in d[d.body_change.notna()].groupby(['meet','distance_m','change_bin'],observed=True):
  p=g.paired_time_change.dropna();rows.append(dict(meet=meet,distance_m=dist,change_bin=str(band),n=len(g),horses=g.horse_id.nunique(),dates=g.day_key.nunique(),body_mean=g.body_weight.mean(),change_mean=g.body_change.mean(),finish_mean=g.finish.mean(),finish_median=g.finish.median(),finish_p20=g.finish.quantile(.2),finish_p80=g.finish.quantile(.8),same_distance_pair_n=len(p),paired_seconds_mean=p.mean(),paired_seconds_median=p.median()))
 pd.DataFrame(rows).to_csv(O/'observed_changes.csv',index=False)
 return d

def design(g,spec):
 xs=[];names=[]
 for col in ([] if spec=='fe_only' else FORM):
  a=g[col].to_numpy(float);miss=~np.isfinite(a)
  if miss.all():continue
  a=np.where(miss,np.median(a[~miss]),a)
  if a.std()>1e-10:xs.append((a-a.mean())/a.std());names.append(col)
  if miss.any():xs.append(miss.astype(float));names.append(col+'_missing')
 return (np.column_stack(xs) if xs else np.empty((len(g),0))),names

def covariances(g,x,res,rank):
 pinv=np.linalg.pinv(x,rcond=1e-10);score=pinv.T*res[:,None];df=len(g)-rank-x.shape[1];assert df>0
 vs=[]
 for ids in [g.horse_id,g.day_key,g.horse_id+':'+g.day_key]:
  c=pd.factorize(ids)[0];ng=c.max()+1;agg=np.zeros((ng,x.shape[1]));np.add.at(agg,c,score);vs.append(agg.T@agg*ng/(ng-1)*(len(g)-1)/df)
 return [vs[0],vs[1],vs[0]+vs[1]-vs[2]],df

def se(v,covs):return math.sqrt(max(float(v@c@v) for c in covs)+0.)
def support(g,col,value):
 q=g[g[col].between(value-3,value+3)]
 return dict(n=len(q),horses=q.horse_id.nunique(),dates=q.day_key.nunique())
def good(a):return a['n']>=100 and a['horses']>=30 and a['dates']>=20

def summarize(g,x,y,control_rank,meta):
 beta=np.linalg.pinv(x,rcond=1e-10)@y;res=y-x@beta;covs,df=covariances(g,x,res,control_rank);crit=t.ppf(.975,min(g.horse_id.nunique(),g.day_key.nunique())-1)
 metric=meta['metric'];col={'change':'body_change','absolute':'body_weight','relative':'relative_body','past_relative':'past_relative_body','change_bins':'body_change'}[metric];levels={'change':[-20,-10,-5,5,10,20],'absolute':[450,470,490,510],'relative':[-20,-10,-5,5,10,20],'past_relative':[-20,-10,-5,5,10,20]}
 a=meta|dict(n=len(g),horses=g.horse_id.nunique(),races=g.source_key.nunique(),dates=g.day_key.nunique(),rank_controls=int(control_rank),residual_df=int(df),body_x_p10=float(g[col].quantile(.1)),body_x_p90=float(g[col].quantile(.9)),date_min=str(g.date.min()),date_max=str(g.date.max()),vertex_kg=np.nan,vertex_se=np.nan,minimum_supported=False,curvature_bh_q=np.nan)
 for j,b in enumerate(beta):
  vv=np.eye(len(beta))[j];err=se(vv,covs);TERMS.append(meta|dict(term=j,coefficient=float(b),se=err,lower=float(b-crit*err),upper=float(b+crit*err)))
 if metric!='change_bins':
  a.update(beta_linear=float(beta[0]),beta_quadratic=float(beta[1]),quadratic_se=se(np.array([0,1]),covs),quadratic_lower=float(beta[1]-crit*se(np.array([0,1]),covs)),quadratic_upper=float(beta[1]+crit*se(np.array([0,1]),covs)))
  if beta[1]>0:
   center=480 if metric=='absolute' else 0;vertex=center-10*beta[0]/(2*beta[1]);grad=np.array([-10/(2*beta[1]),10*beta[0]/(2*beta[1]**2)]);ss=support(g,col,vertex)
   a.update(vertex_kg=float(vertex),vertex_se=se(grad,covs),minimum_supported=bool(a['quadratic_lower']>0 and a['body_x_p10']<=vertex<=a['body_x_p90'] and good(ss) and g.day_key.nunique()>=100),vertex_neighborhood=json.dumps(ss))
  for target in levels[metric]:
   base=480 if metric=='absolute' else 0;z=(target-base)/10;vv=np.array([z,z*z]);est=float(vv@beta);err=se(vv,covs);points=[support(g,col,base),support(g,col,target)];ok=all(good(p) for p in points) and g.day_key.nunique()>=100
   CONTRASTS.append(meta|dict(reference_kg=base,target_kg=target,difference_per1000m=est,se=err,lower=est-crit*err,upper=est+crit*err,supported=ok,support_points=json.dumps(points),n=len(g)))
 else:
  for j,band in enumerate([b for b in BINLABEL if b!='0']):
   base=g[g.change_bin.eq('0')];near=g[g.change_bin.eq(band)];vv=np.eye(len(beta))[j];err=se(vv,covs);ok=len(base)>=100 and len(near)>=100 and near.horse_id.nunique()>=30 and near.day_key.nunique()>=20
   CONTRASTS.append(meta|dict(reference_kg='0',target_kg=band,difference_per1000m=float(beta[j]),se=err,lower=float(beta[j]-crit*err),upper=float(beta[j]+crit*err),supported=ok,n=len(g)))
 MODELS.append(a);return a

def fit_distance(g,meta):
 col={'change':'body_change','absolute':'body_weight','relative':'relative_body','past_relative':'past_relative_body','change_bins':'body_change'}[meta['metric']];g=g[g[col].notna()];q,pi=prune(g)
 if len(q)<300:SKIP.append(meta|dict(input_n=len(g),n=len(q),reason='fewer than300 rows after singleton pruning'));return None
 if meta['metric']=='change_bins':x=np.column_stack([q.change_bin.eq(b).to_numpy(float) for b in BINLABEL if b!='0'])
 else:
  x0=(q[col].to_numpy()-(480 if meta['metric']=='absolute' else 0))/10;x=np.column_stack([x0,x0*x0])
 z,names=design(q,meta['specification']);y=q.finish.to_numpy()*1000/meta['distance_m'];a,it,err=absorb(np.column_stack([x,y,z]),[q.source_key,q.horse_id]);k=x.shape[1];xx=a[:,:k];yy=a[:,k];zz=a[:,k+1:]
 if zz.shape[1]:
  s=np.linalg.svd(zz,compute_uv=False);zr=int((s>s[0]*1e-10).sum());v=np.linalg.pinv(zz,rcond=1e-10)@np.column_stack([xx,yy]);rr=np.column_stack([xx,yy])-zz@v;xx,yy=rr[:,:k],rr[:,k]
 else:zr=0
 s=np.linalg.svd(xx,compute_uv=False);rank=int((s>s[0]*1e-10).sum())
 if rank<k:SKIP.append(meta|dict(input_n=len(g),n=len(q),reason='exposure not fully estimable'));return None
 fr,nc=fe_rank(q,True);DIAG.append(meta|dict(input_n=len(g),n=len(q),excluded_n=len(g)-len(q),prune_iterations=pi,fe_rank=fr,fe_components=nc,nuisance_rank=zr,exposure_rank=rank,nuisance_names='|'.join(names),absorb_iterations=it,max_group_mean=err))
 summarize(q,xx,yy,fr+zr,meta);return q,xx,yy,fr+zr

def fit_window(d,e,window,spec,metric):
 parts={}
 for a in e.itertuples():
  obj=fit_distance(d[d.meet.eq(a.meet)&d.distance_m.eq(a.distance_m)],dict(meet=a.meet,distance_m=int(a.distance_m),window=window,specification=spec,metric=metric))
  if obj is not None:parts.setdefault(a.meet,[]).append(obj)
 parts['전체']=[p for pp in list(parts.values()) for p in pp]
 for meet,pp in parts.items():
  if not pp:continue
  summarize(pd.concat([p[0] for p in pp]),np.vstack([p[1] for p in pp]),np.concatenate([p[2] for p in pp]),sum(p[3] for p in pp),dict(meet=meet,distance_m=0,window=window,specification=spec,metric=metric))
 print(window,spec,metric,'done',flush=True)

def main():
 d=prepare();e=d.groupby(['meet','distance_m']).agg(n=('row_key','size'),dates=('day_key','nunique')).reset_index();e['eligible']=e.n.ge(2000)&e.dates.ge(100)&e.distance_m.between(1000,1800);e.to_csv(O/'eligibility.csv',index=False);e=e[e.eligible]
 refresh='--change-and-past-only' in sys.argv
 if refresh:
  for name,records in [('models.csv',MODELS),('contrasts.csv',CONTRASTS),('terms.csv',TERMS),('diagnostics.csv',DIAG),('skipped.csv',SKIP)]:
   old=pd.read_csv(O/name);records.extend(old[old.metric.isin(['absolute','relative'])].to_dict('records'))
 for metric in (['change','past_relative'] if refresh else ['change','absolute','relative','past_relative']):
  for window,spec,dd in [('all','main',d),('all','fe_only',d),('complete_2024_2025','main',d[d.year.isin([2024,2025])]),('age4plus','main',d[d.age.ge(4)])]:fit_window(dd,e,window,spec,metric)
 conflict=d.previous_date.eq(d.last_history_date)&d.body_change.notna()&d.observed_change.ne(d.body_change)
 fit_window(d[~conflict],e,'exclude_one_history_conflict','main','change')
 fit_window(d,e,'all','main','change_bins')
 models=pd.DataFrame(MODELS)
 for metric in ['change','absolute','relative','past_relative']:
  ix=models.index[models.metric.eq(metric)&models.window.eq('all')&models.specification.eq('main')&models.distance_m.gt(0)];q=models.loc[ix];p=2*t.sf(abs(q.beta_quadratic/q.quadratic_se),np.minimum(q.horses,q.dates)-1);models.loc[ix,'curvature_bh_q']=false_discovery_control(np.asarray(p))
 models.to_csv(O/'models.csv',index=False);pd.DataFrame(CONTRASTS).to_csv(O/'contrasts.csv',index=False);pd.DataFrame(TERMS).to_csv(O/'terms.csv',index=False);pd.DataFrame(DIAG).to_csv(O/'diagnostics.csv',index=False);pd.DataFrame(SKIP).to_csv(O/'skipped.csv',index=False)
 print(models[models.distance_m.eq(0)&models.specification.eq('main')][['meet','window','metric','n','beta_linear','beta_quadratic','quadratic_lower','vertex_kg','minimum_supported']].to_string(index=False),flush=True)
if __name__=='__main__':main()
