"""Trace comparison differences back to frozen API source records."""

from __future__ import annotations

import gzip
import json
import sqlite3

import duckdb
import pandas as pd
from audit import CORE, KEY, OPS, OUT, ROOT, sha

from horse_racing.parsers.dacom11 import parse_dacom11_report


def band_from_percent(s):
    return pd.cut(
        s, [0, 5, 9, 14, 19, float("inf")], labels=["건조", "양호", "다습", "포화", "불량"]
    ).astype("string")


def trace_rpt(diff, new):
    """Compare the archived RPT values without adjudicating which source is correct."""
    rows, files = [], {}
    relevant = diff[diff.status.eq("different")].merge(
        new[KEY + ["horse_number"]], on=KEY, validate="many_to_one"
    )
    attrs = {
        "start_200": "s1f_ms",
        "last_200": "g1f_ms",
        "last_600": "g3f_ms",
        "finish": "finish_time_ms",
    }
    for (meet, date), group in relevant.groupby(["meet", "date"]):
        year, month, day = date.split("-")
        path = ROOT / (
            f"data/raw/kra_text/dacom11/meet={meet}/year={year}/month={month}/day={day}/"
            f"{year}{month}{day}dacom11.rpt"
        )
        if not path.exists():
            rows.append({"meet": int(meet), "date": date, "status": "rpt_absent"})
            continue
        files[str(path.relative_to(ROOT))] = sha(path)
        races = {r.race_number: r for r in parse_dacom11_report(path.read_bytes())}
        for row in group.to_dict("records"):
            race = races.get(row["race_no"])
            entry = (
                next((e for e in race.entries if e.horse_number == row["horse_number"]), None)
                if race
                else None
            )
            value = getattr(entry, attrs[row["field"]]) if entry else None
            rows.append(
                {
                    **{k: row[k] for k in KEY},
                    "field": row["field"],
                    "horse_number": row["horse_number"],
                    "rpt_horse_name": entry.horse_name if entry else None,
                    "rpt_value_ms": value,
                    "old_value_ms": row["old_value"],
                    "new_value_ms": row["new_value"],
                    "rpt_matches_old": value == row["old_value"],
                    "rpt_matches_new": value == row["new_value"],
                    "source_file": str(path.relative_to(ROOT)),
                    "status": "compared" if entry else "rpt_entry_absent",
                }
            )
    pd.DataFrame(rows).to_csv(OUT / "rpt_time_value_checks.csv", index=False)
    examples = []
    for date in ("2018-05-06", "2023-12-16"):
        year, month, day = date.split("-")
        path = ROOT / (
            f"data/raw/kra_text/dacom11/meet=1/year={year}/month={month}/day={day}/"
            f"{year}{month}{day}dacom11.rpt"
        )
        lines = path.read_bytes().decode("cp949").splitlines()
        examples.append(
            {
                "date": date,
                "file": str(path.relative_to(ROOT)),
                "sha256": sha(path),
                "track_lines": [line for line in lines if "날씨" in line],
            }
        )
    (OUT / "rpt_moisture_missing_examples.json").write_text(
        json.dumps(examples, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "compared": sum(r["status"] == "compared" for r in rows),
        "rpt_matches_old": sum(r.get("rpt_matches_old", False) for r in rows),
        "rpt_matches_new": sum(r.get("rpt_matches_new", False) for r in rows),
        "source_hashes": files,
        "note": "RPT lacks official horse IDs; match race/program number, retain name.",
    }


def main():
    output = OUT / "investigation.json"
    if output.exists():
        raise FileExistsError(output)
    old = pd.read_parquet(OUT / "legacy_study_population.parquet")
    new = pd.read_parquet(OUT / "api_study_population.parquet")
    all_new = pd.read_parquet(OUT / "api_all_confirmed_runners.parquet")
    diff = pd.read_csv(OUT / "runner_clean_differences.csv", dtype={"horse_id": str})
    raw_diff = pd.read_csv(OUT / "runner_raw_differences.csv", dtype={"horse_id": str})
    trace = raw_diff.merge(
        new[KEY + ["source_file", "source_item_index", "track_raw"]], on=KEY, validate="many_to_one"
    )
    trace_keys = trace[KEY + ["source_file", "source_item_index"]].drop_duplicates()
    archived, hashes = [], {}
    for filename, group in trace_keys.groupby("source_file"):
        path = (ROOT / filename).resolve()
        path.relative_to(ROOT)
        digest = sha(path)
        with gzip.open(path, "rt", encoding="utf-8") as f:
            doc = json.load(f)
        items = doc["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            items = [items]
        hashes[filename] = digest
        for row in group.to_dict("records"):
            item = items[int(row["source_item_index"])]
            if str(item["hrNo"]).zfill(7) != row["horse_id"]:
                raise ValueError("API source pointer horse ID mismatch")
            if str(item["rcDate"]) != row["date"].replace("-", ""):
                raise ValueError("API source pointer date mismatch")
            if int(item["rcNo"]) != row["race_no"]:
                raise ValueError("API source pointer race mismatch")
            archived.append({**row, "source_record": item, "file_sha256": digest})
        if sha(path) != digest:
            raise RuntimeError("Archived API changed during trace")
    records = {
        (r["meet"], r["date"], r["race_no"], r["horse_id"]): r["source_record"] for r in archived
    }
    value_checks = []
    for row in trace.to_dict("records"):
        item = records[tuple(row[k] for k in KEY)]
        field = row["field"]
        if field == "start_200":
            expected = float(item["seS1fAccTime" if row["meet"] == 1 else "buS1fAccTime"]) * 1000
        elif field in ("last_200", "last_600"):
            point = "1f" if field == "last_200" else "3f"
            if row["meet"] == 3 and float(item.get(f"bu_{point}GTime", 0)) > 0:
                expected = float(item[f"bu_{point}GTime"]) * 1000
            else:
                prefix = "se" if row["meet"] == 1 else "bu"
                expected = (float(item["rcTime"]) - float(item[f"{prefix}G{point}AccTime"])) * 1000
        elif field == "finish":
            expected = float(item["rcTime"]) * 1000
        elif field == "weight":
            expected = float(item["wgBudam"])
        elif field == "moisture":
            expected = float(
                pd.Series([item["track"]]).str.extract(r"(\d+(?:\.\d+)?)\s*%", expand=False).iloc[0]
            )
        else:
            continue
        value_checks.append(
            {
                **{k: row[k] for k in KEY},
                "field": field,
                "expected_from_archived_api": expected,
                "new_value": row["new_value"],
                "matches": (
                    expected == 0
                    if pd.isna(row["new_value"])
                    else abs(expected - float(row["new_value"])) < 1e-6
                ),
            }
        )
    pd.DataFrame(value_checks).to_csv(OUT / "archived_api_value_checks.csv", index=False)
    with (OUT / "archived_api_evidence.jsonl").open("w", encoding="utf-8") as f:
        for row in archived:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    races = all_new.drop_duplicates(KEY[:3]).copy()
    races["band_from_percent"] = band_from_percent(races["moisture"])
    conflict = races[races["band"].ne(races["band_from_percent"]).fillna(True)]
    conflict[
        KEY[:3]
        + ["band", "moisture", "band_from_percent", "track_raw", "source_file", "source_item_index"]
    ].to_csv(OUT / "api_band_percent_conflicts.csv", index=False)
    extras = pd.read_parquet(OUT / "runner_raw_unmatched.parquet")
    with duckdb.connect(str(CORE), read_only=True) as c:
        verdict = (
            c.execute(
                "SELECT * FROM race_execution_adjudicated WHERE meet=? AND date=? AND race_no=?",
                ["3", "20251226", "6"],
            )
            .fetchdf()
            .to_dict("records")
        )
    with sqlite3.connect(OPS.as_uri() + "?mode=ro", uri=True) as c:
        old_entry_meta = pd.read_sql_query(
            """
            SELECT rc.kra_meet_code AS meet, r.race_date_local AS date,
                   r.race_number AS race_no, h.kra_horse_id AS horse_id,
                   re.id AS race_entry_id, r.track_condition AS old_band,
                   rr.finish_position AS old_rank, rr.finish_time_ms AS old_finish
            FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id
            JOIN race_entries re ON re.race_id=r.id JOIN horses h ON h.id=re.horse_id
            LEFT JOIN race_results rr ON rr.race_entry_id=re.id
            WHERE rc.kra_meet_code IN (1,3) AND r.race_date_local BETWEEN ? AND ?
            """,
            c,
            params=("2018-01-01", "2026-09-20"),
        )
    old_entry_meta["horse_id"] = old_entry_meta["horse_id"].astype("string").str.zfill(7)
    extra_meta = extras[KEY].merge(old_entry_meta, on=KEY, how="left", validate="one_to_one")
    extra_meta.to_csv(OUT / "new_only_legacy_entry_metadata.csv", index=False)
    result = {
        "time_differences": {
            "measurements": int(diff.status.eq("different").sum()),
            "runners": len(diff[diff.status.eq("different")].drop_duplicates(KEY)),
            "races": len(diff[diff.status.eq("different")].drop_duplicates(KEY[:3])),
            "meets": sorted(int(v) for v in diff[diff.status.eq("different")]["meet"].unique()),
        },
        "archived_api_records_traced": len(archived),
        "archived_api_value_checks": len(value_checks),
        "archived_api_checks_all_pass": all(r["matches"] for r in value_checks),
        "archived_api_source_hashes": hashes,
        "api_band_percent_conflicts": {
            "races": len(conflict),
            "days": len(conflict[KEY[:2]].drop_duplicates()),
            "by_meet": {str(k): int(v) for k, v in conflict.groupby("meet").size().items()},
        },
        "legacy_bad_band": [
            {
                "meet": int(meet),
                "runners": len(g),
                "all_days": g.date.nunique(),
                "days_with_numeric_percent": g[g.moisture.notna()].date.nunique(),
                "missing_percent_runners": int(g.moisture.isna().sum()),
            }
            for meet, g in old[old.band.eq("불량")].groupby("meet")
        ],
        "api_bad_band": [
            {
                "meet": int(meet),
                "runners": len(g),
                "all_days": g.date.nunique(),
                "numeric_values": sorted(int(x) for x in g.moisture.unique()),
            }
            for meet, g in new[new.band.eq("불량")].groupby("meet")
        ],
        "new_only_runners": len(extras),
        "new_only_races": len(extras[KEY[:3]].drop_duplicates()),
        "new_only_legacy_band_missing": int(extra_meta.old_band.isna().sum()),
        "new_only_legacy_band_present": int(extra_meta.old_band.notna().sum()),
        "legacy_only_race_verdict": verdict,
        "rpt_trace": trace_rpt(diff, new),
        "limits": (
            "API value agreement validates extraction, not physical truth or publication time. "
            "RPT differences remain unadjudicated."
        ),
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "archived_api_source_hashes"},
            ensure_ascii=False,
            indent=2,
        )
    )
    if not result["archived_api_checks_all_pass"]:
        raise RuntimeError("API raw value trace failed")


if __name__ == "__main__":
    main()
