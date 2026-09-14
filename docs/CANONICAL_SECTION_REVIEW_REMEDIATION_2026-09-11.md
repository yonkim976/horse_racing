# Canonical 구간 연구 R1~R4 보완 보고서

- 작성일: 2026-09-11
- 개발·평가 상한: 2026-05-31
- 대상: 독립 검증 보고서의 R1~R4
- 결론: R1~R4 보완과 재현 검사는 완료했으나 운영 승격 또는 다음 연구 단계로 진행하지 않는다. 이 문서는 검증 담당자에게 재검증을 요청하기 위한 제출물이다.

## 1. 보완 범위와 보존 원칙

기존 `section_canonical_seoul_v1` 데이터셋, 기존 `section_canonical_v1/comparison.json`, 기존 run `55456a89-f784-47b0-a704-0fe30562288e` 및 legacy run `8eed3487-3ea1-4900-ad00-7d14cf6949cc`는 덮어쓰지 않았다. 보완 데이터셋, 모델 run, 비교 결과는 모두 새 버전 경로에 만들었다. 실제 개발 평가에는 2026-06-01 이후 자료를 사용하거나 탐색하지 않았다.

제주·부경 확대, DNF 라벨 개편, 새 모델, 추가 seed, C 혼합 실험, 기존 성별 snapshot의 별도 PIT 재설계는 범위에서 제외했다.

## 2. R1 — 확률 동점 처리

### 수정

`src/horse_racing/analysis/metrics.py`에 결과와 독립적인 TopK 동점 기대 포함률을 구현했다. 경계 확률 동점군에서 남은 K자리를 균등 무작위 배정한다고 보고, 공식 우승자가 한 명이면 기존 프로젝트의 기대값 정책과 같은 `남은 자리 수 / 경계 동점 수`를 사용한다. 공식 착순 동착은 여러 `win=1` 라벨로 별도 표현하며, 그중 한 명 이상이 포함될 확률을 조합식으로 계산한다.

`scripts/compare_canonical_section_runs.py`의 Top1/Top3/Top5도 같은 함수를 사용한다. 입력 순서 또는 `horse_number`를 인위적인 타이브레이커로 쓰지 않는다. 산출물에는 실제 착순 동착 경주 수와 확률 경계 동점 경주 수를 서로 다른 필드로 기록한다.

### 회귀 검사

- 원순서, 역순, 고정 seed 무작위 재배열의 Top1/Top3/Top5가 동일함을 검사한다.
- K 경계에 걸친 확률 동점의 기대값을 검사한다.
- 복수 우승 라벨의 공식 동착과 확률 동점을 함께 검사한다.

현재 저장 예측으로 재평가한 결과는 다음과 같다.

| run | 지표 | 수정 전 | 수정 후 |
|---|---:|---:|---:|
| legacy | Top1 | 33.3333% | 31.7130% |
| legacy | Top3 | 62.8472% | 62.3206% |
| legacy | Top5 | 85.0694% | 83.8194% |
| canonical | Top1 | 30.5556% | 31.6956% |
| canonical | Top3 | 64.5833% | 63.6053% |
| canonical | Top5 | 85.7639% | 83.6632% |
| legacy | race winner NLL | 1.920889851 | 1.920889851 |
| canonical | race winner NLL | 1.923827885 | 1.923827885 |

두 run 모두 실제 착순 동착 경주는 0개였다. 확률 경계 동점 경주 수는 legacy가 Top1/3/5 각각 51/163/157개, canonical이 83/151/160개였다. 따라서 기존 TopK 차이를 그대로 성능 근거로 사용하는 것은 부적절하며, NLL 결론은 변하지 않는다.

## 3. R2 — 비교 대상과 coverage 검증

### 수정

비교 스크립트는 run 원장의 `dataset_version`, `valid_period`, `feature_hash`, artifact 경로, model/profile/calibration/seed를 먼저 읽고 데이터셋 manifest와 대조한다. 분모는 각 run 원장에 기록된 validation 기간의 데이터셋 전체 출전집합이다. 예측과의 결합 전에 다음을 모두 검사하며 하나라도 실패하면 비교를 중단한다.

- 데이터셋·예측 키의 중복
- 예측 누락·추가 행과 A/B validation 출전집합 불일치
- `horse_number` 불일치
- 확률의 비유한값, 0~1 범위 이탈, 경주별 합 1 이탈
- validation 종료일의 연구 상한 초과
- A/B의 validation 기간, seed, model, profile, calibration, meet 계약 불일치

새 비교의 양쪽 분모는 각각 3,038행/288경주이고, 누락 0, 추가 0, coverage 1.0이다. 경주별 확률합 최대 오차는 양쪽 모두 `4.44e-16`이다. 실제 평가 날짜 범위는 2026-03-01~2026-05-31이며, 원장에 없는 test 기간은 빈 문자열로 기록했다.

### 회귀 검사

- 예측 한 행 삭제 시 `missing_rows=1` 오류를 검출한다.
- 중복 키, 비유한 확률, 경주별 합 오류를 각각 거부한다.
- A/B 전체 validation 출전 키가 다르면 비교를 거부한다.

## 4. R3 — 물리적 구간 검증

### 수정

`src/horse_racing/analysis/features/canonical_sections.py`에서 거리별 실제 측정 지점과 누적 시간을 함께 검증한다. S1F 지점은 기존 공식 거리 규칙을 재사용하고 G3F는 결승 600m 전, G1F는 결승 200m 전으로 해석한다.

- 거리보다 긴 closing 구간은 사용할 수 없게 했다. 따라서 400m 경주의 `last600`은 unavailable이다.
- 더 앞 지점의 누적 시간이 더 뒤 지점보다 늦으면 관련 관측을 무효화한다. 따라서 1,200m에서 S1F가 G1F보다 늦은 반례를 차단한다.
- 같은 측정 지점은 일률적인 엄격 부등식을 쓰지 않는다. 800m의 S1F와 G3F처럼 동일 지점인 경우 100ms 이내 차이는 허용하고, 이를 넘는 충돌은 양쪽 관측을 무효화한다.
- 최종 유효 값으로 energy feature와 profile flag를 함께 만들므로 불가능·미확정 구간과 flag가 어긋나지 않는다.

### 회귀 검사

1,200m 늦은 S1F, 400m last600, 800m 동일 지점 100ms 허용 및 200ms 거부를 각각 테스트했다.

## 5. R4 — 명시적 날짜 상한

### 수정

`race_date_max`가 전달되면 `src/horse_racing/analysis/features/base.py`가 사용하는 모든 시간가변 source query에 SQL 날짜 상한을 적용했다.

- 과거 경주 결과와 구간기록
- 조교, 출발조교
- 진료, 장구, 기수변경
- 주행심사 결과
- 심판보고서

상한을 적용하지 않을 원천을 미리 전체 조회하지 않는다. 정적 `horse_static`은 이번 범위에서 유지했으며, 기존 성별 snapshot 문제를 함께 재설계하지 않았다.

### 회귀 검사

각 시간가변 source에 상한일 행과 합성 미래 행을 넣은 뒤 반환 source frame에 상한일 행만 남는지 검사한다. 주행심사 결과와 심판보고서도 같은 검사에 포함했다.

이번 보완으로 확인된 것은 source 조회 범위의 계약 위반과 일부 canonical 입력값 변화다. 2026-06-01 이후 행이 과거 실제 예측에 영향을 주었다는 인과적 누수는 입증하지 않았으며 그렇게 해석하지 않는다.

## 6. 데이터·feature 변화와 재학습 판단

새 데이터셋은 15,531행/1,488경주, 2025-01-04~2026-05-31이며 키·schema·canonical feature coverage는 기존 v1과 동일하다. 다만 동일 키 기준 값 비교에서 현재 profile이 선택하는 feature가 변했다.

| 선택 feature | 값이 달라진 행 수 |
|---|---:|
| `canonical_energy_early_late_balance_avg5` | 11 |
| `canonical_energy_resilience_avg5` | 11 |
| `canonical_energy_exact_distance_balance_avg5` | 2 |

동시에 바뀐 `gate_early_speed_*` 네 열은 현재 `racefit_v5_sand` 선택 feature가 아니어서 재학습 판단에서 제외했다. 선택 입력값이 실제로 달라졌으므로 동일 설정(seed 42, `lightgbm_binary_bundle`, `racefit_v5_sand`, calibration auto)으로 새 run `73967a1a-197b-4d81-8149-ee0b008de2a7`을 만들었다. 새 validation 예측은 기존 canonical run과 키 및 확률 값이 모두 동일했고, 예측 파일 SHA-256도 동일하다. 따라서 NLL과 corrected TopK도 기존 저장 예측 재평가 값과 같다.

## 7. 검증 결과

- 관련 Ruff: 통과
- 전체 pytest: `398 passed, 2 warnings in 11.27s`
- 전체 `ruff check .`: 실패, 이번 변경과 무관한 기존 21건이 남아 있다. `scripts/analysis_finish_time_quality.py` 18건, `src/horse_racing/analysis/baselines.py`, `src/horse_racing/analysis/features/ability.py`, `tests/test_segment_correction.py` 각 1건이다.
- 기존 경고 2건: Starlette deprecation 1건, Polars sortedness 1건

관련 테스트 파일은 `tests/test_metrics.py`, `tests/test_compare_canonical_section_runs.py`, `tests/test_features_canonical_sections.py`, `tests/test_feature_source_bounds.py`다.

## 8. 새 산출물

- 데이터셋: `data/datasets/section_canonical_seoul_v2_review/start_minus_30m/dataset.parquet`
- manifest: `data/datasets/section_canonical_seoul_v2_review/start_minus_30m/manifest.json`
- 입력 동등성 로그: `data/logs/canonical_section_input_equivalence_v2_20260911.json`
- 새 run: `73967a1a-197b-4d81-8149-ee0b008de2a7`
- 모델 및 예측: `data/experiments/models/73967a1a-197b-4d81-8149-ee0b008de2a7/`
- 엄격 재비교: `data/experiments/section_canonical_v2_review/comparison.json`
- 기계 판독 보완 로그: `data/logs/canonical_section_review_remediation_20260911.json`
- 본 보고서: `docs/CANONICAL_SECTION_REVIEW_REMEDIATION_2026-09-11.md`

## 9. 남은 한계와 검증 담당자 확인 요청

1. 동점 기대값이 행 순서에 불변이고, 공식 동착 조합식이 기존 singleton 정책을 보존하는지 독립 재현한다.
2. 예측 한 행 삭제, 중복·추가·비유한 확률·합 오류가 결합 전에 실패하는지 확인한다.
3. 800m 동일 측정 지점 100ms 허용치는 source 정밀도에 대한 보수적 공학 허용치다. 공식 정밀도 계약이 별도로 확인되면 조정할 수 있다.
4. 이번 날짜 상한 수정은 조회 계약을 바로잡은 것이며, 과거 실전 예측 누수를 입증한 것은 아니다.
5. 기존 성별 snapshot PIT, DNF 라벨, 타 지역·추가 seed·추가 모델은 의도적으로 미검증 상태다.
6. canonical의 NLL은 legacy보다 `+0.002938` 높고 paired 95% bootstrap 구간은 경주 단위 `[-0.030749, 0.036740]`, 날짜 block `[-0.027583, 0.034556]`이다. 우월성 주장은 유지할 수 없다.

검증 승인 전 운영 승격 또는 다음 연구 단계로 진행하지 않는다.
