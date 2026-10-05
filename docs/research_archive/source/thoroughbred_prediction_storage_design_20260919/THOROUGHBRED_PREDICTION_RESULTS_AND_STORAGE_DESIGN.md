# 더러브렛 예측 결과와 저장 설계

작성일: 2026-09-19  
범위: 기존 데이터·기존 모델·기존 연구 산출물의 읽기 전용 점검과 저장 설계  
상태: 설계 문서만 작성. 운영 DB, 모델, 원천 데이터, 기존 연구 산출물은 변경하지 않음

## 1. 결론

더러브렛 예측의 운영 원본은 **모든 출전마의 말별 행**으로 저장한다. 현재 A 확률 294건을 전부 저장하고, B/C 조합 행은 DB에 적재하지 않는다. 대신 B/C를 정확히 재계산하는 데 필요한 말별 원시 점수, 목표별 보정값, 모델 해시, 조합 알고리즘 버전을 함께 저장한다. 백엔드는 한 경주의 모든 말 행을 읽어 B와 C의 전체 분포를 결정적으로 재계산한 다음 상위 K개만 응답한다.

핵심 결정은 다음과 같다.

1. `model_predictions`에는 모든 출전마가 반드시 한 행씩 존재한다.
2. `prob_top3`에는 현재 채택 A의 `A_slot_inclusion_probability`를 저장한다.
3. `prob_win`과 `prob_top2`는 B/C 값을 섞지 않고, A 계산 때 이미 만들어지는 동일한 A 공동분포에서 주변화한 값만 저장한다.
4. A, B, C는 서로 다른 보정을 사용하므로 A 확률을 곱해 B를 만들거나 B/C 확률을 다시 곱하지 않는다.
5. B/C 조합 자체는 저장하지 않는다. `raw_a_top3_score`, `raw_bc_top3_score`, `raw_win_score`와 보정 메타데이터를 저장하고 백엔드에서 재계산한다.
6. 설명은 LightGBM 원시 점수 기여도로 별도 저장하며 인과적 이유로 표현하지 않는다.
7. 초기 출마표와 경주 직전 갱신은 서로 다른 불변 run으로 남기고, 최종 `live` 발행은 경주별 한 번만 허용한다.

## 2. 확인한 입력과 근거

다음 파일을 읽어 확인했다.

- 구현 요구 문서: `docs/PREDICTION_PROBABILITY_RECOMMENDATION_SERVING_AGENT_PROMPT_2026-09-19.md`
- A 말별 확률: `data/research/thoroughbred_boundary_20260918_v6/future_predictions_20260919_20/A_predictions.parquet`
- B/C 상위 조합: `data/research/thoroughbred_boundary_20260918_v6/future_predictions_20260919_20/B_C_top10_predictions.parquet`
- 예상표: `data/research/thoroughbred_boundary_20260918_v6/UPCOMING_PREDICTIONS.md`
- v6 추론 코드: `data/research/thoroughbred_boundary_20260918_v6/infer.py`
- A 모델: v5 `windows/models/2026H2/rolling_all`
- B/C 모델: v4 `model/models/2026/top3_growth_strength`
- 순서용 우승 점수 모델: v2 `models/2026/H3_relative`
- 피처 계약: `data/research/thoroughbred_three_targets_20260918_v3/FEATURE_DICTIONARY.md`

현재 채택은 A=`current_A`, B=`current_B`, C=`current_C`다. A는 v5 반기 `rolling_all`, B/C는 v4 연간 `top3_growth_strength`를 유지한다.

## 3. Supabase 디스크 경고 진단

스크린샷의 메시지는 프로젝트에 할당된 데이터베이스 디스크의 여유가 부족해지고 있다는 경고다. Supabase에서 데이터베이스 크기와 디스크 사용량은 다르다. 디스크에는 실제 테이블·인덱스 외에 WAL과 시스템 파일도 포함된다.

2026-09-19 읽기 전용 점검값은 다음과 같다.

| 항목 | 측정값 |
|---|---:|
| 프로젝트 상태 | `ACTIVE_HEALTHY` |
| DB 읽기 전용 여부 | `off` — 현재 쓰기 가능 |
| 실제 PostgreSQL DB 크기 | 3,991,391,379 bytes, 약 3.8GB |
| WAL 디렉터리 | 1,996,489,068 bytes, 약 1.9GB |
| DB + WAL | 약 5.7GB, 시스템 예약분 제외 |
| 복제 슬롯 | 0개 |
| autovacuum | `on` |
| 관측 dead tuple | 주요 사용자 테이블에서 0 |

큰 테이블은 `horse_training` 약 1.79GB, `odds_snapshots` 약 741MB, `race_section_results` 약 349MB다. `horse_training`만 테이블 약 931MB와 인덱스 약 860MB를 사용한다.

복제 슬롯이 없어 중단된 복제 슬롯이 WAL을 붙잡는 문제는 아니다. 프로젝트 생성 직후 약 2,050만 행을 대량 이전했으므로 현재 1.9GB WAL은 그 대량 쓰기에서 발생한 일시적 WAL일 가능성이 높다. 이는 측정값에 근거한 추론이며, Supabase 디스크 분포 화면에서 WAL이 실제로 감소하는지 후속 확인해야 한다.

현재 프로젝트는 정상·쓰기 가능 상태이므로 데이터 삭제나 `VACUUM FULL`을 즉시 실행할 근거는 없다. `VACUUM FULL`은 테이블 잠금과 추가 작업 공간을 요구하므로 운영 직전 임의 실행하지 않는다.

Supabase Pro의 기본 gp3 디스크는 프로젝트당 8GB가 포함된다. 공식 현재 가격은 8GB 초과분에 대해 월 GB당 USD 0.125이며 시간 단위로 계산된다. 자동 확장이 8GB에서 12GB로 발생하면 추가 4GB의 한 달 최대 비용은 세전 약 **USD 0.50/월**이다. Spend Cap이 켜져 있으면 초과 사용 제한이 적용될 수 있다. 이 문서 작성 과정에서는 디스크 증설이나 결제를 실행하지 않았다.

공식 근거:

- <https://supabase.com/docs/guides/platform/database-size>
- <https://supabase.com/docs/guides/platform/manage-your-usage/disk-size>
- <https://supabase.com/docs/guides/platform/cost-control>

## 4. 현재 예측 파일 검증 결과

### 4.1 A 파일

| 검증 항목 | 결과 |
|---|---:|
| 경주 수 | 27 |
| 말별 행 수 | 294 |
| `(race_id, hr_no)` 중복 | 0 |
| A 확률 null | 0 |
| 경주별 순위 1..출전두수 완전성 | 27/27 경주 통과 |
| 경주별 A 확률 합 3과의 최대 오차 | `8.881784197001252e-16` |

세부 구성은 서울 9월 19일 10경주·109두, 서울 9월 20일 11경주·120두, 영천 9월 20일 6경주·65두다. 모든 말의 A 확률이 들어 있다.

### 4.2 B/C 파일

| 검증 항목 | 결과 |
|---|---:|
| 전체 행 | 540 |
| B | 27경주 × 10개 = 270행 |
| C | 27경주 × 10개 = 270행 |
| `(race_id, target)` 그룹 수 | 54 |
| 모든 그룹의 순위 1..10 완전성 | 통과 |
| `(race_id, target, prediction_rank)` 중복 | 0 |

현재 파일은 각 경주의 상위 10개만 보존한다. 전체 27경주의 완전한 분포를 행으로 저장한다면 B는 4,525개 세 말 집합, C는 27,150개 정확한 순서가 된다. 조합을 DB 원본으로 저장하지 않고 백엔드에서 재계산하면 이 파생 행을 반복 저장하지 않아도 된다.

### 4.3 설명 근거

현재 A 및 B/C 결과 파일에는 `feature`, `contribution`, `explanation`, `reason` 계열 컬럼이 없다. 즉 말별 설명 근거는 아직 저장되지 않았다.

다만 설명을 재현 가능하게 계산할 수 있다. A 모델의 110개 입력에 대해 LightGBM `pred_contrib=True`를 적용한 읽기 전용 검증 결과:

- 출력 shape: 294행 × 111열 — 110개 피처 기여도 + bias
- 각 행의 기여도 합과 모델 원시 점수의 최대 오차: `3.3306690738754696e-15`

따라서 모델을 다시 학습할 필요 없이, 같은 고정 artifact와 같은 입력 frame에서 원시 점수 기여도를 정확히 재생할 수 있다.

### 4.4 당일 정보와 기수 정보

A와 B/C의 채택 모델은 각각 110개 피처를 사용한다. 확인 결과:

- 당일 마체중, 마체중 증감, 날씨, 주로, 함수율: 채택 모델 피처에 없음
- 294행의 당일 마체중·주로·날씨 관련 값: 전부 null
- `jockey_no`: A/B/C 모델 피처에 포함, 294행 전부 존재
- `research_condition_jockey_changed`: A/B/C 모델 피처에 포함
- 기수 변경 여부: 276행에서 계산 가능, 그중 변경 157행
- 18행은 직전 출전 또는 현재 기수 비교 정보가 부족해 null
- 순서용 v2 우승 점수 모델은 `jockey_no`는 사용하지만 `research_condition_jockey_changed`는 사용하지 않음

부담중량 `burden_weight_kg`과 최근 부담중량 상대 변수는 사용하지만, 여기서 중량은 기수가 부담하는 부담중량이며 말의 당일 마체중과 다르다.

## 5. A·B·C의 표시 의미

### A — 말별 3위 이내 확률

`A_slot_inclusion_probability`는 해당 말이 세 개의 입상 자리에 포함될 모델 추정확률이다. 한 경주의 모든 말 A 확률 합은 3이다. 화면에는 모든 말에 대해 다음을 표시한다.

- A 확률
- 경주 내 A 순위
- A 1위 말과 A 2위 말의 확률 차이
- “확률은 모델 추정치이며 입상을 확정하지 않는다”는 안내

1·2위 차이는 저장된 모든 말의 A 확률로 결정적으로 계산할 수 있으므로 별도 원본 컬럼으로 중복 저장하지 않는다.

### B — 순서 없는 세 말 전체 입상 확률

B는 세 말이 순서와 관계없이 1~3위를 모두 차지할 하나의 집합 확률이다. 세 말의 A 확률을 곱하지 않는다.

### C — 정확한 1→2→3착 확률

C는 세 말이 지정한 순서대로 1·2·3착할 하나의 순서 확률이다. B를 다시 나누거나 다른 화면 확률과 곱하지 않는다.

백엔드는 B와 C의 전체 분포를 재계산하고, API 요청의 `top_k`에 따라 여러 조합을 반환한다. 기본값은 10, 허용 범위는 예를 들어 1~50으로 제한한다.

## 6. 현재 예측 원장과의 대응

현재 Supabase에는 다음 원장이 이미 있다.

- `prediction_runs`: 발행 실행, 기준시각, 모델·입력·예측 해시
- `model_predictions`: 출전마별 `prob_win`, `prob_top2`, `prob_top3`
- `prediction_settlements`: 결과 확정 후 실행 단위 평가
- `prediction_outcomes`: 말별 실제 착순과 hit 라벨

이 원장은 수정·삭제가 차단된 append-only 구조다. 최종 live 예측 원장으로 유지한다.

### 6.1 `model_predictions`에 저장할 값

더러브렛의 각 경주에서 A 계산은 `ja = top3_set_joint(A_raw_score, win_raw_score, T_A, T_win)` 공동분포를 이미 만든다. 따라서 다음처럼 저장한다.

| 기존 컬럼 | 더러브렛 저장값 |
|---|---|
| `race_id` | 내부 `races.id` |
| `race_entry_id` | 내부 `race_entries.id` |
| `horse_number` | 출전번호 `chul_no` |
| `prob_win` | **A 공동분포**에서 해당 말이 첫 위치인 순서 확률 합 |
| `prob_top2` | **같은 A 공동분포**에서 해당 말이 첫 두 위치에 있는 확률 합 |
| `prob_top3` | 현재 A 파일의 `A_slot_inclusion_probability` |

이렇게 하면 `P(win) ≤ P(top2) ≤ P(top3)`와 경주별 합 1·2·3을 만족한다. B 또는 C의 목표별 보정값을 A와 혼합하지 않는다. `prob_win`은 “A 공동분포의 우승 주변확률”로 명시하며 C의 최종 정확순서 확률과 같은 값이라고 표현하지 않는다.

모든 정상 출전마가 반드시 한 행씩 있어야 한다. 취소마는 final live 발행에서는 제외하고, 취소 사실과 이전 draft의 예측은 lineage에 남긴다.

## 7. 권장 스키마

이번 작업에서는 아래 스키마를 적용하지 않는다. 후속 migration의 설계안이다.

### 7.1 `prediction_runs` 보강

기존 컬럼을 유지하고 다음 정보를 추가한다.

| 컬럼 | 권장 타입 | 설명 |
|---|---|---|
| `prediction_stage` | text check | `initial_card`, `pre_race_update` |
| `parent_prediction_run_id` | bigint FK nullable | 초기 run 또는 직전 run |
| `source_card_at` | timestamptz nullable | 원 출마표 공개시각 |
| `history_cutoff_date` | date | 과거 이력 최대 허용일 |
| `input_card_sha256` | text | 정렬·정규화한 출마표 hash |
| `data_availability_status` | text | `complete`, `partial`, `not_available`, `timing_unverified` |
| `probability_contract` | text | `thoroughbred_abc_runner_v1` |
| `combination_algorithm_version` | text | 예: `top3_set_joint_v1` |

현재 `publication_mode`은 `live`/`historical`만 지원하고 같은 경주에 live를 한 번만 허용한다. 초기·직전 갱신을 모두 DB에 보관하려면 `draft` 계층이 필요하다. 권장 구현은 다음 중 하나다.

1. 별도 `draft_prediction_runs` 계층에 모든 stage를 append-only로 저장하고 최종 선택만 기존 원장에 live로 복사한다.
2. `prediction_runs`에 `draft`를 추가하고 payload hash의 전역 unique를 live용 partial unique로 변경한다.

운영 위험이 더 낮은 안은 1번이다. 기존 live 원장 규칙과 기존 326개 말별 예측을 바꾸지 않기 때문이다.

### 7.2 `prediction_run_models`

한 run에서 A, B, C, 순서용 우승 점수가 서로 다른 artifact·보정을 사용하므로 실행 단위 단일 `model_hash`만으로는 부족하다.

| 컬럼 | 설명 |
|---|---|
| `id` | bigint identity PK |
| `prediction_run_id` | FK, 인덱스 |
| `component` | `A`, `B`, `C`, `WIN_ORDER` |
| `model_version` | 예: `v5_2026H2_rolling_all` |
| `model_artifact_sha256` | 모델 파일 hash |
| `metadata_sha256` | category vocab·피처·학습정보 metadata hash |
| `candidate_name` | `current_A`, `current_B`, `current_C` |
| `temperature` | 이 경주/개최지에 실제 적용한 값 |
| `calibration_version` | 보정 계약 버전 |
| `algorithm_version` | 재계산 코드 버전 |

권장 unique는 `(prediction_run_id, component, venue_code)` 또는 경주별 온도가 달라질 수 있으면 `(prediction_run_id, component, race_id)`다.

### 7.3 `model_prediction_components`

기존 `model_predictions` 한 행과 1:1로 연결한다.

| 컬럼 | 설명 |
|---|---|
| `model_prediction_id` | PK/FK |
| `a_rank_in_race` | A 경주 내 순위 |
| `raw_a_top3_score` | v5 A 모델 원시 점수 |
| `raw_bc_top3_score` | v4 B/C 모델 원시 점수 |
| `raw_win_score` | v2 순서용 우승 점수 |
| `field_size` | 해당 run에서 본 전체 출전두수 |
| `jockey_no_snapshot` | 예측 당시 공식 기수 ID |
| `trainer_no_snapshot` | 예측 당시 조교사 ID |
| `owner_no_snapshot` | 예측 당시 마주 ID |
| `jockey_changed_from_last` | 기본 모델 입력, null 허용 |
| `body_weight_kg` | 직전 갱신 시 확보된 경우만 |
| `body_weight_change_kg` | 확보된 경우만 |
| `starter_status` | `declared`, `confirmed`, `scratched`, `unknown` |
| `data_quality_flags` | jsonb, 가변 품질 플래그만 저장 |

조합 재계산의 원본은 `raw_a_top3_score`, `raw_bc_top3_score`, `raw_win_score` 세 값과 `prediction_run_models`의 온도·알고리즘 버전이다.

### 7.4 `prediction_race_contexts`

경주 단위 직전 정보를 말별 행에 반복하지 않는다.

| 컬럼 | 설명 |
|---|---|
| `prediction_run_id`, `race_id` | 복합 unique, 두 FK 인덱스 |
| `weather` | 공개시각 확인 시만 |
| `track_condition` | 공개시각 확인 시만 |
| `track_moisture_percent` | 공개시각 확인 시만 |
| `observed_at` | timestamptz |
| `availability_status` | `available`, `not_available`, `timing_unverified` |
| `source_document_id` | 원문 lineage FK nullable |

당일 정보가 없으면 값을 추정하지 않고 null과 `not_available`을 저장한다. 결과를 보고 복원한 값은 `timing_unverified` 또는 historical 전용으로 분리한다.

### 7.5 `model_prediction_explanations`

한 말에서 표시할 긍정 3개와 부정 3개를 행으로 저장한다.

| 컬럼 | 설명 |
|---|---|
| `id` | bigint identity PK |
| `model_prediction_id` | FK, 인덱스 |
| `component` | 기본은 `A` |
| `feature_name` | 원래 110개 피처명 |
| `readable_feature_name` | 검토된 한국어 이름 |
| `feature_value_json` | 숫자·범주 값을 손실 없이 보존 |
| `field_percentile` | 수치형이며 경주 내 비교 가능할 때만 |
| `contribution_direction` | `positive`, `negative` |
| `contribution_value` | A 원시 점수 기여도 |
| `contribution_rank` | 방향별 1~3 |
| `explanation_type` | `interpretable`, `categorical_model_effect`, `data_quality_flag` |
| `explanation_method` | `lightgbm_pred_contrib` |
| `source_cutoff_at` | timestamptz |

권장 unique는 `(model_prediction_id, component, explanation_type, contribution_direction, contribution_rank)`다.

기수·조교사·마주 ID와 `hr_no` 같은 범주형 효과는 `categorical_model_effect`로 분리한다. “기수가 뛰어나서”, “조교사가 우수해서” 같은 인과 문구를 만들지 않는다.

### 7.6 결과 정산

기존 `prediction_settlements`와 `prediction_outcomes`를 계속 사용한다. A hit은 `finish_position <= 3`으로 계산한다. B/C는 DB에 조합 행이 없어도 해당 run의 원시 점수와 고정 알고리즘으로 경주 종료 후 동일한 top choice를 재생해 평가할 수 있다.

B/C 재생 결과의 평가 payload hash와 조합 알고리즘 버전을 settlement 메타데이터에 남긴다. 동착·취소·실격 규칙은 모델 연구 계약과 동일하게 고정한다.

## 8. 백엔드 B/C 계산 계약

한 경주의 모든 정상 출전마 행을 `horse_number`, `race_entry_id`의 안정된 순서로 읽는다.

### B

1. 각 말의 `raw_bc_top3_score`를 읽는다.
2. B용 temperature를 적용한다.
3. 가능한 모든 중복 없는 3두 집합의 에너지를 계산하고 전체 집합에서 정규화한다.
4. 확률 내림차순, canonical entry ID 순으로 안정 정렬한다.
5. 요청한 상위 K개만 반환한다.

### C

1. 각 말의 `raw_bc_top3_score`와 `raw_win_score`를 읽는다.
2. C용 top3 temperature와 WIN_ORDER temperature를 적용한다.
3. 가능한 모든 3두 집합 확률을 계산한다.
4. 각 집합 안 6개 순서를 우승 점수의 Plackett–Luce 조건부 확률로 계산한다.
5. 모든 정확순서를 전체 확률 내림차순으로 정렬해 상위 K개를 반환한다.

현재 최대 16두 기준 한 경주는 B 560개, C 3,360개다. 요청 시 계산 가능한 크기다. 응답 지연을 줄이려면 `(prediction_run_id, race_id, top_k, algorithm_version)` 키로 애플리케이션 캐시를 둘 수 있지만 캐시는 원본이 아니며 언제든 재생성 가능해야 한다.

백엔드는 저장된 상위 10개 파일을 원본으로 사용하지 않는다. 그 파일은 검증 fixture로 사용해 새 백엔드의 상위 10개가 현재 파일과 확률 오차 `1e-12` 이내로 일치하는지 검사한다.

## 9. 말별 설명 생성 규칙

우선 표시 가능한 설명 그룹은 다음과 같다.

- 편성 대비 보정 스피드
- 전체 및 조건별 ELO
- 최근 3·5회 상대 성적
- 정확거리 경험·입상률
- 휴양 및 출전 주기
- 부담중량과 최근 부담중량 범위
- 게이트 상대 위치와 거리별 게이트 지수
- 선행 성향·편성 내 선행 경쟁·후반 상승
- 최근 성적 추세
- 직전 상대 수준 대비 현재 편성

생성 순서:

1. A 모델의 고정 110개 피처 matrix를 만든다.
2. `pred_contrib=True`로 피처별 원시 점수 기여도를 계산한다.
3. bias 열은 화면 설명 후보에서 제외하되 재현 검증에는 보존한다.
4. 사람이 해석 가능한 allowlist에서 양수 상위 3개, 음수 절댓값 상위 3개를 선택한다.
5. 결측, unseen category, 낮은 이력 표본은 별도 `data_quality_flag`로 저장한다.
6. 기수·조교사·마주·말 ID 효과는 `categorical_model_effect`로만 분류한다.

문서와 API에는 다음 문구를 고정한다.

> 기여도는 고정 모델의 원시 A 점수에 각 입력값이 기여한 방향과 크기다. 경기 결과의 인과적 이유가 아니며, 최종 A 확률은 같은 경주 전체 출전마와 가능한 입상 조합을 함께 정규화한 결과다.

## 10. 초기 출마표와 직전 갱신

### 초기 출마표 run

- stage: `initial_card`
- 공식 출마표와 엄격 이전 이력만 사용
- 당일 마체중·날씨·주로는 null / `not_available`
- 모든 출전마 A 확률과 원시 점수를 저장

### 경주 직전 갱신 run

- stage: `pre_race_update`
- 공개시각이 확인된 변경만 반영
- 초기 run ID를 parent로 저장
- 초기 run을 UPDATE하거나 덮어쓰지 않음
- 취소마와 변경 기수의 snapshot을 보존

### final live

마감 시 선택된 stage payload만 기존 immutable live 원장으로 발행한다. 같은 경주에 live를 두 번 발행하지 않는다. 직전 자료가 없으면 초기 카드 run을 최종 원본으로 사용한다.

## 11. 단계별 변화 비교

동일 `race_id`, `race_entry_id` 또는 `hr_no`로 초기와 직전 run을 join한다.

| 비교값 | 계산 |
|---|---|
| A 확률 변화 | `update.prob_top3 - initial.prob_top3` |
| A 순위 변화 | `initial.a_rank - update.a_rank`; 양수면 순위 상승 |
| 기수 변경 | 두 run의 `jockey_no_snapshot` 비교 |
| 직전 경주 대비 기수 변경 | 각 run의 `jockey_changed_from_last` 비교 |
| 마체중 증감 | update의 공식 `body_weight_change_kg` 및 initial null 여부 |
| 주로·날씨 변경 | 두 `prediction_race_contexts` 비교 |
| 취소 변화 | initial declared → update scratched/excluded |

B/C 변화는 저장 행을 비교하지 않는다. 두 run 각각에서 백엔드가 같은 K와 같은 알고리즘 버전으로 재계산한 뒤 canonical key로 비교한다.

- 기존 top K에서 빠진 조합
- 새로 진입한 조합
- 동일 조합의 순위 변화
- 동일 조합의 확률 변화
- 최고 B/C 선택 변경 여부

비교 응답에는 두 run의 model hash와 algorithm version이 같았는지도 함께 표시한다. 모델이 바뀐 비교와 입력만 바뀐 비교를 구분해야 한다.

## 12. API 표시 계약

경주 카드에는 다음을 제공한다.

- 모든 말의 A 확률과 A 순위
- A 1위와 2위의 차이
- 각 말의 긍정 근거 3개와 부정 근거 3개
- 범주형 모델 효과와 품질 플래그의 별도 섹션
- B 상위 K개 입상 3두 조합
- C 상위 K개 정확순서
- stage, 기준시각, 출마표 시각, 역사 cutoff, 모델·보정·알고리즘 버전
- 당일 정보 availability 상태

응답 문구는 다음 의미를 섞지 않는다.

- A: 한 말이 Top3에 포함될 확률
- B: 표시한 세 말 전체가 Top3를 차지할 확률
- C: 표시한 세 말이 정확한 1→2→3 순서가 될 확률
- 높은 확률은 확정이나 매수 지시가 아님

## 13. 무결성·성능·보안 조건

### 무결성

- 한 run의 정상 출전마 전원에게 `model_predictions` 한 행이 있어야 한다.
- `(prediction_run_id, race_entry_id)` unique를 유지한다.
- A 공동분포의 runner marginal은 합 1·2·3과 단조성을 만족한다.
- A 파일의 `prob_top3`와 저장 후 값은 오차 `1e-12` 이내여야 한다.
- 백엔드 B/C top10은 현재 fixture와 key 및 확률이 일치해야 한다.
- 원시 점수, 모델 artifact, metadata, 입력 카드, 알고리즘에 SHA-256을 남긴다.

### Postgres

- 새 PK는 `bigint generated always as identity`를 사용한다.
- 새 시간 컬럼은 `timestamptz`를 사용한다.
- FK는 모두 별도 인덱스를 둔다.
- 조회 패턴에 맞춰 `(prediction_run_id, race_id)`와 `(model_prediction_id, component)` 복합 인덱스를 둔다.
- 한 run 저장은 run, 모델 metadata, 모든 runner, 설명을 한 transaction에서 batch insert한다.
- `public`에 둘 경우 RLS를 활성화한다. 현재처럼 백엔드 전용이면 `anon`과 `authenticated`에 직접 쓰기 권한을 주지 않는다.

### 저장량

한 경주일 기준 원본은 말 294행과 설명 최대 1,764행(말당 6개) 수준이다. 현재 1.79GB의 `horse_training`이나 741MB의 `odds_snapshots`보다 매우 작다. 조합 전체 31,675행을 반복 적재하지 않는 설계이므로 이번 예측 저장은 현재 디스크 경고의 주원인이 되지 않는다.

## 14. 구현 순서

1. v6 추론기에 A 공동분포의 `prob_win`, `prob_top2`, `prob_top3` 주변화 출력을 추가한다.
2. 세 원시 점수와 목표별 temperature를 canonical runner payload에 추가한다.
3. DB ID 매핑을 날짜·개최지·경주번호·출전번호·KRA 말 ID로 검증한다.
4. 모든 말 행과 run component metadata를 하나의 transaction으로 저장한다.
5. LightGBM 기여도를 계산하고 검토된 allowlist에서 ±3개를 저장한다.
6. 백엔드 B/C 계산기를 구현하고 현재 top10 fixture와 대조한다.
7. 초기/직전 stage 비교 API를 구현한다.
8. historical test run으로 저장·재생·정산을 검증한다.
9. 검증 통과 후에만 실제 live 발행을 연결한다.

## 15. 이번 점검에서 하지 않은 작업

- Supabase 디스크 증설 또는 결제
- Supabase 스키마 변경
- 운영 DB insert/update/delete
- 기존 모델 재학습 또는 변경
- 원천 데이터 변경 또는 삭제
- 기존 A/B/C 연구 산출물 재작성

