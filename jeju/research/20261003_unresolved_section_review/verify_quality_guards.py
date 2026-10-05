"""Exercise the new overlay on a small in-memory copy of the audited races."""
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone

import build_quality_review as review


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def copy_table(c, name, rows):
    require(rows and re.fullmatch(r'[a-zA-Z0-9_]+', name), 'Invalid memory table')
    names = rows[0].keys()
    require(all(re.fullmatch(r'[a-zA-Z0-9_]+', n) for n in names), 'Invalid memory column')
    c.execute('CREATE TABLE ' + name + '(' + ','.join(names) + ')')
    c.executemany('INSERT INTO ' + name + ' VALUES (' + ','.join('?' for n in names) + ')', [tuple(r) for r in rows])


def main():
    source = sqlite3.connect(review.DB.as_uri() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    sql, records = review.prepare(source)
    cases = json.loads(review.SOURCE.read_text())
    dates = sorted({r['date'] for r in cases} | {'2025-10-17', '2026-03-06'})
    marks = ','.join('?' for d in dates)
    orders = list(source.execute('SELECT * FROM jeju_race_section_order_values WHERE race_date IN (' + marks + ')', dates))
    # Read the joined wide view once. Repeated per-runner queries would rescan its aggregate sources.
    wide = list(source.execute('SELECT * FROM jeju_race_postrace_sections_reviewed_2026 WHERE race_date IN (' + marks + ')', dates))
    groups = list(source.execute('SELECT * FROM api303_corner_rank_rows WHERE race_date IN (' + marks + ')', dates))
    ids = sorted({r['api_record_id'] for r in groups})
    placeholders = ','.join('?' for x in ids)
    api = list(source.execute('SELECT api_record_id,source_artifact_id,payload_json,payload_sha256 FROM api_records WHERE api_record_id IN (' + placeholders + ')', ids))
    artifacts = sorted({r['source_artifact_id'] for r in api})
    pages = list(source.execute('SELECT source_artifact_id,raw_relative_path,sha256 FROM source_artifacts WHERE source_artifact_id IN (' + ','.join('?' for a in artifacts) + ')', artifacts))
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    for name, rows in [('jeju_race_section_order_values', orders), ('jeju_race_postrace_sections_reviewed_2026', wide), ('api303_corner_rank_rows', groups), ('api_records', api), ('source_artifacts', pages)]:
        copy_table(c, name, rows)
    c.executescript(sql)
    require(c.execute("SELECT count(*) FROM jeju_race_section_order_quality_values WHERE quality_order_status='internal_conflict_review_not_applied' AND quality_order_value IS NULL").fetchone()[0] == 70, 'Missing rank review guard')
    require(c.execute("SELECT count(*) FROM jeju_race_section_group_quality_values WHERE group_status='internal_conflict_review_not_applied' AND group_value IS NULL").fetchone()[0] == 20, 'Missing group review guard')
    now = datetime.now(timezone.utc).isoformat()
    for record in records:
        c.execute('INSERT INTO section_internal_conflict_reviews VALUES (?,?,?,?,?,?,?,?,?,?)', (*record, 'unresolved_official_internal_conflict', 'guard_fixture', '0' * 64, now))
    selected = list(c.execute('SELECT api_record_id,s1f_order,s1f_order_status,c1_order,c1_order_status,c2_order,c2_order_status,c3_order,c3_order_status,c4_order,c4_order_status,g1f_order,g1f_order_status,g1f_time_seconds,g1f_time_status FROM jeju_race_postrace_sections_quality_2026'))
    require(len(selected) == len({r['api_record_id'] for r in selected}) == len(wide), 'Memory view cardinality')
    old = {r['api_record_id']: r for r in wide}
    masked = 0
    corrected = 0
    for row in selected:
        for _, _, short in review.MAP.values():
            if row[short + '_order_status'] == 'unresolved_official_internal_conflict':
                require(row[short + '_order'] is None, 'Unresolved order must be NULL')
                masked += 1
            else:
                require(row[short + '_order'] == old[row['api_record_id']][short + '_order'], 'Unaffected order changed')
            if row[short + '_order_status'] == 'website_corrected':
                corrected += 1
        require(row['g1f_time_seconds'] == old[row['api_record_id']]['g1f_time_seconds'], 'Time value changed')
    require(masked == 70 and corrected == 14, 'Rank scope or previous correction changed')
    gu = next(r for r in selected if r['api_record_id'] == 191451)
    require(gu['g1f_time_seconds'] is None and gu['g1f_time_status'] == 'unresolved_official_website_anomaly', 'Guanghae NULL changed')
    require(c.execute("SELECT count(*) FROM jeju_race_section_group_quality_values WHERE group_status='unresolved_official_internal_conflict' AND group_value IS NULL").fetchone()[0] == 20, 'Group mask scope')
    rank = next(r for r in records if r[2] == 'individual_order')
    group = next(r for r in records if r[2] == 'group')
    c.execute('UPDATE jeju_race_section_order_values SET api_payload_sha256=? WHERE api_record_id=? AND field_name=?', ('0' * 64, *rank[:2]))
    changed = c.execute('SELECT quality_order_value,quality_order_status FROM jeju_race_section_order_quality_values WHERE api_record_id=? AND field_name=?', rank[:2]).fetchone()
    require(tuple(changed) == (None, 'api_source_changed_since_conflict_review'), 'Changed rank source guard')
    c.execute('UPDATE api_records SET payload_sha256=? WHERE api_record_id=?', ('0' * 64, group[0]))
    changed = c.execute('SELECT group_value,group_status FROM jeju_race_section_group_quality_values WHERE api_record_id=? AND field_name=?', group[:2]).fetchone()
    require(tuple(changed) == (None, 'api_source_changed_since_conflict_review'), 'Changed group source guard')
    report = {'status': 'passed', 'actual_database_modified': False, 'memory_runner_rows': len(wide), 'missing_review_rank_fields_null': 70, 'missing_review_group_points_null': 20, 'applied_unresolved_rank_fields_null': 70, 'applied_unresolved_group_points_null': 20, 'existing_website_rank_corrections_preserved': 14, 'guanghae_time_null_preserved': True, 'unaffected_orders_and_g1f_times_preserved': True, 'changed_rank_source_guard': True, 'changed_group_source_guard': True, 'migration_sha256': hashlib.sha256(sql.encode()).hexdigest()}
    (review.OUT / 'guard_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report))
    source.close()
    c.close()


if __name__ == '__main__':
    main()
