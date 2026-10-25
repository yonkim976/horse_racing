# 역사적 F1_STYLE6 OOS 입력 가용성 및 설계 원천 감사

상태: 2026-10-11 read-only source inventory. 현재 단계에서는 기존 저장 파일만 확인했다. historical refit, raw score 생성, pair fit, pair performance 계산은 하지 않았다. 새 결과 경로는 이 연구 폴더이며, 그 밖의 파일은 수정하지 않았다.

## 지침·계약 확인

이 작업을 시작하며 `jeju/AGENTS.md`, `jeju/docs/RESTART_PLAN_20260928.md`, `jeju/docs/JEJU_PREDICTION_OBJECTIVES_2026-09-28.md`, `jeju/review_documents/README.md`, `jeju/research/RESEARCH_PUBLICATION_POLICY.md`를 읽었다. 제주 데이터·연구 결과·시간 분할·보존 규칙을 적용한다. 코드 보안 작업지침 `~/.codex/skills/code-security/SKILL.md`도 확인했다. 이번 단계는 계획·원천 감사 문서만 작성하므로 신규 모델 코드를 작성하지 않았다.

## 고정 STYLE6 feature 원천

`20261010_style_history_ablation_v1`의 frozen feature table은 52,155 출전·5,206 경주이며 2017-01-13부터 2026-09-19까지다. `F1_STYLE6`는 기존 F1 24개 feature에 여섯 개 history-style 입력을 더한 30입력이다. 이 feature table과 `style_history_lineage.parquet`는 raw score가 아니라 입력·라벨 및 lineage 원천이다. 해당 lineage/cache에는 이 table을 만드는 과거 style 입력 자료가 있지만 F1_STYLE6 역사 예측 점수나 refit model checkpoint는 없다.

| Calendar year | Feature rows | Feature races | Feature date range |
|---:|---:|---:|---|
| 2017 | 4,354 | 432 | 2017-01-13–2017-12-30 |
| 2018 | 5,111 | 503 | 2018-01-12–2018-12-29 |
| 2019 | 5,890 | 576 | 2019-01-11–2019-12-28 |
| 2020 | 3,290 | 329 | 2020-01-03–2020-12-20 |
| 2021 | 4,331 | 418 | 2021-01-08–2021-12-25 |
| 2022 | 5,261 | 512 | 2022-01-07–2022-12-24 |
| 2023 | 6,506 | 657 | 2023-01-06–2023-12-30 |
| 2024 | 6,329 | 637 | 2024-01-05–2024-12-28 |
| 2025 | 6,410 | 654 | 2025-01-03–2025-12-27 |
| 2026 | 4,673 | 488 | 2026-01-02–2026-09-19 |

이 표는 frozen feature table의 calendar inventory다. root/C의 independent source review는 2019–2025 확장 cohort의 full-finishing roster/rank 산술과 style lineage를 확인했다. 아래 pair-specific preflight는 이를 새 파일 hash와 score provenance에 묶어 재확인한다.

## 저장 raw score·model·fit-stage inventory

전체 repository의 숨김 파일까지 `F1_STYLE6`, `calibration_scores`, `evaluation_scores`, `OOF/oof` 및 fit-stage 명칭으로 검색하고 style study의 모든 output 파일을 목록화했다. 저장된 F1_STYLE6 fold/model/raw score는 2024~2026만 있다. 2020~2023의 `F1_STYLE6_{year}` refit 폴더·checkpoint, calibration/evaluation score file, historical OOF score cache는 없다. `candidate_scores_fit_stage.parquet`는 2024~2026 evaluation raw scores 17,412행뿐이다. 다른 연구 폴더에 존재하는 OOF, F1(24 input) 또는 다른 family의 calibration scores는 F1_STYLE6 model family가 아니므로 대체 입력으로 쓰지 않는다.

| Stored fold | Saved model checkpoint | Calibration score role/year | Evaluation score role/year |
|---:|---|---|---|
| 2024 | `outputs/F1_STYLE6_2024/top3.txt` | 2023: 6,506 rows / 657 races | 2024: 6,329 rows / 637 races |
| 2025 | `outputs/F1_STYLE6_2025/top3.txt` | 2024: 6,329 rows / 637 races | 2025: 6,410 rows / 654 races |
| 2026 | `outputs/F1_STYLE6_2026/top3.txt` | 2025: 6,410 rows / 654 races | 2026: 4,673 rows / 488 races |

세 saved calibration/evaluation score 파일은 각 대상연도의 `features.parquet` 출전 ID와 정확히 일치했다(누락 0, 여분 0). 현재 2024–2026 eval score들과 metadata는 기존 direct pair study의 source lock에 pinned되어 있다. 이번 결과 보고에서는 이 평가 파일을 그대로 사용한다.

| 파일 | 행/키 | SHA-256 |
|---|---:|---|
| `20261010_style_history_ablation_v1/outputs/features.parquet` | 52,155 / `api_record_id` unique | `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f` |
| `20261010_style_history_ablation_v1/outputs/candidate_scores_fit_stage.parquet` | 17,412 / 2024–2026 eval only | `593b98f658f859d0cf5636c7d54f5dbf541c5346d384a91da53717f638fdbf05` |
| `F1_STYLE6_2024/calibration_scores.parquet` | 6,506 / 2023 | `360cc559b1ab19cde177e0bb23206fd36f123b707714fbcb63547fdb9bed05b2` |
| `F1_STYLE6_2025/calibration_scores.parquet` | 6,329 / 2024 | `b092d28f0cbd45dd3a184a4a8ab89e9b5b5a78eef8068c45fda3de92734a3755` |
| `F1_STYLE6_2026/calibration_scores.parquet` | 6,410 / 2025 | `6a7ed320e59add698faafd9008c882dc8a83a84f9198094371525f4c4ebd37d8` |
| `F1_STYLE6_2024/evaluation_scores.parquet` | 6,329 / 2024 | `b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60` |
| `F1_STYLE6_2025/evaluation_scores.parquet` | 6,410 / 2025 | `45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12` |
| `F1_STYLE6_2026/evaluation_scores.parquet` | 4,673 / 2026 | `0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a` |

## 역사 OOS refit 가능성

고정 STYLE6 recipe는 평가 fold `Y`에서 초기 train 2017..`Y-3`, early-stop `Y-2`, 해당 best iteration으로 `Y-2`까지 refit, calibration `Y-1`, evaluation `Y`다. 이 recipe에서 첫 calibration OOS 연도 2019를 만드는 fold는 2020이며, 학습은 2017년, early stop은 2018년, final refit은 2017~2018년이다. 따라서 feature/label 행은 2019년 점수를 OOS로 재현할 만큼 존재한다. 2017~2018년은 recipe-valid prior refit OOS calibration score가 없어 pair H1에서 제외한다.

없는 score family를 만드는 데 필요한 최소 fold는 네 개뿐이다.

| Provider fold | Calibration score year | Frozen refit max | First score-year race | Date gap |
|---:|---:|---|---|---:|
| 2020 | 2019 | 2018-12-29 | 2019-01-11 | 13 days |
| 2021 | 2020 | 2019-12-28 | 2020-01-03 | 6 days |
| 2022 | 2021 | 2020-12-20 | 2021-01-08 | 19 days |
| 2023 | 2022 | 2021-12-25 | 2022-01-07 | 13 days |

이 날짜는 frozen feature table의 calendar range와 지정된 base recipe에서 계산한 역사 경계다. 실제 refit 결과가 생긴 후에는 각 model metadata `refit_max`와 score row 전체 race date를 기준으로 T−2 검사를 다시 수행한다. 첫 score race만 확인해 전체 행의 시점 적합성을 대신하지 않는다.

## 확장 H1의 예상 row scope

기존 direct plan의 직전연도 H1/H2 counts는 각각 312/336 (2024), 326/311 (2025), 329/325 (2026)이었다. H2와 evaluation은 그대로 둔다. feature date inventory에서 H1의 `first-H2-race-date minus 2 days` cutoff를 적용했을 때 expanding H1의 사전 예상은 다음과 같다. 새 historical scores를 만들지 않았으므로 2019~2022 행의 score coverage는 미확인이고, 최종 preflight에서 점수 key와 완전 roster로 다시 확인해야 한다.

| Pair fold | H1 race count by component year | H1 total / dates | Existing H1 subset |
|---:|---|---:|---:|
| 2024 | 2019:576 + 2020:329 + 2021:418 + 2022:512 + 2023 H1:312 | 2,147 / 361 | 312 / 47 dates |
| 2025 | 2019–2022:1,835 + 2023:657 + 2024 H1:326 | 2,818 / 462 | 326 / 50 dates |
| 2026 | 2019–2022:1,835 + 2023:657 + 2024:637 + 2025 H1:329 | 3,458 / 560 | 329 / 50 dates |

Known H2/current evaluation supports are 2024 fold 336 H2 races/50 dates and 637 evaluation races/98 dates; 2025 fold 311/48 and 654/98; 2026 fold 325/48 and 488/73. The date counts were recomputed from feature race dates and current saved calibration-year keys. The 2019–2025 historical source review confirmed full-finishing roster/rank arithmetic and style-lineage status. The maximum `field_n` in expanded H1 is 13; pair preflight must enumerate all `C(N,2)` pairs and must not impose an implicit `N<=10` assumption.

## OOS provenance/dedup contract

For each calibration-year race `c`, the one selected provider is fold `c+1`, role `calibration`. For each fixed evaluation-year race `Y`, the one selected provider is fold `Y`, role `evaluation`. A race/provider mapping must have one provider fold/role; runner-grain rows key on `(api_record_id, score_provider_fold_year, score_provider_role)` and after target selection on `(pair_evaluation_year, split_role, api_record_id)`. Target pair fold and H1/H2/EVAL role are separate keys. No two score roles are collapsed by `api_record_id` alone. Within each pair-fold split, every runner receives one and only one score; H1's full previous years and current Jan–Jun segment form a single chronological table, and H2 and EVAL are disjoint by race date.

The base feature file is the only labels/inputs table for historical score fitting. The 2024–2026 saved model scores remain pinned as current direct-model reference. The historic feature table's style lineage and source cache may be read to verify the original time contract, but they are not re-engineered or used to rescore 2024–2026. `outputs/date_bootstrap_schedule.npy` and the pair references from the completed direct study are immutable read-only comparators.

## Frozen reference identities

The completed direct pair study pins the relevant feature, score, and comparator source hashes in `20261011_pair_top3_direct_v1/PREFLIGHT_SOURCE_LOCK.json`. The exact direct model/plan source hashes are recorded in its `ARTIFACT_MANIFEST.json`; the evaluation result artifact is `outputs/REPORT.json`. The bootstrap schedule hash is `d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd` and the prior pair predictions hash is `a8db4d50646b01e009acdf33cfa458840e804a7fb4c26b6387939e12dabbbfa8`. Future preflight must rehash every consumed source rather than trust this inventory text alone.

