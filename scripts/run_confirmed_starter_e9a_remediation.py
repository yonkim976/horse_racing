"""Re-audit only the already sealed E9-A 60 reports, writing a new v9 folder."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from run_confirmed_starter_e9a import _raw_item, _runners, sha, write_jsonl_new, write_new

from horse_racing.analysis.confirmed_starter_e9a import Runner, extract_report
from horse_racing.analysis.confirmed_starter_e9a_remediation import remediate_report

ROOT = Path("data/experiments/confirmed_starter_e9a_20260913")
OLD = Path("data/experiments/confirmed_starter_e9a_20260913_v3")
OUTPUT = Path("data/experiments/confirmed_starter_e9a_20260913_v9")
POPULATION = ROOT / "population_manifest.json"
LABELS = ROOT / "reviewer_labels_v1.json"
INDEPENDENT_LOG = Path("data/logs/confirmed_starter_e9a_independent_review_20260913.json")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _id(row: dict[str, Any]) -> str:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _new_clear(row: dict[str, Any]) -> bool:
    return row["certainty"] == "clear" and row["event_type"] not in {
        "unresolved",
        "sand_overlap_only",
    }


def _verify_row(row: dict[str, Any], fields: dict[str, str | None], runners: list) -> None:
    source = fields.get(row["source_field"]) or ""
    if source[row["span_start"] : row["span_end"]] != row["span_text"]:
        raise RuntimeError("evidence bullet offsets do not match raw source")
    if "clause_start" in row:
        if source[row["clause_start"] : row["clause_end"]] != row["clause_text"]:
            raise RuntimeError("narrow clause offsets do not match raw source")
    if _new_clear(row):
        roster = {tuple(r.source_key) for r in runners}
        if row["horse_source_key"] is None or tuple(row["horse_source_key"]) not in roster:
            raise RuntimeError("clear source key missing from bounded race roster")
        if "clause_start" not in row:
            raise RuntimeError("clear row has no narrow supporting clause")


def _held_clause(row: dict[str, Any]) -> tuple[int, int, str]:
    """Show the rejected horse's local words, not the entire report bullet."""
    text = row["span_text"]
    number = row.get("quoted_horse_number")
    if number is None:
        return row["span_start"], row["span_end"], text
    marker = re.search(re.escape(CIRCLED[number - 1]), text)
    if marker is None:
        return row["span_start"], row["span_end"], text
    next_marker = re.search(r"[①-⑳]", text[marker.end() :])
    end = marker.end() + next_marker.start() if next_marker else len(text)
    stop = [
        position
        for position in (text.find(",", marker.start(), end), text.find(".", marker.start(), end))
        if position >= 0
    ]
    if stop:
        end = min(stop) + 1
    start = row["span_start"] + marker.start()
    return start, row["span_start"] + end, text[marker.start() : end]


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_group: dict[str, Counter] = defaultdict(Counter)
    by_type: dict[str, Counter] = defaultdict(Counter)
    by_role: dict[str, Counter] = defaultdict(Counter)
    by_status: Counter = Counter()
    clear = [row for row in rows if _new_clear(row)]
    for row in rows:
        status = row["certainty"]
        by_group[row["sample_group"]][status] += 1
        by_type[row["event_type"]][status] += 1
        by_role[row["role"]][status] += 1
        by_status[status] += 1
    keys = {(row["race_id"], tuple(row["horse_source_key"])) for row in clear}
    relationships = {
        (
            row["race_id"],
            row["event_type"],
            row["role"],
            tuple(row["horse_source_key"]),
            "start_gate" if row["event_type"] == "start_delay" else row.get("location_raw"),
        )
        for row in clear
    }
    return {
        "evidence_rows": len(rows),
        "clear_rows": len(clear),
        "clear_reports": len({row["report_id"] for row in clear}),
        "clear_race_horse_keys": len(keys),
        "provisional_unique_event_relationships": len(relationships),
        "group_status": {key: dict(value) for key, value in by_group.items()},
        "type_status": {key: dict(value) for key, value in by_type.items()},
        "role_status": {key: dict(value) for key, value in by_role.items()},
        "status": dict(by_status),
        "predictive_effect": "not_tested",
        "F_t_eligibility": "unverified",
        "count_contract": "evidence rows are not event counts; provisional relationship "
        "dedup uses race, event type, role, horse key and start_gate/location; "
        "not an approved feature value",
    }


def main() -> None:
    population = json.loads(POPULATION.read_text(encoding="utf-8"))
    selected = sorted(
        (row for row in population["population"] if row["sample_group"]),
        key=lambda row: row["race_id"],
    )
    if len(selected) != 60 or {row["sample_group"] for row in selected} != {
        "random",
        "cue_oversample",
    }:
        raise RuntimeError("sealed 60-report sample changed")
    if any(not "2025-01-01" <= row["race_date"] <= "2026-02-28" for row in selected):
        raise RuntimeError("sealed date scope changed")
    old_rows = [
        json.loads(line)
        for line in (OLD / "event_evidence.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    protected = [
        Path("data/horse_racing.sqlite3"),
        POPULATION,
        LABELS,
        INDEPENDENT_LOG,
        *sorted(OLD.glob("*")),
        *sorted({Path(row["source_local_path"]) for row in selected if row["source_local_path"]}),
    ]
    before = {str(path): sha(path) for path in protected if path.is_file()}
    if len([row for row in old_rows if _new_clear(row)]) != 197:
        raise RuntimeError("v3 clear count drifted")
    sources = [
        Path("src/horse_racing/analysis/confirmed_starter_e9a.py"),
        Path("src/horse_racing/analysis/confirmed_starter_e9a_remediation.py"),
        Path("scripts/run_confirmed_starter_e9a.py"),
        Path(__file__),
        Path("tests/test_confirmed_starter_e9a_remediation.py"),
    ]
    OUTPUT.mkdir(parents=True, exist_ok=False)
    # Seal the fixed input and code snapshot before the first source/roster read.
    write_new(
        OUTPUT / "execution_protocol.json",
        {
            "population_manifest_sha256": sha(POPULATION),
            "reviewer_labels_sha256": sha(LABELS),
            "old_event_evidence_sha256": sha(OLD / "event_evidence.jsonl"),
            "independent_review_log_sha256": sha(INDEPENDENT_LOG),
            "selected_report_ids": [row["report_id"] for row in selected],
            "date_upper_bound": "2026-02-28",
            "meet": 1,
            "read_only_date_bounded_roster_query": True,
            "outcome_or_next_race_query": False,
            "source_code_sha256": {str(path): sha(path) for path in sources},
            "protected_before_sha256": before,
        },
    )
    runners_by_race = _runners(selected)
    old_by_report: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in old_rows:
        old_by_report[row["report_id"]].append(row)
    evidence: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    contrasts: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for record in selected:
        report_id = int(record["report_id"])
        race_id = int(record["race_id"])
        path = Path(record["source_local_path"])
        if sha(path) != record["source_sha256"]:
            raise RuntimeError("sealed source hash mismatch")
        item = _raw_item(path, record["race_date"].replace("-", ""), record["race_number"])
        if item is None:
            raise RuntimeError("sealed report item missing")
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
        new = remediate_report(fields, runners_by_race.get(race_id, []), context=base)
        old = old_by_report[report_id]
        if len(new) < len(old):
            raise RuntimeError("old evidence row linkage lost")
        for row in new:
            _verify_row(row, fields, runners_by_race.get(race_id, []))
            evidence.append(row)
        clear_count = sum(_new_clear(row) for row in new)
        coverage.append(
            {
                "report_id": report_id,
                "race_id": race_id,
                "sample_group": record["sample_group"],
                "source_presence": "present",
                "source_readability": "readable_hash_verified",
                "race_roster": "bounded_read_only_query_verified",
                "identity_unknown_rows": sum(
                    row["certainty"] == "abstain" and row.get("horse_source_key") is None
                    for row in new
                ),
                "clear_rows": clear_count,
                "event_absence": "not_established" if clear_count == 0 else "not_applicable",
                "pit_availability": "unverified",
                "report_anchor_role": "report_level_presence_only_not_horse_role_approval",
            }
        )
        for old_row, new_row in zip(old, new[: len(old)], strict=True):
            if not _new_clear(old_row):
                continue
            decision = "retain" if _new_clear(new_row) else "hold"
            replacements = [
                candidate
                for candidate in new[len(old) :]
                if _new_clear(candidate)
                and candidate["event_type"] == old_row["event_type"]
                and candidate["source_field"] == old_row["source_field"]
                and candidate["span_start"] == old_row["span_start"]
            ]
            if decision == "hold" and replacements:
                decision = "modify"
            same_bullet_other_clear = [
                candidate
                for candidate in new
                if _new_clear(candidate)
                and candidate["event_type"] == old_row["event_type"]
                and candidate["source_field"] == old_row["source_field"]
                and candidate["span_start"] == old_row["span_start"]
                and candidate["horse_source_key"] != old_row["horse_source_key"]
            ]
            if decision == "hold" and same_bullet_other_clear:
                decision = "delete"
            clause_start, clause_end, clause_text = (
                (new_row["clause_start"], new_row["clause_end"], new_row["clause_text"])
                if "clause_start" in new_row
                else _held_clause(old_row)
            )
            source_text = fields[old_row["source_field"]] or ""
            if source_text[clause_start:clause_end] != clause_text:
                raise RuntimeError("ledger clause offsets do not match raw source")
            ledger.append(
                {
                    "old_evidence_id": _id(old_row),
                    "new_evidence_id": _id(new_row),
                    "replacement_evidence_ids": [_id(row) for row in replacements],
                    "report_id": report_id,
                    "race_id": race_id,
                    "sample_group": record["sample_group"],
                    "source_raw_sha256": record["source_sha256"],
                    "source_field": old_row["source_field"],
                    "old_span_start": old_row["span_start"],
                    "old_span_end": old_row["span_end"],
                    "clause_start": clause_start,
                    "clause_end": clause_end,
                    "clause_text": clause_text,
                    "event_type": old_row["event_type"],
                    "old_horse_source_key": old_row["horse_source_key"],
                    "new_horse_source_key": new_row["horse_source_key"],
                    "old_role": old_row["role"],
                    "new_role": new_row["role"],
                    "decision": decision,
                    "reason": (
                        "wrong_subject_existing_clear_in_same_bullet"
                        if decision == "delete"
                        else new_row.get("reason") or "local_predicate_verified"
                    ),
                    "reviewer_provenance": (
                        "same_agent_source_clause_and_roster_review_not_independent_gold"
                    ),
                }
            )
        for new_row in new[len(old) :]:
            if not _new_clear(new_row):
                continue
            ledger.append(
                {
                    "old_evidence_id": None,
                    "new_evidence_id": _id(new_row),
                    "replacement_evidence_ids": [],
                    "report_id": report_id,
                    "race_id": race_id,
                    "sample_group": record["sample_group"],
                    "source_raw_sha256": record["source_sha256"],
                    "source_field": new_row["source_field"],
                    "old_span_start": None,
                    "old_span_end": None,
                    "clause_start": new_row["clause_start"],
                    "clause_end": new_row["clause_end"],
                    "clause_text": new_row["clause_text"],
                    "event_type": new_row["event_type"],
                    "old_horse_source_key": None,
                    "new_horse_source_key": new_row["horse_source_key"],
                    "old_role": None,
                    "new_role": new_row["role"],
                    "decision": "new_clear",
                    "reason": "predicate_scoped_addition",
                    "reviewer_provenance": (
                        "same_agent_source_clause_and_roster_review_not_independent_gold"
                    ),
                }
            )
        if race_id in {3275, 3095, 277}:
            contrasts.append(
                {
                    "race_id": race_id,
                    "report_id": report_id,
                    "before_start_delay": [
                        row["horse_source_key"]
                        for row in old
                        if row["event_type"] == "start_delay" and _new_clear(row)
                    ],
                    "after_start_delay": [
                        row["horse_source_key"]
                        for row in new
                        if row["event_type"] == "start_delay" and _new_clear(row)
                    ],
                }
            )
    if len([row for row in ledger if row["old_evidence_id"]]) != 197:
        raise RuntimeError("old clear audit coverage is not 197/197")
    if {row["report_id"] for row in evidence} != {row["report_id"] for row in old_rows}:
        raise RuntimeError("sample report coverage changed")
    write_jsonl_new(OUTPUT / "event_evidence.jsonl", evidence)
    write_jsonl_new(OUTPUT / "role_review_ledger.jsonl", ledger)
    write_jsonl_new(OUTPUT / "report_coverage.jsonl", coverage)
    write_new(
        OUTPUT / "information_summary.json",
        {
            "before": _summary(old_rows),
            "after": _summary(evidence),
            "old_clear_audited": 197,
            "new_clear_reviewed": sum(_new_clear(row) for row in evidence),
            "scope": "same fixed 60 reports; retrospective source evidence only",
        },
    )
    probes = json.loads(INDEPENDENT_LOG.read_text(encoding="utf-8"))["synthetic_probes"]
    synthetic_runners = [
        Runner(1, "20250101", 1, 1, "H1", "가온"),
        Runner(1, "20250101", 1, 2, "H2", "나래"),
    ]
    synthetic = {}
    for name, probe in probes.items():
        text = probe["text"]
        fields = {"judgement": text, "addJudgement": None}
        previous = extract_report(fields, synthetic_runners, context={})
        current = remediate_report(fields, synthetic_runners, context={})
        synthetic[name] = {
            "text": text,
            "expected_contract": probe["expected_contract"],
            "before_clear": [
                [row["event_type"], row["role"], row["quoted_horse_number"]]
                for row in previous
                if _new_clear(row)
            ],
            "after_clear": [
                [row["event_type"], row["role"], row["quoted_horse_number"]]
                for row in current
                if _new_clear(row)
            ],
        }
    write_new(
        OUTPUT / "counterexample_contrasts.json",
        {
            "real": contrasts,
            "synthetic": synthetic,
        },
    )
    after = {str(path): sha(path) for path in protected if path.is_file()}
    if before != after:
        raise RuntimeError("protected input changed")
    write_new(
        OUTPUT / "artifact_manifest.json",
        {
            "protected_before_sha256": before,
            "protected_after_sha256": after,
            "source_code_sha256": {str(path): sha(path) for path in sources},
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
                "old_clear": 197,
                "new_clear": sum(_new_clear(row) for row in evidence),
                "ledger_rows": len(ledger),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
