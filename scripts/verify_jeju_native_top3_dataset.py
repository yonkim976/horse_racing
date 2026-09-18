"""Read-only, source-key and combinatorial verification of a Top3 dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify(output: Path) -> dict:
    manifest = json.loads((output / "manifest.json").read_text())
    checked_files = 0
    for name, item in manifest["files"].items():
        path = output / name
        assert path.stat().st_size == item["bytes"], f"size mismatch: {name}"
        assert digest(path) == item["sha256"], f"hash mismatch: {name}"
        checked_files += 1
    db_path = Path(manifest["source_db"]["path"])
    assert digest(db_path) == manifest["source_db"]["sha256"], "source DB hash changed"
    entries = pl.read_parquet(output / "entries.parquet")
    labels = pl.read_parquet(output / "labels.parquet")
    states = pl.read_parquet(output / "horse_states.parquet")
    orders = pl.read_parquet(output / "accepted_orders.parquet")
    sets = pl.read_parquet(output / "accepted_sets.parquet")
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        expected = connection.execute("""
            WITH starters AS (
                SELECT ev.id race_id, e.id entry_id, ev.distance_m, e.identity_status
                FROM event ev JOIN entry e ON e.event_id=ev.id
                WHERE ev.event_type='race'
                  AND ev.population_status='confirmed_native_normal_race'
                  AND (e.finish_position BETWEEN 1 AND 89 OR e.finish_position IN (91,92))
            ), bad AS (
                SELECT DISTINCT race_id FROM starters
                WHERE identity_status!='official_race_ids_linked'
            )
            SELECT race_id,entry_id FROM starters
            WHERE race_id NOT IN (SELECT race_id FROM bad) AND distance_m!=400
        """).fetchall()
    expected_keys = set(expected)
    for frame in (entries, labels, states):
        keys = set(frame.select("race_id", "entry_id").iter_rows())
        assert keys == expected_keys, "entry key coverage differs from independent source SQL"
        assert frame.height == len(keys), "duplicate entry key"
    registry = json.loads((output / "feature_registry.json").read_text())
    feature_names = [item["feature_name"] for item in registry]
    assert len(feature_names) == len(set(feature_names))
    assert set(feature_names) <= set(states.columns)
    forbidden = {
        "finish_position",
        "finish_time_ms",
        "label_top3",
        "label_win",
        "order_key",
        "set_key",
        "target_eligible",
    }
    assert not (set(feature_names) & forbidden)
    for name in feature_names:
        if states.schema[name] in (pl.Float32, pl.Float64):
            assert not states.select(
                (pl.col(name).is_not_null() & ~pl.col(name).is_finite()).any()
            ).item(), name
    order_counts = Counter(orders["race_id"])
    set_counts = Counter(sets["race_id"])
    label_groups = labels.partition_by("race_id", as_dict=True)
    ranks_by_race = {}
    expected_orders, expected_sets, boundary_ties, tied_podiums = 0, 0, 0, 0
    for (race_id,), frame in label_groups.items():
        raw_column = (
            "finish_position_raw" if "finish_position_raw" in frame.columns else "finish_position"
        )
        normal = frame.filter(pl.col(raw_column).is_between(1, 89))
        horse_ranks = dict(normal.select("horse_id", raw_column).iter_rows())
        ranks_by_race[race_id] = horse_ranks
        counts = Counter(horse_ranks.values())
        remaining = 3
        n_orders, n_sets = 1, 1
        relevant_tie = False
        for _, group_count in sorted(counts.items()):
            if not remaining:
                break
            take = min(group_count, remaining)
            n_orders *= math.perm(group_count, take)
            n_sets *= math.comb(group_count, take)
            relevant_tie |= group_count > 1
            remaining -= take
        assert remaining == 0, f"incomplete podium: {race_id}"
        assert order_counts[race_id] == n_orders, f"order count: {race_id}"
        assert set_counts[race_id] == n_sets, f"set count: {race_id}"
        expected_orders += n_orders
        expected_sets += n_sets
        boundary_ties += n_sets > 1
        tied_podiums += relevant_tie
    seen = set()
    projected_sets = set()
    for row in orders.iter_rows(named=True):
        chosen = (row["first_horse_id"], row["second_horse_id"], row["third_horse_id"])
        assert len(set(chosen)) == 3
        ranks = ranks_by_race[row["race_id"]]
        chosen_ranks = [ranks[horse] for horse in chosen]
        assert chosen_ranks == sorted(chosen_ranks), "incompatible order"
        assert all(
            rank >= chosen_ranks[-1] for horse, rank in ranks.items() if horse not in chosen
        ), "omitted earlier finisher"
        key = (row["race_id"], ">".join(chosen))
        assert key not in seen
        seen.add(key)
        projected_sets.add((row["race_id"], "-".join(sorted(chosen))))
    actual_sets = set(sets.select("race_id", "set_key").iter_rows())
    assert actual_sets == projected_sets and sets.height == len(actual_sets)
    assert entries.height == 84583 and entries["race_id"].n_unique() == 8682
    assert expected_orders == 8721 and expected_sets == 8699
    assert boundary_ties == 17 and tied_podiums == 39
    ledger = json.loads((output / "run_ledger.json").read_text())
    assert ledger["model_fit_count"] == ledger["prediction_evaluation_count"] == 0
    return {
        "passed": True,
        "artifact_hashes_checked": checked_files,
        "independent_source_key_count": len(expected_keys),
        "races": 8682,
        "accepted_orders": expected_orders,
        "accepted_sets": expected_sets,
        "podium_tied_races": tied_podiums,
        "third_boundary_tied_races": boundary_ties,
        "feature_count": len(feature_names),
        "feature_and_label_keys_equal": True,
        "verification": "independent_SQL_keys_and_rank_constraints_plus_combinatorial_counts",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(verify(args.dataset), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
