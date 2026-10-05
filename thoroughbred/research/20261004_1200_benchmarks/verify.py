"""Independent SQL summaries, coefficient contrasts, distributions and dated scores."""

import json

import duckdb
import numpy as np
import pandas as pd
from analyze import CORE, HISTORY, OUT, PARTS, PRIOR, ROOT, Model, sha
from evaluate_record import evaluate


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    for name, digest in summary["inputs"].items():
        assert sha(ROOT / name) == digest
    d = pd.read_parquet(PRIOR)
    d = d[d.population.eq("실전1200")].copy()
    assert len(d) == 41623 and set(d.meet) == {"서울", "부산"}
    d["date"] = pd.to_datetime(d.date)
    recent = d[d.year.ge(2024)].copy()
    table = pd.read_csv(OUT / "estimated_benchmarks.csv")
    assert len(table) == 650 and len(table[table.part.eq("finish")]) == 100
    assert not table.duplicated(["meet", "grade", "band", "part"]).any()
    assert not ((table.meet == "서울") & (table.part == "last400")).any()
    assert table[["mean", "p20", "median", "p80"]].notna().all().all()
    assert (table.p10 <= table.p20).all() and (table.p20 <= table["median"]).all()
    assert (table["median"] <= table.p80).all() and (table.p80 <= table.p90).all()
    assert (table.bootstrap_valid_n >= 180).all()

    raw = pd.read_csv(OUT / "observed_time_distribution.csv")
    long = recent.melt(
        id_vars=["meet", "grade", "band", "source_key", "date"],
        value_vars=PARTS,
        var_name="part",
        value_name="time",
    )
    long["time"] = long.time.round(9)
    with duckdb.connect() as con:
        con.register("times", long)
        stats = con.execute("""
          WITH s AS (
            SELECT meet,grade,band,part, count(time) n, count(DISTINCT source_key) races,
                   count(DISTINCT date) AS "days", avg(time) mean,
                   round(quantile_cont(time,0.1),9) p10,
                   round(quantile_cont(time,0.2),9) p20,
                   round(quantile_cont(time,0.5),9) median,
                   round(quantile_cont(time,0.8),9) p80,
                   round(quantile_cont(time,0.9),9) p90
            FROM times WHERE time IS NOT NULL GROUP BY 1,2,3,4
          ) SELECT s.*,avg(t.time) FILTER(WHERE t.time<=s.p20+1e-7) fast20_mean,
              avg(t.time) FILTER(WHERE t.time>s.p20+1e-7 AND t.time<s.p80-1e-7) middle60_mean,
              avg(t.time) FILTER(WHERE t.time>=s.p80-1e-7) slow20_mean
            FROM s JOIN times t USING(meet,grade,band,part) GROUP BY ALL
        """).fetchdf()
    keys = ["meet", "grade", "band", "part"]
    joined = raw[raw.n.gt(0)].merge(stats, on=keys, suffixes=("_a", "_b"), validate="one_to_one")
    assert len(joined) == len(stats) == len(raw[raw.n.gt(0)])
    numeric_checks = 0
    for field in [
        "n",
        "races",
        "days",
        "mean",
        "p10",
        "p20",
        "median",
        "p80",
        "p90",
        "fast20_mean",
        "middle60_mean",
        "slow20_mean",
    ]:
        assert np.allclose(joined[field + "_a"], joined[field + "_b"], atol=1e-9, equal_nan=True)
        numeric_checks += len(joined)

    effects = pd.read_csv(OUT / "state_effects.csv").set_index(keys).shift_from_dry
    coef = pd.read_csv(OUT / "model_coefficients.csv")
    for (meet, grade, band, part), delta in effects.items():
        if part not in CORE + ["last400"]:
            continue
        cc = coef[coef.meet.eq(meet) & coef.part.eq(part)].set_index("feature").coefficient
        scale = summary["selected_interaction_scale"][meet]
        independent = cc["band__band_" + band] - cc["band__band_건조"]
        independent += scale * (
            cc["interaction__interaction_" + grade + "|" + band]
            - cc["interaction__interaction_" + grade + "|건조"]
        )
        assert np.isclose(delta, independent, atol=1e-9)
        numeric_checks += 1

    refs = pd.read_parquet(OUT / "reference_dry_times.parquet")
    assert len(refs) == 13313 and not refs.row_key.duplicated().any()
    assert np.allclose(refs[CORE].sum(axis=1), refs.finish)
    assert np.allclose(refs.middle2 + refs.late, refs.last600)
    raw_join = recent.merge(refs, on="row_key", suffixes=("_raw", "_ref"), validate="one_to_one")
    for part in PARTS:
        ok = raw_join[part + "_raw"].notna()
        values = raw_join.loc[ok, part + "_raw"].to_numpy()
        shifts = np.array(
            [
                effects[m, g, b, part]
                for m, g, b in zip(
                    raw_join.loc[ok, "meet_raw"],
                    raw_join.loc[ok, "grade_raw"],
                    raw_join.loc[ok, "band"],
                    strict=True,
                )
            ]
        )
        assert np.allclose(values - shifts, raw_join.loc[ok, part + "_ref"], atol=1e-9)
        numeric_checks += int(ok.sum())
    for row in table.itertuples():
        v = (
            refs.loc[refs.meet.eq(row.meet) & refs.grade.eq(row.grade), row.part]
            .dropna()
            .to_numpy()
        )
        v = np.round(v + effects[row.meet, row.grade, row.band, row.part], 9)
        q = np.round(np.quantile(v, [0.1, 0.2, 0.5, 0.8, 0.9]), 9)
        assert np.allclose([row.p10, row.p20, row.median, row.p80, row.p90], q)
        assert np.isclose(row.mean, v.mean())
        assert np.isclose(row.fast20_mean, v[v <= q[1] + 1e-7].mean())
        assert np.isclose(row.slow20_mean, v[v >= q[3] - 1e-7].mean())
        numeric_checks += 8
        response = evaluate(row.meet, row.grade, row.band, row.part, float(row.median))
        tie_allowance = 50 * np.count_nonzero(np.abs(v - row.median) <= 1e-7) / len(v) + 0.01
        assert abs(response["same_grade_record_score"] - 50) <= tie_allowance
    means = table.pivot(index=["meet", "grade", "band"], columns="part", values="mean")
    assert np.allclose(means[CORE].sum(axis=1), means.finish)
    assert np.allclose(means.middle2 + means.late, means.last600)
    cohorts = pd.read_csv(OUT / "estimated_finish_cohorts.csv").pivot(
        index=["meet", "grade", "band", "cohort"], columns="part", values="mean"
    )
    assert np.allclose(cohorts[CORE].sum(axis=1), cohorts.finish)

    # Rebuild rank joins without using the analysis population function.
    h = pd.read_parquet(HISTORY)
    h = h[h.distance_m.eq(1200)].copy()
    h["date"] = pd.to_datetime(h.date)
    h["row_key"] = (
        h.meet.map({1: "서울", 3: "부산"})
        + ":"
        + h.date.dt.strftime("%Y%m%d")
        + ":"
        + h.race_no.astype(str)
        + ":"
        + h.horse_id
    )
    dd = d.merge(h[["row_key", "rank", "n"]], on="row_key", validate="one_to_one")
    observed = pd.read_csv(OUT / "observed_rank_cohorts.csv")
    for row in observed.itertuples():
        cc = dd[
            dd.year.ge(2024) & dd.meet.eq(row.meet) & dd.grade.eq(row.grade) & dd.band.eq(row.band)
        ]
        if row.cohort == "top3_rank":
            cc = cc[cc["rank"].le(3)]
        elif row.cohort == "bottom3_rank":
            cc = cc[cc["rank"].gt(cc.n - 3)]
        assert row.n == cc[row.part].count() and np.isclose(row.mean, cc[row.part].mean())
        numeric_checks += 2

    temporal = pd.read_parquet(OUT / "historical_record_scores.parquet")
    assert len(temporal) == 13313 and not temporal.row_key.duplicated().any()
    assert (temporal.reference_max_date < temporal.date).all()
    assert temporal.score_finish.between(0, 100).all()
    assert temporal.score_distance_finish.between(0, 100).all()
    score_checks = 0
    d["rating"] = d.rating.mask(d.rating.le(0))
    d["interaction"] = d.grade + "|" + d.band
    for meet in ["서울", "부산"]:
        for year in [2024, 2025, 2026]:
            tr = d[d.meet.eq(meet) & d.year.lt(year)]
            ref = tr[tr.year.ge(year - 3)]
            m = Model(summary["selected_interaction_scale"][meet]).fit(tr)
            ef = m.effects(tr)
            current = temporal[temporal.meet.eq(meet) & temporal.date.dt.year.eq(year)]
            base = ref[PARTS].to_numpy() - np.stack(
                [ef[g, b] for g, b in zip(ref.grade, ref.band, strict=True)]
            )
            for (grade, band), cc in current.groupby(["grade", "band"]):
                mask = ref.grade.eq(grade).to_numpy()
                for part in PARTS:
                    pos = PARTS.index(part)
                    values = base[mask, pos] + ef[grade, band][pos]
                    values = np.round(values[np.isfinite(values)], 9)
                    if not len(values):
                        assert cc["score_" + part].isna().all()
                        continue
                    # Independent pairwise definition, without searchsorted/analysis score.
                    t = np.round(cc[part].to_numpy(), 9)
                    expected = (
                        100
                        * (
                            (values[:, None] > t + 1e-7).sum(axis=0)
                            + 0.5 * (np.abs(values[:, None] - t) <= 1e-7).sum(axis=0)
                        )
                        / len(values)
                    )
                    assert np.allclose(expected, cc["score_" + part], atol=1e-8)
                    score_checks += len(cc)
                pooled = np.round(base[:, PARTS.index("finish")], 9)
                dry = np.round(cc.finish.to_numpy() - ef[grade, band][PARTS.index("finish")], 9)
                expected = (
                    100
                    * (
                        (pooled[:, None] > dry + 1e-7).sum(axis=0)
                        + 0.5 * (np.abs(pooled[:, None] - dry) <= 1e-7).sum(axis=0)
                    )
                    / len(pooled)
                )
                assert np.allclose(expected, cc.score_distance_finish, atol=1e-8)
                score_checks += len(cc)
    for name in [
        "development_validation",
        "temporal_mean_validation",
        "temporal_threshold_validation",
        "hidden_cell_validation",
    ]:
        a = pd.read_csv(OUT / (name + ".csv"))
        assert (pd.to_datetime(a.train_max).dt.year < a.year).all()
    hidden = pd.read_csv(OUT / "hidden_cell_validation.csv")
    assert (hidden.removed_n >= 100).all() and (hidden.test_days >= 5).all()
    result = dict(
        passed=True,
        input_hashes_unchanged=True,
        venues=["서울", "부산"],
        input_rows=41623,
        reference_rows=13313,
        benchmark_rows=650,
        whole_time_cells=100,
        observed_whole_time_cells=88,
        estimated_only_recent_cells=12,
        numeric_checks=numeric_checks,
        chronological_score_checks=score_checks,
        hidden_cells=len(hidden),
        min_valid_bootstrap=int(table.bootstrap_valid_n.min()),
        all_sections_sum=True,
        score_direction_and_dates=True,
        limitation=(
            "Validates arithmetic, source preservation and chronology; "
            "not future profitability or causal track effects"
        ),
    )
    (OUT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
