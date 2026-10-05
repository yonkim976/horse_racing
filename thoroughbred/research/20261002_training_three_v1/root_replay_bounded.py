"""Read-only replay using Parquet views and SHA-256 of complete typed rows."""
import hashlib
import importlib.util
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('frozen_training_loader', HERE / 'loader/load_training_three.py')
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


def main():
    inventories, sources, coverage, parquets, hashes = loader.verify_inputs(loader.DEFAULT_INPUT)
    for name in ('load_training_three.py', 'schema.sql', 'input_contract.json'):
        path = HERE / 'loader' / name
        hashes[path.relative_to(loader.ROOT).as_posix()] = loader.sha256_file(path)
    before, _, source_count, _, is_replay = loader.inspect_core_state()
    assert is_replay and source_count == 23
    with tempfile.TemporaryDirectory(prefix='training-root-bounded-replay-') as scratch:
        con = duckdb.connect(':memory:')
        try:
            loader.configure_duckdb(con, Path(scratch))
            con.execute('SET threads=2')
            con.execute('SET preserve_insertion_order=false')
            con.execute('ATTACH ' + loader.sql_literal(str(loader.CORE_DB)) + ' AS core_db (READ_ONLY)')
            con.execute('CREATE TEMP VIEW entity_reference_roster AS SELECT * FROM core_db.entity_reference_roster')
            paths = ','.join(loader.parquet_sql_path(parquets[name]) for name in loader.DATASETS)
            con.execute(f'''CREATE TEMP VIEW training_raw_observations AS SELECT p.*,
                '{loader.AVAILABILITY_STATUS}'::VARCHAR AS availability_status,
                FALSE::BOOLEAN AS historical_prerace_eligibility_verified,
                '{loader.PHYSICAL_VENUE_STATUS}'::VARCHAR AS physical_venue_status
                FROM read_parquet([{paths}],union_by_name=false) p''')
            loader.apply_schema(con, dry_run=True)
            loader.load_staging_rows(con, coverage, sources)
            loader.validate_input_capture_linkage(con)
            metrics = loader.validate_staged_data(con, inventories, sources)
            pins = {'loader':loader.sha256_file(HERE/'loader/load_training_three.py'),
                    'schema':loader.sha256_file(HERE/'loader/schema.sql'),
                    'contract':loader.sha256_file(HERE/'loader/input_contract.json')}
            expected = json.dumps(loader.source_manifest_value(inventories, hashes, metrics, pins),
                                  ensure_ascii=False,sort_keys=True)
            stored = con.execute('SELECT json_text FROM core_db.source_manifests WHERE name=?',
                                 [loader.SOURCE_MANIFEST_NAME]).fetchall()
            assert stored == [(expected,)]
            digest = 'sha256(to_json(struct_pack(' + ','.join('"'+name+'":="'+name+'"' for name in loader.RAW_TABLE_COLUMNS) + ')))'
            deltas = []
            for left,right in [('core_db.training_raw_observations','training_raw_observations'),
                               ('training_raw_observations','core_db.training_raw_observations')]:
                deltas.append(con.execute(f'SELECT count(*) FROM (SELECT {digest} FROM {left} EXCEPT ALL SELECT {digest} FROM {right})').fetchone()[0])
            assert deltas == [0,0]
            for table, columns in [('training_capture_coverage', [row[0] for row in con.execute('DESCRIBE training_capture_coverage').fetchall()]),
                                   ('training_source_files', [row[0] for row in con.execute('DESCRIBE training_source_files').fetchall()])]:
                assert loader.compare_small_table(con,table,columns) == 0
            for view,count in metrics['dataset_view_rows'].items():
                assert con.execute('SELECT count(*) FROM core_db.' + view).fetchone()[0] == count
        finally:
            con.close()
    after = loader.sha256_file(loader.CORE_DB)
    assert before == after
    report = {'status':'read_only_bounded_replay_passed','applied':False,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
              'comparison':'SHA-256 of full typed row, EXCEPT ALL both directions; metadata exact comparison',
              'source_manifest_exact_match':True,'row_digest_deltas':deltas,'metrics':metrics,
              'database_sha256_before':before,'database_sha256_after':after,'source_pins':hashes,
              'verification_script_sha256':loader.sha256_file(Path(__file__))}
    (HERE/'loader/root_bounded_replay_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
