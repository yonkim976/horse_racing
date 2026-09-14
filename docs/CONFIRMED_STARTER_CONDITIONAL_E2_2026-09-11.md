# Confirmed-starter conditional E2 연구 데이터셋

작성일: 2026-09-11<br>
범위: 서울, 2025-01-04~2026-05-31, 1,488경주<br>
판정: **후속 통제 학습 비교의 입력 명세까지 가능. 이번 단계의 학습·평가·운영 변경은 보류.**

## 1. 목적과 해석 한계

E2는 정상완주자만 남긴 기존 N 15,531행에 실제 출발 후 DNF 47행과 실격 1행을 더해, 사후 확인 실제 출발집합 A 15,579행을 만드는 연구다. A는 결과를 보고 출발 여부를 확인한 `confirmed-starter conditional / retrospective` 집합이다. 역사적 T-30 출전집합 `F_t`가 아니며 미래 실전 성능이나 환수율을 재현하지 않는다.

E1의 `SealedFieldManifest`를 재사용하지 않았다. 별도 `ConfirmedStarterConditionalManifest` 타입은 다음을 기록하고, pre-race manifest를 넘기면 거부한다.

- field kind: `confirmed_starter_conditional_retrospective`
- 사후 선정 기준과 원천 식별자
- 서울·고정 날짜 범위와 실제 결과 조회 상한 2026-05-31
- 독립 A `(race_id, race_entry_id)` 15,579개 전체와 정렬 독립 SHA-256
- 정상완주 N 대비 DNF 47 + 실격 1의 차이

미출주 267행은 사후적으로 실제 출발하지 않았기 때문에 A에서 제외했다. 이를 T-30 전에 취소를 알았기 때문에 제외했다고 해석하지 않는다.

## 2. 독립 분모와 라벨

E1 v2 evidence에서 정상완주·started DNF·실격 키를 먼저 고정하고, 날짜 상한이 SQL에 들어간 읽기 전용 DB 결과를 별도로 분류했다. dataset과 독립 A의 키를 join 전에 정확히 비교했다.

| split | 정상완주 | DNF | 실격 | A 합계 |
|---|---:|---:|---:|---:|
| train, ~2026-02-28 | 12,493 | 35 | 0 | 12,528 |
| development validation, 2026-03-01~05-31 | 3,038 | 12 | 1 | 3,051 |
| 전체 | 15,531 | 47 | 1 | 15,579 |

모든 1,488경주가 남는다. 중복·누락·추가 키는 0이다. dataset에서 한 행을 지우거나, manifest와 dataset 양쪽에서 같은 말을 지운 것처럼 입력하거나, 같은 오키로 바꾸거나, 중복시키는 합성 반례는 독립 manifest 비교에서 실패한다.

라벨 계약은 다음과 같다.

- 정상완주: 공식 순위로 win/top2/top3를 정하며 E1의 동착 `position <= K` 정의를 유지한다.
- DNF/실격: win/top2/top3는 확정 0이다.
- DNF/실격: `finish_position_target`, `finish_time_ms_target`은 null이고 두 auxiliary-observed flag도 false다. 코드 91/92를 가짜 최하위 순위나 완주시간으로 바꾸지 않는다.
- 미출주·결과 누락·상충 상태: 0으로 채우지 않는다. A에 들어오지 않으며 독립 expected key와 다르면 build가 실패한다.

## 3. Predictor 생성 계약

Feature family는 기존 canonical history인 `racefit_canonical_history`, 선택 profile은 기존 run의 `racefit_v5_sand` 136개를 그대로 사용했다. 새 설명변수와 모델 구조는 추가하지 않았다.

Target/result 원천인 `result_id`, 착순, 완주시간, margin, rank remark, scratched, disqualified 및 모든 label/mask 열은 predictor base를 만들기 전에 제거한다. 이후 target는 완성된 predictor와 `(race_id, race_entry_id)` 1:1로 결합한다.

과거 이력 정책은 기존과 같다. `past_results`는 정상착순 1~89만 사용하며 career/form, speed, Elo, style, canonical section history에 DNF를 새 과거 성적으로 넣지 않았다. 이 한계는 manifest에 명시했다.

기존 파이프라인은 DNF target가 정상완주 history 행에 없어서 shift 기반 feature가 통째로 빠진다. E2는 각 DNF/실격 target에만 null-outcome anchor를 만든다.

- anchor 계산은 target 날짜보다 엄격히 이전인 정상완주 result/section만 본다.
- anchor의 착순과 완주시간은 null이며, target 및 이후 구간 기록은 source에서 제외한다.
- null anchor는 전역 history에 저장하지 않으므로 이후 경주의 rolling window나 Elo update를 바꾸지 않는다.
- speed figure와 Elo의 일괄 계산에서는 각 anchor를 별도 합성 race ID로 격리해 정상 경주의 상태 갱신을 막지 않는다.

합성 회귀에서 고정 A를 둔 채 target의 정상착순을 88로 바꾸거나 완주시간·현재 S1F 구간 값을 극단값으로 바꿔도 target의 form/style predictor가 동일했다. Predictor base 자체도 결과 열 변경에 완전히 불변이다.

경주 내 feature는 A 전체에서 계산했다. 각 행의 `starters`는 같은 race의 A 행 수와 전부 일치한다. `horse_number_pct`, 부담중량 경주 평균, 모든 race z/rank, `known_style_share`, front-runner 경쟁 수와 pace pressure도 N을 거치지 않고 A에서 계산한다. 이는 사후 A에 조건부인 feature이며 live T-30 feature라는 뜻은 아니다.

## 4. 실제 DNF 추적과 결측

실제 사례 `race_id=1849`, `race_entry_id=19361`, 2025-01-26 started DNF는 과거 정상완주 4회가 있다. 순위·완주시간 auxiliary target는 모두 mask됐지만, 선택 feature 136개 중 135개가 비결측이다. DNF라는 이유로 history feature 전체가 사라지지 않았다.

전체 A에서 선택 feature 136개 중 57개는 결측률 0이다. 높은 결측률의 예는 exact-distance Top3 race-z 25.77%, canonical exact-distance balance 23.65%, exact-distance speed-figure race-z 23.47%, canonical finish-change trend 23.35%다. 이는 거리별 표본·필요 이력 수 계약에 따른 실제 이력 부족이며 DNF target 누락 경로와 구분된다. 모든 선택 feature별 결측률은 기계 로그에 기록했다.

## 5. 기존 N과 feature 변경 전수 대조

새 A dataset 안의 정상완주 N 15,531행과 기존 canonical dataset의 같은 키를 정확히 대조했다. 136개 선택 feature에서 달라진 셀은 9,274개였다.

- A 확대에 따른 경주 내 feature 변화: 9,274셀
- DNF용 생성 경로 때문에 기존 N 자체가 달라진 셀: 0
- 설명하지 못한 변화: 0

변경은 DNF/실격이 포함된 경주의 `starters`·마번 비율·gate band·pace 구성과 race z/rank에 국한됐다. 대표적으로 starters와 horse-number percentile은 각각 409셀, race-z 계열은 가용 행에 따라 204~412셀, pace 계열은 51~111셀이 바뀌었다. 상세 feature별 수는 로그에 있다.

두 번 생성한 parquet은 15,579×190 typed cell과 schema가 모두 동일했다. Parquet byte hash는 encoding 차이로 같지 않았으므로 manifest는 현재 제출 파일의 byte SHA-256을 기록하고, 재현성 주장은 값·schema 동일성으로 한정한다.

## 6. 후속 통제 비교 사전 명세

이번에는 실행하지 않는다. 다음 단계에서 아래 두 조건만 달리해야 한다.

| 항목 | 기준 모델 | 비교 모델 |
|---|---|---|
| 공통 predictor table | E2 A 15,579행의 동일 predictor | 동일 |
| train 선택 | 정상완주 N 12,493행 | 실제 출발 A 12,528행 |
| DNF train label | 행 제외 | 35행의 win/top2/top3=0 포함 |
| validation | 동일 A 3,051행 | 동일 A 3,051행 |
| 평가 사건·키 | 동일 retrospective A | 동일 retrospective A |

기존 canonical run `73967a1a-197b-4d81-8149-ee0b008de2a7`을 설정 출처로 고정한다.

- model family: `lightgbm_binary_bundle`, win/top2/top3 이진 bundle
- profile: `racefit_v5_sand`, E2 manifest의 동일 136개 선택 feature
- seed: 42, 추가 seed 탐색 없음
- LightGBM: objective binary, n_estimators 1200, learning_rate 0.03, num_leaves 31, max_depth -1, min_child_samples 80, subsample 0.9/frequency 1, colsample 0.8, reg_lambda 1.0
- fit: ~2025-10-26, tune: 2025-11-01~12-27, calibration: 2025-12-28~2026-02-28
- early stopping/best iteration: 같은 tune split과 기존 trainer 규칙을 양쪽에 동일 적용
- calibration: `auto` 후보와 선택 규칙을 고정하고 같은 calibration split만 사용; validation으로 재선택하지 않음
- development validation: 2026-03-01~05-31 A 3,051행
- test: 없음/미개봉 test로 주장하지 않음

평가는 두 모델의 동일 validation A 예측 key와 확률 coverage를 먼저 검사한 후 수행한다. 전체 A 및 DNF/실격 포함 경주 진단을 함께 보고하고, 날짜 또는 경주 단위 paired bootstrap을 사용한다. 일부 DNF 경주만 골라 전체 우월성을 주장하지 않는다. 기존 N validation 3,038행의 NLL과 새 A 3,051행 NLL은 사건과 분모가 다르므로 직접 빼서 개선으로 표현하지 않는다. 이 validation은 이미 개발에 사용됐으며 최종 일반화 성능이 아니다.

## 7. 검증 결과

| 검사 | 결과 |
|---|---|
| E2 회귀 테스트 | 8 passed |
| E1+E2 관련 테스트 | 32 passed |
| 전체 pytest | 444 passed, 2 warnings |
| E2 관련 Ruff check/format | 통과 |
| 전체 Ruff check | 기존 범위 밖 21건으로 실패 |
| 전체 Ruff format | 기존 범위 밖 96개 파일로 실패 |
| `git diff --check` | 동시 UI 작업 `src/horse_racing/web/racecourse.py:347` EOF blank line 1건 |

전체 Ruff 문제는 이전과 동일하게 `scripts/analysis_finish_time_quality.py`, `analysis/baselines.py`, `features/ability.py`, `tests/test_segment_correction.py`에 있다. dirty work 보존 원칙에 따라 수정하지 않았다.

## 8. 산출물과 판정

- dataset: `data/datasets/confirmed_starter_conditional_e2_retrospective/start_minus_30m/dataset.parquet`
- manifest: 같은 디렉터리의 `manifest.json`
- 기계 로그: `data/logs/confirmed_starter_conditional_e2_20260911.json`
- builder: `scripts/build_confirmed_starter_conditional_e2.py`
- 연구 계약: `src/horse_racing/analysis/confirmed_starter_dataset.py`
- 테스트: `tests/test_confirmed_starter_dataset.py`

후속 통제 학습 비교는 위 고정 명세로 **가능**하다. 다만 역사적 `F_t` 복원, T-30 실전 성능 주장, 운영 dataset 전환, 새 모델 학습·calibration 탐색, 성별 snapshot 등 기존 PIT 재설계는 **보류**다. 이번 단계에서는 production DB, 기존 dataset/run/comparison, 운영 라벨·예측·UI를 변경하지 않았다.
