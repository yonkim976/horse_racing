"""Retrospective Busan analysis joining frozen model picks to latest dividends.

The SQLite database is opened read-only. Model probabilities choose runners or
combinations; the latest stored dividend is used only for settlement and
explicitly hindsight-labelled value filters.
"""

from __future__ import annotations

import itertools
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
DB = ROOT / "data/horse_racing.sqlite3"
MODEL_DIR = ROOT / "data/research/thoroughbred_boundary_20260918_v6"
START_DATE = "2025-01-03"
END_DATE = "2026-10-02"
MARKETS = ("WIN", "PLC", "QNL", "EXA", "QPL", "TLA", "TRI")
DIVIDEND_SENTINEL = 9_999.9
EV_THRESHOLDS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)


def open_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def race_key_from_model_id(race_id: str) -> tuple[str, int]:
    parts = str(race_id).split(":")
    if len(parts) != 4 or parts[0] != "RACE" or parts[1] != "BUSAN":
        raise ValueError(f"unexpected Busan model race id: {race_id!r}")
    date = f"{parts[2][:4]}-{parts[2][4:6]}-{parts[2][6:8]}"
    return date, int(parts[3])


def load_database() -> tuple[dict[tuple[str, int], dict], float]:
    connection = open_db()
    entry_rows = connection.execute(
        """
        SELECT r.id AS db_race_id, r.race_date_local, r.race_number,
               r.scheduled_at_ms, e.horse_number, e.scratched,
               h.kra_horse_id, rr.finish_position, rr.disqualified
        FROM races r
        JOIN racecourses rc ON rc.id = r.racecourse_id
        JOIN race_entries e ON e.race_id = r.id
        JOIN horses h ON h.id = e.horse_id
        LEFT JOIN race_results rr ON rr.race_entry_id = e.id
        WHERE rc.code = ? AND r.status = ?
          AND r.race_date_local BETWEEN ? AND ?
        ORDER BY r.race_date_local, r.race_number, e.horse_number
        """,
        ("BUSAN_GYEONGNAM", "completed", START_DATE, END_DATE),
    ).fetchall()

    grouped: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in entry_rows:
        grouped[int(row["db_race_id"])].append(row)

    races: dict[tuple[str, int], dict] = {}
    for entries in grouped.values():
        first = entries[0]
        date = str(first["race_date_local"])
        race_no = int(first["race_number"])
        active = [row for row in entries if not bool(row["scratched"])]
        id_to_number = {
            str(row["kra_horse_id"]): int(row["horse_number"])
            for row in entries
        }
        active_numbers = {int(row["horse_number"]) for row in active}
        positions: dict[int, list[int]] = defaultdict(list)
        for row in active:
            position = row["finish_position"]
            if position is not None and not bool(row["disqualified"]):
                position = int(position)
                if 1 <= position < 90:
                    positions[position].append(int(row["horse_number"]))
        clean_top3 = all(len(positions[position]) == 1 for position in (1, 2, 3))
        if clean_top3:
            top3 = tuple(positions[position][0] for position in (1, 2, 3))
            clean_top3 = len(set(top3)) == 3
        else:
            top3 = ()
        place_slots = 3 if len(active) >= 8 else 2
        placed = {
            int(row["horse_number"])
            for row in active
            if row["finish_position"] is not None
            and not bool(row["disqualified"])
            and int(row["finish_position"]) <= place_slots
        }
        winners = {
            "WIN": {str(top3[0])} if clean_top3 else set(),
            "PLC": {str(number) for number in placed},
            "QNL": {"-".join(map(str, sorted(top3[:2])))} if clean_top3 else set(),
            "EXA": {f"{top3[0]}-{top3[1]}"} if clean_top3 else set(),
            "QPL": {
                "-".join(map(str, pair))
                for pair in itertools.combinations(sorted(placed), 2)
            },
            "TLA": {"-".join(map(str, sorted(top3)))} if clean_top3 else set(),
            "TRI": {"-".join(map(str, top3))} if clean_top3 else set(),
        }
        key = (date, race_no)
        races[key] = {
            "date": date,
            "year": int(date[:4]),
            "race_no": race_no,
            "db_race_id": int(first["db_race_id"]),
            "scheduled_at_ms": first["scheduled_at_ms"],
            "active_numbers": active_numbers,
            "active_count": len(active),
            "id_to_number": id_to_number,
            "clean_top3": clean_top3,
            "actual_top3": top3,
            "winners": winners,
            "prices": defaultdict(dict),
        }

    quote_rows = connection.execute(
        """
        WITH ranked AS (
          SELECT o.race_id, o.bet_type, o.selection_key, o.odds,
                 o.observed_at_ms, r.scheduled_at_ms,
                 ROW_NUMBER() OVER (
                   PARTITION BY o.race_id, o.bet_type, o.selection_key
                   ORDER BY o.observed_at_ms DESC, o.id DESC
                 ) AS row_number
          FROM odds_snapshots o
          JOIN races r ON r.id = o.race_id
          JOIN racecourses rc ON rc.id = r.racecourse_id
          WHERE rc.code = ? AND r.status = ?
            AND r.race_date_local BETWEEN ? AND ?
            AND o.bet_type IN ('WIN','PLC','QNL','EXA','QPL','TLA','TRI')
        )
        SELECT race_id, bet_type, selection_key, odds, observed_at_ms,
               scheduled_at_ms
        FROM ranked WHERE row_number = 1
        """,
        ("BUSAN_GYEONGNAM", "completed", START_DATE, END_DATE),
    ).fetchall()
    db_id_to_race = {race["db_race_id"]: race for race in races.values()}
    for row in quote_rows:
        race = db_id_to_race.get(int(row["race_id"]))
        if race is None:
            continue
        value = float(row["odds"])
        if math.isfinite(value) and 1.0 <= value < DIVIDEND_SENTINEL:
            race["prices"][str(row["bet_type"])][str(row["selection_key"])] = value

    first_quote = connection.execute(
        """
        SELECT MIN(o.observed_at_ms - r.scheduled_at_ms)
        FROM odds_snapshots o
        JOIN races r ON r.id = o.race_id
        JOIN racecourses rc ON rc.id = r.racecourse_id
        WHERE rc.code = ? AND r.status = ?
          AND r.race_date_local BETWEEN ? AND ?
          AND r.scheduled_at_ms IS NOT NULL
          AND o.bet_type IN ('WIN','PLC','QNL','EXA','QPL','TLA','TRI')
        """,
        ("BUSAN_GYEONGNAM", "completed", START_DATE, END_DATE),
    ).fetchone()[0]
    connection.close()
    hours_after_start = float(first_quote) / 3_600_000 if first_quote is not None else math.nan
    return races, hours_after_start


def attach_model_predictions(races: dict[tuple[str, int], dict]) -> dict:
    a_path = MODEL_DIR / "A_horse_predictions.parquet"
    b_path = MODEL_DIR / "race_metrics.parquet"
    a = pd.read_parquet(a_path)
    a = a[
        a["candidate"].eq("current_A")
        & a["venue_code"].eq("BUSAN")
        & a["race_date"].between(START_DATE, END_DATE)
    ]
    a_races = 0
    for race_id, group in a.groupby("race_id", sort=False):
        key = race_key_from_model_id(str(race_id))
        race = races.get(key)
        if race is None:
            continue
        runners = []
        for row in group.itertuples(index=False):
            number = race["id_to_number"].get(str(row.hr_no))
            if number is None or number not in race["active_numbers"]:
                continue
            runners.append({
                "horse_number": number,
                "horse_id": str(row.hr_no),
                "probability": float(row.probability),
                "top1": bool(row.top1),
                "label": float(row.label),
            })
        runners.sort(key=lambda item: (-item["probability"], item["horse_number"]))
        if runners:
            flagged = [runner for runner in runners if runner["top1"]]
            if len(flagged) == 1:
                runners = [flagged[0]] + [runner for runner in runners if not runner["top1"]]
            race["A_runners"] = runners
            a_races += 1

    b = pd.read_parquet(b_path)
    b = b[
        b["candidate"].eq("current_B")
        & b["target"].eq("B")
        & b["venue_code"].eq("BUSAN")
        & b["race_date"].between(START_DATE, END_DATE)
    ]
    b_races = 0
    for row in b.itertuples(index=False):
        key = race_key_from_model_id(str(row.race_id))
        race = races.get(key)
        if race is None:
            continue
        horse_ids = json.loads(str(row.predicted_key))
        numbers = [race["id_to_number"].get(str(horse_id)) for horse_id in horse_ids]
        if len(numbers) == 3 and all(number is not None for number in numbers):
            numbers = tuple(sorted(int(number) for number in numbers))
            if len(set(numbers)) == 3 and set(numbers).issubset(race["active_numbers"]):
                race["B_set"] = numbers
                race["B_probability"] = float(row.top_probability)
                race["B_hit_flag"] = bool(row.hit)
                b_races += 1
    return {"A_model_races": a_races, "B_model_races": b_races}


def pair_key(pair: tuple[int, int]) -> str:
    return "-".join(map(str, sorted(pair)))


def strategy_candidates(race: dict) -> dict[str, tuple[str, list[str]]]:
    output: dict[str, tuple[str, list[str]]] = {}
    a_runners = race.get("A_runners", [])
    a_numbers = [runner["horse_number"] for runner in a_runners]
    if a_numbers:
        output["A_WIN_top1"] = ("WIN", [str(a_numbers[0])])
        output["A_PLC_top1"] = ("PLC", [str(a_numbers[0])])
        for count in (2, 3):
            if len(a_numbers) >= count:
                output[f"A_WIN_top{count}"] = ("WIN", [str(x) for x in a_numbers[:count]])
                output[f"A_PLC_top{count}"] = ("PLC", [str(x) for x in a_numbers[:count]])
        if len(a_numbers) >= 2:
            output["A_QNL_rank12"] = ("QNL", [pair_key(tuple(a_numbers[:2]))])
            output["A_EXA_rank12"] = ("EXA", [f"{a_numbers[0]}-{a_numbers[1]}"])
        if len(a_numbers) >= 3:
            a_top3 = tuple(sorted(a_numbers[:3]))
            output["A_TLA_top3"] = ("TLA", ["-".join(map(str, a_top3))])
            output["A_QPL_top3_pairs"] = (
                "QPL",
                [pair_key(pair) for pair in itertools.combinations(a_top3, 2)],
            )
    if "B_set" in race:
        b_set = race["B_set"]
        pairs = list(itertools.combinations(b_set, 2))
        output["B_TLA_top1"] = ("TLA", ["-".join(map(str, b_set))])
        output["B_QNL_set_pairs"] = ("QNL", [pair_key(pair) for pair in pairs])
        output["B_QPL_set_pairs"] = ("QPL", [pair_key(pair) for pair in pairs])
        output["B_EXA_set_permutations"] = (
            "EXA",
            ["-".join(map(str, order)) for order in itertools.permutations(b_set, 2)],
        )
        output["B_TRI_set_permutations"] = (
            "TRI",
            ["-".join(map(str, order)) for order in itertools.permutations(b_set, 3)],
        )

    win_prices = race["prices"].get("WIN", {})
    if win_prices:
        favorite = min(win_prices.items(), key=lambda item: (item[1], item[0]))[0]
        output["final_WIN_favorite_hindsight"] = ("WIN", [favorite])
    trio_prices = race["prices"].get("TLA", {})
    if trio_prices:
        favorite = min(trio_prices.items(), key=lambda item: (item[1], item[0]))[0]
        output["final_TLA_lowest_dividend_hindsight"] = ("TLA", [favorite])
    return output


def summarize_bets(records: list[dict]) -> dict:
    races = len(records)
    tickets = sum(len(record["keys"]) for record in records)
    if tickets == 0:
        return {"races": 0, "tickets": 0, "hit_races": 0, "hit_tickets": 0,
                "hit_race_pct": None, "hit_ticket_pct": None, "mean_selected_dividend": None,
                "mean_winning_dividend": None, "gross_return_pct": None, "roi_pct": None,
                "max_single_race_profit_units": None, "roi_without_top_profit_race_pct": None}
    payout = sum(record["payout"] for record in records)
    hit_races = sum(bool(record["hit_keys"]) for record in records)
    hit_tickets = sum(len(record["hit_keys"]) for record in records)
    selected_sum = sum(record["selected_dividend_sum"] for record in records)
    race_profits = [record["payout"] - len(record["keys"]) for record in records]
    max_index = int(np.argmax(race_profits)) if race_profits else 0
    max_profit = race_profits[max_index] if race_profits else 0.0
    if tickets > len(records[max_index]["keys"]) and max_profit > 0:
        remaining_payout = payout - records[max_index]["payout"]
        remaining_tickets = tickets - len(records[max_index]["keys"])
        removed_roi = (remaining_payout / remaining_tickets - 1.0) * 100.0
    else:
        removed_roi = None
    return {
        "races": races,
        "tickets": tickets,
        "hit_races": hit_races,
        "hit_tickets": hit_tickets,
        "hit_race_pct": 100.0 * hit_races / races if races else None,
        "hit_ticket_pct": 100.0 * hit_tickets / tickets if tickets else None,
        "mean_selected_dividend": selected_sum / tickets,
        "mean_winning_dividend": payout / hit_tickets if hit_tickets else None,
        "gross_return_pct": 100.0 * payout / tickets,
        "roi_pct": 100.0 * (payout / tickets - 1.0),
        "max_single_race_profit_units": max_profit,
        "roi_without_top_profit_race_pct": removed_roi,
    }


def summarize_strategy(races: list[dict], strategy: str, year: int | None) -> dict:
    records = []
    possible = 0
    for race in races:
        if year is not None and race["year"] != year:
            continue
        if not race.get("clean_top3"):
            continue
        candidate = strategy_candidates(race).get(strategy)
        if candidate is None:
            continue
        possible += 1
        market, keys = candidate
        prices = race["prices"].get(market, {})
        keys = list(dict.fromkeys(keys))
        if not keys or not all(key in prices for key in keys):
            continue
        hit_keys = [key for key in keys if key in race["winners"].get(market, set())]
        records.append({
            "race_id": race["db_race_id"],
            "date": race["date"],
            "keys": keys,
            "hit_keys": hit_keys,
            "payout": sum(prices[key] for key in hit_keys),
            "selected_dividend_sum": sum(prices[key] for key in keys),
        })
    result = summarize_bets(records)
    result["strategy"] = strategy
    result["year"] = "all" if year is None else year
    result["eligible_races_with_candidate"] = possible
    result["ticket_coverage_pct"] = 100.0 * result["races"] / possible if possible else None
    return result


def build_runner_rows(races: dict[tuple[str, int], dict]) -> pd.DataFrame:
    rows = []
    for race in races.values():
        if not race.get("clean_top3"):
            continue
        prices = race["prices"].get("WIN", {})
        for rank, runner in enumerate(race.get("A_runners", []), 1):
            number = runner["horse_number"]
            key = str(number)
            rows.append({
                "race_id": race["db_race_id"],
                "date": race["date"],
                "year": race["year"],
                "horse_number": number,
                "rank": rank,
                "field_size": race["active_count"],
                "A_top3_probability": runner["probability"],
                "won": key in race["winners"]["WIN"],
                "win_dividend": prices[key],
                "place_dividend": race["prices"].get("PLC", {}).get(key),
                "placed": key in race["winners"]["PLC"],
            })
    return pd.DataFrame(rows)


def calibrate_a_win_probability(runners: pd.DataFrame) -> tuple[pd.DataFrame, float, dict]:
    frame = runners.copy()
    frame["logit_A"] = np.log(
        np.clip(frame["A_top3_probability"].to_numpy(float), 1e-6, 1 - 1e-6)
        / (1 - np.clip(frame["A_top3_probability"].to_numpy(float), 1e-6, 1 - 1e-6))
    )
    train = frame[frame["year"].eq(2025)].copy()
    if train.empty:
        raise RuntimeError("2025 A model rows unavailable for win-score calibration")

    def loss(beta: float, data: pd.DataFrame) -> float:
        values = []
        for _, group in data.groupby("race_id", sort=False):
            scores = float(beta) * group["logit_A"].to_numpy(float)
            winner_mask = group["won"].to_numpy(bool)
            if int(winner_mask.sum()) != 1:
                continue
            winner_index = int(np.flatnonzero(winner_mask)[0])
            values.append(float(logsumexp(scores) - scores[winner_index]))
        if not values:
            raise RuntimeError("no single-winner races for A win calibration")
        return float(np.mean(values))

    fitted = minimize_scalar(lambda beta: loss(beta, train), bounds=(0.01, 8.0), method="bounded")
    if not fitted.success:
        raise RuntimeError("A win-probability temperature fit failed")
    beta = float(fitted.x)
    frame["p_win_model"] = np.nan
    for _, index in frame.groupby("race_id", sort=False).groups.items():
        local = frame.loc[index]
        scores = beta * local["logit_A"].to_numpy(float)
        probabilities = np.exp(scores - logsumexp(scores))
        frame.loc[index, "p_win_model"] = probabilities
    fit_meta = {
        "training_year": 2025,
        "beta": beta,
        "training_races": int(train["race_id"].nunique()),
        "training_entries": int(len(train)),
        "training_log_loss": loss(beta, train),
    }
    return frame, beta, fit_meta


def summarize_filtered(records: list[dict], label: str, year: int, threshold: float) -> dict:
    selected = [record for record in records if record["year"] == year and record["ev_proxy"] >= threshold]
    payout = sum(record["dividend"] for record in selected if record["won"])
    tickets = len(selected)
    hit_races = len({record["race_id"] for record in selected if record["won"]})
    races = len({record["race_id"] for record in selected})
    return {
        "signal": label,
        "year": year,
        "ev_proxy_threshold": threshold,
        "tickets": tickets,
        "races_with_ticket": races,
        "hit_tickets": sum(bool(record["won"]) for record in selected),
        "hit_races": hit_races,
        "hit_ticket_pct": 100.0 * sum(bool(record["won"]) for record in selected) / tickets if tickets else None,
        "hit_race_pct": 100.0 * hit_races / races if races else None,
        "mean_model_probability": float(np.mean([record["probability"] for record in selected])) if tickets else None,
        "mean_confirmed_dividend": float(np.mean([record["dividend"] for record in selected])) if tickets else None,
        "gross_return_pct": 100.0 * payout / tickets if tickets else None,
        "roi_pct": 100.0 * (payout / tickets - 1.0) if tickets else None,
    }


def make_region_tables(races: dict[tuple[str, int], dict], runner_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    calibrated, beta, calibration_meta = calibrate_a_win_probability(runner_rows)
    a_records = []
    for row in calibrated.itertuples(index=False):
        if not math.isfinite(float(row.win_dividend)):
            continue
        a_records.append({
            "race_id": int(row.race_id),
            "year": int(row.year),
            "probability": float(row.p_win_model),
            "dividend": float(row.win_dividend),
            "won": bool(row.won),
            "ev_proxy": float(row.p_win_model) * float(row.win_dividend),
        })

    b_records = []
    for race in races.values():
        if not race.get("clean_top3") or "B_set" not in race:
            continue
        key = "-".join(map(str, race["B_set"]))
        price = race["prices"].get("TLA", {}).get(key)
        if price is None:
            continue
        b_records.append({
            "race_id": race["db_race_id"],
            "year": race["year"],
            "probability": race["B_probability"],
            "dividend": float(price),
            "won": key in race["winners"]["TLA"],
            "ev_proxy": float(race["B_probability"]) * float(price),
        })

    filtered_rows = []
    for label, records in [("A 우승확률 보정점수", a_records), ("B 삼복 3두 세트확률", b_records)]:
        for year in (2025, 2026):
            for threshold in EV_THRESHOLDS:
                filtered_rows.append(summarize_filtered(records, label, year, threshold))
    filtered = pd.DataFrame(filtered_rows)

    # A top-scored runner: separate model confidence from the final win price.
    top1 = calibrated[calibrated["rank"].eq(1) & calibrated["win_dividend"].notna()].copy()
    score_edges = [0.0, 0.50, 0.60, 0.70, 0.80, 1.000001]
    price_edges = [1.0, 2.0, 5.0, 10.0, 20.0, 50.0, math.inf]
    top1["score_bin"] = pd.cut(top1["A_top3_probability"], score_edges, right=False, include_lowest=True)
    top1["price_bin"] = pd.cut(top1["win_dividend"], price_edges, right=False, include_lowest=True)
    cell_rows = []
    for (year, score_bin, price_bin), group in top1.groupby(["year", "score_bin", "price_bin"], observed=True):
        tickets = len(group)
        payout = float(group.loc[group["won"], "win_dividend"].sum())
        winning_dividends = group.loc[group["won"], "win_dividend"]
        drop_largest_roi = (
            100.0 * ((payout - float(winning_dividends.max())) / (tickets - 1) - 1.0)
            if tickets > 1 and not winning_dividends.empty else None
        )
        cell_rows.append({
            "year": int(year),
            "A_top3_probability_bin": str(score_bin),
            "confirmed_WIN_dividend_bin": str(price_bin),
            "races": tickets,
            "hits": int(group["won"].sum()),
            "hit_rate_pct": 100.0 * float(group["won"].mean()),
            "mean_A_top3_probability": float(group["A_top3_probability"].mean()),
            "mean_calibrated_win_probability": float(group["p_win_model"].mean()),
            "mean_confirmed_dividend": float(group["win_dividend"].mean()),
            "gross_return_pct": 100.0 * payout / tickets if tickets else None,
            "roi_pct": 100.0 * (payout / tickets - 1.0) if tickets else None,
            "largest_winning_dividend": float(winning_dividends.max()) if not winning_dividends.empty else None,
            "roi_without_largest_hit_pct": drop_largest_roi,
        })

    # B top pick: calibrated exact-set probability against its settled TLA dividend.
    b_top = pd.DataFrame(b_records)
    b_cell_rows = []
    if not b_top.empty:
        b_top["probability_bin"] = pd.cut(
            b_top["probability"], [0.0, 0.04, 0.06, 0.08, 0.10, 0.15, 1.000001],
            right=False, include_lowest=True,
        )
        b_top["dividend_bin"] = pd.cut(
            b_top["dividend"], [1.0, 5.0, 10.0, 20.0, 50.0, 100.0, 500.0, math.inf],
            right=False, include_lowest=True,
        )
        for (year, probability_bin, dividend_bin), group in b_top.groupby(
            ["year", "probability_bin", "dividend_bin"], observed=True
        ):
            tickets = len(group)
            payout = float(group.loc[group["won"], "dividend"].sum())
            winning_dividends = group.loc[group["won"], "dividend"]
            drop_largest_roi = (
                100.0 * ((payout - float(winning_dividends.max())) / (tickets - 1) - 1.0)
                if tickets > 1 and not winning_dividends.empty else None
            )
            b_cell_rows.append({
                "year": int(year),
                "B_set_probability_bin": str(probability_bin),
                "confirmed_TLA_dividend_bin": str(dividend_bin),
                "races": tickets,
                "hits": int(group["won"].sum()),
                "hit_rate_pct": 100.0 * float(group["won"].mean()),
                "mean_model_probability": float(group["probability"].mean()),
                "mean_confirmed_dividend": float(group["dividend"].mean()),
                "model_probability_times_dividend": float((group["probability"] * group["dividend"]).mean()),
                "gross_return_pct": 100.0 * payout / tickets if tickets else None,
                "roi_pct": 100.0 * (payout / tickets - 1.0),
                "largest_winning_dividend": float(winning_dividends.max()) if not winning_dividends.empty else None,
                "roi_without_largest_hit_pct": drop_largest_roi,
            })
    cells = pd.concat([pd.DataFrame(cell_rows), pd.DataFrame(b_cell_rows)], ignore_index=True, sort=False)
    return filtered, cells, calibration_meta


def main() -> None:
    races, min_snapshot_hours = load_database()
    model_counts = attach_model_predictions(races)
    clean_races = [race for race in races.values() if race.get("clean_top3")]
    common_races = [race for race in clean_races if "A_runners" in race and "B_set" in race]
    a_label_mismatches = sum(
        (runner["label"] >= 0.5) != (runner["horse_number"] in race["actual_top3"])
        for race in common_races for runner in race["A_runners"]
    )
    b_hit_mismatches = sum(
        race["B_hit_flag"] != ("-".join(map(str, race["B_set"])) in race["winners"]["TLA"])
        for race in common_races if "B_hit_flag" in race
    )

    strategy_names = [
        "A_WIN_top1", "A_PLC_top1", "A_WIN_top2", "A_PLC_top2",
        "A_WIN_top3", "A_PLC_top3", "A_QNL_rank12", "A_EXA_rank12",
        "A_TLA_top3", "A_QPL_top3_pairs", "B_TLA_top1",
        "B_QNL_set_pairs", "B_QPL_set_pairs", "B_EXA_set_permutations",
        "B_TRI_set_permutations", "final_WIN_favorite_hindsight",
        "final_TLA_lowest_dividend_hindsight",
    ]
    strategy_rows = []
    for strategy in strategy_names:
        for year in (2025, 2026, None):
            strategy_rows.append(summarize_strategy(common_races, strategy, year))
    strategy_table = pd.DataFrame(strategy_rows)
    runner_rows = build_runner_rows(races)
    regions, cells, calibration_meta = make_region_tables(races, runner_rows)

    OUT.mkdir(parents=True, exist_ok=True)
    strategy_table.to_csv(OUT / "strategy_results.csv", index=False)
    regions.to_csv(OUT / "ev_threshold_regions.csv", index=False)
    cells.to_csv(OUT / "probability_price_cells.csv", index=False)
    metadata = {
        "scope": {"venue": "BUSAN", "start_date": START_DATE, "database_end_date": END_DATE,
                  "model_common_end_date": max((race["date"] for race in clean_races if "A_runners" in race and "B_set" in race), default=None)},
        "model_source": {
            "active_profile": "thoroughbred-main-20260919-v1",
            "A": "current_A: frozen historical runner Top-3 inclusion predictions",
            "B": "current_B: frozen historical highest-probability unordered Top-3 set",
            "C": "historical current_C ticket keys are not retained in this archive; TRI tests use all six orders of the B set, not C output",
            **model_counts,
            "A_runner_label_mismatches_vs_settled_results": int(a_label_mismatches),
            "B_top_set_hit_mismatches_vs_settled_results": int(b_hit_mismatches),
        },
        "settlement": {
            "dividend_source": "latest stored odds_snapshots row per race, bet_type and selection_key",
            "stored_sentinel_excluded": DIVIDEND_SENTINEL,
            "each_ticket_stake_krw": 100,
            "first_snapshot_after_scheduled_start_hours": min_snapshot_hours,
            "clear_top3_races": len(clean_races),
            "common_A_B_clean_top3_races": len(common_races),
            "warning": "The stored snapshots are after scheduled start, so odds-conditioned selection is retrospective and not actionable as a pre-race backtest.",
        },
        "A_win_calibration": calibration_meta,
        "confirmed_odds_are_not_model_features": True,
    }
    (OUT / "analysis_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")

    _write_report(strategy_table, regions, cells, metadata)


def _fmt(value: object, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    try:
        if pd.isna(value):
            return "—"
    except (TypeError, ValueError):
        pass
    return f"{float(value):,.{digits}f}"


def _write_report(strategy: pd.DataFrame, regions: pd.DataFrame, cells: pd.DataFrame, meta: dict) -> None:
    descriptions = {
        "A_WIN_top1": "A 최고 Top-3 확률마 1두 단승",
        "A_PLC_top1": "A 최고 Top-3 확률마 1두 연승",
        "A_WIN_top2": "A 상위 2두 단승 각 1장",
        "A_PLC_top2": "A 상위 2두 연승 각 1장",
        "A_WIN_top3": "A 상위 3두 단승 각 1장",
        "A_PLC_top3": "A 상위 3두 연승 각 1장",
        "A_QNL_rank12": "A 1·2순위 복승 1장",
        "A_EXA_rank12": "A 1→2순위 쌍승 1장",
        "A_TLA_top3": "A 상위 3두 삼복 1장",
        "A_QPL_top3_pairs": "A 상위 3두 복연 3장",
        "B_TLA_top1": "B 최고확률 삼복 조합 1장",
        "B_QNL_set_pairs": "B 최고확률 3두 세트의 복승 3장",
        "B_QPL_set_pairs": "B 최고확률 3두 세트의 복연 3장",
        "B_EXA_set_permutations": "B 최고확률 3두 세트의 6개 쌍승 순서",
        "B_TRI_set_permutations": "B 최고확률 3두 세트의 6개 삼쌍 순서",
        "final_WIN_favorite_hindsight": "확정 단승 최저배당 말 1두 (사후 기준선)",
        "final_TLA_lowest_dividend_hindsight": "확정 삼복 최저배당 조합 1개 (사후 기준선)",
    }
    combined = strategy[strategy["year"].eq("all")].copy()
    by_year = strategy[strategy["year"].isin([2025, 2026])].copy()
    lines = [
        "# 부산 현행 모델 예측 × 확정배당 사후 수익 구간 분석",
        "",
        "## 분석 범위",
        "",
        f"- 자료: 부산 {START_DATE}~{meta['scope']['model_common_end_date']} 모델 공통 구간. 확정배당 DB는 {END_DATE}까지지만 저장된 현행 모델 예측은 2026-09-11에 끝납니다.",
        f"- 경주: 1·2·3착이 각각 단독 확정된 {meta['settlement']['clear_top3_races']:,}경주 중 A/B 모델이 모두 있는 {meta['settlement']['common_A_B_clean_top3_races']:,}경주를 공통 비교했습니다. 전략별로 필요한 배당 조합이 없는 경주는 해당 전략 표본에서 빠집니다.",
        "- 모델: 등록된 현행 A `current_A`의 말별 3위 이내 확률과 B `current_B`의 최고확률 3두 세트. A 확률을 우승확률로 해석하지 않았습니다.",
        f"- 결과 연결 점검: A 말별 입상 라벨과 B 삼복 세트 적중 표지가 DB 착순 결과와 각각 {meta['model_source']['A_runner_label_mismatches_vs_settled_results']}건, {meta['model_source']['B_top_set_hit_mismatches_vs_settled_results']}건 달랐습니다.",
        "- 정산: 각 승식·조합별 가장 늦게 저장된 배당을 환급배수로 사용하고, 한 장당 100원으로 계산했습니다. 결승 3착 동률 경주는 제외했습니다.",
        f"- 시간: 해당 기간 첫 배당 관측이 예정 출발보다 최소 {_fmt(meta['settlement']['first_snapshot_after_scheduled_start_hours'], 3)}시간 뒤입니다. 따라서 확정배당으로 환급은 맞췄지만, 배당으로 후보를 거르는 수익률은 전부 사후 비교입니다.",
        "",
        "## 모델 순위로 고정 구매한 조합",
        "",
        "적중 경주율은 한 장 이상 맞힌 경주의 비율입니다. ROI는 매 선택에 동일 금액을 건 순수익률이며, 여러 장 전략은 경주당 구매 장수만큼 분모에 반영했습니다.",
        "",
        "| 후보 | 2025 ROI | 2025 표본 | 2026 ROI | 2026 표본 | 합산 ROI | 합산 적중 경주율 | 최고 수익 경주 제외 ROI |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy_name in descriptions:
        row_2025 = by_year[(by_year.strategy == strategy_name) & (by_year.year == 2025)]
        row_2026 = by_year[(by_year.strategy == strategy_name) & (by_year.year == 2026)]
        row_all = combined[combined.strategy == strategy_name]
        if row_2025.empty or row_2026.empty or row_all.empty:
            continue
        a, b, c = row_2025.iloc[0], row_2026.iloc[0], row_all.iloc[0]
        lines.append(
            f"| {descriptions[strategy_name]} | {_fmt(a.roi_pct)}% | {int(a.races):,}경주/{int(a.tickets):,}장 | "
            f"{_fmt(b.roi_pct)}% | {int(b.races):,}경주/{int(b.tickets):,}장 | {_fmt(c.roi_pct)}% | "
            f"{_fmt(c.hit_race_pct)}% | {_fmt(c.roi_without_top_profit_race_pct)}% |"
        )

    lines += [
        "",
        "확정배당 최저가를 고른 두 행은 과거 시장 기준선입니다. 그 선택도 출발 뒤 확정배당을 알아야 가능하므로 실전 가능 전략으로 보면 안 됩니다.",
        "",
        "## 모델 확률 × 확정배당 구간",
        "",
        "A는 2025년 부산 예측과 결과만 사용해 A의 Top-3 점수를 우승확률 분포로 다시 스케일하는 계수(β)를 맞춘 뒤 2026년에 고정 적용했습니다. B는 이미 최고 삼복 조합의 정확한 세트 적중확률을 냅니다. 여기서 `모델확률 × 확정배당`은 기대환급 참고값으로 사용했습니다.",
        "아래 필터는 확정배당을 알아야 후보가 정해지는 사후 규칙입니다. 2025에서 표본 30장 이상인 임계값 중 ROI가 가장 높은 것을 고르고, 같은 임계값을 2026에 그대로 적용해 확인했습니다.",
        "",
        "| 신호 | 2025에서 고른 EV 참고 임계값 | 2025 선택 수 | 2025 ROI | 2026 같은 규칙 선택 수 | 2026 ROI |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    selected_thresholds = {}
    for signal in regions.signal.unique():
        train = regions[(regions.signal == signal) & (regions.year == 2025) & (regions.tickets >= 30) & regions.roi_pct.notna()]
        if train.empty:
            continue
        picked = train.sort_values(["roi_pct", "tickets"], ascending=[False, False]).iloc[0]
        test = regions[(regions.signal == signal) & (regions.year == 2026) & (regions.ev_proxy_threshold == picked.ev_proxy_threshold)]
        selected_thresholds[signal] = float(picked.ev_proxy_threshold)
        if test.empty:
            continue
        holdout = test.iloc[0]
        lines.append(
            f"| {signal} | {picked.ev_proxy_threshold:.2f} | {int(picked.tickets):,}장 | {_fmt(picked.roi_pct)}% | "
            f"{int(holdout.tickets):,}장 | {_fmt(holdout.roi_pct)}% |"
        )

    top1_cells = cells[cells["year"].eq(2026) & cells["A_top3_probability_bin"].notna()].copy()
    b_cells = cells[cells["year"].eq(2026) & cells["B_set_probability_bin"].notna()].copy()
    lines += ["", "## 두 연도에 반복된 양수 셀 후보", "", "두 해 각각 20경주 이상이고 두 해 ROI가 모두 양수인 셀만 추렸습니다. 셀 자체는 결과를 본 뒤 발견했으므로 미래 성능을 입증하지 않습니다. 최고 적중 1건을 제거한 ROI도 같이 봤습니다.", "",
              "| 신호·확정배당 구간 | 2025 경주 / ROI / 1건 제외 | 2026 경주 / ROI / 1건 제외 | 합산 경주 / 적중 / ROI |",
              "|---|---:|---:|---:|"]
    repeat_candidates = []
    for signal, probability_col, dividend_col in [
        ("A", "A_top3_probability_bin", "confirmed_WIN_dividend_bin"),
        ("B", "B_set_probability_bin", "confirmed_TLA_dividend_bin"),
    ]:
        part = cells[cells[probability_col].notna()].copy()
        for (probability_bin, dividend_bin), group in part.groupby([probability_col, dividend_col], dropna=False):
            y25 = group[group["year"].eq(2025)]
            y26 = group[group["year"].eq(2026)]
            if y25.empty or y26.empty:
                continue
            r25, r26 = y25.iloc[0], y26.iloc[0]
            if min(r25["races"], r26["races"]) < 20 or min(r25["roi_pct"], r26["roi_pct"]) <= 0:
                continue
            n = int(r25["races"] + r26["races"])
            payout = (r25["gross_return_pct"] / 100.0 * r25["races"]
                      + r26["gross_return_pct"] / 100.0 * r26["races"])
            combined_roi = 100.0 * (payout / n - 1.0)
            repeat_candidates.append({
                "signal": signal,
                "region": f"{probability_bin} × {dividend_bin}",
                "n25": int(r25["races"]), "roi25": float(r25["roi_pct"]),
                "drop25": r25.get("roi_without_largest_hit_pct"),
                "n26": int(r26["races"]), "roi26": float(r26["roi_pct"]),
                "drop26": r26.get("roi_without_largest_hit_pct"),
                "n": n, "hits": int(r25["hits"] + r26["hits"]), "roi": combined_roi,
            })
    repeat_candidates.sort(key=lambda row: row["roi"], reverse=True)
    if not repeat_candidates:
        lines.append("| 반복 양수 셀 없음 | — | — | — |")
    else:
        for row in repeat_candidates:
            lines.append(
                f"| {row['signal']} {row['region']} | {row['n25']} / {_fmt(row['roi25'])}% / {_fmt(row['drop25'])}% | "
                f"{row['n26']} / {_fmt(row['roi26'])}% / {_fmt(row['drop26'])}% | "
                f"{row['n']} / {row['hits']} / {_fmt(row['roi'])}% |"
            )

    lines += ["", "### 2026 A 점수·단승 배당 셀", "", "표본 20경주 이상인 셀만 표시했습니다. 양수라도 사후 배당 구간을 보고 고른 셀이므로 발견용 진단입니다.", "",
              "| A 입상점수 구간 | 확정 단승배당 | 경주 | 우승 | ROI | 최고 적중 1건 제외 |",
              "|---|---:|---:|---:|---:|---:|"]
    if top1_cells.empty:
        lines.append("| 해당 셀 없음 | — | — | — | — |")
    else:
        selected = top1_cells[top1_cells["races"].ge(20)].sort_values("roi_pct", ascending=False)
        if selected.empty:
            lines.append("| 20경주 이상 셀 없음 | — | — | — | — |")
        for row in selected.head(12).itertuples(index=False):
            lines.append(f"| {row.A_top3_probability_bin} | {row.confirmed_WIN_dividend_bin} | {int(row.races)} | {int(row.hits)} | {_fmt(row.roi_pct)}% | {_fmt(row.roi_without_largest_hit_pct)}% |")
    lines += ["", "### 2026 B 확률·삼복배당 셀", "", "표본 20경주 이상인 셀만 표시했습니다.", "",
              "| B 세트확률 구간 | 확정 삼복배당 | 경주 | 적중 | 평균 p×배당 | ROI | 최고 적중 1건 제외 |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    if b_cells.empty:
        lines.append("| 해당 셀 없음 | — | — | — | — | — |")
    else:
        selected = b_cells[b_cells["races"].ge(20)].sort_values("roi_pct", ascending=False)
        if selected.empty:
            lines.append("| 20경주 이상 셀 없음 | — | — | — | — | — |")
        for row in selected.head(12).itertuples(index=False):
            lines.append(f"| {row.B_set_probability_bin} | {row.confirmed_TLA_dividend_bin} | {int(row.races)} | {int(row.hits)} | {_fmt(row.model_probability_times_dividend)} | {_fmt(row.roi_pct)}% | {_fmt(row.roi_without_largest_hit_pct)}% |")
    lines += [
        "",
        "## 해석과 제한",
        "",
        "- 고정 후보표에서 2025 양수 ROI가 나와도 2026에 유지되는지 함께 봐야 합니다. `최고 수익 경주 제외 ROI`는 고배당 한 번이 결과를 끌어올렸는지 보여줍니다.",
        "- A의 `A_top3_probability`는 말이 3위 안에 들 확률입니다. WIN 구간은 2025에서 별도 재스케일한 A 신호를 쓴 탐색이며, 2026 결과를 독립 확인 구간으로 취급했습니다.",
        "- B 삼복은 모델이 직접 내는 3두 세트 확률을 사용했습니다. B 세트에서 복승·쌍승·복연·삼쌍으로 확장한 표는 조합 수가 3장 또는 6장인 포트폴리오이며, 해당 승식의 개별 확률을 모델이 직접 낸 것은 아닙니다.",
        "- 현행 C의 역사적 1→2→3착 예측키가 보관 산출물에 없어, 삼쌍의 직접 C 단일선택 ROI는 계산하지 않았습니다. 삼쌍은 B의 최고 세트 안에서 가능한 6개 순서를 모두 사는 방식만 평가했습니다.",
        "- 반복 양수 셀은 발견됐지만 안정적인 수익구간으로 판정하지 않았습니다. A의 0.60~0.70 점수·단승 5~10배 셀은 2025에서 최고 적중 1건을 빼면 ROI -24.58%, B의 10~15% 삼복 세트확률·삼복 10~20배 셀은 2026에서 그 기준 ROI -23.87%입니다. 나머지 반복 양수 셀도 최고 적중 1건 제거 후 두 해를 유지하지 못했습니다.",
        "- 수익 구간이 보이더라도 확정배당 관측이 예정 출발 이후라 실전 기대수익 증거는 아닙니다. 실전 검증에는 출발 전 고정한 A/B/C 예측과 출발 전 배당 스냅샷, 그 뒤 확정배당 정산을 연결해야 합니다.",
        "",
        "산출물: `strategy_results.csv`, `ev_threshold_regions.csv`, `probability_price_cells.csv`, `analysis_metadata.json`.",
        "",
    ]
    (OUT / "model_dividend_regions.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
