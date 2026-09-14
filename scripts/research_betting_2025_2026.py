"""Exploratory, no-pre-race-odds betting rules on comparable 2025/26 OOS scores.

Final odds settle bets only. This is retrospective research, not a live edge.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations, permutations
from pathlib import Path

import polars as pl

from horse_racing.analysis.ordered_triple import ordered_winner_keys

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/datasets/racefit_v3_lifecycle_history/day_before_18/dataset.parquet"
DATABASE = ROOT / "data/horse_racing.sqlite3"
RUNS = {
    2025: "3cc795cf-1485-43be-8668-8dad02a4926c",
    2026: "3e03923a-c559-4993-a61f-7e9cbdcad0eb",
}
POOLS = ("WIN", "PLC", "QNL", "QPL", "EXA", "TLA", "TRI")


def key(numbers: tuple[int, ...], *, ordered: bool) -> str:
    return "-".join(map(str, numbers if ordered else sorted(numbers)))


def winning_tickets(triples: list[tuple[int, int, int]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {pool: set() for pool in POOLS}
    for a, b, c in triples:
        result["WIN"].add(str(a))
        result["PLC"].update((str(a), str(b), str(c)))
        result["QNL"].add(key((a, b), ordered=False))
        result["EXA"].add(key((a, b), ordered=True))
        result["TLA"].add(key((a, b, c), ordered=False))
        result["TRI"].add(key((a, b, c), ordered=True))
        for pair in combinations((a, b, c), 2):
            result["QPL"].add(key(pair, ordered=False))
    return result


@dataclass(frozen=True)
class Race:
    year: int
    race_id: int
    runners: tuple[int, ...]
    p1: float
    p2: float
    meet_code: int
    date: str
    payouts: dict[str, dict[str, float]]


def load_races() -> tuple[list[Race], dict[str, int]]:
    predictions = pl.concat(
        [
            pl.read_parquet(ROOT / f"data/experiments/walk_forward/{run}/predictions.parquet")
            .select("race_id", "horse_number", "prob_win")
            .with_columns(pl.lit(year).alias("year"))
            for year, run in RUNS.items()
        ]
    )
    if predictions.select("race_id", "horse_number").is_duplicated().any():
        raise ValueError("duplicate predictions")
    dataset = (
        pl.scan_parquet(DATASET)
        .select("race_id", "horse_number", "finish_position", "race_date_local", "meet_code")
        .filter(pl.col("race_id").is_in(predictions["race_id"].unique().to_list()))
        .collect()
    )
    context = {
        int(row["race_id"]): row
        for row in dataset.select("race_id", "race_date_local", "meet_code")
        .unique("race_id")
        .iter_rows(named=True)
    }
    triples: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for row in ordered_winner_keys(dataset).iter_rows(named=True):
        triples[int(row["race_id"])].append(tuple(map(int, row["selection_key"].split("-"))))
    candidate: list[
        tuple[int, int, tuple[int, ...], float, float, int, str, dict[str, set[str]]]
    ] = []
    counts = {"predicted_races": predictions["race_id"].n_unique(), "lt8": 0, "missing_top3": 0}
    for (race_id,), group in predictions.group_by("race_id"):
        race_id = int(race_id)
        group = group.sort("prob_win", "horse_number", descending=[True, False])
        runners = tuple(int(x) for x in group["horse_number"].to_list())
        if len(runners) < 8:
            counts["lt8"] += 1
            continue
        if not triples.get(race_id):
            counts["missing_top3"] += 1
            continue
        info = context[race_id]
        candidate.append(
            (
                int(group["year"][0]),
                race_id,
                runners,
                float(group["prob_win"][0]),
                float(group["prob_win"][1]),
                int(info["meet_code"]),
                str(info["race_date_local"]),
                winning_tickets(triples[race_id]),
            )
        )
    # Scanning each race's odds once avoids many unindexed selection-key queries.
    races: list[Race] = []
    counts["invalid_any_pool"] = 0
    with sqlite3.connect(DATABASE) as conn:
        for year, race_id, runners, p1, p2, meet, date, winners in candidate:
            odds = {
                (pool, selection): float(value)
                for pool, selection, value in conn.execute(
                    "SELECT bet_type,selection_key,odds FROM odds_snapshots WHERE race_id=?",
                    (race_id,),
                )
                if value is not None
            }
            payouts: dict[str, dict[str, float]] = {}
            for pool, selections in winners.items():
                payouts[pool] = {
                    selection: odds[(pool, selection)]
                    for selection in selections
                    if (pool, selection) in odds and 1 <= odds[(pool, selection)] < 9999.9
                }
            if any(len(payouts[pool]) != len(winners[pool]) for pool in POOLS):
                counts["invalid_any_pool"] += 1
                continue
            races.append(Race(year, race_id, runners, p1, p2, meet, date, payouts))
    counts["common_races"] = len(races)
    return races, counts


def tickets(name: str, r: Race) -> tuple[str, tuple[str, ...]]:
    h = r.runners
    if name == "win1":
        return "WIN", (str(h[0]),)
    if name == "win2":
        return "WIN", tuple(map(str, h[:2]))
    if name == "plc1":
        return "PLC", (str(h[0]),)
    if name == "plc2":
        return "PLC", tuple(map(str, h[:2]))
    if name == "plc3":
        return "PLC", tuple(map(str, h[:3]))
    if name == "qnl12":
        return "QNL", (key(h[:2], ordered=False),)
    if name == "qnl1_234":
        return "QNL", tuple(key((h[0], x), ordered=False) for x in h[1:4])
    if name == "qpl12":
        return "QPL", (key(h[:2], ordered=False),)
    if name == "qpl123":
        return "QPL", tuple(key(x, ordered=False) for x in combinations(h[:3], 2))
    if name == "qpl1_234":
        return "QPL", tuple(key((h[0], x), ordered=False) for x in h[1:4])
    if name == "exa12":
        return "EXA", (key(h[:2], ordered=True),)
    if name == "exa1_234":
        return "EXA", tuple(key((h[0], x), ordered=True) for x in h[1:4])
    if name == "exa12_rev":
        return "EXA", (key(h[:2], ordered=True), key(h[1::-1], ordered=True))
    if name == "tla123":
        return "TLA", (key(h[:3], ordered=False),)
    if name == "tla1234":
        return "TLA", tuple(key(x, ordered=False) for x in combinations(h[:4], 3))
    if name == "tla12_345":
        return "TLA", tuple(key((h[0], h[1], x), ordered=False) for x in h[2:5])
    if name == "tri123":
        return "TRI", (key(h[:3], ordered=True),)
    if name == "tri123_box":
        return "TRI", tuple(key(x, ordered=True) for x in permutations(h[:3], 3))
    if name == "tri1_234":
        return "TRI", tuple(key((h[0], *x), ordered=True) for x in permutations(h[1:4], 2))
    if name == "tri12_345":
        return "TRI", tuple(key((h[0], h[1], x), ordered=True) for x in h[2:5])
    raise ValueError(name)


RULES = (
    "win1", "win2", "plc1", "plc2", "plc3", "qnl12", "qnl1_234",
    "qpl12", "qpl123", "qpl1_234", "exa12", "exa1_234", "exa12_rev",
    "tla123", "tla1234", "tla12_345", "tri123", "tri123_box", "tri1_234", "tri12_345",
)


def summary(
    races: list[Race], rule: str, year: int, *, condition: str = "all",
    meet_code: int | None = None, through_month_day: str | None = None,
) -> dict:
    selected = [r for r in races if r.year == year]
    if meet_code is not None:
        selected = [r for r in selected if r.meet_code == meet_code]
    if through_month_day is not None:
        selected = [r for r in selected if r.date[5:] <= through_month_day]
    if condition == "p1_25":
        selected = [r for r in selected if r.p1 >= .25]
    elif condition == "p1_35":
        selected = [r for r in selected if r.p1 >= .35]
    elif condition == "gap10":
        selected = [r for r in selected if r.p1 - r.p2 >= .10]
    elif condition != "all":
        raise ValueError(condition)
    stakes: list[int] = []
    returns: list[float] = []
    hits = 0
    for r in selected:
        pool, chosen = tickets(rule, r)
        stakes.append(len(chosen))
        returned = sum(r.payouts[pool].get(x, 0.0) for x in chosen)
        returns.append(returned)
        hits += returned > 0
    total_stake = sum(stakes)
    total_return = sum(returns)
    top_return = max(returns, default=0)
    return {
        "races": len(selected), "hits": hits,
        "hit_pct": 100 * hits / len(selected) if selected else 0,
        "return_pct": 100 * total_return / total_stake if total_stake else 0,
        "without_top_pct": 100 * (total_return - top_return) / total_stake if total_stake else 0,
        "top_share_pct": 100 * top_return / total_return if total_return else 0,
    }


def main() -> None:
    races, counts = load_races()
    print("runs", RUNS)
    print("counts", counts)
    print("Rule | 2025 n hit% return% ex-top% | 2026 n hit% return% ex-top%")
    for rule in RULES:
        parts = []
        for year in RUNS:
            s = summary(races, rule, year)
            parts.append(
                f"{s['races']} {s['hit_pct']:.1f} {s['return_pct']:.1f} "
                f"{s['without_top_pct']:.1f}"
            )
        print(rule, " | ".join(parts))
    print("FILTERED")
    for condition in ("p1_25", "p1_35", "gap10"):
        for rule in ("win1", "plc1", "qnl12", "qpl12", "tla123", "tri123_box"):
            parts = []
            for year in RUNS:
                s = summary(races, rule, year, condition=condition)
                parts.append(
                    f"{s['races']} {s['hit_pct']:.1f} {s['return_pct']:.1f} "
                    f"{s['without_top_pct']:.1f}"
                )
            print(condition, rule, " | ".join(parts))
    print("MATCHED JAN-AUG 23")
    for rule in ("win1", "win2", "plc1", "plc2", "plc3", "qnl12", "qpl12", "tla123", "tri123_box"):
        parts = []
        for year in RUNS:
            s = summary(races, rule, year, through_month_day="08-23")
            parts.append(f"{s['races']} {s['hit_pct']:.1f} {s['return_pct']:.1f}")
        print(rule, " | ".join(parts))
    print("BY TRACK -- DESCRIPTIVE ONLY; NOT VALIDATED STRATEGIES")
    for meet in (1, 2, 3):
        for rule in ("win1", "win2", "plc1", "qnl12", "qpl12", "tla123", "tri123_box"):
            parts = []
            for year in RUNS:
                s = summary(races, rule, year, meet_code=meet)
                parts.append(f"{s['races']} {s['return_pct']:.1f} {s['without_top_pct']:.1f}")
            print(meet, rule, " | ".join(parts))


if __name__ == "__main__":
    main()
