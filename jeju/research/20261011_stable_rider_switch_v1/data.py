"""Official historical relationships and adjacent selected starts from pinned inputs."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OLD=ROOT/'jeju/research/20261009_jockey_closing_switch_v1'
ID_COLS=['horse_id','jockey_id','trainer_id','owner_id','previous_jockey_id','previous_trainer_id','previous_owner_id']
BASE=['H1_prob','H1_time','previous_H1_time_adv','previous_H1_top3_excess','previous_top3','previous_relative_time',
 'h_any_finish_rank_mean','h_any_relative_time_mean','h_any_n','current_rider_rate','previous_rider_rate','rider_rate_gain',
 'body_kg','carried_weight_kg','moisture','gate_scaled','field_n']
DELTA=['body_kg','carried_weight_kg','moisture','gate_scaled','h_any_relative_time_mean','h_any_finish_rank_mean']
CAT=['year','month','race_distance_m','class_clean']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def save(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def period_data(a,p):
 return a if p=='all' else a[a.year.le(2023)] if p=='past' else a[a.year.between(2024,2025)] if p=='2024_2025' else a[a.year.eq(2026)]
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False);source=OLD/'input01/starts.csv'
 cols=ID_COLS+BASE+CAT+['api_record_id','race_id','race_date','horse_number','trainer_name','jockey_display_name','finish_position','top3','relative_time','history_cutoff','result_payload_sha256','owner_source_sha','previous_api_record_id','previous_race_date','previous_race_distance_m','previous_class_clean','gap_days','changed_jockey','same_relations','rider_stats_valid','upgrade','H1_time_adv','H1_top3_excess','previous_H1_time','previous_H1_prob','current_rider_cutoff','current_rider_last_date','previous_rider_cutoff','previous_rider_last_date']+['previous_'+c for c in DELTA]
 allcols=list(dict.fromkeys(cols));a=pd.read_csv(source,usecols=allcols,dtype={k:str for k in ID_COLS},low_memory=False)
 assert len(a)==52155 and not a.api_record_id.duplicated().any() and not a.horse_id.eq('3005648').any()
 idx=a.set_index('api_record_id');mask=a.previous_api_record_id.notna()
 for c in ['finish_position','field_n']:a['previous_'+c]=a.previous_api_record_id.map(idx[c])
 a=a[a.same_relations&a.gap_days.between(2,90)&a.previous_api_record_id.notna()].copy()
 assert a.trainer_id.eq(a.previous_trainer_id).all() and a.owner_id.eq(a.previous_owner_id).all()
 a['cell']=a.trainer_id+':'+a.jockey_id;a['same_distance']=a.race_distance_m.eq(a.previous_race_distance_m)
 a['rank_quality']=1-(a.finish_position-1)/(a.field_n-1);a['previous_rank_quality']=1-(a.previous_finish_position-1)/(a.previous_field_n-1)
 a['rank_improved']=a.rank_quality.gt(a.previous_rank_quality+1e-10);a['win']=a.finish_position.eq(1).astype(float);a['previous_win']=a.previous_finish_position.eq(1).astype(float)
 a['time_gain']=a.H1_time_adv-a.previous_H1_time_adv;a['top3_excess_gain']=a.H1_top3_excess-a.previous_H1_top3_excess
 a['recent_eligible']=a.H1_time.notna()&a.previous_H1_time.notna();a=a.sort_values(['race_date','race_id','horse_number']).reset_index(drop=True)
 a.to_csv(out/'pairs.csv',index=False,encoding='utf-8-sig');support=[]
 for period in ['all','past','2024_2025','2026']:
  z=period_data(a,period);z=z[z.recent_eligible] if period in ['2024_2025','2026'] else z
  for cell,g in z.groupby('cell'):
   c=g[g.changed_jockey];other=z[z.trainer_id.eq(g.trainer_id.iloc[0])&z.changed_jockey&z.cell.ne(cell)]
   ok=len(c)>=20 and len(g)-len(c)>=20 and g.horse_id.nunique()>=15 and g.race_date.nunique()>=15 and c.horse_id.nunique()>=10 and c.race_date.nunique()>=10 and len(other)>=30
   support.append({'period':period,'cell':cell,'trainer_id':g.trainer_id.iloc[0],'trainer_name':g.trainer_name.iloc[-1],'jockey_id':g.jockey_id.iloc[0],'jockey_name':g.jockey_display_name.iloc[-1],'starts':len(g),'changes':len(c),'retained':len(g)-len(c),'horses':g.horse_id.nunique(),'days':g.race_date.nunique(),'changed_horses':c.horse_id.nunique(),'changed_days':c.race_date.nunique(),'other_changes_same_stable':len(other),'qualified':ok})
 pd.DataFrame(support).to_csv(out/'support.csv',index=False,encoding='utf-8-sig')
 sources=[HERE/'PLAN.md',source,OLD/'input01/source_manifest.json',OLD/'data.py',ROOT/'jeju/research/20261009_jockey_effects_v1/forecast01/predictions.csv',ROOT/'jeju/research/20261009_jockey_effects_v1/forecast01/parameters.json',ROOT/'jeju/data/horse_exclusions.json']
 save(out/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],'database_opened':False,'database_sha256':sha(ROOT/'jeju/data/jeju_native_core.sqlite3'),'input_starts':52155,'eligible_pairs':len(a),'changed_pairs':int(a.changed_jockey.sum()),'horses':a.horse_id.nunique(),'pair_cells':a.cell.nunique(),'first_date':a.race_date.min(),'last_date':a.race_date.max()})
 print(pd.DataFrame(support).groupby('period').qualified.agg(['size','sum']).to_string(),flush=True)
if __name__=='__main__':main()
