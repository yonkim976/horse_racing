"""One-shot E9-B frozen extractor audit. Never run this script twice for one sample."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from horse_racing.analysis.confirmed_starter_e9a import Runner
from horse_racing.analysis.confirmed_starter_e9a_h1h2 import extract_report_h1h2
from scripts.confirmed_starter_e9b_compare import compare

BLIND = Path("data/experiments/confirmed_starter_e9b_blind_20260913_v1")
REFERENCE = Path("data/experiments/confirmed_starter_e9b_reference_20260913_v2")
FROZEN = Path("data/experiments/confirmed_starter_e9a_h1h2_20260913_v2/artifact_manifest.json")
OUTPUT = Path("data/experiments/confirmed_starter_e9b_frozen_evaluation_20260913_v1")
EXPECTED_REFERENCE_SHA = "285d91e0f85b909c4c7ebf889c18158ffdbea62520b1824d4499d8111b1be849"
EXPECTED_FROZEN_SHA = "f19f5b77cb19b5f113585b4ac83497b7ec4579c8652ef2c7c5a72931daad973e"
EXPECTED_BLIND_MANIFEST_SHA = "660030e78baf04e1c98ea158259e1be8582839f00250f21ea664f8f0ffe7b03f"
EVENT_TYPES = {"start_delay", "blocked_or_controlled", "interference", "contact"}
ROLES = {"affected", "victim", "actor"}


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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def _raw_fields(doc: dict[str, Any]) -> dict[str, str | None]:
    source = Path(doc["source_file"])
    if sha(source) != doc["source_sha256_expected"]:
        raise RuntimeError(f"raw source hash mismatch for report {doc['report_id']}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    values = payload["response"]["body"]["items"]["item"]
    if isinstance(values, dict):
        values = [values]
    matches = [
        item
        for item in values
        if str(item.get("rcDate")) == doc["race_date"].replace("-", "")
        and int(item.get("rcNo", -1)) == doc["race_number"]
        and str(item.get("meet")) in {"서울", "Seoul", "SEOUL"}
    ]
    if len(matches) != 1:
        raise RuntimeError(f"raw report item coverage failure: {doc['report_id']}")
    return {field: matches[0].get(field) for field in ("judgement", "addJudgement")}


def preflight() -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[int],
    dict[str, str],
]:
    if sha(REFERENCE / "artifact_manifest.json") != EXPECTED_REFERENCE_SHA:
        raise RuntimeError("reference seal manifest changed")
    if sha(FROZEN) != EXPECTED_FROZEN_SHA:
        raise RuntimeError("frozen extractor manifest changed")
    if sha(BLIND / "artifact_manifest.json") != EXPECTED_BLIND_MANIFEST_SHA:
        raise RuntimeError("blind package manifest changed")
    reference_manifest = json.loads((REFERENCE / "artifact_manifest.json").read_text())
    blind_manifest = json.loads((BLIND / "artifact_manifest.json").read_text())
    frozen_manifest = json.loads(FROZEN.read_text())
    if reference_manifest["package_manifest_sha256"] != EXPECTED_BLIND_MANIFEST_SHA:
        raise RuntimeError("reference seal points to another blind package")
    if reference_manifest["frozen_extractor_manifest_sha256"] != EXPECTED_FROZEN_SHA:
        raise RuntimeError("reference seal points to another frozen extractor")
    if reference_manifest["package_documents_sha256"] != sha(BLIND / "blind_documents.json"):
        raise RuntimeError("reference seal points to another blind document set")
    for filename, expected in reference_manifest["files"].items():
        if sha(REFERENCE / filename) != expected:
            raise RuntimeError(f"reference file changed: {filename}")
    for filename, expected in blind_manifest["output_sha256"].items():
        if sha(BLIND / filename) != expected:
            raise RuntimeError(f"blind package file changed: {filename}")
    for source, expected in frozen_manifest["source_code_sha256"].items():
        if sha(Path(source)) != expected:
            raise RuntimeError(f"frozen source changed: {source}")
    package = json.loads((BLIND / "blind_documents.json").read_text())
    documents = package["documents"]
    references = read_jsonl(REFERENCE / "reference_annotations.jsonl")
    masks = json.loads((REFERENCE / "uncertainty_masks.json").read_text())
    selection = json.loads((BLIND / "selection_protocol.json").read_text())
    order = [row["report_id"] for row in selection["selected_draw_order"]]
    doc_by_id = {doc["report_id"]: doc for doc in documents}
    ref_by_id = {ref["report_id"]: ref for ref in references}
    if len(order) != len(set(order)) or len(order) != 30:
        raise RuntimeError("selection has missing/duplicate report IDs")
    if len(doc_by_id) != len(documents) or len(ref_by_id) != len(references):
        raise RuntimeError("duplicate document/reference report ID")
    if set(order) != set(doc_by_id) or set(order) != set(ref_by_id):
        raise RuntimeError("30-report selection/document/reference coverage mismatch")
    positive_units = set()
    for report_id in order:
        doc, ref = doc_by_id[report_id], ref_by_id[report_id]
        if doc["coverage_status"] != "ready_for_blind_reading" or doc["coverage_issues"]:
            raise RuntimeError(f"blind source coverage failure: {report_id}")
        if doc["fields"] != _raw_fields(doc):
            raise RuntimeError(f"blind fields differ from raw source: {report_id}")
        if ref["source_sha256"] != doc["source_sha256_expected"]:
            raise RuntimeError(f"reference source hash mismatch: {report_id}")
        if ref["race_id"] != doc["race_id"] or ref["review_state"] != "complete":
            raise RuntimeError(f"reference race/readability mismatch: {report_id}")
        roster_keys = [tuple(row["horse_source_key"]) for row in doc["roster"]]
        if not roster_keys or len(roster_keys) != len(set(roster_keys)):
            raise RuntimeError(f"roster key coverage failure: {report_id}")
        for ann in ref["annotations"]:
            field = doc["fields"].get(ann["source_field"])
            if field is None or field[ann["span_start"] : ann["span_end"]] != ann["span_text"]:
                raise RuntimeError(f"reference span mismatch: {report_id}/{ann['annotation_id']}")
            key = ann["horse_source_key"]
            if key is not None and tuple(key) not in roster_keys:
                raise RuntimeError(f"reference key outside roster: {report_id}")
            relation = ann.get("actor_victim_relationship")
            if relation is not None:
                if (
                    relation["actor_source_key"] is not None
                    and tuple(relation["actor_source_key"]) not in roster_keys
                ):
                    raise RuntimeError(f"reference actor relation key outside roster: {report_id}")
                if (
                    relation["victim_source_key"] is not None
                    and tuple(relation["victim_source_key"]) not in roster_keys
                ):
                    raise RuntimeError(f"reference victim relation key outside roster: {report_id}")
                relation_field = doc["fields"].get(relation["relation_field"])
                if (
                    relation_field is None
                    or relation_field[
                        relation["relation_span_start"] : relation["relation_span_end"]
                    ]
                    != relation["relation_span_text"]
                ):
                    raise RuntimeError(f"reference relation span mismatch: {report_id}")
            if (
                ann["assertion_status"] == "asserted"
                and key is not None
                and ann["role"] != "unknown"
            ):
                if ann["event_type"] not in EVENT_TYPES or ann["role"] not in ROLES:
                    raise RuntimeError(f"reference positive type/role invalid: {report_id}")
                positive_units.add((report_id, tuple(key), ann["event_type"], ann["role"]))
    if len(positive_units) != 121:
        raise RuntimeError(f"sealed reference positive contract is not 121: {len(positive_units)}")
    if any(mask["report_id"] not in doc_by_id for mask in masks):
        raise RuntimeError("uncertainty mask outside selected reports")
    protected = {
        str(path): sha(path)
        for path in [
            FROZEN,
            BLIND / "artifact_manifest.json",
            REFERENCE / "artifact_manifest.json",
            *(BLIND / filename for filename in blind_manifest["output_sha256"]),
            *(REFERENCE / filename for filename in reference_manifest["files"]),
            *(Path(source) for source in frozen_manifest["source_code_sha256"]),
            *(Path(doc["source_file"]) for doc in documents),
        ]
    }
    return selection, documents, references, masks, order, protected


def _runners(doc: dict[str, Any]) -> list[Runner]:
    return [
        Runner(
            meet=row["meet"],
            race_date=row["race_date"],
            race_number=row["race_number"],
            horse_number=row["horse_number"],
            horse_source_id=row["horse_source_id"],
            horse_name=row["horse_name"],
        )
        for row in doc["roster"]
    ]


def render_table(comparison: dict[str, Any]) -> str:
    lines = [
        "# E9-B 동결 추출 품질 — 판독표",
        "",
        "이 표는 사후 심판보고서 텍스트의 추출 품질 비교이며 경마 예측 성능이 아니다.",
        "",
    ]
    if comparison["metrics_status"] != "complete":
        lines.append(f"계약 실패로 지표 미계산: {comparison['contract_failures']}")
        return "\n".join(lines) + "\n"
    overall = comparison["overall"]
    metric_line = (
        f"TP {overall['tp']}, FP {overall['fp']}, FN {overall['fn']}, "
        f"unscorable {overall['unscorable']}; precision {overall['precision']}, "
        f"recall {overall['recall']}, F1 {overall['f1']}"
    )
    lines.extend(
        [
            metric_line,
            "",
            "| 상태 | report | horse key | 유형 | 역할 | reference ID | evidence ID | 이유 |",
            "|---|---:|---|---|---|---|---|---|",
        ]
    )
    for row in comparison["units"]:
        key = json.dumps(row["horse_source_key"], ensure_ascii=False)
        lines.append(
            f"| {row['status']} | {row['report_id']} | `{key}` | "
            f"{row['event_type']} | {row['role']} | {', '.join(row['reference_ids'])} | "
            f"{', '.join(row['evidence_ids'])} | {row['reason']} |"
        )
    lines.extend(["", "## 불일치·판정불가 원문", ""])
    for row in comparison["units"]:
        if row["status"] == "tp":
            continue
        lines.append(
            f"### {row['status']} · report {row['report_id']} · {row['event_type']} · {row['role']}"
        )
        lines.append(f"- key: `{json.dumps(row['horse_source_key'], ensure_ascii=False)}`")
        lines.append(f"- reference: {row['reference_ids']}; evidence: {row['evidence_ids']}")
        lines.append(f"- mask: {row['mask_reasons']}")
        for kind in ("reference_spans", "evidence_spans"):
            for span in row[kind]:
                location = f"{span['field']}[{span['start']}:{span['end']}]"
                lines.append(f"- {kind} {location}: {json.dumps(span['text'], ensure_ascii=False)}")
        if not row["reference_spans"] and not row["evidence_spans"]:
            lines.append("- 원문 근거 없음")
        lines.append("")
    lines.extend(["## actor-victim 관계", ""])
    for row in comparison["relations"]["rows"]:
        lines.append(
            f"- {row['status']} report {row['report_id']} {row['event_type']} "
            f"actor `{row['actor_source_key']}` → victim `{row['victim_source_key']}`; "
            f"reference {row['reference_ids']}; evidence {row['evidence_ids']}"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    selection, documents, references, masks, order, protected_before = preflight()
    code_paths = [
        Path(__file__),
        Path("scripts/confirmed_starter_e9b_compare.py"),
        Path("tests/test_confirmed_starter_e9b_frozen_evaluation.py"),
    ]
    code_sha = {str(path): sha(path) for path in code_paths}
    doc_by_id = {doc["report_id"]: doc for doc in documents}
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_new(
        OUTPUT / "evaluation_protocol.json",
        {
            "approved_extractor_manifest_sha256": EXPECTED_FROZEN_SHA,
            "reference_manifest_sha256": EXPECTED_REFERENCE_SHA,
            "blind_manifest_sha256": EXPECTED_BLIND_MANIFEST_SHA,
            "selection_protocol_sha256": sha(BLIND / "selection_protocol.json"),
            "input_and_frozen_source_sha256": protected_before,
            "runner_evaluator_test_sha256": code_sha,
            "report_call_order": order,
            "planned_calls": 30,
            "call_contract": "exactly once per report; first failure stops; no retry",
            "primary_unit": "unique (report_id,horse_source_key,event_type,role) in document",
            "gold": (
                "asserted, resolved key, role not unknown; "
                "includes semantic_extension; expected 121"
            ),
            "prediction": "certainty clear, valid roster key, type, role, and exact raw span",
            "uncertainty": "explicit positive precedence; matching mask without gold is unscorable",
            "quoted": "not positive on its own",
            "metrics": (
                "TP=P∩G; FN=G-P; FP=scorable(P-G); precision TP/(TP+FP); "
                "recall TP/(TP+FN); F1 harmonic, null for zero denominator"
            ),
            "relations": (
                "resolved actor-victim reference pairs only; "
                "no Cartesian expansion; no pair precision"
            ),
            "scope": (
                "30 retrospective Seoul reports; text extraction only; "
                "no outcome or prediction evaluation"
            ),
        },
    )
    outputs: list[dict[str, Any]] = []
    counts = Counter()
    try:
        with (
            (OUTPUT / "call_ledger.jsonl").open("x", encoding="utf-8") as ledger,
            (OUTPUT / "raw_evidence.jsonl").open("x", encoding="utf-8") as raw,
        ):
            for index, report_id in enumerate(order, 1):
                doc = doc_by_id[report_id]
                counts["attempted"] += 1
                try:
                    result = extract_report_h1h2(
                        doc["fields"],
                        _runners(doc),
                        context={
                            "report_id": report_id,
                            "race_id": doc["race_id"],
                            "race_date": doc["race_date"],
                            "race_number": doc["race_number"],
                            "source_document_id": doc["source_document_id"],
                            "source_raw_sha256": doc["source_sha256_expected"],
                            "observation_mode": "retrospective_only",
                            "availability_status": "availability_unverified",
                        },
                    )
                except Exception as exc:
                    ledger.write(
                        json.dumps(
                            {
                                "call_index": index,
                                "report_id": report_id,
                                "status": "failed",
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    ledger.flush()
                    raise
                counts["success"] += 1
                if not result:
                    counts["empty_output"] += 1
                ledger.write(
                    json.dumps(
                        {
                            "call_index": index,
                            "report_id": report_id,
                            "status": "success",
                            "evidence_rows": len(result),
                            "empty_output": not result,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                ledger.flush()
                for row in result:
                    evidence = {"evidence_id": f"E9B-{len(outputs) + 1:06d}", **row}
                    outputs.append(evidence)
                    raw.write(json.dumps(evidence, ensure_ascii=False, sort_keys=True) + "\n")
                raw.flush()
    except Exception:
        write_new(
            OUTPUT / "run_incomplete.json",
            {
                "attempted": counts["attempted"],
                "success": counts["success"],
                "empty_output": counts["empty_output"],
                "reason": "first_call_exception_no_retry_or_metrics",
            },
        )
        raise
    if counts["attempted"] != 30 or counts["success"] != 30:
        raise RuntimeError("call ledger count mismatch; do not retry")
    comparison = compare(documents, references, masks, outputs)
    write_new(OUTPUT / "comparison.json", comparison)
    with (OUTPUT / "comparison_readable.md").open("x", encoding="utf-8") as stream:
        stream.write(render_table(comparison))
    write_new(
        OUTPUT / "reference_disputes.json",
        {
            "disputes": [],
            "note": "No reference edits or post-output adjudication performed in this frozen run.",
        },
    )
    protected_after = {path: sha(Path(path)) for path in protected_before}
    if protected_after != protected_before:
        raise RuntimeError("protected input changed during evaluation")
    if {str(path): sha(path) for path in code_paths} != code_sha:
        raise RuntimeError("evaluation code/test changed after protocol seal")
    write_new(
        OUTPUT / "artifact_manifest.json",
        {
            "protected_before_sha256": protected_before,
            "protected_after_sha256": protected_after,
            "runner_evaluator_test_sha256": code_sha,
            "output_sha256": {
                str(path.relative_to(OUTPUT)): sha(path)
                for path in OUTPUT.iterdir()
                if path.is_file()
            },
            "actual_extractor_calls": counts["attempted"],
            "successful_extractor_calls": counts["success"],
            "empty_output_reports": counts["empty_output"],
            "external_http_requests": 0,
            "model_fits": 0,
        },
    )
    print(
        json.dumps(
            {
                "calls": counts["attempted"],
                "success": counts["success"],
                "evidence_rows": len(outputs),
                "metrics_status": comparison["metrics_status"],
                "overall": comparison.get("overall"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
