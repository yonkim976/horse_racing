"""Check the trial policy independently, including full-roster application behavior."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("builder", HERE / "build.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
SPEC2 = importlib.util.spec_from_file_location("application", HERE / "apply.py")
H = importlib.util.module_from_spec(SPEC2)
SPEC2.loader.exec_module(H)


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    assert all(B.A.sha(B.ROOT / name) == digest for name, digest in summary["input_sha256"].items())
    table = pd.read_csv(OUT / "gate_correction_lookup.csv", dtype={"level": str})
    ledger = pd.read_parquet(OUT / "runner_trial_normalization.parquet")
    population, _ = B.A.load()
    assert len(ledger) == 151074 and len(table) == 8620
    assert not table.duplicated(H.KEYS).any() and not ledger.row_key.duplicated().any()
    base = pd.read_csv(B.BASE, dtype={"level": str}).query(
        "kind=='gate' and adjustment=='dual' and metric=='finish'"
    )
    state = pd.read_csv(B.STATE, dtype={"level": str}).query("adjustment=='dual'")
    old = pd.read_csv(B.MOISTURE)
    copy = pd.read_csv(OUT / "moisture_reference.csv")
    pd.testing.assert_frame_equal(old, copy, check_dtype=False, atol=1e-12)
    model_index = base.set_index(["meet", "distance_m", "period", "block", "family", "level"])
    state_index = state.set_index(
        ["meet", "distance_m", "period", "block", "family", "level", "band"]
    )
    groups = 0
    maxmean = 0.0
    for key, g in table.groupby(
        ["meet", "distance_m", "field_size", "mode", "block", "band", "period"], sort=False
    ):
        meet, dist, n, mode, block, band, period = key
        e = g.raw_base_effect.to_numpy() if g.base_available.all() else np.zeros(len(g))
        es = g.raw_state_effect.to_numpy() if g.state_available.all() else e
        a = 0.30 * g.base_n.to_numpy() / (g.base_n.to_numpy() + 100) * e
        d = 0.15 * g.state_n.to_numpy() / (g.state_n.to_numpy() + 100) * (es - e)
        assert np.allclose(a, g.base_uncentered, atol=1e-12)
        assert np.allclose(d, g.state_uncentered, atol=1e-12)
        w = g.group_weight.to_numpy()
        if mode == "number":
            assert len(g) == n and np.allclose(w, 1)
        else:
            expected = {
                side: sum(
                    ["inner", "middle", "outer"][min(int(3 * (i - 0.5) / n), 2)] == side
                    for i in range(1, n + 1)
                )
                for side in ["inner", "middle", "outer"]
            }
            assert np.allclose(w, g.level.map(expected))
        for values, col, cap in [(a, "base_add_seconds", 0.15), (d, "state_add_seconds", 0.05)]:
            centered = values - np.sum(values * w) / sum(w)
            denominator = max(abs(centered).max(), 1e-15)
            expected = -centered * min(1.0, cap / denominator)
            assert np.allclose(expected, g[col], atol=1e-12)
            mean = abs(np.sum(g[col] * w) / sum(w))
            maxmean = max(maxmean, float(mean))
            assert mean < 1e-12 and g[col].abs().max() <= cap + 1e-12
        assert np.allclose(g.gate_add_seconds, g.base_add_seconds + g.state_add_seconds, atol=1e-12)
        assert g.gate_add_seconds.abs().max() <= 0.20 + 1e-12
        for r in g.itertuples():
            bkey = (meet, dist, period, block, mode, r.level)
            if bkey in model_index.index:
                br = model_index.loc[bkey]
                if br.estimable:
                    assert abs(r.raw_base_effect - br.effect_seconds) < 1e-12
                counts = json.loads(br.support)
                assert r.base_n == (
                    counts[0]["rows"] if mode == "number" else min(s["rows"] for s in counts)
                )
            skey = bkey + (band,)
            if skey in state_index.index:
                sr = state_index.loc[skey]
                if sr.estimable:
                    assert abs(r.raw_state_effect - sr.effect_seconds) < 1e-12
        groups += 1
    assert table.loc[~table.base_available, "gate_add_seconds"].eq(0).all()
    assert table.loc[~table.state_available, "state_add_seconds"].eq(0).all()
    assert (table.gate_add_seconds.ne(0) & table.base_q.gt(0.05)).any()
    assert np.allclose(
        ledger.moisture_gate_finish,
        ledger.finish + ledger.moisture_add_seconds + ledger.gate_add_seconds,
        equal_nan=True,
    )
    assert np.allclose(
        ledger.moisture_month_gate_finish,
        ledger.moisture_gate_finish + ledger.month_candidate_add,
        equal_nan=True,
    )
    assert (
        ledger.loc[
            ~ledger.moisture_supported,
            ["moisture_only_finish", "moisture_gate_finish", "moisture_month_gate_finish"],
        ]
        .isna()
        .all()
        .all()
    )
    norm = H.Normalizer(OUT)
    gates = pd.read_parquet(B.A.L.GATES)
    rosters = gates.groupby("race_key").horse_number.agg(list).to_dict()
    moisture_values = population.set_index("row_key").moisture
    sample = ledger.sample(n=350, random_state=20261008)
    single_checks = 0
    for r in sample.itertuples():
        kwargs = dict(
            meet=r.meet,
            distance=int(r.distance_m),
            finish=float(r.finish),
            moisture=float(moisture_values.loc[r.row_key]),
            record_date=r.date,
            horse_number=int(r.horse_number),
            roster=rosters[r.race_key],
            as_of="2026-10-08",
        )
        a = norm.normalize_record(**kwargs)
        b = norm.normalize_record(**kwargs, include_month=True)
        assert abs(a["gate_add_seconds"] - r.gate_add_seconds) < 1e-12
        if r.moisture_supported:
            assert abs(a["normalized_finish"] - r.moisture_gate_finish) < 1e-10
            assert abs(b["normalized_finish"] - r.moisture_month_gate_finish) < 1e-10
            off = norm.normalize_record(**kwargs, gate_strength=0.0)
            half = norm.normalize_record(**kwargs, gate_strength=0.5)
            assert abs(off["normalized_finish"] - r.moisture_only_finish) < 1e-10
            assert (
                abs(half["normalized_finish"] - (r.moisture_only_finish + 0.5 * r.gate_add_seconds))
                < 1e-10
            )
        else:
            assert a["normalized_finish"] is None
        single_checks += 1
    bad = [
        dict(as_of="2026-10-07"),
        dict(record_date="2026-10-09"),
        dict(roster=[1, 1, 2]),
        dict(horse_number=99),
        dict(finish=-1),
        dict(moisture=0),
        dict(gate_strength=1.1),
        dict(meet="영천"),
    ]
    valid = dict(
        meet="서울",
        distance=1600,
        finish=100.0,
        moisture=3.0,
        record_date="2026-09-19",
        horse_number=10,
        roster=list(range(1, 11)),
        as_of="2026-10-08",
    )
    for change in bad:
        try:
            norm.normalize_record(**(valid | change))
        except ValueError:
            pass
        else:
            raise AssertionError(change)
    # Cancellation/gapped numbers use relative groups, never exact-number rows.
    gapped = norm.gate("서울", 1200, "건조", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12], 12)
    assert gapped["gate_mode"] == "group" and gapped["gate_level"] == "outer"
    x = norm.gate("서울", 2300, "건조", list(range(1, 11)), 10)
    assert x["gate_add_seconds"] == 0 and x["gate_status"] == "neutral_unavailable"
    result = dict(
        passed=True,
        lookup_rows_checked=len(table),
        policy_vectors_checked=groups,
        max_weighted_mean_error_seconds=maxmean,
        single_vs_batch_records_checked=single_checks,
        invalid_input_cases_checked=len(bad),
        roster_gap_case_checked=True,
        moisture_preserved=True,
        source_hashes_unchanged=True,
        production_changed=False,
        predictive_validation=False,
    )
    B.A.dump(OUT / "verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
