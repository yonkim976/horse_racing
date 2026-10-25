"""Read-only inputs; regularized moisture contrasts and empirical time benchmarks."""

import gzip
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
PRIOR = HERE.parent / "20261002_track_source_reconciliation/results/api_study_population.parquet"
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
HISTORY = HERE.parent / "20261002_gate_lateral_bias/outputs/runners.parquet"
GRADES = ["국6", "국5", "국4", "혼4", "국3", "혼3", "2", "1", "국OPEN", "혼OPEN"]
BANDS = ["건조", "양호", "다습", "포화", "불량"]
CORE = ["early", "middle1", "middle2", "late"]
PARTS = CORE + ["finish", "last600", "last400"]
NUMS = [
    "year",
    "age",
    "weight",
    "rating",
    "prior_finish",
    "prior_top3",
    "prior_early",
    "log_starts",
    "log_gap",
]
SCALES = [0.0, 0.3, 1.0, 3.0]
QS = [0.10, 0.20, 0.50, 0.80, 0.90]
SEED = 20261006
BOOT = 200
EPS = 1e-7


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def population():
    a = pd.read_parquet(PRIOR)
    h = pd.read_parquet(HISTORY)
    a = a[a.distance_m.eq(1600)].copy()
    h = h[h.distance_m.eq(1600)].copy()
    keys = ["meet", "date", "race_no", "horse_id"]
    for f in (a, h):
        f["date"] = pd.to_datetime(f.date)
        assert not f.duplicated(keys).any()
    controls = [
        "age",
        "rating",
        "prior_finish",
        "prior_top3",
        "prior_early",
        "log_starts",
        "log_gap",
        "last_history_date",
        "n",
    ]
    r = a.merge(h[keys + controls], on=keys, validate="one_to_one", how="inner")
    assert len(r) == len(h)
    with duckdb.connect(str(DB), read_only=True) as c:
        sex = c.execute("""SELECT CAST(source_meet AS INTEGER) AS meet,
          result_date AS date, CAST(result_race_no AS INTEGER) AS race_no,
          horse_id_raw AS horse_id, horse_sex_raw AS sex FROM confirmed_runners
          WHERE source_meet IN ('1','3') AND race_distance_m_raw='1600'
          AND result_date >= '20180101'""").fetchdf()
        g400 = c.execute("""SELECT meet, race_date AS date, race_no, horse_id,
          time_ms/1000.0 AS last400 FROM section_measurements_api
          WHERE meet=3 AND point_code='2F_G' AND measure_kind='closing_time'
          AND source_field='bu_2fGTime' AND race_date >= '20180101'""").fetchdf()
    for f in (sex, g400):
        f["date"] = pd.to_datetime(f.date)
        assert not f.duplicated(keys).any()
    r = r.merge(sex, on=keys, how="left", validate="one_to_one")
    r = r.merge(g400, on=keys, how="left", validate="one_to_one")
    assert r.sex.notna().all()
    r["finish"] /= 1000
    r["early"] = r.start_200 / 1000
    r["late"] = r.last_200 / 1000
    r["last600"] = r.last_600 / 1000
    r["middle1"] = r.finish - r.last600 - r.early  # 200m -> 1000m: 800m
    r["middle2"] = r.last600 - r.late  # 1000m -> 1400m: 400m
    r["grade"] = r.grade_normalized
    r["meet"] = r.meet.map({1: "서울", 3: "부산"})
    r["source_key"] = r.meet + ":" + r.date.dt.strftime("%Y%m%d") + ":" + r.race_no.astype(str)
    r["row_key"] = r.source_key + ":" + r.horse_id
    r["year"], r["month"] = r.date.dt.year, r.date.dt.month.astype(str)
    r["rating"] = r.rating.mask(r.rating.le(0))
    r["interaction"] = r.grade + "|" + r.band
    valid = (
        r.finish.between(80, 155)
        & r.early.between(10, 25)
        & r.late.between(8, 25)
        & r.middle1.between(32, 80)
        & r.middle2.between(16, 45)
    )
    r["valid_core"] = valid
    good400 = r.last400.between(16, 50) & r.last400.gt(r.late) & r.last400.lt(r.last600)
    r["valid_last400"] = good400
    r["raw_last400"] = r.last400
    r["last400"] = r.last400.where(good400)
    ledger = a[keys].merge(
        r[keys + ["valid_core", "valid_last400"]].assign(meet=r.meet.map({"서울": 1, "부산": 3})),
        on=keys,
        how="left",
        validate="one_to_one",
    )
    ledger["reason"] = np.where(
        ledger.valid_core.isna(),
        "outside_parent_normal_full_race_cohort",
        np.where(ledger.valid_core, "retained", "missing_or_physical_section_bounds"),
    )
    ledger.to_csv(OUT / "selection_ledger.csv", index=False)
    r[~valid].to_csv(OUT / "excluded_sections.csv", index=False)
    r = r[valid].copy()
    assert not r.row_key.duplicated().any()
    assert r[CORE + ["finish", "last600"]].notna().all().all()
    assert np.allclose(r[CORE].sum(axis=1), r.finish)
    hd = pd.to_datetime(r.last_history_date, errors="coerce")
    assert (hd.isna() | hd.lt(r.date)).all()
    # Frozen raw API rows independently verify identity, whole and per-runner section times.
    hashes, raw_checks = {}, 0
    for name, group in r.groupby("source_file"):
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT / "thoroughbred/research/20260929_calendar_api_v1/raw")
        hashes[name] = sha(path)
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            items = json.load(stream)["response"]["body"]["items"]["item"]
        for row in group.itertuples():
            item = items[int(row.source_item_index)]
            assert str(item["rcDate"]) == row.date.strftime("%Y%m%d")
            assert int(item["rcNo"]) == row.race_no and str(item["hrNo"]).zfill(7) == row.horse_id
            assert int(item["rcDist"]) == 1600 and int(item["ord"]) == row.rank
            assert np.isclose(float(item["rcTime"]), row.finish)
            if row.meet == "서울":
                values = [
                    float(item["seS1fAccTime"]),
                    row.finish - float(item["seG3fAccTime"]),
                    row.finish - float(item["seG1fAccTime"]),
                ]
            else:
                values = [
                    float(item["buS1fTime"]),
                    float(item["bu_3fGTime"]),
                    float(item["bu_1fGTime"]),
                ]
                if np.isfinite(row.last400):
                    assert np.isclose(float(item["bu_2fGTime"]), row.last400)
            assert np.allclose(values, [row.early, row.last600, row.late])
            raw_checks += 1
    (OUT / "raw_source_verification.json").write_text(
        json.dumps(
            dict(
                checked_rows=raw_checks,
                mismatches=0,
                raw_file_hashes=hashes,
                audit_rows=len(a),
                parent_normal_rows=len(h),
                retained_rows=len(r),
                selection_counts=ledger.reason.value_counts().to_dict(),
                invalid_busan400=int((r.meet.eq("부산") & ~r.valid_last400).sum()),
                section_metres=dict(early=200, middle1=800, middle2=400, late=200),
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return r.sort_values(["meet", "date", "row_key"]).reset_index(drop=True)


def race_weights(d):
    w = 1 / d.groupby("source_key").source_key.transform("size").to_numpy()
    return w / w.mean()


class Model:
    def __init__(self, scale):
        self.scale = scale
        self.pre = ColumnTransformer(
            [
                (
                    "grade",
                    OneHotEncoder(
                        categories=[GRADES], sparse_output=False, handle_unknown="ignore"
                    ),
                    ["grade"],
                ),
                (
                    "band",
                    OneHotEncoder(categories=[BANDS], sparse_output=False, handle_unknown="ignore"),
                    ["band"],
                ),
                (
                    "context",
                    OneHotEncoder(sparse_output=False, handle_unknown="ignore"),
                    ["month", "sex"],
                ),
                (
                    "num",
                    Pipeline(
                        [
                            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                            ("scale", StandardScaler()),
                        ]
                    ),
                    NUMS,
                ),
                (
                    "interaction",
                    OneHotEncoder(
                        categories=[[g + "|" + b for g in GRADES for b in BANDS]],
                        sparse_output=False,
                        handle_unknown="ignore",
                    ),
                    ["interaction"],
                ),
            ],
            transformer_weights={"interaction": scale},
        )
        self.fit_core = Ridge(alpha=10, solver="cholesky")
        self.fit400 = Ridge(alpha=10, solver="cholesky")

    def fit(self, d):
        self.x = self.pre.fit_transform(d)
        self.w = race_weights(d)
        self.fit_core.fit(self.x, d[CORE], sample_weight=self.w)
        self.has400 = d.last400.notna().any()
        self.good400 = d.last400.notna().to_numpy()
        if self.has400:
            self.fit400.fit(
                self.x[self.good400],
                d.loc[self.good400, "last400"],
                sample_weight=self.w[self.good400],
            )
        return self

    def predict(self, d):
        x = self.pre.transform(d)
        v = pd.DataFrame(self.fit_core.predict(x), columns=CORE, index=d.index)
        v["finish"] = v[CORE].sum(axis=1)
        v["last600"] = v.middle2 + v.late
        v["last400"] = self.fit400.predict(x) if self.has400 else np.nan
        return v

    def effects(self, d):
        # Only band and grade x band change. Context and ability remain fixed.
        probes = []
        for grade in GRADES:
            available = d[d.grade.eq(grade)]
            a = (available if len(available) else d).iloc[[0]].copy()
            a["grade"] = grade
            for band in BANDS:
                b = a.copy()
                b["band"], b["interaction"] = band, grade + "|" + band
                probes.append(b)
        p = pd.concat(probes, ignore_index=True)
        pred = self.predict(p)
        effects = {}
        for i, grade in enumerate(GRADES):
            block = pred.iloc[i * 5 : (i + 1) * 5]
            for j, band in enumerate(BANDS):
                effects[grade, band] = (block.iloc[j] - block.iloc[0]).to_numpy()
        return effects


def effect_matrix(d, effects):
    return np.stack([effects[g, b] for g, b in zip(d.grade, d.band, strict=True)])


def stats(values):
    v = np.asarray(values, dtype=float)
    v = np.round(v[np.isfinite(v)], 9)
    if not len(v):
        return {
            k: np.nan
            for k in [
                "mean",
                "p10",
                "p20",
                "median",
                "p80",
                "p90",
                "fast20_mean",
                "middle60_mean",
                "slow20_mean",
                "fast20_n",
                "middle60_n",
                "slow20_n",
            ]
        }
    q = np.round(np.quantile(v, QS), 9)
    masks = [v <= q[1] + EPS, (v > q[1] + EPS) & (v < q[3] - EPS), v >= q[3] - EPS]
    result = dict(zip(["p10", "p20", "median", "p80", "p90"], q, strict=True), mean=v.mean())
    for name, mask in zip(["fast20", "middle60", "slow20"], masks, strict=True):
        result[name + "_mean"] = v[mask].mean() if mask.any() else np.nan
        result[name + "_n"] = int(mask.sum())
    return result


def score(values, time):
    """Slower share, half credit for ties. 100 is faster than all reference times."""
    v = np.sort(np.round(np.asarray(values, dtype=float), 9))
    v = v[np.isfinite(v)]
    time = np.round(time, 9)
    left = np.searchsorted(v, time - EPS, side="left")
    right = np.searchsorted(v, time + EPS, side="right")
    return np.where(np.isfinite(time), 100 * (1 - (left + right) / (2 * len(v))), np.nan)


def development(d):
    rows = []
    for meet, g in d.groupby("meet"):
        for year in [2021, 2022, 2023]:
            tr, te = g[g.year.lt(year)], g[g.year.eq(year)]
            excluded_unseen = int((~te.grade.isin(tr.grade.unique())).sum())
            original_n = len(te)
            te = te[te.grade.isin(tr.grade.unique())]
            if tr.empty or te.empty:
                continue
            assert tr.date.max() < te.date.min()
            for scale in SCALES:
                m = Model(scale).fit(tr)
                pred = m.predict(te).finish
                z = te[["grade", "band", "finish"]].copy()
                z["pred"] = pred
                cells = z.groupby(["grade", "band"])[["finish", "pred"]].mean()
                rows.append(
                    dict(
                        meet=meet,
                        year=year,
                        scale=scale,
                        n=len(te),
                        original_test_n=original_n,
                        excluded_unseen_grade_n=excluded_unseen,
                        train_n=len(tr),
                        train_days=tr.date.nunique(),
                        cell_count=len(cells),
                        cell_mae=(cells.pred - cells.finish).abs().mean(),
                        runner_mae=(pred - te.finish).abs().mean(),
                        train_max=str(tr.date.max().date()),
                    )
                )
    dev = pd.DataFrame(rows)
    selected = {}
    for meet, g in dev.groupby("meet"):
        losses = g.groupby("scale").cell_mae.mean()
        selected[meet] = float(losses[losses <= losses.min() + 0.01].index.min())
    return dev, selected


def baselines(tr, te):
    grade = tr.groupby("grade").finish.mean()
    cell = tr.groupby(["grade", "band"]).finish.mean()
    fallback = te.grade.map(grade).to_numpy()
    raw = np.array([cell.get((g, b), np.nan) for g, b in zip(te.grade, te.band, strict=True)])
    return fallback, np.where(np.isnan(raw), fallback, raw)


def validation(d, selected):
    errors, coverage, scores, hidden = [], [], [], []
    for meet, g in d.groupby("meet"):
        for year in [2024, 2025, 2026]:
            tr, te = g[g.year.lt(year)], g[g.year.eq(year)]
            ref = tr[tr.year.ge(year - 3)]
            assert tr.date.max() < te.date.min() and ref.date.max() < te.date.min()
            m = Model(selected[meet]).fit(tr)
            effects = m.effects(tr)
            pred = m.predict(te).finish.to_numpy()
            gradebase, cellbase = baselines(ref, te)
            for name, v in [
                ("grade_raw", gradebase),
                ("cell_raw_fallback", cellbase),
                ("regularized_context", pred),
            ]:
                z = te[["grade", "band", "finish"]].copy()
                z["pred"] = v
                for (grade, band), c in z.groupby(["grade", "band"]):
                    errors.append(
                        dict(
                            meet=meet,
                            year=year,
                            method=name,
                            grade=grade,
                            band=band,
                            n=len(c),
                            actual_mean=c.finish.mean(),
                            predicted_mean=c.pred.mean(),
                            mean_error=c.pred.mean() - c.finish.mean(),
                            mae=(c.pred - c.finish).abs().mean(),
                            train_max=str(tr.date.max().date()),
                        )
                    )
            base = ref[PARTS].to_numpy() - effect_matrix(ref, effects)
            for (grade, band), c in te.groupby(["grade", "band"]):
                mask = ref.grade.eq(grade).to_numpy()
                if not mask.any():
                    continue
                v = base[mask] + effects[grade, band]
                dist = stats(v[:, PARTS.index("finish")])
                errors.append(
                    dict(
                        meet=meet,
                        year=year,
                        method="benchmark_shift_reference",
                        grade=grade,
                        band=band,
                        n=len(c),
                        actual_mean=c.finish.mean(),
                        predicted_mean=dist["mean"],
                        mean_error=dist["mean"] - c.finish.mean(),
                        mae=(c.finish - dist["mean"]).abs().mean(),
                        train_max=str(tr.date.max().date()),
                    )
                )
                coverage.append(
                    dict(
                        meet=meet,
                        year=year,
                        grade=grade,
                        band=band,
                        n=len(c),
                        reference_n=int(mask.sum()),
                        reference_days=ref.loc[mask, "date"].nunique(),
                        p20=dist["p20"],
                        median=dist["median"],
                        p80=dist["p80"],
                        fast_share=(c.finish <= dist["p20"]).mean(),
                        slow_share=(c.finish >= dist["p80"]).mean(),
                        train_max=str(tr.date.max().date()),
                    )
                )
                zz = c[["row_key", "horse_id", "date", "grade", "band", "rank", "n"] + PARTS].copy()
                zz["meet"], zz["reference_max_date"] = meet, tr.date.max()
                zz["reference_n"] = int(mask.sum())
                zz["dry_equivalent_finish"] = c.finish - effects[grade, band][PARTS.index("finish")]
                zz["score_distance_finish"] = score(
                    base[:, PARTS.index("finish")], zz.dry_equivalent_finish.to_numpy()
                )
                for j, part in enumerate(PARTS):
                    if not np.isfinite(v[:, j]).any():
                        zz["score_" + part] = np.nan
                        continue
                    zz["score_" + part] = score(v[:, j], c[part].to_numpy())
                scores.append(zz)
            # Mask an entire grade x band cell from history, then predict future means.
            # Require enough dates in both sides to avoid treating a single race as truth.
            for (grade, band), c in te.groupby(["grade", "band"]):
                keep = ~(tr.grade.eq(grade) & tr.band.eq(band))
                removed = tr[~keep]
                if len(removed) < 100 or removed.date.nunique() < 10 or c.date.nunique() < 5:
                    continue
                masked = tr[keep]
                mm = Model(selected[meet]).fit(masked)
                masked_ref = masked[masked.year.ge(year - 3)]
                masked_ref = masked_ref[masked_ref.grade.eq(grade)]
                if masked_ref.empty:
                    continue
                masked_effects = mm.effects(masked)
                shifted = masked_ref[PARTS].to_numpy() - effect_matrix(masked_ref, masked_effects)
                pp_mean = (shifted + masked_effects[grade, band])[:, PARTS.index("finish")].mean()
                assert not ((masked.grade == grade) & (masked.band == band)).any()
                hidden.append(
                    dict(
                        meet=meet,
                        year=year,
                        grade=grade,
                        band=band,
                        removed_n=len(removed),
                        removed_days=removed.date.nunique(),
                        test_n=len(c),
                        test_days=c.date.nunique(),
                        actual_mean=c.finish.mean(),
                        predicted_mean=pp_mean,
                        abs_error=abs(pp_mean - c.finish.mean()),
                        grade_fallback_abs_error=abs(masked_ref.finish.mean() - c.finish.mean()),
                        train_max=str(masked.date.max().date()),
                    )
                )
        print(f"{meet}: chronological and hidden-cell validation complete", flush=True)
    return (
        pd.DataFrame(errors),
        pd.DataFrame(coverage),
        pd.concat(scores, ignore_index=True),
        pd.DataFrame(hidden),
    )


def descriptive(d):
    rows, cohorts = [], []
    recent = d[d.year.ge(2024)]
    for meet, g in recent.groupby("meet"):
        for grade in GRADES:
            for band in BANDS:
                c = g[g.grade.eq(grade) & g.band.eq(band)]
                for part in PARTS:
                    if meet == "서울" and part == "last400":
                        continue
                    rows.append(
                        dict(
                            meet=meet,
                            grade=grade,
                            band=band,
                            part=part,
                            n=int(c[part].count()),
                            races=c.source_key.nunique(),
                            days=c.date.nunique(),
                            **stats(c[part]),
                        )
                    )
                for label, mask in [
                    ("all", c.index == c.index),
                    ("top3_rank", c["rank"].le(3)),
                    ("bottom3_rank", c["rank"].gt(c.n - 3)),
                ]:
                    cc = c[mask]
                    if cc.empty:
                        continue
                    for part in PARTS:
                        if cc[part].notna().any():
                            cohorts.append(
                                dict(
                                    meet=meet,
                                    grade=grade,
                                    band=band,
                                    cohort=label,
                                    part=part,
                                    n=int(cc[part].count()),
                                    races=cc.source_key.nunique(),
                                    days=cc.date.nunique(),
                                    mean=cc[part].mean(),
                                    median=cc[part].median(),
                                )
                            )
    return pd.DataFrame(rows), pd.DataFrame(cohorts)


def bootstrap(d, ref, m):
    rng = np.random.default_rng(SEED)
    days = pd.Index(d.date.unique())
    codes = days.get_indexer(d.date)
    refcodes = days.get_indexer(ref.date)
    samples = np.empty((BOOT, 50, len(PARTS), 4))
    reference_indices = [np.flatnonzero(ref.grade.eq(grade).to_numpy()) for grade in GRADES]
    for b in range(BOOT):
        day_n = np.bincount(rng.integers(0, len(days), size=len(days)), minlength=len(days))
        w = m.w * day_n[codes]
        m.fit_core.fit(m.x, d[CORE], sample_weight=w)
        if m.has400:
            m.fit400.fit(m.x[m.good400], d.loc[m.good400, "last400"], sample_weight=w[m.good400])
        ef = m.effects(d)
        base = ref[PARTS].to_numpy() - effect_matrix(ref, ef)
        for i, grade in enumerate(GRADES):
            indices = reference_indices[i]
            ix = np.repeat(indices, day_n[refcodes[indices]])
            if not len(ix):
                samples[b, i * 5 : (i + 1) * 5] = np.nan
                continue
            for j, band in enumerate(BANDS):
                v = base[ix] + ef[grade, band]
                for k in range(len(PARTS)):
                    a = v[:, k]
                    a = a[np.isfinite(a)]
                    samples[b, i * 5 + j, k] = (
                        [a.mean(), *np.quantile(a, [0.2, 0.5, 0.8])] if len(a) else np.nan
                    )
        if (b + 1) % 50 == 0:
            print(f"{d.meet.iloc[0]}: bootstrap {b + 1}/{BOOT}", flush=True)
    # Restore final coefficients. Preprocessing is deliberately held fixed in resampling.
    m.fit_core.fit(m.x, d[CORE], sample_weight=m.w)
    if m.has400:
        m.fit400.fit(m.x[m.good400], d.loc[m.good400, "last400"], sample_weight=m.w[m.good400])
    return samples


def final_tables(d, selected):
    tables, cohorts, effects_rows, scores_grid, coefficients = [], [], [], [], []
    for meet, g in d.groupby("meet"):
        ref = g[g.year.ge(2024)]
        m = Model(selected[meet]).fit(g)
        ef = m.effects(g)
        base = ref[PARTS].to_numpy() - effect_matrix(ref, ef)
        ci = bootstrap(g, ref, m)
        for part, fit in [(p, m.fit_core) for p in CORE] + (
            [("last400", m.fit400)] if m.has400 else []
        ):
            coef = fit.coef_[CORE.index(part)] if part in CORE else fit.coef_
            for name, value in zip(m.pre.get_feature_names_out(), coef, strict=True):
                coefficients.append(
                    dict(
                        meet=meet,
                        part=part,
                        feature=name,
                        coefficient=value,
                        interaction_scale=m.scale,
                    )
                )
        for i, grade in enumerate(GRADES):
            refmask = ref.grade.eq(grade).to_numpy()
            rr = ref.loc[refmask]
            if rr.empty:
                continue
            for j, band in enumerate(BANDS):
                observed = rr[rr.band.eq(band)]
                historic = g[g.grade.eq(grade) & g.band.eq(band)]
                sparse = (
                    len(observed) < 200
                    or observed.source_key.nunique() < 20
                    or observed.date.nunique() < 20
                )
                status = (
                    "no_recent_observation"
                    if observed.empty
                    else "small_recent_sample"
                    if sparse
                    else "observed_supported"
                )
                v = base[refmask] + ef[grade, band]
                f = np.round(v[:, PARTS.index("finish")], 9)
                p20, p80 = np.round(np.quantile(f, [0.2, 0.8]), 9)
                for k, part in enumerate(PARTS):
                    if meet == "서울" and part == "last400":
                        continue
                    row = dict(
                        meet=meet,
                        distance=1600,
                        grade=grade,
                        band=band,
                        part=part,
                        observed_n=int(observed[part].count()),
                        observed_races=observed.source_key.nunique(),
                        observed_days=observed.date.nunique(),
                        historical_n=int(historic[part].count()),
                        historical_days=historic.date.nunique(),
                        reference_n=int(rr[part].count()),
                        reference_days=rr.date.nunique(),
                        status=status,
                        grade_reference_status=(
                            "very_sparse"
                            if len(rr) < 30 or rr.date.nunique() < 5
                            else "small"
                            if len(rr) < 200 or rr.date.nunique() < 20
                            else "supported"
                        ),
                        reference_version="1600_v1_20261006",
                        observed_mean=observed[part].mean(),
                        observed_median=observed[part].median(),
                        **stats(v[:, k]),
                    )
                    row["bootstrap_valid_n"] = int(np.isfinite(ci[:, i * 5 + j, k, 0]).sum())
                    ci_ok = row["bootstrap_valid_n"] >= BOOT * 0.9
                    for metric_index, name in enumerate(["mean", "p20", "median", "p80"]):
                        row[name + "_ci_low"], row[name + "_ci_high"] = (
                            np.nanquantile(ci[:, i * 5 + j, k, metric_index], [0.025, 0.975])
                            if ci_ok
                            else (np.nan, np.nan)
                        )
                    row["state_shift_from_dry"] = ef[grade, band][k]
                    tables.append(row)
                    effects_rows.append(
                        dict(
                            meet=meet,
                            grade=grade,
                            band=band,
                            part=part,
                            shift_from_dry=ef[grade, band][k],
                            scale=m.scale,
                        )
                    )
                    for value in [10, 20, 50, 80, 90]:
                        threshold = np.quantile(v[:, k], 1 - value / 100)
                        scores_grid.append(
                            dict(
                                meet=meet,
                                distance=1600,
                                grade=grade,
                                band=band,
                                part=part,
                                nominal_score=value,
                                time_threshold=threshold,
                                empirical_score_at_threshold=float(score(v[:, k], threshold)),
                                status=status,
                            )
                        )
                for name, mask in [
                    ("fast20_finish", f <= p20 + EPS),
                    ("middle60_finish", (f > p20 + EPS) & (f < p80 - EPS)),
                    ("slow20_finish", f >= p80 - EPS),
                ]:
                    for k, part in enumerate(PARTS):
                        if not np.isfinite(v[:, k]).any():
                            continue
                        cohorts.append(
                            dict(
                                meet=meet,
                                grade=grade,
                                band=band,
                                cohort=name,
                                part=part,
                                reference_n=int(mask.sum()),
                                mean=v[mask, k].mean(),
                            )
                        )
        print(f"{meet}: final benchmarks complete", flush=True)
    return (
        pd.DataFrame(tables),
        pd.DataFrame(cohorts),
        pd.DataFrame(effects_rows),
        pd.DataFrame(scores_grid),
        pd.DataFrame(coefficients),
    )


def aggregate_validation(errors, coverage, hidden):
    out = []
    for (meet, method), g in errors.groupby(["meet", "method"]):
        out.append(
            dict(
                meet=meet,
                method=method,
                cells=len(g),
                cell_mean_mae=g.mean_error.abs().mean(),
                cell_mean_bias=g.mean_error.mean(),
                runner_mae=np.average(g.mae, weights=g.n),
            )
        )
    shares = []
    for meet, g in coverage.groupby("meet"):
        shares.append(
            dict(
                meet=meet,
                n=int(g.n.sum()),
                fast20_share=np.average(g.fast_share, weights=g.n),
                slow20_share=np.average(g.slow_share, weights=g.n),
                macro_fast20_share=g.fast_share.mean(),
                macro_slow20_share=g.slow_share.mean(),
            )
        )
    hidden_out = []
    for meet, g in hidden.groupby("meet"):
        hidden_out.append(
            dict(
                meet=meet,
                cells=len(g),
                mean_abs_error=g.abs_error.mean(),
                median_abs_error=g.abs_error.median(),
                p90_abs_error=g.abs_error.quantile(0.9),
                grade_fallback_mae=g.grade_fallback_abs_error.mean(),
            )
        )
    return out, shares, hidden_out


def main():
    if OUT.exists():
        raise FileExistsError("Completed outputs are immutable; use a separate run directory")
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in [PRIOR, HISTORY, DB]}
    OUT.mkdir()
    d = population()
    d.to_parquet(OUT / "population.parquet", index=False)
    print(f"Validated input {len(d)} rows; no Yeongcheon", flush=True)
    dev, selected = development(d)
    print(f"Selected interaction scales: {selected}", flush=True)
    errors, coverage, scores, hidden = validation(d, selected)
    raw, rank_cohorts = descriptive(d)
    table, finish_cohorts, effects, score_grid, coefficients = final_tables(d, selected)
    metrics, shares, hidden_metrics = aggregate_validation(errors, coverage, hidden)
    assert hashes == {str(p.relative_to(ROOT)): sha(p) for p in [PRIOR, HISTORY, DB]}
    for name, frame in [
        ("development_validation", dev),
        ("temporal_mean_validation", errors),
        ("temporal_threshold_validation", coverage),
        ("hidden_cell_validation", hidden),
        ("observed_time_distribution", raw),
        ("observed_rank_cohorts", rank_cohorts),
        ("estimated_benchmarks", table),
        ("estimated_finish_cohorts", finish_cohorts),
        ("state_effects", effects),
        ("score_thresholds", score_grid),
        ("model_coefficients", coefficients),
    ]:
        frame.to_csv(OUT / (name + ".csv"), index=False)
    whole = table[table.part.eq("finish")].copy()
    grid = pd.MultiIndex.from_product(
        [["서울", "부산"], GRADES, BANDS], names=["meet", "grade", "band"]
    ).to_frame(index=False)
    whole = grid.merge(whole, on=["meet", "grade", "band"], how="left", validate="one_to_one")
    missing = whole["mean"].isna()
    whole.loc[missing, "status"] = "no_recent_grade_reference"
    for row in whole[missing].itertuples():
        historical = d[d.meet.eq(row.meet) & d.grade.eq(row.grade) & d.band.eq(row.band)]
        whole.loc[row.Index, "historical_n"] = len(historical)
        whole.loc[row.Index, "historical_days"] = historical.date.nunique()
    whole.to_csv(OUT / "whole_time_benchmarks.csv", index=False)
    table[table.band.eq("건조")].to_csv(OUT / "dry_benchmarks.csv", index=False)
    scores.to_parquet(OUT / "historical_record_scores.parquet", index=False)
    references, common = [], []
    recent = d[d.year.ge(2024)]
    lookup = effects.set_index(["meet", "grade", "band", "part"]).shift_from_dry
    for meet, g in recent.groupby("meet"):
        r = g[["meet", "grade", "date", "row_key"]].copy()
        for part in PARTS:
            if meet == "서울" and part == "last400":
                r[part] = np.nan
                continue
            delta = np.array(
                [
                    lookup[meet, grade, band, part]
                    for grade, band in zip(g.grade, g.band, strict=True)
                ]
            )
            r[part] = np.round(g[part] - delta, 9)
            common.append(
                dict(
                    meet=meet,
                    distance=1600,
                    reference_band="건조",
                    part=part,
                    reference_n=int(r[part].count()),
                    **stats(r[part]),
                )
            )
        references.append(r)
    pd.concat(references, ignore_index=True).to_parquet(
        OUT / "reference_dry_times.parquet", index=False
    )
    pd.DataFrame(common).to_csv(OUT / "all_grade_distance_benchmarks.csv", index=False)
    # A record-level example uses only earlier years, not the final retrospective table.
    examples = (
        scores[scores.date.dt.year.eq(2026)]
        .sort_values("date")
        .groupby(["meet", "horse_id"])
        .tail(1)
    )
    examples[
        [
            "meet",
            "horse_id",
            "date",
            "grade",
            "band",
            "finish",
            "early",
            "late",
            "score_finish",
            "score_early",
            "score_late",
            "score_distance_finish",
            "dry_equivalent_finish",
            "reference_max_date",
            "reference_n",
        ]
    ].to_csv(OUT / "latest_horse_record_examples.csv", index=False)
    summary = dict(
        created_on="2026-10-06",
        version="1600_v1_20261006",
        venues=["서울", "부산"],
        inputs=hashes,
        input_n=len(d),
        recent_n=len(recent),
        input_end={m: str(g.date.max().date()) for m, g in d.groupby("meet")},
        selected_interaction_scale=selected,
        ridge_alpha=10,
        training_weight="equal total per race; normalized mean weight 1",
        development_years_requested=[2021, 2022, 2023],
        development_years_by_venue={
            m: sorted(g.year.unique().tolist()) for m, g in dev.groupby("meet")
        },
        evaluation_years=[2024, 2025, 2026],
        boot_replicates=BOOT,
        boot_seed=SEED,
        disjoint_section_metres=dict(early=200, middle1=800, middle2=400, late=200),
        bootstrap=(
            "same-date cluster multipliers for refits and reference, preprocessing fixed; "
            "replicates without the reference grade are omitted for that grade"
        ),
        software=dict(sklearn=sklearn.__version__, numpy=np.__version__, pandas=pd.__version__),
        reference_cells=len(table[table.part.eq("finish")]),
        unsupported_whole_cells=int(missing.sum()),
        benchmark_rows=len(table),
        score_rows=len(scores),
        observed_coverage={
            meet: int(g[g.observed_n.gt(0)].shape[0])
            for meet, g in table[table.part.eq("finish")].groupby("meet")
        },
        mean_validation=metrics,
        threshold_validation=shares,
        hidden_cell_validation=hidden_metrics,
        interpretation=(
            "standardized location-shift distribution of recent same-grade runners; "
            "not causal moisture, win probability or pre-race ability forecast"
        ),
    )
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
