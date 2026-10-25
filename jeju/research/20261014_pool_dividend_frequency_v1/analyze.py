"""Descriptive frequency of actual winning Jeju dividends by pool."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261014_pool_dividend_frequency_v1"
DB_FILE = ROOT / "data/horse_racing.sqlite3"
START = "2025-01-01"
END = "2026-09-19"
MEET = 2
POOLS = ("WIN", "PLC", "QNL", "QPL", "EXA", "TLA", "TRI")
BIN_LABELS = (
    "[1,2)", "[2,3)", "[3,5)", "[5,10)",
    "[10,20)", "[20,50)", "[50,100)", "[100,inf)",
)
POOL_NAMES = {
    "WIN": "단승",
    "PLC": "연승",
    "QNL": "복승",
    "QPL": "복연승",
    "EXA": "쌍승",
    "TLA": "삼복승",
    "TRI": "삼쌍승",
}
OUTPUT_NAMES = (
    "winning_quotes.csv",
    "race_pool_summary.csv",
    "histogram_by_pool_year.csv",
    "race_frequency_by_pool_year.csv",
    "SOURCE_PAGE_INDEX.csv",
    "REPORT.json",
    "SOURCE_HASHES.json",
)


def load_helper():
    import sys

    sys.path.insert(0, str(ROOT / "jeju/research/20261013_pair_payout_audit_v1"))
    import analyze as payout_source  # noqa: PLC0415

    return payout_source


def read_starter_counts() -> dict[tuple[str, int], int]:
    connection = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    rows = connection.execute(
        """SELECT r.race_date_local, r.race_number,
                  SUM(CASE WHEN e.scratched = 0 THEN 1 ELSE 0 END) AS actual_starters
           FROM races r JOIN racecourses c ON c.id = r.racecourse_id
           JOIN race_entries e ON e.race_id = r.id
           WHERE c.kra_meet_code = ? AND r.race_date_local BETWEEN ? AND ?
           GROUP BY r.race_date_local, r.race_number""",
        (MEET, START, END),
    ).fetchall()
    connection.close()
    return {(str(row[0]), int(row[1])): int(row[2]) for row in rows}


def unordered_key(*numbers: int) -> str:
    return "-".join(str(number) for number in sorted(numbers))


def winning_keys(starters: int, result: dict) -> dict[str, list[str]]:
    ranked: dict[int, list[int]] = defaultdict(list)
    for runner in result["runners"]:
        position = runner["finish_position"]
        if (
            not runner["scratched"] and not runner["disqualified"]
            and position is not None and int(position) in (1, 2, 3)
        ):
            ranked[int(position)].append(int(runner["horse_number"]))
    if any(len(ranked[position]) != 1 for position in (1, 2, 3)):
        raise ValueError("eligible race no longer has a unique official podium")
    first, second, third = (ranked[position][0] for position in (1, 2, 3))
    plc_slots = 2 if starters <= 7 else 3
    return {
        "WIN": [str(first)],
        "PLC": [str(ranked[position][0]) for position in range(1, plc_slots + 1)],
        "QNL": [unordered_key(first, second)],
        "QPL": [
            unordered_key(first, second),
            unordered_key(first, third),
            unordered_key(second, third),
        ],
        "EXA": [f"{first}-{second}"],
        "TLA": [unordered_key(first, second, third)],
        "TRI": [f"{first}-{second}-{third}"],
    }


def quote_bin(value: float) -> str:
    if value < 1:
        return "<1"
    for index, lower in enumerate((1, 2, 3, 5, 10, 20, 50, 100)):
        upper = (2, 3, 5, 10, 20, 50, 100, math.inf)[index]
        if lower <= value < upper:
            return BIN_LABELS[index]
    raise ValueError(f"payout outside declared histogram bins: {value}")


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pct(numerator: int, denominator: int) -> float | None:
    return round(100.0 * numerator / denominator, 6) if denominator else None


def main() -> None:
    existing_outputs = [name for name in OUTPUT_NAMES if (STUDY / name).exists()]
    if existing_outputs:
        raise FileExistsError(f"refusing to overwrite existing study outputs: {existing_outputs}")
    helper = load_helper()
    preflight_path = STUDY / "SOURCE_PREFLIGHT.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    eligible = [
        race for race in preflight["candidate_races"]
        if race["all_seven_pools_complete"]
    ]
    eligible_ids = [race["race_id"] for race in eligible]
    if len(eligible) != 1237 or len(set(eligible_ids)) != len(eligible):
        raise ValueError("approved eligible race roster changed")

    candidate_by_key = {
        (race["race_date"], MEET, int(race["race_number"])): race
        for race in eligible
    }
    targets = set(candidate_by_key)
    results = helper.read_results(targets)
    if set(results) != targets:
        raise ValueError("official shared result rows do not cover the approved roster")
    starter_counts = read_starter_counts()

    wanted = defaultdict(list)
    expected_by_race: dict[tuple[str, int, int], dict[str, list[str]]] = {}
    for key in sorted(targets):
        starters = starter_counts.get((key[0], key[2]))
        if starters is None or starters != candidate_by_key[key]["actual_starters_non_scratched"]:
            raise ValueError(f"actual starter count mismatch: {key}")
        keys_by_pool = winning_keys(starters, results[key])
        expected_by_race[key] = keys_by_pool
        for pool, selection_keys in keys_by_pool.items():
            wanted[key].extend((pool, selection_key) for selection_key in selection_keys)

    chosen_runs, source_inventory = helper.archive_rows(targets, wanted)

    quote_rows: list[dict] = []
    race_pool_rows: list[dict] = []
    page_records: dict[tuple[str, str, str], dict] = {}
    race_count_by_year = Counter(race["year"] for race in eligible)

    for key in sorted(targets):
        race = candidate_by_key[key]
        run = chosen_runs[key[:2]]
        page_path_by_hash: dict[str, str] = {}
        for page_hash, page_path in zip(run["hashes"], run["paths"], strict=True):
            page_path_by_hash[page_hash] = page_path
            page_records[(key[0], run["run_id"], page_path)] = {
                "race_date": key[0],
                "year": int(key[0][:4]),
                "meet_code": key[1],
                "source_run_id": run["run_id"],
                "source_page_path": page_path,
                "source_page_sha256": page_hash,
            }

        for pool in POOLS:
            selection_keys = expected_by_race[key][pool]
            values: list[float] = []
            for selection_key in selection_keys:
                source_key = (key[2], pool, selection_key)
                payout = run["values"].get(source_key)
                if not helper.valid_payout(payout):
                    raise ValueError(f"winning payout absent or invalid for {key} {pool} {selection_key}")
                payout = float(payout)
                source_hash = run["page_for_key"][source_key]
                if source_hash not in page_path_by_hash:
                    raise ValueError("winning quote source page missing from selected complete run")
                values.append(payout)
                quote_rows.append(
                    {
                        "race_id": f"{key[0]}_{key[1]}_{key[2]}",
                        "race_date": key[0],
                        "year": int(key[0][:4]),
                        "race_number": key[2],
                        "distance_m": race["distance_m"],
                        "actual_starters": starter_counts[(key[0], key[2])],
                        "pool": pool,
                        "pool_korean": POOL_NAMES[pool],
                        "winning_selection_key": selection_key,
                        "winning_dividend_multiple": payout,
                        "source_run_id": run["run_id"],
                        "source_page_path": page_path_by_hash[source_hash],
                        "source_page_sha256": source_hash,
                    }
                )
            low_any = min(values) < 5
            low_all = max(values) < 5
            high_any = max(values) >= 20
            high_all = min(values) >= 20
            race_pool_rows.append(
                {
                    "race_id": f"{key[0]}_{key[1]}_{key[2]}",
                    "race_date": key[0],
                    "year": int(key[0][:4]),
                    "race_number": key[2],
                    "distance_m": race["distance_m"],
                    "actual_starters": starter_counts[(key[0], key[2])],
                    "pool": pool,
                    "pool_korean": POOL_NAMES[pool],
                    "winning_selection_keys": json.dumps(selection_keys, separators=(",", ":")),
                    "winning_quote_count": len(values),
                    "minimum_winning_dividend": min(values),
                    "maximum_winning_dividend": max(values),
                    "low_any_lt5": low_any,
                    "low_all_max_lt5": low_all,
                    "middle_max_5_to_lt20": not low_all and not high_any,
                    "high_any_max_ge20": high_any,
                    "high_all_min_ge20": high_all,
                    "mixed_low_and_high": low_any and high_any,
                    "any_quote_ge100": max(values) >= 100,
                }
            )

    quote_rows.sort(key=lambda row: (row["year"], row["race_date"], row["race_number"], POOLS.index(row["pool"]), row["winning_selection_key"]))
    race_pool_rows.sort(key=lambda row: (row["year"], row["race_date"], row["race_number"], POOLS.index(row["pool"])))
    if len(quote_rows) != 13560 or len(race_pool_rows) != len(eligible) * len(POOLS):
        raise ValueError("validated winning quote / pool settlement totals changed")

    histogram_rows = []
    frequency_rows = []
    for pool in POOLS:
        for year_label in ("all", "2025", "2026"):
            pool_quotes = [
                row for row in quote_rows
                if row["pool"] == pool and (year_label == "all" or str(row["year"]) == year_label)
            ]
            pool_races = [
                row for row in race_pool_rows
                if row["pool"] == pool and (year_label == "all" or str(row["year"]) == year_label)
            ]
            quote_denominator = len(pool_quotes)
            race_denominator = len(pool_races)
            if not race_denominator:
                raise ValueError(f"empty race frequency denominator: {pool} {year_label}")
            values = [float(row["winning_dividend_multiple"]) for row in pool_quotes]
            median_quote = float(statistics.median(values))
            for bin_label in BIN_LABELS:
                in_bin = [row for row in pool_quotes if quote_bin(float(row["winning_dividend_multiple"])) == bin_label]
                races_with_quote = len({row["race_id"] for row in in_bin})
                histogram_rows.append(
                    {
                        "pool": pool,
                        "pool_korean": POOL_NAMES[pool],
                        "year": year_label,
                        "winning_races": race_denominator,
                        "winning_quote_count": quote_denominator,
                        "dividend_bin": bin_label,
                        "quote_count": len(in_bin),
                        "quote_pct": pct(len(in_bin), quote_denominator),
                        "races_with_at_least_one_quote_in_bin": races_with_quote,
                        "race_pct_with_quote_in_bin": pct(races_with_quote, race_denominator),
                    }
                )
            under_one = [row for row in pool_quotes if float(row["winning_dividend_multiple"]) < 1]
            if under_one:
                histogram_rows.append(
                    {
                        "pool": pool,
                        "pool_korean": POOL_NAMES[pool],
                        "year": year_label,
                        "winning_races": race_denominator,
                        "winning_quote_count": quote_denominator,
                        "dividend_bin": "<1 (outside declared bins)",
                        "quote_count": len(under_one),
                        "quote_pct": pct(len(under_one), quote_denominator),
                        "races_with_at_least_one_quote_in_bin": len({row["race_id"] for row in under_one}),
                        "race_pct_with_quote_in_bin": pct(len({row["race_id"] for row in under_one}), race_denominator),
                    }
                )

            count_by_flag = {
                "low_all_max_lt5": sum(bool(row["low_all_max_lt5"]) for row in pool_races),
                "middle_max_5_to_lt20": sum(bool(row["middle_max_5_to_lt20"]) for row in pool_races),
                "high_any_max_ge20": sum(bool(row["high_any_max_ge20"]) for row in pool_races),
                "low_any_min_lt5": sum(bool(row["low_any_lt5"]) for row in pool_races),
                "high_all_min_ge20": sum(bool(row["high_all_min_ge20"]) for row in pool_races),
                "mixed_low_and_high": sum(bool(row["mixed_low_and_high"]) for row in pool_races),
                "max_ge100": sum(bool(row["any_quote_ge100"]) for row in pool_races),
            }
            frequency_rows.append(
                {
                    "pool": pool,
                    "pool_korean": POOL_NAMES[pool],
                    "year": year_label,
                    "winning_races": race_denominator,
                    "winning_quote_count": quote_denominator,
                    "quote_median_multiple": round(median_quote, 6),
                    "quote_min_multiple": min(values),
                    "quote_max_multiple": max(values),
                    **{f"{name}_races": count for name, count in count_by_flag.items()},
                    **{f"{name}_race_pct": pct(count, race_denominator) for name, count in count_by_flag.items()},
                }
            )

    pool_counts = Counter(row["pool"] for row in quote_rows)
    expected_counts = {"WIN": 1237, "PLC": 3664, "QNL": 1237, "QPL": 3711, "EXA": 1237, "TLA": 1237, "TRI": 1237}
    if dict(pool_counts) != expected_counts:
        raise ValueError(f"per-pool winning quote counts changed: {dict(pool_counts)}")
    if any(row["dividend_bin"] not in BIN_LABELS and not str(row["dividend_bin"]).startswith("<1") for row in histogram_rows):
        raise ValueError("histogram contains an undeclared interval")

    write_csv(
        STUDY / "winning_quotes.csv", quote_rows,
        ["race_id", "race_date", "year", "race_number", "distance_m", "actual_starters", "pool", "pool_korean", "winning_selection_key", "winning_dividend_multiple", "source_run_id", "source_page_path", "source_page_sha256"],
    )
    write_csv(
        STUDY / "race_pool_summary.csv", race_pool_rows,
        ["race_id", "race_date", "year", "race_number", "distance_m", "actual_starters", "pool", "pool_korean", "winning_selection_keys", "winning_quote_count", "minimum_winning_dividend", "maximum_winning_dividend", "low_any_lt5", "low_all_max_lt5", "middle_max_5_to_lt20", "high_any_max_ge20", "high_all_min_ge20", "mixed_low_and_high", "any_quote_ge100"],
    )
    write_csv(
        STUDY / "histogram_by_pool_year.csv", histogram_rows,
        ["pool", "pool_korean", "year", "winning_races", "winning_quote_count", "dividend_bin", "quote_count", "quote_pct", "races_with_at_least_one_quote_in_bin", "race_pct_with_quote_in_bin"],
    )
    write_csv(
        STUDY / "race_frequency_by_pool_year.csv", frequency_rows,
        ["pool", "pool_korean", "year", "winning_races", "winning_quote_count", "quote_median_multiple", "quote_min_multiple", "quote_max_multiple", "low_all_max_lt5_races", "middle_max_5_to_lt20_races", "high_any_max_ge20_races", "low_any_min_lt5_races", "high_all_min_ge20_races", "mixed_low_and_high_races", "max_ge100_races", "low_all_max_lt5_race_pct", "middle_max_5_to_lt20_race_pct", "high_any_max_ge20_race_pct", "low_any_min_lt5_race_pct", "high_all_min_ge20_race_pct", "mixed_low_and_high_race_pct", "max_ge100_race_pct"],
    )

    page_index_rows = []
    for (race_date, run_id, page_path), record in sorted(page_records.items()):
        page_index_rows.append(
            {
                **record,
                "winner_quotes_on_page": sum(
                    row["race_date"] == race_date and row["source_page_sha256"] == record["source_page_sha256"]
                    for row in quote_rows
                ),
                "eligible_races_on_date": sum(race["race_date"] == race_date for race in eligible),
            }
        )
    write_csv(
        STUDY / "SOURCE_PAGE_INDEX.csv", page_index_rows,
        ["race_date", "year", "meet_code", "source_run_id", "source_page_path", "source_page_sha256", "winner_quotes_on_page", "eligible_races_on_date"],
    )

    yearly_totals = {
        str(year): {
            "races": sum(race["year"] == year for race in eligible),
            "winning_quotes": sum(row["year"] == year for row in quote_rows),
        }
        for year in (2025, 2026)
    }
    pool_overall = [row for row in frequency_rows if row["year"] == "all"]
    report = {
        "study": "20261014_pool_dividend_frequency_v1",
        "question": "How often do actual winning dividends fall into low, middle, and high bands by Jeju betting pool?",
        "scope": {
            "meet_code": MEET,
            "start_inclusive": START,
            "end_inclusive": END,
            "candidate_completed_races": preflight["population"]["completed_candidate_races"],
            "eligible_settled_races": len(eligible),
            "eligible_races_by_year": yearly_totals,
            "excluded_podium_dead_heats": 10,
            "excluded_no_valid_podium_races": 27,
            "2026_is_partial_year": True,
        },
        "pool_definitions": {
            "WIN": "official first-place runner",
            "PLC": "first two if actual starters <= 7; first three otherwise",
            "QNL": "unordered official first-two pair",
            "QPL": "all unordered pairs among the official first three regardless of field size",
            "EXA": "official first-place runner followed by second place",
            "TLA": "unordered official top-three combination",
            "TRI": "ordered official first-second-third",
        },
        "frequency_method": {
            "units": "API301 final winning-dividend multiples",
            "winning_quotes_only": True,
            "quote_bins": list(BIN_LABELS),
            "primary_race_categories": {
                "low_all_max_lt5": "the maximum among all winning selections in that race/pool is <5x",
                "middle_max_5_to_lt20": "the maximum is >=5x and <20x",
                "high_any_max_ge20": "the maximum is >=20x",
            },
            "multi_winner_pools": "PLC and QPL retain one row per actual winning dividend quote; race classes use max and min across the race's winning quotes. Quote and race denominators are reported separately.",
            "descriptive_cutoffs_only": "<5x and >=20x are fixed descriptive bands, not optimized betting thresholds or a profitability rule.",
            "quote_median": "median across actual winning dividend quotes in the pool/year; no average is substituted for a winning ticket.",
            "max_ge100_race_flag": "race has at least one actual winning quote >=100x.",
            "uncertainty": "exact local census counts for the defined coverage window; no sampling interval is reported.",
        },
        "totals": {
            "unique_eligible_races": len(eligible),
            "race_pool_rows": len(race_pool_rows),
            "actual_winning_quotes": len(quote_rows),
            "winning_quotes_by_pool": dict(sorted(pool_counts.items())),
            "all_seven_pool_key_coverage": "100% of the 1,237 eligible races",
        },
        "race_frequency_by_pool_year": frequency_rows,
        "source_audit": {
            "source_preflight": "jeju/research/20261014_pool_dividend_frequency_v1/SOURCE_PREFLIGHT.json",
            "native_result_followup": "jeju/research/20261014_pool_dividend_frequency_v1/SOURCE_PREFLIGHT_NATIVE_FOLLOWUP.json",
            "API301_latest_complete_runs_revalidated_for_eligible_races": len(chosen_runs),
            "API301_source_registry_summary": source_inventory,
            "page_index_rows": len(page_index_rows),
            "unique_page_hashes": len({row["source_page_sha256"] for row in page_index_rows}),
        },
        "limitations": [
            "Only the local KRA meet-2 results and complete locally retained API301 runs are represented.",
            "Ten races with a dead heat within ranks 1-3 are excluded because a single unique official podium cannot define a comparable set of exact winning selections under this contract.",
            "Twenty-seven races without a valid unique official podium in the local result sources are excluded; the native follow-up records raw API4 status codes and source hashes.",
            "The local supported period ends 2026-09-19; the 2026 row is partial.",
            "Dividend bands describe realized historical payouts only and do not estimate pre-race odds, win probabilities, expected return, or a betting strategy.",
        ],
        "read_only": {
            "sqlite_uri_mode": "ro",
            "query_only": True,
            "network": False,
            "model_fit": False,
            "database_writes": False,
        },
    }
    (STUDY / "REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    input_paths = {
        "shared_database": DB_FILE,
        "initial_source_preflight": preflight_path,
        "native_result_followup": STUDY / "SOURCE_PREFLIGHT_NATIVE_FOLLOWUP.json",
        "api301_source_helper": ROOT / "jeju/research/20261013_pair_payout_audit_v1/analyze.py",
        "analysis_code": STUDY / "analyze.py",
        "source_preflight_code": STUDY / "source_preflight.py",
        "native_followup_code": STUDY / "native_result_followup.py",
        "plan": STUDY / "PLAN.md",
    }
    hashes = {str(path.relative_to(ROOT)): sha256(path) for path in input_paths.values()}
    source_hashes = sorted({row["source_page_sha256"] for row in page_index_rows})
    source_path_sha = {
        row["source_page_path"]: row["source_page_sha256"] for row in page_index_rows
    }
    source_hash_manifest = {
        "study": "20261014_pool_dividend_frequency_v1",
        "input_sha256": hashes,
        "source_pages": {
            "selected_complete_page_rows": len(page_index_rows),
            "unique_page_hashes": len(source_hashes),
            "unique_hashes_used_for_winning_quotes": len({row["source_page_sha256"] for row in quote_rows}),
            "path_sha256": source_path_sha,
        },
        "output_sha256": {
            name: sha256(STUDY / name)
            for name in (
                "winning_quotes.csv", "race_pool_summary.csv", "histogram_by_pool_year.csv",
                "race_frequency_by_pool_year.csv", "SOURCE_PAGE_INDEX.csv", "REPORT.json",
            )
        },
    }
    (STUDY / "SOURCE_HASHES.json").write_text(json.dumps(source_hash_manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "output": str(STUDY),
        "eligible_races": len(eligible),
        "races_by_year": yearly_totals,
        "winning_quotes_by_pool": dict(sorted(pool_counts.items())),
        "overall_race_frequency": pool_overall,
        "source_page_index_rows": len(page_index_rows),
        "source_unique_hashes": len(source_hashes),
        "source_inventory": source_inventory,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
