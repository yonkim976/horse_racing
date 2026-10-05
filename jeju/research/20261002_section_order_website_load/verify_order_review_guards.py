"""Exercise correction guards in memory; never mutate the actual SQLite source."""
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
MIGRATION = ROOT / 'jeju/data/schema/migrations/20261002_add_section_order_website_review.sql'


def statements(sql):
    pending = ''
    for line in sql.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            yield pending
            pending = ''
    assert not pending.strip()


def main():
    source = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    cases = json.loads((ROOT / 'jeju/research/20261002_section_remaining_review/positive_order_website_correction_candidates.json').read_text())
    field = {'S1F': 'sjS1fOrd', '1C': 'sj_1cOrd', '2C': 'sj_2cOrd', '3C': 'sj_3cOrd', '4C': 'sj_4cOrd', 'G1F': 'sjG1fOrd'}
    keyed = []
    for case in cases:
        record, = source.execute('''SELECT api_record_id FROM race_result_rows
            WHERE race_date=? AND meet_code=2 AND race_number=? AND horse_number=? AND horse_id=?''',
            (case['date'], case['race_no'], case['program_no'], case['horse_id'])).fetchall()
        keyed.append((record[0], field[case['point']], case['website_order']))
    ids = sorted({r[0] for r in keyed} | {191451})
    marks = ','.join('?' for _ in ids)
    mem = sqlite3.connect(':memory:')
    mem.row_factory = sqlite3.Row
    # Clone only the source rows needed by the fixed correction allowlist.
    for name in ('source_artifacts', 'api_records', 'race_result_rows'):
        mem.execute(source.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0])
    rows = source.execute('SELECT * FROM race_result_rows WHERE api_record_id IN (' + marks + ')', ids).fetchall()
    api = source.execute('SELECT * FROM api_records WHERE api_record_id IN (' + marks + ')', ids).fetchall()
    artifact_ids = sorted({r['source_artifact_id'] for r in api})
    artifacts = source.execute('SELECT * FROM source_artifacts WHERE source_artifact_id IN (' + ','.join('?' for _ in artifact_ids) + ')', artifact_ids).fetchall()
    for table, data in [('source_artifacts', artifacts), ('api_records', api), ('race_result_rows', rows)]:
        mem.executemany('INSERT INTO ' + table + ' VALUES (' + ','.join('?' for _ in data[0]) + ')', [tuple(r) for r in data])
    mem.execute(source.execute("SELECT sql FROM sqlite_master WHERE name='jeju_race_population_candidates'").fetchone()[0])
    # A small stand-in for the already verified time view; only its join key is
    # relevant to these rank guards. Actual time-view immutability is checked separately.
    mem.execute('CREATE VIEW jeju_race_postrace_sections_2026 AS SELECT api_record_id,horse_id FROM jeju_race_population_candidates')
    sql = MIGRATION.read_text()
    for statement in statements(sql):
        mem.execute(statement)
    for record, key, expected in keyed:
        selected = mem.execute('SELECT order_value,order_status FROM jeju_race_section_order_values WHERE api_record_id=? AND field_name=?', (record, key)).fetchone()
        assert tuple(selected) == (None, 'website_review_not_applied'), (record, key, tuple(selected))
    stored = source.execute('SELECT * FROM race_section_order_reviews ORDER BY api_record_id,field_name').fetchall()
    assert len(stored) == 14
    mem.executemany('INSERT INTO race_section_order_reviews VALUES (' + ','.join('?' for _ in stored[0]) + ')', [tuple(r) for r in stored])
    for record, key, expected in keyed:
        selected = mem.execute('SELECT order_value,order_status FROM jeju_race_section_order_values WHERE api_record_id=? AND field_name=?', (record, key)).fetchone()
        assert tuple(selected) == (expected, 'website_corrected')
    changed_id = keyed[0][0]
    mem.execute('UPDATE api_records SET payload_sha256=? WHERE api_record_id=?', ('f' * 64, changed_id))
    changed_fields = [(record, key) for record, key, _ in keyed if record == changed_id]
    for record, key in changed_fields:
        selected = mem.execute('SELECT order_value,order_status FROM jeju_race_section_order_values WHERE api_record_id=? AND field_name=?', (record, key)).fetchone()
        assert tuple(selected) == (None, 'api_source_changed_since_review')
    # Non-review API sentinels must remain unavailable; mutate this isolated copy.
    for value in (0, 99, None, '1', 1.5):
        raw = json.loads(mem.execute('SELECT payload_json FROM api_records WHERE api_record_id=?', (changed_id,)).fetchone()[0])
        raw['sj_2cOrd'] = value
        mem.execute('UPDATE api_records SET payload_json=? WHERE api_record_id=?', (json.dumps(raw), changed_id))
        selected = mem.execute('SELECT order_value FROM jeju_race_section_order_values WHERE api_record_id=? AND field_name=?', (changed_id, 'sj_2cOrd')).fetchone()
        assert selected[0] is None, (value, selected[0])
    result = {'status': 'passed', 'database_modified': False, 'test_database': ':memory:',
              'known_unapplied_fields_blocked': 14, 'applied_website_values_verified': 14,
              'source_changed_review_fields_blocked': len(changed_fields),
              'unavailable_or_invalid_samples_blocked': [0, 99, None, '1', 1.5],
              'migration_sha256': hashlib.sha256(sql.encode()).hexdigest()}
    (OUT / 'guard_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
