"""Independent source, aggregation, explicit fixed-effect regression and resampling checks."""

# ruff: noqa: E501
import json

import duckdb
import numpy as np
import pandas as pd
from analyze import CORE, INPUTS, NUMS, OUT, PARTS, ROOT, SEASONS, sha
from scipy import sparse
from scipy.sparse.linalg import lsqr

FIELDS = ["meet", "distance_m", "band", "kind", "label", "part"]


def read(name):
    return pd.read_csv(OUT / name, dtype={"grade": str, "label": str})


def main():
    s = json.loads((OUT / "summary.json").read_text())
    assert s["inputs"] == {str(p.relative_to(ROOT)): sha(p) for p in INPUTS}
    d = pd.read_parquet(OUT / "population.parquet")
    r = pd.read_parquet(OUT / "race_means.parquet")
    assert len(d) == s["input_n"] == 151074 and len(r) == s["race_n"] == 13928
    assert not d.row_key.duplicated().any() and not r.source_key.duplicated().any()
    assert not d.rating.le(0).any()
    source_checks = 0
    for i, p in enumerate(INPUTS):
        original = pd.read_parquet(p)
        if i == 0:
            original = original[original.population.eq("실전1200")].copy()
            original["distance_m"] = 1200
        original["rating"] = original.rating.mask(original.rating.le(0))
        current = d[d.input_path.eq(str(p.relative_to(ROOT)))]
        joined = current.merge(original, on="row_key", suffixes=("_a", "_b"), validate="one_to_one")
        assert len(joined) == len(current) == len(original)
        for field in [*PARTS, "moisture", *NUMS]:
            assert np.allclose(joined[field + "_a"], joined[field + "_b"], equal_nan=True), field
            source_checks += len(joined)
    with duckdb.connect() as con:
        con.register("runners", d)
        independently = con.execute(
            """SELECT source_key, count(*) AS runner_n, avg(finish) AS finish, avg(early) AS early, avg(middle1) AS middle1, avg(middle2) AS middle2, avg(late) AS late, avg(last600) AS last600 FROM runners GROUP BY source_key"""
        ).fetchdf()
    joined = r.merge(independently, on="source_key", suffixes=("_a", "_b"), validate="one_to_one")
    for field in [*PARTS, "runner_n"]:
        assert np.allclose(joined[field + "_a"], joined[field + "_b"])
    assert np.allclose(d[CORE].sum(axis=1), d.finish) and np.allclose(r[CORE].sum(axis=1), r.finish)
    assert d.date.min() == pd.Timestamp("2018-01-05")
    known = d.last_history_date.notna()
    assert (pd.to_datetime(d.loc[known, "last_history_date"]) < d.loc[known, "date"]).all()
    est = read("controlled_month_season_contrasts.csv")
    counts = read("model_support.csv")
    bootstrap = pd.read_parquet(OUT / "date_bootstrap_contrasts.parquet")
    numeric_checks = 0
    for key, g in bootstrap.groupby(FIELDS):
        cell = est
        for name, value in zip(FIELDS, key, strict=True):
            cell = cell[cell[name].eq(value)]
        assert len(cell) == 1
        row = cell.iloc[0]
        good = g.difference.dropna()
        assert int(row.bootstrap_valid_n) == len(good)
        if len(good) >= 180:
            assert np.allclose([row.ci_low, row.ci_high], good.quantile([0.025, 0.975]))
        else:
            assert pd.isna(row.ci_low) and pd.isna(row.ci_high)
        numeric_checks += 4
    for _keys, g in est.groupby(["meet", "distance_m", "band", "kind", "label"]):
        v = g.set_index("part").difference
        if pd.notna(v["finish"]):
            assert np.isclose(v[CORE].sum(), v["finish"])
            assert np.isclose(v["middle2"] + v["late"], v["last600"])
            numeric_checks += 2
    unavailable = est.status.isin(["not_identifiable", "no_within_stratum_month_overlap"])
    assert est.loc[unavailable, "difference"].isna().all()
    assert est.loc[est.bootstrap_valid_n.lt(180), ["ci_low", "ci_high"]].isna().all().all()
    assert not (est.part.eq("last400") & est.meet.eq("서울")).any()
    # Direct explicit fixed-effect dummies form a separate solution from the within transform.
    direct_checks = []
    sex_columns = sorted(c for c in r if c.startswith("sex_share_"))
    for row in counts[counts.band.eq("전체") & counts.informative_races.gt(0)].itertuples():
        g = r[r.meet.eq(row.meet) & r.distance_m.eq(row.distance_m)].copy()
        group_n = g.groupby(["year", "grade", "moisture"]).month.transform("nunique")
        g = g[group_n.ge(2)].reset_index(drop=True)
        assert len(g) == row.informative_races
        x = np.eye(12)[g.month.to_numpy() - 1]
        cols = [*NUMS, "runner_n", *sex_columns, *[c + "_missing" for c in NUMS]]
        z = g[cols].copy()
        for col in cols:
            m = z[col].median()
            z[col] = z[col].fillna(0 if pd.isna(m) else m)
        z = z.to_numpy(float)
        sd = z.std(axis=0)
        sd[sd < 1e-10] = 1
        x = np.column_stack([x, (z - z.mean(axis=0)) / sd])
        codes = pd.factorize(
            g[["year", "grade", "moisture"]].astype(str).agg("|".join, axis=1), sort=True
        )[0]
        fixed = sparse.coo_matrix((np.ones(len(g)), (np.arange(len(g)), codes))).tocsr()
        design = sparse.hstack([sparse.csr_matrix(x), fixed], format="csr")
        betas = []
        for part in CORE:
            result = lsqr(design, g[part].to_numpy(), atol=1e-11, btol=1e-11, iter_lim=10000)
            assert result[1] in [1, 2], (row.meet, row.distance_m, part, result[1])
            betas.append(result[0][: x.shape[1]])
        beta = np.array(betas).T
        for season, months in SEASONS.items():
            if season == "겨울":
                continue
            check = est[
                est.meet.eq(row.meet)
                & est.distance_m.eq(row.distance_m)
                & est.band.eq("전체")
                & est.kind.eq("season")
                & est.label.eq(season)
            ]
            c = np.zeros(x.shape[1])
            c[np.array(months) - 1] = 1 / 3
            c[np.array(SEASONS["겨울"]) - 1] -= 1 / 3
            for part, vector in {
                **{p: np.eye(4)[i] for i, p in enumerate(CORE)},
                "finish": np.ones(4),
                "last600": np.array([0, 0, 1, 1]),
            }.items():
                value = check[check.part.eq(part)].difference.iloc[0]
                if pd.notna(value):
                    assert abs(float(c @ beta @ vector) - value) < 2e-5, (
                        row.meet,
                        row.distance_m,
                        season,
                        part,
                        value,
                        c @ beta @ vector,
                    )
                    direct_checks.append(
                        dict(
                            meet=row.meet,
                            distance_m=row.distance_m,
                            season=season,
                            part=part,
                            absolute_error=abs(float(c @ beta @ vector) - value),
                        )
                    )
    pd.DataFrame(direct_checks).to_csv(OUT / "explicit_fixed_effect_verification.csv", index=False)
    # Matched tables have exact same-year/same-grade support on both seasonal sides.
    details = read("matched_stratum_contrasts.csv")
    assert np.allclose(details.difference, details.target_mean - details.winter_mean)
    assert np.allclose(
        details.weight,
        details.target_races * details.winter_races / (details.target_races + details.winter_races),
    )
    exact = details[details.method.eq("same_exact_moisture")]
    assert (
        exact.moisture.notna().all()
        and exact.winter_races.ge(1).all()
        and exact.target_races.ge(1).all()
    )
    # Rebuild matched seasonal means directly from the retained race table.
    long = r.melt(
        id_vars=["meet", "distance_m", "year", "grade", "moisture", "band", "season"],
        value_vars=PARTS,
        var_name="part",
        value_name="time",
    )
    keys = ["meet", "distance_m", "year", "grade", "moisture", "band", "part"]
    observed = (
        long.groupby(keys + ["season"]).time.agg(actual_mean="mean", actual_n="size").reset_index()
    )
    observed = observed.rename(columns={"band": "stratum_band"})
    join_keys = ["stratum_band" if k == "band" else k for k in keys]
    winter = (
        observed[observed.season.eq("겨울")]
        .drop(columns="season")
        .rename(columns={"actual_mean": "actual_winter", "actual_n": "actual_winter_n"})
    )
    target = observed[~observed.season.eq("겨울")].rename(
        columns={"actual_mean": "actual_target", "actual_n": "actual_target_n"}
    )
    joined = exact.merge(winter, on=join_keys, validate="many_to_one").merge(
        target, on=join_keys + ["season"], validate="many_to_one"
    )
    assert len(joined) == len(exact)
    assert np.allclose(joined.winter_mean, joined.actual_winter)
    assert np.allclose(joined.target_mean, joined.actual_target)
    assert np.allclose(joined.winter_races, joined.actual_winter_n)
    assert np.allclose(joined.target_races, joined.actual_target_n)
    numeric_checks += len(joined) * 4
    aggregate = read("matched_season_contrasts.csv")
    for row in aggregate.itertuples():
        g = details[
            details.meet.eq(row.meet)
            & details.distance_m.eq(row.distance_m)
            & details.band.eq(row.band)
            & details.season.eq(row.season)
            & details.method.eq(row.method)
            & details.part.eq(row.part)
        ]
        assert np.isclose(np.average(g.difference, weights=g.weight), row.difference)
        numeric_checks += 1
    mix = read("seasonal_state_mix.csv")
    assert np.allclose(mix.groupby(["period", "meet", "season"]).share.sum(), 1)
    recent = read("recent_complete_year_contrasts.csv")
    recent_support = read("recent_model_support.csv")
    assert recent_support.years.le(2).all() and recent.period.eq("complete_2024_2025").all()
    result = dict(
        passed=True,
        created_on="2026-10-07",
        inputs_unchanged=True,
        input_rows=len(d),
        race_rows=len(r),
        individual_source_numeric_checks=source_checks,
        table_numeric_checks=numeric_checks,
        explicit_dummy_ols_checks=len(direct_checks),
        max_explicit_dummy_difference=max(x["absolute_error"] for x in direct_checks),
        date_bootstrap_quantiles_checked=True,
        exact_year_grade_moisture_matching=True,
        source_sections_sum=True,
        unsupported_contrasts_null=True,
        recent_analysis_only_complete_2024_2025=True,
        limitation="Verifies source/arithmetic/support/uncertainty; seasonal association is not causal weather or a validated correction",
    )
    (OUT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
