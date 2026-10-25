# Pair 기록 지원·분산 입력 원천 검토

상태: 2026-10-14 읽기 전용 원천·시점·키 검토. DB와 네트워크에 접속하지 않았고, 모델을 적합하거나 pair 성능·정답률을 계산하지 않았다. 직접 확인한 Parquet 내용 검사는 `api_record_id`, 날짜, 이력 count/time 요약 열만 읽었으며 현 경주 착순 열은 읽지 않았다. 기존 연구의 저장된 원천 감사·분할 영수증과 구현 코드를 참조했다.

## 원천과 계산 정의

고정 입력은 [`features.parquet`](../../20261010_style_history_ablation_v1/outputs/features.parquet)다. 파일 SHA-256은 `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f`, 52,155행이다. 요청된 원천 열과 최근 동일거리 시간 창은 [말 프로필 입력 구현](../../20261008_horse_profile_baseline_v1/run.py)의 `read_source`, `card`, `build_features`에서 확인했다. [입력 계약](../../20261008_horse_profile_baseline_v1/CONTRACT.md)은 자료의 부재를 평생 경력 0으로 해석하지 않고, 400m 이력은 경력에만 포함하며, 동일거리 최근 5회 창은 유효시간이 아니라 실제 출전 슬롯 기준으로 유지한다고 명시한다.

- `observed_starts`: 예측 기준일에서 2일 전까지 보유 원천에서 확인된 모든 거리의 `started` 출전수다. `started`는 착순 1–89 또는 91·92다. 현재 모델의 대상 거리만 세는 값은 아니며, 400m 등 다른 거리의 이력도 경력수에 포함될 수 있다.
- `same_valid_times`: 정확히 같은 거리의 과거 `started` 기록 중 정상 착순 1–89이고 `finish_time_seconds > 0`인 시간 관측 수다. 전체 보유 과거 조회 범위 안의 count이며 완전한 생애 census가 아니다. `same_starts`와 달리 시간 없는 DNF·실격은 세지 않는다.
- `days_since_same`: 대상 경주일과 가장 최근 동일거리 `started` 출전일의 달력일 차이다. 최근 기록이 유효시간인지 검사하지 않으므로, 시간 결측·DNF·실격인 최근 동일거리 출전도 날짜를 결정한다. 원천 정의는 `same_valid_times`의 “마지막 유효시간까지의 간격”이 아니다.
- `valid_n5`, `mean5_s`: T−2까지의 실제 동일거리 출전 슬롯 중 가장 최근 5개에서 정상 착순·양수 시간이 확인된 슬롯 수(0–5)와 해당 시간 평균이다. 실패·시간결측 슬롯은 창 안에 남고 더 오래된 유효시간으로 채우지 않는다. 시간 단위는 초다.
- `std5_s`: 위와 같은 최근 5개 실제 슬롯에서 유효한 시간의 표본 표준편차, `ddof=1`이다. 원천 코드가 `valid_n5 >= 3`일 때만 산출한다. `valid_n5`가 1 또는 2이면 NULL이며, 한 관측을 표준편차 0으로 취급하지 않는다. 이에 따라 CV도 유효한 `std5_s`가 실제로 있을 때만 계산해야 하며 2개 관측의 표준편차를 이 후보에서 새로 계산하지 않는다.

이 정의에 맞춰 root는 recency 요약을 “동일거리 실제 출전 간격”으로 명명하고 `same_starts > 0`을 가용성 조건으로 쓰며, `same_valid_times` 지원량은 별도 pair 입력으로 둔다고 승인했다. 따라서 과거 제안의 `same_valid_times > 0` recency gate는 채택하지 않는다. `log1p(days_since_same)`를 pair로 요약하더라도 최근성은 마지막 실제 출전 날짜를 가리킨다.

CV `std5_s / mean5_s`는 같은 목표 거리의 원기록 시간 변동을 나타내는 무차원 설명량이다. 등급·주로·부담중량 등 기록 조건 변화도 섞이므로 원천의 정확도·완전성, 말의 생리적 안정성, 기록 신뢰도 또는 인과 효과로 단정할 수 없다. Pair 입력 이름과 설명은 “최근 동일거리 원시간 CV/분산 proxy” 수준에 머물러야 한다. 유효한 `std5_s`가 없는 말은 CV 미가용으로 세고 0으로 대체하지 않는다.

## 캐시 일관성과 시점

Parquet 스키마에서 위 원천 열과 `same_starts`, `race_date`, `history_cutoff`, `api_record_id`가 모두 확인됐다. 읽기 전용 content check는 52,155행 전부에서 API ID가 non-null·unique, `history_cutoff = race_date − 2일`, `same_valid_times ≤ same_starts ≤ observed_starts`, 동일거리 gap 결측이 `same_starts=0`과 일치하고 gap이 2일 이상, `mean5_s` 결측이 `valid_n5=0`과 일치, `std5_s`는 n<3에서 NULL·n≥3에서 finite/nonnegative임을 확인했다. 검사는 outcome/착순 열을 읽거나 요약하지 않았다.

이력 계산은 각 대상 출전의 `race_date − 2 calendar days`를 cutoff로 하며, 그 날짜까지의 공식 말 ID 동일거리 `started` 행을 사용한다. target 행의 `finish_position`은 frozen table에 라벨로 저장되지만, 위 여섯 원천 요약은 cutoff 이전 `past/same` 기록으로만 계산된다. 새 reliability 입력 계산에는 현 경주 `finish_position`을 포함하지 말고, pair 라벨 생성과 물리적으로 구분해야 한다. 게시·정정 timestamp가 없어 날짜 cutoff는 과거 데이터 가용성의 완전 재생 증거가 아니다.

## 기존 OOS 키·score provider·분할

기존 [역사적 direct-pair 원천 감사](../../20261011_pair_top3_oos_expansion_v1/SOURCE_AUDIT.md)와 [source preflight](../../20261011_pair_top3_oos_expansion_v1/outputs/HISTORICAL_PREFLIGHT.json), [pair fit 구현](../../20261011_pair_top3_oos_expansion_v1/pair_fit.py), [jockey 입력 분할 구현](../../20261012_pair_jockey_basic_v1/pair_jockey_fit.py)을 확인했다. 원천 feature row는 `api_record_id` 유일 키이고, raw-score parquet도 `(api_record_id, score)` 유일 구조다. 각 연도 score-key 집합을 해당 연도 feature row와 대조하고 `api_record_id` one-to-one join 및 T−2 시점 검사를 한다. 소스 감사는 2019–2025 historical input의 공식 API ID 연결과 `race_id`, `horse_id`, 날짜 일치, 2024–2026 eval roster의 연결을 이미 확인했다.

기존 score provider 계약은 다음과 같다.

- 2019–2025 라벨 연도 `c`의 H1/H2 raw runner score는 provider fold `c+1`의 `calibration` 역할이다. 2019–2022 점수는 별도 역사 refit fold 2020–2023, 2023–2025 점수는 저장 F1_STYLE6 fold 2024–2026에서 온다. 2017–2018은 이 pair H1용 recipe-valid OOS score가 없어 제외한다.
- pair 평가 fold `Y`의 H1은 2019년부터 `Y−2`까지의 완전 연도와 `Y−1`년 상반기 중 첫 H2 경주일보다 최소 2일 앞선 경주를 합친다. H2는 `Y−1`년 7월 이후, evaluation은 연도 `Y`다. H1 moments만 학습하고 H2에서 Platt 보정한다.
- evaluation 연도 `Y`는 provider fold `Y`의 `evaluation` 역할 점수를 쓴다. 같은 과거 `api_record_id`가 다른 pair 평가 fold에서 다른 provider role로 다시 쓰일 수 있다. 따라서 runner source row 키는 `(pair_evaluation_year, split_role, api_record_id, score_provider_fold_year, score_provider_role)`처럼 fold·role 문맥을 보존하고, 파일 전체에서 API ID만으로 deduplicate하지 않는다.

| pair fold | H1 구성·행/경주/일 | H1 실제 마지막 날짜 | H2 행/경주/일 | H2 날짜 범위 | Eval 행/경주/일 | H2 마지막 → Eval 첫 날짜 |
|---:|---|---|---:|---|---:|---|
| 2024 | 2019–2022 전체 + 2023 상반기; 21,861 / 2,147 / 361 | 2023-06-24 | 3,327 / 336 / 50 | 2023-07-01–2023-12-30 | 6,329 / 637 / 98 | 2023-12-30 → 2024-01-05 (6일) |
| 2025 | 2019–2023 전체 + 2024 상반기; 28,522 / 2,818 / 462 | 2024-06-29 | 3,085 / 311 / 48 | 2024-07-05–2024-12-28 | 6,410 / 654 / 98 | 2024-12-28 → 2025-01-03 (6일) |
| 2026 | 2019–2024 전체 + 2025 상반기; 34,845 / 3,458 / 560 | 2025-06-28 | 3,172 / 325 / 48 | 2025-07-04–2025-12-27 | 4,673 / 488 / 73 | 2025-12-27 → 2026-01-02 (6일) |

2026 evaluation은 9월 19일까지 부분연도다. H1/H2/EVAL은 모두 앞선 연구에서 반복 사용된 날짜·라벨을 포함하므로 새 독립 미래 검증이 아니다. H1/H2 race-count·행수는 기존 preflight의 고정 cohort이며 outcome rate가 아니다.

기존 [direct-pair plan](../../20261011_pair_top3_oos_expansion_v1/PLAN.md)은 H1→H2와 H2→evaluation 모두 최소 2일 purge를 요구하지만, 기존 `pair_fit.py` 및 `pair_jockey_fit.split_h1_h2`의 실행 assertion은 H1→H2 경계만 직접 검사한다. frozen 날짜에서 H2→Eval은 세 fold 모두 6일 차이로 조건을 만족한다. 새 source preflight는 이 현재 사실에만 기대지 말고 두 경계를 모두 날짜만으로 명시 검사해야 한다.

## 새 pair 입력 연결 전 확인 사항

새 runner context는 위 고정 feature 파일에서 필요한 source 열만 `api_record_id`로 가져와, 기존 runner·score row와 1:1로 붙이는 것이 맞다. join 뒤 `race_id`, `horse_id`, `race_date`를 재대조하고 각 race 내 `horse_number`가 유일함을 확인한다. 그 후 pair basis와 선택키는 같은 race에서 정렬한 `(horse_number_i, horse_number_j)`와 맞춘다. 기존 pair predictor의 평가 output은 pair grain이므로 API ID를 pair ID처럼 쓰지 않는다.

preflight에서 source SHA/schema/key coverage, fold·split/provider-role 유일성, H1-only train moments, 원천 결측 패턴, cutoff, H1→H2 및 H2→Eval 경계를 고정한다. H1-only runner·pair moments를 구하고 raw pair 결측은 H1 평균 대치 후 표준화 0으로 두며 별도 결측 count를 유지한다. H2나 EVAL에서 moments를 다시 추정하지 않는다. 이 문서는 source 검토이며 새로운 fit 승인이나 성능 판단을 포함하지 않는다.
