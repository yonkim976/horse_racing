#!/usr/bin/env python3
"""Apply approved website time reviews without altering API source records."""
import argparse
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
OUT = ROOT / 'jeju/research/20261002_section_passing_audit/website_time_check'
EVIDENCE = OUT / 'evidence.json'
MIGRATION = ROOT / 'jeju/data/schema/migrations/20261002_add_section_time_website_review.sql'
EXPECTED = {
    ('2024-03-02', 3, 9, '3018048', 'jeS1fTime'): (120, 20.0),
    ('2025-10-17', 7, 8, '3017473', 'jeS1fTime'): (77.8, 17.8),
    ('2026-01-17', 5, 8, '3016494', 'jeG1fTime'): (77.2, None),
    ('2026-03-06', 8, 6, '3018729', 'jeG1fTime'): (76, 16.0),
}
VIEWS = ('jeju_race_section_time_values', 'jeju_race_section_times', 'jeju_race_postrace_sections_2026')


def statements(sql):
    pending = ''
    for line in sql.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            yield pending
            pending = ''
    if pending.strip():
        raise RuntimeError('Incomplete migration SQL')


def raw_fingerprint(c):
    h = hashlib.sha256()
    for r in c.execute('SELECT api_record_id,source_artifact_id,record_index,payload_sha256 FROM api_records ORDER BY api_record_id'):
        h.update(json.dumps(tuple(r), separators=(',', ':')).encode())
        h.update(b'\n')
    return h.hexdigest()


def check_existing_objects(c, sql):
    """Reject stale IF NOT EXISTS objects rather than silently accepting them."""
    def normalized(value):
        value = re.sub(r'\bIF\s+NOT\s+EXISTS\b', '', value, flags=re.I)
        return re.sub(r'\s+', ' ', value).strip().rstrip(';').casefold()
    names = set()
    for statement in statements(sql):
        match = re.search(r'CREATE\s+(TABLE|VIEW)\s+IF\s+NOT\s+EXISTS\s+(\w+)', statement, re.I)
        if not match:
            raise RuntimeError('Unexpected migration statement')
        kind, name = match.groups()
        if name not in (*VIEWS, 'race_section_time_reviews'):
            raise RuntimeError('Unexpected migration object')
        names.add(name)
        row = c.execute('SELECT type,sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
        # Exclude the leading SQL comments from the expected CREATE definition.
        definition = statement[match.start():]
        if row and (row['type'] != kind.lower() or normalized(row['sql']) != normalized(definition)):
            raise RuntimeError('Existing object differs from migration: '+name)
    if names != set((*VIEWS, 'race_section_time_reviews')):
        raise RuntimeError('Migration object set does not match the approved scope')


def evidence_rows(c, evidence, evidence_sha, applied_at):
    if len(evidence['cases']) != 4:
        raise RuntimeError('Expected exactly four approved cases')
    result = []
    seen = set()
    for case in evidence['cases']:
        key = (case['date'], case['race_no'], case['program_no'], case['horse_id'], case['api_field'])
        if key not in EXPECTED or key in seen:
            raise RuntimeError('Unexpected or duplicate case key')
        seen.add(key)
        raw_expected, effective = EXPECTED[key]
        rows = c.execute('''SELECT r.api_record_id, r.horse_name, r.finish_position,
                                   a.payload_json, a.payload_sha256
                            FROM jeju_race_population_candidates r
                            JOIN api_records a USING(api_record_id)
                            WHERE r.race_date=? AND r.meet_code=2 AND r.race_number=?
                              AND r.horse_number=? AND r.horse_id=?''', key[:4]).fetchall()
        if len(rows) != 1:
            raise RuntimeError('Website case does not match exactly one candidate row')
        row = rows[0]
        raw = json.loads(row['payload_json'])
        cells = case['website_time_cells']
        idx = 3 if case['api_field'] == 'jeS1fTime' else 9
        minutes, seconds = cells[idx].split(':')
        website_seconds = int(minutes) * 60 + float(seconds)
        if (raw[case['api_field']] != raw_expected or case['api_seconds'] != raw_expected
                or row['horse_name'] != case['horse_name_raw']
                or int(cells[0]) != row['finish_position'] or int(cells[1]) != key[2]
                or website_seconds != case['website_seconds']
                or case['website_display'] != cells[idx]):
            raise RuntimeError('API/website identification or observed values changed')
        if hashlib.sha256(row['payload_json'].encode()).hexdigest() != row['payload_sha256']:
            raise RuntimeError('Original API payload hash mismatch')
        if effective is not None and website_seconds != effective:
            raise RuntimeError('Correction is not the observed website value')
        if effective is None and not website_seconds > float(raw['jeG3fTime']):
            raise RuntimeError('Unresolved G1F no longer matches the anomaly')
        status = 'website_corrected' if effective is not None else 'unresolved_official_website_anomaly'
        reason = ('User approved official website value on 2026-10-02; preserve API original.'
                  if effective is not None else
                  'Website also shows 1:17.2; G1F exceeds G3F. Preserve observations; effective value NULL, no inferred 17.2.')
        result.append((row['api_record_id'], key[4], status, raw_expected, row['payload_sha256'],
                       case['website_display'], website_seconds, effective, case['url'],
                       evidence['checked_date_kst'], EVIDENCE.relative_to(ROOT).as_posix(),
                       evidence_sha, reason, applied_at))
    return result


def verify(c, expected_rows, before_count, before_raw):
    stored = c.execute('SELECT * FROM race_section_time_reviews ORDER BY api_record_id,field_name').fetchall()
    if len(stored) != 4:
        raise RuntimeError('Review table must contain exactly these four cases')
    by_key = {(r['api_record_id'], r['field_name']): tuple(r) for r in stored}
    for expected in expected_rows:
        if by_key[expected[:2]][:-1] != expected[:-1]:
            raise RuntimeError('Existing review differs from approved evidence')
    count, unique_count = c.execute('''SELECT count(*),count(DISTINCT api_record_id)
                                      FROM jeju_race_postrace_sections_2026''').fetchone()
    if count != before_count or unique_count != before_count:
        raise RuntimeError('Postrace join changed runner cardinality')
    if raw_fingerprint(c) != before_raw:
        raise RuntimeError('API record fingerprint changed')
    ids = [x[0] for x in expected_rows]
    marks = ','.join('?' for _ in ids)
    # Placeholder count comes only from the fixed four-case allowlist.
    values = [dict(r) for r in c.execute('''SELECT api_record_id,race_date,race_number,
                    horse_id,horse_name,historical_horse_name_raw,age_2026,
                    s1f_time_seconds,s1f_time_status,g1f_time_seconds,g1f_time_status,
                    section_time_website_correction_count,section_time_review_required_count
                    FROM jeju_race_postrace_sections_2026 WHERE api_record_id IN (''' + marks + ')', ids)]
    actual = {r['api_record_id']: r for r in values}
    for record_id, field, status, _, _, _, _, effective, *_ in expected_rows:
        column = 's1f' if field == 'jeS1fTime' else 'g1f'
        if (actual[record_id][column+'_time_seconds'] != effective
                or actual[record_id][column+'_time_status'] != status):
            raise RuntimeError('Postrace value/status does not match approved review')
    fk = c.execute('PRAGMA foreign_key_check(race_section_time_reviews)').fetchall()
    if fk:
        raise RuntimeError('Review foreign key violation')
    return {'postrace_rows': count, 'unique_runner_rows': unique_count,
            'review_rows': 4, 'website_corrected_fields': 3, 'unresolved_fields_null': 1,
            'api_record_fingerprint_unchanged': True, 'case_values': values}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    evidence_bytes = EVIDENCE.read_bytes()
    evidence = json.loads(evidence_bytes)
    evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()
    sql = MIGRATION.read_text()
    applied_at = datetime.now(UTC).isoformat(timespec='seconds')
    if not DB.is_file():
        raise RuntimeError('Existing local DB is required; refusing to create an empty DB')
    c = sqlite3.connect(DB if args.apply else DB.as_uri()+'?mode=ro', uri=not args.apply, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    if args.apply:
        c.execute('BEGIN IMMEDIATE')
    committed = False
    try:
        check_existing_objects(c, sql)
        count = c.execute('SELECT count(*) FROM jeju_race_analysis_2026').fetchone()[0]
        raw_before = raw_fingerprint(c)
        default_view = c.execute("SELECT sql FROM sqlite_master WHERE name='jeju_race_analysis_2026'").fetchone()[0]
        rows = evidence_rows(c, evidence, evidence_sha, applied_at)
        if not args.apply:
            print(json.dumps({'ready': True, 'matched_cases': len(rows), 'base_analysis_rows': count}, ensure_ascii=False))
            return
        baseline_path = OUT / 'before_application.json'
        if not baseline_path.exists():
            baseline_path.write_text(json.dumps({'default_analysis_view_sql': default_view,
                'base_analysis_rows': count, 'api_record_fingerprint': raw_before,
                'rollback': 'Remove only the three new views and race_section_time_reviews; no original source values were updated.'}, ensure_ascii=False, indent=2)+'\n')
        elif json.loads(baseline_path.read_text())['default_analysis_view_sql'] != default_view:
            raise RuntimeError('Saved baseline does not match the unchanged default view')
        for statement in statements(sql):
            c.execute(statement)
        c.executemany('INSERT OR IGNORE INTO race_section_time_reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
        verified = verify(c, rows, count, raw_before)
        current_view = c.execute("SELECT sql FROM sqlite_master WHERE name='jeju_race_analysis_2026'").fetchone()[0]
        if current_view != default_view:
            raise RuntimeError('Original analysis view was changed')
        c.commit()
        committed = True
        manifest = {'status': 'applied_and_verified', 'database': DB.relative_to(ROOT).as_posix(),
                    'database_modified': True, 'api_source_values_modified': False,
                    'default_analysis_view_unchanged': True, 'existing_model_input_adoption': False,
                    'postrace_view': 'jeju_race_postrace_sections_2026',
                    'evidence_sha256': evidence_sha, 'migration_sha256': hashlib.sha256(sql.encode()).hexdigest(),
                    'verified_at_utc': applied_at, **verified}
        manifest_tmp = OUT / 'application_manifest.tmp'
        manifest_tmp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        manifest_tmp.replace(OUT / 'application_manifest.json')
        print(json.dumps(manifest,ensure_ascii=False,indent=2))
    except BaseException as exc:
        if committed:
            raise RuntimeError('DB committed and verified; manifest recording failed. Rerun --apply to recover the receipt.') from exc
        if args.apply:
            c.rollback()
        raise
    finally:
        c.close()


if __name__ == '__main__':
    main()
