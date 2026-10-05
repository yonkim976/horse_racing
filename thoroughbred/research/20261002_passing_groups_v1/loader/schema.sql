-- Passing-group research append v1. Inputs are staged as static, pinned input_* views.
-- Raw source rows are not mutated or merged; derived point values remain separate.
CREATE TABLE passing_api_observations AS SELECT * FROM input_api_observations;
CREATE TABLE passing_api_page_ledger AS SELECT * FROM input_api_page_ledger;
CREATE TABLE passing_api_exclusions AS SELECT * FROM input_api_exclusions;
CREATE TABLE passing_rpt_race_headers AS SELECT * FROM input_rpt_race_headers;
CREATE TABLE passing_rpt_point_observations AS SELECT * FROM input_rpt_point_observations;
CREATE TABLE passing_rpt_source_files AS SELECT * FROM input_rpt_source_files;
CREATE TABLE passing_rpt_point_mapping AS SELECT * FROM input_rpt_point_mapping;
CREATE TABLE passing_rpt_snapshot_comparison AS SELECT * FROM input_rpt_snapshot_comparison;
CREATE TABLE passing_api_mapping_validation AS SELECT * FROM input_api_mapping_validation;
CREATE TABLE passing_api_rpt_value_matches AS SELECT * FROM input_api_rpt_value_matches;
CREATE TABLE passing_confirmed_race_keys AS
SELECT k.meet AS actual_meet_code,k.event_date,k.race_no,k.distance_raw,
       'confirmed_executed_race'::VARCHAR AS race_key_status,
       c.source_meet AS core_source_meet,c.actual_venue_label_raw,
       c.scheduled_distance_m AS planned_distance_m_raw,
       c.actual_distance_m_raw AS actual_distance_m_raw
FROM input_confirmed_race_keys k
JOIN input_core_confirmed_races c USING(meet,event_date,race_no);
CREATE TABLE passing_core_execution_ledger AS SELECT * FROM input_core_execution_ledger;
CREATE TABLE passing_api_error_evidence AS SELECT * FROM input_api_error_evidence;
CREATE TABLE passing_source_metadata AS SELECT * FROM input_source_metadata;
CREATE TABLE passing_source_output_hashes AS SELECT * FROM input_source_output_hashes;

-- API race-level elapsed times stay on race records; they are not horse section fields.
CREATE VIEW passing_api_race_times AS
SELECT source_row_sha256 AS observation_locator,source_cohort,actual_meet_code,
       race_date_iso AS event_date,rcNo AS race_no,passtime_3f,passtime_4f,tempo,
       meet AS meet_raw,rcDate AS rcDate_source_raw,rcNo AS rcNo_source_raw,
       source_path,page_sha256,source_captured_at_utc,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst
FROM passing_api_observations;

-- Preserve each nonplaceholder API field as a point candidate, including held mappings.
-- Only Seoul 2020–2021 uses unique same-race RPT literal evidence for an effective mapping.
CREATE VIEW passing_api_point_observations AS
SELECT a.source_row_sha256 AS observation_locator, a.source_cohort,
       a.actual_meet_code, a.race_date_iso AS event_date, a.rcNo AS race_no,
       a.requested_meet, a.requested_year, p.api_field_raw AS source_point_label_raw,
       m.canonical_point_code AS nominal_point_code,
       CASE WHEN a.actual_meet_code=1 AND a.requested_year IN (2020,2021)
            THEN CASE WHEN vm.mapping_evidence='unique_exact_value_pair' THEN vm.canonical_point_code END
            ELSE m.canonical_point_code END AS canonical_point_code,
       CASE WHEN a.actual_meet_code=1 AND a.requested_year IN (2020,2021)
            THEN CASE WHEN vm.mapping_evidence='unique_exact_value_pair'
                      THEN 'suspect_per_race_unique_rpt_label_evidence'
                      ELSE 'known_suspect_hold_no_unique_per_race_label' END
            WHEN m.canonical_point_code IS NOT NULL THEN 'official_documented_nominal_default'
            ELSE 'no_documented_api_point_map' END AS mapping_status,
       v.evidence_status AS annual_validation_status,
       CASE p.api_field_raw
         WHEN 'corner_1' THEN a.corner_1 WHEN 'corner_2' THEN a.corner_2
         WHEN 'corner_3' THEN a.corner_3 WHEN 'corner_4' THEN a.corner_4
         WHEN 'corner_5' THEN a.corner_5 WHEN 'corner_6' THEN a.corner_6
         WHEN 'corner_7' THEN a.corner_7 WHEN 'corner_8' THEN a.corner_8
         WHEN 'corner_9' THEN a.corner_9 END AS notation_raw,
       a.source_path, a.page_sha256 AS source_sha256, a.page_no, a.row_no,
       a.raw_item_json, a.source_captured_at_utc,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst,
       m.mapping_basis AS mapping_evidence,
       v.evidence_status AS annual_validation_evidence,
       vm.rpt_observation_locator AS mapped_rpt_observation_locator,
       vm.rpt_print_label_raw AS mapped_rpt_print_label_raw,
       vm.api_field_candidate_count AS row_mapping_api_field_candidate_count,
       vm.rpt_point_candidate_count AS row_mapping_rpt_point_candidate_count,
       vm.api_value_raw AS mapping_api_value_raw,
       vm.rpt_value_raw AS mapping_rpt_value_raw,
       vm.mapping_evidence AS row_mapping_evidence
FROM passing_api_observations AS a
 CROSS JOIN LATERAL (VALUES
  ('corner_1',a.corner_1),('corner_2',a.corner_2),('corner_3',a.corner_3),
  ('corner_4',a.corner_4),('corner_5',a.corner_5),('corner_6',a.corner_6),
  ('corner_7',a.corner_7),('corner_8',a.corner_8),('corner_9',a.corner_9)
) AS p(api_field_raw,notation_raw)
LEFT JOIN passing_rpt_point_mapping AS m
  ON m.actual_meet_code=a.actual_meet_code AND m.api_field_nominal=p.api_field_raw
LEFT JOIN passing_api_mapping_validation AS v
  ON v.actual_meet_code=a.actual_meet_code AND v.event_year=a.requested_year
 AND v.api_field=p.api_field_raw
LEFT JOIN passing_api_rpt_value_matches AS vm
  ON vm.observation_locator=a.source_row_sha256 AND vm.api_field_raw=p.api_field_raw
 AND a.actual_meet_code=1 AND a.requested_year IN (2020,2021)
 AND vm.mapping_evidence='unique_exact_value_pair'
WHERE a.row_scope_status='in_scope'
  AND a.actual_meet_code IN (1,3,4)
  AND a.race_date_iso BETWEEN '2010-01-01' AND '2026-09-29'
  AND coalesce(trim(p.notation_raw,' '),'') NOT IN ('','-','X');

CREATE VIEW passing_api_unmapped_point_observations AS
SELECT * FROM passing_api_point_observations WHERE canonical_point_code IS NULL;

CREATE VIEW passing_api_unmapped_race_holds AS
SELECT actual_meet_code,event_date,race_no,count(*)::BIGINT AS held_nonempty_api_slot_count,
       to_json(list(observation_locator ORDER BY observation_locator,source_point_label_raw)) AS held_api_observations_json,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst
FROM passing_api_unmapped_point_observations
WHERE mapping_status='known_suspect_hold_no_unique_per_race_label'
GROUP BY actual_meet_code,event_date,race_no;

-- RPT values use exact, already-canonical printed labels. Their full line and bytes remain raw.
CREATE VIEW passing_rpt_mapped_point_observations AS
SELECT r.observation_locator, r.actual_meet_code, r.event_date, r.race_no,
       m.canonical_point_code, r.print_label_raw AS source_point_label_raw,
       r.notation_raw, r.mapping_status, r.source_path, r.source_sha256,
       r.source_line_no, r.raw_line_text, r.raw_line_bytes_hex,
       r.notation_raw_bytes_hex, r.source_capture_time_status,r.source_captured_at_utc,
       r.source_capture_timestamp_basis,r.source_capture_manifest_path,r.source_capture_manifest_sha256,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst,
       'exact literal RPT label mapping; notation retained without parsing' AS mapping_evidence
FROM passing_rpt_point_observations AS r
JOIN passing_rpt_point_mapping AS m
  ON m.actual_meet_code=r.actual_meet_code
 AND m.print_label_raw=r.print_label_raw
 AND m.canonical_point_code=r.canonical_point_code
WHERE r.actual_meet_code IN (1,3,4)
  AND r.event_date BETWEEN '2010-01-01' AND '2026-09-29'
  AND r.mapping_status='exact_observed_print_label_mapping'
  AND r.notation_state='nonempty_literal'
  AND coalesce(trim(r.notation_raw,' '),'') NOT IN ('','-','X');

CREATE VIEW passing_rpt_unmapped_nonempty_point_observations AS
SELECT r.*
FROM passing_rpt_point_observations r
LEFT JOIN passing_rpt_point_mapping m
  ON m.actual_meet_code=r.actual_meet_code
 AND m.print_label_raw=r.print_label_raw
 AND m.canonical_point_code=r.canonical_point_code
WHERE r.actual_meet_code IN (1,3,4)
  AND r.event_date BETWEEN '2010-01-01' AND '2026-09-29'
  AND coalesce(trim(r.notation_raw,' '),'') NOT IN ('','-','X')
  AND (m.canonical_point_code IS NULL OR r.mapping_status<>'exact_observed_print_label_mapping');

CREATE VIEW passing_mapped_point_observations AS
SELECT observation_locator, 'api303' AS source_kind, source_cohort,
       actual_meet_code, event_date, race_no, canonical_point_code,
       source_point_label_raw, notation_raw, mapping_status,
       source_path, source_sha256, page_no, row_no, CAST(NULL AS INTEGER) AS source_line_no,
       source_captured_at_utc,'api_source_capture_time' AS source_capture_time_status,
       mapping_evidence,FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst
FROM passing_api_point_observations
WHERE canonical_point_code IS NOT NULL
  AND mapping_status<>'known_suspect_hold_no_unique_per_race_label'
UNION ALL
SELECT observation_locator, 'dacom11_rpt', 'rpt',
       actual_meet_code, event_date, race_no, canonical_point_code,
       source_point_label_raw, notation_raw, mapping_status,
       source_path, source_sha256, CAST(NULL AS INTEGER), CAST(NULL AS INTEGER), source_line_no,
       source_captured_at_utc,source_capture_time_status,
       mapping_evidence,FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst
FROM passing_rpt_mapped_point_observations;

-- Aggregate all exact source values and provenance at race×point grain.
CREATE VIEW passing_point_comparison AS
WITH evidence AS (
  SELECT actual_meet_code, event_date, race_no, canonical_point_code, source_kind,
         count(*)::BIGINT AS source_occurrence_count,
         count(DISTINCT notation_raw)::BIGINT AS exact_literal_variant_count,
         count(DISTINCT trim(notation_raw,' '))::BIGINT AS normalized_literal_variant_count,
         to_json(list(notation_raw ORDER BY observation_locator)) AS notation_values_json,
         to_json(list(DISTINCT trim(notation_raw,' ') ORDER BY trim(notation_raw,' '))) AS normalized_notation_values_json,
         to_json(list(observation_locator ORDER BY observation_locator)) AS observation_locators_json,
         to_json(list(source_captured_at_utc ORDER BY observation_locator)) AS source_capture_times_utc_json,
         to_json(list(source_capture_time_status ORDER BY observation_locator)) AS source_capture_time_statuses_json,
         to_json(list(source_point_label_raw ORDER BY observation_locator)) AS source_labels_json,
         to_json(list(source_path ORDER BY observation_locator)) AS source_paths_json,
         string_agg(DISTINCT mapping_status, ',' ORDER BY mapping_status) AS mapping_statuses
  FROM passing_mapped_point_observations
  GROUP BY actual_meet_code,event_date,race_no,canonical_point_code,source_kind
), api AS (SELECT * FROM evidence WHERE source_kind='api303'), rpt AS (SELECT * FROM evidence WHERE source_kind='dacom11_rpt')
SELECT coalesce(a.actual_meet_code,r.actual_meet_code) AS actual_meet_code,
       coalesce(a.event_date,r.event_date) AS event_date,
       coalesce(a.race_no,r.race_no) AS race_no,
       coalesce(a.canonical_point_code,r.canonical_point_code) AS canonical_point_code,
       a.source_occurrence_count AS api_occurrence_count,
       a.exact_literal_variant_count AS api_literal_variant_count,
       a.normalized_literal_variant_count AS api_normalized_literal_variant_count,
       a.notation_values_json AS api_notation_values_json,
       a.normalized_notation_values_json AS api_normalized_notation_values_json,
       a.observation_locators_json AS api_observation_locators_json,
       a.source_capture_times_utc_json AS api_source_capture_times_utc_json,
       a.source_capture_time_statuses_json AS api_source_capture_time_statuses_json,
       a.source_labels_json AS api_source_columns_json,
       a.source_paths_json AS api_source_paths_json,
       a.mapping_statuses AS api_mapping_statuses,
       r.source_occurrence_count AS rpt_occurrence_count,
       r.exact_literal_variant_count AS rpt_literal_variant_count,
       r.normalized_literal_variant_count AS rpt_normalized_literal_variant_count,
       r.notation_values_json AS rpt_notation_values_json,
       r.normalized_notation_values_json AS rpt_normalized_notation_values_json,
       r.observation_locators_json AS rpt_observation_locators_json,
       r.source_capture_times_utc_json AS rpt_source_capture_times_utc_json,
       r.source_capture_time_statuses_json AS rpt_source_capture_time_statuses_json,
       r.source_labels_json AS rpt_source_labels_json,
       r.source_paths_json AS rpt_source_paths_json,
       r.mapping_statuses AS rpt_mapping_statuses,
       CASE
         WHEN a.actual_meet_code IS NULL THEN 'rpt_only'
         WHEN r.actual_meet_code IS NULL THEN 'api_only'
         WHEN a.normalized_literal_variant_count=1 AND r.normalized_literal_variant_count=1
           AND a.normalized_notation_values_json=r.normalized_notation_values_json THEN 'equal_after_outer_ascii_space_trim'
         WHEN a.normalized_literal_variant_count=1 AND r.normalized_literal_variant_count=1
           AND a.normalized_notation_values_json<>r.normalized_notation_values_json THEN 'source_value_discrepancy'
         ELSE 'source_internal_variants_or_ambiguity'
       END AS comparison_status,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst
FROM api a FULL OUTER JOIN rpt r USING(actual_meet_code,event_date,race_no,canonical_point_code);

-- API is primary whenever its effective point value is internally unique.
-- RPT fills only API-absent points with one normalized literal; notation is never parsed.
CREATE VIEW race_passing_groups AS
SELECT c.actual_meet_code,c.event_date,c.race_no,c.canonical_point_code,
       CASE WHEN c.api_occurrence_count IS NOT NULL AND c.api_normalized_literal_variant_count=1
            THEN json_extract_string(c.api_notation_values_json,'$[0]')
            WHEN c.api_occurrence_count IS NULL AND c.rpt_occurrence_count IS NOT NULL
                 AND c.rpt_normalized_literal_variant_count=1
            THEN json_extract_string(c.rpt_notation_values_json,'$[0]') END AS notation_raw,
       CASE WHEN c.api_occurrence_count IS NOT NULL AND c.api_normalized_literal_variant_count=1
            THEN 'api303'
            WHEN c.api_occurrence_count IS NULL AND c.rpt_occurrence_count IS NOT NULL
                 AND c.rpt_normalized_literal_variant_count=1 THEN 'dacom11_rpt'
            ELSE NULL END AS selected_source,
       CASE WHEN c.api_occurrence_count IS NOT NULL AND c.api_normalized_literal_variant_count=1
                 AND c.comparison_status='source_value_discrepancy' THEN 'api_primary_with_rpt_discrepancy'
            WHEN c.api_occurrence_count IS NOT NULL AND c.api_normalized_literal_variant_count=1
                 AND c.rpt_occurrence_count IS NOT NULL
                 AND c.comparison_status='source_internal_variants_or_ambiguity' THEN 'api_primary_rpt_internal_variants'
            WHEN c.api_occurrence_count IS NOT NULL AND c.api_normalized_literal_variant_count=1
                 AND c.rpt_occurrence_count IS NOT NULL THEN 'api_primary_exact_agreement_after_outer_space_trim'
            WHEN c.api_occurrence_count IS NOT NULL AND c.api_normalized_literal_variant_count=1 THEN 'api_primary_unique_literal'
            WHEN c.api_occurrence_count IS NULL AND c.rpt_occurrence_count IS NOT NULL AND c.rpt_normalized_literal_variant_count=1
                 AND coalesce(u.held_nonempty_api_slot_count,0)>0 THEN 'rpt_unique_literal_fill_api_mapping_held_same_race'
            WHEN c.api_occurrence_count IS NULL AND c.rpt_occurrence_count IS NOT NULL AND c.rpt_normalized_literal_variant_count=1 THEN 'rpt_unique_literal_fill_api_absent'
            WHEN c.api_occurrence_count IS NOT NULL AND c.api_normalized_literal_variant_count>1 THEN 'api_internal_value_conflict_hold'
            WHEN c.rpt_occurrence_count IS NOT NULL AND c.rpt_normalized_literal_variant_count>1 THEN 'rpt_internal_value_conflict_hold'
            ELSE 'no_selectable_source_value' END AS selection_status,
       c.api_occurrence_count,c.api_literal_variant_count,c.api_normalized_literal_variant_count,c.api_notation_values_json,
       c.api_observation_locators_json,c.api_source_columns_json,c.api_mapping_statuses,
       c.api_source_paths_json,c.api_source_capture_times_utc_json,c.api_source_capture_time_statuses_json,
       c.rpt_occurrence_count,c.rpt_literal_variant_count,c.rpt_normalized_literal_variant_count,c.rpt_notation_values_json,
       c.rpt_observation_locators_json,c.rpt_source_labels_json,c.rpt_mapping_statuses,
       c.rpt_source_paths_json,c.rpt_source_capture_times_utc_json,c.rpt_source_capture_time_statuses_json,
       'passing_point_map_v1' AS point_mapping_version,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst,
       'notation is source-literal text; no grouping grammar interpretation' AS notation_semantics
FROM passing_point_comparison c
LEFT JOIN passing_api_unmapped_race_holds u USING(actual_meet_code,event_date,race_no)
JOIN passing_confirmed_race_keys k USING(actual_meet_code,event_date,race_no);

CREATE VIEW passing_point_discrepancy_ledger AS
SELECT *,
       CASE WHEN comparison_status='source_value_discrepancy' THEN 'api_rpt_literal_disagreement'
            WHEN comparison_status='source_internal_variants_or_ambiguity' THEN 'source_internal_ambiguity'
            ELSE comparison_status END AS discrepancy_type
FROM passing_point_comparison
WHERE comparison_status IN ('source_value_discrepancy','source_internal_variants_or_ambiguity');

-- Exactly one row for every confirmed in-scope race; zero observed point values remain explicit.
CREATE VIEW passing_race_coverage AS
WITH point_counts AS (
  SELECT actual_meet_code,event_date,race_no,
         count(*)::BIGINT AS mapped_point_keys,
         count(*) FILTER (WHERE notation_raw IS NOT NULL)::BIGINT AS selected_point_values,
         count(*) FILTER (WHERE selected_source IS NULL)::BIGINT AS nonselected_point_keys
  FROM race_passing_groups GROUP BY ALL
), api_counts AS (
  SELECT actual_meet_code,race_date_iso AS event_date,rcNo AS race_no,count(*)::BIGINT AS api_row_occurrences
  FROM passing_api_observations
  WHERE row_scope_status='in_scope' AND actual_meet_code IN (1,3,4)
  GROUP BY ALL
), rpt_counts AS (
  SELECT actual_meet_code,event_date,race_no,count(*)::BIGINT AS rpt_header_occurrences
  FROM passing_rpt_race_headers WHERE actual_meet_code IN (1,3,4) GROUP BY ALL
)
SELECT k.*, coalesce(a.api_row_occurrences,0) AS api_row_occurrences,
       coalesce(r.rpt_header_occurrences,0) AS rpt_header_occurrences,
       coalesce(p.mapped_point_keys,0) AS mapped_point_keys,
       coalesce(p.selected_point_values,0) AS selected_point_values,
       coalesce(p.nonselected_point_keys,0) AS nonselected_point_keys,
       coalesce(u.held_nonempty_api_slot_count,0) AS unmapped_api_nonempty_slot_count,
       coalesce(rptu.unmapped_rpt_nonempty_point_count,0) AS unmapped_rpt_nonempty_point_count,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst,
       CASE WHEN coalesce(p.selected_point_values,0)>0 THEN 'point_value_present'
            WHEN coalesce(a.api_row_occurrences,0)>0 OR coalesce(r.rpt_header_occurrences,0)>0 THEN 'race_source_present_no_selectable_point_value'
            ELSE 'no_passing_point_source_recorded' END AS coverage_status
FROM passing_confirmed_race_keys k
LEFT JOIN api_counts a USING(actual_meet_code,event_date,race_no)
LEFT JOIN rpt_counts r USING(actual_meet_code,event_date,race_no)
LEFT JOIN point_counts p USING(actual_meet_code,event_date,race_no)
LEFT JOIN passing_api_unmapped_race_holds u USING(actual_meet_code,event_date,race_no)
LEFT JOIN (
  SELECT actual_meet_code,event_date,race_no,count(*)::BIGINT AS unmapped_rpt_nonempty_point_count
  FROM passing_rpt_unmapped_nonempty_point_observations GROUP BY ALL
) rptu USING(actual_meet_code,event_date,race_no);

-- Raw API items outside confirmed races remain classifiable or explicitly unknown.
CREATE VIEW passing_api_event_reconciliation AS
SELECT a.source_row_sha256 AS observation_locator,a.source_path,a.page_sha256 AS response_page_sha256,
       a.actual_meet_code,a.race_date_iso AS event_date,a.rcNo AS race_no,a.row_scope_status,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst,
       k.race_key_status AS confirmed_race_status,
       e.execution_status,e.execution_verdict,e.adjudication_status,e.nonexecution_scope,
       pe.review_decision AS planless_positive_result_review,
       ne.review_decision AS result_only_nonfinish_review,
       CASE WHEN a.row_scope_status<>'in_scope' THEN 'api_source_scope_exclusion'
            WHEN k.actual_meet_code IS NOT NULL THEN 'confirmed_executed_race'
            WHEN e.execution_status IS NOT NULL AND e.execution_status<>'executed_plan_and_result'
                 THEN 'core_execution_ledger_nonconfirmed_match'
            WHEN pe.meet IS NOT NULL OR ne.meet IS NOT NULL THEN 'core_reviewed_api_error_key_match'
            ELSE 'api_key_not_in_confirmed_or_reviewed_core_ledgers' END AS reconciliation_status
FROM passing_api_observations a
LEFT JOIN passing_confirmed_race_keys k
  ON k.actual_meet_code=a.actual_meet_code AND k.event_date=a.race_date_iso AND k.race_no=a.rcNo
LEFT JOIN passing_core_execution_ledger e
  ON e.meet=CAST(a.actual_meet_code AS VARCHAR)
 AND e.date=replace(a.race_date_iso,'-','') AND e.race_no=CAST(a.rcNo AS VARCHAR)
LEFT JOIN passing_api_error_evidence pe
  ON pe.error_source='planless_positive_result_review'
 AND pe.meet=CAST(a.actual_meet_code AS VARCHAR)
 AND pe.date=replace(a.race_date_iso,'-','') AND pe.race_no=CAST(a.rcNo AS VARCHAR)
LEFT JOIN passing_api_error_evidence ne
  ON ne.error_source='result_only_nonfinish_anomaly_review'
 AND ne.meet=CAST(a.actual_meet_code AS VARCHAR)
 AND ne.date=replace(a.race_date_iso,'-','') AND ne.race_no=CAST(a.rcNo AS VARCHAR);
