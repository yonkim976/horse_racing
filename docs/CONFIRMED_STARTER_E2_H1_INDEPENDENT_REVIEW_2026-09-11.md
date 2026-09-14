# E2-H1 독립 재검증

검증일: 2026-09-11 KST

**판정: H1 보완 통과. 지정된 H1 artifact를 E3 N-vs-A 통제 연구의 학습 입력으로 승인한다.**
이번 판정은 데이터 보완에 대한 것이다. 예측력 향상, 역사적 T-30 재현, 운영 승격을 승인하는 것은 아니다.
검증자는 모델 학습·성능 비교·운영 연결을 실행하지 않았다.

## 독립 확인 결과

제출 로그의 성공 여부를 읽는 데 그치지 않고 SQLite를 read-only로 열어 별도 SQL로 집계했다.
대상은 서울 2025-01-04~2026-05-31이며, 과거 정상완주 이력은 target보다 엄격히 이전 날짜만
말×기수로 연결했다. 실제 결과 조회는 2026-05-31 상한 안에서 수행했다.

| 검사 | 독립 실측 |
|---|---:|
| SQL로 복원한 A 키와 artifact 키 | 15,579행 일치 |
| 조합 starts/wins/first 전수 불일치 | 0 |
| v2 대비 실질 변경 | 30행·71셀 |
| starts / wins / first 변경 | 30 / 11 / 30셀 |
| 정상완주 행의 실질 변경 | 0 |
| 다른 선택 feature / 비선택 열 실질 변경 | 0 / 0 |
| NaN/Inf | 0 |
| 기준 run의 선택 feature 이름·순서·hash | 136개 일치 |
| A 전체 38개 field feature 독립 산식 | 불일치 0 |
| A 개별 입력을 N으로 제한한 field 재계산 vs 기존 N | 불일치 0 |
| N 공통행의 선택 feature 변화 | 9,668셀 |
| null→값 / 값→null | 4 / 10셀 |
| 확대 42경주 밖 실질 변경 | 0 |

비교 계약은 null 상태를 정확히 비교하고, 유한 숫자에 절대오차 1e-10을 적용했다.
38개 field 산식의 최대 수치오차는 4.610134496374485e-11,
N counterfactual의 최대 수치오차는 6.135980612498315e-12였다.
v2 대비 네 비선택 gate 열의 미세 차이는 최대 4.58e-15다. 따라서 전체 parquet의
bit-for-bit 동일성을 주장하지 않으며, 보고된 71셀은 명시된 허용오차 기준의 변경이다.

## 코드와 회귀 검증

수정 함수는 horse_id+jockey_id별 정렬 이력과 bisect_left를 사용한다. target 결과행의
존재를 lookup 조건으로 사용하지 않는다. null jockey와 알려진 기수의 첫 조합을 구분한다.
기존 정상완주 조건부 과거 이력 정책도 유지한다.

전체 pytest를 직접 재실행해 **450 passed, 2 warnings**를 확인했다.
여기에는 실제 feature 모듈을 사용하는 race 1849의 축소 source fixture가 포함된다.
이 테스트는 target 결과행 삭제와 상태 교환, 당일 결과·구간 변경, 합성 미래행 추가를 조합한
세 candidate를 baseline과 비교하며 선택 predictor 전체에 null/수치 계약을 적용한다.
이를 서로 완전히 독립된 네 실험 또는 모든 source의 PIT 전수 증명으로 확대 해석하지 않는다.
이번에는 전체 dataset builder를 다시 실행하지 않았다. 저장 artifact의 전수 독립 집계,
v2와의 전열 비교 및 실제 모듈 회귀 테스트로 H1 범위를 검증했다.

관련 구현·builder·test 세 파일의 Ruff check/format은 통과했다.
전체 Ruff는 범위 밖 네 파일의 기존 21건, 전체 format은 기존 96개 파일로 실패했다.
git diff --check는 기존 web/racecourse.py:347 EOF 빈 줄 한 건만 검출했다.
이 파일들은 수정하지 않았다.

## 보존 확인

H1 dataset, manifest의 source hash 및 DB hash는 현재 파일과 일치했다.
제출 로그에 봉인된 v2 dataset·manifest·log 해시 세 개도 각각 재계산해 일치를 확인했다.
이 확인을 해시 기준이 없는 모든 과거 산출물의 불변성 증명으로 확대하지 않는다.

- H1 dataset SHA256: `9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7`
- H1 manifest SHA256: `f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801`
- 선택 feature SHA256: `b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48`

## 승인 범위와 다음 비교

H1은 사후 실제 출발집합 A 15,579행·1,488경주의 연구 입력이다.
역사적 T-30 F_t 복원 불가, 정상완주 조건부 과거 이력, 성별 snapshot PIT 한계는 남아 있다.

E3에서는 이 동일한 A feature 표에서 train의 정상완주 행만 선택한 N 모델과 train 전체를
선택한 A 모델을 각각 새로 학습한다. 공통 validation은 A 3,051행·288경주다.
train 차이는 35 DNF이며 fit 18, tune 9, calibration 8행으로 나뉜다.
따라서 비교 대상은 fit뿐 아니라 조기 종료·보정에 쓰이는 행의 포함 정책까지 포함한 학습 절차다.
validation의 특수 상태 13행은 12경주에 분포한다.

현행 calibration auto는 development validation에서 후보를 선택한다.
이 평가와 bootstrap은 독립 test나 미래 성능의 확증이 아니다. 실제 2026-06-01 이후 결과는
열지 않고, 두 연구 bundle을 만든 뒤 결과 제출에서 멈춘다.

실행 명세: `docs/CONFIRMED_STARTER_N_VS_A_E3_AGENT_PROMPT_2026-09-11.md`

기계 판독 증거와 독립 검사 source:
`data/logs/confirmed_starter_e2_h1_independent_review_20260911.json`
