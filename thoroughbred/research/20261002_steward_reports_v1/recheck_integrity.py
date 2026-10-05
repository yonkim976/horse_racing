"""Read-only post-load audit; leave the original frozen proof files intact."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    baseline = json.loads((HERE / 'root_preservation_verification.json').read_text())
    manifest = json.loads(DB.with_name('manifest.json').read_text())
    before = sha(DB)
    assert before == baseline['database_sha256'] == manifest['database_sha256']
    contract = json.loads((HERE / 'loader/input_contract.json').read_text())
    for relative, pin in contract['file_pins'].items():
        path = (ROOT / relative).resolve()
        assert path.is_relative_to(ROOT.resolve()) and path.is_file()
        assert path.stat().st_size == pin['bytes'] and sha(path) == pin['sha256'], relative
    con = duckdb.connect(str(DB), read_only=True)
    con.execute("SET memory_limit='2GB'")
    con.execute('SET threads=2')
    pages = con.execute('SELECT raw_page_path,response_body_sha256,response_body_bytes FROM steward_api_page_ledger').fetchall()
    for relative, digest, size in pages:
        path = (HERE / 'source' / relative).resolve()
        assert path.is_relative_to((HERE / 'source').resolve())
        assert path.stat().st_size == size and sha(path) == digest
    queries = {
        'source_observation_locator_duplicates': "SELECT count(*) FROM (SELECT observation_locator FROM steward_api_source_observations GROUP BY 1 HAVING count(*)<>1)",
        'raw_item_digest_mismatches': "SELECT count(*) FROM steward_api_source_observations WHERE sha256(raw_item_json) IS DISTINCT FROM source_row_sha256",
        'in_scope_source_violations': "SELECT count(*) FROM steward_api_source_observations WHERE row_scope_status='included' AND (actual_meet_code NOT IN (1,3,4) OR try_cast(race_date_iso AS DATE) NOT BETWEEN DATE '2010-01-01' AND DATE '2026-09-29' OR try_cast(race_date_iso AS DATE) IS NULL)",
        'missing_target_roster_links': "SELECT count(*) FROM steward_report_horse_links l WHERE NOT EXISTS (SELECT 1 FROM runner_results r WHERE try_cast(r.source_meet AS INTEGER)=l.target_actual_meet_code AND r.result_date=replace(l.target_event_date,'-','') AND try_cast(r.result_race_no AS INTEGER)=l.target_race_no AND try_cast(r.horse_program_no_raw AS INTEGER)=try_cast(l.program_no_raw AS INTEGER) AND r.horse_id_raw=l.official_horse_id AND r.horse_name_raw=l.roster_horse_name_raw)",
        'duplicate_horse_paragraph_links': "SELECT count(*) FROM (SELECT paragraph_locator,official_horse_id FROM steward_report_horse_links GROUP BY 1,2 HAVING count(*)<>1)",
        'wrong_or_unresolved_supplement_target_links': "SELECT count(*) FROM steward_report_horse_links l JOIN steward_report_paragraphs p USING(paragraph_locator) WHERE p.report_text_field='addJudgement' AND (p.target_context_status<>'add_judgement_exact_leading_date_race_context' OR l.target_event_date>p.parent_event_date OR l.target_actual_meet_code<>p.parent_actual_meet_code)",
        'paragraph_source_slice_mismatches': "SELECT count(*) FROM steward_report_paragraphs WHERE substr(paragraph_source_text_raw,span_start_codepoint+1,span_end_codepoint-span_start_codepoint) IS DISTINCT FROM paragraph_raw",
        'missing_paragraph_or_report_reference': "SELECT count(*) FROM steward_report_horse_links l LEFT JOIN steward_report_paragraphs p USING(paragraph_locator) LEFT JOIN steward_report_observations o ON o.observation_locator=l.observation_locator WHERE p.paragraph_locator IS NULL OR o.observation_locator IS NULL OR p.observation_locator<>l.observation_locator",
        'linked_unapproved_mentions': "SELECT count(*) FROM steward_report_horse_links l CROSS JOIN UNNEST(from_json(l.linked_mention_locators_json,'[\"VARCHAR\"]')) a(mid) LEFT JOIN steward_report_horse_mentions m ON m.mention_locator=a.mid WHERE m.mention_locator IS NULL OR m.candidate_official_horse_id IS DISTINCT FROM l.official_horse_id OR m.paragraph_locator IS DISTINCT FROM l.paragraph_locator OR m.candidate_status NOT IN ('explicit_number_name_race_roster_exact','explicit_number_name_venue_prefix_exact','report_local_exact_name_from_unique_anchor')",
        'invalid_horse_id_formats': "SELECT count(*) FROM steward_report_horse_links WHERE NOT regexp_full_match(official_horse_id,'[0-9]{7}') OR official_horse_id IS NULL",
        'unverified_sanction_event_target_links': "SELECT count(*) FROM steward_sanction_target_link_audit WHERE exact_target_entry_match_count<>1 OR NOT target_event_entry_link_verified OR NOT target_entity_reference_verified",
        'unsupported_sanction_targets': "SELECT count(*) FROM steward_sanction_target_link_audit WHERE target_entity_type NOT IN ('horse','jockey') OR target_entity_type IS NULL",
        'missing_canonical_origin_observations': "SELECT count(*) FROM horse_steward_history h CROSS JOIN UNNEST(from_json(h.full_report_observation_locators_json,'[\"VARCHAR\"]')) a(oid) LEFT JOIN steward_report_observations o ON o.observation_locator=a.oid WHERE o.observation_locator IS NULL OR o.actual_meet_code<>h.parent_report_meet_code OR o.race_date_iso<>h.parent_report_event_date",
        'canonical_origin_count_mismatches': "SELECT count(*) FROM horse_steward_history WHERE json_array_length(full_report_observation_locators_json)<>full_report_observation_count",
        'false_publication_time_claims': "SELECT count(*) FROM steward_api_source_observations WHERE historical_publication_time_verified OR source_publication_at_kst IS NOT NULL",
    }
    violations = {name: con.execute(query).fetchone()[0] for name, query in queries.items()}
    assert not any(violations.values()), violations
    assert con.execute('SELECT sum(full_report_observation_count) FROM horse_steward_history').fetchone()[0] == 149008
    candidate_counts = dict(con.execute('SELECT candidate_status,count(*) FROM steward_report_horse_link_candidates GROUP BY 1').fetchall())
    coverage = con.execute("SELECT execution_status,count(*),sum(report_observation_count=0) FROM steward_report_event_coverage GROUP BY 1 ORDER BY 1").fetchall()
    namediff = con.execute('SELECT count(*) FROM steward_sanction_target_link_audit WHERE NOT target_name_exact_roster_match').fetchone()[0]
    con.close()
    assert sha(DB) == before
    result = {'all_passed': True, 'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'read_only': True,
              'database_sha256_unchanged': before, 'frozen_inputs_checked': len(contract['file_pins']),
              'raw_pages_checked': len(pages), 'integrity_violation_counts': violations,
              'known_unresolved_candidate_counts': candidate_counts, 'event_coverage': coverage,
              'known_sanction_name_display_differences': namediff, 'historical_publication_time_verified': False}
    (HERE / 'recheck_integrity.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
