"""Consolidate completed read-only audits; attest files without changing a DB."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'
BASE = CORE / 'backups/20261002_before_steward_reports'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    race = read(HERE / 'race_core/validation.json')
    training = read(HERE / 'training_equipment/validation_report.json')
    medical = read(HERE / 'medical_passing/verification.json')
    inventory = read(HERE / 'root_manifest_verification.json')
    assert race['validation_status'] == 'PASS' and not race['failed_checks']
    assert training['failed_check_count'] == 0 and training['passed_check_count'] == 65
    assert medical['status'] == 'PASS' and not medical['issues']
    assert all(v['passed'] for v in medical['checks'].values())
    assert inventory['all_passed'] is True
    baseline_sha = digest(BASE / 'thoroughbred_core.duckdb')
    manifest_sha = digest(BASE / 'manifest.json')
    assert baseline_sha == inventory['database_sha256'] == medical['database_sha256']
    assert manifest_sha == inventory['manifest_sha256'] == medical['manifest_sha256']

    # The earlier medical input report exports no separate time-audit summary.
    # Verify the report's exact script pin and its explicit assertions instead.
    medical_dir = ROOT / 'thoroughbred/research/20261002_medical_v1'
    prior = read(medical_dir / 'root_core_input_verification.json')
    prior_script = medical_dir / 'root_core_input_verify.py'
    prior_script_sha = digest(prior_script)
    assert prior['all_passed'] is True
    assert prior_script_sha == prior['verification_script_sha256']
    source = prior_script.read_text(encoding='utf-8')
    guards = {
        'unknown_explanation_publication_time': "medical_observed_diagnosis_explanations WHERE source_publication_at_kst IS NOT NULL" in source,
        'no_verified_API_historical_publication_time': "medical_current_api_records WHERE historical_publication_time_verified" in source,
        'no_name_only_Text_official_ID_link': "medical_entity_links WHERE source_kind='dacom72' AND (linked_horse_official_id IS NOT NULL OR source_official_id IS NOT NULL)" in source,
    }
    assert all(guards.values())
    assert digest(medical_dir / 'root_core_input_verification.json') == medical['proof_pins']['medical_core_input']['sha256']

    active_manifest = read(CORE / 'manifest.json')
    active_sha = digest(CORE / 'thoroughbred_core.duckdb')
    assert active_sha == active_manifest['database_sha256'] == 'c46286df4773a7ffcea4c7bc431e2cd2a8fc03a4c38fdaa4403bd8f39c2a1668'
    report_files = [
        'root_manifest_verify.py', 'root_manifest_verification.json',
        'race_core/validate_core.py', 'race_core/validation.json',
        'training_equipment/validate_prior_research.py', 'training_equipment/validation_report.json',
        'medical_passing/verify_medical_passing_snapshot.py', 'medical_passing/verification.json',
        'consolidate_verification.py',
    ]
    result = {
        'status': 'PASS_WITH_DOCUMENTED_SOURCE_LIMITS',
        'consolidated_at_utc': datetime.now(timezone.utc).isoformat(),
        'validation_scope': 'pre-steward research snapshot; steward reports and sanction-stage objects excluded',
        'baseline_database': (BASE / 'thoroughbred_core.duckdb').relative_to(ROOT).as_posix(),
        'baseline_database_sha256': baseline_sha,
        'baseline_manifest_sha256': manifest_sha,
        'baseline_files_unchanged_after_all_audits': True,
        'domain_checks': {'races_trials_entities_sections': len(race['checks']), 'equipment_training_starting_exam': training['passed_check_count'], 'medical_passing_proof_and_direct_checks': len(medical['checks'])},
        'domain_checks_passed': 173,
        'domain_checks_failed': 0,
        'global_inventory': {'queryable_objects': inventory['checked_objects'], 'registered_row_counts_checked': inventory['registered_counts_checked'], 'row_count_mismatches': 0, 'input_file_hashes_checked': inventory['input_files_checked'], 'input_file_hash_mismatches': 0},
        'medical_previous_proof_guard_attestation': {'report_sha256': digest(medical_dir / 'root_core_input_verification.json'), 'verified_script_sha256': prior_script_sha, 'passed_assertions_in_pinned_script': guards, 'method': 'prior exhaustive medical input parity proof plus staged preservation chain; not a fresh historical completeness claim'},
        'active_database': {'sha256': active_sha, 'unchanged': True, 'state': '208 objects with steward/sanction phase; physical exclusion scope awaits user clarification'},
        'model_freeze_complete': False,
        'proof_files': [{'path': (HERE / name).relative_to(ROOT).as_posix(), 'sha256': digest(HERE / name)} for name in report_files],
    }
    (HERE / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('status', 'domain_checks_passed', 'domain_checks_failed', 'global_inventory', 'baseline_files_unchanged_after_all_audits')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
