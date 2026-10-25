# Hash-pinned input contract

Status: draft for root approval. These source paths, hashes, keys, and label roles are fixed before calculating any new result. The study will fail closed if an input differs.

## Immutable inputs

| Role | Path | SHA-256 |
|---|---|---|
| Joint-study manifest and source lineage | `jeju/research/20261010_joint_relationship_v1/ARTIFACT_MANIFEST.json` | `d0d1a749afb6a6f894de1bb4263c9d67dd1e3b2d1a35bf1b5fd38d8948c656b0` |
| Full unordered Top3 distributions for both arms | `jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet` | `13409e65353c0cb6dab14df97317cce24de913056ae464ee3524520759de681c` |
| Per-runner Top3 outcomes and saved marginal references | `jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv` | `0e6a01607164a7cb54fbbb5fb445e975ea9fbadad21d4e7a842adfc915616a09` |
| Existing per-race six-ticket parity reference | `jeju/research/20261010_joint_relationship_v1/outputs/report/race_metrics.csv` | `89820acf0dfafc749f394cf9e74a3b58a5ec890e2c746f890ad257eaf32ff115` |
| Existing report receipt | `jeju/research/20261010_joint_relationship_v1/outputs/report/report_receipt.json` | `5720519b0d8860f5652650b4d2ee3b6f8444a6c6f01421395cd51f4a0251fae4` |
| Finish-position labels for secondary exact-Top2 outcome | `jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet` | `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f` |
| Label and cohort definitions for the saved feature artifact | `jeju/research/20261010_style_history_ablation_v1/CONTRACT.md` | `c10aac8f6faa6e841afd9ef829bfa0b29ada2dceabcbb5405fdfad9c12536bf9` |

The first two hashes are the locked primary distribution inputs. The runner file supplies Top3 labels and per-runner join validation. `race_metrics.csv` and `report_receipt.json` are used only to verify the already saved six-ticket parity and cohort metadata. `features.parquet` supplies finish ranks solely for the empirical exact-Top2 secondary label. It does not supply policy scores or alter the existing distribution.

## Cohort and join keys

The evaluation cohort is the saved 2024-01-05 through 2026-09-19 cohort: 1,779 races, 17,412 runners, and 269 race dates. Treat 2026 as a partial year. Field sizes range from 7 to 12, so all five anchored policies can supply three or four unique tickets throughout the cohort. Do not run pair-anchored K=6: a two-horse pair has only `N−2` unique remaining-member tickets, leaving the 36 seven-runner races unable to fill six. The only K=6 analysis is unrestricted top six for the original 407/423 hit-rate parity reference. Use `race_id` as the race key and `(race_id, horse_number)` for runner labels. For triples, use `(race_id, arm, triple_numbers)`; parse each `triple_numbers` string as a sorted tuple of distinct integer horse numbers.

The exact-Top3 truth is the unique triple marked `is_true_set=true` for a race and arm, cross-checked against `y_top3` in `runner_marginals.csv` and the frozen label definition in the source contract. Join the feature label rows to `runner_marginals.csv` by unique `api_record_id`; cross-check `race_id` and `horse_number`, and `horse_id` where both sources provide it. Require source event-runner keys to be one-to-one. For the secondary exact-Top2 outcome, a selected pair hits only when its two horse numbers have observed `finish_position` values 1 and 2, in either order, in the same race. This label is evaluated after ticket selection and never used to select an axis or ticket. Fail closed if any race does not have exactly one unambiguous first-place and one unambiguous second-place runner under the saved normal-finish cohort.

## Required integrity checks before scoring policies

After root approves the plan, verify hashes before reading analytical values. Then require:

- Both arms contain the same race, roster, and unordered-triple keys, with one row per key and complete `C(N,3)` triples per race.
- Each arm's per-race `probability` values are finite and in `[0,1]`, and sum to 1 within absolute tolerance `1e-12`. Do not renormalize or round source probabilities.
- Reconstructed per-runner Top3 marginals and labels agree with `runner_marginals.csv`; marginal probabilities sum to 3 within `1e-12`. Pair-in-Top3 probabilities, computed by summing `q` over triples containing each pair, have total mass 3 per race within `1e-12`.
- `canonical_rank` is unique within each race and arm and matches descending `total_energy`; canonical numeric triple ordering resolves exact `total_energy` ties only. Saved `probability` is nonincreasing in `canonical_rank`; equal floating-point probabilities do not imply a tie when `total_energy` differs. Recreate unrestricted top-six tickets and verify exact ticket parity and the existing hit totals: 407 `matched_baseline`, 423 `candidate`.
- The `api_record_id` join to `features.parquet` is one-to-one for the evaluation cohort; cross-check `race_id`, `horse_number`, and `horse_id` where available. The Top3 outcome agrees with the frozen `finish_position <= 3` label. Verify unique observed finish ranks 1 and 2 before scoring the empirical exact-Top2 secondary outcome.
- Race date and evaluation year agree across the frozen sources; the resulting cohort has the expected race, runner, and race-date counts.

Probability accumulation must use `math.fsum` over canonical source order. The stated `1e-12` tolerance is only for probability identity checks; it is never used to declare ranking ties. Rankings use the frozen `canonical_rank` where applicable, and exact policy-score ties use the tie rules in `PLAN.md`.

## Forbidden inputs and mutations

Do not access the shared or local database, network, operating registry, current model, or any source outside the table above. Do not fit or recalibrate a model. Do not use labels to change policy definitions, thresholds, bins, tie rules, or the evaluation cohort. Do not edit any pinned source or existing research folder. Any approved implementation and outputs belong only under `jeju/research/20261010_pair_axis_v1/`.
