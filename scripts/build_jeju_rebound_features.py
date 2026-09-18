"""Build new features without modifying sealed historical artifacts."""

import json
import shutil
import sqlite3
from pathlib import Path

import polars as pl

from horse_racing.analysis.jeju_rebound_features import DEFINITIONS, FEATURES, build_features
from scripts.build_jeju_context_features import DATA, DB, H3, _history_rows, _sha, _source_rows

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/jeju_native_rebound_features_v1_20260916"


def main():
    OUT.mkdir(exist_ok=False)
    entries = pl.read_parquet(DATA / "entries.parquet").filter(
        pl.col("event_date").dt.year() <= 2025
    )
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        source = _source_rows(db)
    history = _history_rows(
        entries,
        pl.read_parquet(DATA / "labels.parquet"),
        source,
        pl.read_parquet(DATA / "horse_states.parquet"),
    )
    distances = dict(entries.select("entry_id", "distance_m").iter_rows())
    for r in history:
        r["distance_m"] = distances[r["entry_id"]]
    rows, lineage = build_features(entries.to_dicts(), history)
    frame = pl.DataFrame(rows)
    frame.write_parquet(OUT / "features.parquet")
    lin = pl.DataFrame(lineage)
    lin.write_parquet(OUT / "lineage.parquet")
    assert len(frame) == 79731 and frame["entry_id"].n_unique() == 79731
    assert lin.filter(pl.col("max_history_date") > pl.col("cutoff_date")).is_empty()
    ev = frame.join(
        entries.filter(pl.col("event_date").dt.year() == 2025).select("entry_id"),
        on="entry_id",
        how="semi",
    )
    report = dict(
        rows=len(frame),
        features=FEATURES,
        definitions=DEFINITIONS,
        coverage_2025={f: ev[f].is_finite().sum() for f in FEATURES},
        source_sha256=dict(
            database=_sha(DB), dataset=_sha(DATA / "manifest.json"), h3=_sha(H3 / "manifest.json")
        ),
        cutoff_days=2,
        shrinkage_pseudocount=3,
        trained_parameters=0,
        model_predictions_2026=0,
    )
    (OUT / "build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (OUT / "reproduce").mkdir()
    for p in [
        Path(__file__),
        ROOT / "src/horse_racing/analysis/jeju_rebound_features.py",
        ROOT / "tests/test_jeju_rebound_features.py",
    ]:
        shutil.copy2(p, OUT / "reproduce" / p.name)
    manifest = {str(p.relative_to(OUT)): _sha(p) for p in sorted(OUT.rglob("*")) if p.is_file()}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
