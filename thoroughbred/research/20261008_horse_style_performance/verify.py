"""Independent SQL, scalar histories, coefficient reconstruction and stationarity audit."""
from pathlib import Path
from collections import defaultdict
from itertools import product
from math import comb,sqrt
import hashlib,json
import numpy as np,pandas as pd,duckdb
from scipy.stats import t,false_discovery_control

H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs';M=H/'models';checks=0
def equal(x,y):
 global checks
 assert x==y,(x,y);checks+=1
def close(x,y,atol=1e-9):
 global checks
 np.testing.assert_allclose(x,y,atol=atol,rtol=1e-8,equal_nan=True);checks+=np.size(x)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
a=pd.read_parquet(O/'roster.parquet');d=pd.read_parquet(O/'performance_observations.parquet');pr=pd.read_csv(O/'horse_profiles.csv',dtype={'horse_id':str});cells=pd.read_csv(O/'horse_distance_style.csv',dtype={'horse_id':str});audit=json.loads((O/'source_audit.json').read_text());con=duckdb.connect();con.register('a',a);con.register('d',d);con.register('pr',pr)
equal(len(a),159014);equal(len(d),151065);equal(a.row_key.nunique(),len(a));equal(d.row_key.nunique(),len(d));equal(a.duplicated(['horse_id','date']).sum(),0)
for f in audit['input_files']:equal(sha(ROOT/f['path']),f['sha256'])
equal(set(d.row_key),set(a.loc[a.group_observed&a.performance_retained,'row_key']))
q=con.execute('''select horse_id,count(*) roster_n,sum(cast(role4>=0 as int)) observed_n,
sum(cast(role4=0 as int)) c0,sum(cast(role4=1 as int)) c1,
sum(cast(role4=2 as int)) c2,sum(cast(role4=3 as int)) c3
from a group by horse_id order by horse_id''').df();p=pr.sort_values('horse_id');equal(q.horse_id.tolist(),p.horse_id.tolist());close(q[['roster_n','observed_n','c0','c1','c2','c3']],p[['roster_n','observed_n','lifetime_0','lifetime_1','lifetime_2','lifetime_3']])
recent=con.execute('''with x as (select *,row_number() over(partition by horse_id order by date desc,source_key desc) rn from a)
select horse_id,
count(*) filter(where rn<=5) n5,sum(cast(role4>=0 as int)) filter(where rn<=5) v5,
min(date) filter(where rn<=5) first5,
count(*) filter(where rn<=10) n10,sum(cast(role4>=0 as int)) filter(where rn<=10) v10,
min(date) filter(where rn<=10) first10,
sum(cast(role4=0 as int)) filter(where rn<=5) c50,sum(cast(role4=1 as int)) filter(where rn<=5) c51,
sum(cast(role4=2 as int)) filter(where rn<=5) c52,sum(cast(role4=3 as int)) filter(where rn<=5) c53,
sum(cast(role4=0 as int)) filter(where rn<=10) c100,sum(cast(role4=1 as int)) filter(where rn<=10) c101,
sum(cast(role4=2 as int)) filter(where rn<=10) c102,sum(cast(role4=3 as int)) filter(where rn<=10) c103
from x group by horse_id order by horse_id''').df()
cut=pd.Timestamp('2026-09-20')
for n in [5,10]:
 close(recent[[f'c{n}{j}' for j in range(4)]],p[[f'count{n}_{j}' for j in range(4)]]);valid=recent[f'n{n}'].eq(n)&recent[f'v{n}'].eq(n)&((cut-recent[f'first{n}']).dt.days<=730);equal(valid.tolist(),p[f'supported{n}'].tolist())
labels=['선행','선입','중단','후미'];pv={r.horse_id:r for r in pr.itertuples()};expected_ps=[];changed=0
for horse,g in a.groupby('horse_id',sort=True):
 z=g.sort_values('date').tail(10);r=pv[horse];supported=len(z)==10 and z.role4.ge(0).all() and (cut-z.date.min()).days<=730;equal(supported,r.change_supported)
 if not supported:continue
 old=[int((z.role4.iloc[:5]==j).sum()) for j in range(4)];new=[int((z.role4.iloc[5:]==j).sum()) for j in range(4)];om=int(np.argmax(old));nm=int(np.argmax(new));flag=max(old)>=3 and max(new)>=3 and om!=nm;equal(flag,r.change_candidate);changed+=flag;close(sum(abs(v-w) for v,w in zip(old,new))/10,r.tv_distance)
 for j in range(4):equal(old[j],getattr(r,f'old_count5_{j}'))
 # Multivariate hypergeometric count enumeration, independent of 252-slot enumeration.
 total=np.array(old)+new;observed=sum(abs(v-w) for v,w in zip(old,new));tail=0
 for x in product(*(range(int(n)+1) for n in total)):
  if sum(x)!=5 or sum(abs(2*np.array(x)-total))<observed:continue
  ways=1
  for n,k in zip(total,x):ways*=comb(int(n),int(k))
  tail+=ways
 prob=tail/comb(10,5);close(prob,r.change_p);expected_ps.append((horse,prob))
close(false_discovery_control([x[1] for x in expected_ps]),[pv[x[0]].change_q for x in expected_ps])
def reconstructed(q,name):
 sp=json.loads((M/(name+'.json')).read_text());b=np.load(M/(name+'.npz'))['beta'];pen=np.load(M/(name+'.npz'))['penalty'];n=len(q);k=len(sp['form'])*2;ns=len(sp['strata']);parts=[];pred=np.zeros(n);offset=0
 for si,s in enumerate(sp['strata']):
  idx=np.flatnonzero(q.stratum.eq(s));g=q.iloc[idx];st=sp['statistics'][s];cols=[]
  for j,col in enumerate(sp['form']):
   v=g[col].to_numpy(float);cols.append(np.where(np.isfinite(v),v,st['medians'][j]))
  cols +=[(~np.isfinite(g[col].to_numpy(float))).astype(float) for col in sp['form']];x=(np.column_stack(cols)-st['means'])/st['sds'];pred[idx]+=x@b[si*k:(si+1)*k];parts.append((idx,x,si*k))
 offset=ns*k;hmap=dict(zip(sp['horses'],range(len(sp['horses']))));hc=np.array([hmap.get(h,-1) for h in q.horse_id]);assert (hc>=0).all();nh=len(hmap);pred+=b[offset+hc];hoff=offset;offset+=nh
 dm=dict(zip(sp['horse_distances'],range(len(sp['horse_distances']))));dc=np.array([dm.get(h,-1) for h in q.hd_key]);assert (dc>=0).all();nd=len(dm);pred+=b[offset+dc];doff=offset;offset+=nd
 sc=pd.Index(sp['strata']).get_indexer(q.stratum);sx=sc*4+q.role4.to_numpy();goff=None;zoff=None
 if sp['kind']!='none':goff=offset;pred+=b[offset+sx];offset+=ns*4
 if sp['kind']=='personal':
  zoff=offset;hsmap=dict(zip(sp['horse_styles'],range(len(sp['horse_styles']))));zc=np.array([hsmap[h] for h in q.hs_key]);owner=np.array(sp['hs_owner']);w=np.array(sp['hs_weights']);theta=b[zoff:];mu=np.bincount(owner,weights=w*theta,minlength=nh);pred+=theta[zc]-mu[hc];close(np.bincount(owner,weights=w,minlength=nh),np.ones(nh))
 # Race means reconstructed with groupby, not the analysis bincount projection.
 predc=pd.Series(pred,index=q.index)-pd.Series(pred,index=q.index).groupby(q.source_key).transform('mean');yc=q.y-q.groupby('source_key').y.transform('mean');res=yc.to_numpy()-predc.to_numpy();grad=pen*b
 for idx,x,off in parts:grad[off:off+k]-=np.sum(x*res[idx,None],axis=0)
 hs=np.bincount(hc,weights=res,minlength=nh);grad[hoff:hoff+nh]-=hs;grad[doff:doff+nd]-=np.bincount(dc,weights=res,minlength=nd)
 if goff is not None:grad[goff:goff+ns*4]-=np.bincount(sx,weights=res,minlength=ns*4)
 if zoff is not None:grad[zoff:]-=np.bincount(zc,weights=res,minlength=len(zc) if len(sp['horse_styles'])==0 else len(sp['horse_styles']))-w*hs[owner]
 assert abs(grad).max()<2e-4,(name,abs(grad).max());equal(len(q),sp['train_n']);close(abs(grad).max(),sp['gradient_max'],atol=1e-7)
 return predc.to_numpy(),yc.to_numpy(),sp,b
details=[]
for name in ['final_no_style','final_global','final_personal','final_lambda10','final_lambda100']:
 pred,y,sp,b=reconstructed(d.reset_index(drop=True),name);details.append(dict(name=name,stationarity_verified=True,n=len(d),columns=len(b)))
 if name=='final_no_style':close(y-pred,d.adjusted_performance.to_numpy())
 if name=='final_personal':finalsp,finalb=sp,b
good=con.execute('''with x as (select *,count(*) over(partition by horse_id) nn,quantile_cont(adjusted_performance,.8) over(partition by horse_id) p80 from d)
select row_key,nn>=10 and adjusted_performance>=p80 as good from x order by row_key''').df();dd=d.sort_values('row_key');equal(good.row_key.tolist(),dd.row_key.tolist());equal(good.good.tolist(),dd.good_adjusted.tolist())
# Independently verify every horse-distance support, effect and selected candidate.
hn=d.horse_id.value_counts();nc=len(finalsp['strata'])*len(finalsp['form'])*2;nh=len(finalsp['horses']);nd=len(finalsp['horse_distances']);glob=finalb[nc+nh+nd:nc+nh+nd+len(finalsp['strata'])*4].reshape(-1,4);theta=finalb[-len(finalsp['horse_styles']):];mean=defaultdict(float)
for hs,owner,w,coef in zip(finalsp['horse_styles'],finalsp['hs_owner'],finalsp['hs_weights'],theta):mean[finalsp['horses'][owner]]+=w*coef
thetamap=dict(zip(finalsp['horse_styles'],theta));lookup=cells.set_index(['horse_id','distance_m','role4'])
for (horse,dist),g in d.groupby(['horse_id','distance_m']):
 counts=g.role4.value_counts();ok=len(g)>=10 and (counts>=3).sum()>=2 and hn[horse]>=15;eff={}
 for role,n in counts.items():
  row=lookup.loc[(horse,dist,role)];equal(bool(ok),row.comparison_supported);equal(int(n),row.n);avg=0
  for s,nn in g.stratum.value_counts().items():avg+=nn/len(g)*glob[finalsp['strata'].index(s),role]
  dev=thetamap[horse+':'+str(role)]-mean[horse];close(avg,row.global_effect);close(dev,row.personal_effect);close(avg+dev,row.total_effect);eff[role]=avg+dev
 if ok:
  elig=counts[counts>=3].index;ordered=sorted(elig,key=lambda z:(-eff[z],z));row=lookup.loc[(horse,dist,ordered[0])];equal(float(ordered[0]),row.candidate_style);close(eff[ordered[0]]-eff[ordered[1]],row.candidate_gap)
def independent_ci(q,values):
 v=np.asarray(values,float);est=float(np.mean(v));scores=(v-est)/len(q);vars=[];counts=[]
 for keys in [q.horse_id.tolist(),q.date.dt.strftime('%Y-%m-%d').tolist(),list(zip(q.horse_id,q.date.dt.strftime('%Y-%m-%d')))]:
  agg=defaultdict(float)
  for key,score in zip(keys,scores):agg[key]+=score
  n=len(agg);vars.append(sum(x*x for x in agg.values())*n/(n-1));counts.append(n)
 se=sqrt(max(0,vars[0],vars[1],vars[0]+vars[1]-vars[2]));crit=t.ppf(.975,min(counts[:2])-1);return est,se,est-crit*se,est+crit*se
ep=pd.read_parquet(O/'conditional_evaluation.parquet');mt=pd.read_csv(O/'conditional_evaluation_metrics.csv')
for rr in mt.itertuples():
 q=ep if rr.window=='2024_2025' else ep[ep.year.eq(int(rr.window))];q=q[q.supported] if rr.scope=='supported' else q;equal(len(q),rr.n);close(abs(q.actual-q.global_model).mean(),rr.global_mae);close(abs(q.actual-q.personal_model).mean(),rr.personal_mae);close(independent_ci(q,abs(q.actual-q.personal_model)-abs(q.actual-q.global_model)),[rr.estimate,rr.se,rr.lower,rr.upper])
for year in [2024,2025]:
 q=d[d.year.lt(year)].reset_index(drop=True)
 for kind in ['global','personal']:reconstructed(q,str(year)+'_'+kind);checks+=1
 equal(ep[ep.year.eq(year)].row_key.tolist(),d[d.year.eq(year)].row_key.tolist())
 test=d[d.year.eq(year)].reset_index(drop=True);stored=ep[ep.year.eq(year)].reset_index(drop=True)
 for kind in ['global','personal']:
  sp=json.loads((M/(str(year)+'_'+kind+'.json')).read_text());beta=np.load(M/(str(year)+'_'+kind+'.npz'))['beta'];assert pd.Timestamp(sp['train_end']).year<year
  raw=np.zeros(len(test));k=2*len(sp['form']);ns=len(sp['strata']);off=ns*k
  for s in sp['strata']:
   idx=np.flatnonzero(test.stratum.eq(s));st=sp['statistics'][s];vals=[]
   for j,col in enumerate(sp['form']):
    v=test.iloc[idx][col].to_numpy(float);vals.append(np.where(np.isfinite(v),v,st['medians'][j]))
   vals +=[(~np.isfinite(test.iloc[idx][col].to_numpy(float))).astype(float) for col in sp['form']];x=(np.column_stack(vals)-st['means'])/st['sds'];si=sp['strata'].index(s);raw[idx]+=x@beta[si*k:(si+1)*k]
  hcoef=dict(zip(sp['horses'],beta[off:off+len(sp['horses'])]));off+=len(sp['horses']);dcoef=dict(zip(sp['horse_distances'],beta[off:off+len(sp['horse_distances'])]));off+=len(sp['horse_distances']);raw+=[hcoef.get(h,0)+dcoef.get(hd,0) for h,hd in zip(test.horse_id,test.hd_key)]
  gb=beta[off:off+ns*4].reshape(-1,4);off+=ns*4;raw+=[gb[sp['strata'].index(s),role] for s,role in zip(test.stratum,test.role4)]
  if kind=='personal':
   theta=beta[off:];mu=defaultdict(float)
   for owner,w,coef in zip(sp['hs_owner'],sp['hs_weights'],theta):mu[sp['horses'][owner]]+=w*coef
   dev={hs:coef-mu[hs.rsplit(':',1)[0]] for hs,coef in zip(sp['horse_styles'],theta)};raw+=[dev.get(hs,0) for hs in test.hs_key]
  rc=pd.Series(raw).groupby(test.source_key).transform('mean');close(raw-rc,stored[kind+'_model'])
 # Re-select every frozen candidate using only this fold's training records.
 sp=json.loads((M/(str(year)+'_personal.json')).read_text());b=np.load(M/(str(year)+'_personal.npz'))['beta'];off=2*len(sp['form'])*len(sp['strata'])+len(sp['horses'])+len(sp['horse_distances']);gb=b[off:off+4*len(sp['strata'])].reshape(-1,4);theta=b[off+4*len(sp['strata']):];mu=defaultdict(float)
 for owner,w,coef in zip(sp['hs_owner'],sp['hs_weights'],theta):mu[sp['horses'][owner]]+=w*coef
 dev={hs:coef-mu[hs.rsplit(':',1)[0]] for hs,coef in zip(sp['horse_styles'],theta)};hc=q.horse_id.value_counts();candidates={}
 for hd,g in q.groupby('hd_key'):
  h=g.horse_id.iloc[0];counts=g.role4.value_counts();roles=counts[counts>=3].index
  if len(g)<10 or len(roles)<2 or hc[h]<15:continue
  totals={role:sum(n/len(g)*gb[sp['strata'].index(s),role] for s,n in g.stratum.value_counts().items())+dev[h+':'+str(role)] for role in roles};candidates[hd]=sorted(roles,key=lambda role:(-totals[role],role))[0]
 close([candidates.get(hd,np.nan) for hd in stored.hd_key],stored.prior_candidate)
events=pd.read_csv(O/'change_events.csv',dtype={'horse_id':str});future=pd.read_parquet(O/'change_followup.parquet');ag={h:g.sort_values('date').reset_index(drop=True) for h,g in a.groupby('horse_id')}
for r in events.itertuples():
 g=ag[r.horse_id];i=int(np.flatnonzero(g.row_key.eq(r.event_row_key))[0]);cutoff=pd.Timestamp(r.event_date)-pd.Timedelta(days=2);history=g.iloc[:i];history=history[history.date<=cutoff].tail(10);equal(len(history),10);assert history.role4.ge(0).all();equal(str(history.date.max().date()),r.history_last);c0=history.role4.iloc[:5].value_counts();c1=history.role4.iloc[5:].value_counts();equal(int(c0.idxmax()),r.old_style);equal(int(c1.idxmax()),r.new_style)
 f=g.iloc[i:i+5];ok=len(f)==5 and f.role4.ge(0).all() and (f.date.max()-g.date.iloc[i]).days<=365;equal(bool(ok),r.followup_supported)
 if ok:equal(f.row_key.tolist(),future[future.event_row_key.eq(r.event_row_key)].row_key.tolist());equal(int(f.role4.eq(r.new_style).sum()),int(r.new_hits))
equal(events.horse_id.nunique(),len(events))
# Supplementary pre/post outcomes are checked by a separate roster-rank SQL join.
cp=pd.read_csv(O/'change_performance.csv',dtype={'horse_id':str});con.register('cp',cp)
beforeafter=con.execute('''with x as (select *,row_number() over(partition by horse_id order by date desc,source_key desc) rn from a),
z as (select x.horse_id,case when rn<=5 then 'new' else 'old' end period,d.adjusted_performance,d.rank_raw from x join cp using(horse_id) left join d using(row_key) where rn<=10)
select horse_id,period,count(adjusted_performance) nn,avg(adjusted_performance) adjusted,avg(case when adjusted_performance is not null then cast(rank_raw<=5 as int) end) top5 from z group by horse_id,period''').df()
cpl=cp.set_index('horse_id')
for r in beforeafter.itertuples():
 rec=cpl.loc[r.horse_id];equal(int(r.nn),int(rec[r.period+'_normal_n']));close(r.adjusted,rec[r.period+'_adjusted_mean']);close(r.top5,rec[r.period+'_top5_rate'])
close(cp.loc[cp.performance_comparable,'adjusted_change'],cp.loc[cp.performance_comparable,'new_adjusted_mean']-cp.loc[cp.performance_comparable,'old_adjusted_mean'])
fm=pd.read_csv(O/'change_followup_metrics.csv')
for r in fm.itertuples():
 q=future[future.same_distance_history] if r.scope!='all' else future;close(independent_ci(q,q.new_hit.astype(float)-q.old_hit.astype(float)),[r.estimate,r.se,r.lower,r.upper])
baseline=json.loads((O/'baseline_inventory.json').read_text());shared={'thoroughbred/research/'+f for f in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};preserved=0
for r in baseline['related_existing_files']:
 if r['path'] in shared:continue
 equal(sha(ROOT/r['path']),r['sha256']);equal((ROOT/r['path']).stat().st_size,r['bytes']);preserved+=1
result=dict(passed=True,checks=int(checks),input_hashes=3,prior_files_preserved=preserved,sql_roster_and_windows=True,hypergeometric_permutation_and_bh=True,all_final_and_four_temporal_model_stationarity=True,model_reconstruction=details,all_individual_effects_checked=True,good_outcome_quantiles_checked=True,conditional_cluster_intervals_checked=True,change_event_actual_slots_checked=True,personal_optimal_style_proven=False)
(O/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
