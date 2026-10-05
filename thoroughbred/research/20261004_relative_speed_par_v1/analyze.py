"""Read-only 1200m sectional ratios, descriptive par candidates and temporal checks."""

import gzip
import importlib.util
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
SEED = 20261004
BOOT = 200
PART_DISTANCE = dict(
    early=200,
    middle1=400,
    middle2=400,
    late=200,
    last600=600,
    last400=400,
    closing4c=530,
    c4tog1=330,
)
STRUCTURES = ["region", "grade", "grade_band", "cell"]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


bench = module("bench", HERE.parent / "20261004_1200_benchmarks/analyze.py")
seoul = module("seoul4c", HERE.parent / "20261004_seoul4c_finish/analyze.py")


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def runtime_metadata():
    return dict(
        runtime=dict(
            python=platform.python_version(),
            numpy=np.__version__,
            pandas=pd.__version__,
            sklearn=bench.sklearn.__version__,
            duckdb=seoul.duckdb.__version__,
        ),
        reused_code_hashes=[
            dict(path=str(p.relative_to(ROOT)), sha256=bench.sha(p))
            for p in [Path(bench.__file__), Path(seoul.__file__)]
        ],
    )


def parts(meet):
    return bench.CORE + ["last600"] + (["closing4c", "c4tog1"] if meet == "서울" else ["last400"])


def load():
    d = bench.population()
    s = seoul.load_data()
    d = d.merge(
        s[["row_key", "c4", "g1", "g3", "p4", "p1", "closing4c", "c4tog1"]],
        how="left",
        on="row_key",
        validate="one_to_one",
    )
    hashes, names, checked = [], {}, 0
    for filename, group in d.groupby("source_file"):
        path = ROOT / filename
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            raw = json.load(stream)["response"]["body"]["items"]["item"]
        for row in group.itertuples():
            r = raw[int(row.source_item_index)]
            assert str(r["rcDate"]) == row.date.strftime("%Y%m%d")
            assert int(r["rcNo"]) == int(row.source_key.split(":")[-1])
            assert str(r["hrNo"]).zfill(7) == row.horse_id
            assert int(r["rcDist"]) == 1200 and int(r["ord"]) == row.rank
            values = {"finish": float(r["rcTime"])}
            if row.meet == "서울":
                values.update(
                    early=float(r["seS1fAccTime"]),
                    last600=values["finish"] - float(r["seG3fAccTime"]),
                    late=values["finish"] - float(r["seG1fAccTime"]),
                    c4=float(r["se_4cAccTime"]),
                    g1=float(r["seG1fAccTime"]),
                    g3=float(r["seG3fAccTime"]),
                    p4=float(r["sj_4cOrd"]),
                    p1=float(r["sjG1fOrd"]),
                )
            else:
                values.update(
                    early=float(r["buS1fTime"]),
                    last600=float(r["bu_3fGTime"]),
                    late=float(r["bu_1fGTime"]),
                )
                if np.isfinite(row.last400):
                    assert row.g400_source_file == filename
                    r400 = raw[int(row.g400_source_item_index)]
                    assert (str(r400["rcDate"]), int(r400["rcNo"]), str(r400["hrNo"]).zfill(7)) == (
                        row.date.strftime("%Y%m%d"),
                        int(row.source_key.split(":")[-1]),
                        row.horse_id,
                    )
                    values["last400"] = float(r400["bu_2fGTime"])
            values["middle1"] = values["finish"] - values["last600"] - values["early"]
            values["middle2"] = values["last600"] - values["late"]
            assert all(abs(value - getattr(row, key)) < 1e-7 for key, value in values.items())
            names[row.row_key] = r["hrName"]
            checked += 1
        hashes.append(dict(path=filename, sha256=bench.sha(path), checked_rows=len(group)))
    assert checked == 41623
    d["horse_name"] = d.row_key.map(names)
    for part, distance in PART_DISTANCE.items():
        d["rs_" + part] = 100 * distance * d.finish / (1200 * d[part])
    assert np.allclose(d.fs200, d.rs_late) and np.allclose(d.fs600, d.rs_last600)
    b = d.meet.eq("부산") & d.last400.notna()
    assert np.allclose(d.loc[b, "fs400"], d.loc[b, "rs_last400"])
    # Harmonic, distance-weighted ratios reconstruct the same overall speed.
    harmonic = sum(PART_DISTANCE[p] / 1200 / (d["rs_" + p] / 100) for p in bench.CORE)
    assert np.allclose(harmonic, 1)
    return d, hashes


def statistics(v):
    v = np.asarray(v, dtype=float)
    v = v[np.isfinite(v)]
    if not len(v):
        return {}
    q = np.quantile(v, [0.1, 0.2, 0.5, 0.8, 0.9])
    low, high = v[v <= q[1] + 1e-7], v[v >= q[3] - 1e-7]
    return dict(
        mean=v.mean(),
        p10=q[0],
        p20=q[1],
        median=q[2],
        p80=q[3],
        p90=q[4],
        low20_mean=low.mean(),
        high20_mean=high.mean(),
        low20_n=len(low),
        high20_n=len(high),
    )


def distributions(d):
    rows = []
    for meet, region in d[d.year.ge(2024)].groupby("meet"):
        for grade, band in (
            [("ALL", "ALL")]
            + [(g, "ALL") for g in bench.GRADES]
            + [(g, b) for g in bench.GRADES for b in bench.BANDS]
        ):
            cell = region
            if grade != "ALL":
                cell = cell[cell.grade.eq(grade)]
            if band != "ALL":
                cell = cell[cell.band.eq(band)]
            for cohort in ["all", "winner", "top3", "bottom3"]:
                g = cell
                if cohort == "winner":
                    g = g[g["rank"].eq(1)]
                elif cohort == "top3":
                    g = g[g["rank"].le(3)]
                elif cohort == "bottom3":
                    g = g[g["rank"].ge(g.n - 2)]
                for part in parts(meet):
                    a = g[g["rs_" + part].notna()]
                    rows.append(
                        dict(
                            meet=meet,
                            grade=grade,
                            band=band,
                            cohort=cohort,
                            part=part,
                            nominal_distance_m=PART_DISTANCE[part],
                            n=len(a),
                            races=a.source_key.nunique(),
                            dates=a.date.nunique(),
                            **statistics(a["rs_" + part]),
                        )
                    )
    return pd.DataFrame(rows)


def weighted_quantile(v, w, q):
    """Left-continuous weighted empirical quantile, ties kept in the selected cohort."""
    keep = np.asarray(w) > 0
    v, w = np.asarray(v)[keep], np.asarray(w)[keep]
    order = np.argsort(v, kind="stable")
    return float(v[order[np.searchsorted(np.cumsum(w[order]), q * w.sum(), side="left")]])


def select_fast(reference, expected, fraction=0.2, date_counts=None, thresholds=None):
    r = reference.copy()
    r["whole_residual"] = r.finish.to_numpy() - np.asarray(expected)
    w = r[r["rank"].eq(1)].copy()
    w["date_weight"] = 1.0 if date_counts is None else w.date.map(date_counts).fillna(0).to_numpy()
    if thresholds is None:
        thresholds = {}
        for grade, a in w.groupby("grade"):
            if a.date_weight.sum() > 0:
                thresholds[grade] = weighted_quantile(a.whole_residual, a.date_weight, fraction)
    w["threshold"] = w.grade.map(thresholds)
    good = w[w.whole_residual.le(w.threshold + 1e-7) & w.date_weight.gt(0)]
    ids = set(good.source_key)
    chosen = r[r.source_key.isin(ids) & r["rank"].le(3)].copy()
    return chosen, thresholds, good


def par_table(reference, chosen, date_counts=None, trim=False):
    meet = reference.meet.iloc[0]
    rows = []
    for part in parts(meet):
        a = chosen[chosen["rs_" + part].notna()].copy()
        if trim:
            lo, hi = a["rs_" + part].quantile([0.01, 0.99])
            a = a[a["rs_" + part].between(lo, hi)].copy()
        a["w"] = 1 / a.groupby("source_key").source_key.transform("size")
        if date_counts is not None:
            a["w"] *= a.date.map(date_counts).fillna(0)
        a = a[a.w.gt(0)].copy()
        value = "rs_" + part
        common = np.average(a[value], weights=a.w)
        gm, gc = {}, {}
        for grade in bench.GRADES:
            z = a[a.grade.eq(grade)]
            n = z.w.sum()
            gc[grade] = n
            gm[grade] = (np.dot(z.w, z[value]) + 40 * common) / (n + 40)
        a["grade_base"] = a.grade.map(gm)
        bm = {}
        for band in bench.BANDS:
            z = a[a.band.eq(band)]
            bm[band] = np.dot(z.w, z[value] - z.grade_base) / (z.w.sum() + 40)
        for grade in bench.GRADES:
            for band in bench.BANDS:
                z = a[a.grade.eq(grade) & a.band.eq(band)]
                n = z.w.sum()
                base = gm[grade] + bm[band]
                cell = base + np.dot(z.w, z[value] - base) / (n + 20)
                raw = reference[
                    reference.grade.eq(grade)
                    & reference.band.eq(band)
                    & reference["rs_" + part].notna()
                ]
                nr, nd = z.source_key.nunique(), z.date.nunique()
                rows.append(
                    dict(
                        meet=meet,
                        grade=grade,
                        band=band,
                        part=part,
                        nominal_distance_m=PART_DISTANCE[part],
                        region=common,
                        grade_par=gm[grade],
                        grade_band=base,
                        cell=cell,
                        raw_n=len(raw),
                        raw_races=raw.source_key.nunique(),
                        raw_dates=raw.date.nunique(),
                        reference_n=len(z),
                        reference_races=nr,
                        reference_dates=nd,
                        weighted_reference_races=n,
                        grade_reference_races=gc[grade],
                        local_mean=float(np.average(z[value], weights=z.w)) if n else np.nan,
                        support="local_supported"
                        if len(z) >= 60 and nr >= 20 and nd >= 20
                        else ("unobserved" if not len(raw) else "smoothed_sparse"),
                    )
                )
    return pd.DataFrame(rows)


def predict_par(table, d, part, structure):
    col = "grade_par" if structure == "grade" else structure
    mapping = table[table.part.eq(part)].set_index(["grade", "band"])[col]
    return np.array([mapping[g, b] for g, b in zip(d.grade, d.band, strict=True)])


def temporal(d):
    rows, selected, future_rows = [], {}, []
    for meet, region in d.groupby("meet"):
        for year in range(2021, 2027):
            tr, te = region[region.year.lt(year)], region[region.year.eq(year)]
            assert tr.date.max() < te.date.min()
            model = bench.Model(0).fit(tr)
            ref = tr[tr.year.ge(year - 3)]
            chosen, thresholds, good = select_fast(ref, model.predict(ref).finish)
            future, _, good_future = select_fast(
                te, model.predict(te).finish, thresholds=thresholds
            )
            table = par_table(ref, chosen)
            for part in parts(meet):
                a = future[future["rs_" + part].notna()]
                for structure in STRUCTURES:
                    p = predict_par(table, a, part, structure)
                    error = p - a["rs_" + part].to_numpy()
                    cell = a[["grade", "band", "source_key", "date", "rs_" + part]].copy()
                    cell["pred"] = p
                    c = cell.groupby(["grade", "band"]).agg(
                        observed=("rs_" + part, "mean"),
                        pred=("pred", "mean"),
                        n=("pred", "size"),
                        races=("source_key", "nunique"),
                        dates=("date", "nunique"),
                    )
                    c = c[(c.n >= 5) & (c.races >= 3) & (c.dates >= 3)]
                    rows.append(
                        dict(
                            meet=meet,
                            year=year,
                            stage="development" if year <= 2023 else "test",
                            part=part,
                            structure=structure,
                            reference_races=len(good),
                            test_races=len(good_future),
                            test_n=len(a),
                            cells=len(c),
                            cell_mae=float((c.pred - c.observed).abs().mean()),
                            runner_mae=float(np.average(abs(error), weights=bench.race_weights(a))),
                            bias=float(np.average(error, weights=bench.race_weights(a))),
                            constant100_mae=float(
                                np.average(
                                    abs(100 - a["rs_" + part]), weights=bench.race_weights(a)
                                )
                            ),
                            train_max=str(tr.date.max().date()),
                            test_min=str(te.date.min().date()),
                        )
                    )
                if year >= 2024:
                    c = a[["row_key", "date", "source_key", "grade", "band", "rs_" + part]].copy()
                    c["part"], c["year"], c["meet"] = part, year, meet
                    c["region_par"] = predict_par(table, a, part, "region")
                    for structure in STRUCTURES[1:]:
                        c[structure + "_par"] = predict_par(table, a, part, structure)
                    future_rows.append(c)
        dev = pd.DataFrame(rows)
        dev = dev[(dev.meet.eq(meet)) & dev.stage.eq("development")]
        for part, a in dev.groupby("part"):
            means = a.groupby("structure").cell_mae.mean()
            selected[meet + "|" + part] = next(
                s for s in STRUCTURES if means[s] <= means.min() + 0.01
            )
    result = pd.DataFrame(rows)
    result["selected_structure"] = [
        selected[m + "|" + p] for m, p in zip(result.meet, result.part, strict=True)
    ]
    result["selected"] = result.structure.eq(result.selected_structure)
    return result, selected, pd.concat(future_rows, ignore_index=True)


def final_tables(d, selected):
    final, selections, sensitivity, boot_reports, runner_results = [], [], [], [], []
    rng = np.random.default_rng(SEED)
    for meet, region in d.groupby("meet"):
        model = bench.Model(0).fit(region)
        ref = region[region.year.ge(2024)].copy()
        ref_expected = model.predict(ref).finish
        chosen, thresholds, good = select_fast(ref, ref_expected)
        table = par_table(ref, chosen)
        table["structure"] = [selected[meet + "|" + p] for p in table.part]
        table["par"] = [
            row.grade_par if row.structure == "grade" else getattr(row, row.structure)
            for row in table.itertuples()
        ]
        for label, fraction, trim in [
            ("fast10", 0.1, False),
            ("fast30", 0.3, False),
            ("trim1pct", 0.2, True),
            ("all_top3", 1.0, False),
        ]:
            z, _, _ = select_fast(ref, ref_expected, fraction)
            t = par_table(ref, z, trim=trim)
            for row, baseline in zip(t.itertuples(), table.itertuples(), strict=True):
                col = "grade_par" if baseline.structure == "grade" else baseline.structure
                sensitivity.append(
                    dict(
                        meet=meet,
                        grade=row.grade,
                        band=row.band,
                        part=row.part,
                        variant=label,
                        par=getattr(row, col),
                        baseline_par=baseline.par,
                        difference_pp=getattr(row, col) - baseline.par,
                    )
                )
        dates = np.sort(region.date.unique())
        x, y = model.x, region[bench.CORE].to_numpy()
        refmask = region.year.ge(2024).to_numpy()
        estimates = []
        for i in range(BOOT):
            counts = pd.Series(
                rng.choice(dates, size=len(dates)), dtype="datetime64[ns]"
            ).value_counts()
            weights = model.w * region.date.map(counts).fillna(0).to_numpy()
            weights *= len(weights) / weights.sum()
            reg = Ridge(alpha=10, solver="cholesky").fit(x, y, sample_weight=weights)
            expected = np.asarray(reg.predict(x[refmask])).sum(axis=1)
            z, _, _ = select_fast(ref, expected, date_counts=counts)
            t = par_table(ref, z, date_counts=counts)
            estimates.append(
                [
                    row.grade_par if base.structure == "grade" else getattr(row, base.structure)
                    for row, base in zip(t.itertuples(), table.itertuples(), strict=True)
                ]
            )
            if (i + 1) % 50 == 0:
                print(f"{meet}: bootstrap {i + 1}/{BOOT}", flush=True)
        draws = np.asarray(estimates)
        table["ci_low"], table["ci_high"] = np.quantile(draws, [0.025, 0.975], axis=0)
        table["ci_width_pp"] = table.ci_high - table.ci_low
        final.append(table)
        boot_reports.append(
            dict(
                meet=meet,
                repeats=BOOT,
                dates=len(dates),
                reference_races=len(good),
                reference_runners=len(chosen),
                thresholds_seconds=thresholds,
                preprocessing="fixed",
                structure="fixed from 2021-2023 development",
                model_refit=True,
                fast_races_reselected=True,
            )
        )
        good["meet"] = meet
        selections.append(
            good[
                [
                    "meet",
                    "source_key",
                    "date",
                    "grade",
                    "band",
                    "finish",
                    "whole_residual",
                    "threshold",
                ]
            ]
        )
        for part in parts(meet):
            a = ref[ref["rs_" + part].notna()].copy()
            a["part"] = part
            a["relative_speed"] = a["rs_" + part]
            a["par"] = predict_par(table, a, part, selected[meet + "|" + part])
            a["delta_pp"] = a.relative_speed - a.par
            runner_results.append(
                a[
                    [
                        "row_key",
                        "meet",
                        "date",
                        "source_key",
                        "horse_id",
                        "horse_name",
                        "grade",
                        "band",
                        "rank",
                        "finish",
                        "part",
                        "relative_speed",
                        "par",
                        "delta_pp",
                    ]
                ]
            )
    return (
        pd.concat(final, ignore_index=True),
        pd.concat(selections, ignore_index=True),
        pd.DataFrame(sensitivity),
        boot_reports,
        pd.concat(runner_results, ignore_index=True),
    )


def history_features(d):
    d = d.sort_values(["horse_id", "date", "row_key"]).copy()
    assert not d.duplicated(["horse_id", "date"]).any()
    columns = ["rs_" + p for p in bench.CORE + ["last600", "last400", "closing4c"]]
    h = []
    for _horse, a in d.groupby("horse_id", sort=False):
        assert a.date.is_monotonic_increasing
        previous = a.date.shift(1)
        assert (previous.dropna() < a.loc[previous.notna(), "date"]).all()
        for col in columns:
            a["history_" + col] = a[col].shift(1).rolling(3, min_periods=1).mean()
        a["history1200_count"] = np.minimum(np.arange(len(a)), 3)
        a["history1200_last_date"] = previous
        h.append(a)
    return pd.concat(h).sort_index()


def prediction_ablation(d):
    h = history_features(d)
    rows, predictions = [], []
    rng = np.random.default_rng(SEED + 1)
    for meet, region in h.groupby("meet"):
        extra = [
            "history_rs_" + p
            for p in bench.CORE + ["last600"] + (["closing4c"] if meet == "서울" else ["last400"])
        ] + ["history1200_count"]
        for year in [2024, 2025, 2026]:
            tr, te = region[region.year.lt(year)].copy(), region[region.year.eq(year)].copy()
            assert tr.date.max() < te.date.min()
            # Same metadata/history baseline in both arms. Do not assume race-final moisture
            # was known at entry finalization; its columns are constant in this separate test.
            for a in [tr, te]:
                a["band"] = "건조"
                a["interaction"] = a.grade + "|건조"
            pre = bench.Model(0).pre
            x, xx = pre.fit_transform(tr), pre.transform(te)
            impute = SimpleImputer(strategy="median", add_indicator=True)
            scale = StandardScaler()
            z = scale.fit_transform(impute.fit_transform(tr[extra]))
            zz = scale.transform(impute.transform(te[extra]))
            w = bench.race_weights(tr)
            base = Ridge(alpha=10, solver="cholesky").fit(x, tr.finish, sample_weight=w)
            added = Ridge(alpha=10, solver="cholesky").fit(
                np.column_stack([x, z]), tr.finish, sample_weight=w
            )
            a = te[
                [
                    "row_key",
                    "meet",
                    "date",
                    "source_key",
                    "finish",
                    "history1200_count",
                    "history1200_last_date",
                ]
            ].copy()
            a["year"] = year
            a["baseline"] = base.predict(xx)
            a["with_relative_history"] = added.predict(np.column_stack([xx, zz]))
            a["baseline_error"] = abs(a.baseline - a.finish)
            a["added_error"] = abs(a.with_relative_history - a.finish)
            race = (
                a.groupby(["date", "source_key"])[["baseline_error", "added_error"]]
                .mean()
                .reset_index()
            )
            delta = (race.added_error - race.baseline_error).to_numpy()
            dates = np.sort(race.date.unique())
            draws = []
            for _ in range(2000):
                counts = pd.Series(
                    rng.choice(dates, len(dates)), dtype="datetime64[ns]"
                ).value_counts()
                draws.append(np.average(delta, weights=race.date.map(counts).fillna(0)))
            lo, hi = np.quantile(draws, [0.025, 0.975])
            rows.append(
                dict(
                    meet=meet,
                    year=year,
                    n=len(a),
                    races=len(race),
                    dates=len(dates),
                    history_available_share=float(a.history1200_count.gt(0).mean()),
                    baseline_mae_seconds=race.baseline_error.mean(),
                    added_mae_seconds=race.added_error.mean(),
                    delta_seconds=delta.mean(),
                    paired_delta_ci_low=lo,
                    paired_delta_ci_high=hi,
                    train_max=str(tr.date.max().date()),
                    test_min=str(te.date.min().date()),
                    moisture_input="omitted",
                    current_outcomes_input="none",
                )
            )
            predictions.append(a)
    return pd.DataFrame(rows), pd.concat(predictions, ignore_index=True)


def web_export(table, selected):
    records = []
    for r in table.itertuples():
        records.append(
            dict(
                region=r.meet,
                distance_m=1200,
                grade=r.grade,
                moisture_band=r.band,
                section=r.part,
                nominal_section_m=r.nominal_distance_m,
                distance_status="nominal_checkpoint"
                if r.part in ["closing4c", "c4tog1"]
                else "nominal_section",
                display_scope="research_nominal_only"
                if r.part in ["closing4c", "c4tog1"]
                else "research_candidate",
                par_candidate_percent=round(r.par, 6),
                ci95_percent=[round(r.ci_low, 6), round(r.ci_high, 6)],
                support=r.support,
                raw_n=r.raw_n,
                reference_n=r.reference_n,
                reference_races=r.reference_races,
                reference_dates=r.reference_dates,
                structure=r.structure,
            )
        )
    return dict(
        version="1200-relative-par-research-v1-20261004",
        status="research_candidate",
        period_start="2024-01-01",
        period_end_by_region={"서울": "2026-09-20", "부산": "2026-09-18"},
        formula="100 * section_distance * whole_time / (1200 * section_time)",
        deviation_unit="percentage_points",
        optimality_proven=False,
        causal_effect=False,
        independent_ability_score=False,
        operating_model_applied=False,
        reference="Top three in grade-wise fastest 20% winner residual races",
        support_note=(
            "Support fields describe the local grade-moisture cell. Smoothed candidates borrow "
            "from grade, moisture and regional pools; narrow intervals do not validate "
            "sparse cells."
        ),
        pooled_reference_by_section=table.groupby(["meet", "part"])[
            ["reference_n", "reference_races"]
        ]
        .sum()
        .reset_index()
        .to_dict("records"),
        selected_structures=selected,
        cells=records,
    )


def main():
    OUT.mkdir(exist_ok=True)
    d, source_hashes = load()
    print(f"Raw API verified: {len(d)} runners", flush=True)
    distribution = distributions(d)
    distribution.to_csv(OUT / "relative_speed_distributions.csv", index=False)
    temporal_results, selected, future = temporal(d)
    temporal_results.to_csv(OUT / "temporal_par_validation.csv", index=False)
    future.to_parquet(OUT / "future_selected_runners.parquet", index=False)
    print("Development structures:", selected, flush=True)
    table, races, sensitivity, boot, runner = final_tables(d, selected)
    table.to_csv(OUT / "par_candidates.csv", index=False)
    races.to_csv(OUT / "selected_fast_races.csv", index=False)
    sensitivity.to_csv(OUT / "sensitivity.csv", index=False)
    runner.to_parquet(OUT / "recent_runner_relative_speed.parquet", index=False)
    ablation, predictions = prediction_ablation(d)
    ablation.to_csv(OUT / "history_prediction_ablation.csv", index=False)
    predictions.to_parquet(OUT / "history_prediction_rows.parquet", index=False)
    d[
        [
            "row_key",
            "meet",
            "date",
            "source_key",
            "grade",
            "band",
            "horse_id",
            "horse_name",
            "rank",
            "n",
            "finish",
        ]
        + list(PART_DISTANCE)
        + ["rs_" + p for p in PART_DISTANCE]
    ].to_parquet(OUT / "population_relative_speed.parquet", index=False)
    save_json(OUT / "web_relative_speed_par.json", web_export(table, selected))
    save_json(
        OUT / "summary.json",
        dict(
            runners=len(d),
            recent_runners=int(d.year.ge(2024).sum()),
            par_rows=len(table),
            selected=selected,
            bootstrap=boot,
            support=table.groupby(["meet", "support"])
            .size()
            .reset_index(name="n")
            .to_dict("records"),
            sources=source_hashes,
            input_hashes=[
                dict(path=str(p.relative_to(ROOT)), sha256=bench.sha(p))
                for p in [bench.PRIOR, bench.HISTORY, seoul.DB]
            ],
            **runtime_metadata(),
        ),
    )
    print(ablation.to_string(index=False), flush=True)
    print("Complete analysis outputs", flush=True)


if __name__ == "__main__":
    main()
