"""Verify raw observation integrity and an exported as-of declaration dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

from horse_racing.parsers.jeju_pregame import VERSION, parse_page
from horse_racing.services.jeju_pregame_store import (
    PregameStore,
    canonical,
    digest,
    replay,
    timestamp_ms,
)


def verify(export_dir):
    meta = json.loads((export_dir / "export.json").read_text())
    for name, value in json.loads((export_dir / "manifest.json").read_text()).items():
        assert digest((export_dir / name).read_bytes()) == value, name
    store = PregameStore(Path(meta["root"]))
    cutoff = timestamp_ms(meta["cutoff"])
    observations = store.observations(cutoff)
    assert [p["observation_id"] for p in observations] == meta["observation_ids"]
    parsed = 0
    for p in observations:
        if p["parser_version"] == VERSION and p["parsed"] is not None:
            raw = (store.root / "observations" / p["observation_id"] / "raw.html").read_bytes()
            assert parse_page(p["kind"], raw, p["encoding"]) == p["parsed"]
            parsed += 1
    computed = replay(store, cutoff, race_dates=meta["race_dates"])
    saved = json.loads((export_dir / "replay.json").read_text())
    assert canonical(computed) == canonical(saved)
    entries = pl.read_parquet(export_dir / "declarations.parquet")
    assert len(entries) == meta["rows"]
    if len(entries):
        assert entries.select(
            pl.struct("race_date", "race_number", "horse_id").n_unique()
        ).item() == len(entries)
    n = 0
    for race in saved["races"]:
        if race["declaration_complete"]:
            assert len(race["runners"]) == race["declared_count"] == race["listed_count"]
        for horse in race["runners"]:
            matches = entries.filter(
                (pl.col("race_date") == race["race_date"])
                & (pl.col("race_number") == race["race_number"])
                & (pl.col("horse_id") == horse["horse_id"])
            )
            assert len(matches) == 1
            entry = matches.row(0, named=True)
            assert json.loads(entry["sources_json"]) == horse["sources"]
            for key, value in horse.items():
                if key != "sources":
                    assert entry[key] == value
            for source in horse["sources"].values():
                assert source["known_at_ms"] <= cutoff
                assert source["observed_at_ms"] <= source["known_at_ms"]
            assert timestamp_ms(race["scheduled_start_at"]) > cutoff
            n += 1
    assert n == len(entries)
    return dict(
        passed=True,
        observations_verified=len(observations),
        current_parser_pages_reparsed=parsed,
        races=meta["races"],
        rows=n,
        exact_cutoff_replay=True,
        predictions=0,
        model_fits=0,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.export_dir), indent=2))


if __name__ == "__main__":
    main()
