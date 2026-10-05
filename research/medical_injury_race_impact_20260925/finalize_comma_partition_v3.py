#!/usr/bin/env python3
"""Finalize comma partition candidates using user-confirmed term readings."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from build_candidates import classify

ROOT = Path(__file__).resolve().parent
AUDIT = ROOT / "comma_entry_review_v2_20260926.csv"
DECISIONS = ROOT / "comma_terms_adjudicated_v3_20260926.csv"
SPLIT = ROOT / "split_comma_components_v3_20260926.csv"
SINGLE = ROOT / "comma_terms_retained_as_one_phrase_v3_20260926.csv"
REPORT = ROOT / "comma_partition_final_report_ko_v3_20260926.md"
META = ROOT / "comma_partition_final_metadata_v3_20260926.json"

SPLIT_CATEGORIES = {
    "two_distinct_textual_items",
    "two_source_entries_same_text",
    "two_medical_phrases_with_internal_anatomic_enumeration",
    "heat_stroke_term_with_other_phrase",
}
SINGLE_CATEGORIES = {
    "single_medical_phrase_internal_anatomic_enumeration",
    "single_official_heat_stroke_term",
}


def main() -> None:
    with AUDIT.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    decisions, components, singles = [], [], []
    counts = Counter()
    for row in rows:
        kind = row["review_interpretation"]
        parts = json.loads(row["component_proposals_json"])
        if kind in SPLIT_CATEGORIES:
            if kind == "two_medical_phrases_with_internal_anatomic_enumeration":
                # The second phrase has an internal number-list comma. V2
                # recorded the two manually inspected top-level components.
                assert len(parts) == 2
            else:
                assert len(parts) == 2
            counts["split_source_terms"] += 1
            decisions.append({**row, "final_partition_status": "split_into_two_review_candidates", "final_components_json": json.dumps(parts, ensure_ascii=False)})
            for ordinal, raw_component in enumerate(parts, 1):
                component = raw_component.strip()
                labels = classify(component)
                if component == "일,열사병":
                    labels = {
                        "term_kind": "disease", "anatomic_system": "systemic",
                        "race_impact_prior": "context_dependent",
                        "review_status": "rule_candidate", "clinical_severity": "unknown",
                        "rule_ids": "R_USER_SUPPLIED_HEAT_STROKE_GLOSSARY",
                        "classification_evidence": "사용자 제공 KRA 용어표에서 일,열사병을 HEAT STROKE 단일 질병명으로 확인; 별도 중증도/회복 상태 미확정",
                    }
                components.append({
                    "source_term_id": row["term_id"], "source_raw_text": row["raw_text"],
                    "source_term_frequency": row["frequency"],
                    "source_frequency_is_component_frequency": "no; allocation not available",
                    "source_review_interpretation": kind,
                    "component_ordinal": ordinal, "component_raw_text": component,
                    "duplicate_component_text": "yes" if kind == "two_source_entries_same_text" else "no",
                    "term_kind_candidate": labels["term_kind"],
                    "anatomic_system_candidate": labels["anatomic_system"],
                    "race_impact_prior_candidate": labels["race_impact_prior"],
                    "review_status": "rule_candidate_unreviewed" if labels["review_status"] == "rule_candidate" else "unreviewed",
                    "clinical_severity": "unknown", "rule_ids": labels["rule_ids"],
                    "classification_evidence": labels["classification_evidence"],
                })
        elif kind in SINGLE_CATEGORIES:
            counts["single_phrase_retained"] += 1
            reason = row["review_reason"]
            candidate = {
                "disease_candidate": "yes" if kind == "single_official_heat_stroke_term" else "unreviewed",
                "anatomic_system_candidate": "systemic" if kind == "single_official_heat_stroke_term" else "musculoskeletal",
                "race_impact_prior_candidate": "context_dependent" if kind == "single_official_heat_stroke_term" else "unknown",
                "clinical_severity": "unknown",
                "review_status": "rule_candidate_unreviewed" if kind == "single_official_heat_stroke_term" else "veterinary_review_needed",
                "rule_ids": "R_USER_SUPPLIED_HEAT_STROKE_GLOSSARY" if kind == "single_official_heat_stroke_term" else "R_SINGLE_ANATOMIC_PHRASE_RETAINED",
            }
            singles.append({**row, "retention_reason": reason, **candidate})
            decisions.append({**row, "final_partition_status": "retain_as_one_phrase_no_split", "final_components_json": json.dumps([row["raw_text"]], ensure_ascii=False)})
        else:
            raise AssertionError(f"Unexpected unresolved category: {kind}: {row['raw_text']}")

    assert len(rows) == 3731
    assert counts["split_source_terms"] == 3722
    assert len(components) == 7444
    assert counts["single_phrase_retained"] == 9
    assert len(singles) == 9
    assert len(decisions) == 3731

    for path, items in ((DECISIONS, decisions), (SPLIT, components), (SINGLE, singles)):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(items[0]))
            writer.writeheader()
            writer.writerows(items)

    meta = {
        "source_audit": AUDIT.name, "source_comma_terms": len(rows),
        "split_source_terms": len(components) // 2,
        "split_component_rows": len(components), "retained_single_phrase_terms": len(singles),
        "unresolved_comma_boundary_terms": 0,
        "frequency_policy": "Frequency remains attached to original source term only; no component-level allocation.",
        "user_confirmed_glossary": "일,열사병 (HEAT STROKE), one disease term",
        "anatomy_adjudication": "Seven numeric anatomy-comma phrases retained whole; six are interosseous-ligament conditions with differing location/subtype, one describes proximal metacarpal hypertrophy.",
        "clinical_risk_review_complete": False,
        "source_database_modified": False,
    }
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = [
        "# 진료 원문 쉼표 분리 최종 검토 v3 · 2026-09-26",
        "",
        "## 결론",
        "",
        "사용자가 확인한 KRA 용어표 정의에 따라 `일,열사병`은 쉼표로 나누지 않는 하나의 HEAT STROKE 질병 용어로 처리했다. 해부학 번호를 나열하는 쉼표 7개도 단일 진단명 내부 표기로 유지했다. 이에 따라 쉼표 원문 3,731개의 경계를 모두 처리했고, 판정 대기 경계는 0개다.",
        "",
        "- 두 후보로 분리해 저장: 원문 term 3,722개 → component 7,444행.",
        "- 단일 문구로 유지: term 9개(해부학 열거 7개 + 열사병 용어 2개).",
        "- 전체 원문 판단: `comma_terms_adjudicated_v3_20260926.csv`.",
        "- 분리 후보: `split_comma_components_v3_20260926.csv`.",
        "- 한 문구로 유지한 term: `comma_terms_retained_as_one_phrase_v3_20260926.csv`.",
        "",
        "## 해부학 열거 7개",
        "",
        "6개는 제2·제3 또는 제3·제4 중수골/중족골 사이 골간인대의 염증 또는 염좌·파열을 적은 표현으로 읽힌다. 위치는 좌우와 앞다리(중수골)/뒷다리(중족골), 그리고 병변 표현이 다르다. 나머지 1개 `우제2,4중수골근위부비대`는 오른쪽 앞다리 제2·제4 중수골 근위부 비대를 가리키는 별도 병변 표현이다. 모두 단일 원문 term으로 유지한다.",
        "",
        "## 의미와 빈도 보존",
        "",
        "분리 component는 사람 검토용 후보이며 실제로 서로 다른 두 진료행·질환인지 확정하지 않는다. component 행에는 부모 term의 빈도를 출처 정보로 반복해 기록했으며 component 빈도로 분배한 값이 아니다. 각 행의 `source_frequency_is_component_frequency`를 확인하고 component 행 빈도를 합산하지 않는다.",
        "",
        "이로써 쉼표 경계 정리 작업은 완료했다. 원문만으로 임상 중증도, 현재 회복 상태, 실제 경주성적 영향, 공식 출전 가능 여부를 결정하는 일은 완료되지 않았다. 수의학 검토와 공식 자료 대조가 별도로 필요하다. 운영 DB·Supabase·프론트엔드에는 적용하지 않았다.",
        "",
    ]
    REPORT.write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
