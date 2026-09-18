# 서울·부경·영천 통합 더러브렛 데이터셋 구축 보고서

## 결론

서울·부경·영천을 공식 말 ID로 연결한 연구용 데이터셋을 실제 생성했다. 결과물은 [통합 DuckDB](/Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb)와 같은 디렉터리의 Parquet 파일이다. 기존 운영 DB, 모델, registry, 제주 산출물은 변경하지 않았다.

모델은 하나의 공통 데이터 스키마와 시간축을 쓰되 `venue_code`와 개최지 이동 피처를 명시하는 방식이 적합하다. 서울·부경은 2006년부터 공동 학습이 가능하고, 영천은 6경주뿐이므로 독립 모델이 아니라 공통 모델의 새 개최지로 취급해야 한다. 평가 결과는 개최지별로 별도 산출해야 한다.

## 구축 결과

| 자료 | 행 수 | 핵심 범위 |
|---|---:|---|
| 경주 | 44,089 | 서울 28,506, 부경 15,577, 영천 6 |
| 출전·결과 | 489,851 | 공식 `hrNo` 결측 0 |
| 구간기록 | 4,242,283 | 서울 1,676,045, 부경 2,565,960, 영천 278 |
| 주행심사 출전 | 76,413 | 서울 46,603, 부경 29,762, 영남 개최지 미확정 48 |
| 조교·출발조교 | 7,749,406 | 경주 전 28일 피처 별도 계산 |
| 진료·치료 | 2,181,002 | API와 Text 분리, 연결 상태 보존 |
| 마체중 | 438,868 | 본중량·증감 분리 |
| 장구 | 441,918 | 원문 필드 보존 |
| 기본 학습 출전행 | 410,168 | 2006년 이후 결과 확정 36,748경주 |
| 말 차원 | 30,024 | 공식 `hrNo` 기준 |
| 미해결 연결 원장 | 1,405,260 | 모호·미연결·개최지 미확정 행 |

개최지별 정식 경주·출전 범위는 다음과 같다.

| 개최지 | 경주 기간 | 경주 | 출전행 | 모델 목표 시작 |
|---|---|---:|---:|---|
| 서울 | 2000-01-08 ~ 2026-09-13 | 28,506 | 318,733 | 2006-01-07 |
| 부산경남 | 2005-01-07 ~ 2026-09-11 | 15,577 | 171,064 | 2006-01-06 |
| 영천 | 2026-09-13 | 6 | 54 | 2026-09-13 |

서울 2000~2005년 6,656경주·72,607출전행과 부경 2005년 474경주·4,694출전행은 2006년 초 출전마의 과거 이력을 계산하는 warm-up으로 남겼다. 정식 경주 목표값에는 포함하지 않았다.

## 통합 방법

경주 키는 `(venue_code, race_date, race_no)`를 문자열 `race_id`로 고정했고, 출전 키는 `(race_id, hr_no)`로 정했다. 출전번호와 정규화 마명은 교차검증에만 사용했다. 말은 개최지를 넘어 공식 `hrNo` 하나로 연결했다. 그 결과 1,144두가 두 개최지 이상에서 출전했고, 직전 경주와 개최지가 달라진 출전행은 3,175건이었다.

기수·조교사·마주는 공식 `jkNo/trNo/owNo`를 문자열로 저장했다. 마주 원문 표현은 `owner_no_raw_json`에 별도로 보존했다. 출전행의 기수 ID는 전부 존재하며, 조교사·마주 ID는 서울 각 59행, 부경 각 21행이 미확정이다. 이 80행은 추정하지 않고 미해결 원장에 넣었다.

동착은 경주 안에서 동일 유효 순위가 2두 이상인 경우 표시했다. 완주, 실격, 주행중지/미완주, 미출주·취소, 출발 제외, 경주 제외, 무효·미확정을 `result_status`로 분리했다. 주행심사는 별도 `trial_entry` 테이블이며 정식 경주 결과와 섞지 않았다.

## 영천 분리

영천은 영남 경마 권역이지만 공식 API 키는 `meet=4`다. 2026-09-13 확정 결과 6경주·54출전행·278구간행·54마체중행을 `YEONGCHEON`으로 적재했다. 부산 Text 경로에 잘못 놓인 같은 날 마체중 54행은 부산에서 제외하고 대표 이슈로 기록했다.

2026-09-20 영천 예정 6경주는 결과가 확정되지 않았으므로 학습 라벨에서 제외했다. 영천 분리 뒤 `meet=3`으로 들어온 2026-09-17 주행심사 48행은 공식 말 ID는 있지만 실제 부산/영천 개최지를 입증할 수 없어 `venue_code=NULL`, `venue_resolution_status=unresolved_after_yeongcheon_split`으로 남겼다.

## 자료 종류별 모델 사용 가능 시점

| 자료 종류 | 서울 | 부경 | 영천 | 모델 입력 판단 |
|---|---|---|---|---|
| 정식 경주·출전·결과 | 2000-01-08부터, 목표는 2006년부터 | 2005-01-07부터, 목표는 2006년부터 | 2026-09-13 6경주 | 서울·부경은 2006년부터 공동 학습 가능. 영천은 공통 모델 추론·후속 적응용 |
| 공식 말·기수 ID | 전체 출전행 | 전체 출전행 | 전체 출전행 | 바로 사용 가능 |
| 조교사·마주 ID | 59행 결측 | 21행 결측 | 결측 0 | 결측 플래그와 함께 사용 가능 |
| 구간기록 | 2000년부터, 누적시간 의미 검증 | 2005년부터, 의미 미검증 | 첫 6경주 누적시간 | 서울·영천과 부경 구간을 같은 열로 합치지 않음 |
| 일별 조교 | 1998-09-25부터 | 2004-06-30부터 | 고유 원천 없음 | 공식 `hrNo` 연결, 경주일 이전만 사용 가능 |
| 출발조교 | 2009-05-21부터 | 2009-05-21부터 | 고유 원천 없음 | 2009년 이후 보조 피처. 이전 연도는 0이 아니라 원천 미제공 |
| 주행심사 | 2003-07-03부터 | 2004-11-07부터 | 분리 뒤 개최지 미확정 | 확정 신원만 과거 이력으로 사용 |
| 공식 API 진료 | 2025-01-01부터 | 2019-04-07부터 | 없음 | 공식 ID 기반 피처로 사용 가능, 공개시각은 미검증 |
| Text 진료 | 2003-09-18부터 | 2005-05-04부터 | 없음 | 확정 연결만 사용. 서울 27.3%, 부경 32.7%만 ID 연결 |
| 마체중 | 2003-09-06부터 | 2004-11-28부터 | 첫 6경주 | 값은 사용 가능하나 과거 공개시각 미검증이므로 기본 백테스트에서 제외 권장 |
| 장구 | 2003-09-20부터 | 2005-01-07부터 | 첫 6경주 | 원문 보존, 공개시각 미검증으로 기본 피처 제외 권장 |
| 주로·날씨 | 경주 원천 범위 | 경주 원천 범위 | 첫 6경주 | 당일 가용 시각을 별도 증명한 실험에서 사용 |

조교·진료의 최신 사건일은 2026-09-16이고, 서울 주행심사는 2026-09-17까지다. 확정 경주 결과의 최신일은 서울 2026-09-13, 부경 2026-09-11, 영천 2026-09-13이다.

## 누수 방지와 학습 테이블

`model_entry_base`는 warm-up을 포함해 말의 개최지 간 전체 시간축을 계산한다. `model_target_entry`는 2006년 이후 결과 확정 경주만 고른 상세 테이블이다. 현재 경주의 결과·배당도 감사 목적으로 포함하므로 피처 행렬로 직접 쓰지 않는다.

기본 학습 파일은 `model_training_entry`다. 현재 경주의 사후 값은 `target_*` 이름으로만 제공하고, 배당·착차·결과 원문은 제외했다. 과거 성적은 윈도 함수의 `1 PRECEDING`까지만, 조교·진료는 `event_date < race_date`와 28일 하한으로 계산했다. 독립 검증에서는 결정적 표본 250행의 3/7/14/28일 조교 값을 원천 사건에서 다시 계산해 모두 일치함을 확인했다.

당일 마체중과 주로·날씨는 테이블에 남겼지만 `feature_availability_note`에 기본 제외 조건을 명시했다. 당시 공개 시각을 증명할 수 있는 별도 스냅샷이 마련되기 전에는 실시간 예측을 모사하는 기본 피처로 사용하면 안 된다.

## 미해결 연결

과거 Text 진료는 말 ID가 없는 행이 많다. 서울 1,349,468행 중 368,626행, 부경 628,141행 중 205,148행만 확정했다. 모호 1,346,107행과 미연결 57,728행은 이름 하나로 자동 연결하지 않고 후보와 원문을 보존했다.

마체중은 437,672행을 경주·출전번호·정규화 마명으로 확정했고 영천 54행은 공식 ID로 연결했다. 부경 759행과 서울 85행은 경주·출전번호 후보와 마명이 충돌하며, 부경 298행은 대응 경주 후보가 없다. 주행심사는 알려진 서울 Text/API 충돌 4건, 부경 과거 모호 5건, 서울의 신원 미확정·충돌 행을 그대로 남겼다.

전체 후속 처리 대상은 [미해결 원장 요약](/Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_unified_20260918/unresolved_identity_summary.csv)과 `unresolved_identity_ledger`에 있다.

## 검증

[독립 검증 결과](/Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_unified_20260918/independent_validation.json)는 원본 서울·부경·운영 SQLite를 읽기 전용으로 다시 열어 다음을 확인한다.

- 개최지별 경주·출전·구간 원천 행 수 전수 일치
- 각 테이블 기본키 중복 0, 출전·구간 고아 행 0
- 부경 2006년 578경주·6,569출전행
- 부경 Text `dacom01`, `dacom12`, `dacom71`의 2006년 표제 키 각 578개
- 영천 6경주·54출전·54마체중 및 부산 오분류 0
- 2026-09-20 예정 경주의 학습 라벨 혼입 0
- 모델 목표 최소일 2006-01-06, 비확정 경주 혼입 0
- DuckDB와 모든 Parquet 행 수 일치
- 시점 이전 조교 피처의 독립 재계산 일치

최종 검증은 51개 항목을 모두 통과했다. 연도별 전체 coverage는 [coverage CSV](/Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_unified_20260918/coverage_year_source.csv)에서 확인할 수 있다.

## 재현과 향후 통합

빌드 코드는 [build_unified_thoroughbred_dataset.py](/Users/kimyongjin/Desktop/horse_racing/scripts/build_unified_thoroughbred_dataset.py), 독립 검증 코드는 [verify_unified_thoroughbred_dataset.py](/Users/kimyongjin/Desktop/horse_racing/scripts/verify_unified_thoroughbred_dataset.py)다.

```bash
cd /Users/kimyongjin/Desktop/horse_racing
PYTHONPATH=src .venv/bin/python scripts/build_unified_thoroughbred_dataset.py \
  --output data/research/thoroughbred_unified_YYYYMMDD
PYTHONPATH=src .venv/bin/python scripts/verify_unified_thoroughbred_dataset.py \
  --database data/research/thoroughbred_unified_YYYYMMDD/thoroughbred_unified.duckdb \
  --output data/research/thoroughbred_unified_YYYYMMDD/independent_validation.json
PYTHONPATH=src .venv/bin/python scripts/finalize_unified_thoroughbred_dataset.py \
  --output data/research/thoroughbred_unified_YYYYMMDD
```

향후 다른 DB와 통합할 때는 `hr_no`를 말 전역 키로 유지하고, 경주 키에는 반드시 실제 `venue_code`를 포함해야 한다. `region_code=YEONGNAM`을 개최지 키로 쓰면 부경과 영천이 충돌한다. 주행심사·조교·진료 사건은 정식 경주 테이블에 inner join하지 말고 사건 테이블로 보존한 뒤 예측 시점 기준으로만 집계한다.

이번 작업에서는 모델 학습, 성능 비교, 운영 승격을 수행하지 않았다.
