---
name: horse-racing-prediction-publisher
description: Run the horse_racing project's explicitly promoted main prediction model, validate complete runner probabilities and explanations, and safely append a draft, historical, or live prediction run to its database. Use when asked to predict a race card, inspect which production model would run, prepare prediction payloads, or publish/store prediction results. Do not use to train, compare, or automatically promote experimental models.
---

# Horse Racing Prediction Publisher

Operate only inside the `horse_racing` repository. Treat predictions as immutable publications, not rows to overwrite.

## Resolve the model first

Run:

```bash
.venv/bin/python .agents/skills/horse-racing-prediction-publisher/scripts/resolve_main_model.py --repo-root . --domain DOMAIN
```

Use only the active profile in `config/prediction_model_registry.json` after the resolver passes every path, hash, and verification gate.

- Route Seoul, Busan, and Yeongcheon Thoroughbred cards to `--domain thoroughbred`.
- Route Jeju native-horse cards to `--domain jeju`. Its current champion must resolve to `HY_R_FORM`.
- Never mix artifacts, features, calibrations, or raw-score contracts across the two domains.

- “Best/main model” means the model explicitly promoted in the registry after evaluation, not the newest folder, highest isolated metric, or most recent experiment.
- Never auto-promote an experiment during a prediction request.
- If a later study says `production_changed: false`, retain the current profile.
- If no valid active profile exists, hashes differ, or a verification gate fails, stop before inference or DB writes and report the exact blocker.
- Read [model-promotion.md](references/model-promotion.md) only when asked to adopt/promote a newly developed model.

## Choose the requested mode

- A request to “predict” authorizes read-only inference and validation only.
- A request to “save as draft/historical” authorizes that named append-only write after validation.
- A request to “publish/save to the production DB” authorizes one live append after validation. Resolve the exact date, venue, stage, and target project before writing.
- Never infer live publication from a plain prediction request. Never update or delete an existing prediction run.

Read [publishing-contract.md](references/publishing-contract.md) before any DB write or when building the canonical payload.

## Prediction workflow

1. Confirm the repository and working tree. Preserve unrelated changes and all research artifacts.
2. Resolve the active model profile. Record the registry SHA-256 and every component artifact SHA-256 in the run metadata.
3. Freeze the card source timestamp, history cutoff, prediction stage (`initial_card` or `pre_race_update`), and input-card SHA-256.
4. Run the registered inference implementation in a new output directory. Do not edit model artifacts or prior outputs.
5. Produce one canonical runner row for every non-scratched entry. A Thoroughbred publication needs A-joint `prob_win`, `prob_top2`, `prob_top3` and three raw scores. A Jeju publication needs HY_R_FORM joint marginals plus `rank_score`, `order_score`, `beta`, and `beta_order`. Do not mix domains or target calibrations.
6. Validate the payload before writing:

```bash
.venv/bin/python .agents/skills/horse-racing-prediction-publisher/scripts/validate_prediction_payload.py PATH_TO_PARQUET --domain DOMAIN
```

Use `--publication` only after the domain-specific output has been converted to the canonical DB runner payload.

7. Generate explanations from the registered A model with LightGBM `pred_contrib=True`; retain the top three positive and negative interpretable contributions per runner. Keep jockey/trainer/owner/horse-ID effects under `categorical_model_effect`, never as causal claims.
8. Recompute B/C from the runner raw scores only as a verification fixture. Do not persist combination rows; the backend serves top K combinations deterministically.
9. Before a write, confirm the destination schema supports all required runner components, explanations, stage lineage, and model metadata. If it does not, stop and report the missing migration instead of silently dropping fields.
10. Write the run, component metadata, all runner rows, and explanations in one transaction through the repository publisher. Roll back on any mismatch.
11. Read the stored run back and verify entry count, race coverage, payload hash, registry hash, model hashes, and probability invariants. Report the immutable run ID and publication mode.

When the user explicitly authorizes a database save, build the canonical bundle described in [publication-bundle.md](references/publication-bundle.md), then run:

```bash
.venv/bin/python .agents/skills/horse-racing-prediction-publisher/scripts/publish_prediction_bundle.py \
  PATH_TO_BUNDLE \
  --publication-mode live \
  --expected-project-ref xkykmhhkjtosptoibduo \
  --gcp-secret horse-racing-database-url \
  --gcp-project mapilog-509017 \
  --confirm-write
```

Use `historical` only when requested. The production command reads the existing Secret Manager value in memory and never prints it. The publisher refuses SQLite unless its hidden test-only flag is used, verifies the configured Supabase project ref without printing credentials, re-verifies the active registry and artifact hashes, and performs a read-back check after commit. Never run it for a plain prediction-only request.

## Required invariants

- Every eligible runner appears exactly once; no partial race is published.
- Per runner: `0 ≤ prob_win ≤ prob_top2 ≤ prob_top3 ≤ 1`.
- Per race, runner marginals sum to 1, 2, and 3 respectively, within `1e-6`.
- A is the runner Top-3 inclusion probability. B is one unordered Top-3 set probability. C is one exact 1→2→3 order probability.
- Never multiply A values to create B, combine B and C, or mix target-specific calibrations.
- Initial-card and pre-race-update predictions use different run IDs. Missing same-day inputs remain null with an availability status.
- Do not publish after the applicable as-of deadline, include scratched runners in a final live run, or republish a race that already has a live run.
- Never expose database passwords, secret keys, or `service_role` credentials in files, logs, prompts, or frontend code.

## Current champions

- Thoroughbred: A v5 `rolling_all`, B/C v4 `top3_growth_strength`, order v2 `H3_relative`.
- Jeju native: frozen `HY_R_FORM` bundle and `scripts/predict_jeju_live_hy_r_form.py`.

Future candidates replace these only through an explicit verified registry promotion.
