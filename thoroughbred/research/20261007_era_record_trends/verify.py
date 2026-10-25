"""Independent SQL stratum means, sparse dummy regressions and bootstrap checks."""

# ruff: noqa: E501
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import lsmr

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SOURCE = HERE.parent / "20261007_seasonal_same_moisture/outputs"
PARTS = [
    "early",
    "middle1",
    "middle2",
    "late",
    "finish",
    "last600",
    "early_relative_pct",
    "late_relative_pct",
    "last600_relative_pct",
]
KEY = ["meet", "distance_m", "window", "band"]


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    for name, value in summary["source_sha256"].items():
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == value
    races = pd.read_parquet(OUT / "analysis_race_means.parquet")
    original = pd.read_parquet(SOURCE / "race_means.parquet")
    pd.testing.assert_frame_equal(races[original.columns], original)
    pop = pd.read_parquet(SOURCE / "population.parquet")
    for name, meters, part in [
        ("early_relative_pct", 200, "early"),
        ("late_relative_pct", 200, "late"),
        ("last600_relative_pct", 600, "last600"),
    ]:
        calculated = (
            (100 * meters * pop.finish / (pop.distance_m * pop[part]))
            .groupby(pop.source_key)
            .mean()
        )
        np.testing.assert_allclose(
            races.set_index("source_key")[name].sort_index(), calculated.sort_index(), atol=1e-10
        )
    membership = pd.read_parquet(OUT / "model_membership.parquet")
    con = duckdb.connect()
    con.register("races", races)
    con.register("membership", membership)
    actual = pd.read_parquet(OUT / "exact_matched_strata.parquet")
    columns = ",".join(f'avg(r."{c}") AS "{c}"' for c in PARTS)
    sql = con.execute(f"""SELECT m.meet,m.distance_m,m.window,m.band,r.grade,r.moisture,r.month,m.era,count(*) AS n,{columns}
        FROM membership m JOIN races r USING(source_key) GROUP BY ALL""").df()
    order = KEY + ["grade", "moisture", "month", "era"]
    a, b = (
        actual.sort_values(order).reset_index(drop=True),
        sql.sort_values(order).reset_index(drop=True),
    )
    pd.testing.assert_frame_equal(a[order], b[order], check_dtype=False)
    np.testing.assert_allclose(a[["n"] + PARTS], b[["n"] + PARTS], atol=1e-10)
    estimates = pd.read_csv(OUT / "era_contrasts.csv")
    assert len(estimates) == 1710
    common = {k: g for k, g in membership.groupby(KEY, observed=True)}
    means = {k: g for k, g in sql.groupby(KEY, observed=True)}
    matches_checked = 0
    independent_ols = []
    for key, series in estimates.groupby(KEY, observed=True):
        window = summary["windows"][key[2]]
        raw = races.loc[
            races.meet.eq(key[0])
            & races.distance_m.eq(key[1])
            & races.year.isin(window["before_years"] + window["recent_years"])
            & races.month.isin(window["months"])
        ]
        if key[3] != "전체":
            raw = raw.loc[raw.band.eq(key[3])]
        raw = raw.assign(era=raw.year.isin(window["recent_years"]).astype(int))
        wanted = raw.loc[
            raw.groupby(["grade", "moisture", "month"], observed=True)
            .era.transform("nunique")
            .eq(2)
        ]
        member = common.get(key)
        assert set([] if member is None else member.source_key) == set(wanted.source_key)
        for row in series.itertuples(index=False):
            expected = (
                raw.loc[raw.era.eq(1), row.part].mean() - raw.loc[raw.era.eq(0), row.part].mean()
            )
            np.testing.assert_allclose(row.raw_difference, expected, atol=1e-10, equal_nan=True)
            assert row.informative_races == len(wanted)
            assert (
                row.before_races == wanted.era.eq(0).sum()
                and row.recent_races == wanted.era.eq(1).sum()
            )
            if row.specification == "exact_matched" and key in means:
                s = means[key].pivot(
                    index=["grade", "moisture", "month"], columns="era", values=["n", row.part]
                )
                w = s["n"][0] * s["n"][1] / (s["n"][0] + s["n"][1])
                delta = np.average(s[row.part][1] - s[row.part][0], weights=w)
                np.testing.assert_allclose(row.difference, delta, atol=1e-9)
                matches_checked += 1
        # Independent explicit sparse fixed-effect dummies for focal main and complete-year models.
        if (
            key[1] in [1200, 1300, 1400, 1700, 1800]
            and key[2] in ["common_jan_aug", "complete_2024_2025"]
            and key[3] == "전체"
            and len(wanted)
        ):
            g = wanted.reset_index(drop=True)
            group = pd.factorize(
                pd.MultiIndex.from_frame(g[["grade", "moisture", "month"]]), sort=True
            )[0]
            dummy = sparse.csr_matrix(
                (np.ones(len(g)), (np.arange(len(g)), group)), shape=(len(g), group.max() + 1)
            )
            cols = (
                [
                    "age",
                    "weight",
                    "rating",
                    "prior_finish",
                    "prior_top3",
                    "prior_early",
                    "log_starts",
                    "log_gap",
                    "runner_n",
                ]
                + [c for c in g if c.startswith("sex_share_")]
                + [
                    c + "_missing"
                    for c in [
                        "age",
                        "weight",
                        "rating",
                        "prior_finish",
                        "prior_top3",
                        "prior_early",
                        "log_starts",
                        "log_gap",
                    ]
                ]
            )
            z = g[cols].fillna(g[cols].median()).fillna(0).to_numpy(dtype=float)
            sd = z.std(axis=0)
            sd[sd < 1e-10] = 1
            x = sparse.hstack(
                [
                    dummy,
                    sparse.csr_matrix(g[["era"]].to_numpy()),
                    sparse.csr_matrix((z - z.mean(axis=0)) / sd),
                ],
                format="csr",
            )
            for part in PARTS:
                solution = lsmr(x, g[part].to_numpy(), atol=1e-12, btol=1e-12, maxiter=10000)
                assert solution[1] in [1, 2], solution[1]
                beta = solution[0][dummy.shape[1]]
                row = series.loc[
                    series.specification.eq("composition_adjusted") & series.part.eq(part)
                ].iloc[0]
                error = abs(beta - row.difference)
                assert error < 1e-7, (key, part, error)
                independent_ols.append(
                    dict(zip(KEY, key, strict=True))
                    | dict(
                        part=part,
                        explicit_dummy_difference=beta,
                        saved_difference=row.difference,
                        error=error,
                    )
                )
    boot = pd.read_parquet(OUT / "date_bootstrap_contrasts.parquet")
    grouping = KEY + ["specification", "part"]
    bgroup = {k: g.difference.dropna().to_numpy() for k, g in boot.groupby(grouping, observed=True)}
    for row in estimates.itertuples(index=False):
        key = tuple(getattr(row, k) for k in grouping)
        values = bgroup[key]
        assert len(values) == row.bootstrap_valid_n
        q = np.percentile(values, [2.5, 97.5]) if len(values) >= 180 else [np.nan, np.nan]
        np.testing.assert_allclose([row.ci_low, row.ci_high], q, atol=1e-10, equal_nan=True)
        adequate = (
            row.strata >= 20
            and min(row.before_races, row.recent_races) >= 50
            and min(row.before_days, row.recent_days) >= 20
            and min(row.before_years, row.recent_years) >= 2
            and row.status == "supported"
            and row.residual_df > 0
            and row.bootstrap_valid_n >= 180
        )
        assert row.interpretation_support == adequate
    for data, keys in [
        (estimates, KEY + ["specification"]),
        (boot, KEY + ["specification", "replicate"]),
    ]:
        pivot = data.pivot(index=keys, columns="part", values="difference")
        np.testing.assert_allclose(
            pivot.finish,
            pivot[["early", "middle1", "middle2", "late"]].sum(axis=1, min_count=4),
            atol=1e-9,
            equal_nan=True,
        )
        np.testing.assert_allclose(
            pivot.last600, pivot.middle2 + pivot.late, atol=1e-9, equal_nan=True
        )
    annual = pd.read_csv(OUT / "annual_race_means.csv")
    for row in annual.itertuples(index=False):
        h = races.loc[
            races.meet.eq(row.meet) & races.distance_m.eq(row.distance_m) & races.year.eq(row.year)
        ]
        if row.window == "jan_aug":
            h = h.loc[h.month.le(8)]
        assert len(h) == row.races and h.runner_n.sum() == row.runner_n
        np.testing.assert_allclose([getattr(row, p) for p in PARTS], h[PARTS].mean(), atol=1e-9)
    # Check every runner percentile independently, without rounding input records.
    distribution = pd.read_csv(OUT / "annual_runner_distributions.csv")
    for row in distribution.itertuples(index=False):
        h = pop.loc[
            pop.meet.eq(row.meet) & pop.distance_m.eq(row.distance_m) & pop.year.eq(row.year)
        ]
        if row.window == "jan_aug":
            h = h.loc[h.month.le(8)]
        q = np.percentile(h[row.part], [20, 50, 80])
        np.testing.assert_allclose([row.p20, row.median, row.p80], q, atol=1e-9)
        np.testing.assert_allclose(row.mean, h[row.part].mean(), atol=1e-9)
        assert row.n == len(h)
    grade_changes = pd.read_csv(OUT / "grade_matched_changes.csv", dtype={"grade": str})
    grade_checks = 0
    for key, strata in sql.loc[sql.window.eq("common_jan_aug") & sql.band.eq("전체")].groupby(
        ["meet", "distance_m", "grade"], observed=True
    ):
        pivot = strata.pivot(index=["moisture", "month"], columns="era", values=["n"] + PARTS)
        weights = pivot["n"][0] * pivot["n"][1] / (pivot["n"][0] + pivot["n"][1])
        saved = grade_changes.loc[
            grade_changes.meet.eq(key[0])
            & grade_changes.distance_m.eq(key[1])
            & grade_changes.grade.eq(key[2])
        ].set_index("part")
        for part in PARTS:
            expected = np.average(pivot[part][1] - pivot[part][0], weights=weights)
            np.testing.assert_allclose(saved.loc[part, "difference"], expected, atol=1e-9)
            grade_checks += 1
    assert grade_checks == len(grade_changes)
    recent = pd.read_csv(OUT / "recent_year_matched_changes.csv")
    year_checks = 0
    for (meet, distance, year), saved in recent.groupby(["meet", "distance_m", "year"]):
        part = races.loc[
            races.meet.eq(meet)
            & races.distance_m.eq(distance)
            & races.month.le(8)
            & (races.year.le(2023) | races.year.eq(year))
        ].copy()
        part["era"] = part.year.eq(year).astype(int)
        part = part.loc[part.groupby(["grade", "moisture", "month"]).era.transform("nunique").eq(2)]
        pivot = part.groupby(["grade", "moisture", "month", "era"])[PARTS].mean().unstack("era")
        counts = part.groupby(["grade", "moisture", "month", "era"]).size().unstack("era")
        weights = counts[0] * counts[1] / (counts[0] + counts[1])
        for row in saved.itertuples(index=False):
            expected = np.average(pivot[row.part][1] - pivot[row.part][0], weights=weights)
            np.testing.assert_allclose(row.difference, expected, atol=1e-9)
            assert (
                row.before_races == part.era.eq(0).sum()
                and row.recent_races == part.era.eq(1).sum()
            )
            year_checks += 1
    mix = pd.read_csv(OUT / "era_grade_moisture_mix.csv", dtype={"value": str})
    for row in mix.itertuples(index=False):
        raw = races.loc[
            races.meet.eq(row.meet) & races.distance_m.eq(row.distance_m) & races.month.le(8)
        ]
        raw = raw.loc[raw.year.ge(2024) if row.era else raw.year.le(2023)]
        count = raw[row.field].astype(str).eq(row.value).sum()
        assert count == row.races
        np.testing.assert_allclose(row.share, count / len(raw), atol=1e-10)
    for name, value in summary["source_sha256"].items():
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == value
    pd.DataFrame(independent_ols).to_csv(OUT / "explicit_dummy_verification.csv", index=False)
    result = dict(
        passed=True,
        source_hashes_unchanged=True,
        original_race_means_preserved=True,
        individual_relative_ratios_checked=len(pop) * 3,
        sql_strata_checked=len(sql),
        exact_matched_differences_checked=matches_checked,
        explicit_dummy_ols_checked=len(independent_ols),
        max_dummy_error=max(x["error"] for x in independent_ols),
        bootstrap_quantile_rows_checked=len(estimates),
        annual_mean_rows_checked=len(annual),
        runner_distribution_rows_checked=len(distribution),
        grade_change_rows_checked=grade_checks,
        recent_year_change_rows_checked=year_checks,
        era_mix_rows_checked=len(mix),
        membership_and_partial_year_filters_checked=True,
        additive_sections_checked=True,
    )
    (OUT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
