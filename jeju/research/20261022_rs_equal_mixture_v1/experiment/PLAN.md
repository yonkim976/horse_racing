# R/S 50:50 full Top-3 공동분포 혼합

상태: **구현·합성검사·구조 사전검사만 허용. 실데이터 혼합분포와 성과 계산은 감독관의 hash-bound 1회 승인 전 금지.** 설계 기준은 `supervisor/DESIGN_CONTRACT.md` SHA-256 `e3cd97f4c2081e23dc077bf20641e5012e39ece3a396b11fd6838bef971e13a8`이다.

## 단일 후보와 비교

평가연도별로 이미 고정된 raw runner score와 positive PL temperature를 각각 적용해 R/S의 full-field ordered Top-3 공동분포를 만든다. 새 후보는 오직 `Q_E(i,j,k) = 0.5 Q_R(i,j,k) + 0.5 Q_S(i,j,k)`이다. 각 Q는 먼저 자체적으로 전체 ordered triples에 정규화한다. score, temperature, 선택 tickets 또는 일부 event 확률을 평균하거나 재정규화하지 않는다. 모든 경주에서 weight는 정확히 0.5이며 학습·보정·weight search는 각각 0회다.

주 비교는 E−S, 보호 비교는 E−R이다. 두 비교 각각 TRI categorical NLL 날짜 bootstrap 95% 상한<0, TRI Brier 차이<=0, WIN NLL/Brier 차이<=0를 요구한다. 모든 7승식 손실과 연도별 값을 보고한다. R/S가 이미 평가에 사용된 개발기간이므로 결과는 독립 미래검증이 아니다.

## 고정 원천과 기간

회고 정답·명단은 F1_STYLE6 frozen feature table `jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet` (SHA-256 `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f`)의 키·최종 순위를 참조한다. R의 연도별 score는 같은 연구의 raw `F1_STYLE6_{2024,2025,2026}/evaluation_scores.parquet`를 쓴다. 해당 score hash는 2024 `b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60`, 2025 `45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12`, 2026 `0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a`이며 frozen `ARTIFACT_MANIFEST.json` SHA-256은 `6afc0e8f73ec086052fad4cde4d7edcd62fdf1bbc782108da89732dc3a5b4a4e`다. R 온도는 기존 동적 PL 연구 parameter reference의 2024/25/26 값 `1.2378241690081193 / 1.2652561077417601 / 1.11598418811972`를 고정 재사용한다.

S는 `jeju/research/20261022_tb_state_transfer_v1/experiment/outputs/candidate_oos_scores.parquet`에서 `arm == S, role == evaluation`만 읽고 그 연구의 arm=S annual `temperature_fit.temperature`를 재사용한다. Score table SHA-256 `fe08bdf93b07f8a180ad02416cbbc1488db282c761564b67b886114ece56f6e9`, parameter SHA-256 `46fda546b2a537373291c83190ef7c6f00ffda94fccebcf9090c6f01dfc9c23e`; S temperatures: 2024 `1.2839358195588775`, 2025 `1.323027519896799`, 2026 `1.165540100038154`. R temperature source parameter SHA-256 `28da20c16c65450c024b07a4a12b916e88eaf8b9d16b8fdc66e1a6e582934dff`. The asset audit and runtime preflight also pin both prior `FINAL_MANIFEST.json` files, source artifacts, frozen rules, and bootstrap schedule/receipt.

Evaluation is the unchanged cohort 2024-01-01 through 2026-09-19: 1,779 races, 17,412 runners, 269 dates, year counts 637/654/488. PLC has 1,743 rows: 36 actual N=7 races are excluded only from PLC because sales-opening roster is unknown. The other six pools have 1,779 races each. Rules, ties, cancellation and roster handling follow the frozen rules contract `jeju/research/20261022_joint_wager_baseline_v1/rules_contract/rules_contract.json` (SHA-256 `20cd4b17274018a36efbb1b0cea64eb5d5c9809ed5f3481bea59c734f99fee83`). No market-price/ROI reconstruction is performed.

## 계산·저장

The hash-pinned pure probability/event helpers in `20261022_dynamic_ability_pace_v1/experiment/dynamic_ability_pace.py` (SHA-256 `706b2e94a6b311e5bd9b3706da7df4f6a08117e917d22171fbde63a4d1a3210c`) may be loaded read-only under `-B`; their source tree is checked before/after. Q is constructed one race at a time and never persisted. Pool event probabilities are sums over E's Q; overlapping PLC/QPL event maps are not normalized.

New E-only outputs retain compact, reviewable ledgers: `race_pool_metrics.parquet`, `selected_ticket_ledger.parquet`, `evaluation_runner_marginals.parquet`, `win_axis_ledger.parquet`, `pair_selection_diagnostics.parquet`, `reliability_bins.parquet`, plus a small paired `pool_summary.parquet`, `comparison_bootstrap_draws.parquet`, `report.json`, and run receipt. QNL/QPL k=1/3 pair selected sets are evaluated by a second streaming pass over R/S triples; the exact union probability and hit-count PMF 0..3 are retained. Selection tolerance is 1e-12 with horse-number lexicographic tie-break. It is never used in probability or loss calculations. Reliability uses fixed 16 bins and pooled ticket-event weighting, separately by ALL/year. EPS is 1e-15. Bootstrap uses the frozen 2,000×269 date schedule and sorted evaluation-date roster.

The source preflight may inspect only pinned input hashes, schemas, provider metadata, keys, dates, labels/roster integrity, existing R/S reference-ledger keys, legal denominators, and bootstrap metadata. It must not construct E, evaluate Q, or compute E probability/performance quantities. `--run` requires `supervisor/EXECUTION_APPROVAL.json` with `status=PASS`, `scope=evaluate_fixed_mixture`, and `run_count=1`, bound to the final code/PLAN/source-preflight hashes; it refuses any pre-existing E output or execution claim. Its first action is an exclusive single-run claim, so a partial/failed run cannot be repeated. The full experiment remains below 25,000,000 bytes; no source/model/DB/Q copying is allowed.
