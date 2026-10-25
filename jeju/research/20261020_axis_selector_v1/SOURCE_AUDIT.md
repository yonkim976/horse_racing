# F1_STYLE6 축 선택 연구 입력·OOF 감사

상태: **로컬 소스/OOF 계약 검토 PASS.** source-only 실행 영수증은 `outputs/PREFLIGHT.json`에 남긴다. 본 문서는 예측 성과를 계산하지 않으며 selector fit 승인 전 자료 계약을 기록한다. 독립 감독자의 상세 source inventory는 `jeju/research/20261020_axis_selector_rootreview_v1/ROOT_SOURCE_AUDIT.json`에 있다.

## 확인한 고정 자료

- `20261010_style_history_ablation_v1/outputs/features.parquet`: 52,155 출전·5,206경주, 2017-01-13~2026-09-19. `api_record_id`와 `(race_id, horse_number)`가 유일하다. 보유 이력의 `history_cutoff`는 모든 행에서 경주일−2일이고, `latest_history_date`는 cutoff를 넘지 않는다. 제외된 말 ID `3005648`은 없다.
- `20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet`: 17,412 출전·1,779경주·269일, 2024-01-05~2026-09-19. score, `p_top3`, y는 모두 유한하고 `api_record_id`가 유일하다. features의 2024–2026 key/roster와 정확히 대응한다. 900·1000·1110·1200m 주 코호트는 14,714 출전·1,503경주다. 평가 prediction schema에는 favorite/odds 입력이 없다.
- F1_STYLE6 30개 원입력 목록은 동결 모델 meta의 2024–2026 세 fold에서 일치한다. selector가 사용할 기존 피처는 `observed_starts`, `days_since_start`, `same_starts`, `same_valid_times`, `days_since_same`, `mean5_rank_fraction`뿐이며 모두 해당 30열 안에 있다.
- 기존 historical refit 영수증은 `historical_F1_STYLE6_calibration_raw_scores_only` 범위와 fold 2020–2023을 PASS로 기록한다. historical evaluation score, temperature fit, pair fit, pair 성과 계산은 없었다고 기록한다. 각 학습연도에는 다음 fold의 calibration raw score를 연결한다.

| selector 학습 라벨 연도 | raw OOS score 제공자 | 출전/경주 | provider `refit_max` |
|---:|---:|---:|---|
| 2019 | `F1_STYLE6_2020/calibration_scores.parquet` | 5,890 / 576 | 2018-12-29 |
| 2020 | `F1_STYLE6_2021/calibration_scores.parquet` | 3,290 / 329 | 2019-12-28 |
| 2021 | `F1_STYLE6_2022/calibration_scores.parquet` | 4,331 / 418 | 2020-12-20 |
| 2022 | `F1_STYLE6_2023/calibration_scores.parquet` | 5,261 / 512 | 2021-12-25 |
| 2023 | `F1_STYLE6_2024/calibration_scores.parquet` | 6,506 / 657 | 2022-12-24 |
| 2024 | `F1_STYLE6_2025/calibration_scores.parquet` | 6,329 / 637 | 2023-12-30 |
| 2025 | `F1_STYLE6_2026/calibration_scores.parquet` | 6,410 / 654 | 2024-12-28 |

각 연도 calibration score는 feature table의 해당 연도 전체 출전키와 정확히 일치하고 score는 유한하다. 모든 provider는 그 연도의 경주일보다 2일 이상 앞서 refit을 마쳤다. selector training input은 raw score만 사용하며, 같은 연도 라벨로 적합한 temperature의 calibrated 확률을 사용하지 않는다. 세 expanding selector fit의 전체 학습 source roster는 25,278·31,607·38,017출전이며, K=3 후보 학습행은 각각 7,476·9,387·11,349행이다. Preflight는 학습 label에서만 `R_mix`와 informative pair 수를 적으며 후보 적중·모델 성과 통계는 계산하지 않는다.

평가 2024·2025·2026에는 각각 해당 `F1_STYLE6_Y/evaluation_scores.parquet`와 동결 baseline runner prediction을 사용한다. 이들의 rows/races는 각각 6,329/637, 6,410/654, 4,673/488이다. 검토 과정에서 score 파일과 baseline 사이의 key·연도·score 일치, baseline y와 frozen label 일치를 확인한다. `p_top3`는 기존 비교 값으로 보존하며 selector 입력이나 새로운 확률로 변환하지 않는다.

## 평가 schedule과 해석 경계

날짜 cluster schedule은 기존 `20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy`이며 고정 SHA-256은 `d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd`다. 2,000 draw, 269개 평가일, seed 20261011이다. source preflight에서 2024–2026 정렬 날짜 inventory와 schedule 원본을 대조한다.

T−2는 저장된 과거 이력 cutoff 계약을 확인한 것이며 실제 당시 원천 공개 시각을 증명하지 않는다. 2019–2025 calibration score와 2024–2026 평가 점수는 서로 다른 model vintage다. 2024–2026 결과는 반복 개발 표본이며 새 미래 holdout이 아니다. 이 감사는 모델 입력 채택, 기존 F1_STYLE6 변경, 운영 등록부 변경을 승인하지 않는다.
