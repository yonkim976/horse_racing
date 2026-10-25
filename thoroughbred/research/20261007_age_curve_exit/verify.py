# ruff: noqa: E501
"""Independent SQL reconstruction and explicit sparse weighted-dummy regression checks."""

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import lsmr

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"


def assert_close(a, b, atol=1e-9):
    np.testing.assert_allclose(
        np.asarray(a, float), np.asarray(b, float), atol=atol, rtol=1e-9, equal_nan=True
    )


def main():
    d = pd.read_parquet(OUT / "analysis_population.parquet")
    original = pd.read_parquet(HERE.parent / "20261007_sex_ability_gap/outputs/population.parquet")
    z = d.merge(original, on="row_key", validate="one_to_one", suffixes=("_new", "_old"))
    assert len(z) == 151074
    for col in [
        "finish",
        "early",
        "middle1",
        "middle2",
        "late",
        "age",
        "moisture",
        "weight",
        "body_weight",
    ]:
        assert_close(z[col + "_new"], z[col + "_old"])
    assert d.age_birth_match.all() and not d.birthday_missing.any()
    assert_close(d.finish, d.early + d.middle1 + d.middle2 + d.late)
    assert_close(d.last600, d.middle2 + d.late)
    c = duckdb.connect()
    c.register("population", original)
    c.register("analysis", d)
    cells = pd.read_parquet(OUT / "matched_transition_cells.parquet")
    cell_checks = 0
    for match in ["moisture", "band"]:
        q = c.execute(f"""with a as (
            select horse_id,meet,distance_m,year,month,{match},age,avg(finish) as time
            from population group by all)
            select a.horse_id,a.meet,a.distance_m,a.year,a.month,a.{match},a.age,b.time-a.time as delta
            from a join a b on a.horse_id=b.horse_id and a.meet=b.meet and a.distance_m=b.distance_m
            and a.year+1=b.year and a.month=b.month and a.{match}=b.{match} and a.age+1=b.age""").fetchdf()
        got = cells[cells.match.eq(match)]
        keys = ["horse_id", "meet", "distance_m", "year", "month", match, "age"]
        j = q.merge(got, on=keys, validate="one_to_one")
        assert len(j) == len(q) == len(got)
        assert_close(j.delta, j.change_seconds)
        cell_checks += len(j)
    c.register("cells", cells)
    h = pd.read_parquet(OUT / "horse_age_transitions.parquet")
    q = c.execute("""select match,horse_id,meet,distance_m,year,age,avg(change_seconds) as sec,
        avg(change_per60) as norm,count(*) as cells from cells group by all""").fetchdf()
    keys = ["match", "horse_id", "meet", "distance_m", "year", "age"]
    j = h.merge(q, on=keys, validate="one_to_one")
    assert len(j) == len(h) == len(q)
    assert_close(j.change_seconds, j.sec)
    assert_close(j.change_per60, j.norm)
    assert_close(j.matched_cells, j.cells)
    changes = pd.read_csv(OUT / "matched_age_changes.csv")
    aggregate_checks = 0
    for r in changes.itertuples():
        sub = h[h.match.eq(r.match) & h.meet.eq(r.meet) & h.age.eq(r.age_from)]
        if r.distance_m:
            sub = sub[sub.distance_m.eq(r.distance_m)]
        else:
            sub = sub.groupby(["horse_id", "year", "age"], as_index=False).change_per60.mean()
        if r.window == "recent_2022plus":
            sub = sub[sub.year.ge(2022)]
        if r.window == "without_2020_2021":
            sub = sub[~sub.year.isin([2020, 2021])]
        assert_close(sub[r.metric].mean(), r.mean)
        assert len(sub) == r.rows and sub.horse_id.nunique() == r.horses
        aggregate_checks += 1
    # Rebuild all subsequent-start dates straight from the read-only core, not the saved extraction.
    core = duckdb.connect(
        str(ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"),
        read_only=True,
    )
    source = core.execute("""select horse_id_raw as horse_id,source_meet as meet_code,result_date,
        cast(result_race_no as integer) as race_no,cast(result_rank_raw as integer) as rank
        from confirmed_runners where (try_cast(result_rank_raw as integer) between 1 and 20
        or try_cast(result_rank_raw as integer) in (91,92)) and result_date<='20260918'""").fetchdf()
    core.close()
    c.register("raw_starts", source)
    nxt = c.execute("""select horse_id,meet_code,race_no,strptime(result_date,'%Y%m%d')::date as date,
        lead(strptime(result_date,'%Y%m%d')::date) over(partition by horse_id order by result_date) as next_date
        from raw_starts""").fetchdf()
    s = pd.read_parquet(OUT / "observed_starts.parquet")
    s["meet_code"] = s.meet_code.astype(str)
    keys = ["horse_id", "meet_code", "race_no", "date"]
    j = s.merge(nxt, on=keys, validate="one_to_one", suffixes=("_saved", "_sql"))
    assert len(j) == len(s) == len(source)
    assert (
        j.next_date_saved.fillna(pd.Timestamp("1900-01-01"))
        .eq(j.next_date_sql.fillna(pd.Timestamp("1900-01-01")))
        .all()
    )
    landmarks = pd.read_parquet(OUT / "annual_followup_landmarks.parquet")
    c.register("starts", s)
    expected = c.execute("""select * from starts where meet_code in ('1','3') and year(date) between 2018 and 2024
        qualify row_number() over(partition by horse_id,year(date) order by date desc)=1""").fetchdf()
    assert set(expected.row_key) == set(landmarks.row_key)
    cutoff = pd.Timestamp("2026-09-18")
    for days in [365, 730]:
        eligible = (cutoff - landmarks.date).dt.days.ge(days)
        if days == 730:
            eligible &= landmarks.year.le(2023)
        assert eligible.eq(landmarks[f"eligible_{days}"]).all()
        q = landmarks[eligible]
        got = q.next_date.isna() | (q.next_date - q.date).dt.days.gt(days)
        assert got.eq(q[f"no_start_{days}"].astype(bool)).all()
        assert landmarks.loc[~eligible, f"no_start_{days}"].isna().all()
    c.register("landmarks", landmarks)
    trend = c.execute("""with m as (
        select l.row_key,a.date,a.raw_seconds_per60,a.context_seconds_per60,
        row_number() over(partition by l.row_key order by a.date desc) as seq
        from landmarks l join analysis a on l.horse_id=a.horse_id
        and a.date<=l.date and a.date>=l.date-interval 730 day), q as (
        select row_key,count(*) as valid_rows_730,
        avg(raw_seconds_per60) filter(where seq<=3)-avg(raw_seconds_per60) filter(where seq between 4 and 6) as raw_delta,
        avg(context_seconds_per60) filter(where seq<=3)-avg(context_seconds_per60) filter(where seq between 4 and 6) as context_delta
        from m group by row_key)
        select * from q""").fetchdf()
    j = landmarks.merge(trend, on="row_key", validate="one_to_one", suffixes=("_saved", "_sql"))
    assert len(j) == len(landmarks[landmarks.valid_rows_730.gt(0)])
    assert_close(j.valid_rows_730_saved, j.valid_rows_730_sql)
    q = j[j.valid_rows_730_sql.ge(6)]
    assert_close(q.raw_seconds_per60_change, q.raw_delta)
    # Missing context in unsupported tiny-distance models must remain missing.
    q = q[q.context_seconds_per60_change.notna()]
    assert_close(q.context_seconds_per60_change, q.context_delta)
    six_trend_checks = len(q)
    curves = pd.read_csv(OUT / "age_profiles.csv")
    independent = []
    se_checks = 0
    for meet in ["서울", "부산"]:
        g = d[d.meet.eq(meet) & d.distance_m.eq(1200)].reset_index(drop=True)
        fe = pd.factorize(
            g.year.astype(str) + ":" + g.month.astype(str) + ":" + g.moisture.astype(str)
        )[0]
        rows = np.arange(len(g))
        w = 1 / g.groupby(["horse_id", "age_bin"]).row_key.transform("size").to_numpy(float)
        fe_matrix = sparse.coo_matrix(
            (np.ones(len(g)), (rows, fe)), shape=(len(g), fe.max() + 1)
        ).tocsr()
        for grade in [False, True]:
            labels = ["age:" + a for a in ["2", "3", "5", "6", "7", "8+"]] + ["sex:암", "sex:거"]
            columns = [g.age_bin.eq(a).to_numpy(float) for a in ["2", "3", "5", "6", "7", "8+"]] + [
                g.sex.eq(s).to_numpy(float) for s in ["암", "거"]
            ]
            if grade:
                for a in sorted(g.grade.unique())[1:]:
                    columns.append(g.grade.eq(a).to_numpy(float))
                    labels.append("grade:" + a)
            xx = np.column_stack(columns)
            x = sparse.hstack([sparse.csr_matrix(xx), fe_matrix], format="csr")
            xw = x.multiply(np.sqrt(w)[:, None]).tocsr()
            for part in ["finish", "early", "middle1", "middle2", "late", "last600"]:
                fit = lsmr(
                    xw, g[part].to_numpy() * np.sqrt(w), atol=1e-12, btol=1e-12, maxiter=10000
                )
                assert fit[1] in [1, 2]
                for age in ["2", "3", "5", "6", "7", "8+"]:
                    row = curves[
                        curves.meet.eq(meet)
                        & curves.distance_m.eq(1200)
                        & curves.window.eq("all")
                        & curves.sex_group.eq("all")
                        & curves.specification.eq("context_grade" if grade else "context")
                        & curves.age.eq(age)
                        & curves.part.eq(part)
                    ].iloc[0]
                    value = fit[0][labels.index("age:" + age)]
                    assert_close(value, row.difference_seconds, atol=1e-7)
                    independent.append(
                        dict(
                            meet=meet,
                            specification=row.specification,
                            age=age,
                            part=part,
                            explicit_dummy=value,
                            saved=row.difference_seconds,
                            error=value - row.difference_seconds,
                        )
                    )
                    if part == "finish" and age in ["2", "5"]:
                        # FWL residualization with the explicit sparse FE matrix is independent
                        # of the analyzer's weighted group demeaning and Gram inverse.
                        k = labels.index("age:" + age)
                        keep = np.arange(x.shape[1]) != k
                        fit_age = lsmr(
                            xw[:, keep],
                            xx[:, k] * np.sqrt(w),
                            atol=1e-12,
                            btol=1e-12,
                            maxiter=10000,
                        )[0]
                        u = xx[:, k] - x[:, keep] @ fit_age
                        e = g[part].to_numpy() - x @ fit[0]
                        influence = w * u * e / np.sum(w * u * u)
                        correction = (len(g) - 1) / row.residual_df
                        variances = []
                        for cluster in [g.horse_id, g.day_key, g.horse_id + ":" + g.day_key]:
                            code = pd.factorize(cluster)[0]
                            n = code.max() + 1
                            score = np.bincount(code, weights=influence)
                            variances.append(score @ score * correction * n / (n - 1))
                        vh, vd, vi = variances
                        se = np.sqrt(max(vh + vd - vi, vh, vd, 0))
                        assert_close(se, row.se, atol=1e-7)
                        se_checks += 1
    pd.DataFrame(independent).to_csv(OUT / "independent_dummy_checks.csv", index=False)
    # Independent table aggregation for inactivity/trends, including the no-decline fractions.
    follow = pd.read_csv(OUT / "inactivity_by_age.csv")
    checks = 0
    for r in follow.itertuples():
        q = landmarks[landmarks[f"eligible_{r.horizon_days}"] & landmarks.meet.eq(r.meet)]
        if r.window == "without_2020_2021":
            q = q[~q.year.isin([2020, 2021])]
        if r.grouping in ["age", "age_sex"]:
            q = q[q.age_bin.eq(str(r.age_bin))]
        if r.grouping == "age_sex":
            q = q[q.sex.eq(r.sex)]
        if r.grouping == "year":
            q = q[q.year.eq(r.year)]
        assert len(q) == r.rows
        assert_close(q[f"no_start_{r.horizon_days}"].astype(float).mean(), r.mean)
        checks += 1
    t = pd.read_csv(OUT / "pre_inactivity_record_changes.csv")
    for r in t.itertuples():
        q = landmarks[
            landmarks[f"eligible_{r.horizon_days}"]
            & landmarks.meet.eq(r.meet)
            & landmarks[r.metric].notna()
        ]
        if r.window == "without_2020_2021":
            q = q[~q.year.isin([2020, 2021])]
        if r.age_bin != "all":
            q = q[q.age_bin.eq(r.age_bin)]
        q = q[q[f"no_start_{r.horizon_days}"].astype(bool).eq(r.inactive)]
        assert len(q) == r.rows
        assert_close(q[r.metric].mean(), r.mean)
        assert_close(q[r.metric].le(0).mean(), r.not_worse_share)
        assert_close(q[r.metric].gt(0.5).mean(), r.worse_050_share)
        checks += 1
    audit = json.loads((OUT / "source_audit.json").read_text())
    db = ROOT / audit["database_path"]
    assert (
        db.stat().st_size == audit["database_size"]
        and db.stat().st_mtime_ns == audit["database_mtime_ns"]
    )
    result = dict(
        passed=True,
        source_population_rows_checked=len(d),
        birth_age_checks=len(d),
        section_identity_checks=len(d) * 2,
        sql_matched_cells_checked=cell_checks,
        sql_horse_transition_checks=len(h),
        aggregate_age_change_checks=aggregate_checks,
        core_next_start_checks=len(s),
        sql_landmark_checks=len(landmarks),
        sql_six_record_trends_checked=six_trend_checks,
        explicit_dummy_contrasts=len(independent),
        independent_cluster_se_checks=se_checks,
        maximum_dummy_error=float(max(abs(x["error"]) for x in independent)),
        followup_trend_table_checks=checks,
        input_database_unchanged=True,
        official_retirement_not_inferred=True,
    )
    (OUT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
