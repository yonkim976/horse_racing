# Race family adapter

`thoroughbred/refresh/races.py` describes nine official KRA API families for
incremental collection. It plans annual partitions for APIs 72, 4, 303, 20,
215, and 180, and exact date/meet requests for APIs 78, 26, and 25. All public
request parameters are exposed in `FAMILY_SPECS`; the shared API client
supplies the credential and pagination fields. The adapter makes no network
calls. `iter_baseline_rows` uses its supplied connection only for read-only
queries and reads archived source files without mutating them.

| Family | Official endpoint | Partition | Date field(s) |
| --- | --- | --- | --- |
| `race_schedule` | `/API72_2/racePlan_2` | `rc_year`, `meet` | `rcDate` |
| `race_results` | `/API4_3/raceResult_3` | `rc_year`, `meet` | `rcDate` |
| `passing_groups` | `/API303/corner_rank` | `rc_year`, `meet` | `rcDate` |
| `trial_results` | `/API20_1/ridingTestResult_1` | `tr_year`, `meet` | `trainDate` |
| `public_cards` | `/API78/chulmainfo` | `race_dt`, `rccrs_cd` | `race_dt` or request date |
| `entry_sheets` | `/API26_2/entrySheet_2` | `rc_date`, `meet` | `rcDate`, `rc_date`, or request date |
| `body_weights` | `/API25_1/entryHorseWeightInfo_1` | `rc_date`, `meet` | `rcDate`, `rc_date`, or request date |
| `steward_reports` | `/API215/JudgeReport` | `rc_year`, `meet` | `rcDate` |
| `sanctions` | `/API180_1/sanctionHistory_1` | `rc_year`, `meet` | `rcDate`, `spDate`, `stDate` |

`build_requests(start_date, end_date)` treats both endpoints as inclusive. An
annual request covers a complete year/meet partition intersecting the window;
the caller controls how wide a window to refresh. API78 has a confirmed exact
date parameter, so it gets a date/meet request for each day in the window.
APIs 26 and 25 use their `rc_date` date parameters for entry-sheet and body
weight snapshots.
The previous official collectors queried meet 4 for 2026 and later. The
planner starts that partition at 2026 for each family; it never requests
Jeju/meet 2. An empty complete response is an observed empty partition/date,
not proof that no event was ever scheduled or that the API archive is
historically complete.

`transform(family, payload_row, context)` returns the source family, ISO event
date when supplied or recoverable from a date-partition request, meet code as text,
natural key list plus canonical key JSON, nullable official horse ID, nullable
race number, full original payload object, and view-oriented typed fields.
Pass `requested_date` or public `request_params` in context for API78 because
date-partitioned runner items may omit the query date. Pass the requested meet
along with capture provenance. Repeated rows are observations: key equality never drops
an occurrence. The canonical `payload` retains fields and JSON types even
when a convenience field cannot be parsed.

API4 results preserve body weight and collect the original sectional-time and
passing-order columns in `section_values_raw` and `passing_order_raw`. API303
corner strings are retained as `passing_group_values_raw` without parsing
notation. API78 `equipCrs` remains a raw declaration; API78 capture time does
not certify what was physically worn at race time. API215 narrative remains
race-level source text without an inferred horse link. API180 horse identity
is exposed only for records whose `gubun` identifies a horse; sanctions for
other subjects keep their raw source fields.

`iter_baseline_rows(connection, start_iso, end_iso)` normalizes the original
baseline occurrences in an inclusive date range. API4 rows come from the
archived annual gzip and are limited to `confirmed_runners`; schedule rows
retain all official planned keys. API303, API20, API215, and API180 use the
stored original item JSON. API78 uses the original page item when its stored
SHA256 matches; if that item cannot be verified, it emits a natural-key-only
baseline marker with `payload_unavailable=True`. Source capture timestamps
are carried where stored; legacy files without one use the explicit baseline
freeze date rather than the event date. API26 and API25 have no independent
original baseline family and therefore produce no legacy seed rows.

The adapter does not decide whether a result-only key is a real race, whether
a planned race ran, how to adjudicate later corrections, or how to interpret
empty/cancelled/ghost races. The refresh store applies the existing reviewed
exclusions and hold rules while retaining source occurrences and preserving
the original core rows. Meet 3 labels such as `영남` remain source labels and
are not converted into a physical venue assignment.
