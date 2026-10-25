"""Layoff episodes follow all observed actual starts, never skipping unusable races."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OLD=ROOT/'jeju/research/20261015_start_interval_v1'
IDS=['horse_id','jockey_id','trainer_id','owner_id'];END='2026-09-19'
CURRENT=[800,900,1000,1110,1200,1300,1400,1610]
HISTORY=['h_any_finish_rank_mean','h_same_finish_rank_mean','h_any_relative_time_mean','h_same_relative_time_mean','h_any_n','h_same_n','previous_rank_fraction','previous_relative_time']
NUM=['body_kg','carried_weight_kg','gate_scaled']+HISTORY
TARGETS=['relative_time','rank10_quality','top3_pp']
CONFIG={'primary':(91,60,120),'rest181':(181,60,120),'followup180':(91,90,180)}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def period_mask(s,p):return np.ones(len(s),bool) if p=='all' else s.anchor_year.between(2024,2025) if p=='2024_2025' else s.anchor_year.eq(2026)
def build_events(h,a):
 selected=a.set_index('api_record_id');events=[];links=[]
 for mode,(threshold,step,horizon) in CONFIG.items():
  maturity=(pd.Timestamp(END)-pd.Timedelta(days=horizon)).strftime('%Y-%m-%d')
  for horse,g in h.groupby('horse_id',sort=False):
   rows=list(g.itertuples())
   for i,r in enumerate(rows):
    if pd.isna(r.gap_days) or r.gap_days<threshold or r.race_date<'2017-01-01' or r.race_distance_m not in CURRENT:continue
    ep=f'{mode}:{horse}:{int(r.api_record_id)}';ids=[int(r.api_record_id)];dates=[r.race_date];reason='three_observed'
    for phase in [2,3]:
     if i+phase-1>=len(rows):reason='no_next_observed_start';break
     q=rows[i+phase-1];delta=(pd.Timestamp(q.race_date)-pd.Timestamp(dates[-1])).days;total=(pd.Timestamp(q.race_date)-pd.Timestamp(r.race_date)).days
     if delta>=91:reason='new_long_gap';break
     if delta>step:reason='followup_gap_exceeded';break
     if total>horizon:reason='horizon_exceeded';break
     ids.append(int(q.api_record_id));dates.append(q.race_date)
    chosen=[key in selected.index for key in ids];distance=[float(selected.loc[key,'race_distance_m']) for key in ids if key in selected.index];complete=len(ids)==3 and all(chosen);same=complete and len(set(distance))==1
    event={'mode':mode,'episode_id':ep,'horse_id':horse,'anchor_id':int(r.api_record_id),'anchor_date':r.race_date,'anchor_year':int(r.race_date[:4]),'rest_days':float(r.gap_days),'threshold':threshold,'max_step_days':step,'horizon_days':horizon,'maturity_cutoff':maturity,'mature':r.race_date<=maturity,'observed_phases':len(ids),'stop_reason':reason,'first_selected':chosen[0],'second_selected':len(ids)>=2 and chosen[1],'third_selected':len(ids)>=3 and chosen[2],'complete_selected_triplet':complete,'same_distance_triplet':same}
    for phase,key in enumerate(ids,1):
     event['phase'+str(phase)+'_id']=key;event['phase'+str(phase)+'_date']=dates[phase-1];links.append({'mode':mode,'episode_id':ep,'horse_id':horse,'anchor_id':int(r.api_record_id),'anchor_date':r.race_date,'anchor_year':int(r.race_date[:4]),'mature':event['mature'],'rest_days':float(r.gap_days),'phase':phase,'api_record_id':key,'selected_outcome':chosen[phase-1]})
    if len(ids)>=2 and chosen[0] and chosen[1]:event['pair12_same_distance']=float(selected.loc[ids[0],'race_distance_m'])==float(selected.loc[ids[1],'race_distance_m'])
    else:event['pair12_same_distance']=False
    if len(ids)>=3 and chosen[0] and chosen[2]:event['pair13_same_distance']=float(selected.loc[ids[0],'race_distance_m'])==float(selected.loc[ids[2],'race_distance_m'])
    else:event['pair13_same_distance']=False
    events.append(event)
 return pd.DataFrame(events),pd.DataFrame(links)
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False);a=pd.read_csv(OLD/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);h=pd.read_csv(OLD/'input01/ledger_rows.csv',dtype={'horse_id':str});h=h[h.observed_started].sort_values(['horse_id','race_date','race_number','api_record_id']).copy();h['gap_days']=h.groupby('horse_id').race_date.transform(lambda s:pd.to_datetime(s).diff().dt.days)
 assert len(a)==52155 and len(h)==65269 and not a.horse_id.eq('3005648').any();events,links=build_events(h,a);assert not links.duplicated(['mode','api_record_id']).any()
 H1source=ROOT/'jeju/research/20261009_jockey_closing_switch_v1/input01/starts.csv';p=pd.read_csv(H1source,usecols=['api_record_id','H1_time','H1_time_adv'],low_memory=False);a=a.merge(p,on='api_record_id',validate='one_to_one');a.to_csv(out/'starts.csv',index=False,encoding='utf-8-sig');events.to_csv(out/'episodes.csv',index=False,encoding='utf-8-sig');links.to_csv(out/'phase_lineage.csv',index=False,encoding='utf-8-sig')
 sources=[OLD/'input01/starts.csv',OLD/'input01/ledger_rows.csv',OLD/'verification01/verification.json',ROOT/'jeju/research/20261015_personal_start_interval_v1/analysis.py',ROOT/'jeju/research/20261015_personal_start_interval_v1/verify_main.py',H1source,ROOT/'jeju/research/20261009_jockey_effects_v1/forecast01/fit_audit.json',HERE/'PLAN.md']
 save(out/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],'source_starts':len(a),'source_races':a.race_id.nunique(),'source_horses':a.horse_id.nunique(),'actual_ledger_starts':len(h),'configuration':{k:list(v) for k,v in CONFIG.items()},'data_upper':END,'partial_2026':True,'database_opened':False,'gap_is_observed_candidate_ledger_not_complete_lifetime':True,'history_contract':'Inherited T-2 max10/730days; current declaration/body availability assumed','phase_does_not_skip_unselected_actual_starts':True})
 print(events.groupby('mode')[['mature','first_selected','complete_selected_triplet','same_distance_triplet']].sum().to_string(),flush=True)
 for period in ['all','2024_2025','2026']:
  z=events[events['mode'].eq('primary')&events.mature&events.same_distance_triplet&period_mask(events,period)];print('PRIMARY balanced',period,len(z),'horses',z.horse_id.nunique(),flush=True)
if __name__=='__main__':main()
