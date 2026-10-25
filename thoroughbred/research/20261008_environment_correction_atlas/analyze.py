"""Joint sensitivity fits and moisture-specific, within-pack position comparisons."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
TAIL = HERE.parent / "20261008_detached_tail_sensitivity"
SPEC = importlib.util.spec_from_file_location("tail_source", TAIL / "analyze.py")
T = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T)
N, A, L, OLD = T.N, T.A, T.L, T.OLD
PARTS = T.PARTS
PERIODS = ["all_mad4", "recent_mad4"]
VARIANTS = ["baseline", "tail25"]
LAT_DESIGN = L.lateral_design
LAT_SPECS = L.contrast_specs
BANDS = A.BANDS


def dump(path, obj):
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def joint_specs(d, kind):
    x, labels, specs = T.specs_for(d, kind)
    _, _, gates, _ = OLD.design(d)
    specs += LAT_SPECS(d, labels, gates, False)
    return x, labels, specs


def lateral_design(d):
    x, labels = LAT_DESIGN(d)
    cols, names = [], []
    for band in BANDS:
        if not d.band.eq(band).any():
            continue
        for j in range(3):
            cols.append(x[:, j] * d.band.eq(band).to_numpy(float))
            names.append(f"side:{band}:{j}")
    return np.column_stack(cols + [x[:, 3:]]), names + labels[3:]


def lateral_specs(d, labels, specs, lateral):
    assert lateral
    result = []
    for band in BANDS:
        if not d.band.eq(band).any():
            continue
        for block, level, coefs, sides in [
            ("pair", "outer-inner", [0, 0, 1], ["inner", "outer"]),
            ("triple", "middle-inner", [1, 0, 0], ["middle", "inner"]),
            ("triple", "outer-inner", [0, 1, 0], ["outer", "inner"]),
            ("triple", "outer-middle", [-1, 1, 0], ["outer", "middle"]),
        ]:
            b = d[d.band.eq(band) & (d.pack_size.eq(2) if block == "pair" else d.pack_size.ge(3))]
            vector = np.zeros(len(labels))
            for j, coef in enumerate(coefs):
                vector[labels.index(f"side:{band}:{j}")] = coef
            support = []
            for side in sides:
                s = b[b.lateral_side.eq(side)]
                support.append(
                    dict(
                        rows=len(s),
                        packs=int(s.pack_id.nunique()),
                        races=int(s.race_key.nunique()),
                        days=int(s.date.nunique()),
                    )
                )
            supported = all(
                s["rows"] >= 100 and s["packs"] >= 50 and s["races"] >= 30 and s["days"] >= 20
                for s in support
            )
            result.append(
                (
                    vector,
                    dict(
                        band=band,
                        family=block,
                        block=block,
                        level=level,
                        supported=supported,
                        strict_supported=supported,
                        minimum_rows=min(s["rows"] for s in support),
                        support=support,
                    ),
                )
            )
    return result


def set_mix(d):
    key = (str(d.meet.iloc[0]), int(d.distance_m.iloc[0]))
    races = d.groupby("race_key")[["band", "moisture"]].first()
    T.MOIST_WEIGHTS[key] = {
        band: {float(k): float(v) for k, v in g.moisture.value_counts(normalize=True).items()}
        for band, g in races.groupby("band", observed=True)
    }
    return key, T.MOIST_WEIGHTS[key]


def fdr(frame, keys):
    frame["q"] = 1.0
    for _, ix in frame.groupby(keys, observed=True).groups.items():
        active = frame.loc[ix].index[frame.loc[ix].supported & frame.loc[ix].p.notna()]
        if len(active):
            frame.loc[active, "q"] = OLD.bh(frame.loc[active, "p"].to_numpy())
    return frame


def describe_positions(p):
    results = []
    for variant in VARIANTS:
        s = p[p.mad4_keep & (~p.tail25 if variant == "tail25" else True)].copy()
        good = s.groupby("pack_id").row_key.transform("size").eq(s.pack_size)
        s = s[good]
        values = s.groupby(["pack_id", "lateral_side"])[["finish", "remaining"]].mean().unstack()
        meta = s.groupby("pack_id")[
            ["meet", "distance_m", "point", "band", "year", "date", "race_key", "pack_size"]
        ].first()
        meta["quarter"] = meta.date.dt.to_period("Q").astype(str)
        for block, left, right in [
            ("pair", "outer", "inner"),
            ("triple", "middle", "inner"),
            ("triple", "outer", "inner"),
            ("triple", "outer", "middle"),
        ]:
            chosen = meta.pack_size.eq(2) if block == "pair" else meta.pack_size.ge(3)
            for metric in ["finish", "remaining"]:
                z = meta[chosen].copy()
                z["difference"] = (values[(metric, left)] - values[(metric, right)]).reindex(
                    z.index
                )
                z = z[z.difference.notna()]
                for grain in ["year", "quarter"]:
                    keys = ["meet", "distance_m", "point", "band", grain]
                    for key, g in z.groupby(keys, observed=True):
                        results.append(
                            dict(zip(keys, key, strict=True))
                            | dict(
                                variant=variant,
                                grain=grain,
                                block=block,
                                level=left + "-" + right,
                                metric=metric,
                                packs=len(g),
                                races=int(g.race_key.nunique()),
                                days=int(g.date.nunique()),
                                pack_mean=float(g.difference.mean()),
                                race_equal_mean=float(
                                    g.groupby("race_key").difference.mean().mean()
                                ),
                                median=float(g.difference.median()),
                                supported=bool(
                                    len(g) >= 50
                                    and g.race_key.nunique() >= 30
                                    and g.date.nunique() >= 20
                                ),
                                method="unadjusted_same_pack_difference",
                            )
                        )
    pd.DataFrame(results).to_csv(OUT / "lateral_year_quarter_descriptive.csv", index=False)


def main():
    sources = [
        L.POP,
        L.GATES,
        L.LEDGER,
        L.POSITIONS,
        L.FOURC,
        TAIL / "outputs/runner_tail_flags.parquet",
        HERE / "PLAN.md",
        HERE / "analyze.py",
        TAIL / "analyze.py",
        N.HERE / "analyze.py",
        L.HERE / "analyze.py",
        OLD.HERE / "analyze.py",
        A.HERE / "analyze.py",
    ]
    hashes = {str(p.relative_to(ROOT)): A.sha(p) for p in sources}
    flags = pd.read_parquet(
        TAIL / "outputs/runner_tail_flags.parquet", columns=["row_key", "tail25"]
    )
    population, d = A.load()
    d = d.merge(flags, on="row_key", validate="one_to_one")
    N.specs_for = joint_specs
    profiles, models, matrices, mixes = [], [], {}, {}
    for (meet, dist), g in d.groupby(["meet", "distance_m"], observed=True):
        for period in PERIODS:
            baseline = L.select(g, period)
            if not L.minimum(baseline, False):
                continue
            _, mix = set_mix(baseline)
            mixes[f"{meet}:{dist}:{period}"] = mix
            for variant in VARIANTS:
                s = baseline if variant == "baseline" else baseline[~baseline.tail25]
                if not L.minimum(s, False):
                    continue
                print("joint", meet, dist, period, variant, len(s), flush=True)
                r, m = N.fit(
                    s,
                    dict(
                        meet=meet,
                        distance_m=int(dist),
                        period=period,
                        variant=variant,
                        model_type="month",
                    ),
                    matrices,
                )
                profiles.extend(r)
                models.append(m)
    j = fdr(pd.DataFrame(profiles), ["period", "variant", "section", "family"])
    j["support"] = j.support.map(json.dumps)
    j.to_csv(OUT / "joint_sensitivity_profiles.csv", index=False)
    dump(OUT / "joint_models.json", models)
    np.savez_compressed(
        OUT / "joint_parameters.npz",
        **{f"{k}_{name}": arr for k, m in matrices.items() for name, arr in m.items()},
    )
    print("loading positions", flush=True)
    _, p, audit = L.load()
    p = p.merge(flags, on="row_key", validate="many_to_one")
    describe_positions(p)
    L.lateral_design = lateral_design
    L.contrast_specs = lateral_specs
    records, latmodels, latmatrices, coverage = [], [], {}, []
    for (meet, point), g in p.groupby(["meet", "point"], observed=True):
        for dist in [0, *sorted(g.distance_m.unique())]:
            a = g if dist == 0 else g[g.distance_m.eq(dist)]
            for period in PERIODS:
                b = L.select(a, period, True)
                for variant in VARIANTS:
                    s = (
                        b
                        if variant == "baseline"
                        else b[~b.groupby("pack_id").tail25.transform("any")]
                    )
                    coverage.append(
                        dict(
                            meet=meet,
                            point=point,
                            distance_m=int(dist),
                            period=period,
                            variant=variant,
                            rows=len(s),
                            packs=int(s.pack_id.nunique()),
                            races=int(s.race_key.nunique()),
                            days=int(s.date.nunique()),
                            horses=int(s.horse_id.nunique()),
                            model_minimum=bool(L.minimum(s, True)),
                        )
                    )
                    if not L.minimum(s, True):
                        continue
                    scopes = [("all", s)]
                    if s.remaining.notna().any() and s.remaining.isna().any():
                        scopes.append(("known_remaining", s[s.remaining.notna()]))
                    for scope, sample in scopes:
                        if not L.minimum(sample, True):
                            continue
                        print(
                            "lateral",
                            meet,
                            point,
                            dist,
                            period,
                            variant,
                            scope,
                            len(sample),
                            flush=True,
                        )
                        r, m = L.fit(
                            sample,
                            dict(
                                kind="lateral",
                                meet=meet,
                                point=point,
                                distance_m=int(dist),
                                period=period,
                                variant=variant,
                                scope=scope,
                                adjustment="dual",
                            ),
                            latmatrices,
                        )
                        if m is None:
                            continue
                        for row in r:
                            row["matrix_key"] = m["matrix_key"]
                            if not row["estimable"]:
                                for col in ["effect_seconds", "se", "ci_low", "ci_high", "p"]:
                                    row[col] = None
                        records.extend(
                            [row for row in r if scope == "all" or row["metric"] == "remaining"]
                        )
                        latmodels.append(m)
    lat = fdr(pd.DataFrame(records), ["period", "variant", "metric", "block"])
    lat["support"] = lat.support.map(json.dumps)
    lat["outer_tendency"] = np.where(
        lat.effect_seconds < 0, "외측/왼쪽 비교위치가 빠름", "외측/왼쪽 비교위치가 느림"
    )
    lat.loc[~lat.supported, "outer_tendency"] = "표본부족/미식별"
    lat.to_csv(OUT / "lateral_moisture_period_profiles.csv", index=False)
    pd.DataFrame(coverage).to_csv(OUT / "lateral_model_coverage.csv", index=False)
    dump(OUT / "lateral_models.json", latmodels)
    np.savez_compressed(
        OUT / "lateral_parameters.npz",
        **{f"{k}_{name}": arr for k, m in latmatrices.items() for name, arr in m.items()},
    )
    dump(
        OUT / "analysis_summary.json",
        dict(
            input_sha256=hashes,
            population_rows=len(population),
            eligible_rows=len(d),
            joint_models=len(models),
            joint_profiles=len(j),
            lateral_models=len(latmodels),
            lateral_profiles=len(lat),
            position_audit=audit,
            position_data_start=str(p.date.min().date()),
            position_data_end=str(p.date.max().date()),
            moisture_mix=mixes,
            production_changed=False,
            prediction_validation=False,
        ),
    )


if __name__ == "__main__":
    main()
