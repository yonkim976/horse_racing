"""Read-only retrospective section study; annual references use strictly earlier years."""

import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
RESEARCH = HERE.parent
TRIAL = RESEARCH / "20261003_trial_time_baselines/outputs/participants.parquet"
RACE = RESEARCH / "20261002_track_source_reconciliation/results/api_study_population.parquet"
HISTORY = RESEARCH / "20261002_gate_lateral_bias/outputs/runners.parquet"
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
KEY = ["meet", "date", "race_no", "horse_id"]
BANDS = ["건조", "양호", "다습", "포화", "불량"]
PARTS = ["finish", "early", "middle1", "middle2", "middle", "late", "last600", "last400"]
LABELS = ["빠름", "보통", "느림"]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def prepare():
    t = pd.read_parquet(TRIAL)
    trial_new = t.api_reason.eq("주행미합(신)") & t.api_passFlag.isin(["합격", "불합격"])
    t = t.loc[trial_new].copy()
    t["valid"] = t.valid_core & t.moisture_band.isin(BANDS)
    t["exclusion_reason"] = t.quality_flags.fillna("").astype(str)
    t.loc[~t.moisture_band.isin(BANDS), "exclusion_reason"] += "|missing_moisture"
    t["population"] = "주행심사1000"
    t["band"] = t.moisture_band
    t["early"] = t.s1f
    t["middle1"] = t.middle200
    t["middle2"] = t.middle400
    t["late"] = t.g1f
    t["last600"] = t.g3f
    t["last400"] = t.g400.where(t.valid_g400)
    t["weight"] = pd.to_numeric(t.api_wgBudam, errors="coerce")
    t["sex"] = t.api_sex.fillna("미상")
    t["grade"] = "주행미합(신)"
    t["passed"] = t.api_passFlag.eq("합격")
    t["row_key"] = t.participant_row_id
    t["source_key"] = t.trial_session_id

    a = pd.read_parquet(RACE)
    h = pd.read_parquet(HISTORY)
    a = a[a.distance_m.eq(1200)].copy()
    h = h[h.distance_m.eq(1200)].copy()
    for f in (a, h):
        f["date"] = pd.to_datetime(f.date)
    assert not a.duplicated(KEY).any() and not h.duplicated(KEY).any()
    history_cols = [
        "age",
        "rating",
        "prior_finish",
        "prior_top3",
        "prior_early",
        "log_starts",
        "log_gap",
        "last_history_date",
    ]
    r = a.merge(h[KEY + history_cols], on=KEY, validate="one_to_one", how="inner")
    assert len(r) == len(h)
    # Add source sex using fixed, read-only SQL; no credentials, dynamic SQL, or writes.
    with duckdb.connect(str(DB), read_only=True) as c:
        g400 = c.execute("""SELECT meet, race_date AS date, race_no, horse_id,
            time_ms / 1000.0 AS last400, source_file AS g400_source_file,
            source_item_index AS g400_source_item_index
            FROM section_measurements_api WHERE meet=3 AND point_code='2F_G'
            AND measure_kind='closing_time' AND source_field='bu_2fGTime'
            AND race_date >= '20180101'""").fetchdf()
        sex = c.execute("""SELECT CAST(source_meet AS INTEGER) AS meet,
            result_date AS date, CAST(result_race_no AS INTEGER) AS race_no,
            horse_id_raw AS horse_id, horse_sex_raw AS sex
            FROM confirmed_runners WHERE source_meet IN ('1','3')
            AND race_distance_m_raw='1200' AND result_date >= '20180101'""").fetchdf()
    for f in (g400, sex):
        f["date"] = pd.to_datetime(f.date)
        assert not f.duplicated(KEY).any()
    r = r.merge(g400, on=KEY, how="left", validate="one_to_one")
    r = r.merge(sex, on=KEY, how="left", validate="one_to_one")
    assert r.sex.notna().all()
    r["population"] = "실전1200"
    r["meet"] = r.meet.map({1: "서울", 3: "부산"})
    r["finish"] = r.finish / 1000
    r["early"] = r.start_200 / 1000
    r["late"] = r.last_200 / 1000
    r["last600"] = r.last_600 / 1000
    r["middle1"] = r.finish - r.last600 - r.early
    r["middle2"] = r.last600 - r.late
    r["grade"] = r.grade_normalized.fillna("미상")
    r["passed"] = False
    r["source_key"] = r["meet"] + ":" + r.date.dt.strftime("%Y%m%d") + ":" + r.race_no.astype(str)
    r["row_key"] = r.source_key + ":" + r.horse_id
    valid = r.finish.between(60, 110) & r.early.between(10, 25) & r.late.between(8, 25)
    valid &= r.middle1.between(16, 45) & r.middle2.between(16, 45)
    r["valid"] = valid
    r["exclusion_reason"] = np.where(valid, "", "physical_section_bounds")
    gvalid = r.last400.between(16, 50) & (r.last400 > r.late) & (r.last400 < r.last600)
    r["last400"] = r.last400.where(gvalid)
    history_dates = pd.to_datetime(r.last_history_date, errors="coerce")
    assert (history_dates.isna() | (history_dates < r.date)).all()

    shared = [
        "population",
        "meet",
        "date",
        "band",
        "moisture",
        "age",
        "sex",
        "weight",
        "grade",
        "passed",
        "row_key",
        "source_key",
        "valid",
        "exclusion_reason",
        "source_file",
        "source_item_index",
    ]
    t["source_item_index"] = pd.to_numeric(t.source_item_index).astype(int)
    r["source_item_index"] = r.source_item_index.astype(int)
    frames = []
    for f in (t, r):
        f["middle"] = f.middle1 + f.middle2
        f["year"] = f.date.dt.year
        f["month"] = f.date.dt.month.astype(str)
        f["distance"] = 1000 if f.population.iloc[0] == "주행심사1000" else 1200
        f["fs200"] = 100 * 200 * f.finish / (f.distance * f.late)
        f["fs600"] = 100 * 600 * f.finish / (f.distance * f.last600)
        f["fs400"] = 100 * 400 * f.finish / (f.distance * f.last400)
        extras = ["year", "month", "distance", "fs200", "fs600", "fs400"]
        if f is r:
            extras += history_cols + ["g400_source_file", "g400_source_item_index"]
            extras.remove("age")
        frames.append(f[shared + PARTS + extras].copy())
    all_rows = pd.concat(frames, ignore_index=True)
    ledger = (
        all_rows.groupby(["population", "meet", "year", "valid"])
        .size()
        .rename("rows")
        .reset_index()
    )
    return all_rows[all_rows.valid].reset_index(drop=True), ledger, all_rows[~all_rows.valid]


def distribution(frame, keys):
    rows = []
    for key, g in frame.groupby(keys, observed=True):
        if not isinstance(key, tuple):
            key = (key,)
        for p in PARTS + ["fs200", "fs400", "fs600"]:
            v = g[p].dropna()
            if len(v):
                rows.append(
                    dict(
                        zip(keys, key, strict=True),
                        part=p,
                        n=len(v),
                        days=g.loc[v.index, "date"].nunique(),
                        mean=v.mean(),
                        median=v.median(),
                        p10=v.quantile(0.1),
                        p90=v.quantile(0.9),
                    )
                )
    return pd.DataFrame(rows)


def model(cats, nums):
    preprocess = ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cats),
            (
                "num",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                        ("scale", StandardScaler()),
                    ]
                ),
                nums,
            ),
        ]
    )
    return Pipeline([("preprocess", preprocess), ("regression", Ridge(alpha=10))])


def labels(values, q):
    return np.where(values < q[0], "빠름", np.where(values > q[1], "느림", "보통"))


def annual_references(data):
    frames, validation, thresholds, effects, slopes = [], [], [], [], []
    for (pop, meet), g in data.groupby(["population", "meet"]):
        cats = ["band", "month", "sex"]
        nums = ["age", "weight"]
        if pop == "실전1200":
            cats += ["grade"]
            nums += ["rating", "prior_finish", "prior_top3", "prior_early", "log_starts", "log_gap"]
        for year in (2024, 2025, 2026):
            train = g[g.year.lt(year)].copy()
            test = g[g.year.eq(year)].copy()
            test["reference_max_date"] = train.date.max()
            assert train.date.max() < test.date.min()
            for part in [
                "early",
                "middle1",
                "middle2",
                "middle",
                "late",
                "finish",
                "last600",
                "last400",
            ]:
                tr = train[train[part].notna()].copy()
                te_mask = test[part].notna()
                if len(tr) < 100:
                    continue
                fitted = model(cats, nums).fit(tr, tr[part])
                pred_train = fitted.predict(tr)
                train_res = tr[part] - pred_train
                q = train_res.quantile([0.25, 0.75]).to_numpy()
                test.loc[te_mask, "expected_" + part] = fitted.predict(test.loc[te_mask])
                test["res_" + part] = test[part] - test["expected_" + part]
                test["pace_" + part] = labels(test["res_" + part], q)
                test.loc[~te_mask, "pace_" + part] = None
                thresholds.append(
                    dict(
                        population=pop,
                        meet=meet,
                        year=year,
                        part=part,
                        q25=q[0],
                        q75=q[1],
                        train_rows=len(tr),
                        train_max_date=str(tr.date.max()),
                    )
                )
                val = test.loc[te_mask, "res_" + part]
                validation.append(
                    dict(
                        population=pop,
                        meet=meet,
                        year=year,
                        part=part,
                        model="기본 조건",
                        n=len(val),
                        mae=val.abs().mean(),
                        bias=val.mean(),
                    )
                )
                # Fitted environmental contrast; not an adopted correction or causal effect.
                names = fitted.named_steps["preprocess"].get_feature_names_out()
                coefficients = dict(zip(names, fitted.named_steps["regression"].coef_, strict=True))
                dry = coefficients.get("cat__band_건조")
                if dry is not None:
                    for band in BANDS:
                        name = "cat__band_" + band
                        if name in coefficients:
                            bg = tr[tr.band.eq(band)]
                            effects.append(
                                dict(
                                    population=pop,
                                    meet=meet,
                                    year=year,
                                    part=part,
                                    band=band,
                                    seconds_vs_dry=coefficients[name] - dry,
                                    n=len(bg),
                                    days=bg.date.nunique(),
                                )
                            )
            conditional = model(cats, nums + ["early", "middle"]).fit(train, train.late)
            test["expected_late_conditional"] = conditional.predict(test)
            test["res_late_conditional"] = test.late - test.expected_late_conditional
            cq = (train.late - conditional.predict(train)).quantile([0.25, 0.75]).to_numpy()
            test["pace_late_conditional"] = labels(test.res_late_conditional, cq)
            thresholds.append(
                dict(
                    population=pop,
                    meet=meet,
                    year=year,
                    part="late_conditional",
                    q25=cq[0],
                    q75=cq[1],
                    train_rows=len(train),
                    train_max_date=str(train.date.max()),
                )
            )
            validation.append(
                dict(
                    population=pop,
                    meet=meet,
                    year=year,
                    part="late",
                    model="초중반 추가",
                    n=len(test),
                    mae=test.res_late_conditional.abs().mean(),
                    bias=test.res_late_conditional.mean(),
                )
            )
            scale = (
                conditional.named_steps["preprocess"]
                .named_transformers_["num"]
                .named_steps["scale"]
                .scale_
            )
            names = conditional.named_steps["preprocess"].get_feature_names_out()
            coef = dict(zip(names, conditional.named_steps["regression"].coef_, strict=True))
            for p in ("early", "middle"):
                slopes.append(
                    dict(
                        population=pop,
                        meet=meet,
                        year=year,
                        part=p,
                        late_seconds_per_one_slower_second=coef["num__" + p]
                        / scale[(nums + ["early", "middle"]).index(p)],
                    )
                )
            frames.append(test)
    return pd.concat(frames, ignore_index=True), validation, thresholds, effects, slopes


def bootstrap(g):
    day = g.groupby("date").res_late.agg(["sum", "count"])
    if len(day) < 2:
        return (None, None)
    rng = np.random.default_rng(20261003)
    idx = rng.integers(0, len(day), size=(2000, len(day)))
    means = day["sum"].to_numpy()[idx].sum(1) / day["count"].to_numpy()[idx].sum(1)
    return tuple(np.quantile(means, [0.025, 0.975]))


def profiles(frame, extra=(), ci=False):
    keys = ["population", "meet"] + list(extra) + ["pace_early", "pace_middle"]
    rows = []
    for key, g in frame.groupby(keys, observed=True):
        lo, hi = bootstrap(g) if ci else (None, None)
        rows.append(
            dict(
                zip(keys, key, strict=True),
                n=len(g),
                days=g.date.nunique(),
                small_support=g.date.nunique() < 20,
                early_mean=g.early.mean(),
                middle1_mean=g.middle1.mean(),
                middle2_mean=g.middle2.mean(),
                middle_mean=g.middle.mean(),
                late_mean=g.late.mean(),
                finish_mean=g.finish.mean(),
                late_residual_mean=g.res_late.mean(),
                late_residual_median=g.res_late.median(),
                late_residual_ci_low=lo,
                late_residual_ci_high=hi,
                late_conditional_residual_mean=g.res_late_conditional.mean(),
                fast_late_share=g.pace_late.eq("빠름").mean(),
                fast_conditional_late_share=g.pace_late_conditional.eq("빠름").mean(),
                slow_late_share=g.pace_late.eq("느림").mean(),
                finish_residual_mean=g.res_finish.mean(),
            )
        )
    return pd.DataFrame(rows)


def main():
    if OUT.exists():
        raise FileExistsError("Outputs already exist; preserve completed runs")
    OUT.mkdir()
    paths = [TRIAL, RACE, HISTORY, DB, HERE / "PLAN.md", HERE / "analyze.py"]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    data, ledger, excluded = prepare()
    data.to_parquet(OUT / "population.parquet", index=False)
    ledger.to_csv(OUT / "quality_ledger.csv", index=False)
    excluded.to_parquet(OUT / "excluded.parquet", index=False)
    recent = data[data.year.ge(2024)]
    distribution(recent, ["population", "meet", "band"]).to_csv(
        OUT / "moisture_sections.csv", index=False
    )
    distribution(recent, ["population", "meet"]).to_csv(OUT / "overall_sections.csv", index=False)
    distribution(recent[recent.passed], ["population", "meet", "band"]).to_csv(
        OUT / "passed_moisture_sections.csv", index=False
    )
    distribution(recent[recent.population.eq("실전1200")], ["meet", "grade"]).to_csv(
        OUT / "grade_sections.csv", index=False
    )
    scored, val, thresholds, effects, slopes = annual_references(data)
    scored.to_parquet(OUT / "scored_recent.parquet", index=False)
    pd.DataFrame(val).to_csv(OUT / "annual_validation.csv", index=False)
    pd.DataFrame(thresholds).to_csv(OUT / "reference_thresholds.csv", index=False)
    pd.DataFrame(effects).to_csv(OUT / "moisture_model_contrasts.csv", index=False)
    pd.DataFrame(slopes).to_csv(OUT / "conditional_slopes.csv", index=False)
    profiles(scored, ci=True).to_csv(OUT / "pace_profiles.csv", index=False)
    profiles(scored, ["band"]).to_csv(OUT / "moisture_pace_profiles.csv", index=False)
    profiles(scored, ["year"]).to_csv(OUT / "year_pace_profiles.csv", index=False)
    profiles(scored[scored.passed], ci=True).to_csv(OUT / "passed_profiles.csv", index=False)
    profiles(scored[scored.grade.eq("국6")], ci=True).to_csv(
        OUT / "grade6_profiles.csv", index=False
    )
    pattern = (
        scored.groupby(
            ["population", "meet", "pace_early", "pace_middle", "pace_late"], observed=True
        )
        .size()
        .rename("n")
        .reset_index()
    )
    pattern.to_csv(OUT / "pattern_counts.csv", index=False)
    coverage = (
        data.groupby(["population", "meet", "year"])
        .agg(n=("row_key", "size"), days=("date", "nunique"), sessions=("source_key", "nunique"))
        .reset_index()
    )
    coverage.to_csv(OUT / "coverage.csv", index=False)
    assert hashes == {str(p.relative_to(ROOT)): sha(p) for p in paths}
    summary = dict(
        inputs_sha256=hashes,
        inputs_unchanged=True,
        no_track_speed=True,
        valid_rows=len(data),
        recent_rows=len(scored),
        excluded_rows=len(excluded),
        recent_coverage=scored.groupby(["population", "meet"])
        .agg(n=("row_key", "size"), days=("date", "nunique"))
        .reset_index()
        .to_dict("records"),
    )
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
