"""Read-only guard: production must still equal the frozen pre-load backup."""
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    baseline = json.loads((HERE / 'root_before_load.json').read_text())
    db = Path(baseline['database']).resolve()
    connection = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        schema = {r['name']: {'type': r['type'], 'sql': r['sql']} for r in connection.execute(
            "SELECT name,type,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}
        assert schema == baseline['schema'], 'Production schema changed since backup'
        connection.execute('ATTACH DATABASE ? AS before_snapshot',
                           ((HERE / 'before_load.sqlite3').resolve().as_uri() + '?mode=ro',))
        for table, expected_count in baseline['table_counts'].items():
            assert table.isidentifier()
            count = connection.execute(f'SELECT COUNT(*) FROM main."{table}"').fetchone()[0]
            assert count == expected_count, (table, 'row_count_changed')
            info = list(connection.execute(f'PRAGMA before_snapshot.table_info("{table}")'))
            columns = [r['name'] for r in info]
            primary = [r['name'] for r in sorted(info, key=lambda r: r['pk']) if r['pk']]
            assert primary and all(col.isidentifier() for col in columns)
            join = ' AND '.join(f'n."{col}" IS o."{col}"' for col in primary)
            difference = ' OR '.join(f'n."{col}" IS NOT o."{col}"' for col in columns)
            changed = connection.execute(f'''SELECT COUNT(*) FROM before_snapshot."{table}" o
                LEFT JOIN main."{table}" n ON {join}
                WHERE n."{primary[0]}" IS NULL OR ({difference})''').fetchone()[0]
            assert changed == 0, (table, 'existing_rows_changed', changed)
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
    finally:
        connection.close()
    report = {'status': 'passed', 'database': str(db),
              'existing_table_counts_and_all_rows_match_backup': True,
              'backup_sha256': baseline['backup_sha256']}
    (HERE / 'production_precondition.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
