"""Read-only Seoul1700 grade availability check, with original result evidence."""

import gzip
import hashlib
import json
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
API = HERE.parent / "20261002_track_source_reconciliation/results/api_study_population.parquet"
PARENT = HERE.parent / "20261002_gate_lateral_bias/outputs/runners.parquet"
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
KEYS = ["meet", "date", "race_no", "horse_id"]
BANDS = ["건조", "양호", "다습", "포화", "불량"]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def counts(frame):
    return dict(
        records=len(frame),
        races=frame.race_key.nunique(),
        n_days=frame.date.nunique(),
        unique_horses=frame.horse_id.nunique(),
        first_date=frame.date.min() if len(frame) else None,
        last_date=frame.date.max() if len(frame) else None,
    )


def main():
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in [API, PARENT, DB]}
    a = pd.read_parquet(API)
    a = a[a.meet.eq(1) & a.distance_m.eq(1700)].copy()
    h = pd.read_parquet(PARENT)
    h = h[h.meet.eq(1) & h.distance_m.eq(1700)].copy()
    for frame in [a, h]:
        assert not frame.duplicated(KEYS).any()
    normal = a.merge(h[KEYS], on=KEYS, how="inner", validate="one_to_one")
    assert len(normal) == len(h)
    for frame in [a, normal]:
        frame["race_key"] = frame.date + ":" + frame.race_no.astype(str)
        assert frame.groupby("race_key").grade_normalized.nunique().eq(1).all()
    rows = []
    for label, frame in [("source_audited", a), ("parent_normal_full_race", normal)]:
        for period, subset in [
            ("2018plus", frame),
            ("2024plus", frame[frame.date.ge("2024-01-01")]),
        ]:
            for grade, group in subset.groupby("grade_normalized"):
                rows.append(dict(cohort=label, period=period, grade=grade, **counts(group)))
    coverage = pd.DataFrame(rows)
    coverage.to_csv(OUT / "grade_coverage.csv", index=False)
    recent = normal[normal.date.ge("2024-01-01")]
    bands = []
    for grade in sorted(recent.grade_normalized.unique()):
        for band in BANDS:
            group = recent[recent.grade_normalized.eq(grade) & recent.band.eq(band)]
            bands.append(dict(grade=grade, band=band, **counts(group)))
    pd.DataFrame(bands).to_csv(OUT / "recent_grade_band_coverage.csv", index=False)
    yearly = []
    for (year, grade), group in normal.groupby([normal.date.str[:4], "grade_normalized"]):
        yearly.append(dict(year=year, grade=grade, **counts(group)))
    pd.DataFrame(yearly).to_csv(OUT / "annual_grade_coverage.csv", index=False)
    low = normal[normal.grade_normalized.isin(["국5", "국6"])].copy()
    with duckdb.connect(str(DB), read_only=True) as c:
        raw = c.execute("""SELECT CAST(source_meet AS INTEGER) meet,
            result_date, CAST(result_race_no AS INTEGER) race_no, horse_id_raw horse_id,
            horse_name_raw horse_name, grade_raw, TRY_CAST(result_rank_raw AS INTEGER) finish_rank,
            TRY_CAST(finish_time_seconds_raw AS DOUBLE) finish_seconds,
            race_distance_m_raw distance_raw
            FROM confirmed_runners WHERE source_meet='1' AND race_distance_m_raw='1700'
            AND result_date >= '20180101'""").fetchdf()
        races = c.execute("""SELECT result_date_key,
            TRY_CAST(result_race_no_key AS INTEGER) race_no,
            actual_grade_raw, actual_distance_m_raw FROM confirmed_races
            WHERE source_meet='1' AND actual_distance_m_raw='1700'
            AND result_date_key >= '20180101'""").fetchdf()
    raw["date"] = pd.to_datetime(raw.result_date).dt.strftime("%Y-%m-%d")
    merged = low.merge(raw, on=KEYS, how="left", validate="one_to_one")
    assert merged.grade_raw.notna().all()
    assert merged.grade.eq(merged.grade_raw).all()
    assert merged["rank"].eq(merged.finish_rank).all()
    assert ((merged.finish / 1000 - merged.finish_seconds).abs() < 1e-8).all()
    races["date"] = pd.to_datetime(races.result_date_key).dt.strftime("%Y-%m-%d")
    low_races = low[["date", "race_no", "grade", "race_key"]].drop_duplicates()
    race_check = low_races.merge(races, on=["date", "race_no"], how="left", validate="one_to_one")
    assert race_check.grade.eq(race_check.actual_grade_raw).all()
    assert race_check.actual_distance_m_raw.eq("1700").all()
    source_hashes = {}
    for name, group in merged.groupby("source_file"):
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT / "thoroughbred/research/20260929_calendar_api_v1/raw")
        source_hashes[name] = sha(path)
        with gzip.open(path, "rt", encoding="utf-8") as f:
            items = json.load(f)["response"]["body"]["items"]["item"]
        for row in group.itertuples():
            item = items[int(row.source_item_index)]
            assert str(item["rcDate"]) == row.date.replace("-", "")
            assert int(item["rcNo"]) == row.race_no
            assert str(item["hrNo"]).zfill(7) == row.horse_id
            assert int(item["rcDist"]) == 1700
            assert item["rank"] == row.grade
            assert abs(float(item["rcTime"]) - row.finish_seconds) < 1e-8
    examples = merged.sort_values(["date", "race_no", "rank"], ascending=[False, False, True])
    examples = examples.groupby("grade_normalized", sort=False).head(3)
    columns = [
        "date",
        "race_no",
        "grade_normalized",
        "horse_id",
        "horse_name",
        "rank",
        "finish_seconds",
        "source_file",
        "source_item_index",
    ]
    examples[columns].to_csv(OUT / "recent_examples.csv", index=False)
    assert len(normal) == 9077 and len(recent) == 2311
    for grade, n, nr in [("국5", 3075, 875), ("국6", 1171, 485)]:
        assert len(normal[normal.grade_normalized.eq(grade)]) == n
        assert len(recent[recent.grade_normalized.eq(grade)]) == nr
    assert sum(row["records"] for row in bands) == len(recent)
    assert {str(p.relative_to(ROOT)): sha(p) for p in [API, PARENT, DB]} == inputs
    verification = dict(
        passed=True,
        input_hashes_unchanged=True,
        inputs=inputs,
        core_runner_rows_verified=len(merged),
        core_races_verified=len(race_check),
        original_api_rows_verified=len(merged),
        raw_files=source_hashes,
        grade_distance_time_identity_mismatches=0,
        grade_is_race_event_grade=True,
        counting_unit="runner appearances, not unique horses",
        no_new_section_quality_filter=True,
    )
    (OUT / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2) + "\n"
    )
    summary = dict(
        checked_on="2026-10-06",
        meet="서울",
        distance_m=1700,
        scope="Availability only; no 1700m time benchmarks or moisture effects estimated",
        source_audited=counts(a),
        parent_normal_full_race=counts(normal),
        recent_reference=counts(recent),
        grades_with_recent_reference=sorted(recent.grade_normalized.unique()),
        grade_counts=json.loads(coverage.to_json(orient="records", force_ascii=False)),
        recent_bands=bands,
        verification=verification,
    )
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in [
                    "source_audited",
                    "parent_normal_full_race",
                    "recent_reference",
                    "grades_with_recent_reference",
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
