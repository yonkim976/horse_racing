# 제주 축선택 모델 독립 검토

이 검토는 `F1_STYLE6` 상위 후보 중 입상 축 한 마리를 고르는 보조 모델의 데이터 출처·시점 경계와 완료된 고정 평가를 독립 확인한다. 기준 모델은 기존 `F1_STYLE6`로 유지하고, 후보군에서 한 마리를 고르는 단일 소형 모델을 2024–2026에 후향 비교했다. 이 기간은 이미 반복 개발에 사용됐으므로 새 독립 holdout으로 부르지 않는다.

## 독립 검산 결과

2019–2025 selector 학습용 F1 raw score는 각 target year 다음 해의 `F1_STYLE6_{year+1}/calibration_scores.parquet`에서 읽었다. 2019–2022는 2026-10-11 historical refit 산출물이고, 2023–2025는 고정 F1_STYLE6 저장 fold의 calibration scores다. 7개 연도 모두 runner key가 frozen feature 표본과 완전히 일치하고 unique·finite였으며, 각 provider 모델의 `refit_max`가 그 해 가장 이른 경주일의 T−2보다 앞섰다. 2019–2022 역사 refit 영수증은 raw calibration 점수만 만들었고 temperature 최적화, 평가 점수, 지표 및 pair fit은 만들지 않았다고 기록한다.

동결된 2024–2026 F1 평가도 같은 30개 입력, 저장 `evaluation_scores`, 저장 tau를 읽어 확률만 다시 계산했다. 평가 출력 `baseline_runner_predictions.parquet`와 score, `p_top3`, 실제 Top3 label이 세 연도 모두 runner별로 정확히 일치했다(17,412두, 1,779경주). 이는 저장 점수의 결정적 재계산이며 새 모델 학습이 아니다. 확률은 raw score의 단순 logistic 변환이 아니라 race 단위 exact unordered Top3 분포의 말별 주변확률이다.

전체 입력 피처의 history cutoff는 경주일 T−2이고, 확인 가능한 history source date는 cutoff를 넘지 않았다. `style_history_lineage`도 target cutoff와 source date를 전수 대조했다. 원천 table·저장 prediction에는 배당/인기 필드가 없다. 성능 표본은 동결 기준과 같이 4개 거리(900·1000·1110·1200m) 1,503경주를 주 평가로, 전체 1,779경주를 보조로 삼아야 한다. 1,477 favorite 경주 코호트는 이 검토에 사용하지 않았다.

## 고정 selector의 결과와 독립 재생

사전 등록한 K=3 pairwise selector 세 개를 승인된 코드 그대로 한 번씩 적합했다. `verify_fit.py`는 저장 계수로 목적값·해석적 gradient를 다시 계산하고, frozen 입력에서 학습 scaler, 후보 utility, 경주별 축 선택, 지표, 2,000회 날짜 paired bootstrap을 재생했다. 계수 최적화나 추가 fit은 하지 않았다. 37개 잠금 입력과 각 모델·예측·평가 산출물 해시, 학습·평가 provider 역할을 확인했으며 2019–2025 학습 점수는 해당 연도 라벨을 사용하지 않은 다음 해 OOS calibration raw score였다. 2024–2026 평가 입력의 frozen raw score와 `p_top3` 값도 후보 ledger에 그대로 대응됐다.

주 코호트 1,503경주에서 기준 축은 861회(57.285%), selector 축은 857회(57.019%) 입상했다. 차이는 **−0.266 percentage point**이며, 동일 날짜 paired bootstrap 95% percentile 구간은 **[−1.081, +0.586] pp**다. 50경주에서 축이 바뀌었고, 그중 selector만 입상한 경주는 13, 기준만 입상한 경주는 17이었다. 사전 성공 조건인 양의 점추정치와 95% 구간 하한 양수를 충족하지 못했다.

전체 거리 1,779경주에서는 기준 1,023회(57.504%), selector 1,016회(57.111%)로 차이는 −0.393 pp였다. K=5는 별도 selector가 아니라 후보 coverage 진단이며, 주 코호트의 1,477/1,503경주(98.270%)에 입상마가 한 마리 이상 있었다. 이 결과를 근거로 selector를 보류하고 `F1_STYLE6`를 유지한다. 후향 표본의 결과는 미래 검증, 수익성 또는 운영 승격 증거가 아니다.

독립 replay에서 학습 scaler 최대 차이는 0, 목적값 최대 차이는 `1.11e-16`, gradient 최대 차이는 `3.47e-16`, 후보 utility 및 bootstrap CI 최대 차이는 0이었다. 5,337개 K=3 후보와 1,779개 경주 선택을 모두 재계산해 저장 결과와 일치시켰다.

## 모델 준비 전 잠금 조건

- 모델 한 종류와 모든 설정을 결과 확인 전에 고정한다. 2024 평가 모델은 selector label을 2023년까지, 2025 모델은 2024년까지, 2026 모델은 2025년까지 사용한다. 이는 한 고정 알고리즘의 연도별 expanding refit이며, 2024–2026 전체 라벨로 한 번 적합해 같은 기간에 보고하는 방식은 허용되지 않는다.
- selector 학습 race의 base score는 위 `calibration_scores` raw score와 provider role을 사용한다. 해당 calibration 연도 라벨로 맞춘 provider tau를 같은 연도 학습 행에 적용해 만든 `p_top3`는 학습 입력으로 쓰지 않는다. 기존 frozen 평가의 score와 `p_top3`는 비교값으로 원본 그대로 보존한다.
- 고정된 30개 `F1_STYLE6` 입력과 score/`p_top3`를 `api_record_id`로 한 번만 연결하고 race/horse identity, 입력 순서, 해시, 중복·누락을 검사한다. 기존 runner prediction이나 연구 산출물을 덮어쓰지 않는다.
- K=3에서 한 마리를 고르는 선택 적중률을 주 결과로 사전 고정한다. K=5는 고정 후보군이 실제 상위 3두를 얼마나 포함하는지에 대한 coverage 진단으로만 둔다. 후보 순위 동점·정렬, 연도별 refit, 완전 출전마 요건, 날짜 단위 paired 불확실도 계산도 결과를 보기 전에 문서화한다.
- 배당과 인기·favorite ID를 입력 또는 표본 필터로 쓰지 않는다. 2024–2026 평가 전체에서 같은 경주를 비교하며 날짜 단위 paired 구간과 거리/연도별 반례를 함께 보고한다. 주 표본은 1,503경주, 전체 1,779경주는 보조 분석으로 표시한다.

## 범위

평가 모집단은 동결된 실제 출발마 roster를 재사용하므로 당일 실제 출전집합이 사전에 완전히 알려졌다는 뜻은 아니다. 결과는 이 고정 사후 roster 조건의 역사 replay로 표현한다.

검토 코드는 읽기 전용 원천·모델 산출물을 확인하고 `outputs/SOURCE_REVIEW.json`과 `outputs/FIT_REVIEW.json`만 이 검토 폴더에 쓴다. 데이터베이스 연결, 외부 자료 수집, 모델 추가 학습, 운영 등록부 수정은 수행하지 않았다.

재현: `.venv/bin/python jeju/research/20261020_axis_selector_review_v1/verify_source.py` 및 `.venv/bin/python jeju/research/20261020_axis_selector_review_v1/verify_fit.py`
