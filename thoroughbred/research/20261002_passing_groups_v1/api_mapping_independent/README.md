# Independent API303–RPT point-map check

Read-only comparison of frozen API303 observations and the RPT point rows. No source file or database was changed. See `independent_mapping_check.json` for every physical meet/year/API field and the Seoul race-level lists.

## Method

The nominal map is the project `CORNER_POINTS` definition, bridged to literal RPT labels (`C1`…`C4`, `S-1F`, `G-1F` for Seoul; `G8F`…`G1F`, `S1F` for Busan/Yeongcheon). Comparison is exact text only. For this check, API `null`, empty string, `-`, and `X` are blank states; RPT empty string is blank. No passing-order notation was parsed.

Input pins: API `facfeca265488a7907ae913d4b7605e3e64aa8b324cca3b8287f1f3dbe316df7`, RPT `25087828d433a4cc4b3c1e51904ae4ae0c7f33513c3cbcfa12f502a89f730807`, map code `1d8180fb4725d99e1f76c331fb65d75403160e4af91eea42da0112c173dfc37b`.

## Seoul 2020–2021 race-level result

Every one of the 1,495 RPT race keys in these two years has one API row.

| Year | RPT keys | Same valid-value multiset, same nominal slots | Same multiset, slot disagreement | At least one RPT value absent from all six API slots |
| ---: | ---: | ---: | ---: | ---: |
| 2020 | 630 | 65 | 63 | 502 |
| 2021 | 865 | 316 | 85 | 464 |
| **Total** | **1495** | **381** | **148** | **966** |

Among the 148 same-multiset slot-disagreement races, 130 have a unique value-to-label alignment and 18 have repeated values allowing multiple alignments. The JSON lists candidate labels and the number of possible alignments; it intentionally selects no permutation for ambiguous races.

The 966 missing-value race records list each RPT literal absent from the entire six-field API value multiset and preserve API/RPT source locators. There were 0 API-only value groups in those cases.

### Seoul 2020–2021 by nominal API field

Counts below compare one API field with its nominal RPT label over 1,495 race keys. `API blank / RPT value` and `API value / RPT blank` are kept separate from exact agreement and literal disagreement.

| API field | RPT label | Exact same | Different | API blank, RPT value | API value, RPT blank | Both blank |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| corner_1 | C1 | 94 | 136 | 42 | 502 | 721 |
| corner_2 | C2 | 80 | 143 | 56 | 526 | 690 |
| corner_3 | C3 | 399 | 537 | 559 | 0 | 0 |
| corner_4 | C4 | 382 | 529 | 584 | 0 | 0 |
| corner_7 | S-1F | 415 | 513 | 567 | 0 | 0 |
| corner_8 | G-1F | 381 | 534 | 580 | 0 | 0 |

## Full meet/year/field counts

`independent_mapping_check.json` contains the complete raw state count for all nine API corner fields, plus nominal exact/different/blank comparisons for every RPT-overlap meet/year/field. Years without local RPT point rows remain represented in API raw-state counts but have no RPT comparison. The keys are API physical meet + event date + race number; RPT lines are compared by their exact printed point label.

## Scope and interpretation

This audit establishes observed value alignment or absence in the two frozen inputs. It does not validate the API's internal semantics beyond the nominal map definition and does not infer a permutation from repeated values. The full per-race evidence is in `seoul_2020_2021_race_level_multiset_check.wrong_slot_cases` and `rpt_values_missing_entirely_cases`.
