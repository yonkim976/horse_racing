"""Retrospective detached-finish sensitivity; fixed local sources, no production writes."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
PREV = HERE.parent / "20261008_section_normalization_candidate_v1"
SPEC = importlib.util.spec_from_file_location("section_sensitivity_source", PREV / "analyze.py")
N = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(N)
A, L, OLD = N.A, N.L, N.OLD
PARTS = ["early", "last600", "late", "finish"]
VARIANTS = ["baseline", "tail25", "tail30"]
N.PARTS = PARTS
ORIGINAL_SPECS = N.specs_for
MOIST_WEIGHTS = {}


def dump(path, data):
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def classify(g):
    """Use the complete original roster, independent of subsequent quality filters."""
    g = g.copy()
    group = g.groupby("race_key").finish
    g["race_winner"] = group.transform("min")
    g["race_median"] = group.transform("median")
    g["abs_deviation"] = abs(g.finish - g.race_median)
    g["race_mad"] = g.groupby("race_key").abs_deviation.transform("median")
    g["robust_sigma"] = 1.4826 * g.race_mad
    g["time_rank"] = group.rank(method="min")
    g["bottom_quarter"] = g.time_rank > g.n - np.ceil(g.n / 4)
    g["winner_gap"] = g.finish - g.race_winner
    g["median_gap"] = g.finish - g.race_median
    g["winner_floor"] = np.maximum(3.0, 0.04 * g.race_winner)
    for name, z in [("tail20", 2.0), ("tail25", 2.5), ("tail30", 3.0)]:
        threshold = np.maximum.reduce(
            [np.full(len(g), 2.0), 0.02 * g.race_median, z * g.robust_sigma]
        )
        g[name + "_median_floor"] = threshold
        g[name] = g.bottom_quarter & g.winner_gap.gt(g.winner_floor) & g.median_gap.gt(threshold)
    g["leader36"] = g.winner_gap.gt(3.6)
    g["leader10"] = g.winner_gap.gt(10.0)
    # A tied last position is intentionally not arbitrarily broken.
    g["last_place"] = g.time_rank.eq(group.transform("count"))
    order = g.sort_values(["race_key", "finish", "horse_number"]).copy()
    gap = order.groupby("race_key").finish.diff().fillna(0)
    floor = np.maximum.reduce(
        [np.ones(len(order)), 0.01 * order.race_median, 1.5 * order.robust_sigma]
    )
    split = order.bottom_quarter & gap.gt(floor)
    order["adjacent_tail"] = split.groupby(order.race_key).cummax()
    g["adjacent_tail"] = order.adjacent_tail.reindex(g.index)
    g["row_key"] = (
        g.meet.map({1: "서울", 3: "부산"})
        + ":"
        + g.date.str.replace("-", "")
        + ":"
        + g.race_no.astype(str)
        + ":"
        + g.horse_id
    )
    return g.drop(columns="abs_deviation")


def specs_for(d, kind):
    x, labels, specs = ORIGINAL_SPECS(d, kind)
    if kind != "month":
        return x, labels, specs
    fixed = MOIST_WEIGHTS[(str(d.meet.iloc[0]), int(d.distance_m.iloc[0]))]
    available = set(float(v) for v in d.moisture.unique())
    columns = {
        float(s.rsplit(":", 1)[1]): i
        for i, s in enumerate(labels)
        if s.startswith("control:moisture:")
    }
    for band, values in fixed.items():
        if band == "건조":
            continue
        vector = np.zeros(len(labels))
        defined = set(values).issubset(available) and set(fixed["건조"]).issubset(available)
        for sign, shares in [(1, values), (-1, fixed["건조"])]:
            for level, weight in shares.items():
                if level in columns:
                    vector[columns[level]] += sign * weight
        groups = [d[d.band.eq(b)] for b in [band, "건조"]]
        support = [
            dict(
                rows=len(s),
                races=int(s.race_key.nunique()),
                days=int(s.date.nunique()),
                years=int(s.year.nunique()),
            )
            for s in groups
        ]
        specs.append(
            (
                vector,
                dict(
                    family="moisture",
                    block="fixed_band_mix",
                    level=band,
                    support=support,
                    contrast_defined=defined,
                    supported=bool(
                        defined and all(s["races"] >= 50 and s["days"] >= 20 for s in support)
                    ),
                ),
            )
        )
    return x, labels, specs


def descriptions(d):
    rows, paired = [], []
    variants = dict(baseline=np.ones(len(d), bool))
    variants.update(
        {
            name: ~d[name].to_numpy()
            for name in [
                "tail20",
                "tail25",
                "tail30",
                "leader36",
                "leader10",
                "last_place",
                "adjacent_tail",
            ]
        }
    )
    rng = np.random.default_rng(20261008)
    for (meet, dist), frame in d.groupby(["meet", "distance_m"], observed=True):
        base_races = frame.groupby("race_key")[PARTS].mean()
        dates = frame.groupby("race_key").date.first()
        for variant, mask in variants.items():
            s = frame[mask[frame.index]]
            for part in PARTS:
                race_mean = s.groupby("race_key")[part].mean()
                rows.append(
                    dict(
                        meet=meet,
                        distance_m=int(dist),
                        variant=variant,
                        section=part,
                        rows=len(s),
                        removed=len(frame) - len(s),
                        mean=float(s[part].mean()),
                        median=float(s[part].median()),
                        race_equal_mean=float(race_mean.mean()),
                    )
                )
                if variant != "tail25":
                    continue
                delta = race_mean - base_races[part]
                assert delta.notna().all()
                by_day = (
                    pd.DataFrame(dict(delta=delta, date=dates))
                    .groupby("date")
                    .delta.agg(["sum", "count"])
                )
                boot = []
                for _ in range(1000):
                    ix = rng.integers(0, len(by_day), len(by_day))
                    boot.append(
                        by_day["sum"].to_numpy()[ix].sum() / by_day["count"].to_numpy()[ix].sum()
                    )
                lo, hi = np.quantile(boot, [0.025, 0.975])
                paired.append(
                    dict(
                        meet=meet,
                        distance_m=int(dist),
                        section=part,
                        races=len(delta),
                        days=len(by_day),
                        mean_change=float(delta.mean()),
                        ci_low=float(lo),
                        ci_high=float(hi),
                    )
                )
    return pd.DataFrame(rows), pd.DataFrame(paired)


def main():
    sources = [
        L.POP,
        L.GATES,
        L.LEDGER,
        HERE / "PLAN.md",
        HERE / "analyze.py",
        PREV / "analyze.py",
        N.PREV / "build.py",
        A.HERE / "analyze.py",
        L.HERE / "analyze.py",
        OLD.HERE / "analyze.py",
    ]
    hashes = {str(p.relative_to(ROOT)): A.sha(p) for p in sources}
    roster = classify(pd.read_parquet(L.GATES))
    flags = [
        "row_key",
        "race_key",
        "horse_number",
        "n",
        "finish",
        "race_winner",
        "race_median",
        "race_mad",
        "robust_sigma",
        "time_rank",
        "bottom_quarter",
        "winner_gap",
        "median_gap",
        "winner_floor",
        "tail20_median_floor",
        "tail25_median_floor",
        "tail30_median_floor",
        "tail20",
        "tail25",
        "tail30",
        "leader36",
        "leader10",
        "last_place",
        "adjacent_tail",
    ]
    roster[flags].to_parquet(OUT / "runner_tail_flags.parquet", index=False)
    population, eligible = A.load()
    extra = [s for s in flags if s not in population.columns and s != "race_key"]
    eligible = eligible.merge(roster[["row_key", *extra]], on="row_key", validate="one_to_one")
    eligible["tail_count"] = eligible.race_key.map(roster.groupby("race_key").tail25.sum())
    d = eligible[eligible.mad4_keep].copy().reset_index(drop=True)
    masks = {
        v: ~d[v]
        for v in [
            "tail20",
            "tail25",
            "tail30",
            "leader36",
            "leader10",
            "last_place",
            "adjacent_tail",
        ]
    }
    coverage = []
    for dimensions in [["meet", "distance_m"], ["meet", "band"], ["meet", "grade"]]:
        for key, g in d.groupby(dimensions, observed=True):
            meta = dict(zip(dimensions, key, strict=True))
            coverage.append(
                meta
                | dict(
                    grouping="+".join(dimensions),
                    rows=len(g),
                    races=int(g.race_key.nunique()),
                    tail25=int(g.tail25.sum()),
                    rate=float(g.tail25.mean()),
                    median_winner_floor=float(g.winner_floor.median()),
                    median_median_floor=float(g.tail25_median_floor.median()),
                    median_tail_winner_gap=float(g.loc[g.tail25, "winner_gap"].median())
                    if g.tail25.any()
                    else None,
                )
            )
    pd.DataFrame(coverage).to_csv(OUT / "tail_coverage.csv", index=False)
    desc, paired = descriptions(d)
    desc.to_csv(OUT / "record_baseline_sensitivity.csv", index=False)
    paired.to_csv(OUT / "paired_race_changes.csv", index=False)
    example_keys = []
    for _, g in d.groupby(["meet", "distance_m"], observed=True):
        for count in [1, 2]:
            s = g[g.tail25 & g.tail_count.eq(count)]
            if len(s):
                example_keys.append(
                    s.iloc[np.argmin(abs(s.winner_gap - s.winner_gap.median()))].race_key
                )
    example = d[d.race_key.isin(example_keys)].sort_values(["race_key", "finish"])
    example[
        [
            "meet",
            "distance_m",
            "race_key",
            "date",
            "grade",
            "band",
            "horse_number",
            "time_rank",
            *PARTS,
            "winner_gap",
            "median_gap",
            "robust_sigma",
            "winner_floor",
            "tail25_median_floor",
            "tail25",
            "tail_count",
            "adjacent_tail",
        ]
    ].to_csv(OUT / "race_examples.csv", index=False)
    for key, g in d.groupby(["meet", "distance_m"], observed=True):
        races = g.groupby("race_key")[["band", "moisture"]].first()
        MOIST_WEIGHTS[key] = {
            band: {float(k): float(v) for k, v in s.moisture.value_counts(normalize=True).items()}
            for band, s in races.groupby("band", observed=True)
        }
    N.specs_for = specs_for
    records, models, matrices = [], [], {}
    for (meet, dist), g in d.groupby(["meet", "distance_m"], observed=True):
        for variant in VARIANTS:
            s = g if variant == "baseline" else g[masks[variant].loc[g.index]]
            if not L.minimum(s, False):
                continue
            for kind in ["base", "month"]:
                print(meet, dist, variant, kind, len(s), flush=True)
                r, m = N.fit(
                    s,
                    dict(
                        meet=meet,
                        distance_m=int(dist),
                        variant=variant,
                        period="all_mad4",
                        model_type=kind,
                    ),
                    matrices,
                )
                records.extend(r)
                models.append(m)
    profiles = pd.DataFrame(records)
    profiles["q"] = 1.0
    for _, ix in profiles.groupby(
        ["variant", "model_type", "section", "family"], observed=True
    ).groups.items():
        active = profiles.loc[ix].index[profiles.loc[ix].supported & profiles.loc[ix].p.notna()]
        if len(active):
            profiles.loc[active, "q"] = OLD.bh(profiles.loc[active, "p"].to_numpy())
    profiles["support"] = profiles.support.map(json.dumps)
    profiles.to_csv(OUT / "adjusted_effect_profiles.csv", index=False)
    np.savez_compressed(
        OUT / "model_parameters.npz",
        **{f"{key}_{name}": value for key, m in matrices.items() for name, value in m.items()},
    )
    dump(OUT / "models.json", models)
    keys = ["meet", "distance_m", "model_type", "family", "block", "level", "section"]
    before = profiles[profiles.variant.eq("baseline")][
        keys + ["effect_seconds", "supported"]
    ].rename(columns={"effect_seconds": "before", "supported": "before_supported"})
    changes = profiles[~profiles.variant.eq("baseline")].merge(
        before, on=keys, validate="many_to_one"
    )
    changes["effect_change"] = changes.effect_seconds - changes.before
    changes.to_csv(OUT / "adjusted_effect_changes.csv", index=False)
    dump(
        OUT / "summary.json",
        dict(
            input_sha256=hashes,
            original_rows=len(roster),
            original_races=int(roster.race_key.nunique()),
            enriched_rows=len(population),
            eligible_rows=len(eligible),
            mad4_rows=len(d),
            original_tail25=int(roster.tail25.sum()),
            eligible_tail25=int(eligible.tail25.sum()),
            overlap_mad4_removed=int((eligible.tail25 & ~eligible.mad4_keep).sum()),
            additional_tail25_removed=int(d.tail25.sum()),
            retained_primary=int((~d.tail25).sum()),
            races_with_tail=int(d.loc[d.tail25, "race_key"].nunique()),
            models=len(models),
            profiles=len(profiles),
            variants={v: int(m.sum()) for v, m in masks.items()},
            paired_bootstrap=dict(
                repetitions=1000, seed=20261008, cluster="calendar_date_within_venue_distance"
            ),
            moisture_mix={f"{m}:{dist}": v for (m, dist), v in MOIST_WEIGHTS.items()},
            status="retrospective_sensitivity_only",
            production_changed=False,
            prediction_validation=False,
        ),
    )


if __name__ == "__main__":
    main()
