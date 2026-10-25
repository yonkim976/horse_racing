"""Make small, explicit trial corrections from frozen descriptive estimates."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
CROSS = HERE.parent / "20261008_moisture_gate_seconds"
SPEC = importlib.util.spec_from_file_location("cross", CROSS / "analyze.py")
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)
BASE = A.PREV / "outputs/seconds_profiles.csv"
STATE = CROSS / "outputs/seconds_profiles.csv"
MOISTURE = A.L.PREVIOUS / "outputs/moisture_reference_preserved.csv"
MONTH = A.L.PREVIOUS / "outputs/monthly_candidate_table.csv"
POLICY = dict(
    version="gate_candidate_v1_20261008",
    status="trial_only",
    created_on="2026-10-08",
    available_from="2026-10-08",
    data_end={"서울": "2026-09-20", "부산": "2026-09-18"},
    base_fraction=0.30,
    state_fraction=0.15,
    shrink_k=100.0,
    base_cap_seconds=0.15,
    state_cap_seconds=0.05,
    total_gate_cap_seconds=0.20,
    default_period="all_mad4",
    recent_period="recent_mad4",
    evidence="descriptive estimates; rule-based shrinkage, not optimal or posterior estimates",
    production_changed=False,
    predictive_validation=False,
)


def block_for(n, mode):
    if mode == "number":
        assert n in [10, 12]
        return f"exact{n}"
    return "other_" + ("6to9" if n <= 9 else str(n) if n <= 12 else "13plus")


def side_for(ordinal, n):
    return A.SIDES[min(int(3 * (ordinal - 0.5) / n), 2)]


def cap_center(v, weights, cap):
    v = np.asarray(v, float)
    centered = v - np.average(v, weights=weights)
    scale = min(1.0, cap / max(float(np.max(abs(centered))), 1e-15))
    return centered * scale, scale, float(np.average(v, weights=weights))


def n_for(row, family):
    if row is None:
        return 0
    counts = json.loads(row.support)
    return counts[0]["rows"] if family == "number" else min(s["rows"] for s in counts)


def get_rows(frame, meet, dist, period, block, family, band=None):
    g = frame[
        frame.meet.eq(meet)
        & frame.distance_m.eq(dist)
        & frame.period.eq(period)
        & frame.block.eq(block)
        & frame.family.eq(family)
    ]
    if band is not None:
        g = g[g.band.eq(band)]
    assert not g.level.duplicated().any()
    return {r.level: r for r in g.itertuples()}


def build_table(population, base, state):
    records = []
    pairs = population.groupby(["meet", "distance_m"], observed=True)
    for (meet, dist), population_pair in pairs:
        for n in sorted(population_pair.n.unique()):
            n = int(n)
            for mode in ["group", "number"] if n in [10, 12] else ["group"]:
                block = block_for(n, mode)
                levels = [str(i) for i in range(1, n + 1)] if mode == "number" else A.SIDES
                weights = (
                    np.ones(n)
                    if mode == "number"
                    else np.array(
                        [sum(side_for(i, n) == side for i in range(1, n + 1)) for side in levels],
                        float,
                    )
                )
                for period in ["all_mad4", "recent_mad4"]:
                    b = get_rows(base, meet, dist, period, block, mode)
                    base_available = all(level in b and b[level].estimable for level in levels)
                    raw_base = (
                        np.array([b[level].effect_seconds for level in levels])
                        if base_available
                        else np.zeros(len(levels))
                    )
                    nb = np.array([n_for(b.get(level), mode) for level in levels])
                    base_uncentered = (
                        POLICY["base_fraction"] * nb / (nb + POLICY["shrink_k"]) * raw_base
                    )
                    base_effect, base_scale, base_center = cap_center(
                        base_uncentered, weights, POLICY["base_cap_seconds"]
                    )
                    for band in A.BANDS:
                        s = get_rows(state, meet, dist, period, block, mode, band)
                        state_available = base_available and all(
                            level in s and s[level].estimable for level in levels
                        )
                        ns = np.array([n_for(s.get(level), mode) for level in levels])
                        raw_state = (
                            np.array([s[level].effect_seconds for level in levels])
                            if state_available
                            else raw_base.copy()
                        )
                        delta_uncentered = (
                            POLICY["state_fraction"]
                            * ns
                            / (ns + POLICY["shrink_k"])
                            * (raw_state - raw_base)
                        )
                        state_effect, state_scale, state_center = cap_center(
                            delta_uncentered, weights, POLICY["state_cap_seconds"]
                        )
                        for i, level in enumerate(levels):
                            br, sr = b.get(level), s.get(level)
                            status = (
                                "state_blend"
                                if state_available
                                else "base_only"
                                if base_available
                                else "neutral_unavailable"
                            )
                            records.append(
                                dict(
                                    meet=meet,
                                    distance_m=int(dist),
                                    field_size=n,
                                    mode=mode,
                                    block=block,
                                    band=band,
                                    period=period,
                                    level=level,
                                    base_available=bool(base_available),
                                    state_available=bool(state_available),
                                    status=status,
                                    base_n=int(nb[i]),
                                    state_n=int(ns[i]),
                                    raw_base_effect=float(br.effect_seconds)
                                    if br is not None and br.estimable
                                    else None,
                                    raw_state_effect=float(sr.effect_seconds)
                                    if sr is not None and sr.estimable
                                    else None,
                                    raw_base_se=float(br.se)
                                    if br is not None and br.estimable
                                    else None,
                                    raw_state_se=float(sr.se)
                                    if sr is not None and sr.estimable
                                    else None,
                                    base_q=float(br.q) if br is not None else None,
                                    state_q=float(sr.q) if sr is not None else None,
                                    base_uncentered=float(base_uncentered[i]),
                                    state_uncentered=float(delta_uncentered[i]),
                                    base_center=base_center,
                                    state_center=state_center,
                                    base_cap_scale=base_scale,
                                    state_cap_scale=state_scale,
                                    base_add_seconds=-float(base_effect[i]),
                                    state_add_seconds=-float(state_effect[i]),
                                    gate_add_seconds=-float(base_effect[i] + state_effect[i]),
                                    group_weight=float(weights[i]),
                                )
                            )
    return pd.DataFrame(records)


def main():
    OUT.mkdir(exist_ok=True)
    sources = [
        BASE,
        STATE,
        MOISTURE,
        MONTH,
        A.L.POP,
        A.L.GATES,
        A.L.LEDGER,
        CROSS / "analyze.py",
        A.PREV / "analyze.py",
        A.L.PREVIOUS / "analyze.py",
        HERE / "PLAN.md",
        HERE / "build.py",
        HERE / "apply.py",
    ]
    hashes = {str(p.relative_to(ROOT)): A.sha(p) for p in sources}
    population, _ = A.load()
    base = pd.read_csv(BASE, dtype={"level": str}).query(
        "kind=='gate' and adjustment=='dual' and metric=='finish'"
    )
    state = pd.read_csv(STATE, dtype={"level": str}).query("adjustment=='dual'")
    table = build_table(population, base, state)
    table.to_csv(OUT / "gate_correction_lookup.csv", index=False)
    moisture = pd.read_csv(MOISTURE)
    moisture.to_csv(OUT / "moisture_reference.csv", index=False)
    wide = pd.read_csv(MONTH)
    month = wide.melt(
        id_vars=["지역", "거리m"], var_name="month", value_name="month_candidate_add"
    ).rename(columns={"지역": "meet", "거리m": "distance_m"})
    month["month"] = month.month.str.replace("월", "").astype(int)
    month.to_csv(OUT / "month_candidate_reference.csv", index=False)
    config = POLICY | dict(input_sha256=hashes)
    A.dump(OUT / "config.json", config)
    spec = importlib.util.spec_from_file_location("apply_trial", HERE / "apply.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    normalizer = helper.Normalizer(OUT)
    ledger = normalizer.apply_population(population, as_of="2026-10-08")
    ledger.to_parquet(OUT / "runner_trial_normalization.parquet", index=False)
    summary = dict(
        policy=POLICY,
        lookup_rows=len(table),
        default_rows=int(table.period.eq("all_mad4").sum()),
        default_nonzero=int(
            (table.period.eq("all_mad4") & table.gate_add_seconds.abs().gt(1e-12)).sum()
        ),
        default_status_counts=table[table.period.eq("all_mad4")].status.value_counts().to_dict(),
        roster_starts=len(ledger),
        gate_nonzero_starts=int(ledger.gate_add_seconds.abs().gt(1e-12).sum()),
        supported_total_records=int(ledger.moisture_gate_finish.notna().sum()),
        max_gate_seconds=float(table.gate_add_seconds.abs().max()),
        input_sha256=hashes,
    )
    A.dump(OUT / "summary.json", summary)
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in ["input_sha256", "policy"]},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
