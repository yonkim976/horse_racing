"""Independent source, paired-bootstrap and SQL matching verification."""

import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "20261007_seasonal_same_moisture/outputs"
OUT = HERE / "outputs"
KEY = ["meet", "distance_m", "band", "part"]


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    for name, value in summary["input_sha256"].items():
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == value
    d = pd.read_csv(OUT / "monthly_levels.csv", dtype={"label": str})
    source = pd.read_csv(SOURCE / "controlled_month_season_contrasts.csv", dtype={"label": str})
    source = source.loc[source.kind.eq("month")].sort_values(KEY + ["label"]).reset_index(drop=True)
    actual = d.sort_values(KEY + ["label"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(actual[source.columns], source)
    assert d.month.between(1, 12).all() and len(d) == 8208
    assert (
        d.interpretation_support == (d.status.eq("supported") & d.bootstrap_valid_n.ge(180))
    ).all()
    p = d.pivot(index=["meet", "distance_m", "band", "month"], columns="part", values="difference")
    np.testing.assert_allclose(
        p.finish, p[["early", "middle1", "middle2", "late"]].sum(axis=1, min_count=4), atol=1e-10
    )
    np.testing.assert_allclose(p.last600, p.middle2 + p.late, atol=1e-10)
    boot = pd.read_parquet(SOURCE / "date_bootstrap_contrasts.parquet")
    boot = boot.loc[boot.kind.eq("month")].copy()
    boot["month"] = boot.label.astype(int)
    # Independent long-table merge; target/reference must use the same replicate.
    tables = {k: g for k, g in boot.groupby(KEY, observed=True)}
    points = d.set_index(KEY + ["month"])
    pairs = pd.read_csv(OUT / "paired_month_differences.csv")
    n = 0
    for row in pairs.itertuples(index=False):
        key = tuple(getattr(row, k) for k in KEY)
        group = tables.get(key)
        values = np.array([])
        if group is not None:
            left = group.loc[group.month.eq(row.target_month), ["replicate", "difference"]]
            right = group.loc[group.month.eq(row.reference_month), ["replicate", "difference"]]
            join = left.merge(right, on="replicate", validate="one_to_one")
            values = (join.difference_x - join.difference_y).dropna().to_numpy()
        assert len(values) == row.bootstrap_valid_n
        ci = np.percentile(values, [2.5, 97.5]) if len(values) >= 180 else [np.nan, np.nan]
        np.testing.assert_allclose(ci, [row.ci_low, row.ci_high], atol=1e-10, equal_nan=True)
        expected = (
            points.loc[key + (row.target_month,), "difference"]
            - points.loc[key + (row.reference_month,), "difference"]
        )
        np.testing.assert_allclose(expected, row.difference, atol=1e-10, equal_nan=True)
        n += 1
    races = pd.read_parquet(SOURCE / "race_means.parquet")
    con = duckdb.connect()
    con.register("races", races)
    sql = con.execute("""
        WITH expanded AS (
            SELECT *, band AS selected_band FROM races WHERE year <= 2025
            UNION ALL
            SELECT *, '전체' AS selected_band FROM races WHERE year <= 2025
        ), t AS (
            SELECT meet,distance_m,selected_band AS band,year,month,grade,moisture,
                avg(finish) AS target_mean,count(*) AS target_races
            FROM expanded WHERE month BETWEEN 3 AND 11 GROUP BY ALL
        ), w AS (
            SELECT meet,distance_m,selected_band AS band,year,grade,moisture,
                avg(finish) AS winter_mean,count(*) AS winter_races
            FROM expanded WHERE month IN (12,1,2) GROUP BY ALL
        ) SELECT t.*,w.winter_mean,w.winter_races,
            target_races*1.0*winter_races/(target_races+winter_races) AS weight,
            target_mean-winter_mean AS difference
          FROM t JOIN w USING(meet,distance_m,band,year,grade,moisture)
    """).df()
    strata = pd.read_csv(OUT / "yearly_matched_strata.csv", dtype={"grade": str})
    strata_keys = ["meet", "distance_m", "band", "year", "month", "grade", "moisture"]
    sql = sql.sort_values(strata_keys).reset_index(drop=True)
    strata = strata.sort_values(strata_keys).reset_index(drop=True)
    assert len(sql) == len(strata)
    pd.testing.assert_frame_equal(sql[strata_keys], strata[strata_keys], check_dtype=False)
    for column in [
        "target_mean",
        "target_races",
        "winter_mean",
        "winter_races",
        "weight",
        "difference",
    ]:
        np.testing.assert_allclose(sql[column], strata[column], atol=1e-10)
    annual = pd.read_csv(OUT / "yearly_monthly_matches.csv")
    con.register("strata", sql)
    aggregate = con.execute("""
        SELECT meet,distance_m,band,year,month,
        sum(difference*weight)/sum(weight) AS difference,
        count(*) AS matched_strata,sum(target_races) AS target_races,
        sum(winter_races) AS winter_races
        FROM strata GROUP BY ALL
    """).df()
    join = annual.merge(
        aggregate, on=["meet", "distance_m", "band", "year", "month"], suffixes=("_out", "_sql")
    )
    assert len(join) == annual.difference.notna().sum()
    for column in ["difference", "matched_strata", "target_races", "winter_races"]:
        np.testing.assert_allclose(join[column + "_out"], join[column + "_sql"], atol=1e-10)
    expected_support = (
        annual.matched_strata.ge(2)
        & annual.target_races.ge(3)
        & annual.winter_races.ge(3)
        & annual.target_days.ge(2)
        & annual.winter_days.ge(2)
    )
    assert (annual.descriptive_support == expected_support).all()
    # Independently count matched dates using raw races, including all exact-grade/pct keys.
    raw = races.loc[
        races.year.le(2025),
        ["meet", "distance_m", "year", "month", "grade", "moisture", "date", "band"],
    ]
    expanded = pd.concat([raw, raw.assign(band="전체")], ignore_index=True)
    counts = []
    for keys, matched in sql.groupby(
        ["meet", "distance_m", "band", "year", "month"], observed=True
    ):
        meet, distance, band, year, month = keys
        part = expanded.loc[
            expanded.meet.eq(meet)
            & expanded.distance_m.eq(distance)
            & expanded.band.eq(band)
            & expanded.year.eq(year)
        ]
        joined = part.merge(
            matched[["grade", "moisture"]], on=["grade", "moisture"], validate="many_to_one"
        )
        counts.append(
            dict(zip(["meet", "distance_m", "band", "year", "month"], keys, strict=True))
            | dict(
                target_days=int(joined.loc[joined.month.eq(month), "date"].nunique()),
                winter_days=int(joined.loc[joined.month.isin([12, 1, 2]), "date"].nunique()),
            )
        )
    counted = annual.merge(
        pd.DataFrame(counts),
        on=["meet", "distance_m", "band", "year", "month"],
        suffixes=("_out", "_raw"),
    )
    for column in ["target_days", "winter_days"]:
        assert (counted[column + "_out"] == counted[column + "_raw"]).all()
    stability = pd.read_csv(OUT / "monthly_year_stability.csv")
    annual_indexed = annual.set_index(["meet", "distance_m", "band", "month"])
    for row in stability.itertuples(index=False):
        group = annual_indexed.loc[[(row.meet, row.distance_m, row.band, row.month)]]
        eligible = group.loc[group.descriptive_support]
        assert row.eligible_years == len(eligible)
        assert row.faster_years == eligible.difference.lt(0).sum()
        assert row.slower_years == eligible.difference.gt(0).sum()
        np.testing.assert_allclose(
            [row.median_difference, row.minimum, row.maximum],
            [eligible.difference.median(), eligible.difference.min(), eligible.difference.max()],
            atol=1e-10,
            equal_nan=True,
        )
    recent = pd.read_csv(OUT / "recent_monthly_levels.csv", dtype={"label": str})
    old_recent = pd.read_csv(SOURCE / "recent_complete_year_contrasts.csv", dtype={"label": str})
    old_recent = (
        old_recent.loc[old_recent.kind.eq("month")]
        .sort_values(KEY + ["label"])
        .reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(
        recent.sort_values(KEY + ["label"]).reset_index(drop=True)[old_recent.columns], old_recent
    )
    assert (
        not recent.uncertainty_available.any()
    )  # No bootstrap was run for the source's 2-year fit.
    for name, value in summary["input_sha256"].items():
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == value
    result = dict(
        passed=True,
        source_hashes_unchanged=True,
        original_monthly_rows_checked=len(d),
        paired_contrasts_checked=n,
        sql_matched_strata_checked=len(strata),
        annual_aggregates_checked=len(join),
        annual_date_counts_checked=len(counted),
        annual_direction_summaries_checked=len(stability),
        additive_sections_checked=True,
        recent_source_alignment=True,
        inherited_original_population_and_ols_verification_passed=True,
    )
    (OUT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
