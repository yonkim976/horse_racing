"""Read-only Busan sectional environment fits using the frozen Seoul policy."""

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
SEOUL = HERE.parent / "20261011_seoul_section_corrections"
SPEC = importlib.util.spec_from_file_location("frozen_seoul_sections", SEOUL / "analyze.py")
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)
E, N, A, L, OLD = S.E, S.N, S.A, S.L, S.OLD
DB, FLAGS = S.DB, S.FLAGS
CORE, PERIODS, VARIANTS = S.CORE, S.PERIODS, S.VARIANTS
POINTS = ["S1F", "G8F", "G6F", "G4F", "G3F", "G2F", "G1F"]
FIELDS = dict(
    zip(
        POINTS,
        [
            "buS1fAccTime",
            "buG8fAccTime",
            "buG6fAccTime",
            "buG4fAccTime",
            "buG3fAccTime",
            "buG2fAccTime",
            "buG1fAccTime",
        ],
        strict=True,
    )
)
REMAINING = {"G8F": 1600, "G6F": 1200, "G4F": 800, "G3F": 600, "G2F": 400, "G1F": 200}
DISTANCES = [1000, 1200, 1300, 1400, 1600, 1800, 1900, 2000, 2200]


def dump(path, data):
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def layout(dist):
    points = [("START", 0), ("S1F", 200), ("FIN", dist)]
    points += [
        (code, dist - remaining)
        for code, remaining in REMAINING.items()
        if 0 < dist - remaining < dist and dist - remaining != 200
    ]
    return sorted(points, key=lambda x: x[1])


def partition(dist):
    points = layout(dist)
    names = []
    for (left, _), (right, _) in zip(points, points[1:], strict=False):
        names.append(
            "early"
            if (left, right) == ("START", "S1F")
            else "late"
            if (left, right) == ("G1F", "FIN")
            else f"{left}_to_{right}"
        )
    return names


def core_length(dist, part):
    if part == "last400":
        return 400
    if part in CORE + ["finish", "last600"]:
        return S.core_length(dist, part)
    points = layout(dist)
    lengths = {
        name: right[1] - left[1]
        for name, left, right in zip(partition(dist), points, points[1:], strict=False)
    }
    return lengths.get(part)


def parts_for(dist, scope):
    return (
        CORE + ["finish", "last600"]
        if scope == "core"
        else list(dict.fromkeys(partition(dist) + CORE + ["finish", "last600", "last400"]))
    )


def load():
    population, eligible = A.load()
    population = population[population.meet.eq("부산")].copy()
    eligible = eligible[eligible.meet.eq("부산")].copy()
    with duckdb.connect(str(DB), read_only=True) as con:
        q = con.execute("""
            SELECT '부산:' || race_date || ':' || race_no || ':' || horse_id AS row_key,
              point_code,time_ms/1000.0 AS seconds,source_file,source_item_index
            FROM section_measurements_api
            WHERE meet=3 AND measure_kind='cumulative_time'
        """).df()
    assert not q.duplicated(["row_key", "point_code"]).any()
    q = q[q.row_key.isin(population.row_key)]
    assert not q.groupby("row_key").source_file.nunique().gt(1).any()
    assert not q.groupby("row_key").source_item_index.nunique().gt(1).any()
    population = population.merge(
        q.pivot(index="row_key", columns="point_code", values="seconds"),
        on="row_key",
        validate="one_to_one",
    )
    population = population.merge(
        q.groupby("row_key")[["source_file", "source_item_index"]].first(),
        on="row_key",
        validate="one_to_one",
        suffixes=("", "_point"),
    )
    assert population.source_file.eq(population.source_file_point).all()
    assert population.source_item_index.eq(population.source_item_index_point).all()
    assert np.allclose(population.S1F, population.early)
    assert np.allclose(population.finish - population.G3F, population.last600)
    assert np.allclose(population.finish - population.G1F, population.late)
    assert np.allclose(population[CORE].sum(axis=1), population.finish)
    population["detail_valid"] = False
    population["distance_outside_fields"] = ""
    population["missing_detail_fields"] = ""
    population["START"], population["FIN"] = 0.0, population.finish
    for dist, g in population.groupby("distance_m"):
        dist = int(dist)
        codes = [code for code, _ in layout(dist)]
        z = g[codes]
        valid = z.notna().all(axis=1) & z.diff(axis=1).iloc[:, 1:].gt(0).all(axis=1)
        population.loc[g.index, "detail_valid"] = valid
        population.loc[g.index, "missing_detail_fields"] = z.isna().apply(
            lambda r: ",".join(r.index[r]), axis=1
        )
        outside = [code for code, rem in REMAINING.items() if dist - rem <= 0]
        if outside:
            population.loc[g.index, "distance_outside_fields"] = (
                g[outside].notna().apply(lambda r: ",".join(r.index[r]), axis=1)
            )
        for name, left, right in zip(partition(dist), codes, codes[1:], strict=False):
            if name not in ["early", "late"]:
                population.loc[g.index, name] = g[right] - g[left]
        population.loc[g.index, "last400"] = g.finish - g.G2F
        assert np.allclose(
            population.loc[g.index[valid], partition(dist)].sum(axis=1), g.loc[valid, "finish"]
        )
        assert sum(core_length(dist, name) for name in partition(dist)) == dist
    extras = [
        *POINTS,
        "detail_valid",
        "distance_outside_fields",
        "missing_detail_fields",
        *sorted({part for dist in DISTANCES for part in partition(dist) if part not in CORE}),
    ]
    eligible = eligible.merge(population[["row_key", *extras]], on="row_key", validate="one_to_one")
    eligible["last400"] = eligible.finish - eligible.G2F
    eligible = eligible.merge(
        pd.read_parquet(FLAGS, columns=["row_key", "tail25"]), on="row_key", validate="one_to_one"
    )
    return population, eligible


def sample(data, dist, scope, period, variant):
    s = L.select(data[data.distance_m.eq(dist)], period)
    if scope == "detail":
        s = s[s.detail_valid]
    if variant == "tail25":
        s = s[~s.tail25]
    return s.reset_index(drop=True)


def raw_verify(population):
    rows, cells, hashes = 0, 0, {}
    for source, group in population.groupby("source_file"):
        path = (ROOT / source).resolve()
        assert path.is_relative_to(ROOT / "thoroughbred/research/20260929_calendar_api_v1/raw")
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            items = json.load(stream)["response"]["body"]["items"]["item"]
        for row in group.itertuples():
            item = items[int(row.source_item_index)]
            assert (
                row.row_key == f"부산:{item['rcDate']}:{item['rcNo']}:{str(item['hrNo']).zfill(7)}"
            )
            assert int(item["rcDist"]) == row.distance_m
            assert abs(float(item["rcTime"]) - row.finish) < 1e-8
            for point, field in FIELDS.items():
                value = getattr(row, point)
                if pd.notna(value):
                    assert abs(float(item[field]) - value) < 1e-8
                    cells += 1
            rows += 1
        hashes[source] = dict(sha256=A.sha(path), rows=len(group))
    return dict(rows=rows, checkpoint_cells=cells, source_files=hashes)


def main():
    OUT.mkdir(exist_ok=True)
    population, data = load()
    raw = raw_verify(population)
    print("raw verified", raw["rows"], raw["checkpoint_cells"], flush=True)
    columns = [
        "row_key",
        "distance_m",
        "date",
        "finish",
        *CORE,
        "last600",
        "last400",
        *POINTS,
        "detail_valid",
        "distance_outside_fields",
        "missing_detail_fields",
        "source_file",
        "source_item_index",
        *sorted({p for dist in DISTANCES for p in partition(dist) if p not in CORE}),
    ]
    population[columns].to_parquet(OUT / "checkpoint_ledger.parquet", index=False)
    population[~population.detail_valid | population.distance_outside_fields.ne("")][
        columns
    ].to_csv(OUT / "checkpoint_exceptions.csv", index=False)
    coverage, profiles, models, matrices, mixes, definitions = [], [], [], {}, {}, []
    for dist, group in population.groupby("distance_m"):
        dist = int(dist)
        for scope in ["core", "detail"]:
            for part in parts_for(dist, scope):
                definitions.append(
                    dict(
                        distance_m=dist,
                        scope=scope,
                        section=part,
                        length_m=core_length(dist, part),
                        partition=part in (CORE if scope == "core" else partition(dist)),
                        multiple_of_200=core_length(dist, part) % 200 == 0,
                    )
                )
            for period in PERIODS:
                original = group if period == "all_mad4" else group[group.year.ge(2024)]
                for variant in VARIANTS:
                    s = sample(data, dist, scope, period, variant)
                    coverage.append(
                        dict(
                            distance_m=dist,
                            scope=scope,
                            period=period,
                            variant=variant,
                            original_rows=len(original),
                            original_races=int(original.race_key.nunique()),
                            rows=len(s),
                            races=int(s.race_key.nunique()),
                            days=int(s.date.nunique()),
                            horses=int(s.horse_id.nunique()),
                            detail_invalid=int((~original.detail_valid).sum()),
                            model_minimum=bool(L.minimum(s, False)),
                        )
                    )
                    if not L.minimum(s, False):
                        continue
                    baseline = sample(data, dist, scope, period, "baseline")
                    _, mix = E.set_mix(baseline)
                    mixes[f"{dist}:{scope}:{period}"] = mix
                    N.PARTS = parts_for(dist, scope)
                    N.specs_for = S.specs_for
                    meta = dict(
                        meet="부산",
                        distance_m=dist,
                        scope=scope,
                        period=period,
                        variant=variant,
                        model_type="month",
                    )
                    print(dist, scope, period, variant, len(s), flush=True)
                    rows, model = N.fit(s, meta, matrices)
                    profiles.extend(rows)
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
            f"{key}_{name}": array
            for key, arrays in matrices.items()
            for name, array in arrays.items()
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
        SEOUL / "analyze.py",
        SEOUL / "build.py",
        SEOUL / "outputs/summary.json",
        SEOUL / "outputs/parameters.npz",
        SEOUL / "outputs/models.json",
        SEOUL / "outputs/correction_components.csv",
        SEOUL / "outputs/effect_profiles.csv",
        E.HERE / "analyze.py",
        E.T.HERE / "analyze.py",
        N.HERE / "analyze.py",
        A.HERE / "analyze.py",
        L.HERE / "analyze.py",
        OLD.HERE / "analyze.py",
    ]
    dump(
        OUT / "summary.json",
        dict(
            completed_on="2026-10-13",
            population_rows=len(population),
            eligible_rows=len(data),
            mad4_rows=int(data.mad4_keep.sum()),
            tail25_rows=int((data.mad4_keep & ~data.tail25).sum()),
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
