"""Mass × distance hypotheses; read-only prior populations, race/horse FE."""
from pathlib import Path
import hashlib,json,math
import numpy as np,pandas as pd
from scipy.stats import t,false_discovery_control
from model import absorb,prune,fe_rank
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2]
P=H.parent/'20261007_sex_ability_gap/outputs/population.parquet'
F=H.parent/'20261008_body_weight_change_optimum/outputs/body_features.parquet'
FORM=['weight','weight_squared','age','age_squared','rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap']
OUTCOMES=['finish1000','late','last600','fade'];MODELS=[];C=[];D=[];SKIP=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def prepare():
 d=pd.read_parquet(P).merge(pd.read_parquet(F)[['row_key','past_body_mean','past_relative_body','previous_date']],on='row_key',validate='one_to_one');d['day_key']=d.date.dt.strftime('%Y-%m-%d');d['age_squared']=d.age**2;d['finish1000']=d.finish*1000/d.distance_m;d['fade']=d.late-d.middle2/2
 assert len(d)==151074 and d.row_key.is_unique and not d.duplicated(['horse_id','date']).any()
 assert (d.previous_date.dropna()<d.loc[d.previous_date.notna(),'date']).all()
 assert abs(d.finish-d[['early','middle1','middle2','late']].sum(axis=1)).max()<1e-8
 assert abs(d.last600-d.middle2-d.late).max()<1e-8
 e=d.groupby(['meet','distance_m']).agg(n=('row_key','size'),dates=('day_key','nunique')).reset_index();e['eligible']=e.n.ge(2000)&e.dates.ge(100)&e.distance_m.between(1000,1800);e.to_csv(O/'eligibility.csv',index=False)
 audit=dict(input_n=len(d),races=d.source_key.nunique(),horses=d.horse_id.nunique(),source_start=d.groupby('meet').date.min().astype(str).to_dict(),source_end=d.groupby('meet').date.max().astype(str).to_dict(),inputs_sha256={str(p.relative_to(ROOT)):sha(p) for p in [P,F]},eligible_n=int(e.loc[e.eligible,'n'].sum()),eligible_distances=int(e.eligible.sum()),past_relative_missing=int(d.past_relative_body.isna().sum()),late_definition='last200 seconds',fade_definition='last200 minus preceding400/2, seconds',last600_overlaps_late=True,actual_path_length_inferred=False,causal=False,operational=False)
 (O/'source_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
 d['mass_bin']=pd.cut(d.body_weight,[-np.inf,450,469,489,509,np.inf],labels=['≤450','451–469','470–489','490–509','≥510'])
 rows=[]
 for (m,dist,b),q in d.groupby(['meet','distance_m','mass_bin'],observed=True):
  a=dict(meet=m,distance_m=dist,mass_bin=str(b),n=len(q),horses=q.horse_id.nunique(),dates=q.day_key.nunique(),body_mean=q.body_weight.mean())
  for y in ['finish','late','last600','fade']:
   for s,v in [('mean',q[y].mean()),('median',q[y].median()),('p20',q[y].quantile(.2)),('p80',q[y].quantile(.8))]:a[y+'_'+s]=v
  rows.append(a)
 pd.DataFrame(rows).to_csv(O/'observed_mass_sections.csv',index=False)
 return d,e[e.eligible]
def controls(q):
 z=[];names=[]
 for col in FORM+['early','early_squared','middle1','middle1_squared','middle2','middle2_squared']:
  v=q[col].to_numpy(float);miss=~np.isfinite(v)
  if miss.all():continue
  v=np.where(miss,np.nanmedian(v),v)
  if v.std()>1e-10:z.append((v-v.mean())/v.std());names.append(col)
  if miss.any():z.append(miss.astype(float));names.append(col+'_missing')
 for value in ['암','거']:
  z.append(q.sex.eq(value).to_numpy(float));names.append('sex_'+value)
 return np.column_stack(z),names
def cov(q,x,y,rank):
 b=np.linalg.pinv(x,rcond=1e-10)@y;res=y-x@b;score=np.linalg.pinv(x,rcond=1e-10).T*res[:,None];df=len(q)-rank-x.shape[1];assert df>0;v=[]
 for ids in [q.horse_id,q.day_key,q.horse_id+':'+q.day_key]:
  cc=pd.factorize(ids)[0];ng=cc.max()+1;agg=np.zeros((ng,x.shape[1]));np.add.at(agg,cc,score);v.append(agg.T@agg*ng/(ng-1)*(len(q)-1)/df)
 return b,[v[0],v[1],v[0]+v[1]-v[2]],df
def stats(v,b,vs,q):
 est=float(v@b);err=math.sqrt(max(0,max(float(v@a@v) for a in vs)));df=min(q.horse_id.nunique(),q.day_key.nunique())-1;crit=t.ppf(.975,df);return dict(estimate=est,se=err,lower=est-crit*err,upper=est+crit*err,p=float(2*t.sf(abs(est/err),df)) if err>0 else 0.)
def support(q,metric,target):
 col='body_weight' if metric=='absolute' else 'past_relative_body';base=480 if metric=='absolute' else 0;ss=[]
 for point in [base,target]:
  r=q[q[col].between(point-5,point+5)];ss.append(dict(point=point,n=len(r),horses=r.horse_id.nunique(),dates=r.day_key.nunique()))
 return all(a['n']>=100 and a['horses']>=30 and a['dates']>=20 for a in ss),json.dumps(ss)
def summary(q,x,y,rank,meta):
 b,vs,df=cov(q,x,y,rank);rec=meta|dict(n=len(q),horses=q.horse_id.nunique(),races=q.source_key.nunique(),dates=q.day_key.nunique(),control_rank=rank,residual_df=df,beta_linear=b[0],beta_quadratic=b[1],date_min=str(q.date.min()),date_max=str(q.date.max()))
 MODELS.append(rec)
 for target in ([450,510] if meta['metric']=='absolute' else [-10,10]):
  base=480 if meta['metric']=='absolute' else 0;z=(target-base)/10;ok,ss=support(q,meta['metric'],target)
  C.append(meta|dict(comparison='target_vs_reference',reference_kg=base,target_kg=target,supported=ok,support_points=ss,n=len(q),primary=False,bh_q=np.nan)|stats(np.array([z,z*z]),b,vs,q))
def joint(parts,meta):
 if not parts:return
 q=pd.concat([p[0] for p in parts],ignore_index=True);x=np.vstack([p[1] for p in parts]);y=np.concatenate([p[2] for p in parts]);rank=sum(p[3] for p in parts);long=q.distance_m.ge(1600).to_numpy();xx=np.column_stack([x*(~long)[:,None],x*long[:,None]]);b,vs,df=cov(q,xx,y,rank)
 for group,ix in [('short',0),('long',2)]:
  qq=q[long if group=='long' else ~long];i=np.where(long if group=='long' else ~long)[0];summary(qq,x[i],y[i],sum(p[3] for p in parts if (p[0].distance_m.iloc[0]>=1600)==(group=='long')),meta|dict(scope=group,distance_m=0))
 for target in ([450,510] if meta['metric']=='absolute' else [-10,10]):
  base=480 if meta['metric']=='absolute' else 0;z=(target-base)/10;v0=np.array([z,z*z]);short=np.r_[v0,0,0];longv=np.r_[0,0,v0]
  ok1,s1=support(q[~long],meta['metric'],target);ok2,s2=support(q[long],meta['metric'],target)
  for name,v in [('short',short),('long',longv),('short_minus_long',short-longv),('long_minus_short',longv-short)]:
   heavy=target>base;primary=meta['window']=='all' and meta['specification']=='main' and ((heavy and meta['outcome']=='finish1000' and name in ['short','short_minus_long']) or (not heavy and meta['outcome']=='late' and name in ['long','long_minus_short']))
   C.append(meta|dict(scope='joint',distance_m=0,comparison=name,reference_kg=base,target_kg=target,supported=(ok1 if name=='short' else ok2 if name=='long' else ok1 and ok2),support_points=json.dumps(dict(short=json.loads(s1),long=json.loads(s2))),n=len(q),primary=primary,bh_q=np.nan)|stats(v,b,vs,q))
def run_config(d,e,window,metric):
 parts={};col='body_weight' if metric=='absolute' else 'past_relative_body'
 for a in e.itertuples():
  q=d[d.meet.eq(a.meet)&d.distance_m.eq(a.distance_m)&d[col].notna()].copy();input_n=len(q)
  if metric!='absolute':q,pi=prune(q)
  else:q=q[q.groupby('source_key').row_key.transform('size').ge(2)].copy();pi=0
  if len(q)<300:SKIP.append(dict(window=window,metric=metric,meet=a.meet,distance_m=a.distance_m,n=len(q)));continue
  q=q.reset_index(drop=True)
  for c in ['early','middle1','middle2']:q[c+'_squared']=q[c]**2
  z,names=controls(q);u=(q[col].to_numpy()-(480 if metric=='absolute' else 0))/10;x=np.column_stack([u,u*u]);yy=q[OUTCOMES].to_numpy()
  dm,it,err=absorb(np.column_stack([x,yy,z]),[q.source_key] if metric=='absolute' else [q.source_key,q.horse_id]);fr,nc=fe_rank(q,metric!='absolute');dz=dm[:,6:]
  specs=['main']+(['no_pace'] if window=='all' else [])+(['sex_control'] if metric=='absolute' and window=='all' else [])
  for spec in specs:
   for j,yname in enumerate(OUTCOMES):
    pace=[] if spec=='no_pace' or yname=='finish1000' else ['early','early_squared','middle1','middle1_squared']+(['middle2','middle2_squared'] if yname=='late' else [])
    nn=FORM+[n for n in names if n.endswith('_missing') and n.split('_missing')[0] in FORM]+pace+(['sex_암','sex_거'] if spec=='sex_control' else [])
    ix=[i for i,n in enumerate(names) if n in nn];zz=dz[:,ix];xy=dm[:,[0,1,2+j]]
    if zz.shape[1]:
     sv=np.linalg.svd(zz,compute_uv=False);zr=int((sv>sv[0]*1e-10).sum());xy=xy-zz@(np.linalg.pinv(zz,rcond=1e-10)@xy)
    else:zr=0
    xx,y=xy[:,:2],xy[:,2];assert np.linalg.matrix_rank(xx,tol=np.linalg.svd(xx,compute_uv=False)[0]*1e-10)==2
    meta=dict(window=window,metric=metric,specification=spec,outcome=yname,meet=a.meet,distance_m=int(a.distance_m),scope='distance')
    D.append(meta|dict(input_n=input_n,n=len(q),excluded_n=input_n-len(q),prune_iterations=pi,fe_rank=fr,fe_components=nc,nuisance_rank=zr,nuisance_names='|'.join(names[i] for i in ix),absorb_iterations=it,max_group_mean=err))
    summary(q,xx,y,fr+zr,meta);parts.setdefault((spec,yname),[]).append((q,xx,y,fr+zr))
 for (spec,yname),pp in parts.items():
  for meet in ['서울','부산','전체']:
   selected=[p for p in pp if meet=='전체' or p[0].meet.iloc[0]==meet];joint(selected,dict(window=window,metric=metric,specification=spec,outcome=yname,meet=meet))
 print('completed',window,metric,flush=True)
def main():
 d,e=prepare()
 for window,q in [('all',d),('complete_2024_2025',d[d.year.isin([2024,2025])]),('age4plus',d[d.age.ge(4)])]:
  for metric in ['absolute','past_relative']:run_config(q,e,window,metric)
 c=pd.DataFrame(C);ix=c.index[c.primary&c.meet.eq('전체')];assert len(ix)==8;c.loc[ix,'bh_q']=false_discovery_control(c.loc[ix,'p'].to_numpy());pd.DataFrame(MODELS).to_csv(O/'models.csv',index=False);c.to_csv(O/'contrasts.csv',index=False);pd.DataFrame(D).to_csv(O/'diagnostics.csv',index=False);pd.DataFrame(SKIP).to_csv(O/'skipped.csv',index=False)
 print(c.loc[ix,['metric','outcome','comparison','target_kg','estimate','lower','upper','bh_q','supported']].to_string(index=False),flush=True)
if __name__=='__main__':main()
