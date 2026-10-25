"""Race and horse-distance fixed effects; cluster uncertainty for trainer contrasts."""
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix,csc_matrix,bmat,diags
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu,spsolve
from scipy.stats import t
from data import HERE,save,FE_NUM
TARGETS=['time','top3','first_pack','late_gain','g3f_rank']
def bh(p):
 p=np.array(p,float);ix=np.argsort(p);q=np.minimum.accumulate((p[ix]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1];r=np.empty(len(p));r[ix]=np.minimum(q,1);return r

def project(g,unit):
 r,rv=pd.factorize(g.race_id,sort=True);h,hv=pd.factorize(g[unit],sort=True);nr,nh=len(rv),len(hv);rows=np.arange(len(g))
 graph=coo_matrix((np.ones(2*len(g)),(np.r_[r,nr+h],np.r_[nr+h,r])),shape=(nr+nh,nr+nh)).tocsr();components,labels=connected_components(graph,directed=False)
 anchors=pd.Series(np.arange(nh)).groupby(labels[nr:]).min().to_numpy();keep=np.ones(nh,bool);keep[anchors]=False;mapping=np.full(nh,-1);mapping[keep]=np.arange(keep.sum())+nr
 mask=keep[h];z=coo_matrix((np.ones(len(g)+mask.sum()),(np.r_[rows,rows[mask]],np.r_[r,mapping[h[mask]]])),shape=(len(g),nr+nh-components)).tocsc()
 lu=splu((z.T@z).tocsc());return z,lu,{'rank':z.shape[1],'components':components,'unit':unit,'units':nh,'races':nr}
def design(g,variant):
 levels=sorted(g.trainer_id.unique());reference=g.trainer_id.value_counts().idxmax();jcols=[j for j in levels if j!=reference]
 J=pd.DataFrame({'trainer='+j:g.trainer_id.eq(j).astype(float) for j in jcols},index=g.index)
 cols=FE_NUM if variant!='no_history' else ['carried_weight_kg','body_kg','gate_scaled']
 n=g[cols].copy();med=n.median();n=n.fillna(med).fillna(0)
 for c in cols:
  if g[c].isna().any():n[c+'_missing']=g[c].isna().astype(float)
 n=pd.concat([n,pd.get_dummies(g.jockey_id,prefix='jockey',drop_first=True,dtype=float)],axis=1)
 sd=n.std(ddof=0);n=n[sd[sd>1e-12].index];mu=n.mean();sd=n.std(ddof=0);n=(n-mu)/sd
 x=pd.concat([J,n],axis=1)
 return x,{'columns':x.columns.tolist(),'trainer_ids':levels,'reference':reference,'trainer_columns':jcols,'n_trainer_columns':len(jcols),
  'nuisance_medians':{k:float(v) for k,v in med.fillna(0).items()},'nuisance_means':mu.to_dict(),'nuisance_sd':sd.to_dict()}
def cluster(x,res,bread,key,df):
 codes,ids=pd.factorize(key);score=np.zeros((len(ids),x.shape[1]));np.add.at(score,codes,x*res[:,None]);return bread@(score.T@score)@bread*(len(ids)/(len(ids)-1)*(len(x)-1)/df)
def fit(g,targets,period,variant):
 x,spec=design(g,variant);X=x.to_numpy();Y=g[targets].to_numpy();z,lu,info=project(g,'horse_id' if variant=='horse_only' else 'horse_distance')
 v=np.column_stack([Y,X]);rv=v-z@lu.solve(np.asarray(z.T@v));yr=rv[:,:len(targets)];xr=rv[:,len(targets):]
 orth=float(np.max(np.abs(z.T@rv)));assert orth<1e-6,orth
 nj=spec['n_trainer_columns'];jj=xr[:,:nj];nn=xr[:,nj:]
 jres=jj-nn@np.linalg.lstsq(nn,jj,rcond=1e-10)[0] if nn.shape[1] else jj
 rank=np.linalg.matrix_rank(jres,tol=1e-7);assert rank==nj,('trainer_unidentified',period,variant,rank,nj)
 df=len(g)-info['rank']-np.linalg.matrix_rank(xr,tol=1e-7);assert df>20
 penalty=np.r_[np.zeros(nj),np.ones(X.shape[1]-nj)];bread=np.linalg.inv(xr.T@xr+np.diag(penalty));beta=bread@xr.T@yr
 direct_error=None
 if period=='all' and variant=='primary' and 'time' in targets:
  xs=csc_matrix(X);system=bmat([[z.T@z,z.T@xs],[xs.T@z,xs.T@xs+diags(penalty)]],format='csc');joint=spsolve(system,np.vstack([z.T@Y,X.T@Y]));direct_error=float(np.max(np.abs(joint[z.shape[1]:]-beta)));assert direct_error<1e-6
 weights=g.trainer_id.value_counts(normalize=True).reindex(spec['trainer_ids']).to_numpy();eye=np.zeros((len(weights),X.shape[1]))
 for i,j in enumerate(spec['trainer_ids']):
  if j!=spec['reference']:eye[i,spec['trainer_columns'].index(j)]=1
 vectors=eye-np.average(eye,axis=0,weights=weights)
 switchunits=set(g.groupby('horse_distance').trainer_id.nunique().loc[lambda v:v.gt(1)].index)
 switchhorses=g[g.horse_distance.isin(switchunits)].groupby('trainer_id').horse_id.nunique()
 support=g.groupby('trainer_id').agg(starts=('api_record_id','size'),horses=('horse_id','nunique'),races=('race_id','nunique'),days=('race_date','nunique'))
 support['switch_horses_hd']=support.index.map(switchhorses).fillna(0).astype(int)
 rows=[];models=[];resids=[];crit=float(t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1))
 for k,target in enumerate(targets):
  res=yr[:,k]-xr@beta[:,k];dc=cluster(xr,res,bread,g.race_date,df);hc=cluster(xr,res,bread,g.horse_id,df)
  alpha=lu.solve(np.asarray(z.T@(Y[:,k]-X@beta[:,k])));fitted=X@beta[:,k]+z@alpha
  assert np.max(np.abs((Y[:,k]-fitted)-res))<1e-7
  sign=-1 if target in ['time','g3f_rank'] else 1;scale=1 if target=='time' else 100
  for i,j in enumerate(spec['trainer_ids']):
   vec=vectors[i]*sign*scale;point=float(vec@beta[:,k]);sd=float(np.sqrt(max(0,vec@dc@vec)));sh=float(np.sqrt(max(0,vec@hc@vec)));sup=support.loc[j]
   rows.append({'period':period,'variant':variant,'target':target,'trainer_id':j,'name':g.loc[g.trainer_id.eq(j),'trainer_display_name'].iloc[0],**{c:int(sup[c]) for c in support.columns},
    'effect':point,'date_low':point-crit*sd,'date_high':point+crit*sd,'horse_low':point-crit*sh,'horse_high':point+crit*sh,
    'date_p':float(2*t.sf(abs(point/sd),min(g.race_date.nunique(),g.horse_id.nunique())-1)) if sd else 1.,
    'support':bool(sup.starts>=(300 if period in ['all','past'] else 100) and sup.days>=20 and sup.horses>=30 and sup.switch_horses_hd>=10),
    'units':'seconds_faster' if target=='time' else 'rank_fraction_pp_faster' if target=='g3f_rank' else 'percentage_points',
    'first_date':g.race_date.min(),'last_date':g.race_date.max(),'field_min':int(g.field_n.min()),'field_max':int(g.field_n.max())})
  models.append({'period':period,'variant':variant,'target':target,'spec':spec,'beta':beta[:,k].tolist(),'alpha':alpha.tolist(),'FE':info,'rank_trainer':int(rank),'trainer_singular_min':float(np.linalg.svd(jres,compute_uv=False)[-1]),'trainer_singular_max':float(np.linalg.svd(jres,compute_uv=False)[0]),'residual_df':int(df),
   'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'weights':weights.tolist(),'crit':crit,'projection_orthogonality':orth,'direct_joint_error':direct_error})
  zz=g[['api_record_id','trainer_id','horse_id','race_id','race_date']].copy();zz['period']=period;zz['variant']=variant;zz['target']=target;zz['outcome']=Y[:,k];zz['fit']=fitted;zz['residual']=res;resids.append(zz)
 print('FE fitted',period,variant,targets,len(g),info['rank'],flush=True)
 return rows,models,resids

def main():
 out=HERE/'effects01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/starts.csv',dtype={'horse_id':str,'trainer_id':str,'trainer_id':str},low_memory=False)
 rows=[];models=[];resids=[]
 for period,g in [('all',a),('2024_2025',a[a.year.isin([2024,2025])]),('2026',a[a.year.eq(2026)]),('past',a[a.year.le(2023)])]:
  targets=TARGETS if period!='past' else ['time'];batches={}
  for target in targets:
   mask=g[target].notna();batches.setdefault(mask.to_numpy().tobytes(),(mask,[]))[1].append(target)
  for mask,tt in batches.values():
   rr,mm,ss=fit(g.loc[mask].copy(),tt,period,'primary');rows+=rr;models+=mm;resids+=ss
  if period!='past':
   for variant in ['horse_only','no_history']:
    rr,mm,ss=fit(g,['time'],period,variant);rows+=rr;models+=mm;resids+=ss
 df=pd.DataFrame(rows)
 for _,g in df.groupby(['period','variant','target']):df.loc[g.index,'BH_q']=bh(g.date_p)
 df['direction_supported']=df.support&df.BH_q.lt(.05)&((df.date_low.gt(0)&df.horse_low.gt(0))|(df.date_high.lt(0)&df.horse_high.lt(0)))
 df.to_csv(out/'trainer_effects.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models);pd.concat(resids,ignore_index=True).to_csv(out/'fitted_and_residuals.csv',index=False,encoding='utf-8-sig')
 print(df[(df.period=='2026')&(df.variant=='primary')&(df.target=='time')].sort_values('effect',ascending=False)[['name','starts','effect','date_low','date_high','horse_low','horse_high','BH_q','direction_supported']].to_string(index=False))
if __name__=='__main__':main()
