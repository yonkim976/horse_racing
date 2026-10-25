# 사전 원천·가용성 조사

작성일: 2026-10-10. 읽기 전용 로컬 자산 조사다. 모델 학습·새 outcome 집계·평가·DB 접속은 실행하지 않았다.

## 잠금과 관련 문서

- 설계 감사: `jeju/research/20261010_probability_combo_gap_design_audit_v1/README.md`, `REVIEW_MEMO.md`, `source_manifest.json`. 조합 확률 정의, tie 순서, 이전 축 동반 연구 중복 경계 및 반복 사용 코호트 한계를 참조했다.
- 이전 조합 gap source lock은 요청된 연구 폴더 최상위가 아니라 `jeju/research/20261010_probability_combo_gap_v1/outputs/source_lock.json`에 있다. 해시 `e66b4f33919af721a3ebceccfef2966783aea0b4b322d760de179ef06fa921a9`. 같은 연구의 `PLAN.md`와 `data_contract.json`도 manifest가 고정한 계획·모집단 근거다.
- F1_STYLE6 저장 자산 목록은 `jeju/research/20261010_style_history_ablation_v1/ARTIFACT_MANIFEST.json`, 입력 lock은 `.../outputs/prepared_lock.json`(SHA-256 `f110b33b0442e519fd3f9852098aa847af90d2228af674c39db4914142675e24`)이다. 입력 feature와 기존 결과는 참조만 한다.

## 확인된 OOS 점수와 입력

| 사용할 fold | OOS calibration raw score | 생성 모델의 학습/refit 이력 | 점수 행·경주 | 파일 SHA-256 |
|---|---|---|---:|---|
| 2024 평가 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/calibration_scores.parquet` | 2017~2021 초기학습; 2022 early-stop/refit; 2023 calibration; 2024 평가 | 6,506 / 657 | `360cc559b1ab19cde177e0bb23206fd36f123b707714fbcb63547fdb9bed05b2` |
| 2025 평가 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/calibration_scores.parquet` | 2017~2022 초기학습; 2023 early-stop/refit; 2024 calibration; 2025 평가 | 6,329 / 637 | `b092d28f0cbd45dd3a184a4a8ab89e9b5b5a78eef8068c45fda3de92734a3755` |
| 2026 평가 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/calibration_scores.parquet` | 2017~2023 초기학습; 2024 early-stop/refit; 2025 calibration; 2026 평가 | 6,410 / 654 | `6a7ed320e59add698faafd9008c882dc8a83a84f9198094371525f4c4ebd37d8` |

파일은 기존 manifest에 모두 등록됐고 `run.py`는 이 점수를 calibration 연도의 같은 refit model에서 `raw_score=True`로 만든다. 세 calibration score schema는 writer 코드 기준 `api_record_id:int64, score:float64`다. fold별 calibration window는 각각 2023-01-06~12-30, 2024-01-05~12-28, 2025-01-03~12-27이다. 해당 연도 saved `tau`는 전체 window 라벨로 최적화되어 있어 H1에서 쓰지 않는다.

모든 score와 runner 입력은 `jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet` (52,155행·5,206경주, SHA-256 `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f`)의 `api_record_id`로 연결 가능하다. 이 저장 테이블은 F1 24열에 앞서 감사된 T−2 style-history 6열을 더한다. 관계 입력으로 사용할 정확한 style 열은 PLAN에 열거했다. roster·label·date도 동일 테이블에서 읽을 수 있고 별도 수집/DB 연결이 필요하지 않다.

평가 원시 점수는 기존 `.../outputs/F1_STYLE6_{2024,2025,2026}/evaluation_scores.parquet`에 저장되어 있다. row/hash와 `meta.json`의 저장 tau는 style ablation manifest에 고정됐다. baseline 비교 결과는 `.../outputs/f1_reproduced_runner_predictions.parquet` 및 `.../outputs/report/canonical_six_combinations.csv`에서 고정 reference로 추적한다. 기존 combo-gap 연구의 `data_contract.json`은 동일 F1_STYLE6 모집단을 1,779경주·17,412출전·269일(2026-09-19까지)로 선언한다.

`outputs/candidate_scores_fit_stage.parquet`는 이름과 달리 training rows의 OOF 파일이 아니다. style `run.py`에서 세 평가연도의 `evaluation_scores.parquet`를 이어 붙인 17,412행 평가 score artifact다. 관계 모형 H1 자료로 쓰지 않는다. 반면 연도별 `calibration_scores.parquet`가 필요한 OOS calibration score 원천이다.

## 수용 가능성·계산 규모

기존 보유 자산만으로 H1 관계 fit, H2 확률 보정, 2024~2026 평가를 구성할 수 있다. 기반 F1_STYLE6 말모형 학습은 추가하지 않는다. 연도별 H1/H2 calendar split 사전 조사 경주 수는 2023년 321/336, 2024년 326/311, 2025년 329/325(H1/H2)다. 이는 T−2 boundary purge 전 잠정치다. 정확 날짜, purge 후 수와 날짜별 roster를 outcome 실행 전에 코드 preflight로 확정하고 source lock에 넣어야 한다.

가장 큰 평가 계산은 같은 1,779경주 전체에서 모든 unordered triple을 한 번 순회하는 것이다. 앞선 F1/F1_STYLE6 combo-gap 진단은 두 variant 합계 402,808 triple을 저장했으므로 이 후보 하나의 규모는 약 절반인 201,404 triple이다. 실제 수는 preflight에서 같은 roster를 기준으로 재계산해 고정한다. 학습은 3개 H1 fold마다 수백 경주의 모든 triple에 대해 11차원 선형 조건부 likelihood를 최적화하고, H2에는 baseline/candidate scalar temperature를 각각 맞춘다. 이는 기존 6회 LightGBM base fit을 새로 하는 작업과 달리 CPU 상의 작은 저차원 최적화다. 데이터 복사·DB·네트워크 작업은 필요하지 않다.

## 확정하지 않은 점

이 초안은 독립 감사 및 root 검토가 끝나기 전이다. 특히 calendar split에서 실제 `D_H2`, T−2 purge 뒤 H1 row/race/date 수, fold별 정확 triple 수, projection degenerate-column 기록은 preflight에서 확인해 계약에 잠근다. 이 확인은 입력·키·시점·구조만 검사하며 outcome metric이나 모델 계수를 계산하지 않는다.
