# Top5 reward-learning source audit

상태: 입력 원천·기존 root source audit를 고정했다. 기존 audit는 evaluation outcome 및 feature label columns를 읽지 않았으며 실제 fit은 새 폴더의 승인된 코드로만 수행한다. 원천 테이블·모델·DB는 복사하지 않는다.

## 고정 원천

| 목적 | 읽기 전용 경로 | SHA-256 |
|---|---|---|
| 2017–2026 고정 F1_STYLE6 runner feature와 학습 finish labels | `jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet` | `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f` |
| frozen 2024–2026 runner roster/raw score | `jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet` | `c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1` |
| independent source-only audit | `jeju/research/20261025_top5_direct_learning_rootreview_v1/ROOT_SOURCE_AUDIT.json` | `b263703aae9e7d5eca2bda394d4c20de67144bcaf78e959f5add9efffc8310f8` |
| OOF score source | 2019–2022 `20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_{2020..2023}/calibration_scores.parquet`; 2023–2025 `20261010_style_history_ablation_v1/outputs/F1_STYLE6_{2024..2026}/calibration_scores.parquet` | 각 파일 hash는 `fit_selector.py`의 상수와 fit receipt에 고정 |
| 이전 partial-event NLL 선택 arm | `jeju/research/20261025_top5_direct_learning_v1/outputs/candidate_choices.jsonl` 및 receipt | 선택 단계에서 path/hash를 재검증해 비교; 기존 파일을 변경하지 않음 |
| 이전 root review의 fitted model audit | `jeju/research/20261025_top5_direct_learning_rootreview_v1/ROOT_FITTED_MODEL_AUDIT.json` | SHA 검증 후 fit/선택 뒤 감사 참조 |
| 고정 2,000회 date-bootstrap draws | `jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy` | `d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd` |

## 독립 점검 상태

`ROOT_SOURCE_AUDIT.json`은 `passed=true`, 17,412 evaluation runners / 1,779 races, 52,155 feature rows, runner ID·OOF score coverage, T−2 history cutoff, provider refit date 조건, 제외 말 `3005648` 부재를 기록한다. 해당 audit 시점에 DB를 열지 않았고 `finish_position`/evaluation outcomes를 읽지 않았다. Training labels의 경주 완전성 검사는 새 fit script가 각 cutoff에서 별도로 수행한다.

**이전 manifest의 hash typo를 보존/처리한다.** 이전 `20261025_top5_direct_learning_v1/FINAL_MANIFEST.json`(SHA `29cb6310bbecf79245b69ddc43521d01257b80a99f802e48840742a0752dc8e5`)의 `/frozen_sources/evaluation_raw_score_and_roster/sha256` 값은 잘못 기재되어 있다. 원본 manifest를 수정하지 않고 `jeju/research/20261025_top5_direct_gain_loss_rootreview_v1/SOURCE_HASH_METADATA_CORRECTION.json`(SHA `dfa60f6e7ced44f6c565be406a6cbd5e6784da74c5752d9dada608c7e8bd648d`)에서 올바른 baseline SHA `c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1`를 확인했다. 기존 source audit와 selection code는 올바른 파일 hash를 사용한다고 수정 영수증에 기록되어 있다. 새 코드도 올바른 hash로 직접 검사한다.

Training-label cutoff는 fold별 `2019 <= year < evaluation_year`이고 evaluation year labels는 이 fit에서 읽지 않는다. OOF score provider의 metadata `refit_max`는 각 row의 race date보다 적어도 이틀 앞서야 한다. input feature, rosters, outputs는 저장된 source file path와 hash로만 참조한다. 새 study 외부 파일을 생성하거나 DB/network를 사용하지 않는다.

## Population / method boundary

Old root source audit의 평가 roster는 269 dates (2024-01-05~2026-09-19), 1,503 primary-distance races 및 1,779 full-distance races다. 이를 반복 사용한 과거 개발자료로 취급한다. 학습 window는 2,492 / 3,129 / 3,783 races (Y=2024/2025/2026)다. 최대 field size는 13, `C(13,5)=1,287`; candidate arrays are fold-local transient memory, never persisted.

New fit objective is the exact expected `+1/-1` reward over every five-runner set under temperature-1 Gibbs `softmax(E)`, with fixed additive raw-score prior and the same 11 standardized features. It is not PPO/LLM tuning, calibrated probability, or a direct deterministic argmax coverage objective. Any later deterministic coverage number comes only from the separately approved choice and outcome stages.
