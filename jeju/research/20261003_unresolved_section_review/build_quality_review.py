"""Prepare a reversible quality overlay for officially conflicting section fields.

No source fields or existing views are updated. Applying requires --apply.
"""
import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = OUT.parent / '20261002_section_remaining_review/remaining_website_internal_order_conflicts.json'
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
MIGRATION = ROOT / 'jeju/data/schema/migrations/20261003_add_section_internal_conflict_quality.sql'
MAP = {'S1F': ('sjS1fOrd', 'corner_7', 's1f'), '1C': ('sj_1cOrd', 'corner_1', 'c1'),
       '2C': ('sj_2cOrd', 'corner_2', 'c2'), '3C': ('sj_3cOrd', 'corner_3', 'c3'),
       '4C': ('sj_4cOrd', 'corner_4', 'c4'), 'G1F': ('sjG1fOrd', 'corner_8', 'g1f')}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def literal(value):
    if type(value) is int:
        return str(value)
    require(isinstance(value, str), 'Invalid SQL literal')
    return "'" + value.replace("'", "''") + "'"


def values(rows):
    return ',\n    '.join('(' + ','.join(literal(v) for v in r) + ')' for r in rows)


def statements(sql):
    pending = ''
    for line in sql.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            yield pending
            pending = ''
    require(not pending.strip(), 'Incomplete SQL')


def norm(sql):
    return re.sub(r'\s+', ' ', re.sub(r'\bIF\s+NOT\s+EXISTS\b', '', sql, flags=re.I)).strip().rstrip(';').casefold()


def fingerprint(c):
    h = hashlib.sha256()
    for r in c.execute('SELECT api_record_id,source_artifact_id,record_index,payload_sha256 FROM api_records ORDER BY api_record_id'):
        h.update(json.dumps(tuple(r), separators=(',', ':')).encode() + b'\n')
    return h.hexdigest()


def prepare(c):
    cases = json.loads(SOURCE.read_text())
    require(len(cases) == 70, 'Expected original 70 conflicts')
    scope, groups, records = [], {}, []
    for x in cases:
        date, race, num, horse, point = x['date'], int(x['race_no']), int(x['program_no']), x['horse_id'], x['point']
        require(re.fullmatch(r'\d{4}-\d{2}-\d{2}', date) and re.fullmatch(r'\d{7}', horse) and point in MAP, 'Invalid conflict key')
        field, group_field, short = MAP[point]
        key = (date, 2, race, num, horse, field)
        require(key not in scope, 'Repeated conflict')
        scope.append(key)
        found = c.execute('SELECT r.api_record_id,a.payload_json,a.payload_sha256 FROM jeju_race_population_candidates r JOIN api_records a USING(api_record_id) WHERE r.race_date=? AND r.meet_code=2 AND r.race_number=? AND r.horse_number=? AND r.horse_id=?', (date, race, num, horse)).fetchall()
        require(len(found) == 1, 'Ambiguous runner key')
        r = found[0]
        raw = json.loads(r['payload_json'])[field]
        require(raw == int(x['api4_order']) and hashlib.sha256(r['payload_json'].encode()).hexdigest() == r['payload_sha256'], 'Changed API order source')
        url = f'https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet=2&realRcDate={date.replace("-", "")}&realRcNo={race}'
        records.append((r['api_record_id'], field, 'individual_order', json.dumps(raw, ensure_ascii=False), r['payload_sha256'], url))
        gkey = (date, 2, race, point)
        if gkey not in groups:
            rows = c.execute('SELECT r.api_record_id,a.payload_json,a.payload_sha256 FROM api303_corner_rank_rows r JOIN api_records a USING(api_record_id) WHERE r.race_date=? AND r.meet_code=2 AND r.race_number=?', (date, race)).fetchall()
            require(len(rows) == 1, 'Ambiguous group source')
            gr = rows[0]
            value = json.loads(gr['payload_json'])[group_field]
            require(re.sub(r'\s+', '', value) == re.sub(r'\s+', '', x['website_group_raw']), 'Group source changed')
            require(hashlib.sha256(gr['payload_json'].encode()).hexdigest() == gr['payload_sha256'], 'Changed group payload')
            groups[gkey] = (gr['api_record_id'], group_field, 'group', json.dumps(value, ensure_ascii=False), gr['payload_sha256'], url)
    require(len(groups) == 20 and len({k[:3] for k in groups}) == 19, 'Unexpected point scope')
    records += list(groups.values())
    sql = '''-- Official sources disagree internally; preserve raw data and mask only audited fields.
CREATE TABLE IF NOT EXISTS section_internal_conflict_reviews (
    api_record_id INTEGER NOT NULL REFERENCES api_records(api_record_id),
    field_name TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('individual_order','group')),
    raw_value_json_at_review TEXT NOT NULL CHECK(json_valid(raw_value_json_at_review)),
    api_payload_sha256_at_review TEXT NOT NULL CHECK(length(api_payload_sha256_at_review)=64),
    website_url TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK(review_status='unresolved_official_internal_conflict'),
    evidence_relative_path TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256)=64),
    reviewed_at_utc TEXT NOT NULL,
    CHECK((source_kind='individual_order' AND field_name IN ('sjS1fOrd','sj_1cOrd','sj_2cOrd','sj_3cOrd','sj_4cOrd','sjG1fOrd'))
       OR (source_kind='group' AND field_name IN ('corner_7','corner_1','corner_2','corner_3','corner_4','corner_8'))),
    PRIMARY KEY(api_record_id,field_name)
);
'''
    sql += '''CREATE VIEW IF NOT EXISTS jeju_race_section_order_quality_values AS
WITH known(race_date,meet_code,race_number,horse_number,horse_id,field_name) AS (VALUES
    ''' + values(scope) + ''')
SELECT v.*,
       CASE WHEN k.field_name IS NOT NULL THEN NULL ELSE v.order_value END AS quality_order_value,
       CASE WHEN k.field_name IS NULL THEN v.order_status
            WHEN f.api_record_id IS NULL THEN 'internal_conflict_review_not_applied'
            WHEN f.api_payload_sha256_at_review<>v.api_payload_sha256 THEN 'api_source_changed_since_conflict_review'
            ELSE f.review_status END AS quality_order_status,
       f.evidence_relative_path AS conflict_evidence_path,
       f.evidence_sha256 AS conflict_evidence_sha256
FROM jeju_race_section_order_values v
LEFT JOIN known k ON (v.race_date,v.meet_code,v.race_number,v.horse_number,v.horse_id,v.field_name)
                   = (k.race_date,k.meet_code,k.race_number,k.horse_number,k.horse_id,k.field_name)
LEFT JOIN section_internal_conflict_reviews f ON f.api_record_id=v.api_record_id AND f.field_name=v.field_name AND f.source_kind='individual_order';
'''
    sql += 'CREATE VIEW IF NOT EXISTS jeju_race_section_order_quality AS\nSELECT api_record_id,\n'
    columns = []
    for field, group_field, short in MAP.values():
        columns += [f"MAX(CASE WHEN field_name='{field}' THEN quality_order_value END) AS {short}_order", f"MAX(CASE WHEN field_name='{field}' THEN quality_order_status END) AS {short}_order_status"]
    columns += ["SUM(quality_order_status IN ('unresolved_official_internal_conflict','internal_conflict_review_not_applied','api_source_changed_since_conflict_review')) AS section_internal_conflict_order_count"]
    sql += '    ' + ',\n    '.join(columns) + '\nFROM jeju_race_section_order_quality_values GROUP BY api_record_id;\n'
    group_map = [(point, gf) for point, (_, gf, _) in MAP.items()]
    sql += '''CREATE VIEW IF NOT EXISTS jeju_race_section_group_quality_values AS
WITH fields(point,field_name) AS (VALUES ''' + values(group_map) + '''),
known(race_date,meet_code,race_number,point) AS (VALUES ''' + values(sorted(groups)) + '''),
raw AS (
 SELECT r.api_record_id,r.race_date,r.meet_code,r.race_number,p.point,p.field_name,
        json_extract(a.payload_json,'$.'||p.field_name) AS group_raw,
        a.payload_sha256,s.raw_relative_path,s.sha256 AS source_page_sha256
 FROM api303_corner_rank_rows r JOIN api_records a USING(api_record_id)
 JOIN source_artifacts s USING(source_artifact_id) CROSS JOIN fields p WHERE r.meet_code=2
)
SELECT r.*,
       CASE WHEN k.point IS NOT NULL THEN NULL
            WHEN trim(COALESCE(r.group_raw,'')) IN ('','-','0','X') THEN NULL ELSE r.group_raw END AS group_value,
       CASE WHEN k.point IS NOT NULL AND f.api_record_id IS NULL THEN 'internal_conflict_review_not_applied'
            WHEN k.point IS NOT NULL AND f.api_payload_sha256_at_review<>r.payload_sha256 THEN 'api_source_changed_since_conflict_review'
            WHEN k.point IS NOT NULL THEN f.review_status
            WHEN trim(COALESCE(r.group_raw,'')) IN ('','-','0','X') THEN 'api_group_unavailable'
            ELSE 'api_group_unreviewed' END AS group_status,
       f.evidence_relative_path AS conflict_evidence_path,f.evidence_sha256 AS conflict_evidence_sha256
FROM raw r LEFT JOIN known k ON (r.race_date,r.meet_code,r.race_number,r.point)=(k.race_date,k.meet_code,k.race_number,k.point)
LEFT JOIN section_internal_conflict_reviews f ON f.api_record_id=r.api_record_id AND f.field_name=r.field_name AND f.source_kind='group';
'''
    sql += 'CREATE VIEW IF NOT EXISTS jeju_race_section_group_quality AS\nSELECT api_record_id,\n'
    columns = []
    for point, (_, _, short) in MAP.items():
        columns += [f"MAX(CASE WHEN point='{point}' THEN group_value END) AS {short}_group", f"MAX(CASE WHEN point='{point}' THEN group_status END) AS {short}_group_status"]
    columns += ["SUM(group_status IN ('unresolved_official_internal_conflict','internal_conflict_review_not_applied','api_source_changed_since_conflict_review')) AS section_internal_conflict_group_count"]
    sql += '    ' + ',\n    '.join(columns) + '\nFROM jeju_race_section_group_quality_values GROUP BY api_record_id;\n'
    names = [r['name'] for r in c.execute('PRAGMA table_info(jeju_race_postrace_sections_reviewed_2026)')]
    replaced = {short + suffix for _, _, short in MAP.values() for suffix in ('_order', '_order_status')}
    require(all(re.fullmatch(r'[a-zA-Z0-9_]+', name) for name in names), 'Unexpected view identifier')
    projections = ['a.' + name for name in names if name not in replaced]
    for _, _, short in MAP.values():
        projections += ['o.' + short + '_order', 'o.' + short + '_order_status', 'g.' + short + '_group', 'g.' + short + '_group_status']
    projections += ['o.section_internal_conflict_order_count', 'g.section_internal_conflict_group_count']
    sql += 'CREATE VIEW IF NOT EXISTS jeju_race_postrace_sections_quality_2026 AS\nSELECT ' + ',\n       '.join(projections) + '''
FROM jeju_race_postrace_sections_reviewed_2026 a
LEFT JOIN jeju_race_section_order_quality o ON o.api_record_id=a.api_record_id
LEFT JOIN jeju_race_section_group_quality g ON g.api_record_id=a.api303_api_record_id;
'''
    return sql, records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    c = sqlite3.connect(DB.as_uri() + ('?mode=rw' if args.apply else '?mode=ro'), uri=True)
    c.row_factory = sqlite3.Row
    sql, records = prepare(c)
    if MIGRATION.exists():
        require(MIGRATION.read_text() == sql, 'Migration differs from prepared scope')
    else:
        MIGRATION.write_text(sql)
    proof = OUT / 'official_recheck/manifest.json'
    require(proof.exists(), 'Fresh website evidence required before validation or application')
    evidence = json.loads(proof.read_text())
    require(len(evidence) == 19 and all(r.get('identity_verified') and r.get('http_status') == 200 for r in evidence), 'Incomplete fresh website evidence')
    evidence_sha = hashlib.sha256(proof.read_bytes()).hexdigest()
    root_check = json.loads((OUT / 'root_fresh_evidence_check.json').read_text())
    require(root_check.get('status') == 'passed' and root_check.get('manifest_sha256') == evidence_sha and (root_check.get('conflict_order_fields'), root_check.get('conflict_points')) == (70, 20), 'Independent fresh evidence check required')
    if not args.apply:
        c.close()
        print(json.dumps({'status': 'prepared', 'review_rows': len(records), 'migration': str(MIGRATION.relative_to(ROOT)), 'database_modified': False}))
        return
    before = json.loads((OUT / 'root_before_review.json').read_text())
    require(fingerprint(c) == before['api_fingerprint'], 'Source fingerprint changed')
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('BEGIN IMMEDIATE')
    try:
        for statement in statements(sql):
            match = re.search(r'CREATE\s+(TABLE|VIEW)\s+IF\s+NOT\s+EXISTS\s+(\w+)', statement, re.I)
            require(match is not None, 'Unexpected migration statement')
            kind, name = match.groups()
            existing = c.execute('SELECT type,sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
            if existing:
                require(existing['type'] == kind.lower() and norm(existing['sql']) == norm(statement[match.start():]), 'Existing definition differs')
            c.execute(statement)
        now = datetime.now(timezone.utc).isoformat()
        for record in records:
            row = (*record, 'unresolved_official_internal_conflict', 'jeju/research/20261003_unresolved_section_review/official_recheck/manifest.json', evidence_sha, now)
            existing = c.execute('SELECT * FROM section_internal_conflict_reviews WHERE api_record_id=? AND field_name=?', row[:2]).fetchone()
            if existing:
                require(tuple(existing)[:-1] == row[:-1], 'Review differs')
            else:
                c.execute('INSERT INTO section_internal_conflict_reviews VALUES (?,?,?,?,?,?,?,?,?,?)', row)
        order = c.execute("SELECT count(*) FROM jeju_race_section_order_quality_values WHERE quality_order_status='unresolved_official_internal_conflict' AND quality_order_value IS NULL").fetchone()[0]
        group = c.execute("SELECT count(*) FROM jeju_race_section_group_quality_values WHERE group_status='unresolved_official_internal_conflict' AND group_value IS NULL").fetchone()[0]
        require((order, group) == (70, 20), 'Unexpected masked scope')
        require(not c.execute('PRAGMA foreign_key_check(section_internal_conflict_reviews)').fetchall(), 'Foreign key violation')
        require(fingerprint(c) == before['api_fingerprint'], 'Raw source changed')
        for name, definition in before['protected_schema'].items():
            current = c.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
            require(current and current[0] == definition, 'Protected schema changed: ' + name)
        for name, key in [('race_section_time_reviews', 'time_reviews'), ('race_section_order_reviews', 'order_reviews')]:
            require([dict(r) for r in c.execute('SELECT * FROM ' + name + ' ORDER BY api_record_id,field_name')] == before[key], 'Existing reviews changed')
        c.commit()
        receipt = {'status': 'applied', 'review_rows': len(records), 'individual_order_fields_null': order, 'group_points_null': group, 'api_fingerprint_unchanged': True, 'protected_schema_unchanged': True, 'existing_time_and_order_reviews_unchanged': True, 'applied_at_utc': now, 'evidence_sha256': evidence_sha, 'migration_sha256': hashlib.sha256(sql.encode()).hexdigest(), 'selected_view': 'jeju_race_postrace_sections_quality_2026', 'model_input_adoption': False}
        (OUT / 'application_receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(receipt, ensure_ascii=False))
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


if __name__ == '__main__':
    main()
