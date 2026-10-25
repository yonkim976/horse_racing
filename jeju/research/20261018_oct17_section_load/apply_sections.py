"""Narrow, source-bound Oct 17 section append and six website distance reviews.

Run prepare, independent review, apply, verify in that order. No network access.
"""
from pathlib import Path
import argparse
from datetime import datetime, UTC
import fcntl
import hashlib
import json
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from jeju.refresh.core import apply_core, CANON, DIGEST, page_items

DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
SOURCE = ROOT / 'jeju/research/20261018_oct17_sections_website_review'
PLAN = HERE / 'plan.json'
RECEIPT = HERE / 'application_manifest.json'
BACKUP = HERE / 'before_section_load.sqlite3'
SIDECAR = ROOT / 'jeju/data/jeju_native_core.refresh_manifest.json'
RUN = '20261018_oct17_sections_website_distance'
DATE = '2026-10-17'

DDL = '''CREATE TABLE api6_section_distance_reviews(
 api_record_id INTEGER NOT NULL REFERENCES refresh_section_records(api_record_id),
 furlong_index INTEGER NOT NULL CHECK(furlong_index BETWEEN 1 AND 10),
 race_date TEXT NOT NULL, meet_code INTEGER NOT NULL, race_number INTEGER NOT NULL,
 race_distance_m_at_review INTEGER NOT NULL,
 api_payload_sha256_at_review TEXT NOT NULL CHECK(length(api_payload_sha256_at_review)=64),
 api_source_artifact_id_at_review INTEGER NOT NULL REFERENCES source_artifacts(source_artifact_id),
 api_source_page_sha256_at_review TEXT NOT NULL CHECK(length(api_source_page_sha256_at_review)=64),
 api_distance_m_at_review INTEGER NOT NULL,
 website_distance_m INTEGER NOT NULL CHECK(website_distance_m>0),
 effective_distance_m INTEGER NOT NULL CHECK(effective_distance_m=website_distance_m),
 review_status TEXT NOT NULL CHECK(review_status='website_corrected'),
 website_url TEXT NOT NULL, checked_date_kst TEXT NOT NULL,
 website_relative_path TEXT NOT NULL, website_sha256 TEXT NOT NULL CHECK(length(website_sha256)=64),
 evidence_relative_path TEXT NOT NULL, evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256)=64),
 decision_reason TEXT NOT NULL, applied_at_utc TEXT NOT NULL,
 PRIMARY KEY(api_record_id,furlong_index))'''

VIEW = '''CREATE VIEW api6_section_points_current AS
WITH indices(furlong_index) AS (VALUES(1),(2),(3),(4),(5),(6),(7),(8),(9),(10)),
raw AS (
 SELECT x.*,i.furlong_index,
 json_extract(payload_json,'$.rcDist') AS race_distance_m_raw,
 json_extract(payload_json,'$.dist_'||i.furlong_index||'f') AS api_distance_m_raw,
 json_type(payload_json,'$.dist_'||i.furlong_index||'f') AS api_distance_json_type,
 json_extract(payload_json,'$.time_'||i.furlong_index||'f') AS interval_time_raw,
 json_type(payload_json,'$.time_'||i.furlong_index||'f') AS interval_time_json_type,
 json_extract(payload_json,'$.passtime_'||i.furlong_index||'f') AS cumulative_time_raw,
 json_type(payload_json,'$.passtime_'||i.furlong_index||'f') AS cumulative_time_json_type
 FROM api6_section_records_current x CROSS JOIN indices i
), reviewed AS (
 SELECT b.*,r.website_distance_m,r.website_url,r.website_relative_path,r.website_sha256,
 r.evidence_relative_path,r.evidence_sha256,
 CASE WHEN b.race_date='2026-10-17' AND b.meet_code=2 AND b.race_number=5 AND b.furlong_index<=6
           AND r.api_record_id IS NULL THEN 'website_review_not_applied'
      WHEN r.api_record_id IS NOT NULL AND NOT(
       r.race_date IS b.race_date AND r.meet_code IS b.meet_code AND r.race_number IS b.race_number
       AND r.race_distance_m_at_review IS b.race_distance_m_raw
       AND r.api_payload_sha256_at_review IS b.payload_sha256
       AND r.api_source_artifact_id_at_review IS b.source_artifact_id
       AND r.api_source_page_sha256_at_review IS b.artifact_sha256
       AND r.api_distance_m_at_review IS b.api_distance_m_raw
       AND b.api_distance_json_type IN ('integer','real')
       AND r.effective_distance_m IS r.website_distance_m AND r.review_status='website_corrected'
      ) THEN 'api_source_changed_since_review'
      WHEN r.api_record_id IS NOT NULL THEN 'website_corrected'
      WHEN b.api_distance_json_type IN ('integer','real') AND b.api_distance_m_raw>0
           THEN 'api_positive_unreviewed' ELSE 'missing_or_nonpositive' END AS distance_status
 FROM raw b LEFT JOIN api6_section_distance_reviews r
 ON r.api_record_id=b.api_record_id AND r.furlong_index=b.furlong_index
 WHERE (b.api_distance_json_type IN ('integer','real') AND b.api_distance_m_raw>0)
    OR (b.interval_time_json_type IN ('integer','real') AND b.interval_time_raw>0)
    OR (b.cumulative_time_json_type IN ('integer','real') AND b.cumulative_time_raw>0)
    OR (b.race_date='2026-10-17' AND b.meet_code=2 AND b.race_number=5 AND b.furlong_index<=6)
)
SELECT *, CASE WHEN distance_status='website_corrected' THEN website_distance_m
               WHEN distance_status='api_positive_unreviewed' THEN api_distance_m_raw END AS distance_m,
 CASE WHEN interval_time_json_type IN ('integer','real') AND interval_time_raw>0 THEN interval_time_raw END AS interval_seconds,
 CASE WHEN cumulative_time_json_type IN ('integer','real') AND cumulative_time_raw>0 THEN cumulative_time_raw END AS cumulative_seconds
FROM reviewed'''


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(2**20), b''):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists(), 'Immutable output exists: ' + str(path))
    with path.open('x', encoding='utf-8') as f:
        f.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def relative(path):
    return str(path.resolve().relative_to(ROOT))


def connect(read_only=True):
    c = sqlite3.connect(DB.as_uri() + ('?mode=ro' if read_only else '?mode=rw'), uri=True)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


def check_inputs(plan):
    require(plan['loader_sha256'] == sha(Path(__file__)), 'Loader changed since prepare')
    require(plan['schema_sha256'] == DIGEST([DDL, VIEW]), 'DDL changed')
    for item in plan['inputs']:
        p = (ROOT / item['path']).resolve()
        p.relative_to(ROOT / 'jeju')
        require(sha(p) == item['sha256'], 'Source changed: ' + item['path'])
    for p in plan['pages']:
        raw, rows = page_items(ROOT, p)
        body = json.loads(raw)['response']['body']
        require(body['totalCount'] == 7 and len(rows) == 7, 'Incomplete API page')
        require({(str(r['rcDate']), str(r['meet']), int(r['rcNo'])) for r in rows}
                == {('20261017', '제주', n) for n in range(1, 8)}, 'Unexpected API keys')
    comparison = json.loads((SOURCE / 'root_api_website_comparison.json').read_text())
    require(comparison['api6_interval_and_cumulative_time_points_match_website'] == 39
            and comparison['nonempty_groups_match_website'] == {'corner_rank': 29, 'section_records': 29},
            'Website comparison incomplete')


def prepare():
    require(not PLAN.exists(), 'Plan exists')
    meta = json.loads((SOURCE / 'api_recheck_summary.json').read_text())
    pages = []
    for p in meta['today']['families']:
        pages.append({**p, 'path': relative(SOURCE / p['raw_path']), 'pagination_complete': True})
    website = json.loads((SOURCE / 'website_page_evidence.json').read_text())['per_race_pages']
    review5 = next(p for p in website if p['race_no'] == 5)
    evidence = json.loads((SOURCE / 'root_independent_verification.json').read_text())
    race5 = next(p for p in evidence['races'] if p['race'] == 5)
    require([int(x) for x in race5['passing_distances_m']] == [110, 310, 510, 710, 910, 1110], 'Website grid')
    paths = [SOURCE / p['raw_path'] for p in website]
    paths += [ROOT / p['path'] for p in pages]
    paths += [SOURCE / name for name in ('website_page_evidence.json', 'root_independent_verification.json',
                                         'root_api_website_comparison.json', 'api_recheck_summary.json')]
    migration = ROOT / 'jeju/data/schema/migrations/20261018_add_api6_section_distance_reviews.sql'
    require(migration.read_text() == DDL + ';\n\n' + VIEW + ';\n', 'Migration differs from applied schema')
    paths.append(migration)
    plan = {'run_id': RUN, 'date': DATE, 'database_sha256_before': sha(DB),
            'loader_sha256': sha(Path(__file__)), 'schema_sha256': DIGEST([DDL, VIEW]),
            'inputs': [{'path': relative(p), 'sha256': sha(p)} for p in paths], 'pages': pages,
            'review5': {'url': review5['url'], 'path': relative(SOURCE / review5['raw_path']),
                        'sha256': review5['sha256'], 'distances_m': [110, 310, 510, 710, 910, 1110]},
            'expected_new_rows': {'api_records': 14, 'refresh_section_records': 7,
                                  'api303_corner_rank_rows': 7, 'source_artifacts': 2,
                                  'research_refresh_observations': 14, 'research_refresh_runs': 1,
                                  'api6_section_distance_reviews': 6},
            'prior_refresh_pointer': json.loads(SIDECAR.read_text())}
    check_inputs(plan)
    write(PLAN, plan)
    print('Prepared plan SHA256', sha(PLAN), flush=True)


def target_check(c):
    result = {}
    for table in ('refresh_section_records', 'api303_corner_rank_rows'):
        rows = c.execute('SELECT race_number FROM ' + table + ' WHERE race_date=? AND meet_code=2 ORDER BY race_number', (DATE,)).fetchall()
        require([r[0] for r in rows] == list(range(1, 8)), 'Target race count: ' + table)
        result[table] = len(rows)
    points = [dict(r) for r in c.execute('''SELECT furlong_index,api_distance_m_raw,distance_m,distance_status
      FROM api6_section_points_current WHERE race_date=? AND meet_code=2 AND race_number=5 ORDER BY furlong_index''', (DATE,))]
    require([p['distance_m'] for p in points] == [110, 310, 510, 710, 910, 1110], 'Effective grid mismatch')
    require(all(p['distance_status'] == 'website_corrected' for p in points), 'Review status mismatch')
    require([p['api_distance_m_raw'] for p in points] == [100, 300, 500, 700, 900, 1100], 'Raw changed')
    result['reviewed_points'] = points
    require(c.execute('SELECT count(*) FROM api6_section_points_current WHERE race_date=? AND meet_code=2', (DATE,)).fetchone()[0] == 39, 'Target points')
    return result


def apply():
    plan = json.loads(PLAN.read_text())
    check_inputs(plan)
    gate = json.loads((HERE / 'verification/preapply.json').read_text())
    require(gate['passed'] is True and gate['plan_sha256'] == sha(PLAN), 'Independent gate missing or stale')
    require(not RECEIPT.exists() and not BACKUP.exists(), 'Already applied or interrupted; inspect receipt/backup')
    with (ROOT / 'jeju/research/20261017_core_refresh/refresh.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(sha(DB) == plan['database_sha256_before'], 'Database changed since prepare')
        with connect() as old, sqlite3.connect(BACKUP) as dst:
            old.backup(dst)
        # SQLite backup can change header bookkeeping; record both hashes.
        with sqlite3.connect(BACKUP.as_uri() + '?mode=ro', uri=True) as frozen:
            require(frozen.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'Backup integrity failure')
        require(sha(DB) == plan['database_sha256_before'], 'Source changed while backing up')
        write(HERE / 'prior_refresh_pointer.json', plan['prior_refresh_pointer'])
        started = datetime.now(UTC).isoformat()
        c = connect(False)
        try:
            c.execute('BEGIN IMMEDIATE')
            c.execute('INSERT INTO research_refresh_runs VALUES(?,?,?,?,?,?,?)',
                      (RUN, started, None, DATE, DATE, relative(PLAN), 'applying'))
            summary = apply_core(c, plan['pages'], ROOT, RUN, DATE, DATE)
            require(all(summary[f].get('inserted') == 7 and not summary[f].get('held') for f in ('section_records', 'corner_rank')), 'Unexpected loader decision')
            c.execute(DDL)
            record = c.execute('''SELECT x.*,a.payload_sha256,a.source_artifact_id,a.payload_json,sa.sha256
               FROM refresh_section_records x JOIN api_records a USING(api_record_id)
               JOIN source_artifacts sa USING(source_artifact_id)
               WHERE race_date=? AND meet_code=2 AND race_number=5''', (DATE,)).fetchone()
            raw = json.loads(record['payload_json'])
            require(raw['rcDist'] == 1110, 'Race distance changed')
            for i, distance in enumerate(plan['review5']['distances_m'], 1):
                require(raw['dist_' + str(i) + 'f'] == 100 + (i - 1) * 200, 'Raw grid changed')
                values = (record['api_record_id'], i, DATE, 2, 5, 1110, record['payload_sha256'],
                          record['source_artifact_id'], record['sha256'], raw['dist_' + str(i) + 'f'],
                          distance, distance, 'website_corrected', plan['review5']['url'], '2026-10-18',
                          plan['review5']['path'], plan['review5']['sha256'],
                          relative(SOURCE / 'root_api_website_comparison.json'), sha(SOURCE / 'root_api_website_comparison.json'),
                          'User-approved exact-race homepage distance correction; API raw retained; no inferred global +10m rule.', started)
                c.execute('INSERT INTO api6_section_distance_reviews VALUES(' + ','.join('?' for _ in values) + ')', values)
            c.execute(VIEW)
            checks = target_check(c)
            require(not c.execute('PRAGMA foreign_key_check').fetchall(), 'Foreign key failure')
            c.execute('UPDATE research_refresh_runs SET completed_at_utc=?,status=? WHERE run_id=?',
                      (datetime.now(UTC).isoformat(), 'applied_verified', RUN))
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()
        after = sha(DB)
        receipt = {'run_id': RUN, 'status': 'applied_verified', 'scope': 'narrow_oct17_section_append_and_six_website_distance_reviews',
                   'start': DATE, 'end': DATE, 'plan': relative(PLAN), 'plan_sha256': sha(PLAN),
                   'database_sha256_before': plan['database_sha256_before'], 'database_sha256_after': after,
                   'backup': relative(BACKUP), 'backup_sha256': sha(BACKUP),
                   'summary': summary, 'checks': checks, 'prior_refresh_pointer': plan['prior_refresh_pointer'],
                   'completed_at_utc': datetime.now(UTC).isoformat()}
        write(RECEIPT, receipt)
        pointer = {'latest_run_id': RUN, 'application_manifest': relative(RECEIPT), 'sha256': sha(RECEIPT), 'database_sha256': after}
        tmp = SIDECAR.with_name(SIDECAR.name + '.oct17.tmp')
        with tmp.open('x') as f:
            f.write(json.dumps(pointer, ensure_ascii=False, indent=2) + '\n')
        tmp.replace(SIDECAR)
        print(CANON(receipt), flush=True)


def verify():
    plan = json.loads(PLAN.read_text())
    check_inputs(plan)
    receipt = json.loads(RECEIPT.read_text())
    before_sha = sha(DB)
    require(before_sha == receipt['database_sha256_after'], 'Receipt stale')
    q = lambda x: '"' + x.replace('"', '""') + '"'
    with connect() as c:
        c.execute('ATTACH DATABASE ? AS frozen', (BACKUP.as_uri() + '?mode=ro',))
        c.execute('PRAGMA query_only=ON')
        baseline_schema = list(c.execute('SELECT type,name,tbl_name,sql FROM frozen.sqlite_master ORDER BY type,name'))
        now_schema = {r[1]: tuple(r) for r in c.execute('SELECT type,name,tbl_name,sql FROM main.sqlite_master')}
        require(all(now_schema[r[1]] == tuple(r) for r in baseline_schema), 'Existing schema changed')
        tables = {}
        for (name,) in c.execute("SELECT name FROM frozen.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
            cols = [r[1] for r in c.execute('PRAGMA frozen.table_info(' + q(name) + ')')]
            old = c.execute('SELECT count(*) FROM frozen.' + q(name)).fetchone()[0]
            new = c.execute('SELECT count(*) FROM main.' + q(name)).fetchone()[0]
            require(new - old == plan['expected_new_rows'].get(name, 0), 'Unexpected row delta ' + name)
            diff = ' OR '.join('b.' + q(k) + ' IS NOT m.' + q(k) for k in cols)
            bad = c.execute('SELECT count(*) FROM frozen.' + q(name) + ' b LEFT JOIN main.' + q(name) + ' m ON m.rowid=b.rowid WHERE m.rowid IS NULL OR ' + diff).fetchone()[0]
            require(bad == 0, 'Existing rows changed: ' + name)
            tables[name] = {'before': old, 'after': new, 'all_columns_preserved': True}
            print(name, old, new, 'preserved', flush=True)
        checks = target_check(c)
        require(c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'Integrity failure')
        require(not c.execute('PRAGMA foreign_key_check').fetchall(), 'Foreign key failure')
    # Replay under rollback: exercises the actual loader without changing the file.
    with connect(False) as c:
        c.execute('BEGIN IMMEDIATE')
        replay = apply_core(c, plan['pages'], ROOT, RUN, DATE, DATE)
        require(all(replay[f].get('replay_skipped') == 7 and not replay[f].get('inserted') for f in ('section_records', 'corner_rank')), 'Replay failed')
        c.rollback()
    require(sha(DB) == before_sha, 'Verification/replay changed DB')
    write(HERE / 'verification/preservation.json', {'passed': True, 'database_sha256': before_sha,
          'existing_schema_unchanged': True, 'tables': tables, 'tables_checked': len(tables),
          'rows_checked': sum(t['before'] for t in tables.values()), 'checks': checks,
          'idempotent_replay': replay, 'integrity_check': 'ok', 'foreign_key_violations': 0})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('prepare', 'apply', 'verify'))
    globals()[parser.parse_args().phase]()
