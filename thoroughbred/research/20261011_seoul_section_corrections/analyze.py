"""Read-only direct sectional environment estimates from fixed Seoul sources."""

import gzip
import importlib.util
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location(
    "seoul_atlas_source", HERE.parent / "20261008_environment_correction_atlas/analyze.py"
)
E = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E)
N, A, L, OLD = E.N, E.A, E.L, E.OLD
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
FLAGS = HERE.parent / "20261008_detached_tail_sensitivity/outputs/runner_tail_flags.parquet"
POINTS = ["S1F", "1C", "2C", "3C", "G3F", "4C", "G1F"]
FIELDS = dict(
    zip(
        POINTS,
        [
            "seS1fAccTime",
            "se_1cAccTime",
            "se_2cAccTime",
            "se_3cAccTime",
            "seG3fAccTime",
            "se_4cAccTime",
            "seG1fAccTime",
        ],
        strict=True,
    )
)
CORE = ["early", "middle1", "middle2", "late"]
PERIODS = ["all_mad4", "recent_mad4"]
VARIANTS = ["baseline", "tail25"]
LAYOUTS = {
    1000: ["S1F", "G3F", "4C", "G1F"],
    1200: ["S1F", "3C", "G3F", "4C", "G1F"],
    1300: ["S1F", "3C", "G3F", "4C", "G1F"],
    1400: ["S1F", "3C", "G3F", "4C", "G1F"],
    1600: ["S1F", "3C", "G3F", "4C", "G1F"],
    1700: ["S1F", "2C", "3C", "G3F", "4C", "G1F"],
    1800: ["S1F", "1C", "2C", "3C", "G3F", "4C", "G1F"],
    1900: ["S1F", "1C", "2C", "3C", "G3F", "4C", "G1F"],
    2000: ["S1F", "1C", "2C", "3C", "G3F", "4C", "G1F"],
    2300: ["S1F", "1C", "2C", "3C", "G3F", "4C", "G1F"],
}
ALIASES = {1000: "3C", 1600: "2C", 1700: "1C"}


def dump(path, obj):
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def core_length(dist, section):
    return {
        "early": 200,
        "middle1": dist - 800,
        "middle2": 400,
        "late": 200,
        "last600": 600,
        "finish": dist,
    }.get(section)


def segments(dist):
    points = LAYOUTS[dist]
    return [f"{left}_to_{right}" for left, right in zip(points, points[1:], strict=False)]


def parts_for(dist, scope):
    return (
        CORE + ["finish", "last600"]
        if scope == "core"
        else ["early", *segments(dist), "late", "finish", "last600", "middle1", "middle2"]
    )


def load():
    population, eligible = A.load()
    population = population[population.meet.eq("서울")].copy()
    eligible = eligible[eligible.meet.eq("서울")].copy()
    with duckdb.connect(str(DB), read_only=True) as con:
        q = con.execute("""
            SELECT '서울:' || race_date || ':' || race_no || ':' || horse_id AS row_key,
              point_code, time_ms/1000.0 AS seconds, source_file, source_item_index
            FROM section_measurements_api
            WHERE meet=1 AND measure_kind='cumulative_time'
        """).df()
    assert not q.duplicated(["row_key", "point_code"]).any()
    q = q[q.row_key.isin(population.row_key)]
    points = q.pivot(index="row_key", columns="point_code", values="seconds")
    assert not q.groupby("row_key").source_file.nunique().gt(1).any()
    assert not q.groupby("row_key").source_item_index.nunique().gt(1).any()
    source = q.groupby("row_key")[["source_file", "source_item_index"]].first()
    population = population.merge(points, on="row_key", validate="one_to_one")
    population = population.merge(
        source, on="row_key", validate="one_to_one", suffixes=("", "_point")
    )
    assert population.source_file.eq(population.source_file_point).all()
    assert population.source_item_index.eq(population.source_item_index_point).all()
    assert np.allclose(population.S1F, population.early, atol=1e-8)
    assert np.allclose(population.finish - population.G3F, population.last600, atol=1e-8)
    assert np.allclose(population.finish - population.G1F, population.late, atol=1e-8)
    assert np.allclose(population[CORE].sum(axis=1), population.finish, atol=1e-8)
    population["corner_valid"] = False
    population["alias_valid"] = True
    for dist, group in population.groupby("distance_m"):
        dist = int(dist)
        if dist not in LAYOUTS:
            continue
        layout = LAYOUTS[dist]
        g = group[layout]
        alias = np.ones(len(g), bool)
        if dist in ALIASES:
            alias = np.isclose(group[ALIASES[dist]], group.S1F, atol=1e-8)
        valid = g.notna().all(axis=1) & (g.diff(axis=1).iloc[:, 1:] > 0).all(axis=1)
        valid &= alias & group.S1F.gt(0) & group.G1F.lt(group.finish)
        population.loc[group.index, "corner_valid"] = valid
        population.loc[group.index, "alias_valid"] = alias
        for left, right in zip(layout, layout[1:], strict=False):
            population.loc[group.index, f"{left}_to_{right}"] = group[right] - group[left]
        candidate = population.loc[group.index, ["early", *segments(dist), "late"]]
        assert np.allclose(candidate.loc[valid].sum(axis=1), group.loc[valid, "finish"])
    cols = [
        "row_key",
        *POINTS,
        "corner_valid",
        "alias_valid",
        *sorted({s for dist in LAYOUTS for s in segments(dist)}),
    ]
    eligible = eligible.merge(population[cols], on="row_key", validate="one_to_one")
    flags = pd.read_parquet(FLAGS, columns=["row_key", "tail25"])
    eligible = eligible.merge(flags, on="row_key", validate="one_to_one")
    return population, eligible


def raw_verify(population):
    rows, cells, hashes = 0, 0, {}
    for source, group in population.groupby("source_file"):
        path = (ROOT / source).resolve()
        assert path.is_relative_to(ROOT / "thoroughbred/research/20260929_calendar_api_v1/raw")
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            items = json.load(stream)["response"]["body"]["items"]["item"]
        for r in group.itertuples():
            item = items[int(r.source_item_index)]
            expected = f"서울:{item['rcDate']}:{item['rcNo']}:{str(item['hrNo']).zfill(7)}"
            assert expected == r.row_key and int(item["rcDist"]) == r.distance_m
            assert abs(float(item["rcTime"]) - r.finish) < 1e-8
            for point, field in FIELDS.items():
                value = getattr(r, point if point.isidentifier() else "_invalid", None)
                # Numeric-leading corner names are not valid namedtuple attributes.
                if point[0].isdigit():
                    value = population.loc[r.Index, point]
                if pd.notna(value):
                    assert abs(float(item[field]) - value) < 1e-8
                    cells += 1
            rows += 1
        hashes[source] = dict(sha256=A.sha(path), rows=len(group))
    return dict(rows=rows, checkpoint_cells=cells, source_files=hashes)


def specs_for(d, kind):
    x, labels, specs = E.joint_specs(d, kind)
    dry = d[d.band.eq("건조")]
    specs.append(
        (
            np.zeros(len(labels)),
            dict(
                family="moisture",
                block="fixed_band_mix",
                level="건조",
                support=[
                    dict(
                        rows=len(dry),
                        races=int(dry.race_key.nunique()),
                        days=int(dry.date.nunique()),
                        years=int(dry.year.nunique()),
                    )
                ],
                supported=bool(dry.race_key.nunique() >= 50 and dry.date.nunique() >= 20),
            ),
        )
    )
    return x, labels, specs


def sample(d, dist, scope, period, variant):
    s = L.select(d[d.distance_m.eq(dist)], period)
    if scope == "corner":
        s = s[s.corner_valid]
    if variant == "tail25":
        s = s[~s.tail25]
    return s.reset_index(drop=True)


def main():
    OUT.mkdir(exist_ok=True)
    population, d = load()
    raw = raw_verify(population)
    print("raw verified", raw["rows"], raw["checkpoint_cells"], flush=True)
    checkpoint_cols = [
        "row_key",
        "distance_m",
        "date",
        "finish",
        *CORE,
        "last600",
        *POINTS,
        "source_file",
        "source_item_index",
        "corner_valid",
        "alias_valid",
        *sorted({s for dist in LAYOUTS for s in segments(dist)}),
    ]
    population[checkpoint_cols].to_parquet(OUT / "checkpoint_ledger.parquet", index=False)
    coverage, profiles, models, matrices, mixes, definitions = [], [], [], {}, {}, []
    for dist, group in population.groupby("distance_m"):
        dist = int(dist)
        for scope in ["core", "corner"]:
            for section in parts_for(dist, scope):
                is_partition = section in (
                    CORE if scope == "core" else ["early", *segments(dist), "late"]
                )
                definitions.append(
                    dict(
                        distance_m=dist,
                        scope=scope,
                        section=section,
                        length_m=core_length(dist, section),
                        partition=is_partition,
                        multiple_of_200=(core_length(dist, section) % 200 == 0)
                        if core_length(dist, section) is not None
                        else None,
                    )
                )
            for period in PERIODS:
                s_all = group if period == "all_mad4" else group[group.year.ge(2024)]
                for variant in VARIANTS:
                    s = sample(d, dist, scope, period, variant)
                    coverage.append(
                        dict(
                            distance_m=dist,
                            scope=scope,
                            period=period,
                            variant=variant,
                            original_rows=len(s_all),
                            rows=len(s),
                            races=int(s.race_key.nunique()),
                            days=int(s.date.nunique()),
                            horses=int(s.horse_id.nunique()),
                            corner_invalid=int((~s_all.corner_valid).sum()),
                            alias_invalid=int((~s_all.alias_valid).sum()),
                            model_minimum=bool(L.minimum(s, False)),
                        )
                    )
                    if not L.minimum(s, False):
                        continue
                    baseline = sample(d, dist, scope, period, "baseline")
                    _, mix = E.set_mix(baseline)
                    mixes[f"{dist}:{scope}:{period}"] = mix
                    N.PARTS = parts_for(dist, scope)
                    N.specs_for = specs_for
                    meta = dict(
                        meet="서울",
                        distance_m=dist,
                        scope=scope,
                        period=period,
                        variant=variant,
                        model_type="month",
                    )
                    print(dist, scope, period, variant, len(s), flush=True)
                    r, model = N.fit(s, meta, matrices)
                    profiles.extend(r)
                    models.append(model)
    frame = E.fdr(pd.DataFrame(profiles), ["scope", "period", "variant", "section", "family"])
    frame["support"] = frame.support.map(json.dumps)
    frame.to_csv(OUT / "effect_profiles.csv", index=False)
    pd.DataFrame(coverage).to_csv(OUT / "coverage.csv", index=False)
    pd.DataFrame(definitions).to_csv(OUT / "section_definitions.csv", index=False)
    dump(OUT / "models.json", models)
    np.savez_compressed(
        OUT / "parameters.npz",
        **{
            f"{key}_{name}": values
            for key, arrays in matrices.items()
            for name, values in arrays.items()
        },
    )
    sources = [
        DB,
        L.POP,
        L.GATES,
        L.LEDGER,
        FLAGS,
        HERE / "PLAN.md",
        HERE / "analyze.py",
        E.HERE / "analyze.py",
        E.T.TAIL / "analyze.py" if hasattr(E.T, "TAIL") else E.T.HERE / "analyze.py",
        N.HERE / "analyze.py",
        A.HERE / "analyze.py",
        L.HERE / "analyze.py",
        OLD.HERE / "analyze.py",
    ]
    dump(
        OUT / "summary.json",
        dict(
            completed_on="2026-10-11",
            population_rows=len(population),
            eligible_rows=len(d),
            mad4_rows=int(d.mad4_keep.sum()),
            tail25_rows=int((d.mad4_keep & ~d.tail25).sum()),
            start=str(population.date.min().date()),
            end=str(population.date.max().date()),
            models=len(models),
            profiles=len(frame),
            raw_verification=raw,
            moisture_mix=mixes,
            input_sha256={str(p.relative_to(ROOT)): A.sha(p) for p in sources},
            status="trial_only",
            production_changed=False,
            prediction_validation=False,
        ),
    )


if __name__ == "__main__":
    main()
