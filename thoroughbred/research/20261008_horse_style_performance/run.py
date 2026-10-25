"""Observed S1F styles, conditional performance and chronological change follow-up."""
from pathlib import Path
from itertools import combinations
import hashlib,json,math
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import LinearOperator,cg
from scipy.stats import t

H=Path(__file__).resolve().parent;ROOT=H.parents[2];R=H.parent;O=H/'outputs';M=H/'models'
LABELS=['선행','선입','중단','후미'];CUTOFF=pd.Timestamp('2026-09-20');ASOF=pd.Timestamp('2026-09-22')
INPUTS=[R/'20261008_passing_group_style/outputs/observations.parquet',R/'20261007_sex_ability_gap/outputs/population.parquet',R/'20261008_running_style_foundation/outputs/observed_styles.parquet']
FORM=['age','age_squared','weight','body_weight','rating','prior_finish','prior_top3','log_starts','log_gap','gate_relative']
FITLOG=[]
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def center(v,c):
 n=np.bincount(c)
 return v-np.bincount(c,weights=v)[c]/n[c]
def interval(q,v,w=None):
 v=np.asarray(v,float);w=np.ones(len(v)) if w is None else np.asarray(w,float);est=float(w@v/w.sum());s=w*(v-est)/w.sum();vs=[];ng=[]
 for ids in [q.horse_id,q.date.dt.strftime('%Y-%m-%d'),q.horse_id+':'+q.date.dt.strftime('%Y-%m-%d')]:
  c=pd.factorize(ids)[0];g=int(c.max()+1);z=np.bincount(c,weights=s);vs.append(float(z@z)*g/(g-1) if g>1 else 0.);ng.append(g)
 se=math.sqrt(max(0.,vs[0],vs[1],vs[0]+vs[1]-vs[2]));crit=float(t.ppf(.975,min(ng[:2])-1)) if min(ng[:2])>1 else float('nan')
 return dict(estimate=est,se=se,lower=est-crit*se,upper=est+crit*se,n=len(q),horses=q.horse_id.nunique(),dates=q.date.nunique())
def prepare():
 a=pd.read_parquet(INPUTS[0]);p=pd.read_parquet(INPUTS[1]);f=pd.read_parquet(INPUTS[2],columns=['row_key','grade_normalized','raw_finish_rank','finish_p'])
 assert len(a)==159014 and len(p)==151074 and all(x.row_key.is_unique for x in [a,p,f])
 a=a.merge(f,on='row_key',validate='one_to_one').sort_values(['horse_id','date','source_key']).reset_index(drop=True)
 a['performance_retained']=a.row_key.isin(p.row_key);a['normal_outcome']=a.raw_finish_rank.between(1,a.field_size)
 a.to_parquet(O/'roster.parquet',index=False)
 keep=['row_key','horse_name','role4','role5','group_mean_relative','gate','leader_conflict_race','selected_source']
 d=p.merge(a[keep],on='row_key',validate='one_to_one');d=d[d.role4.ge(0)].copy().reset_index(drop=True)
 d['day_key']=d.date.dt.strftime('%Y-%m-%d');d['age_squared']=d.age**2;d['gate_relative']=(d.gate-1)/(d.field_size-1)
 d['distance_band']=np.where(d.distance_m.le(1400),'short',np.where(d.distance_m.le(1800),'middle','long'))
 d['stratum']=d.meet+':'+d.distance_band;d['hd_key']=d.horse_id+':'+d.distance_m.astype(str);d['hs_key']=d.horse_id+':'+d.role4.astype(str)
 d['y']=-100*np.log(d.finish);assert (d.last_history_date.isna()|d.last_history_date.lt(d.date)).all()
 audit=dict(roster_n=len(a),roster_horses=a.horse_id.nunique(),roster_races=a.source_key.nunique(),group_observed=int(a.group_observed.sum()),normal_population_n=len(p),analysis_n=len(d),analysis_horses=d.horse_id.nunique(),analysis_races=d.source_key.nunique(),normal_population_missing_group=len(p)-len(d),non_normal_with_group=int((a.group_observed&~a.performance_retained).sum()),input_files=[dict(path=str(x.relative_to(ROOT)),bytes=x.stat().st_size,sha256=sha(x)) for x in INPUTS],start_by_meet=a.groupby('meet').date.min().astype(str).to_dict(),end_by_meet=a.groupby('meet').date.max().astype(str).to_dict(),asof=str(ASOF.date()),cutoff=str(CUTOFF.date()),uses_track_speed=False,causal=False,operational=False)
 dump(O/'source_audit.json',audit)
 a.groupby(['meet','role4']).agg(n=('row_key','size'),normal_n=('performance_retained','sum'),horses=('horse_id','nunique')).reset_index().to_csv(O/'selection_by_style.csv',index=False)
 d.groupby(['meet','distance_m','role4']).agg(n=('row_key','size'),horses=('horse_id','nunique'),races=('source_key','nunique'),time_mean=('finish','mean'),time_median=('finish','median'),p20=('finish',lambda x:x.quantile(.2)),p80=('finish',lambda x:x.quantile(.8)),top5=('rank_raw',lambda x:x.le(5).mean())).reset_index().to_csv(O/'raw_distance_style.csv',index=False)
 return a,d
def spec(q,kind,lam):
 st={}
 for s,g in q.groupby('stratum'):
  cols=[];med=[]
  for col in FORM:
   v=g[col].to_numpy(float);m=float(np.nanmedian(v)) if np.isfinite(v).any() else 0.;med.append(m);cols.append(np.where(np.isfinite(v),v,m))
  cols +=[(~np.isfinite(g[col].to_numpy(float))).astype(float) for col in FORM];x=np.column_stack(cols);sd=x.std(axis=0);sd[sd<1e-8]=1.
  st[s]=dict(medians=med,means=x.mean(axis=0).tolist(),sds=sd.tolist())
 horses=sorted(q.horse_id.unique());hd=sorted(q.hd_key.unique());hs=sorted(q.hs_key.unique()) if kind=='personal' else []
 owner=pd.Index(horses).get_indexer(pd.Series(hs).str.rsplit(':',n=1).str[0]) if hs else np.array([],int)
 counts=q.hs_key.value_counts().reindex(hs).to_numpy() if hs else np.array([]);hn=q.horse_id.value_counts().reindex(horses).to_numpy()
 return dict(kind=kind,lambda_style=lam,horses=horses,horse_distances=hd,horse_styles=hs,hs_owner=owner.tolist(),hs_weights=(counts/hn[owner]).tolist() if hs else [],strata=sorted(st),statistics=st,train_n=len(q),train_end=str(q.date.max().date()),form=FORM)
def matrix(q,sp):
 n=len(q);k=len(FORM)*2;ns=len(sp['strata']);sc=pd.Index(sp['strata']).get_indexer(q.stratum);assert (sc>=0).all();a=np.zeros((n,k))
 for s in sp['strata']:
  mask=q.stratum.eq(s).to_numpy();g=q.loc[mask];st=sp['statistics'][s];cols=[]
  for j,col in enumerate(FORM):
   v=g[col].to_numpy(float);cols.append(np.where(np.isfinite(v),v,st['medians'][j]))
  cols +=[(~np.isfinite(g[col].to_numpy(float))).astype(float) for col in FORM];a[mask]=(np.column_stack(cols)-st['means'])/st['sds']
 cx=sparse.csr_matrix((a.ravel(),(np.repeat(np.arange(n),k),np.repeat(sc*k,k)+np.tile(np.arange(k),n))),shape=(n,ns*k))
 hc=pd.Index(sp['horses']).get_indexer(q.horse_id);mask=hc>=0;bx=sparse.csr_matrix((np.ones(mask.sum()),(np.arange(n)[mask],hc[mask])),shape=(n,len(sp['horses'])))
 dc=pd.Index(sp['horse_distances']).get_indexer(q.hd_key);mask=dc>=0;dx=sparse.csr_matrix((np.ones(mask.sum()),(np.arange(n)[mask],dc[mask])),shape=(n,len(sp['horse_distances'])))
 blocks=[cx,bx,dx];pen=[np.ones(ns*k),np.ones(len(sp['horses'])),np.full(len(sp['horse_distances']),20.)]
 if sp['kind']!='none':
  sx=sparse.csr_matrix((np.ones(n),(np.arange(n),sc*4+q.role4.to_numpy())),shape=(n,ns*4));blocks.append(sx);pen.append(np.ones(ns*4))
 if sp['kind']=='personal':
  z=pd.Index(sp['horse_styles']).get_indexer(q.hs_key);mask=z>=0;zx=sparse.csr_matrix((np.ones(mask.sum()),(np.arange(n)[mask],z[mask])),shape=(n,len(sp['horse_styles'])))
  w=sparse.csr_matrix((sp['hs_weights'],(sp['hs_owner'],np.arange(len(sp['horse_styles'])))),shape=(len(sp['horses']),len(sp['horse_styles'])))
  blocks.append(zx-bx.multiply(mask[:,None])@w);pen.append(np.full(len(sp['horse_styles']),sp['lambda_style']))
 x=sparse.hstack(blocks,format='csr');x.eliminate_zeros();return x,np.concatenate(pen)
def fit(q,kind,lam,name):
 q=q.reset_index(drop=True);sp=spec(q,kind,lam);x,pen=matrix(q,sp);rc=pd.factorize(q.source_key)[0];y=center(q.y.to_numpy(),rc);rhs=x.T@y;p=x.shape[1]
 op=LinearOperator((p,p),matvec=lambda b:x.T@center(x@b,rc)+pen*b,dtype=float);diag=np.asarray(x.power(2).sum(axis=0)).ravel()+pen;pre=LinearOperator((p,p),matvec=lambda b:b/diag,dtype=float);it=[0]
 def cb(_):it[0]+=1
 beta,info=cg(op,rhs,M=pre,rtol=2e-9,atol=1e-9,maxiter=3000,callback=cb);grad=float(np.max(abs(op@beta-rhs)));assert info==0 and grad<2e-4,(name,info,grad)
 sp.update(columns=p,iterations=it[0],gradient_max=grad);dump(M/(name+'.json'),sp);np.savez_compressed(M/(name+'.npz'),beta=beta,penalty=pen)
 FITLOG.append(dict(name=name,train_n=len(q),columns=p,iterations=it[0],gradient_max=grad,train_end=sp['train_end']));print('fit',name,len(q),p,it[0],flush=True);return sp,beta
def predict(q,obj):
 sp,b=obj;x,_=matrix(q,sp);rc=pd.factorize(q.source_key)[0];return center(x@b,rc),center(q.y.to_numpy(),rc)
def effects(q,obj):
 sp,b=obj;nc=len(sp['strata'])*len(FORM)*2;nh=len(sp['horses']);nd=len(sp['horse_distances']);globalb=b[nc+nh+nd:nc+nh+nd+len(sp['strata'])*4].reshape(-1,4);theta=b[-len(sp['horse_styles']):];mu=np.bincount(sp['hs_owner'],weights=np.asarray(sp['hs_weights'])*theta,minlength=nh)
 personal=dict(zip(sp['horse_styles'],theta-mu[sp['hs_owner']]));rows=[];horse_counts=q.horse_id.value_counts()
 for (horse,dist),g in q.groupby(['horse_id','distance_m']):
  counts=g.role4.value_counts();eligible=counts[counts.ge(3)].index.tolist();supported=len(g)>=10 and len(eligible)>=2 and int(horse_counts[horse])>=15
  # Global effects averaged over the horse's observed venues at this exact distance.
  mix=g.stratum.value_counts(normalize=True);total={}
  for role,n in counts.items():
   glob=sum(float(w)*globalb[sp['strata'].index(s),int(role)] for s,w in mix.items());dev=personal[horse+':'+str(role)];total[int(role)]=glob+dev
   rows.append(dict(horse_id=horse,distance_m=int(dist),role4=int(role),style=LABELS[int(role)],n=int(n),horse_distance_n=len(g),comparison_supported=supported,global_effect=float(glob),personal_effect=float(dev),total_effect=float(glob+dev),first_date=str(g.date.min().date()),last_date=str(g.date.max().date())))
  if supported:
   ordered=sorted(eligible,key=lambda z:(-total[z],z));best=ordered[0];runner=ordered[1];gap=total[best]-total[runner]
   for row in rows[-len(counts):]:row.update(candidate_style=int(best),runner_style=int(runner),candidate_gap=float(gap),is_candidate=row['role4']==best)
 r=pd.DataFrame(rows);return r
def conditional_evaluation(d):
 pred=[]
 for year in [2024,2025]:
  train=d[d.year.lt(year)].copy();test=d[d.year.eq(year)].copy().reset_index(drop=True)
  base=fit(train,'global',None,str(year)+'_global');personal=fit(train,'personal',30.,str(year)+'_personal');b,y=predict(test,base);p,yy=predict(test,personal);np.testing.assert_allclose(y,yy)
  r=test[['row_key','source_key','horse_id','date','year','meet','distance_m','role4','hd_key']].copy();r['actual']=y;r['global_model']=b;r['personal_model']=p;r['global_abs_error']=abs(y-b);r['personal_abs_error']=abs(y-p);r['difference']=r.personal_abs_error-r.global_abs_error
  hc=train.horse_id.value_counts();support=train.groupby(['hd_key','role4']).size().ge(3).groupby('hd_key').sum();r['supported']=r.horse_id.map(hc).fillna(0).ge(15)&r.hd_key.map(support).fillna(0).ge(2)
  ep=effects(train,personal);cand=ep[ep.comparison_supported].drop_duplicates(['horse_id','distance_m']).set_index(['horse_id','distance_m']).candidate_style.to_dict();r['prior_candidate']=[cand.get((h,int(v)),np.nan) for h,v in zip(r.horse_id,r.distance_m)];r['candidate_match']=r.role4.eq(r.prior_candidate);pred.append(r)
 allp=pd.concat(pred,ignore_index=True);allp.to_parquet(O/'conditional_evaluation.parquet',index=False);metrics=[]
 for window in ['2024','2025','2024_2025']:
  qq=allp if window=='2024_2025' else allp[allp.year.eq(int(window))]
  for scope in ['all','supported']:
   g=qq[qq.supported] if scope=='supported' else qq
   metrics.append(dict(window=window,scope=scope,global_mae=g.global_abs_error.mean(),personal_mae=g.personal_abs_error.mean())|interval(g,g.difference))
 pd.DataFrame(metrics).to_csv(O/'conditional_evaluation_metrics.csv',index=False)
 # Candidate selection is past-only. Realized style is an outcome-side conditioning variable.
 repl=[];repl_rows=[]
 for year,g in allp.groupby('year'):
  g=g[g.prior_candidate.notna()].copy();g['adjusted']=g.actual-g.global_model;ns=g.groupby(['hd_key','candidate_match']).size().unstack(fill_value=0)
  if True not in ns or False not in ns:continue
  valid=ns[(ns[True]>=2)&(ns[False]>=2)].index;z=g[g.hd_key.isin(valid)].copy()
  if not len(z):continue
  k=z.hd_key.nunique();num=z.groupby(['hd_key','candidate_match']).row_key.transform('size');z['contrast_weight']=np.where(z.candidate_match,1.,-1.)/num/k
  est=float(z.contrast_weight@z.adjusted);means=z.groupby('candidate_match').apply(lambda a:np.average(a.adjusted,weights=abs(a.contrast_weight)),include_groups=False).to_dict();v=z.adjusted-np.where(z.candidate_match,means[True],means[False]);s=z.contrast_weight*v;vs=[];ng=[]
  for ids in [z.horse_id,z.date.dt.strftime('%Y-%m-%d'),z.horse_id+':'+z.date.dt.strftime('%Y-%m-%d')]:
   c=pd.factorize(ids)[0];n=c.max()+1;sc=np.bincount(c,weights=s);vs.append(float(sc@sc)*n/(n-1));ng.append(n)
  se=math.sqrt(max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2]));crit=t.ppf(.975,min(ng[:2])-1);repl.append(dict(year=int(year),horse_distances=k,horses=z.horse_id.nunique(),n=len(z),estimate=est,se=se,lower=est-crit*se,upper=est+crit*se));repl_rows.append(z)
 pd.DataFrame(repl).to_csv(O/'candidate_replication.csv',index=False)
 pd.concat(repl_rows,ignore_index=True).to_parquet(O/'candidate_replication_rows.parquet',index=False)
def window(g,n,cut):
 z=g.tail(n);valid=len(z)==n and z.role4.ge(0).all() and (cut-z.date.min()).days<=730;counts=np.bincount(z.loc[z.role4.ge(0),'role4'].to_numpy(),minlength=4);mode=int(counts.argmax()) if valid and counts.max()>=math.ceil(.6*n) else -1
 return z,bool(valid),counts,mode
def permutation_p(v):
 v=np.asarray(v,int);allc=np.bincount(v,minlength=4);observed=np.abs(np.bincount(v[:5],minlength=4)-np.bincount(v[5:],minlength=4)).sum();n=0
 for inds in combinations(range(10),5):
  c=np.bincount(v[list(inds)],minlength=4);n+=np.abs(2*c-allc).sum()>=observed
 return n/252
def bh(p):
 p=np.asarray(p,float);ix=np.argsort(p);q=np.minimum.accumulate((p[ix]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1];out=np.empty(len(p));out[ix]=np.minimum(1,q);return out
def profiles(a,d,baseline,personal,sens):
 yhat,y=predict(d,baseline);d=d.copy();d['adjusted_performance']=y-yhat;d['good_adjusted']=False
 for horse,idx in d.groupby('horse_id').groups.items():
  if len(idx)>=10:d.loc[idx,'good_adjusted']=d.loc[idx,'adjusted_performance'].ge(d.loc[idx,'adjusted_performance'].quantile(.8))
 d.to_parquet(O/'performance_observations.parquet',index=False)
 cells=effects(d,personal);alt={str(k):effects(d,v) for k,v in sens.items()}
 for k,x in alt.items():
  lookup=x.set_index(['horse_id','distance_m','role4']).candidate_style.to_dict();cells['candidate_lambda'+k]=[lookup.get((h,dist,role),np.nan) for h,dist,role in zip(cells.horse_id,cells.distance_m,cells.role4)]
 cells['sensitivity_stable']=cells.comparison_supported&cells.candidate_style.eq(cells.candidate_lambda10)&cells.candidate_style.eq(cells.candidate_lambda100)
 perf=d.groupby(['horse_id','distance_m','role4']).agg(top5_n=('rank_raw',lambda x:int(x.le(5).sum())),top5_rate=('rank_raw',lambda x:x.le(5).mean()),good_adjusted_n=('good_adjusted','sum'),mean_adjusted_performance=('adjusted_performance','mean')).reset_index();cells=cells.merge(perf,on=['horse_id','distance_m','role4'],validate='one_to_one');cells.to_csv(O/'horse_distance_style.csv',index=False)
 style=d.groupby(['horse_id','role4']).agg(normal_n=('row_key','size'),top5_n=('rank_raw',lambda x:int(x.le(5).sum())),top5_rate=('rank_raw',lambda x:x.le(5).mean()),good_adjusted_n=('good_adjusted','sum'),mean_adjusted_performance=('adjusted_performance','mean')).reset_index();style['style']=style.role4.map(dict(enumerate(LABELS)));style.to_csv(O/'horse_performance_style.csv',index=False)
 pdx=d.groupby('horse_id');cellgroups={k:g for k,g in cells[cells.comparison_supported].groupby('horse_id')};rows=[];changes=[]
 for horse,g in a.groupby('horse_id',sort=False):
  g=g[g.date.le(CUTOFF)];last=g.iloc[-1];r=dict(horse_id=horse,horse_name=last.horse_name,latest_meet=last.meet,last_date=str(last.date.date()),first_date=str(g.date.min().date()),roster_n=len(g),observed_n=int(g.group_observed.sum()),recent365=bool(last.date>=CUTOFF-pd.Timedelta(days=365)))
  for role in range(4):r['lifetime_'+str(role)]=int(g.role4.eq(role).sum())
  for n in [5,10]:
   z,ok,c,m=window(g,n,CUTOFF);r.update({f'supported{n}':ok,f'mode{n}':LABELS[m] if m>=0 else '혼합' if ok else '자료부족',f'valid{n}':int(z.role4.ge(0).sum()),f'slots{n}':len(z)})
   for role in range(4):r[f'count{n}_{role}']=int(c[role])
  old=g.iloc[:-5];z0,ok0,c0,m0=window(old,5,CUTOFF);z1,ok1,c1,m1=window(g,5,CUTOFF);supported=ok0 and ok1;change=bool(supported and m0>=0 and m1>=0 and m0!=m1)
  r.update(change_supported=supported,old_mode=LABELS[m0] if m0>=0 else '혼합' if ok0 else '자료부족',change_candidate=change,tv_distance=float(abs(c1-c0).sum()/10) if supported else None,relative_position_change=float(z1.group_mean_relative.mean()-z0.group_mean_relative.mean()) if supported else None,old_distance_mean=float(z0.distance_m.mean()) if supported else None,new_distance_mean=float(z1.distance_m.mean()) if supported else None,all10_same_distance=bool(supported and g.tail(10).distance_m.nunique()==1),venue_changed=bool(supported and set(z0.meet)!=set(z1.meet)))
  for role in range(4):r[f'old_count5_{role}']=int(c0[role])
  r['change_p']=permutation_p(g.tail(10).role4) if supported else None
  zz,ok20,cc,mm=window(g,20,CUTOFF);old10,okold10,co,mo=window(g.iloc[:-10],10,CUTOFF);new10,oknew10,cn,mn=window(g,10,CUTOFF);r['supported20']=bool(ok20 and okold10 and oknew10);r['change20_candidate']=bool(r['supported20'] and mo>=0 and mn>=0 and mo!=mn)
  q=pdx.get_group(horse) if horse in pdx.groups else None;r['normal_n']=len(q) if q is not None else 0
  r['top5_n']=int(q.rank_raw.le(5).sum()) if q is not None else 0;r['good_adjusted_n']=int(q.good_adjusted.sum()) if q is not None else 0
  for role in range(4):
   r[f'top5_style_{role}']=int((q.rank_raw.le(5)&q.role4.eq(role)).sum()) if q is not None else 0;r[f'good_style_{role}']=int((q.good_adjusted&q.role4.eq(role)).sum()) if q is not None else 0
  r['performance_comparison_supported']=horse in cellgroups
  if horse in cellgroups:
   supportedcells=cellgroups[horse];ds=supportedcells.drop_duplicates('distance_m').copy();recentcounts=g.tail(10).distance_m.value_counts();ds['recent_n']=ds.distance_m.map(recentcounts).fillna(0);ref=ds.sort_values(['recent_n','horse_distance_n','distance_m'],ascending=[False,False,True]).iloc[0];r.update(reference_distance=int(ref.distance_m),performance_candidate=LABELS[int(ref.candidate_style)],performance_runner=LABELS[int(ref.runner_style)],candidate_gap=float(ref.candidate_gap),sensitivity_stable=bool(ref.sensitivity_stable),supported_distances=len(ds),distance_candidates_disagree=bool(ds.candidate_style.nunique()>1),candidate_status='차이작음' if ref.candidate_gap<.1 else '잠정후보')
  else:r.update(reference_distance=None,performance_candidate='자료부족',performance_runner='',candidate_gap=None,sensitivity_stable=False,supported_distances=0,distance_candidates_disagree=False,candidate_status='자료부족')
  rows.append(r)
 pr=pd.DataFrame(rows);mask=pr.change_p.notna();pr.loc[mask,'change_q']=bh(pr.loc[mask,'change_p']);pr['change_bh05']=pr.change_q.le(.05);pr.to_csv(O/'horse_profiles.csv',index=False);pr[pr.recent365].to_csv(O/'recent_horse_profiles.csv',index=False);pr[pr.change_candidate].to_csv(O/'current_change_candidates.csv',index=False)
 summary=dict(horses=len(pr),recent365=int(pr.recent365.sum()),supported5=int(pr.supported5.sum()),supported10=int(pr.supported10.sum()),change_comparable=int(pr.change_supported.sum()),change_candidates=int(pr.change_candidate.sum()),change_bh05=int(pr.change_bh05.sum()),supported20=int(pr.supported20.sum()),change20_candidates=int(pr.change20_candidate.sum()),performance_supported=int(pr.performance_comparison_supported.sum()),recent_performance_supported=int((pr.recent365&pr.performance_comparison_supported).sum()),candidate_small_gap=int((pr.performance_comparison_supported&pr.candidate_gap.lt(.1)).sum()),sensitivity_stable=int(pr.sensitivity_stable.sum()),distance_disagreement=int(pr.distance_candidates_disagree.sum()),supported_horse_distances=int(cells[cells.comparison_supported].drop_duplicates(['horse_id','distance_m']).shape[0]))
 dump(O/'profile_summary.json',summary);return pr,cells
def change_followup(a):
 events=[];future=[]
 for horse,g in a.groupby('horse_id',sort=False):
  g=g.reset_index(drop=True)
  for i in range(10,len(g)):
   row=g.iloc[i]
   if row.year not in [2024,2025]:continue
   hist=g.iloc[:i];hist=hist[hist.date.le(row.date-pd.Timedelta(days=2))]
   if len(hist)<10:continue
   z=hist.tail(10)
   if not z.role4.ge(0).all() or (row.date-z.date.min()).days>730:continue
   c0=np.bincount(z.role4.iloc[:5],minlength=4);c1=np.bincount(z.role4.iloc[5:],minlength=4);m0=int(c0.argmax());m1=int(c1.argmax())
   if c0.max()<3 or c1.max()<3 or m0==m1:continue
   f=g.iloc[i:i+5];ok=len(f)==5 and f.role4.ge(0).all() and (f.date.max()-row.date).days<=365
   event=dict(horse_id=horse,event_date=str(row.date.date()),event_row_key=row.row_key,old_style=m0,new_style=m1,history_last=str(z.date.max().date()),old_count=int(c0[m0]),new_count=int(c1[m1]),same_distance_history=z.distance_m.nunique()==1,followup_supported=bool(ok),followup_slots=len(f),followup_valid=int(f.role4.ge(0).sum()),new_hits=int(f.role4.eq(m1).sum()) if ok else None,old_hits=int(f.role4.eq(m0).sum()) if ok else None,new_retained3of5=bool(ok and f.role4.eq(m1).sum()>=3));events.append(event)
   if ok:
    for ff in f.itertuples():future.append(dict(horse_id=horse,date=ff.date,row_key=ff.row_key,event_row_key=row.row_key,new_style=m1,old_style=m0,actual_style=ff.role4,new_hit=ff.role4==m1,old_hit=ff.role4==m0,same_distance_history=event['same_distance_history']))
   break
 e=pd.DataFrame(events);z=pd.DataFrame(future);e.to_csv(O/'change_events.csv',index=False);z.to_parquet(O/'change_followup.parquet',index=False);rows=[]
 for scope in ['all','same_distance_history']:
  q=z[z.same_distance_history] if scope!='all' else z;ev=e[e.followup_supported&(e.same_distance_history if scope!='all' else True)];r=dict(scope=scope,events=len(ev),new_rate=q.new_hit.mean(),old_rate=q.old_hit.mean(),retained3of5=ev.new_retained3of5.mean())|interval(q,q.new_hit.astype(float)-q.old_hit.astype(float));rows.append(r)
 pd.DataFrame(rows).to_csv(O/'change_followup_metrics.csv',index=False)
def main():
 assert not (O/'horse_profiles.csv').exists(),'Completed outputs must not be overwritten'
 a,d=prepare();conditional_evaluation(d);baseline=fit(d,'none',None,'final_no_style');glob=fit(d,'global',None,'final_global');personal=fit(d,'personal',30.,'final_personal');sens={10:fit(d,'personal',10.,'final_lambda10'),100:fit(d,'personal',100.,'final_lambda100')};profiles(a,d,baseline,personal,sens);change_followup(a);pd.DataFrame(FITLOG).to_csv(O/'fit_diagnostics.csv',index=False);print((O/'profile_summary.json').read_text(),flush=True)
if __name__=='__main__':main()
