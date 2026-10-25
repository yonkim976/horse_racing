# 입력 계약과 해시 잠금 초안

상태: root 승인 대기. 아래 해시·키·열·구간은 사전 계획에서 고정할 후보 입력이다. 승인 전에는 입력의 outcome 값으로 새 지표를 계산하거나 모델을 fit하지 않는다. root가 이 계약을 승인한 뒤에도 먼저 구조 preflight만 실행한다. fit은 별도 root 승인 뒤에만 허용한다.

## 고정 원천과 SHA-256

| 역할 | 경로 | SHA-256 |
|---|---|---|
| 저장 F1_STYLE6 평가 cohort, 라벨, roster, 6개 style 입력 | `jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet` | `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f` |
| 평가 2024 fold의 2023 calibration-year 원시 OOS 점수 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/calibration_scores.parquet` | `360cc559b1ab19cde177e0bb23206fd36f123b707714fbcb63547fdb9bed05b2` |
| 평가 2025 fold의 2024 calibration-year 원시 OOS 점수 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/calibration_scores.parquet` | `b092d28f0cbd45dd3a184a4a8ab89e9b5b5a78eef8068c45fda3de92734a3755` |
| 평가 2026 fold의 2025 calibration-year 원시 OOS 점수 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/calibration_scores.parquet` | `6a7ed320e59add698faafd9008c882dc8a83a84f9198094371525f4c4ebd37d8` |
| 평가 2024 fold의 evaluation-year 원시 OOS 점수 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/evaluation_scores.parquet` | `b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60` |
| 평가 2025 fold의 evaluation-year 원시 OOS 점수 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/evaluation_scores.parquet` | `45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12` |
| 평가 2026 fold의 evaluation-year 원시 OOS 점수 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/evaluation_scores.parquet` | `0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a` |
| 평가 fold별 저장 base model 입력·refit 경계·tau 메타정보 (Y=2024) | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/meta.json` | `15acbf959654da82d2240027e7b7d768bb9226af18395dac9ec92a68a4471726` |
| 평가 fold별 저장 base model 입력·refit 경계·tau 메타정보 (Y=2025) | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/meta.json` | `23c4b0684477f34fbb2e99c22d0037cd903d5459db369f084773ec25c640f4a8` |
| 평가 fold별 저장 base model 입력·refit 경계·tau 메타정보 (Y=2026) | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/meta.json` | `e9dbfe5226571cb29e34b352a4ad8808a735d70929e66b42efb41b3e807ff06d` |
| 기존 horse marginal: 저장 원 F1_STYLE6 확률 및 기존 joint q 말 marginal | `jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv` | `0e6a01607164a7cb54fbbb5fb445e975ea9fbadad21d4e7a842adfc915616a09` |
| 기존 joint baseline/candidate의 full unordered Top3 q | `jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet` | `13409e65353c0cb6dab14df97317cce24de913056ae464ee3524520759de681c` |
| 기존 pair 선택 재현값 (`top_two_marginal_pair`, `maximum_joint_pair`) | `jeju/research/20261010_pair_axis_v1/outputs/per_race_metrics.csv` | `78b75895ddd82a72a406aa2b9d4fa889946d25e6a8d8c8f50069aac286b267c1` |
| 저장 STYLE6 study source/lineage manifest | `jeju/research/20261010_style_history_ablation_v1/ARTIFACT_MANIFEST.json` | `6afc0e8f73ec086052fad4cde4d7edcd62fdf1bbc782108da89732dc3a5b4a4e` |
| 기존 joint study source/lineage manifest | `jeju/research/20261010_joint_relationship_v1/ARTIFACT_MANIFEST.json` | `d0d1a749afb6a6f894de1bb4263c9d67dd1e3b2d1a35bf1b5fd38d8948c656b0` |
| 기존 pair-axis 정책 및 tie rules | `jeju/research/20261010_pair_axis_v1/PLAN.md` | `fcecdd848f3e4e46cc9c41d9cb4f86b1cf6ae02a0e4ceef196b422b40e102d4a` |
| 기존 pair-axis 결과 manifest | `jeju/research/20261010_pair_axis_v1/outputs/ARTIFACT_MANIFEST.json` | `0f82c19c8d3dd318e984d860bff098738e27429c7006f7acdd9312d75f01a0ad` |
| STYLE6 입력·라벨·시간 기준 계약 | `jeju/research/20261010_style_history_ablation_v1/CONTRACT.md` | `c10aac8f6faa6e841afd9ef829bfa0b29ada2dceabcbb5405fdfad9c12536bf9` |

위 해시는 설계 단계에서 읽기 전용으로 계산했다. preflight는 승인 후 각 파일을 값으로 읽기 전에 SHA-256을 다시 계산하고 전부 일치해야만 진행한다. 한 파일이라도 달라졌다면 대체하거나 수정하지 않고 중단한다.

## 열 사용과 금지 입력

`features.parquet`에서 model/evaluation table에 쓰는 열은 `api_record_id`, `race_id`, `race_date`, `year`, `horse_id`, `horse_number`, `field_n`, `finish_position`, 그리고 PLAN에 적힌 여섯 style 열뿐이다. `horse_id`·`race_id`·마번은 join, group, 표시·동점 처리에만 쓰고 모델 입력 basis에서 제외한다. `finish_position`은 pair 라벨 및 무결성 검사에만 쓴다. 단, preflight 시 기존 STYLE6 feature-lineage의 `history_cutoff` 및 `latest_history_date` 시점 metadata는 history leakage/T−2 확인에만 읽을 수 있다. 이를 모델 입력·평가에는 쓰지 않는다. 다른 F1 입력, 저장 예측 label/loss, source DB, 운영 등록부, 현 모델, 새 외부 자료, 더러브렛 자료는 금지한다.

각 score parquet은 `api_record_id:int64, score:double` 두 열이어야 한다. key는 유일해야 하며 해당 fold의 score key와 `features.parquet`에서 calendar year가 맞는 roster key가 일대일이어야 한다. evaluation score와 calibration score를 섞지 않는다. 특히 2024 evaluation IDs는 `F1_STYLE6_2024/evaluation_scores`와 `F1_STYLE6_2025/calibration_scores` 양쪽에 나오지만, 두 파일은 서로 다른 saved refit model의 score를 담으므로 `api_record_id`만으로 fold를 합치거나 deduplicate하지 않는다. 각 evaluation fold는 자기 폴더의 calibration/evaluation score pair만 사용한다. 저장된 `tau`는 H1 학습·입력 scaling에 사용하지 않는다. H1/H2/OOS 경주 roster와 라벨은 score 파일의 키로 선택한다.

`runner_marginals.csv`에서는 join key와 `saved_f1_style6_p_top3`, `candidate_joint_marginal`만 입력 정책에 사용한다. 이 source의 `y_top3`, `saved_y_top3` 및 어떠한 결과열도 pair를 고르는 데 사용하지 않는다. 원래 말 확률은 저장 `F1_STYLE6` 모델의 Top3 확률이며, candidate joint marginal은 저장 joint `q`에서 유도한 기존 방식이다. preflight는 evaluation cohort에서 저장 확률 상위2와 raw-score 상위2를 비교한다. rank-2와 rank-3 raw score가 다르면 두 pair는 반드시 같아야 한다. raw rank-2 boundary가 exact tie면 저장 확률 상위2 pair는 별도 comparator로 유지하고, 선택 pair의 모든 말이 rank-2 threshold 이상이며 rank-1보다 높은 말이 있으면 그 말을 포함함을 assert한다. source-only로 확인한 경계 tie 예외 6건은 `AMENDMENT.md`에 기록한다. 이 검사는 라벨을 읽지 않는다.

`all_triples.parquet`에서는 `race_id`, `race_date`, `evaluation_year`, `distance_m`, `arm`, `triple_numbers`, `probability`만 사용한다. `arm`은 `candidate` 또는 `matched_baseline`이다. `distance_m`은 연도·거리 보고에만 사용한다. `is_true_set` 및 outcome-related 열은 loader에서 제외한다. 모든 pair별 joint 기준확률은 pair를 포함한 unordered triple의 저장 `probability`를 canonical source order로 합산한다.

`per_race_metrics.csv`에서 comparator parity에 쓰는 열은 `race_id`, `race_date`, `evaluation_year`, `arm`, `policy`, `budget_k`, `axis_horses`, `axis_probability`뿐이다. `ticket_hit`, `axis_hit`, `exact_top2_pair_hit`, `failure_component`와 기타 label/성과 열은 읽지 않는다. 선택 pair 재구성 검증에만 사용하고 신규 성능지표 source로 사용하지 않는다.

## 코호트, 키와 pair 라벨 계약

고정 evaluation cohort는 2024-01-05~2026-09-19, 1,779경주·17,412출전·269경주일이다. `features.parquet` 전체는 style-history study의 52,155 출전·5,206경주 cohort다. 평가 경주는 2024, 2025, 2026년에 따라 각각 해당 저장 fold의 `evaluation_scores.parquet`를 쓴다. 저장 fold meta의 `evaluation_min/max`, 원시 score 행 수, score key·race key가 기존 저장 코호트와 맞아야 한다. 2026년은 부분연도로 표시한다.

race key는 `race_id`, runner key는 `(race_id, horse_number)`이며 `api_record_id`로 score/features/marginal sources를 연결한다. 키마다 한 행만 허용한다. 한 경주 roster는 전부 같은 H1/H2/evaluation 구간에 포함돼야 하고 완전 편성에서 `field_n`과 고유 horse number 수가 같아야 한다. 모든 H1/H2/evaluation 경주는 `field_n >= 4`여야 한다. 각 경주에는 고유한 finish position 1, 2, 3이 각각 있어야 하며 `finish_position <= 3`인 말은 정확히 3두여야 한다. 그 세 말로 이루어진 positive unordered pair는 경주마다 정확히 3개다. pair 생성에서 `N_r < 4`이면 즉시 전체 preflight를 실패시킨다. 이 조건은 라벨/roster 감사이며 pair hit 평가가 아니다.

Pair는 오름차순 마번 `(min(h_i,h_j), max(h_i,h_j))`으로 canonicalize한다. pair 순서가 입력에 영향을 주지 않는지 synthetic swap assertion을 둔다. 완전 roster에서 `C(N_r,2)` pair를 만들며 `N_r<4` 또는 duplicate number/horse, 누락·비유한 score, 불완전 labels가 있으면 race를 조용히 제외하지 않고 전체 preflight를 실패시킨다.

## 고정 시간 경계와 fold

| 평가연도 | OOS score folder | calibration/H1·H2 calendar year | 저장 refit 최대일 |
|---:|---|---:|---|
| 2024 | `F1_STYLE6_2024` | 2023 | 2022-12-24 |
| 2025 | `F1_STYLE6_2025` | 2024 | 2023-12-30 |
| 2026 | `F1_STYLE6_2026` | 2025 | 2024-12-28 |

H1 날짜는 직전 연도 1월 1일~6월 30일, H2는 7월 1일~12월 31일이다. 경주일 전체를 단위로 유지하며 H1 마지막 허용일은 H2 첫 실제 경주일에서 최소 2일 앞선다. saved refit은 H1 첫 실제 경주일에서 최소 2일 앞서야 한다. H2 마지막 라벨 경주일은 evaluation 첫 실제 경주일에서 최소 2일 앞서야 한다. split별 실제 최소·최대 경주일, race/date/runner/pair 수, purge된 날짜 목록을 lock에 저장한다. 구간 경계나 purge로 점수 roster가 달라지는 경우 source 대체나 사후 경계 조정 없이 중단한다.

선행 C preflight에 확인된 T−2 purge 후 H1/H2 예상 경주 수는 평가 2024의 312/336, 2025의 326/311, 2026의 329/325다. 새 preflight에서 실제 날짜·경주 key를 다시 계산해 세 값과 일치하지 않으면 중단한다.

## 고정 모델·보정·평가 계산

말 표준화 통계, pair basis 표준화 통계, model fit은 H1에서만 한다. H1 race weight는 각 race의 각 pair에 `1 / C(N_r,2)`다. 고정 ridge는 `lambda=1.0`, 절편 없음, 시작 계수 0, optimizer는 PLAN의 한 번짜리 L-BFGS-B다. 기본 offset `logit(p0_r,ij)`는 저장 raw score를 temperature 1로 exact unordered Top3 distribution `q0(T) proportional exp(fsum(score_h))`에 넣은 뒤 pair를 포함하는 triple 확률을 모두 더해 구한다. triple은 numeric horse number 기준 canonical order로 열거한다. 각 triple energy `fsum(score_h)`, max-shift exponential을 쓴 softmax normalizer, pair marginal 합은 Python `math.fsum`으로 canonical 순서의 항을 합산한다. H1 학습에는 저장 full-year `tau`를 쓰지 않는다. 모든 source-compatible race에서 `p0`는 finite하고 `0 < p0 < 1`이어야 한다. `beta=0`에서 모든 `p0`와 선택을 재현해야 하며 evaluation 전체에서 p0 maximum pair가 raw-score 상위2와 일치하는지 preflight로 assert한다. 점수 동점은 exact float equality만 사용하고 pair 동점은 오름차순 numeric horse-number pair로 푼다.

H2에는 같은 labels·race-equal pair BCE·SciPy L-BFGS-B·bounds `A in [-20,20]`, `B in [0.05,20]`, 초기값 `(A,B)=(0,1)`, `maxiter=500`, `ftol=1e-12`, `gtol=1e-8`로 두 positive-slope Platt map을 별도 fit한다. 두 fit은 PLAN의 동일 analytic gradient와 race-equal objective를 쓴다. 하나는 candidate H1 raw logits `eta=logit(p0)+beta'v`, 하나는 `logit(p0)` baseline 입력이다. 두 fit 모두 재시도·대체 calibrator 없이 한 번만 실행한다. `beta=0`에서는 두 logit 행렬이 같아서 deterministic fits·보정 확률이 같아야 한다. H1/H2 optimizer 결과는 `success=True`, finite parameters/objective/gradient, bound 준수와 projected-gradient infinity norm `<=1e-6`을 만족해야 한다. H1에는 bounds가 없으므로 analytic gradient `g=mean_r(mean_pairs((p-y)*v))+beta`의 infinity norm을 검사한다. H2 objective는 `L(A,B)=mean_r(mean_pairs BCE(y,sigmoid(A+B*u)))`이고 analytic gradient은 `g_A=mean_r(mean_pairs(p-y))`, `g_B=mean_r(mean_pairs((p-y)*u))`다. H2에서는 bound 안쪽은 gradient를, lower bound에서는 `g>=0`, upper bound에서는 `g<=0`일 때 해당 좌표의 projected gradient를 0으로 처리하고 반대 부호는 유지한다. 경계 도달과 projected-gradient 결과를 기록한다. 기준을 충족하지 못하면 평가 전에 중단한다. H2는 보정 산출만을 위한 것이며 평가 gate·features·threshold 선택에는 쓰지 않는다.

평가에서 선택 pair는 race별 candidate H1 raw logit `eta` 최댓값, 완전 float 동점은 오름차순 numeric pair다. positive-slope H2 map은 pair 순위를 보존하므로 calibrated-probability ranking과 같음을 assert한다. 기본 outcome은 선택 pair의 두 말이 실제 Top3에 모두 든 사건이다. 주 pair-hit gate comparator는 저장 raw-score 상위2 pair 하나다. All-pair 및 selected-pair Brier/log-loss는 레이스 내부 pair 평균 후 레이스 평균으로 계산한다. All-pair reliability bin의 pair weight는 race별 `1/M_r`이며 bin 안에서 그 weight로 예측·관측 conditional mean을 낸다. Selected-pair reliability bin은 race당 하나의 선택 pair에 weight 1을 준다. 빈 bin은 undefined로 표기한다. `p_cal >= .20` subset은 예측값으로 고정한 mask다. paired date bootstrap은 전체 269 경주일을 복원추출해 이 고정 mask를 재사용한다. 재표집에서 subset 분모가 0이면 undefined 반복으로 세고 유효·undefined 수를 보고한다. 모든 evaluation race에서 candidate와 baseline 각각 calibrated pair 확률 합에서 3을 뺀 signed·absolute 편차도 race-level diagnostics로 저장하며 제약으로 맞추지 않는다.

## 금지된 변경·범위

fit 승인 전에는 계수, H2 calibrator, 새 pair 확률, 신규 pair 적중/확률 품질, 연도·거리 성능을 산출하지 않는다. 승인된 preflight는 hash, schema, 키, cohort/split, 결측 규칙, 세 개 positive pair 수 산술, 기존 comparator 선택 재현만 확인한다. 기존 source·연구·운영 파일을 수정하지 않고 모든 새 문서·코드·lock·출력은 `jeju/research/20261011_pair_top3_direct_v1/` 아래에 둔다. DB는 연결하지 않고 네트워크를 사용하지 않는다.
