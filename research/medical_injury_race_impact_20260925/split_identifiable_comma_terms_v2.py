#!/usr/bin/env python3
"""Create v2 split candidates after identifying the single heat-stroke term."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from audit_comma_entries_v2 import OUTPUT as AUDIT, review
from build_candidates import classify

ROOT = Path(__file__).resolve().parent
SPLIT_OUT = ROOT / "split_comma_components_v2_20260926.csv"
HOLD_OUT = ROOT / "comma_terms_needing_confirmation_v2_20260926.csv"
SINGLE_OUT = ROOT / "comma_terms_retained_as_single_term_v2_20260926.csv"


def main() -> None:
    with AUDIT.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    split = []
    held = []
    single = []
    split_terms = set()
    for row in rows:
        parts = json.loads(row["component_proposals_json"])
        category = row["review_interpretation"]
        if category == "single_official_heat_stroke_term":
            item = dict(row)
            item["retention_reason"] = "공식 용어명 전체가 하나의 HEAT STROKE 항목이므로 분리하지 않음"
            item["candidate_term_kind"] = "disease"
            item["candidate_anatomic_system"] = "systemic"
            item["candidate_race_impact_prior"] = "context_dependent"
            item["clinical_severity"] = "unknown"
            item["review_status"] = "rule_candidate_unreviewed"
            item["rule_ids"] = "R_USER_SUPPLIED_HEAT_STROKE_GLOSSARY"
            single.append(item)
            continue
        should_split = category in {
            "two_distinct_textual_items", "two_source_entries_same_text",
            "two_medical_phrases_with_internal_anatomic_enumeration",
            "heat_stroke_term_with_other_phrase",
        }
        if not should_split:
            item = dict(row)
            item["suggested_action"] = "keep_original_unsplit_pending_confirmation"
            item["literal_chunks_json"] = json.dumps(row["raw_text"].split(","), ensure_ascii=False)
            held.append(item)
            continue
        assert len(parts) == 2 and all(x.strip() for x in parts), (row["term_id"], parts)
        split_terms.add(row["term_id"])
        for ordinal, part in enumerate(parts, 1):
            part = part.strip()
            labels = classify(part)
            if part == "일,열사병":
                labels = {
                    "term_kind": "disease",
                    "anatomic_system": "systemic",
                    "race_impact_prior": "context_dependent",
                    "review_status": "rule_candidate",
                    "clinical_severity": "unknown",
                    "rule_ids": "R_USER_SUPPLIED_HEAT_STROKE_GLOSSARY",
                    "classification_evidence": "사용자가 제공한 KRA 용어 설명상 일,열사병은 단일 HEAT STROKE 질병명; 원문 내부 쉼표 미분리; 현재 중증도/회복 상태 미확정",
                }
            split.append({
                "source_term_id": row["term_id"],
                "source_raw_text": row["raw_text"],
                "source_term_frequency": row["frequency"],
                "source_frequency_is_component_frequency": "no; allocation not available",
                "source_review_interpretation": category,
                "component_ordinal": ordinal,
                "component_raw_text": part,
                "duplicate_component_text": "yes" if category == "two_source_entries_same_text" else "no",
                "component_term_kind_candidate": labels["term_kind"],
                "component_anatomic_system_candidate": labels["anatomic_system"],
                "component_race_impact_prior_candidate": labels["race_impact_prior"],
                "component_review_status": "rule_candidate_unreviewed" if labels["review_status"] == "rule_candidate" else "unreviewed",
                "component_clinical_severity": "unknown",
                "component_rule_ids": labels["rule_ids"],
                "component_evidence": labels["classification_evidence"],
            })

    assert len(rows) == 3731
    assert len(split_terms) == 3722
    assert len(split) == 7444
    assert len(held) == 7
    assert len(single) == 2
    assert sum(int(r["frequency"]) for r in rows) == 70262
    for path, output_rows in ((SPLIT_OUT, split), (HOLD_OUT, held), (SINGLE_OUT, single)):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(output_rows[0]))
            writer.writeheader()
            writer.writerows(output_rows)
    print(f"split source terms={len(split_terms)}; component rows={len(split)}; held original terms={len(held)}")


if __name__ == "__main__":
    main()
