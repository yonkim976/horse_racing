"""Reopen persisted research DB and compare all source-backed new tables."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def qi(value):
    return '"'+value.replace('"','""')+'"'


def main():
    spec=importlib.util.spec_from_file_location('loader_review',HERE/'loader/load_steward_reports.py')
    loader=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    con=duckdb.connect(str(ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'),read_only=True)
    con.execute("SET memory_limit='2GB'")
    parity={}
    for relative,table in loader.PARQUET_INPUTS.values():
        path=HERE/relative
        columns=','.join(qi(c) for c in pq.read_schema(path).names)
        a=f'SELECT {columns} FROM {qi(table)}'
        if table == 'steward_report_paragraphs':
            a = f'SELECT {columns} FROM (SELECT * FROM steward_report_paragraphs UNION ALL SELECT * FROM steward_report_paragraph_field_states)'
        b=f'SELECT {columns} FROM read_parquet(?)'
        added=con.execute(f'SELECT count(*) FROM ({a} EXCEPT ALL {b})',[str(path)]).fetchone()[0]
        lost=con.execute(f'SELECT count(*) FROM ({b} EXCEPT ALL {a})',[str(path)]).fetchone()[0]
        assert added==lost==0,(table,added,lost)
        parity[table]={'added':added,'lost':lost}
    expected=pq.read_table(HERE/'root_sanction_entry_expectations.parquet')
    con.register('expected_sanctions',expected)
    mismatches=con.execute('''SELECT count(*) FROM steward_sanction_target_link_audit a
       FULL JOIN expected_sanctions e ON e.observation_locator=a.sanction_observation_locator
       WHERE a.sanction_observation_locator IS NULL OR e.observation_locator IS NULL
          OR a.exact_target_entry_match_count IS DISTINCT FROM e.exact_target_matches
          OR a.exact_id_entry_and_name_match_count IS DISTINCT FROM e.exact_target_name_matches''').fetchone()[0]
    assert mismatches==0
    fake_provenance=con.execute('''SELECT count(*) FROM horse_steward_history h
      LEFT JOIN steward_report_observations o ON o.observation_locator=h.full_report_observation_locator
      WHERE o.observation_locator IS NULL OR o.source_path<>h.source_path
         OR o.page_sha256<>h.page_sha256 OR o.source_row_sha256<>h.source_row_sha256
         OR o.source_captured_at_utc<>h.source_captured_at_utc''').fetchone()[0]
    assert fake_provenance==0
    canonical_count=con.execute('SELECT count(*) FROM horse_steward_history').fetchone()[0]
    ordinary=con.execute("SELECT count(*) FROM steward_report_horse_paragraph_history WHERE source_report_text_field<>'addJudgement'").fetchone()[0]
    unique_supplement=con.execute('''SELECT count(*) FROM (SELECT DISTINCT horse_id,event_date,venue_code,race_no,program_no_raw,paragraph_raw,parent_report_event_date,parent_report_meet_code,mention_semantics
      FROM steward_report_horse_paragraph_history WHERE source_report_text_field='addJudgement')''').fetchone()[0]
    assert canonical_count==ordinary+unique_supplement
    assert con.execute('SELECT count(*) FROM steward_report_event_coverage').fetchone()[0]==29826
    assert con.execute('SELECT count(*) FROM steward_report_nonexecution_observations').fetchone()[0]==14
    assert con.execute('SELECT count(*) FROM steward_api_source_observations WHERE historical_publication_time_verified OR source_publication_at_kst IS NOT NULL').fetchone()[0]==0
    counts={name:con.execute('SELECT count(*) FROM '+qi(name)).fetchone()[0] for _,name in loader.schema_objects()}
    # Materialize every persisted view after the loader connection is closed;
    # this detects any accidental dependency on dry-run/temp aliases.
    con.close()
    result={'all_passed':True,'checked_at_utc':datetime.now(timezone.utc).isoformat(),'source_table_exact_multiset_parity':parity,
            'sanction_occurrence_expectation_mismatches':mismatches,'canonical_history_provenance_mismatches':fake_provenance,
            'horse_steward_history_rows':canonical_count,'ordinary_history_rows':ordinary,'distinct_supplemental_rows':unique_supplement,
            'all_persisted_objects_queryable':True,'new_object_counts':counts}
    (HERE/'root_loaded_data_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('new_object_counts','source_table_exact_multiset_parity')},ensure_ascii=False))


if __name__=='__main__':
    main()
