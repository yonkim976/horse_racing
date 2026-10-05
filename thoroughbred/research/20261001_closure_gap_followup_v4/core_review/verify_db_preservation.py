"""Read-only comparison with the pre-v4 database, including unchanged event data."""
import hashlib
import json
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
OUT = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'

def quote(name):
    return '"' + name.replace('"', '""') + '"'

def main():
    con = duckdb.connect(str(OUT / 'thoroughbred_core.duckdb'), read_only=True)
    old = OUT / 'backups/20261001_before_closure_gap_followup_v4/thoroughbred_core.duckdb'
    con.execute("ATTACH '" + str(old).replace("'", "''") + "' AS prior (READ_ONLY)")
    changes = {'calendar_days', 'annual_summary', 'official_closure_intervals', 'source_manifests'}
    objects = con.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog='prior' AND table_schema='main'").fetchall()
    checks, comparison = {}, {}
    for (name,) in objects:
        if name in changes:
            continue
        table = quote(name)
        diff = con.execute(f'SELECT (SELECT count(*) FROM (SELECT * FROM {table} EXCEPT ALL SELECT * FROM prior.main.{table})), (SELECT count(*) FROM (SELECT * FROM prior.main.{table} EXCEPT ALL SELECT * FROM {table}))').fetchone()
        comparison[name] = list(diff)
    checks['all_other_tables_and_views_exact'] = all(value == [0, 0] for value in comparison.values())
    for table, excluded in (
        ('calendar_days', {'official_closure_reason', 'official_closure_source_url', 'race_day_status'}),
        ('annual_summary', {'official_closure_calendar_days_documented'}),
    ):
        columns = ','.join(quote(row[0]) for row in con.execute('DESCRIBE ' + quote(table)).fetchall() if row[0] not in excluded)
        checks[table + '_other_columns_exact'] = con.execute(f'SELECT NOT EXISTS(SELECT {columns} FROM {quote(table)} EXCEPT ALL SELECT {columns} FROM prior.main.{quote(table)}) AND NOT EXISTS(SELECT {columns} FROM prior.main.{quote(table)} EXCEPT ALL SELECT {columns} FROM {quote(table)})').fetchone()[0]
    checks['old_77_intervals_preserved'] = con.execute('SELECT NOT EXISTS(SELECT * FROM prior.main.official_closure_intervals EXCEPT ALL SELECT * FROM official_closure_intervals)').fetchone()[0]
    counts = con.execute("SELECT (SELECT count(*) FROM official_closure_intervals), count(*) FILTER(WHERE coalesce(official_closure_source_url,'')<>''), count(*) FILTER(WHERE coalesce(official_closure_source_url,'')<>'' AND cast(executed_race_count AS INTEGER)>0) FROM calendar_days").fetchone()
    checks['81_intervals_552_venue_days_zero_conflicts'] = counts == (81, 552, 0)
    checks['12_new_days_exact'] = con.execute("WITH changed AS (SELECT n.* FROM calendar_days n JOIN prior.main.calendar_days o USING(meet,date) WHERE coalesce(n.official_closure_source_url,'')<>coalesce(o.official_closure_source_url,'')) SELECT count(*)=12 AND bool_and(meet IN ('1','3') AND (date BETWEEN '2021-01-01' AND '2021-01-03' OR date BETWEEN '2021-02-12' AND '2021-02-14') AND cast(executed_race_count AS INTEGER)=0) FROM changed").fetchone()[0]
    checks['four_user_document_intervals_typed'] = con.execute("WITH added AS (SELECT * FROM official_closure_intervals EXCEPT ALL SELECT * FROM prior.main.official_closure_intervals) SELECT count(*)=4 AND bool_and(evidence_kind='kra_authored_plan_user_supplied' AND starts_with(source_url,'user-file:') AND meet_code IN ('1','3')) FROM added").fetchone()[0]
    checks['feb20_busan_execution_retained'] = con.execute("SELECT executed_race_count='10' AND coalesce(official_closure_source_url,'')='' FROM calendar_days WHERE meet='3' AND date='2021-02-20'").fetchone()[0]
    checks['116_adjudications_preserved'] = con.execute('SELECT count(*)=116 FROM race_nonexecution_adjudication').fetchone()[0] and comparison['race_nonexecution_adjudication'] == [0,0]
    checks['29_subtypes_preserved'] = comparison['race_nonexecution_subtype_review'] == [0,0]
    checks['secondary_candidates_not_promoted'] = con.execute("SELECT NOT EXISTS(SELECT * FROM official_closure_intervals WHERE start_date<'2016-01-01' EXCEPT ALL SELECT * FROM prior.main.official_closure_intervals)").fetchone()[0]
    review = json.loads((HERE / 'manifest.json').read_text())
    checks['all_input_hashes_match'] = all(hashlib.sha256((ROOT/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in review['pinned_files'])
    manifest = json.loads((OUT/'manifest.json').read_text())
    checks['builder_checks_pass'] = all(manifest['checks'].values())
    checks['database_hash_matches'] = hashlib.sha256((OUT/'thoroughbred_core.duckdb').read_bytes()).hexdigest()==manifest['database_sha256']
    report = {'checks':checks, 'all_passed':all(checks.values()), 'unchanged_objects':comparison, 'closure_intervals':counts[0], 'closure_venue_days':counts[1], 'builder_check_count':len(manifest['checks'])}
    (HERE/'root_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='unchanged_objects'},ensure_ascii=False,indent=2))
    con.close()
    if not report['all_passed']:
        raise RuntimeError('v4 preservation checks failed')

if __name__=='__main__':
    main()
