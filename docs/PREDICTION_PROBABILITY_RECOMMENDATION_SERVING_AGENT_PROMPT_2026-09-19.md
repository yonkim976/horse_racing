# 제주마·더러브렛 확률·후보 추천·웹 서빙 구현 프롬프트

## 목적

제주 `HY_R_FORM`과 더러브렛 모델의 출전마별 확률을 하나의 계약으로 반환·저장하고, 그 확률 분포에서 **축마·후보 풀·혼전**을 결정하는 추천 계층을 구현한다.

추천 계층은 모델을 다시 학습하는 기능이 아니다. 이미 계산된 확률과 Top3 조합 분포를 입력으로 받는 결정적 후처리다. 상위 1두를 자동 축으로 지정하거나 상위 5두를 자동 후보로 지정해서는 안 된다.

## 반드시 지킬 원칙

1. `P(우승)`과 `P(입상: Top3)`은 별도 값이다. `P(입상)`을 우승확률의 대용값으로 사용하거나, 한 값에서 다른 값을 임의로 변환하지 않는다.
2. 후보 풀의 품질은 개별 확률 합이 아니라 `P(실제 Top3 전체가 후보 풀에 포함)`으로 계산한다.
3. 두 축의 판단에는 두 말의 개별 입상확률이 아니라 `P(두 말이 모두 Top3)`을 사용한다.
4. 남은 입상마 후보는 `P(C가 Top3 | A와 B가 모두 Top3)` 같은 조건부 확률로 정한다.
5. 확률과 추천은 경주 전 정보 기준시각, 모델 버전, 데이터셋 버전, 추천 규칙 버전을 함께 저장한다.
6. 이미 `live`로 공개한 예측은 수정하거나 덮어쓰지 않는다. 마감 전 갱신은 draft로만 저장하며, 마감 시점에 한 번만 immutable live publication으로 발행한다.
7. 배당·기대수익·매수 지시는 이번 범위에 포함하지 않는다.

## 입력과 공통 확률 계약

두 모델 어댑터가 아래 계약을 반환하도록 만든다.

```json
{
  "schema_version": "race_prediction_v1",
  "model": {
    "model_type": "jeju_hy_r_form_v1",
    "artifact_sha256": "...",
    "dataset_version": "..."
  },
  "as_of": {
    "feature_cutoff_at_ms": 0,
    "generated_at_ms": 0,
    "policy": "start_minus_30m"
  },
  "race": {"race_id": 0, "race_entry_ids": [0]},
  "runners": [
    {
      "race_entry_id": 0,
      "horse_number": 1,
      "probabilities": {"win": 0.0, "top2": 0.0, "top3": 0.0},
      "ranks": {"win": 1, "top3": 1}
    }
  ],
  "top3_set_distribution": [
    {"entry_ids": [11, 12, 13], "probability": 0.0}
  ],
  "ordered_top3_distribution": [
    {"entry_ids": [11, 12, 13], "probability": 0.0}
  ]
}
```

### 확률 불변조건

경주마다 아래를 자동 검증한다.

- 모든 확률은 유한한 `0 ≤ p ≤ 1`이다.
- 출전마별 `P(win) ≤ P(top2) ≤ P(top3)`이다.
- 모든 출전마의 `P(win)` 합은 1, `P(top2)` 합은 2, `P(top3)` 합은 3이다. 출전두수 3두 미만은 명시적으로 예외 처리한다.
- `top3_set_distribution`은 중복 없는 오름차순 세 `race_entry_id`이며 확률 합은 1이다.
- `ordered_top3_distribution`은 중복 없는 순서 세 `race_entry_id`이며 확률 합은 1이다.
- runner marginal은 ordered distribution에서 재합산한 값과 일치한다. 우승은 첫 위치, Top2는 첫 두 위치, Top3는 세 위치 합이다.

현재 제주 저장 출력의 `top3_probability`만으로는 이 계약이 충분하지 않다. `HY_R_FORM`의 순서·집합 분포에서 `P(win)`, `P(top2)`, `P(top3)`을 함께 산출한다. 우승확률을 입상확률로 대체하지 않는다.

## 추천 결정 규칙

추천 결과는 모델 출력과 별도로 산출한다. 정책은 설정 파일 또는 DB에 버전으로 고정하고, 수치 임계값은 시간순 과거 검증으로 선택한다. 구현자가 임의의 “40% 이상이면 축” 같은 기준을 확정해서는 안 된다.

### 경주별 계산 수치

```text
p1_top3                = Top3 확률 1위 말의 P(Top3)
anchor_margin           = P(Top3 1위) - P(Top3 2위)
boundary_gap_3_4        = P(Top3 3위) - P(Top3 4위)
pair_joint(A, B)        = P(A와 B가 모두 Top3)
pool_coverage(S)        = P(실제 Top3 세 말 모두 후보 풀 S 안에 있음)
remaining(C | A)       = P(C가 Top3 | A가 Top3)
remaining(C | A, B)    = P(C가 Top3 | A와 B가 모두 Top3)
```

`pair_joint`, `pool_coverage`, 조건부 확률은 `top3_set_distribution`에서 직접 합산한다. 분모가 0 또는 매우 작으면 추천을 보류하고 `insufficient_joint_mass` 상태로 남긴다.

### 추천 유형

한 경주에는 아래 중 하나의 설명 가능한 추천 유형을 반환한다.

- `one_anchor_pool`: 1축이 정책의 신뢰·우위 조건을 통과했고, 그 축을 포함한 최소 후보 풀이 목표 포괄확률을 만족할 때.
- `two_anchor_pool`: 두 축의 동시 Top3 확률과 두 축의 우위가 정책 조건을 통과했을 때만. 단순히 개별 확률 상위 2두라는 이유로 사용하지 않는다.
- `mixed_pool`: 축 조건이 통과하지 않거나 Top3/Top4 경계가 좁을 때. 앵커를 빈 배열로 두고 후보 풀만 제시한다.
- `withhold`: 데이터 완전성, 확률 검증, 조합 분포가 부족할 때. 추천을 생성하지 않고 이유를 보여준다.

후보 풀 크기는 3, 4, 5, 6 등의 고정 목록을 평가하되, 정책에서 정한 목표 포괄확률을 만족하는 **가장 작은 풀**을 선택한다. 어느 크기도 목표를 만족하지 않으면 최대 후보 풀과 미달 상태를 명시한다. 상위 5두를 무조건 선택하지 않는다.

추천 반환 예:

```json
{
  "recommendation_type": "mixed_pool",
  "policy_version": "candidate_policy_v1",
  "anchors": [],
  "candidate_entry_ids": [11, 12, 13, 14],
  "candidate_pool_size": 4,
  "pool_top3_coverage_probability": 0.0,
  "boundary_gap_3_4": 0.0,
  "anchor_joint_probability": null,
  "status": "ready",
  "reason_codes": ["narrow_top3_top4_boundary"]
}
```

## DB 저장 구조

기존 `prediction_runs`와 `model_predictions`는 출전마별 marginal 확률의 불변 원장으로 계속 사용한다. 기존 공개 데이터를 수정하지 않는다.

### 기존 테이블

`model_predictions`에 `prob_win`, `prob_top2`, `prob_top3`을 저장한다.

### 추가 테이블

1. `prediction_top3_sets`
   - `id`, `prediction_run_id`, `race_id`
   - `entry_a_id`, `entry_b_id`, `entry_c_id` — 오름차순 canonical order
   - `probability`
   - `(prediction_run_id, race_id, entry_a_id, entry_b_id, entry_c_id)` unique

2. `prediction_ordered_top3`
   - `id`, `prediction_run_id`, `race_id`
   - `first_entry_id`, `second_entry_id`, `third_entry_id`, `probability`
   - `(prediction_run_id, race_id, first_entry_id, second_entry_id, third_entry_id)` unique

3. `prediction_recommendation_runs`
   - `id`, `public_id`, `prediction_run_id`, `policy_version`
   - `generated_at_ms`, `payload_sha256`, `status`
   - 입력 prediction run과 정책 버전을 immutable하게 연결

4. `race_recommendations`
   - `id`, `recommendation_run_id`, `race_id`, `recommendation_type`, `status`
   - `candidate_pool_size`, `pool_top3_coverage_probability`
   - `anchor_joint_probability`, `boundary_gap_3_4`, `reason_codes_json`
   - 경주당 추천 결과 1건 unique

5. `race_recommendation_items`
   - `race_recommendation_id`, `race_entry_id`, `role` (`anchor`/`candidate`)
   - `display_rank`, `prob_win`, `prob_top3`, `conditional_remaining_probability`

마감 전 갱신은 별도 `draft_prediction_runs` 계층 또는 파일 기반 preview를 사용한다. `live` prediction run은 현재 계약대로 경주별 단 한 번만 발행한다.

## 근거(설명) 데이터

근거 문구를 LLM 또는 템플릿으로 임의 생성하지 않는다. 모델이 산출한 feature contribution을 구조화해 저장한다.

`model_prediction_explanations` 또는 동등한 테이블에 다음을 저장한다.

- `model_prediction_id`
- `feature_name`, `feature_label`
- `raw_value`, `contribution`, `direction`
- `explanation_method` — tree contribution / SHAP / linear coefficient 등
- `source_cutoff_at_ms`
- `rank_within_direction`

설명 화면에는 “모델 점수에 기여한 관측 변수”로 표시한다. 기여도를 인과관계나 경기 결과의 확정 이유로 표현하지 않는다.

## 웹/API 반환

`/forecast`는 제주와 더러브렛을 같은 JSON 계약으로 읽는다. 경마장과 모델 유형은 필터일 뿐, 화면 데이터 구조는 공통이다.

경주 카드에는 아래를 표시한다.

- 추천 유형: 1축, 2축, 혼전, 보류
- 앵커와 후보 풀
- `P(win)`과 `P(top3)`를 서로 다른 열로 표시
- 후보 풀의 Top3 포괄확률
- 두 축인 경우 동시 입상확률
- 혼전 판단의 경계 차이
- 발행시각, feature cutoff, 모델·정책 버전
- 모델 기여도 상·하위 항목과 데이터 출처 시점

정확한 1·2·3위는 별도 “순서 조합” 섹션에 표시한다. 입상 후보 풀과 같은 의미로 표시하지 않는다.

## 검증·테스트 완료 조건

1. 제주와 더러브렛의 최소 한 경주씩을 동일 JSON 스키마로 직렬화한다.
2. 모든 확률 불변조건을 자동 테스트한다.
3. Top3 set 및 ordered distribution의 합이 1인지 검증한다.
4. 같은 prediction run과 policy version은 같은 추천 결과 hash를 만든다.
5. 추천 결과가 확률 분포만으로 재현되고, 결과·배당·미래 정보에 접근하지 않음을 검증한다.
6. live 예측 덮어쓰기 시도는 거부되고, draft 갱신과 live 발행이 분리됨을 테스트한다.
7. 웹 화면이 `mixed_pool`에서 축을 표시하지 않고, `two_anchor_pool`에서 joint probability를 표시함을 테스트한다.
8. 테스트 결과와 스키마, 마이그레이션, 입력·출력 manifest를 문서화한다.

## 현재 테스트 HTML에 대한 정정

`data/predictions/jeju_live_20260919_hy_r_form_20260918/forecast_candidate_test.html`은 화면 시안이다. 현재는 상위 1두와 상위 5두를 단순 표시하므로 운영 추천으로 승격하지 않는다. 위 추천 계층과 joint probability 저장이 완성된 뒤 이 화면을 그 결과만 읽도록 교체한다.
