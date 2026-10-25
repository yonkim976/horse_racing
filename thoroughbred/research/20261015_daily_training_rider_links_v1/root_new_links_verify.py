"""Independent read-only checks of the applied daily-training rider-name links."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'
REVIEW = ROOT / 'thoroughbred/research/20261015_daily_training_rider_identity_review_v1'
HOLD_ID = 'api18_1:api18-monthly-m1-202609-fresh-8667fb7f6c:7c2ef0c7e449dc216e246dd4b6a05eeba3bc806e6239dea181603bf34f305bed:p1:r1345'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    expected = json.loads((HERE / 'root_expected_mapping_and_unmatched.json').read_text(encoding='utf-8'))
    web = [json.loads(line) for line in (REVIEW / 'web_API_exact_event_rows.jsonl').read_text(encoding='utf-8').splitlines()]
    c = duckdb.connect(str(CORE / 'thoroughbred_core.duckdb'), read_only=True)
    c.execute('SET threads=2')
    c.execute("SET memory_limit='2GB'")
    scratch = HERE / 'new_link_verification_scratch'
    scratch.mkdir(exist_ok=True)
    c.execute("SET temp_directory='" + str(scratch).replace("'", "''") + "'")
    checks = {}

    def check(name, condition, detail):
        checks[name] = {'passed': bool(condition), 'details': detail}
        if not condition:
            raise AssertionError((name, detail))

    mapping = c.execute('SELECT rider_id_raw,name_snapshot,official_jockey_id_raw_string FROM rider_name_links').fetchall()
    check('mapping_exact_ID_and_name_pairs', len(mapping)==282 and {(x[0],x[1]) for x in mapping}=={(x['number'],x['name']) for x in expected['mapping']} and all(x[0]==x[2] for x in mapping), {'mapping_rows': len(mapping)})
    actual_status = dict(c.execute('SELECT rider_identity_status,count(*) FROM daily_training_rider_linked GROUP BY 1').fetchall())
    wanted_status = {'exact_official_profile_id_name_link': 1_599_487, 'source_conflict_hold': 1, 'pr_no_absent': 3_383_170, 'profile_id_unmatched': 190_375}
    check('linked_and_unresolved_partition', actual_status==wanted_status and sum(actual_status.values())==5_173_033, actual_status)
    violations = c.execute("""SELECT count(*) FROM daily_training_rider_linked WHERE
        (rider_identity_status='exact_official_profile_id_name_link' AND (rider_name_linked IS NULL OR rider_official_id_linked IS DISTINCT FROM rider_id_raw)) OR
        (rider_identity_status!='exact_official_profile_id_name_link' AND (rider_name_linked IS NOT NULL OR rider_official_id_linked IS NOT NULL))""").fetchone()[0]
    check('no_unapproved_link_and_no_missing_linked_name', violations==0, {'violations': violations})
    hold = c.execute('SELECT horse_name_raw,event_date,meet,rider_id_raw,rider_name_candidate,rider_name_linked,rider_official_id_linked,event_verification_web_rider_display_raw,rider_identity_status FROM daily_training_rider_linked WHERE observation_id=?', [HOLD_ID]).fetchall()
    check('single_Songdang_Sky_event_held', len(hold)==1 and hold[0][0]=='송당스카이' and str(hold[0][1])=='2026-09-28' and hold[0][2:] == ('1','080608','오수철',None,None,'유승완','source_conflict_hold'), {'record': hold})
    others = c.execute("SELECT count(*),count(*) FILTER(WHERE rider_identity_status!='exact_official_profile_id_name_link' OR rider_name_linked!='오수철') FROM daily_training_rider_linked WHERE rider_id_raw='080608' AND observation_id!=?", [HOLD_ID]).fetchone()
    check('same_number_other_events_not_held', others[0]>0 and others[1]==0, {'other_080608_rows': others[0], 'incorrectly_held_or_named': others[1]})
    duplicate = c.execute('SELECT count(*) FROM (SELECT observation_id FROM daily_training_rider_linked GROUP BY 1 HAVING count(*)!=1)').fetchone()[0]
    check('no_view_row_multiplication', duplicate==0, {'duplicate_observation_ids': duplicate})

    cur = c.execute('SELECT rider_id_raw,daily_training_rows,first_event_date,last_event_date,observed_meets_json,observed_rider_types_json FROM rider_unmatched_ids')
    actual_unmatched = {row[0]: {'rows': row[1], 'first_date': str(row[2]), 'last_date': str(row[3]), 'source_meets': sorted(json.loads(row[4])), 'roles': sorted(json.loads(row[5]))} for row in cur.fetchall()}
    wanted_unmatched = {row['number']: {key: row[key] for key in ('rows','first_date','last_date','source_meets','roles')} for row in expected['unmatched']}
    check('all_70_unmatched_numbers_and_metadata', actual_unmatched==wanted_unmatched, {'numbers': len(actual_unmatched), 'rows': sum(row['rows'] for row in actual_unmatched.values())})
    horse_diffs = c.execute("""WITH actual AS (SELECT d.rider_id_raw,count(DISTINCT d.official_horse_id) horses
        FROM daily_training_raw d JOIN rider_unmatched_ids u ON d.rider_id_raw=u.rider_id_raw GROUP BY 1)
        SELECT count(*) FROM actual a JOIN rider_unmatched_ids u ON a.rider_id_raw=u.rider_id_raw WHERE a.horses!=u.distinct_horse_count""").fetchone()[0]
    check('unmatched_distinct_horse_counts', horse_diffs==0, {'mismatches': horse_diffs})
    actual_web = dict(c.execute('SELECT observation_id,source_record_json FROM rider_web_event_verification').fetchall())
    check('web_evidence_full_source_parity', len(actual_web)==1247 and actual_web.keys()=={row['observation_id'] for row in web} and all(json.loads(actual_web[row['observation_id']])==row for row in web), {'web_evidence_rows': len(actual_web)})
    provenance_bad = c.execute("""SELECT count(*) FROM rider_name_links m LEFT JOIN person_reference_profile_snapshots p
        ON p.entity_type='jockey' AND m.rider_id_raw=p.official_id_raw_string AND m.name_snapshot=p.name_snapshot
        AND m.source_service=p.source_service AND CAST(m.source_capture_date AS VARCHAR)=p.capture_date
        AND m.source_file=p.source_file AND m.source_sha256=p.source_sha256
        WHERE p.official_id_raw_string IS NULL""").fetchone()[0]
    check('name_link_provenance_matches_profile_snapshot', provenance_bad==0, {'unmatched_provenance': provenance_bad})
    old_cols = [row[0] for row in c.execute('DESCRIBE daily_training_raw').fetchall()]
    new_cols = [row[0] for row in c.execute('DESCRIBE daily_training_rider_linked').fetchall()]
    check('raw_columns_retained_at_view_start', new_cols[:len(old_cols)]==old_cols, {'raw_columns': len(old_cols), 'enriched_columns': len(new_cols)})
    c.close()
    manifest = json.loads((CORE / 'manifest.json').read_text(encoding='utf-8'))
    db_sha = sha(CORE / 'thoroughbred_core.duckdb')
    check('manifest_database_sha', db_sha==manifest['database_sha256'], {'database_sha256': db_sha})
    report = {'all_passed': True, 'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'read_only': True, 'checks': checks,
              'database_sha256': db_sha, 'verification_script_sha256': sha(Path(__file__)),
              'root_expected_input_sha256': sha(HERE / 'root_expected_mapping_and_unmatched.json')}
    (HERE / 'root_new_links_verification.json').write_text(json.dumps(report, ensure_ascii=False,default=str,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'all_passed': True, 'checks_passed': len(checks), 'database_sha256': db_sha}, ensure_ascii=False))


if __name__ == '__main__':
    main()
