# API303 passing-group raw capture

This package captures `https://apis.data.go.kr/B551015/API303/corner_rank` by annual `rc_year` and `meet` partition. It uses the project settings key in memory and never stores or prints it. Request pacing is at least 0.5 seconds.

The raw page JSON files are the exact successful HTTP response body bytes. Parquet observations keep one item occurrence per source page and row; they retain source fields including `corner_1` through `corner_9`, `meet`, `rcDate`, `rcNo`, `passtime_3f`, `passtime_4f`, and `tempo`. Empty strings, `-`, `X`, and nulls are not interpreted in this package. `actual_meet_code` and `race_date_iso` are extra derived locator fields; `raw_item_json` and the exact page body preserve the original values. Records outside scope remain in the observation file and are repeated in `api_exclusions.parquet` with reasons.

Completeness is reported per year/meet in `api_year_meet_coverage.json`. A zero-count request still has a page-ledger row. This source collector does not read or write any database.
