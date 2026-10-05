"""Read-only source readiness audit; no model training or DB writes."""
from pathlib import Path
import json,sqlite3,hashlib
import duckdb
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
DB=ROOT/'data/horse_racing.sqlite3'
OLD=ROOT/'data/research/thoroughbred_three_targets_20260918_v3/prepared_context.parquet'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
with sqlite3.connect(f'file:{DB}?mode=ro',uri=True) as con:
    con.execute('PRAGMA query_only=ON')
    batches=pd.read_sql_query('SELECT * FROM race_point_source_batches ORDER BY meet_code,race_year',con)
    sections=pd.read_sql_query('''SELECT b.meet_code,b.race_year,s.point_code,s.time_kind,count(*) rows,
        count(s.elapsed_time_ms) timed_rows,sum(CASE WHEN s.position_raw BETWEEN 1 AND 20 THEN 1 ELSE 0 END) positive_rank_rows
        FROM race_section_times s JOIN race_point_source_batches b ON b.id=s.source_batch_id
        WHERE b.meet_code IN (1,3) GROUP BY 1,2,3,4''',con)
    groups=pd.read_sql_query('''SELECT b.meet_code,b.race_year,count(*) rows,count(DISTINCT p.race_id) races,
        min(r.race_date_local) first_date,max(r.race_date_local) last_date
        FROM race_passing_groups p JOIN race_point_source_batches b ON b.id=p.source_batch_id
        JOIN races r ON r.id=p.race_id WHERE b.meet_code IN (1,3) GROUP BY 1,2''',con)
    history=pd.read_sql_query('''SELECT h.kra_horse_id hr_no,r.race_date_local race_date,
        CASE rc.kra_meet_code WHEN 1 THEN 'SEOUL' WHEN 3 THEN 'BUSAN' END venue_code
        FROM race_section_times s JOIN race_entries e ON e.id=s.race_entry_id
        JOIN races r ON r.id=e.race_id JOIN racecourses rc ON rc.id=r.racecourse_id
        JOIN horses h ON h.id=e.horse_id JOIN race_results rr ON rr.race_entry_id=e.id
        WHERE rc.kra_meet_code IN (1,3) AND r.race_date_local BETWEEN '2017-01-01' AND '2026-09-13'
        AND s.point_code='S1F' AND s.time_kind='cumulative'
        AND s.elapsed_time_ms>0 AND s.position_raw BETWEEN 1 AND COALESCE(r.field_size,20)
        AND rr.finish_position BETWEEN 1 AND 20 AND COALESCE(rr.disqualified,0)=0 AND COALESCE(e.scratched,0)=0''',con)
with duckdb.connect() as con:
    old=con.execute('''SELECT race_id,race_date,hr_no,venue_code,research_pace_early_pos_pct_avg5,
        research_pace_late_gain_pct_avg5 FROM read_parquet(?)
        WHERE venue_code IN ('SEOUL','BUSAN') AND race_date BETWEEN '2021-01-01' AND '2026-09-13' ''',[str(OLD)]).df()
old.race_date=pd.to_datetime(old.race_date);history.race_date=pd.to_datetime(history.race_date)
first=history.groupby('hr_no').race_date.min().rename('first_valid_new_S1F_date')
x=old.merge(first,on='hr_no',how='left',validate='many_to_one')
x['old_early_available']=x.research_pace_early_pos_pct_avg5.notna()
x['new_prior_S1F_available']=x.first_valid_new_S1F_date.lt(x.race_date)
x['newly_supported']=~x.old_early_available&x.new_prior_S1F_available
coverage=[]
for venue,g in x.groupby('venue_code'):
    coverage.append({'venue':venue,'old_dataset_rows':len(g),'old_early_available':int(g.old_early_available.sum()),'old_early_available_rate':float(g.old_early_available.mean()),'new_prior_S1F_available':int(g.new_prior_S1F_available.sum()),'new_prior_S1F_available_rate':float(g.new_prior_S1F_available.mean()),'newly_supported_old_missing_rows':int(g.newly_supported.sum())})
sections.to_csv(OUT/'section_coverage_by_year.csv',index=False);groups.to_csv(OUT/'passing_group_coverage_by_year.csv',index=False)
batches.to_json(OUT/'source_batches_snapshot.json',orient='records',indent=2,force_ascii=False)
files=['docs/THOROUGHBRED_HUMAN_ANALYSIS_FRAMEWORK_2026-09-28.md','docs/PASSING_SECTION_OPERATIONAL_MIGRATION_2026-09-28.md','research/track_common_residual_20260928/FINAL_REPORT_KO.md','data/research/thoroughbred_three_targets_20260918_v3/code/context_features.py','data/research/thoroughbred_followup_20260918_v4/model/candidate_features.json']
result={'scope':'read-only readiness audit, not trained feature coverage or accuracy measurement','source_as_of':'2026-09-28','database_open_mode':'read-only + query_only','old_dataset_sha256':sha(OLD),'read_sources_sha256':{f:sha(ROOT/f) for f in files},'prior_S1F_support':coverage,'new_history_valid_rows':len(history),'notes':['Old counts are nonmissing features in the frozen evaluation dataset, not counts of direct raw sections.','Potential new coverage requires a valid observed S1F on a strictly earlier date for the same horse; includes earlier starts at either venue.','Only new 2017+ history is counted; earlier legacy data are not reconstructed.','No newly generated input values, model fitting, prediction or probability change.','Availability by past race date does not independently verify original publication timestamps.']}
(OUT/'audit_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'prior_S1F_support':coverage,'new_history_valid_rows':len(history)},ensure_ascii=False,indent=2))
