"""Observed true-ledger intervals, immutable outcome cohort and read-only SQLite."""
from pathlib import Path
import hashlib,json,sqlite3
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
DB=ROOT/'jeju/data/jeju_native_core.sqlite3'
SOURCE=ROOT/'jeju/research/20261009_jockey_closing_switch_v1/input01/starts.csv'
IDS=['horse_id','jockey_id','trainer_id','owner_id']
BINS=['1_7','8_14','15_21','22_28','29_42','43_60','61_90','91_180','181_plus']
GROUPS=['1_7','8_14','15_28','29_42','43_60','61_90','91_180','181_plus'];REF='15_28'
NUM=['body_kg','carried_weight_kg','gate_scaled','h_any_finish_rank_mean','h_same_finish_rank_mean','h_any_relative_time_mean','h_same_relative_time_mean','h_any_n','h_same_n','previous_rank_fraction','previous_relative_time']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def period_data(a):return {'all':a,'past':a[a.year.le(2023)],'2024_2025':a[a.year.between(2024,2025)],'2026':a[a.year.eq(2026)]}
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False);before=sha(DB)
 cols=['api_record_id','race_id','horse_id','race_date','year','month','horse_number','race_distance_m','field_n','finish_position','time','relative_time','top3','jockey_id','trainer_id','owner_id','history_cutoff','result_payload_sha256','class_clean','gap_days']+NUM[:-2]
 a=pd.read_csv(SOURCE,usecols=list(dict.fromkeys(cols)),dtype={c:str for c in IDS},low_memory=False).rename(columns={'gap_days':'selected_cohort_gap_days'})
 assert len(a)==52155 and not a.horse_id.eq('3005648').any()
 con=sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
 h=pd.read_sql_query('SELECT api_record_id,horse_id,horse_name,race_date,meet_code,race_number,race_distance_m,finish_position,finish_status_raw,finish_time_seconds,api4_3_payload_sha256 FROM jeju_race_analysis_2026 WHERE race_date <= ?',con,params=['2026-09-19'])
 fields=pd.read_sql_query('SELECT race_date,meet_code,race_number,SUM(CASE WHEN finish_position BETWEEN 1 AND 89 OR finish_position IN (91,92) THEN 1 ELSE 0 END) AS actual_field_n,AVG(CASE WHEN finish_position BETWEEN 1 AND 89 AND finish_time_seconds>0 THEN finish_time_seconds END) AS normal_mean_time FROM race_result_rows WHERE race_date <= ? GROUP BY race_date,meet_code,race_number',con,params=['2026-09-19']);con.close()
 assert before==sha(DB),'Database changed during read snapshot'
 h.horse_id=h.horse_id.astype(str);h=h[h.horse_id.isin(set(a.horse_id))].copy();assert not h.api_record_id.duplicated().any()
 h=h.merge(fields,on=['race_date','meet_code','race_number'],how='left',validate='many_to_one')
 h['observed_started']=h.finish_position.between(1,89)|h.finish_position.isin([91,92])
 h.to_csv(out/'ledger_rows.csv',index=False,encoding='utf-8-sig');fields.to_csv(out/'raw_race_field_context.csv',index=False,encoding='utf-8-sig')
 starts=h[h.observed_started].sort_values(['horse_id','race_date','race_number','api_record_id']).copy()
 assert not starts.duplicated(['horse_id','race_date']).any(),'Ambiguous same-day starts require review'
 starts['previous_api_record_id']=starts.groupby('horse_id').api_record_id.shift();starts['previous_race_date']=starts.groupby('horse_id').race_date.shift()
 starts['gap_days']=(pd.to_datetime(starts.race_date)-pd.to_datetime(starts.previous_race_date)).dt.days
 starts['rank_fraction']=np.where(starts.finish_position.between(1,89)&starts.actual_field_n.gt(1),(starts.finish_position-1)/(starts.actual_field_n-1),np.nan)
 starts['relative_time']=np.where(starts.finish_position.between(1,89)&starts.finish_time_seconds.gt(0),starts.finish_time_seconds-starts.normal_mean_time,np.nan)
 for c in ['finish_position','actual_field_n','rank_fraction','relative_time','race_distance_m','finish_status_raw']:starts['previous_'+c]=starts.groupby('horse_id')[c].shift()
 linkcols=['api_record_id','horse_name','api4_3_payload_sha256','actual_field_n','finish_position','finish_time_seconds','gap_days']+[c for c in starts if c.startswith('previous_')]
 cur=starts[linkcols].rename(columns={'finish_position':'ledger_finish_position','finish_time_seconds':'ledger_time'})
 a=a.merge(cur,on='api_record_id',how='left',validate='one_to_one')
 assert a.ledger_finish_position.eq(a.finish_position).all() and np.allclose(a.ledger_time,a.time)
 assert a.result_payload_sha256.eq(a.api4_3_payload_sha256).all() and a.field_n.eq(a.actual_field_n).all()
 assert a.gap_days.dropna().ge(1).all() and a.history_cutoff.lt(a.race_date).all()
 a['gap_bin']=pd.cut(a.gap_days,[0,7,14,21,28,42,60,90,180,np.inf],labels=BINS).astype('string')
 a['gap_group']=a.gap_bin.replace({'15_21':REF,'22_28':REF})
 a['rank_quality']=1-(a.finish_position-1)/(a.field_n-1);a['rank10_quality']=9*a.rank_quality;a['top3_pp']=100*a.top3
 a['rank_gain']=np.where(a.previous_finish_position.between(1,89),a.previous_finish_position-a.finish_position,np.nan)
 a['rank10_gain']=9*((1-a.previous_rank_fraction)-a.rank_quality)*-1
 a['same_previous_distance']=a.race_distance_m.eq(a.previous_race_distance_m)
 a['horse_distance']=a.horse_id+':'+a.race_distance_m.astype(str)
 a.to_csv(out/'starts.csv',index=False,encoding='utf-8-sig')
 sources=[SOURCE,HERE/'PLAN.md',ROOT/'jeju/research/20261007_foundation_v1/build_foundation.py',ROOT/'jeju/research/20261009_jockey_effects_v1/input01/source_manifest.json',ROOT/'jeju/data/horse_exclusions.json']
 save(out/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],'database_path':str(DB.relative_to(ROOT)),'database_sha256_before':before,'database_sha256_after':sha(DB),'database_read_only':True,'cohort_starts':len(a),'cohort_races':a.race_id.nunique(),'cohort_horses':a.horse_id.nunique(),'ledger_rows_for_cohort_horses':len(h),'observed_start_rows':len(starts),'prior_observed':int(a.gap_days.notna().sum()),'prior_unobserved':int(a.gap_days.isna().sum()),'selected_vs_ledger_gap_disagreements':int((a.selected_cohort_gap_days.notna()&a.gap_days.notna()&a.selected_cohort_gap_days.ne(a.gap_days)).sum()),'ignored_ledger_result_codes':h[~h.observed_started].finish_status_raw.value_counts().to_dict(),'period_end':'2026-09-19','partial_2026':True,'current_cohort_api_id_payload_rank_time_field_verified':len(a),'gap_is_latest_observed_start_in_candidate_ledger_not_complete_lifetime':True,'source_history_contract':'T-2 maximum10/730days; declarations/body at race availability not reconstructed','database_written':False})
 print('Interval source ready',len(a),'prior observed',a.gap_days.notna().sum(),'unknown',a.gap_days.isna().sum(),flush=True)
 print(a.gap_bin.value_counts(dropna=False).to_string(),flush=True)
if __name__=='__main__':main()
