# E2 담당자 지시서: 실제 출발자 조건부 연구 데이터셋

작업 경로는 /Users/kimyongjin/Desktop/horse_racing이다. E1 R1~R4는 격리 연구 계약 범위에서 독립 검증을 통과했다. PRE_RACE_FIELD_DNF_E1_REMEDIATION_INDEPENDENT_REVIEW_2026-09-11.md와 E1 원문 감사, 현재 dataset/feature/prediction 구현을 읽고 작업한다.

## 목표와 해석

기존 학습은 정상완주자 N만 남겨 실제 출발한 DNF/실격 48행도 제외한다. 서울의 확인된 실제 출발집합 A를 포함한 새 연구 전용 데이터셋을 만들고, 다음 단계에서 학습 표본 선택 효과를 분리할 통제 비교 명세를 작성하라.

A는 사후 실제 출발 여부에 조건부인 집합이다. 역사적 T-30 F_t가 아니다. manifest·파일명·보고서·비교 명세에 confirmed-starter conditional / retrospective라는 뜻을 명시한다. SealedFieldManifest에 사후 A를 넣고 사전 공개 증거를 확보한 것처럼 처리하지 않는다. 미래 실전 성능이나 환수율을 추정하는 단계도 아니다.

## 보존 및 작업 범위

- 표적은 서울 2025-01-04~2026-05-31, 기존 1,488경주. 필요한 과거 이력은 그 이전까지 허용한다. 모든 실제 결과 조회에 상한을 먼저 적용하며 2026-06-01 이후 실제 결과·성능을 읽지 않는다.
- 현재 dirty 작업, production DB, 기존 dataset/run/comparison, 운영 라벨 정책·예측·UI를 보존한다.
- 연구 전용 builder·명세·manifest·dataset·테스트만 새 경로로 만든다. 운영 경로의 기본 동작을 바꾸지 않는다. 새 모델 학습·성능 비교·seed/calibration 탐색·실제 수집 실행은 이번에 하지 않는다.

## 1. 독립 집합과 라벨

E1 원천 증거와 현재 DB를 키로 대조해 A를 먼저 확정한다. 기대값은 총 15,579행·1,488경주다. train은 정상완주 12,493+DNF 35=12,528행, development validation은 정상완주 3,038+DNF 12+실격 1=3,051행이다. 미출주 267행은 A의 정의로 제외하며 '사전 취소라서 제외'했다고 표현하지 않는다.

새 retrospective field manifest에는 집합 종류, 선정 기준, 경주/출전 키·해시, 상태 매핑, 조회 상한, 원천 식별자와 기존 N 대비 차이를 기록한다. E1의 사전 sealed field 계약과 구분된 타입/명칭을 사용하고, 두 종류를 혼용하면 거부하게 한다.

DNF/실격의 확정 win/top2/top3는 0으로 두되 순위·완주시간 보조 target은 mask한다. 없는 결과나 모호한 상태를 0으로 채우지 않는다. 동착은 E1의 공식 순위 정의를 유지한다. 서로 다른 집합의 라벨이나 결과를 inner join으로 일부만 남기지 않는다.

## 2. feature는 모든 A 행에 대해 사전 이력으로 계산

기존 canonical history와 racefit_v5_sand의 선택 feature 구성을 기준으로 한다. 이번에는 새로운 설명변수나 모델 구조를 추가하지 않는다.

- 모든 A 행의 학습 입력에 같은 이력 조회 규칙을 적용한다. DNF 대상 행이 과거 정상완주 history 테이블에 없다는 이유로 현재 feature 전체가 빠지지 않게 한다.
- 대상 경주의 실제 순위·기록·구간·DNF/실격 상태는 target과 별도다. 이를 predictor 계산에 쓰거나, 현재 DNF를 정상완주처럼 가짜 순위로 끼워 넣어 feature를 계산하지 않는다.
- 경주 내 starters·마번 비율·상대평가·pace 경쟁자 수는 A에서 일관되게 계산한다. 이는 사후 A에 조건부인 feature라는 한계를 명시한다.
- 과거 이력 자체의 DNF 포함 정책은 이번에 임의 변경하지 않는다. 기존 career/form 등의 정상완주 이력 조건이 남으면 정확히 기록한다. 이번 변경은 우선 표적 집합과 그 집합에 의존하는 feature의 계약이다.
- 새 A 데이터셋 안의 기존 N 행과 이전 canonical 데이터셋을 키로 대조한다. 차이를 'A 집합 확대에 따른 경주 내 feature 변화', '의도된 feature 생성 경로 보완', '설명 못한 변화'로 근거와 함께 보고한다. 설명 못한 선택 feature 차이가 있으면 제출 전에 원인을 규명한다.
- 알려진 성별 snapshot PIT 등 기존 한계가 사라졌다고 주장하지 않는다. 과거 A를 완전한 실전 재현 자료로 표현하지 않는다.

## 3. 반드시 통과할 검사

1. 독립 A 예상 키와 dataset 행을 정확히 대조한다. 48행 누락·중복·추가 및 양쪽에서 같은 말이 빠지는 반례를 검출한다.
2. 고정 A를 그대로 두고 대상 결과를 정상완주↔DNF 또는 순위 변경해도 선택 predictor 값은 바뀌지 않아야 한다. A 자체가 시작 여부 조건부임을 이 검사와 혼동하지 않는다.
3. 대상 및 이후 구간 기록·완주시간을 바꿔도 대상 predictor가 불변이어야 한다. 미래 검사에는 합성 행만 사용한다.
4. target가 DNF라는 이유로 history feature가 전부 결측이 되지 않는 실제 사례를 추적한다. 진짜 이력 부족으로 생긴 결측은 구분한다.
5. 경주 내 feature의 분모가 A와 일치함을 검사한다. 정상완주 N을 거쳐 starters를 다시 계산하는 경로를 남기지 않는다.
6. train/validation 날짜·라벨·feature 계약과 보조 target mask를 검증한다. 운영 기존 경로의 회귀도 확인한다.

## 4. 후속 통제 비교 명세만 작성

나중에 진행할 학습 비교는 같은 A 기반 predictor 테이블을 공유하고 다음 두 조건만 다르게 하는 설계를 제안하라.

- 기준 모델: train의 정상완주 N 행으로 학습.
- 비교 모델: train의 실제 출발 A 행으로 학습, DNF의 확정 비입상 라벨 포함.
- 양쪽 모두 동일 validation A 3,051행과 동일 평가 사건으로 평가한다. 경주 내 입력과 validation을 다르게 만들어 학습 행 선택 효과와 혼합하지 않는다.
- 모델 family, 선택 feature, seed, 분할, calibration/early stopping 규칙을 사전 명세한다. 기존 run 설정을 출처로 삼고 탐색하지 않는다.
- 기존 N validation 3,038행의 NLL을 새 A NLL과 직접 빼서 개선이라고 하지 않는다. 이미 사용한 development validation이며 미개봉 test가 아니라는 점을 명시한다.
- 향후 paired 경주·날짜 bootstrap, 전체 A 및 DNF/실격 경주 진단을 보고하되 일부 경주만 골라 전체 우월성을 주장하지 않는다. 실제 평가는 이번에 수행하지 않는다.

## 제출

- docs/CONFIRMED_STARTER_CONDITIONAL_E2_2026-09-11.md: 목적·사후 조건부 한계·키/상태/feature 검증·통제 비교 명세·후속 가능/보류 판정.
- 새 연구 dataset.parquet 및 manifest: 기존 버전을 덮어쓰지 않는 명확한 E2 경로.
- data/logs/confirmed_starter_conditional_e2_20260911.json: 독립 분모·키·변경 셀·결측률·분할·코드/데이터 해시·실제 사례.
- 재현 가능한 연구 builder와 유의미한 회귀 테스트. 관련 검사 및 전체 pytest/Ruff/diff-check 결과를 분리 보고.

현재 설계로 모든 A 행의 predictor를 결과와 분리해 만들 수 없는 부분은 추정값이나 가짜 순위로 메우지 않는다. 가능한 독립 작업을 완료하고 구체적인 결함과 해결 필요사항을 제출한다. 학습·운영 변경 없이 독립 검증에 제출하고 종료한다.
