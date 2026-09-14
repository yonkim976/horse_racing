"""Compare flat-stake ordered-trifecta boxes on one fixed OOS race cohort.

The saved RaceFit V5 walk-forward predictions are made by training on prior
calendar years. Final TRI dividends are used only for settlement, never for
selecting horses. One unit is staked on every ordered ticket in each box.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from horse_racing.analysis.ordered_triple import ordered_winner_keys

ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS = (
    ROOT
    / "data/experiments/walk_forward/b3eed694-89a1-4bcf-ac8c-9677760c1448/predictions.parquet"
)
DATASET = ROOT / "data/datasets/racefit_v5_sand_rich_v2_matched/start_minus_30m/dataset.parquet"
DATABASE = ROOT / "data/horse_racing.sqlite3"
MAX_N = 10


@dataclass(frozen=True)
class Race:
    race_id: int
    meet_code: int
    runners: tuple[int, ...]
    winning_payouts: tuple[tuple[tuple[int, int, int], float], ...]


def load_races() -> tuple[list[Race], dict[str, int]]:
    predictions = pl.read_parquet(PREDICTIONS).select("race_id", "horse_number", "prob_win")
    if predictions.select("race_id", "horse_number").is_duplicated().any():
        raise ValueError("duplicate prediction horse numbers")
    dataset = pl.scan_parquet(DATASET).select(
        "race_id", "horse_number", "finish_position", "race_date_local", "meet_code"
    ).filter(pl.col("race_id").is_in(predictions["race_id"].unique().to_list())).collect()
    race_meets = dict(
        dataset.select("race_id", "meet_code")
        .unique()
        .select("race_id", "meet_code")
        .iter_rows()
    )
    winners = ordered_winner_keys(dataset)
    winner_map: dict[int, list[str]] = {}
    for row in winners.iter_rows(named=True):
        winner_map.setdefault(int(row["race_id"]), []).append(str(row["selection_key"]))

    counts = {
        "predicted_races": predictions["race_id"].n_unique(),
        "missing_complete_top3": 0,
        "missing_or_invalid_winning_odds": 0,
        "invalid_runner_count": 0,
        "dead_heat_races": 0,
    }
    races: list[Race] = []
    with sqlite3.connect(DATABASE) as connection:
        for (race_id,), group in predictions.group_by("race_id"):
            race_id = int(race_id)
            ordered = group.sort("prob_win", "horse_number", descending=[True, False])
            runners = tuple(int(x) for x in ordered["horse_number"].to_list())
            if len(runners) != len(set(runners)) or len(runners) < 3:
                counts["invalid_runner_count"] += 1
                continue
            winning_keys = winner_map.get(race_id, [])
            if not winning_keys:
                counts["missing_complete_top3"] += 1
                continue
            payouts: list[tuple[tuple[int, int, int], float]] = []
            for key in winning_keys:
                row = connection.execute(
                    """SELECT odds FROM odds_snapshots
                       WHERE race_id = ? AND bet_type = 'TRI' AND selection_key = ?
                       ORDER BY observed_at_ms DESC LIMIT 1""",
                    (race_id, key),
                ).fetchone()
                if row is None or row[0] is None or not 1 < float(row[0]) < 9999.9:
                    payouts = []
                    break
                numbers = tuple(int(x) for x in key.split("-"))
                if len(numbers) != 3 or len(set(numbers)) != 3:
                    payouts = []
                    break
                payouts.append((numbers, float(row[0])))
            if len(payouts) != len(winning_keys):
                counts["missing_or_invalid_winning_odds"] += 1
                continue
            if len(payouts) > 1:
                counts["dead_heat_races"] += 1
            races.append(Race(race_id, int(race_meets[race_id]), runners, tuple(payouts)))
    return races, counts


def summarize(races: list[Race], *, n: int, bootstrap_draws: int = 5000) -> dict[str, float | int]:
    eligible = [race for race in races if len(race.runners) >= n]
    tickets_per_race = n * (n - 1) * (n - 2)
    payouts = np.array(
        [
            sum(
                dividend
                for numbers, dividend in race.winning_payouts
                if set(numbers).issubset(race.runners[:n])
            )
            for race in eligible
        ],
        dtype=float,
    )
    if payouts.size == 0:
        raise ValueError(f"no eligible races for n={n}")
    rng = np.random.default_rng(20260913 + n)
    indices = rng.integers(0, payouts.size, size=(bootstrap_draws, payouts.size))
    boot = payouts[indices].mean(axis=1) / tickets_per_race
    gross = float(payouts.sum())
    stake = int(payouts.size * tickets_per_race)
    hits = int(np.count_nonzero(payouts > 0))
    return {
        "n": n,
        "races": int(payouts.size),
        "tickets_per_race": tickets_per_race,
        "hits": hits,
        "hit_pct": 100 * hits / payouts.size,
        "stake_units": stake,
        "return_units": gross,
        "return_pct": 100 * gross / stake,
        "net_roi_pct": 100 * (gross / stake - 1),
        "bootstrap_low_pct": 100 * float(np.quantile(boot, 0.025)),
        "bootstrap_high_pct": 100 * float(np.quantile(boot, 0.975)),
        "top_payout_share_pct": 100 * float(payouts.max()) / gross if gross else 0.0,
        "without_top_payout_pct": 100 * float(gross - payouts.max()) / stake,
        "mean_hit_dividend": gross / hits if hits else 0.0,
    }


def print_table(races: list[Race], *, common_cohort: bool, meet_code: int | None = None) -> None:
    cohort = [race for race in races if meet_code is None or race.meet_code == meet_code]
    if common_cohort:
        cohort = [race for race in cohort if len(race.runners) >= MAX_N]
    title = f"COMMON >= {MAX_N} RUNNERS" if common_cohort else "ALL ELIGIBLE BY N"
    if meet_code is not None:
        title += f" MEET={meet_code}"
    print(f"\n{title}: cohort={len(cohort)}")
    print(
        "n races combos hits hit% stake return return% netROI% "
        "95%CI_return% top1_share% without_top1_return% mean_hit_dividend"
    )
    for n in range(3, MAX_N + 1):
        s = summarize(cohort, n=n)
        print(
            f"{n} {s['races']} {s['tickets_per_race']} {s['hits']} "
            f"{s['hit_pct']:.2f} {s['stake_units']} {s['return_units']:.1f} "
            f"{s['return_pct']:.2f} {s['net_roi_pct']:.2f} "
            f"[{s['bootstrap_low_pct']:.2f},{s['bootstrap_high_pct']:.2f}] "
            f"{s['top_payout_share_pct']:.2f} {s['without_top_payout_pct']:.2f} "
            f"{s['mean_hit_dividend']:.1f}"
        )


def main() -> None:
    races, counts = load_races()
    print(f"source_predictions={PREDICTIONS}")
    print(f"source_dataset={DATASET}")
    print(f"quality_counts={counts}")
    print_table(races, common_cohort=True)
    print_table(races, common_cohort=False)
    print_table(races, common_cohort=True, meet_code=1)


if __name__ == "__main__":
    main()
