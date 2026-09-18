"""Verify section audit outputs against frozen inputs and raw source evidence."""

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict

import polars as pl

from scripts.audit_jeju_section_lineage import (
    CTX,
    DB,
    OUT,
    PARENTS,
    ROOT,
    TRIAL,
    V9,
    _date,
    _sha,
    save,
)


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    parents = {}
    assert _sha(DB) == protocol["database_sha256"]
    for folder in PARENTS:
        assert _sha(folder / "manifest.json") == protocol["parent_manifests"][folder.name]
        m = json.loads((folder / "manifest.json").read_text())
        hashes = {k: v["sha256"] for k, v in m["files"].items()} if "files" in m else m
        for name, digest in hashes.items():
            assert _sha(folder / name) == digest, (folder.name, name)
        parents[folder.name] = len(hashes)
    for name, digest in protocol["source_files"].items():
        assert _sha(ROOT / name) == digest
    source_hashes = json.loads((OUT / "source_hashes.json").read_text())
    for name, digest in source_hashes.items():
        assert _sha(ROOT / name) == digest
    own = 0
    if (OUT / "manifest.json").exists():
        for name, digest in json.loads((OUT / "manifest.json").read_text()).items():
            assert _sha(OUT / name) == digest, name
            own += 1
    allrows = pl.read_parquet(OUT / "all_entry_audit.parquet")
    missing = pl.read_parquet(OUT / "missing_entry_audit.parquet")
    expected = pl.read_parquet(V9 / "audit_context.parquet").sort("entry_id")
    assert allrows["entry_id"].n_unique() == len(allrows) == len(expected) == 6953
    assert allrows["features_match"].all()
    actual = allrows.sort("entry_id")
    assert actual["entry_id"].to_list() == expected["entry_id"].to_list()
    assert actual["section_missing"].to_list() == expected["section_missing"].to_list()
    assert missing.sort("entry_id").equals(actual.filter(pl.col("section_missing")))
    m = missing.filter(pl.col("in_v9_probability_population"))
    assert len(m) == 292 and len(missing) == 296 and m["horse_id"].n_unique() == 292
    assert (missing["history_count"] == 0).all() and (missing["saved_starts_pre"] == 0).all()
    assert (missing["source_prior_trials"] == missing["saved_trial_count_pre"]).all()
    assert allrows.filter(pl.col("max_history_date") > pl.col("cutoff_date")).is_empty()
    lineage = pl.read_parquet(CTX / "lineage.parquet").select(
        "entry_id", pl.col("history_starts").alias("original_history_count")
    )
    assert (
        allrows.join(lineage, on="entry_id")
        .select((pl.col("history_count") == pl.col("original_history_count")).all())
        .item()
    )
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    raw_byhorse = defaultdict(list)
    for row in c.execute("""select e.id,e.hr_no,e.finish_position,e.finish_time_ms,e.horse_name,
            v.event_date,v.event_type from entry e join event v on v.id=e.event_id
            where v.event_date<='20251231' """):
        r = dict(row)
        r["event_date"] = _date(r["event_date"])
        raw_byhorse[r["hr_no"]].append(r)
    for row in missing.iter_rows(named=True):
        prior = [r for r in raw_byhorse[row["horse_id"]] if r["event_date"] <= row["cutoff_date"]]
        races = [r for r in prior if r["event_type"] == "race"]
        trials = [r for r in prior if r["event_type"] == "trial"]
        assert set(row["source_prior_race_ids"]) == {r["id"] for r in races}
        assert set(row["source_prior_trial_ids"]) == {r["id"] for r in trials}
        assert all(r["finish_position"] in {93, 94, 95} for r in races)
        assert not any(
            r["event_type"] == "race" and row["cutoff_date"] < r["event_date"] < row["event_date"]
            for r in raw_byhorse[row["horse_id"]]
        )
    # Compare retained source rows with DB hashes and original JSONL lines when present.
    evidence = [
        json.loads(line) for line in (OUT / "source_row_evidence.jsonl").read_text().splitlines()
    ]
    lines = {}
    verified_lines = 0
    emap = {r["id"]: r for r in evidence}
    assert len(emap) == len(evidence)
    for e in evidence:
        assert hashlib.sha256(e["normalized_json"].encode()).hexdigest() == e["row_sha256"]
        dbrow = c.execute(
            "select normalized_json,row_sha256 from source_row where id=?", (e["source_row_id"],)
        ).fetchone()
        assert (
            dbrow["normalized_json"] == e["normalized_json"]
            and dbrow["row_sha256"] == e["row_sha256"]
        )
        if e["line_number"] is not None:
            if e["path"] not in lines:
                lines[e["path"]] = (ROOT / e["path"]).read_text().splitlines()
            assert json.loads(lines[e["path"]][e["line_number"] - 1]) == json.loads(
                e["normalized_json"]
            )
            verified_lines += 1
    trial = pl.read_parquet(OUT / "trial_evidence.parquet")
    targetmap = {r["entry_id"]: r for r in missing.iter_rows(named=True)}
    for row in trial.iter_rows(named=True):
        target = targetmap[row["target_entry_id"]]
        assert row["event_date"] <= target["cutoff_date"] and row["horse_id"] == target["horse_id"]
        data = json.loads(emap[row["entry_id"]]["normalized_json"])["trial_result"]
        for key in [
            "s1f_ms",
            "g1f_ms",
            "g3f_ms",
            "passing_order_raw",
            "judgement",
            "inspection_reason",
        ]:
            assert row[key] == data.get(key)
    conflicts = json.loads((OUT / "same_name_other_id.json").read_text())
    assert len({r["target_entry_id"] for r in conflicts}) == 1
    assert all(r["horse_id"] != r["target_horse_id"] for r in conflicts)
    candidates = json.loads((OUT / "unresolved_trial_candidates.json").read_text())
    unresolved = (TRIAL / "unresolved_trials_final.jsonl").read_text().splitlines()
    cache = {}
    for line in (TRIAL / "official_response_cache.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["date"] <= "20251231":
            cache[(row["date"], row["race_number"])] = row
    for candidate in candidates:
        r = candidate["record"]
        target = targetmap[candidate["target_entry_id"]]
        assert json.loads(unresolved[candidate["source_line_number"] - 1]) == r
        assert _date(r["trial_date"]) <= target["cutoff_date"]
        source = cache[(r["trial_date"], r["trial_race_number"])]
        assert source["request"]["response_sha256"] == r["official_response_sha256"]
        assert any(
            o["hrNo"] == candidate["target_horse_id"] and o["horse_number"] == r["horse_number"]
            for o in source["official_rows"]
        )
        official = next(
            o
            for o in source["official_rows"]
            if o["hrNo"] == candidate["target_horse_id"] and o["horse_number"] == r["horse_number"]
        )
        for key in ["age", "sex", "trainer_name", "body_weight_kg"]:
            assert official[key] == r["trial_result"][key]
        assert official["horse_name"] != r["trial_result"]["horse_name"]
        assert candidate["action"] == "unresolved_not_used_as_feature"
        assert target["source_prior_trials"] == 0
    summary = json.loads((OUT / "summary.json").read_text())
    assert summary["reasons"] == dict(Counter(m["reason"]))
    assert summary["source_rows_verified"] == len(evidence)
    assert (
        summary["prior_trial_evidence_rows"]
        == trial.filter(pl.col("target_entry_id").is_in(m["entry_id"].to_list())).height
    )
    assert (
        summary["model_fits"]
        == summary["prediction_changes"]
        == summary["confirmed_feature_errors"]
        == 0
    )
    c.close()
    result = dict(
        passed=True,
        manifest_files_checked=own,
        parent_files_checked=parents,
        source_file_hashes_checked=len(source_hashes),
        source_rows_checked=len(evidence),
        original_jsonl_rows_compared=verified_lines,
        evaluation_rows=6953,
        missing_rows_checked=296,
        probability_missing_rows=292,
        trial_rows_checked=len(trial),
        unresolved_candidates_checked=len(candidates),
        future_history_rows=0,
        model_fits=0,
        prediction_changes=0,
    )
    save("verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
