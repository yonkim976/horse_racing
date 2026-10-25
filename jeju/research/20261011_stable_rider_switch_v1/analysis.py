"""Two stable-specific switch comparisons with pre-performance and rider quality controls."""
import numpy as np
import pandas as pd
from scipy.stats import t
from data import HERE,BASE,DELTA,CAT,ID_COLS,period_data,save
TARGETS=['H1_time_adv','H1_top3_excess']
def bh(p):
 p=np.asarray(p,float);ix=np.argsort(p);q=np.minimum.accumulate((p[ix]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1];r=np.empty(len(p));r[ix]=np.minimum(q,1);return r
def design(g,treatment):
 x=pd.DataFrame({'intercept':1.,'comparison':treatment.astype(float)},index=g.index)
 n=g[BASE].copy();n['log_gap']=np.log1p(g.gap_days);n['distance_changed']=(~g.same_distance).astype(float);n['grade_changed']=g.class_clean.ne(g.previous_class_clean).astype(float)
 for c in DELTA:n['delta_'+c]=g[c]-g['previous_'+c]
 med=n.median().fillna(0);missing=n.isna();n=n.fillna(med)
 for c in med.index:
  if missing[c].any():n[c+'_missing']=missing[c].astype(float)
 sd=n.std(ddof=0);n=n.loc[:,sd.gt(1e-12)];mu=n.mean();sd=n.std(ddof=0);n=(n-mu)/sd
 cat=pd.get_dummies(g[CAT].astype(str),drop_first=True,dtype=float);x=pd.concat([x,n,cat],axis=1)
 return x,{'columns':x.columns.tolist(),'medians':med.to_dict(),'means':mu.to_dict(),'sd':sd.to_dict()}
def cluster(x,res,bread,key,df):
 codes,ids=pd.factorize(key);s=np.zeros((len(ids),x.shape[1]));np.add.at(s,codes,x*res[:,None]);return bread@(s.T@s)@bread*(len(ids)/(len(ids)-1)*(len(x)-1)/df)
def comparison_data(a,cell,comparison):
 trainer=cell.split(':')[0]
 if comparison=='other_switches':
  g=a[a.trainer_id.eq(trainer)&a.changed_jockey].copy();tr=g.cell.eq(cell)
 else:g=a[a.cell.eq(cell)].copy();tr=g.changed_jockey
 return g,tr
def fit(g,tr,period,cell,comparison,variant):
 meta={'period':period,'cell':cell,'comparison':comparison,'variant':variant,'rows':len(g),'treated':int(tr.sum()),'controls':int((~tr).sum())}
 if tr.sum()<20 or (~tr).sum()<(30 if comparison=='other_switches' else 20):return [],{**meta,'status':'insufficient_subset_support'}
 x,spec=design(g,tr);X=x.to_numpy();rank=np.linalg.matrix_rank(X,tol=1e-8);df=len(g)-rank
 if df<=15:return [],{**meta,'status':'insufficient_residual_df','df':int(df)}
 nuisance=X[:,np.arange(X.shape[1])!=1];resid_t=X[:,1]-nuisance@np.linalg.lstsq(nuisance,X[:,1],rcond=1e-10)[0];ident=float(np.linalg.norm(resid_t))
 if ident<1e-6:return [],{**meta,'status':'comparison_unidentified','ident_norm':ident}
 penalty=np.r_[0.,0.,np.ones(X.shape[1]-2)];bread=np.linalg.inv(X.T@X+np.diag(penalty));crit=float(t.ppf(.975,min(g.race_date.nunique(),g.horse_id.nunique())-1));rows=[];models=[]
 for target in TARGETS:
  y=g[target].to_numpy();assert np.isfinite(y).all();beta=bread@X.T@y;res=y-X@beta;dc=cluster(X,res,bread,g.race_date,df);hc=cluster(X,res,bread,g.horse_id,df);sd=float(np.sqrt(max(0,dc[1,1])));sh=float(np.sqrt(max(0,hc[1,1])));point=float(beta[1]);deg=min(g.race_date.nunique(),g.horse_id.nunique())-1
  rows.append({**meta,'target':target,'trainer_name':g.trainer_name.iloc[-1],'jockey_name':g.loc[g.cell.eq(cell),'jockey_display_name'].iloc[-1],'horses':g.horse_id.nunique(),'days':g.race_date.nunique(),'effect':point,'date_low':point-crit*sd,'date_high':point+crit*sd,'horse_low':point-crit*sh,'horse_high':point+crit*sh,'date_p':float(2*t.sf(abs(point/sd),deg)) if sd else 1.,'units':'relative_seconds_faster' if target=='H1_time_adv' else 'percentage_points','residual_df':int(df),'ident_norm':ident})
  models.append({'target':target,'spec':spec,'beta':beta.tolist(),'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'crit':crit,'residual_df':int(df)})
 return rows,{**meta,'status':'fitted','row_ids':g.api_record_id.astype(int).tolist(),'treatment':tr.astype(int).tolist(),'models':models}
def raw_tables(a):
 rows=[]
 for period in ['all','past','2024_2025','2026']:
  for (cell,changed),g in period_data(a,period).groupby(['cell','changed_jockey']):
   rows.append({'period':period,'cell':cell,'trainer_id':g.trainer_id.iloc[0],'trainer_name':g.trainer_name.iloc[-1],'jockey_id':g.jockey_id.iloc[0],'jockey_name':g.jockey_display_name.iloc[-1],'changed':bool(changed),'starts':len(g),'horses':g.horse_id.nunique(),'days':g.race_date.nunique(),'current_top3_count':int(g.top3.sum()),'previous_top3_count':int(g.previous_top3.sum()),'current_top3':g.top3.mean(),'previous_top3':g.previous_top3.mean(),'top3_gain_pp':100*(g.top3.mean()-g.previous_top3.mean()),'current_win':g.win.mean(),'previous_win':g.previous_win.mean(),'rank_improved':g.rank_improved.mean(),'current_rank_quality':g.rank_quality.mean(),'previous_rank_quality':g.previous_rank_quality.mean(),'H1_current_available':int(g.H1_time.notna().sum()),'H1_previous_available':int(g.previous_H1_time.notna().sum()),'H1_current_time_adv':g.H1_time_adv.mean(),'H1_previous_time_adv':g.previous_H1_time_adv.mean(),'H1_time_gain':g.time_gain.mean(),'H1_top3_excess_gain_pp':g.top3_excess_gain.mean(),'upgrades':int(g.upgrade.sum()),'valid_rider_quality_starts':int(g.rider_stats_valid.sum()),'first_date':g.race_date.min(),'last_date':g.race_date.max(),'field_min':g.field_n.min(),'field_max':g.field_n.max()})
 return pd.DataFrame(rows)
def main():
 out=HERE/'analysis01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/pairs.csv',dtype={c:str for c in ID_COLS},low_memory=False);support=pd.read_csv(HERE/'input01/support.csv',dtype={'period':str})
 raw_tables(a).to_csv(out/'raw_all_cells.csv',index=False,encoding='utf-8-sig');rows=[];models=[]
 for period in ['2024_2025','2026']:
  z=period_data(a,period);z=z[z.recent_eligible]
  for cell in support[support.period.eq(period)&support.qualified].cell:
   for variant,v in [('primary',z),('same_distance',z[z.same_distance])]:
    for comp in ['other_switches','same_pair_retained']:
     g,tr=comparison_data(v,cell,comp);rr,mm=fit(g,tr,period,cell,comp,variant);rows+=rr;models.append(mm)
  print('Stable switch fitted',period,len(z),'pairs',flush=True)
 r=pd.DataFrame(rows);r['BH_q']=np.nan;mask=r.variant.eq('primary');r.loc[mask,'BH_q']=bh(r.loc[mask,'date_p']);r['positive_supported']=mask&r.BH_q.lt(.05)&r.date_low.gt(0)&r.horse_low.gt(0);r['negative_supported']=mask&r.BH_q.lt(.05)&r.date_high.lt(0)&r.horse_high.lt(0)
 r.to_csv(out/'effects.csv',index=False,encoding='utf-8-sig');save(out/'models.json',models)
 repeats=[]
 for (cell,target,comp),g in r[mask].groupby(['cell','target','comparison']):
  if len(g)==2:repeats.append({'cell':cell,'target':target,'comparison':comp,'trainer_name':g.trainer_name.iloc[-1],'jockey_name':g.jockey_name.iloc[-1],'repeat_positive':bool(g.positive_supported.all()),'same_positive_point_direction':bool(g.effect.gt(0).all())})
 pd.DataFrame(repeats).to_csv(out/'repeat_checks.csv',index=False,encoding='utf-8-sig');print(r[mask&r.positive_supported].to_string(index=False));print('Primary tests',int(mask.sum()),'repeat positive',sum(v['repeat_positive'] for v in repeats),flush=True)
if __name__=='__main__':main()
