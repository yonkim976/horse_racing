#!/usr/bin/env python3
"""Audit comma-bearing source terms without changing or normalizing them."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "candidate_terms.csv"
OUTPUT = ROOT / "comma_entry_review_20260926.csv"
REPORT = ROOT / "comma_entry_review_report_ko.md"


def review(text: str) -> tuple[int, str, str]:
    """Return literal comma chunks, conservative semantic reading, and reason."""
    pieces = text.split(",")
    n = len(pieces)
    if n == 2 and re.search(r"\d+,\d+", text):
        return n, "single_medical_phrase_internal_anatomic_enumeration", (
            "숫자-숫자 쉼표가 제2·3/제2·4 중수골처럼 한 해부학 명칭 안에 있어, 이 쉼표만으로 진단 두 개라 볼 수 없음"
        )
    if n == 2 and pieces[0].strip() == pieces[1].strip():
        return n, "two_source_entries_same_text", (
            "양쪽 쉼표 조각은 두 번 기록됐지만 글자가 같아 서로 다른 두 질환은 아님"
        )
    if n == 3 and "일" in [x.strip() for x in pieces] and "열사병" in [x.strip() for x in pieces]:
        return n, "two_medical_phrases_plus_unresolved_token", (
            "열사병과 다른 의학 문구는 보이나 단독 '일'의 뜻은 문맥 없이 판정 불가; 세 번째 독립 진단으로 세지 않음"
        )
    if n == 3 and re.search(r"\d+,\d+", text):
        return n, "two_medical_phrases_with_internal_anatomic_enumeration", (
            "첫 문구와 두 번째 진단성 문구가 쉼표로 구분되고, 두 번째 문구 안 숫자열은 해부학적 열거로 읽힘"
        )
    if n == 2:
        return n, "two_distinct_textual_items", (
            "한 개의 쉼표로 두 개의 서로 다른 원문 조각이 구분됨; 각각의 독립 진단 여부는 출처 문맥에서 확인 필요"
        )
    return n, "multiple_or_unresolved_components", (
        "쉼표 조각이 둘보다 많고 알려진 해부학 열거 이외의 경계가 있음; 원문 작성 문맥 확인 필요"
    )


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as f:
        source = list(csv.DictReader(f))
    selected = [r for r in source if "," in r["raw_text"]]
    counts: Counter[str] = Counter()
    frequencies: Counter[str] = Counter()
    output_rows = []
    for row in selected:
        chunks, interpretation, reason = review(row["raw_text"])
        counts[interpretation] += 1
        frequencies[interpretation] += int(row["frequency"])
        output_rows.append({
            "term_id": row["term_id"],
            "raw_text": row["raw_text"],
            "frequency": row["frequency"],
            "literal_comma_chunks": chunks,
            "review_interpretation": interpretation,
            "review_reason": reason,
            "source_text_preserved": "yes",
        })

    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    assert len(selected) == 3731
    assert sum(int(r["frequency"]) for r in selected) == 70262
    assert sum(counts.values()) == len(selected)
    assert sum(frequencies.values()) == 70262
    assert counts["two_distinct_textual_items"] == 3704
    assert counts["single_medical_phrase_internal_anatomic_enumeration"] == 7
    assert counts["two_source_entries_same_text"] == 6
    assert counts["two_medical_phrases_plus_unresolved_token"] == 12
    assert counts["two_medical_phrases_with_internal_anatomic_enumeration"] == 2

    report = [
        "# 쉼표 포함 진료 원문 재검토 · 2026-09-26",
        "",
        "이번 검토는 원문 조각이 몇 개인지와 문구가 독립 항목 두 개처럼 읽히는지를 조사한 것이다. 임상 진단의 정확성이나 각 조각이 별도 진료행인지 확인한 것은 아니다. 원문은 전혀 수정하지 않았다.",
        "",
        "## 전수 구조 결과",
        "",
        f"- 쉼표 포함 고유 원문: {len(selected):,}개; 이 원문들의 진료 슬롯 연결 빈도 합: 70,262건.",
        "- 쉼표를 단순 문자 경계로 세면 두 조각 원문 3,717개, 세 조각 원문 14개다. 그러나 쉼표마다 진단 항목 경계인 것은 아니다.",
        "",
        "| 판독 후보 | 고유 원문 | 연결 빈도 | 해석 |",
        "|---|---:|---:|---|",
        f"| 서로 다른 두 원문 조각 | {counts['two_distinct_textual_items']:,} | {frequencies['two_distinct_textual_items']:,} | 서로 다른 두 문구가 쉼표로 나뉨. 각각 독립 진료 항목인지는 원자료 문맥 확인 필요 |",
        f"| 같은 문구 두 번 | {counts['two_source_entries_same_text']:,} | {frequencies['two_source_entries_same_text']:,} | 쉼표 양쪽이 같은 문구여서 두 번의 텍스트 기록이지 서로 다른 두 질환은 아님 |",
        f"| 진단 하나 안의 해부학 열거 | {counts['single_medical_phrase_internal_anatomic_enumeration']:,} | {frequencies['single_medical_phrase_internal_anatomic_enumeration']:,} | 제2,3중수골 등 숫자 열거가 한 진단명 안에 포함됨 |",
        f"| 의학 문구 둘 + 뜻 불명 '일' | {counts['two_medical_phrases_plus_unresolved_token']:,} | {frequencies['two_medical_phrases_plus_unresolved_token']:,} | 두 진단성 문구 외에 단독 '일' 토큰이 있어 그 뜻은 판정 보류 |",
        f"| 진단 문구 둘, 내부 해부학 열거 포함 | {counts['two_medical_phrases_with_internal_anatomic_enumeration']:,} | {frequencies['two_medical_phrases_with_internal_anatomic_enumeration']:,} | 전체 세 조각처럼 보여도 뒤쪽 쉼표는 제2,3/제2,4중수골 열거에 속함 |",
        "",
        "## 대표적인 예외",
        "",
        "- `좌제2,3중수골골간인대염`, `우제2,4중수골근위부비대` 등 7개 원문은 쉼표가 병명 내부의 뼈 번호를 나열한다. 이 원문은 진단 문구 하나로 판단했다.",
        "- `좌전내측근위종자골염,좌제2,4중수골골절`과 `양요골전측원위단이단성골연골염,양제2,3중수골골간인대염`은 두 개의 진단성 문구가 있고 두 번째 문구 안에 번호 열거가 있다. 단순 split으로는 세 조각이 된다.",
        "- `...,일,열사병` 형태가 12개 있다. `일`을 독립 질병으로 볼 근거가 없어 뜻을 판정하지 않았다. 각 문구에 다른 진단성 표현과 `열사병`은 보이지만, 이 토큰의 원자료 입력 문맥은 추가 확인 대상이다.",
        "- `인푸렌자예방접종,인푸렌자예방접종`, `교돌상,교돌상`처럼 동일 텍스트를 반복한 원문 6개도 있다. 쉼표로 두 칸이 있지만 서로 다른 질환 두 개라고 세면 안 된다.",
        "",
        "## 결론",
        "",
        "따라서 ‘쉼표가 있으니 무조건 두 진단’은 맞지 않는다. 이 자료에서 3,717개는 쉼표 기준으로 두 조각이지만 그중 7개는 단일 병명 안 해부학 열거, 6개는 같은 문구 반복이다. 나머지 3,704개는 서로 다른 두 문구로 보인다. 14개 세 조각 원문 중 2개는 진단 둘과 해부학 열거, 12개는 진단성 문구 둘과 뜻을 확인할 수 없는 `일` 토큰으로 판독했다.",
        "",
        "서로 다른 두 텍스트 조각도 반드시 ‘두 질병’이나 ‘두 번의 진료’를 뜻하지는 않는다. 처치와 병명이 같이 들어갈 수 있고 좌우 부위만 다른 같은 진단일 수 있다. 별도 진료 항목 여부를 확정하려면 원본 화면/필드 정의나 수의사·자료관리자 확인이 필요하다. term별 근거와 빈도는 `comma_entry_review_20260926.csv`에 기록했다.",
        "",
    ]
    REPORT.write_text("\n".join(report), encoding="utf-8")
    metadata = {
        "source_file": "candidate_terms.csv",
        "comma_terms": len(selected),
        "linked_frequency_sum": 70262,
        "interpretation_counts": dict(counts),
        "interpretation_frequency_sums": dict(frequencies),
        "source_text_modified": False,
    }
    (ROOT / "comma_entry_review_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
