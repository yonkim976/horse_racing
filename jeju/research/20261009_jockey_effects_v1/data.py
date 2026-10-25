"""Join preserved quality results, T-minus-two features and event identities read-only."""
from pathlib import Path
import hashlib,json,sqlite3
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def save(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
NUM=['field_n','gate_scaled','carried_weight_kg','body_kg','moisture','year_index','month_sin','month_cos',
 'h_any_n','h_same_n','h_any_gap_days','h_same_gap_days','h_any_finish_rank_mean','h_same_finish_rank_mean','h_any_finish_rank_last','h_same_finish_rank_last',
 'h_any_relative_time_mean','h_same_relative_time_mean','h_any_s1ftime_mean','h_same_s1ftime_mean','h_any_g3ftime_mean','h_any_g1ftime_mean',
 'h_any_s1f_first_mean','h_same_s1f_first_mean','h_any_s1f_front_mean','h_any_s1f_middle_mean','h_any_s1f_rear_mean',
 'opp_rank_mean','opp_time_mean','own_vs_field_rank','own_vs_field_time']
CAT=['race_distance_m','class_clean']
FE_NUM=['carried_weight_kg','body_kg','gate_scaled','h_any_n','h_same_n','h_any_gap_days','h_same_gap_days',
 'h_any_finish_rank_mean','h_same_finish_rank_mean','h_any_relative_time_mean','h_same_relative_time_mean',
 'h_any_s1ftime_mean','h_any_g3ftime_mean','h_any_g1ftime_mean','h_any_s1f_first_mean','h_any_s1f_front_mean','h_any_s1f_middle_mean','h_any_s1f_rear_mean']
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False)
 w=ROOT/'jeju/research/20261008_weight_speed_v2/source_lineage.csv';f=ROOT/'jeju/research/20261008_gate_region_pace_prediction_v2/features01/features_and_targets.csv';r=ROOT/'jeju/research/20261008_running_style_outcomes_v1/run01/runner_types_and_evidence.csv';db=ROOT/'jeju/data/jeju_native_core.sqlite3'
 sources=[HERE/'PLAN.md',w,f,r,ROOT/'jeju/research/20261008_gate_region_pace_prediction_v2/features01/history_lineage.csv',ROOT/'jeju/data/horse_exclusions.json']
 manifest={'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],'database_path':str(db.relative_to(ROOT)),'database_sha256_before':sha(db),'database_bytes':db.stat().st_size}
 a=pd.read_csv(w,dtype={'horse_id':str,'jockey_id':str});features=pd.read_csv(f,dtype={'horse_id':str},low_memory=False)
 keep=['api_record_id','gate_scaled','y_s1f_pack3','y_s1f_position4']+[c for c in features if c.startswith('h_')]
 a=a.merge(features[keep],on='api_record_id',validate='one_to_one');a.jockey_id=a.jockey_id.str.zfill(6)
 outcomes=pd.read_csv(r,usecols=['api_record_id','g3f_relative_rank_fraction','c4_rank_lo','g1f_rank_hi']);a=a.merge(outcomes,on='api_record_id',validate='one_to_one')
 con=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON')
 ids=pd.read_sql_query('SELECT r.api_record_id,r.horse_id,r.race_date,r.race_distance_m,r.jockey_id,r.jockey_name,r.trainer_id,r.trainer_name,a.payload_sha256 FROM race_result_rows r JOIN api_records a ON a.api_record_id=r.api_record_id',con);con.close()
 ids.jockey_id=ids.jockey_id.astype('string').str.zfill(6);a=a.merge(ids,on=['api_record_id','horse_id','race_date','race_distance_m','jockey_id'],validate='one_to_one',how='left')
 assert len(a)==52155 and a.payload_sha256.notna().all() and a.result_payload_sha256.eq(a.payload_sha256).all()
 missing=int(a.trainer_id.isna().sum());a.trainer_id=a.trainer_id.fillna('unknown').astype(str).str.zfill(6)
 names=a.sort_values(['race_date','api_record_id']).groupby('jockey_id').jockey_name.last().to_dict();a['jockey_display_name']=a.jockey_id.map(names)
 a['horse_distance']=a.horse_id+':'+a.race_distance_m.astype(str);a['horse_jockey']=a.horse_id+':'+a.jockey_id
 a['year_index']=a.year-2020;a['month_sin']=np.sin(2*np.pi*(a.month-1)/12);a['month_cos']=np.cos(2*np.pi*(a.month-1)/12)
 a['class_clean']=a.rank_class_raw.replace({'제1':'제1등급','제OPEN':'제오픈'})
 a['top3']=a.finish_position.le(3).astype(float);a['relative_time']=a.time-a.groupby('race_id').time.transform('mean')
 a['first_pack']=np.where(a.y_s1f_pack3.notna(),a.y_s1f_pack3.eq(0).astype(float),np.nan)
 a['late_gain']=np.where(a.c4_rank_lo.notna()&a.g1f_rank_hi.notna(),a.c4_rank_lo-a.g1f_rank_hi>=2,np.nan)
 a['g3f_rank']=a.g3f_relative_rank_fraction
 for short,col in [('rank','h_any_finish_rank_mean'),('time','h_any_relative_time_mean')]:
  count=a[col].notna().groupby(a.race_id).transform('sum')-a[col].notna().astype(int);total=a[col].fillna(0).groupby(a.race_id).transform('sum')-a[col].fillna(0)
  a['opp_'+short+'_mean']=total/count.where(count>0);a['own_vs_field_'+short]=a[col]-a['opp_'+short+'_mean']
 assert not a.horse_id.eq('3005648').any();a=a.sort_values(['race_date','race_id','horse_number']).reset_index(drop=True)
 a.to_csv(out/'starts.csv',index=False,encoding='utf-8-sig')
 pd.DataFrame([{'jockey_id':j,'latest_event_name':n,'event_name_variants':'|'.join(sorted(a.loc[a.jockey_id.eq(j),'jockey_name'].dropna().unique()))} for j,n in names.items()]).to_csv(out/'jockey_names.csv',index=False,encoding='utf-8-sig')
 manifest['database_sha256_after']=sha(db);assert manifest['database_sha256_before']==manifest['database_sha256_after'];manifest.update(database_read_only=True,source_payload_hashes_checked=len(a),trainer_missing_rows=missing,trainers=a.trainer_id.nunique())
 assert all(sha(ROOT/x['path'])==x['sha256'] for x in manifest['files']);save(out/'source_manifest.json',manifest)
 print('Inputs',len(a),'jockeys',a.jockey_id.nunique(),'trainers',a.trainer_id.nunique(),'missing trainer',missing,flush=True)
if __name__=='__main__':main()
