# Medical dictionary snapshot v1

This folder contains a frozen research dictionary built from saved KRA source captures and the reviewed phrase snapshot. It contains no medical event rows and does not assign diagnoses to horses or races.

## Scope and handling

- The phrase review snapshot spans the previous all-meet source inventory. Its old usage counts are not copied into this package and are not a research-scope count. The event loader must compute counts from the approved Seoul and Busan-Gyeongnam source rows for 2010-01-01 through 2026-09-29.
- API33 `illDesc` is preserved exactly; every source value is `-`, so it is not treated as an explanation.
- KRA web glossary, KRA profile captures, and user-provided KRA detail are distinct sources. `collected_at_kst` records when the capture was saved; `event_date_local`/`event_dates_json` record historical profile dates. `source_publication_at_kst` is null because the saved evidence does not provide a publication time.
- Profile source meet 2 is Jeju, meet 1 is Seoul, and meet 3 is Busan-Gyeongnam. The captured explanation evidence is retained with its original source meet; the research event loader must exclude Jeju clinical events.
- Phrase IDs are SHA-256 hashes of the exact UTF-8 raw phrase. Operating database integer IDs are deliberately absent. Original phrase text, including spacing and punctuation, is preserved.
- `phrase_components.reviewed_target_ordinal` preserves the order in the review cell separated by exact ` | `. It is the saved reviewed target order, not an inferred diagnosis-slot order. It must not be used to split source event slots.
- Phrase rows preserve the approved review status, but `event_link_policy` disables automatic event linking. Contextual mappings require fresh in-scope event evidence; do not turn them into global aliases.
- 356 historical Dacom72 decisions removed literal `동물  ` before matching. That prefix can come from a hospital-cell parsing artifact in the prior Text workflow; `mapping_rule_scope=prior_rpt_parser_context_only` and `prefix_rule_reusable=false` keep those decisions as audit evidence only. Do not strip the prefix from new API16_1 diagnosis slots.
- Excluded phrase rows stay in `phrase_decisions.parquet` with their exact raw text and review note; the source text is not altered or deleted.
- Explanation observations retain repeated source provenance. `explanation_terms.parquet` is a deduplicated exact-tuple lookup derived from those observations; it does not discard the source observation rows.
- No explanation is synthesized. A missing or title-only explanation stays null.
- Full Parquet column names, Arrow types, and nullability are recorded in `schema.json`; source file hashes and row-level validation details are in `manifest.json`.

## Parquet files

| File | Grain | Rows | Key fields |
|---|---|---:|---|
| `api33_source_rows.parquet` | one original API33 response row | 3,523 | page/row ordinal, exact title/English/description, source hashes |
| `api33_terms.parquet` | one exact Korean+English+description tuple | 3,511 | exact tuple hash, first source row, all duplicate source row IDs |
| `phrase_decisions.parquet` | one exact raw phrase review decision | 5,397 | raw phrase hash/text, review status, rule note, event link policy |
| `phrase_components.parquet` | one reviewed target per phrase | 9,113 | raw phrase hash/text, target ordinal/title, evidence note |
| `explanation_observations.parquet` | one saved source capture/summary row | 145 | source kind, exact title/English/description, capture and event provenance |
| `explanation_terms.parquet` | one exact captured title+English+description tuple | 119 | exact tuple hash, source kinds and observation IDs |

## Snapshot checks

- API33 original rows: 3,523; exact tuple rows: 3,511; distinct Korean titles: 3,500; exact duplicate excess rows: 12.
- Phrase decisions: 5,397; reviewed mapping rows: 5,392; excluded raw phrases: 5.
- Profile title count represented by saved sources: 68; profile titles with non-empty captured description: 67.
- KRA web glossary source rows: 50; user-provided KRA detail rows: 1.
- API33 XML page SHA-256, per-page counts, and row-for-row XML/JSON field equality were asserted by `build_dictionary.py` before writing the Parquet files.

Rebuild with the repository virtual environment: `./.venv/bin/python thoroughbred/research/20261002_medical_v1/dictionary/build_dictionary.py`.
