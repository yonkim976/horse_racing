"""Review only the E9-A sealed 60-report sample; no external collection or model fit."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from horse_racing.analysis.confirmed_starter_e9a import Runner, extract_report
from horse_racing.analysis.features.sand_response import (
    sand_reaction_severity,
    sand_recovery_observation,
)

ROOT = Path("data/experiments/confirmed_starter_e9a_20260913")
OUTPUT = Path("data/experiments/confirmed_starter_e9a_20260913_v3")
DB = Path("data/horse_racing.sqlite3")
POPULATION = ROOT / "population_manifest.json"
LABELS = ROOT / "reviewer_labels_v1.json"
START = "2025-01-01"
END = "2026-02-28"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def write_jsonl_new(path: Path, rows: list[dict]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _raw_item(path: Path, race_date: str, race_number: int) -> dict | None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    response = payload.get("response", payload)
    body = response.get("body", {})
    container = body.get("items") or {}
    items = container.get("item", [])
    if isinstance(items, dict):
        items = [items]
    matches = [
        item
        for item in items
        if str(item.get("rcDate")) == race_date
        and int(item.get("rcNo", -1)) == race_number
        and str(item.get("meet")) in {"서울", "Seoul", "SEOUL"}
    ]
    if len(matches) > 1:
        raise RuntimeError("duplicate raw report item")
    return matches[0] if matches else None


def _runners(sample: list[dict]) -> dict[int, list[Runner]]:
    race_ids = sorted({int(row["race_id"]) for row in sample})
    marks = ",".join("?" for _ in race_ids)
    connection = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    rows = connection.execute(
        f"""
        SELECT r.id AS race_id, r.race_date_local AS race_date, r.race_number,
               re.horse_number, h.kra_horse_id, h.name_ko
        FROM race_entries AS re
        JOIN races AS r ON r.id=re.race_id
        JOIN racecourses AS rc ON rc.id=r.racecourse_id
        JOIN horses AS h ON h.id=re.horse_id
        WHERE rc.kra_meet_code=1
          AND r.race_date_local BETWEEN ? AND ?
          AND r.id IN ({marks})
        ORDER BY r.id, re.horse_number
        """,
        (START, END, *race_ids),
    ).fetchall()
    connection.close()
    by_race: dict[int, list[Runner]] = defaultdict(list)
    for row in rows:
        by_race[int(row["race_id"])].append(
            Runner(
                1,
                str(row["race_date"]).replace("-", ""),
                int(row["race_number"]),
                int(row["horse_number"]),
                str(row["kra_horse_id"]),
                str(row["name_ko"]),
            )
        )
    return by_race


def _anchor_span(fields: dict[str, str | None], anchor: str) -> dict | None:
    for field in ("judgement", "addJudgement"):
        text = fields.get(field) or ""
        index = text.find(anchor)
        if index >= 0:
            bullet_start = text.rfind("●", 0, index)
            bullet_end = text.find("●", index)
            return {
                "source_field": field,
                "anchor_start": index,
                "anchor_end": index + len(anchor),
                "review_span_text": text[
                    max(0, bullet_start) : bullet_end if bullet_end >= 0 else len(text)
                ].strip(),
            }
    return None


def main() -> None:
    population = json.loads(POPULATION.read_text(encoding="utf-8"))
    labels = json.loads(LABELS.read_text(encoding="utf-8"))["labels"]
    selected = sorted(
        (row for row in population["population"] if row["sample_group"]),
        key=lambda row: row["race_id"],
    )
    if len(selected) > 60 or set(labels) != {str(row["race_id"]) for row in selected}:
        raise RuntimeError("review labels do not match sealed sample")
    OUTPUT.mkdir(parents=True, exist_ok=False)
    protected = [
        DB,
        Path(population["h1"]["manifest_path"]),
        Path(population["h1"]["dataset_path"]),
        Path("data/experiments/model_runs.jsonl"),
        Path("data/experiments/confirmed_starter_e8b_20260913_attempt2/page_key_time_audit.json"),
        Path(
            "data/experiments/confirmed_starter_e8b_source_control_20260913_attempt2/control_comparison.json"
        ),
    ]
    before = {str(path): sha(path) for path in protected if path.is_file()}
    source_code = [
        Path("src/horse_racing/analysis/confirmed_starter_e9a.py"),
        Path("scripts/seal_confirmed_starter_e9a.py"),
        Path(__file__),
        Path("src/horse_racing/analysis/features/sand_response.py"),
    ]
    write_new(
        OUTPUT / "execution_protocol.json",
        {
            "population_manifest_sha256": sha(POPULATION),
            "reviewer_labels_sha256": sha(LABELS),
            "selected_report_ids": [row["report_id"] for row in selected],
            "date_upper_bound": END,
            "meet": 1,
            "read_only_db": True,
            "outcome_or_next_race_query": False,
            "source_code_sha256": {str(path): sha(path) for path in source_code},
            "protected_before_sha256": before,
        },
    )
    runners = _runners(selected)
    evidence: list[dict] = []
    review_rows: list[dict] = []
    discrepancies: list[dict] = []
    sand_horses: set[tuple[Any, ...]] = set()
    sand_recovery_horses: set[tuple[Any, ...]] = set()
    group_counts: dict[str, Counter] = defaultdict(Counter)
    for record in selected:
        report_id = int(record["report_id"])
        race_id = int(record["race_id"])
        group = str(record["sample_group"])
        source_path = Path(record["source_local_path"]) if record["source_local_path"] else None
        base = {
            "report_id": report_id,
            "race_id": race_id,
            "sample_group": group,
            "race_date": record["race_date"],
            "race_number": record["race_number"],
            "source_document_id": record["source_document_id"],
            "source_raw_sha256": record["source_sha256"],
            "source_local_path": str(source_path) if source_path else None,
            "source_requested_at_ms": record["source_requested_at_ms"],
            "source_retrieved_at_ms": record["source_retrieved_at_ms"],
            "report_observed_at_ms": record["report_observed_at_ms"],
            "source_published_at_ms": None,
            "source_effective_at_ms": None,
            "observation_mode": "retrospective_only",
            "availability_status": "availability_unverified",
        }
        row = {
            **base,
            "review_label": "explicit_e9_event",
            "review_event_type": labels[str(race_id)][0],
            "review_anchor": labels[str(race_id)][1],
            "review_provenance": "same_agent_source_review_not_independent_gold",
            "review_span": None,
            "extractor_anchor_matched": False,
            "coverage_state": None,
            "clear_events": 0,
            "ambiguous_events": 0,
            "abstain_events": 0,
            "identified_runners": len(runners.get(race_id, [])),
            "sand_adverse_horses": 0,
            "sand_recovery_horses": 0,
        }
        if (
            source_path is None
            or not source_path.is_file()
            or sha(source_path) != record["source_sha256"]
        ):
            row["coverage_state"] = "source_missing_or_hash_mismatch"
            group_counts[group]["source_missing"] += 1
            review_rows.append(row)
            discrepancies.append(
                {**base, "kind": "missing_source", "review_anchor": row["review_anchor"]}
            )
            continue
        item = _raw_item(source_path, record["race_date"].replace("-", ""), record["race_number"])
        if item is None:
            row["coverage_state"] = "report_item_missing"
            group_counts[group]["report_item_missing"] += 1
            review_rows.append(row)
            discrepancies.append(
                {**base, "kind": "report_item_missing", "review_anchor": row["review_anchor"]}
            )
            continue
        fields = {"judgement": item.get("judgement"), "addJudgement": item.get("addJudgement")}
        if not any(fields.values()):
            row["coverage_state"] = "report_text_missing"
            group_counts[group]["report_text_missing"] += 1
            review_rows.append(row)
            discrepancies.append(
                {**base, "kind": "report_text_missing", "review_anchor": row["review_anchor"]}
            )
            continue
        row["review_span"] = _anchor_span(fields, row["review_anchor"])
        if row["review_span"] is None:
            discrepancies.append(
                {
                    **base,
                    "kind": "manual_anchor_not_in_source",
                    "review_anchor": row["review_anchor"],
                }
            )
        rows = extract_report(fields, runners.get(race_id, []), context=base)
        evidence.extend(rows)
        row["clear_events"] = sum(
            e["certainty"] == "clear" and e["event_type"] != "sand_overlap_only" for e in rows
        )
        row["ambiguous_events"] = sum(e["certainty"] == "ambiguous" for e in rows)
        row["abstain_events"] = sum(e["certainty"] == "abstain" for e in rows)
        if row["review_span"]:
            anchor = row["review_anchor"]
            row["extractor_anchor_matched"] = any(
                e["event_type"] == row["review_event_type"]
                and anchor in e["span_text"]
                and e["certainty"] != "abstain"
                for e in rows
            )
        if not row["extractor_anchor_matched"]:
            discrepancies.append(
                {
                    **base,
                    "kind": "review_anchor_not_extracted",
                    "review_anchor": row["review_anchor"],
                    "review_event_type": row["review_event_type"],
                    "extractor_types": sorted({e["event_type"] for e in rows}),
                }
            )
        if row["clear_events"]:
            row["coverage_state"] = "clear_event_extracted"
            group_counts[group]["clear_report"] += 1
        elif row["ambiguous_events"] or row["abstain_events"]:
            row["coverage_state"] = "abstain_or_ambiguous_only"
            group_counts[group]["abstain_report"] += 1
        else:
            row["coverage_state"] = "no_rule_event"
            group_counts[group]["no_rule_event"] += 1
        text = " ".join(str(value) for value in fields.values() if value)
        for runner in runners.get(race_id, []):
            if sand_reaction_severity(text, runner.horse_name) > 0:
                sand_horses.add((race_id, *runner.source_key))
                row["sand_adverse_horses"] += 1
            if sand_recovery_observation(text, runner.horse_name) > 0:
                sand_recovery_horses.add((race_id, *runner.source_key))
                row["sand_recovery_horses"] += 1
        group_counts[group]["reviewed"] += 1
        group_counts[group]["identified_runners"] += row["identified_runners"]
        group_counts[group]["ambiguous_rows"] += row["ambiguous_events"]
        group_counts[group]["abstain_rows"] += row["abstain_events"]
        review_rows.append(row)
    clear = [
        e
        for e in evidence
        if e["certainty"] == "clear" and e["event_type"] not in {"sand_overlap_only", "unresolved"}
    ]
    e9_report_ids = {e["report_id"] for e in clear}
    e9_horses = {
        (e["race_id"], *e["horse_source_key"]) for e in clear if e["horse_source_key"] is not None
    }
    missing_anchor = [d for d in discrepancies if d["kind"] == "review_anchor_not_extracted"]
    summary = {
        "sample_reports": len(selected),
        "population_reports": population["population_count"],
        "sample_groups": {name: dict(counts) for name, counts in group_counts.items()},
        "evidence_rows": len(evidence),
        "clear_event_rows": len(clear),
        "ambiguous_event_rows": sum(e["certainty"] == "ambiguous" for e in evidence),
        "abstain_event_rows": sum(e["certainty"] == "abstain" for e in evidence),
        "extra_e9_reports": len(e9_report_ids),
        "extra_e9_horses": len(e9_horses),
        "existing_sand_adverse_horses": len(sand_horses),
        "existing_sand_recovery_horses": len(sand_recovery_horses),
        "e9_sand_horse_overlap": len(e9_horses & sand_horses),
        "e9_horses_without_sand_adverse": len(e9_horses - sand_horses),
        "manual_anchor_misses": len(missing_anchor),
        "manual_label_provenance": "same_agent_source_review_not_independent_gold",
        "predictive_effect": "not_tested",
        "F_t_eligibility": "unverified",
        "operating_model_status": "not_activated",
    }
    write_jsonl_new(OUTPUT / "event_evidence.jsonl", evidence)
    write_jsonl_new(OUTPUT / "report_review.jsonl", review_rows)
    write_new(OUTPUT / "review_disagreements.json", {"rows": discrepancies})
    write_new(OUTPUT / "information_summary.json", summary)
    after = {str(path): sha(path) for path in protected if path.is_file()}
    if after != before:
        raise RuntimeError("protected input changed during read-only review")
    manifest = {
        "preserved_before_sha256": before,
        "preserved_after_sha256": after,
        "source_code_sha256": {str(path): sha(path) for path in source_code},
        "output_sha256": {
            str(path.relative_to(OUTPUT)): sha(path)
            for path in OUTPUT.iterdir()
            if path.is_file() and path.name != "artifact_manifest.json"
        },
        "external_http_requests": 0,
        "model_fits": 0,
        "performance_evaluations": 0,
    }
    write_new(OUTPUT / "artifact_manifest.json", manifest)
    print(
        json.dumps(
            {
                "reports": len(selected),
                "clear_reports": len(e9_report_ids),
                "manual_anchor_misses": len(missing_anchor),
                "evidence_rows": len(evidence),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
