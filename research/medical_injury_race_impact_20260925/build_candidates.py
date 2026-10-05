#!/usr/bin/env python3
"""Build a read-only, reproducible candidate review catalog from the local SQLite DB."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


OUT_DIR = Path(__file__).resolve().parent
DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "horse_racing.sqlite3"
RULESET_VERSION = "medical-term-candidates-v1.0.0"

FIELDS = [
    "term_id", "raw_text", "frequency", "term_kind", "anatomic_system",
    "race_impact_prior", "review_status", "clinical_severity",
    "veterinary_review_needed", "classification_evidence", "rule_ids",
    "source_text_preserved", "special_review_flag",
]

CASES = [
    ("좌전지파행", "symptom", "musculoskeletal", "direct_concern", "R_LAMENESS"),
    ("좌요골원위단골편골절", "injury", "musculoskeletal", "direct_concern", "R_STRUCTURAL_INJURY"),
    ("좌중수부계인대염", "injury", "musculoskeletal", "direct_concern", "R_STRUCTURAL_INJURY"),
    ("좌중수부 열창", "injury", "musculoskeletal", "context_dependent", "R_SOFT_TISSUE_INJURY"),
    ("좌각막찰과상", "injury", "eye", "context_dependent", "R_EYE_CONDITION"),
    ("각막염", "disease", "eye", "context_dependent", "R_EYE_CONDITION"),
    ("감기", "disease", "respiratory", "context_dependent", "R_RESPIRATORY_DISEASE"),
    ("인푸렌자예방접종", "prevention", "unknown", "no_injury_signal", "R_PREVENTION"),
    ("정치", "administrative", "unknown", "no_injury_signal", "R_ADMIN"),
    ("재료판매", "administrative", "unknown", "no_injury_signal", "R_ADMIN"),
    ("운동기인성 피로회복", "treatment_or_test", "unknown", "unknown", "R_PROCEDURE"),
    ("운동기인성폐출혈", "unknown", "unknown", "unknown", "R_BLEEDING_HOLD"),
    ("비출혈", "unknown", "unknown", "unknown", "R_BLEEDING_HOLD"),
    ("예방접종,검사", "mixed", "mixed", "unknown", "R_COMPOUND_HOLD"),
    ("낯선표현XYZ", "unknown", "unknown", "unknown", "R_NO_MATCH"),
    ("동물  좌전지파행", "symptom", "musculoskeletal", "direct_concern", "R_LAMENESS"),
]


def classify(raw_text: str) -> dict[str, str]:
    """Apply conservative phrase rules; never split or merge source terms."""
    text = raw_text
    source_prefix = "동물  "
    match_text = text[len(source_prefix):] if text.startswith(source_prefix) else text
    rules: list[str] = []
    prefix_note = ""
    if match_text != text:
        prefix_note = "원문 접두어 '동물  '를 그대로 보존하고 후보 규칙 탐색에서만 접두어 뒤 문구를 참조"
        rules.append("R_SOURCE_PREFIX_PASSTHROUGH")

    if "," in text or "，" in text or "、" in text:
        rules.append("R_COMPOUND_HOLD")
        evidence = "쉼표형 결합 원문 전체를 그대로 유지; 구성 문구를 분리하거나 개별 진단으로 확정하지 않음"
        if any(token in match_text for token in ("폐출혈", "비출혈", "출혈")):
            rules.append("R_BLEEDING_HOLD")
            evidence += "; 출혈 문자열 포함으로 출처별 별도 검증 표시"
        return _result("mixed", "mixed", "unknown", "rule_candidate", True,
                       evidence + ("; " + prefix_note if prefix_note else ""), rules,
                       "bleeding_source_reconciliation" if "R_BLEEDING_HOLD" in rules else "")

    if any(token in match_text for token in ("폐출혈", "비출혈", "출혈")):
        rules.append("R_BLEEDING_HOLD")
        return _result("unknown", "unknown", "unknown", "rule_candidate", True,
                       "출혈 관련 문자열만으로 폐출혈 종류·공식 사건·출전제한을 확정하지 않음" + ("; " + prefix_note if prefix_note else ""),
                       rules, "bleeding_source_reconciliation")

    if "예방접종" in match_text or "백신접종" in match_text:
        rules.append("R_PREVENTION")
        return _result("prevention", "unknown", "no_injury_signal", "rule_candidate", False,
                       "명시적 예방접종 문구; 부상 확인 신호가 아니라는 분류이며 건강·컨디션·경주영향 판단은 아님" + ("; " + prefix_note if prefix_note else ""), rules, "")

    if match_text in {"정치", "재료판매", "진단서 발급", "등록", "서류발급"}:
        rules.append("R_ADMIN")
        return _result("administrative", "unknown", "no_injury_signal", "rule_candidate", False,
                       "명시된 행정·비진단 항목; 부상 확인 신호가 아니라는 뜻" + ("; " + prefix_note if prefix_note else ""), rules, "")

    # Anatomical cues are used only where the whole phrase clearly names a body site.
    if any(token in match_text for token in ("각막", "안구", "눈")):
        system = "eye"
        if any(token in match_text for token in ("찰과상", "열창", "외상", "손상", "상처")):
            rules.append("R_EYE_CONDITION")
            return _result("injury", system, "context_dependent", "rule_candidate", True,
                           "눈 부위의 상처·손상 표현; 깊이·시력 영향·회복 상태 불명" + ("; " + prefix_note if prefix_note else ""), rules, "")
        if any(token in match_text for token in ("염", "염증", "이상", "질환")):
            rules.append("R_EYE_CONDITION")
            return _result("disease", system, "context_dependent", "rule_candidate", True,
                           "눈 부위 질환 표현; 임상 중증도·현재 상태 미확정" + ("; " + prefix_note if prefix_note else ""), rules, "")

    if "파행" in match_text:
        rules.append("R_LAMENESS")
        return _result("symptom", "musculoskeletal", "direct_concern", "rule_candidate", True,
                       "파행은 운동 관련 증상 신호; 원인과 중증도는 원문만으로 확정하지 않음" + ("; " + prefix_note if prefix_note else ""), rules, "")

    if any(token in match_text for token in ("골절", "건염", "건초염", "계인대", "인대손상", "인대염", "염좌", "골막염", "파열")):
        rules.append("R_STRUCTURAL_INJURY")
        return _result("injury", "musculoskeletal", "direct_concern", "rule_candidate", True,
                       "뼈·건·인대 또는 구조 손상 표현; 현재 손상 정도·회복 여부는 미확정" + ("; " + prefix_note if prefix_note else ""), rules, "")

    if any(token in match_text for token in ("찰과상", "열창", "교돌상", "답창", "창상", "좌상", "외상", "상처")):
        rules.append("R_SOFT_TISSUE_INJURY")
        if any(token in match_text for token in ("지", "수부", "족부", "구절", "계부", "제부", "중수골", "비절")):
            system = "musculoskeletal"
        elif any(token in match_text for token in ("찰과상", "열창", "답창", "창상", "상처")):
            system = "skin"
        else:
            system = "unknown"
        return _result("injury", system, "context_dependent", "rule_candidate", True,
                       "외상·연부조직 상처 표현; 위치·깊이·기능 영향·회복 상태 불명" + ("; " + prefix_note if prefix_note else ""), rules, "")

    if any(token in match_text for token in ("근육통", "요배통", "부종", "통증", "동통", "근육염", "산통", "설사")):
        rules.append("R_SYMPTOM_CONTEXT")
        system = "musculoskeletal" if any(token in match_text for token in ("지", "수부", "족부", "구절", "요배", "근육", "관절")) else "systemic"
        return _result("symptom", system, "context_dependent", "rule_candidate", True,
                       "증상 표현으로 보수 분류; 원인·지속기간·중증도·회복 상태 불명" + ("; " + prefix_note if prefix_note else ""), rules, "")

    if "감기" in match_text or "기관지염" in match_text or "호흡기질환" in match_text:
        rules.append("R_RESPIRATORY_DISEASE")
        return _result("disease", "respiratory", "context_dependent", "rule_candidate", True,
                       "호흡기 질환 표현; 임상 중증도·현재 증상·회복 상태 불명" + ("; " + prefix_note if prefix_note else ""), rules, "")

    if any(token in match_text for token in ("피부염", "피부병", "담마진", "진드기성외이염")):
        rules.append("R_SKIN_DISEASE")
        return _result("disease", "skin", "context_dependent", "rule_candidate", True,
                       "피부 질환 표현; 정도·위치·현재 상태 불명" + ("; " + prefix_note if prefix_note else ""), rules, "")

    procedure_tokens = ("피로회복", "수액처치", "물리치료", "충격파", "진정(", "장제", "술후처치", "거세술", "거세", "수술", "발치", "구충", "검사", "검진", "마체검사", "치료(", "침치료")
    if any(token in match_text for token in procedure_tokens):
        rules.append("R_PROCEDURE")
        return _result("treatment_or_test", "unknown", "unknown", "rule_candidate", True,
                       "처치·검사 표현만으로 적응증, 부상, 경주영향을 역추정하지 않음" + ("; " + prefix_note if prefix_note else ""), rules, "")

    if any(token in match_text for token in ("염", "염증", "질환", "증", "감염", "성 식욕부진")):
        rules.append("R_DISEASE_GENERAL")
        system = "musculoskeletal" if any(token in match_text for token in ("지", "구절", "관절", "골", "근육", "건", "인대", "제염")) else "unknown"
        return _result("disease", system, "context_dependent", "rule_candidate", True,
                       "명시적 질환성 어미·표현으로 후보 분류; 병명·중증도·현재 상태는 검토 필요" + ("; " + prefix_note if prefix_note else ""), rules, "")

    rules.append("R_NO_MATCH")
    return _result("unknown", "unknown", "unknown", "unreviewed", True,
                   "적용 가능한 보수적 규칙 없음; 원문만으로 판정 보류" + ("; " + prefix_note if prefix_note else ""), rules, "")


def _result(kind, system, impact, status, vet_needed, evidence, rules, special):
    return {
        "term_kind": kind,
        "anatomic_system": system,
        "race_impact_prior": impact,
        "review_status": status,
        "clinical_severity": "unknown",
        "veterinary_review_needed": "yes" if vet_needed else "no_for_term_classification_only",
        "classification_evidence": evidence,
        "rule_ids": ";".join(rules),
        "source_text_preserved": "yes",
        "special_review_flag": special,
    }


def run_self_check() -> None:
    failures = []
    for text, kind, system, impact, rule in CASES:
        out = classify(text)
        got = (out["term_kind"], out["anatomic_system"], out["race_impact_prior"])
        want = (kind, system, impact)
        prefix_rule_missing = text.startswith("동물  ") and "R_SOURCE_PREFIX_PASSTHROUGH" not in out["rule_ids"].split(";")
        if got != want or rule not in out["rule_ids"].split(";") or prefix_rule_missing:
            failures.append({"raw_text": text, "expected": want, "actual": got, "rules": out["rule_ids"]})
    if failures:
        raise SystemExit(json.dumps(failures, ensure_ascii=False, indent=2))


def sha256_rows(rows) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update("\x1f".join("" if x is None else str(x) for x in row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def build(db_path: Path) -> None:
    run_self_check()
    con = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    terms = con.execute("""
        SELECT t.id, t.raw_text, COUNT(d.horse_medical_id) AS frequency
        FROM medical_diagnosis_terms AS t
        LEFT JOIN horse_medical_diagnoses AS d ON d.term_id = t.id
        GROUP BY t.id, t.raw_text
        ORDER BY t.id
    """).fetchall()
    if not terms:
        raise SystemExit("No terms found")
    term_source_hash = sha256_rows((r["id"], r["raw_text"]) for r in terms)
    link_hash = sha256_rows(con.execute("SELECT horse_medical_id, source_slot, term_id FROM horse_medical_diagnoses ORDER BY horse_medical_id, source_slot"))
    medical_rows = con.execute("SELECT COUNT(*) FROM horse_medical").fetchone()[0]
    links = con.execute("SELECT COUNT(*) FROM horse_medical_diagnoses").fetchone()[0]
    candidates = []
    for row in terms:
        candidate = {"term_id": row["id"], "raw_text": row["raw_text"], "frequency": row["frequency"]}
        candidate.update(classify(row["raw_text"]))
        candidates.append(candidate)

    with (OUT_DIR / "candidate_terms.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(candidates)

    with (OUT_DIR / "rule_validation_cases.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["raw_text", "expected_term_kind", "expected_anatomic_system", "expected_race_impact_prior", "expected_rule_id", "result", "test_purpose"])
        for text, kind, system, impact, rule in CASES:
            out = classify(text)
            w.writerow([text, kind, system, impact, rule, "pass", out["classification_evidence"]])

    equipment_summary = con.execute("""
        SELECT COUNT(*) AS rows_total,
               SUM(CASE WHEN bleeding_count IS NOT NULL THEN 1 ELSE 0 END) AS count_rows,
               SUM(CASE WHEN bleeding_date_raw IS NOT NULL THEN 1 ELSE 0 END) AS date_rows,
               SUM(CASE WHEN illness_note IS NOT NULL THEN 1 ELSE 0 END) AS illness_note_rows
        FROM entry_equipment
    """).fetchone()
    equipment_dist = [dict(r) for r in con.execute("""
        SELECT bleeding_count, COUNT(*) AS entry_rows
        FROM entry_equipment WHERE bleeding_count IS NOT NULL
        GROUP BY bleeding_count ORDER BY bleeding_count
    """)]
    bleeding_terms = [dict(r) for r in con.execute("""
        SELECT t.id AS term_id, t.raw_text, COUNT(d.horse_medical_id) AS frequency
        FROM medical_diagnosis_terms t JOIN horse_medical_diagnoses d ON d.term_id=t.id
        WHERE t.raw_text LIKE '%출혈%' GROUP BY t.id, t.raw_text ORDER BY frequency DESC, t.id
    """)]
    counts = {key: dict(Counter(row[key] for row in candidates)) for key in ("term_kind", "anatomic_system", "race_impact_prior", "review_status")}
    metadata = {
        "ruleset_version": RULESET_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_db_path_argument": str(db_path),
        "source_db_bytes": db_path.stat().st_size,
        "source_db_sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
        "term_catalog_rows": len(terms),
        "medical_diagnosis_link_rows": links,
        "horse_medical_rows": medical_rows,
        "term_catalog_sha256_id_raw_text_ordered": term_source_hash,
        "term_links_sha256_ordered": link_hash,
        "classification_counts": counts,
        "validation_case_count": len(CASES),
        "validation_status": "passed" if len(CASES) else "not_run",
        "entry_equipment": dict(equipment_summary),
        "entry_equipment_bleeding_count_distribution_entry_rows": equipment_dist,
        "medical_term_raw_text_with_bleeding": bleeding_terms,
        "read_only_source_query": True,
    }
    (OUT_DIR / "source_and_run_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rule_catalog = {
        "ruleset_version": RULESET_VERSION,
        "principle": "Exact source text is retained; any phrase rule generates an unreviewed candidate, not a diagnosis, severity, performance effect, or eligibility decision.",
        "rules": {
            "R_COMPOUND_HOLD": "Comma-like separator in original: preserve whole term; mixed kind/system, race-impact unknown; never split.",
            "R_BLEEDING_HOLD": "Any 출혈 string: preserve unknown and route for source reconciliation; not an official pulmonary-bleeding event.",
            "R_SOURCE_PREFIX_PASSTHROUGH": "For matching only, inspect text after exact '동물  ' prefix; preserve raw text, term_id and frequency independently.",
            "R_PREVENTION": "Explicit 예방접종/백신접종: prevention and no_injury_signal; not health or no-performance-effect evidence.",
            "R_ADMIN": "Small exact allowlist of administrative phrases only; no_injury_signal is not a health judgment.",
            "R_EYE_CONDITION": "Explicit eye-site words with injury or disease phrase; context-dependent pending exam.",
            "R_LAMENESS": "파행 is a symptom with direct concern; cause and severity remain unknown.",
            "R_STRUCTURAL_INJURY": "Explicit bone/tendon/ligament/structural terms; direct concern, severity/recovery unknown.",
            "R_SOFT_TISSUE_INJURY": "Explicit wound/trauma terms; context-dependent, site only when phrase supports it.",
            "R_SYMPTOM_CONTEXT": "Explicit symptom vocabulary; cause, duration and severity unknown.",
            "R_RESPIRATORY_DISEASE": "Explicit respiratory illness term; context-dependent and current status unknown.",
            "R_SKIN_DISEASE": "Explicit skin disease phrase; context-dependent and current status unknown.",
            "R_PROCEDURE": "Treatment/test vocabulary alone; indication and race impact unknown.",
            "R_DISEASE_GENERAL": "Limited disease-like vocabulary; term and site remain candidates requiring review.",
            "R_NO_MATCH": "No conservative rule matched: retain unknown and unreviewed."
        },
        "validation_cases_file": "rule_validation_cases.csv",
        "rule_source": "build_candidates.py"
    }
    (OUT_DIR / "rule_catalog.json").write_text(json.dumps(rule_catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(candidates, metadata)
    con.close()


def write_report(rows, metadata):
    kind = metadata["classification_counts"]["term_kind"]
    impacts = metadata["classification_counts"]["race_impact_prior"]
    status = metadata["classification_counts"]["review_status"]
    top = sorted(rows, key=lambda r: (-r["frequency"], r["term_id"]))[:30]
    bleeding = metadata["medical_term_raw_text_with_bleeding"]
    dist = metadata["entry_equipment_bleeding_count_distribution_entry_rows"]
    lines = [
        "# 진료 원문 부상·경주 영향 분류 후보 및 검증 보고서",
        "",
        "생성물은 임상 진단, 공식 출전 가능 판정, 검증된 경주 성적 효과 추정치가 아니다. 전체 5,397개 고유 원문을 원문 그대로 보존한 검토 후보 연구 산출물이다.",
        "",
        "## 입력과 재현성",
        "",
        f"- 입력 DB: `{metadata['source_db_path_argument']}` (SQLite 읽기 전용 연결)",
        f"- DB SHA-256: `{metadata['source_db_sha256']}`",
        f"- 원문 term 수: {metadata['term_catalog_rows']:,}; horse_medical 원행 수: {metadata['horse_medical_rows']:,}; 원문 슬롯 연결 수: {metadata['medical_diagnosis_link_rows']:,}",
        f"- term 카탈로그 SHA-256: `{metadata['term_catalog_sha256_id_raw_text_ordered']}`",
        f"- term 연결 SHA-256: `{metadata['term_links_sha256_ordered']}`",
        f"- 규칙 버전: `{metadata['ruleset_version']}`; 고정 검증 사례: {metadata['validation_case_count']}개, 결과: {metadata['validation_status']}",
        "- 재생성: `python3 research/medical_injury_race_impact_20260925/build_candidates.py --db data/horse_racing.sqlite3`",
        "- 주요 파일: `candidate_terms.csv` (term별 결과), `rule_validation_cases.csv`, `rule_catalog.json`, `source_and_run_metadata.json`.",
        "",
        "## 구분 원칙",
        "",
        "- `race_impact_prior`는 원문 문구가 주는 검토 우선 신호다. 임상 중증도, 실제 성적 효과, 공식 출전 자격과 별도다.",
        "- 모든 행에서 `clinical_severity=unknown`. 분류가 `no_injury_signal`이어도 건강함·경주 영향 없음 판정이 아니다.",
        "- 파행은 원인이 확정되지 않은 증상이다. 구조 손상(골절·건·인대 등)은 직접 우려 후보, 외상·눈 질환·통증 등은 상황 의존 후보로 분류하되 원문만으로 현재 상태를 확정하지 않는다.",
        "- 예방접종과 제한된 명시 행정어만 `no_injury_signal`로 표시한다. 처치·검사는 적응증을 역추정하지 않고 영향은 `unknown`으로 둔다.",
        "- 쉼표 포함 원문은 `mixed / unknown` 후보로 그대로 유지한다. 분리·동의어 통합·맞춤법 정규화는 하지 않는다. `동물  ` 접두어도 원문과 term_id를 유지한다.",
        "- `veterinary_review_needed=yes`는 사람 검토를 권하는 신호이며 승인된 진단이 아니다. 공식 출전 가능성은 이 산출물에서 판정하지 않는다.",
        "",
        "## 후보 분포",
        "",
        "### term_kind",
        "",
    ]
    lines += [f"- `{k}`: {v:,}개" for k, v in sorted(kind.items())]
    lines += ["", "### race_impact_prior", ""]
    lines += [
        "요청한 검토 후보와 값의 대응: `direct_concern` = 경주에 직접 영향 우려, `context_dependent` = 상황에 따라 영향, `no_injury_signal` = 부상 신호 아님, `unknown` = 판정 보류. 이는 관찰된 성적 효과의 등급이 아니다.",
        "",
    ]
    lines += [f"- `{k}`: {v:,}개" for k, v in sorted(impacts.items())]
    lines += ["", "### review_status", ""]
    lines += [f"- `{k}`: {v:,}개" for k, v in sorted(status.items())]
    lines += ["", "규칙 후보는 전수 확정 분류가 아니다. `unknown`은 잘못된 긍정 신호보다 명시적 보류를 택한 값이다.", "", "## 빈도 상위 30개 사례", "", "| term_id | 빈도 | 원문 | 후보 종류 | 계통 | 우려 prior | 상태 |", "|---:|---:|---|---|---|---|---|"]
    insert_at = lines.index("## 빈도 상위 30개 사례")
    lines[insert_at:insert_at] = [f"해석상 보류(`race_impact_prior=unknown`)는 {impacts.get('unknown', 0):,}개 term이고, 규칙 매칭 없이 미분류(`review_status=unreviewed`)인 term은 {status.get('unreviewed', 0):,}개다. 쉼표 결합 {kind.get('mixed', 0):,}개도 mixed 표지만 했으며 개별 진단과 위험도는 보류했다.", ""]
    for r in top:
        text = r["raw_text"].replace("|", "\\|")
        lines.append(f"| {r['term_id']} | {r['frequency']:,} | {text} | {r['term_kind']} | {r['anatomic_system']} | {r['race_impact_prior']} | {r['review_status']} |")
    lines += [
        "",
        "상위 사례는 행정·처치·예방접종 결합문과 질환·증상이 섞여 있다. 빈도는 해당 용어가 원문 슬롯에 연결된 횟수이며 독립 사건 수나 말 수가 아니다. 특히 진료 원행에 `동물  ` 접두어가 붙은 별도 term은 접두어가 없는 term과 빈도를 합치지 않았다.",
        "",
        "## 규칙 검증과 위험 오분류",
        "",
        f"`rule_validation_cases.csv`의 {metadata['validation_case_count']}개 고정 사례 검사가 모두 통과했다. 사례에는 파행, 골절, 계인대, 피부·눈 상처, 각막염, 감기, 예방접종, 행정·처치 문구, 폐출혈·비출혈, 쉼표 결합문, 미인식 문구, `동물  ` 접두어 원문이 포함된다. 이 검사는 규칙 동작의 회귀 검사이지 임상 정확도 검증이나 5,397개 수동 판독의 대체가 아니다.",
        "",
        "위험한 오분류를 줄이기 위해 `파행`을 확정 질환으로, `비출혈`을 공식 폐출혈로, 처치명을 부상 확정으로 해석하지 않는다. `운동기인성폐출혈`도 단일 원문만으로 공식 사건·횟수·제재를 확정하지 않는다. 넓은 질환 어미 규칙은 후보를 만들 뿐이며 계통 또는 중증도는 임상 검토 대상이다. 규칙에 없는 표현은 unknown으로 남는다.",
        "",
        "## 폐출혈 별도 검증안",
        "",
        f"- 의료 원문 중 `출혈`을 포함하는 고유 term은 {len(bleeding)}개다. term별 슬롯 연결 빈도는 메타데이터 JSON에 있으며 원문은 보존했다.",
        f"- `entry_equipment`에는 {metadata['entry_equipment']['rows_total']:,}개 출전표 행이 있고 `bleeding_count` 비결측 {metadata['entry_equipment']['count_rows']:,}행, `bleeding_date_raw` 비결측 {metadata['entry_equipment']['date_rows']:,}행이다. 이 수치는 경주 행 수이지 독립 출혈 사건 수가 아니다.",
        "- 저장된 `bleeding_count` 값별 출전표 행 수: " + ", ".join(f"{x['bleeding_count']}회 표기 {x['entry_rows']:,}행" for x in dist) + ".",
        "- 대조 절차: (1) 말 식별자와 원문 진료일/수집시각을 보존하고, (2) 출전표의 `bleeding_date_raw`를 원문 그대로 검토하면서 연속 출전표의 누적 `bleeding_count`를 사건으로 재합산하지 않고, (3) KRA 심판·수의사 공식 처분 및 경주별 문서를 날짜·말·경주로 대조하고, (4) 불일치는 출처별 원문과 불확실성을 그대로 기록한다. `비출혈`은 자동으로 운동기인성 폐출혈 사건이 되지 않는다.",
        "- 현재 로컬 스키마에서 확인한 공식 분리 필드는 진료 문구, 출전표 정보, 출전 취소 사유(`race_scratches.reason`)다. 수의사·심판의 공식 폐출혈 제재 레지스트리와 공개 시각은 확인되지 않았으므로 별도 원본 확보와 사람 대조가 필요하다.",
        "",
        "## 공식 기준 참고",
        "",
        "- KRA 질병용어검색은 견·관파행을 병명보다 증상성 표현으로 설명하고 정밀진단으로 원인을 확인해야 한다고 안내한다. 이 원칙을 파행 후보의 `symptom` 분류에 반영했다: [KRA 질병용어검색](https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do?pageIndex=2).",
        "- 2026 제주 시행계획은 경주 중 폐출혈의 통산 발생 횟수와 최근 2년 발생 기준에 따른 출전정지·주행심사, 마체이상 시 수의사 진단 및 심판위원 판단, 마체검사 불합격/미검사 조치를 별도 규정한다. 이는 진료 원문 분류와 출전 자격이 다른 자료·판정이라는 점을 뒷받침한다: [KRA 2026 제주 경마시행계획, 25–26쪽](https://race.kra.co.kr/down/raceplan2026_jeju.pdf). 지역과 연도별 규정 적용은 다시 확인해야 한다.",
        "- KRA 출전마처분제도는 질병·사고에 따른 출전취소, 경주제외, 출발제외, 주행중지 절차를 별도 설명한다: [KRA 출전마처분제도](https://race.kra.co.kr/raceguide/RaceTakePartHorseCancleService.do?Act=06&Sub=3&meet=2).",
        "",
        "## 성적 분석 및 시점 누수 방지",
        "",
        "향후 연관성을 보더라도 진료일(`clinic_date_local`), 최초 공개 가능 시각(현재 미확인), 우리 수집시각(`observed_at_ms`), 경주일(`race_date_local`)을 별도 필드로 다뤄야 한다. 수집시각은 최초 공개 증거가 아니다. 공개 가능 시각을 확인할 수 없는 과거 진료를 라이브 예측 백테스트의 입력으로 쓰면 안 된다. 성능 차이는 교란과 선택 편향을 고려한 연관성으로 표현하고 인과효과로 부르지 않는다. 임상 중증도·공식 출전자격·실제 성적 효과를 하나의 등급이나 점수로 합치지 않는다.",
        "",
        "## 다음 단계 결정",
        "",
        "### 자동 분류 가능",
        "",
        "- 후보 생성 및 재현 가능한 문구별 빈도 집계.",
        "- 예방접종, 일부 명시 행정어, 파행, 명시 구조손상 및 명확한 쉼표 결합 여부를 검토 큐로 보내는 제한적 규칙 적용.",
        "- 모든 원문 보존, 분류 근거·규칙 버전·입력 해시 기록.",
        "",
        "### 사람 검토 필요",
        "",
        "- `direct_concern` 및 `context_dependent` 후보 전부의 수의학적 확인, 특히 구조 손상·반복 증상·눈/피부 외상.",
        "- mixed/복합문·낯선 용어·일반 질환 어미 후보의 원문별 판독과 해부학 계통 확인.",
        "- 폐출혈 term, 출전표 누적 횟수/날짜, 공식 처분 근거의 말·날짜별 대조.",
        "",
        "### 현 자료로 판정 불가",
        "",
        "- 원문만으로 임상 중증도, 회복 여부, 실제 성적 영향 및 공식 출전 가능 여부.",
        "- 과거 기록의 KRA 최초 공개 시각과 라이브 시점 사용 가능성.",
        "- 이 보고서의 규칙 후보가 실제 경주성과를 예측하는지 또는 인과적으로 영향을 주는지.",
        "",
        "운영 적용 전에 승인된 분류 용어집과 수의사 판독자, `veterinary_reviewed` 상태의 근거·감사 절차, 공식 출전 제한 원천 및 공개시각 데이터, 모델 연결·롤백 기준을 정해야 한다. 이번 산출물은 신규 연구 폴더에만 생성했으며 운영 DB·Supabase·프론트엔드에는 쓰지 않았다.",
        "",
    ]
    (OUT_DIR / "report_ko.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        run_self_check()
        print(f"{len(CASES)} classification cases passed")
        return
    build(args.db)
    print(f"Wrote candidate catalog and report to {OUT_DIR}")


if __name__ == "__main__":
    main()
