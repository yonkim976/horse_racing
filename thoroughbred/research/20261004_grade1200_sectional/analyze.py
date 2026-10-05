"""Grade-specific descriptive sections and strictly prior-year pace references."""

import gzip
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
PRIOR = HERE.parent / "20261003_sectional_pace_moisture/outputs/population.parquet"
HISTORY = HERE.parent / "20261002_gate_lateral_bias/outputs/runners.parquet"
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
RAW = HERE.parent / "20260929_calendar_api_v1/raw/race_execution_probe/2026/meet_4.json.gz"
PARTS = ["early", "middle1", "middle2", "late", "finish", "last600", "last400"]
GRADES = ["국6", "국5", "국4", "혼4", "국3", "혼3", "2", "1", "국OPEN", "혼OPEN"]
BANDS = ["건조", "양호", "다습", "포화", "불량"]
CATS = ["band", "month", "sex", "grade"]
NUMS = [
    "age",
    "weight",
    "rating",
    "prior_finish",
    "prior_top3",
    "prior_early",
    "log_starts",
    "log_gap",
]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def population():
    d = pd.read_parquet(PRIOR)
    d = d[d.population.eq("실전1200")].copy()
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
    d = d.merge(h[["row_key", "rank", "horse_number"]], on="row_key", validate="one_to_one")
    assert len(d) == 41623
    with duckdb.connect(str(DB), read_only=True) as c:
        y = c.execute("""SELECT result_date AS date, result_race_no AS race_no,
          horse_id_raw AS horse_id, horse_name_raw AS horse_name,
          TRY_CAST(result_rank_raw AS INTEGER) AS rank,
          TRY_CAST(horse_program_no_raw AS INTEGER) AS horse_number,
          TRY_CAST(finish_time_seconds_raw AS DOUBLE) AS finish,
          TRY_CAST(horse_age_raw AS DOUBLE) AS age, horse_sex_raw AS sex,
          TRY_CAST(carried_weight_raw AS DOUBLE) AS weight,
          TRY_CAST(horse_rating_raw AS DOUBLE) AS rating,
          grade_raw, track_condition_raw AS track_raw, source_file, source_item_index
          FROM confirmed_runners WHERE source_meet='4' AND race_distance_m_raw='1200'""").fetchdf()
        inventory = c.execute("""SELECT result_date_key AS date, result_race_no_key AS race_no,
          actual_venue_label_raw AS venue, actual_distance_m_raw AS distance,
          actual_grade_raw AS grade, actual_track_condition_raw AS track,
          result_item_count AS runners, execution_status_from_prior_ledger AS status
          FROM confirmed_races WHERE source_meet='4' ORDER BY 1,2""").fetchdf()
        assert inventory.venue.eq("영천").all()
    raw = json.loads(gzip.decompress(RAW.read_bytes()))["response"]["body"]["items"]["item"]
    values = []
    for row in y.itertuples():
        r = raw[int(row.source_item_index)]
        assert (str(r["rcDate"]), str(r["rcNo"]), str(r["hrNo"]), r["meet"]) == (
            row.date,
            row.race_no,
            row.horse_id,
            "영천",
        )
        early, late = float(r["buS1fAccTime"]), float(r["bu_1fGTime"])
        g3_direct = float(r.get("bu_3fGTime", 0))
        g3_derived = float(r["rcTime"]) - float(r["buG3fAccTime"])
        assert np.isclose(early, float(r["buS1fTime"]))
        assert np.isclose(late, float(r["rcTime"]) - float(r["buG1fAccTime"]))
        if g3_direct > 0:
            assert np.isclose(g3_direct, g3_derived)
        values.append(
            {
                "early": early,
                "late": late,
                "last600": g3_direct if g3_direct > 0 else g3_derived,
                "last400": float(r["bu_2fGTime"]),
                "last600_source": "direct" if g3_direct > 0 else "finish_minus_G3F_cumulative",
                "g3f_cumulative": float(r["buG3fAccTime"]),
                "last600_direct": g3_direct,
            }
        )
    y = pd.concat([y.reset_index(drop=True), pd.DataFrame(values)], axis=1)
    y["date"] = pd.to_datetime(y.date)
    y["meet"] = "영천"
    y["grade"] = y.grade_raw.str.replace("등급", "", regex=False)
    y["moisture"] = pd.to_numeric(y.track_raw.str.extract(r"\((\d+)%\)")[0])
    y["band"] = pd.cut(y.moisture, [0, 5, 9, 14, 19, np.inf], labels=BANDS).astype(str)
    y["middle1"] = y.finish - y.last600 - y.early
    y["middle2"] = y.last600 - y.late
    y["middle"] = y.middle1 + y.middle2
    y["year"] = y.date.dt.year
    y["month"] = y.date.dt.month.astype(str)
    y["source_key"] = "영천:" + y.date.dt.strftime("%Y%m%d") + ":" + y.race_no
    y["row_key"] = y.source_key + ":" + y.horse_id
    for _, g in y.groupby("source_key"):
        assert len(g) >= 6 and sorted(g["rank"]) == list(range(1, len(g) + 1))
        assert g.horse_number.notna().all() and not g.horse_number.duplicated().any()
    valid = y.finish.between(60, 110) & y.early.between(10, 25) & y.late.between(8, 25)
    valid &= y.middle1.between(16, 45) & y.middle2.between(16, 45)
    valid400 = y.last400.between(16, 50) & y.last400.gt(y.late) & y.last400.lt(y.last600)
    assert valid.all() and valid400.all()
    assert not y.row_key.duplicated().any()
    return d, y, inventory


def descriptive(frame, keys, ci=False):
    rows = []
    for key, g in frame.groupby(keys, observed=True):
        if not isinstance(key, tuple):
            key = (key,)
        bounds = {}
        if ci and g.date.nunique() >= 2:
            days = g.groupby("date")[PARTS]
            sums, counts = days.sum().to_numpy(), days.count().to_numpy()
            rng = np.random.default_rng(20261004)
            idx = rng.integers(0, len(sums), size=(2000, len(sums)))
            total_n = counts[idx].sum(axis=1)
            means = np.divide(
                sums[idx].sum(axis=1),
                total_n,
                out=np.full_like(total_n, np.nan, dtype=float),
                where=total_n > 0,
            )
            bounds = dict(zip(PARTS, np.nanquantile(means, [0.025, 0.975], axis=0).T, strict=True))
        for part in PARTS:
            good = g[g[part].notna()]
            if good.empty:
                continue
            v = good[part]
            lo, hi = bounds.get(part, (np.nan, np.nan))
            rows.append(
                dict(
                    zip(keys, key, strict=True),
                    part=part,
                    n=len(v),
                    races=good.source_key.nunique(),
                    days=good.date.nunique(),
                    mean=v.mean(),
                    median=v.median(),
                    p10=v.quantile(0.1),
                    p90=v.quantile(0.9),
                    mean_ci_low=lo,
                    mean_ci_high=hi,
                    small_support=len(v) < 200
                    or good.source_key.nunique() < 20
                    or good.date.nunique() < 20,
                )
            )
    return pd.DataFrame(rows)


def ridge(nums=NUMS):
    preprocess = ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATS),
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
    return Pipeline([("preprocess", preprocess), ("fit", Ridge(alpha=10))])


def references(d):
    out, thresholds, validation = [], [], []
    for meet, g in d.groupby("meet"):
        for year in [2024, 2025, 2026]:
            tr, te = g[g.year < year].copy(), g[g.year == year].copy()
            assert tr.date.max() < te.date.min()
            te["reference_max_date"] = tr.date.max()
            for part in ["early", "middle", "late", "late_conditional"]:
                target = "late" if part == "late_conditional" else part
                fit = ridge(NUMS + ["early", "middle"] if part == "late_conditional" else NUMS).fit(
                    tr, tr[target]
                )
                tr["res_" + part] = tr[target] - fit.predict(tr)
                te["expected_" + part] = fit.predict(te)
                te["res_" + part] = te[target] - te["expected_" + part]
                te["pace_" + part] = None
                for grade, tg in tr.groupby("grade"):
                    sg = te.grade.eq(grade)
                    supported = len(tg) >= 100 and tg.date.nunique() >= 10
                    q = tg["res_" + part].quantile([0.25, 0.75]).to_numpy()
                    thresholds.append(
                        dict(
                            meet=meet,
                            year=year,
                            grade=grade,
                            part=part,
                            q25=q[0],
                            q75=q[1],
                            train_n=len(tg),
                            train_days=tg.date.nunique(),
                            supported=supported,
                        )
                    )
                    if supported:
                        v = te.loc[sg, "res_" + part]
                        te.loc[sg, "pace_" + part] = np.where(
                            v < q[0], "빠름", np.where(v > q[1], "느림", "보통")
                        )
                    if target == "late" and sg.any():
                        v = te.loc[sg, "res_" + part]
                        validation.append(
                            dict(
                                meet=meet,
                                year=year,
                                grade=grade,
                                part=part,
                                n=len(v),
                                mae=v.abs().mean(),
                                bias=v.mean(),
                            )
                        )
            keep = (
                ["meet", "date", "year", "grade", "band", "row_key", "source_key", "rank"]
                + PARTS
                + ["middle", "reference_max_date"]
            )
            keep += [c for c in te if c.startswith(("expected_", "res_", "pace_"))]
            out.append(te[keep])
    scored = pd.concat(out, ignore_index=True)
    rows = []
    for key, g in scored.dropna(subset=["pace_early", "pace_middle", "pace_late"]).groupby(
        ["meet", "grade", "pace_early", "pace_middle"]
    ):
        rows.append(
            dict(
                zip(["meet", "grade", "pace_early", "pace_middle"], key, strict=True),
                n=len(g),
                races=g.source_key.nunique(),
                days=g.date.nunique(),
                small_support=len(g) < 200 or g.source_key.nunique() < 20 or g.date.nunique() < 20,
                early_mean=g.early.mean(),
                middle_mean=g.middle.mean(),
                late_mean=g.late.mean(),
                finish_mean=g.finish.mean(),
                late_residual_mean=g.res_late.mean(),
                late_conditional_residual_mean=g.res_late_conditional.mean(),
                fast_late_share=g.pace_late.eq("빠름").mean(),
                slow_late_share=g.pace_late.eq("느림").mean(),
                fast_conditional_late_share=g.pace_late_conditional.eq("빠름").mean(),
            )
        )
    return scored, pd.DataFrame(thresholds), pd.DataFrame(validation), pd.DataFrame(rows)


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite finished output folder")
    OUT.mkdir()
    paths = [PRIOR, HISTORY, DB, RAW, HERE / "PLAN.md", HERE / "analyze.py"]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    d, y, inventory = population()
    y.to_parquet(OUT / "yeongcheon_1200.parquet", index=False)
    inventory.to_csv(OUT / "yeongcheon_race_inventory.csv", index=False)
    recent = pd.concat([d[d.year >= 2024], y], ignore_index=True)
    for name, frame, keys, ci in [
        ("grade_sections", recent, ["meet", "grade"], True),
        ("dry_grade_sections", recent[recent.band.eq("건조")], ["meet", "grade"], True),
        ("moisture_grade_sections", recent, ["meet", "grade", "band"], False),
        ("year_grade_sections", recent, ["meet", "grade", "year"], False),
        ("winner_grade_sections", recent[recent["rank"].eq(1)], ["meet", "grade"], True),
        ("top3_grade_sections", recent[recent["rank"].le(3)], ["meet", "grade"], False),
        ("yeongcheon_race_sections", y, ["meet", "grade", "source_key"], False),
    ]:
        descriptive(frame, keys, ci).to_csv(OUT / (name + ".csv"), index=False)
    scored, thresholds, validation, profiles = references(d)
    scored.to_parquet(OUT / "scored_recent.parquet", index=False)
    thresholds.to_csv(OUT / "grade_reference_thresholds.csv", index=False)
    validation.to_csv(OUT / "grade_reference_validation.csv", index=False)
    profiles.to_csv(OUT / "grade_pace_profiles.csv", index=False)
    coverage = []
    for meet in ["서울", "부산", "영천"]:
        for grade in GRADES:
            g = recent[(recent.meet == meet) & (recent.grade == grade)]
            coverage.append(
                dict(
                    meet=meet,
                    grade=grade,
                    n=len(g),
                    races=g.source_key.nunique(),
                    days=g.date.nunique(),
                    status="no_data"
                    if g.empty
                    else "small_sample"
                    if len(g) < 200 or g.source_key.nunique() < 20 or g.date.nunique() < 20
                    else "descriptive_supported",
                )
            )
    pd.DataFrame(coverage).to_csv(OUT / "coverage.csv", index=False)
    assert hashes == {str(p.relative_to(ROOT)): sha(p) for p in paths}
    summary = dict(
        as_of="2026-10-04",
        input_hashes=hashes,
        inputs_unchanged=True,
        no_track_speed=True,
        prior_valid_runners=len(d),
        recent_runners=len(recent),
        yeongcheon_runners=len(y),
        yeongcheon_races=y.source_key.nunique(),
        yeongcheon_days=y.date.nunique(),
        yeongcheon_derived600=int(y.last600_source.ne("direct").sum()),
        recent_coverage=recent.groupby("meet")
        .agg(
            n=("row_key", "size"),
            races=("source_key", "nunique"),
            days=("date", "nunique"),
            end=("date", "max"),
        )
        .reset_index()
        .assign(end=lambda x: x.end.dt.strftime("%Y-%m-%d"))
        .to_dict("records"),
    )
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "input_hashes"}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
