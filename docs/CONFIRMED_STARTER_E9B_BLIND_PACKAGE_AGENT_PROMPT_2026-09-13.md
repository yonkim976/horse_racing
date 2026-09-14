# E9-B 준비 프롬프트 — 미사용 30건의 독립 판독 패키지 봉인

작업 위치: `/Users/kimyongjin/Desktop/horse_racing`.
E9-A H1/H2의 고정 표본 감사는 승인됐다. `docs/CONFIRMED_STARTER_E9A_H1_H2_INDEPENDENT_REVIEW_2026-09-13.md`를 먼저 읽어라. 다음 목적은 같은 표본에서 더 많은 규칙을 만드는 것이 아니라 미사용 문서에서 현재 추출 품질을 확인하는 것이다.

**이번 실행은 평가 패키지 작성까지만 한다. 새 30건에 대한 추출 실행·정답 라벨링·성능 계산을 하지 않는다.** 사용자가 패키지를 검증 담당자에게 전달하면, 검증 담당자가 출력에 노출되지 않은 상태에서 원문을 판독할 예정이다. 이번 작업자는 다른 에이전트를 자동 실행하거나 메시지를 보내지 않는다.

## 동결·범위

- 기존 `confirmed_starter_e9a_h1h2_20260913_v2` manifest SHA256 `f19f5b77cb19b5f113585b4ac83497b7ec4579c8652ef2c7c5a72931daad973e` 및 추출기 의존 소스 hash를 확인하고 동결한다. 추출 규칙·정규식·기존 테스트를 변경하지 않는다.
- 기존 모집단 manifest의 서울 2025-01-01~2026-02-28 심판보고서 1,200건 안에서만 작업한다. 원문과 roster만 읽기 전용으로 사용한다. 결과/배당·2026-03 이후 보고서·외부 HTTP·feature dataset·모델 학습·성능 비교·운영 연결은 범위 밖이다.
- 기존 E9-A의 60개 report ID를 제외한다. 그 밖에 이미 상세 판독/규칙 개발/출력 확인에 사용된 report가 있다는 기록이 있으면 제외 사유를 별도 명시한다. 추가 노출이 없다는 것을 확인할 수 없으면 노출 상태를 unknown으로 남기며 독립 미사용 표본이라고 단정하지 않는다.

## 표본 및 패키지

1. 남은 후보를 `(race_id, report_id)` 순서로 정렬한다. 추가 제외가 없으면 1,140건이다. `random.Random(20260914).sample(candidates, 30)`으로 **단순 무작위 30건**을 선택한다. 문구 점수, 사건 존재, 예상 추출 결과로 선택하거나 교체하지 않는다. 모집단/제외 목록/후보 목록/seed/선택 ID와 raw hash를 상세 원문 판독 전에 새 protocol에 봉인한다.
2. 원문 누락·신원 충돌·읽기 실패가 발견돼도 좋은 사례로 교체하지 않는다. 선택한 30건의 coverage와 실패 사유를 남긴다. 전체 package가 차단되면 의존 작업을 실행하지 말고 사유만 제출한다.
3. 검증자가 읽을 Markdown과 기계 판독 JSON을 새 폴더에 만든다. 문서마다 report/race ID, 날짜, 경주번호, 번호·말 이름·horse source ID roster, judgement/addJudgement 원문 전체, source file/hash, 필드별 문자 offset 식별 방식을 제공한다. 자동 사건 강조·추출 cue 강조·예상 라벨·기존 추출 출력은 넣지 않는다. 원문 공백/구두점을 임의 정규화하지 않는다.
4. 사람이 판단할 기준을 설명하는 빈 annotation schema만 제공한다. 필드는 source/report, 원문 근거 span, 말 source key, 사건 유형(start_delay, blocked_or_controlled, interference, contact), 역할(affected/victim/actor/unknown), asserted/quoted/negated/uncertain, actor-victim 관계 근거, 판독 불명 이유다. 빈 template을 no-event 라벨로 해석하지 않는다. 기계가 이 칸을 채우지 않는다.
5. 향후 비교의 사전 단위는 `(report_id, horse source key, event type, role)`의 문서 내 존재 여부 및 별도 actor-victim 관계로 정한다. 같은 사건의 복수 evidence 행을 성능 분모에 중복해서 넣지 않는다. 고유 사건 발생 횟수나 다음 경주 예측력을 측정하는 단계가 아니다. 음성/불명/미판독 분모, unmatched/추가/누락 보고 방식만 protocol에 적고 지표를 계산하지 않는다.

## 보존·제출

기존 모든 산출물·코드·DB·registry·동시 dirty 변경을 보존한다. 새 패키지용 코드를 작성한다면 기존 규칙 모듈을 실행/수정하지 않고 출력은 전부 새 경로에 둔다. 원문 span/roster·범위·30개 키의 중복/누락, seed 재현 및 보호/신규 hash를 확인한다. 새 코드가 있으면 관련 lint와 필요한 계약 검사만 한다. 실제 자료를 추가로 학습하거나 반복 평가하지 않는다.

제출물은 사전 protocol, 독립 판독용 Markdown/JSON, 빈 annotation schema, coverage/exposure 상태, 보존/신규 hash manifest, 짧은 보고서다. 검증자가 바로 30건을 읽을 수 있게 보고서에 판독용 파일 경로를 명시한다. 수작업 기준 라벨 봉인과 별도 실행 지시 전에는 동결 추출기를 새 표본에 실행하지 않는다. T-30 가용성 미검증과 사후 자료라는 한계를 유지하고 종료하라.
