# Canonical publication bundle

Create a new directory for every attempted publication. Never reuse or edit an earlier bundle.

## Required files

- `runner_predictions.parquet`: one row per eligible runner. Include the six legacy ledger fields (`race_id`, `race_entry_id`, `horse_number`, `prob_win`, `prob_top2`, `prob_top3`) and all domain-specific detail fields from `publishing-contract.md`.
- `runner_explanations.json`: a JSON array with exactly three positive and three negative rows per runner. Each row contains `race_entry_id`, `component`, `feature_name`, `readable_feature_name`, `feature_value`, nullable `field_percentile`, `contribution_direction`, `contribution_value`, `contribution_rank`, `explanation_type`, `explanation_method`, and nullable `source_cutoff_at_ms`.
- `publication_metadata.json`: the immutable run envelope below.

## Metadata schema

```json
{
  "schema_version": 1,
  "domain": "thoroughbred",
  "prediction_stage": "initial_card",
  "experiment_run_id": "UUID",
  "model_type": "registered_main_prediction",
  "dataset_version": "frozen dataset/version",
  "as_of_policy": "day_before_18",
  "feature_hash": "64 hex characters",
  "model_artifact_sha256": "64 hex characters",
  "registry_sha256": "64 hex characters",
  "input_card_sha256": "64 hex characters",
  "source_card_at_ms": 0,
  "history_cutoff_date": "YYYY-MM-DD",
  "feature_cutoff_at_ms": 0,
  "data_availability_status": "complete",
  "probability_contract": "registry value",
  "combination_algorithm_version": "registry value",
  "parent_public_id": null,
  "runner_predictions_sha256": "optional file hash",
  "runner_explanations_sha256": "optional file hash",
  "components": [
    {
      "component": "A",
      "model_version": "registry component version",
      "candidate_name": "registry candidate",
      "artifact_sha256": "active registry artifact hash",
      "metadata_sha256": null,
      "algorithm_version": "scoring algorithm version",
      "parameters": {}
    }
  ],
  "notes": null
}
```

Use the active registry's domain contract and component hashes. `pre_race_update` requires the immutable `public_id` of its `initial_card` parent. It must never overwrite the parent.

## Domain-specific runner fields

Thoroughbred requires `a_rank_in_race`, `field_size`, `raw_a_top3_score`, `raw_bc_top3_score`, `raw_win_score`, and `starter_status`.

Jeju requires `a_rank_in_race`, `field_size`, `raw_rank_score`, `raw_order_score`, `beta_set`, `beta_order`, and `starter_status`. For Jeju, `a_rank_in_race` is the all-runner Top-3 marginal rank produced by the frozen `HY_R_FORM` distribution.

Optional snapshot fields are `runner_identifier`, `jockey_identifier`, `trainer_identifier`, `owner_identifier`, `cancellation_status`, `body_weight_kg`, `body_weight_change_kg`, and `data_quality_flags_json`.

The database publisher verifies all-runner completeness, probability monotonicity and sums, rank permutations, the six explanations, model hashes, card hashes, target project, live timing, and duplicate runs before appending anything.
