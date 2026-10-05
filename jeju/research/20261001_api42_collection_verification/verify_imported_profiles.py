"""Compare every imported profile and its provenance to immutable API42 raw bytes."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COLLECTION = HERE.parent / '20260930_api42_horse_breed_collection'


def main():
    events = {}
    for line in (COLLECTION / 'request_ledger.jsonl').read_text().splitlines():
        event = json.loads(line)
        events[event['hrNo']] = event
    if len(events) != 4617 or any(e['validation_status'] != 'validated' for e in events.values()):
        raise ValueError('Collection incomplete')
    conn = sqlite3.connect((ROOT / 'jeju/data/jeju_native_core.sqlite3').as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    imported = list(conn.execute('''SELECT h.*,a.payload_json,a.payload_sha256,a.source_artifact_id,
            s.sha256 AS source_sha256,s.raw_relative_path,s.response_bytes,s.http_status_code,
            s.operation,s.public_dataset_id,s.request_params_json,s.collected_at_utc,s.source_role
        FROM horse_profile_observations h JOIN api_records a USING(api_record_id)
        JOIN source_artifacts s USING(source_artifact_id) ORDER BY h.horse_id'''))
    if len(imported) != 4617 or {row['horse_id'] for row in imported} != set(events):
        raise ValueError('DB profile target mismatch')
    evidence_ids = set()
    dates = Counter()
    normalized = {'hrNm':'horse_name_raw', 'birthDt':'birth_date_raw', 'age':'age_raw',
                  'breed':'breed_label_raw', 'sex':'sex_raw', 'color':'color_raw', 'prdCty':'production_country_raw'}
    for row in imported:
        event = events[row['horse_id']]
        expected_path = (COLLECTION / event['raw_response_file']).resolve()
        actual_path = (ROOT / row['raw_relative_path']).resolve()
        if actual_path != expected_path or not actual_path.is_relative_to((COLLECTION / 'raw').resolve()):
            raise ValueError('Wrong source path')
        raw = actual_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row['source_sha256'] or row['source_sha256'] != event['response_sha256']:
            raise ValueError('Raw response hash mismatch')
        if len(raw) != row['response_bytes'] or row['http_status_code'] != 200:
            raise ValueError('HTTP metadata mismatch')
        response = json.loads(raw)['response']
        if str(response['header']['resultCode']) not in {'00','0000'} or int(response['body']['totalCount']) != 1:
            raise ValueError('API response not successful')
        item = response['body']['items']['item']
        item = item[0] if isinstance(item, list) and len(item) == 1 else item
        stored_item = json.loads(row['payload_json'])
        if not isinstance(item, dict) or json.dumps(stored_item, sort_keys=True, ensure_ascii=False) != json.dumps(item, sort_keys=True, ensure_ascii=False):
            raise ValueError('Stored full item differs from API source')
        if hashlib.sha256(row['payload_json'].encode()).hexdigest() != row['payload_sha256']:
            raise ValueError('Stored item hash mismatch')
        if str(item['hrNo']) != row['horse_id']:
            raise ValueError('Horse ID mismatch')
        for field, column in normalized.items():
            if str(item[field]) != row[column]:
                raise ValueError('Normalized raw field mismatch: ' + field)
        if row['observed_at_utc'] != event['retrieved_at_utc'] or row['collected_at_utc'] != event['retrieved_at_utc']:
            raise ValueError('Observation time differs from collection')
        expected_date = datetime.fromisoformat(event['retrieved_at_utc']).astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
        if row['observed_kst_date'] != expected_date:
            raise ValueError('Observation KST date mismatch')
        if row['operation'] != 'totalHorseInfo_1' or row['public_dataset_id'] != '15057985' or row['source_role'] != 'primary':
            raise ValueError('Wrong API identity')
        params = json.loads(row['request_params_json'])
        if params.get('hr_no') != row['horse_id'] or any('key' in key.casefold() for key in params):
            raise ValueError('Public request parameters incorrect')
        evidence = list(conn.execute('SELECT * FROM breed_evidence WHERE api_record_id=?', (row['api_record_id'],)))
        if len(evidence) != 1:
            raise ValueError('Expected one breed evidence per profile')
        evidence = evidence[0]
        if evidence['horse_id'] != row['horse_id'] or evidence['breed_label_raw'] != item['breed'] or evidence['source_artifact_id'] != row['source_artifact_id']:
            raise ValueError('Breed evidence FK or value mismatch')
        if evidence['observed_event_date'] is not None or evidence['evidence_kind'] == 'API20_1 majong observation':
            raise ValueError('Current breed observation mixed with event-date evidence')
        evidence_ids.add(evidence['breed_evidence_id'])
        dates[row['observed_kst_date']] += 1
    latest = list(conn.execute('SELECT horse_id,api_record_id FROM horse_profile_latest'))
    if {tuple(row) for row in latest} != {(r['horse_id'],r['api_record_id']) for r in imported} or len(latest) != 4617:
        raise ValueError('Latest profile view incorrect')
    race_ids = {r[0] for r in conn.execute('SELECT DISTINCT horse_id FROM jeju_race_population_candidates')}
    trial_ids = {r[0] for r in conn.execute('SELECT DISTINCT horse_id FROM running_trial_rows')}
    result = {'profiles_verified':len(imported), 'unique_horse_ids':len(events),
              'full_api_items_equal_archived_source':True, 'source_and_item_hashes_verified':True,
              'normalized_fields_verified':list(normalized), 'observation_dates_kst':dict(dates),
              'current_profile_breed_evidence_verified':len(evidence_ids),
              'latest_profile_view_verified':len(latest),
              'race_candidate_horse_ids_linked':len(set(events) & race_ids),
              'trial_horse_ids_linked':len(set(events) & trial_ids),
              'unmatched_race_candidate_horse_ids':sorted(race_ids-set(events)),
              'history_not_reclassified':True}
    if result['unmatched_race_candidate_horse_ids']:
        raise ValueError('Missing race candidate profile')
    (HERE/'db_profile_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False))
    conn.close()


if __name__ == '__main__':
    main()
