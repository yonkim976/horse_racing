# ruff: noqa: E501
"""Observed age profiles, matched within-horse changes and censored inactivity diagnostics."""

import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import t as student_t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
POP = HERE.parent / "20261007_sex_ability_gap/outputs/population.parquet"
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
CUT = pd.Timestamp("2026-09-18")
AGES = ["2", "3", "4", "5", "6", "7", "8+"]
PARTS = ["finish", "early", "middle1", "middle2", "late", "last600"]


def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(4194304), b""):
            h.update(b)
    return h.hexdigest()


def dump(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def codes(x):
    return pd.factorize(x)[0]


def weighted_within(x, group, w):
    x = np.asarray(x)
    if x.ndim == 1:
        x = x[:, None]
    sw = np.bincount(group, weights=w)
    means = np.column_stack([np.bincount(group, weights=w * a) / sw for a in x.T])
    return x - means[group], means


def cluster_cov(influence, labels, corr):
    group = codes(labels)
    n = int(group.max() + 1)
    sums = np.column_stack([np.bincount(group, weights=v) for v in influence.T])
    return sums.T @ sums * corr * (n / (n - 1) if n > 1 else 1), n


def design(g, grade=False):
    x, labels = [], []
    for age in AGES:
        if age != "4":
            x.append(g.age_bin.eq(age).to_numpy(float))
            labels.append("age:" + age)
    for sex in ["암", "거"]:
        x.append(g.sex.eq(sex).to_numpy(float))
        labels.append("sex:" + sex)
    if grade:
        for level in sorted(g.grade.unique())[1:]:
            x.append(g.grade.eq(level).to_numpy(float))
            labels.append("grade:" + level)
    return np.column_stack(x), labels


def age_fit(g, grade, meta):
    x, labels = design(g, grade)
    group = codes(g.year.astype(str) + ":" + g.month.astype(str) + ":" + g.moisture.astype(str))
    w = 1 / g.groupby(["horse_id", "age_bin"]).row_key.transform("size").to_numpy(float)
    y = g[PARTS].to_numpy(float)
    xd, _ = weighted_within(x, group, w)
    yd, _ = weighted_within(y, group, w)
    gram = xd.T @ (w[:, None] * xd)
    inv = np.linalg.pinv(gram, rcond=1e-11)
    beta = inv @ xd.T @ (w[:, None] * yd)
    residual = yd - xd @ beta
    projection = inv @ gram
    rank = np.linalg.matrix_rank(gram, tol=1e-8)
    dof = len(g) - len(np.unique(group)) - rank
    corr = (len(g) - 1) / max(dof, 1)
    rows = []
    for age in AGES:
        v = np.zeros(len(labels))
        if age != "4":
            v[labels.index("age:" + age)] = 1
        estimable = bool(np.allclose(v @ projection, v, atol=1e-7))
        a, b = g[g.age_bin.eq(age)], g[g.age_bin.eq("4")]
        support = (
            estimable
            and dof > 0
            and all(
                len(z) >= 100 and z.horse_id.nunique() >= 30 and z.date.nunique() >= 20
                for z in [a, b]
            )
        )
        for j, part in enumerate(PARTS):
            influence = (xd @ (inv @ v) * w * residual[:, j])[:, None]
            vh, nh = cluster_cov(influence, g.horse_id, corr)
            vd, nd = cluster_cov(influence, g.day_key, corr)
            vi, _ = cluster_cov(influence, g.horse_id + ":" + g.day_key, corr)
            se = float(np.sqrt(max((vh + vd - vi)[0, 0], vh[0, 0], vd[0, 0], 0)))
            crit = float(student_t.ppf(0.975, min(nh, nd) - 1)) if min(nh, nd) > 1 else np.nan
            value = float(v @ beta[:, j]) if estimable else np.nan
            rows.append(
                meta
                | dict(
                    age=age,
                    reference_age="4",
                    part=part,
                    difference_seconds=value,
                    se=se,
                    ci_low=value - crit * se if support else np.nan,
                    ci_high=value + crit * se if support else np.nan,
                    supported=bool(support),
                    estimable=estimable,
                    rows=len(a),
                    horses=a.horse_id.nunique(),
                    dates=a.date.nunique(),
                    reference_rows=len(b),
                    reference_horses=b.horse_id.nunique(),
                    model_rows=len(g),
                    model_horses=g.horse_id.nunique(),
                    fe_groups=int(group.max() + 1),
                    rank=int(rank),
                    design_columns=len(labels),
                    residual_df=int(dof),
                )
            )
    # Remove only estimated calendar/moisture FE; retain sex/age effects and all individual residuals.
    _, fe = weighted_within(y - x @ beta, group, w)
    fe_finish = fe[group, 0]
    centered = fe_finish - np.average(fe_finish, weights=w)
    normalized = pd.DataFrame(
        {
            "row_key": g.row_key,
            "calendar_moisture_component": centered,
            "finish_context": g.finish.to_numpy() - centered,
        }
    )
    return rows, normalized


def prepare():
    d = pd.read_parquet(POP)
    assert len(d) == 151074 and not d.row_key.duplicated().any()
    d["date"] = pd.to_datetime(d.date)
    d["age_bin"] = d.age.map(lambda x: str(int(x)) if x < 8 else "8+")
    c = duckdb.connect(str(DB), read_only=True)
    starters = c.execute("""select source_meet, result_date, result_race_no, horse_id_raw,
        horse_age_raw, horse_sex_raw, result_rank_raw, race_distance_m_raw, finish_time_seconds_raw
        from confirmed_runners""").fetchdf()
    profiles = c.execute(
        "select horse_id_raw_string as horse_id,birthday_raw from horse_profile_snapshot_membership"
    ).fetchdf()
    table_audit = c.execute(
        "select table_name,column_name from information_schema.columns where regexp_matches(lower(column_name),'birth|retir|exit|end_date')"
    ).fetchdf()
    c.close()
    table_audit.to_csv(OUT / "available_event_columns.csv", index=False)
    assert profiles.groupby("horse_id").birthday_raw.nunique().max() == 1
    profiles = profiles.drop_duplicates("horse_id")
    profiles["birthday"] = pd.to_datetime(profiles.birthday_raw, format="%Y%m%d", errors="coerce")
    d = d.merge(
        profiles[["horse_id", "birthday"]], on="horse_id", how="left", validate="many_to_one"
    )
    d["calendar_age_from_birth"] = d.year - d.birthday.dt.year
    d["age_birth_match"] = d.calendar_age_from_birth.eq(d.age)
    d["exact_age_years"] = (d.date - d.birthday).dt.days / 365.2425
    d["birthday_missing"] = d.birthday.isna()
    d.loc[
        ~d.age_birth_match | d.birthday_missing,
        ["row_key", "horse_id", "age", "birthday", "calendar_age_from_birth"],
    ].to_csv(OUT / "age_birth_exceptions.csv", index=False)
    rank = pd.to_numeric(starters.result_rank_raw, errors="coerce")
    starter_counts = rank.value_counts(dropna=False).sort_index().to_dict()
    starters = starters[rank.between(1, 20) | rank.isin([91, 92])].copy()
    starters["horse_id"] = starters.horse_id_raw.astype(str).str.zfill(7)
    starters["date"] = pd.to_datetime(starters.result_date, format="%Y%m%d")
    starters["meet_code"] = pd.to_numeric(starters.source_meet).astype(int)
    starters["race_no"] = pd.to_numeric(starters.result_race_no).astype(int)
    starters["age"] = pd.to_numeric(starters.horse_age_raw).astype(int)
    starters["sex"] = starters.horse_sex_raw
    starters["rank"] = pd.to_numeric(starters.result_rank_raw).astype(int)
    # A missing distance must not erase a confirmed subsequent start from follow-up.
    starters["distance_m"] = pd.to_numeric(starters.race_distance_m_raw).astype("Int64")
    starters["finish_raw"] = pd.to_numeric(starters.finish_time_seconds_raw, errors="coerce")
    starters["meet"] = starters.meet_code.map({1: "서울", 3: "부산", 4: "영천"}).fillna(
        starters.source_meet
    )
    starters["source_key"] = (
        starters.meet
        + ":"
        + starters.date.dt.strftime("%Y%m%d")
        + ":"
        + starters.race_no.astype(str)
    )
    starters["row_key"] = starters.source_key + ":" + starters.horse_id
    assert not starters.row_key.duplicated().any()
    assert not starters.duplicated(["horse_id", "date"]).any()
    starters = starters[
        [
            "row_key",
            "horse_id",
            "date",
            "meet",
            "meet_code",
            "race_no",
            "age",
            "sex",
            "rank",
            "distance_m",
            "finish_raw",
        ]
    ].sort_values(["horse_id", "date"])
    starters = starters[starters.date.le(CUT)].reset_index(drop=True)
    starters["next_date"] = starters.groupby("horse_id").date.shift(-1)
    starters["observed_first_date"] = starters.groupby("horse_id").date.transform("min")
    starters.to_parquet(OUT / "observed_starts.parquet", index=False)
    refs = (
        d.groupby(["meet", "distance_m"])
        .finish.median()
        .rename("reference_median_seconds")
        .reset_index()
    )
    refs.to_csv(OUT / "distance_scale.csv", index=False)
    d = d.merge(refs, on=["meet", "distance_m"], validate="many_to_one")
    d["raw_seconds_per60"] = d.finish * 60 / d.reference_median_seconds
    raw = (
        d.groupby(["meet", "distance_m", "age_bin"])
        .agg(
            rows=("row_key", "size"),
            horses=("horse_id", "nunique"),
            dates=("date", "nunique"),
            mean=("finish", "mean"),
            median=("finish", "median"),
            p20=("finish", lambda x: x.quantile(0.2)),
            p80=("finish", lambda x: x.quantile(0.8)),
        )
        .reset_index()
    )
    raw.to_csv(OUT / "raw_age_distributions.csv", index=False)
    audit = dict(
        population_sha256=sha(POP),
        population_rows=len(d),
        population_horses=d.horse_id.nunique(),
        population_races=d.source_key.nunique(),
        source_end={k: str(v.date()) for k, v in d.groupby("meet").date.max().items()},
        birth_missing_rows=int(d.birthday_missing.sum()),
        birth_age_mismatch_rows=int((~d.age_birth_match & ~d.birthday_missing).sum()),
        profile_snapshot_rows=len(profiles),
        observed_start_rows=len(starters),
        observed_start_horses=starters.horse_id.nunique(),
        followup_cutoff=str(CUT.date()),
        raw_rank_counts={str(k): int(v) for k, v in starter_counts.items()},
        observed_starts_sha256=sha(OUT / "observed_starts.parquet"),
        db_read_only=True,
        official_retirement_events_available=False,
        additional_api_requests=0,
        database_path=str(DB.relative_to(ROOT)),
        database_size=DB.stat().st_size,
        database_mtime_ns=DB.stat().st_mtime_ns,
    )
    dump(OUT / "source_audit.json", audit)
    return d, starters


def profiles(d):
    rows, norm = [], []
    for (meet, dist), g in d.groupby(["meet", "distance_m"]):
        if len(g) < 100:
            continue
        print("age profile", meet, dist, len(g), flush=True)
        for window, q in [("all", g), ("recent_2022plus", g[g.year.ge(2022)])]:
            if len(q) < 100:
                continue
            for grade in [False, True]:
                r, n = age_fit(
                    q,
                    grade,
                    dict(
                        meet=meet,
                        distance_m=int(dist),
                        window=window,
                        sex_group="all",
                        specification="context_grade" if grade else "context",
                    ),
                )
                rows.extend(r)
                if window == "all" and not grade:
                    norm.append(n)
        if dist == 1200:
            for sex, q in g.groupby("sex"):
                for grade in [False, True]:
                    r, _ = age_fit(
                        q,
                        grade,
                        dict(
                            meet=meet,
                            distance_m=1200,
                            window="all",
                            sex_group=sex,
                            specification="context_grade" if grade else "context",
                        ),
                    )
                    rows.extend(r)
    curves = pd.DataFrame(rows)
    curves.to_csv(OUT / "age_profiles.csv", index=False)
    d = d.merge(pd.concat(norm, ignore_index=True), on="row_key", how="left", validate="one_to_one")
    d["context_seconds_per60"] = d.finish_context * 60 / d.reference_median_seconds
    d.to_parquet(OUT / "analysis_population.parquet", index=False)
    return d, curves


def estimate(g, col, seed=20261007):
    v = g[col].to_numpy(float)
    mean = float(v.mean())
    influence = ((v - mean) / len(v))[:, None]
    vh, nh = cluster_cov(influence, g.horse_id, 1)
    vy, ny = cluster_cov(influence, g.year.astype(str), 1)
    vi, _ = cluster_cov(influence, g.horse_id + ":" + g.year.astype(str), 1)
    se = float(np.sqrt(max((vh + vy - vi)[0, 0], vh[0, 0], vy[0, 0], 0)))
    supported = nh >= 30 and ny >= 3
    crit = student_t.ppf(0.975, min(nh, ny) - 1) if min(nh, ny) > 1 else np.nan
    # Repeated transitions for a horse travel together in the bootstrap.
    h = g.groupby("horse_id")[col].agg(["sum", "count"])
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(h), size=(500, len(h)))
    boot = h["sum"].to_numpy()[picks].sum(axis=1) / h["count"].to_numpy()[picks].sum(axis=1)
    return dict(
        mean=mean,
        median=float(np.median(v)),
        rows=len(g),
        horses=nh,
        years=ny,
        se=se,
        supported=bool(supported),
        ci_low=float(mean - crit * se) if supported else np.nan,
        ci_high=float(mean + crit * se) if supported else np.nan,
        horse_boot_low=float(np.quantile(boot, 0.025)) if nh >= 30 else np.nan,
        horse_boot_high=float(np.quantile(boot, 0.975)) if nh >= 30 else np.nan,
        slower_share=float((v > 0).mean()),
    )


def paired(d):
    cells, horses, tables = [], [], []
    for match in ["moisture", "band"]:
        keys = ["horse_id", "meet", "distance_m", "year", "month", match, "age"]
        a = d.groupby(keys, as_index=False).agg(
            finish=("finish", "mean"),
            starts=("finish", "size"),
            first_date=("date", "min"),
            last_date=("date", "max"),
            reference=("reference_median_seconds", "first"),
        )
        b = a.copy()
        b["year"] -= 1
        b["age"] -= 1
        m = a.merge(b, on=keys, suffixes=("_before", "_after"), validate="one_to_one")
        m["match"] = match
        m["change_seconds"] = m.finish_after - m.finish_before
        m["change_per60"] = m.change_seconds * 60 / m.reference_before
        cells.append(m)
        h = m.groupby(
            ["match", "horse_id", "meet", "distance_m", "year", "age"], as_index=False
        ).agg(
            change_seconds=("change_seconds", "mean"),
            change_per60=("change_per60", "mean"),
            matched_cells=("month", "size"),
        )
        horses.append(h)
        pooled = h.groupby(["match", "horse_id", "meet", "year", "age"], as_index=False).agg(
            change_per60=("change_per60", "mean"), matched_cells=("matched_cells", "sum")
        )
        pooled["distance_m"] = 0
        both = pd.concat([h, pooled], ignore_index=True)
        for window, q in [
            ("all", both),
            ("recent_2022plus", both[both.year.ge(2022)]),
            ("without_2020_2021", both[~both.year.isin([2020, 2021])]),
        ]:
            for (meet, dist, age), g in q.groupby(["meet", "distance_m", "age"]):
                for col in ["change_per60"] + (["change_seconds"] if dist != 0 else []):
                    tables.append(
                        dict(
                            match=match,
                            window=window,
                            meet=meet,
                            distance_m=int(dist),
                            age_from=int(age),
                            age_to=int(age) + 1,
                            metric=col,
                        )
                        | estimate(g, col)
                    )
    pd.concat(cells, ignore_index=True).to_parquet(
        OUT / "matched_transition_cells.parquet", index=False
    )
    pd.concat(horses, ignore_index=True).to_parquet(
        OUT / "horse_age_transitions.parquet", index=False
    )
    table = pd.DataFrame(tables)
    table.to_csv(OUT / "matched_age_changes.csv", index=False)
    return table


def build_landmarks(d, s):
    local = s[s.meet.isin(["서울", "부산"])].copy()
    local["year"] = local.date.dt.year
    landmarks = (
        local[local.year.between(2018, 2024)]
        .sort_values("date")
        .groupby(["horse_id", "year"])
        .tail(1)
        .copy()
    )
    # The next date is from ALL official venues and distances, not from the time-quality cohort.
    landmarks["gap_days"] = (landmarks.next_date - landmarks.date).dt.days
    landmarks["followup_days"] = (CUT - landmarks.date).dt.days
    landmarks["age_bin"] = landmarks.age.map(lambda x: str(x) if x < 8 else "8+")
    for days in [365, 730]:
        landmarks[f"eligible_{days}"] = landmarks.followup_days.ge(days)
        if days == 730:
            landmarks[f"eligible_{days}"] &= landmarks.year.le(2023)
        landmarks[f"no_start_{days}"] = (
            landmarks.next_date.isna() | landmarks.gap_days.gt(days)
        ).where(landmarks[f"eligible_{days}"])
    # Last six valid time observations within two years, avoiding best-time selection.
    hist = {k: v.sort_values("date") for k, v in d.groupby("horse_id")}
    trends = []
    for r in landmarks.itertuples():
        g = hist.get(r.horse_id)
        if g is None:
            continue
        z = g[g.date.le(r.date) & g.date.ge(r.date - pd.Timedelta(days=730))]
        last = z.tail(6)
        meta = dict(
            row_key=r.row_key,
            valid_rows_730=len(z),
            six_available=len(last) == 6,
            last_valid_date=str(last.date.max().date()) if len(last) else None,
            anchor_time_available=r.row_key in set(last.row_key),
        )
        for col in ["raw_seconds_per60", "context_seconds_per60"]:
            v = last[col].to_numpy(float)
            meta[col + "_change"] = (
                float(v[3:].mean() - v[:3].mean())
                if len(v) == 6 and np.isfinite(v).all()
                else np.nan
            )
            meta[col + "_recent"] = (
                float(v[3:].mean()) if len(v) == 6 and np.isfinite(v).all() else np.nan
            )
        meta["trend_first_date"] = str(last.date.min().date()) if len(last) == 6 else None
        trends.append(meta)
    landmarks = landmarks.merge(
        pd.DataFrame(trends), on="row_key", how="left", validate="one_to_one"
    )
    landmarks.to_parquet(OUT / "annual_followup_landmarks.parquet", index=False)
    tables, trows = [], []
    for horizon in [365, 730]:
        q0 = landmarks[landmarks[f"eligible_{horizon}"]].copy()
        q0["inactive"] = q0[f"no_start_{horizon}"].astype(float)
        q0["late_return"] = (q0.inactive.eq(1) & q0.next_date.notna()).astype(float)
        for window, q in [("all", q0), ("without_2020_2021", q0[~q0.year.isin([2020, 2021])])]:
            for grouping, keys in [
                ("age", ["meet", "age_bin"]),
                ("age_sex", ["meet", "age_bin", "sex"]),
                ("year", ["meet", "year"]),
            ]:
                for key, g in q.groupby(keys):
                    meta = dict(zip(keys, key if isinstance(key, tuple) else [key], strict=True))
                    stat = estimate(g, "inactive")
                    stat["ci_low"] = max(0, stat["ci_low"]) if stat["supported"] else np.nan
                    stat["ci_high"] = min(1, stat["ci_high"]) if stat["supported"] else np.nan
                    tables.append(
                        meta
                        | dict(
                            horizon_days=horizon,
                            window=window,
                            grouping=grouping,
                            no_start_count=int(g.inactive.sum()),
                            late_return_count=int(g.late_return.sum()),
                            late_return_interpretation="observed by common cutoff; unequal additional followup",
                        )
                        | stat
                    )
            for col in ["raw_seconds_per60_change", "context_seconds_per60_change"]:
                valid = q[q[col].notna()].copy()
                for (meet, age, status), g in valid.groupby(["meet", "age_bin", "inactive"]):
                    meta = dict(
                        meet=meet,
                        age_bin=age,
                        inactive=bool(status),
                        horizon_days=horizon,
                        window=window,
                        metric=col,
                    )
                    trows.append(
                        meta
                        | estimate(g, col)
                        | dict(
                            worse_025_share=float(g[col].gt(0.25).mean()),
                            worse_050_share=float(g[col].gt(0.50).mean()),
                            not_worse_share=float(g[col].le(0).mean()),
                        )
                    )
                for meet, g in valid.groupby("meet"):
                    for status, z in g.groupby("inactive"):
                        meta = dict(
                            meet=meet,
                            age_bin="all",
                            inactive=bool(status),
                            horizon_days=horizon,
                            window=window,
                            metric=col,
                        )
                        trows.append(
                            meta
                            | estimate(z, col)
                            | dict(
                                worse_025_share=float(z[col].gt(0.25).mean()),
                                worse_050_share=float(z[col].gt(0.50).mean()),
                                not_worse_share=float(z[col].le(0).mean()),
                            )
                        )
    follow = pd.DataFrame(tables)
    trend = pd.DataFrame(trows)
    follow.to_csv(OUT / "inactivity_by_age.csv", index=False)
    trend.to_csv(OUT / "pre_inactivity_record_changes.csv", index=False)
    return landmarks, follow, trend


def main():
    d, s = prepare()
    d, curves = profiles(d)
    pairs = paired(d)
    landmarks, follow, trend = build_landmarks(d, s)
    summary = dict(
        completed_on="2026-10-07",
        question="observed average aging, within-horse change and inactivity selection",
        population_rows=len(d),
        population_horses=d.horse_id.nunique(),
        profile_rows=len(curves),
        matched_change_rows=len(pairs),
        landmark_rows=len(landmarks),
        landmark_horses=landmarks.horse_id.nunique(),
        eligible365=int(landmarks.eligible_365.sum()),
        eligible730=int(landmarks.eligible_730.sum()),
        official_retirement_confirmed=False,
        aging_correction_adopted=False,
        forecast_improvement_tested=False,
        source_audit="source_audit.json",
        followup_cutoff=str(CUT.date()),
        normalizer="retrospective calendar/moisture FE only; no age/sex/grade removal; not a validated environment correction",
        ci="pointwise, conservative horse/date or horse/year cluster inference; not simultaneous intervals",
        selection="normal complete-race/section cohort for times; all confirmed starts including nonfinishers for followup",
    )
    dump(OUT / "summary.json", summary)
    web = dict(
        version="age_curve_exit_v1",
        title="평균 연령별 기록과 출전 중단 전 변화",
        summary=summary,
        age_profiles=json.loads(curves.to_json(orient="records", force_ascii=False)),
        matched_age_changes=json.loads(pairs.to_json(orient="records", force_ascii=False)),
        inactivity=json.loads(follow.to_json(orient="records", force_ascii=False)),
        pre_inactivity_changes=json.loads(trend.to_json(orient="records", force_ascii=False)),
    )
    dump(OUT / "web_age_curve_exit.json", web)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
