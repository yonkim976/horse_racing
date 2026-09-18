"""Export a new immutable declaration dataset at an explicit observed cutoff."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

from horse_racing.services.jeju_pregame_store import PregameStore, digest, replay, timestamp_ms


def export(root: Path, cutoff: str, output: Path, dates=None):
    cutoff_ms = timestamp_ms(cutoff)
    store = PregameStore(root)
    result = replay(store, cutoff_ms, race_dates=dates)
    output.mkdir(parents=True, exist_ok=False)
    (output / "replay.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    entries = []
    for race in result["races"]:
        for horse in race["runners"]:
            entries.append(
                dict(
                    race_date=race["race_date"],
                    race_number=race["race_number"],
                    scheduled_start_at=race["scheduled_start_at"],
                    cutoff_at_ms=cutoff_ms,
                    declaration_complete=race["declaration_complete"],
                    declared_count=race["declared_count"],
                    listed_count=race["listed_count"],
                    eligible_count=len(race["eligible_numbers"]),
                    **{k: v for k, v in horse.items() if k != "sources"},
                    sources_json=json.dumps(horse["sources"], ensure_ascii=False, sort_keys=True),
                    issues_json=json.dumps(race["issues"], ensure_ascii=False),
                    track_json=json.dumps(race["track"], ensure_ascii=False),
                )
            )
    frame = (
        pl.DataFrame(entries, infer_schema_length=None)
        if entries
        else pl.DataFrame(
            schema={"race_date": pl.String, "race_number": pl.Int64, "horse_id": pl.String}
        )
    )
    frame.write_parquet(output / "declarations.parquet")
    (output / "export.json").write_text(
        json.dumps(
            dict(
                root=str(root.resolve()),
                cutoff=cutoff,
                race_dates=dates,
                rows=len(entries),
                races=len(result["races"]),
                purpose="observed declaration replay; not training features or predictions",
                observation_ids=[p["observation_id"] for p in store.observations(cutoff_ms)],
            ),
            indent=2,
        )
        + "\n"
    )
    manifest = {p.name: digest(p.read_bytes()) for p in sorted(output.iterdir()) if p.is_file()}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path("data/research/jeju_native_pregame_observations_v1")
    )
    parser.add_argument("--cutoff", required=True, help="ISO time with explicit offset")
    parser.add_argument(
        "--output", type=Path, required=True, help="New directory; refuses overwrite"
    )
    parser.add_argument("--date", action="append")
    args = parser.parse_args()
    result = export(args.root, args.cutoff, args.output, args.date)
    print(json.dumps(dict(races=len(result["races"]), output=str(args.output)), indent=2))


if __name__ == "__main__":
    main()
