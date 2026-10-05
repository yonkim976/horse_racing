"""Verify raw Yeongcheon source, independent SQL summaries, and grade pace labels."""

import gzip
import json

import duckdb
import numpy as np
import pandas as pd
from analyze import CATS, DB, NUMS, OUT, PARTS, PRIOR, RAW, ROOT, sha


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    for path, digest in summary["input_hashes"].items():
        assert sha(ROOT / path) == digest, path
    y = pd.read_parquet(OUT / "yeongcheon_1200.parquet")
    d = pd.read_parquet(PRIOR)
    d = d[d.population.eq("실전1200")]
    recent = pd.concat([d[d.year.ge(2024)], y], ignore_index=True)
    assert len(recent) == summary["recent_runners"] == 13363
    assert len(y) == 50 and y.source_key.nunique() == 5 and y.date.nunique() == 2
    assert y.band.eq("건조").all() and y.moisture.eq(3).all()
    assert not recent.duplicated(["meet", "row_key"]).any()
    assert np.allclose(recent.finish, recent.early + recent.middle1 + recent.middle2 + recent.late)
    assert np.allclose(recent.last600, recent.middle2 + recent.late)
    assert y.last400.gt(y.late).all() and y.last400.lt(y.last600).all()
    with duckdb.connect(str(DB), read_only=True) as c:
        source = c.execute("""SELECT result_date, result_race_no, horse_id_raw,
             finish_time_seconds_raw, source_item_index, race_distance_m_raw,
             result_rank_raw, grade_raw FROM confirmed_runners WHERE source_meet='4'""").fetchdf()
    raw = json.loads(gzip.decompress(RAW.read_bytes()))["response"]["body"]["items"]["item"]
    for row in source.itertuples():
        r = raw[int(row.source_item_index)]
        assert (str(r["rcDate"]), str(r["rcNo"]), str(r["hrNo"]), r["meet"]) == (
            row.result_date,
            row.result_race_no,
            row.horse_id_raw,
            "영천",
        )
        assert float(r["rcTime"]) == float(row.finish_time_seconds_raw)
        assert str(r["rcDist"]) == row.race_distance_m_raw
        assert str(r["ord"]) == row.result_rank_raw and r["rank"] == row.grade_raw
    for row in y.itertuples():
        r = raw[int(row.source_item_index)]
        assert row.finish == float(r["rcTime"])
        assert row.early == float(r["buS1fAccTime"])
        assert row.late == float(r["bu_1fGTime"])
        assert row.last400 == float(r["bu_2fGTime"])
        assert np.isclose(row.last600, row.finish - float(r["buG3fAccTime"]))
        direct = float(r.get("bu_3fGTime", 0))
        if direct > 0:
            assert row.last600 == direct and row.last600_source == "direct"
        else:
            assert row.last600_source == "finish_minus_G3F_cumulative"
    assert (y.last600_source != "direct").sum() == 11

    scored = pd.read_parquet(OUT / "scored_recent.parquet")
    assert len(scored) == len(d[d.year.ge(2024)])
    assert (scored.reference_max_date < scored.date).all()
    dates = pd.to_datetime(d.last_history_date, errors="coerce")
    assert (dates.isna() | (dates < d.date)).all()
    assert not {"finish", "rank", "odds", "win", "top3"}.intersection(CATS + NUMS)
    thresholds = pd.read_csv(OUT / "grade_reference_thresholds.csv", float_precision="round_trip")
    classifications = 0
    for t in thresholds.itertuples():
        g = scored[(scored.meet == t.meet) & (scored.year == t.year) & (scored.grade == t.grade)]
        res = g["res_" + t.part]
        if t.supported:
            expected = np.where(res < t.q25, "빠름", np.where(res > t.q75, "느림", "보통"))
            assert (expected == g["pace_" + t.part]).all()
            classifications += len(g)
        else:
            assert g["pace_" + t.part].isna().all()
    # rank is joined from the previously verified, immutable complete-runner snapshot.
    history = pd.read_parquet(
        ROOT / "thoroughbred/research/20261002_gate_lateral_bias/outputs/runners.parquet"
    )
    history["date"] = pd.to_datetime(history.date)
    history["row_key"] = (
        history.meet.map({1: "서울", 3: "부산"})
        + ":"
        + history.date.dt.strftime("%Y%m%d")
        + ":"
        + history.race_no.astype(str)
        + ":"
        + history.horse_id
    )
    d = d.merge(history[["row_key", "rank"]], on="row_key", validate="one_to_one")
    recent = pd.concat([d[d.year.ge(2024)], y], ignore_index=True)
    history["source_key"] = history.row_key.str.rsplit(":", n=1).str[0]
    source_races = history[
        history.source_key.isin(set(recent.loc[recent.meet.ne("영천"), "source_key"]))
    ]
    for _, g in source_races.groupby("source_key"):
        assert len(g) >= 6 and sorted(g["rank"].astype(int)) == list(range(1, len(g) + 1))
    for _, g in y.groupby("source_key"):
        assert len(g) >= 6 and sorted(g["rank"].astype(int)) == list(range(1, len(g) + 1))
    c = duckdb.connect()
    c.register("recent", recent)
    checks = 0
    for filename, keys, where in [
        ("grade_sections", ["meet", "grade"], "TRUE"),
        ("dry_grade_sections", ["meet", "grade"], "band='건조'"),
        ("moisture_grade_sections", ["meet", "grade", "band"], "TRUE"),
        ("year_grade_sections", ["meet", "grade", "year"], "TRUE"),
        ("winner_grade_sections", ["meet", "grade"], "rank=1"),
        ("top3_grade_sections", ["meet", "grade"], "rank<=3"),
        ("yeongcheon_race_sections", ["meet", "grade", "source_key"], "meet='영천'"),
    ]:
        actual = pd.read_csv(OUT / (filename + ".csv"))
        for part in PARTS:
            # All identifiers and predicates are fixed internal constants, never user input.
            cols = ", ".join(keys)
            query = f"""SELECT {cols}, COUNT(*) AS n, COUNT(DISTINCT date) AS days,
                COUNT(DISTINCT source_key) AS races, AVG({part}) AS mean,
                MEDIAN({part}) AS median, QUANTILE_CONT({part},0.1) AS p10,
                QUANTILE_CONT({part},0.9) AS p90
                FROM recent WHERE {where} AND {part} IS NOT NULL GROUP BY ALL"""
            expected = c.execute(query).fetchdf()
            a = actual[actual.part.eq(part)].merge(
                expected, on=keys, validate="one_to_one", suffixes=("", "_sql")
            )
            assert len(a) == len(expected) == len(actual[actual.part.eq(part)])
            for col in ["n", "days", "races", "mean", "median", "p10", "p90"]:
                assert np.allclose(a[col], a[col + "_sql"], atol=1e-10)
                checks += len(a)
    c.register("scored", scored)
    expected = c.execute("""SELECT meet,grade,pace_early,pace_middle,COUNT(*) AS n,
        AVG(late) AS late_mean, AVG(res_late) AS late_residual_mean,
        AVG(CASE WHEN pace_late='빠름' THEN 1.0 ELSE 0.0 END) AS fast_late_share
        FROM scored WHERE pace_early IS NOT NULL AND pace_middle IS NOT NULL
        AND pace_late IS NOT NULL GROUP BY ALL""").fetchdf()
    actual = pd.read_csv(OUT / "grade_pace_profiles.csv")
    merged = actual.merge(
        expected,
        on=["meet", "grade", "pace_early", "pace_middle"],
        validate="one_to_one",
        suffixes=("", "_sql"),
    )
    assert len(merged) == len(expected) == len(actual)
    for col in ["n", "late_mean", "late_residual_mean", "fast_late_share"]:
        assert np.allclose(merged[col], merged[col + "_sql"])
    coverage = pd.read_csv(OUT / "coverage.csv")
    assert len(coverage) == 30 and coverage.n.sum() == len(recent)
    assert coverage[(coverage.meet == "영천") & coverage.n.gt(0)].status.eq("small_sample").all()
    assert coverage[(coverage.meet == "영천") & coverage.n.eq(0)].status.eq("no_data").all()
    result = dict(
        inputs_unchanged=True,
        readonly_database=True,
        existing_runners_checked=len(d),
        yeongcheon_confirmed_raw_rows_checked=len(source),
        yeongcheon_1200_rows_checked=len(y),
        derived_last600_checked=11,
        independent_sql_metrics=checks,
        independent_pace_groups=len(merged),
        grade_classifications_checked=classifications,
        strictly_prior_year_and_history=True,
        partition_sums=True,
        coverage_cells_checked=30,
    )
    (OUT / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
