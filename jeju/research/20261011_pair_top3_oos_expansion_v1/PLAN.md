# F1_STYLE6 direct pair 모델의 과거 OOS H1 확장 사전 계획

상태: **확장 설계와 구조 preflight만 승인됨.** 역사적 F1_STYLE6 refit, raw score 생성, direct pair/H2 fit, 새 pair 예측 또는 성과 계산은 root의 구체적인 fit 승인 전까지 금지한다. 이 문서는 이전 direct pair plan의 모형·평가 계약을 상속하고 H1의 과거 OOS 경주 수만 늘리는 한 개 arm을 고정한다.

## 질문과 변경 범위

저장 `F1_STYLE6`의 30개 입력과 해당 시점에 OOS인 원시 말 점수를 유지하고, 기존 직접 pair 모형의 H1 경주만 늘렸을 때 같은 2024~2026 평가 경주에서 두 Top3 말 pair 선택이 달라지는지 비교한다. 이는 확장된 학습량의 후향 비교다. 동일한 과거 평가 라벨을 다시 사용하므로 새 독립 holdout이나 운영 후보 승격으로 해석하지 않는다.

이번 arm에서 바뀌는 것은 각 평가 fold의 H1 구성뿐이다. H1은 가장 이른 recipe-valid OOS 연도인 2019년부터 평가 fold 직전 연도의 6월 구간까지 expanding window로 구성한다. 평가 fold 직전 연도의 기존 Jan–Jun H1 행은 그대로 포함하고, 이전 연도는 해당 연도의 전체 경주를 앞에 더한다. 기존 H1/H2 경계의 2일 purge를 그대로 적용한다. H2는 직전 연도 7–12월, 평가 cohort·저장 평가 점수·평가 라벨·비교 대상·pair 목표·basis·loss·`lambda=1.0`·H2 보정 규칙·seed·bootstrap schedule을 기존 계획대로 고정한다.

기존 primary gate를 유지한다. Primary comparator는 원시 `F1_STYLE6` 점수 상위 2두 pair이며, 확장 direct pair가 이 기준보다 높은 점추정과 같은 paired date-bootstrap 95% 구간의 하한이 0보다 커야 성공 신호다. `expanded − old direct 426/1,779`는 학습량 증가의 직접 비교로 사전 고정해 같은 bootstrap schedule의 CI와 함께 보고하지만 primary gate를 대체하지 않는다. 저장 말별 `P(Top3)` Top2, joint 주변확률 Top2, candidate maximum-joint pair, matched-baseline maximum-joint pair, H2 baseline과 나머지 기존 참조도 그대로 보고한다.

## 원시 OOS 점수의 단일 출처 규칙

과거 경주가 pair H1/H2에 들어갈 때 경주 연도 `c`의 점수는 한 가족만 사용한다: `F1_STYLE6_{c+1}/calibration_scores.parquet`. 저장된 최신 평가 모델로 과거 점수를 다시 만들지 않는다. 이 규칙은 한 경주가 `evaluation_scores`와 다음 fold의 `calibration_scores` 양쪽에 있을 때 선택을 유일하게 정한다.

| 경주 연도 | pair 학습에 허용되는 score file | 상태 |
|---:|---|---|
| 2019 | `F1_STYLE6_2020/calibration_scores.parquet` | 새 historical refit과 OOS raw score 생성 필요 |
| 2020 | `F1_STYLE6_2021/calibration_scores.parquet` | 새 historical refit과 OOS raw score 생성 필요 |
| 2021 | `F1_STYLE6_2022/calibration_scores.parquet` | 새 historical refit과 OOS raw score 생성 필요 |
| 2022 | `F1_STYLE6_2023/calibration_scores.parquet` | 새 historical refit과 OOS raw score 생성 필요 |
| 2023 | `F1_STYLE6_2024/calibration_scores.parquet` | 기존 저장 OOS 점수 |
| 2024 | `F1_STYLE6_2025/calibration_scores.parquet` | 기존 저장 OOS 점수 |
| 2025 | `F1_STYLE6_2026/calibration_scores.parquet` | 기존 저장 OOS 점수 |

고정 평가연도 `Y`의 평가는 기존 `F1_STYLE6_Y/evaluation_scores.parquet`만 사용한다. 이 평가 점수 파일은 현재 2024~2026 값과 해시를 고정하고 그대로 재사용한다. OOS 학습 테이블에는 `pair_evaluation_year`, `split_role`(H1/H2/EVAL), `race_id`, `api_record_id`, `race_year`, `score_provider_fold_year`, `score_provider_role`, `source_path`, `source_sha256`를 보존한다. 한 race는 각 목적 fold/split에서 정확히 하나의 `(score_provider_fold_year, score_provider_role)`를 가져야 한다. runner-grain score 행은 `(api_record_id, score_provider_fold_year, score_provider_role)` 및 선택 후 `(pair_evaluation_year, split_role, api_record_id)`가 유일해야 한다. 각 pair fold의 H1에는 `(race_id, pair_evaluation_year)`당 한 provider model이 있어야 한다. 같은 `api_record_id`가 다른 fold/role 파일에 나타나도 fold-role 키 없이 합치거나 deduplicate하지 않는다.

각 score의 provider fold metadata에서 `refit_max`를 기록하고 그 score가 쓰이는 경주의 `race_date - 2 days` 이하인지 행별로 확인한다. H1 마지막 경주일은 H2 첫 실제 경주일보다 최소 2일 앞서야 한다. H2 마지막 경주일은 그 fold의 evaluation 첫 실제 경주일보다 최소 2일 앞서야 한다. 어떤 키·날짜·row 수·완전 편성·라벨 계약이라도 어긋나면 대체·보정·조용한 제외 없이 중단한다.

## 필요한 historical F1_STYLE6 점수 생성

현재 style feature table은 2017~2026 범위를 보유하지만, recipe-valid OOS score가 가장 먼저 생길 수 있는 연도는 2019년이다. 2019년을 점수화하는 fold 2020에서는 초기 학습 2017년, early stop 2018년, 최종 refit 2017~2018년이 모두 존재한다. 2017~2018년 자체를 pair H1에 넣을 OOS 점수는 현재 recipe로 만들 수 없으므로 제외한다.

root가 후속 fit 승인을 한 경우에만 missing provider fold 2020~2023을 각각 한 번 재현한다. 기존 F1_STYLE6 raw-score model recipe를 정확히 유지한다: 30개 frozen inputs, train-only category vocabulary, 경주 균등 출전 가중치 `1/field_n`, seed 20261008, frozen LightGBM parameters, fold `f`의 initial train 2017..`f-3`, early-stop `f-2`, 그 best iteration으로 2017..`f-2` refit. 총 8회의 LightGBM `train` 호출(각 fold initial+refit)만 허용한다. 원 pair 계산은 raw score를 temperature 1로 사용하므로 F1 temperature calibration은 실행하지 않는다. 역사 fold의 `evaluation_scores`, 평가 지표, pair 결과는 생성하지 않는다. 필요한 calibration-year raw score와 모델·recipe metadata만 새 폴더에 한 번 저장한다. 저장된 2024~2026 F1_STYLE6 모델·평가 점수는 읽기 전용이다.

## 고정 H1/H2/evaluation 코호트

아래 race 수는 고정 F1_STYLE6 feature table의 race-date/key inventory에 기존 H1/H2 날짜 규칙을 적용한 구조적 사전 예상이다. 역사 score를 생성하기 전이며, 성능 결과가 아니다. 별도 preflight에서 score-key 전체 coverage, race당 완전 roster, 최소 4두, 순위 1·2·3 각각 한 마리와 양성 pair 3개를 확인하고 정확히 일치하지 않으면 중단한다.

| Pair 평가 fold | 확장 H1 구성 | 확장 H1 경주/일 | 기존 H1 경주/일 | H2 경주/일 | 고정 EVAL 경주/일 |
|---:|---|---:|---:|---:|---:|
| 2024 | 2019–2022 전체 + 2023 기존 H1 | 2,147 / 361 | 312 / 47 | 336 / 50 | 637 / 98 |
| 2025 | 2019–2023 전체 + 2024 기존 H1 | 2,818 / 462 | 326 / 50 | 311 / 48 | 654 / 98 |
| 2026 | 2019–2024 전체 + 2025 기존 H1 | 3,458 / 560 | 329 / 50 | 325 / 48 | 488 / 73 |

확장 fold는 앞선 평가연도의 결과 라벨을 다음 fold H1 학습에 사용한다. 이는 frozen chronological recipe의 forward-chaining 구성이다. 비교는 표본 수만 바꾸지 않고 과거 달력 연도와 그해에 맞는 OOS score model vintage도 포함하므로, 차이를 경주 수 자체의 인과효과로 분리할 수 없다. 이 결과는 training volume과 historical regime mix를 함께 넓힌 비교다. 또한 2024~2026 경주일은 이미 반복 사용된 개발 자료다. 기존 paired bootstrap은 저장된 269개 평가 경주일의 같은 2,000회 schedule을 모든 비교에 그대로 적용하고, fit된 fold들을 조건으로 한 불확실도만 나타낸다. H1 학습 표본의 변동에 대한 재학습 bootstrap이나 독립 미래검증을 뜻하지 않는다.

## pair 모형·보정·평가의 고정 항목

기존 direct pair model의 핵심 구현을 고정 참조한다. 말별 7개 입력은 원시 raw score와 기존 여섯 style feature다. H1만으로 runner와 고정 20개 symmetric pair basis를 표준화한다. 기준 pair prior는 해당 경주 raw score에 temperature 1을 적용한 exact unordered Top3 분포의 pair marginal이다. 학습은 race-equal pair Bernoulli log loss, 고정 `lambda=1.0`, intercept 없음, L-BFGS-B의 기존 tolerance·gradient acceptance다. pair 선택은 H1 raw logit 기준으로 각 race당 하나다. 완전 편성 `field_n`은 10보다 클 수도 있으므로 최대 10두라고 가정하지 않고 모든 `C(N,2)` pair를 만든다. preflight에서 `N>=4`, 모든 pair prior finite, 양성 pair 3개를 확인한다. 현재 expanded-H1 source inventory의 최대 `field_n`은 13이다.

각 fold의 H2는 기존 경주의 동일한 H2 raw score와 pair label을 사용한다. candidate와 `logit(p0)` baseline에 positive-slope Platt를 각 1회 맞춰 평가확률만 보정하며, 총 6개 H2 map을 산출한다. H2·평가 입력과 H2 날짜는 바꾸지 않는다. 확률 품질·calibration·all-pair predictions는 fit 승인 후에만 계산한다.

평가 코호트는 기존과 동일한 1,779경주·17,412출전·269경주일이다. 직접 평가 426/1,779, raw Top2 429/1,779, saved-F1 PTop3 Top2 429/1,779, joint marginal Top2 434/1,779, candidate maximum joint pair 422/1,779, matched maximum joint pair 429/1,779 등 이전 참조는 기존 저장 출력에서 읽기 전용으로 가져온다. 모든 비교에 `outputs/date_bootstrap_schedule.npy`를 그대로 재사용한다(2,000 draw, seed 20261011, 269 dates). 새 schedule을 만들거나 H1 결과에 맞춰 표본·cutoff·primary를 바꾸지 않는다.

## 승인 게이트와 순서

1. 이 plan과 `SOURCE_AUDIT.md`에 대해 root 및 독립 reviewer가 source/설계 검토를 마친다.
2. preflight code와 lock을 새 폴더에 저장한다. 입력·hash·score role/key·source model `refit_max` T−2·roster·label 산술·H1/H2 counts·고정 evaluation key만 검증한다. 이 단계에서 historical F1 model을 fit하거나 raw score를 생성하지 않고 pair 성과도 계산하지 않는다.
3. root가 preflight와 코드를 검토한 뒤 별도 역사 refit/raw-score 승인을 내리면, 2020~2023 fold 4개를 한 번씩 실행해 calibration-year raw score만 새 폴더에 저장한다. 이후 exact historical score coverage와 source provenance를 독립 확인한다.
4. root가 concrete source lock, historical score receipt 및 preflight를 확인하고 별도 pair-fit 승인을 낸 뒤에만 expanded H1 3개 모델, H2 map 6개, 모든 evaluation pair 예측을 한 번 산출한다. 수정·재시도·추가 arm은 금지한다.
5. 기존 bootstrap schedule과 모든 locked comparator로 최종 보고서, 독립 C 재현, 한국어 README 및 artifact manifest를 완성한다. 이 산출물은 `jeju/research/20261011_pair_top3_oos_expansion_v1/` 안에 둔다. 중앙 publication은 지표·독립 검토가 완료된 뒤 fresh compare-and-swap 검토와 root의 별도 지시가 있을 때만 진행한다. 운영 등록은 이 연구 범위가 아니다.

