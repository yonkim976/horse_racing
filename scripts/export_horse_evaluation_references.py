"""Export frozen, prior-year research references for the read-only web evaluator.

Run from the repository root. This does not fit models or connect to a database.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "thoroughbred/research"
DESTINATION = ROOT / "src/horse_racing/web/data/horse_evaluation_v1.json"


def main() -> None:
    raw = RESEARCH / "20261003_baseline_v1/outputs/record_references.csv"
    moist = RESEARCH / "20261003_pace_gate_moisture_v2/outputs/record_references.csv"
    effects = RESEARCH / "20261003_pace_gate_moisture_v2/outputs/effects.parquet"
    payload: dict = {
        "version": "horse_profile_v1_20261008",
        "sources": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (raw, moist, effects)
        },
    }
    for name, path in (("raw", raw), ("moist", moist)):
        frame = pl.read_csv(path)
        assert frame.filter(pl.col("trained_through") >= pl.col("source_year")).is_empty()
        payload[name] = {
            f"{r['meet']}:{r['source_year']}:{r['result_distance']}": [r["median"], r["scale"]]
            for r in frame.iter_rows(named=True)
        }
    frame = pl.read_parquet(effects)
    cells = frame.group_by("meet", "year", "distance_m", "band").agg(
        pl.col("correction_seconds").min().alias("low"),
        pl.col("correction_seconds").max().alias("high"),
        pl.col("supported").n_unique().alias("support_values"),
        pl.col("supported").first(),
        pl.col("environment_trained_through").max().alias("trained_through"),
    )
    assert cells.filter((pl.col("high") - pl.col("low")).abs() > 1e-10).is_empty()
    assert cells.filter(pl.col("support_values") != 1).is_empty()
    supported = cells.filter(pl.col("supported"))
    assert supported.filter(pl.col("trained_through") >= pl.col("year")).is_empty()
    payload["corrections"] = {
        f"{r['meet']}:{r['year']}:{r['distance_m']}:{r['band']}": r["low"]
        for r in supported.iter_rows(named=True)
    }
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    print(f"Exported {DESTINATION.relative_to(ROOT)} ({DESTINATION.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
