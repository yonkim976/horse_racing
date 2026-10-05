"""Independent arithmetic, exported-table and temporal-integrity verification."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
DISTANCES = dict(
    early=200,
    middle1=400,
    middle2=400,
    late=200,
    last600=600,
    last400=400,
    closing4c=530,
    c4tog1=330,
)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    d = pd.read_parquet(OUT / "population_relative_speed.parquet")
    assert len(d) == 41623 and not d.row_key.duplicated().any()
    assert np.allclose(d[["early", "middle1", "middle2", "late"]].sum(axis=1), d.finish)
    assert np.allclose(d.middle2 + d.late, d.last600)
    s = d[d.meet.eq("서울")]
    assert np.allclose(s.c4tog1 + s.late, s.closing4c)
    ratio_checks = 0
    for part, distance in DISTANCES.items():
        a = d[d[part].notna()]
        expected = (distance / a[part]) / (1200 / a.finish) * 100
        assert np.allclose(expected, a["rs_" + part], atol=1e-10, rtol=0)
        ratio_checks += len(a)
    distribution = pd.read_csv(OUT / "relative_speed_distributions.csv")
    statistic_checks = 0
    recent = d[d.date.dt.year.ge(2024)]
    for row in distribution[distribution.n.gt(0)].itertuples():
        a = recent[recent.meet.eq(row.meet)]
        if row.grade != "ALL":
            a = a[a.grade.eq(row.grade)]
        if row.band != "ALL":
            a = a[a.band.eq(row.band)]
        if row.cohort == "winner":
            a = a[a["rank"].eq(1)]
        elif row.cohort == "top3":
            a = a[a["rank"].le(3)]
        elif row.cohort == "bottom3":
            a = a[a["rank"].ge(a.n - 2)]
        a = a[a["rs_" + row.part].notna()]
        v = a["rs_" + row.part].to_numpy()
        assert len(a) == row.n and a.source_key.nunique() == row.races
        assert a.date.nunique() == row.dates
        stats = [np.mean(v), *np.quantile(v, [0.1, 0.2, 0.5, 0.8, 0.9])]
        expected = [row.mean, row.p10, row.p20, row.median, row.p80, row.p90]
        assert np.allclose(stats, expected, atol=1e-8, rtol=0)
        low, high = v[v <= row.p20 + 1e-7], v[v >= row.p80 - 1e-7]
        assert len(low) == row.low20_n and len(high) == row.high20_n
        assert np.allclose(
            [low.mean(), high.mean()], [row.low20_mean, row.high20_mean], atol=1e-8, rtol=0
        )
        statistic_checks += 8
    table = pd.read_csv(OUT / "par_candidates.csv")
    assert len(table) == 650 and not table.duplicated(["meet", "grade", "band", "part"]).any()
    assert table[["par", "ci_low", "ci_high"]].notna().all().all()
    assert table.ci_low.le(table.ci_high).all()
    for row in table.itertuples():
        expected = row.grade_par if row.structure == "grade" else getattr(row, row.structure)
        assert abs(row.par - expected) < 1e-9
        supported = (
            row.reference_n >= 60 and row.reference_races >= 20 and row.reference_dates >= 20
        )
        assert (row.support == "local_supported") == supported
    runner = pd.read_parquet(OUT / "recent_runner_relative_speed.parquet")
    assert not runner.duplicated(["row_key", "part"]).any()
    assert np.allclose(runner.relative_speed - runner.par, runner.delta_pp, atol=1e-10, rtol=0)
    for part, a in runner.groupby("part"):
        actual = a.row_key.map(d.set_index("row_key")["rs_" + part])
        assert np.allclose(actual, a.relative_speed, atol=1e-10, rtol=0)
    web = json.loads((OUT / "web_relative_speed_par.json").read_text())
    assert (
        len(web["cells"]) == 650
        and not web["optimality_proven"]
        and not web["operating_model_applied"]
    )
    keys = {(r.meet, r.grade, r.band, r.part): r for r in table.itertuples()}
    for cell in web["cells"]:
        row = keys[cell["region"], cell["grade"], cell["moisture_band"], cell["section"]]
        assert abs(cell["par_candidate_percent"] - row.par) <= 5.1e-7
    temporal = pd.read_csv(OUT / "temporal_par_validation.csv")
    summary = json.loads((OUT / "summary.json").read_text())
    for (meet, part), a in temporal[temporal.stage.eq("development")].groupby(["meet", "part"]):
        means = a.groupby("structure").cell_mae.mean()
        chosen = next(
            x for x in ["region", "grade", "grade_band", "cell"] if means[x] <= means.min() + 0.01
        )
        assert summary["selected"][meet + "|" + part] == chosen
    assert (pd.to_datetime(temporal.train_max) < pd.to_datetime(temporal.test_min)).all()
    pred = pd.read_parquet(OUT / "history_prediction_rows.parquet")
    assert len(pred) == 13313 and not pred.row_key.duplicated().any()
    history = d.sort_values(["horse_id", "date", "row_key"]).copy()
    history["last"] = history.groupby("horse_id").date.shift(1)
    history["count"] = history.groupby("horse_id").cumcount().clip(upper=3)
    join = pred.merge(history[["row_key", "last", "count"]], on="row_key", validate="one_to_one")
    known = join["last"].notna()
    assert (
        join.loc[known, "last"].to_numpy() == join.loc[known, "history1200_last_date"].to_numpy()
    ).all()
    assert (join.loc[known, "last"] < join.loc[known, "date"]).all()
    assert np.array_equal(join["count"], join.history1200_count)
    ablation = pd.read_csv(OUT / "history_prediction_ablation.csv")
    for row in ablation.itertuples():
        a = pred[pred.meet.eq(row.meet) & pred.year.eq(row.year)].copy()
        assert np.allclose(abs(a.baseline - a.finish), a.baseline_error)
        assert np.allclose(abs(a.with_relative_history - a.finish), a.added_error)
        r = a.groupby("source_key")[["baseline_error", "added_error"]].mean()
        assert np.allclose(
            [r.baseline_error.mean(), r.added_error.mean()],
            [row.baseline_mae_seconds, row.added_mae_seconds],
        )
    for source in (
        summary["sources"] + summary["input_hashes"] + summary.get("reused_code_hashes", [])
    ):
        assert sha(ROOT / source["path"]) == source["sha256"]
    report = dict(
        status="passed",
        independent_ratio_checks=ratio_checks,
        distribution_statistic_checks=statistic_checks,
        par_rows=650,
        recent_runner_section_rows=len(runner),
        strict_history_rows=len(join),
        development_selection_recomputed=True,
        input_hashes_unchanged=True,
        raw_api_checked_rows=sum(x["checked_rows"] for x in summary["sources"]),
        source_files=len(summary["sources"]),
        mismatches=0,
    )
    (OUT / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
