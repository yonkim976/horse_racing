#!/usr/bin/env python3
"""Write review-only split candidates while preserving source term provenance."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

from audit_comma_entries import review
from build_candidates import classify

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "candidate_terms.csv"
REVIEW = ROOT / "comma_entry_review_20260926.csv"
SPLIT_OUT = ROOT / "split_comma_components_20260926.csv"
HOLD_OUT = ROOT / "comma_terms_needing_confirmation_20260926.csv"
REPORT = ROOT / "split_comma_terms_report_ko_20260926.md"
METADATA = ROOT / "split_comma_run_metadata_20260926.json"


def main() -> None:
    with SOURCE.open(encoding="utf-8-sig", newline="") as f:
        source_rows = {r["raw_text"]: r for r in csv.DictReader(f)}
    with REVIEW.open(encoding="utf-8-sig", newline="") as f:
        audit_rows = list(csv.DictReader(f))

    split_parents = []
    hold_rows = []
    split_rows = []
    disposition_counts = Counter()
    split_parent_frequency = Counter()
    for audit in audit_rows:
        raw = audit["raw_text"]
        row = source_rows[raw]
        interpretation = audit["review_interpretation"]
        if interpretation in {
            "two_distinct_textual_items",
            "two_source_entries_same_text",
            "two_medical_phrases_with_internal_anatomic_enumeration",
        }:
            # These two reviewed examples contain an internal numeric comma in
            # the second phrase. Split only on the first, top-level delimiter.
            parts = raw.split(",", 1)
            assert len(parts) == 2 and all(p.strip() for p in parts)
            split_parents.append(row)
            disposition_counts[interpretation] += 1
            split_parent_frequency[interpretation] += int(row["frequency"])
            for ordinal, part in enumerate(parts, 1):
                labels = classify(part.strip())
                split_rows.append({
                    "source_term_id": row["term_id"],
                    "source_raw_text": raw,
                    "source_term_frequency": row["frequency"],
                    "source_frequency_is_component_frequency": "no; allocation not available",
                    "source_review_interpretation": interpretation,
                    "component_ordinal": ordinal,
                    "component_raw_text": part.strip(),
                    "duplicate_component_text": "yes" if interpretation == "two_source_entries_same_text" else "no",
                    "component_term_kind_candidate": labels["term_kind"],
                    "component_anatomic_system_candidate": labels["anatomic_system"],
                    "component_race_impact_prior_candidate": labels["race_impact_prior"],
                    "component_review_status": "rule_candidate_unreviewed" if labels["review_status"] == "rule_candidate" else "unreviewed",
                    "component_clinical_severity": "unknown",
                    "component_rule_ids": labels["rule_ids"],
                    "component_evidence": labels["classification_evidence"],
                })
        else:
            disposition_counts[interpretation] += 1
            hold = dict(audit)
            hold["suggested_action"] = "keep_original_unsplit_pending_confirmation"
            hold["literal_chunks_json"] = json.dumps(raw.split(","), ensure_ascii=False)
            hold_rows.append(hold)

    with SPLIT_OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(split_rows[0]))
        writer.writeheader()
        writer.writerows(split_rows)
    with HOLD_OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(hold_rows[0]))
        writer.writeheader()
        writer.writerows(hold_rows)

    assert len(audit_rows) == 3731
    assert len(split_parents) == 3712
    assert len(split_rows) == 7424
    assert len(hold_rows) == 19
    assert sum(int(r["frequency"]) for r in audit_rows) == 70262
    assert disposition_counts["single_medical_phrase_internal_anatomic_enumeration"] == 7
    assert disposition_counts["two_medical_phrases_plus_unresolved_token"] == 12

    metadata = {
        "source_file": SOURCE.name,
        "comma_audit_file": REVIEW.name,
        "comma_terms_total": len(audit_rows),
        "split_source_terms": len(split_parents),
        "split_component_rows": len(split_rows),
        "held_source_terms": len(hold_rows),
        "all_comma_term_frequency_sum": 70262,
        "component_frequency_policy": "Source phrase frequency is repeated as provenance only and must not be summed per component; component-level allocation is unavailable.",
        "split_policy": "Split at the comma only for 3,704 different two-text terms, 6 identical repeated-text pairs, and 2 manually inspected top-level pairs whose second diagnosis contains a numeric anatomical enumeration.",
        "hold_policy": "Preserve 7 likely single diagnoses with an internal numeric anatomical comma and 12 terms with an unresolved isolated token '일' as whole raw source terms.",
        "source_text_modified": False,
        "disposition_counts": dict(disposition_counts),
        "split_parent_frequency_by_disposition": dict(split_parent_frequency),
    }
    METADATA.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = [
        "# 쉼표 항목 분리 후보와 확인 대기 원문 · 2026-09-26",
        "",
        "## 분리해 저장한 항목",
        "",
        "쉼표 포함 고유 term 3,731개 중 3,712개를 검토 가능한 분리 후보로 저장했다. 서로 다른 두 원문 조각 3,704개, 같은 문구가 반복된 6개, 두 진단 문구 중 두 번째에 해부학 번호 열거 쉼표가 든 2개다. 결과는 `split_comma_components_20260926.csv`의 7,424행이다.",
        "",
        "동일 원문에서 나온 두 component 행은 같은 `source_term_id`와 `source_raw_text`를 갖는다. 원문 슬롯 빈도는 부모 원문에만 관측되므로 각 행에 `source_term_frequency`로 출처만 남겼고, component별 빈도로 해석하거나 합산하지 않도록 표시했다. component 분류도 기존 규칙을 적용한 검토 후보일 뿐이다.",
        "",
        "## 분리하지 않고 확인 목록에 둔 항목",
        "",
        "`comma_terms_needing_confirmation_20260926.csv`에는 19개 원문을 그대로 남겼다.",
        "",
        "- 7개는 `좌제2,3중수골골간인대염`처럼 해부학 번호를 열거하는 쉼표가 병명 내부에 있어 하나의 문구로 보인다.",
        "- 12개는 `...,일,열사병` 구조다. 두 의학 문구는 식별되지만 `일`의 뜻과 앞뒤 관계가 불명확해 원문 전체를 분리하지 않았다.",
        "",
        "각 보류 원문에는 term_id, 원문 빈도, 문자상 쉼표 조각, 보류 이유가 있다. 사용자가 확인해주면 해당 원문만 후속 분리하면 된다.",
        "",
        "## 사용 시 주의",
        "",
        "기존 `candidate_terms.csv`와 원문 DB는 변경하지 않았다. 분리본은 별도 연구용 후보다. 서로 다른 텍스트 조각이 두 질병 또는 두 진료행이라고 확정된 것은 아니며, 치료·검사와 진단이 함께 있을 수 있다. 운영 DB, Supabase, 프론트엔드에 적용하지 않았다.",
        "",
        "재생성: `python3 research/medical_injury_race_impact_20260925/split_identifiable_comma_terms.py` (쉼표 전수 audit 산출물을 먼저 생성해야 함).",
        "",
    ]
    REPORT.write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
