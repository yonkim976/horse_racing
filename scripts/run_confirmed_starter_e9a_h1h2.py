"""Sealed H1/H2 recheck of the fixed E9-A 60-report sample only."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from run_confirmed_starter_e9a import _raw_item, _runners, sha, write_jsonl_new, write_new

from horse_racing.analysis.confirmed_starter_e9a import Runner
from horse_racing.analysis.confirmed_starter_e9a_h1h2 import (
    conflicted_numbers,
    extract_report_h1h2,
)
from horse_racing.analysis.confirmed_starter_e9a_remediation import remediate_report

ROOT = Path("data/experiments/confirmed_starter_e9a_20260913")
V9 = Path("data/experiments/confirmed_starter_e9a_20260913_v9")
OUTPUT = Path("data/experiments/confirmed_starter_e9a_h1h2_20260913_v2")
POPULATION = ROOT / "population_manifest.json"
LABELS = ROOT / "reviewer_labels_v1.json"
INDEPENDENT_LOG = Path(
    "data/logs/confirmed_starter_e9a_remediation_independent_review_20260913.json"
)


def _id(row: dict[str, Any]) -> str:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row["certainty"] for row in rows)
    clear = [row for row in rows if row["certainty"] == "clear"]
    groups: dict[str, Counter] = defaultdict(Counter)
    types: dict[str, Counter] = defaultdict(Counter)
    roles: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        groups[row["sample_group"]][row["certainty"]] += 1
        types[row["event_type"]][row["certainty"]] += 1
        roles[row["role"]][row["certainty"]] += 1
    keys = {(row["race_id"], tuple(row["horse_source_key"])) for row in clear}
    relationships = {
        (
            row["race_id"],
            row["event_type"],
            row["role"],
            tuple(row["horse_source_key"]),
            tuple(row.get("victim_horse_source_key") or []),
            "start_gate" if row["event_type"] == "start_delay" else row.get("location_raw"),
        )
        for row in clear
    }
    return {
        "evidence_rows": len(rows),
        "status": dict(counts),
        "clear_reports": len({row["report_id"] for row in clear}),
        "clear_race_horse_keys": len(keys),
        "provisional_unique_event_relationships": len(relationships),
        "group_status": {key: dict(value) for key, value in groups.items()},
        "type_status": {key: dict(value) for key, value in types.items()},
        "role_status": {key: dict(value) for key, value in roles.items()},
        "count_limit": "evidence rows differ from event relationships and horse keys; "
        "this provisional dedup is not a feature count",
    }


def _verify(row: dict[str, Any], fields: dict[str, str | None], runners: list[Runner]) -> None:
    source = fields.get(row["source_field"]) or ""
    if source[row["span_start"] : row["span_end"]] != row["span_text"]:
        raise RuntimeError("bullet span differs from raw source")
    if row["certainty"] == "clear":
        if tuple(row["horse_source_key"] or []) not in {tuple(r.source_key) for r in runners}:
            raise RuntimeError("clear source key absent from bounded roster")
        if source[row["clause_start"] : row["clause_end"]] != row["clause_text"]:
            raise RuntimeError("clear clause differs from raw source")
    if row["certainty"] == "clear" and row["role"] == "actor":
        if (
            source[row["relation_span_start"] : row["relation_span_end"]]
            != row["relation_span_text"]
        ):
            raise RuntimeError("actor relation span differs from raw source")
        for prefix in ("actor_action_span", "victim_observation_span"):
            start, end = row[f"{prefix}_start"], row[f"{prefix}_end"]
            if not 0 <= start < end <= len(source):
                raise RuntimeError("actor/victim subspan is out of raw source")
        if tuple(row["victim_horse_source_key"]) not in {tuple(r.source_key) for r in runners}:
            raise RuntimeError("victim source key absent from bounded roster")


def _semantic(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "source_field",
        "span_start",
        "span_end",
        "span_text",
        "event_type",
        "role",
        "certainty",
        "horse_source_key",
        "quoted_horse_number",
        "quoted_horse_name",
        "clause_start",
        "clause_end",
        "clause_text",
        "reason",
    )
    return {key: row.get(key) for key in keys}


def main() -> None:
    population = json.loads(POPULATION.read_text(encoding="utf-8"))
    selected = sorted(
        (row for row in population["population"] if row["sample_group"]),
        key=lambda row: row["race_id"],
    )
    if len(selected) != 60 or any(
        not "2025-01-01" <= row["race_date"] <= "2026-02-28" for row in selected
    ):
        raise RuntimeError("sealed sample scope changed")
    v9_rows = [
        json.loads(line)
        for line in (V9 / "event_evidence.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if (
        len(v9_rows) != 375
        or sum(row["certainty"] == "clear" and row["role"] == "actor" for row in v9_rows) != 37
    ):
        raise RuntimeError("v9 evidence/actor coverage drifted")
    protected = [
        Path("data/horse_racing.sqlite3"),
        POPULATION,
        LABELS,
        INDEPENDENT_LOG,
        Path("data/experiments/model_runs.jsonl"),
        Path("src/horse_racing/analysis/confirmed_starter_e9a.py"),
        Path("src/horse_racing/analysis/confirmed_starter_e9a_remediation.py"),
        Path("scripts/run_confirmed_starter_e9a.py"),
        Path("scripts/run_confirmed_starter_e9a_remediation.py"),
        Path("tests/test_confirmed_starter_e9a.py"),
        Path("tests/test_confirmed_starter_e9a_remediation.py"),
        Path("docs/CONFIRMED_STARTER_E9A_REMEDIATION_2026-09-13.md"),
        Path(population["h1"]["manifest_path"]),
        Path(population["h1"]["dataset_path"]),
        Path("data/experiments/confirmed_starter_e8b_20260913_attempt2/page_key_time_audit.json"),
        Path(
            "data/experiments/confirmed_starter_e8b_source_control_20260913_attempt2/"
            "control_comparison.json"
        ),
        *sorted(Path("data/experiments/confirmed_starter_e9a_20260913_v3").glob("*")),
        *sorted(Path("data/experiments/confirmed_starter_e9a_20260913_v4").glob("*")),
        *sorted(Path("data/experiments/confirmed_starter_e9a_20260913_v5").glob("*")),
        *sorted(Path("data/experiments/confirmed_starter_e9a_20260913_v6").glob("*")),
        *sorted(Path("data/experiments/confirmed_starter_e9a_20260913_v7").glob("*")),
        *sorted(Path("data/experiments/confirmed_starter_e9a_20260913_v8").glob("*")),
        *sorted(V9.glob("*")),
        *sorted(Path("data/experiments/confirmed_starter_e9a_h1h2_20260913_v1").glob("*")),
        *sorted({Path(row["source_local_path"]) for row in selected if row["source_local_path"]}),
    ]
    protected_hash = {str(path): sha(path) for path in protected if path.is_file()}
    sources = [
        Path("src/horse_racing/analysis/confirmed_starter_e9a.py"),
        Path("src/horse_racing/analysis/confirmed_starter_e9a_remediation.py"),
        Path("src/horse_racing/analysis/confirmed_starter_e9a_h1h2.py"),
        Path("scripts/run_confirmed_starter_e9a.py"),
        Path(__file__),
        Path("tests/test_confirmed_starter_e9a_remediation.py"),
        Path("tests/test_confirmed_starter_e9a_h1h2.py"),
    ]
    source_hash = {str(path): sha(path) for path in sources}
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_new(
        OUTPUT / "execution_protocol.json",
        {
            "date_range": ["2025-01-01", "2026-02-28"],
            "meet": 1,
            "selected_report_ids": [row["report_id"] for row in selected],
            "population_manifest_sha256": sha(POPULATION),
            "reviewer_labels_sha256": sha(LABELS),
            "v9_evidence_sha256": sha(V9 / "event_evidence.jsonl"),
            "independent_log_sha256": sha(INDEPENDENT_LOG),
            "source_code_sha256": source_hash,
            "protected_before_sha256": protected_hash,
            "read_only_sql_date_bounded_roster": True,
            "external_http_or_outcome_query": False,
        },
    )
    roster = _runners(selected)
    v9_by_report: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in v9_rows:
        v9_by_report[row["report_id"]].append(row)
    evidence: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    actor_review: list[dict[str, Any]] = []
    report_coverage: list[dict[str, Any]] = []
    for record in selected:
        report_id = int(record["report_id"])
        race_id = int(record["race_id"])
        path = Path(record["source_local_path"])
        if sha(path) != record["source_sha256"]:
            raise RuntimeError("sealed raw source hash changed")
        item = _raw_item(path, record["race_date"].replace("-", ""), record["race_number"])
        if item is None:
            raise RuntimeError("sealed raw report item missing")
        fields = {"judgement": item.get("judgement"), "addJudgement": item.get("addJudgement")}
        base = {
            "report_id": report_id,
            "race_id": race_id,
            "sample_group": record["sample_group"],
            "race_date": record["race_date"],
            "race_number": record["race_number"],
            "source_document_id": record["source_document_id"],
            "source_raw_sha256": record["source_sha256"],
            "source_local_path": str(path),
            "source_requested_at_ms": record["source_requested_at_ms"],
            "source_retrieved_at_ms": record["source_retrieved_at_ms"],
            "report_observed_at_ms": record["report_observed_at_ms"],
            "source_published_at_ms": None,
            "source_effective_at_ms": None,
            "observation_mode": "retrospective_only",
            "availability_status": "availability_unverified",
        }
        old = v9_by_report[report_id]
        new = extract_report_h1h2(fields, roster[race_id], context=base)
        if len(old) != len(new):
            raise RuntimeError("actual sample evidence row coverage changed")
        if conflicted_numbers(roster[race_id]):
            raise RuntimeError("actual sample roster has unexpected identity conflict")
        for old_row, new_row in zip(old, new, strict=True):
            _verify(new_row, fields, roster[race_id])
            if _semantic(old_row) != _semantic(new_row):
                if old_row["role"] != "actor" or old_row["certainty"] != "clear":
                    raise RuntimeError("non-actor v9 semantics changed")
            decision = (
                "retain_with_relation"
                if new_row["role"] == "actor" and new_row["certainty"] == "clear"
                else "hold_actor"
                if old_row["role"] == "actor" and new_row["certainty"] != "clear"
                else "retain_unchanged"
            )
            ledger_row = {
                "old_evidence_id": _id(old_row),
                "new_evidence_id": _id(new_row),
                "report_id": report_id,
                "race_id": race_id,
                "source_raw_sha256": record["source_sha256"],
                "source_field": old_row["source_field"],
                "event_type": old_row["event_type"],
                "old_role": old_row["role"],
                "new_role": new_row["role"],
                "old_horse_source_key": old_row["horse_source_key"],
                "new_horse_source_key": new_row["horse_source_key"],
                "clause_start": new_row.get("clause_start"),
                "clause_end": new_row.get("clause_end"),
                "relation_type": new_row.get("relation_type"),
                "relation_span_start": new_row.get("relation_span_start"),
                "relation_span_end": new_row.get("relation_span_end"),
                "victim_horse_source_key": new_row.get("victim_horse_source_key"),
                "decision": decision,
                "reason": new_row.get("reason") or "same_event_relationship_verified",
                "reviewer_provenance": "same_agent_source_relation_review_not_independent_gold",
            }
            lineage.append(ledger_row)
            if old_row["certainty"] == "clear" and old_row["role"] == "actor":
                actor_review.append(
                    {
                        **ledger_row,
                        "actor_action_span_start": new_row.get("actor_action_span_start"),
                        "actor_action_span_end": new_row.get("actor_action_span_end"),
                        "victim_observation_span_start": new_row.get(
                            "victim_observation_span_start"
                        ),
                        "victim_observation_span_end": new_row.get("victim_observation_span_end"),
                        "relation_span_text": new_row.get("relation_span_text"),
                    }
                )
            evidence.append(new_row)
        report_coverage.append(
            {
                "report_id": report_id,
                "race_id": race_id,
                "source_presence": "present_hash_verified",
                "roster": "unique_number_and_source_id_date_bounded_read_only",
                "v9_evidence_rows": len(old),
                "new_evidence_rows": len(new),
                "pit_availability": "unverified",
            }
        )
    if len(evidence) != 375 or len(lineage) != 375 or len(actor_review) != 37:
        raise RuntimeError("final row/actor audit coverage mismatch")
    if any(row["decision"] != "retain_with_relation" for row in actor_review):
        raise RuntimeError("actor relationship lacks reviewed support")
    log = json.loads(INDEPENDENT_LOG.read_text(encoding="utf-8"))
    probes = {}
    for name, probe in log["new_counterexamples"].items():
        runners = [Runner(**row) for row in probe["roster"]]
        fields = {"judgement": probe["text"], "addJudgement": None}
        before = remediate_report(fields, runners, context={})
        after = extract_report_h1h2(fields, runners, context={})
        probes[name] = {
            "text": probe["text"],
            "roster": probe["roster"],
            "before_clear": [
                [row["event_type"], row["role"], row["quoted_horse_number"]]
                for row in before
                if row["certainty"] == "clear"
            ],
            "after_clear": [
                [row["event_type"], row["role"], row["quoted_horse_number"]]
                for row in after
                if row["certainty"] == "clear"
            ],
            "after_holds_or_abstains": [
                [row["event_type"], row["quoted_horse_number"], row["certainty"], row.get("reason")]
                for row in after
                if row["certainty"] in {"hold", "abstain"}
            ],
        }
    real_1698 = [
        row
        for row in actor_review
        if row["race_id"] == 1698
        and row["old_horse_source_key"] is not None
        and row["old_horse_source_key"][3] == 7
    ]
    write_jsonl_new(OUTPUT / "event_evidence.jsonl", evidence)
    write_jsonl_new(OUTPUT / "lineage_ledger.jsonl", lineage)
    write_jsonl_new(OUTPUT / "actor_relationship_review.jsonl", actor_review)
    write_jsonl_new(OUTPUT / "report_coverage.jsonl", report_coverage)
    write_new(
        OUTPUT / "counterexample_contrasts.json",
        {
            "synthetic": probes,
            "real_1698_actor": real_1698,
        },
    )
    write_new(
        OUTPUT / "information_summary.json",
        {
            "v9": _summary(v9_rows),
            "h1h2": _summary(evidence),
            "actor_rows_reviewed": len(actor_review),
            "actual_roster_identity_conflicts": 0,
            "predictive_effect": "not_tested",
            "F_t_eligibility": "unverified",
        },
    )
    protected_after = {str(path): sha(path) for path in protected if path.is_file()}
    if protected_after != protected_hash:
        raise RuntimeError("protected input changed during H1/H2 read-only review")
    if {str(path): sha(path) for path in sources} != source_hash:
        raise RuntimeError("H1/H2 source or test changed after protocol seal")
    write_new(
        OUTPUT / "artifact_manifest.json",
        {
            "protected_before_sha256": protected_hash,
            "protected_after_sha256": protected_after,
            "source_code_sha256": source_hash,
            "output_sha256": {
                str(path.relative_to(OUTPUT)): sha(path)
                for path in OUTPUT.iterdir()
                if path.is_file() and path.name != "artifact_manifest.json"
            },
            "external_http_requests": 0,
            "model_fits": 0,
            "performance_evaluations": 0,
        },
    )
    print(
        json.dumps(
            {
                "evidence_rows": len(evidence),
                "clear_rows": sum(row["certainty"] == "clear" for row in evidence),
                "actor_reviewed": len(actor_review),
                "lineage_rows": len(lineage),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
