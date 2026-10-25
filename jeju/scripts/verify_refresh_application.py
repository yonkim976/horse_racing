"""Read-only audit of a completed Jeju refresh against its before-image.

Checks every pre-existing row/column and schema definition, official page SHA,
pagination, manifest pair and the known section reviews. No network or DB writes.
The only output is a new audit JSON in the selected domain run directory.
"""
from pathlib import Path
from collections import Counter
from datetime import datetime, UTC
import argparse
import fcntl
import hashlib
import json
import sqlite3


ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / 'jeju/research/20261017_core_refresh'
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4194304), b''):
            digest.update(block)
    return digest.hexdigest()


def local_path(relative):
    path = (ROOT / relative).resolve()
    path.relative_to((ROOT / 'jeju').resolve())
    return path


def quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def verify(directory, expected_before=None):
    directory = directory.resolve()
    directory.relative_to((HOME / 'runs').resolve())
    output = directory / 'independent_application_verification.json'
    require(not output.exists(), 'Audit already exists; preserve it')
    with (HOME / 'refresh.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt_path = directory / 'application_manifest.json'
        receipt = json.loads(receipt_path.read_text())
        require(receipt['status'] == 'applied_verified', 'Refresh not applied')
        require(receipt['idempotent_replay'], 'Missing replay check')
        require(not receipt['source_failures'], 'Source failures remain')
        require(all(v.get('failed', 0) == 0 for v in receipt['source_family_coverage'].values()), 'Failed source partitions')
        require(receipt['starting_training_website_status'] == 'complete', 'Website collection incomplete')
        sidecar = json.loads((ROOT / 'jeju/data/jeju_native_core.refresh_manifest.json').read_text())
        require(sidecar['latest_run_id'] == receipt['run_id'], 'A different run is current')
        require(local_path(sidecar['application_manifest']) == receipt_path, 'Receipt pointer mismatch')
        require(sidecar['sha256'] == sha(receipt_path), 'Receipt SHA mismatch')
        db_sha = sha(DB)
        require(db_sha == receipt['database_sha256_after'] == sidecar['database_sha256'], 'DB SHA mismatch')
        backup = HOME / 'rolling_backups' / receipt['run_id'] / DB.name
        require(sha(backup) == receipt['backup_pair']['db_sha256'], 'Backup SHA mismatch')
        if expected_before:
            require(receipt['backup_pair']['source_database_sha256'] == expected_before, 'Unexpected before-image')

        source_path = local_path(receipt['source_manifest'])
        require(sha(source_path) == receipt['source_manifest_sha256'], 'Source manifest SHA mismatch')
        source = json.loads(source_path.read_text())
        families = Counter()
        for page in source['pages']:
            path = local_path(page['path'])
            require(sha(path) == page['sha256'], 'Raw page SHA mismatch')
            require(page['pagination_complete'] and page['http_status'] == 200, 'Incomplete API page')
            doc = json.loads(path.read_text())
            require(str(doc['response']['header']['resultCode']) == '00', 'Official API error')
            body = doc['response']['body']
            rows = (body.get('items') or {}).get('item') or []
            if isinstance(rows, dict):
                rows = [rows]
            require(len(rows) == page['row_count'], 'Raw item count mismatch')
            require(int(body['totalCount']) == int(page['total_count']), 'Total count mismatch')
            families[page['family']] += 1
        for operation in source['operations']:
            if operation['family'] == 'horse_profile':
                require(operation['status'] == 'complete_selected_slice', 'Profile slice failed')
                require(operation['requested_id_count'] + operation['cache_reused_id_count'] == operation['selected_id_count'], 'Profile selection incomplete')
            else:
                require(operation['actual_page_count'] == operation['expected_page_count'], 'Operation pagination incomplete')

        website_path = local_path(receipt['website_manifest'])
        website = json.loads(website_path.read_text())
        website_pages = 0
        for item in website['dates']:
            require(item['method'] == 'POST', 'Website method changed')
            if item.get('html_path'):
                path = (website_path.parent / item['html_path']).resolve()
                path.relative_to(website_path.parent.resolve())
                require(sha(path) == item['html_sha256'], 'Website SHA mismatch')
                website_pages += 1

        connection = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('ATTACH DATABASE ? AS frozen', (backup.as_uri() + '?mode=ro',))
            connection.execute('PRAGMA query_only=ON')
            before_schema = list(connection.execute('SELECT type,name,tbl_name,sql FROM frozen.sqlite_master'))
            now_schema = {r[1]: tuple(r) for r in connection.execute('SELECT type,name,tbl_name,sql FROM main.sqlite_master')}
            require(all(now_schema.get(row[1]) == tuple(row) for row in before_schema), 'Existing schema changed')
            tables = {}
            names = connection.execute("SELECT name FROM frozen.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
            for (table,) in names:
                columns = [r[1] for r in connection.execute('PRAGMA frozen.table_info(' + quote(table) + ')')]
                diff = ' OR '.join('b.' + quote(k) + ' IS NOT m.' + quote(k) for k in columns)
                bad = connection.execute('SELECT count(*) FROM frozen.' + quote(table) + ' b LEFT JOIN main.' + quote(table) + ' m ON b.rowid=m.rowid WHERE m.rowid IS NULL OR ' + diff).fetchone()[0]
                require(bad == 0, 'Pre-existing data changed: ' + table)
                counts = [connection.execute('SELECT count(*) FROM ' + schema + '.' + quote(table)).fetchone()[0] for schema in ('frozen', 'main')]
                tables[table] = {'before': counts[0], 'after': counts[1], 'all_existing_columns_unchanged': True}
                print(table, counts[0], counts[1], 'preserved', flush=True)
            excluded = {table: connection.execute('SELECT count(*) FROM ' + table + ' WHERE horse_id=?', ('3005648',)).fetchone()[0]
                        for table in ('race_result_rows', 'running_trial_rows', 'daily_training_api_rows', 'medical_api_rows', 'starting_exam_api_rows', 'horse_profile_observations')}
            require(not any(excluded.values()), 'Excluded horse returned')
            grid = [dict(r) for r in connection.execute("SELECT furlong_index,distance_m,distance_status FROM api6_section_points_current WHERE race_date='2026-10-17' AND meet_code=2 AND race_number=5 ORDER BY furlong_index")]
            require([r['distance_m'] for r in grid] == [110, 310, 510, 710, 910, 1110], 'R5 reviewed grid changed')
            require(all(r['distance_status'] == 'website_corrected' for r in grid), 'R5 review bypassed')
            require(connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'DB integrity failed')
            require(not connection.execute('PRAGMA foreign_key_check').fetchall(), 'Foreign key error')
        finally:
            connection.close()
        require(sha(DB) == db_sha, 'DB changed during verification')
        report = {'passed': True, 'run_id': receipt['run_id'], 'database_sha256': db_sha,
                  'requested_range': source['requested_range'], 'source_failures': [],
                  'raw_api_pages_verified': dict(families), 'website_pages_verified': website_pages,
                  'all_operation_pagination_verified': True, 'manifest_pair_verified': True,
                  'existing_schema_preserved': True, 'tables_checked': len(tables), 'tables': tables,
                  'rows_preserved': sum(v['before'] for v in tables.values()),
                  'excluded_horse_rows': excluded, 'oct17_r5_reviewed_grid': grid,
                  'integrity_check': 'ok', 'foreign_key_violations': 0, 'idempotent_replay_verified': True,
                  'current_views': receipt['checks']['current_views'],
                  'website_holds': receipt['summary']['starting_training_website']['held_dates'],
                  'completed_at_utc': datetime.now(UTC).isoformat()}
        with output.open('x') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({k: v for k, v in report.items() if k not in ('tables', 'current_views')}, ensure_ascii=False))
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--expected-before-sha256')
    arguments = parser.parse_args()
    verify(arguments.run, arguments.expected_before_sha256)
