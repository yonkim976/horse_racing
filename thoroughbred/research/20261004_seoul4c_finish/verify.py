"""Independently verify retained checkpoint calculations and benchmark tables."""

import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"


def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as stream:
        for block in iter(lambda: stream.read(4194304), b""):
            h.update(block)
    return h.hexdigest()


def main():
    s = json.loads((OUT / "summary.json").read_text())
    d = pd.read_parquet(OUT / "runner_4c_analysis.parquet")
    assert len(d) == s["n_recent"] == 7897
    assert d.source_key.nunique() == s["races_recent"] == 743
    assert d.date.nunique() == s["days_recent"] == 269
    assert not d.row_key.duplicated().any()
    identities = [
        (d.finish, d.c4 + d.closing4c),
        (d.closing4c, d.c4tog1 + d.late),
        (d.c4tog1, d.g1 - d.c4),
        (d.late, d.finish - d.g1),
        (d.gain4tofin, d.gain4to1 + d.gain1tofin),
        (d.gap4c - d.gapfin_same_leader, d.recovered_seconds),
    ]
    for left, right in identities:
        assert np.allclose(left, right, rtol=0, atol=1e-7)
    assert not d.duplicated(["source_key", "p4"]).any()
    assert d.gap4c.min() >= -1e-7
    sorted_times = d.sort_values(["source_key", "p4"])
    assert sorted_times.groupby("source_key").c4.diff().dropna().ge(-1e-7).all()
    assert ((d.p4 >= 1) & (d.p4 <= d.n)).all()
    assert ((d.p1 >= 1) & (d.p1 <= d.n)).all()
    v = pd.read_csv(OUT / "temporal_validation.csv")
    assert (pd.to_datetime(v.train_end) < pd.to_datetime(v.test_start)).all()
    assert v.test_n.sum() == len(d)
    b = pd.read_csv(OUT / "estimated_benchmarks.csv")
    assert len(b) == 150 and not b.duplicated(["grade", "band", "part"]).any()
    assert (b.p10 <= b.p20).all() and (b.p20 <= b["median"]).all()
    assert (b["median"] <= b.p80).all() and (b.p80 <= b.p90).all()
    sums = b.pivot(index=["grade", "band"], columns="part", values="mean")
    assert np.allclose(sums.closing4c, sums.c4tog1 + sums.late)
    refs = pd.read_parquet(OUT / "dry_reference.parquet")
    effects = pd.read_csv(OUT / "state_effects.csv").set_index(["grade", "band", "part"])
    checks = 0
    for r in b.itertuples():
        a = refs.loc[refs.grade.eq(r.grade), r.part].to_numpy()
        values = np.round(a + effects.loc[(r.grade, r.band, r.part), "effect_seconds"], 9)
        q = np.round(np.quantile(values, [0.1, 0.2, 0.5, 0.8, 0.9]), 9)
        assert np.allclose(q, [r.p10, r.p20, r.median, r.p80, r.p90], atol=1e-7)
        assert abs(values.mean() - r.mean) < 1e-7
        masks = [
            values <= q[1] + 1e-7,
            (values > q[1] + 1e-7) & (values < q[3] - 1e-7),
            values >= q[3] - 1e-7,
        ]
        for name, mask in zip(["fast20", "middle60", "slow20"], masks, strict=True):
            assert mask.sum() == getattr(r, name + "_n")
            if mask.any():
                assert abs(values[mask].mean() - getattr(r, name + "_mean")) < 1e-7
        checks += 12
    db = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
    assert sha(db) == s["core_db_sha256"]
    with duckdb.connect(str(db), read_only=True) as con:
        con.register("selected", d[["date_key", "race_no", "horse_id", "c4", "p4"]])
        matched, mismatch = con.execute("""
            SELECT count(*), count(*) FILTER (WHERE
              (s.measure_kind='cumulative_time' AND abs(s.time_ms/1000.0-d.c4)>0.000001)
               OR (s.measure_kind='passing_order' AND s.passing_order<>d.p4))
            FROM selected d JOIN section_measurements_api s
            ON s.meet=1 AND s.race_date=d.date_key AND s.race_no=d.race_no
              AND s.horse_id=d.horse_id AND s.point_code='4C'
            WHERE s.measure_kind IN ('cumulative_time','passing_order')
        """).fetchone()
    assert mismatch == 0
    assert matched == 2 * len(d)
    for path, key in [
        (
            HERE.parent / "20261003_sectional_pace_moisture/outputs/population.parquet",
            "parent_sha256",
        ),
        (HERE.parent / "20261002_gate_lateral_bias/outputs/runners.parquet", "history_sha256"),
    ]:
        assert sha(path) == s[key]
    for raw in s["raw_sources"]:
        assert sha(ROOT / raw["path"]) == raw["sha256"]
    result = dict(
        status="passed",
        recent_rows=len(d),
        arithmetic_checks=len(d) * len(identities),
        benchmark_stat_checks=checks,
        independent_db_mismatches=mismatch,
        raw_verified_rows=sum(r["checked_rows"] for r in s["raw_sources"]),
        source_hashes_unchanged=True,
        chronological_folds=3,
    )
    (OUT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
