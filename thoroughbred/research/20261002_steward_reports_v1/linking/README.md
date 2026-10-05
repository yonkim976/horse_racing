# API215 steward report paragraph linkage

This package turns the captured KRA API215 narrative fields into exact-source
paragraphs, conservative sentence spans, horse-name/entry candidates, and
non-attributive links to the event roster. It is a research extract, not an
operating database update.

## Scope and inputs

- Event dates: 2010-01-01 through 2026-09-29, inclusive.
- Actual meet codes: 1 Seoul, 3 Busan/Gyeongnam, 4 Yeongcheon. Jeju (2) is out
  of scope.
- API215 input: `../source/api_observations.parquet`; related pinned API page,
  exclusion, and capture manifest files are listed in `manifest.json`.
- Event roster: `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`,
  opened read-only, table `runner_results`. Both executed and planned/cancelled
  event rows are retained as roster evidence; output records carry the core
  `execution_status` so an entry is not asserted to have started or raced.
- All API215 report occurrences are preserved separately. The source locator is
  `capture_id|source_location`; capture/request time is not treated as a
  historical publication or availability time.

## Output tables

- `report_event_paragraphs.parquet`: one exact source slice for each `●` event
  paragraph (and any nonblank preamble), plus explicit null/blank/dash/literal
  `null` field-state rows. Parent report event and target event are separate.
- `report_event_sentences.parquet`: punctuation-based exact spans nested under
  event paragraphs. Paragraphs remain the primary linkage unit.
- `report_horse_mentions.parquet`: quoted-name and circled-number candidates,
  codepoint offsets, raw value, candidate status, and roster evidence.
- `report_horse_links.parquet`: only verified exact entry links, one row per
  paragraph and official horse ID, with neutral semantics
  `mentioned_in_report_paragraph`. It does not assign blame, victimhood, or
  sanctions.
- `report_marker_residuals.parquet`: circled markers that could not be
  parsed as an immediately adjacent supported quoted name.
- `build_summary.json` and `manifest.json`: counts, input/output hashes,
  and pinned provenance.

## Frozen snapshot counts

The pinned input snapshot contains 14,867 API215 report observations and
331,811 event-roster rows across 29,826 event keys. The derived package has
98,467 paragraph/state rows (71,970 text paragraphs and 26,497 explicit
null/blank/dash/literal-`null` states), 107,007 sentence spans, 175,170
mention candidates, and 228 unparsed circled-marker residuals. All 171,151
circled-marker occurrences in the three source prose fields are represented
exactly once in the mention ledger. The selected link table has 149,008
paragraph-to-horse links for 12,546 distinct official horse IDs; every link was
independently joined back to the exact event, program number, horse ID, and
roster name. These counts are repeated in `build_summary.json` and pinned by
`manifest.json`.

For `addJudgement`, 1,656 paragraph occurrences have one safe leading date/race
target context, 33 have a weekday/date contradiction, and 2,447 remain missing
or non-leading context. The 53 source-row occurrences across the audited
weekday-contradiction values produced no links from mismatched paragraphs.
Other unnumbered names, name/number mismatches, missing rosters, and residual
markers remain visible as candidate or residual rows.

Offsets are zero-based Python Unicode codepoints with exclusive ends. Every
paragraph, sentence, mention, and marker raw slice can be checked directly
against its source field. API raw rows and full page bytes remain preserved in
the source package.

## Linking and abstention rules

An explicit marker plus quoted horse name links only when the marker's program
number and exact roster name identify one horse in the relevant event roster.
The KRA origin/display prefixes `[서울]`, `[부산경남]`, `[부경]`, `[영천]`,
and `[영남]` may be removed for name corroboration when they appear on either
the printed name or event-roster name. These prefixes do not set the event
venue. The same event's program number must identify one roster entry, and the
remaining name must match exactly. Raw source spelling remains unchanged in
every output; other prefix forms stay unresolved.

An unnumbered quoted name may inherit an identity only from one validated
explicit anchor in the same API text field and target event. A conflicting
number/name anchor blocks that reuse. No alias crosses report fields, target
events, dates, venues, or API occurrences. Other quoted names, nonadjacent
markers, mismatches, absent rosters, ambiguous event headers, and incomplete
IDs remain candidate rows without a horse link.

`judgement` and `jkChange` use the parent report race key. `addJudgement` is
often a prior-day or prior-race supplemental narrative, so it uses no parent
race roster. A paragraph can target a different same-meet race only when its
own leading text supplies one exact numeric or Korean-written date plus
`제N경주`, any supplied Korean weekday agrees with the Gregorian date, that
date is in scope and no later than the parent report date, and that event has a roster. Missing,
future, invalid, or multiple distinct event headers remain unresolved.

## Rebuild and checks

Run `.venv/bin/python thoroughbred/research/20261002_steward_reports_v1/linking/build_linking_artifacts.py`
from the project root. This reads the captured parquet and research core only
and writes only into this directory. `report_linker.py` exposes the pure
`process_report(report, runners)` function for additional controls. The supplied
root negative controls and three manually expected report cases were run
in-memory and passed before artifact generation.

No external web collection, service calls, or database writes are performed by
the builder.
