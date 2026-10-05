"""Read-only fingerprints before/after the API42 SQLite append."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
BASELINE = HERE / 'db_before_import.json'


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def fingerprint(conn, table, max_rowid=None):
    sql = 'SELECT rowid,* FROM ' + quote(table)
    params = ()
    if max_rowid is not None:
        sql += ' WHERE rowid <= ?'
        params = (max_rowid,)
    sql += ' ORDER BY rowid'
    digest = hashlib.sha256()
    count = 0
    maximum = 0
    for row in conn.execute(sql, params):
        digest.update(json.dumps(row, ensure_ascii=False, separators=(',', ':')).encode())
        digest.update(b'\n')
        count += 1
        maximum = max(maximum, row[0])
    return {'rows': count, 'max_rowid': maximum, 'sha256': digest.hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    conn = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
    if args.baseline:
        if BASELINE.exists():
            raise ValueError('Baseline already exists; preserve it')
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        result = {
            'database': str(DB.relative_to(ROOT)),
            'tables': {table: fingerprint(conn, table) for table in tables},
            'existing_views': dict(conn.execute("SELECT name,sql FROM sqlite_master WHERE type='view' ORDER BY name")),
        }
        BASELINE.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({table: r['rows'] for table, r in result['tables'].items()}))
    else:
        baseline = json.loads(BASELINE.read_text())
        checks = {}
        for table, old in baseline['tables'].items():
            current = fingerprint(conn, table, old['max_rowid'])
            if current != old:
                raise ValueError('Pre-existing rows changed: ' + table)
            checks[table] = current['rows']
        for name, sql in baseline['existing_views'].items():
            row = conn.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (name,)).fetchone()
            if row is None or row[0] != sql:
                raise ValueError('Pre-existing view changed: ' + name)
        result = {'unchanged_preexisting_rows': checks, 'unchanged_existing_views': list(baseline['existing_views']),
                  'integrity_check': [r[0] for r in conn.execute('PRAGMA integrity_check')],
                  'foreign_key_violations': [list(r) for r in conn.execute('PRAGMA foreign_key_check')]}
        if result['integrity_check'] != ['ok'] or result['foreign_key_violations']:
            raise ValueError('SQLite integrity failed')
        (HERE / 'db_preservation_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False))
    conn.close()


if __name__ == '__main__':
    main()
