"""Verify batch application against frozen single-record lookups and raw identities."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    a = module("history_verification_source", HERE / "analyze.py")
    summary = json.loads((OUT / "application_summary.json").read_text())
    for name, digest in summary["input_sha256"].items():
        assert a.S.A.sha(a.ROOT / name) == digest, name
    for name, digest in summary["raw_name_source_sha256"].items():
        assert a.S.A.sha(a.ROOT / name) == digest, name
    d = pd.read_parquet(OUT / "core_historical_records.parquet")
    alt = pd.read_parquet(OUT / "alternate_historical_records.parquet")
    original = pd.read_parquet(a.S.L.POP).set_index("row_key")
    for part in a.TARGETS:
        assert np.allclose(d[f"raw_{part}"], original.loc[d.row_key, part])
        assert np.allclose(
            d[f"adjusted_{part}"], d[f"raw_{part}"] + d[f"add_{part}"], equal_nan=True
        )
        complete = d[f"add_{part}"].notna()
        assert np.allclose(
            d.loc[complete, f"add_{part}"],
            d.loc[complete, [f"{term}_add_{part}" for term in ["moisture", "month", "gate"]]].sum(
                axis=1
            ),
        )
        assert d.loc[complete, f"adjusted_{part}"].gt(0).all()
    good = d[d.complete]
    assert np.allclose(good[[f"adjusted_{p}" for p in a.CORE]].sum(axis=1), good.adjusted_finish)
    assert np.allclose(good.adjusted_middle2 + good.adjusted_late, good.adjusted_last600)
    assert d.loc[~d.complete, "adjusted_finish"].isna().all()
    gates = pd.read_parquet(a.S.L.GATES)
    rosters = gates.groupby("race_key").horse_number.agg(lambda v: [int(x) for x in v])
    helpers = {
        "서울": module("frozen_seoul_lookup", a.SEOUL / "apply.py").SeoulSections(),
        "부산": module("frozen_busan_lookup", a.BUSAN / "apply.py").BusanSections(),
    }
    checked, max_error = 0, 0.0
    for ledger in [d, alt]:
        # Distinct observed conditions include missing cells and estimates outside fit cohorts.
        sample = ledger.drop_duplicates(
            ["meet", "distance_m", "band", "month", "gate_block", "gate_level"]
        )
        sample = sample.groupby(["meet", "distance_m"], group_keys=False).head(8)
        for row in sample.itertuples():
            result = helpers[row.meet].lookup(
                distance=int(row.distance_m),
                moisture=int(row.moisture),
                month=int(row.month),
                horse_number=int(row.horse_number),
                roster=rosters[row.race_key],
                as_of="2026-10-15",
                scope=row.scope,
            )
            assert result["gate_block"] == row.gate_block and result["gate_level"] == row.gate_level
            for part in a.TARGETS:
                expected = result["sections"].get(part, {}).get("total_add_seconds")
                if not row.raw_partition_valid:
                    expected = None
                actual = getattr(row, f"add_{part}")
                if expected is None:
                    assert pd.isna(actual)
                else:
                    error = abs(actual - expected)
                    max_error = max(max_error, error)
                    assert error < 1e-10
                checked += 1
    stats = pd.read_csv(OUT / "before_after_summary.csv")
    assert np.allclose(stats.adjusted_mean - stats.raw_mean, stats.delta_mean, atol=1e-8)
    best = pd.read_parquet(OUT / "horse_best_record_comparisons.parquet")
    selected = best.groupby(["meet", "section"], group_keys=False).head(10)
    nbest = 0
    for r in selected.itertuples():
        g = good[
            good.meet.eq(r.meet) & good.horse_id.eq(r.horse_id) & good.distance_m.eq(r.distance_m)
        ]
        old, new = f"raw_{r.section}", f"adjusted_{r.section}"
        old_set = set(g[g[old].sub(g[old].min()).abs().lt(1e-8)].row_key)
        new_set = set(g[g[new].sub(g[new].min()).abs().lt(1e-8)].row_key)
        assert r.changed_best == (not bool(old_set & new_set))
        nbest += 1
    assert alt.loc[~alt.raw_partition_valid, "adjusted_finish"].isna().all()
    for venue, folder in [("서울", a.SEOUL), ("부산", a.BUSAN)]:
        defs = pd.read_csv(folder / "outputs/section_definitions.csv")
        for (dist, scope), g in alt[alt.meet.eq(venue) & alt.complete].groupby(
            ["distance_m", "scope"]
        ):
            parts = defs[
                defs.distance_m.eq(dist) & defs.scope.eq(scope) & defs.partition
            ].section.tolist()
            assert np.allclose(g[[f"adjusted_{p}" for p in parts]].sum(axis=1), g.adjusted_finish)
    a.dump(
        OUT / "verification.json",
        dict(
            passed=True,
            core_rows=len(d),
            alternate_rows=len(alt),
            independent_single_lookup_targets=checked,
            max_single_lookup_error=max_error,
            independently_checked_horse_groups=nbest,
            input_hashes_preserved=True,
            raw_values_preserved=True,
            core_and_alternate_partition_identities=True,
            partial_values_not_labeled_complete=True,
            production_changed=False,
            prediction_validation=False,
        ),
    )
    print("verification passed", checked, max_error, nbest)


if __name__ == "__main__":
    main()
