"""Independently verify the actual quality view and source preservation."""
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
POINTS = {'S1F': 's1f', '1C': 'c1', '2C': 'c2', '3C': 'c3', '4C': 'c4', 'G1F': 'g1f'}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def main():
    baseline = json.loads((OUT / 'root_before_review.json').read_text())
    conflicts = json.loads((OUT.parent / '20261002_section_remaining_review/remaining_website_internal_order_conflicts.json').read_text())
    scope = {(r['date'], int(r['race_no']), int(r['program_no']), r['horse_id'], POINTS[r['point']]) for r in conflicts}
    group_scope = {(r['date'], int(r['race_no']), POINTS[r['point']]) for r in conflicts}
    c = sqlite3.connect((ROOT / 'jeju/data/jeju_native_core.sqlite3').as_uri() + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    h = hashlib.sha256()
    for row in c.execute('SELECT api_record_id,source_artifact_id,record_index,payload_sha256 FROM api_records ORDER BY api_record_id'):
        h.update(json.dumps(tuple(row), separators=(',', ':')).encode() + b'\n')
    require(h.hexdigest() == baseline['api_fingerprint'], 'Source fingerprint changed')
    for name, sql in baseline['protected_schema'].items():
        require(c.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0] == sql, 'Old schema changed')
    for table, key in [('race_section_time_reviews', 'time_reviews'), ('race_section_order_reviews', 'order_reviews')]:
        require([dict(r) for r in c.execute('SELECT * FROM ' + table + ' ORDER BY api_record_id,field_name')] == baseline[key], 'Old reviews changed')
    base = ['api_record_id', 'race_date', 'race_number', 'horse_number', 'horse_id', 'horse_name', 'age_2026', 'finish_position', 'finish_time_seconds']
    times = [short + suffix for short in ('s1f', 'c1', 'c2', 'c3', 'c4', 'g3f', 'g1f') for suffix in ('_time_seconds', '_time_status')]
    ranks = [short + suffix for short in POINTS.values() for suffix in ('_order', '_order_status')]
    columns = base + times + ranks
    old_rows = {r['api_record_id']: r for r in c.execute('SELECT ' + ','.join(columns) + ' FROM jeju_race_postrace_sections_reviewed_2026')}
    new_rows = list(c.execute('SELECT ' + ','.join(columns + [s + suffix for s in POINTS.values() for suffix in ('_group', '_group_status')]) + ' FROM jeju_race_postrace_sections_quality_2026'))
    require(len(new_rows) == len({r['api_record_id'] for r in new_rows}) == len(old_rows) == baseline['candidate_rows'] == 92513, 'View cardinality changed')
    rank_masks = group_runner_masks = website_corrected = 0
    for row in new_rows:
        prior = old_rows[row['api_record_id']]
        require(all(row[col] == prior[col] for col in base + times), 'Non-rank field changed')
        require(row['horse_id'] != '3005648', 'Excluded horse returned')
        for short in POINTS.values():
            affected = (row['race_date'], row['race_number'], row['horse_number'], row['horse_id'], short) in scope
            if affected:
                require(row[short + '_order'] is None and row[short + '_order_status'] == 'unresolved_official_internal_conflict', 'Conflict mask missing')
                rank_masks += 1
            else:
                require(row[short + '_order'] == prior[short + '_order'] and row[short + '_order_status'] == prior[short + '_order_status'], 'Unaffected rank changed')
            if row[short + '_order_status'] == 'website_corrected':
                website_corrected += 1
            if (row['race_date'], row['race_number'], short) in group_scope:
                require(row[short + '_group'] is None and row[short + '_group_status'] == 'unresolved_official_internal_conflict', 'Group mask missing')
                group_runner_masks += 1
    require(rank_masks == 70 and website_corrected == 14, 'Incorrect mask or correction count')
    groups = list(c.execute("SELECT * FROM jeju_race_section_group_quality_values WHERE group_status='unresolved_official_internal_conflict'"))
    require(len(groups) == 20 and all(r['group_value'] is None and r['group_raw'] for r in groups), 'Group source not preserved')
    gu = next(r for r in new_rows if r['api_record_id'] == 191451)
    require(gu['g1f_time_seconds'] is None, 'Guanghae time NULL lost')
    require(c.execute('SELECT count(*) FROM section_internal_conflict_reviews').fetchone()[0] == 90, 'Review count changed')
    require(not c.execute('PRAGMA foreign_key_check(section_internal_conflict_reviews)').fetchall(), 'Foreign key violation')
    result = {'status': 'passed', 'database_opened_read_only': True, 'selected_view': 'jeju_race_postrace_sections_quality_2026', 'selected_rows': 92513, 'unique_runner_rows': 92513, 'masked_order_fields': rank_masks, 'masked_group_points': len(groups), 'group_mask_runner_point_occurrences': group_runner_masks, 'existing_website_rank_corrections_preserved': website_corrected, 'all_other_orders_and_time_fields_preserved': True, 'names_age_finish_results_preserved': True, 'raw_api_fingerprint_and_existing_schema_preserved': True, 'guanghae_g1f_null_preserved': True, 'excluded_horse_not_reintroduced': True, 'review_rows': 90, 'model_input_adoption': False}
    (OUT / 'root_independent_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result))
    c.close()


if __name__ == '__main__':
    main()
