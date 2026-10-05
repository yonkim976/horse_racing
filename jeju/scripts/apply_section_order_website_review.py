"""Reattach the 14 approved website rank reviews; dry run unless --apply."""
import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'jeju/research/20261002_section_order_website_load'
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
MIGRATION = ROOT / 'jeju/data/schema/migrations/20261002_add_section_order_website_review.sql'
PINS = {
    'root_fresh_website_verification.json': '594616cab762e7bba530f684f7d461f83956a968ce3445f946dd978e7796806e',
    'fresh_website/evidence.json': '66248b10e549649ddb281cca8e753e6d9249d8eb0cd769b7155e4798744ee965',
}
OBJECTS = {'race_section_order_reviews', 'jeju_race_section_order_values',
           'jeju_race_section_orders', 'jeju_race_postrace_sections_reviewed_2026'}
FIELDS = {'S1F': ('sjS1fOrd', 's1f_order'), 'G1F': ('sjG1fOrd', 'g1f_order')}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def fingerprint(c):
    h = hashlib.sha256()
    for row in c.execute('SELECT api_record_id,source_artifact_id,record_index,payload_sha256 FROM api_records ORDER BY api_record_id'):
        h.update(json.dumps(tuple(row), separators=(',', ':')).encode() + b'\n')
    return h.hexdigest()


def statements(sql):
    pending = ''
    for line in sql.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            yield pending
            pending = ''
    require(not pending.strip(), 'Incomplete migration')


def normalized(sql):
    sql = re.sub(r'\bIF\s+NOT\s+EXISTS\b', '', sql, flags=re.I)
    return re.sub(r'\s+', ' ', sql).strip().rstrip(';').casefold()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    pinned = {}
    for name, sha in PINS.items():
        data = (OUT / name).read_bytes()
        require(hashlib.sha256(data).hexdigest() == sha, 'Changed evidence: ' + name)
        pinned[name] = json.loads(data)
    proof = pinned['root_fresh_website_verification.json']
    pages = pinned['fresh_website/evidence.json']
    require(len(proof['rank_fields']) == 14, 'Expected 14 approved fields')
    for page in pages:
        path = (OUT / 'fresh_website' / page['raw_path']).resolve()
        require(path.is_relative_to((OUT / 'fresh_website').resolve()), 'Invalid evidence path')
        data = path.read_bytes()
        require(len(data) == page['bytes'] and hashlib.sha256(data).hexdigest() == page['sha256'], 'Changed website HTML')
        require(page['http_status'] == 200, 'Unsuccessful website response')
    sql = MIGRATION.read_text()
    require(hashlib.sha256(MIGRATION.read_bytes()).hexdigest() == '3f473b4aa106b463e9859ccdda73224f6c860c345359d2d3a8086895bc5c3a7c', 'Changed migration')
    source = sqlite3.connect(DB.as_uri() + '?mode=rw', uri=True)
    source.row_factory = sqlite3.Row
    if args.apply:
        c = source
    else:
        c = sqlite3.connect(':memory:')
        source.backup(c)
        source.close()
        c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    before = fingerprint(c)
    protected = list(c.execute("SELECT name,sql FROM sqlite_master WHERE type='view' AND name NOT IN (?,?,?) ORDER BY name", tuple(sorted(OBJECTS - {'race_section_order_reviews'}))))
    time_reviews = list(c.execute('SELECT * FROM race_section_time_reviews ORDER BY api_record_id,field_name'))
    candidate_count = c.execute('SELECT count(*) FROM jeju_race_population_candidates').fetchone()[0]
    c.execute('BEGIN IMMEDIATE')
    try:
        names = set()
        for statement in statements(sql):
            match = re.search(r'CREATE\s+(TABLE|VIEW)\s+IF\s+NOT\s+EXISTS\s+(\w+)', statement, re.I)
            require(match is not None, 'Unexpected SQL')
            kind, name = match.groups()
            require(name in OBJECTS and name not in names, 'Unexpected object')
            names.add(name)
            existing = c.execute('SELECT type,sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
            if existing:
                require(existing[0] == kind.lower() and normalized(existing[1]) == normalized(statement[match.start():]), 'Existing object differs: ' + name)
            c.execute(statement)
        require(names == OBJECTS, 'Incomplete object set')
        seen = set()
        now = datetime.now(timezone.utc).isoformat()
        for case in proof['rank_fields']:
            field, col = FIELDS[case['point']]
            key = (case['date'], case['race_no'], case['program_no'], case['horse_id'])
            require((*key, field) not in seen, 'Duplicate review')
            seen.add((*key, field))
            rows = c.execute('SELECT r.api_record_id,a.payload_json,a.payload_sha256 FROM jeju_race_population_candidates r JOIN api_records a USING(api_record_id) WHERE r.race_date=? AND r.meet_code=2 AND r.race_number=? AND r.horse_number=? AND r.horse_id=?', key).fetchall()
            require(len(rows) == 1, 'Candidate identity mismatch')
            row = rows[0]
            require(hashlib.sha256(row['payload_json'].encode()).hexdigest() == row['payload_sha256'], 'API payload hash mismatch')
            require(json.loads(row['payload_json'])[field] == case['api_order'], 'API value changed')
            require(case['fresh_website_order'] == case['website_order'] and case['fresh_horse_id'] == case['horse_id'], 'Website identity mismatch')
            values = (row['api_record_id'], field, 'website_corrected', case['api_order'], row['payload_sha256'], case['website_order'], case['website_order'], case['fresh_website_url'], '2026-10-02', 'jeju/research/20261002_section_order_website_load/fresh_website/evidence.json', PINS['fresh_website/evidence.json'], 'User approved official website rank correction; API original preserved.', now)
            existing = c.execute('SELECT * FROM race_section_order_reviews WHERE api_record_id=? AND field_name=?', values[:2]).fetchone()
            if existing:
                require(tuple(existing)[:12] == values[:12], 'Existing review differs')
            else:
                c.execute('INSERT INTO race_section_order_reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', values)
        selected_rows = c.execute('SELECT api_record_id,s1f_order,s1f_order_status,g1f_order,g1f_order_status,g1f_time_seconds,g1f_time_status FROM jeju_race_postrace_sections_reviewed_2026').fetchall()
        selected = {r['api_record_id']: r for r in selected_rows}
        require(len(selected_rows) == len(selected) == candidate_count == 92513, 'Candidate cardinality changed')
        for case in proof['rank_fields']:
            field, col = FIELDS[case['point']]
            row = c.execute('SELECT api_record_id FROM jeju_race_population_candidates WHERE race_date=? AND meet_code=2 AND race_number=? AND horse_number=? AND horse_id=?', (case['date'], case['race_no'], case['program_no'], case['horse_id'])).fetchone()
            require(selected[row[0]][col] == case['website_order'] and selected[row[0]][col + '_status'] == 'website_corrected', 'Selected order mismatch')
        require(selected[191451]['g1f_time_seconds'] is None and selected[191451]['g1f_time_status'] == 'unresolved_official_website_anomaly', 'Guanghae G1F NULL changed')
        require(not c.execute('PRAGMA foreign_key_check(race_section_order_reviews)').fetchall(), 'Foreign key violation')
        require(fingerprint(c) == before, 'Raw source fingerprint changed')
        require([tuple(r) for r in protected] == [tuple(r) for r in c.execute("SELECT name,sql FROM sqlite_master WHERE type='view' AND name NOT IN (?,?,?) ORDER BY name", tuple(sorted(OBJECTS - {'race_section_order_reviews'})))], 'Protected view changed')
        require([tuple(r) for r in time_reviews] == [tuple(r) for r in c.execute('SELECT * FROM race_section_time_reviews ORDER BY api_record_id,field_name')], 'Time review changed')
        if args.apply:
            c.commit()
        else:
            c.rollback()
        print(json.dumps({'status': 'passed', 'mode': 'apply' if args.apply else 'dry_run_memory_copy', 'review_fields': 14, 'source_values_modified': False, 'candidate_rows': candidate_count}))
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


if __name__ == '__main__':
    main()
