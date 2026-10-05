# v4/model reproduction and inference

The frozen candidate is a research-only model. v3 and the operational database are
read-only inputs. `selection_frozen_before_reference.json` is the decision record;
2025--2026 are exposed reference results and cannot change it.

From the repository root, verify the delivered artifacts:

```bash
.venv/bin/python data/research/thoroughbred_followup_20260918_v4/model/code/verify.py
```

The reproduction wrapper requires a nonexistent destination, copies the exact frozen
inputs/code, replays all six folds, and then audits the already-frozen selection using
only rows with year <= 2024. A replay necessarily knows the historical reference
exists; it does not claim to recreate the original decision timing.
It writes `selection_audit.json` with status
`historical_replay_dev_only_selection`, `reference_metrics_present_at_audit=true`,
and `fresh_freeze=false`; it never labels the replay as a new pre-reference freeze.

```bash
.venv/bin/python data/research/thoroughbred_followup_20260918_v4/model/code/reproduce.py \
  --output /absolute/path/to/nonexistent_replay_directory
```

Recreate the selected September 19--20 output (destination must not exist):

```bash
.venv/bin/python data/research/thoroughbred_followup_20260918_v4/model/code/infer_selected_future.py \
  --output /absolute/path/to/nonexistent_forecast_directory
```

The future inference rebuilds the six v4 features from history ending before the
card dates, never updates from either future date, uses v3 `top3_allcore` for A and
v4 `top3_growth_strength` for B/C, and leaves v3 r2 untouched.
