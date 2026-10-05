"""Read-only comparison to the independent pre-load SQLite snapshot."""
import argparse
import json
import sqlite3
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', type=Path, required=True)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--before-report', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    before = json.loads(args.before_report.read_text())
    conn = sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('ATTACH DATABASE ? AS old', (args.baseline.resolve().as_uri() + '?mode=ro',))
    current = {r['name']: {'type': r['type'], 'sql': r['sql']} for r in conn.execute(
        "SELECT name,type,sql FROM main.sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}
    for name, obj in before['schema'].items():
        assert current.get(name) == obj, ('existing_schema_changed', name)
    allowed_additions = {'api_records', 'source_artifacts', 'horse_profile_observations', 'breed_evidence', 'schema_metadata'}
    checks = {}
    for table, count in before['table_counts'].items():
        assert table.isidentifier()
        info = list(conn.execute(f'PRAGMA old.table_info("{table}")'))
        columns = [r['name'] for r in info]
        primary = [r['name'] for r in sorted(info, key=lambda x: x['pk']) if r['pk']]
        assert primary and all(x.isidentifier() for x in columns)
        join = ' AND '.join(f'n."{x}" IS o."{x}"' for x in primary)
        difference = ' OR '.join(f'n."{x}" IS NOT o."{x}"' for x in columns)
        changed = conn.execute(f'SELECT count(*) FROM old."{table}" o LEFT JOIN main."{table}" n ON {join} '
                               f'WHERE n."{primary[0]}" IS NULL OR ({difference})').fetchone()[0]
        assert changed == 0, ('existing_rows_changed_or_deleted', table, changed)
        now = conn.execute(f'SELECT count(*) FROM main."{table}"').fetchone()[0]
        assert now >= count and (table in allowed_additions or now == count), ('unexpected_row_addition', table, count, now)
        checks[table] = {'before': count, 'after': now, 'changed_or_deleted': changed}
    fk = [tuple(r) for r in conn.execute('PRAGMA foreign_key_check')]
    assert not fk, ('foreign_key_violations', fk[:10])
    quick = conn.execute('PRAGMA quick_check').fetchall()
    assert [r[0] for r in quick] == ['ok'], ('quick_check', quick[:10])
    conn.close()
    result = {'all_passed': True, 'database': str(args.db), 'existing_schema_preserved': True,
              'existing_table_rows': checks, 'foreign_key_violations': 0, 'quick_check': 'ok'}
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'all_passed': True, 'existing_tables_verified': len(checks),
                      'added_to_existing': {k: v['after'] - v['before'] for k,v in checks.items() if v['after'] != v['before']}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
