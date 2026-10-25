"""Read-only official runner identity/outcome/field audit, without policy scoring."""
from pathlib import Path
import hashlib
import json
import sqlite3
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent

def main():
 f=pd.read_parquet(ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet',
  columns=['api_record_id','race_id','race_date','year','horse_id','horse_number','field_n','finish_position'])
 f=f[f.year.between(2024,2026)].copy();f.race_id=f.race_id.astype(str)
 connection=sqlite3.connect((ROOT/'data/horse_racing.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
 connection.execute('PRAGMA query_only=ON');connection.execute('BEGIN')
 sql='''SELECT r.race_date_local, r.race_number,r.field_size,r.status,e.horse_number,e.scratched,
 z.finish_position,z.disqualified,h.kra_horse_id
 FROM races r JOIN racecourses c ON c.id=r.racecourse_id
 JOIN race_entries e ON e.race_id=r.id JOIN horses h ON h.id=e.horse_id
 LEFT JOIN race_results z ON z.race_entry_id=e.id
 WHERE c.kra_meet_code=? AND r.race_date_local BETWEEN ? AND ?'''
 official=pd.read_sql_query(sql,connection,params=(2,'2024-01-01','2026-09-19'));connection.close()
 official['race_id']=official.race_date_local+'_'+'2'+'_'+official.race_number.astype(str)
 official=official[official.race_id.isin(f.race_id)].copy()
 assert len(official)==len(f)==17412 and not official.duplicated(['race_id','horse_number']).any()
 joined=f.merge(official,on=['race_id','horse_number'],validate='one_to_one',suffixes=('','_official'))
 assert len(joined)==17412 and joined.horse_id.astype(str).eq(joined.kra_horse_id.astype(str)).all()
 assert joined.finish_position.eq(joined.finish_position_official).all()
 assert joined.field_n.eq(joined.field_size).all() and joined.scratched.eq(0).all() and joined.disqualified.eq(0).all()
 for rid,g in joined.groupby('race_id'):
  assert len(g)==g.field_n.iloc[0] and sorted(g.finish_position)==list(range(1,len(g)+1))
 target=STUDY/'ROOT_OFFICIAL_RESULTS.csv';assert not target.exists();official.sort_values(['race_id','horse_number']).to_csv(target,index=False)
 report={'status':'PASS','runner_keys_and_horse_ids_verified':17412,'races':1779,
  'official_and_model_actual_field_sizes_match':True,'scratch_DQ_dead_heat_or_incomplete_model_rosters':0,
  'race_status_counts':official.drop_duplicates('race_id').status.value_counts().to_dict(),
  'outcome_identity_check_only':True,'policy_metrics_computed':False,'database_access':'mode=ro; query_only; read transaction',
  'reference_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
 dest=STUDY/'ROOT_OFFICIAL_SOURCE_REVIEW.json';assert not dest.exists();dest.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
