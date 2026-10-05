"""Independent SQL aggregation and source/chronology/partition checks."""

import json

import duckdb
import numpy as np
import pandas as pd
from analyze import BANDS, DB, HISTORY, OUT, PARTS, RACE, ROOT, TRIAL, sha


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    for name, digest in summary["inputs_sha256"].items():
        assert sha(ROOT / name) == digest, name
    p = pd.read_parquet(OUT / "population.parquet")
    scored = pd.read_parquet(OUT / "scored_recent.parquet")
    excluded = pd.read_parquet(OUT / "excluded.parquet")
    assert not p.duplicated(["population", "row_key"]).any()
    assert len(p) == summary["valid_rows"] and len(excluded) == summary["excluded_rows"]
    assert p.band.isin(BANDS).all()
    assert np.allclose(p.finish, p.early + p.middle1 + p.middle2 + p.late)
    assert np.allclose(p.middle, p.middle1 + p.middle2)
    assert np.allclose(p.last600, p.middle2 + p.late)
    assert np.allclose(p.fs200, 100 * 200 * p.finish / (p.distance * p.late))
    assert p.loc[p.meet.eq("서울"), "last400"].isna().all()
    assert (
        p.loc[p.meet.eq("부산") & p.population.eq("실전1200") & p.year.ge(2024), "last400"]
        .notna()
        .all()
    )
    assert (scored.reference_max_date < scored.date).all()
    assert len(scored) == p.year.ge(2024).sum() == summary["recent_rows"]

    source_t = pd.read_parquet(TRIAL)
    t = p[p.population.eq("주행심사1000")].merge(
        source_t,
        left_on="row_key",
        right_on="participant_row_id",
        suffixes=("", "_src"),
        validate="one_to_one",
    )
    assert t.api_reason.eq("주행미합(신)").all()
    assert t.api_passFlag.isin(["합격", "불합격"]).all()
    assert t.valid_core.all()
    for target, source in [("early", "s1f"), ("late", "g1f"), ("last600", "g3f")]:
        assert np.allclose(t[target], t[source])
    assert np.allclose(t.middle1, t.finish - t.g3f - t.s1f)
    source_r = pd.read_parquet(RACE)
    history = pd.read_parquet(HISTORY)
    for f in (source_r, history):
        f["date"] = pd.to_datetime(f.date)
        f["meet"] = f.meet.map({1: "서울", 3: "부산"})
        f["row_key"] = (
            f.meet
            + ":"
            + f.date.dt.strftime("%Y%m%d")
            + ":"
            + f.race_no.astype(str)
            + ":"
            + f.horse_id
        )
    r = p[p.population.eq("실전1200")].merge(
        source_r, on="row_key", suffixes=("", "_src"), validate="one_to_one"
    )
    assert r.distance_m.eq(1200).all()
    assert np.allclose(r.finish, r.finish_src / 1000)
    for target, source in [("early", "start_200"), ("late", "last_200"), ("last600", "last_600")]:
        assert np.allclose(r[target], r[source] / 1000)
    assert set(r.row_key).issubset(set(history.row_key))
    previous = pd.to_datetime(p.last_history_date, errors="coerce")
    assert (previous.isna() | (previous < p.date)).all()
    with duckdb.connect(str(DB), read_only=True) as c:
        raw400 = c.execute("""SELECT '부산:' || race_date || ':' || CAST(race_no AS VARCHAR)
             || ':' || horse_id AS row_key, time_ms/1000.0 AS raw400
             FROM section_measurements_api WHERE meet=3 AND point_code='2F_G'
             AND measure_kind='closing_time' AND source_field='bu_2fGTime'
             AND race_date >= '20180101'""").fetchdf()
    b = p[p.population.eq("실전1200") & p.meet.eq("부산")].merge(
        raw400, on="row_key", validate="one_to_one"
    )
    assert len(b) == len(r[r.meet.eq("부산")])
    good400 = b.raw400.between(16, 50) & (b.raw400 > b.late) & (b.raw400 < b.last600)
    assert np.allclose(b.loc[good400, "last400"], b.loc[good400, "raw400"])
    assert b.loc[~good400, "last400"].isna().all()
    b.loc[~good400, ["row_key", "date", "raw400", "finish", "last600", "late"]].to_csv(
        OUT / "partial_400_exclusions.csv", index=False
    )

    threshold = pd.read_csv(OUT / "reference_thresholds.csv", float_precision="round_trip")
    checks = 0
    for row in threshold.itertuples():
        group = scored[
            (scored.population == row.population)
            & (scored.meet == row.meet)
            & (scored.year == row.year)
        ]
        res = group["res_" + row.part]
        present = res.notna()
        independent = np.where(res < row.q25, "빠름", np.where(res > row.q75, "느림", "보통"))
        assert (independent[present] == group.loc[present, "pace_" + row.part]).all()
        checks += int(present.sum())
    c = duckdb.connect()
    c.register("population", p)
    aggregate_checks = 0
    for filename, groupkeys, selection in [
        ("moisture_sections.csv", ["population", "meet", "band"], "year >= 2024"),
        ("overall_sections.csv", ["population", "meet"], "year >= 2024"),
        ("passed_moisture_sections.csv", ["population", "meet", "band"], "year >= 2024 AND passed"),
        ("grade_sections.csv", ["meet", "grade"], "year >= 2024 AND population='실전1200'"),
    ]:
        actual = pd.read_csv(OUT / filename)
        for part in PARTS + ["fs200", "fs400", "fs600"]:
            # Identifiers and predicates come only from fixed code constants, never user input.
            columns = ", ".join(groupkeys)
            expected = c.execute(f"""SELECT {columns}, COUNT({part}) AS n,
                 COUNT(DISTINCT date) AS days, AVG({part}) AS mean,
                 MEDIAN({part}) AS median, QUANTILE_CONT({part},0.1) AS p10,
                 QUANTILE_CONT({part},0.9) AS p90
                 FROM population WHERE {selection} AND {part} IS NOT NULL GROUP BY ALL""").fetchdf()
            a = actual[actual.part.eq(part)].merge(
                expected, on=groupkeys, suffixes=("", "_sql"), validate="one_to_one"
            )
            assert len(a) == len(expected) == len(actual[actual.part.eq(part)])
            for metric in ("n", "days", "mean", "median", "p10", "p90"):
                assert np.allclose(a[metric], a[metric + "_sql"], atol=1e-10)
                aggregate_checks += len(a)
    c.register("scored", scored)
    actual = pd.read_csv(OUT / "pace_profiles.csv")
    expected = c.execute("""SELECT population, meet, pace_early, pace_middle,
        COUNT(*) AS n, COUNT(DISTINCT date) AS days, AVG(late) AS late_mean,
        AVG(res_late) AS late_residual_mean,
        AVG(CASE WHEN pace_late='빠름' THEN 1.0 ELSE 0.0 END) AS fast_late_share
        FROM scored GROUP BY ALL""").fetchdf()
    merged = actual.merge(
        expected,
        on=["population", "meet", "pace_early", "pace_middle"],
        suffixes=("", "_sql"),
        validate="one_to_one",
    )
    assert len(merged) == 36
    for col in ("n", "days", "late_mean", "late_residual_mean", "fast_late_share"):
        assert np.allclose(merged[col], merged[col + "_sql"])
    result = dict(
        source_rows_checked=len(t) + len(r),
        busan400_checked=int(good400.sum()),
        invalid_busan400_masked=int((~good400).sum()),
        independent_aggregate_metrics=aggregate_checks,
        pace_classifications_checked=checks,
        profile_groups_checked=len(merged),
        partition_sum=True,
        strict_prior_dates=True,
        input_hashes_unchanged=True,
        read_only_database=True,
    )
    (OUT / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
