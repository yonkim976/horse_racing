"""Independent read-only comparison of loaded SQLite rows to archived API items."""
import argparse
import collections
import hashlib
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / 'jeju/research/20261001_starting_exam_api_collection'
FIELDS = {
    'meet': 'meet_raw', 'trainDate': 'train_date_raw',
    'daySerial': 'day_serial_raw', 'trainNo': 'train_no_raw',
    'chulNo': 'chul_no_raw', 'hrName': 'hr_name_raw', 'hrNo': 'hr_no_raw',
    'name': 'name_raw', 'sex': 'sex_raw', 'age': 'age_raw',
    'rider': 'rider_raw', 'trName': 'tr_name_raw', 'trNo': 'tr_no_raw',
    'owName': 'ow_name_raw', 'owNo': 'ow_no_raw', 'passFlag': 'pass_flag_raw',
    'reason': 'reason_raw', 'nopassReason': 'nopass_reason_raw',
}


def read(path):
    return json.loads(path.read_text())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def txt(value):
    return None if value is None else str(value)


def safe_path(parent, relative):
    path = (parent / relative).resolve()
    assert path.is_relative_to(parent.resolve()), relative
    return path


def items(data):
    value = data['response']['body']['items']['item']
    return value if isinstance(value, list) else [value]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--output-report', type=Path, required=True)
    parser.add_argument('--quick-check', action='store_true', help='Use quick_check when the loader has already completed full integrity_check on staging')
    args = parser.parse_args()
    before = read(HERE / 'root_before_load.json')
    precheck = read(HERE / 'root_source_precheck.json')
    candidate_path = SOURCE / 'api21_verified_native_candidate_rows.jsonl'
    assert sha(candidate_path.read_bytes()) == precheck['candidate_sha256']
    candidates = [json.loads(line) for line in candidate_path.read_text().splitlines()]
    followups = read(HERE / 'root_followup_profiles.json')
    conn = sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    report = {'database': str(args.db.resolve()), 'candidate_sha256': precheck['candidate_sha256']}
    try:
        schema = {r['name']: {'type': r['type'], 'sql': r['sql']} for r in
                  conn.execute("SELECT name,type,sql FROM sqlite_master WHERE sql IS NOT NULL")}
        for name, old in before['schema'].items():
            assert schema[name] == old, ('old_schema_changed', name)
        counts = {}
        permitted = {'schema_metadata': 12, 'source_artifacts': 56, 'api_records': 10685,
                     'horse_profile_observations': 21, 'breed_evidence': 21}
        for name, count in before['table_counts'].items():
            assert name.isidentifier()
            actual = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            counts[name] = actual
            assert actual == count + permitted.get(name, 0), (name, count, actual)
        for name, id_column, old_rows in [
            ('horse_profile_observations', 'horse_profile_observation_id', before['profiles']),
            ('source_artifacts', 'source_artifact_id', before['source_artifacts']),
            ('schema_metadata', 'key', before['metadata']),
        ]:
            now = {r[id_column]: dict(r) for r in conn.execute(f'SELECT * FROM "{name}"')}
            for old in old_rows:
                assert now[old[id_column]] == old, ('old_row_changed', name, old[id_column])
        conn.execute('ATTACH DATABASE ? AS before_snapshot',
                     ((HERE / 'before_load.sqlite3').resolve().as_uri() + '?mode=ro',))
        old_rows_verified = {}
        for name in before['table_counts']:
            info = list(conn.execute(f'PRAGMA before_snapshot.table_info("{name}")'))
            columns = [r['name'] for r in info]
            primary = [r['name'] for r in sorted(info, key=lambda r: r['pk']) if r['pk']]
            assert primary and all(column.isidentifier() for column in columns)
            join = ' AND '.join(f'n."{col}" IS o."{col}"' for col in primary)
            difference = ' OR '.join(f'n."{col}" IS NOT o."{col}"' for col in columns)
            changed = conn.execute(f'''SELECT COUNT(*) FROM before_snapshot."{name}" o
                LEFT JOIN main."{name}" n ON {join}
                WHERE n."{primary[0]}" IS NULL OR ({difference})''').fetchone()[0]
            assert changed == 0, ('old_table_rows_changed', name, changed)
            old_rows_verified[name] = before['table_counts'][name]
        sources = {r['source_artifact_id']: dict(r) for r in conn.execute('SELECT * FROM source_artifacts')}
        page_cache = {}
        source_for_position = {}
        for candidate in candidates:
            path = safe_path(SOURCE, candidate['source_path'])
            relative = path.relative_to(ROOT).as_posix()
            if relative not in page_cache:
                raw_bytes = path.read_bytes()
                data = read(path)
                assert data['response']['header']['resultCode'] == '00'
                page_cache[relative] = items(data)
                match = [s for s in sources.values() if s['raw_relative_path'] == relative]
                assert len(match) == 1, (relative, 'artifact_not_unique')
                artifact = match[0]
                assert artifact['sha256'] == sha(raw_bytes)
                assert artifact['response_bytes'] == len(raw_bytes)
                assert artifact['operation'] == 'startingTestResult_1'
                manifest = read(path.parents[1] / 'attempt_manifest.json')
                page = next(p for p in manifest['source_pages'] if p['response_file'] == 'source_pages/' + path.name)
                assert page['response_sha256'] == artifact['sha256']
                assert artifact['collected_at_utc'] == page['retrieved_at_utc']
                assert artifact['http_status_code'] == page['status_code'] == 200
                assert 'ServiceKey' not in artifact['request_params_json']
                source_for_position[relative] = artifact['source_artifact_id']
            assert page_cache[relative][candidate['source_row_no'] - 1] == candidate['raw']
        loaded = {(r['raw_relative_path'], r['source_row_no']): dict(r) for r in conn.execute('''
            SELECT se.*,ar.payload_json,ar.payload_sha256,ar.record_index,
                   ar.source_artifact_id AS record_artifact,sa.raw_relative_path
            FROM starting_exam_api_rows se
            JOIN api_records ar ON ar.api_record_id=se.api_record_id
            JOIN source_artifacts sa ON sa.source_artifact_id=se.source_artifact_id''')}
        assert len(loaded) == len(candidates) == 10664
        group_rounds = collections.defaultdict(set)
        labels = collections.Counter()
        for candidate in candidates:
            raw = candidate['raw']
            relative = safe_path(SOURCE, candidate['source_path']).relative_to(ROOT).as_posix()
            row = loaded[(relative, candidate['source_row_no'])]
            assert row['source_artifact_id'] == row['record_artifact'] == source_for_position[relative]
            assert row['record_index'] == row['source_row_no']
            assert json.loads(row['payload_json']) == raw
            assert sha(row['payload_json'].encode()) == row['payload_sha256']
            for key, column in FIELDS.items():
                assert row[column] == txt(raw.get(key)), (row['api_record_id'], key)
            present = json.loads(row['raw_key_presence_json'])
            absent = json.loads(row['raw_key_absence_json'])
            assert set(present) == set(raw).intersection(FIELDS)
            assert set(absent) == set(FIELDS).difference(raw)
            assert row['horse_id'] == str(raw['hrNo'])
            date = str(raw['trainDate'])
            assert row['exam_date'] == f'{date[:4]}-{date[4:6]}-{date[6:8]}'
            label = txt(raw.get('passFlag'))
            assert row['judgment_label_normalized'] == (None if label in (None, '', '-', '0') else label)
            assert row['judgment_status'] == ('unknown' if label in (None, '', '-', '0') else 'observed')
            trno = txt(raw.get('trNo'))
            assert row['trainer_id_normalized'] == (trno if trno and trno.isdigit() and trno != '0' else None)
            labels[label] += 1
            group_rounds[(row['horse_id'], row['exam_date'])].add(row['train_no_raw'])
        assert dict(labels) == precheck['judgements']
        # In these source data, trainNo differentiates the two examinations on the same date.
        assert sum(len(rounds) > 1 for rounds in group_rounds.values()) == 779
        profiles = {r['horse_id']: dict(r) for r in conn.execute('SELECT * FROM horse_profile_latest')}
        assert len(profiles) == 4637
        assert set(str(c['raw']['hrNo']) for c in candidates).issubset(profiles)
        for horse_id, item in followups.items():
            profile = profiles[horse_id]
            raw = item['raw']
            assert json.loads(profile['payload_json']) == raw
            for raw_key, column in [('hrNm','horse_name_raw'),('birthDt','birth_date_raw'),
                                    ('age','age_raw'),('breed','breed_label_raw'),
                                    ('sex','sex_raw'),('color','color_raw'),('prdCty','production_country_raw')]:
                assert txt(profile[column]) == txt(raw.get(raw_key)), (horse_id, raw_key)
            assert profile['breed_label_raw'] == '제주마'
            manifest = read(Path(item['source']).parents[1] / 'attempt_manifest.json')
            assert profile['observed_at_utc'] == manifest['completed_at_utc']
            path = Path(item['source']).resolve()
            assert path.is_relative_to(SOURCE.resolve())
            raw_bytes = path.read_bytes()
            assert items(json.loads(raw_bytes)) == [raw]
            artifact = sources[profile['source_artifact_id']]
            assert artifact['raw_relative_path'] == path.relative_to(ROOT).as_posix()
            assert artifact['sha256'] == sha(raw_bytes)
            assert artifact['response_bytes'] == len(raw_bytes)
            probe = next(p for p in manifest['probes'] if str(p['queried_hr_no']) == horse_id)
            assert probe['response_sha256'] == artifact['sha256']
            assert artifact['collected_at_utc'] == manifest['completed_at_utc']
            assert artifact['http_status_code'] == probe['http_status'] == 200
            evidence = list(conn.execute('''SELECT * FROM breed_evidence
                WHERE horse_id=? AND api_record_id=?''', (horse_id, profile['api_record_id'])))
            assert len(evidence) == 1
            assert evidence[0]['source_artifact_id'] == profile['source_artifact_id']
            assert evidence[0]['observed_event_date'] is None
            assert evidence[0]['timing_basis'] == 'profile_retrieval_time'
        analysis = {r['starting_exam_api_row_id']: dict(r) for r in conn.execute('SELECT * FROM starting_exam_api_rows_analysis_2026')}
        assert len(analysis) == 10620
        for row in loaded.values():
            if row['exam_date'] > '2026-09-19':
                assert row['starting_exam_api_row_id'] not in analysis
                continue
            view = analysis[row['starting_exam_api_row_id']]
            profile = profiles[row['horse_id']]
            assert view['current_horse_name'] == profile['horse_name_raw']
            assert view['current_horse_age_2026'] == 2026 - int(str(profile['birth_date_raw'])[:4])
            assert view['sex_at_exam_raw'] == row['sex_raw']
            assert view['sex_current_profile'] == profile['sex_raw']
        assert conn.execute("SELECT COUNT(*) FROM starting_exam_api_rows WHERE rider_raw IS NULL").fetchone()[0] == 5795
        assert conn.execute("SELECT COUNT(*) FROM starting_exam_api_rows WHERE tr_name_raw='외부마' AND tr_no_raw='0BBBBB' AND trainer_id_normalized IS NULL").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM starting_exam_api_rows WHERE horse_id='3005897' AND sex_raw='수'").fetchone()[0] > 0
        assert profiles['3005897']['sex_raw'] == '암'
        for table in ['horse_profile_observations','starting_exam_api_rows','running_trial_rows','race_result_rows']:
            assert conn.execute(f'SELECT COUNT(*) FROM {table} WHERE horse_id=?', ('3005648',)).fetchone()[0] == 0
        violations = list(conn.execute('PRAGMA foreign_key_check'))
        assert not violations
        pragma = 'PRAGMA quick_check' if args.quick_check else 'PRAGMA integrity_check'
        integrity = [r[0] for r in conn.execute(pragma)]
        assert integrity == ['ok'], integrity
        report.update(status='passed', rows=len(loaded), horses=4636, profiles=len(profiles),
                      profiles_added=21, candidate_pages=len(page_cache), analysis_rows=len(analysis),
                      after_cutoff_rows=44, rider_null_rows=5795, multiple_round_groups=779,
                      judgment_counts=dict(labels), table_counts=counts,
                      old_schema_and_snapshot_rows_unchanged=True, foreign_key_violations=0,
                      existing_rows_verified_unchanged=old_rows_verified,
                      sqlite_check_pragma=pragma, sqlite_check_result=integrity, excluded_horse_active_rows=0,
                      verification_basis='Independent raw page + item position + payload + field comparison; no importer helper functions used')
    finally:
        conn.close()
    args.output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('table_counts','judgment_counts')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
