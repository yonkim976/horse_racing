"""Audit local later-period coverage without converting post-race captures into PIT inputs."""
from datetime import datetime,timezone
import duckdb
import support as s

def main():
    core=s.ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'
    stage=s.ROOT/'thoroughbred/refresh/runs/20261017_full_20261016/staged_core.duckdb'
    queries={
        'core':"SELECT source_meet,max(result_date) latest_date,count(*) FILTER(WHERE result_date>'20260920') later_rows FROM confirmed_runners GROUP BY 1",
        'results':"SELECT meet,min(event_date)::VARCHAR first_date,max(event_date)::VARCHAR latest_date,count(*) row_count,count(distinct (event_date,race_no)) races FROM research_current_race_results WHERE meet IN ('1','3') AND event_date>DATE '2026-09-20' GROUP BY 1",
        'cards':"SELECT meet,min(event_date)::VARCHAR first_date,max(event_date)::VARCHAR latest_date,count(*) row_count,count(distinct (event_date,race_no)) races,min(captured_at_utc) first_capture,max(captured_at_utc) last_capture FROM research_current_entry_sheets WHERE meet IN ('1','3') AND event_date>DATE '2026-09-20' GROUP BY 1",
        'matched':"""SELECT count(*) row_count,count(distinct (a.meet,a.event_date,a.race_no)) races,
            count(*) FILTER(WHERE CAST(b.captured_at_utc AS TIMESTAMPTZ)<CAST(a.event_date AS TIMESTAMPTZ)) card_captured_before_utc_event_day
            FROM research_current_race_results a LEFT JOIN research_current_entry_sheets b
            ON a.meet=b.meet AND a.event_date=b.event_date AND a.race_no=b.race_no AND a.horse_id=b.horse_id
            WHERE a.meet IN ('1','3') AND a.event_date>DATE '2026-09-20'"""}
    with duckdb.connect(str(core),read_only=True) as db:core_rows=db.execute(queries['core']).df().to_dict('records')
    with duckdb.connect(str(stage),read_only=True) as db:
        values={key:db.execute(queries[key]).df().to_dict('records') for key in ['results','cards','matched']}
    s.save(s.OUT/'later_period_readiness.json',{'checked_at_utc':datetime.now(timezone.utc).isoformat(),
        'sources':{str(p.relative_to(s.ROOT)):{'sha256':s.sha(p),'bytes':p.stat().st_size} for p in [core,stage]},
        'queries':queries,'core':core_rows,**values,'new_118_feature_frame_built':False,'prospective_input_sealed':False,
        'new_future_performance_claim':False,
        'requirements':['Replay the exact 118-feature contract on prior races before extending dates.',
            'Link canonical recent result/section/adjudication histories through each cutoff.',
            'Use timestamped pre-race field and carried-weight sources, seal model/input/prediction hashes before outcomes.',
            'Keep later retrospective evaluation separate from actual prospective evaluation.'],
        'network_collection_or_source_database_write':False})
    print(values,flush=True)

if __name__=='__main__':main()
