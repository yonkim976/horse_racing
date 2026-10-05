"""Recheck original API rows and independently aggregate the primary reference."""

import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    for item in summary["input_files"]:
        assert sha(ROOT / item["path"]) == item["sha256"], item["path"]
    df = pd.read_parquet(OUT / "participants.parquet")
    assert len(df) == 61777 == summary["raw_rows"]
    assert df.participant_row_id.is_unique
    fields = {
        "finish": "rcTime",
        "s1f": "rcTimeS1f",
        "g3f": "rcTimeG3f",
        "g1f": "rcTimeG1f",
        "g400": "rcTimeG400",
    }
    matched = 0
    for path, one in df.groupby("source_file"):
        payload = json.loads((ROOT / path).read_text())
        items = payload["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            items = [items]
        for row in one.itertuples(index=False):
            record = items[int(row.source_item_index)]
            assert record == json.loads(row.source_record_json)
            assert str(record["passFlag"]) == row.api_passFlag
            assert str(record["reason"]) == row.api_reason
            for metric, field in fields.items():
                expected = float(record[field]) if record.get(field) is not None else np.nan
                actual = getattr(row, metric + "_raw")
                assert (np.isnan(expected) and np.isnan(actual)) or expected == actual
            matched += 1
    independent_core = (
        df.finish_raw.between(50, 100)
        & df.s1f_raw.between(10, 30)
        & df.g3f_raw.between(25, 60)
        & df.g1f_raw.between(8, 25)
        & (df.finish_raw - df.g3f_raw - df.s1f_raw).between(8, 30)
        & (df.g3f_raw - df.g1f_raw).between(16, 50)
    )
    np.testing.assert_array_equal(independent_core, df.valid_core)
    good = df[df.valid_core]
    np.testing.assert_allclose(good.s1f + good.middle200 + good.g3f, good.finish)
    np.testing.assert_allclose(good.middle400 + good.g1f, good.g3f)
    np.testing.assert_allclose(good.fs200, 100 * (200 / good.g1f) / (1000 / good.finish))
    np.testing.assert_allclose(good.fs600, 100 * (600 / good.g3f) / (1000 / good.finish))
    assert df.loc[df.g400_raw <= 0, "g400"].isna().all()
    assert df.loc[df.meet == "서울", "g400"].isna().all()
    audited = df[(df.trial_date == "2026-09-17") & (df.source_meet_query == "3")]
    assert len(audited) == 48
    assert audited.physical_venue.eq("부산경남").all()
    assert audited.reviewed_distance_m.eq(1000).all()
    primary = pd.read_csv(OUT / "primary_recent_new_pass.csv")
    con = duckdb.connect()
    con.register("rows", df)
    aggregate = con.execute("""
        SELECT meet, metric, count(value) n, avg(value) mean, median(value) median,
               min(value) minimum, max(value) maximum,
               quantile_cont(value, 0.1) p10, quantile_cont(value, 0.25) p25,
               quantile_cont(value, 0.75) p75, quantile_cont(value, 0.9) p90
        FROM (UNPIVOT (
            SELECT meet, finish, s1f, g3f, g1f, g400, middle200, middle400,
                   fs200, fs600, fs400 FROM rows
            WHERE valid_core AND trial_date >= '2024-01-01'
              AND api_passFlag='합격' AND api_reason='주행미합(신)'
        ) ON finish, s1f, g3f, g1f, g400, middle200, middle400, fs200, fs600, fs400
          INTO NAME metric VALUE value)
        GROUP BY meet, metric ORDER BY meet, metric
    """).fetchdf()
    joined = primary.merge(
        aggregate, on=["meet", "metric"], validate="one_to_one", suffixes=("_a", "_b")
    )
    assert len(joined) == len(primary) == len(aggregate)
    for metric in ["n", "mean", "median", "minimum", "maximum", "p10", "p25", "p75", "p90"]:
        np.testing.assert_allclose(joined[metric + "_a"], joined[metric + "_b"], atol=1e-9, rtol=0)
    assert int(primary[primary.metric == "finish"].n.sum()) == summary["primary_rows"]
    minimum = pd.read_parquet(OUT / "minimum_records.parquet")
    for row in minimum.itertuples(index=False):
        group = good[(good.meet == row.meet) & good.api_passFlag.eq("합격")]
        if row.period == "최근2024이후":
            group = group[group.trial_date >= "2024-01-01"]
        assert group[row.minimum_metric].min() == row.minimum_value
    rpt_records = []
    for meet, date, name, expected in [
        (1, "20191115", "천지스톰", "0:58.9"),
        (3, "20240824", "벌마의스타", "0:58.7"),
        (1, "20240229", "어마어마", "0:59.9"),
        (1, "20251218", "거센대로", "0:59.9"),
    ]:
        path = ROOT / (
            "data/raw/kra_text/dacom23/"
            f"meet={meet}/year={date[:4]}/month={date[4:6]}/day={date[6:]}/{date}dacom23.rpt"
        )
        lines = [
            line
            for line in path.read_bytes().decode("cp949").splitlines()
            if name in line and expected in line
        ]
        assert len(lines) == 1
        rpt_records.append(
            {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "line": lines[0]}
        )
    rule = pd.read_csv(OUT / "rule_time_audit_2026.csv")
    assert not rule.above_rule_time.any()
    result = {
        "status": "passed",
        "raw_api_rows_matched": matched,
        "core_validity_reproduced": int(independent_core.sum()),
        "primary_aggregate_metrics_reproduced": len(joined),
        "zero_sentinels_excluded": True,
        "partition_and_fs_checked": True,
        "venue_review_48_rows_checked": True,
        "minimum_rows_checked": len(minimum),
        "rpt_minimum_evidence": rpt_records,
        "2026_pass_above_time_rule_rows": int(rule.above_rule_time.sum()),
        "source_hashes_checked": len(summary["input_files"]),
        "verification_sha256": sha(HERE / "verify.py"),
    }
    (OUT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
