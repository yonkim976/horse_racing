#!/usr/bin/env python3
"""Re-audit comma-bearing terms using the supplied KRA heat-stroke definition."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from audit_comma_entries import review as review_v1

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "candidate_terms.csv"
OUTPUT = ROOT / "comma_entry_review_v2_20260926.csv"
REPORT = ROOT / "comma_entry_review_report_v2_20260926.md"
METADATA = ROOT / "comma_entry_review_metadata_v2_20260926.json"
HEAT_STROKE_TERM = "일,열사병"
ANIMAL_PREFIX = "동물  "


def review(raw: str) -> tuple[int, str, str, list[str]]:
    body = raw[len(ANIMAL_PREFIX):] if raw.startswith(ANIMAL_PREFIX) else raw
    if body == HEAT_STROKE_TERM:
        return 2, "single_official_heat_stroke_term", (
            "사용자가 제시한 KRA 용어 정의에서 '일,열사병'은 HEAT STROKE 한 용어로 제시됨; 내부 쉼표로 분리하지 않음"
        ), [raw]
    if HEAT_STROKE_TERM in body:
        before, after = body.split(HEAT_STROKE_TERM, 1)
        parts = []
        if before:
            assert before.endswith(",")
            parts.append(before[:-1].strip())
        heat = HEAT_STROKE_TERM
        if raw.startswith(ANIMAL_PREFIX) and not before:
            heat = ANIMAL_PREFIX + heat
        parts.append(heat)
        if after:
            assert after.startswith(",")
            parts.append(after[1:].strip())
        return 2, "heat_stroke_term_with_other_phrase", (
            "확인된 단일 질병명 '일,열사병'을 보존하고 그 앞/뒤의 바깥 쉼표에서만 나눔"
        ), parts

    chunks, interpretation, reason = review_v1(raw)
    if interpretation == "two_medical_phrases_plus_unresolved_token":
        raise AssertionError(f"Unexpected unresolved heat-stroke case: {raw}")
    if interpretation == "two_medical_phrases_with_internal_anatomic_enumeration":
        return chunks, interpretation, reason, raw.split(",", 1)
    return chunks, interpretation, reason, raw.split(",")


def main() -> None:
    with SOURCE.open(encoding="utf-8-sig", newline="") as f:
        source = list(csv.DictReader(f))
    rows = [r for r in source if "," in r["raw_text"]]
    counts, freqs = Counter(), Counter()
    out = []
    component_map = {}
    for row in rows:
        n, interpretation, reason, parts = review(row["raw_text"])
        assert all(p.strip() for p in parts)
        counts[interpretation] += 1
        freqs[interpretation] += int(row["frequency"])
        component_map[row["raw_text"]] = parts
        out.append({
            "term_id": row["term_id"], "raw_text": row["raw_text"],
            "frequency": row["frequency"], "literal_comma_chunks": n,
            "review_interpretation": interpretation, "review_reason": reason,
            "component_proposals_json": json.dumps(parts, ensure_ascii=False),
        })

    assert len(rows) == 3731
    assert sum(int(r["frequency"]) for r in rows) == 70262
    assert counts["two_distinct_textual_items"] == 3702
    assert counts["two_source_entries_same_text"] == 6
    assert counts["two_medical_phrases_with_internal_anatomic_enumeration"] == 2
    assert counts["heat_stroke_term_with_other_phrase"] == 12
    assert counts["single_official_heat_stroke_term"] == 2
    assert counts["single_medical_phrase_internal_anatomic_enumeration"] == 7

    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)

    report = [
        "# 쉼표 포함 진료 원문 재검토 v2 · 2026-09-26",
        "",
        "사용자가 제공한 KRA 용어 설명에서 `일,열사병 (HEAT STROKE)`가 한 용어로 제시된 점을 반영했다. 따라서 이 용어 안의 쉼표는 항목 구분자로 보지 않는다.",
        "",
        "## 전수 구조 결과",
        "",
        "- 쉼표 포함 고유 원문: 3,731개; 원문 슬롯 연결 빈도 합: 70,262건.",
        "- 구분 후보: 서로 다른 두 문구 3,702개, 동일 문구 반복 6개, 해부학 내부 쉼표를 포함한 진단 문구 쌍 2개, 확인된 열사병 문구와 다른 문구가 함께 있는 12개.",
        "- 단일 용어로 유지: KRA 용어 `일,열사병`(일반 표기 및 `동물  ` 접두 표기) 2개. 내부 쉼표는 분리하지 않는다.",
        "- 사용자 확인 대기: 병명 안 해부학 번호를 쉼표로 이은 7개. 이들은 단일 진단 문구로 보이지만 후보 분리에서 제외했다.",
        "",
        "| 검토 결과 | 고유 원문 | 원문 연결 빈도 |",
        "|---|---:|---:|",
    ]
    for k, n in counts.most_common():
        report.append(f"| `{k}` | {n:,} | {freqs[k]:,} |")
    report += [
        "",
        "## `일,열사병`이 포함된 원문 처리",
        "",
        "`일,열사병`만 있는 term 2개(일반 표기 1개와 `동물  ` 접두어 표기 1개)는 각각 하나의 열사병 용어로 유지한다. 다른 문구가 붙은 12개는 확인된 열사병 용어 내부를 자르지 않고, 바깥 경계에서 두 후보 성분으로 나눴다. 예: `우전지파행,일,열사병` → `우전지파행` + `일,열사병`; `일,열사병,외상기타` → `일,열사병` + `외상기타`.",
        "",
        "## 생성 파일과 주의점",
        "",
        "- `comma_entry_review_v2_20260926.csv`: 3,731개 원문 전체와 판정, 이유, 후보 성분 JSON.",
        "- `split_comma_components_v2_20260926.csv`: 구분 후보 3,722개 원문을 두 component 행으로 펼친 결과.",
        "- `comma_terms_needing_confirmation_v2_20260926.csv`: 확인 대기 7개 원문(해부학 숫자 열거).",
        "- `comma_terms_retained_as_single_term_v2_20260926.csv`: 확인된 열사병 단일 용어 2개.",
        "- component 행의 부모 빈도는 출처 메타데이터다. 각 성분의 개별 발생 빈도로 배분하거나 합산하면 안 된다. 실제 두 진료행/두 질병인지도 원문 필드 정의 없이는 확정할 수 없다.",
        "- v1 산출물과 원본 DB는 보존했다. 이 v2 결과도 검토용이며 운영 DB·Supabase·프론트엔드에 적용하지 않았다.",
        "",
    ]
    REPORT.write_text("\n".join(report), encoding="utf-8")
    metadata = {
        "source_file": SOURCE.name,
        "definition_source": "User-provided KRA glossary entry: 일,열사병 (HEAT STROKE)",
        "comma_terms": len(rows), "frequency_sum": 70262,
        "interpretation_counts": dict(counts),
        "interpretation_frequency_sums": dict(freqs),
    }
    METADATA.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
