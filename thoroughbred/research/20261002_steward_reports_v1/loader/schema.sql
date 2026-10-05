-- Append-only raw evidence plus non-attributive, roster-verified views.
-- The loader stages literal source tables as input_* views and the existing
-- research runner roster as runner_results (READ_ONLY during preflight).
CREATE TABLE steward_api_source_observations AS
SELECT *,capture_id || '|' || source_location AS observation_locator,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst
FROM input_source_observations;

CREATE TABLE steward_api_page_ledger AS
SELECT * FROM input_api_page_ledger;

CREATE TABLE steward_api_scope_exclusions AS
SELECT * FROM input_source_exclusions;

CREATE TABLE steward_source_year_meet_coverage AS
SELECT dataset,requested_year,requested_meet,
       count(*)::BIGINT AS page_request_count,
       count(DISTINCT reported_page_no)::BIGINT AS reported_page_count,
       max(expected_pages_at_response)::BIGINT AS expected_page_count,
       max(total_count)::BIGINT AS reported_total_item_count,
       sum(returned_item_count)::BIGINT AS captured_item_count,
       count(*) FILTER (WHERE http_status=200 AND result_code='00')::BIGINT AS successful_page_count,
       (count(*) FILTER (WHERE http_status=200 AND result_code='00')=count(*)
         AND sum(returned_item_count)=max(total_count)
         AND (max(total_count)=0 OR count(DISTINCT reported_page_no)=max(expected_pages_at_response)))
         AS response_partition_complete,
       CASE WHEN count(*) FILTER (WHERE http_status=200 AND result_code='00')<>count(*)
              THEN 'page_failure_or_non_normal_result'
            WHEN sum(returned_item_count)<>max(total_count)
              THEN 'captured_rows_do_not_match_reported_total'
            WHEN max(total_count)>0 AND count(DISTINCT reported_page_no)<>max(expected_pages_at_response)
              THEN 'page_count_incomplete'
            WHEN max(total_count)=0 THEN 'complete_successful_zero_row_response'
            ELSE 'complete_successful_nonzero_response' END AS response_partition_status
FROM steward_api_page_ledger
GROUP BY dataset,requested_year,requested_meet;

CREATE TABLE steward_report_paragraphs AS
SELECT * FROM input_report_event_paragraphs WHERE paragraph_state='text';

CREATE TABLE steward_report_paragraph_field_states AS
SELECT * FROM input_report_event_paragraphs WHERE paragraph_state<>'text';

CREATE TABLE steward_report_sentences AS
SELECT * FROM input_report_event_sentences;

CREATE TABLE steward_report_horse_mentions AS
SELECT * FROM input_report_horse_mentions;

CREATE TABLE steward_report_horse_links AS
SELECT * FROM input_report_horse_links
WHERE status='linked';

CREATE TABLE steward_report_horse_link_candidates AS
SELECT * FROM input_report_horse_mentions
WHERE candidate_status IS NULL OR candidate_status NOT IN (
  'explicit_number_name_race_roster_exact',
  'explicit_number_name_venue_prefix_exact',
  'report_local_exact_name_from_unique_anchor'
);

CREATE TABLE steward_report_marker_residuals AS
SELECT * FROM input_report_marker_residuals;

CREATE TABLE steward_source_metadata AS
SELECT * FROM input_source_metadata;

CREATE TABLE steward_source_output_hashes AS
SELECT * FROM input_source_output_hashes;

CREATE VIEW steward_report_observations AS
SELECT * FROM steward_api_source_observations
WHERE dataset='api215_judge_report';

CREATE VIEW steward_sanction_observations AS
SELECT * FROM steward_api_source_observations
WHERE dataset='api180_1_sanction_history';

-- One row per source occurrence, never one row per natural-key sanction.
-- gubun determines the target namespace; exact ID + event roster + entry number
-- are required. `reason` is not used to infer who was sanctioned or blamed.
CREATE TABLE steward_sanction_target_link_audit AS
WITH sanctions AS (
  SELECT * FROM steward_sanction_observations
  WHERE row_scope_status='included'
), matches AS (
  SELECT s.observation_locator AS sanction_observation_locator,
         s.capture_id,s.source_path,s.page_sha256,s.page_no,s.row_no,
         s.actual_meet_code,s.race_date_iso,s.rcNo,
         s.rcDate,
         CAST(s.gubun AS VARCHAR) AS target_gubun_raw,
         CAST(s.prNo AS VARCHAR) AS target_official_id_raw,
         CAST(s.prName AS VARCHAR) AS target_name_raw,
         CAST(s.chulNo AS VARCHAR) AS target_program_no_raw,
         r.source_meet AS roster_meet_raw,r.result_date AS roster_event_date,
         r.result_race_no AS roster_race_no,
         r.horse_program_no_raw AS roster_program_no_raw,
         r.horse_id_raw AS roster_horse_id_raw,
         r.horse_name_raw AS roster_horse_name_raw,
         r.jockey_id_raw AS roster_jockey_id_raw,
         r.jockey_name_raw AS roster_jockey_name_raw,
         CASE CAST(s.gubun AS VARCHAR)
           WHEN '말' THEN r.horse_id_raw
           WHEN '기수' THEN r.jockey_id_raw
           ELSE NULL
         END AS roster_target_id_raw,
         try_cast(CAST(s.chulNo AS VARCHAR) AS INTEGER) AS target_program_no_int,
         try_cast(r.horse_program_no_raw AS INTEGER) AS roster_program_no_int
  FROM sanctions s
  LEFT JOIN runner_results r
    ON try_cast(r.source_meet AS SMALLINT)=try_cast(s.actual_meet_code AS SMALLINT)
   AND r.result_date=replace(s.race_date_iso,'-','')
   AND try_cast(r.result_race_no AS INTEGER)=try_cast(CAST(s.rcNo AS VARCHAR) AS INTEGER)
), by_occurrence AS (
  SELECT sanction_observation_locator,
         any_value(capture_id) AS capture_id,
         any_value(source_path) AS source_path,
         any_value(page_sha256) AS page_sha256,
         any_value(page_no) AS page_no,
         any_value(row_no) AS row_no,
         any_value(actual_meet_code) AS actual_meet_code,
         any_value(race_date_iso) AS event_date,
         any_value(rcDate) AS rc_date_raw,
         any_value(rcNo) AS race_no_raw,
         any_value(target_gubun_raw) AS target_gubun_raw,
         any_value(target_official_id_raw) AS target_official_id_raw,
         any_value(target_name_raw) AS target_name_raw,
         any_value(target_program_no_raw) AS target_program_no_raw,
         count(*) FILTER (WHERE roster_target_id_raw=target_official_id_raw)::BIGINT
           AS event_target_id_match_count,
         count(*) FILTER (WHERE roster_target_id_raw=target_official_id_raw
                           AND target_program_no_int=roster_program_no_int)::BIGINT
           AS exact_target_entry_match_count,
         count(*) FILTER (WHERE roster_target_id_raw=target_official_id_raw
                           AND target_program_no_int=roster_program_no_int
                           AND ((target_gubun_raw='말' AND target_name_raw=roster_horse_name_raw)
                             OR (target_gubun_raw='기수' AND target_name_raw=roster_jockey_name_raw)))::BIGINT
           AS exact_id_entry_and_name_match_count,
         min(roster_program_no_raw) FILTER (WHERE roster_target_id_raw=target_official_id_raw
                           AND target_program_no_int=roster_program_no_int) AS linked_program_no_raw,
         min(roster_horse_id_raw) FILTER (WHERE roster_target_id_raw=target_official_id_raw
                           AND target_program_no_int=roster_program_no_int) AS linked_horse_id_raw,
         min(roster_horse_name_raw) FILTER (WHERE roster_target_id_raw=target_official_id_raw
                           AND target_program_no_int=roster_program_no_int) AS linked_horse_name_raw,
         min(roster_jockey_id_raw) FILTER (WHERE roster_target_id_raw=target_official_id_raw
                           AND target_program_no_int=roster_program_no_int) AS linked_jockey_id_raw,
         min(roster_jockey_name_raw) FILTER (WHERE roster_target_id_raw=target_official_id_raw
                           AND target_program_no_int=roster_program_no_int) AS linked_jockey_name_raw
  FROM matches
  GROUP BY sanction_observation_locator
), entity_reference AS (
  SELECT s.observation_locator AS sanction_observation_locator,
         count(e.entity_id_official_string)::BIGINT AS exact_official_entity_reference_count,
         min(e.entity_type) AS exact_official_entity_type,
         min(e.entity_id_official_string) AS exact_official_entity_id
  FROM sanctions s
  LEFT JOIN entity_reference_roster e
    ON e.entity_type=CASE CAST(s.gubun AS VARCHAR) WHEN '말' THEN 'horse'
                                                   WHEN '기수' THEN 'jockey' END
   AND e.entity_id_official_string=CAST(s.prNo AS VARCHAR)
  GROUP BY s.observation_locator
)
SELECT b.*,
       CASE target_gubun_raw WHEN '말' THEN 'horse'
                             WHEN '기수' THEN 'jockey' END AS target_entity_type,
       CASE
         WHEN target_gubun_raw NOT IN ('말','기수') OR target_gubun_raw IS NULL THEN 'unsupported_target_gubun'
         WHEN target_official_id_raw IS NULL OR trim(target_official_id_raw)='' THEN 'missing_target_official_id'
         WHEN er.exact_official_entity_reference_count=0 AND event_target_id_match_count=0 THEN 'official_id_not_in_core_entity_roster_or_event_roster'
         WHEN er.exact_official_entity_reference_count=0 THEN 'event_roster_id_present_but_not_in_core_entity_roster'
         WHEN event_target_id_match_count=0 THEN 'known_official_entity_id_no_verified_event_entry'
         WHEN exact_target_entry_match_count=0 THEN 'target_id_roster_entry_number_conflict'
         WHEN exact_target_entry_match_count>1 THEN 'ambiguous_target_id_and_entry_roster_match'
         WHEN exact_id_entry_and_name_match_count=1 THEN 'verified_exact_id_entry_and_name'
         ELSE 'verified_exact_id_entry_name_differs'
       END AS target_link_status,
       er.exact_official_entity_reference_count,er.exact_official_entity_type,er.exact_official_entity_id,
       (er.exact_official_entity_reference_count=1) AS target_entity_reference_verified,
       (exact_target_entry_match_count=1) AS target_event_entry_link_verified,
       (exact_id_entry_and_name_match_count=1) AS target_name_exact_roster_match,
       'API180_1 gubun namespace + exact official ID + same event roster entry number'::VARCHAR AS link_evidence_rule,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst
FROM by_occurrence b
JOIN entity_reference er USING(sanction_observation_locator);

CREATE VIEW steward_sanction_target_links AS
SELECT sanction_observation_locator,capture_id,event_date,actual_meet_code,
       race_no_raw,target_entity_type,target_official_id_raw,target_name_raw,
       linked_program_no_raw,linked_horse_id_raw,linked_horse_name_raw,
       linked_jockey_id_raw,linked_jockey_name_raw,target_link_status,
       exact_official_entity_reference_count,exact_official_entity_type,exact_official_entity_id,
       target_event_entry_link_verified,target_name_exact_roster_match,
       link_evidence_rule,source_path,page_sha256,page_no,row_no,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst
FROM steward_sanction_target_link_audit
WHERE target_entity_reference_verified;

CREATE VIEW steward_sanction_target_link_exceptions AS
SELECT * FROM steward_sanction_target_link_audit
WHERE NOT target_entity_reference_verified;

CREATE VIEW steward_sanction_event_entry_links AS
SELECT * FROM steward_sanction_target_links
WHERE target_event_entry_link_verified;

CREATE VIEW steward_horse_sanctions AS
SELECT * FROM steward_sanction_target_links
WHERE target_entity_type='horse';

-- Report versions and capture timestamps stay distinct. The latest row is a
-- deterministic selected observation; exact text variants remain inspectable.
CREATE VIEW steward_report_variant_summary AS
SELECT actual_meet_code,race_date_iso AS event_date,
       try_cast(CAST(rcNo AS VARCHAR) AS INTEGER) AS race_no,
       count(*)::BIGINT AS report_observation_count,
       count(DISTINCT sha256(to_json(struct_pack(
         judgement := judgement, addJudgement := addJudgement,
         jkChange := jkChange, member := member, weather := weather
       ))))::BIGINT AS exact_report_variant_count,
       max(source_captured_at_ms) AS latest_capture_at_ms,
       max(source_captured_at_utc) FILTER (WHERE source_captured_at_ms=(
         SELECT max(x.source_captured_at_ms) FROM steward_report_observations x
         WHERE x.actual_meet_code=steward_report_observations.actual_meet_code
           AND x.race_date_iso=steward_report_observations.race_date_iso
           AND x.rcNo=steward_report_observations.rcNo
       )) AS latest_capture_at_utc,
       count(DISTINCT sha256(to_json(struct_pack(
         judgement := judgement, addJudgement := addJudgement,
         jkChange := jkChange, member := member, weather := weather
       )))) FILTER (WHERE source_captured_at_ms=(
         SELECT max(x.source_captured_at_ms) FROM steward_report_observations x
         WHERE x.actual_meet_code=steward_report_observations.actual_meet_code
           AND x.race_date_iso=steward_report_observations.race_date_iso
           AND x.rcNo=steward_report_observations.rcNo
       ))::BIGINT AS latest_capture_variant_count,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst
FROM steward_report_observations
WHERE row_scope_status='included'
GROUP BY actual_meet_code,race_date_iso,try_cast(CAST(rcNo AS VARCHAR) AS INTEGER);

CREATE VIEW steward_report_latest_observation AS
SELECT * EXCLUDE (latest_row_number)
FROM (
  SELECT r.*,v.exact_report_variant_count,v.latest_capture_variant_count,
         CASE WHEN v.latest_capture_variant_count>1 THEN 'latest_capture_conflicting_variants'
              ELSE 'latest_capture_selected' END AS selection_status,
         row_number() OVER (
           PARTITION BY r.actual_meet_code,r.race_date_iso,r.rcNo
           ORDER BY r.source_captured_at_ms DESC NULLS LAST,
                    r.source_captured_at_utc DESC NULLS LAST,
                    r.source_row_sha256 DESC
         ) AS latest_row_number
  FROM steward_report_observations r
  JOIN steward_report_variant_summary v
    ON v.actual_meet_code=r.actual_meet_code
   AND v.event_date=r.race_date_iso
   AND v.race_no=try_cast(CAST(r.rcNo AS VARCHAR) AS INTEGER)
  WHERE r.row_scope_status='included'
) ranked
WHERE latest_row_number=1;

CREATE VIEW steward_report_horse_paragraph_history AS
SELECT l.official_horse_id AS horse_id,
       l.target_event_date AS event_date,l.target_actual_meet_code AS venue_code,
       try_cast(l.target_race_no AS INTEGER) AS race_no,
       l.program_no_raw,p.paragraph_raw,l.match_rule,
       p.report_text_field AS source_report_text_field,
       l.observation_locator AS full_report_observation_locator,
       r.race_date_iso AS parent_report_event_date,r.actual_meet_code AS parent_report_meet_code,
       try_cast(CAST(r.rcNo AS VARCHAR) AS INTEGER) AS parent_report_race_no,
       l.linked_mention_locators_json,l.mention_semantics,
       r.source_row_sha256 AS source_row_sha256,r.source_path,r.page_sha256,
       r.source_captured_at_utc AS source_captured_at_utc,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst
FROM steward_report_horse_links l
JOIN steward_report_paragraphs p ON p.paragraph_locator=l.paragraph_locator
JOIN steward_report_observations r ON r.observation_locator=l.observation_locator;

CREATE VIEW horse_steward_history AS
WITH ordinary AS (
  SELECT *,1::BIGINT AS full_report_observation_count,
         'one_source_occurrence'::VARCHAR AS history_aggregation_status,
         to_json(list_value(full_report_observation_locator)) AS full_report_observation_locators_json
  FROM steward_report_horse_paragraph_history
  WHERE source_report_text_field IS DISTINCT FROM 'addJudgement'
), supplemental AS (
  SELECT horse_id,event_date,venue_code,race_no,program_no_raw,paragraph_raw,
         arg_min(match_rule,full_report_observation_locator) AS match_rule,parent_report_event_date,parent_report_meet_code,
         'addJudgement'::VARCHAR AS source_report_text_field,
         arg_min(parent_report_race_no,full_report_observation_locator) AS parent_report_race_no,
         arg_min(linked_mention_locators_json,full_report_observation_locator) AS linked_mention_locators_json,
         mention_semantics,
         arg_min(source_row_sha256,full_report_observation_locator) AS source_row_sha256,
         arg_min(source_path,full_report_observation_locator) AS source_path,
         arg_min(page_sha256,full_report_observation_locator) AS page_sha256,
         arg_min(source_captured_at_utc,full_report_observation_locator) AS source_captured_at_utc,
         FALSE AS historical_publication_time_verified,
         CAST(NULL AS VARCHAR) AS source_publication_at_kst,
         'exact_supplemental_paragraph_occurrences_grouped'::VARCHAR AS history_aggregation_status,
         count(DISTINCT full_report_observation_locator)::BIGINT AS full_report_observation_count,
         arg_min(full_report_observation_locator,full_report_observation_locator)
           AS full_report_observation_locator,
         to_json(list(DISTINCT full_report_observation_locator ORDER BY full_report_observation_locator))
           AS full_report_observation_locators_json
  FROM steward_report_horse_paragraph_history
  WHERE source_report_text_field='addJudgement'
  GROUP BY horse_id,event_date,venue_code,race_no,program_no_raw,paragraph_raw,
           parent_report_event_date,parent_report_meet_code,mention_semantics
)
SELECT horse_id,event_date,venue_code AS actual_meet_code,race_no,
       program_no_raw,paragraph_raw,match_rule,
       source_report_text_field,history_aggregation_status,
       parent_report_event_date,parent_report_meet_code,parent_report_race_no,
       full_report_observation_locator,full_report_observation_count,
       full_report_observation_locators_json,linked_mention_locators_json,
       mention_semantics,source_row_sha256,source_path,page_sha256,
       source_captured_at_utc,historical_publication_time_verified,
       source_publication_at_kst
FROM ordinary
UNION ALL
SELECT horse_id,event_date,venue_code AS actual_meet_code,race_no,
       program_no_raw,paragraph_raw,match_rule,
       source_report_text_field,history_aggregation_status,
       parent_report_event_date,parent_report_meet_code,parent_report_race_no,
       full_report_observation_locator,full_report_observation_count,
       full_report_observation_locators_json,linked_mention_locators_json,
       mention_semantics,source_row_sha256,source_path,page_sha256,
       source_captured_at_utc,historical_publication_time_verified,
       source_publication_at_kst
FROM supplemental;

-- One row per core event key. Absence means only that no row was observed in
-- the captured API set; it never asserts a clean event or exhaustive history.
CREATE VIEW steward_report_event_coverage AS
WITH events AS (
  SELECT try_cast(a.meet AS SMALLINT) AS actual_meet_code,
         substr(a.date,1,4)||'-'||substr(a.date,5,2)||'-'||substr(a.date,7,2) AS event_date,
         try_cast(a.race_no AS INTEGER) AS race_no,
         r.actual_venue_label_raw,a.execution_status,a.execution_verdict
  FROM race_execution_adjudicated a
  JOIN race_events r ON r.source_meet=a.meet AND r.result_date_key=a.date
                     AND r.result_race_no_key=a.race_no
  WHERE a.date BETWEEN '20100101' AND '20260929'
    AND a.meet IN ('1','3','4')
), reports AS (
  SELECT actual_meet_code,race_date_iso AS event_date,
         try_cast(CAST(rcNo AS VARCHAR) AS INTEGER) AS race_no,
         count(*)::BIGINT AS report_observation_count
  FROM steward_report_observations
  WHERE row_scope_status='included'
  GROUP BY actual_meet_code,race_date_iso,try_cast(CAST(rcNo AS VARCHAR) AS INTEGER)
), paragraphs AS (
  SELECT observation_locator,count(DISTINCT paragraph_locator)::BIGINT AS paragraph_count
  FROM steward_report_paragraphs GROUP BY observation_locator
), links AS (
  SELECT observation_locator,count(DISTINCT paragraph_locator)::BIGINT AS linked_horse_paragraph_count
  FROM steward_report_horse_links GROUP BY observation_locator
)
SELECT e.actual_meet_code,e.event_date,e.race_no,e.actual_venue_label_raw,
       e.execution_status,e.execution_verdict,
       coalesce(r.report_observation_count,0)::BIGINT AS report_observation_count,
       coalesce(sum(p.paragraph_count),0)::BIGINT AS paragraph_count,
       coalesce(sum(l.linked_horse_paragraph_count),0)::BIGINT AS linked_horse_paragraph_count,
       yc.response_partition_complete AS report_query_partition_complete,
       yc.response_partition_status AS report_query_partition_status,
       CASE WHEN r.report_observation_count IS NULL AND yc.response_partition_complete
              THEN 'no_report_row_in_complete_requested_year_meet_response'
            WHEN r.report_observation_count IS NULL AND yc.response_partition_complete IS FALSE
              THEN 'no_report_row_in_incomplete_requested_year_meet_response'
            WHEN r.report_observation_count IS NULL
              THEN 'no_report_row_and_no_partition_receipt'
            WHEN coalesce(sum(p.paragraph_count),0)=0 THEN 'report_present_no_nonblank_event_paragraph'
            WHEN coalesce(sum(l.linked_horse_paragraph_count),0)=0 THEN 'report_paragraphs_present_no_verified_horse_link'
            ELSE 'report_paragraph_with_verified_horse_link' END AS observed_report_state,
       'absence_not_evidence_of_clean_event_or_exhaustive_historical_availability'::VARCHAR AS interpretation_limit,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst
FROM events e
LEFT JOIN reports r USING(actual_meet_code,event_date,race_no)
LEFT JOIN steward_report_observations o
  ON o.actual_meet_code=e.actual_meet_code AND o.race_date_iso=e.event_date
 AND try_cast(CAST(o.rcNo AS VARCHAR) AS INTEGER)=e.race_no AND o.row_scope_status='included'
LEFT JOIN steward_source_year_meet_coverage yc
  ON yc.dataset='api215_judge_report'
 AND yc.requested_year=try_cast(substr(e.event_date,1,4) AS SMALLINT)
 AND yc.requested_meet=e.actual_meet_code
LEFT JOIN paragraphs p ON p.observation_locator=o.observation_locator
LEFT JOIN links l ON l.observation_locator=o.observation_locator
GROUP BY e.actual_meet_code,e.event_date,e.race_no,e.actual_venue_label_raw,
         e.execution_status,e.execution_verdict,r.report_observation_count,
         yc.response_partition_complete,yc.response_partition_status;

CREATE VIEW steward_report_nonexecution_observations AS
SELECT r.*,
       a.execution_status,a.execution_verdict,a.adjudication_status
FROM steward_report_observations r
JOIN race_execution_adjudicated a
  ON a.meet=CAST(r.actual_meet_code AS VARCHAR)
 AND a.date=replace(r.race_date_iso,'-','')
 AND try_cast(a.race_no AS INTEGER)=try_cast(CAST(r.rcNo AS VARCHAR) AS INTEGER)
WHERE a.execution_verdict='no_valid_completed_race';

CREATE VIEW steward_sanction_event_receipts AS
SELECT actual_meet_code,event_date,
       try_cast(CAST(race_no_raw AS VARCHAR) AS INTEGER) AS race_no,
       count(*)::BIGINT AS sanction_observation_count,
       count(*) FILTER (WHERE target_event_entry_link_verified)::BIGINT AS verified_target_event_entry_link_count,
       count(*) FILTER (WHERE NOT target_event_entry_link_verified)::BIGINT AS unresolved_target_event_entry_link_count,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst,
       'absence of a row is not evidence of no sanction or a clean race'::VARCHAR AS interpretation_limit
FROM steward_sanction_target_link_audit
GROUP BY actual_meet_code,event_date,try_cast(CAST(race_no_raw AS VARCHAR) AS INTEGER);

CREATE VIEW steward_sanction_event_coverage AS
SELECT c.actual_meet_code,c.event_date,c.race_no,c.actual_venue_label_raw,
       c.execution_status,c.execution_verdict,
       coalesce(s.sanction_observation_count,0)::BIGINT AS sanction_observation_count,
       coalesce(s.verified_target_event_entry_link_count,0)::BIGINT AS verified_target_event_entry_link_count,
       y.response_partition_complete AS sanction_query_partition_complete,
       y.response_partition_status AS sanction_query_partition_status,
       CASE WHEN s.sanction_observation_count>0 THEN 'sanction_rows_observed'
            WHEN y.response_partition_complete THEN 'no_sanction_row_returned_in_complete_query_not_negative_evidence'
            ELSE 'no_sanction_row_and_partition_not_complete' END AS observed_sanction_state,
       FALSE AS historical_publication_time_verified,
       CAST(NULL AS VARCHAR) AS source_publication_at_kst,
       'absence of API180_1 row is not evidence of no sanction'::VARCHAR AS interpretation_limit
FROM steward_report_event_coverage c
LEFT JOIN steward_sanction_event_receipts s USING(actual_meet_code,event_date,race_no)
LEFT JOIN steward_source_year_meet_coverage y
  ON y.dataset='api180_1_sanction_history'
 AND y.requested_year=try_cast(substr(c.event_date,1,4) AS SMALLINT)
 AND y.requested_meet=c.actual_meet_code;
