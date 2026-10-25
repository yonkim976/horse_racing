"""Matched-return episodes with the full normal field as background controls."""
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu
from scipy.stats import t
from data import HERE,NUM,HISTORY,IDS,TARGETS,END,period_mask,save
VARIANTS=['primary','rest181','followup180','pair12','pair13','all_distances','with_recent_form']
def bh(p):
 p=np.asarray(p,float);ix=np.argsort(p);r=np.empty(len(p));r[ix]=np.minimum(1,np.minimum.accumulate((p[ix]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1]);return r
def choose_events(events,period,variant):
 mode=variant if variant in ['rest181','followup180'] else 'primary';e=events[events['mode'].eq(mode)&events.mature&period_mask(events,period)]
 mask=e.pair12_same_distance if variant=='pair12' else e.pair13_same_distance if variant=='pair13' else e.complete_selected_triplet if variant=='all_distances' else e.same_distance_triplet
 return e[mask].copy()
def build_sample(a,events,links,period,variant,target_h1=False):
 e=choose_events(events,period,variant);phases=[1,2] if variant=='pair12' else [1,3] if variant=='pair13' else [1,2,3];l=links[links.episode_id.isin(e.episode_id)&links.phase.isin(phases)].copy()
 if target_h1:
  known=set(a[a.H1_time_adv.notna()].api_record_id);ok=l.groupby('episode_id').api_record_id.apply(lambda s:all(i in known for i in s));e=e[e.episode_id.isin(ok[ok].index)];l=l[l.episode_id.isin(e.episode_id)]
 ids=set(l.api_record_id);races=set(a[a.api_record_id.isin(ids)].race_id);mask=np.ones(len(a),bool) if period=='all' else a.year.between(2024,2025) if period=='2024_2025' else a.year.eq(2026)
 g=a[mask|a.race_id.isin(races)].copy()
 if target_h1:g=g[g.H1_time_adv.notna()].copy()
 mapping=l.set_index('api_record_id');g['phase']=g.api_record_id.map(mapping.phase).fillna(0).astype(int);g['episode_id']=g.api_record_id.map(mapping.episode_id);g['anchor_id']=g.api_record_id.map(mapping.anchor_id)
 g['analysis_unit']='H:'+g.horse_distance;tr=g.phase.gt(0)
 g.loc[tr,'analysis_unit']='E:'+g.loc[tr,'episode_id']
 if variant=='all_distances':g.loc[tr,'analysis_unit']=g.loc[tr,'analysis_unit']+':'+g.loc[tr,'race_distance_m'].astype(str)
 if variant!='with_recent_form':
  idx=a.set_index('api_record_id')
  for c in HISTORY:g.loc[tr,c]=g.loc[tr,'anchor_id'].map(idx[c]).to_numpy()
 return g.reset_index(drop=True),e
def project(g):
 r,rv=pd.factorize(g.race_id,sort=True);h,hv=pd.factorize(g.analysis_unit,sort=True);nr,nh=len(rv),len(hv);rows=np.arange(len(g));graph=coo_matrix((np.ones(2*len(g)),(np.r_[r,nr+h],np.r_[nr+h,r])),shape=(nr+nh,nr+nh)).tocsr();components,lab=connected_components(graph,directed=False);anchor=pd.Series(np.arange(nh)).groupby(lab[nr:]).min().to_numpy();keep=np.ones(nh,bool);keep[anchor]=False;mp=np.full(nh,-1);mp[keep]=nr+np.arange(keep.sum());mask=keep[h];Z=coo_matrix((np.ones(len(g)+mask.sum()),(np.r_[rows,rows[mask]],np.r_[r,mp[h[mask]]])),shape=(len(g),nr+nh-components)).tocsc();return Z,splu((Z.T@Z).tocsc()),{'rank':Z.shape[1],'components':components,'units':nh,'races':nr,'unit':'analysis_unit'}
def design(g):
 phases=[p for p in [2,3] if g.phase.eq(p).any()];D=pd.DataFrame({'phase='+str(p):g.phase.eq(p).astype(float) for p in phases},index=g.index);n=g[NUM].copy();med=n.median().fillna(0);missing=n.isna();n=n.fillna(med)
 for c in NUM:
  if missing[c].any():n[c+'_missing']=missing[c].astype(float)
 n=pd.concat([n,pd.get_dummies(g.jockey_id,prefix='jockey',drop_first=True,dtype=float),pd.get_dummies(g.trainer_id,prefix='trainer',drop_first=True,dtype=float)],axis=1);sd=n.std(ddof=0);n=n.loc[:,sd.gt(1e-12)];mu=n.mean();sd=n.std(ddof=0);n=(n-mu)/sd;X=pd.concat([D,n],axis=1);return X,{'columns':X.columns.tolist(),'phases':phases,'num_columns':NUM,'medians':med.to_dict(),'means':mu.to_dict(),'sd':sd.to_dict()}
def cluster(X,res,bread,key,df):
 codes,ids=pd.factorize(key);s=np.zeros((len(ids),X.shape[1]));np.add.at(s,codes,X*res[:,None]);return bread@s.T@s@bread*(len(ids)/(len(ids)-1)*(len(X)-1)/df)
def fit(g,e,period,variant,targets):
 meta={'period':period,'variant':variant,'background_rows':len(g),'episodes':len(e),'return_horses':e.horse_id.nunique(),'anchor_days':e.anchor_date.nunique(),'strict_initial50_support':len(e)>=50,'phase_rows':int(g.phase.gt(0).sum()),'first_anchor':e.anchor_date.min() if len(e) else None,'last_anchor':e.anchor_date.max() if len(e) else None}
 if len(e)<30 or e.horse_id.nunique()<30 or e.anchor_date.nunique()<20:return [],[],{**meta,'status':'insufficient_episode_support'}
 frame,spec=design(g);X=frame.to_numpy();Y=g[targets].to_numpy();assert np.isfinite(Y).all();Z,lu,info=project(g);V=np.column_stack([Y,X]);R=V-Z@lu.solve(np.asarray(Z.T@V));yr=R[:,:len(targets)];xr=R[:,len(targets):];K=len(spec['phases']);D=xr[:,:K];N=xr[:,K:];resD=D-N@np.linalg.lstsq(N,D,rcond=1e-10)[0];rank=int(np.linalg.matrix_rank(resD,tol=1e-7));df=len(g)-info['rank']-np.linalg.matrix_rank(xr,tol=1e-7)
 if rank<K or df<=20:return [],[],{**meta,'status':'unidentified_or_insufficient_df','rank':rank,'df':int(df)}
 pen=np.r_[np.zeros(K),np.ones(X.shape[1]-K)];bread=np.linalg.inv(xr.T@xr+np.diag(pen));beta=bread@xr.T@yr;crit=float(t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1));deg=min(g.race_date.nunique(),g.horse_id.nunique())-1;rows=[];aux=[];models=[]
 for k,target in enumerate(targets):
  res=yr[:,k]-xr@beta[:,k];dc=cluster(xr,res,bread,g.race_date,df);hc=cluster(xr,res,bread,g.horse_id,df);sign=-1 if target=='relative_time' else 1
  for i,phase in enumerate(spec['phases']):
   point=float(sign*beta[i,k]);sd=np.sqrt(max(0,dc[i,i]));sh=np.sqrt(max(0,hc[i,i]));rows.append({**meta,'target':target,'comparison':str(phase)+'_minus_1','effect':point,'date_low':point-crit*sd,'date_high':point+crit*sd,'horse_low':point-crit*sh,'horse_high':point+crit*sh,'date_p':float(2*t.sf(abs(point/sd),deg)) if sd else 1.,'units':'seconds_faster' if target in ['relative_time','H1_time_adv'] else '10runner_places_better' if target=='rank10_quality' else 'percentage_points','first_result_date':g.loc[g.phase.gt(0),'race_date'].min(),'last_result_date':g.loc[g.phase.gt(0),'race_date'].max(),'residual_df':int(df)})
  if spec['phases']==[2,3]:
   vec=np.zeros(X.shape[1]);vec[0]=-sign;vec[1]=sign;point=float(vec@beta[:,k]);sd=np.sqrt(max(0,vec@dc@vec));sh=np.sqrt(max(0,vec@hc@vec));aux.append({**meta,'target':target,'comparison':'3_minus_2','effect':point,'date_low':point-crit*sd,'date_high':point+crit*sd,'horse_low':point-crit*sh,'horse_high':point+crit*sh})
  models.append({'target':target,'beta':beta[:,k].tolist(),'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'crit':crit})
 print('Layoff fitted',period,variant,len(e),'episodes',len(g),'background rows',flush=True)
 return rows,aux,{**meta,'status':'fitted','row_ids':g.api_record_id.astype(int).tolist(),'episode_ids':e.episode_id.tolist(),'spec':spec,'FE':info,'residual_df':int(df),'projection_orthogonality':float(np.abs(Z.T@R).max()),'models':models}
def main():
 out=HERE/'analysis01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);e=pd.read_csv(HERE/'input01/episodes.csv',dtype={'horse_id':str});l=pd.read_csv(HERE/'input01/phase_lineage.csv',dtype={'horse_id':str});rows=[];aux=[];models=[]
 for period in ['all','2024_2025','2026']:
  for variant in VARIANTS:
   g,z=build_sample(a,e,l,period,variant);r,s,m=fit(g,z,period,variant,TARGETS);rows+=r;aux+=s;models.append(m)
  if period!='all':
   g,z=build_sample(a,e,l,period,'primary',True);r,s,m=fit(g,z,period,'H1_residual',['H1_time_adv']);rows+=r;aux+=s;models.append(m)
 r=pd.DataFrame(rows);r['BH_q']=np.nan
 for variant in ['primary','H1_residual']:
  mask=r.variant.eq(variant);r.loc[mask,'BH_q']=bh(r.loc[mask,'date_p'])
 r['direction_supported']=r.variant.isin(['primary','H1_residual'])&r.BH_q.lt(.05)&((r.date_low.gt(0)&r.horse_low.gt(0))|(r.date_high.lt(0)&r.horse_high.lt(0)));r.to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');pd.DataFrame(aux).to_csv(out/'third_minus_second.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models)
 repeat=[]
 for (variant,target,comp),z in r[r.variant.isin(['primary','H1_residual'])&r.period.ne('all')].groupby(['variant','target','comparison']):repeat.append({'variant':variant,'target':target,'comparison':comp,'periods':len(z),'same_direction':len(z)==2 and bool(z.effect.gt(0).all() or z.effect.lt(0).all()),'repeated_supported':len(z)==2 and bool(z.direction_supported.all()) and bool(z.effect.gt(0).all() or z.effect.lt(0).all())})
 pd.DataFrame(repeat).to_csv(out/'repeat_checks.csv',index=False,encoding='utf-8-sig');print(r[r.variant.isin(['primary','H1_residual'])][['period','variant','target','comparison','episodes','effect','date_low','date_high','horse_low','horse_high','BH_q','direction_supported']].to_string(index=False),flush=True)
if __name__=='__main__':main()
