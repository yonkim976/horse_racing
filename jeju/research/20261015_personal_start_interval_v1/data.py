"""Personal usual intervals from completed past gaps only, without DB access."""
from pathlib import Path
import bisect,hashlib,json
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OLD=ROOT/'jeju/research/20261015_start_interval_v1'
IDS=['horse_id','jockey_id','trainer_id','owner_id']
BINS=['short','usual','long','very_long'];GROUPS=BINS;REF='usual'
ABS_GROUPS=['1_7','8_14','15_28','29_42','43_60','61_90','91_180','181_plus']
BASE=['body_kg','carried_weight_kg','gate_scaled','h_any_finish_rank_mean','h_same_finish_rank_mean','h_any_relative_time_mean','h_same_relative_time_mean','h_any_n','h_same_n','previous_rank_fraction','previous_relative_time']
NUM=BASE+['log_typical','typical_n','typical_mad_ratio']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def period_data(a):return {'all':a,'past':a[a.year.le(2023)],'2024_2025':a[a.year.between(2024,2025)],'2026':a[a.year.eq(2026)]}
def label(r):return 'short' if r<.75 else 'usual' if r<=1.25 else 'long' if r<=2 else 'very_long'
def ledger_intervals():
 h=pd.read_csv(OLD/'input01/ledger_rows.csv',dtype={'horse_id':str});h=h[h.observed_started].sort_values(['horse_id','race_date','race_number','api_record_id']).copy();h['interval_days']=h.groupby('horse_id').race_date.transform(lambda s:pd.to_datetime(s).diff().dt.days);return h
def baseline(history,cutoff,number):
 end=bisect.bisect_right(history['days'],cutoff);lo=bisect.bisect_left(history['days'],cutoff-pd.Timedelta(days=730));ix=list(range(max(lo,end-number),end));values=np.array([history['gaps'][i] for i in ix],float)
 if len(values)<3:return None,ix
 med=float(np.median(values));return {'median':med,'n':len(values),'mad_ratio':float(np.median(np.abs(values-med))/med)},ix
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False);a=pd.read_csv(OLD/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False).rename(columns={'gap_group':'absolute_gap_group','gap_bin':'absolute_gap_bin'})
 h=ledger_intervals();hist={}
 for horse,g in h[h.interval_days.notna()&h.interval_days.gt(0)].groupby('horse_id'):
  hist[horse]={'days':pd.to_datetime(g.race_date).tolist(),'gaps':g.interval_days.tolist(),'ids':g.api_record_id.astype(int).tolist()}
 records=[];windows=[]
 for r in a.itertuples():
  cutoff=pd.Timestamp(r.race_date)-pd.Timedelta(days=2);history=hist.get(r.horse_id,{'days':[],'gaps':[],'ids':[]});row={'api_record_id':int(r.api_record_id),'typical_cutoff':cutoff.strftime('%Y-%m-%d')}
  for number in [5,10]:
   b,ix=baseline(history,cutoff,number);row['typical'+str(number)]=b['median'] if b else None;row['typical'+str(number)+'_n']=len(ix);row['typical'+str(number)+'_mad_ratio']=b['mad_ratio'] if b else None
   row['typical'+str(number)+'_ids']=json.dumps([history['ids'][i] for i in ix])
  for ordinal,i in enumerate(baseline(history,cutoff,10)[1],1):windows.append({'api_record_id':int(r.api_record_id),'horse_id':r.horse_id,'history_end_api_record_id':history['ids'][i],'history_end_date':history['days'][i].strftime('%Y-%m-%d'),'history_interval_days':history['gaps'][i],'ordinal_oldest_to_newest':ordinal})
  records.append(row)
 a=a.merge(pd.DataFrame(records),on='api_record_id',validate='one_to_one');a['typical_n']=a.typical5_n;a['typical_mad_ratio']=a.typical5_mad_ratio;a['log_typical']=np.log1p(a.typical5);a['relative_interval']=a.gap_days/a.typical5;a['relative_interval10']=a.gap_days/a.typical10
 a['gap_group']=a.relative_interval.map(lambda r:label(r) if pd.notna(r) else None);a['gap_bin']=a.gap_group;a['gap_group10']=a.relative_interval10.map(lambda r:label(r) if pd.notna(r) else None);a['gap_deviation_days']=a.gap_days-a.typical5
 a['preference_gap_group']=a.absolute_gap_group.replace({'43_60':'43_90','61_90':'43_90','91_180':'91_plus','181_plus':'91_plus'})
 source=ROOT/'jeju/research/20261009_jockey_closing_switch_v1/input01/starts.csv';H1=pd.read_csv(source,usecols=['api_record_id','H1_time_adv','H1_time','H1_prob'],low_memory=False);a=a.merge(H1,on='api_record_id',validate='one_to_one')
 assert len(a)==52155 and not a.horse_id.eq('3005648').any();a.to_csv(out/'starts.csv',index=False,encoding='utf-8-sig');pd.DataFrame(windows).to_csv(out/'history_lineage.csv',index=False,encoding='utf-8-sig')
 profiles=[]
 for horse,g in a.groupby('horse_id'):
  history=hist.get(horse,{'days':[],'gaps':[],'ids':[]});b,ix=baseline(history,pd.Timestamp('2026-09-19'),5);profiles.append({'horse_id':horse,'horse_name':g.horse_name.iloc[-1],'asof':'2026-09-19','latest_observed_race':g.race_date.max(),'observed_selected_starts':len(g),'usual_interval_days':b['median'] if b else None,'usual_intervals_n':len(ix),'usual_interval_mad_ratio':b['mad_ratio'] if b else None,'usual_interval_end_ids':json.dumps([history['ids'][i] for i in ix]),'status':'supported_baseline' if b else 'insufficient_recent_observed_intervals'})
 pd.DataFrame(profiles).to_csv(out/'horse_usual_profiles.csv',index=False,encoding='utf-8-sig')
 files=[OLD/'input01/starts.csv',OLD/'input01/ledger_rows.csv',OLD/'verification01/verification.json',OLD/'analysis.py',OLD/'verify.py',source,ROOT/'jeju/research/20261009_jockey_effects_v1/forecast01/parameters.json',ROOT/'jeju/research/20261009_jockey_effects_v1/forecast01/fit_audit.json',HERE/'PLAN.md']
 save(out/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'cohort_starts':len(a),'personal_baseline_starts':int(a.gap_group.notna().sum()),'personal_baseline_horses':a[a.gap_group.notna()].horse_id.nunique(),'history_lineage_rows':len(windows),'period_end':'2026-09-19','partial_2026':True,'database_opened':False,'current_gap_excluded_from_usual_baseline':True,'baseline_contract':'Completed intervals ending <=T-2, ending within730days, last5(min3); last10 sensitivity','past_performance_contract':'Inherited T-2 maximum10/730days; current declaration availability assumed'})
 print('Personal baseline eligible',a.gap_group.notna().sum(),a[a.gap_group.notna()].groupby('year').size().to_dict(),flush=True)
if __name__=='__main__':main()
