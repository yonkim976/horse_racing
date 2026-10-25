"""Compare retrospective Busan betting scenarios using confirmed dividends only.

Inputs are race dates, runner numbers, official result labels, and final odds.
The SQLite database is opened read-only and horse-history/model tables are not read.
"""

from __future__ import annotations

import itertools
import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[3]
DB_PATH = ROOT / "data/horse_racing.sqlite3"
OUTPUT = Path(__file__).resolve().with_name("confirmed_odds_scenarios.json")
START_DATE = "2025-01-03"
END_DATE = "2026-10-02"
MARKETS = ("WIN", "QNL", "EXA", "QPL", "TLA", "TRI")
COMBO_MARKETS = ("QNL", "EXA", "QPL", "TLA", "TRI")
K_VALUES = tuple(range(1, 11))
RANK_VALUES = tuple(range(1, 11))
ODDS_BANDS = ((1, 2), (2, 5), (5, 10), (10, 30), (30, 100), (100, 500), (500, math.inf))


def open_read_only() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def load_races(connection: sqlite3.Connection) -> list[dict]:
    result_rows = connection.execute(
        """
        SELECT r.id AS race_id, r.race_date_local AS race_date,
               e.horse_number, e.scratched, rr.finish_position, rr.disqualified
        FROM races r
        JOIN racecourses rc ON rc.id=r.racecourse_id
        JOIN race_entries e ON e.race_id=r.id
        LEFT JOIN race_results rr ON rr.race_entry_id=e.id
        WHERE rc.code=? AND r.status=? AND r.race_date_local BETWEEN ? AND ?
        ORDER BY r.race_date_local, r.id, e.horse_number
        """,
        ("BUSAN_GYEONGNAM", "completed", START_DATE, END_DATE),
    ).fetchall()
    runners: dict[int, list[dict]] = defaultdict(list)
    dates: dict[int, str] = {}
    for row in result_rows:
        if not row["scratched"]:
            race_id = int(row["race_id"])
            runners[race_id].append({
                "horse": int(row["horse_number"]),
                "position": int(row["finish_position"])
                if row["finish_position"] is not None and not row["disqualified"] else None,
            })
            dates[race_id] = str(row["race_date"])

    quote_rows = connection.execute(
        """
        WITH latest_quote AS (
          SELECT o.race_id, o.bet_type, o.selection_key, o.odds,
                 ROW_NUMBER() OVER (
                   PARTITION BY o.race_id, o.bet_type, o.selection_key
                   ORDER BY o.observed_at_ms DESC, o.id DESC
                 ) AS rn
          FROM odds_snapshots o
          JOIN races r ON r.id=o.race_id
          JOIN racecourses rc ON rc.id=r.racecourse_id
          WHERE rc.code=? AND r.status=? AND r.race_date_local BETWEEN ? AND ?
            AND o.bet_type IN ('WIN','QNL','EXA','QPL','TLA','TRI')
        )
        SELECT race_id, bet_type, selection_key, odds
        FROM latest_quote WHERE rn=1
        """,
        ("BUSAN_GYEONGNAM", "completed", START_DATE, END_DATE),
    ).fetchall()
    prices: dict[int, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for row in quote_rows:
        value = float(row["odds"])
        # 9999.9 is the project's sentinel for an unavailable/capped dividend.
        if math.isfinite(value) and 1.0 <= value < 9999.9:
            prices[int(row["race_id"])][str(row["bet_type"])][str(row["selection_key"])] = value

    output = []
    for race_id, entries in runners.items():
        positions: dict[int, set[int]] = defaultdict(set)
        for entry in entries:
            if entry["position"] is not None:
                positions[entry["position"]].add(entry["horse"])
        clear_top3 = all(len(positions[pos]) == 1 for pos in (1, 2, 3))
        if clear_top3:
            first, second, third = (next(iter(positions[pos])) for pos in (1, 2, 3))
            clear_top3 = len({first, second, third}) == 3
        if not clear_top3:
            continue
        first, second, third = (next(iter(positions[pos])) for pos in (1, 2, 3))
        active_horses = {entry["horse"] for entry in entries}
        race_prices = {}
        for market, market_prices in prices[race_id].items():
            filtered = {}
            for key, value in market_prices.items():
                try:
                    numbers = tuple(int(number) for number in key.split("-"))
                except ValueError:
                    continue
                if numbers and all(number in active_horses for number in numbers):
                    filtered[key] = value
            race_prices[market] = filtered
        winner_keys = {
            "WIN": {str(first)},
            "QNL": {"-".join(map(str, sorted((first, second))))},
            "EXA": {f"{first}-{second}"},
            "QPL": {"-".join(map(str, pair)) for pair in itertools.combinations(sorted((first, second, third)), 2)},
            "TLA": {"-".join(map(str, sorted((first, second, third))))},
            "TRI": {f"{first}-{second}-{third}"},
        }
        output.append({
            "race_id": race_id,
            "date": dates[race_id],
            "year": int(dates[race_id][:4]),
            "entries": entries,
            "prices": race_prices,
            "winners": winner_keys,
        })
    return output


def select_low_or_high_k(prices: dict[str, float], k: int, *, high: bool = False) -> tuple[dict[str, float], float, int]:
    """Expected ticket weights from a uniform random tie break at the cutoff."""
    ordered = sorted(prices.items(), key=lambda item: ((-item[1]) if high else item[1], item[0]))
    selected: dict[str, float] = {}
    left = k
    i = 0
    while i < len(ordered) and left > 0:
        j = i + 1
        while j < len(ordered) and ordered[j][1] == ordered[i][1]:
            j += 1
        group = ordered[i:j]
        take = min(left, len(group))
        weight = take / len(group)
        for key, _ in group:
            selected[key] = weight
        left -= take
        i = j
    return selected, float(left), k - left


def pick_rank(prices: dict[str, float], rank: int) -> tuple[dict[str, float], dict | None]:
    ordered = sorted(prices.items(), key=lambda item: (item[1], item[0]))
    if len(ordered) < rank:
        return {}, None
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and ordered[j][1] == ordered[i][1]:
            j += 1
        if i < rank <= j:
            group = ordered[i:j]
            return {key: 1.0 / len(group) for key, _ in group}, {"n": len(group), "rank_slots": j - i}
        i = j
    return {}, None


def hit_probability_for_selection(prices: dict[str, float], winners: set[str], selected: dict[str, float]) -> float:
    if not selected or not winners:
        return 0.0
    if any(key in winners and weight >= 1.0 for key, weight in selected.items()):
        return 1.0
    chosen_wins = [(key, weight) for key, weight in selected.items() if key in winners and weight > 0]
    if not chosen_wins:
        return 0.0
    # The only fractional group is the price tie at the ticket-count cutoff.
    odds_values = {prices[key] for key, _ in chosen_wins}
    if len(odds_values) != 1:
        return min(1.0, sum(weight for _, weight in chosen_wins))
    boundary_price = next(iter(odds_values))
    group = [key for key, value in prices.items() if value == boundary_price]
    selected_in_group = round(sum(selected.get(key, 0.0) for key in group))
    winning_in_group = sum(key in winners for key in group)
    if selected_in_group >= len(group):
        return 1.0 if winning_in_group else 0.0
    if selected_in_group <= 0:
        return 0.0
    no_hit = math.comb(len(group) - winning_in_group, selected_in_group) / math.comb(len(group), selected_in_group)
    return 1.0 - no_hit


def summarize_portfolio(rows: list[tuple[dict, dict[str, float]]], *, fixed_tickets: int | None = None) -> dict:
    stakes = 0.0
    payouts = 0.0
    winning_ticket_weight = 0.0
    expected_hit_races = 0.0
    selected_odds_sum = 0.0
    selected_weight = 0.0
    races = len(rows)
    for race, weights in rows:
        pool = race["_pool"]
        prices = race["prices"].get(pool, {})
        winners = race["winners"][pool]
        stake = float(fixed_tickets if fixed_tickets is not None else sum(weights.values()))
        stakes += stake
        selected_weight += sum(weights.values())
        selected_odds_sum += sum(prices[key] * weight for key, weight in weights.items())
        winning_ticket_weight += sum(weight for key, weight in weights.items() if key in winners)
        payouts += sum(prices[key] * weight for key, weight in weights.items() if key in winners)
        expected_hit_races += hit_probability_for_selection(prices, winners, weights)
    if stakes <= 0:
        return {"races": races, "tickets": 0, "hit_races_pct": None, "mean_selected_odds": None,
                "mean_winning_dividend": None, "gross_return_pct": None, "net_roi_pct": None}
    return {
        "races": races,
        "tickets": round(stakes, 3),
        "tickets_per_race": round(stakes / races, 3) if races else None,
        "hit_races_pct": round(100 * expected_hit_races / races, 3) if races else None,
        "winning_ticket_weight": round(winning_ticket_weight, 3),
        "winning_ticket_rate_pct": round(100 * winning_ticket_weight / stakes, 3),
        "mean_selected_odds": round(selected_odds_sum / selected_weight, 3) if selected_weight else None,
        "mean_winning_dividend": round(payouts / winning_ticket_weight, 3) if winning_ticket_weight else None,
        "gross_return_per_100w": round(100 * payouts / stakes, 2),
        "gross_return_pct": round(100 * payouts / stakes, 3),
        "net_roi_pct": round(100 * (payouts / stakes - 1), 3),
    }


def evaluate_rank_strategy(races: list[dict], pool: str, rank: int) -> dict:
    rows = []
    for race in races:
        prices = race["prices"].get(pool, {})
        selected, _ = pick_rank(prices, rank)
        if selected:
            row = dict(race)
            row["_pool"] = pool
            rows.append((row, selected))
    result = summarize_portfolio(rows, fixed_tickets=1)
    result["races"] = len(rows)
    return result


def evaluate_top_k(races: list[dict], pool: str, k: int, *, high: bool = False) -> dict:
    rows = []
    for race in races:
        prices = race["prices"].get(pool, {})
        if not prices:
            continue
        chosen_count = min(k, len(prices))
        selected, left, _ = select_low_or_high_k(prices, chosen_count, high=high)
        if left == 0:
            row = dict(race)
            row["_pool"] = pool
            rows.append((row, selected))
    return summarize_portfolio(rows)


def evaluate_price_bands(races: list[dict], pool: str) -> dict:
    output = {}
    for lower, upper in ODDS_BANDS:
        tickets = 0
        payout = 0.0
        wins = 0
        hit_races = 0
        for race in races:
            selected = {key: value for key, value in race["prices"].get(pool, {}).items()
                        if lower <= value < upper}
            if not selected:
                continue
            tickets += len(selected)
            winners = race["winners"][pool]
            ticket_wins = sum(key in winners for key in selected)
            wins += ticket_wins
            hit_races += ticket_wins > 0
            payout += sum(selected[key] for key in selected if key in winners)
        label = f"{lower:g}-{upper:g}" if math.isfinite(upper) else f">={lower:g}"
        output[label] = {
            "tickets": tickets,
            "hit_races": hit_races,
            "hit_races_pct_of_races_with_bets": round(100 * hit_races / sum(
                bool(any(lower <= v < upper for v in race["prices"].get(pool, {}).values())) for race in races
            ), 3) if any(any(lower <= v < upper for v in race["prices"].get(pool, {}).values()) for race in races) else None,
            "winning_tickets": wins,
            "mean_dividend": round(mean(value for race in races for value in race["prices"].get(pool, {}).values()
                                          if lower <= value < upper), 3) if tickets else None,
            "gross_return_per_100w": round(100 * payout / tickets, 2) if tickets else None,
            "gross_return_pct": round(100 * payout / tickets, 3) if tickets else None,
            "net_roi_pct": round(100 * (payout / tickets - 1), 3) if tickets else None,
        }
    return output


def candidates_from_win_ranks(race: dict, pool: str, n: int) -> set[str]:
    win_prices = race["prices"].get("WIN", {})
    top = [int(key) for key, _ in sorted(win_prices.items(), key=lambda item: (item[1], int(item[0])))[:n]]
    if len(top) < n:
        return set()
    if pool in ("QNL", "QPL"):
        tuples = itertools.combinations(top, 2)
        return {"-".join(map(str, sorted(pair))) for pair in tuples}
    if pool == "EXA":
        return {f"{first}-{second}" for first, second in itertools.permutations(top, 2)}
    if pool == "TLA":
        tuples = itertools.combinations(top, 3)
        return {"-".join(map(str, sorted(triple))) for triple in tuples}
    if pool == "TRI":
        return {"-".join(map(str, triple)) for triple in itertools.permutations(top, 3)}
    return set()


def evaluate_win_top_n_boxes(races: list[dict], pool: str, n: int) -> dict:
    total_races = 0
    covered_races = 0
    tickets = 0
    payout = 0.0
    hit_races = 0
    winning_tickets = 0
    selected_odds_sum = 0.0
    for race in races:
        candidates = candidates_from_win_ranks(race, pool, n)
        if not candidates:
            continue
        total_races += 1
        valid = candidates & set(race["prices"].get(pool, {}))
        if not valid:
            continue
        covered_races += 1
        tickets += len(valid)
        odds = race["prices"][pool]
        winners = race["winners"][pool]
        winning = valid & winners
        winning_tickets += len(winning)
        hit_races += bool(winning)
        payout += sum(odds[key] for key in winning)
        selected_odds_sum += sum(odds[key] for key in valid)
    return {
        "eligible_races": total_races,
        "races_with_at_least_one_quoted_candidate": covered_races,
        "tickets": tickets,
        "tickets_per_race_with_bet": round(tickets / covered_races, 3) if covered_races else None,
        "hit_races_pct": round(100 * hit_races / covered_races, 3) if covered_races else None,
        "winning_tickets": winning_tickets,
        "mean_selected_odds": round(selected_odds_sum / tickets, 3) if tickets else None,
        "mean_winning_dividend": round(payout / winning_tickets, 3) if winning_tickets else None,
        "gross_return_per_100w": round(100 * payout / tickets, 2) if tickets else None,
        "gross_return_pct": round(100 * payout / tickets, 3) if tickets else None,
        "net_roi_pct": round(100 * (payout / tickets - 1), 3) if tickets else None,
    }


def summarize_market(races: list[dict], pool: str) -> dict:
    return {
        "price_rank_single_ticket": {
            str(rank): evaluate_rank_strategy(races, pool, rank) for rank in RANK_VALUES
        },
        "lowest_dividend_k_tickets": {
            str(k): evaluate_top_k(races, pool, k, high=False) for k in K_VALUES
        },
        "highest_dividend_k_tickets": {
            str(k): evaluate_top_k(races, pool, k, high=True) for k in K_VALUES
        },
        "all_ticket_dividend_bands": evaluate_price_bands(races, pool),
    }


def main() -> None:
    connection = open_read_only()
    try:
        all_clear_races = load_races(connection)
    finally:
        connection.close()

    # Use the same clear-result races with at least ten valid quotes in every pool.
    # This keeps comparisons across the five combination pools on an identical cohort.
    common = [race for race in all_clear_races
              if all(len(race["prices"].get(pool, {})) >= 10 for pool in COMBO_MARKETS)
              and len(race["prices"].get("WIN", {})) >= 5]
    periods = {
        "all_2025_2026": common,
        "year_2025": [race for race in common if race["year"] == 2025],
        "year_2026": [race for race in common if race["year"] == 2026],
    }
    output = {
        "title": "Busan confirmed-dividend-only candidate scenario comparison",
        "date_range": {"start": START_DATE, "end": END_DATE},
        "selection_inputs": "Confirmed dividend odds and runner numbers only; no horse history or model predictions.",
        "settlement": "Official top-three result labels; 100 KRW per ticket; payout uses the same official confirmed dividend. Net ROI = payout / stake - 1.",
        "quote_handling": "Latest quote per race, market, and selection; 9999.9 sentinel or invalid values are unavailable and excluded. A missing winning quote is a losing ticket.",
        "tie_handling": "For dividend-rank K strategies, equal-price ties at the cutoff are treated as a uniform random choice with the same expected ticket budget.",
        "cohort": {
            "clear_top_three_races_before_quote_filter": len(all_clear_races),
            "common_races": len(common),
            "common_races_by_year": dict(sorted(Counter(race["year"] for race in common).items())),
            "exclusion_rule": "Unique first, second, and third place; at least ten valid final-odds combinations in QNL, EXA, QPL, TLA, and TRI; at least five valid WIN quotes.",
            "note": "Combination pools begin in 2025 in this local database, so this common comparison covers 2025 through 2026-10-02.",
        },
        "markets": {},
        "win_rank_box": {},
    }
    for period, period_race_list in periods.items():
        output["markets"][period] = {pool: summarize_market(period_race_list, pool) for pool in MARKETS}
        output["win_rank_box"][period] = {
            pool: {str(n): evaluate_win_top_n_boxes(period_race_list, pool, n)
                   for n in range(2 if pool in ("QNL", "EXA", "QPL") else 3, 6)}
            for pool in COMBO_MARKETS
        }

    # Choose only within 2025, then carry the same price-rank rule into 2026.
    holdout = periods["year_2026"]
    transfers = {}
    for pool in MARKETS:
        low = output["markets"]["year_2025"][pool]["lowest_dividend_k_tickets"]
        high = output["markets"]["year_2025"][pool]["highest_dividend_k_tickets"]
        family, chosen_k = max(
            ((family, int(k)) for family, table in (("lowest", low), ("highest", high)) for k in table),
            key=lambda item: output["markets"]["year_2025"][pool][
                "lowest_dividend_k_tickets" if item[0] == "lowest" else "highest_dividend_k_tickets"
            ][str(item[1])]["net_roi_pct"],
        )
        rule_table = "lowest_dividend_k_tickets" if family == "lowest" else "highest_dividend_k_tickets"
        transfers[pool] = {
            "selected_in_2025": {"price_direction": family, "k": chosen_k,
                                 "net_roi_pct": output["markets"]["year_2025"][pool][rule_table][str(chosen_k)]["net_roi_pct"]},
            "fixed_rule_result_in_2026": output["markets"]["year_2026"][pool][rule_table][str(chosen_k)],
        }
        rank_table = output["markets"]["year_2025"][pool]["price_rank_single_ticket"]
        best_rank = max(rank_table, key=lambda rank: rank_table[rank]["net_roi_pct"])
        transfers[pool]["best_single_rank_selected_in_2025"] = {
            "rank": int(best_rank),
            "net_roi_pct_2025": rank_table[best_rank]["net_roi_pct"],
            "fixed_rank_result_in_2026": output["markets"]["year_2026"][pool]["price_rank_single_ticket"][best_rank],
        }
        if pool in COMBO_MARKETS:
            boxes = output["win_rank_box"]["year_2025"][pool]
            best_n = max(boxes, key=lambda n: boxes[n]["net_roi_pct"])
            transfers[pool]["best_win_rank_box_selected_in_2025"] = {
                "top_n": int(best_n),
                "net_roi_pct_2025": boxes[best_n]["net_roi_pct"],
                "fixed_box_result_in_2026": output["win_rank_box"]["year_2026"][pool][best_n],
            }
    output["validation_to_holdout"] = {
        "selection_period": "2025",
        "fixed_holdout_period": "2026-01-01 through 2026-10-02",
        "rule": "Within each market, choose the best 1-10 cheapest or 1-10 most expensive tickets by 2025 ROI, then apply that same direction and K in 2026. Also choose the best single price rank 1-10 and, for combination pools, best WIN-rank box size from 2025.",
        "results_by_market": transfers,
    }

    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "cohort": output["cohort"],
        "all_2025_2026_low_k10": {
            pool: output["markets"]["all_2025_2026"][pool]["lowest_dividend_k_tickets"]["10"]
            for pool in MARKETS
        },
        "all_2025_2026_win_top3_box": {
            pool: output["win_rank_box"]["all_2025_2026"][pool].get("3")
            for pool in COMBO_MARKETS
        },
        "validation_to_holdout": output["validation_to_holdout"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
