"""Read-only Seoul 1200m checkpoint analysis, with strictly past-year evaluation."""

import gzip
import importlib.util
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
spec = importlib.util.spec_from_file_location(
    "bench", HERE.parent / "20261004_1200_benchmarks/analyze.py"
)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
TARGETS = ["pre4c", "c4tog1", "late"]
PARTS = ["closing4c", "c4tog1", "late"]
EXTRA = ["pre4c", "leader_c4", "p4_pct"]


def load_data():
    d = bench.population()
    d = d[d.meet.eq("서울")].copy()
    with duckdb.connect(str(DB), read_only=True) as con:
        s = con.execute("""
            SELECT race_date AS date_key, race_no, horse_id,
              max(time_ms) FILTER (WHERE point_code='4C'
                AND measure_kind='cumulative_time')/1000.0 AS c4,
              max(time_ms) FILTER (WHERE point_code='G1F'
                AND measure_kind='cumulative_time')/1000.0 AS g1,
              max(time_ms) FILTER (WHERE point_code='G3F'
                AND measure_kind='cumulative_time')/1000.0 AS g3,
              max(passing_order) FILTER (WHERE point_code='4C'
                AND measure_kind='passing_order') AS p4,
              max(passing_order) FILTER (WHERE point_code='G1F'
                AND measure_kind='passing_order') AS p1
            FROM section_measurements_api WHERE meet=1 AND race_date>='20180101'
            GROUP BY race_date, race_no, horse_id
        """).df()
    s["row_key"] = "서울:" + s.date_key + ":" + s.race_no.astype(str) + ":" + s.horse_id
    d = d.merge(s.drop(columns="horse_id"), on="row_key", validate="one_to_one")
    assert len(d) == 24961 and not d.row_key.duplicated().any()
    assert d[["c4", "g1", "g3", "p4", "p1"]].notna().all().all()
    d["pre4c"] = d.c4
    d["closing4c"] = d.finish - d.c4
    d["c4tog1"] = d.g1 - d.c4
    assert np.allclose(d.finish - d.g1, d.late)
    assert (d[TARGETS] > 0).all().all()
    assert ((d.p4 >= 1) & (d.p4 <= d.n)).all()
    assert ((d.p1 >= 1) & (d.p1 <= d.n)).all()
    assert not d.duplicated(["source_key", "p4"]).any()
    leaders = d[d.p4.eq(1)][["source_key", "c4", "finish", "closing4c"]].rename(
        columns={"c4": "leader_c4", "finish": "leader_finish", "closing4c": "leader_closing"}
    )
    d = d.merge(leaders, on="source_key", validate="many_to_one")
    assert d.leader_c4.notna().all()
    d["p4_pct"] = (d.p4 - 1) / (d.n - 1)
    d["position4c"] = np.select(
        [d.p4_pct <= 1 / 3, d.p4_pct <= 2 / 3], ["앞", "중간"], default="뒤"
    )
    d["gain4to1"] = d.p4 - d.p1
    d["gain1tofin"] = d.p1 - d["rank"]
    d["gain4tofin"] = d.p4 - d["rank"]
    d["gap4c"] = d.c4 - d.leader_c4
    d["gapfin_same_leader"] = d.finish - d.leader_finish
    d["recovered_seconds"] = d.leader_closing - d.closing4c
    assert np.allclose(d.gap4c - d.gapfin_same_leader, d.recovered_seconds)
    return d.sort_values(["date", "row_key"]).reset_index(drop=True)


def verify_raw(d):
    hashes, checked = [], 0
    names = {}
    for name, group in d.groupby("source_file"):
        path = ROOT / name
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            raw = json.load(stream)["response"]["body"]["items"]["item"]
        for row in group.itertuples():
            r = raw[int(row.source_item_index)]
            assert str(r["rcDate"]) == row.date_key
            assert int(r["rcNo"]) == row.race_no
            assert str(r["hrNo"]).zfill(7) == row.horse_id
            assert int(r["rcDist"]) == 1200
            names[row.row_key] = r["hrName"]
            for key, value in [
                ("se_4cAccTime", row.c4),
                ("seG1fAccTime", row.g1),
                ("seG3fAccTime", row.g3),
                ("rcTime", row.finish),
                ("sj_4cOrd", row.p4),
                ("sjG1fOrd", row.p1),
                ("ord", row.rank),
            ]:
                assert abs(float(r[key]) - value) < 1e-7
            checked += 1
        hashes.append(dict(path=name, sha256=bench.sha(path), checked_rows=len(group)))
    assert checked == len(d)
    d["horse_name"] = d.row_key.map(names)
    return hashes


class SectionModel:
    def __init__(self, conditional=False):
        self.pre = bench.Model(0).pre
        self.scaler = StandardScaler()
        self.reg = Ridge(alpha=10, solver="cholesky")
        self.conditional = conditional

    def fit(self, d):
        x = self.pre.fit_transform(d)
        if self.conditional:
            x = np.column_stack([x, self.scaler.fit_transform(d[EXTRA])])
        targets = ["closing4c"] if self.conditional else TARGETS
        self.reg.fit(x, d[targets], sample_weight=bench.race_weights(d))
        return self

    def predict(self, d):
        x = self.pre.transform(d)
        if self.conditional:
            x = np.column_stack([x, self.scaler.transform(d[EXTRA])])
            return np.asarray(self.reg.predict(x)).reshape(-1)
        v = pd.DataFrame(self.reg.predict(x), index=d.index, columns=TARGETS)
        v["closing4c"] = v.c4tog1 + v.late
        return v


def out_of_time(d):
    rows, checks, cellchecks = [], [], []
    for year in [2024, 2025, 2026]:
        tr, te = d[d.year.lt(year)], d[d.year.eq(year)].copy()
        assert tr.date.max() < te.date.min()
        basic, conditional = SectionModel().fit(tr), SectionModel(True).fit(tr)
        pred, train_pred = basic.predict(te), basic.predict(tr)
        te["expected_pre4c"] = pred.pre4c
        te["expected_closing_basic"] = pred.closing4c
        te["expected_closing_at4c"] = conditional.predict(te)
        te["early_residual"] = te.pre4c - te.expected_pre4c
        te["closing_residual"] = te.closing4c - te.expected_closing_at4c
        te["relative_late200"] = te.late - pred.late
        te["pace_group"] = ""
        te["closing_group"] = ""
        train_early = tr.pre4c - train_pred.pre4c
        train_close = tr.closing4c - conditional.predict(tr)
        for grade in bench.GRADES:
            mask = te.grade.eq(grade)
            a, b = train_early[tr.grade.eq(grade)].quantile([0.25, 0.75])
            c, e = train_close[tr.grade.eq(grade)].quantile([0.2, 0.8])
            te.loc[mask, "pace_group"] = np.select(
                [te.loc[mask, "early_residual"] < a, te.loc[mask, "early_residual"] > b],
                ["4C까지빠름", "4C까지느림"],
                default="4C까지보통",
            )
            te.loc[mask, "closing_group"] = np.select(
                [te.loc[mask, "closing_residual"] <= c, te.loc[mask, "closing_residual"] >= e],
                ["기대보다빠름", "기대보다느림"],
                default="기대범위",
            )
        # The published benchmark has no individual runner context. Validate that
        # separate use case using only the previous three years as its reference.
        trref = tr[tr.year.ge(year - 3)]
        probe = tr.iloc[[0]].copy()
        probe["band"], probe["interaction"] = "건조", probe.grade.iloc[0] + "|건조"
        dry_pred = basic.predict(probe).closing4c.iloc[0]
        shift = {}
        for band in bench.BANDS:
            probe["band"], probe["interaction"] = band, probe.grade.iloc[0] + "|" + band
            shift[band] = basic.predict(probe).closing4c.iloc[0] - dry_pred
        for (grade, band), z in te.groupby(["grade", "band"]):
            ref = trref[trref.grade.eq(grade)]
            if len(ref) < 30 or len(z) < 20:
                continue
            values = ref.closing4c.to_numpy() - ref.band.map(shift).to_numpy() + shift[band]
            stat = bench.stats(values)
            cellchecks.append(
                dict(
                    year=year,
                    grade=grade,
                    band=band,
                    test_n=len(z),
                    reference_n=len(ref),
                    predicted_mean=stat["mean"],
                    observed_mean=z.closing4c.mean(),
                    mean_error=stat["mean"] - z.closing4c.mean(),
                    fast20_share=z.closing4c.le(stat["p20"] + bench.EPS).mean(),
                    slow20_share=z.closing4c.ge(stat["p80"] - bench.EPS).mean(),
                )
            )
        rows.append(te)
        checks.append(
            dict(
                year=year,
                train_n=len(tr),
                test_n=len(te),
                train_end=str(tr.date.max().date()),
                test_start=str(te.date.min().date()),
                closing_mae_basic=float(np.mean(abs(te.closing4c - pred.closing4c))),
                closing_mae_at4c=float(np.mean(abs(te.closing_residual))),
            )
        )
    return pd.concat(rows, ignore_index=True), pd.DataFrame(checks), pd.DataFrame(cellchecks)


def profiles(d, keys):
    rows = []
    for key, g in d.groupby(keys, observed=True):
        key = key if isinstance(key, tuple) else (key,)
        rows.append(
            dict(
                zip(keys, key, strict=True),
                n=len(g),
                races=g.source_key.nunique(),
                days=g.date.nunique(),
                closing4c_mean=g.closing4c.mean(),
                c4tog1_mean=g.c4tog1.mean(),
                late200_mean=g.late.mean(),
                mean_gain=g.gain4tofin.mean(),
                gain_rate=g.gain4tofin.gt(0).mean(),
                mean_gain4to1=g.gain4to1.mean(),
                mean_gain1tofin=g.gain1tofin.mean(),
                gain2_rate=g.gain4tofin.ge(2).mean(),
                top3_rate=g["rank"].le(3).mean(),
                recovered_mean=g.recovered_seconds.mean(),
            )
        )
    return pd.DataFrame(rows)


def benchmarks(d):
    model = SectionModel().fit(d)
    recent = d[d.year.ge(2024)].copy()
    effects, rows, refrows = [], [], []
    for grade in bench.GRADES:
        g = recent[recent.grade.eq(grade)].copy()
        probe = g.iloc[[0]].copy()
        probe["band"] = "건조"
        probe["interaction"] = grade + "|건조"
        dry = model.predict(probe).iloc[0]
        shifts = {}
        for band in bench.BANDS:
            probe["band"], probe["interaction"] = band, grade + "|" + band
            shifts[band] = model.predict(probe).iloc[0] - dry
            for part in PARTS:
                effects.append(
                    dict(
                        grade=grade, band=band, part=part, effect_seconds=float(shifts[band][part])
                    )
                )
        dry_times = g[PARTS].to_numpy() - np.stack([shifts[b][PARTS] for b in g.band])
        dryframe = g[["row_key", "grade", "band"]].copy()
        dryframe[PARTS] = dry_times
        refrows.append(dryframe)
        for band in bench.BANDS:
            observed = g[g.band.eq(band)]
            historical = d[d.grade.eq(grade) & d.band.eq(band)]
            support = (
                len(observed) >= 200
                and observed.source_key.nunique() >= 20
                and observed.date.nunique() >= 20
            )
            status = "관측지원" if support else "소표본추정"
            if observed.empty:
                status = "최근관측없음"
            if historical.empty:
                status = "전체기간관측없음"
            for j, part in enumerate(PARTS):
                v = dry_times[:, j] + shifts[band][part]
                result = dict(
                    grade=grade,
                    band=band,
                    part=part,
                    reference_n=len(g),
                    observed_n=len(observed),
                    observed_days=observed.date.nunique(),
                    observed_races=observed.source_key.nunique(),
                    status=status,
                    observed_mean=observed[part].mean(),
                    **bench.stats(v),
                )
                rows.append(result)
    return pd.DataFrame(rows), pd.DataFrame(effects), pd.concat(refrows, ignore_index=True)


def main():
    OUT.mkdir(exist_ok=True)
    d = load_data()
    raw_hashes = verify_raw(d)
    recent, validation, cell_validation = out_of_time(d)
    b, effects, refs = benchmarks(d)
    b.to_csv(OUT / "estimated_benchmarks.csv", index=False)
    effects.to_csv(OUT / "state_effects.csv", index=False)
    refs.to_parquet(OUT / "dry_reference.parquet", index=False)
    validation.to_csv(OUT / "temporal_validation.csv", index=False)
    cell_validation.to_csv(OUT / "temporal_benchmark_validation.csv", index=False)
    recent.to_parquet(OUT / "runner_4c_analysis.parquet", index=False)
    profiles(recent, ["position4c"]).to_csv(OUT / "position_profiles.csv", index=False)
    profiles(recent, ["grade", "position4c"]).to_csv(
        OUT / "grade_position_profiles.csv", index=False
    )
    profiles(recent, ["pace_group", "closing_group"]).to_csv(
        OUT / "pace_closing_profiles.csv", index=False
    )
    distribution = []
    for (grade, band), g in recent.groupby(["grade", "band"]):
        for cohort, subset in [
            ("전체", g),
            ("상위착순3두", g[g["rank"].le(3)]),
            ("하위착순3두", g[g["rank"].ge(g.n - 2)]),
        ]:
            for part in PARTS:
                distribution.append(
                    dict(
                        grade=grade,
                        band=band,
                        cohort=cohort,
                        part=part,
                        n=len(subset),
                        **bench.stats(subset[part]),
                    )
                )
    pd.DataFrame(distribution).to_csv(OUT / "observed_cohorts.csv", index=False)
    corr = recent[["closing4c", "c4tog1", "late", "last600"]].corr()
    corr.to_csv(OUT / "section_correlations.csv")
    examples = recent[recent.date_key.eq("20260920") & recent.race_no.eq(11)].copy()
    examples[
        [
            "row_key",
            "horse_name",
            "grade",
            "band",
            "rank",
            "p4",
            "p1",
            "c4",
            "finish",
            "closing4c",
            "c4tog1",
            "late",
            "gain4tofin",
            "recovered_seconds",
            "expected_closing_at4c",
            "closing_residual",
        ]
    ].to_csv(OUT / "latest_race_examples.csv", index=False)
    sensitivity = []
    for grade, g in recent.groupby("grade"):
        p01, p99 = g.closing4c.quantile([0.01, 0.99])
        trimmed = g[g.closing4c.between(p01, p99)]
        sensitivity.append(
            dict(
                grade=grade,
                n=len(g),
                raw_mean=g.closing4c.mean(),
                median=g.closing4c.median(),
                trim1_mean=trimmed.closing4c.mean(),
                trim1_n=len(trimmed),
                p01=p01,
                p99=p99,
            )
        )
    pd.DataFrame(sensitivity).to_csv(OUT / "tail_sensitivity.csv", index=False)
    summary = dict(
        study="서울1200m 4C 이후",
        official_remaining_label_m=530,
        source_definition_url="https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1",
        n_all=len(d),
        n_recent=len(recent),
        races_recent=recent.source_key.nunique(),
        days_recent=recent.date.nunique(),
        start=str(d.date.min().date()),
        reference_start=str(recent.date.min().date()),
        end=str(d.date.max().date()),
        core_db_sha256=bench.sha(DB),
        parent_sha256=bench.sha(bench.PRIOR),
        history_sha256=bench.sha(bench.HISTORY),
        raw_sources=raw_hashes,
        correlation_4c_last600=corr.loc["closing4c", "last600"],
        correlation_4c_late200=corr.loc["closing4c", "late"],
        g3_to_4c_mean_seconds=float((d.c4 - d.g3).mean()),
        dry_grade_means=b[b.band.eq("건조") & b.part.eq("closing4c")][
            ["grade", "mean", "p20", "median", "p80", "fast20_mean", "slow20_mean"]
        ].to_dict("records"),
        validation=validation.to_dict("records"),
        benchmark_cell_validation=dict(
            eligible_cells=len(cell_validation),
            equal_cell_mean_absolute_error=float(cell_validation.mean_error.abs().mean()),
            fast20_share=float(
                np.average(cell_validation.fast20_share, weights=cell_validation.test_n)
            ),
            slow20_share=float(
                np.average(cell_validation.slow20_share, weights=cell_validation.test_n)
            ),
        ),
    )
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in [
                    "n_all",
                    "n_recent",
                    "races_recent",
                    "days_recent",
                    "correlation_4c_last600",
                    "dry_grade_means",
                    "validation",
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
