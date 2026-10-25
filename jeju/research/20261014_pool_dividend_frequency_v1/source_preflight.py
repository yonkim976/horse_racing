"""Read-only inventory of Jeju results and cached API301 settlement coverage."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261014_pool_dividend_frequency_v1"
DB_FILE = ROOT / "data/horse_racing.sqlite3"
START = "2025-01-01"
END = "2026-09-19"
MEET = 2
POOLS = ("WIN", "PLC", "QNL", "QPL", "EXA", "TLA", "TRI")
POOL_DEFINITIONS = {
    "WIN": "unique official first-place runner",
    "PLC": "first two if actual starters <= 7; first three otherwise",
    "QNL": "unordered pair of official first- and second-place runners",
    "QPL": "all unordered pairs among the official first three",
    "EXA": "official first-place runner followed by second-place runner",
    "TLA": "unordered combination of official first three",
    "TRI": "official first-, second-, and third-place runners in order",
}


def load_payout_helper():
    path = ROOT / "jeju/research/20261013_pair_payout_audit_v1/analyze.py"
    spec = importlib.util.spec_from_file_location("readonly_payout_source_helper", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("read-only API301 source helper could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def race_key(date_value: str, race_number: int) -> tuple[str, int, int]:
    return date_value, MEET, int(race_number)


def unordered(*numbers: int) -> str:
    return "-".join(str(value) for value in sorted(numbers))


def expected_keys(starters: int, by_position: dict[int, int]) -> dict[str, list[str]]:
    first, second, third = (by_position[i] for i in (1, 2, 3))
    plc_cut = 2 if starters <= 7 else 3
    plc = [str(by_position[i]) for i in range(1, plc_cut + 1)]
    return {
        "WIN": [str(first)],
        "PLC": plc,
        "QNL": [unordered(first, second)],
        "QPL": [unordered(first, second), unordered(first, third), unordered(second, third)],
        "EXA": [f"{first}-{second}"],
        "TLA": [unordered(first, second, third)],
        "TRI": [f"{first}-{second}-{third}"],
    }


def read_races() -> tuple[dict[tuple[str, int, int], dict], dict]:
    connection = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    rows = connection.execute(
        """SELECT r.id AS race_db_id, r.race_date_local, r.race_number, r.status,
                  r.distance_m, e.id AS entry_id, e.horse_id, e.horse_number,
                  e.scratched, rr.id AS result_id, rr.finish_position, rr.disqualified
           FROM races r
           JOIN racecourses c ON c.id = r.racecourse_id
           LEFT JOIN race_entries e ON e.race_id = r.id
           LEFT JOIN race_results rr ON rr.race_entry_id = e.id
           WHERE c.kra_meet_code = ? AND r.race_date_local BETWEEN ? AND ?
           ORDER BY r.race_date_local, r.race_number, e.horse_number""",
        (MEET, START, END),
    ).fetchall()
    connection.close()

    races: dict[tuple[str, int, int], dict] = {}
    status_counts: Counter[str] = Counter()
    excluded_horse_entries = 0
    excluded_horse_races: set[tuple[str, int, int]] = set()
    exclusions_path = ROOT / "jeju/data/horse_exclusions.json"
    exclusions = json.loads(exclusions_path.read_text(encoding="utf-8"))
    excluded_ids = {int(horse_id) for horse_id in exclusions["horses"]}

    for row in rows:
        date_value = str(row["race_date_local"])
        key = race_key(date_value, int(row["race_number"]))
        race = races.setdefault(
            key,
            {
                "race_db_id": int(row["race_db_id"]),
                "race_date": date_value,
                "year": int(date_value[:4]),
                "race_number": int(row["race_number"]),
                "status": str(row["status"]),
                "distance_m": row["distance_m"],
                "entries": [],
            },
        )
        if int(row["race_db_id"]) != race["race_db_id"]:
            raise ValueError("duplicate Jeju date/meet/race business key")
        status_counts[str(row["status"])] += 0
        if row["entry_id"] is None:
            continue
        entry = {
            "horse_id": None if row["horse_id"] is None else int(row["horse_id"]),
            "horse_number": int(row["horse_number"]),
            "scratched": bool(row["scratched"]),
            "result_present": row["result_id"] is not None,
            "finish_position": None if row["finish_position"] is None else int(row["finish_position"]),
            "disqualified": bool(row["disqualified"]),
        }
        race["entries"].append(entry)
        if entry["horse_id"] in excluded_ids:
            excluded_horse_entries += 1
            excluded_horse_races.add(key)

    for race in races.values():
        status_counts[race["status"]] += 1
    return races, {
        "race_status_counts": dict(sorted(status_counts.items())),
        "excluded_horse_period_entries": excluded_horse_entries,
        "excluded_horse_period_races": len(excluded_horse_races),
        "horse_exclusions_sha256": hashlib.sha256(exclusions_path.read_bytes()).hexdigest(),
    }


def main() -> None:
    helper = load_payout_helper()
    races, result_inventory = read_races()
    candidates = {
        key: race for key, race in races.items() if race["status"] == "completed"
    }
    targets_by_day: dict[tuple[str, int], set[tuple[str, int, int]]] = defaultdict(set)
    for key in candidates:
        targets_by_day[key[:2]].add(key)

    source_runs: dict[tuple[str, int], dict] = {}
    source_errors: dict[str, str] = {}
    source_registry_rows = 0
    duplicate_registry_alias_rows = 0
    for day_key, day_targets in sorted(targets_by_day.items()):
        try:
            chosen, summary = helper.archive_rows(
                day_targets, {key: [] for key in day_targets}
            )
        except Exception as exc:
            source_errors[day_key[0]] = f"{type(exc).__name__}: {exc}"
            continue
        source_runs[day_key] = chosen[day_key]
        source_registry_rows += int(summary["api301_registry_rows_for_target_days"])
        duplicate_registry_alias_rows += int(summary["duplicate_registry_alias_rows_collapsed"])

    race_audit: list[dict] = []
    rank_issue_counts: Counter[str] = Counter()
    pool_coverage = {
        pool: {"expected_quotes": 0, "covered_quotes": 0, "races_expected": 0, "races_complete": 0}
        for pool in POOLS
    }
    total_expected_quotes = 0
    total_covered_quotes = 0
    all7_complete_races = 0
    for key, race in sorted(candidates.items()):
        starters = [entry for entry in race["entries"] if not entry["scratched"]]
        valid_ranked = [
            entry for entry in starters
            if not entry["disqualified"] and entry["finish_position"] in {1, 2, 3}
        ]
        by_rank: dict[int, list[int]] = defaultdict(list)
        for entry in valid_ranked:
            by_rank[int(entry["finish_position"])].append(entry["horse_number"])
        missing_ranks = [rank for rank in (1, 2, 3) if not by_rank.get(rank)]
        tied_ranks = [rank for rank in (1, 2, 3) if len(by_rank.get(rank, [])) > 1]
        unique_top3 = not missing_ranks and not tied_ranks
        day_key = key[:2]
        run = source_runs.get(day_key)
        pool_detail: dict[str, dict] = {}
        complete_all = False
        wanted = {}
        if unique_top3:
            wanted = expected_keys(len(starters), {rank: by_rank[rank][0] for rank in (1, 2, 3)})
            each_pool_complete = []
            for pool in POOLS:
                keys = wanted[pool]
                source_values = {} if run is None else run["values"]
                values = [source_values.get((key[2], pool, item_key)) for item_key in keys]
                covered = [helper.valid_payout(value) for value in values]
                pool_complete = all(covered)
                pool_coverage[pool]["expected_quotes"] += len(keys)
                pool_coverage[pool]["covered_quotes"] += sum(covered)
                pool_coverage[pool]["races_expected"] += 1
                pool_coverage[pool]["races_complete"] += int(pool_complete)
                total_expected_quotes += len(keys)
                total_covered_quotes += sum(covered)
                each_pool_complete.append(pool_complete)
                pool_detail[pool] = {
                    "expected_winning_quotes": len(keys),
                    "covered_winning_quotes": int(sum(covered)),
                    "complete": pool_complete,
                }
            complete_all = bool(run is not None and all(each_pool_complete))
            all7_complete_races += int(complete_all)
            rank_status = "unique_top3"
        elif missing_ranks:
            rank_status = "missing_official_top3_rank"
            rank_issue_counts[rank_status] += 1
        else:
            rank_status = "top3_dead_heat"
            rank_issue_counts[rank_status] += 1
        if unique_top3 and run is None:
            rank_issue_counts["no_complete_API301_run_for_date"] += 1
        if unique_top3 and run is not None and not complete_all:
            rank_issue_counts["one_or_more_winning_keys_missing_or_invalid"] += 1
        race_audit.append(
            {
                "race_id": f"{key[0]}_{key[1]}_{key[2]}",
                "race_date": race["race_date"],
                "year": race["year"],
                "race_number": race["race_number"],
                "distance_m": race["distance_m"],
                "actual_starters_non_scratched": len(starters),
                "race_entry_rows": len(race["entries"]),
                "entries_without_result_row": sum(not entry["result_present"] for entry in race["entries"]),
                "entries_without_finish_position": sum(entry["finish_position"] is None for entry in race["entries"]),
                "official_rank1_3_counts": {str(rank): len(by_rank.get(rank, [])) for rank in (1, 2, 3)},
                "top3_status": rank_status,
                "source_complete_run_available": run is not None,
                "source_run_id": None if run is None else run["run_id"],
                "source_run_page_count": None if run is None else run["page_count"],
                "source_page_paths": [] if run is None else run["paths"],
                "source_page_sha256s": [] if run is None else run["hashes"],
                "pool_key_coverage": pool_detail,
                "all_seven_pools_complete": complete_all,
            }
        )

    connection = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    registered = connection.execute(
        """SELECT json_extract(request_params_json, '$.rc_date') AS rc_date,
                  COUNT(*) AS registry_rows
           FROM source_documents
           WHERE endpoint = '/API301/Dividend_rate_total'
             AND CAST(json_extract(request_params_json, '$.meet') AS INTEGER) = ?
             AND json_extract(request_params_json, '$.rc_date') BETWEEN ? AND ?
           GROUP BY rc_date ORDER BY rc_date""",
        (MEET, START.replace("-", ""), END.replace("-", "")),
    ).fetchall()
    connection.close()

    unique_top3_count = sum(item["top3_status"] == "unique_top3" for item in race_audit)
    result = {
        "study": "20261014_pool_dividend_frequency_v1",
        "status": "source_preflight_only_no_dividend_histograms",
        "window": {"start_inclusive": START, "end_inclusive": END, "meet_code": MEET},
        "population": {
            "all_stored_jeju_races": len(races),
            "completed_candidate_races": len(candidates),
            "candidate_race_days": len(targets_by_day),
            "candidate_by_year": {
                str(year): sum(race["year"] == year for race in candidates.values())
                for year in (2025, 2026)
            },
            "unique_official_top3_races": unique_top3_count,
            "top3_tied_or_missing_exclusions": len(candidates) - unique_top3_count,
            "unique_top3_and_all_seven_pool_keys_covered": all7_complete_races,
        },
        "race_and_exclusion_inventory": result_inventory,
        "source_inventory": {
            "registered_API301_source_dates": len(registered),
            "registered_API301_source_documents_for_window": sum(int(row["registry_rows"]) for row in registered),
            "registered_source_race_dates_without_completed_race": [
                str(row["rc_date"]) for row in registered
                if str(row["rc_date"])[:4] in {"2025", "2026"}
                and str(row["rc_date"]) not in {day[0].replace("-", "") for day in targets_by_day}
            ],
            "candidate_dates_with_latest_complete_verified_run": len(source_runs),
            "candidate_dates_missing_complete_verified_run": source_errors,
            "API301_registry_rows_examined_for_candidate_dates": source_registry_rows,
            "duplicate_registry_alias_rows_collapsed": duplicate_registry_alias_rows,
            "method": "read-only source_documents registry and cached API301 page files; page hashes checked; latest complete run selected per candidate date",
        },
        "settlement_key_coverage": {
            "pool_definitions": POOL_DEFINITIONS,
            "by_pool": pool_coverage,
            "total_expected_winning_quotes": total_expected_quotes,
            "total_covered_winning_quotes": total_covered_quotes,
            "all_seven_winning_keys_match_race_count": all7_complete_races,
        },
        "candidate_races": race_audit,
        "rank_or_settlement_issue_counts": dict(sorted(rank_issue_counts.items())),
        "read_only": {
            "sqlite_uri_mode": "ro",
            "query_only": True,
            "network": False,
            "model_fit": False,
            "payout_amounts_or_histograms_computed": False,
        },
        "input_sha256": {
            "database_file": hashlib.sha256(DB_FILE.read_bytes()).hexdigest(),
            "prior_readonly_API301_helper": hashlib.sha256(
                (ROOT / "jeju/research/20261013_pair_payout_audit_v1/analyze.py").read_bytes()
            ).hexdigest(),
            "horse_exclusions": result_inventory["horse_exclusions_sha256"],
        },
    }
    out = STUDY / "SOURCE_PREFLIGHT.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(out),
        "population": result["population"],
        "source_inventory": result["source_inventory"],
        "settlement_key_coverage": result["settlement_key_coverage"],
        "rank_or_settlement_issue_counts": result["rank_or_settlement_issue_counts"],
        "read_only": result["read_only"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
