-- Jeju API16 clinic source rows and dictionary snapshot. Existing tables are append-only.
CREATE TABLE IF NOT EXISTS medical_api16_year_coverage (
    year INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    actual_page_count INTEGER NOT NULL,
    actual_total_rows INTEGER NOT NULL,
    rows_matching_requested_year INTEGER,
    rows_after_cutoff INTEGER,
    rows_with_unparseable_date INTEGER,
    date_min_raw TEXT,
    date_max_raw TEXT,
    positive_data_evidence INTEGER,
    year_manifest_sha256 TEXT NOT NULL,
    year_manifest_json TEXT NOT NULL,
    coverage_interpretation TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS medical_api16_page_ledger (
    source_artifact_id INTEGER PRIMARY KEY REFERENCES source_artifacts(source_artifact_id),
    year INTEGER NOT NULL,
    page_no INTEGER NOT NULL CHECK (page_no >= 1),
    source_row_count INTEGER NOT NULL CHECK (source_row_count >= 0),
    response_sha256 TEXT NOT NULL,
    response_bytes INTEGER NOT NULL,
    page_manifest_json TEXT NOT NULL,
    UNIQUE (year, page_no)
);

CREATE TABLE IF NOT EXISTS medical_api16_load_metadata (
    metadata_key TEXT PRIMARY KEY,
    metadata_value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS medical_api_rows (
    medical_api_row_id INTEGER PRIMARY KEY,
    api_record_id INTEGER NOT NULL UNIQUE REFERENCES api_records(api_record_id),
    source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts(source_artifact_id),
    source_row_no INTEGER NOT NULL CHECK (source_row_no >= 1),
    clinic_date TEXT NOT NULL,
    horse_id TEXT NOT NULL,
    meet_raw TEXT,
    clinic_date_raw TEXT,
    hr_name_raw TEXT,
    hr_no_raw TEXT,
    hospi_name_raw TEXT,
    ill_name1_raw TEXT,
    ill_name2_raw TEXT,
    part_raw TEXT,
    raw_key_presence_json TEXT NOT NULL,
    raw_key_absence_json TEXT NOT NULL,
    raw_field_types_json TEXT NOT NULL,
    UNIQUE (source_artifact_id, source_row_no)
);

CREATE INDEX IF NOT EXISTS ix_medical_api_rows_horse_date
    ON medical_api_rows(horse_id, clinic_date);
CREATE INDEX IF NOT EXISTS ix_medical_api_rows_date
    ON medical_api_rows(clinic_date, horse_id);
CREATE INDEX IF NOT EXISTS ix_medical_api_rows_artifact_order
    ON medical_api_rows(source_artifact_id, source_row_no);

CREATE TABLE IF NOT EXISTS medical_api_diagnosis_slots (
    medical_api_diagnosis_slot_id INTEGER PRIMARY KEY,
    medical_api_row_id INTEGER NOT NULL REFERENCES medical_api_rows(medical_api_row_id),
    api_record_id INTEGER NOT NULL REFERENCES api_records(api_record_id),
    source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts(source_artifact_id),
    source_row_no INTEGER NOT NULL CHECK (source_row_no >= 1),
    horse_id TEXT NOT NULL,
    clinic_date TEXT NOT NULL,
    source_slot_ordinal INTEGER NOT NULL CHECK (source_slot_ordinal IN (1,2)),
    source_slot_kind TEXT NOT NULL CHECK (source_slot_kind IN ('illName1','illName2')),
    raw_diagnosis_text TEXT,
    normalized_diagnosis_text TEXT,
    raw_text_sha256 TEXT,
    UNIQUE (api_record_id, source_slot_ordinal)
);
CREATE INDEX IF NOT EXISTS ix_medical_api_diagnosis_slots_text_hash
    ON medical_api_diagnosis_slots(raw_text_sha256, raw_diagnosis_text);

CREATE TABLE IF NOT EXISTS medical_dictionary_output_hashes (
    file_name TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    response_bytes INTEGER NOT NULL,
    row_count INTEGER,
    column_schema_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS medical_dictionary_metadata (
    metadata_key TEXT PRIMARY KEY,
    metadata_value TEXT NOT NULL
);

-- This view has one row per exact-ID-linked API16 source item. Slot and glossary joins
-- are intentionally kept in separate views so they cannot multiply event rows.
CREATE VIEW IF NOT EXISTS medical_api_rows_analysis_2026 AS
WITH current_profiles AS MATERIALIZED (
    SELECT horse_id, horse_name, age_2026, birth_date_raw,
           profile_breed_label_raw, profile_observed_at_utc,
           profile_payload_sha256, profile_source_artifact_id
    FROM horse_analysis_2026
    WHERE profile_breed_label_raw = '제주마'
)
SELECT r.medical_api_row_id,
       r.api_record_id,
       r.source_artifact_id,
       r.source_row_no,
       r.horse_id,
       r.clinic_date,
       r.meet_raw,
       r.clinic_date_raw,
       r.hr_name_raw,
       r.hr_no_raw,
       r.hospi_name_raw,
       r.ill_name1_raw,
       r.ill_name2_raw,
       r.part_raw,
       r.raw_key_presence_json,
       r.raw_key_absence_json,
       r.raw_field_types_json,
       ha.horse_name AS current_horse_name,
       ha.age_2026 AS current_horse_age_2026,
       ha.birth_date_raw AS current_profile_birth_date_raw,
       ha.profile_breed_label_raw AS current_profile_breed_label_raw,
       ha.profile_observed_at_utc AS current_profile_observed_at_utc,
       ha.profile_payload_sha256 AS current_profile_payload_sha256,
       ar.payload_json AS source_item_payload_json,
       ar.payload_sha256 AS source_item_payload_sha256,
       sa.sha256 AS source_page_sha256,
       sa.raw_relative_path AS source_page_raw_relative_path,
       sa.collected_at_utc AS source_page_retrieved_at_utc,
       'clinic date is an event date; historical publication time is unverified' AS timing_semantics
FROM medical_api_rows AS r
JOIN api_records AS ar
  ON ar.api_record_id = r.api_record_id
 AND ar.source_artifact_id = r.source_artifact_id
 AND ar.record_index = r.source_row_no
JOIN source_artifacts AS sa
  ON sa.source_artifact_id = r.source_artifact_id
JOIN current_profiles AS ha
  ON ha.horse_id = r.horse_id
WHERE r.clinic_date <= '2026-09-19';

-- One row per API16 occurrence and one of its two literal diagnosis slots.
CREATE VIEW IF NOT EXISTS medical_api_diagnosis_slot_review AS
SELECT s.medical_api_diagnosis_slot_id, s.medical_api_row_id, s.api_record_id,
       s.source_artifact_id, s.source_row_no, s.horse_id, s.clinic_date,
       s.source_slot_ordinal, s.source_slot_kind, s.raw_diagnosis_text,
       s.normalized_diagnosis_text, s.raw_text_sha256,
       p.review_decision, p.review_status, p.original_match_status,
       p.reviewed_target_count, p.contextual_evidence_required,
       p.mapping_rule_scope, p.prefix_rule_reusable, p.event_link_policy,
       CASE
         WHEN s.raw_diagnosis_text IS NULL OR s.raw_diagnosis_text = ''
           THEN 'source_empty'
         WHEN s.raw_diagnosis_text = '-'
           THEN 'unknown_placeholder_dash'
         WHEN p.raw_text_sha256 IS NULL
           THEN 'no_exact_review_phrase'
         WHEN p.review_status = 'excluded'
           THEN 'excluded_review_metadata'
         WHEN p.review_status = 'confirmed_review_mapping'
          AND p.mapping_rule_scope = 'reviewed_phrase_candidate_only'
          AND p.contextual_evidence_required = 0
          AND p.prefix_rule_reusable IS NOT 0
          AND p.reviewed_target_count > 0
           THEN 'reviewed_exact_phrase_component_metadata_only'
         WHEN p.mapping_rule_scope IN ('event_specific_reference_only', 'prior_rpt_parser_context_only')
           OR coalesce(p.contextual_evidence_required, 1) <> 0
           OR p.prefix_rule_reusable = 0
           THEN 'hold_requires_new_in_scope_event_evidence'
         ELSE 'unresolved_review_metadata'
       END AS mapping_disposition,
       0 AS automatically_applied_to_event
FROM medical_api_diagnosis_slots AS s
LEFT JOIN medical_phrase_decisions AS p
  ON p.raw_text_sha256 = s.raw_text_sha256
 AND p.raw_text = s.raw_diagnosis_text
 AND s.raw_diagnosis_text IS NOT NULL
 AND s.raw_diagnosis_text <> ''
 AND s.raw_diagnosis_text <> '-';

-- One-to-many reviewed targets are exposed separately from the source-row view.
CREATE VIEW IF NOT EXISTS medical_api_diagnosis_components AS
SELECT s.medical_api_diagnosis_slot_id, s.medical_api_row_id, s.api_record_id,
       s.source_artifact_id, s.source_row_no, s.horse_id, s.clinic_date,
       s.source_slot_ordinal, s.source_slot_kind, s.raw_diagnosis_text,
       s.raw_text_sha256, s.mapping_disposition,
       c.reviewed_target_ordinal, c.target_ill_name, c.target_order_semantics,
       c.evidence_note AS component_evidence_note,
       0 AS automatically_applied_to_event
FROM medical_api_diagnosis_slot_review AS s
JOIN medical_phrase_components AS c
  ON c.raw_text_sha256 = s.raw_text_sha256
 AND c.raw_text = s.raw_diagnosis_text
WHERE s.mapping_disposition = 'reviewed_exact_phrase_component_metadata_only';

-- Exact title lookup keeps all captured explanation variants and their nulls.
CREATE VIEW IF NOT EXISTS medical_api_diagnosis_explanation_terms AS
SELECT c.medical_api_diagnosis_slot_id, c.medical_api_row_id, c.api_record_id,
       c.source_artifact_id, c.source_row_no, c.horse_id, c.clinic_date,
       c.source_slot_ordinal, c.source_slot_kind, c.raw_diagnosis_text,
       c.mapping_disposition, c.reviewed_target_ordinal, c.target_ill_name,
       e.exact_explanation_tuple_sha256, e.source_title, e.source_english_name,
       e.description_text, e.description_present, e.source_observation_count,
       e.source_kinds_json, e.source_meets_json, e.source_observation_ids_json,
       e.source_files_json, e.description_text_sha256,
       CASE WHEN e.exact_explanation_tuple_sha256 IS NULL
            THEN 'no_exact_title_explanation_tuple'
            ELSE 'captured_title_tuple; description may be null' END AS explanation_lookup_status,
       0 AS automatically_applied_to_event
FROM medical_api_diagnosis_components AS c
LEFT JOIN medical_explanation_terms AS e
  ON e.source_title = c.target_ill_name
WHERE c.mapping_disposition = 'reviewed_exact_phrase_component_metadata_only';

-- Observation-level capture provenance stays separate from deduplicated title tuples.
CREATE VIEW IF NOT EXISTS medical_api_diagnosis_explanation_observations AS
SELECT c.medical_api_diagnosis_slot_id, c.medical_api_row_id, c.api_record_id,
       c.source_artifact_id, c.source_row_no, c.horse_id, c.clinic_date,
       c.source_slot_ordinal, c.source_slot_kind, c.raw_diagnosis_text,
       c.mapping_disposition, c.reviewed_target_ordinal, c.target_ill_name,
       e.explanation_observation_id, e.source_kind, e.source_title,
       e.source_english_name, e.description_text, e.description_present,
       e.exact_explanation_tuple_sha256, e.description_text_sha256,
       e.raw_capture_text, e.source_url, e.source_file, e.source_file_sha256,
       e.source_row_ordinal, e.source_subrow_ordinal, e.source_row_sha256,
       e.collected_at_kst, e.source_publication_at_kst, e.source_meet,
       e.source_meet_name, e.horse_name AS explanation_source_horse_name,
       e.horse_id AS explanation_source_horse_id,
       e.event_date_local AS explanation_source_event_date_local,
       e.event_dates_json AS explanation_source_event_dates_json,
       e.hospital_name AS explanation_source_hospital,
       e.capture_status,
       'capture time is not asserted as historical publication time' AS timing_semantics
FROM medical_api_diagnosis_components AS c
JOIN medical_explanation_observations AS e
  ON e.source_title = c.target_ill_name
WHERE c.mapping_disposition = 'reviewed_exact_phrase_component_metadata_only';

CREATE INDEX IF NOT EXISTS ix_medical_phrase_decisions_text_hash
    ON medical_phrase_decisions(raw_text_sha256, raw_text);
CREATE INDEX IF NOT EXISTS ix_medical_phrase_components_text_hash
    ON medical_phrase_components(raw_text_sha256, raw_text);
CREATE INDEX IF NOT EXISTS ix_medical_explanation_terms_title
    ON medical_explanation_terms(source_title);
CREATE INDEX IF NOT EXISTS ix_medical_explanation_observations_title
    ON medical_explanation_observations(source_title);
