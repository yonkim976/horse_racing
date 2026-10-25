"""Post-primary categorical shape/tail check, with independent sparse QR checks."""
from pathlib import Path
import json,math
import numpy as np,pandas as pd
from scipy import sparse,linalg
from scipy.sparse.linalg import splu
from scipy.sparse.csgraph import connected_components
from scipy.stats import t,false_discovery_control
from analyze import controls,cov,stats,FORM,OUTCOMES
from model import absorb,prune,fe_rank
H=Path(__file__).resolve().parent;O=H/'outputs';checks=[];rows=[];diags=[];distances=[];skipped=[]
d=pd.read_parquet(H.parent/'20261007_sex_ability_gap/outputs/population.parquet').merge(pd.read_parquet(H.parent/'20261008_body_weight_change_optimum/outputs/body_features.parquet')[['row_key','past_relative_body']],on='row_key',validate='one_to_one');d['day_key']=d.date.dt.strftime('%Y-%m-%d');d['age_squared']=d.age**2;d['finish1000']=d.finish*1000/d.distance_m;d['fade']=d.late-d.middle2/2;e=pd.read_csv(O/'eligibility.csv');e=e[e.eligible]
def check(name,error):
 error=float(error);assert error<4e-6,(name,error);checks.append(dict(check=name,error=error,tolerance=4e-6))
def explicit(q,xy,two):
 n=len(q);rc=pd.factorize(q.source_key)[0];nr=rc.max()+1;z=sparse.csr_matrix((np.ones(n),(np.arange(n),rc)),shape=(n,nr))
 if two:
  hc=pd.factorize(q.horse_id)[0];nh=hc.max()+1;adj=sparse.csr_matrix((np.ones(2*n),(np.r_[hc,rc+nh],np.r_[rc+nh,hc])),shape=(nh+nr,nh+nr));_,lab=connected_components(adj,directed=False);_,first=np.unique(lab[:nh],return_index=True);keep=np.ones(nh,bool);keep[first]=False;mapping=np.cumsum(keep)-1;mask=keep[hc];z=sparse.hstack([z,sparse.csr_matrix((np.ones(mask.sum()),(np.arange(n)[mask],mapping[hc[mask]])),shape=(n,keep.sum()))],format='csr')
 return xy-z@splu((z.T@z).tocsc()).solve(z.T@xy)
for window,metric,spec in [('all','absolute','main'),('all','absolute','sex_control'),('complete_2024_2025','absolute','main'),('all','past_relative','main'),('complete_2024_2025','past_relative','main')]:
 col='body_weight' if metric=='absolute' else 'past_relative_body';labels=['≤430','431–450','451–469','470–489','490–509','510–529','≥530'] if metric=='absolute' else ['≤−15','−14–−6','−5–+5','+6–+14','≥+15'];base='470–489' if metric=='absolute' else '−5–+5';edges=[-np.inf,430,450,469,489,509,529,np.inf] if metric=='absolute' else [-np.inf,-15,-6,5,14,np.inf];nonref=[v for v in labels if v!=base];k=len(nonref);parts={}
 for a in e.itertuples():
  q=d[d.meet.eq(a.meet)&d.distance_m.eq(a.distance_m)&d[col].notna()].copy()
  if window!='all':q=q[q.year.isin([2024,2025])]
  if metric!='absolute':q,_=prune(q)
  else:q=q[q.groupby('source_key').row_key.transform('size').ge(2)]
  if len(q)<300:skipped.append(dict(window=window,metric=metric,specification=spec,meet=a.meet,distance_m=a.distance_m,n=len(q),reason='fewer than300 repeat-comparable observations'));continue
  q=q.reset_index(drop=True)
  for name in ['early','middle1','middle2']:q[name+'_squared']=q[name]**2
  q['category']=pd.cut(q[col],edges,labels=labels);x=np.column_stack([q.category.eq(v).to_numpy(float) for v in nonref]);z,names=controls(q);xy=np.column_stack([x,q[OUTCOMES].to_numpy(),z]);dm,_,_=absorb(xy,[q.source_key] if metric=='absolute' else [q.source_key,q.horse_id]);alt=explicit(q,xy,metric!='absolute');fr,_=fe_rank(q,metric!='absolute')
  for j,outcome in enumerate(OUTCOMES):
   pace=[] if outcome=='finish1000' else ['early','early_squared','middle1','middle1_squared']+(['middle2','middle2_squared'] if outcome=='late' else []);nn=FORM+[n for n in names if n.endswith('_missing')]+pace+(['sex_암','sex_거'] if spec=='sex_control' else []);ix=[i for i,n in enumerate(names) if n in nn];zz=dm[:,k+4+np.array(ix)];r=dm[:,list(range(k))+[k+j]];ss=np.linalg.svd(zz,compute_uv=False);rank=int((ss>ss[0]*1e-10).sum());r=r-zz@(np.linalg.pinv(zz,rcond=1e-10)@r);altz=alt[:,k+4+np.array(ix)];altr=alt[:,list(range(k))+[k+j]];ab,_,arank,_=linalg.lstsq(altz,altr,cond=1e-10,lapack_driver='gelsy');altr-=altz@ab;assert arank==rank;bb,_,xr,_=linalg.lstsq(altr[:,:k],altr[:,k],cond=1e-10,lapack_driver='gelsy');b=np.linalg.pinv(r[:,:k],rcond=1e-10)@r[:,k];assert xr==k;check('tail independent distance coefficient',max(abs(b-bb)));diags.append(dict(window=window,metric=metric,specification=spec,meet=a.meet,distance_m=a.distance_m,outcome=outcome,n=len(q),fe_rank=fr,nuisance_rank=rank));parts.setdefault(outcome,[]).append((q,r[:,:k],r[:,k],fr+rank));distances.append(dict(window=window,metric=metric,specification=spec,meet=a.meet,distance_m=a.distance_m,outcome=outcome,coefficients=json.dumps(b.tolist())))
 for outcome,pp in parts.items():
  for meet in ['서울','부산','전체']:
   selected=[p for p in pp if meet=='전체' or p[0].meet.iloc[0]==meet];q=pd.concat([p[0] for p in selected],ignore_index=True);x=np.vstack([p[1] for p in selected]);y=np.concatenate([p[2] for p in selected]);rank=sum(p[3] for p in selected);long=q.distance_m.ge(1600).to_numpy();xx=np.column_stack([x*(~long)[:,None],x*long[:,None]]);b,vs,df=cov(q,xx,y,rank);ib,_,_,_=linalg.lstsq(xx,y,cond=1e-10,lapack_driver='gelsy');check('tail joint QR',max(abs(b-ib)));score=linalg.pinv(xx,rtol=1e-10).T*(y-xx@ib)[:,None];altv=[]
   for ids in [q.horse_id,q.day_key,pd.MultiIndex.from_frame(q[['horse_id','day_key']])]:
    agg=pd.DataFrame(score).groupby(pd.factorize(ids)[0]).sum().to_numpy();ng=len(agg);altv.append(agg.T@agg*ng/(ng-1)*(len(q)-1)/df)
   altv=[altv[0],altv[1],altv[0]+altv[1]-altv[2]]
   for group,mask,offset in [('short',~long,0),('long',long,k)]:
    qq=q[mask];ref=qq[qq.category.eq(base)]
    for j,label in enumerate(nonref):
     near=qq[qq.category.eq(label)];v=np.eye(2*k)[offset+j];ss=stats(v,b,vs,q);err=math.sqrt(max(0,max(float(v@a@v) for a in altv)));check('tail clustered SE',abs(err-ss['se']));ok=all(len(vv)>=100 and vv.horse_id.nunique()>=30 and vv.day_key.nunique()>=20 for vv in [ref,near]);primary=window=='all' and spec=='main' and meet=='전체' and ((group=='short' and outcome=='finish1000' and label==nonref[-1]) or (group=='long' and outcome=='late' and label==nonref[0]));rows.append(dict(window=window,metric=metric,specification=spec,meet=meet,outcome=outcome,group=group,reference=base,target=label,n=len(near),horses=near.horse_id.nunique(),dates=near.day_key.nunique(),reference_n=len(ref),supported=ok,exploratory_primary=primary,bh_q=np.nan)|ss)
 print('tail completed',window,metric,spec,flush=True)
c=pd.DataFrame(rows);ix=c.exploratory_primary;assert ix.sum()==4;c.loc[ix,'bh_q']=false_discovery_control(c.loc[ix,'p'].to_numpy());c.to_csv(O/'categorical_contrasts.csv',index=False);pd.DataFrame(diags).to_csv(O/'categorical_diagnostics.csv',index=False);pd.DataFrame(distances).to_csv(O/'categorical_distance_coefficients.csv',index=False);pd.DataFrame(skipped).to_csv(O/'categorical_skipped.csv',index=False);(O/'categorical_verification.json').write_text(json.dumps(dict(passed=True,post_primary_exploratory=True,independent_distance_coefficients=len(diags),skipped=skipped,checks=checks),ensure_ascii=False,indent=2)+'\n');print(c[ix].to_string(index=False))
