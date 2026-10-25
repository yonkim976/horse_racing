"""Link archived daily-training rider numbers without changing event rows.

Default: write a review plan. --apply: add an explicitly reviewed mapping and
two views to the named local Jeju SQLite DB. No network requests.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from collections import OrderedDict
from bs4 import BeautifulSoup
from urllib.parse import urlsplit, parse_qs

if not __debug__:
    raise RuntimeError('Run without -O; source and transaction checks must remain enabled')

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
JOCKEY_DIR = ROOT / 'data/research/jockey_roster_20261008'
MIGRATION = ROOT / 'jeju/data/schema/migrations/20261015_add_daily_training_rider_identity.sql'
VALID_NUMBER = re.compile(r'[0-9]{6}\Z')
WEBSITE_EVIDENCE = HERE / 'source_review/staff_website_identity_evidence.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def website_observations(connection):
    if not WEBSITE_EVIDENCE.exists():
        return []
    ledger = json.loads(WEBSITE_EVIDENCE.read_text())
    parsed_pages = {}
    page_hashes = {}
    observations = {}
    for item in ledger['evidence'] + ledger.get('unresolved_observations', []):
        path = (ROOT / item['source_path']).resolve(strict=True)
        require(path.is_relative_to(HERE / 'source_review'), 'Website source outside review folder')
        parsed = urlsplit(item['url'])
        query = parse_qs(parsed.query)
        require(parsed.scheme == 'https' and parsed.hostname == 'race.kra.co.kr'
                and parsed.path == '/racehorse/profileTrainState.do'
                and query.get('meet') == ['2'] and query.get('hrNo') == [item['horse_id']],
                'Wrong website URL/horse/meet')
        if path not in parsed_pages:
            raw = path.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == item['source_sha256'], 'Website SHA mismatch')
            page_hashes[path] = item['source_sha256']
            soup = BeautifulSoup(raw.decode('euc-kr'), 'html.parser')
            horse_input = soup.find('input', attrs={'name': 'hrNo'})
            require(horse_input and horse_input.get('value') == item['horse_id'], 'Website horse ID mismatch')
            cells = [[td.get_text(' ', strip=True) for td in tr.find_all('td')]
                     for tr in soup.find_all('tr')]
            parsed_pages[path] = cells
        require(page_hashes[path] == item['source_sha256'], 'Conflicting website page SHA')
        training = connection.execute('SELECT * FROM daily_training_api_rows WHERE daily_training_api_row_id=?',
                                      (item['training_row_id'],)).fetchone()
        require(training is not None, 'Missing training source row')
        for raw_key, website_key in (('prNo_raw','employee_number'), ('prGubun_raw','category_raw'),
                                     ('horse_id','horse_id'), ('training_date','date'),
                                     ('start_time_local','start_time_local'), ('end_time_local','end_time_local')):
            require(training[raw_key] == item[website_key], f'Website/API training key mismatch: {raw_key}')
        require(VALID_NUMBER.fullmatch(item['employee_number']), 'Missing/invalid employee number')
        start, end = training['start_time_local'], training['end_time_local']
        require(start and end and training['duration_seconds'], 'Unusable times for event matching')
        date_text = training['training_date'].replace('-', '/')
        matching = [r for r in parsed_pages[path] if len(r) == 7 and r[1].startswith(date_text)
                    and r[2] == item['website_name_raw'] and r[3] == start[11:16] and r[4] == end[11:16]
                    and r[5] == str(training['duration_seconds'] // 60) + '분']
        require(len(matching) == 1, 'Website row not uniquely matched by horse/date/name/times/duration')
        name = re.sub(r'\((?:관|조|생|트)\)$', '', item['website_name_raw']).strip()
        if item['person_name'] is None:
            require(name in ('', '-', '관', '조', '생', '외'), 'Unrecognized name-missing website token')
        else:
            require(name == item['person_name'] and name not in ('', '-', '관', '조', '생', '외', '경주일'), 'Invalid rider name extraction')
        old = observations.get(item['training_row_id'])
        require(old is None or old['person_name'] == item['person_name'], 'Conflicting website observations for one event')
        observations[item['training_row_id']] = item
    return sorted(observations.values(), key=lambda r: r['training_row_id'])


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def reference_item(payload, complete=True):
    response = payload['response']
    assert str(response['header']['resultCode']) in ('00', '0'), 'API error response'
    body = response['body']
    rows = body['items']['item']
    if isinstance(rows, dict):
        rows = [rows]
    if complete:
        assert len(rows) == int(body['totalCount']), 'Incomplete archived page'
    else:
        assert len(rows) <= int(body['totalCount']), 'Invalid archived page count'
    return rows


def build_plan(connection):
    connection.row_factory = sqlite3.Row
    refs = defaultdict(lambda: defaultdict(list))
    sources = []
    roster = json.loads((JOCKEY_DIR / 'manifest.json').read_text())
    for meet in (1, 2, 3):
        path = JOCKEY_DIR / f'api_{meet}.json'
        digest = file_sha(path)
        declared = {r['api_sha256'] for r in roster['rows'] if r['meet_code'] == meet}
        assert declared == {digest}, f'API307 archive SHA mismatch: meet {meet}'
        items = reference_item(json.loads(path.read_text()))
        sources.append({'path': str(path.relative_to(ROOT)), 'sha256': digest,
                        'endpoint': '/API307/jockeyInfo', 'meet_code': meet,
                        'rows': len(items), 'observed_at': roster['observed_at']})
        for index, item in enumerate(items, 1):
            number, name = item.get('jkNo'), item.get('jkName')
            if VALID_NUMBER.fullmatch(str(number)) and name not in (None, '', '-'):
                refs[('기수', str(number))][str(name)].append({
                    'type': 'api307', 'path': str(path.relative_to(ROOT)),
                    'source_sha256': digest, 'item_index': index,
                    'observed_at': roster['observed_at'], 'payload': item})
    witness_query = """
        SELECT '기수' AS kind,jockey_id AS number,jockey_name AS name,
               MIN(api_record_id) AS witness,COUNT(*) AS observations,
               MIN(race_date) AS first_date,MAX(race_date) AS last_date
        FROM race_result_rows GROUP BY jockey_id,jockey_name
        UNION ALL
        SELECT '기수',jockey_id,jockey_name,MIN(api_record_id),COUNT(*),MIN(trial_date),MAX(trial_date)
        FROM running_trial_rows GROUP BY jockey_id,jockey_name
        UNION ALL
        SELECT '조교사',trainer_id,trainer_name,MIN(api_record_id),COUNT(*),MIN(race_date),MAX(race_date)
        FROM race_result_rows GROUP BY trainer_id,trainer_name
        UNION ALL
        SELECT '조교사',trainer_id,trainer_name,MIN(api_record_id),COUNT(*),MIN(trial_date),MAX(trial_date)
        FROM running_trial_rows GROUP BY trainer_id,trainer_name
    """
    page_cache = OrderedDict()
    verified_pages = set()
    witness_count = 0
    for row in connection.execute(witness_query):
        if not VALID_NUMBER.fullmatch(str(row['number'])) or row['name'] in (None, '', '-'):
            continue
        record = connection.execute('''SELECT a.*,s.raw_relative_path,s.sha256 AS source_sha256
            FROM api_records a JOIN source_artifacts s USING(source_artifact_id)
            WHERE api_record_id=?''', (row['witness'],)).fetchone()
        payload = json.loads(record['payload_json'])
        assert hashlib.sha256(canonical(payload).encode()).hexdigest() == record['payload_sha256']
        id_field, name_field = ('jkNo', 'jkName') if row['kind'] == '기수' else ('trNo', 'trName')
        assert str(payload[id_field]) == row['number'] and payload[name_field] == row['name']
        path = (ROOT / record['raw_relative_path']).resolve()
        assert path.is_relative_to(ROOT), 'API evidence path escaped project'
        if path not in page_cache:
            assert file_sha(path) == record['source_sha256'], 'Archived source SHA mismatch'
            page_cache[path] = reference_item(json.loads(path.read_text()), complete=False)
            verified_pages.add(path)
            if len(page_cache) > 3:
                page_cache.popitem(last=False)
        else:
            page_cache.move_to_end(path)
        assert page_cache[path][record['record_index'] - 1] == payload, 'API item differs from DB witness'
        witness_count += 1
        refs[(row['kind'], row['number'])][row['name']].append({
            'type': 'historical_official_api', 'api_record_id': row['witness'],
            'payload_sha256': record['payload_sha256'], 'path': record['raw_relative_path'],
            'source_sha256': record['source_sha256'], 'item_index': record['record_index'],
            'observations': row['observations'], 'first_date': row['first_date'],
            'last_date': row['last_date']})
    web_observations = website_observations(connection)
    for item in web_observations:
        if item['person_name'] is None:
            continue
        refs[('홈페이지기승자', item['employee_number'])][item['person_name']].append({
            'type': 'official_daily_training_website', **item})
    training_groups = connection.execute('''SELECT prGubun_raw,prNo_raw,COUNT(*) AS rows,
        MIN(training_date) AS first_date,MAX(training_date) AS last_date
        FROM daily_training_api_rows GROUP BY prGubun_raw,prNo_raw ORDER BY 1,2''').fetchall()
    decisions = []
    for group in training_groups:
        role, number = group['prGubun_raw'], group['prNo_raw']
        assert role is not None and number is not None, 'New null representation requires review'
        kinds = [kind for kind in ('기수', '조교사') if (kind, number) in refs]
        selected_kind = None
        status = 'unresolved_employee_number'
        if number in ('', '-'):
            status = 'missing_employee_number'
        elif not VALID_NUMBER.fullmatch(number):
            status = 'invalid_employee_number'
        elif role in ('기수', '기수후보생'):
            if '기수' in kinds:
                selected_kind = '기수'
                status = 'matched_jockey_id' if role == '기수' else 'matched_jockey_id_candidate_role'
            elif kinds:
                status = 'role_number_conflict'
        elif role == '조교사':
            if '조교사' in kinds:
                selected_kind, status = '조교사', 'matched_trainer_id'
            elif kinds:
                status = 'role_number_conflict'
        elif role == '-':
            if len(kinds) == 1:
                selected_kind, status = kinds[0], 'matched_id_role_not_provided'
            elif len(kinds) > 1:
                status = 'ambiguous_person_role'
        if (selected_kind is None and status == 'unresolved_employee_number'
                and role in ('-', '조교보', '조교승인')
                and ('홈페이지기승자', number) in refs):
            selected_kind = '홈페이지기승자'
            status = 'matched_employee_number_website_reference'
        elif (selected_kind is None and status == 'unresolved_employee_number'
              and any(w['employee_number'] == number and w['person_name'] is None for w in web_observations)):
            status = 'website_person_name_not_provided'
        evidence = []
        name = None
        names = refs.get((selected_kind, number), {})
        if selected_kind:
            # A unique official ID/name mapping is required across all retained
            # sources; conflicting names remain unresolved instead of guessed.
            if len(names) == 1:
                name = next(iter(names))
                evidence = names[name]
            else:
                status = 'ambiguous_reference_names'
                selected_kind = None
                evidence = [{'candidate_name': k, 'evidence': v} for k, v in names.items()]
        witness = next((e for e in evidence if e.get('type') == 'historical_official_api'), None)
        decisions.append({
            'rider_category_raw': role, 'employee_number_raw': number,
            'rider_name': name, 'reference_person_kind': selected_kind,
            'identity_status': status, 'training_rows': group['rows'],
            'first_training_date': group['first_date'], 'last_training_date': group['last_date'],
            'witness_api_record_id': witness['api_record_id'] if witness else None,
            'witness_payload_sha256': witness['payload_sha256'] if witness else None,
            'evidence_json': canonical(evidence)})
    counts = Counter()
    role_counts = defaultdict(Counter)
    for decision in decisions:
        counts[decision['identity_status']] += decision['training_rows']
        role_counts[decision['rider_category_raw']]['total'] += decision['training_rows']
        role_counts[decision['rider_category_raw']]['named' if decision['rider_name'] else 'unresolved'] += decision['training_rows']
    return {'schema_version': 1, 'review_date_kst': '2026-10-15',
            'database_modified': False, 'model_inputs_modified': False,
            'reference_artifacts': sources, 'historical_witness_count': witness_count,
            'website_observations': web_observations,
            'website_evidence_sha256': file_sha(WEBSITE_EVIDENCE) if WEBSITE_EVIDENCE.exists() else None,
            'historical_pages_verified': len(verified_pages),
            'decisions': decisions, 'total_training_rows': sum(counts.values()),
            'status_counts': dict(counts), 'role_counts': {k: dict(v) for k,v in role_counts.items()},
            'named_rows': sum(r['training_rows'] for r in decisions if r['rider_name']),
            'unresolved_rows': sum(r['training_rows'] for r in decisions if not r['rider_name'])}


def statements(text):
    pending = ''
    for line in text.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            yield pending
            pending = ''
    assert not pending.strip(), 'Incomplete migration'


def apply_plan(connection, plan, expected_sha, db):
    if not expected_sha or file_sha(db) != expected_sha:
        raise ValueError('Expected DB SHA required/mismatch')
    old_schema = dict(connection.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))
    columns = ('rider_category_raw', 'employee_number_raw', 'rider_name', 'reference_person_kind',
               'identity_status', 'training_rows', 'first_training_date', 'last_training_date',
               'witness_api_record_id', 'witness_payload_sha256', 'evidence_json')
    tuples = [tuple(row[column] for column in columns) for row in plan['decisions']]
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='training_rider_identity_reviews'").fetchone()
    if exists and connection.execute('SELECT COUNT(*) FROM training_rider_identity_reviews').fetchone()[0]:
        existing = list(connection.execute('SELECT ' + ','.join(columns) +
                       ' FROM training_rider_identity_reviews ORDER BY rider_category_raw,employee_number_raw'))
        assert existing == tuples, 'Existing rider identity review differs; new version needed'
        saved_web = list(connection.execute('''SELECT daily_training_api_row_id,employee_number_raw,
            rider_category_raw,person_name,rider_name_raw,source_path,source_sha256,source_url
            FROM training_rider_website_observations ORDER BY daily_training_api_row_id'''))
        expected_web = [(r['training_row_id'],r['employee_number'],r['category_raw'],r['person_name'],
                         r['website_name_raw'],r['source_path'],r['source_sha256'],r['url'])
                        for r in plan['website_observations']]
        require(saved_web == expected_web, 'Existing website rider observations differ')
        return {'status': 'already_applied', 'inserted_reviews': 0}
    if exists:
        require(connection.execute('SELECT COUNT(*) FROM training_rider_website_observations').fetchone()[0] == 0,
                'Partial existing website observations require explicit review')
    connection.execute('BEGIN IMMEDIATE')
    try:
        for sql in statements(MIGRATION.read_text()):
            connection.execute(sql)
        marks = ','.join('?' for _ in columns)
        connection.executemany('INSERT INTO training_rider_identity_reviews (' + ','.join(columns) + ') VALUES (' + marks + ')', tuples)
        connection.executemany('''INSERT INTO training_rider_website_observations
            (daily_training_api_row_id,employee_number_raw,rider_category_raw,person_name,
             rider_name_raw,source_path,source_sha256,source_url)
            VALUES (?,?,?,?,?,?,?,?)''', [
                (r['training_row_id'],r['employee_number'],r['category_raw'],r['person_name'],
                 r['website_name_raw'],r['source_path'],r['source_sha256'],r['url'])
                for r in plan['website_observations']])
        after_schema = dict(connection.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))
        assert all(after_schema[k] == v for k,v in old_schema.items()), 'Existing schema changed'
        assert connection.execute('SELECT COUNT(*) FROM daily_training_riders').fetchone()[0] == plan['total_training_rows']
        assert connection.execute('SELECT COUNT(*) FROM daily_training_riders_analysis_2026').fetchone()[0] == 907389
        assert not connection.execute('PRAGMA foreign_key_check(training_rider_identity_reviews)').fetchall()
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return {'status': 'applied', 'inserted_reviews': len(tuples),
            'applied_at_utc': datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-db-sha256')
    parser.add_argument('--db', type=Path, default=DB)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    db = args.db.resolve(strict=True)
    if not (db == DB or db.is_relative_to(HERE)):
        raise ValueError('Only the local Jeju DB or a staged DB in this work folder is allowed')
    if args.apply and db == DB:
        require((HERE / 'root/before_rider_identity.sqlite3').is_file(), 'Production backup required')
    output = args.output.resolve()
    assert output.is_relative_to(HERE) and not output.exists(), 'Use a new report inside this work folder'
    with sqlite3.connect(db.as_uri() + ('?mode=rw' if args.apply else '?mode=ro'), uri=True) as c:
        c.execute('PRAGMA foreign_keys=ON')
        if not args.apply:
            c.execute('PRAGMA query_only=ON')
        plan = build_plan(c)
        c.row_factory = None
        if args.apply:
            plan['application'] = apply_plan(c, plan, args.expected_db_sha256, db)
            plan['database_modified'] = plan['application']['status'] == 'applied'
        output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k:v for k,v in plan.items() if k not in ('decisions','reference_artifacts','website_observations')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
