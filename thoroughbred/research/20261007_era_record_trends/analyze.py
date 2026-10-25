"""Era comparisons within race-grade, exact-moisture and month strata; read-only inputs."""

# ruff: noqa: E501
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "20261007_seasonal_same_moisture/outputs"
OUT = HERE / "outputs"
CORE = ["early", "middle1", "middle2", "late"]
RATIOS = ["early_relative_pct", "late_relative_pct", "last600_relative_pct"]
PARTS = CORE + ["finish", "last600"] + RATIOS
YCOLS = CORE + RATIOS
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
STRATA = ["grade", "moisture", "month"]
WINDOWS = {
    "common_jan_aug": (range(2018, 2024), range(2024, 2027), range(1, 9)),
    "complete_2024_2025": (range(2018, 2024), range(2024, 2026), range(1, 13)),
    "nearby_complete": (range(2021, 2024), range(2024, 2026), range(1, 13)),
    "all_available_partial_2026": (range(2018, 2024), range(2024, 2027), range(1, 13)),
}
BOOT = 200
SEED = 20261007


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load():
    inputs = ["population.parquet", "race_means.parquet", "summary.json", "verification.json"]
    hashes = {name: sha(SOURCE / name) for name in inputs}
    assert json.loads((SOURCE / "verification.json").read_text())["passed"]
    p = pd.read_parquet(SOURCE / "population.parquet")
    races = pd.read_parquet(SOURCE / "race_means.parquet")
    for name, length, time in [
        (RATIOS[0], 200, "early"),
        (RATIOS[1], 200, "late"),
        (RATIOS[2], 600, "last600"),
    ]:
        p[name] = 100 * length * p.finish / (p.distance_m * p[time])
    ratios = p.groupby("source_key")[RATIOS].mean()
    races = races.join(ratios, on="source_key", validate="one_to_one")
    assert len(p) == 151074 and len(races) == 13928
    assert np.allclose(races[CORE].sum(axis=1), races.finish)
    assert p.rating.dropna().gt(0).all()
    races.to_parquet(OUT / "analysis_race_means.parquet", index=False)
    return p, races, hashes


def select(races, window, band="전체"):
    before, after, months = WINDOWS[window]
    g = races.loc[races.year.isin([*before, *after]) & races.month.isin(months)].copy()
    if band != "전체":
        g = g.loc[g.band.eq(band)].copy()
    g["era"] = g.year.isin(after).astype(int)
    overlap = g.groupby(STRATA, observed=True).era.transform("nunique").eq(2)
    return g, g.loc[overlap].reset_index(drop=True)


def demean(a, groups, weights):
    counts = np.bincount(groups, weights=weights)
    sums = np.zeros((len(counts), a.shape[1]))
    np.add.at(sums, groups, a * weights[:, None])
    means = np.divide(sums, counts[:, None], out=np.zeros_like(sums), where=counts[:, None] > 0)
    return a - means[groups]


def design(g, controls):
    x = g[["era"]].to_numpy(dtype=float)
    if controls:
        columns = (
            NUMS
            + ["runner_n"]
            + [c for c in g if c.startswith("sex_share_")]
            + [c + "_missing" for c in NUMS]
        )
        z = g[columns].copy()
        z = z.fillna(z.median()).fillna(0).to_numpy(dtype=float)
        sd = z.std(axis=0)
        sd[sd < 1e-10] = 1
        x = np.column_stack([x, (z - z.mean(axis=0)) / sd])
    groups = pd.factorize(pd.MultiIndex.from_frame(g[STRATA]), sort=True)[0]
    return x, g[YCOLS].to_numpy(dtype=float), groups


def fit(x, y, groups, w):
    xx, yy = demean(x, groups, w), demean(y, groups, w)
    gram = xx.T @ (xx * w[:, None])
    inv = np.linalg.pinv(gram, rcond=1e-10, hermitian=True)
    coef = inv @ (xx.T @ (yy * w[:, None]))
    c = np.zeros(x.shape[1])
    c[0] = 1
    identified = np.max(np.abs(c - c @ inv @ gram)) < 1e-7
    rank = np.linalg.matrix_rank(xx * np.sqrt(w[:, None]), tol=1e-7)
    residual_df = np.count_nonzero(w) - np.count_nonzero(np.bincount(groups, weights=w)) - rank
    return coef[0] if identified else np.full(y.shape[1], np.nan), identified, int(residual_df)


def expand(values):
    # First four columns are independent section times; other columns are ratios in %.
    return np.concatenate([values[:4], [values[:4].sum(), values[2:4].sum()], values[4:]])


def estimate(races):
    rows, boot_rows, supports, stratum_rows, memberships = [], [], [], [], []
    for (meet, distance), source in races.groupby(["meet", "distance_m"], observed=True):
        for wi, window in enumerate(WINDOWS):
            for bi, band in enumerate(["전체", "건조"] if window == "common_jan_aug" else ["전체"]):
                raw, g = select(source, window, band)
                key = dict(meet=meet, distance_m=int(distance), window=window, band=band)
                before, after = g.loc[g.era.eq(0)], g.loc[g.era.eq(1)]
                nstrata = g.groupby(STRATA, observed=True).ngroups
                info = dict(
                    **key,
                    total_races=len(raw),
                    informative_races=len(g),
                    strata=nstrata,
                    before_races=len(before),
                    recent_races=len(after),
                    before_days=before.date.nunique(),
                    recent_days=after.date.nunique(),
                    before_years=before.year.nunique(),
                    recent_years=after.year.nunique(),
                    before_overlap_share=len(before) / max(1, raw.era.eq(0).sum()),
                    recent_overlap_share=len(after) / max(1, raw.era.eq(1).sum()),
                )
                supports.append(info)
                memberships.extend(
                    key | dict(source_key=r.source_key, era=int(r.era)) for r in g.itertuples()
                )
                if len(g):
                    strata = (
                        g.groupby(STRATA + ["era"], observed=True)
                        .agg(n=("source_key", "size"), **{p: (p, "mean") for p in PARTS})
                        .reset_index()
                    )
                    stratum_rows.extend(key | r for r in strata.to_dict("records"))
                for controls in [False, True]:
                    spec = "composition_adjusted" if controls else "exact_matched"
                    delta, valid, df = np.full(len(YCOLS), np.nan), False, 0
                    reps = np.full((BOOT, len(PARTS)), np.nan)
                    if len(g):
                        x, y, groups = design(g, controls)
                        delta, valid, df = fit(x, y, groups, np.ones(len(g)))
                        codes, dates = pd.factorize(g.date, sort=True)
                        year_dates = [
                            np.unique(codes[g.year.eq(year)]) for year in sorted(g.year.unique())
                        ]
                        rng = np.random.default_rng(
                            SEED
                            + int(distance) * 100
                            + (1 if meet == "서울" else 2) * 100000
                            + wi * 10
                            + bi
                        )
                        for b in range(BOOT):
                            counts = np.zeros(len(dates))
                            for ix in year_dates:
                                picked = rng.choice(ix, size=len(ix), replace=True)
                                counts += np.bincount(picked, minlength=len(dates))
                            beta, good, rdf = fit(x, y, groups, counts[codes])
                            if good and rdf > 0:
                                reps[b] = expand(beta)
                    point = expand(delta)
                    nvalid = int(np.isfinite(reps).all(axis=1).sum())
                    adequate = (
                        nstrata >= 20
                        and min(len(before), len(after)) >= 50
                        and min(before.date.nunique(), after.date.nunique()) >= 20
                        and min(before.year.nunique(), after.year.nunique()) >= 2
                        and valid
                        and df > 0
                    )
                    status = (
                        "not_identifiable"
                        if not valid
                        else "limited_support"
                        if not adequate
                        else "supported"
                    )
                    for j, part in enumerate(PARTS):
                        qq = (
                            np.quantile(reps[:, j][np.isfinite(reps[:, j])], [0.025, 0.975])
                            if nvalid >= 180
                            else [np.nan, np.nan]
                        )
                        rawdiff = (
                            raw.loc[raw.era.eq(1), part].mean()
                            - raw.loc[raw.era.eq(0), part].mean()
                        )
                        rows.append(
                            dict(
                                **info,
                                specification=spec,
                                part=part,
                                unit="percentage_points" if part in RATIOS else "seconds",
                                difference=point[j],
                                raw_difference=rawdiff,
                                status=status,
                                residual_df=df,
                                bootstrap_valid_n=nvalid,
                                ci_low=qq[0],
                                ci_high=qq[1],
                                interpretation_support=bool(adequate and nvalid >= 180),
                            )
                        )
                        boot_rows.extend(
                            dict(
                                **key,
                                specification=spec,
                                part=part,
                                replicate=b,
                                difference=reps[b, j],
                            )
                            for b in range(BOOT)
                        )
                print(
                    f"{meet} {distance}m {window} {band}: {len(g)} / {len(raw)} common-stratum races",
                    flush=True,
                )
    pd.DataFrame(rows).to_csv(OUT / "era_contrasts.csv", index=False)
    pd.DataFrame(boot_rows).to_parquet(OUT / "date_bootstrap_contrasts.parquet", index=False)
    pd.DataFrame(supports).to_csv(OUT / "overlap_support.csv", index=False)
    pd.DataFrame(stratum_rows).to_parquet(OUT / "exact_matched_strata.parquet", index=False)
    pd.DataFrame(memberships).to_parquet(OUT / "model_membership.parquet", index=False)


def descriptive(population, races):
    annual, mixes, individual, grades, recent_years = [], [], [], [], []
    for window, months in [("full_available", range(1, 13)), ("jan_aug", range(1, 9))]:
        g = races.loc[races.month.isin(months)]
        for keys, h in g.groupby(["meet", "distance_m", "year"], observed=True):
            annual.append(
                dict(zip(["meet", "distance_m", "year"], keys, strict=True))
                | dict(
                    window=window,
                    races=len(h),
                    runner_n=int(h.runner_n.sum()),
                    days=h.date.nunique(),
                    **{p: h[p].mean() for p in PARTS},
                )
            )
        p = population.loc[population.month.isin(months)]
        for keys, h in p.groupby(["meet", "distance_m", "year"], observed=True):
            for part in [*CORE, "finish", "last600"]:
                individual.append(
                    dict(zip(["meet", "distance_m", "year"], keys, strict=True))
                    | dict(
                        window=window,
                        part=part,
                        n=len(h),
                        mean=h[part].mean(),
                        p20=h[part].quantile(0.2),
                        median=h[part].median(),
                        p80=h[part].quantile(0.8),
                    )
                )
    for (meet, distance), source in races.groupby(["meet", "distance_m"], observed=True):
        raw, g = select(source, "common_jan_aug")
        for field in ["grade", "band"]:
            for (era, value), h in raw.groupby(["era", field], observed=True):
                mixes.append(
                    dict(
                        meet=meet,
                        distance_m=distance,
                        field=field,
                        era=era,
                        value=str(value),
                        races=len(h),
                        share=len(h) / raw.era.eq(era).sum(),
                    )
                )
        if len(g):
            s = (
                g.groupby(STRATA + ["era"], observed=True)
                .agg(n=("finish", "size"), **{p: (p, "mean") for p in PARTS})
                .unstack("era")
            )
            w = s["n"][0] * s["n"][1] / (s["n"][0] + s["n"][1])
            for grade, h in s.groupby(level="grade", observed=True):
                weights = w.loc[h.index]
                for part in PARTS:
                    grades.append(
                        dict(
                            meet=meet,
                            distance_m=distance,
                            grade=str(grade),
                            part=part,
                            strata=len(h),
                            before_races=int(h["n"][0].sum()),
                            recent_races=int(h["n"][1].sum()),
                            difference=np.average(h[part][1] - h[part][0], weights=weights),
                        )
                    )
        for year in [2024, 2025, 2026]:
            h = source.loc[
                source.month.le(8) & (source.year.le(2023) | source.year.eq(year))
            ].copy()
            h["era"] = h.year.eq(year).astype(int)
            h = h.loc[h.groupby(STRATA, observed=True).era.transform("nunique").eq(2)]
            if h.empty:
                continue
            s = (
                h.groupby(STRATA + ["era"], observed=True)
                .agg(n=("finish", "size"), **{p: (p, "mean") for p in PARTS})
                .unstack("era")
            )
            w = s["n"][0] * s["n"][1] / (s["n"][0] + s["n"][1])
            for part in PARTS:
                recent_years.append(
                    dict(
                        meet=meet,
                        distance_m=distance,
                        year=year,
                        part=part,
                        strata=len(s),
                        before_races=int(s["n"][0].sum()),
                        recent_races=int(s["n"][1].sum()),
                        difference=np.average(s[part][1] - s[part][0], weights=w),
                    )
                )
    for name, rows in [
        ("annual_race_means.csv", annual),
        ("annual_runner_distributions.csv", individual),
        ("era_grade_moisture_mix.csv", mixes),
        ("grade_matched_changes.csv", grades),
        ("recent_year_matched_changes.csv", recent_years),
    ]:
        pd.DataFrame(rows).to_csv(OUT / name, index=False)


def main():
    p, races, hashes = load()
    descriptive(p, races)
    estimate(races)
    assert hashes == {name: sha(SOURCE / name) for name in hashes}
    summary = dict(
        version="era_record_trends_v1",
        completed_on="2026-10-07",
        source_study="20261007_seasonal_same_moisture",
        runner_records=len(p),
        race_n=len(races),
        venue_distance_pairs=19,
        windows={
            k: dict(before_years=list(v[0]), recent_years=list(v[1]), months=list(v[2]))
            for k, v in WINDOWS.items()
        },
        main_window="common_jan_aug",
        strata=STRATA,
        bootstrap=dict(
            replicates=BOOT,
            seed=SEED,
            min_valid=180,
            cluster="date sampled separately within calendar year; fixed preprocessing; recomputed weighted stratum means",
        ),
        support=">=20 common strata; each era >=50 races,20 dates,2 years; contrast identifiable and residual df>0; bootstrap>=180 for interpretation_support",
        unit="seconds or percentage points for relative pace",
        source_sha256=hashes,
        previous_benchmarks_changed=False,
        adopted_correction=False,
        interpretation="observational historical cohort shift; not causal improvement, breed evolution or new operational correction",
    )
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    print("Analysis completed", flush=True)


if __name__ == "__main__":
    main()
