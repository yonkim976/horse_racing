# 통합 더러브렛 우승 확률 모델 — 격리 오프라인 실험

서울·부경 통합, 개최지별 개별, 통합 모델의 개최지별 온도 보정을 실제 학습하고 비교했다. 고정 비교 모델은 2006–2022년으로 학습하고, 2023–2024년 검증에서 개최지별 후보를 고정한 뒤 2025–2026-09-13 최종 테스트를 평가했다. 영천은 독립 학습 없이 통합 모델로 추론했다.

## 결론과 다음 실험 후보

검증 손실 기준으로 고정한 다음 후보는 **서울 partial_shared, 부경 partial_shared**이다. 영천은 항상 `integrated`를 사용한다. `selected_route`는 이 사전 결정의 테스트 성능이다. 테스트 결과를 보고 후보·하이퍼파라미터·보정값을 변경하지 않았다. 운영 승격은 수행하지 않았다.

테스트 부경에서는 보정 전 통합 모델의 log loss가 2.085600, 부분 공유 보정 모델은 2.092085였다. 보정이 모든 기간·개최지에서 우월하지 않으므로 다음 새 검증 기간에서는 부경의 보정 안정성을 우선 확인해야 한다. 이번 테스트를 재사용해 후보를 다시 고르지 않는다.

| model | value | races | log_loss | brier_score | top1_accuracy | winner_probability | top_choice_ece_10_bins |
|---|---|---|---|---|---|---|---|
| uniform | ALL | 3044 | 2.371257 | 0.905399 | 0.104468 | 0.093944 | 0.014232 |
| history | ALL | 3044 | 2.256683 | 0.881371 | 0.198095 | 0.112268 | 0.047018 |
| integrated | ALL | 3044 | 2.083090 | 0.843350 | 0.264455 | 0.166216 | 0.033224 |
| venue_specific | ALL | 3044 | 2.132548 | 0.856640 | 0.245729 | 0.163725 | 0.064765 |
| partial_shared | ALL | 3044 | 2.082697 | 0.842049 | 0.264455 | 0.154533 | 0.014028 |
| selected_route | ALL | 3044 | 2.082660 | 0.842049 | 0.264455 | 0.154554 | 0.013579 |

동일 테스트에서 개최지별 결과는 다음과 같다. 작은 표본의 차이를 개선의 확정 증거로 해석하지 않는다.

| model | value | races | log_loss | brier_score | top1_accuracy | winner_probability | top_choice_ece_10_bins |
|---|---|---|---|---|---|---|---|
| uniform | BUSAN | 1246 | 2.394562 | 0.907738 | 0.088283 | 0.091861 | 0.007318 |
| uniform | SEOUL | 1792 | 2.355654 | 0.903833 | 0.116071 | 0.095330 | 0.020741 |
| uniform | YEONGCHEON | 6 | 2.191409 | 0.887626 | 0.000000 | 0.112374 | 0.112374 |
| history | BUSAN | 1246 | 2.288952 | 0.886614 | 0.182183 | 0.108533 | 0.035707 |
| history | SEOUL | 1792 | 2.234925 | 0.877786 | 0.209821 | 0.114795 | 0.057409 |
| history | YEONGCHEON | 6 | 2.053870 | 0.863216 | 0.000000 | 0.133349 | 0.178591 |
| integrated | BUSAN | 1246 | 2.085600 | 0.843400 | 0.271268 | 0.162505 | 0.019604 |
| integrated | SEOUL | 1792 | 2.082163 | 0.843409 | 0.260045 | 0.168735 | 0.046487 |
| integrated | YEONGCHEON | 6 | 1.838396 | 0.815153 | 0.166667 | 0.184438 | 0.330722 |
| venue_specific | BUSAN | 1246 | 2.142675 | 0.859548 | 0.242376 | 0.158259 | 0.060795 |
| venue_specific | SEOUL | 1792 | 2.126492 | 0.854757 | 0.248326 | 0.167455 | 0.071783 |
| venue_specific | YEONGCHEON | 6 | 1.838396 | 0.815153 | 0.166667 | 0.184438 | 0.330722 |
| partial_shared | BUSAN | 1246 | 2.092085 | 0.843646 | 0.271268 | 0.148157 | 0.035411 |
| partial_shared | SEOUL | 1792 | 2.076924 | 0.841028 | 0.260045 | 0.158901 | 0.025848 |
| partial_shared | YEONGCHEON | 6 | 1.857351 | 0.815130 | 0.166667 | 0.174010 | 0.211765 |
| selected_route | BUSAN | 1246 | 2.092085 | 0.843646 | 0.271268 | 0.148157 | 0.035411 |
| selected_route | SEOUL | 1792 | 2.076924 | 0.841028 | 0.260045 | 0.158901 | 0.025848 |
| selected_route | YEONGCHEON | 6 | 1.838396 | 0.815153 | 0.166667 | 0.184438 | 0.330722 |

## 검증에서의 모델 선택

| model | value | races | log_loss | brier_score | top1_accuracy | winner_probability | top_choice_ece_10_bins |
|---|---|---|---|---|---|---|---|
| uniform | BUSAN | 1448 | 2.384467 | 0.905491 | 0.104282 | 0.092783 | 0.011499 |
| uniform | SEOUL | 2101 | 2.351781 | 0.903181 | 0.094717 | 0.095867 | 0.004009 |
| history | BUSAN | 1448 | 2.302998 | 0.889776 | 0.165746 | 0.106193 | 0.025277 |
| history | SEOUL | 2101 | 2.269991 | 0.885783 | 0.185150 | 0.110160 | 0.036736 |
| integrated | BUSAN | 1448 | 2.110510 | 0.850168 | 0.250691 | 0.162326 | 0.047246 |
| integrated | SEOUL | 2101 | 2.108779 | 0.854623 | 0.247025 | 0.163941 | 0.060520 |
| venue_specific | BUSAN | 1448 | 2.164234 | 0.865697 | 0.232735 | 0.158309 | 0.075486 |
| venue_specific | SEOUL | 2101 | 2.153053 | 0.867828 | 0.235602 | 0.160598 | 0.080312 |
| partial_shared | BUSAN | 1448 | 2.106744 | 0.846903 | 0.250691 | 0.148401 | 0.021301 |
| partial_shared | SEOUL | 2101 | 2.098708 | 0.850053 | 0.247025 | 0.155198 | 0.027599 |

`integrated`: 서울·부경 공통 모델. `venue_specific`: 서울·부경 각각의 독립 모델, 영천은 공통 모델 대체. `partial_shared`: 통합 점수에 학습기간 내부의 개최지별 온도 보정. `history`: 고정 사전분포를 사용한 엄격한 과거 승률 점수. `uniform`: 출전마별 1/N.

온도 보정용 보조 모델은 2006–2021년에 학습하고 2022년에 온도를 추정했다. 공통 최종 모델은 2006–2022년으로 다시 학습했다. 검증·테스트 라벨은 보정에 사용하지 않았다. 보조 모델과 다시 학습한 모델 간 점수 분포 변화는 보정의 한계다. 고정 분할 외에 2019–2024년 각각을 대상으로 과거 기간을 확장하는 여섯 번의 연간 검증을 수행했다. 각 fold는 자기 학습기간 안에서 범주 사전과 보정을 새로 적합했다. 연간 결과는 `metrics.csv`의 `expanding_*`에 있다.

## 데이터·모집단·누수 처리

- 원본 410,168행, 36,748경주를 파생 데이터에 보존했다. 실격·미완주는 우승 목표 0이다. 동착 1위는 각 말에 1/동착 우승마 수의 질량을 부여한다.
- 영천 54행은 원본 숫자 착순이 NULL인 변환 누락이 있었다. 공식 결과의 숫자 `finish_raw`를 파생 데이터에 정규화하고 원래 열과 수정 근거를 보존했다. 원본 DB는 변경하지 않았다. 자세한 내용은 `issues.json`, `data_validation.json`에 있다.
- `full_card`는 공급된 결과 기반 출전행 전체다. 실제 사전 출전표의 완전한 보존 여부와 취소 정보 공개 시각은 증명되지 않았다. `final_starters`는 완주·실격·미완주 행만 남기고 같은 모델의 확률을 재정규화한 조건부 평가로, 사후 집단 확인을 사용한다.
- 당일 체중·증감·날씨·주로·장구·배당을 제외했다. 조교·진료도 사건일이 과거라는 사실과 공개 시각을 구분해, 가용 시각 미검증으로 기본 피처에서 모두 제외했다. 미확정 Text 진료 연결은 사용하지 않는다. 부경 구간기록은 사용하지 않는다.
- 모든 과거 경력은 날짜 단위로 재계산해 같은 날 결과를 배제했다. 2006년 이전 자료는 과거 이력의 warm-up에만 쓰였다. 테스트 기간에서도 현재 경주일보다 앞선 결과를 과거 피처에 활용하는 순차 예측 조건이다. 모델 가중치는 갱신하지 않는다.
- 비확정 과거 자료 251경주·2,872행을 이력 계산에서 제외했다. 그중 2026-08-26 자료에는 같은 말이 서울·부경에 중복 기재된 103건이 있었다. 이 수정으로 원본의 과거 이력과 달라진 목표 출전행은 23,988개다. 과거 `starts` 계열은 확정 경주의 출전 기록 수이며, 과거 취소 행까지 포함하므로 실제 출발 횟수와 구분해야 한다.
- ID는 문자열 범주이며 학습기간의 값만 사전에 적합한다. 미지/결측 범주는 공통 대체 범주, 수치 결측은 LightGBM의 결측 분기를 사용한다. ID target encoding은 없다.
- 과거 출전표의 rating/부담중량/관계자 등은 해당 경주 기록의 출전 정보로 취급한다. 원천 수집 시각까지 보장된 라이브 재현은 아니므로 운영 투입 전 실제 시점별 출전표 검증이 필요하다.

피처 수: 범주형 13개, 수치형 25개. 확정 목록은 `features.json`, 계산식·자료형·가용성은 `feature_dictionary.md`, 실제 행 데이터는 `prepared.parquet`이다.

분할: `{"train": {"rows": 339337, "races": 30155, "first_date": "2006-01-06", "last_date": "2022-12-25"}, "validation": {"rows": 38036, "races": 3549, "first_date": "2023-01-06", "last_date": "2024-12-29"}, "test": {"rows": 32795, "races": 3044, "first_date": "2025-01-03", "last_date": "2026-09-13"}}`

## 평가 정의와 해석

경주별 log loss는 `-sum(y * log(p))`, Brier는 `sum((p-y)^2)`이고 경주를 동일 가중 평균한다. 동착 라벨에 대한 Brier이므로 one-hot 일반형의 최솟값 해석과 구분한다. top-1/top-3는 공식 우승마 중 하나라도 예상 순위 안에 있으면 적중이다. 실제 우승마 평균 확률과 MRR은 동착 질량으로 가중한다. 정렬 동점은 출전번호와 공식 말 ID로 결정한다. 균등 모델 적중률은 이 결정적 동점 규칙에 의존하므로 log loss·Brier 비교를 우선한다.

ECE는 경주별 최고 예측확률을 10개 고정 구간으로 나눈 뒤 top-1 적중률과 비교한 경주 가중 값이다. `calibration.csv`와 `calibration.png`는 출전행의 예측확률 대비 관측 승리 질량을 별도로 보여준다. 수익률·베팅 실험은 수행하지 않았다.

![Test calibration](/Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_model_20260918_v1/calibration.png)

테스트 선택 후보와 균등 모델의 log loss 차이는 `bootstrap_comparison.json`에 경주일 단위 2,000회 bootstrap으로 기록했다. 음수가 개선이다. 영천은 단 하루여서 이 신뢰구간을 계산하지 않았다.

## 실패 구간과 한계

테스트에서 균등 기준 대비 손실 차이가 가장 큰 구간 15개를 표본 수와 함께 그대로 공개한다. 모든 구간은 `test_slice_diagnostics.csv` 및 `metrics.csv`에 있으며 작은 구간도 숨기지 않았다. 출전두수·거리·등급·월·연도·원정마/신규마 포함 여부별 진단이다. 원정/신규마 구간은 해당 말이 한 두라도 포함된 **경주 단위** 분할이다.

| dimension | value | races | log_loss | log_loss_uniform | log_loss_delta | top1_accuracy |
|---|---|---|---|---|---|---|
| distance_m | 2300 | 3 | 2.522502 | 2.384872 | 0.137630 | 0.333333 |
| field_size_band | 1-7 | 2 | 1.962154 | 1.945910 | 0.016244 | 0.000000 |
| distance_m | 2200 | 1 | 2.386702 | 2.397895 | -0.011193 | 0.000000 |
| race_class | 혼OPEN | 45 | 2.455737 | 2.484157 | -0.028420 | 0.133333 |
| has_away_horse | 1 | 54 | 2.523652 | 2.573852 | -0.050199 | 0.092593 |
| field_size_band | 14+ | 32 | 2.638604 | 2.733295 | -0.094691 | 0.093750 |
| distance_m | 1000 | 71 | 2.181384 | 2.308323 | -0.126939 | 0.183099 |
| race_class | 1등급 | 72 | 2.179948 | 2.328152 | -0.148204 | 0.194444 |
| month | 2025-07 | 125 | 2.158368 | 2.322055 | -0.163687 | 0.248000 |
| month | 2025-02 | 119 | 2.242759 | 2.426064 | -0.183305 | 0.235294 |
| month | 2025-04 | 140 | 2.215643 | 2.410092 | -0.194449 | 0.257143 |
| race_class | 국OPEN | 42 | 2.263158 | 2.467387 | -0.204229 | 0.166667 |
| distance_m | 2000 | 58 | 2.175388 | 2.384972 | -0.209584 | 0.241379 |
| month | 2025-01 | 148 | 2.161545 | 2.399825 | -0.238280 | 0.195946 |
| month | 2025-06 | 153 | 2.084572 | 2.327604 | -0.243032 | 0.235294 |

## 영천 6경주 cold-start

| race_id | entries | predicted_winner | actual_winner | top1_hit | history_available |
|---|---|---|---|---|---|
| RACE:YEONGCHEON:20260913:01 | 8 | 파초의꿈 | 모멘텀 | False | 8 |
| RACE:YEONGCHEON:20260913:02 | 9 | 정문파피아노 | 정문파피아노 | True | 9 |
| RACE:YEONGCHEON:20260913:03 | 8 | 스텔스킹맨 | 오아시스영 | False | 8 |
| RACE:YEONGCHEON:20260913:04 | 9 | 성실드림 | 하늘신화 | False | 9 |
| RACE:YEONGCHEON:20260913:05 | 9 | 해운대파워 | 플라잉레이스 | False | 9 |
| RACE:YEONGCHEON:20260913:06 | 11 | 바람대로 | 레몬트리 | False | 11 |

영천 54두 중 과거 이력 보유 행은 54개다. 각 말의 이전 개최지와 이력 수를 예측 파일에 포함했다. 새 개최지 `YEONGCHEON` 및 개최지×거리×등급 범주는 학습 중 관측되지 않았으므로 미지 범주로 처리했다. 숫자 개최지 코드로 거리를 가정하지 않는다. 6경주·하루 표본으로 영천 성능 일반화를 주장할 수 없다.

## 재현과 추론

현재 실행 환경은 `environment.json`에 기록했다. 새 패키지 설치 없이 프로젝트 `.venv`를 사용했다. 모델은 고정 seed=20260918, LightGBM cross_entropy 300회, 31 leaves, learning_rate=0.05, 4 threads다. 경주당 학습 행 가중치 합은 1이고 출력 raw margin을 경주 내 softmax로 변환한다. 이것은 순위 모델 최적화가 아닌 경주 단위로 정규화한 트리 기준 모델이다.

새 결과 경로에서 전체 재현:

```bash
cd /Users/kimyongjin/Desktop/horse_racing
.venv/bin/python /Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_model_20260918_v1/code/reproduce.py --output data/research/thoroughbred_model_20260918_reproduction
```

현재 저장된 통합 모델의 추론:

```bash
cd /Users/kimyongjin/Desktop/horse_racing
.venv/bin/python /Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_model_20260918_v1/code/infer.py \
  --input /Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_model_20260918_v1/inference_smoke_input.parquet \
  --bundle /Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_model_20260918_v1/models/fixed/integrated \
  --output /private/tmp/thoroughbred_new_predictions.parquet
```

검증에서 고정한 개최지별 선택 경로 추론은 `code/infer_selected.py --run-dir ... --input ... --output ...`를 사용한다. 입력은 `feature_dictionary.md`대로 작성된 완전한 경주별 피처 표이며 신규 경주의 외부 자료 수집은 포함하지 않는다. 날짜가 있는 모든 과거 자료는 경주일 미만이어야 한다. 추론은 사후 라벨을 필요로 하지 않는다.

산출물에는 학습·평가·추론 코드, 각 fold와 고정 모델, 사전/결측 규칙, validation/test 예측 Parquet, 보정·피처 중요도, 독립 검토와 자동 검증, SHA-256 manifest가 있다. `preservation_check.json`은 운영 DB·기존 모델·registry·예측 경로와 원천 데이터의 전후 해시를 비교한다. `manifest.json`은 자기 자신과 실행 캐시를 제외한 산출물 해시를 기록한다.

준비 데이터 검사 26/26개, 단위 테스트 14개, 학습 후 산출물 검사 540/540개를 통과했다. 마지막 검사에는 28개 저장 모델의 학습기간·범주 사전, 22개 예측 파일의 키·확률합·순위, 라벨 없는 입력을 사용한 선택 경로 추론 재현과 부분 카드 거부가 포함된다.

보존 검사는 기존 핵심 파일의 내용 보존과 전체 작업공간의 동일성을 구분한다. 작업공간 전체는 완전히 동일하지 않았다. 변경 또는 누락 경로: ['data/predictions/.DS_Store']. 새로 관측된 외부 경로: ['data/research/jeju_steward_pace_v2_pilot_20260918/bundles/PACE_BURDEN.pkl', 'data/research/jeju_steward_pace_v2_pilot_20260918/bundles/STEWARD.pkl', 'src/horse_racing/analysis/jeju_steward_events_v2.py', 'src/horse_racing/analysis/jeju_wager_probabilities.py']. 기존 모델·DB 해시 동일 여부: True. 스냅샷 차이만으로 작성 주체를 추정하지 않는다. 이 실험의 쓰기는 격리 경로 안에서만 수행했다. 기존 파일 변경, Finder 메타데이터, 새 외부 파일을 구분한 상세 기록은 `preservation_check.json`에 있다.
