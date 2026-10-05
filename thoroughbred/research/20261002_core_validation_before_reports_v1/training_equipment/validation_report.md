# Training and equipment pre-report validation

Status: **passed_with_documented_limitations** (65 pass, 0 fail).

Database: `/Users/kimyongjin/Desktop/horse_racing/thoroughbred/data/core_api_2010_20260929_v1/backups/20261002_before_steward_reports/thoroughbred_core.duckdb` (read-only; SHA-256 `616aa6111242cfbcee4b87bc2e77251644e5c3780fc8c978319f69e7b1c4c8f7`).

Scope: event dates 2010-01-01 through 2026-09-29; model window starts 2017-01-01. API78 includes meets 1/3/4. Training and starting-exam source records include API meets 1/3.

## Checks

- **PASS** `backup_database_hash_matches_manifest` — expected `616aa6111242cfbcee4b87bc2e77251644e5c3780fc8c978319f69e7b1c4c8f7`, actual `616aa6111242cfbcee4b87bc2e77251644e5c3780fc8c978319f69e7b1c4c8f7`.
- **PASS** `backup_database_hash_matches_pair_attestation` — expected `616aa6111242cfbcee4b87bc2e77251644e5c3780fc8c978319f69e7b1c4c8f7`, actual `616aa6111242cfbcee4b87bc2e77251644e5c3780fc8c978319f69e7b1c4c8f7`.
- **PASS** `backup_manifest_hash_matches_pair_attestation` — expected `6aa4d2870fbd087afa81973d5fc8f3966cfc00fd7896c656cb4fedaef2ef1697`, actual `6aa4d2870fbd087afa81973d5fc8f3966cfc00fd7896c656cb4fedaef2ef1697`.
- **PASS** `backup_pair_attested_equal` — expected `True`, actual `True`.
- **PASS** `research_source_manifest_rows_present` — expected `['equipment_api78_full_v1', 'starting_exam_api21_1_v1', 'training_three_api18_api22_api216_v1']`, actual `['equipment_api78_full_v1', 'starting_exam_api21_1_v1', 'training_three_api18_api22_api216_v1']`.
- **PASS** `manifest_object_inventory_matches_backup` — expected `{'declared_object_count': 178, 'allowed_unregistered_intermediate_views': ['confirmed_runners_entity_reviewed_before_role_review', 'trial_participants_entity_reviewed_before_role_review']}`, actual `{'object_count': 180, 'missing': [], 'unexpected': ['confirmed_runners_entity_reviewed_before_role_review', 'trial_participants_entity_reviewed_before_role_review']}`.
- **PASS** `official_entity_roster_key_unique` — expected `0`, actual `0`.
- **PASS** `equipment_batches_scope_and_count` — expected `{'1': 1562, '3': 1553, '4': 2}`, actual `{'1': 1562, '3': 1553, '4': 2}`.
- **PASS** `equipment_batch_date_bounds` — expected `['20100108', '20260920']`, actual `['20100108', '20260920']`.
  Capture dates can postdate the requested last event date when no later in-scope card exists; event rows are separately bounded.
- **PASS** `equipment_batch_meet_and_event_scope` — expected `0`, actual `0`.
- **PASS** `equipment_selected_batches_complete` — expected `0`, actual `0`.
- **PASS** `equipment_observation_count` — expected `331450`, actual `331450`.
- **PASS** `equipment_observation_scope` — expected `0`, actual `0`.
- **PASS** `equipment_observation_primary_key_unique` — expected `331450`, actual `331450`.
- **PASS** `equipment_source_locator_unique` — expected `0`, actual `0`.
- **PASS** `equipment_observations_trace_to_page_manifest` — expected `0`, actual `0`.
- **PASS** `equipment_raw_field_state_consistent` — expected `0`, actual `0`.
- **PASS** `equipment_is_retrospective_and_wear_unknown` — expected `0`, actual `0`.
- **PASS** `equipment_plus_minus_marks_preserve_raw_semantics` — expected `0`, actual `0`.
  A trailing + means new; a trailing - means removed; all other tokens are unmarked.
- **PASS** `equipment_tokens_reconstruct_exactly_from_raw_field` — expected `326385`, actual `{'expected_token_rows': 326385, 'missing_token_rows': 0, 'raw_token_mismatches': 0, 'name_mismatches': 0, 'mark_mismatches': 0}`.
- **PASS** `equipment_removed_tokens_excluded_from_active_declared_view` — expected `0`, actual `0`.
- **PASS** `equipment_active_declared_view_retains_all_nonremoved_tokens` — expected `312714`, actual `312714`.
- **PASS** `equipment_core_runner_ledger_five_key_unique` — expected `[330465, 330465]`, actual `[330465, 330465]`.
- **PASS** `equipment_core_coverage_has_each_confirmed_runner_once` — expected `[330465, 330465]`, actual `[330465, 330465]`.
- **PASS** `equipment_runner_ledger_exact_confirmed_runner_keyset` — expected `0`, actual `0`.
- **PASS** `equipment_link_requires_one_core_key_and_name_match` — expected `0`, actual `0`.
- **PASS** `equipment_api78_priority_and_score_fallback_separation` — expected `0`, actual `0`.
- **PASS** `equipment_declared_union_fallback_preserves_api_priority_and_excludes_removed` — expected `{'rows': 311790, 'removed_rows': 0}`, actual `{'rows': 311790, 'removed_rows': 0}`.
- **PASS** `equipment_links_resolve_by_exact_runner_key_and_normalized_name` — expected `0`, actual `0`.
- **PASS** `equipment_linked_observations_map_one_to_one_to_core_runner` — expected `[330106, 330106]`, actual `[330106, 330106]`.
- **PASS** `training_observation_counts` — expected `{'daily_training': 5173033, 'start_training': 431517, 'swim_training': 459604}`, actual `{'daily_training': 5173033, 'start_training': 431517, 'swim_training': 459604}`.
- **PASS** `training_meet_and_date_scope` — expected `0`, actual `0`.
- **PASS** `training_observation_id_primary_key_unique` — expected `6064154`, actual `6064154`.
- **PASS** `training_same_source_locator_unique` — expected `0`, actual `0`.
- **PASS** `training_source_locator_and_raw_fields_present` — expected `0`, actual `0`.
- **PASS** `training_observations_trace_to_selected_source_files` — expected `0`, actual `0`.
- **PASS** `training_full_date_meet_coverage_matches_contract` — expected `{'daily_training': (12232, 10211, 2021, 0), 'start_training': (12232, 5688, 6544, 0), 'swim_training': (12232, 5691, 6541, 0)}`, actual `{'daily_training': (12232, 10211, 2021, 0), 'start_training': (12232, 5688, 6544, 0), 'swim_training': (12232, 5691, 6541, 0)}`.
- **PASS** `training_coverage_rows_match_observation_counts` — expected `0`, actual `0`.
- **PASS** `training_coverage_scope` — expected `0`, actual `0`.
- **PASS** `training_horse_links_are_exact_official_id_only` — expected `0`, actual `0`.
- **PASS** `training_retro_availability_and_unadjudicated_venue_flags` — expected `0`, actual `0`.
- **PASS** `training_views_preserve_base_rows` — expected `{'daily_training_raw': 5173033, 'start_training_raw': 431517, 'swim_training_raw': 459604, 'training_observation_qa': 6064154, 'training_date_coverage': 36696}`, actual `{'daily_training_raw': 5173033, 'start_training_raw': 431517, 'swim_training_raw': 459604, 'training_observation_qa': 6064154, 'training_date_coverage': 36696}`.
- **PASS** `training_source_payload_json_valid` — expected `0`, actual `0`.
- **PASS** `daily_training_known_nonidentical_natural_key_variants` — expected `{'repeated_groups': 8, 'affected_rows': 16, 'excess_rows': 8, 'nonidentical_groups': 8, 'nonidentical_rows': 16}`, actual `{'repeated_groups': 8, 'affected_rows': 16, 'excess_rows': 8, 'nonidentical_groups': 8, 'nonidentical_rows': 16}`.
- **PASS** `daily_training_existing_raw_value_qa_flags` — expected `{'duration_negative': 8, 'duration_zero': 11, 'end_before_start': 9, 'duration_differs_from_raw_time_delta': 337, 'nonidentical_natural_key_variant': 16}`, actual `{'duration_differs_from_raw_time_delta': 337, 'duration_negative': 8, 'duration_zero': 11, 'end_before_start': 9, 'nonidentical_natural_key_variant': 16}`.
- **PASS** `training_exact_payload_repeats_match_existing_qa` — expected `{'swim_training': (8, 24, 16)}`, actual `{'swim_training': (8, 24, 16)}`.
  Repeated source payload rows are preserved as QA observations and are not interpreted as real training-session counts.
- **PASS** `api22_occurrence_order_not_promoted_to_event_or_chronology` — expected `0`, actual `0`.
- **PASS** `swim_raw_counts_preserved_and_unit_unresolved` — expected `{'zero_rows': 3, 'twenty_plus_rows': 33, 'resolved_unit_rows': 0}`, actual `{'zero_rows': 3, 'twenty_plus_rows': 33, 'resolved_unit_rows': 0}`.
- **PASS** `starting_exam_observation_count` — expected `52325`, actual `52325`.
- **PASS** `starting_exam_meet_and_date_scope` — expected `0`, actual `0`.
- **PASS** `starting_exam_observation_primary_key_unique` — expected `52325`, actual `52325`.
- **PASS** `starting_exam_source_locator_unique` — expected `0`, actual `0`.
- **PASS** `starting_exam_observations_trace_to_selected_source_files` — expected `0`, actual `0`.
- **PASS** `starting_exam_daily_coverage` — expected `12232`, actual `12232`.
- **PASS** `starting_exam_all_34_year_meet_partitions_complete` — expected `34`, actual `34`.
- **PASS** `starting_exam_exact_repeat_keys_preserved` — expected `{'repeated_key_groups': 8, 'repeated_key_rows': 16, 'repeated_excess_rows': 8, 'exact_repeat_groups': 8, 'nonidentical_groups': 0}`, actual `{'repeated_key_groups': 8, 'repeated_key_rows': 16, 'repeated_excess_rows': 8, 'exact_repeat_groups': 8, 'nonidentical_groups': 0}`.
- **PASS** `starting_exam_missing_natural_key_components_retained` — expected `128`, actual `128`.
  Rows missing a source key component are retained and not force-linked.
- **PASS** `starting_exam_horse_link_exact_id_and_unmatched_ledger` — expected `0`, actual `0`.
- **PASS** `starting_exam_role_link_view_cardinality` — expected `156975`, actual `156975`.
- **PASS** `starting_exam_person_role_links_use_exact_source_ids` — expected `0`, actual `0`.
- **PASS** `starting_exam_rider_names_not_linked_as_jockey_ids` — expected `0`, actual `0`.
- **PASS** `starting_exam_retro_availability_and_venue_flags` — expected `0`, actual `0`.
- **PASS** `starting_exam_view_cardinalities` — expected `{'starting_exam_results': 52325, 'starting_exam_qa': 52325, 'starting_exam_sessions': 3538, 'starting_exam_date_coverage': 12232, 'starting_exam_entity_links': 156975}`, actual `{'starting_exam_results': 52325, 'starting_exam_qa': 52325, 'starting_exam_sessions': 3538, 'starting_exam_date_coverage': 12232, 'starting_exam_entity_links': 156975}`.
- **PASS** `starting_exam_source_payload_json_valid` — expected `0`, actual `0`.
- **PASS** `database_hash_unchanged_after_readonly_audit` — expected `616aa6111242cfbcee4b87bc2e77251644e5c3780fc8c978319f69e7b1c4c8f7`, actual `616aa6111242cfbcee4b87bc2e77251644e5c3780fc8c978319f69e7b1c4c8f7`.

## Source and scope limitations

- **training_and_starting_exam_meet3_is_integrated_region** — API18_1/API22_1/API216 and API21_1 provide meet 1 and raw meet 3 only. Meet 3 remains the source's Yeongnam region label and cannot be split into Busan meet 3 and Yeongcheon meet 4; no meet 4 rows are present in these datasets.
- **all_three_sources_are_retrospective** — The source captures do not establish historical pre-race availability. Every row retains a retrospective/unverified status. The 2017+ row counts are reported separately; passing this QA does not approve feature use.
- **training_payload_repeats_are_not_session_counts** — Identical repeated source payloads, especially the 24-row/8-group swim repeat set, remain observations and must not be interpreted as additional real workouts without a separate aggregation rule. API22 occurrence order is anonymous storage order, not an event ID or chronology.
- **entity_reference_roster_is_exact_id_reference_only** — Horse, trainer and owner links use exact source official IDs. Names are not join keys; current profile trainer/owner values are not backfilled into historical rows. Unmatched and missing source IDs remain separate exceptions.
- **two_manifest_unregistered_intermediate_views** — The backup contains confirmed_runners_entity_reviewed_before_role_review and trial_participants_entity_reviewed_before_role_review outside the manifest object-count map. The coordinator confirmed these two helper views are intentional unregistered intermediates; all other declared object names match.

## Output

The JSON report retains counts, grouped statuses, provenance hash checks, and any failed check details.
