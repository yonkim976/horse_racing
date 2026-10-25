"""Seasonal differences within year, race grade and exact numeric moisture; read-only inputs."""

# ruff: noqa: E501

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
BANDS = ["건조", "양호", "다습", "포화", "불량"]
SEASONS = {"겨울": [12, 1, 2], "봄": [3, 4, 5], "여름": [6, 7, 8], "가을": [9, 10, 11]}
CORE = ["early", "middle1", "middle2", "late"]
PARTS = CORE + ["finish", "last600"]
NUMS = [
    "age",
    "weight",
    "rating",
    "prior_finish",
    "prior_top3",
    "prior_early",
    "log_starts",
    "log_gap",
]
BOOT = 200
SEED = 20261007
INPUTS = [
    HERE.parent / "20261003_sectional_pace_moisture/outputs/population.parquet",
    *[
        HERE.parent / f"{name}/outputs/population.parquet"
        for name in [
            "20261005_1300_benchmarks",
            "20261005_1400_benchmarks",
            "20261006_1600_benchmarks",
        ]
    ],
    *[
        HERE.parent / f"20261006_1700_1800_benchmarks/{d}/outputs/population.parquet"
        for d in [1700, 1800]
    ],
    *[
        HERE.parent / f"20261006_remaining_distance_benchmarks/{d}/outputs/population.parquet"
        for d in [1000, 1900, 2000, 2200, 2300]
    ],
]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def load():
    pieces = []
    for i, p in enumerate(INPUTS):
        assert p.resolve().is_relative_to(ROOT)
        d = pd.read_parquet(p)
        if i == 0:
            d = d[d.population.eq("실전1200")].copy()
            d["distance_m"] = 1200
        d["date"] = pd.to_datetime(d.date)
        d["rating"] = d.rating.mask(d.rating.le(0))
        d["grade"] = d.grade.astype(str)
        d["month"] = d.date.dt.month
        d["year"] = d.date.dt.year
        d["season"] = d.month.map({m: s for s, ms in SEASONS.items() for m in ms})
        d["input_path"] = str(p.relative_to(ROOT))
        fields = [
            "meet",
            "distance_m",
            "date",
            "year",
            "month",
            "season",
            "grade",
            "band",
            "moisture",
            "source_key",
            "row_key",
            "sex",
            *NUMS,
            *PARTS,
            "last400",
            "last_history_date",
            "input_path",
        ]
        pieces.append(d[fields])
    d = pd.concat(pieces, ignore_index=True)
    assert not d.row_key.duplicated().any()
    assert set(d.meet) == {"서울", "부산"} and set(d.band) == set(BANDS)
    assert d.moisture.notna().all() and np.allclose(d.moisture, d.moisture.round())
    expected = d.moisture.map(
        lambda v: (
            "건조"
            if v <= 5
            else "양호"
            if v <= 9
            else "다습"
            if v <= 14
            else "포화"
            if v <= 19
            else "불량"
        )
    )
    assert expected.eq(d.band).all()
    assert np.allclose(d[CORE].sum(axis=1), d.finish)
    assert np.allclose(d.middle2 + d.late, d.last600)
    prior = pd.to_datetime(d.last_history_date)
    assert (prior[prior.notna()] < d.loc[prior.notna(), "date"]).all()
    d.to_parquet(OUT / "population.parquet", index=False)
    consistency = d.groupby("source_key")[
        ["meet", "distance_m", "date", "grade", "band", "moisture"]
    ].nunique()
    assert consistency.eq(1).all().all()
    sex_columns = []
    for sex in sorted(d.sex.dropna().astype(str).unique()):
        col = "sex_share_" + sex
        d[col] = d.sex.astype(str).eq(sex).astype(float)
        sex_columns.append(col)
    for col in NUMS:
        d[col + "_missing"] = d[col].isna().astype(float)
    aggs = {
        k: "first"
        for k in [
            "meet",
            "distance_m",
            "date",
            "year",
            "month",
            "season",
            "grade",
            "band",
            "moisture",
        ]
    }
    aggs.update(
        {
            k: "mean"
            for k in [*PARTS, "last400", *NUMS, *sex_columns, *[c + "_missing" for c in NUMS]]
        }
    )
    aggs["row_key"] = "size"
    races = (
        d.groupby("source_key", sort=False)
        .agg(aggs)
        .reset_index()
        .rename(columns={"row_key": "runner_n"})
    )
    races.to_parquet(OUT / "race_means.parquet", index=False)
    return d, races, sex_columns


def distribution(d, races):
    counts = []
    for period, subset in [
        ("all_2018_2026", races),
        ("recent_2024_2026", races[races.year.ge(2024)]),
        ("complete_2024_2025", races[races.year.isin([2024, 2025])]),
    ]:
        for (meet, season), g in subset.groupby(["meet", "season"]):
            for band in BANDS:
                h = g[g.band.eq(band)]
                counts.append(
                    dict(
                        period=period,
                        meet=meet,
                        season=season,
                        band=band,
                        races=len(h),
                        all_season_races=len(g),
                        share=len(h) / len(g),
                        runner_n=int(h.runner_n.sum()),
                        days=h.date.nunique(),
                    )
                )
    pd.DataFrame(counts).to_csv(OUT / "seasonal_state_mix.csv", index=False)
    descriptions = []
    for period, subset in [("all_2018_2026", d), ("recent_2024_2026", d[d.year.ge(2024)])]:
        for keys, g in subset.groupby(["meet", "distance_m", "grade", "band", "season"]):
            meet, distance, grade, band, season = keys
            for part in [*PARTS, "last400"]:
                v = g[part].dropna()
                if not len(v):
                    continue
                descriptions.append(
                    dict(
                        period=period,
                        meet=meet,
                        distance_m=distance,
                        grade=grade,
                        band=band,
                        season=season,
                        part=part,
                        n=len(v),
                        races=g.source_key.nunique(),
                        days=g.date.nunique(),
                        years=g.year.nunique(),
                        mean=v.mean(),
                        median=v.median(),
                        p20=v.quantile(0.2),
                        p80=v.quantile(0.8),
                    )
                )
    pd.DataFrame(descriptions).to_csv(OUT / "observed_seasonal_distributions.csv", index=False)
    monthly = (
        races.groupby(["meet", "distance_m", "band", "year", "month"])
        .agg(
            races=("source_key", "size"),
            days=("date", "nunique"),
            runner_n=("runner_n", "sum"),
            race_mean_finish=("finish", "mean"),
        )
        .reset_index()
    )
    monthly.to_csv(OUT / "observed_monthly_race_means.csv", index=False)


def matched_details(races, exact=True):
    strata = ["year", "grade", "moisture"] if exact else ["year", "grade", "band"]
    rows = []
    for (meet, distance), g in races.groupby(["meet", "distance_m"]):
        for band, source in [("전체", g), *[(b, g[g.band.eq(b)]) for b in BANDS]]:
            for season in ["봄", "여름", "가을"]:
                pair = source[source.season.isin(["겨울", season])]
                for key, h in pair.groupby(strata):
                    winter = h[h.season.eq("겨울")]
                    target = h[h.season.eq(season)]
                    if winter.empty or target.empty:
                        continue
                    n0, n1 = len(winter), len(target)
                    w = n0 * n1 / (n0 + n1)
                    for part in PARTS:
                        rows.append(
                            dict(
                                meet=meet,
                                distance_m=distance,
                                band=band,
                                season=season,
                                method="same_exact_moisture" if exact else "same_band",
                                year=key[0],
                                grade=key[1],
                                moisture=key[2] if exact else np.nan,
                                stratum_band=key[2] if not exact else winter.band.iloc[0],
                                part=part,
                                winter_races=n0,
                                target_races=n1,
                                winter_days=winter.date.nunique(),
                                target_days=target.date.nunique(),
                                weight=w,
                                winter_mean=winter[part].mean(),
                                target_mean=target[part].mean(),
                                difference=target[part].mean() - winter[part].mean(),
                            )
                        )
    return pd.DataFrame(rows)


def paired_summary(details):
    rows = []
    for keys, g in details.groupby(["meet", "distance_m", "band", "season", "method", "part"]):
        rows.append(
            dict(
                zip(["meet", "distance_m", "band", "season", "method", "part"], keys, strict=True),
                strata=len(g),
                years=g.year.nunique(),
                winter_races=int(g.winter_races.sum()),
                target_races=int(g.target_races.sum()),
                difference=float(np.average(g.difference, weights=g.weight)),
            )
        )
    return pd.DataFrame(rows)


def demean(matrix, groups, weight):
    sizes = np.bincount(groups, weights=weight)
    sums = np.zeros((len(sizes), matrix.shape[1]))
    np.add.at(sums, groups, matrix * weight[:, None])
    means = np.divide(sums, sizes[:, None], out=np.zeros_like(sums), where=sizes[:, None] > 0)
    return matrix - means[groups]


def within_fit(x, y, groups, weight):
    xx = demean(x, groups, weight)
    yy = demean(y, groups, weight)
    gram = xx.T @ (weight[:, None] * xx)
    inverse = np.linalg.pinv(gram, rcond=1e-10, hermitian=True)
    coef = inverse @ (xx.T @ (weight[:, None] * yy))
    return coef, inverse @ gram, xx, yy, inverse


def contrasts(width):
    rows = []
    winter = np.zeros(width)
    winter[np.array(SEASONS["겨울"]) - 1] = 1 / 3
    for m in range(1, 13):
        c = np.zeros(width)
        c[m - 1] = 1
        rows.append(("month", str(m), c - winter))
    for season, months in SEASONS.items():
        if season == "겨울":
            continue
        c = np.zeros(width)
        c[np.array(months) - 1] = 1 / 3
        rows.append(("season", season, c - winter))
    return rows


def estimate(
    races, sex_columns, boot=0, mode="exact_moisture", controls=True, period="all_2018_2026"
):
    estimates, models, coefs, bootstrap_rows = [], [], [], []
    for (meet, distance), g0 in races.groupby(["meet", "distance_m"]):
        for band, g in [("전체", g0), *[(b, g0[g0.band.eq(b)]) for b in BANDS]]:
            groups_cols = (
                ["year", "grade", "moisture"]
                if mode == "exact_moisture"
                else ["year", "grade", "band"]
            )
            count = (
                g.groupby(groups_cols).month.transform("nunique")
                if len(g)
                else pd.Series(dtype=float)
            )
            g = g[count.ge(2)].copy().reset_index(drop=True)
            model_key = dict(
                period=period,
                mode=mode,
                controls=controls,
                meet=meet,
                distance_m=int(distance),
                band=band,
            )
            models.append(
                dict(
                    **model_key,
                    total_races=len(g0) if band == "전체" else int(g0.band.eq(band).sum()),
                    informative_races=len(g),
                    days=g.date.nunique(),
                    years=g.year.nunique(),
                    months=g.month.nunique(),
                    strata=g.groupby(groups_cols).ngroups,
                )
            )
            if g.empty:
                for kind, label, _ in contrasts(12):
                    for part in PARTS:
                        estimates.append(
                            dict(
                                **model_key,
                                kind=kind,
                                label=label,
                                part=part,
                                difference=np.nan,
                                status="no_within_stratum_month_overlap",
                                informative_races=0,
                                days=0,
                                years=0,
                                bootstrap_valid_n=0,
                                ci_low=np.nan,
                                ci_high=np.nan,
                                cluster_ci_low=np.nan,
                                cluster_ci_high=np.nan,
                            )
                        )
                continue
            x = np.eye(12)[g.month.to_numpy() - 1]
            names = [f"month_{m}" for m in range(1, 13)]
            if controls:
                cols = [*NUMS, "runner_n", *sex_columns, *[c + "_missing" for c in NUMS]]
                z = g[cols].copy()
                for col in cols:
                    median = z[col].median()
                    z[col] = z[col].fillna(0 if pd.isna(median) else median)
                zz = z.to_numpy(dtype=float)
                scale = zz.std(axis=0)
                scale[scale < 1e-10] = 1
                x = np.column_stack([x, (zz - zz.mean(axis=0)) / scale])
                names.extend(cols)
            y = g[CORE].to_numpy()
            keys = g[groups_cols].astype(str).agg("|".join, axis=1)
            groups = pd.factorize(keys, sort=True)[0]
            coef, projection, xx, yy, inverse = within_fit(x, y, groups, np.ones(len(g)))
            contrasts_info = contrasts(x.shape[1])
            cc = np.array([c for _, _, c in contrasts_info])
            identifiable = np.max(np.abs(cc - cc @ projection), axis=1) < 1e-7
            score = xx[:, :, None] * (yy - xx @ coef)[:, None, :]
            dates, date_values = pd.factorize(g.date, sort=True)
            cluster_scores = np.zeros((len(date_values), x.shape[1], len(CORE)))
            np.add.at(cluster_scores, dates, score)
            # Sandwich covariance after exact-stratum fixed effects; date is the cluster.
            rank = int(np.linalg.matrix_rank(xx, tol=1e-7))
            df_res = len(g) - len(np.unique(groups)) - rank
            adjustment = (
                (len(date_values) / (len(date_values) - 1)) * (len(g) - 1) / df_res
                if len(date_values) > 1 and df_res > 0
                else np.nan
            )
            targets = {
                **{p: np.eye(4)[i] for i, p in enumerate(CORE)},
                "finish": np.ones(4),
                "last600": np.array([0, 0, 1, 1]),
            }
            boot_values = np.full((boot, len(cc), len(CORE)), np.nan)
            if boot:
                rng = np.random.default_rng(
                    SEED
                    + int(distance)
                    + (1 if meet == "서울" else 3) * 10000
                    + BANDS.index(band) * 100
                    if band != "전체"
                    else SEED + int(distance) + (1 if meet == "서울" else 3) * 10000
                )
                year_date_codes = [
                    np.unique(dates[g.year.eq(year)]) for year in sorted(g.year.unique())
                ]
                for b in range(boot):
                    date_counts = np.zeros(len(date_values))
                    for idx in year_date_codes:
                        picked = rng.choice(idx, size=len(idx), replace=True)
                        date_counts += np.bincount(picked, minlength=len(date_values))
                    beta, proj, _, _, _ = within_fit(x, y, groups, date_counts[dates])
                    good = np.max(np.abs(cc - cc @ proj), axis=1) < 1e-7
                    boot_values[b, good] = cc[good] @ beta
                print(
                    f"{meet} {distance}m {band}: {len(g)} informative races; bootstrap {boot}",
                    flush=True,
                )
            for i, (kind, label, c) in enumerate(contrasts_info):
                target_months = [int(label)] if kind == "month" else SEASONS[label]
                winter_months = SEASONS["겨울"]
                target = g[g.month.isin(target_months)]
                winter = g[g.month.isin(winter_months)]
                support = (
                    min(target.date.nunique(), winter.date.nunique()) >= 10
                    and min(target.year.nunique(), winter.year.nunique()) >= 3
                    and len(g) >= 100
                )
                for part, vector in targets.items():
                    delta = float(c @ coef @ vector) if identifiable[i] else np.nan
                    cl = c @ inverse
                    u = cluster_scores @ vector
                    se = (
                        np.sqrt(max(0, float(np.square(u @ cl).sum() * adjustment)))
                        if np.isfinite(adjustment)
                        else np.nan
                    )
                    margin = student_t.ppf(0.975, max(1, len(date_values) - 1)) * se
                    ci0, ci1 = (
                        (delta - margin, delta + margin)
                        if identifiable[i] and len(date_values) >= 20
                        else (np.nan, np.nan)
                    )
                    valid = (
                        np.isfinite(boot_values[:, i]).all(axis=1)
                        if boot
                        else np.zeros(0, dtype=bool)
                    )
                    count_valid = int(valid.sum())
                    q = (
                        np.quantile(boot_values[valid, i] @ vector, [0.025, 0.975])
                        if count_valid >= 0.9 * boot and boot > 0
                        else [np.nan, np.nan]
                    )
                    status = (
                        "not_identifiable"
                        if not identifiable[i]
                        else "supported"
                        if support
                        else "limited_support"
                    )
                    estimates.append(
                        dict(
                            **model_key,
                            kind=kind,
                            label=label,
                            part=part,
                            difference=delta,
                            status=status,
                            informative_races=len(g),
                            days=g.date.nunique(),
                            years=g.year.nunique(),
                            target_races=len(target),
                            winter_races=len(winter),
                            target_days=target.date.nunique(),
                            winter_days=winter.date.nunique(),
                            target_years=target.year.nunique(),
                            winter_years=winter.year.nunique(),
                            bootstrap_valid_n=count_valid,
                            ci_low=q[0],
                            ci_high=q[1],
                            cluster_ci_low=ci0,
                            cluster_ci_high=ci1,
                        )
                    )
                    if boot:
                        for b in range(boot):
                            value = float(boot_values[b, i] @ vector) if valid[b] else np.nan
                            bootstrap_rows.append(
                                dict(
                                    **model_key,
                                    kind=kind,
                                    label=label,
                                    part=part,
                                    replicate=b,
                                    difference=value,
                                )
                            )
            for i, name in enumerate(names):
                for j, part in enumerate(CORE):
                    coefs.append(
                        dict(
                            **model_key,
                            feature=name,
                            part=part,
                            coefficient=coef[i, j],
                            design_rank=rank,
                            design_columns=x.shape[1],
                        )
                    )
    return (
        pd.DataFrame(estimates),
        pd.DataFrame(models),
        pd.DataFrame(coefs),
        pd.DataFrame(bootstrap_rows),
    )


def main():
    if (OUT / "summary.json").exists() or (OUT / "population.parquet").exists():
        raise FileExistsError("Completed outputs are immutable; use a new run directory")
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in INPUTS}
    d, races, sex_columns = load()
    print(f"Population: {len(d)} runner records, {len(races)} races", flush=True)
    distribution(d, races)
    details = pd.concat(
        [matched_details(races, exact=False), matched_details(races, exact=True)], ignore_index=True
    )
    details.to_csv(OUT / "matched_stratum_contrasts.csv", index=False)
    paired = paired_summary(details)
    paired.to_csv(OUT / "matched_season_contrasts.csv", index=False)
    yearly = []
    exact = details[details.method.eq("same_exact_moisture")]
    for keys, g in exact.groupby(["meet", "distance_m", "band", "season", "part", "year"]):
        yearly.append(
            dict(
                zip(["meet", "distance_m", "band", "season", "part", "year"], keys, strict=True),
                strata=len(g),
                winter_races=int(g.winter_races.sum()),
                target_races=int(g.target_races.sum()),
                difference=float(np.average(g.difference, weights=g.weight)),
            )
        )
    pd.DataFrame(yearly).to_csv(OUT / "yearly_exact_moisture_contrasts.csv", index=False)
    tables, support, coefs, boots = estimate(races, sex_columns, boot=BOOT)
    tables.to_csv(OUT / "controlled_month_season_contrasts.csv", index=False)
    support.to_csv(OUT / "model_support.csv", index=False)
    coefs.to_csv(OUT / "model_coefficients.csv", index=False)
    boots.to_parquet(OUT / "date_bootstrap_contrasts.parquet", index=False)
    # Complete recent years test whether the long-run pattern persists without the truncated 2026 autumn.
    recent, rs, rc, _ = estimate(
        races[races.year.isin([2024, 2025])], sex_columns, period="complete_2024_2025"
    )
    recent.to_csv(OUT / "recent_complete_year_contrasts.csv", index=False)
    rs.to_csv(OUT / "recent_model_support.csv", index=False)
    # A no-participant-controls version shows whether the seasonal association changes with entry composition.
    sensitivity, _, _, _ = estimate(races, sex_columns, controls=False)
    sensitivity.to_csv(OUT / "uncontrolled_exact_moisture_contrasts.csv", index=False)
    assert hashes == {str(p.relative_to(ROOT)): sha(p) for p in INPUTS}
    summary = dict(
        created_on="2026-10-07",
        version="seasonal_same_moisture_v1",
        inputs=hashes,
        input_n=len(d),
        race_n=len(races),
        date_n=d[["meet", "date"]].drop_duplicates().shape[0],
        distances=sorted(d.distance_m.astype(int).unique().tolist()),
        input_start={m: str(g.date.min().date()) for m, g in d.groupby("meet")},
        input_end={m: str(g.date.max().date()) for m, g in d.groupby("meet")},
        seasons=SEASONS,
        reference="winter mean of Dec/Jan/Feb; each month equal weight",
        matching="same venue/distance/year/race grade/exact integer moisture percentage; rows with >=2 months in stratum",
        race_weight="one retained race mean per race; runners not independent weather exposures",
        controls=NUMS + ["runner_n"] + sex_columns + ["missing-value fractions"],
        bootstrap=dict(
            replicates=BOOT,
            seed=SEED,
            cluster="date within venue, sampled with replacement separately within each calendar year",
            fixed_preprocessing=True,
            recomputed_weighted_stratum_means=True,
            min_valid=180,
        ),
        supported_threshold=">=100 informative races; target and winter each >=10 dates and >=3 years; contrast estimable",
        uncertainty="pointwise 95% intervals; not adjusted for all monthly/state/section comparisons",
        recent_sensitivity="complete calendar years 2024 and 2025; 2026 not a full annual cycle",
        incomplete_2026_months=[10, 11, 12],
        prior_benchmarks_changed=False,
        interpretation="conditional seasonal association in historical race-mean records, not causal heat/cold or an adopted record correction",
        software=dict(numpy=np.__version__, pandas=pd.__version__),
    )
    json_write(OUT / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
