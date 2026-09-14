"""Seal and render a blind E9-B annotation package; never run the extractor."""

from __future__ import annotations

import hashlib
import json
import random
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

POPULATION = Path("data/experiments/confirmed_starter_e9a_20260913/population_manifest.json")
FREEZE = Path("data/experiments/confirmed_starter_e9a_h1h2_20260913_v2/artifact_manifest.json")
OUTPUT = Path("data/experiments/confirmed_starter_e9b_blind_20260913_v1")
DB = Path("data/horse_racing.sqlite3")
EXPECTED_FREEZE_SHA = "f19f5b77cb19b5f113585b4ac83497b7ec4579c8652ef2c7c5a72931daad973e"
SEED = 20260914
DATE_START = "2025-01-01"
DATE_END = "2026-02-28"
_E9A_ROOT = Path("data/experiments")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_population(population: dict[str, Any]) -> list[dict[str, Any]]:
    rows = population["population"]
    if population["population_count"] != 1200 or len(rows) != 1200:
        raise RuntimeError("sealed population is not 1200 rows")
    if population["scope"] != {
        "date_end": DATE_END,
        "date_start": DATE_START,
        "meet": 1,
        "read_only_db": True,
    }:
        raise RuntimeError("sealed population scope changed")
    keys = [(int(row["race_id"]), int(row["report_id"])) for row in rows]
    if len(set(keys)) != len(keys):
        raise RuntimeError("duplicate race/report keys in population")
    if any(not DATE_START <= row["race_date"] <= DATE_END for row in rows):
        raise RuntimeError("population row outside allowed dates")
    return rows


def _recorded_exposure_ids() -> tuple[set[int], list[str]]:
    """Only explicit E9-A detail/output files count; metadata census does not."""
    ids: set[int] = set()
    checked: list[str] = []
    for folder in sorted(_E9A_ROOT.glob("confirmed_starter_e9a*")):
        for path in sorted(folder.glob("event_evidence.jsonl")):
            checked.append(str(path))
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    ids.add(int(json.loads(line)["report_id"]))
    return ids, checked


def select_records(
    population: list[dict[str, Any]], recorded_exposure: set[int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    sealed_sixty = {int(row["report_id"]) for row in population if row["sample_group"]}
    if len(sealed_sixty) != 60:
        raise RuntimeError("the original detailed sample is not 60 reports")
    additional = recorded_exposure - sealed_sixty
    excluded = [
        {"report_id": report_id, "reason": "e9a_sealed_detailed_sample"}
        for report_id in sorted(sealed_sixty)
    ] + [
        {"report_id": report_id, "reason": "other_recorded_e9a_detailed_exposure"}
        for report_id in sorted(additional)
    ]
    excluded_ids = {row["report_id"] for row in excluded}
    candidates = sorted(
        (row for row in population if int(row["report_id"]) not in excluded_ids),
        key=lambda row: (int(row["race_id"]), int(row["report_id"])),
    )
    if len(candidates) < 30:
        raise RuntimeError("fewer than 30 eligible metadata records")
    selected = random.Random(SEED).sample(candidates, 30)
    if len({int(row["report_id"]) for row in selected}) != 30:
        raise RuntimeError("duplicate report in seeded sample")
    return excluded, candidates, selected


def _frozen_sources() -> dict[str, str]:
    if sha(FREEZE) != EXPECTED_FREEZE_SHA:
        raise RuntimeError("approved E9-A H1/H2 manifest hash changed")
    manifest = json.loads(FREEZE.read_text(encoding="utf-8"))
    source_hashes = manifest["source_code_sha256"]
    for source, expected in source_hashes.items():
        path = Path(source)
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"frozen extractor dependency changed: {source}")
    return source_hashes


def _rosters(selected: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    race_ids = sorted({int(row["race_id"]) for row in selected})
    marks = ",".join("?" for _ in race_ids)
    connection = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
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
            ORDER BY r.id, re.horse_number, h.kra_horse_id
            """,
            (DATE_START, DATE_END, *race_ids),
        ).fetchall()
    finally:
        connection.close()
    by_race: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_race[int(row["race_id"])].append(
            {
                "meet": 1,
                "race_date": str(row["race_date"]).replace("-", ""),
                "race_number": int(row["race_number"]),
                "horse_number": int(row["horse_number"]),
                "horse_name": str(row["name_ko"]),
                "horse_source_id": str(row["kra_horse_id"]),
                "horse_source_key": [
                    1,
                    str(row["race_date"]).replace("-", ""),
                    int(row["race_number"]),
                    int(row["horse_number"]),
                    str(row["kra_horse_id"]),
                ],
            }
        )
    return by_race


def _raw_item(path: Path, race_date: str, race_number: int) -> dict[str, Any] | None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    response = payload.get("response", payload)
    items = (response.get("body") or {}).get("items") or {}
    values = items.get("item", [])
    if isinstance(values, dict):
        values = [values]
    if not isinstance(values, list):
        raise ValueError("raw items are not a list/dict")
    matches = [
        item
        for item in values
        if isinstance(item, dict)
        and str(item.get("rcDate")) == race_date.replace("-", "")
        and int(item.get("rcNo", -1)) == race_number
        and str(item.get("meet")) in {"서울", "Seoul", "SEOUL"}
    ]
    if len(matches) > 1:
        raise ValueError("duplicate report item on raw source page")
    return matches[0] if matches else None


def _identity_issues(roster: list[dict[str, Any]]) -> list[str]:
    if not roster:
        return ["roster_empty"]
    numbers = Counter(row["horse_number"] for row in roster)
    source_ids = Counter(row["horse_source_id"] for row in roster)
    issues = []
    if any(count != 1 for count in numbers.values()):
        issues.append("duplicate_horse_number")
    if any(count != 1 for count in source_ids.values()):
        issues.append("duplicate_horse_source_id")
    return issues


def _document(record: dict[str, Any], roster: list[dict[str, Any]]) -> dict[str, Any]:
    path = Path(record["source_local_path"]) if record.get("source_local_path") else None
    issues = _identity_issues(roster)
    fields: dict[str, str | None] = {"judgement": None, "addJudgement": None}
    observed_sha = None
    if path is None or not path.is_file():
        issues.append("source_missing")
    else:
        observed_sha = sha(path)
        if observed_sha != record["source_sha256"]:
            issues.append("source_hash_mismatch")
        else:
            try:
                item = _raw_item(path, record["race_date"], int(record["race_number"]))
                if item is None:
                    issues.append("report_item_missing")
                else:
                    for field in fields:
                        value = item.get(field)
                        if value is not None and not isinstance(value, str):
                            issues.append(f"{field}_not_text")
                        else:
                            fields[field] = value
            except (OSError, UnicodeError, ValueError, TypeError, KeyError):
                issues.append("source_unreadable")
    if all(value is None for value in fields.values()):
        issues.append("report_text_absent")
    issues = list(dict.fromkeys(issues))
    return {
        "report_id": int(record["report_id"]),
        "race_id": int(record["race_id"]),
        "race_date": record["race_date"],
        "race_number": int(record["race_number"]),
        "source_document_id": record["source_document_id"],
        "source_file": str(path) if path else None,
        "source_sha256_expected": record["source_sha256"],
        "source_sha256_observed": observed_sha,
        "roster": roster,
        "fields": fields,
        "field_codepoint_lengths": {
            field: len(value) if value is not None else None for field, value in fields.items()
        },
        "coverage_issues": issues,
        "coverage_status": "ready_for_blind_reading" if not issues else "incomplete_do_not_replace",
        "recorded_e9a_detail_exposure": False,
        "other_exposure_status": "unknown_not_auditable_from_local_records",
    }


def _fence(text: str) -> str:
    runs = [len(match.group()) for match in re.finditer(r"`+", text)]
    return "`" * max(3, max(runs, default=0) + 1)


def render_markdown(documents: list[dict[str, Any]]) -> str:
    lines = [
        "# E9-B 블라인드 원문 판독 패키지 — 30건",
        "",
        "이 파일에는 자동 사건 강조, 추출 결과, 예상 라벨이 없다.",
        "원문은 아래 코드 블록에 표시하며 ",
        "정확한 필드 문자열과 0-based half-open Unicode codepoint offset의 기준은 동봉 JSON이다.",
        "기존 E9-A 상세 노출은 기록상 제외했지만 그 밖의 노출 여부는 unknown이다.",
        "빈 annotation schema는 no-event 라벨이 아니다.",
        "",
    ]
    for index, doc in enumerate(documents, 1):
        lines.extend(
            [
                f"## {index:02d}. report {doc['report_id']} · race {doc['race_id']}",
                "",
                f"- 날짜: {doc['race_date']}; 경주번호: {doc['race_number']}",
                f"- 원본: `{doc['source_file']}`",
                f"- 원본 SHA256(예상/실제): `{doc['source_sha256_expected']}` / "
                f"`{doc['source_sha256_observed']}`",
                f"- coverage: {doc['coverage_status']}; issues: "
                f"{', '.join(doc['coverage_issues']) if doc['coverage_issues'] else 'none'}",
                "- 다른 경로 상세 노출: unknown (기록만으로 독립 미사용 증명 불가)",
                "",
                "| 번호 | 말 이름 | horse source ID | horse source key |",
                "|---:|---|---|---|",
            ]
        )
        for runner in doc["roster"]:
            name = runner["horse_name"].replace("|", "\\|")
            lines.append(
                f"| {runner['horse_number']} | {name} | {runner['horse_source_id']} | "
                f"`{json.dumps(runner['horse_source_key'], ensure_ascii=False)}` |"
            )
        lines.append("")
        for field in ("judgement", "addJudgement"):
            value = doc["fields"][field]
            lines.append(f"### {field}")
            lines.append("")
            if value is None:
                lines.append("원천 필드 없음 또는 판독 불가 (coverage 참조).")
            else:
                fence = _fence(value)
                lines.append(f"문자수: {len(value)} codepoints; `{field}[start:end]`")
                lines.append("(0-based, end exclusive)")
                lines.append("")
                lines.append(fence + "text")
                lines.append(value)
                lines.append(fence)
            lines.append("")
    return "\n".join(lines) + "\n"


def _annotation_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "E9-B independent manual annotation schema (no labels supplied)",
        "type": "object",
        "required": ["report_id", "review_state"],
        "properties": {
            "report_id": {"type": "integer"},
            "review_state": {"enum": ["unread", "complete", "unreadable"]},
            "event_presence": {"enum": ["present", "confirmed_absent", "unknown"]},
            "annotations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "source_field",
                        "span_start",
                        "span_end",
                        "horse_source_key",
                        "event_type",
                        "role",
                        "assertion_status",
                    ],
                    "properties": {
                        "source_field": {"enum": ["judgement", "addJudgement"]},
                        "span_start": {"type": "integer", "minimum": 0},
                        "span_end": {"type": "integer", "minimum": 1},
                        "horse_source_key": {
                            "type": ["array", "null"],
                            "minItems": 5,
                            "maxItems": 5,
                        },
                        "event_type": {
                            "enum": [
                                "start_delay",
                                "blocked_or_controlled",
                                "interference",
                                "contact",
                            ]
                        },
                        "role": {"enum": ["affected", "victim", "actor", "unknown"]},
                        "assertion_status": {
                            "enum": ["asserted", "quoted", "negated", "uncertain"]
                        },
                        "actor_victim_relationship": {
                            "type": ["object", "null"],
                            "properties": {
                                "actor_source_key": {"type": ["array", "null"]},
                                "victim_source_key": {"type": ["array", "null"]},
                                "relation_field": {"enum": ["judgement", "addJudgement"]},
                                "relation_span_start": {"type": "integer", "minimum": 0},
                                "relation_span_end": {"type": "integer", "minimum": 1},
                            },
                        },
                        "unreadable_reason": {"type": ["string", "null"]},
                    },
                },
            },
            "report_unreadable_reason": {"type": ["string", "null"]},
        },
        "description": "Schema only. No report instance or event/no-event label is populated.",
    }


def main() -> None:
    frozen_sources = _frozen_sources()
    population_manifest = json.loads(POPULATION.read_text(encoding="utf-8"))
    population = _validate_population(population_manifest)
    recorded_ids, exposure_files = _recorded_exposure_ids()
    excluded, candidates, selected = select_records(population, recorded_ids)
    candidate_keys = [[int(row["race_id"]), int(row["report_id"])] for row in candidates]
    selected_records = [
        {
            "draw_index": index,
            "race_id": int(row["race_id"]),
            "report_id": int(row["report_id"]),
            "race_date": row["race_date"],
            "race_number": int(row["race_number"]),
            "source_file": row["source_local_path"],
            "source_sha256": row["source_sha256"],
        }
        for index, row in enumerate(selected)
    ]
    if len(candidates) != 1140 and not any(
        row["reason"] == "other_recorded_e9a_detailed_exposure" for row in excluded
    ):
        raise RuntimeError("unexpected candidate count without recorded extra exposure")
    protected = [
        DB,
        POPULATION,
        FREEZE,
        Path("data/experiments/model_runs.jsonl"),
        Path("data/experiments/confirmed_starter_e9a_20260913_v9/event_evidence.jsonl"),
        Path("data/experiments/confirmed_starter_e9a_h1h2_20260913_v2/event_evidence.jsonl"),
        *[Path(path) for path in frozen_sources],
        *[Path(path) for path in exposure_files],
    ]
    protected_before = {str(path): sha(path) for path in protected if path.is_file()}
    code_paths = [Path(__file__), Path("tests/test_confirmed_starter_e9b_blind_package.py")]
    code_before = {str(path): sha(path) for path in code_paths}
    OUTPUT.mkdir(parents=True, exist_ok=False)
    # Protocol is written before any selected raw report is parsed or roster queried.
    write_new(
        OUTPUT / "selection_protocol.json",
        {
            "population_manifest_sha256": sha(POPULATION),
            "approved_freeze_manifest_sha256": EXPECTED_FREEZE_SHA,
            "frozen_extractor_dependency_sha256": frozen_sources,
            "package_code_test_sha256": code_before,
            "protected_before_sha256": protected_before,
            "scope": {"meet": 1, "date_start": DATE_START, "date_end": DATE_END},
            "population_rows": len(population),
            "exclusions": excluded,
            "recorded_exposure_files_checked": exposure_files,
            "recorded_detail_exposure_ids": sorted(recorded_ids),
            "other_exposure_status": "unknown_not_auditable_from_local_records",
            "candidate_keys_sorted": candidate_keys,
            "candidate_keys_sha256": _canonical_hash(candidate_keys),
            "candidate_count": len(candidates),
            "selection_method": (
                "random.Random(20260914).sample(candidates_sorted_by_race_report, 30)"
            ),
            "seed": SEED,
            "selected_draw_order": selected_records,
            "selected_keys_sha256": _canonical_hash(
                [[row["race_id"], row["report_id"]] for row in selected_records]
            ),
            "replacement_policy": "none_for_missing_source_identity_conflict_or_unreadable",
            "offset_contract": "decoded raw field Unicode codepoint indices, zero-based half-open; "
            "no whitespace or punctuation normalization",
            "comparison_unit": "presence of (report_id, horse_source_key, event_type, role) "
            "within document; actor-victim relationship separate; duplicate evidence "
            "rows collapse to one unit",
            "denominator_contract": {
                "complete_readable": "eligible for manual positive/confirmed-negative comparison",
                "confirmed_absent": (
                    "only explicit complete reviewer decision, never blank template"
                ),
                "unknown_unreadable_unread": "reported separately, not silently counted negative",
                "unmatched_extra_missing": (
                    "report by key and role after labels sealed; no inner-join-only scoring"
                ),
            },
            "extractor_executed_on_selected": False,
            "labels_or_metrics_created": False,
        },
    )
    roster_by_race = _rosters(selected)
    documents = [
        _document(record, roster_by_race.get(int(record["race_id"]), []))
        for record in sorted(selected, key=lambda row: (int(row["race_id"]), int(row["report_id"])))
    ]
    if len(documents) != 30 or len({doc["report_id"] for doc in documents}) != 30:
        raise RuntimeError("package report coverage is not 30 unique reports")
    coverage = [
        {
            "report_id": doc["report_id"],
            "race_id": doc["race_id"],
            "coverage_status": doc["coverage_status"],
            "issues": doc["coverage_issues"],
            "source_sha256_expected": doc["source_sha256_expected"],
            "source_sha256_observed": doc["source_sha256_observed"],
            "roster_rows": len(doc["roster"]),
            "other_exposure_status": doc["other_exposure_status"],
        }
        for doc in documents
    ]
    write_new(
        OUTPUT / "blind_documents.json",
        {
            "package_type": "human_blind_source_and_roster_only",
            "extraction_output_included": False,
            "annotation_labels_included": False,
            "offset_contract": "Unicode codepoints in decoded raw field; 0-based [start:end)",
            "documents": documents,
        },
    )
    with (OUTPUT / "blind_documents.md").open("x", encoding="utf-8", newline="") as stream:
        stream.write(render_markdown(documents))
    write_new(OUTPUT / "annotation_schema.json", _annotation_schema())
    write_new(
        OUTPUT / "coverage_exposure.json",
        {
            "selected_reports": len(documents),
            "coverage_counts": dict(Counter(doc["coverage_status"] for doc in documents)),
            "recorded_additional_exclusions": [
                row for row in excluded if row["reason"] != "e9a_sealed_detailed_sample"
            ],
            "other_exposure_status": "unknown_not_auditable_from_local_records",
            "rows": coverage,
        },
    )
    protected_after = {str(path): sha(path) for path in protected if path.is_file()}
    if protected_after != protected_before:
        raise RuntimeError("protected input changed while building blind package")
    if {str(path): sha(path) for path in code_paths} != code_before:
        raise RuntimeError("package code/test changed after protocol seal")
    manifest = {
        "protected_before_sha256": protected_before,
        "protected_after_sha256": protected_after,
        "frozen_extractor_dependency_sha256": frozen_sources,
        "package_code_test_sha256": code_before,
        "output_sha256": {
            str(path.relative_to(OUTPUT)): sha(path)
            for path in OUTPUT.iterdir()
            if path.is_file() and path.name != "artifact_manifest.json"
        },
        "external_http_requests": 0,
        "extractor_runs_on_selected": 0,
        "manual_labels": 0,
        "performance_calculations": 0,
        "model_fits": 0,
    }
    write_new(OUTPUT / "artifact_manifest.json", manifest)
    print(
        json.dumps(
            {
                "selected": len(documents),
                "candidates": len(candidates),
                "coverage": dict(Counter(doc["coverage_status"] for doc in documents)),
                "other_exposure": "unknown",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
