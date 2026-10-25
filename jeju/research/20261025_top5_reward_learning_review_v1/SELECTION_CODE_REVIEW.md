# Selection code review before choice execution

Status: **PASS for the reviewed selection source hash**, pending the root's separate hash-bound selection approval and independent replay of the resulting ledger.

- Earlier reviewed `select_sets.py` SHA-256: `3250ce2c1738e6501d7c8819caf353742100df50e624cb7ff5d83b208a833c44` (superseded)
- Final reviewed `select_sets.py` SHA-256: `332304c499615288b37d9bc485f45f926931dedaf35d8242a4823e14fc616d54`
- `FIT_RECEIPT.json` SHA-256: `5e193b1cfa382e61f87933b9072454ae402ab47cc542598fc174abdb3f1ed24d`
- Three model hashes are recorded in `FIT_RECEIPT.json`; the selector verifies those files against the receipt and its approval.

## Label-free input and choice logic

The final source differs from the earlier reviewed hash by dropping the selection-stage prior root/outcome summary check and consolidating receipt validation outside the per-year loop. The selector reads explicit raw-score/roster fields from the frozen baseline, saved evaluation score allowlists, and the 11 feature inputs plus race metadata. It does not materialize finish ranks, `y`, `p_top3`, loss, Brier, odds, or any new evaluation outcomes. The prior-study comparison source read during this stage is only the hash-locked choice ledger; outcome values are not parsed or used. The prior `outcomes.json` source check present in the first draft was removed before the final hash was frozen.

Per year, the selector applies the fold's saved scaler and beta to the same 11 raw inputs, holds the within-race standardized raw score coefficient at 1, and computes `E(S)=Σz+βᵀΣx` for every exact five-set in one race at a time. The saved selection is the maximum-energy set. Ties within the fixed `1e−12` tolerance prefer greatest overlap with the raw-score Top5, then the lexicographically smallest horse-number tuple. The explicit beta-zero negative control verifies identity with raw-score Top5 for all races. The receipt saves only one compact choice row per race plus counts and source/approval hashes; it does not save the full candidate space.

The source hashes the frozen baseline and feature files for provenance, but selects only the declared allowlisted columns. It checks exact score parity against stored F1_STYLE6 evaluation scores and verifies roster, key, date, horse number, field size, and distance consistency. It has no database/network access and creates outputs write-once inside the study directory.

## Remaining checks

After the separate root approval, `verify_locked_choices.py` independently replayed all 1,779 race choices and exact selected utilities, enumerating 411,084 candidate five-sets without importing the main selector or reading outcome values. It matched every selected set, utility, baseline utility, and race metadata field; the beta-zero control reproduced raw-score Top5 on 1,779/1,779 races. The prior partial-NLL Top5 and raw-score Top5 ledgers shared the same race cohort, and score parity matched all 17,412 evaluation runners. The compact audit receipt is `INDEPENDENT_CHOICE_AUDIT.json`.
