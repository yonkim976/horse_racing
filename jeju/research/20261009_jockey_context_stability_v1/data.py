"""Build the fixed research inputs from preserved quality and history artifacts."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OLD=ROOT/'jeju/research/20261009_jockey_effects_v1'
NUM=['field_n','gate_scaled','carried_weight_kg','body_kg','moisture','year_index','month_sin','month_cos',
 'h_any_n','h_same_n','h_any_gap_days','h_same_gap_days','h_any_finish_rank_mean','h_same_finish_rank_mean','h_any_finish_rank_last','h_same_finish_rank_last',
 'h_any_relative_time_mean','h_same_relative_time_mean','h_any_s1ftime_mean','h_same_s1ftime_mean','h_any_g3ftime_mean','h_any_g1ftime_mean',
 'h_any_s1f_first_mean','h_same_s1f_first_mean','h_any_s1f_front_mean','h_any_s1f_middle_mean','h_any_s1f_rear_mean',
 'opp_rank_mean','opp_time_mean','own_vs_field_rank','own_vs_field_time']
CAT=['race_distance_m','class_clean']
FE_NUM=['carried_weight_kg','body_kg','gate_scaled','h_any_n','h_same_n','h_any_gap_days','h_same_gap_days',
 'h_any_finish_rank_mean','h_same_finish_rank_mean','h_any_relative_time_mean','h_same_relative_time_mean',
 'h_any_s1ftime_mean','h_any_g3ftime_mean','h_any_g1ftime_mean','h_any_s1f_first_mean','h_any_s1f_front_mean','h_any_s1f_middle_mean','h_any_s1f_rear_mean']
CONTEXT=['opp_inner_faster_count','opp_outer_faster_count','opp_inner_lead_sum','opp_outer_lead_sum','opp_speed_known_fraction','opp_known_fraction']
ADJUST=FE_NUM+CONTEXT+['h_any_c4_first_mean','h_any_late_mean','h_any_late_n','own_prior_front','rival_leaders','HIST_coverage']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def save(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False)
 pf=ROOT/'jeju/research/20261008_gate_region_pace_prediction_v2/features01/features_and_targets.csv'
 sf=ROOT/'jeju/research/20261009_style_leader_density_v1/features01/start_features.csv'
 of=ROOT/'jeju/research/20261008_running_style_outcomes_v1/run01/runner_types_and_evidence.csv'
 sources=[HERE/'PLAN.md',OLD/'input01/starts.csv',pf,sf,of,OLD/'forecast01/predictions.csv',OLD/'forecast01/parameters.json',OLD/'effects.py',OLD/'data.py',ROOT/'jeju/data/horse_exclusions.json',ROOT/'jeju/research/20261008_gate_region_pace_prediction_v2/features01/history_lineage.csv']
 base=['api_record_id','race_id','race_date','horse_id','jockey_id','trainer_id','jockey_display_name','trainer_name','year','month','horse_number','horse_distance','horse_jockey','finish_position','time','relative_time','top3','first_pack','g3f_rank','history_cutoff','result_payload_sha256','c4_rank_lo','h_any_s1f_n','h_any_c4_first_mean']
 cols=list(dict.fromkeys(base+NUM+CAT+FE_NUM));a=pd.read_csv(sources[1],usecols=cols,dtype={'horse_id':str,'jockey_id':str,'trainer_id':str},low_memory=False)
 p=pd.read_csv(pf,usecols=['api_record_id','y_s1f_pack3','gate_band']+CONTEXT)
 a=a.merge(p,on='api_record_id',validate='one_to_one')
 s=pd.read_csv(sf,usecols=['api_record_id','leaders_any','coverage_any','style_any','h_any_late_mean','h_any_late_n'])
 a=a.merge(s,on='api_record_id',validate='one_to_one')
 o=pd.read_csv(of,usecols=['api_record_id','c4_rank_hi','c4_zone','s1f_rank_lo','s1f_rank_hi'])
 a=a.merge(o,on='api_record_id',validate='one_to_one');assert len(a)==52155 and a.api_record_id.nunique()==len(a)
 a['front_pack2']=np.where(a.y_s1f_pack3.notna(),a.y_s1f_pack3.le(1).astype(float),np.nan)
 a['outer']=a.gate_scaled.gt(2/3)
 a['own_prior_front']=a.style_any.isin(['lead','front']).astype(float)
 a['rival_leaders']=a.leaders_any-a.style_any.eq('lead').astype(int)
 a['HIST_coverage']=a.coverage_any;a['pace_eligible']=a.coverage_any.ge(.8-1e-12);a['pressure']=a.rival_leaders.ge(2)
 a['fade3']=np.where(a.c4_rank_hi.notna(),a.finish_position.ge(a.c4_rank_hi+3).astype(float),np.nan)
 a['gate_x_early']=a.gate_scaled*a.h_any_s1ftime_mean
 for dist in sorted(a.race_distance_m.unique()):a['gate_d'+str(int(dist))]=a.gate_scaled*a.race_distance_m.eq(dist)
 pr=pd.read_csv(OLD/'forecast01/predictions.csv')
 for model in ['H0','H1','H2']:
  z=pr[pr.model.eq(model)][['api_record_id','time_prediction','prob_top3']].rename(columns={'time_prediction':model+'_time','prob_top3':model+'_prob'})
  a=a.merge(z,on='api_record_id',how='left',validate='one_to_one')
 a['H1_slow_error']=a.relative_time-a.H1_time
 a['big_slow']=np.where(a.H1_time.notna(),a.H1_slow_error.gt(1.5).astype(float),np.nan)
 a['slow_loss']=a.H1_slow_error.clip(lower=0);a['absolute_error']=a.H1_slow_error.abs()
 a['jockey_distance']=a.jockey_id+':'+a.race_distance_m.astype(str);a['trainer_jockey']=a.trainer_id+':'+a.jockey_id
 a=a.sort_values(['race_date','race_id','horse_number']).reset_index(drop=True)
 assert not a.horse_id.eq('3005648').any() and a.rival_leaders.ge(0).all()
 assert np.allclose(a.first_pack,np.where(a.y_s1f_pack3.notna(),a.y_s1f_pack3.eq(0).astype(float),np.nan),equal_nan=True)
 a.to_csv(out/'starts.csv',index=False,encoding='utf-8-sig')
 manifest={'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],'database_opened':False,'database_sha256':sha(ROOT/'jeju/data/jeju_native_core.sqlite3'),'source_starts':len(a),'races':a.race_id.nunique(),'horses':a.horse_id.nunique()};save(out/'source_manifest.json',manifest)
 support=[]
 for period,g in [('all',a),('2024_2025',a[a.year.between(2024,2025)]),('2026',a[a.year.eq(2026)])]:
  support.append({'period':period,'starts':len(g),'outer':int(g.outer.sum()),'pace_eligible':int(g.pace_eligible.sum()),'pace_pressure':int((g.pace_eligible&g.pressure).sum()),'first_pack_available':int(g.first_pack.notna().sum()),'fade_available':int(g.fade3.notna().sum()),'tail_available':int(g.big_slow.notna().sum())})
 save(out/'support.json',support);print('Input support',support,flush=True)
if __name__=='__main__':main()
