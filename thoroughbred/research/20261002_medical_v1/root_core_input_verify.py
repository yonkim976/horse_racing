"""Independent input/core typed row parity and clinical linking safeguards."""
import hashlib
import json
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'
S, D = HERE / 'source', HERE / 'dictionary'
INPUTS = {
    'medical_observations': [S / name for name in ('api16_current_annual_observations.parquet', 'api16_archived_daily_observations.parquet', 'dacom72_observations.parquet')],
    'medical_api16_page_ledger': [S / 'api16_page_ledger.parquet'],
    'medical_api16_year_meet_coverage': [S / 'api16_year_meet_coverage.parquet'],
    'medical_api16_archived_page_ledger': [S / 'api16_archived_page_ledger.parquet'],
    'medical_archived_daily_coverage': [S / 'archived_daily_coverage.parquet'],
    'medical_api16_current_exclusions': [S / 'api16_current_annual_exclusions.parquet'],
    'medical_api16_archived_exclusions': [S / 'api16_archived_exclusions.parquet'],
    'medical_existing_raw_inventory': [S / 'existing_raw_inventory.parquet'],
    'medical_dacom72_file_ledger': [S / 'dacom72_file_ledger.parquet'],
    'medical_dacom72_exclusions': [S / 'dacom72_exclusions.parquet'],
    'medical_dacom72_layout_reconciliation': [S / 'dacom72_layout_reconciliation.parquet'],
    'medical_dacom72_year_meet_coverage': [S / 'dacom72_year_meet_coverage.parquet'],
    'medical_api_comparison_ledger': [S / 'medical_api_comparison_ledger.parquet'],
    'medical_fingerprint_candidates': [S / 'medical_fingerprint_candidates.parquet'],
    'medical_source_year_meet_coverage': [S / 'source_year_meet_coverage.parquet'],
    **{'medical_' + name: [D / (name + '.parquet')] for name in ('api33_source_rows', 'api33_terms', 'phrase_decisions', 'phrase_components', 'explanation_observations', 'explanation_terms')},
}


def qi(value):
    return '"' + value.replace('"', '""') + '"'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    con = duckdb.connect(str(CORE / 'thoroughbred_core.duckdb'), read_only=True)
    con.execute("SET memory_limit='2GB'")
    con.execute('SET threads=2')
    con.execute('SET preserve_insertion_order=false')
    parity = {}
    for table, files in INPUTS.items():
        quoted = '[' + ','.join("'" + str(path).replace("'", "''") + "'" for path in files) + ']'
        source = 'read_parquet(' + quoted + ')'
        cols = con.execute('DESCRIBE ' + qi(table)).fetchall()
        assert cols == con.execute('DESCRIBE SELECT * FROM ' + source).fetchall(), table
        expr = 'sha256(to_json(struct_pack(' + ','.join(qi(c[0]) + ':=' + qi(c[0]) for c in cols) + ')))'
        added = con.execute(f'SELECT count(*) FROM (SELECT {expr} FROM {qi(table)} EXCEPT ALL SELECT {expr} FROM {source})').fetchone()[0]
        lost = con.execute(f'SELECT count(*) FROM (SELECT {expr} FROM {source} EXCEPT ALL SELECT {expr} FROM {qi(table)})').fetchone()[0]
        assert added == lost == 0, table
        parity[table] = {'added': added, 'lost': lost, 'columns': len(cols)}
        print(json.dumps({'stage': 'input_core_parity', 'table': table}), flush=True)
    metadata_checks = {}
    for table in ('medical_source_metadata', 'medical_dictionary_metadata'):
        rows = con.execute('SELECT source_path,source_sha256,metadata_json FROM ' + qi(table)).fetchall()
        for relative, digest, literal in rows:
            path = (ROOT / relative).resolve(strict=True)
            assert path.is_relative_to(ROOT.resolve()) and path.is_file(), relative
            assert sha(path) == digest and path.read_text(encoding='utf-8') == literal, relative
        metadata_checks[table] = len(rows)
    manifest = json.loads((CORE / 'manifest.json').read_text())
    for item in manifest['input_files']:
        if item.get('loaded_to_database') and '/20261002_medical_v1/' in item['path']:
            assert item['table'] in INPUTS, item
            assert (ROOT / item['path']).resolve() in INPUTS[item['table']], item
            assert sha(ROOT / item['path']) == item['sha256'], item
    expected = json.loads((HERE / 'root_expected_horse_links.json').read_text())['independent_source_roster_counts']
    actual = con.execute('SELECT source_kind,source_cohort,link_status,count(*),count(DISTINCT source_official_id) FROM medical_entity_links GROUP BY ALL').fetchall()
    assert set(actual) == {(r['source_kind'],r['source_cohort'],r['link_status'],r['rows'],r['distinct_source_ids']) for r in expected}
    assert con.execute("SELECT count(*) FROM medical_observations WHERE meet_code NOT IN (1,3) OR event_date<'2010-01-01' OR event_date>'2026-09-29'").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM medical_entity_links WHERE source_kind='dacom72' AND (linked_horse_official_id IS NOT NULL OR source_official_id IS NOT NULL)").fetchone()[0] == 0
    assert con.execute('SELECT count(*) FROM medical_api_comparison_ledger WHERE automatically_linked').fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM medical_observed_diagnosis_components WHERE mapping_disposition='reviewed_exact_phrase_component_metadata_only' AND (review_status IS DISTINCT FROM 'confirmed_review_mapping' OR mapping_rule_scope IS DISTINCT FROM 'reviewed_phrase_candidate_only' OR phrase_contextual_evidence_required IS DISTINCT FROM FALSE OR prefix_rule_reusable=FALSE)").fetchone()[0] == 0
    assert con.execute('SELECT count(*) FROM medical_observed_diagnosis_explanations WHERE source_publication_at_kst IS NOT NULL OR description_text IS NULL OR description_text=\'\'').fetchone()[0] == 0
    assert con.execute('SELECT count(*) FROM medical_current_api_records WHERE historical_publication_time_verified').fetchone()[0] == 0
    summary = {}
    for name, query in {
        'horse_link_counts': 'SELECT source_kind,source_cohort,link_status,count(*) n FROM medical_entity_links GROUP BY ALL ORDER BY 1,3',
        'current_api_phrase_states': 'SELECT exact_phrase_review_status,count(*) n,count(DISTINCT illness_raw) phrases FROM medical_api16_current_phrase_review GROUP BY ALL',
        'text_phrase_states': 'SELECT exact_phrase_review_status,count(*) fingerprint_candidates,sum(occurrence_count) raw_occurrences,count(DISTINCT diagnosis_rpt_raw) phrases FROM medical_text_phrase_review GROUP BY ALL',
        'explanation_distinct_source_slots': 'SELECT source_kind,source_cohort,count(DISTINCT (observation_locator,source_slot_kind)) slots,count(*) capture_component_rows FROM medical_observed_diagnosis_explanations GROUP BY ALL',
    }.items():
        cur = con.execute(query)
        labels = [c[0] for c in cur.description]
        summary[name] = [dict(zip(labels,row)) for row in cur.fetchall()]
    con.close()
    report = {'all_passed': True, 'input_table_parity': parity, 'metadata_checks': metadata_checks, 'summary': summary,
              'verification_script_sha256': sha(Path(__file__))}
    (HERE / 'root_core_input_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
