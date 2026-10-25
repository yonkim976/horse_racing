"""Past-only style rates and within-race ability-adjusted Top3 associations."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
from scipy.linalg import qr
from scipy.stats import t
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OLD=ROOT/'jeju/research/20261009_style_leader_density_v1'
SOURCE=OLD/'features01/start_features.csv';STYLES=['lead','front','closing'];CONFIGS=['any','same','any40']
COLS=['gate_scaled','carried_weight_kg','h_any_finish_rank_mean','h_any_relative_time_mean','h_same_finish_rank_mean','h_same_relative_time_mean','h_any_s1ftime_mean','h_any_g3ftime_mean','h_any_g1ftime_mean','h_any_n','h_same_n','h_any_gap_days']
PAIRS=[('front','lead'),('closing','lead'),('closing','front')]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def clean(frame):return frame.astype(object).where(pd.notna(frame),None).to_dict('records')
def load():return pd.read_csv(SOURCE,dtype={'horse_id':str},low_memory=False)
def periods(a):return {'all':a,'2024_2025':a[a.year.between(2024,2025)],'2026':a[a.year.eq(2026)]}
def bh(p):
 p=np.array(p,float);ix=np.argsort(p);q=np.empty(len(p));q[ix]=np.minimum(1,np.minimum.accumulate((p[ix]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1]);return q
def interval(g):
 if not len(g):return {'rate_pp':None,'date_low':None,'date_high':None,'horse_low':None,'horse_high':None}
 y=100*g.top3.astype(float);point=y.mean();d={'rate_pp':point}
 for label,key in [('date','race_date'),('horse','horse_id')]:
  score=(y-point).groupby(g[key]).sum();G=len(score);half=t.ppf(.975,G-1)*np.sqrt(float(score@score)/len(g)**2*G/(G-1)) if G>1 else np.nan
  d.update({label+'_low':point-half,label+'_high':point+half})
 return d
def raw(g,style,base):
 return {**base,'style':style,'starts':len(g),'top3':int(g.top3.sum()),'horses':g.horse_id.nunique(),'races':g.race_id.nunique(),'days':g.race_date.nunique(),'first_date':g.race_date.min() if len(g) else None,'last_date':g.race_date.max() if len(g) else None,'low_support':len(g)<100 or g.race_id.nunique()<30 or g.race_date.nunique()<20,**interval(g)}
def demean(g,x):return x-x.groupby(g.race_id).transform('mean')
def design(g):
 D=pd.DataFrame({s:g['style'].eq(s).astype(float) for s in ['front','closing']},index=g.index);raw=g[COLS];med=raw.median().fillna(0);N=raw.fillna(med).copy()
 for col in COLS:
  if raw[col].isna().any():N[col+'_missing']=raw[col].isna().astype(float)
 sd=N.std(ddof=0);N=N.loc[:,sd.gt(1e-10)];mu=N.mean();sd=N.std(ddof=0);N=(N-mu)/sd;dr=demean(g,D);nr=demean(g,N)
 if np.linalg.matrix_rank(dr.to_numpy(),tol=1e-9)<2:return None,None
 conditional=nr.to_numpy()-dr.to_numpy()@np.linalg.lstsq(dr.to_numpy(),nr.to_numpy(),rcond=1e-12)[0];_,r,piv=qr(conditional,mode='economic',pivoting=True);rank=int((np.abs(np.diag(r))>1e-9).sum());keep=sorted(piv[:rank]);N=N.iloc[:,keep]
 X=pd.concat([D,N],axis=1)
 return X,{'columns':X.columns.tolist(),'numeric_medians':med.to_dict(),'means':mu.to_dict(),'sd':sd.to_dict(),'nuisance_dropped':[c for c in nr if c not in N]}
def fit(g,config,period):
 g=g[g['style_'+config].isin(STYLES)].copy().reset_index(drop=True);g['style']=g['style_'+config];frame,spec=design(g);meta={'configuration':config,'period':period,'rows':len(g),'races':g.race_id.nunique(),'horses':g.horse_id.nunique(),'dates':g.race_date.nunique()};contrasts=[]
 for pos,ref in PAIRS:
  a=g[g['style'].eq(pos)];b=g[g['style'].eq(ref)];co=set(a.race_id)&set(b.race_id);ok=min(len(a),len(b))>=100 and min(a.horse_id.nunique(),b.horse_id.nunique())>=30 and min(a.race_date.nunique(),b.race_date.nunique())>=20 and len(co)>=30
  contrasts.append({'comparison':pos+'_minus_'+ref,'positive':pos,'reference':ref,'positive_starts':len(a),'reference_starts':len(b),'positive_horses':a.horse_id.nunique(),'reference_horses':b.horse_id.nunique(),'cooccurring_races':len(co),'support':bool(ok)})
 if frame is None:return [],{**meta,'status':'unidentified_style','contrasts':contrasts}
 X=demean(g,frame).to_numpy();y=demean(g,pd.DataFrame({'y':100*g.top3.astype(float)})).y.to_numpy();K=X.shape[1];df=len(g)-g.race_id.nunique()-K;assert df>20 and np.linalg.matrix_rank(X,tol=1e-9)==K
 bread=np.linalg.inv(X.T@X);beta=bread@X.T@y;res=y-X@beta;covs={};critical=float(t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1));out=[]
 for label,key in [('date','race_date'),('horse','horse_id')]:
  codes,ids=pd.factorize(g[key]);scores=np.zeros((len(ids),K));np.add.at(scores,codes,X*res[:,None]);covs[label]=bread@scores.T@scores@bread*(len(ids)/(len(ids)-1)*(len(g)-1)/df)
 for c in contrasts:
  if not c['support']:out.append({**meta,**c,'effect_pp':None,'date_low':None,'date_high':None,'horse_low':None,'horse_high':None,'date_p':1.});continue
  v=np.zeros(K)
  if c['positive']!='lead':v[spec['columns'].index(c['positive'])]+=1
  if c['reference']!='lead':v[spec['columns'].index(c['reference'])]-=1
  effect=float(v@beta);se={k:np.sqrt(max(0,float(v@C@v))) for k,C in covs.items()};r={**meta,**c,'effect_pp':effect,'date_p':float(2*t.sf(abs(effect/se['date']),min(g.race_date.nunique(),g.horse_id.nunique())-1)) if se['date'] else 1.}
  for label in covs:r.update({label+'_low':effect-critical*se[label],label+'_high':effect+critical*se[label]})
  out.append(r)
 model={**meta,'status':'fitted','row_ids':g.api_record_id.astype(int).tolist(),'spec':spec,'contrasts':contrasts,'beta':beta.tolist(),'date_cov':covs['date'].tolist(),'horse_cov':covs['horse'].tolist(),'df':int(df),'critical':critical,'normal_equation_max':float(np.abs(X.T@res).max())}
 print('Style model',config,period,len(g),flush=True);return out,model
def main():
 out=HERE/'run02';out.mkdir(exist_ok=False)
 old_manifest=json.loads((OLD/'artifact_manifest.json').read_text());expected=next(r for r in old_manifest['files'] if r['path']==str(SOURCE.relative_to(ROOT)));assert sha(SOURCE)==expected['sha256'] and SOURCE.stat().st_size==expected['bytes']
 assert json.loads((OLD/'verification01/verification.json').read_text())['status']=='passed'
 sources=[HERE/'PLAN.md',SOURCE,OLD/'artifact_manifest.json',OLD/'verification01/verification.json',OLD/'features.py',OLD/'features01/source_manifest.json']
 manifest={'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],'prior_past_only_verification_reused':True,'source_upper':'2026-09-19','database_opened':False}
 if (HERE/'source_manifest.json').exists():assert json.loads((HERE/'source_manifest.json').read_text())==manifest
 else:save(HERE/'source_manifest.json',manifest)
 a=load();assert len(a)==52155 and a.race_id.nunique()==5206 and a.horse_id.nunique()==2813 and not a.horse_id.eq('3005648').any();assert np.array_equal(a.top3,a.finish_position.le(3))
 rates=[];effects=[];models=[];coverage=[]
 for config in CONFIGS:
  for period,g in periods(a).items():
   coverage.append({'configuration':config,'period':period,'source_starts':len(g),'typed_starts':int(g['style_'+config].isin(STYLES).sum()),'style_counts':g['style_'+config].value_counts().to_dict()})
   for style in ['lead','front','closing','other','unknown']:
    rates.append(raw(g[g['style_'+config].eq(style)],style,{'configuration':config,'period':period,'distance':'all'}))
   for distance in [800,900,1000,1110,1200,1300,1400,1610]:
    z=g[g.race_distance_m.eq(distance)]
    for style in STYLES:rates.append(raw(z[z['style_'+config].eq(style)],style,{'configuration':config,'period':period,'distance':str(distance)}))
   r,m=fit(g,config,period);effects+=r;models.append(m)
 ef=pd.DataFrame(effects);ef['BH_q']=np.nan;mask=ef.configuration.eq('any');assert mask.sum()==9;ef.loc[mask,'BH_q']=bh(ef.loc[mask,'date_p']);ef['direction_supported']=mask&ef.support&ef.BH_q.lt(.05)&((ef.date_low.gt(0)&ef.horse_low.gt(0))|(ef.date_high.lt(0)&ef.horse_high.lt(0)))
 ef.to_csv(out/'adjusted_effects.csv',index=False,encoding='utf-8-sig');pd.DataFrame(rates).to_csv(out/'rates.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models);save(out/'coverage.json',coverage)
 print('Primary rates',flush=True);print(pd.DataFrame(rates).query("configuration=='any' and distance=='all'")[['period','style','starts','top3','rate_pp','date_low','date_high']].to_string(index=False),flush=True)
 print('Primary adjusted',flush=True);print(ef[mask].to_string(index=False),flush=True)
if __name__=='__main__':main()
