"""Retrospective Busan market-only betting diagnostics.

This script reads only race identity, runner number, final result labels, and
official final dividends. It never loads horse history or model predictions.
The odds source is post-race and cannot validate a pre-race betting strategy.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[3]
DATABASE = ROOT / "data/horse_racing.sqlite3"
OUTPUT = Path(__file__).resolve().parent / "results.json"
START_DATE = "2015-01-01"
END_DATE = "2026-10-02"
COMBO_START_DATE = "2025-01-03"
GAP_CUTS_PP = (11.11, 27.91)
FAVORITE_ODDS_CUTS = (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.5, 10.0, 15.0)
PRICE_BINS = ((1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 5.0),
              (5.0, 10.0), (10.0, 20.0), (20.0, math.inf))
VALIDATION_YEAR = 2023
TEST_START_YEAR = 2024


def connect_read_only() -> sqlite3.Connection:
    uri = DATABASE.resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def round_float(value: float | None, digits: int = 6):
    return None if value is None else round(float(value), digits)


def summarize_bets(odds: list[float], weighted_hits: list[float],
                   return_factors: list[float], *, races: int | None = None) -> dict:
    n = len(odds)
    if n == 0:
        return {"bets": 0, "races": races or 0, "hit_rate": None,
                "mean_odds": None, "gross_return_pct": None, "net_roi_pct": None}
    gross = sum(return_factors) / n
    return {
        "bets": n,
        "races": races if races is not None else n,
        "weighted_hits": round_float(sum(weighted_hits)),
        "hit_rate_pct": round_float(100.0 * sum(weighted_hits) / n, 3),
        "mean_odds": round_float(mean(odds), 3),
        "gross_return_pct": round_float(100.0 * gross, 3),
        "net_roi_pct": round_float(100.0 * (gross - 1.0), 3),
    }


def market_rank_slots(entries: list[dict]) -> list[dict]:
    """Return ordinal odds slots, sharing equal-price horses symmetrically."""
    ordered = sorted(entries, key=lambda row: (row["odds"], row["horse_number"]))
    slots: list[dict] = []
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and ordered[j]["odds"] == ordered[i]["odds"]:
            j += 1
        group = ordered[i:j]
        winner_share = sum(row["finish_position"] == 1 for row in group) / len(group)
        for _ in range(i, j):
            slots.append({"odds": float(group[0]["odds"]), "hit_share": winner_share})
        i = j
    return slots


def load_win_races(db: sqlite3.Connection) -> tuple[list[dict], dict]:
    rows = db.execute(
        """
        WITH latest_win AS (
          SELECT race_id, selection_key, odds,
                 ROW_NUMBER() OVER (
                   PARTITION BY race_id, selection_key
                   ORDER BY observed_at_ms DESC, id DESC
                 ) AS rn
          FROM odds_snapshots WHERE bet_type='WIN'
        )
        SELECT r.id AS race_id, r.race_date_local AS race_date,
               e.horse_number, e.scratched, rr.finish_position,
               w.odds, r.scheduled_at_ms
        FROM races r
        JOIN racecourses rc ON rc.id=r.racecourse_id
        JOIN race_entries e ON e.race_id=r.id
        LEFT JOIN race_results rr ON rr.race_entry_id=e.id
        LEFT JOIN latest_win w
          ON w.race_id=r.id AND w.selection_key=CAST(e.horse_number AS TEXT) AND w.rn=1
        WHERE rc.code=? AND r.status=? AND r.race_date_local BETWEEN ? AND ?
        ORDER BY r.race_date_local, r.id, e.horse_number
        """,
        ("BUSAN_GYEONGNAM", "completed", START_DATE, END_DATE),
    ).fetchall()
    grouped: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        if not row["scratched"]:
            grouped[int(row["race_id"])].append(row)

    excluded = Counter()
    prepared: list[dict] = []
    for race_id, runners in grouped.items():
        if len(runners) < 5:
            excluded["fewer_than_5_active_runners"] += 1
            continue
        if any(row["finish_position"] is None for row in runners):
            excluded["missing_active_runner_result"] += 1
            continue
        if any(row["odds"] is None or not (1.0 <= row["odds"] < 9999.9) for row in runners):
            excluded["incomplete_or_invalid_win_odds"] += 1
            continue
        if not any(row["finish_position"] == 1 for row in runners):
            excluded["no_first_place_result"] += 1
            continue

        entries = [
            {"horse_number": int(row["horse_number"]),
             "finish_position": int(row["finish_position"]),
             "odds": float(row["odds"])}
            for row in runners
        ]
        entries.sort(key=lambda row: (row["odds"], row["horse_number"]))
        slots = market_rank_slots(entries)
        implied = [1.0 / row["odds"] for row in entries]
        first_two_gap = 100.0 * (implied[0] - implied[1])
        prepared.append({
            "race_id": race_id,
            "date": str(runners[0]["race_date"]),
            "year": int(str(runners[0]["race_date"])[:4]),
            "runners": len(entries),
            "entries": entries,
            "slots": slots,
            "favorite_odds": slots[0]["odds"],
            "favorite_share": implied[0] / sum(implied),
            "gap_pp": first_two_gap,
            "overround": sum(implied),
        })
    timing = db.execute(
        """
        SELECT COUNT(*) AS rows,
               SUM(CASE WHEN o.observed_at_ms < r.scheduled_at_ms THEN 1 ELSE 0 END) AS before_scheduled,
               MIN(o.observed_at_ms-r.scheduled_at_ms) AS min_delay_ms,
               MAX(o.observed_at_ms-r.scheduled_at_ms) AS max_delay_ms,
               MIN(o.observed_at_ms) AS min_observed_ms,
               MAX(o.observed_at_ms) AS max_observed_ms
        FROM odds_snapshots o
        JOIN races r ON r.id=o.race_id
        JOIN racecourses rc ON rc.id=r.racecourse_id
        WHERE rc.code=? AND r.race_date_local BETWEEN ? AND ?
          AND r.scheduled_at_ms IS NOT NULL AND o.bet_type='WIN'
        """,
        ("BUSAN_GYEONGNAM", START_DATE, END_DATE),
    ).fetchone()
    all_timing = db.execute(
        """
        SELECT COUNT(*) AS rows, COUNT(DISTINCT o.race_id) AS races,
               MIN(o.observed_at_ms) AS min_observed_ms,
               MAX(o.observed_at_ms) AS max_observed_ms,
               SUM(date(o.observed_at_ms/1000,'unixepoch','+9 hours') < r.race_date_local) AS before_race_date,
               SUM(date(o.observed_at_ms/1000,'unixepoch','+9 hours') = r.race_date_local) AS on_race_date,
               SUM(date(o.observed_at_ms/1000,'unixepoch','+9 hours') > r.race_date_local) AS after_race_date
        FROM odds_snapshots o
        JOIN races r ON r.id=o.race_id
        JOIN racecourses rc ON rc.id=r.racecourse_id
        WHERE rc.code=? AND o.bet_type='WIN'
        """,
        ("BUSAN_GYEONGNAM",),
    ).fetchone()
    timing_result = {
        "all_win_snapshot_rows": int(all_timing["rows"]),
        "all_win_races_with_quotes": int(all_timing["races"]),
        "observed_kst_date_before_race_date_count": int(all_timing["before_race_date"] or 0),
        "observed_kst_date_on_race_date_count": int(all_timing["on_race_date"] or 0),
        "observed_kst_date_after_race_date_count": int(all_timing["after_race_date"] or 0),
        "all_win_min_observed_utc": datetime.fromtimestamp(all_timing["min_observed_ms"] / 1000, timezone.utc).isoformat(),
        "all_win_max_observed_utc": datetime.fromtimestamp(all_timing["max_observed_ms"] / 1000, timezone.utc).isoformat(),
        "scheduled_time_available_win_rows": int(timing["rows"]),
        "observed_before_scheduled_count": int(timing["before_scheduled"] or 0),
        "minimum_delay_after_scheduled_hours": round_float((timing["min_delay_ms"] or 0) / 3_600_000, 3),
        "maximum_delay_after_scheduled_days": round_float((timing["max_delay_ms"] or 0) / 86_400_000, 3),
    }
    return prepared, {"eligible_races": len(prepared), "excluded_races": dict(excluded),
                      "eligible_races_by_year": dict(sorted(Counter(x["year"] for x in prepared).items())),
                      "price_timing": timing_result}


def rows_for_period(races: list[dict], start_year: int, end_year: int) -> list[dict]:
    return [race for race in races if start_year <= race["year"] <= end_year]


def evaluate_win_rank(races: list[dict], rank: int) -> dict:
    chosen = [race for race in races if len(race["slots"]) >= rank]
    return summarize_bets(
        [race["slots"][rank - 1]["odds"] for race in chosen],
        [race["slots"][rank - 1]["hit_share"] for race in chosen],
        [race["slots"][rank - 1]["odds"] * race["slots"][rank - 1]["hit_share"] for race in chosen],
        races=len(chosen),
    )


def evaluate_favorite_rule(races: list[dict], predicate) -> dict:
    chosen = [race for race in races if predicate(race)]
    return summarize_bets(
        [race["slots"][0]["odds"] for race in chosen],
        [race["slots"][0]["hit_share"] for race in chosen],
        [race["slots"][0]["odds"] * race["slots"][0]["hit_share"] for race in chosen],
        races=len(chosen),
    )


def evaluate_price_bins(races: list[dict]) -> list[dict]:
    output = []
    for lower, upper in PRICE_BINS:
        odds: list[float] = []
        hits: list[float] = []
        returns: list[float] = []
        for race in races:
            for entry in race["entries"]:
                if lower <= entry["odds"] < upper:
                    hit = float(entry["finish_position"] == 1)
                    odds.append(entry["odds"])
                    hits.append(hit)
                    returns.append(entry["odds"] * hit)
        label = f"{lower:g}-{upper:g}" if math.isfinite(upper) else f">={lower:g}"
        output.append({"odds_bin": label, **summarize_bets(odds, hits, returns)})
    return output


def load_combo_data(db: sqlite3.Connection) -> tuple[list[dict], dict]:
    result_rows = db.execute(
        """
        SELECT r.id AS race_id, r.race_date_local AS race_date,
               e.horse_number, rr.finish_position
        FROM races r
        JOIN racecourses rc ON rc.id=r.racecourse_id
        JOIN race_entries e ON e.race_id=r.id
        JOIN race_results rr ON rr.race_entry_id=e.id
        WHERE rc.code=? AND r.status=? AND r.race_date_local BETWEEN ? AND ?
          AND e.scratched=0 AND rr.disqualified=0 AND rr.finish_position IN (1,2,3)
        ORDER BY r.race_date_local, r.id, rr.finish_position, e.horse_number
        """,
        ("BUSAN_GYEONGNAM", "completed", COMBO_START_DATE, END_DATE),
    ).fetchall()
    positions: dict[int, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    dates: dict[int, str] = {}
    for row in result_rows:
        race_id = int(row["race_id"])
        positions[race_id][int(row["finish_position"])].add(int(row["horse_number"]))
        dates[race_id] = str(row["race_date"])
    prices: dict[int, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    price_rows = db.execute(
        """
        SELECT o.race_id, o.bet_type, o.selection_key, o.odds
        FROM odds_snapshots o
        JOIN races r ON r.id=o.race_id
        JOIN racecourses rc ON rc.id=r.racecourse_id
        WHERE rc.code=? AND r.status=? AND r.race_date_local BETWEEN ? AND ?
          AND o.bet_type IN ('TRI','TLA') AND o.odds>=1 AND o.odds<9999.9
        """,
        ("BUSAN_GYEONGNAM", "completed", COMBO_START_DATE, END_DATE),
    ).fetchall()
    for row in price_rows:
        prices[int(row["race_id"])][str(row["bet_type"])][str(row["selection_key"])] = float(row["odds"])

    prepared = []
    excluded = Counter()
    race_ids = set(positions) | set(prices)
    for race_id in race_ids:
        pos = positions[race_id]
        if not all(len(pos[rank]) == 1 for rank in (1, 2, 3)):
            excluded["missing_or_dead_heat_top_three"] += 1
            continue
        first, second, third = (next(iter(pos[rank])) for rank in (1, 2, 3))
        if len({first, second, third}) != 3:
            excluded["repeated_horse_in_top_three"] += 1
            continue
        if any(len(prices[race_id][pool]) < 10 for pool in ("TRI", "TLA")):
            excluded["fewer_than_10_valid_combos_in_either_pool"] += 1
            continue
        prepared.append({
            "race_id": race_id,
            "date": dates[race_id],
            "year": int(dates[race_id][:4]),
            "winner_tri": f"{first}-{second}-{third}",
            "winner_tla": "-".join(map(str, sorted((first, second, third)))),
            "prices": prices[race_id],
        })
    return sorted(prepared, key=lambda x: (x["date"], x["race_id"])), {
        "eligible_races": len(prepared),
        "eligible_races_by_year": dict(sorted(Counter(x["year"] for x in prepared).items())),
        "excluded_races": dict(excluded),
    }


def combo_rank_slots(odds_map: dict[str, float], winner_key: str) -> list[dict]:
    ordered = sorted(odds_map.items(), key=lambda row: (row[1], row[0]))
    slots = []
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and ordered[j][1] == ordered[i][1]:
            j += 1
        group = ordered[i:j]
        winner_in_group = any(key == winner_key for key, _ in group)
        hit_share = (1.0 / len(group)) if winner_in_group else 0.0
        for _ in range(i, j):
            slots.append({"odds": float(group[0][1]), "hit_share": hit_share})
        i = j
    return slots


def evaluate_combo_pool(races: list[dict], pool: str) -> dict:
    prepared = []
    missing_winner_quote = 0
    for race in races:
        winner_key = race[f"winner_{pool.lower()}"]
        odds_map = race["prices"][pool]
        if winner_key not in odds_map:
            missing_winner_quote += 1
        slots = combo_rank_slots(odds_map, winner_key)
        prepared.append({**race, "winner_key": winner_key, "slots": slots,
                         "winner_quote": odds_map.get(winner_key)})

    per_rank = {}
    for rank in range(1, 11):
        chosen = [race for race in prepared if len(race["slots"]) >= rank]
        per_rank[str(rank)] = summarize_bets(
            [race["slots"][rank - 1]["odds"] for race in chosen],
            [race["slots"][rank - 1]["hit_share"] for race in chosen],
            [race["slots"][rank - 1]["odds"] * race["slots"][rank - 1]["hit_share"] for race in chosen],
            races=len(chosen),
        )

    top_k = {}
    for k in range(1, 11):
        if not prepared:
            top_k[str(k)] = {"races": 0, "bets": 0, "hit_rate_pct": None,
                             "mean_selected_odds": None, "gross_return_pct": None,
                             "net_roi_pct": None, "gross_payout_per_100w": 0}
            continue
        per_race_returns = []
        hit_probability = []
        selected_odds = []
        for race in prepared:
            if len(race["slots"]) < k:
                continue
            selected_odds.extend(slot["odds"] for slot in race["slots"][:k])
            per_race_returns.append(sum(slot["odds"] * slot["hit_share"] for slot in race["slots"][:k]))
            hit_probability.append(min(1.0, sum(slot["hit_share"] for slot in race["slots"][:k])))
        n_races = len(per_race_returns)
        stakes = n_races * k
        gross_factor = sum(per_race_returns) / stakes if stakes else 0.0
        top_k[str(k)] = {
            "races": n_races,
            "bets": stakes,
            "expected_hits": round_float(sum(hit_probability)),
            "hit_rate_pct": round_float(100.0 * sum(hit_probability) / n_races, 3) if n_races else None,
            "mean_selected_odds": round_float(mean(selected_odds), 3) if selected_odds else None,
            "mean_winning_dividend_odds_if_hit": round_float(
                sum(per_race_returns) / sum(hit_probability), 3
            ) if sum(hit_probability) else None,
            "gross_payout_per_100w": round_float(gross_factor * 100.0, 2),
            "gross_return_pct": round_float(100.0 * gross_factor, 3),
            "net_roi_pct": round_float(100.0 * (gross_factor - 1.0), 3),
        }
    best_validation_k = max(range(1, 11), key=lambda k: top_k[str(k)]["net_roi_pct"])
    low10 = top_k["10"]
    low10["actual_winner_quotes_missing"] = missing_winner_quote
    return {"races": len(prepared), "races_by_year": dict(sorted(Counter(x["year"] for x in prepared).items())),
            "missing_winner_quote_count": missing_winner_quote, "per_price_rank": per_rank,
            "top_k": top_k, "best_k_in_2025_validation": best_validation_k}


def main() -> None:
    db = connect_read_only()
    try:
        win_races, win_quality = load_win_races(db)
        splits = {
            "train_2015_2022": rows_for_period(win_races, 2015, 2022),
            "validation_2023": rows_for_period(win_races, 2023, 2023),
            "test_2024_2026_partial": rows_for_period(win_races, 2024, 2026),
        }
        win_rank_summary = {}
        for label, races in splits.items():
            win_rank_summary[label] = {str(rank): evaluate_win_rank(races, rank) for rank in range(1, 6)}
        for year in range(2015, 2027):
            races = rows_for_period(win_races, year, year)
            if races:
                win_rank_summary[f"year_{year}"] = {str(rank): evaluate_win_rank(races, rank) for rank in range(1, 6)}

        validation = splits["validation_2023"]
        test = splits["test_2024_2026_partial"]
        threshold_scan = []
        for threshold in FAVORITE_ODDS_CUTS:
            valid_metric = evaluate_favorite_rule(validation, lambda row, cap=threshold: row["favorite_odds"] <= cap)
            test_metric = evaluate_favorite_rule(test, lambda row, cap=threshold: row["favorite_odds"] <= cap)
            threshold_scan.append({"favorite_final_odds_at_most": threshold,
                                   "validation_2023": valid_metric, "test_2024_2026": test_metric})
        best_threshold = max(
            (row for row in threshold_scan if row["validation_2023"]["bets"] >= 100),
            key=lambda row: row["validation_2023"]["net_roi_pct"],
        )
        best_threshold_value = best_threshold["favorite_final_odds_at_most"]
        best_threshold_test_by_year = {
            str(year): evaluate_favorite_rule(rows_for_period(win_races, year, year),
                                               lambda row, cap=best_threshold_value: row["favorite_odds"] <= cap)
            for year in range(TEST_START_YEAR, 2027)
        }

        def gap_bucket(row):
            if row["gap_pp"] < GAP_CUTS_PP[0]:
                return "small"
            if row["gap_pp"] <= GAP_CUTS_PP[1]:
                return "medium"
            return "large"

        gap_summary = {}
        for split_name, races in {"train_2015_2022": splits["train_2015_2022"],
                                  "validation_2023": validation,
                                  "test_2024_2026": test}.items():
            gap_summary[split_name] = {
                bucket: evaluate_favorite_rule(races, lambda row, b=bucket: gap_bucket(row) == b)
                for bucket in ("small", "medium", "large")
            }
        best_gap = max((bucket for bucket in ("small", "medium", "large")
                        if gap_summary["validation_2023"][bucket]["bets"] >= 100),
                       key=lambda bucket: gap_summary["validation_2023"][bucket]["net_roi_pct"])
        gap_test_by_year = {
            str(year): evaluate_favorite_rule(rows_for_period(win_races, year, year),
                                               lambda row, b=best_gap: gap_bucket(row) == b)
            for year in range(TEST_START_YEAR, 2027)
        }
        price_bin_summary = {name: evaluate_price_bins(races) for name, races in {
            "train_2015_2022": splits["train_2015_2022"],
            "validation_2023": validation,
            "test_2024_2026": test,
        }.items()}

        combo_races, combo_quality = load_combo_data(db)
        combo_results = {}
        for pool in ("TRI", "TLA"):
            combo_results[pool] = {
                "all_2025_2026": evaluate_combo_pool(combo_races, pool),
                "year_2025_validation": evaluate_combo_pool([r for r in combo_races if r["year"] == 2025], pool),
                "year_2026_test": evaluate_combo_pool([r for r in combo_races if r["year"] == 2026], pool),
            }
            best_k = combo_results[pool]["year_2025_validation"]["best_k_in_2025_validation"]
            combo_results[pool]["selected_k_test_2026"] = {
                "k_selected_on_2025": best_k,
                "test_2026": combo_results[pool]["year_2026_test"]["top_k"][str(best_k)],
            }

        output = {
            "title": "Busan odds-board-only retrospective profitability search",
            "analysis_dates": {"win_start": START_DATE, "end": END_DATE,
                               "combo_start": COMBO_START_DATE},
            "feature_scope": "Final market prices and race-level price shape only; horse histories and model outputs are not read.",
            "settlement_scope": "Official first-place result labels and final dividend multipliers; flat 100 KRW per ticket; gross return includes the displayed dividend; net ROI=gross return/stake-1.",
            "win_sample": win_quality,
            "chronological_splits": {"train": "2015-2022", "validation": "2023", "test": "2024-2026-10-02"},
            "win_market_rank_returns": win_rank_summary,
            "favorite_price_rule": {"threshold_scan": threshold_scan,
                                    "selected_on_validation": best_threshold_value,
                                    "selected_rule_validation": best_threshold["validation_2023"],
                                    "selected_rule_test": best_threshold["test_2024_2026"],
                                    "selected_rule_test_by_year": best_threshold_test_by_year},
            "favorite_probability_gap_rule": {"gap_definition": "100*(1/lowest_WIN_odds - 1/second_lowest_WIN_odds), percentage points; tied odds give 0",
                                              "fixed_bins_pp": {"small": f"<{GAP_CUTS_PP[0]}", "medium": f"{GAP_CUTS_PP[0]}..{GAP_CUTS_PP[1]}", "large": f">{GAP_CUTS_PP[1]}"},
                                              "summary": gap_summary,
                                              "best_validation_bucket": best_gap,
                                              "selected_bucket_test_by_year": gap_test_by_year},
            "runner_final_odds_bands": price_bin_summary,
            "combo_sample": combo_quality,
            "combo_low_odds_rank_search": combo_results,
            "limitations": [
                "odds_snapshots are API301 confirmed dividends observed after the scheduled start; none of the Busan WIN observations precede scheduled start.",
                "2026-10-09 local API301 probe returned no odds 2-16 minutes before scheduled start and returned odds about 10 minutes after for the probed Busan races.",
                "All retrospective ROI results use post-race final dividends to rank selections, so they are leakage diagnostics, not achievable pre-race betting performance.",
                "Historical time splits reduce threshold-selection bias but do not fix the post-race price availability problem; 2024-2026 have also been reviewed in earlier project work.",
                "Equal-priced rank ties are shared equally; TRI/TLA dead-heat top-three results are excluded from the exact-combination sample; absent actual TRI prices are counted as misses.",
            ],
        }
        OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(OUTPUT),
                          "win_sample": output["win_sample"],
                          "favorite_price_rule": output["favorite_price_rule"],
                          "favorite_probability_gap_rule": output["favorite_probability_gap_rule"],
                          "combo_sample": output["combo_sample"],
                          "tri_low10": {k: v["top_k"]["10"] for k, v in output["combo_low_odds_rank_search"]["TRI"].items() if isinstance(v, dict) and "top_k" in v},
                          "tla_low10": {k: v["top_k"]["10"] for k, v in output["combo_low_odds_rank_search"]["TLA"].items() if isinstance(v, dict) and "top_k" in v},
                          "win_test_ranks": output["win_market_rank_returns"]["test_2024_2026_partial"]}, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
