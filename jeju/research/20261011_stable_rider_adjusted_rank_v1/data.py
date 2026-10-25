"""Read immutable historical pairs and explicitly join pre-race field proxies."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
PAIR=ROOT/'jeju/research/20261011_stable_rider_switch_v1/input01/pairs.csv'
SOURCE=ROOT/'jeju/research/20261009_jockey_closing_switch_v1/input01/starts.csv'
PRED=ROOT/'jeju/research/20261009_jockey_effects_v1/forecast01/predictions.csv'
ID_COLS=['horse_id','trainer_id','jockey_id','owner_id','previous_jockey_id','previous_trainer_id','previous_owner_id']
EXTRA=['opp_rank_mean','opp_time_mean','h_same_finish_rank_mean','h_same_relative_time_mean','h_same_n','h_any_finish_rank_last','h_same_finish_rank_last']
BASE=['H1_prob','H1_time','previous_H1_prob','previous_H1_time','previous_H1_time_adv','previous_H1_top3_excess','previous_top3','previous_relative_time','previous_finish_position','previous_rank_quality','previous_field_n','predicted_rank','previous_predicted_rank','predicted_rank10','previous_predicted_rank10','h_any_finish_rank_mean','h_any_relative_time_mean','h_any_n','current_rider_rate','previous_rider_rate','rider_rate_gain','body_kg','carried_weight_kg','moisture','gate_scaled','field_n']+EXTRA+['previous_'+c for c in EXTRA]
DELTA=['body_kg','carried_weight_kg','moisture','gate_scaled','h_any_relative_time_mean','h_any_finish_rank_mean','opp_rank_mean','opp_time_mean']
CAT=['year','month','race_distance_m','class_clean']
TARGETS=['normalized10_gain','raw_rank_gain']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False)
 a=pd.read_csv(PAIR,dtype={c:str for c in ID_COLS},low_memory=False)
 s=pd.read_csv(SOURCE,usecols=['api_record_id','race_id','H1_time','field_n','finish_position']+EXTRA,low_memory=False)
 assert len(a)==43024 and len(s)==52155 and not s.api_record_id.duplicated().any()
 s['predicted_rank']=s.groupby('race_id').H1_time.rank(method='average',ascending=True)
 s['predicted_rank10']=1+9*(s.predicted_rank-1)/(s.field_n-1)
 idx=s.set_index('api_record_id')
 for prefix,key in [('', 'api_record_id'),('previous_','previous_api_record_id')]:
  for c in EXTRA+['predicted_rank','predicted_rank10']:a[prefix+c]=a[key].map(idx[c])
  for c in ['field_n','finish_position']:assert np.array_equal(a[prefix+c],a[key].map(idx[c]))
 a=a[a.year.ge(2024)&a.recent_eligible].copy()
 assert a.predicted_rank.notna().all() and a.previous_predicted_rank.notna().all()
 a['normalized10_gain']=9*(a.rank_quality-a.previous_rank_quality)
 a['raw_rank_gain']=a.previous_finish_position-a.finish_position
 assert not a.horse_id.eq('3005648').any() and a.race_date.max()=='2026-09-19'
 a.to_csv(out/'pairs.csv',index=False,encoding='utf-8-sig')
 files=[PAIR,SOURCE,PRED,HERE/'PLAN.md',ROOT/'jeju/research/20261009_jockey_effects_v1/forecast01/parameters.json',ROOT/'jeju/research/20261009_jockey_effects_v1/forecast01/fit_audit.json',ROOT/'jeju/research/20261011_stable_rider_switch_v1/verification02/verification.json',ROOT/'jeju/data/horse_exclusions.json']
 save(out/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'eligible_pairs':len(a),'pairs_by_year':{str(k):int(v) for k,v in a.groupby('year').size().items()},'database_opened':False,'input_contract':'Annual frozen H1, T-2 history max10/730days; observed declarations availability assumed; no new forecast fit'})
 print('Adjusted-rank input pairs',len(a),a.groupby('year').size().to_dict(),flush=True)
if __name__=='__main__':main()
