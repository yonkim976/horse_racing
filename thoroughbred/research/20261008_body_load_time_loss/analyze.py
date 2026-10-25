"""Conditional body-mass by carried-load associations, including horse and race effects."""
from pathlib import Path
import hashlib,json,time
import numpy as np,pandas as pd
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.stats import t
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2]
SOURCE=H.parent/'20261007_sex_ability_gap/outputs/population.parquet'
CORE=['load_center','load_squared','body_center','body_squared','load_body']
FORM=['rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap']
RESULT=[];META=[];COEFFICIENTS=[];SKIPPED=[]

def load():
 d=pd.read_parquet(SOURCE);d['rank']=pd.to_numeric(d.rank_raw,errors='raise');d['age_squared']=d.age**2
 return d

def prune(g):
 q=g.copy();iterations=0
 while True:
  keep=q.groupby('horse_id').horse_id.transform('size').ge(2)&q.groupby('source_key').source_key.transform('size').ge(2)
  if keep.all():break
  q=q[keep].copy();iterations+=1
 return q,iterations

def incidence(ids):
 c=pd.factorize(ids)[0];n=np.bincount(c);a=sparse.csr_matrix((1/n[c],(c,np.arange(len(c)))),shape=(len(n),len(c)))
 return c,a

def absorb(y,groups):
 out=y.copy();ops=[incidence(g) for g in groups]
 if not ops:return out,0,0.
 for it in range(20000):
  old=out.copy()
  for c,a in ops:out-= (a@out)[c]
  change=np.max(abs(out-old))
  if change<1e-13:break
 else:raise RuntimeError('Absorption did not converge')
 err=max(float(np.max(abs(a@out))) for _,a in ops)
 assert err<1e-10,err
 return out,it+1,err

def fe_rank(g,two):
 nr=g.source_key.nunique()
 if not two:return nr,1
 hc=pd.factorize(g.horse_id)[0];rc=pd.factorize(g.source_key)[0];nh=hc.max()+1
 u=np.r_[hc,rc+nh];v=np.r_[rc+nh,hc];adj=sparse.csr_matrix((np.ones(len(u)),(u,v)),shape=(nh+nr,nh+nr))
 nc=connected_components(adj,directed=False,return_labels=False)
 return int(nh+nr-nc),int(nc)

def design(g,full=True,no_rating=False):
 w=g.weight.to_numpy()-54;b=(g.body_weight.to_numpy()-480)/50
 xs=[w,w*w,b,b*b,w*b];names=CORE.copy()
 if full:
  cols=['sex_female','sex_gelded','age','age_squared']+[a for a in FORM if not(no_rating and a.startswith('rating'))]
  z=g.assign(sex_female=g.sex.eq('암').astype(float),sex_gelded=g.sex.eq('거').astype(float))
  for col in cols:
   v=z[col].to_numpy(float);missing=~np.isfinite(v)
   if missing.all():continue
   v=np.where(missing,np.median(v[~missing]),v)
   if v.std()>1e-10:xs.append((v-v.mean())/v.std());names.append(col)
   if missing.any():xs.append(missing.astype(float));names.append(col+'_missing')
 return np.column_stack(xs),names

def cluster(score,ids,cor):
 c=pd.factorize(ids)[0];n=c.max()+1;agg=np.bincount(c,weights=score)
 return float(agg@agg)*n/(n-1)*cor,n

def supported(g,body,weight):
 q=g[g.body_weight.between(body-15,body+15)&g.weight.between(weight-.5,weight+.5)]
 a=dict(n=len(q),horses=q.horse_id.nunique(),dates=q.day_key.nunique())
 return a['n']>=100 and a['horses']>=30 and a['dates']>=20,a

def fit(g,meta):
 spec=meta['specification'];two=spec.startswith('horse_race');q,prune_iters=prune(g) if two else (g.copy(),0)
 if len(q)<300:
  SKIPPED.append(meta|dict(input_n=len(g),n=len(q),pruned_n=len(g)-len(q),reason='fewer than300 rows after recursive FE singleton removal'));return None
 x,names=design(q,full=spec!='raw',no_rating=spec.endswith('no_rating'))
 if spec=='raw':x=np.column_stack([x,np.ones(len(q))]);names+=['intercept'];groups=[];frank=0;components=1
 else:
  groups=[q.source_key]+([q.horse_id] if two else []);frank,components=fe_rank(q,two)
 outcomes=['finish','early','late'];y=q[outcomes].to_numpy(float);dm,it,err=absorb(np.column_stack([x,y]),groups)
 xd=dm[:,:x.shape[1]];yd=dm[:,x.shape[1]:];singular=np.linalg.svd(xd,compute_uv=False);pseudo=np.linalg.pinv(xd,rcond=1e-10);inv=pseudo@pseudo.T;beta=pseudo@yd;resid=yd-xd@beta
 rank=int(np.sum(singular>singular[0]*1e-10));df=len(q)-frank-rank;assert df>0
 proj=pseudo@xd;cor=(len(q)-1)/df;nh=q.horse_id.nunique();nd=q.day_key.nunique();crit=t.ppf(.975,min(nh,nd)-1)
 byhorse=q.groupby('horse_id').weight.agg(['min','max','size']);changing=(byhorse['max']-byhorse['min']).ge(.5)
 metadata=meta|dict(input_n=len(g),n=len(q),pruned_n=len(g)-len(q),prune_iterations=prune_iters,horses=nh,races=q.source_key.nunique(),dates=nd,fe_rank=frank,fe_components=components,design_rank=int(rank),residual_df=int(df),absorb_iterations=it,max_absorbed_group_mean=err,changing_load_horses=int(changing.sum()),changing_load_rows=int(byhorse.loc[changing,'size'].sum()),min_body=float(q.body_weight.min()),max_body=float(q.body_weight.max()),min_load=float(q.weight.min()),max_load=float(q.weight.max()),names='|'.join(names))
 META.append(metadata)
 for j,part in enumerate(outcomes):
  for i,name in enumerate(CORE):COEFFICIENTS.append(meta|dict(part=part,term=name,coefficient=float(beta[i,j])))
 vectors=[]
 for body in [450,480,510]:
  for to in [52,53,55,56,57,58]:
   dw=to-54;v=np.zeros(x.shape[1]);v[0]=dw;v[1]=dw*dw;v[4]=dw*(body-480)/50
   vectors.append(('load_change',body,54,to,v,[(body,54),(body,to)]))
 # Difference in 54->55 association: light 450kg minus heavy 510kg.
 v=np.zeros(x.shape[1]);v[4]=-1.2;vectors.append(('light_minus_heavy',450,54,55,v,[(450,54),(450,55),(510,54),(510,55)]))
 for kind,body,frm,to,v,points in vectors:
  checks=[supported(q,b,w) for b,w in points];ok=all(a[0] for a in checks) and np.allclose(proj@v,v,atol=1e-7)
  for j,part in enumerate(outcomes):
   score=(v@pseudo)*resid[:,j];vh,_=cluster(score,q.horse_id,cor);vd,_=cluster(score,q.day_key,cor);vi,_=cluster(score,q.horse_id+':'+q.day_key,cor);se=np.sqrt(max(vh,vd,vh+vd-vi,0));est=float(v@beta[:,j])
   RESULT.append(meta|dict(part=part,contrast=kind,body_kg=body,comparison_body_kg=510 if kind=='light_minus_heavy' else body,from_load=frm,to_load=to,difference_seconds=est,se_seconds=se,lower=est-crit*se if ok else np.nan,upper=est+crit*se if ok else np.nan,supported=ok,estimable=bool(np.allclose(proj@v,v,atol=1e-7)),n=len(q),horses=nh,races=q.source_key.nunique(),dates=nd,support_points=json.dumps([dict(body=b,load=w,**a[1]) for (b,w),a in zip(points,checks)])))
 return q,x,xd,yd,beta,inv,resid,metadata

def descriptions(d):
 rows=[]
 for (meet,dist),g in d.groupby(['meet','distance_m']):
  for body,lo,hi in [(435,420,449.999),(465,450,479.999),(495,480,509.999),(525,510,539.999)]:
   q=g[g.body_weight.between(lo,hi)]
   for weight,v in q.groupby('weight'):
    a=dict(meet=meet,distance_m=dist,body_band=f'{lo:g}~{hi+0.001:g}',weight=weight,n=len(v),horses=v.horse_id.nunique(),races=v.source_key.nunique(),dates=v.day_key.nunique())
    for c in ['body_weight','finish','early','late']:a.update({c+'_mean':v[c].mean(),c+'_median':v[c].median(),c+'_p20':v[c].quantile(.2),c+'_p80':v[c].quantile(.8)})
    rows.append(a)
 pd.DataFrame(rows).to_csv(O/'observed_body_load_cells.csv',index=False)

def main():
 d=load();assert len(d)==151074;descriptions(d)
 eligibility=d.groupby(['meet','distance_m']).agg(n=('row_key','size'),horses=('horse_id','nunique'),races=('source_key','nunique'),dates=('day_key','nunique')).reset_index()
 eligibility['primary_eligible']=eligibility.n.ge(2000)&eligibility.dates.ge(100)&eligibility.distance_m.le(1800);eligibility.to_csv(O/'distance_eligibility.csv',index=False)
 for a in eligibility[eligibility.primary_eligible].itertuples():
  g=d[d.meet.eq(a.meet)&d.distance_m.eq(a.distance_m)]
  for spec in ['raw','race_full','horse_race_full','horse_race_no_rating']:
   fit(g,dict(meet=a.meet,distance_m=a.distance_m,window='all',specification=spec))
  fit(g[g.year.isin([2024,2025])],dict(meet=a.meet,distance_m=a.distance_m,window='complete_2024_2025',specification='horse_race_full'))
  if a.distance_m==1200:fit(g[g['rank'].le(5)],dict(meet=a.meet,distance_m=a.distance_m,window='top5_selected',specification='horse_race_full'))
  print(a.meet,a.distance_m,'done',flush=True)
 result=pd.DataFrame(RESULT)
 primary=result[result.window.eq('all')&result.specification.eq('horse_race_full')&result.part.eq('finish')&result.contrast.eq('light_minus_heavy')&result.supported]
 pvals=2*t.sf(abs(primary.difference_seconds/primary.se_seconds),np.minimum(primary.horses,primary.dates)-1);order=np.argsort(pvals);adjusted=np.empty(len(pvals));adjusted[order]=np.minimum(1,np.minimum.accumulate((pvals[order]*len(pvals)/np.arange(1,len(pvals)+1))[::-1])[::-1])
 result['modifier_bh_q']=np.nan;result['modifier_p']=np.nan;result.loc[primary.index,'modifier_p']=pvals;result.loc[primary.index,'modifier_bh_q']=adjusted
 result.to_csv(O/'load_contrasts.csv',index=False);pd.DataFrame(SKIPPED).to_csv(O/'skipped_models.csv',index=False);pd.DataFrame(META).to_csv(O/'model_diagnostics.csv',index=False);pd.DataFrame(COEFFICIENTS).to_csv(O/'core_coefficients.csv',index=False)
 inputs=[SOURCE,H.parent/'20261007_sex_ability_gap/outputs/source_audit.json',H.parent/'20261005_relative_load1200/outputs/weight_population.parquet',H.parent/'20261005_relative_load1200/README.md',H.parent/'20261007_sex_top5_followup/outputs/contrasts.csv']
 obj=dict(executed_on='2026-10-08',input_n=len(d),races=d.source_key.nunique(),horses=d.horse_id.nunique(),inputs_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},source_end=d.groupby('meet').date.max().astype(str).to_dict(),primary_distances=eligibility[eligibility.primary_eligible][['meet','distance_m']].to_dict('records'),formula='Wc + Wc^2 + Bc + Bc^2 + Wc*Bc; Wc=carried-54, Bc=(body-480)/50',main_question='54->55kg change conditional on body=450/480/510kg; light 450 minus heavy 510 contrast',no_new_source_requests=True,causal=False,operational_correction=False,uncertainty='horse/date two-way or either one-way maximum; FE rank and t correction; pointwise95%',support='each required (body+-15kg,load+-.5kg) neighborhood:100 rows,30 horses,20 dates',limitations=['load assignment is endogenous','body weight and status may change with ability,health and age','race and horse effects do not identify random load changes','quadratic interaction structure','normal finish selection','current body publication timing not verified','top5 is outcome-selected sensitivity','no prediction evaluation'])
 (O/'source_and_method.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');print('saved',len(META),'models',len(RESULT),'contrasts')
if __name__=='__main__':main()
