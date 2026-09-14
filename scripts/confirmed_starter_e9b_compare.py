"""Pure, predeclared document-presence comparison for the E9-B text audit."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

EVENT_TYPES = {"start_delay", "blocked_or_controlled", "interference", "contact"}
ROLES = {"affected", "victim", "actor"}
Key = tuple[int, tuple[Any, ...], str, str]
Pair = tuple[int, str, tuple[Any, ...], tuple[Any, ...]]


def unit(report_id: int, horse_key: list[Any], event_type: str, role: str) -> Key:
    return (report_id, tuple(horse_key), event_type, role)


def key_json(key: Key) -> dict[str, Any]:
    return {
        "report_id": key[0],
        "horse_source_key": list(key[1]),
        "event_type": key[2],
        "role": key[3],
    }


def pair_json(pair: Pair) -> dict[str, Any]:
    return {
        "report_id": pair[0],
        "event_type": pair[1],
        "actor_source_key": list(pair[2]),
        "victim_source_key": list(pair[3]),
    }


def evidence_issues(
    outputs: list[dict[str, Any]], documents: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    issues = []
    evidence_ids = [row.get("evidence_id") for row in outputs]
    if len(evidence_ids) != len(set(evidence_ids)):
        issues.append({"evidence_id": None, "reason": "duplicate_evidence_id"})
    for row in outputs:
        report_id = row.get("report_id")
        evidence_id = row.get("evidence_id")
        if report_id not in documents:
            issues.append({"evidence_id": evidence_id, "reason": "extra_report"})
            continue
        if row.get("certainty") != "clear":
            continue
        doc = documents[report_id]
        field = row.get("source_field")
        value = doc["fields"].get(field) if field in {"judgement", "addJudgement"} else None
        start, end = row.get("span_start"), row.get("span_end")
        if (
            value is None
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(value)
            or value[start:end] != row.get("span_text")
        ):
            issues.append({"evidence_id": evidence_id, "reason": "invalid_clear_span"})
        horse_key = row.get("horse_source_key")
        if not isinstance(horse_key, list) or not horse_key:
            issues.append({"evidence_id": evidence_id, "reason": "empty_clear_identity"})
        roster_keys = {tuple(runner["horse_source_key"]) for runner in doc["roster"]}
        if isinstance(horse_key, list) and horse_key and tuple(horse_key) not in roster_keys:
            issues.append({"evidence_id": evidence_id, "reason": "key_outside_roster"})
        victim_key = row.get("victim_horse_source_key")
        if victim_key is not None and (
            not isinstance(victim_key, list) or tuple(victim_key) not in roster_keys
        ):
            issues.append({"evidence_id": evidence_id, "reason": "relation_key_outside_roster"})
        if row.get("event_type") not in EVENT_TYPES or row.get("role") not in ROLES:
            issues.append({"evidence_id": evidence_id, "reason": "invalid_clear_type_or_role"})
    return issues


def _status_metric(tp: int, fp: int, fn: int, unscorable: int = 0) -> dict[str, Any]:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        (2 * precision * recall / (precision + recall) if precision + recall else 0.0)
        if precision is not None and recall is not None
        else None
    )
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "unscorable": unscorable,
        "precision_denominator": tp + fp,
        "recall_denominator": tp + fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "null_reasons": {
            "precision": "no_scorable_predictions" if precision is None else None,
            "recall": "no_reference_positives" if recall is None else None,
            "f1": "undefined_precision_or_recall" if f1 is None else None,
        },
    }


def compare(
    documents: list[dict[str, Any]],
    references: list[dict[str, Any]],
    masks: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare one complete fixed report set; never intersect report sets silently."""
    doc_by_id = {row["report_id"]: row for row in documents}
    ref_by_id = {row["report_id"]: row for row in references}
    if len(doc_by_id) != len(documents) or len(ref_by_id) != len(references):
        raise ValueError("duplicate document or reference report")
    if set(doc_by_id) != set(ref_by_id):
        missing = sorted(set(doc_by_id) - set(ref_by_id))
        extra = sorted(set(ref_by_id) - set(doc_by_id))
        raise ValueError(f"reference report mismatch: missing={missing}, extra={extra}")
    actual_report_ids = {row.get("report_id") for row in outputs}
    if not actual_report_ids <= set(doc_by_id):
        raise ValueError(f"extra output reports: {sorted(actual_report_ids - set(doc_by_id))}")
    issues = evidence_issues(outputs, doc_by_id)
    if issues:
        return {"contract_failures": issues, "metrics_status": "blocked_by_output_contract"}

    gold: dict[Key, list[dict[str, Any]]] = defaultdict(list)
    ref_unknown: list[dict[str, Any]] = []
    ref_quoted: list[dict[str, Any]] = []
    ref_pairs: dict[Pair, set[str]] = defaultdict(set)
    ref_pair_spans: dict[Pair, list[dict[str, Any]]] = defaultdict(list)
    for report in references:
        report_id = report["report_id"]
        if report.get("review_state") != "complete":
            raise ValueError(f"incomplete reference report: {report_id}")
        for ann in report["annotations"]:
            if ann["assertion_status"] == "quoted":
                ref_quoted.append({"report_id": report_id, **ann})
            if ann["role"] == "unknown" or ann["horse_source_key"] is None:
                ref_unknown.append({"report_id": report_id, **ann})
            if (
                ann["assertion_status"] == "asserted"
                and ann["horse_source_key"] is not None
                and ann["role"] != "unknown"
            ):
                key = unit(report_id, ann["horse_source_key"], ann["event_type"], ann["role"])
                gold[key].append(ann)
                relation = ann.get("actor_victim_relationship")
                if (
                    relation
                    and relation.get("actor_source_key")
                    and relation.get("victim_source_key")
                ):
                    pair = (
                        report_id,
                        ann["event_type"],
                        tuple(relation["actor_source_key"]),
                        tuple(relation["victim_source_key"]),
                    )
                    ref_pairs[pair].add(ann["annotation_id"])
                    ref_pair_spans[pair].append(
                        {
                            "annotation_id": ann["annotation_id"],
                            "field": relation["relation_field"],
                            "start": relation["relation_span_start"],
                            "end": relation["relation_span_end"],
                            "text": relation["relation_span_text"],
                        }
                    )

    predictions: dict[Key, list[dict[str, Any]]] = defaultdict(list)
    output_pairs: dict[Pair, set[str]] = defaultdict(set)
    output_pair_spans: dict[Pair, list[dict[str, Any]]] = defaultdict(list)
    coverage = Counter(row.get("certainty", "missing") for row in outputs)
    for row in outputs:
        if row["certainty"] != "clear":
            continue
        key = unit(row["report_id"], row["horse_source_key"], row["event_type"], row["role"])
        predictions[key].append(row)
        if row["role"] == "actor" and row.get("victim_horse_source_key"):
            pair = (
                row["report_id"],
                row["event_type"],
                tuple(row["horse_source_key"]),
                tuple(row["victim_horse_source_key"]),
            )
            output_pairs[pair].add(row["evidence_id"])
            output_pair_spans[pair].append(
                {
                    "evidence_id": row["evidence_id"],
                    "field": row["source_field"],
                    "start": row.get("relation_span_start"),
                    "end": row.get("relation_span_end"),
                    "text": row.get("relation_span_text"),
                }
            )

    def masked(key: Key) -> list[str]:
        return [
            mask["reason"]
            for mask in masks
            if mask["report_id"] == key[0]
            and mask["event_type"] == key[2]
            and key[1][3] in mask["horse_numbers"]
            and key[3] in mask["roles"]
        ]

    status: dict[Key, str] = {}
    records: list[dict[str, Any]] = []
    for key in sorted(set(gold) | set(predictions)):
        refs = gold.get(key, [])
        evidence = predictions.get(key, [])
        if refs and evidence:
            state, reason = "tp", "explicit_positive_precedes_uncertainty"
        elif refs:
            state, reason = "fn", "reference_positive_not_extracted_clear"
        elif masked(key):
            state, reason = "unscorable", "uncertainty_mask"
        else:
            state, reason = "fp", "unmatched_clear_in_complete_report"
        status[key] = state
        doc = doc_by_id[key[0]]
        records.append(
            {
                **key_json(key),
                "status": state,
                "reason": reason,
                "mask_reasons": masked(key),
                "reference_ids": [ann["annotation_id"] for ann in refs],
                "evidence_ids": [row["evidence_id"] for row in evidence],
                "reference_spans": [
                    {
                        "field": ann["source_field"],
                        "start": ann["span_start"],
                        "end": ann["span_end"],
                        "text": ann["span_text"],
                    }
                    for ann in refs
                ],
                "evidence_spans": [
                    {
                        "field": row["source_field"],
                        "start": row["span_start"],
                        "end": row["span_end"],
                        "text": row["span_text"],
                    }
                    for row in evidence
                ],
                "source_fields": doc["fields"],
                "reference_scopes": sorted({ann["comparison_scope"] for ann in refs}),
            }
        )
    if set(status) != set(gold) | set(predictions):
        raise AssertionError("unit conservation failure")
    if any(status[key] not in {"tp", "fn"} for key in gold):
        raise AssertionError("gold positive conservation failure")
    if any(status[key] not in {"tp", "fp", "unscorable"} for key in predictions):
        raise AssertionError("clear prediction conservation failure")
    counts = Counter(status.values())
    overall = _status_metric(counts["tp"], counts["fp"], counts["fn"], counts["unscorable"])
    overall["clear_unique_units"] = len(predictions)
    overall["unscorable_fraction_of_clear_unique"] = (
        counts["unscorable"] / len(predictions) if predictions else None
    )
    overall["unscorable_fraction_null_reason"] = "no_clear_predictions" if not predictions else None
    overall["reference_positive_unique_units"] = len(gold)
    overall["reference_positive_annotation_rows"] = sum(len(rows) for rows in gold.values())
    overall["clear_evidence_rows"] = sum(len(rows) for rows in predictions.values())

    def slice_metric(predicate: Any) -> dict[str, Any]:
        subset = Counter(state for key, state in status.items() if predicate(key))
        return _status_metric(subset["tp"], subset["fp"], subset["fn"], subset["unscorable"])

    diagnostics = {
        "event_type": {
            name: slice_metric(lambda key, name=name: key[2] == name)
            for name in sorted(EVENT_TYPES)
        },
        "role": {
            name: slice_metric(lambda key, name=name: key[3] == name) for name in sorted(ROLES)
        },
        "reference_scope": {
            name: {
                "gold_units": sum(
                    any(ann["comparison_scope"] == name for ann in anns) for anns in gold.values()
                ),
                "tp": sum(
                    status[key] == "tp" and any(ann["comparison_scope"] == name for ann in anns)
                    for key, anns in gold.items()
                ),
                "fn": sum(
                    status[key] == "fn" and any(ann["comparison_scope"] == name for ann in anns)
                    for key, anns in gold.items()
                ),
                "scope_recall": (
                    sum(
                        status[key] == "tp" and any(ann["comparison_scope"] == name for ann in anns)
                        for key, anns in gold.items()
                    )
                    / sum(
                        any(ann["comparison_scope"] == name for ann in anns)
                        for anns in gold.values()
                    )
                    if any(
                        any(ann["comparison_scope"] == name for ann in anns)
                        for anns in gold.values()
                    )
                    else None
                ),
                "note": "reference-positive scope only; no independent FP/precision denominator",
            }
            for name in ("core", "semantic_extension")
        },
    }

    pair_rows = []
    for pair in sorted(set(ref_pairs) | set(output_pairs)):
        pair_rows.append(
            {
                **pair_json(pair),
                "status": "matched_confirmed"
                if pair in ref_pairs and pair in output_pairs
                else "missed_confirmed"
                if pair in ref_pairs
                else "unmatched_output_not_scored_negative",
                "reference_ids": sorted(ref_pairs.get(pair, set())),
                "evidence_ids": sorted(output_pairs.get(pair, set())),
                "reference_relation_spans": ref_pair_spans.get(pair, []),
                "output_relation_spans": output_pair_spans.get(pair, []),
                "source_fields": doc_by_id[pair[0]]["fields"],
            }
        )
    unknown_reference: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for row in ref_unknown:
        if (
            row["assertion_status"] == "asserted"
            and row["event_type"] == "contact"
            and row["role"] == "unknown"
            and row["horse_source_key"] is not None
        ):
            item = (row["report_id"], tuple(row["horse_source_key"]), row["event_type"])
            unknown_reference[item].append(row["annotation_id"])
    unknown_output: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for row in outputs:
        if (
            row.get("event_type") == "contact"
            and row.get("role") == "unknown"
            and isinstance(row.get("horse_source_key"), list)
        ):
            item = (row["report_id"], tuple(row["horse_source_key"]), row["event_type"])
            unknown_output[item].append(row["evidence_id"])
    unknown_rows = [
        {
            "report_id": item[0],
            "horse_source_key": list(item[1]),
            "event_type": item[2],
            "reference_ids": unknown_reference.get(item, []),
            "evidence_ids": unknown_output.get(item, []),
            "source_fields": doc_by_id[item[0]]["fields"],
        }
        for item in sorted(set(unknown_reference) | set(unknown_output))
    ]
    return {
        "metrics_status": "complete",
        "overall": overall,
        "diagnostics": diagnostics,
        "units": records,
        "coverage_by_certainty": dict(coverage),
        "reference_unknown_rows": ref_unknown,
        "reference_quoted_rows": ref_quoted,
        "mutual_contact_unknown_participants": {
            "reference_units": len(unknown_reference),
            "output_units_with_key": len(unknown_output),
            "overlap_units": len(set(unknown_reference) & set(unknown_output)),
            "rows": unknown_rows,
            "not_binary_accuracy": True,
        },
        "relations": {
            "confirmed_reference_pairs": len(ref_pairs),
            "confirmed_pairs_recovered": len(set(ref_pairs) & set(output_pairs)),
            "rows": pair_rows,
            "pair_precision": None,
            "pair_precision_null_reason": "unknown_relation_negative_set_incomplete",
        },
        "conservation": {
            "gold_units": len(gold),
            "gold_tp_plus_fn": counts["tp"] + counts["fn"],
            "clear_unique_units": len(predictions),
            "clear_tp_plus_fp_plus_unscorable": counts["tp"] + counts["fp"] + counts["unscorable"],
        },
        "contract_failures": [],
    }
