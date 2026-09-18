"""Build a separate immutable trial-detail table from canonical checkpoints."""

import json
import shutil
import sqlite3
from pathlib import Path

import polars as pl

from horse_racing.analysis.jeju_trial_features import DEFINITIONS, FEATURES, build_features
from scripts.build_jeju_context_features import DATA, DB, ROOT, _date, _sha

OUT = ROOT / "data/research/jeju_native_trial_features_v1_20260916"


def load_trials():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    trials = {}
    for r in c.execute("""select e.id entry_id,e.hr_no horse_id,e.finish_time_ms,e.record_status,
       e.segment_quality,e.source_row_id,v.event_date,v.distance_m from entry e
       join event v on v.id=e.event_id where v.event_type='trial' and v.event_date<='20251231'
       and e.hr_no is not null and e.breed_status='native_confirmed' """):
        row = dict(r)
        row["event_date"] = _date(row["event_date"])
        row["sections"] = {}
        trials[row["entry_id"]] = row
    for r in c.execute("""select s.* from section_checkpoint s join entry e on e.id=s.entry_id
       join event v on v.id=e.event_id where v.event_type='trial' and v.event_date<='20251231'
       and s.section_code in ('S1F','G1F','G3F') """):
        if r["entry_id"] in trials:
            assert r["section_code"] not in trials[r["entry_id"]]["sections"]
            trials[r["entry_id"]]["sections"][r["section_code"]] = dict(r)
    c.close()
    return list(trials.values())


def main():
    OUT.mkdir(exist_ok=False)
    entries = pl.read_parquet(DATA / "entries.parquet").filter(
        pl.col("event_date").dt.year() <= 2025
    )
    trials = load_trials()
    rows, lineage = build_features(entries.to_dicts(), trials)
    frame = pl.DataFrame(rows)
    lin = pl.DataFrame(lineage, infer_schema_length=None)
    assert len(frame) == 79731 and frame["entry_id"].n_unique() == 79731
    assert lin.filter(pl.col("max_source_date") > pl.col("cutoff_date")).is_empty()
    frame.write_parquet(OUT / "features.parquet")
    lin.write_parquet(OUT / "lineage.parquet")
    with (OUT / "source_trials.jsonl").open("w") as f:
        for r in trials:
            f.write(json.dumps(r, ensure_ascii=False, default=str, sort_keys=True) + "\n")
    ev = frame.join(
        entries.filter(pl.col("event_date").dt.year() == 2025).select("entry_id"),
        on="entry_id",
        how="semi",
    )
    report = dict(
        rows=len(frame),
        features=FEATURES,
        definitions=DEFINITIONS,
        source_trials=len(trials),
        source_trial_distance_counts={
            str(d): sum(t["distance_m"] == d for t in trials)
            for d in sorted({t["distance_m"] for t in trials})
        },
        coverage_2025={k: int(ev[k].is_finite().sum()) for k in FEATURES},
        source_sha256=dict(database=_sha(DB), dataset_manifest=_sha(DATA / "manifest.json")),
        policy="T-2 cutoff; only800m trials. "
        "Last3 valid finish records within365d for sections/trends. "
        "Canonical S1F cumulative200m, G1F closing200m, G3F closing600m; exact geometry only. "
        "No name-conflict rescue. Trial performance kept separate from race performance.",
        predictions_2026=0,
    )
    (OUT / "build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (OUT / "reproduce").mkdir()
    for p in [
        Path(__file__),
        ROOT / "src/horse_racing/analysis/jeju_trial_features.py",
        ROOT / "tests/test_jeju_trial_features.py",
    ]:
        shutil.copy2(p, OUT / "reproduce" / p.name)
    manifest = {str(p.relative_to(OUT)): _sha(p) for p in sorted(OUT.rglob("*")) if p.is_file()}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
