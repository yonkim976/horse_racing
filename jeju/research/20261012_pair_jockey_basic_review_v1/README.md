# Independent review: pair jockey basic feature

This folder contains an independent audit of the single rolling-365-day jockey feature arm in `20261012_pair_jockey_basic_v1`. The review read saved source files and artifacts only; it did not access the database or network, fit a model, or modify the candidate study.

The source/key and roster audit is in [REVIEW_MEMO.md](REVIEW_MEMO.md) and [source_coverage.json](source_coverage.json). Independent rolling-feature, fit arithmetic, and all-pair prediction/report checks are recorded in [rolling_feature_independent.json](rolling_feature_independent.json), [independent_fit_audit.json](independent_fit_audit.json), and [independent_prediction_audit.json](independent_prediction_audit.json). Reproduction scripts are saved beside each receipt.

All three audit stages passed. The candidate selected 429/1,779 races versus 427 for the latest pair reference, but the primary date-bootstrap interval was `[-0.003396, 0.005695]`; the raw-429 gate also failed. The review therefore confirms implementation and reported arithmetic, not evidence of an improvement. Root later removed identical duplicate keys from the prediction receipt and refreshed dependent hashes; the fit and prediction artifacts stayed byte-for-byte unchanged. Source-cohort, historical jockey-publication-time, and repeated-development-sample limits are described in the memo.
