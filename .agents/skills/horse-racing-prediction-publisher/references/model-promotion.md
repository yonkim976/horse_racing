# Production model promotion

Prediction execution and model promotion are separate operations. A prediction request must never turn an experimental result into the production model.

## Promotion requirements

A new profile can replace the active profile only when all of the following are available:

1. Frozen model and metadata artifacts for every required component.
2. Strictly past-only feature construction and a reproducible inference entrypoint.
3. Target-specific A/B/C calibration without cross-target probability mixing.
4. Completed verification artifacts with explicit pass status.
5. Comparative evidence against the current champion on the predeclared primary metric and stability gates.
6. A written decision that the production model changed. A study whose result is `production_changed: false` is not a promotion.
7. SHA-256 values for every executable, model, metadata, selection, and verification artifact.
8. A successful dry-run that reproduces a locked fixture and passes runner-level probability invariants.

## Registry update

Create a new immutable profile in `config/prediction_model_registry.json`, set its status to `production`, and change the domain's `active_profile` only after the above evidence is reviewed. Do not mutate the old profile; retain it for run reproduction.

The active profile must contain component paths and hashes, an inference reference, verification gates, probability-contract version, and algorithm version. After editing the registry, run the resolver and commit the registry change with the new artifacts or stable artifact references.

Do not select models by directory date, version number, a single hit rate, or a single backtest row. Those signals can be newer while still failing the production gate.
