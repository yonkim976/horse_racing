"""Trace all 2025 section features and missing entries to immutable source evidence."""

import hashlib
import json
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from horse_racing.analysis.jeju_history_audit import (
    classify_missing,
    finite,
    historical_rows,
)
from scripts.build_jeju_context_features import (
    DATA,
    DB,
    H3,
    ROOT,
    _date,
    _history_rows,
    _sha,
    _source_rows,
)

CTX = ROOT / "data/research/jeju_native_context_features_v1_20260916"
V9 = ROOT / "data/research/jeju_native_experience_calibration_v9_20260916"
TRIAL = ROOT / "data/research/jeju_native_running_trial_links_20260915"
OUT = ROOT / "data/research/jeju_native_section_lineage_v10_20260916"
PARENTS = [DATA, H3, CTX, V9]


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n"
    )


def source_evidence(connection, ids):
    rows = []
    values = sorted(ids)
    for start in range(0, len(values), 500):
        batch = values[start : start + 500]
        query = (
            """SELECT e.id,e.horse_name,e.hr_no,s.id AS source_row_id,s.line_number,
          s.row_sha256,s.normalized_json,a.path,a.sha256 AS artifact_sha256
          FROM entry e JOIN source_row s ON s.id=e.source_row_id
          JOIN source_artifact a ON a.id=s.source_artifact_id WHERE e.id IN ("""
            + ",".join("?" for _ in batch)
            + ")"
        )
        for row in connection.execute(query, batch):
            r = dict(row)
            assert hashlib.sha256(r["normalized_json"].encode()).hexdigest() == r["row_sha256"]
            rows.append(r)
    return rows


def compute():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    entries = pl.read_parquet(DATA / "entries.parquet").filter(
        pl.col("event_date").dt.year() <= 2025
    )
    labels = pl.read_parquet(DATA / "labels.parquet")
    states = pl.read_parquet(DATA / "horse_states.parquet").filter(
        pl.col("event_date").dt.year() <= 2025
    )
    source = _source_rows(c)
    history = _history_rows(entries, labels, source, states)
    byhorse = defaultdict(list)
    for r in history:
        byhorse[str(r["horse_id"])].append(r)
    raw_byhorse = defaultdict(list)
    raw_byname = defaultdict(list)
    raw_byid = {}
    for row in c.execute("""SELECT e.id AS entry_id,e.hr_no AS horse_id,e.horse_name,
       e.finish_position,e.finish_time_ms,e.record_status,e.segment_quality,e.identity_status,
       e.source_row_id,v.event_date,v.event_type,v.distance_m
       FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_date<='20251231' """):
        r = dict(row)
        r["event_date"] = _date(r["event_date"])
        raw_byid[r["entry_id"]] = r
        raw_byhorse[str(r["horse_id"])].append(r)
        raw_byname[r["horse_name"]].append(r)
    allctx = pl.read_parquet(V9 / "audit_context.parquet")
    original = pl.read_parquet(V9 / "horse_predictions.parquet").filter(
        pl.col("model") == "HY_R_FORM"
    )
    selected = original.select("race_id", "horse_id", "boundary_tie", "selected", "official_top3")
    state = states.select(
        "entry_id", "starts_pre", "trial_count_pre", "trial_last_valid_time_ms_pre"
    )
    targets = allctx.join(selected, on=["race_id", "horse_id"], validate="1:1").join(
        state, on="entry_id", validate="1:1"
    )
    unlinked = []
    for line_no, line in enumerate(
        (TRIAL / "unresolved_trials_final.jsonl").read_text().splitlines(), 1
    ):
        r = json.loads(line)
        if r.get("trial_date", "99999999") <= "20251231":
            unlinked.append((line_no, r))
    audits = []
    excluded = []
    conflicts = []
    candidates = []
    trialevidence = []
    evidence_ids = set()
    for target in targets.sort("race_id", "horse_id").iter_rows(named=True):
        eid = target["entry_id"]
        cutoff = target["event_date"] - timedelta(days=2)
        prior = historical_rows(target, byhorse[target["horse_id"]])
        rawprior = historical_rows(target, raw_byhorse[target["horse_id"]])
        races = [r for r in rawprior if r["event_type"] == "race"]
        trials = [r for r in rawprior if r["event_type"] == "trial"]
        result = classify_missing(prior, races, target)
        record = dict(
            entry_id=eid,
            race_id=target["race_id"],
            horse_id=target["horse_id"],
            horse_name=raw_byid[eid]["horse_name"],
            event_date=target["event_date"],
            cutoff_date=cutoff,
            boundary_tie=target["boundary_tie"],
            in_v9_probability_population=not target["boundary_tie"],
            baseline_selected=target["selected"],
            official_top3=target["official_top3"],
            saved_starts_pre=target["starts_pre"],
            saved_trial_count_pre=target["trial_count_pre"],
            saved_trial_last_time_ms=target["trial_last_valid_time_ms_pre"],
            source_prior_races=len(races),
            source_prior_trials=len(trials),
            max_history_date=prior[-1]["event_date"] if prior else None,
            saved_early=float(target["historical_early_front_rate"])
            if finite(target["historical_early_front_rate"])
            else None,
            saved_closing=float(target["closing_speed_quality_mean_3"])
            if finite(target["closing_speed_quality_mean_3"])
            else None,
            history_entry_ids=[r["entry_id"] for r in prior],
            source_prior_race_ids=[r["entry_id"] for r in races],
            source_prior_trial_ids=[r["entry_id"] for r in trials],
            **result,
        )
        audits.append(record)
        if not result["section_missing"]:
            continue
        evidence_ids.add(eid)
        for r in races:
            excluded.append(dict(target_entry_id=eid, **r))
            evidence_ids.add(r["entry_id"])
        for r in trials:
            trialevidence.append(dict(target_entry_id=eid, cutoff_date=cutoff, **r))
            evidence_ids.add(r["entry_id"])
        for r in raw_byname[record["horse_name"]]:
            if (
                r["horse_id"] != target["horse_id"]
                and r["event_date"] <= cutoff
                and r["event_type"] == "race"
            ):
                conflicts.append(
                    dict(
                        target_entry_id=eid,
                        target_horse_id=target["horse_id"],
                        action="not_linked_by_name",
                        **r,
                    )
                )
        for line_no, r in unlinked:
            if _date(r["trial_date"]) > cutoff:
                continue
            matches = [
                o
                for o in r.get("official_candidates", [])
                if str(o.get("hrNo")) == target["horse_id"]
            ]
            if matches:
                candidates.append(
                    dict(
                        target_entry_id=eid,
                        target_horse_id=target["horse_id"],
                        target_horse_name=record["horse_name"],
                        source_line_number=line_no,
                        action="unresolved_not_used_as_feature",
                        record=r,
                    )
                )
    evidence = source_evidence(c, evidence_ids)
    emap = {r["id"]: r for r in evidence}
    for row in trialevidence:
        e = emap[row["entry_id"]]
        payload = json.loads(e["normalized_json"])["trial_result"]
        row.update(
            source_path=e["path"],
            source_row_sha256=e["row_sha256"],
            source_artifact_sha256=e["artifact_sha256"],
            s1f_ms=payload.get("s1f_ms"),
            g1f_ms=payload.get("g1f_ms"),
            g3f_ms=payload.get("g3f_ms"),
            passing_order_raw=payload.get("passing_order_raw"),
            judgement=payload.get("judgement"),
            inspection_reason=payload.get("inspection_reason"),
        )
    c.close()
    return audits, excluded, conflicts, candidates, trialevidence, evidence


def main():
    OUT.mkdir(exist_ok=True)
    assert not (OUT / "protocol.json").exists(), "Refuse overwrite"
    files = [
        TRIAL / "unresolved_trials_final.jsonl",
        TRIAL / "official_response_cache.jsonl",
        TRIAL / "official_request_manifest.jsonl",
    ]
    save(
        "protocol.json",
        dict(
            version="section_lineage_audit_v10",
            created_at=datetime.now(UTC).isoformat(),
            parent_manifests={p.name: _sha(p / "manifest.json") for p in PARENTS},
            database_sha256=_sha(DB),
            source_files={str(p.relative_to(ROOT)): _sha(p) for p in files},
            scope="Reconstruct two section features for all6953 evaluation rows2025; audit all296 missing, "  # noqa: E501
            "report292 nonboundary probability rows separately from4 boundary rows.",
            attribution="T-2 cutoff, same official horse ID; compare sealed starter history with all DB "  # noqa: E501
            "race rows, nonstarters, name conflicts, linked trials and unresolved candidates.",
            exclusion="Nonstart codes93/94/95 are not performance history. Same-name different-ID "
            "horses are not linked. Trial/name conflicts remain unresolved absent corroboration.",
            mutation="Read-only sources. No model fitting or prediction changes. No substitution of "  # noqa: E501
            "trial section times for race section features. Only confirmed mismatches warrant fixes.",  # noqa: E501
            limits="No earlier row in available sources is not a universal proof of lifetime debut. "  # noqa: E501
            "Archived identities/publication times may be retrospective. No2026 model evaluation.",
        ),
    )
    audits, excluded, conflicts, candidates, trials, evidence = compute()
    allrows = pl.DataFrame(audits, infer_schema_length=None)
    missing = allrows.filter(pl.col("section_missing"))
    mainrows = missing.filter(pl.col("in_v9_probability_population"))
    allrows.write_parquet(OUT / "all_entry_audit.parquet")
    missing.write_parquet(OUT / "missing_entry_audit.parquet")
    pl.DataFrame(trials, infer_schema_length=None).write_parquet(OUT / "trial_evidence.parquet")
    save("excluded_prior_races.json", excluded)
    save("same_name_other_id.json", conflicts)
    save("unresolved_trial_candidates.json", candidates)
    with (OUT / "source_row_evidence.jsonl").open("w") as f:
        for r in evidence:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    hashes = {r["path"]: r["artifact_sha256"] for r in evidence}
    for candidate in candidates:
        r = candidate["record"]
        path = ROOT / r["text_source"]
        assert _sha(path) == r["text_sha256"]
        hashes[r["text_source"]] = r["text_sha256"]
    for name, digest in hashes.items():
        assert _sha(ROOT / name) == digest, name
    save("source_hashes.json", hashes)
    targetids = set(mainrows["entry_id"])
    maintrials = [t for t in trials if t["target_entry_id"] in targetids]
    readiness = {
        key: len({r["target_entry_id"] for r in maintrials if finite(r.get(key)) and r[key] > 0})
        for key in ["finish_time_ms", "s1f_ms", "g1f_ms", "g3f_ms"]
    }
    summary = dict(
        evaluation_rows=len(allrows),
        feature_reconstruction_mismatches=int((~allrows["features_match"]).sum()),
        missing_all=len(missing),
        missing_probability_rows=len(mainrows),
        missing_boundary_rows=len(missing) - len(mainrows),
        missing_unique_horses=mainrows["horse_id"].n_unique(),
        reasons=dict(Counter(mainrows["reason"])),
        missing_with_prior_starter_history=int((mainrows["history_count"] > 0).sum()),
        nonstarter_prior_rows=sum(r["target_entry_id"] in targetids for r in excluded),
        name_conflict_targets=len(
            {r["target_entry_id"] for r in conflicts if r["target_entry_id"] in targetids}
        ),
        prior_trial_targets=int((mainrows["source_prior_trials"] > 0).sum()),
        no_linked_trial_targets=int((mainrows["source_prior_trials"] == 0).sum()),
        prior_trial_evidence_rows=len(maintrials),
        trial_positive_field_targets=readiness,
        saved_trial_count_mismatches=int(
            (mainrows["source_prior_trials"] != mainrows["saved_trial_count_pre"]).sum()
        ),
        unresolved_trial_candidate_targets=len(
            {r["target_entry_id"] for r in candidates if r["target_entry_id"] in targetids}
        ),
        source_rows_verified=len(evidence),
        source_files_verified=len(hashes),
        model_fits=0,
        prediction_changes=0,
        confirmed_feature_errors=0
        if allrows["features_match"].all()
        else int((~allrows["features_match"]).sum()),
        next_direction="Separate race-history absence from trial-history availability. Evaluate richer "  # noqa: E501
        "strictly prior trial signals as a new fixed experiment; do not impute race sections.",
    )
    save("summary.json", summary)
    (OUT / "reproduce").mkdir(exist_ok=True)
    for file in [
        Path(__file__),
        ROOT / "src/horse_racing/analysis/jeju_history_audit.py",
        ROOT / "tests/test_jeju_history_audit.py",
        ROOT / "scripts/build_jeju_context_features.py",
        ROOT / "src/horse_racing/analysis/jeju_context_features.py",
    ]:
        shutil.copy2(file, OUT / "reproduce" / file.name)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
