"""Pinned prior research artifacts; official event trainer and owner IDs only."""
from pathlib import Path
import hashlib,json,importlib.util
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OLD=ROOT/'jeju/research/20261009_jockey_effects_v1'
spec=importlib.util.spec_from_file_location('old_data_contract',OLD/'data.py');contract=importlib.util.module_from_spec(spec);spec.loader.exec_module(contract)
NUM=contract.NUM;CAT=contract.CAT;FE_NUM=contract.FE_NUM
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def save(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False)
 source=ROOT/'jeju/research/20261009_jockey_closing_switch_v1/input01/starts.csv'
 cols=['api_record_id','race_id','horse_id','race_date','year','horse_number','horse_distance','time','relative_time','finish_position','top3','first_pack','late_gain','g3f_rank','jockey_id','trainer_id','trainer_name','owner_id','history_cutoff','result_payload_sha256','payload_sha256','owner_source_sha','previous_api_record_id','previous_race_date','previous_jockey_id','previous_trainer_id','previous_owner_id','previous_race_distance_m','gap_days','H1_time','H1_prob','H1_time_adv','H1_top3_excess','previous_H1_time','previous_H1_prob','previous_H1_time_adv','previous_H1_top3_excess']
 a=pd.read_csv(source,usecols=list(dict.fromkeys(cols+NUM+CAT+FE_NUM)),dtype={k:str for k in ['horse_id','jockey_id','trainer_id','owner_id','previous_jockey_id','previous_trainer_id','previous_owner_id']},low_memory=False)
 assert len(a)==52155 and not a.api_record_id.duplicated().any() and not a.horse_id.eq('3005648').any()
 assert a[['trainer_id','owner_id']].notna().all().all() and a.payload_sha256.eq(a.result_payload_sha256).all()
 a['changed_trainer']=a.previous_trainer_id.notna()&a.trainer_id.ne(a.previous_trainer_id)
 a['trainer_display_name']=a.trainer_id.map(a.sort_values('race_date').groupby('trainer_id').trainer_name.last())
 a=a.sort_values(['race_date','race_id','horse_number']).reset_index(drop=True)
 a.to_csv(out/'starts.csv',index=False,encoding='utf-8-sig')
 sources=[HERE/'PLAN.md',source,OLD/'data.py',OLD/'effects.py',OLD/'forecast01/predictions.csv',OLD/'forecast01/parameters.json',ROOT/'jeju/research/20261009_jockey_closing_switch_v1/input01/source_manifest.json',ROOT/'jeju/data/horse_exclusions.json']
 save(out/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],'database_opened':False,'database_sha256':sha(ROOT/'jeju/data/jeju_native_core.sqlite3'),'starts':len(a),'races':a.race_id.nunique(),'horses':a.horse_id.nunique(),'trainers':a.trainer_id.nunique(),'start':a.race_date.min(),'end':a.race_date.max()})
 support=[]
 for period,g in [('all',a),('2024_2025',a[a.year.between(2024,2025)]),('2026',a[a.year.eq(2026)])]:
  switchhorses=g.groupby('horse_distance').trainer_id.nunique();switchunits=set(switchhorses[switchhorses.gt(1)].index)
  for k,z in g.groupby('trainer_id'):
   support.append({'period':period,'trainer_id':k,'name':z.trainer_display_name.iloc[0],'starts':len(z),'horses':z.horse_id.nunique(),'days':z.race_date.nunique(),'changed_in':int(z.changed_trainer.sum()),'switch_horses_hd':z.loc[z.horse_distance.isin(switchunits),'horse_id'].nunique()})
 pd.DataFrame(support).to_csv(out/'support.csv',index=False,encoding='utf-8-sig');print('Trainer inputs ready',len(a),flush=True)
if __name__=='__main__':main()
