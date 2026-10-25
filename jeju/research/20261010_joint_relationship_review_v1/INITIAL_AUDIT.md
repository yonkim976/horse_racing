# 공동입상 관계 학습 사전 독립감사 메모

상태: 설계·원천 검토. outcome 기반 계산, 후보 학습, 성능 집계는 실행하지 않았다. 이 문서는 지정된 기존 계약·메타데이터·해시를 읽어 만든 독립 검증 기준이다. 이 폴더 밖의 파일과 DB는 수정하지 않았다.

## 범위와 고정 비교

목표는 기존 `F1_STYLE6`의 말별 raw score를 그대로 고정하고, 무순서 정확 Top3 분포에 실제 쌍 관계 항을 추가해 기존 최대 6조합 선택과 비교하는 것이다. 점수 모형이나 말별 입력을 다시 fit하지 않는다. 관계항이 바뀌면 joint distribution에서 계산한 말별 marginal은 달라질 수 있으므로, “말 점수 고정”은 저장 raw score가 고정된다는 뜻으로 계약에 적어야 한다.

현재 비교 기준은 `20261010_probability_combo_gap_v1`의 2024-01-05~2026-09-19 후향 코호트다. 고정 모집단은 1,779경주, 17,412출전, 269경주일이며 실제 출전수는 7~12두다. 따라서 모든 경주에서 `C(N,3) >= 6`을 충족한다. 기존 계획은 F1과 F1_STYLE6의 canonical 6조합을 비교한다. 2026년은 9월 19일까지의 부분연도다. 기존 F1_STYLE6 결과에는 평가 출전 17,412행, 경주별 6장 총 10,674장, 원본 parity 영수증 PASS가 기록돼 있다. 이 독립 검토는 해당 기준 결과를 다시 만들거나 바꾸지 않고 입력 참조로 잠근다.

## 확인한 원천과 해시

지정된 확률 갭 연구의 `README.md`, `data_contract.json`, `ARTIFACT_MANIFEST.json`, `PLAN.md`, `outputs/source_lock.json`과 STYLE6 연구의 `README.md`, `CONTRACT.md`, `IMPLEMENTATION_PLAN.md`, `prepare.py`, `run.py`, `outputs/prepared_lock.json`, replay·preflight 영수증을 읽었다. 실제 파일 위치는 `style_history_ablation`에 `PLAN.md`·`train.py`가 없고 `IMPLEMENTATION_PLAN.md`·`run.py`가 있다.

root가 승인한 구현 계획의 SHA-256 `e0a34c6962112d88bfec7e645efbd8e4ea69bf4aada088f580e1188bac1207f3`와 기존 source lock / artifact manifest에 기록된 해시를 로컬 파일과 대조했다. 확률 갭 계획·계약·분석 코드·점수 계약 입력·STYLE6 모델·평가 score·보존된 canonical 6조합은 잠금값과 일치했다. STYLE6 calibration score 3개도 STYLE6 artifact manifest의 잠금값과 일치한다. 단, calibration score는 앞선 확률 갭 분석의 입력이 아니므로 그 분석의 `source_lock.json` `source_files` 목록에는 없고, 새 연구의 source lock에 별도 등록해야 한다.

| 자산 | SHA-256 | 잠금 근거 |
|---|---|---|
| `20261010_probability_combo_gap_v1/PLAN.md` | `09cb2d20554f2f98a7f9aeaef21b722f86e544e46e904d1b7d80278ab086d4d4` | probability gap source_lock |
| `20261010_probability_combo_gap_v1/data_contract.json` | `7ea6ba197c76e1f83dd73e3dc84939704261695733e93b55dfbb45539d3c018d` | probability gap source_lock |
| `20261010_probability_combo_gap_v1/analyze.py` | `81cce3ada764f3affaf7fafad668f9da7e478aa76cc3cd28baaeb4345b138ecc` | probability gap source_lock |
| `20261010_probability_combo_gap_v1/source_lock.json` | `e66b4f33919af721a3ebceccfef2966783aea0b4b322d760de179ef06fa921a9` | probability gap artifact manifest |
| `20261010_style_history_ablation_v1/ARTIFACT_MANIFEST.json` | `6afc0e8f73ec086052fad4cde4d7edcd62fdf1bbc782108da89732dc3a5b4a4e` | probability gap source_lock |
| `20261010_style_history_ablation_v1/prepared_lock.json` | `f110b33b0442e519fd3f9852098aa847af90d2228af674c39db4914142675e24` | probability gap source_lock |
| `20261009_finish_history_ablation_v1/prepared_lock.json` | `4609c6f40418aaffd833e05c49843357f5ffcdd4b8393bb1da22ec035d3b4378` | probability gap source_lock |
| `20261010_style_history_ablation_v1/f1_reproduced_runner_predictions.parquet` | `04fc9f9a5ce45e8aee76028f10663d6d3c69646e120627f8fca3d545be49914f` | probability gap source_lock |
| `20261010_style_history_ablation_v1/f1_reproduced_six_combinations.csv` | `f2661e7e3d50becd4aee8e01574dd247bf9dfca8fbee1b0a89e900ec5433dbba` | probability gap source_lock |
| `20261010_style_history_ablation_v1/report/canonical_six_combinations.csv` | `9cd5e7e3fed202f1a709aee4a0d43a75850661fc17b691679c447b8c24182e71` | probability gap source_lock |
| `20261010_style_history_ablation_v1/features.parquet` | `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f` | STYLE6 prepared_lock |
| `20261010_style_history_ablation_v1/F1_STYLE6_2024/top3.txt` | `6ab3c54f55f925336256d1e3e8680087993ba377b2863b367b505fda3b281be5` | STYLE6 artifact manifest |
| `20261010_style_history_ablation_v1/F1_STYLE6_2024/meta.json` | `15acbf959654da82d2240027e7b7d768bb9226af18395dac9ec92a68a4471726` | STYLE6 artifact manifest |
| `20261010_style_history_ablation_v1/F1_STYLE6_2024/evaluation_scores.parquet` | `b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60` | STYLE6 artifact manifest |
| `20261010_style_history_ablation_v1/F1_STYLE6_2024/calibration_scores.parquet` | `360cc559b1ab19cde177e0bb23206fd36f123b707714fbcb63547fdb9bed05b2` | STYLE6 artifact manifest |
| `20261009_finish_history_ablation_v1/F1_2024/top3.txt` | `f2373c48e0a6d415e64f577dc64c14d12d71f9b97ea5d3a0c78853f12870eb5d` | probability gap source_lock |
| `20261009_finish_history_ablation_v1/F1_2024/meta.json` | `937df06c1c9ed61b8b380bcbb3c0db33b5efd1b197f0c262ceab19c162c63970` | probability gap source_lock |
| `20261010_style_history_ablation_v1/F1_STYLE6_2025/top3.txt` | `0853e411bac3ea0424fd3d9332a9e2b9ffc0b83eab9fbde7316ddd3a35dde5c4` | STYLE6 artifact manifest |
| `20261010_style_history_ablation_v1/F1_STYLE6_2025/meta.json` | `23c4b0684477f34fbb2e99c22d0037cd903d5459db369f084773ec25c640f4a8` | STYLE6 artifact manifest |
| `20261010_style_history_ablation_v1/F1_STYLE6_2025/evaluation_scores.parquet` | `45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12` | STYLE6 artifact manifest |
| `20261010_style_history_ablation_v1/F1_STYLE6_2025/calibration_scores.parquet` | `b092d28f0cbd45dd3a184a4a8ab89e9b5b5a78eef8068c45fda3de92734a3755` | STYLE6 artifact manifest |
| `20261009_finish_history_ablation_v1/F1_2025/top3.txt` | `b66ece1487c86ad1cd05aabed7f3781d84e89c24e6a3ebcb010f38b811009b9d` | probability gap source_lock |
| `20261009_finish_history_ablation_v1/F1_2025/meta.json` | `6be12814c61da778077c2706712171db55b878e2b917f63608af1dfa81e09272` | probability gap source_lock |
| `20261010_style_history_ablation_v1/F1_STYLE6_2026/top3.txt` | `732911138e2bb495ea48a49b3f736a7dbd5b28f5b0b441ae20d6a61d19fb7e40` | STYLE6 artifact manifest |
| `20261010_style_history_ablation_v1/F1_STYLE6_2026/meta.json` | `e9dbfe5226571cb29e34b352a4ad8808a735d70929e66b42efb41b3e807ff06d` | STYLE6 artifact manifest |
| `20261010_style_history_ablation_v1/F1_STYLE6_2026/evaluation_scores.parquet` | `0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a` | STYLE6 artifact manifest |
| `20261010_style_history_ablation_v1/F1_STYLE6_2026/calibration_scores.parquet` | `6a7ed320e59add698faafd9008c882dc8a83a84f9198094371525f4c4ebd37d8` | STYLE6 artifact manifest |
| `20261009_finish_history_ablation_v1/F1_2026/top3.txt` | `15654e60d6736aabc0ec0af60cbdf4478c05b8fb6227d826dd8aff0ef1f347a4` | probability gap source_lock |
| `20261009_finish_history_ablation_v1/F1_2026/meta.json` | `ae5d32feb5fdfe3145851dee335bbf9bdbfb9073b9f541c678c90f89245e3189` | probability gap source_lock |
| `20261010_joint_relationship_v1/PLAN.md` | `e0a34c6962112d88bfec7e645efbd8e4ea69bf4aada088f580e1188bac1207f3` | root-approved plan hash |

| 평가 연도 | 모델 SHA-256 | meta SHA-256 | raw evaluation score SHA-256 | calibration raw score SHA-256 | 기존 τ |
|---:|---|---|---|---|---:|
| 2024 | `6ab3c54f55f925336256d1e3e8680087993ba377b2863b367b505fda3b281be5` | `15acbf959654da82d2240027e7b7d768bb9226af18395dac9ec92a68a4471726` | `b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60` | `360cc559b1ab19cde177e0bb23206fd36f123b707714fbcb63547fdb9bed05b2` | 1.1006448744 |
| 2025 | `0853e411bac3ea0424fd3d9332a9e2b9ffc0b83eab9fbde7316ddd3a35dde5c4` | `23c4b0684477f34fbb2e99c22d0037cd903d5459db369f084773ec25c640f4a8` | `45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12` | `b092d28f0cbd45dd3a184a4a8ab89e9b5b5a78eef8068c45fda3de92734a3755` | 1.1156577765 |
| 2026 | `732911138e2bb495ea48a49b3f736a7dbd5b28f5b0b441ae20d6a61d19fb7e40` | `e9dbfe5226571cb29e34b352a4ad8808a735d70929e66b42efb41b3e807ff06d` | `0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a` | `6a7ed320e59add698faafd9008c882dc8a83a84f9198094371525f4c4ebd37d8` | 0.9719459584 |
해시 근거는 [확률 갭 artifact manifest](../20261010_probability_combo_gap_v1/ARTIFACT_MANIFEST.json), [확률 갭 source lock](../20261010_probability_combo_gap_v1/outputs/source_lock.json), [STYLE6 artifact manifest](../20261010_style_history_ablation_v1/ARTIFACT_MANIFEST.json), [STYLE6 prepared lock](../20261010_style_history_ablation_v1/outputs/prepared_lock.json)이다. 기존 보호 잠금은 운영 DB·등록부·`HY_R_FORM.pkl`도 기록하며, 이 연구 경로에서는 쓰기 금지다. 새 검증은 baseline 및 STYLE6 점수·모형 해시가 시작과 끝에 유지되는지도 확인해야 한다.

## 시점 분할과 OOF 가능성

각 저장 STYLE6 후보는 30개 입력(기존 F1 24개 + STYLE6 6개)을 사용한다. 연도 Y의 후보는 초기 학습 2017~Y−3, 조기종료 및 refit 상한 Y−2, calibration Y−1, evaluation Y다. 따라서 2024 평가 모델은 2022-12-24까지 refit하고 2023 raw calibration score를 저장했으며, 2025 모델은 2023-12-30까지 refit하고 2024 calibration score를, 2026 모델은 2024-12-28까지 refit하고 2025 calibration score를 저장했다. 평가 시작일은 각각 2024-01-05, 2025-01-03, 2026-01-02다.

저장 calibration raw score는 그 해당 연도의 F1_STYLE6 모델 학습·refit에 쓰이지 않은 연도 점수이므로, 다음 평가연도 관계 학습에 쓸 시계열 OOF 후보 입력이 존재한다. 반면 모델 학습연도 안의 저장 feature 행을 같은 모델로 점수화해 관계를 학습하면 in-sample이므로 허용하지 않는다. 저장된 기존 τ는 calibration 연도 전체 라벨을 이용해 산출됐다. 따라서 그 τ를 같은 해 H1 관계 fit에 쓰면 H2 라벨 정보가 fit 경로로 섞인다.

감독 검토 방향은 calibration 연도의 날짜순 H1/H2 분할이다. H1은 raw score를 offset으로 삼아 관계 계수만 fit하고, 이 단계에 기존 연간 τ를 사용하지 않는다. H2는 후보 joint τ와 같은 날짜 집합에서 다시 계산한 matched baseline τ만 보정한다. 다음 연도 평가 점수·라벨은 fit·calibration 경로에 들어가지 않는다. 비교 문서에는 원래 저장 τ를 쓴 고정 F1_STYLE6 결과도 계속 포함하고, H2 matched-τ null baseline과 관계 후보 비교를 따로 표시해야 한다.

정확한 분할은 race date 기준으로 계약에 고정해야 한다. 같은 날 여러 경주가 있으면 전부 같은 H1/H2 블록에 둔다. 각 경계에서 `train_max_date <= next_block_min_date - 2 calendar days`를 만족하도록 H1 말단을 purge한다. 이 검사는 F1 refit→H1, H1 pair fit→H2 calibration, H2 calibration→다음 평가연도 세 구간마다 실제 날짜로 확인한다. 단순히 연도나 반기로 나눴다는 설명은 통과 근거가 아니다. 이 2일 간격은 F1 역사 입력의 경주일 T−2 계약과 맞춘 날짜 기반 절단이며, 게시시각이 복구됐다는 뜻은 아니다.



실제 calibration-year 분할은 달력 규칙과 T−2 purge 후 다음과 같이 재구성됐다. race별 runner 수 일치와 메타데이터 상 refit cutoff도 별도 검사한다.

| 평가연도 | calibration 연도 | H1 race / purge | H1 마지막 날짜 | H2 race / 첫 날짜 | H1/H2 최소 출전수 |
|---:|---:|---:|---|---:|---:|
| 2024 | 2023 | 312 / 9 | 2023-06-24 | 336 / 2023-07-01 | 8 / 8 |
| 2025 | 2024 | 326 / 0 | 2024-06-29 | 311 / 2024-07-05 | 8 / 8 |
| 2026 | 2025 | 329 / 0 | 2025-06-28 | 325 / 2025-07-04 | 7 / 7 |

세 fold 모두 refit→H1, purge 후 H1→H2, H2→평가 첫 경주일의 실제 날짜 차이를 각각 계산해 최소 2일을 만족해야 한다. 검증 코드는 각 race day를 분할 단위로 유지하고, H1 말단은 `H2 min date - 2 days`보다 늦을 경우 경주 전체를 purge한다.

## 남은 검토 위험

1. 관계 learner의 pair term이 어떤 사전 경주 변수에서 만들어지는지, 해당 변수가 모든 대상 경주에서 T−2 기준으로 가용했는지 아직 새 계약이 없다.
2. pair term이 단순 unary 점수 재표현이 아닌지 수학적으로 확인해야 한다. 모든 가능한 triple에서 pair correction을 unary incidence 공간에 사영하고, 잔차 interaction이 수치 허용오차보다 큰지 독립 계산할 수 있다.
3. H2 tau를 별도 fit하면 기존 저장 τ 기준 baseline과 후보의 calibration 설정이 다르다. 원래 frozen baseline, 동일 H2 기간 matched-τ null, pair 후보를 각각 보존해 해석을 분리해야 한다.
4. 이번 고정 코호트는 이미 반복 사용된 후향 자료다. 결과는 미래 독립 검증이나 운영 반영 근거가 아니다.

독립 검증 전까지 성능 주장은 보류한다. 학습 실행, outcome 결과 생성, 중앙 conclusion/등록부 갱신, 운영 승격은 범위 밖이며 root의 별도 승인 없이는 진행하지 않는다.
