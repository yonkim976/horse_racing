"""Read-only comparison of the final track study with the new API core DB."""

from __future__ import annotations

import hashlib
import json
import platform
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "results"
OPS = ROOT / "data/horse_racing.sqlite3"
SECTION = ROOT / "data/research/section_point_db_20260925/section_points_adjudicated.sqlite3"
CORE = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
REPORT = ROOT / "research/track_common_residual_20260928/FINAL_REPORT_KO.md"
MANIFEST = CORE.with_name("manifest.json")
KEY = ["meet", "date", "race_no", "horse_id"]
RKEY = KEY[:3]
PARTS = ["start_200", "last_200", "last_600", "finish"]
START, END = "2018-01-01", "2026-09-20"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stamps():
    return {
        str(p.relative_to(ROOT)): {"bytes": p.stat().st_size, "sha256": sha(p)}
        for p in (OPS, SECTION, CORE, REPORT, MANIFEST)
    }


def clean_times(df):
    df = df.copy()
    for part, (lo, hi) in {
        "start_200": (10000, 40000),
        "last_200": (8000, 45000),
        "last_600": (30000, 100000),
    }.items():
        df.loc[~df[part].between(lo, hi) | df[part].ge(df["finish"]), part] = np.nan
    bad = df["last_200"].gt(df["last_600"])
    df.loc[bad, ["last_200", "last_600"]] = np.nan
    speed = df["distance_m"] / (df["finish"] / 1000)
    df.loc[~speed.between(10, 20), "finish"] = np.nan
    return df


def old_data():
    with sqlite3.connect(SECTION.as_uri() + "?mode=ro", uri=True) as c:
        c.execute("ATTACH DATABASE ? AS ops", (OPS.as_uri() + "?mode=ro",))
        c.execute("PRAGMA query_only=ON")
        # Identical study eligibility; official identifiers are added for cross-DB joining.
        raw = pd.read_sql_query(
            """
            SELECT c.race_entry_id, c.meet_code AS meet, c.race_date AS date,
                   c.race_number AS race_no, c.distance_m, c.kra_horse_id AS horse_id,
                   c.horse_number, c.point_code, c.time_kind, c.elapsed_time_ms,
                   c.source_name, c.source_field, h.kra_horse_id AS ops_horse_id,
                   re.horse_number AS ops_horse_number, re.horse_id AS internal_horse_id,
                   re.gate_number AS gate, re.carried_weight_kg AS weight,
                   r.grade, r.track_condition AS band, r.track_moisture_percent AS moisture,
                   r.distance_m AS ops_distance_m, p.tempo_raw, rr.finish_position AS rank,
                   rr.finish_time_ms AS finish, r.race_date_local AS ops_date,
                   r.race_number AS ops_race_no, rc.kra_meet_code AS ops_meet
            FROM common_point c
            JOIN ops.race_entries re ON re.id=c.race_entry_id
            JOIN ops.races r ON r.id=re.race_id
            JOIN ops.racecourses rc ON rc.id=r.racecourse_id
            JOIN ops.horses h ON h.id=re.horse_id
            JOIN ops.race_results rr ON rr.race_entry_id=re.id
            LEFT JOIN ops.race_passing_summaries p ON p.race_id=r.id
            WHERE c.race_date BETWEEN ? AND ? AND c.meet_code IN (1,3)
              AND c.point_code IN ('S1F','G1F','G3F')
              AND rr.finish_position BETWEEN 1 AND 20 AND rr.finish_time_ms>0
              AND r.track_condition IN ('건조','양호','다습','포화','불량')
        """,
            c,
            params=(START, END),
        )
        races = pd.read_sql_query(
            """
            SELECT rc.kra_meet_code AS meet, r.race_date_local AS date,
                   r.race_number AS race_no, r.distance_m, r.grade,
                   r.track_condition AS band, r.track_moisture_percent AS moisture,
                   p.tempo_raw
            FROM ops.races r JOIN ops.racecourses rc ON rc.id=r.racecourse_id
            LEFT JOIN ops.race_passing_summaries p ON p.race_id=r.id
            WHERE r.race_date_local BETWEEN ? AND ? AND rc.kra_meet_code IN (1,3)
        """,
            c,
            params=(START, END),
        )
    if raw.duplicated(["race_entry_id", "point_code", "time_kind"]).any():
        raise ValueError("Duplicate legacy section key")
    meta = raw.drop_duplicates("race_entry_id").set_index("race_entry_id")
    wide = raw.pivot(
        index="race_entry_id", columns=["point_code", "time_kind"], values="elapsed_time_ms"
    )
    wide.columns = ["_".join(x) for x in wide.columns]
    rec = meta.join(wide).reset_index()
    rec["start_200"] = rec["S1F_cumulative"]
    for point, part in (("G1F", "last_200"), ("G3F", "last_600")):
        direct = rec.get(point + "_closing", pd.Series(np.nan, index=rec.index))
        cumulative = rec.get(point + "_cumulative", pd.Series(np.nan, index=rec.index))
        rec[part] = direct.fillna(rec["finish"] - cumulative)
    rec["horse_id"] = rec["horse_id"].astype("string").str.zfill(7)
    rec["ops_horse_id"] = rec["ops_horse_id"].astype("string").str.zfill(7)
    integrity = {}
    for a, b in (
        ("horse_id", "ops_horse_id"),
        ("horse_number", "ops_horse_number"),
        ("distance_m", "ops_distance_m"),
        ("date", "ops_date"),
        ("race_no", "ops_race_no"),
        ("meet", "ops_meet"),
    ):
        integrity[a] = int(rec[a].ne(rec[b]).sum())
    return rec, races, integrity


def new_data():
    with duckdb.connect(str(CORE), read_only=True) as c:
        c.execute("BEGIN TRANSACTION")
        rec = c.execute("""
            SELECT cast(source_meet AS integer) AS meet,
                   strftime(strptime(result_date,'%Y%m%d'),'%Y-%m-%d') AS date,
                   cast(result_race_no AS integer) AS race_no, horse_id_raw AS horse_id,
                   cast(horse_program_no_raw AS integer) AS horse_number,
                   try_cast(result_rank_raw AS integer) AS rank,
                   round(try_cast(finish_time_seconds_raw AS double)*1000) AS finish,
                   try_cast(race_distance_m_raw AS integer) AS distance_m,
                   grade_raw AS grade, track_condition_raw AS track_raw,
                   try_cast(carried_weight_raw AS double) AS weight,
                   source_file, source_item_index
            FROM confirmed_runners
            WHERE source_meet IN ('1','3') AND result_date BETWEEN '20180101' AND '20260920'
        """).fetchdf()
        race = c.execute(
            """
            SELECT cast(source_meet AS integer) AS meet,
                   cast(race_date AS varchar) AS date,
                   cast(result_race_no_key AS integer) AS race_no,
                   try_cast(actual_distance_m_raw AS integer) AS distance_m,
                   actual_grade_raw AS grade, actual_track_condition_raw AS track_raw
            FROM confirmed_races
            WHERE source_meet IN ('1','3') AND race_date BETWEEN ? AND ?
        """,
            [START, END],
        ).fetchdf()
        sec = c.execute("""
            SELECT meet, strftime(strptime(race_date,'%Y%m%d'),'%Y-%m-%d') AS date,
                   race_no, horse_id, horse_program_no, point_code, measure_kind,
                   source_field, time_ms
            FROM section_measurements_api
            WHERE meet IN (1,3) AND race_date BETWEEN '20180101' AND '20260920'
              AND measure_kind<>'passing_order'
              AND point_code IN ('S1F','G1F','G3F','1F_G','3F_G')
        """).fetchdf()
        columns = c.execute("""SELECT table_name,column_name FROM information_schema.columns
            WHERE regexp_matches(lower(column_name),'tempo|moist|track') ORDER BY 1,2""").fetchall()
        c.execute("COMMIT")
    for df in (rec, race):
        df["band"] = df["track_raw"].str.extract(r"^(건조|양호|다습|포화|불량)", expand=False)
        df["moisture"] = pd.to_numeric(
            df["track_raw"].str.extract(r"(\d+(?:\.\d+)?)\s*%", expand=False), errors="coerce"
        )
    if sec.duplicated(KEY + ["point_code", "measure_kind"]).any():
        raise ValueError("Duplicate API section key")
    wide = sec.pivot(index=KEY, columns=["point_code", "measure_kind"], values="time_ms")
    wide.columns = ["_".join(x) for x in wide.columns]
    rec = rec.merge(wide.reset_index(), on=KEY, how="left", validate="one_to_one")
    rec["start_200"] = rec["S1F_cumulative_time"]
    for point, part, direct_point in (("G1F", "last_200", "1F_G"), ("G3F", "last_600", "3F_G")):
        direct = rec.get(direct_point + "_closing_time", pd.Series(np.nan, index=rec.index))
        rec[part] = direct.fillna(rec["finish"] - rec[point + "_cumulative_time"])
    rec["gate"] = rec["horse_number"]  # comparison proxy only; not independently verified gate.
    return rec, race, columns


def normalized_grade(s):
    return (
        s.astype("string").str.replace("등급", "", regex=False).str.replace(r"\s+", "", regex=True)
    )


def compare(left, right, key, fields, label):
    merged = left.merge(
        right, on=key, how="outer", suffixes=("_old", "_new"), indicator=True, validate="one_to_one"
    )
    both = merged["_merge"].eq("both")
    counts = {str(k): int(v) for k, v in merged["_merge"].value_counts().items()}
    summaries, differences, by_year = {}, [], []
    for field in fields:
        a, b = merged[field + "_old"], merged[field + "_new"]
        valid = both & a.notna() & b.notna()
        numeric = pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b)
        equal = pd.Series(False, index=merged.index)
        if numeric:
            equal.loc[valid] = np.isclose(
                a[valid].astype(float), b[valid].astype(float), rtol=0, atol=1e-6
            )
        else:
            equal.loc[valid] = a[valid].eq(b[valid])
        mismatch = valid & ~equal
        missing_old = both & a.isna() & b.notna()
        missing_new = both & a.notna() & b.isna()
        summaries[field] = {
            "both_present": int(valid.sum()),
            "equal": int(equal.sum()),
            "different": int(mismatch.sum()),
            "old_missing_new_present": int(missing_old.sum()),
            "old_present_new_missing": int(missing_new.sum()),
            "both_missing": int((both & a.isna() & b.isna()).sum()),
        }
        if numeric and mismatch.any():
            summaries[field]["max_absolute_difference"] = float(
                (a[mismatch] - b[mismatch]).abs().max()
            )
        for mask, reason in (
            (mismatch, "different"),
            (missing_old, "old_missing"),
            (missing_new, "new_missing"),
        ):
            d = merged.loc[mask, key].copy()
            d["field"], d["status"] = field, reason
            d["old_value"], d["new_value"] = a[mask].astype("string"), b[mask].astype("string")
            differences.append(d)
        for (meet, year), ix in (
            merged[both].groupby(["meet", merged["date"].str[:4]]).groups.items()
        ):
            by_year.append(
                {
                    "meet": int(meet),
                    "year": str(year),
                    "field": field,
                    "both_present": int(valid.loc[ix].sum()),
                    "equal": int(equal.loc[ix].sum()),
                    "different": int(mismatch.loc[ix].sum()),
                    "old_missing_new_present": int(missing_old.loc[ix].sum()),
                    "old_present_new_missing": int(missing_new.loc[ix].sum()),
                }
            )
    pd.concat(differences, ignore_index=True).to_csv(
        OUT / (label + "_differences.csv"), index=False
    )
    merged[~both].to_parquet(OUT / (label + "_unmatched.parquet"), index=False)
    pd.DataFrame(by_year).to_csv(OUT / (label + "_by_year.csv"), index=False)
    return {"keys": counts, "fields": summaries}


def history_coverage(df):
    results = []
    for part in PARTS:
        valid = (
            df[df[part].notna()]
            .sort_values(KEY[:1] + ["horse_id", "distance_m", "date", "race_no"])
            .copy()
        )
        valid["dt"] = pd.to_datetime(valid["date"])
        prev = valid.groupby(["meet", "horse_id", "distance_m"])["dt"].shift()
        valid["history_eligible"] = (valid["dt"] - prev).dt.days.between(1, 365)
        for (meet, year), g in valid.groupby(["meet", valid["date"].str[:4]]):
            results.append(
                {
                    "meet": int(meet),
                    "year": str(year),
                    "part": part,
                    "valid_times": len(g),
                    "history_eligible": int(g["history_eligible"].sum()),
                }
            )
    return results


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite existing audit results")
    OUT.mkdir()
    before = stamps()
    old, old_races, integrity = old_data()
    new, new_races, environment_columns = new_data()
    new_eligible = new[
        new["rank"].between(1, 20) & new["finish"].gt(0) & new["band"].notna()
    ].copy()
    for frame in (old, new_eligible, old_races, new_races):
        frame["grade_normalized"] = normalized_grade(frame["grade"])
    race_stats = compare(
        old_races,
        new_races,
        RKEY,
        ["distance_m", "grade", "grade_normalized", "band", "moisture"],
        "race",
    )
    runner_stats = compare(
        old,
        new_eligible,
        KEY,
        [
            "horse_number",
            "rank",
            "distance_m",
            "grade",
            "grade_normalized",
            "weight",
            "gate",
            "band",
            "moisture",
        ]
        + PARTS,
        "runner_raw",
    )
    old_clean, new_clean = clean_times(old), clean_times(new_eligible)
    cleaned_stats = compare(old_clean, new_clean, KEY, PARTS, "runner_clean")
    # Preserve exact populations used in the audit, with original source pointers.
    old_clean.to_parquet(OUT / "legacy_study_population.parquet", index=False)
    new_clean.to_parquet(OUT / "api_study_population.parquet", index=False)
    new.to_parquet(OUT / "api_all_confirmed_runners.parquet", index=False)
    moisture = []
    for name, races in (("legacy", old_races), ("api", new_races)):
        for (meet, band), g in races.groupby(["meet", "band"], dropna=False):
            moisture.append(
                {
                    "source": name,
                    "meet": int(meet),
                    "band": None if pd.isna(band) else band,
                    "races": len(g),
                    "days": int(g["date"].nunique()),
                    "moisture_missing": int(g["moisture"].isna().sum()),
                    "moisture_values": sorted(float(x) for x in g["moisture"].dropna().unique()),
                }
            )
    after = stamps()
    result = {
        "scope": {
            "start": START,
            "end": END,
            "meets": [1, 3],
            "legacy_study_runners": len(old),
            "new_confirmed_runners": len(new),
            "new_eligible_finishers": len(new_eligible),
            "excluded_from_comparison": "Jeju (2), Yeongcheon (4), pre-2018",
        },
        "legacy_join_integrity": integrity,
        "races": race_stats,
        "runners_raw": runner_stats,
        "runners_clean": cleaned_stats,
        "history_coverage": {
            "legacy": history_coverage(old_clean),
            "api": history_coverage(new_clean),
        },
        "moisture_coverage": moisture,
        "core_environment_columns": environment_columns,
        "source_files_before": before,
        "source_files_after": after,
        "source_files_unchanged": before == after,
        "gate_note": (
            "API horse program number is only a comparison proxy; "
            "verify actual gate before modeling."
        ),
        "method": (
            "Exact final study SQL/filter and time conversion; same physical filters; "
            "official horse ID keys, milliseconds."
        ),
        "versions": {
            "python": platform.python_version(),
            "duckdb": duckdb.__version__,
            "pandas": pd.__version__,
        },
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    (OUT / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "scope",
                    "legacy_join_integrity",
                    "races",
                    "runners_clean",
                    "source_files_unchanged",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if before != after:
        raise RuntimeError("A source changed during the audit; do not treat results as frozen")


if __name__ == "__main__":
    main()
