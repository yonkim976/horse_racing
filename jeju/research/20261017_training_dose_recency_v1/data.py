"""Extend frozen pre-race training windows with own duration and last participation."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OLD=ROOT/'jeju/research/20261017_jockey_training_v1'
BASE=['body_kg','carried_weight_kg','gate_scaled','h_any_finish_rank_mean','h_same_finish_rank_mean','h_any_relative_time_mean','h_same_relative_time_mean','h_any_n','h_same_n','previous_rank_fraction','previous_relative_time','log_gap']
IDS=['horse_id','jockey_id','trainer_id','owner_id'];WINDOWS=[7,14,28]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def starts():return pd.read_csv(OLD/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False)
def load():return starts(),pd.read_csv(HERE/'input01/features.csv')
def periods(a):return {'all':a,'2024_2025':a[a.year.between(2024,2025)],'2026':a[a.year.eq(2026)]}
def groups(g):
 g=g.copy();g['own_days_group']=np.select([g.same_jockey_days.eq(0),g.same_jockey_days.eq(1),g.same_jockey_days.between(2,3)],['0','1','2_3'],default='4plus');g['own_recency_group']=np.select([g.own_lag_days.between(2,3),g.own_lag_days.between(4,7),g.own_lag_days.ge(8)],['2_3','4_7','8plus'],default='none');g['own_time_group']=np.where(g.same_jockey_days.eq(0),'none',np.where(g.own_minutes.le(30),'le30',np.where(g.own_minutes.le(60),'30_60','gt60')))
 g['count_group']=np.where(g.training_rows.le(4),'1_4',np.where(g.training_rows.le(8),'5_8','9plus'));g['days_group']=np.where(g.training_days.le(4),'1_4',np.where(g.training_days.le(8),'5_8','9plus'));g['time_group']=np.where(g.training_minutes.le(60),'le60',np.where(g.training_minutes.le(120),'60_120','gt120'))
 return g
def extend(a,tr):
 byhorse={h:g.sort_values(['training_date','daily_training_api_row_id']) for h,g in tr.groupby('horse_id')};rows=[]
 for h,g in a.groupby('horse_id'):
  z=byhorse[h];dates=z.training_date.to_numpy(dtype='datetime64[D]');isj=z.rider_type.eq('기수').to_numpy();ids=z.prNo_raw.fillna('').to_numpy();duration=z.duration_seconds.to_numpy(float)
  for r in g.itertuples():
   race=np.datetime64(r.race_date,'D');end=np.datetime64(r.history_cutoff,'D');prev=np.datetime64(r.previous_race_date,'D') if pd.notna(r.previous_race_date) else None
   for w in WINDOWS:
    lo=race-np.timedelta64(w,'D');lo=max(lo,prev+np.timedelta64(1,'D')) if prev is not None else lo;l,u=np.searchsorted(dates,lo,'left'),np.searchsorted(dates,end,'right');own=isj[l:u]&(ids[l:u]==r.jockey_id);dd=dates[l:u][own];dur=duration[l:u][own];last=dd.max() if len(dd) else None
    rows.append({'api_record_id':r.api_record_id,'window_days':w,'own_minutes':float(np.nansum(dur)/60),'own_duration_missing_rows':int(np.isnan(dur).sum()),'own_last_date':str(last) if last is not None else None,'own_lag_days':int((race-last)/np.timedelta64(1,'D')) if last is not None else None,'own_days_recomputed':len(np.unique(dd))})
 return pd.DataFrame(rows)
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False);a=starts();tr=pd.read_csv(OLD/'input01/training_rows.csv',dtype={'horse_id':str,'prNo_raw':str},low_memory=False);f=pd.read_csv(OLD/'input01/features.csv');extra=extend(a,tr);f=f.merge(extra,on=['api_record_id','window_days'],validate='one_to_one');assert np.array_equal(f.same_jockey_days,f.own_days_recomputed);f=groups(f);f.to_csv(out/'features.csv',index=False,encoding='utf-8-sig')
 census=[]
 for period,z in periods(a).items():
  g=f[f.api_record_id.isin(z.api_record_id)&f.window_days.eq(14)]
  for label,mask,col in [('own_days',g.identity_complete,'own_days_group'),('recency',g.identity_complete&g.same_jockey,'own_recency_group'),('own_time',g.identity_complete&g.same_jockey&g.own_duration_missing_rows.eq(0),'own_time_group'),('total_count',g.training_rows.gt(0)&g.duration_missing_rows.eq(0),'count_group'),('total_time',g.training_rows.gt(0)&g.duration_missing_rows.eq(0),'time_group')]:
   for value,n in g[mask][col].value_counts().items():census.append({'period':period,'family':label,'group':value,'starts':int(n)})
 save(out/'denominator_census.json',census)
 sources=[OLD/'input01/starts.csv',OLD/'input01/training_rows.csv',OLD/'input01/features.csv',OLD/'input01/lineage.csv',OLD/'verification02/verification.json',OLD/'verification02/current_source_context.json',OLD/'analysis.py',ROOT/'jeju/research/20261017_jockey_training_individual_v1/input01/jockey_names.csv',HERE/'PLAN.md']
 save(out/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],'source_starts':len(a),'feature_rows':len(f),'training_rows':len(tr),'data_upper':'2026-09-19','partial_2026':True,'database_opened':False,'actual_training_count_fields_unavailable':True,'rows_are_not_proven_session_counts':True});print(pd.DataFrame(census).to_string(index=False),flush=True)
if __name__=='__main__':main()
