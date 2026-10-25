# 2026-10-25 추천 5두 집합 선택: 원천 감사

상태: **구조·출처 감사 및 승인된 후향 실행 완료.** 원천·모집단·후보 확률을 결과 계산 전에 확인했다. Root는 candidate Q를 독립 복원했고 selection/report 코드를 각각 검토 승인했다. 결과 단계는 선택 원장 hash를 고정 확인한 뒤 별도 실행했으며, 독립 outcome 재계산 key metrics가 일치했다. 전체 결과는 `outputs/REPORT.md`와 `outputs/metrics.json`에 있다.

## 사용할 기존 원천

| 역할 | 읽기 전용 경로 | 고정 SHA-256 | 크기 |
|---|---|---|---:|
| F1_STYLE6 원점수·경주 roster·Top3 label | `jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet` | `c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1` | 약 860 KB |
| 관계 입력·사전 이력 | `jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet` | `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f` | 5,476,534 B |
| 동결 관계 후보의 전체 정확 Top3 분포 | `jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet` | `13409e65353c0cb6dab14df97317cce24de913056ae464ee3524520759de681c` | 10,000,041 B |
| 동결 관계 계수·scaler·fold별 온도 | `jeju/research/20261010_joint_relationship_v1/outputs/fit_parameters.json` | `ff96e32cc4e0c991ac1326ef111a785b0e4f11b49daedc9f584be00dfe72eaeb` | 27,463 B |
| 관계 후보 실행 영수증 | `jeju/research/20261010_joint_relationship_v1/outputs/fit_receipt.json` | `8470f4d5848e12824511e3a6b03b2f481f760dcb7c433b59624894a8482b61dc` | 4,096 B |
| 평가일 paired bootstrap 일정 | `jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy` | `d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd` | 2,152,128 B |
| 독립 Q 복원 receipt | `jeju/research/20261025_top5_set_rootreview_v1/ROOT_Q_RECONSTRUCTION.json` | `f50e75f1815793fd4874bc36f38f80d64c4fd0192da2e89fb144b9ae7bae627a` | root 재검산 receipt |
| 독립 Q 복원 코드 | `jeju/research/20261025_top5_set_rootreview_v1/reconstruct_q.py` | `1e6c0f2b6b479273907328b3d32a6ffd903217afd445678dd684f7bc50fa04ec` | root 재검산 코드 |

관계 연구의 원천 잠금은 39개 파일을 경로·해시로 기록하고 있으며 fit 전후 해시가 같다고 보고한다. 고정 계획 SHA는 `e0a34c6962112d88bfec7e645efbd8e4ea69bf4aada088f580e1188bac1207f3`다. 기존 source lock, feature, parquet, 계수 파일은 새 폴더로 복제하지 않는다.

## 출처·범위 확인

- Frozen runner 파일은 `variant=F1_STYLE6`만 포함하며 17,412행, 1,779경주, 269경주일이다. 제외 말 `3005648`은 없다. `score`는 성능 선택에 사용할 raw score다. 2024·2025·2026 각 연도에 대해 이 점수를 기존 관계 연구의 `evaluation_scores.parquet`와 `api_record_id`로 일대일 대조했고 모든 점수가 완전히 같았다(연도별 최대 절대차 0.0).
- 같은 세 연도의 17,412개 `(race_id, horse_number)` 키가 스타일 feature roster와 정확히 같다. 저장된 관계 분포의 candidate arm도 baseline의 1,779개 race ID를 모두 포함하고 거리·경주 분포가 같다.
- `all_triples.parquet`는 두 arm에 대해 각각 201,404행이다. candidate 행은 경주 전체 `C(N,3)` 정확 Top3 집합의 저장 확률 `probability`와 정렬된 `triple_numbers`를 포함한다. 이 연구에서 읽을 candidate 열은 `race_id`, `evaluation_year`, `distance_m`, `triple_numbers`, `probability`뿐이다. `is_true_set` 등 결과 label 열은 선택 단계에서 읽지 않는다.
- 기존 candidate는 F1_STYLE6 점수와 사전 기록된 스타일 관계 입력을 사용한다. fold별 계수는 H1에서 학습하고 baseline/candidate의 온도는 H2에서 각각 정했다. 평가연도 2024·2025·2026에서 H1/H2 경주는 각각 312/336, 326/311, 329/325다. 기존 fit receipt는 기본 말 모델 재학습 0회, 계수 최적화 3회, 온도 최적화 6회, fit 단계 결과 지표 계산 0회, 입력 해시 변경 0회를 기록한다. 기존 계획·독립 구조 검증과 원천 기반 사후 검산은 PASS다.
- 이 저장 확률은 기존 6-ticket exact-set 평가용 관계 후보다. 기존 6-ticket hit/NLL 성능 gate는 실패했고 승격되지 않았다. 5두 coverage는 별도 단일 후향 선택 결정이다. 같은 2024–2026 label을 이미 기존 연구에서 검토했으므로 이 비교는 독립 미래검증이 아니다.
- 최근 연구 폴더를 확인했다. 2026-10-22 joint wager baseline은 F1_STYLE6 점수의 Plackett–Luce 온도 변환이다. 이 모델의 top-3 순서는 독립 `E_i ~ Exp(1)` 기준변수로 만든 시계 `E_i / w_i`의 처음 세 말로 표현된다. 선택 집합 안의 말 `b`와 밖의 말 `a`에 대해 `w_b > w_a`이면, `E_a,E_b`를 고정한 상태에서 같은 집합의 성공은 `b`의 rate를 키우고 `a`의 rate를 낮출수록 단조 증가한다. 이 rate를 교환한 분포는 말 이름을 맞바꾼 원래 PL 분포와 같으므로 `a` 대신 더 높은 점수의 `b`를 넣은 집합의 q가 더 크거나 같다. 따라서 고정 크기 5두의 q 최대화는 PL의 상위 5두와 일치한다. 원시 additive exact-set Gibbs 분포도 고정 크기 집합에서 세 가중치의 elementary symmetric sum을 최대화하므로 Top5와 일치한다. 선택 집합을 바꿀 수 있는 기존 호환 후보로는 2026-10-10의 pair-interaction joint 분포가 적합하다. 이후 S/TB-state 모델은 말 평가 점수 자체를 바꾸므로 이번 고정-score 질문에 넣지 않는다.

Root의 독립 Q 복원은 고정된 feature/scaler/projection/RMS/beta/tau로 candidate와 matched-baseline 201,404개씩을 재구성했다. receipt는 1,779경주, 두 arm 모두 최대 절대 Q 오차 0.0, 최대 질량 오차 `6.66e-16`, temporal-gap 검사 PASS, outcome label 미조회, 새 적합 0회를 기록한다. selector는 실행 전 receipt·복원 코드와 네 source hash를 고정 확인한다.

## 승인된 선택 및 결과 실행

- 전체 1,779경주에서 점수 Top5와 joint q-max Top5를 비교했다. 경주마다 정확히 5두를 선택했고, matched-baseline unary negative control은 모든 1,779경주에서 기존 score Top5와 일치했다. 후보 집합은 전체에서 386경주, primary 거리에서 331경주 변경됐다.
- Primary 1,503경주에서 all-three hit은 score Top5 439/1,503 (29.208%)이고 joint q-max Top5 415/1,503 (27.611%)였다. 차이는 −1.597 percentage points이며 2,000회 paired date-bootstrap 95% CI는 [−2.804, −0.402] pp다. 사전 성공 gate(차이와 CI 하한 모두 0 초과)는 통과하지 않았다.
- Full cohort에서는 score Top5 519/1,779 (29.174%), joint q-max Top5 500/1,779 (28.106%), 차이 −1.068 pp였다. Primary에서 후보만 맞힌 경주는 27, baseline만 맞힌 경주는 51이다. mean captured actual Top3는 2.072에서 2.057로 낮아졌다.
- Primary의 candidate-distribution expected coverage utility는 baseline set의 평균 0.26930에서 q-max set의 0.27139로 올랐지만, 실제 all-three hit-rate는 낮았다. 예측 효용을 실측 포함률로 해석하지 않는다.
- Root의 독립 outcome 재계산은 label 확인 뒤 별도 구현으로 primary/full hit counts, paired bootstrap CI, year별 primary counts를 검증했고 모두 일치했다. selector와 report는 새 적합·결과 후 튜닝을 하지 않았다. 이 반복 사용 개발 표본의 후향 결과는 독립 미래검증이나 운영 승격 근거가 아니다.

## 모집단과 보조 층화의 사전 확인

- 전체 모집단은 2024-01-05~2026-09-19, 1,779경주·17,412두·269일이며 2026년은 9월 19일까지의 부분 연도다.
- 지정 primary 거리는 900/1000/1110/1200m이고 각각 251/508/482/262경주, 합계 1,503경주다. 모든 269 경주일에 primary 경주가 하나 이상 있다. 전체 1,779경주는 secondary로 유지한다. favorite 여부로 표본을 제한하지 않는다.
- 편성은 N=7: 36경주, N=8: 81, N=9: 112, N=10: 1,548, N=12: 2다. 최소 N=7이므로 N<5 선택 불가 경주는 0이다.
- 2,000×269 bootstrap 일정은 NumPy `int32` 배열이고 receipt상 seed 20261011, 날짜 inventory hash `e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84`다. 새 일정은 생성하지 않는다.
- 경력 층화는 label을 쓰지 않고 race roster의 pre-race `observed_starts` 중앙값을 사용했다. Primary 1,503경주의 중앙값 분포 1/3·2/3 분위수는 사전 자료만으로 고정한 13.5와 26.5이며 구간은 `≤13.5`, `(13.5, 26.5]`, `>26.5`다. 같은 경계로 전체 코호트도 기술했다.

원천 수집, DB 연결, 시장·odds 데이터는 필요하지 않다. 저장된 분포는 원 경주에 대한 OOS F1_STYLE6 raw score를 사용했으나, 라벨·경주일은 반복 분석된 과거 개발 자료다. 공개 시각을 새로 복원하거나 독립 홀드아웃으로 부르지 않는다.
