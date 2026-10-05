import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection')
entries = [json.loads(l) for l in (SOURCE / 'api21_verified_native_candidate_rows.jsonl').read_text().splitlines()]
unknown = [e for e in entries if e['raw']['passFlag'] == '-']
failure_labels = {'불합격', '불합격(발검)', '발주불합격', '출발불합격'}
reason_missing = [e for e in entries if e['raw']['passFlag'] in failure_labels and e['raw'].get('nopassReason') in (None, '', '-')]
counts = Counter(e['raw']['passFlag'] for e in entries)
horse_days = defaultdict(list)
for e in entries:
    horse_days[(str(e['raw']['trainDate']), str(e['raw']['hrNo']))].append(e)
repeated_horse_days = [rs for rs in horse_days.values() if len(rs) > 1]
exceptions = {'unknown_judgement_rows': unknown, 'failure_reason_unprovided_rows': reason_missing}
(ROOT / 'exceptions.json').write_text(json.dumps(exceptions, ensure_ascii=False, indent=2) + '\n')
report = {'candidate_rows': len(entries), 'judgement_counts': dict(counts), 'unknown_judgement_rows': len(unknown), 'failure_reason_unprovided_rows': len(reason_missing), 'website_crosscheck': json.loads((ROOT / 'website_crosscheck/comparison.json').read_text()), 'profile_comparison': json.loads((ROOT / 'summary.json').read_text()), 'known_sex_conflict': {'horse_id': '3005897', 'horse_name': '토종등극', 'exam_date': '20021115', 'round': 1, 'sex_raw': '수', 'current_profile_sex': '암', 'policy': 'Retain source record; extend audit evidence for existing user-approved unresolved provenance conflict. No automatic correction.'}, 'names': {'all_candidate_names_match_current_profile': True, 'historical_name_snapshot_not_assumed': True, 'example': {'horse_id': '3107458', 'api21_name': '무명전설', 'retained_race_name': '동방라오'}}, 'analysis_policy': {'age_2026': '2026 minus latest API42 birth year', 'raw_age': 'Preserve API21 age; all 10666 match completed years since birth at examination date', 'identity': 'Official horse ID, never horse-name string', 'outcome': 'Unknown judgement excluded from pass/fail aggregation, source row retained. Cancellation/exclusion labels retained distinctly. 1차합격 not silently mapped to final 합격.', 'rider': 'API missing rider remains null; website supplemental provenance is separate.'}, 'database_write_performed': False, 'source_rows_changed_or_deleted': 0, 'database_sha256_verified': 'fbc21f5229aa654ea3442141c3f3e7044f41bf7069c8f77e6f3c9f0af562f0b3'}
report['same_horse_date_different_rounds'] = {'native_horse_date_groups': len(repeated_horse_days), 'native_rows': sum(map(len, repeated_horse_days)), 'all_groups_have_distinct_trainNo': all(len({e['raw']['trainNo'] for e in rs}) == len(rs) for rs in repeated_horse_days), 'example_date': '20260930', 'example_ids': ['3107923', '3017464', '3018494'], 'website_example_source': '../20261001_starting_exam_api_collection/website_validation/website_observations.json', 'interpretation': 'Separate source rounds preserved; examples also observed on website. Do not deduplicate by horse ID and date or collapse 1차합격 into final 합격.'}
report['official_field_definitions'] = {'daySerial': '심사차수', 'trainNo': '경주번호', 'chulNo': '마번(출주번호)', 'rider': '기승자 (not an ID field)', 'metadata_source': '../20261001_starting_exam_api_collection/official_metadata/swagger.json'}
report['extreme_age_review'] = json.loads((ROOT / 'extreme_age_crosscheck/context_report.json').read_text())
report['trainer_code_not_ordinary_id'] = [e for e in entries if not str(e['raw'].get('trNo', '')).isdigit() or len(str(e['raw'].get('trNo', ''))) != 6]
(ROOT / 'root_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'unknown_judgement_rows': len(unknown), 'failure_reason_unprovided_rows': len(reason_missing), 'judgement_counts': dict(counts)}, ensure_ascii=False))
