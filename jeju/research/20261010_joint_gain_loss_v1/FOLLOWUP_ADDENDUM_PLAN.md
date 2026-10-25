# Follow-up addendum: corrected subgroup label and fixed cross-tabs

This is a retrospective reporting correction and a descriptive cross-tab addendum requested after the core and first supplemental outputs had already been inspected. It is not a preregistration, confirmatory analysis, independent validation, or future-use rule. The core input contract, core outputs, original supplemental outputs, and their receipts remain unchanged.

## Locked calculations

1. Recompute the actual Top3 context summary only from the saved 252 runner rows representing three actual finishers in each of the 84 gained/lost races. First collapse to one vector per race, then report the 84 discordant races together as all_discordant_84, plus gained (50 races) and lost (34 races). Do not include empty both-hit/both-miss rows in this scoped table. This supersedes only the misleading all_1779 label in the earlier supplemental summary; the original file is preserved for audit.
2. Cross-tab the same fixed 1,779-race ledger by evaluation year × each exact saved distance and evaluation year × each source moisture band. Emit every combination from the fixed levels, including any zero-support cells. For each cell report race count, share of all 1,779 races, unique race dates, 2026-partial flag, gained/lost/net, both-hit/both-miss, each arm's hit counts/rates, and candidate-minus-baseline rate difference. No interval or threshold is computed for these added cells; they are descriptive support tables. Keep all rows and do not merge or select strata by observed outcomes.
3. Use exact race-level join keys, preserve source band labels/order, and verify each year and table partitions the fixed cohort. A zero-support cell has undefined rates and is explicitly marked zero_support; it is not imputed.

All results remain retrospective. Band and current-event body/burden timing are unverified at prediction time. Year × distance includes a partial 2026 and sparse 1300m/1400m/1610m support; the cross-tabs motivate at most a future pooled/shrunken validation hypothesis and do not support a distance-only gate.

## Outputs

- outputs_followup_addendum/actual_top3_context_summary_corrected.csv
- outputs_followup_addendum/year_distance_condition_summary.csv
- outputs_followup_addendum/year_moisture_band_condition_summary.csv
- outputs_followup_addendum/followup_receipt.json

