"""Verify inventory totals and pin the read-only review's source evidence."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    inventory_path = HERE / 'local_inventory/daily_training_rider_identity_inventory.json'
    inventory = json.loads(inventory_path.read_text(encoding='utf-8'))
    web = json.loads((HERE / 'web_API_exact_event_verification.json').read_text(encoding='utf-8'))
    con = duckdb.connect(str(CORE / 'thoroughbred_core.duckdb'), read_only=True)
    con.execute('SET threads=2')
    observed = con.execute("""WITH profiles AS (
        SELECT DISTINCT official_id_raw_string FROM person_reference_profile_snapshots WHERE entity_type='jockey'
    ) SELECT count(*),count(*) FILTER(WHERE d.rider_id_raw='-'),
        count(*) FILTER(WHERE d.rider_id_raw!='-'),
        count(DISTINCT d.rider_id_raw) FILTER(WHERE d.rider_id_raw!='-'),
        count(*) FILTER(WHERE p.official_id_raw_string IS NOT NULL),
        count(DISTINCT d.rider_id_raw) FILTER(WHERE p.official_id_raw_string IS NOT NULL)
    FROM daily_training_raw d LEFT JOIN profiles p ON d.rider_id_raw=p.official_id_raw_string""").fetchone()
    con.close()
    assert observed == (5_173_033, 3_383_170, 1_789_863, 352, 1_599_488, 282)
    assert inventory['daily_training_identifier_inventory']['row_count'] == observed[0]
    assert inventory['direct_official_jockey_profile_comparison']['comparison']['daily_rows_with_exact_profile_id_match'] == observed[4]
    assert web['exact_event_rows'] == 1_247
    assert sum(v['web_rows'] for v in web['venues'].values()) == 1_248
    assert sum(v.get('web_name_matches_profile', 0) for v in web['venues'].values()) == 347
    assert sum(v.get('web_name_suffix_only_variation', 0) for v in web['venues'].values()) == 51
    assert sum(v.get('web_name_not_in_profile_candidates', 0) for v in web['venues'].values()) == 1
    manifest = json.loads((CORE / 'manifest.json').read_text(encoding='utf-8'))
    actual_db_sha = sha(CORE / 'thoroughbred_core.duckdb')
    assert actual_db_sha == manifest['database_sha256'] == 'c46286df4773a7ffcea4c7bc431e2cd2a8fc03a4c38fdaa4403bd8f39c2a1668'
    files = [inventory_path, HERE / 'web_API_exact_event_verification.json', HERE / 'web_API_exact_event_rows.jsonl',
             HERE / 'official_web/capture_manifest.jsonl', HERE / 'capture_public_pages.py',
             HERE / 'verify_daily_web_rows.py', Path(__file__).resolve()]
    receipts = [json.loads(line) for line in (HERE / 'official_web/capture_manifest.jsonl').read_text(encoding='utf-8').splitlines()]
    for item in receipts:
        path = (HERE / item['raw_file']).resolve()
        assert path.is_relative_to(HERE.resolve()) and sha(path) == item['sha256']
        files.append(path)
    result = {'status': 'REVIEW_COMPLETE_WITH_SOURCE_EXCEPTIONS', 'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'database_sha256': actual_db_sha, 'database_writes': False, 'database_still_matches_prior_manifest': True,
              'inventory_recomputed_by_root': list(observed),
              'name_linkage': {'exact_ID_profile_candidate_rows': 1_599_488, 'candidate_IDs': 282,
                               'not_automatically_confirmed_for_all_historical_events': True,
                               'number_present_unmatched_rows': 190_375, 'number_absent_rows': 3_383_170},
              'official_web_sample': {'date': '2026-09-28', 'web_rows': 1248, 'unique_event_matches': 1247,
                                      'exact_name_matches': 347, 'name_with_literal_suffix_only': 51,
                                      'actual_person_name_conflicts': 1, 'stable_number_differences': 4,
                                      'unmatched_event_rows': 1},
              'schema_or_entity_links_applied': False,
              'proof_files': [{'path': path.resolve().relative_to(ROOT.resolve()).as_posix(), 'sha256': sha(path)} for path in files]}
    (HERE / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key!='proof_files'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
