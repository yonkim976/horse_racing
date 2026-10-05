# Passing-group research loader

This package appends verified race-level passing-group evidence to the research core. The loader defaults to a read-only in-memory dry run; only the root operator may run its explicitly gated `--apply` mode.

## Grain and preservation

- Keep each API303 page-item occurrence and each RPT physical point line in separate raw tables with literal source values, file/page/line locators, capture metadata, and SHA-256 provenance.
- Keep API 3F/4F race times and tempo as race-level source fields. They do not become horse-level section points.
- Map exact documented labels by physical venue for ordinary years. For Seoul API rows in 2020–2021, use only a unique same-race exact API-value/RPT-label pair as the effective mapping evidence; leave repeated-value or unmatched API fields held. Do not infer a year-wide permutation.
- Treat `''`, `-`, `X`, and null point values as raw source states, never as passing points. Do not parse notation text or its number-like components.
- Build `race_passing_groups` at one row per confirmed race × mapped point. An internally unique effective API value remains selected even if RPT differs; preserve that discrepancy in the discrepancy ledger. RPT fills an API-absent point only when its normalized literal is unique. API mapping holds, RPT physical lines, and all raw source occurrences remain separately inspectable.
- Provide one coverage row for every in-scope confirmed race, including rows with no recorded point value. Preserve nonexecution, response failure, excluded-scope, and unknown-key evidence separately; do not imply missing values mean a clean race.

## Loader gates

The dry run pins every required artifact by repository-relative path, SHA-256, byte length, and Parquet row count. It checks the 2010-01-01 through 2026-09-29 scope, meets 1/3/4, all confirmed race keys, source page/file evidence, mapping policy, table/view collisions, and core object/manifest baselines. It attaches the core read-only and verifies the baseline SHA is unchanged. It does not open an operational database or service.

## Preflight result

The frozen loader passed a read-only dry run. It verified the 29,774 API observations, all 48 API response pages, the 35 annual meet partitions, 111,467 RPT point lines across 1,827 source files, the 29,710 confirmed core race keys, and exact six-column selection parity against the independent 144,001-row artifact. The dry-run report is `dry_run_report.json`; the root operator reviews it and the paired backup before applying.
