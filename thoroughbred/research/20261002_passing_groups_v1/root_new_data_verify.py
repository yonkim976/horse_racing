"""Read-only raw row parity and independent passing-group selection checks."""
import csv
import hashlib
import json
from pathlib import Path
import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'
FILES = {
    'passing_api_observations':'api_source/api_observations.parquet',
    'passing_api_page_ledger':'api_source/api_page_ledger.parquet',
    'passing_api_exclusions':'api_source/api_exclusions.parquet',
    'passing_rpt_race_headers':'rpt_mapping/rpt_race_headers.parquet',
    'passing_rpt_point_observations':'rpt_mapping/rpt_point_observations.parquet',
    'passing_rpt_source_files':'rpt_mapping/rpt_source_files.parquet',
    'passing_rpt_snapshot_comparison':'rpt_mapping/rpt_snapshot_comparison.parquet',
    'passing_rpt_point_mapping':'rpt_mapping/rpt_point_mapping.csv',
    'passing_api_mapping_validation':'api_mapping_independent/api_mapping_validation_by_year.parquet',
    'passing_api_rpt_value_matches':'api_mapping_independent/api_rpt_value_matches.parquet',
}


def qi(value):
    return '"'+value.replace('"','""')+'"'


def sl(value):
    return "'"+str(value).replace("'","''")+"'"


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def mismatch(con,a,b,cols):
    expr = 'sha256(to_json(struct_pack('+','.join(qi(name)+':='+qi(name) for name in cols)+')))'
    return [con.execute(f'SELECT count(*) FROM (SELECT {expr} FROM {left} EXCEPT ALL SELECT {expr} FROM {right})').fetchone()[0] for left,right in [(a,b),(b,a)]]


def main():
    con = duckdb.connect(str(CORE),read_only=True)
    con.execute("SET memory_limit='2GB'")
    con.execute('SET threads=2')
    parity = {}
    for table,relative in FILES.items():
        path = HERE/relative
        source = ('read_parquet('+sl(path)+')') if path.suffix=='.parquet' else ('read_csv_auto('+sl(path)+',header=true)')
        schema = con.execute('DESCRIBE '+qi(table)).fetchall()
        assert schema == con.execute('DESCRIBE SELECT * FROM '+source).fetchall(),table
        diff = mismatch(con,qi(table),source,[col[0] for col in schema])
        assert diff == [0,0],(table,diff)
        parity[table] = {'bidirectional_mismatch':diff,'rows':con.execute('SELECT count(*) FROM '+qi(table)).fetchone()[0],'source_sha256':sha(path)}
        print(json.dumps({'stage':'raw_input_parity','table':table}),flush=True)
    selected = ['actual_meet_code','event_date','race_no','canonical_point_code','notation_raw','selected_source']
    diff = mismatch(con,'race_passing_groups','read_parquet('+sl(HERE/'root_expected_selected_points.parquet')+')',selected)
    assert diff == [0,0],('independent_selection',diff)
    expected_conflicts = json.loads((HERE/'root_expected_value_conflicts.json').read_text())
    actual_conflicts = {(m,d,int(n),point) for m,d,n,point in con.execute("SELECT actual_meet_code,event_date,race_no,canonical_point_code FROM passing_point_discrepancy_ledger WHERE comparison_status='source_value_discrepancy'").fetchall()}
    assert actual_conflicts == {(row['actual_meet_code'],row['event_date'],row['race_no'],row['canonical_point_code']) for row in expected_conflicts}
    expected_keys = {(row['meet'],row['event_date'],row['race_no']) for row in json.loads((HERE/'root_expected_confirmed_races.json').read_text())}
    coverage = con.execute('SELECT actual_meet_code,event_date,race_no,selected_point_values FROM passing_race_coverage').fetchall()
    assert len(coverage)==29710 and {(m,d,int(n)) for m,d,n,_ in coverage} == expected_keys
    assert all(n>0 for *_,n in coverage)
    assert con.execute("SELECT count(*) FROM race_passing_groups WHERE notation_raw IS NULL OR trim(notation_raw,' ') IN ('','-','X') OR historical_publication_time_verified IS DISTINCT FROM FALSE OR source_publication_at_kst IS NOT NULL").fetchone()[0] == 0
    assert con.execute('SELECT count(*)-count(DISTINCT (actual_meet_code,event_date,race_no,canonical_point_code)) FROM race_passing_groups').fetchone()[0] == 0
    reconciliation = dict(con.execute('SELECT reconciliation_status,count(*) FROM passing_api_event_reconciliation GROUP BY 1').fetchall())
    assert reconciliation == {'confirmed_executed_race':29710,'core_execution_ledger_nonconfirmed_match':64},reconciliation
    for relative,digest,literal in con.execute('SELECT source_path,source_sha256,metadata_json FROM passing_source_metadata').fetchall():
        path=(ROOT/relative).resolve(strict=True)
        assert path.is_relative_to(ROOT) and sha(path)==digest and path.read_text()==literal
    errors = {}
    cursor = con.execute('SELECT * FROM passing_api_error_evidence')
    labels = [col[0] for col in cursor.description]
    for vals in cursor.fetchall():
        row = dict(zip(labels,vals));key=(row['error_source'],row['meet'],row['date'],row['race_no']);assert key not in errors;errors[key]=row
    for source in ('planless_positive_result_review','result_only_nonfinish_anomaly_review'):
        path = ROOT/'thoroughbred/research/20260929_calendar_api_v1'/(source+'.csv')
        with path.open(encoding='utf-8-sig') as stream:
            for row in csv.DictReader(stream):
                target=errors[(source,row['meet'],row['date'],row['race_no'])]
                assert all(target[key]==value for key,value in row.items())
    assert len(errors)==72
    source_counts=dict(con.execute('SELECT selected_source,count(*) FROM race_passing_groups GROUP BY 1').fetchall())
    assert source_counts=={'api303':142227,'dacom11_rpt':1774}
    result={'all_passed':True,'input_table_parity':parity,'independent_selection_mismatch':diff,'selected_source_counts':source_counts,'confirmed_race_coverage':len(coverage),'cross_source_conflicting_points':len(actual_conflicts),'api_event_reconciliation':reconciliation,'api_error_evidence_rows_checked':len(errors),'verification_script_sha256':sha(Path(__file__))}
    (HERE/'root_new_data_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
