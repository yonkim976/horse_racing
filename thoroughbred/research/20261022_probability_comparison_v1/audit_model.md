# 운영 모델과 연구 기준 모델 감사

2026-10-22. 서울·부산 더러브렛. 기존 학습·추론·DB 접근 없이 등록부, 코드, 동결 산출물만 읽어 확인했다. 운영 모델, 10/08의 선택 연구 기준, 10/09~12의 full103 기준, 10/21 부산 전개 연구의 기준은 서로 다른 역할이다.

## 현재 운영 기준

[`config/prediction_model_registry.json`](../../../config/prediction_model_registry.json)의 해시는 `944e4aad25c99d9d346dab23c7f7596c216d8722a548dea2c7c07abf9b10b70b`이다. Thoroughbred의 active profile은 `thoroughbred-main-20260919-v1`, champion은 `thoroughbred-abc-current-a-b-c-20260919`이며 승격일은 2026-09-19다. 등록부는 명시적으로 승격되고 해시가 확인된 모델만 게시에 쓰도록 정한다. 현행 후보는 A=`current_A`, B=`current_B`, C=`current_C`다.

| 등록 구성 | 실제 모델 의미 | 등록 가중치 경로 (정확한 바이트) | 메타데이터 경로 (정확한 바이트) |
| --- | --- | --- | --- |
| A, `v5_2026H2_rolling_all` | 단일 말의 Top3 포함 확률을 만드는 `top3_set_energy`; 97 숫자+13 범주 입력. 학습 396,366행/35,462경주, 2006-01-06~2025-12-28. | `data/research/thoroughbred_offline_20260918_v5/windows/models/2026H2/rolling_all/top3.txt` — 1,682,348 B | 같은 폴더 `metadata.json` — 519,619 B |
| B, `v4_2026_top3_growth_strength` | 세 말이 모두 Top3인 **순서 없는 조합** 확률을 구성하는 `top3_set_energy`; 97 숫자+13 범주 입력. 학습 386,999행/34,589경주, 2006-01-06~2025-06-29. | `data/research/thoroughbred_followup_20260918_v4/model/models/2026/top3_growth_strength/top3.txt` — 1,649,286 B | 같은 폴더 `metadata.json` — 505,847 B |
| C의 순서 성분, `v2_2026_H3_relative` | 정확한 **1→2→3착 순서** 확률의 순서 모델. 59 숫자+13 범주 입력; 우승 동착은 정답 질량을 균등 분할한다. 학습 386,999행/34,589경주, 2006-01-06~2025-06-29. | `data/research/thoroughbred_win_research_20260918_v2/models/2026/H3_relative/model.txt` — 6,841,216 B | 같은 폴더 `metadata.json` — 504,851 B |

현재 서빙 계약은 A=`p_top3` runner marginal, B=`unordered_top3_set`, C=`ordered_1_2_3`다. 모델별·지역별 온도 보정값을 적용하고 경주 내 확률합 검사를 한다. 순서 모델의 정답 모집단은 원출마카드 전체이며 스크래치와 DQ/DNF는 0, 경주 가중치 합은 1이다. 코드 근거는 [`thoroughbred/cli.py`](../../cli.py)의 `predict_frame` 및 같은 해시로 보존된 [`production_models/20261004/thoroughbred/reference/infer.py`](../../../production_models/20261004/thoroughbred/reference/infer.py)다. registry/챔피언 해시와 위 세 모델 파일은 로컬 바이트·SHA 확인값이 등록부와 일치했다.

따라서 **운영 모델은 full103이나 122가 아니다.** production profile은 승격 상태로 계속 등록돼 있고, 여기서 후보 실험을 production으로 바꾼 증거는 없다.

## 연구에서 유지 중인 기준

연구 기준은 하나의 전역 모델이 아니다. 목적별로 구분한다.

| 기준 | 현재 상태와 근거 | 재사용 경로 및 크기 |
| --- | --- | --- |
| 22 입력 `month_gate_weight22` | 10/08에 사용자가 `research_ablation_baseline`으로 지정했다. 22개 입력의 연구 절제 기준이며 운영 등록이 아니다. 10/12 full103 보고서도 “선택22 유지”와 “103 baseline 유지”를 따로 기록한다. 평가 계약은 서울·부산, 2017년부터 학습·2010~2016 warm-up, 2024~2026-09-20 평가다. | [`research_baseline_selection.json`](../20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json) — 3,671 B; [`features_month_gate_weight22.parquet`](../20261008_profile_carried_weight_v1/outputs/features_month_gate_weight22.parquet) — 11,035,929 B; 선택 6개 model bundle은 `outputs/models/{1,3}_{2024,2025,2026}_month_gate_weight22/` — 총 4,387,194 B (그중 `top3.txt` 가중치 2,037,687 B). |
| full103 | 10/09에 만든 서울·부산 연구 후보. 10/12의 103→122 비교에서 동결 `baseline103`이 주 기준으로 남았다. 122 주 후보와 126 민감도 대조 모두 full103을 일관되게 능가하지 못해 122로 바꿀 근거가 없다는 결론이다. full103 자체도 운영 승격은 아니다. | 178,497행 입력 [`20261009_gate_front_late_v1/outputs/features.parquet`](../20261009_gate_front_late_v1/outputs/features.parquet) — 52,498,099 B; 동결 per-runner 결과 [`runner_predictions.parquet`](../20261009_gate_front_late_v1/outputs/runner_predictions.parquet) — 4,385,044 B; `full103_{meet}_{year}` 6개 모델은 2,215,263 B, 그 6개 metadata는 49,536 B. |
| combined122 | 10/12 challenger. 서울·부산의 같은 4,799경주/50,754 출전(2024 1,761, 2025 1,750, 2026-09-20까지 1,288)에 평가했다. 축 Top3는 60.47→60.83%, 복승1조합 12.40→12.15%, 축+차순위 3조합 28.07→27.96%, Top3 Brier 0.174657→0.174808. 세 주요 적중 차이 구간은 0을 포함하고 확률오차도 개선하지 않아 미채택이다. | [`20261012_full103_retention_v1/outputs/features.parquet`](../20261012_full103_retention_v1/outputs/features.parquet) — 62,317,864 B; `runner_predictions.parquet` — 4,404,105 B; challenger `models/` — 12,436,132 B; `sensitivity_models/` — 4,151,307 B. |

### full103의 확률과 정책

full103은 말별 `outcome <= 3` 이진 라벨로 학습한 원시 LightGBM 점수다. 점수 자체는 확률이 아니다. 경주 내 모든 순서 없는 3두 집합에 세 말 점수 합을 쓰고, 시험연도 Y−1에서 맞춘 온도로 나눈 뒤 softmax해 (q(S))를 만든다. 말별 `prob_top3`는 그 분포에서 해당 말을 포함하는 집합 확률을 합한 marginal이다. 103 입력은 [`feature_contract.json`](../20261009_gate_front_late_v1/outputs/feature_contract.json)의 `full103`; 면허 없는 현재 구간·착순은 입력하지 않는다. 초기 학습은 2017~Y−3, Y−2 조기종료·재학습, Y−1 조합 온도 보정, Y 평가다.

동결 결과는 축 순위와 unrestricted unordered trio 확률을 모두 담지만, 선택 규칙을 섞지 않아야 한다. 기존 “축+2·3·4위”의 복승 3조합은 축을 고정하는 정책이다. `q(S)` 상위 6개 임의 삼복 조합은 다른 티켓 정책이다. 둘의 성적 차이는 모델 점수 변화와 선택 정책 변화를 분리해 평가해야 한다.

### 최근 부산 기준은 별도 목적

10/21의 부산 57G/57J/57K 연구는 full103/122나 production ABC를 평가한 것이 아니다.

| 연구 기준 | 입력·목표·표본 | 보존물 |
| --- | --- | --- |
| 57G `B3` | 부산 101개 입력. 목표는 `(같은 경주의 정상완주마 완주시간 중앙값 − 본인 완주시간) × 1000 / 거리`로, 우승/Top3 확률이 아닌 연속 상대 수행값이다. 이력은 부산 2010-01-08~2026-09-18 자료, 2017+ 학습, 2024~2026-09-18 평가 1,976경주/21,452 정상완주 출전(경주당 정상완주 6두 이상). | [`features.parquet`](../20261021_busan_all_distance_profiles/outputs/features.parquet) — 22,733,300 B; `profiles.parquet` — 14,664,940 B; 세 개 B3 평가연도 모델 가중치 합 668,748 B. |
| 57J `B3` → D/I/J | B3를 동일 성적 목표의 연구 baseline으로 재사용. D는 직접 313입력, I/J는 17개 전개 예측을 더한 330입력이다. 전개 보조 목표는 S1F 첫 통과 묶음 소속·두수이며 이 보조 확률을 최종착순 확률로 읽으면 안 된다. 1,976경주/21,452 정상완주 출전, 부산만 학습. | 입력 출처 [`20261008_field_pace_prediction/outputs/feature_context.parquet`](../20261008_field_pace_prediction/outputs/feature_context.parquet) — 58,823,119 B 및 `feature_frame.parquet` — 45,084,556 B; 최종 점수 [`finish_predictions.parquet`](../20261021_busan_joint_pace_stack/outputs/finish_predictions.parquet) — 1,162,307 B. `score_B/D/I/J`는 연속 성적 점수고, 축 선택은 경주 내 높은 점수 순이다. |
| 57K `J` / PB·PF | 성적 비교의 입력 330(J), 340(H), 348(S); 추가 쌍 입력 44(PB), 56(PF). 성적 목표는 57J와 같은 연속 수행값. 쌍 모델은 “두 말 모두 Top3”와 “두 말이 1·2착” 이진 사건 확률을 각각 낸다. 이 쌍별 숫자는 전체 경주 착순의 정규화된 공동분포나 말별 Top3 확률이 아니다. 47개 신규 모델, 107,378개 평가 쌍, 같은 부산 1,976경주다. | [`pair_predictions.parquet`](../20261021_busan_late_survival_pairs/outputs/pair_predictions.parquet) — 4,707,730 B; 모델 폴더 14,606,245 B. README의 현재 판단은 H/S를 작은 변화의 연구 후보로 보존, PB/PF 관계 추가는 개선 근거 부족, production 변경 없음이다. |

따라서 최근 부산 연구의 재사용 기준은 그 표적의 연속 수행 순위 또는 특정 쌍 사건이다. 이것을 A/B/C의 runner·unordered trio·ordered triple 확률과 직접 비교할 수 없다.

## 같은 표적에서 운영과 비교할 수 있는 범위

full103은 A의 Top3 marginal과 B의 순서 없는 Top3 집합에 대응하는 확률을 만들 수 있다. raw 점수와 시험연도 temperature가 보존돼 있으므로 연구 score를 다시 학습하지 않고 집합분포를 재구성할 수 있다. 다만 저장된 보고서의 10/12 평가는 현 운영 A/B/C를 같은 4,799경주에서 채점하지 않았다. full103의 50,754 평가 출전은 문서상 출전행이며, 운영 순서 모델은 원출마카드 전체(스크래치 포함)를 기준으로 한다. 완전한 출전표 슬롯, DQ/DNF·동착 라벨을 같은 모집단과 정산 계약으로 맞춘 비교라는 증거는 저장물에 없다.

full103 산출물에는 정확한 1→2→3착 전체 순서분포가 없다. `q(trio)`만으로 순서확률이 식별되지 않는다. production C와 비교하려면 별도 순서 조건부 모델/온도 또는 다른 명시적 공동분포 계약을 연구 설계에 추가하고, 순서 계층의 입력·라벨·시간 분할을 고정해야 한다. production C를 full103의 누락된 계층에 그대로 끼워 넣으면 순수한 full103 대 운영 비교가 아니라 혼합 모델이 된다.

## 저장 결과 확인 및 재현 경로

이미 보관된 요약은 다음 파일에서 읽을 수 있다: 103/122 [`outputs/metrics.csv`](../20261012_full103_retention_v1/outputs/metrics.csv), [`race_metrics.csv`](../20261012_full103_retention_v1/outputs/race_metrics.csv), 57J [`outputs/finish_metrics.csv`](../20261021_busan_joint_pace_stack/outputs/finish_metrics.csv), 57K [`outputs/selection_metrics.csv`](../20261021_busan_late_survival_pairs/outputs/selection_metrics.csv)와 [`pair_probability_metrics.csv`](../20261021_busan_late_survival_pairs/outputs/pair_probability_metrics.csv).

모델 재생 검증의 코드 진입점은 아래와 같다. 이 명령은 모델을 로드해 점수를 다시 계산하고 검증 JSON을 쓴다. 이번 감사에서는 실행하지 않았다. 학습 진입점(`20261012_full103_retention_v1/run.py train`, `20261021_busan_joint_pace_stack/experiment.py`, `20261021_busan_late_survival_pairs/train.py`)도 실행하지 않았다.

```bash
# 10/09 full103 모델·저장 점수 재생
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261009_gate_front_late_v1/run.py verify

# 10/12 103/122 고정 비교 산출물 재생
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261012_full103_retention_v1/verify.py

# 10/21 부산 공동 전개 스택
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261021_busan_joint_pace_stack/verify.py

# 10/21 부산 종반 생존·쌍 모델
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261021_busan_late_survival_pairs/verify.py
```

이 감사에서 실행한 작업은 파일·문서·등록부·메타데이터 읽기와 바이트/SHA 측정뿐이다. 기존 파일은 수정하지 않았고, 학습·모델 로드·추론·DB·운영 변경도 없었다.
