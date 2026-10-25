"""Personal training baselines use only earlier completed observed preparations."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OLD=ROOT/'jeju/research/20261017_jockey_training_v1'
LEDGER=ROOT/'jeju/research/20261015_start_interval_v1/input01/ledger_rows.csv';LOWER='2016-12-16';END='2026-09-19';CURRENT=[800,900,1000,1110,1200,1300,1400,1610]
IDS=['horse_id','jockey_id','trainer_id','owner_id'];BASE=['body_kg','carried_weight_kg','gate_scaled','h_any_finish_rank_mean','h_same_finish_rank_mean','h_any_relative_time_mean','h_same_relative_time_mean','h_any_n','h_same_n','previous_rank_fraction','previous_relative_time','log_gap']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def starts():return pd.read_csv(OLD/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False)
def load():return starts(),pd.read_csv(HERE/'input01/features.csv',dtype={'horse_id':str})
def periods(a):return {'all':a,'2024_2025':a[a.year.between(2024,2025)],'2026':a[a.year.eq(2026)]}
def preparation_windows(h,tr):
 h=h[h.observed_started].sort_values(['horse_id','race_date','race_number','api_record_id']).copy();h['previous_date']=h.groupby('horse_id').race_date.shift();byhorse={horse:g.sort_values(['training_date','daily_training_api_row_id']) for horse,g in tr.groupby('horse_id')};rows=[]
 for horse,g in h.groupby('horse_id'):
  z=byhorse[horse];dates=z.training_date.to_numpy(dtype='datetime64[D]');duration=z.duration_seconds.to_numpy(float)
  for r in g.itertuples():
   if r.race_date<'2016-12-18' or r.race_date>END or r.race_distance_m not in CURRENT:continue
   day=np.datetime64(r.race_date,'D');end=day-np.timedelta64(2,'D');prev=np.datetime64(r.previous_date,'D') if pd.notna(r.previous_date) else None
   for w in [7,14,28]:
    start=day-np.timedelta64(w,'D');start=max(start,prev+np.timedelta64(1,'D')) if prev is not None else start;opp=max(0,int((end-start)/np.timedelta64(1,'D'))+1);coverage=str(start)>=LOWER and opp>0;l,u=np.searchsorted(dates,start,'left'),np.searchsorted(dates,end,'right');values=duration[l:u];days=len(np.unique(dates[l:u]));known=coverage and days>0 and np.isfinite(values).all();minutes=float(np.nansum(values)/60) if coverage else np.nan
    rows.append({'api_record_id':r.api_record_id,'horse_id':horse,'race_date':r.race_date,'window_days':w,'previous_date':r.previous_date,'window_start':str(start),'window_end':str(end),'opportunity_days':opp,'source_coverage_complete':coverage,'training_rows':u-l if coverage else np.nan,'training_days':days if coverage else np.nan,'training_minutes':minutes,'duration_missing_rows':int(np.isnan(values).sum()) if coverage else np.nan,'known_preparation':known,'minutes_per_observed_day':minutes/days if known else np.nan,'day_rate':days/opp if known else np.nan,'minute_rate':minutes/opp if known else np.nan})
 return pd.DataFrame(rows)
METRICS=['training_days','training_minutes','minutes_per_observed_day','opportunity_days','day_rate','minute_rate']
def baseline_features(a,h):
 selected=set(a.api_record_id);rows=[];profiles=[];names=a.groupby('horse_id').horse_name.first().to_dict();active=set(a[a.year.eq(2026)].horse_id)
 for (horse,w),g in h.groupby(['horse_id','window_days'],sort=True):
  g=g.sort_values(['race_date','api_record_id']);records=list(g.itertuples());valid=[r for r in records if r.known_preparation];days=np.array([r.race_date for r in valid],dtype='datetime64[D]')
  for r in records:
   if r.api_record_id not in selected:continue
   cutoff=np.datetime64(r.window_end,'D');lo=np.searchsorted(days,cutoff-np.timedelta64(730,'D'),'left');hi=np.searchsorted(days,cutoff,'right');past=valid[lo:hi];past=[v for v in past if v.api_record_id!=r.api_record_id]
   d=r._asdict()
   for size,minimum in [(5,3),(10,5)]:
    use=past[-size:];prefix='usual'+str(size)+'_';d[prefix+'n']=len(use);d[prefix+'ids']=json.dumps([int(v.api_record_id) for v in use]);d[prefix+'supported']=len(use)>=minimum;d[prefix+'first_date']=use[0].race_date if use else None;d[prefix+'last_date']=use[-1].race_date if use else None
    for field in METRICS:d[prefix+field]=float(np.median([getattr(v,field) for v in use])) if len(use)>=minimum else np.nan
   rows.append(d)
  cutoff=np.datetime64(END,'D');eligible=[v for v in valid if cutoff-np.timedelta64(730,'D')<=np.datetime64(v.race_date,'D')<=cutoff];use=eligible[-5:];profile={'horse_id':horse,'horse_name':names[horse],'window_days':int(w),'as_of':END,'observed_in_selected_2026':horse in active,'n':len(use),'supported':len(use)>=3,'history_ids':json.dumps([int(v.api_record_id) for v in use]),'last_completed_race':use[-1].race_date if use else None}
  for field in METRICS:profile[field]=float(np.median([getattr(v,field) for v in use])) if len(use)>=3 else None
  profiles.append(profile)
 return pd.DataFrame(rows),pd.DataFrame(profiles)
def classify(g,size=5,rate=False):
 g=g.copy();p='usual'+str(size)+'_';g['days_departure']=(g.day_rate-g[p+'day_rate'])*(g.window_days-1) if rate else g.training_days-g[p+'training_days'];g['minutes_ratio']=g.minute_rate/g[p+'minute_rate'] if rate else g.training_minutes/g[p+'training_minutes'];g['daily_minutes_ratio']=g.minutes_per_observed_day/g[p+'minutes_per_observed_day'];g['days_group']=np.where(g.days_departure.le(-2),'decreased',np.where(g.days_departure.ge(2),'increased','usual'));g['minutes_group']=np.where(g.minutes_ratio.le(.75),'decreased',np.where(g.minutes_ratio.ge(1.25),'increased','usual'));g['daily_minutes_group']=np.where(g.daily_minutes_ratio.le(.75),'decreased',np.where(g.daily_minutes_ratio.ge(1.25),'increased','usual'))
 return g
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False);a=starts();h=pd.read_csv(LEDGER,dtype={'horse_id':str});assert int(h.observed_started.sum())==65269 and not a.horse_id.eq('3005648').any();tr=pd.read_csv(OLD/'input01/training_rows.csv',dtype={'horse_id':str},low_memory=False);history=preparation_windows(h,tr);history.to_csv(out/'preparation_history.csv',index=False,encoding='utf-8-sig');f,profiles=baseline_features(a,history);assert len(f)==3*len(a) and not f.duplicated(['api_record_id','window_days']).any();f.to_csv(out/'features.csv',index=False,encoding='utf-8-sig');profiles.to_csv(out/'horse_profiles.csv',index=False,encoding='utf-8-sig')
 census=[]
 for period,z in periods(a).items():
  g=f[f.api_record_id.isin(z.api_record_id)&f.window_days.eq(14)];known=g[g.known_preparation&g.usual5_supported];v=classify(known);census.append({'period':period,'starts':len(g),'eligible':len(v),'horses':v.horse_id.nunique(),'current_unobserved':int((~g.known_preparation).sum()),'current_known_insufficient_history':int((g.known_preparation&~g.usual5_supported).sum()),'first_eligible_date':v.race_date.min(),'days_groups':v.days_group.value_counts().to_dict(),'minutes_groups':v.minutes_group.value_counts().to_dict(),'daily_minutes_groups':v.daily_minutes_group.value_counts().to_dict()})
 sources=[OLD/'input01/starts.csv',OLD/'input01/training_rows.csv',OLD/'input01/features.csv',OLD/'verification02/verification.json',LEDGER,ROOT/'jeju/research/20261017_training_dose_recency_v1/verification01/verification.json',OLD/'analysis.py',ROOT/'jeju/research/20261017_jockey_training_individual_v1/verify.py',HERE/'PLAN.md'];save(out/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],'source_starts':len(a),'actual_ledger_starts':65269,'preparation_window_rows':len(history),'preparation_source_lower':LOWER,'data_upper':END,'partial_2026':True,'database_opened':False,'baseline_outcome_independent_actual_start_history':True});save(out/'denominator_census.json',census);print(json.dumps(census,ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
