-- Medical research load v1. Inputs are bound by load_medical.py as input_* views.
-- This schema preserves source occurrence rows and raw literal diagnosis slots.
CREATE TABLE medical_observations AS
SELECT * FROM input_medical_observations;

CREATE TABLE medical_api16_page_ledger AS SELECT * FROM input_api16_page_ledger;
CREATE TABLE medical_api16_year_meet_coverage AS SELECT * FROM input_api16_year_meet_coverage;
CREATE TABLE medical_api16_archived_page_ledger AS SELECT * FROM input_api16_archived_page_ledger;
CREATE TABLE medical_archived_daily_coverage AS SELECT * FROM input_archived_daily_coverage;
CREATE TABLE medical_api16_current_exclusions AS SELECT * FROM input_api16_current_exclusions;
CREATE TABLE medical_api16_archived_exclusions AS SELECT * FROM input_api16_archived_exclusions;
CREATE TABLE medical_existing_raw_inventory AS SELECT * FROM input_existing_raw_inventory;
CREATE TABLE medical_dacom72_file_ledger AS SELECT * FROM input_dacom72_file_ledger;
CREATE TABLE medical_dacom72_exclusions AS SELECT * FROM input_dacom72_exclusions;
CREATE TABLE medical_dacom72_layout_reconciliation AS SELECT * FROM input_dacom72_layout_reconciliation;
CREATE TABLE medical_dacom72_year_meet_coverage AS SELECT * FROM input_dacom72_year_meet_coverage;
CREATE TABLE medical_api_comparison_ledger AS SELECT * FROM input_medical_api_comparison_ledger;
CREATE TABLE medical_fingerprint_candidates AS SELECT * FROM input_medical_fingerprint_candidates;
CREATE TABLE medical_source_year_meet_coverage AS SELECT * FROM input_source_year_meet_coverage;
CREATE TABLE medical_source_metadata AS SELECT * FROM input_source_metadata;
CREATE TABLE medical_source_output_hashes AS SELECT * FROM input_medical_source_output_hashes;

CREATE TABLE medical_api33_source_rows AS SELECT * FROM input_api33_source_rows;
CREATE TABLE medical_api33_terms AS SELECT * FROM input_api33_terms;
CREATE TABLE medical_phrase_decisions AS SELECT * FROM input_phrase_decisions;
CREATE TABLE medical_phrase_components AS SELECT * FROM input_phrase_components;
CREATE TABLE medical_explanation_observations AS SELECT * FROM input_explanation_observations;
CREATE TABLE medical_explanation_terms AS SELECT * FROM input_explanation_terms;
CREATE TABLE medical_dictionary_metadata AS SELECT * FROM input_dictionary_metadata;
CREATE TABLE medical_dictionary_output_hashes AS SELECT * FROM input_medical_dictionary_output_hashes;

-- One source observation per row. Text has one whole-literal slot; API has two.
CREATE VIEW medical_raw_diagnosis_slots AS
SELECT source_row_hash AS observation_locator, source_kind, source_cohort,
       event_date, meet_code, horse_name_raw, hr_no_raw, stable_no_raw,
       hospital_name_raw, 1 AS source_slot_ordinal, 'api16_illName1' AS source_slot_kind,
       ill_name1_raw AS raw_diagnosis_text, source_path, source_sha256,
       page_no, row_no, line_no
FROM medical_observations
WHERE source_kind IN ('api16','api16_archived')
UNION ALL
SELECT source_row_hash, source_kind, source_cohort, event_date, meet_code,
       horse_name_raw, hr_no_raw, stable_no_raw, hospital_name_raw,
       2, 'api16_illName2', ill_name2_raw, source_path, source_sha256,
       page_no, row_no, line_no
FROM medical_observations
WHERE source_kind IN ('api16','api16_archived')
UNION ALL
SELECT source_row_hash, source_kind, source_cohort, event_date, meet_code,
       horse_name_raw, hr_no_raw, stable_no_raw, hospital_name_raw,
       CAST(NULL AS INTEGER), 'rpt_combined_literal', diagnosis_rpt_raw,
       source_path, source_sha256, page_no, row_no, line_no
FROM medical_observations
WHERE source_kind='dacom72' AND source_cohort='rpt';

-- One row per API occurrence and source diagnosis slot; raw values are unchanged.
CREATE VIEW medical_api16_illness_slots AS
SELECT source_row_hash AS observation_locator, source_cohort, event_date, meet_code,
       horse_name_raw, hr_no_raw, hospital_name_raw, 1 AS illness_slot_number,
       ill_name1_raw AS illness_raw, source_path, source_sha256, page_no, row_no
FROM medical_observations
WHERE source_kind IN ('api16', 'api16_archived')
UNION ALL
SELECT source_row_hash, source_cohort, event_date, meet_code,
       horse_name_raw, hr_no_raw, hospital_name_raw, 2,
       ill_name2_raw, source_path, source_sha256, page_no, row_no
FROM medical_observations
WHERE source_kind IN ('api16', 'api16_archived');

CREATE VIEW medical_current_api_payload_capture_counts AS
SELECT raw_payload_json, count(*)::BIGINT AS current_payload_string_capture_count
FROM medical_observations
WHERE source_kind='api16' AND source_cohort='current_annual'
  AND raw_payload_json IS NOT NULL
GROUP BY raw_payload_json;

CREATE VIEW medical_current_api_exact_slot_keys AS
SELECT event_date, meet_code, horse_name_raw, hospital_name_raw,
       illness_raw AS diagnosis_exact_raw,
       count(*)::BIGINT AS current_api_slot_match_count
FROM medical_api16_illness_slots
WHERE source_cohort='current_annual' AND illness_raw IS NOT NULL
GROUP BY event_date, meet_code, horse_name_raw, hospital_name_raw, illness_raw;

-- Exact official horse IDs only. No name-based or roster-snapshot inference.
CREATE VIEW medical_current_api_records AS
SELECT o.*,
       CASE WHEN o.hr_no_raw IS NULL OR o.hr_no_raw = '' THEN 'missing_official_id'
            WHEN h.entity_id_official_string IS NOT NULL THEN 'exact_core_roster_match'
            ELSE 'unmatched_official_id' END AS horse_link_status,
       CASE WHEN h.entity_id_official_string IS NOT NULL THEN h.entity_id_official_string END
            AS linked_horse_official_id,
       'retrospective_capture_publication_time_unverified' AS availability_status,
       FALSE AS historical_publication_time_verified
FROM medical_observations AS o
LEFT JOIN entity_reference_roster AS h
  ON h.entity_type='horse' AND h.entity_id_official_string=o.hr_no_raw
WHERE o.source_kind='api16' AND o.source_cohort='current_annual';

-- Exact source IDs alone can link to the horse roster. Text records stay unlinked.
CREATE VIEW medical_entity_links AS
SELECT o.source_row_hash AS observation_locator, o.source_kind, o.source_cohort,
       o.event_date, o.meet_code, 'horse' AS entity_role,
       o.horse_name_raw AS source_name, o.hr_no_raw AS source_official_id,
       CASE WHEN o.source_kind='dacom72' THEN 'source_has_no_official_id'
            WHEN o.hr_no_raw IS NULL OR o.hr_no_raw='' THEN 'missing_official_id'
            WHEN h.entity_id_official_string IS NOT NULL THEN 'exact_core_roster_match'
            ELSE 'unmatched_official_id' END AS link_status,
       CASE WHEN h.entity_id_official_string IS NOT NULL THEN h.entity_id_official_string END
            AS linked_horse_official_id,
       o.source_path, o.source_row_hash,
       'exact source official ID only; no name-only inference' AS linking_basis
FROM medical_observations AS o
LEFT JOIN entity_reference_roster AS h
  ON h.entity_type='horse' AND h.entity_id_official_string=o.hr_no_raw;

CREATE VIEW medical_link_exceptions AS
SELECT * FROM medical_entity_links
WHERE link_status<>'exact_core_roster_match';

-- Archived API rows remain separate evidence, including exact payload repeats.
CREATE VIEW medical_api16_archived_candidates AS
SELECT o.*,
       coalesce(p.current_payload_string_capture_count,0) AS current_exact_raw_payload_string_capture_count,
       CASE WHEN p.current_payload_string_capture_count IS NOT NULL
            THEN 'additional_capture_evidence_exact_payload_in_current'
            ELSE 'archived_api_candidate_not_in_current_capture' END AS candidate_status,
       'retrospective_capture_publication_time_unverified' AS availability_status,
       FALSE AS historical_publication_time_verified
FROM medical_observations AS o
LEFT JOIN medical_current_api_payload_capture_counts AS p USING(raw_payload_json)
WHERE o.source_kind='api16_archived' AND o.source_cohort='archived_daily_snapshot';

-- Grouping key is an exact source fingerprint, not a visit identity or visit count.
CREATE VIEW medical_text_record_candidates AS
SELECT source_cohort, source_kind, event_date, meet_code, meet_raw,
       horse_name_raw, stable_no_raw, hospital_name_raw, diagnosis_rpt_raw,
       occurrence_count, provenance_row_hashes_json AS source_row_hashes_json,
       source_paths_json, source_sha256s_json, raw_source_variants_json,
       'exact source fingerprint grouping; occurrence_count is not a verified visit count' AS grouping_semantics
FROM medical_fingerprint_candidates
WHERE source_kind='dacom72' AND source_cohort='rpt';

-- Exact phrase decisions and components are review metadata, not inferred diagnoses.
-- Context-dependent and historical parser-prefix decisions remain on hold.
CREATE VIEW medical_diagnosis_term_links AS
SELECT pc.raw_text_sha256, pc.raw_text, pc.reviewed_target_ordinal,
       pc.target_ill_name, pc.target_order_semantics,
       pd.review_decision, pd.review_status, pd.original_match_status,
       pd.mapped_kra_titles_raw, pd.contextual_evidence_required,
       pd.mapping_rule_scope, pd.prefix_rule_reusable,
       pd.event_link_policy, pd.evidence_note,
       CASE
         WHEN pd.review_status='excluded' THEN 'excluded_review_metadata'
         WHEN pd.review_status<>'confirmed_review_mapping' THEN 'unresolved_review_metadata'
         WHEN pd.mapping_rule_scope='reviewed_phrase_candidate_only'
           AND pd.contextual_evidence_required=FALSE
           AND pc.contextual_evidence_required=FALSE
           AND pd.prefix_rule_reusable IS DISTINCT FROM FALSE
           THEN 'reviewed_exact_phrase_component_metadata_only'
         WHEN pd.mapping_rule_scope IN ('event_specific_reference_only','prior_rpt_parser_context_only')
           OR coalesce(pd.contextual_evidence_required,TRUE)
           OR coalesce(pc.contextual_evidence_required,TRUE)
           OR pd.prefix_rule_reusable=FALSE
           THEN 'hold_requires_new_in_scope_event_evidence'
         ELSE 'hold_unapproved_or_unknown_rule_scope'
       END AS mapping_disposition,
       FALSE AS automatically_applied_to_event
FROM medical_phrase_components AS pc
JOIN medical_phrase_decisions AS pd
  ON pd.raw_text_sha256=pc.raw_text_sha256 AND pd.raw_text=pc.raw_text;

-- Explanation tuples retain their capture provenance and do not multiply event rows.
CREATE VIEW medical_diagnosis_explanations AS
SELECT l.raw_text_sha256, l.raw_text, l.reviewed_target_ordinal,
       l.target_ill_name, l.mapping_disposition,
       e.exact_explanation_tuple_sha256, e.source_title, e.source_english_name,
       e.description_text, e.description_present, e.source_observation_count,
       e.source_kinds_json, e.source_meets_json, e.source_observation_ids_json,
       e.source_files_json, e.description_text_sha256,
       CASE WHEN e.exact_explanation_tuple_sha256 IS NULL
            THEN 'no_exact_title_explanation_tuple' ELSE 'exact_title_explanation_tuple' END
            AS explanation_lookup_status,
       'capture timestamp is separate; historical publication time may be unknown' AS timing_semantics
FROM medical_diagnosis_term_links AS l
LEFT JOIN medical_explanation_terms AS e ON e.source_title=l.target_ill_name
WHERE l.mapping_disposition='reviewed_exact_phrase_component_metadata_only';

-- Event-to-reviewed-term metadata remains one-to-many outside raw observations.
CREATE VIEW medical_observed_diagnosis_components AS
SELECT s.observation_locator, s.source_kind, s.source_cohort, s.event_date,
       s.meet_code, s.horse_name_raw, s.hr_no_raw, s.stable_no_raw,
       s.hospital_name_raw, s.source_slot_ordinal, s.source_slot_kind,
       s.raw_diagnosis_text, s.source_path, s.source_sha256,
       s.page_no, s.row_no, s.line_no,
       p.raw_text_sha256 AS reviewed_phrase_sha256,
       p.review_decision, p.review_status, p.original_match_status,
       p.contextual_evidence_required AS phrase_contextual_evidence_required,
       p.mapping_rule_scope, p.prefix_rule_reusable, p.event_link_policy,
       c.reviewed_target_ordinal, c.target_ill_name, c.target_order_semantics,
       CASE
         WHEN s.raw_diagnosis_text IS NULL OR s.raw_diagnosis_text IN ('','-') THEN 'source_empty_or_placeholder'
         WHEN p.raw_text_sha256 IS NULL THEN 'no_exact_review_phrase'
         WHEN p.review_status='excluded' THEN 'excluded_review_metadata'
         WHEN p.review_status<>'confirmed_review_mapping' THEN 'unresolved_review_metadata'
         WHEN p.mapping_rule_scope='reviewed_phrase_candidate_only'
           AND p.contextual_evidence_required=FALSE
           AND c.contextual_evidence_required=FALSE
           AND p.prefix_rule_reusable IS DISTINCT FROM FALSE
           AND c.target_ill_name IS NOT NULL THEN 'reviewed_exact_phrase_component_metadata_only'
         WHEN p.mapping_rule_scope IN ('event_specific_reference_only','prior_rpt_parser_context_only')
           OR coalesce(p.contextual_evidence_required,TRUE)
           OR coalesce(c.contextual_evidence_required,TRUE)
           OR p.prefix_rule_reusable=FALSE THEN 'hold_requires_new_in_scope_event_evidence'
         WHEN c.target_ill_name IS NULL THEN 'confirmed_review_without_component'
         ELSE 'hold_unapproved_or_unknown_rule_scope'
       END AS mapping_disposition,
       FALSE AS automatically_applied_to_event
FROM medical_raw_diagnosis_slots AS s
LEFT JOIN medical_phrase_decisions AS p
  ON p.raw_text=s.raw_diagnosis_text
 AND s.raw_diagnosis_text IS NOT NULL AND s.raw_diagnosis_text NOT IN ('','-')
LEFT JOIN medical_phrase_components AS c
  ON c.raw_text_sha256=p.raw_text_sha256 AND c.raw_text=p.raw_text;

-- Grain: source diagnosis slot × reviewed target component × actual description capture.
-- Only non-contextual reviewed components with a non-empty captured description appear.
CREATE VIEW medical_observed_diagnosis_explanations AS
SELECT c.observation_locator, c.source_kind, c.source_cohort, c.event_date,
       c.meet_code, c.horse_name_raw, c.hr_no_raw, c.stable_no_raw,
       c.hospital_name_raw, c.source_slot_ordinal, c.source_slot_kind,
       c.raw_diagnosis_text, c.reviewed_phrase_sha256,
       c.reviewed_target_ordinal, c.target_ill_name,
       l.link_status AS event_horse_link_status,
       l.linked_horse_official_id,
       e.explanation_observation_id, e.source_kind AS explanation_source_kind,
       e.source_title, e.source_english_name, e.description_text,
       e.exact_explanation_tuple_sha256, e.description_text_sha256,
       e.source_url, e.source_file, e.source_file_sha256,
       e.source_row_ordinal, e.source_subrow_ordinal, e.source_row_sha256,
       e.collected_at_kst, e.source_publication_at_kst,
       e.source_meet, e.source_meet_name, e.horse_name AS explanation_source_horse_name,
       e.horse_id AS explanation_source_horse_id,
       e.event_date_local AS explanation_source_event_date_local,
       e.event_dates_json AS explanation_source_event_dates_json,
       e.hospital_name AS explanation_source_hospital,
       e.capture_status AS explanation_capture_status,
       'captured explanation metadata; publication time unknown unless source explicitly provides it' AS timing_semantics
FROM medical_observed_diagnosis_components AS c
JOIN medical_entity_links AS l ON l.observation_locator=c.observation_locator
JOIN medical_explanation_observations AS e ON e.source_title=c.target_ill_name
WHERE c.mapping_disposition='reviewed_exact_phrase_component_metadata_only'
  AND e.description_present=TRUE
  AND e.description_text IS NOT NULL AND e.description_text<>'';

-- All current API raw slots remain visible, including unmatched review phrases.
CREATE VIEW medical_api16_current_phrase_review AS
SELECT s.*,
       p.raw_text_sha256 AS reviewed_phrase_sha256,
       p.review_decision, p.review_status, p.contextual_evidence_required,
       p.mapping_rule_scope, p.prefix_rule_reusable, p.event_link_policy,
       CASE WHEN s.illness_raw IS NULL OR s.illness_raw IN ('','-') THEN 'source_empty_or_placeholder'
            WHEN p.raw_text_sha256 IS NULL THEN 'no_exact_review_phrase'
            WHEN p.review_status='excluded' THEN 'excluded_review_metadata'
         WHEN p.review_status='confirmed_review_mapping'
              AND p.mapping_rule_scope='reviewed_phrase_candidate_only'
              AND p.contextual_evidence_required=FALSE
              AND p.prefix_rule_reusable IS DISTINCT FROM FALSE THEN 'reviewed_exact_phrase_metadata_only'
            WHEN p.review_status='confirmed_review_mapping' THEN 'hold_requires_new_in_scope_event_evidence'
            ELSE 'unresolved_review_metadata' END AS exact_phrase_review_status,
       FALSE AS automatically_applied_to_event
FROM medical_api16_illness_slots AS s
LEFT JOIN medical_phrase_decisions AS p
  ON p.raw_text=s.illness_raw AND s.illness_raw IS NOT NULL AND s.illness_raw NOT IN ('','-')
WHERE s.source_cohort='current_annual';

-- RPT full-literal review is independent of API diagnosis slots; no splitting/normalization.
CREATE VIEW medical_text_phrase_review AS
SELECT c.*, p.raw_text_sha256 AS reviewed_phrase_sha256,
       p.review_decision, p.review_status, p.contextual_evidence_required,
       p.mapping_rule_scope, p.prefix_rule_reusable, p.event_link_policy,
       CASE WHEN c.diagnosis_rpt_raw IS NULL OR c.diagnosis_rpt_raw IN ('','-') THEN 'source_empty_or_placeholder'
            WHEN p.raw_text_sha256 IS NULL THEN 'no_exact_review_phrase'
            WHEN p.review_status='excluded' THEN 'excluded_review_metadata'
            WHEN p.review_status='confirmed_review_mapping'
              AND p.mapping_rule_scope='reviewed_phrase_candidate_only'
              AND p.contextual_evidence_required=FALSE
              AND p.prefix_rule_reusable IS DISTINCT FROM FALSE THEN 'reviewed_exact_phrase_metadata_only'
            WHEN p.review_status='confirmed_review_mapping' THEN 'hold_requires_new_in_scope_event_evidence'
            ELSE 'unresolved_review_metadata' END AS exact_phrase_review_status,
       FALSE AS automatically_applied_to_event
FROM medical_text_record_candidates AS c
LEFT JOIN medical_phrase_decisions AS p
  ON p.raw_text=c.diagnosis_rpt_raw
 AND c.diagnosis_rpt_raw IS NOT NULL AND c.diagnosis_rpt_raw NOT IN ('','-');

-- A direct exact-title lookup intentionally retains multiple English/source variants.
CREATE VIEW medical_api16_current_api33_exact_title_lookup AS
SELECT s.observation_locator, s.source_cohort, s.event_date, s.meet_code,
       s.horse_name_raw, s.hr_no_raw, s.hospital_name_raw,
       s.illness_slot_number, s.illness_raw,
       t.api33_tuple_sha256, t.ill_name, t.ill_eng_name, t.ill_desc,
       t.source_row_ids_json, t.source_duplicate_count,
       'exact Korean title lookup; variants are separate dictionary tuples' AS lookup_semantics
FROM medical_api16_illness_slots AS s
JOIN medical_api33_terms AS t ON t.ill_name=s.illness_raw
WHERE s.source_cohort='current_annual';

-- Candidate union keeps all three cohorts and marks priority/evidence role explicitly.
-- No raw rows are removed when a candidate overlaps another source.
CREATE VIEW medical_union_candidates AS
SELECT source_row_hash AS candidate_locator,
       to_json(struct_pack(source_row_hash := source_row_hash)) AS candidate_key_json,
       'current_api_primary' AS candidate_type, source_cohort, source_kind,
       event_date, meet_code, horse_name_raw, hr_no_raw, stable_no_raw,
       hospital_name_raw, ill_name1_raw, ill_name2_raw, diagnosis_rpt_raw,
       1::BIGINT AS source_occurrence_count,
       CAST(NULL AS BIGINT) AS exact_current_api_slot_match_count,
       FALSE AS archived_exact_current_payload_match,
       FALSE AS unique_exact_current_api_overlap,
       'source row occurrence; not a deduplicated visit' AS candidate_semantics
FROM medical_observations
WHERE source_kind='api16' AND source_cohort='current_annual'
UNION ALL
SELECT source_row_hash,
       to_json(struct_pack(source_row_hash := source_row_hash)) AS candidate_key_json,
       CASE WHEN p.current_payload_string_capture_count IS NOT NULL
         THEN 'archived_api_additional_capture_evidence'
         ELSE 'archived_api_candidate' END,
       source_cohort, source_kind, event_date, meet_code, horse_name_raw,
       hr_no_raw, stable_no_raw, hospital_name_raw, ill_name1_raw, ill_name2_raw,
       diagnosis_rpt_raw, 1::BIGINT, coalesce(p.current_payload_string_capture_count,0),
       p.current_payload_string_capture_count IS NOT NULL,
       FALSE,
       'archived capture evidence; exact payload repeats do not inflate primary event rows'
FROM medical_observations o
LEFT JOIN medical_current_api_payload_capture_counts p USING(raw_payload_json)
WHERE source_kind='api16_archived' AND source_cohort='archived_daily_snapshot'
UNION ALL
SELECT CAST(NULL AS VARCHAR),
       to_json(struct_pack(source_cohort := t.source_cohort, event_date := t.event_date,
           meet_code := t.meet_code, horse_name_raw := t.horse_name_raw,
           stable_no_raw := t.stable_no_raw, hospital_name_raw := t.hospital_name_raw,
           diagnosis_rpt_raw := t.diagnosis_rpt_raw)) AS candidate_key_json,
       'rpt_fingerprint_supplementary_candidate', t.source_cohort, t.source_kind,
       t.event_date, t.meet_code, t.horse_name_raw, CAST(NULL AS VARCHAR), t.stable_no_raw,
       t.hospital_name_raw, CAST(NULL AS VARCHAR), CAST(NULL AS VARCHAR), t.diagnosis_rpt_raw,
       t.occurrence_count, coalesce(k.current_api_slot_match_count,0),
       FALSE,
       t.occurrence_count=1 AND coalesce(k.current_api_slot_match_count,0)=1,
       t.grouping_semantics
FROM medical_text_record_candidates t
LEFT JOIN medical_current_api_exact_slot_keys k
  ON k.event_date=t.event_date AND k.meet_code=t.meet_code
 AND k.horse_name_raw=t.horse_name_raw AND k.hospital_name_raw=t.hospital_name_raw
 AND k.diagnosis_exact_raw=t.diagnosis_rpt_raw;

CREATE VIEW medical_api16_current_phrase_usage AS
SELECT illness_raw AS exact_raw_phrase, illness_slot_number,
       count(*)::BIGINT AS source_slot_occurrence_count,
       count(DISTINCT observation_locator)::BIGINT AS source_observation_count,
       count(*) FILTER (WHERE illness_raw IS NULL OR illness_raw='')::BIGINT AS blank_or_null_slot_count,
       'current annual API16 scoped raw slot count, not an inferred clinical visit count' AS count_semantics
FROM medical_api16_illness_slots
WHERE source_cohort='current_annual'
GROUP BY illness_raw, illness_slot_number;

CREATE VIEW medical_text_full_literal_phrase_usage AS
SELECT diagnosis_rpt_raw AS exact_raw_phrase,
       sum(occurrence_count)::BIGINT AS raw_occurrence_count,
       count(*)::BIGINT AS exact_fingerprint_candidate_count,
       'whole RPT diagnosis literal; no splitting or normalization; occurrences are not verified visits' AS count_semantics
FROM medical_text_record_candidates
GROUP BY diagnosis_rpt_raw;
