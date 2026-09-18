# Prediction publishing contract

## Canonical runner payload

Every eligible runner must have these values before publication:

- race identity: `race_id`, `race_date`, `venue_code`, `race_no`
- runner identity: `race_entry_id`, `hr_no`, `chul_no`, `horse_name`
- probabilities from the same A joint distribution: `prob_win`, `prob_top2`, `prob_top3`
- A presentation: `a_rank_in_race`, `field_size`
- reproducibility: `raw_a_top3_score`, `raw_bc_top3_score`, `raw_win_score`
- snapshots: jockey, trainer, owner, starter/cancellation state, and available same-day fields

The production database may use `model_predictions` plus additive component and explanation tables. Do not discard required fields just because the legacy ledger lacks columns.

For Jeju `HY_R_FORM`, preserve `rank_score`, `order_score`, `beta`, and `beta_order` instead of inventing the three Thoroughbred raw scores. Derive all-runner Top-3 inclusion from the set distribution and, when the canonical ledger requires them, derive win/top2 marginals from the same normalized HY_R_FORM exact-order joint distribution. Never route Jeju data through the Thoroughbred model contract.

## Stages

- `initial_card`: official card plus strictly earlier history. Same-day body weight, weather, moisture, and track fields are null/not available unless their publication time is proven.
- `pre_race_update`: a separate run using only changes publicly available before its cutoff. It must reference the initial run and never overwrite it.

The final live run is the selected stage appended to the immutable ledger. Existing live runs are not updated.

## A/B/C

- Store all runner A probabilities and the A-joint win/top2 marginals.
- Store raw A, B/C, and order scores with the exact temperatures and algorithm version.
- For Jeju, store HY_R_FORM rank/order scores and both beta values with the bundle hash and `jeju_hybrid_distribution` algorithm version.
- Do not store B/C combination rows. Backend calculation must enumerate the full support, normalize it, apply stable tie-breaking, and return only requested top K.
- A current top-10 combination file is a regression fixture, not the source of truth.

## Explanations

Use A-model raw-score contributions. Save top-three positive and negative interpretable features. Store raw feature name/value, reviewed Korean name, field percentile where meaningful, contribution value/direction/rank, method, and cutoff. ID effects are categorical model effects, not evidence of human skill or causation.

## Transaction and verification

Use one transaction for the run, model components, every runner, and explanations. Abort if any race is incomplete, probabilities fail invariants, an ID mapping is ambiguous, a hash differs, or the DB schema cannot preserve the payload.

After commit, read the run back and compare canonical payload hashes. Never retry a successful or uncertain live commit blindly; query by payload hash and race first.
