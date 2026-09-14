# E8-A H1/H2 독립 재검증 — 합성 최소 경로 승인

판정: **H1/H2 보완 승인. E8-A 합성 offline 최소 경로의 보완을 종료한다.** 이번 범위에서 추가 차단 결함은 발견하지 않았다. 실제 수집·F_t feature·실전 모델·운영 적격까지 승인하는 것은 아니며 기존 `not_activated` 상태를 유지한다.

## 독립 반례 및 정상 경로

새 구현을 직접 호출하되 제출 runner를 실행하지 않고 임시 저장소에서 clock 순서와 입력을 구성했다. 이전 v2의 fixture 생성 함수만 재사용했으며 판정과 원장 확인은 별도로 수행했다.

- **H1 관측/field/snapshot/prediction:** 네 단계 모두 insert 뒤 ack가 역행하고 다시 회복하는 시퀀스에서 예외로 거부됐다. 각 단계 pending 1개, 해당 ack/admission 0개였다. 새 store 인스턴스로 재시작해도 승인 기록은 없었다.
- **H2 cutoff+1 및 예정 출발+1ms:** snapshot pending 생성 이전 거부. 선언값을 clamp하지 않았다.
- **H2 cutoff−1:** 정확시각 field 뒤 계산이 끝나는 현재 계약에서는 계산 완료보다 빠르므로 하한 위반으로 거부됐다.
- **정상 cutoff equal:** snapshot과 prediction 모두 accepted. 예정 출발 뒤 동일 prediction 재시도는 같은 hash를 반환했고, 새 model 식별자의 늦은 prediction은 거부됐다.
- **기존 회귀:** 늦은 field 완료는 late_ineligible, 옛 출전표 선택은 superseded, 최신 유효 정정 선택은 `(7,11)`만 봉인, 원문과 다른 합성 feature 값은 거부됐다. 기존 R1–R4 회귀 테스트도 전체 검사에 포함됐다.

코드의 샘플별 clock 검사와 admission payload 하한 검사가 함께 적용되는 것을 확인했다. 미래 declared feature availability의 cutoff 상한 검사도 실제 생성 경로 앞에 있다.

## 제출 artifact 독립 대조

제출 SQLite는 read-only로만 열었다. 평가용 결과나 운영 DB를 조회하지 않았다.

| 항목 | 확인 결과 |
|---|---|
| 보존 경로 | 27개 전후 SHA256 일치 |
| 신규 source/계약/참조 | 5개 SHA256 일치 |
| 출력 | 13개 SHA256 일치 |
| 합성 원장 | 6개 SQLite, 총 28개 이벤트 |
| 원장 검증 | payload hash, 이전 hash chain, raw 바이트, 참조 존재·순서, 제출 admission ack 하한·상한 일치 |
| 정상 합성 feature | 원문에서 값·키·결과 hash 독립 재계산 일치 |
| 상위 E7-B | 보존 112개 및 출력 68개 경로 hash 일치 |

전체 `.venv/bin/python -m pytest -q`는 **611 passed, 2 warnings**, 30.70초였다. console pytest는 이번 재검증에서 반복 실행하지 않았다. 관련 새 Python 3개 파일 Ruff check/format은 통과했다. 전체 diff-check에는 기존 `src/horse_racing/web/racecourse.py:347` EOF 빈 줄 1건이 남아 있다. 전체 Ruff/format을 이번에 재실행한 것으로 주장하지 않는다.

실제 수집·모델 학습·확률 발행·성능 계산은 이번 검증에서도 0회다. 기존 구현은 수정하지 않았고, 새 검증 문서·JSON·다음 작업 지시문만 작성했다.

## 승인 범위와 종료 기준

이번 승인은 고정된 합성 parser·계산 한 개와 로컬 SQLite/clock 모델에서 제기했던 계약 결함의 수정에 대한 것이다. 실제 원천의 응답 완전성·갱신 시각, 실제 시간 오차·다중 프로세스 환경, 실제 136열의 PIT, DNS 사건 정의와 실전 성능은 승인 대상이 아니다. 정확시각 field와 0ms 허용 지연을 실제 scheduler의 운영 정책으로 채택하지 않는다.

이제 같은 합성 저장기에서 새 기능을 계속 늘리지 않는다. 다음 작업은 **공식 일정·출전표를 제한적으로 실제 수집하여 raw와 관측 시각, parser 및 페이지 완전성을 확인하는 일회성 capture-only pilot**이다. T−30에 정확히 seal하려고 기다리거나 실제 예측을 발행하지 않는다. 신규 capture 기록을 합성 이벤트로 위장하지 않고 F_t 적격은 별도로 미확인 상태로 둔다.

실제 자료가 확보되면 수집 경로를 운영하기 위한 조건을 판단할 수 있다. 예측력 연구는 별도로 새 정보 후보를 제한하여 진행할 수 있으며, E8-A 승인 자체를 정확도 향상으로 해석하지 않는다.

- [기계 판독 결과와 독립 재현 소스](../data/logs/confirmed_starter_e8a_v2_h1h2_independent_review_20260913.json)
- [다음 에이전트용 E8-B 지시문](CONFIRMED_STARTER_E8B_AGENT_PROMPT_2026-09-13.md)
