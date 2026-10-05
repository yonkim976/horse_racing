"""Read-only descriptive trial benchmarks; no race par or prediction promotion."""

import hashlib
import json
import shutil
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
OUT = HERE / "outputs"
FIELDS = {
    "finish": "rcTime",
    "s1f": "rcTimeS1f",
    "g3f": "rcTimeG3f",
    "g1f": "rcTimeG1f",
    "g400": "rcTimeG400",
}
METRICS = list(FIELDS) + ["middle200", "middle400", "fs200", "fs600", "fs400"]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def numeric(series):
    return pd.to_numeric(series, errors="coerce")


def describe(frame, keys):
    rows = []
    for group, one in frame.groupby(keys, dropna=False, sort=True):
        group = group if isinstance(group, tuple) else (group,)
        tags = dict(zip(keys, group, strict=True))
        for metric in METRICS:
            good = one.dropna(subset=[metric])
            x = good[metric]
            if x.empty:
                continue
            row = dict(
                tags,
                metric=metric,
                n=len(x),
                horses=good.horse_id.nunique(),
                sessions=good.trial_session_id.nunique(),
                days=good.trial_date.nunique(),
                mean=float(x.mean()),
                sd=float(x.std(ddof=1)),
                median=float(x.median()),
                minimum=float(x.min()),
                maximum=float(x.max()),
                date_equal_mean=float(good.groupby("trial_date")[metric].mean().mean()),
            )
            row.update({f"p{q}": float(x.quantile(q / 100)) for q in [10, 25, 75, 90]})
            rows.append(row)
    return pd.DataFrame(rows)


def main():
    if OUT.exists():
        raise SystemExit("Existing outputs preserved; use a new study version.")
    db_before = sha(DB)
    with duckdb.connect(str(DB), read_only=True) as con:
        raw = con.execute("SELECT * FROM trial_participants_venue_reviewed").fetchdf()
    assert raw.participant_row_id.is_unique
    assert set(raw.source_meet_query) == {"1", "3"}
    df = raw.copy()
    df["meet"] = df.source_meet_query.map({"1": "서울", "3": "부산"})
    df["date"] = pd.to_datetime(df.trial_date)
    df["year"] = df.date.dt.year
    df["age"] = numeric(df.api_age)
    df["moisture"] = numeric(df.api_track.str.extract(r"(\d+(?:\.\d+)?)\s*%")[0])
    df["moisture_band"] = (
        pd.cut(
            df.moisture, [0, 5, 9, 14, 19, np.inf], labels=["건조", "양호", "다습", "포화", "불량"]
        )
        .astype("string")
        .fillna("미확정")
    )
    for metric, field in FIELDS.items():
        df[metric + "_raw"] = numeric(df["api_" + field])
        df[metric] = df[metric + "_raw"].where(df[metric + "_raw"] > 0)
    bounds = {"finish": (50, 100), "s1f": (10, 30), "g3f": (25, 60), "g1f": (8, 25)}
    flags = {}
    for metric, (lo, hi) in bounds.items():
        flags[metric + "_missing_or_range"] = ~df[metric].between(lo, hi)
    df["middle200"] = df.finish - df.g3f - df.s1f
    df["middle400"] = df.g3f - df.g1f
    flags["partition_invalid"] = ~(df.middle200.between(8, 30) & df.middle400.between(16, 50))
    flag_frame = pd.DataFrame(flags)
    df["valid_core"] = ~flag_frame.any(axis=1)
    df["valid_finish"] = df.finish.between(50, 100)
    df["quality_flags"] = flag_frame.apply(lambda row: "|".join(row.index[row]), axis=1)
    df["valid_g400"] = df.g400.between(8, 50) & (df.g400 > df.g1f) & (df.g400 < df.g3f)
    df["g400"] = df.g400.where(df.valid_g400)
    df["fs200"] = 20 * df.finish / df.g1f
    df["fs600"] = 60 * df.finish / df.g3f
    df["fs400"] = 40 * df.finish / df.g400
    df["cohort"] = np.select(
        [
            (df.api_passFlag == "합격") & (df.api_reason == "주행미합(신)"),
            df.api_passFlag == "합격",
            (df.api_passFlag == "불합격") & (df.api_reason == "주행미합(신)"),
            df.api_passFlag == "불합격",
            df.api_passFlag.isin(["연습주행", "주행연습"]),
        ],
        ["신마사유 합격", "그밖의 합격", "신마사유 불합격", "그밖의 불합격", "연습"],
        default="기타판정",
    )
    df["phase"] = np.where(
        df.year == 2026,
        np.where(df.date.dt.month < 7, "2026 상반기", "2026 하반기"),
        df.year.astype(str),
    )
    df["age_band"] = np.select(
        [df.age <= 2, df.age == 3, df.age >= 4], ["2세 이하", "3세", "4세 이상"], default="미확정"
    )
    OUT.mkdir()
    df.to_parquet(OUT / "participants.parquet", index=False)
    df.loc[
        ~df.valid_core,
        ["participant_row_id", "meet", "trial_date", "api_passFlag", "api_reason", "quality_flags"]
        + [x + "_raw" for x in FIELDS],
    ].to_csv(OUT / "quality_ledger.csv", index=False)
    stats = []
    for period, since in [
        ("전체2010이후", "2010-01-01"),
        ("2017이후", "2017-01-01"),
        ("2024이후", "2024-01-01"),
    ]:
        one = df[df.valid_core & (df.trial_date >= since)].copy()
        s = describe(one, ["meet", "cohort"])
        s["period"] = period
        stats.append(s)
        allpass = one[one.api_passFlag == "합격"].copy()
        allpass["cohort"] = "전체 합격"
        s = describe(allpass, ["meet", "cohort"])
        s["period"] = period
        stats.append(s)
    distributions = pd.concat(stats, ignore_index=True)
    distributions.to_csv(OUT / "distributions.csv", index=False)
    recent = df[df.valid_core & (df.trial_date >= "2024-01-01")].copy()
    primary = recent[recent.cohort == "신마사유 합격"].copy()
    describe(primary, ["meet"]).to_csv(OUT / "primary_recent_new_pass.csv", index=False)
    describe(recent, ["meet", "phase", "cohort", "age_band"]).to_csv(
        OUT / "phase_age_cohorts.csv", index=False
    )
    describe(primary, ["meet", "moisture_band"]).to_csv(OUT / "moisture_reference.csv", index=False)
    total = df[df.valid_finish & (df.api_passFlag == "합격")].copy()
    for metric in METRICS:
        if metric != "finish":
            total[metric] = np.nan
    total["cohort"] = "전체시간만 적격인 합격"
    describe(total, ["meet", "cohort"]).to_csv(OUT / "finish_only_sensitivity.csv", index=False)
    minima = []
    for period, since in [("전체2010이후", "2010-01-01"), ("최근2024이후", "2024-01-01")]:
        one = df[df.valid_core & (df.api_passFlag == "합격") & (df.trial_date >= since)]
        for _meet, part in one.groupby("meet"):
            for metric in FIELDS:
                target = part[metric].min()
                selected = part[part[metric].eq(target)].copy()
                selected["minimum_metric"] = metric
                selected["minimum_value"] = target
                selected["period"] = period
                minima.append(selected)
    minimum_rows = pd.concat(minima, ignore_index=True)
    minimum_rows.to_parquet(OUT / "minimum_records.parquet", index=False)
    columns = [
        "period",
        "meet",
        "minimum_metric",
        "minimum_value",
        "trial_date",
        "trial_no",
        "api_chulNo",
        "horse_id",
        "horse_name",
        "api_reason",
        "source_file",
        "source_item_index",
    ]
    minimum_rows[columns].to_csv(OUT / "minimum_records.csv", index=False)
    statuses = (
        df.groupby(["meet", "api_passFlag"], dropna=False)
        .agg(
            raw_rows=("participant_row_id", "size"),
            valid_core=("valid_core", "sum"),
            valid_finish=("valid_finish", "sum"),
        )
        .reset_index()
    )
    statuses.to_csv(OUT / "status_coverage.csv", index=False)
    threshold = pd.Series(np.nan, index=df.index)
    threshold.loc[df.year == 2026] = 66
    threshold.loc[(df.year == 2026) & (df.date.dt.month >= 7) & (df.age >= 3)] = 65
    threshold.loc[(df.year == 2026) & df.age.isna()] = np.nan
    rule_audit = df.loc[
        (df.year == 2026) & (df.api_passFlag == "합격"),
        ["participant_row_id", "meet", "trial_date", "age", "finish_raw", "api_nopassReason"],
    ].copy()
    rule_audit["time_threshold"] = threshold.loc[rule_audit.index]
    rule_audit["above_rule_time"] = rule_audit.finish_raw > rule_audit.time_threshold + 1e-8
    rule_audit.to_csv(OUT / "rule_time_audit_2026.csv", index=False)
    snapshots = [
        DB,
        DB.parent / "manifest.json",
        HERE / "PLAN.md",
        HERE / "analyze.py",
        ROOT / "thoroughbred/research/20261001_yeongnam_trial_venue_recheck_v2/README.md",
        ROOT
        / "thoroughbred/research/20261001_yeongnam_trial_venue_recheck_v2"
        / "raceplan2026_20260516.pdf",
    ]
    input_manifest = [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in snapshots]
    for path, claimed in df.groupby("source_file").source_file_sha256.first().items():
        actual = sha(ROOT / path)
        assert actual == claimed, path
        input_manifest.append({"path": path, "sha256": actual})
    assert sha(DB) == db_before
    summary = {
        "scope": "서울·부산 1000m 주행심사 원시 기록 기초분포",
        "assembled_on": "2026-10-03",
        "data_start": df.trial_date.min(),
        "data_end": df.trial_date.max(),
        "raw_rows": len(df),
        "raw_sessions": df.trial_session_id.nunique(),
        "valid_core_rows": int(df.valid_core.sum()),
        "primary_rows": len(primary),
        "input_files": input_manifest,
        "primary": json.loads(describe(primary, ["meet"]).to_json(orient="records")),
        "coverage": json.loads(statuses.to_json(orient="records")),
        "official_rule_2026": {
            "distance_m": 1000,
            "through_age3_june_seconds": 66,
            "age3_july_and_older_seconds_from_2026H2": 65,
        },
        "no_moisture_correction": True,
        "no_par_adoption": True,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    shutil.copyfile(snapshots[-1], OUT / "official_plan_2026.pdf")
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in ["input_files", "coverage", "primary"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
