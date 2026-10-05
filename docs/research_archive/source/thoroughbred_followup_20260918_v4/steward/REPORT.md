# Seoul/Busan steward-event extraction audit

This is a conservative research extraction from the 3,024 locally stored official steward report rows dated 2025-01-03 through 2026-09-13: 1,780 Seoul reports and 1,244 Busan reports. All 3,024 reports linked to an operational race roster, covering 32,584 entry rows. No v3 artifact or model was changed.

## Result

The final table contains **5,136 horse-event rows** across 2,533 races and 2,297 horses: 2,909 delayed starts (2,135 reports; 1,631 horses), 364 explicitly bad break/start-process events (336 reports; 295 horses), 1,207 blocked/trouble events (971 reports; 972 horses), 600 observed wide paths (544 reports; 494 horses), and 56 direct kickback reactions (55 reports; 56 horses). The wide label records an observed wide path; it does **not** assert disadvantage, causality, or lost distance. Counts by venue are in `extraction_summary.json`.

Every positive requires a circled horse number plus quoted name, exact agreement with that race roster, and a bounded direct predicate. Ordinary numbers such as distances, dates, margins, and jockey references cannot create a horse event. Each row retains report ID, source field, exact paragraph, matched substring and offsets, date, race/entry/horse IDs, collection time, and an explicit posting-availability warning.

`additional_judgement` is excluded from positives. Its 411 nonempty fields frequently refer to a prior meeting/race while the table row carries the later report key; without a separate referenced-race parser, a coincidental number/name match could silently assign the event to the wrong race.

## Audit and limitations

The locked stratified positive sample has 58 records (up to six per venue × event type; Busan kickback has four total). Manual review found 58/58 supported with the correct horse. This is sample precision only, not a whole-corpus precision or recall claim.

The 40-record ambiguity sample found 24 recoverable positives, 15 correct exclusions, and one uncertain case. The missed positives mainly require Korean anaphora (`동 말`), collective predicates, nonstandard quote characters, or broader narrative interpretation. This is intentional precision-first loss. Keyword-only paragraphs, generic sentences, hypothetical concern about going wide, avoiding kickback, and prior-race supplemental text remain excluded. `ambiguous_candidates.parquet` preserves all 1,635 candidates and reasons for future adjudication.

Concrete misses include report 2697, where the bad-break ruling refers back with `동 말`; report 3867, where kickback reaction is narrated after a long jockey statement; and report 3874, where two horses share the collective wide predicate. A useful correct exclusion is report 460: the paragraph contains “바깥” language while adjudicating interference and does not directly say the named horse ran a wide path. Report 3678 also demonstrates why roster disagreement is a hard stop: number ⑧ is `예술이야` in the linked roster while the text names `파워풀비전`.

The source provides `observed_at_ms` collection times in 2026, not historical publication timestamps. Therefore the events are **retrospective-only with posting availability unverified**. The proposed previous-race features in `strict_prior_feature_spec.json` require `event race_date < prediction race_date`, exclude same-date reports, and distinguish report-known exposure. Even those guards do not establish leakage-free deployment until posted-at evidence exists.

## Reproduction

Run `.venv/bin/python extract_steward_events.py` in a clean copy of this directory. The script refuses to overwrite artifacts unless `--overwrite` is explicitly supplied. `source_reports_snapshot.parquet` and `roster_snapshot.parquet` freeze the exact rows used; their hashes are in `extraction_summary.json`. Run `.venv/bin/python validate_extraction.py` for roster, match-span, duplication, field, and audit checks.

The full event and ambiguity outputs are Parquet only. The two small JSON audit samples retain human-readable snippets. `REVISION_LOG.md` records failures found and corrected during the initial audit.
