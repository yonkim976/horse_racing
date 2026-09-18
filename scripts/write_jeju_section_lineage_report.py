"""Korean report for the source lineage audit; no feature or model mutation."""
# ruff: noqa: E501

import json

import polars as pl

from scripts.audit_jeju_section_lineage import OUT, ROOT, save


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    missing = pl.read_parquet(OUT / "missing_entry_audit.parquet").filter(
        pl.col("in_v9_probability_population")
    )
    trials = pl.read_parquet(OUT / "trial_evidence.parquet").filter(
        pl.col("target_entry_id").is_in(missing["entry_id"].to_list())
    )
    groups = (
        trials.group_by("record_status", "judgement")
        .len()
        .sort("record_status", "judgement")
        .to_dicts()
    )
    readiness = dict(
        targets=292,
        linked_trial_targets=291,
        trial_rows=547,
        record_status_and_judgement=groups,
        availability_is_not_training_eligibility=True,
        semantics="Trial counts/time already exist in the base model. Positive S1F/G1F/G3F "
        "coverage does not imply all rows usable; nonpositive/invalid rows remain masked.",
        next_experiment="Separate strictly prior trial section/form signals from race section history; "
        "freeze candidate/eligibility rules before training, no name-only linkage.",
    )
    save("trial_readiness.json", readiness)
    text = """# 제주마 구간 결측 원인·주행심사 계보 점검 v10

작성일: 2026-09-16

## 결론

**조사한 자료 범위에서, 기존에 지적한 결측 292건은 과거 실제 경주 이력이 없는 말의 첫 관측 출전이었다. 구간 변수를 만드는 과정에서 값이 누락된 오류는 발견하지 못했다.** 전체 2025년 평가 6,953행의 초반·막판 변수를 재구성했고 저장값과 불일치는 0건이었다.

다만 ‘경주 이력이 없다’와 ‘쓸 수 있는 사전 정보가 전혀 없다’는 다르다. **291두에는 출전 전 주행심사 547건이 있고, 각 말에서 초반·막판 구간시간의 양수 관측을 확인했다.** 기존 모델은 심사 횟수와 최근 유효 총기록을 이미 사용하지만, 해당 심사의 상세 구간 기록을 이번에 살펴본 경주 구간 변수로 사용하지 않는다.

확인된 변수 생성 오류가 없어 기존 데이터와 예측을 수정하지 않았다. 이번 단계는 자료 계보 점검이며 모델 재학습·예측 변경·새 적중률 평가는 모두 0회다. 후속 개선 방향은 주행심사 상세 정보를 별도 사전 변수로 검증하는 것이다.

## 1. 292건과 296건의 차이

| 모집단 | 결측 출전 행 |
|---|---:|
| 전체 평가 715경주 | 296 |
| 확률 오차 평가에서 제외했던 경계 동착 경주 | 4 |
| v9 확률 진단 709경주 | **292** |

292건은 이 표본에서 서로 다른 292두다. 이번 점검은 제외했던 4건도 함께 확인했다. ‘결측’은 과거 초반 상위 3 빈도 또는 최근 3회 출전의 막판 상대속도 중 하나라도 유효값이 없는 경우다.

## 2. 원천 자료까지 추적한 결과

| 원인 | v9 대상 건수 | 판단 |
|---|---:|---|
| 같은 공식 말 ID의 T−2 이전 경주 행이 없음 | 289 | 조사한 원천 자료에 과거 경주 이력 없음 |
| 과거 결과 행은 있으나 미출전 코드 94뿐임 | 3 | 실제 출전 이력에서 제외한 처리가 맞음 |
| 과거 출전 이력이 있는데 변수 생성 중 구간값을 잃음 | 0 | 확인된 변환 오류 없음 |
| 저장 변수와 재계산 값 불일치 | 0 | 전체 6,953행에서 일치 |

이력은 대상 경주일 T−2까지, 같은 공식 말 ID만 연결했다. 하루 전 경주가 시점 제한 때문에 빠진 사례도 이 결측 집단에서는 없었다. 변수 정의상 초반 빈도는 전체 과거 유효 초반 순위, 막판 상대속도는 최근 **3회 출전** 중 유효값 평균이다. ‘최근 유효 기록 3개’로 바꾸어 과거 값을 끌어오지 않았다.

세 건의 제외 이력은 다음과 같다. 코드 94는 기존 봉인 데이터의 미출전 코드 집합에 포함되며 기록시간과 구간값도 없었다.

| 말 | 공식 ID | 이전 결과 행 날짜 | 코드 |
|---|---|---|---:|
| 소나기 | 3104308 | 2025-04-18 | 94 |
| 뉴저지 | 3104811 | 2025-06-21 | 94 |
| 태흥제일 | 3107569 | 2025-09-26 | 94 |

이들을 출전한 것으로 간주해 0초 또는 0점 구간 기록으로 채우면 잘못된 이력이 된다. 미출전 경험 자체를 사용하려면 경주 수행 기록과 분리된 별도 변수로 정의해야 한다.

## 3. 이름으로 연결하면 생길 수 있는 오류

‘백두평정’의 현재 대상 공식 ID는 3104081이다. 동일 이름의 과거 말 3005766에 연결된 경주 행 82개가 원천 자료에 있었다. **이름이 같아도 공식 ID가 다르므로 연결하지 않았다.** 오래된 다른 말의 기록을 붙여 결측을 없애는 처리는 하지 않는다.

현재 동일 ID의 과거 행이 없다는 사실은 확인했지만, 확보되지 않은 자료까지 포함해 생애 최초 출전을 보편적으로 증명한 것은 아니다. 따라서 산출물 원인값은 ‘확보한 자료에서 과거 경주 행 없음’으로 남겼다.

## 4. 주행심사는 대부분 확보돼 있다

| 항목 | 확인된 대상 |
|---|---:|
| T−2 이전 연결된 주행심사 있음 | 291/292두 |
| 해당 291두의 심사 원천 행 | 547건 |
| 양수 총시간이 한 번 이상 있음 | 291두 |
| 양수 초반 S1F 시간이 한 번 이상 있음 | 291두 |
| 양수 최종 G1F 시간이 한 번 이상 있음 | 291두 |
| 양수 최종 G3F 시간이 한 번 이상 있음 | 291두 |
| 기존 저장 심사 횟수와 원천 행 수 불일치 | 0두 |

위 구간시간 표는 **관측 가능성**이다. 모든 심사 행이 학습에 적합하다는 의미는 아니다. 547건의 상태와 원문 판정은 다음과 같다.

| 저장 결과 상태 | 원문 심사 판정 | 행 수 |
|---|---|---:|
"""
    for r in groups:
        text += f"| {r['record_status']} | {r['judgement']} | {r['len']} |\n"
    text += """
총 537건은 정상 완주 상태, 10건은 비양수 결과 상태다. 합격·불합격 판정은 착순이나 완주 여부와 같지 않다. 다음 변수 생성에서 비양수·비정상 시간은 수행 기록에서 제외하고 원래 상태를 별도로 남겨야 한다.

기존 모델의 `trial_count_pre`, `trial_last_valid_time_ms_pre`에는 주행심사 횟수와 최근 유효 총기록이 이미 들어 있다. 이번 발견은 주행심사가 전혀 없었다는 뜻이 아니다. 상세 구간·심사일 간격·여러 심사 사이 변화 등을 경주 기록과 구분해 활용할 여지가 있다는 뜻이다. 심사와 본경주는 목적·거리·경쟁 조건이 다를 수 있어 기록을 동일 척도로 바로 합치지 않는다.

## 5. 연결이 보류된 한 건

대상 말은 **디아즈타임(3104167), 2025-11-01 출전**이다.

- 보유 주행심사 원장에 2025-08-07 제2심사 8번 말의 연결 보류 기록이 있다.
- 보존된 심사 문서 이름은 **천지영웅**, 같은 날짜·심사·번호의 공식 조회 캐시 이름은 **디아즈타임**, 공식 ID는 **3104167**이다.
- 원장 사유는 `horse_name_conflict`다. 원문 문서 해시, 조회 응답 해시와 캐시 행, 연결 보류 원장 행을 대조했다.
- 날짜·번호·공식 ID 외에 연령·성별·조교사·마체중이 일치해 개명 가능성을 검토할 수 있지만, 이번 로컬 자료 점검에서 확정된 개명 이력 증거를 확보한 것은 아니다. 이름 충돌을 임의로 해소하지 않았다.

이 기록은 **연결 후보**로 별도 저장했고 심사 횟수나 시간에 추가하지 않았다. 설령 이후 동일 말로 확인되더라도 주행심사가 생기는 것이며, 과거 본경주 구간 기록의 결측이 사라지는 것은 아니다.

## 6. 검증한 범위

- 전체 평가 6,953행의 두 구간 변수 재계산, 불일치 0건.
- 결측 296건의 T−2 시점·공식 ID·과거 결과 행·주행심사 행 확인.
- 원천 파일 82개의 SHA-256 확인, 저장 원천 행 854개 대조.
- 줄 번호가 있는 경주 JSONL 원본 299행을 DB 정규화 행과 직접 비교.
- 결측 대상 전체의 주행심사 행 555개 확인. 이 중 확률 진단 대상 292두에 대응하는 행은 547개다.
- 동일 이름·다른 ID 사례와 주행심사 연결 보류 후보를 별도 기록.
- 관련 테스트 **21개 통과**. 시점 경계, 같은 ID만 연결, 최근 3회 정의, 미출전 제외, 변수 불일치 탐지, 구간값 범위를 포함한다.
- 별도 검증 스크립트와 최종 파일 해시 점검 결과를 `verification.json`에 저장한다.

기존 봉인 자료·학습 데이터·예측은 변경하지 않았다. 현재 모델의 적중률이 이번 점검으로 올랐다고 보고하지 않는다. 2026년 모델 학습·예측·평가도 수행하지 않았다.

## 7. 수정된 다음 계획

1. **결측 의미를 분리한다.** ‘과거 본경주 없음’, ‘주행심사는 있음’, ‘주행심사 ID 연결 보류’를 구분한다. 경주 이력 결측을 모두 수집 실패로 취급하지 않는다.
2. **주행심사 상세 변수 실험을 고정한다.** 심사 당시 거리·유효 시간·구간 관측 여부를 확인한 뒤 초반과 막판 기록, 출전까지의 간격, 여러 심사의 변화 등을 별도 묶음으로 설계한다. 구간 변수 결측 집단만 골라 학습하지 않고 전체 평가 분모를 유지한다.
3. **기존 주행심사 정보와 추가 효과를 구분한다.** 기존 심사 횟수·총기록을 대조 조건으로 남기고, 상세 구간 추가 효과를 비교한다. 말별 입상·세 마리 집합·정확한 순서를 각각 보고한다.
4. **연결 보류 후보는 따로 검증한다.** 개명 또는 동일 ID를 뒷받침하는 추가 공식 근거가 확보되기 전까지 현재 특징값은 유지한다. 사후 조회 자료의 공개·수정 시점 한계도 기록한다.
5. **현재 선택과 보정 연구 후보를 유지한다.** 기존 HY_R_FORM의 선택과 v9의 보정 연구 후보를 이번 자료 점검 결과만으로 바꾸지 않는다. 최종 후보 고정 후 미사용 기간 검증으로 이어간다.

## 산출물

- 전체 재계산: `all_entry_audit.parquet`
- 결측 원인: `missing_entry_audit.parquet`, `excluded_prior_races.json`
- 주행심사 근거: `trial_evidence.parquet`, `trial_readiness.json`
- 식별자 검토: `same_name_other_id.json`, `unresolved_trial_candidates.json`
- 출처: `source_row_evidence.jsonl`, `source_hashes.json`, `protocol.json`
- 저장 위치: `data/research/jeju_native_section_lineage_v10_20260916/`
- 재검증: `.venv/bin/python -m scripts.verify_jeju_section_lineage`

manifest는 자기 자신과 재검증 때 갱신되는 verification.json을 제외한 산출물의 SHA-256을 보존한다.
"""
    assert (
        summary["feature_reconstruction_mismatches"] == 0 and summary["prior_trial_targets"] == 291
    )
    (OUT / "report.md").write_text(text)
    (ROOT / "docs/JEJU_NATIVE_SECTION_LINEAGE_REPORT_2026-09-16.md").write_text(text)


if __name__ == "__main__":
    main()
