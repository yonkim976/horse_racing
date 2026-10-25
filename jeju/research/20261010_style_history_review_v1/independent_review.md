# 독립 검토 메모 — 과거 전개 위치 이력 F1 추가 비교

상태: 원천 cache와 F1_STYLE6 사전 입력 검증은 독립 PASS했고, root의 조건부 fit 승인이 발효된 뒤 후보 3개 모형을 학습했다. 저장 F1·STYLE6 모형, calibration/evaluation 점수, 공동·주변 확률, canonical 6조합, 평가 지표·paired CI·공통 467경주를 독립 재계산해 저장 결과와 일치함을 확인했다. 고정 cohort에서 7개 target row perturb도 24/30 입력·점수·확률·canonical 6조합 불변 PASS다. 중앙 결론의 별도 발행 내역은 [publication receipt](central_publication_receipt.json)에 기록한다.

## 사전 계약 검토

- F1 모집단·2017-01-13~2026-09-19 범위, 평가 2024~2026(17,412행·1,779경주·269일), T−2 및 제외 ID 3005648을 기존 F1과 동일하게 고정해야 한다. 실제 동일거리 최근 최대 5개 출전 슬롯을 공식 출전 ID와 말 ID로 연결하고, 날짜·거리는 과거 경주의 값으로 확인한다.
- 상대 위치는 API4 말별 품질 선택 통과착순에 기반한 후향 측정이다. API303 통과조는 별도 경주 단위 군집 원천이다. 괄호 안 군집 순서를 개별 말 순위로 바꾸거나 두 원천을 같은 측정으로 합치면 안 된다.
- 각 point의 rank를 `r=(rank−1)/(N−1)`로 변환하려면 과거 경주의 actual-started horse ID 집합과 해당 point의 선택 rank 집합이 완전하게 일치하고, rank 값이 정확히 `1..N`의 유일한 순열이어야 한다. 값이 모두 정수·범위 안인지 확인하는 것만으로 중복·누락을 막지 못한다. 한 point에서 이 조건이 실패하면 그 point의 모든 horse rank와 그 point를 포함하는 paired change를 NULL로 둔다.
- finish를 후보 입력에 쓰지 않고 G1F rank로 끝나는 묶음은 F1의 최근 착순 정보와 직접 중복되는 정도를 낮춘다. 다만 G1F는 결승에 가까운 측정점이므로 결과와의 상관이 가능하며, 이를 결과와 독립된 스타일이나 순수 인과 효과로 설명해서는 안 된다.
- S1F·4C·G1F 순서를 전 거리의 보편적인 거리·물리 위치로 가정하지 않는다. 정확 거리별 point chronology와 해당 거리의 선택 rank 지원을 확인한다. 특히 1300m의 출발→2C→S1F 정정 계약을 보존한다. S1F는 원천 필드명으로만 사용하고 200m/210m로 환산하지 않는다.
- `conflict`, `not_applied`, `source_changed`, 선택 상태 누락·미분류는 영향을 받는 point의 값과 거기에서 파생한 paired change를 fail-closed 처리한다. `api_group_unavailable`는 API303 군집 부재라는 별도 상태다. 이 cohort에서는 관측되지 않았지만, 계약은 full API4 permutation이 독립적으로 완결되고 허용 status일 때만 이 group 상태를 허용한다. known conflict와 absent/unknown metadata는 fail-closed다.
- 과거 history finish 결과는 현재 경주일의 한국 기준 T−2일까지(그 날짜 포함) 입력에 허용된 이력이다. 4C→G1F 선택 이유는 누수 회피가 아니라 새 전개 묶음의 증분 효과에 최근 평균 착순 정보를 함께 추가하지 않기 위한 해석 범위 조정이다.

2026-10-10 최종 CONTRACT/PLAN은 이 6열 구성과 고정 모집단을 반영했다. Source audit은 status allowlist, point 완결성, 거리별 지원과 시간 순서 검사를 고정했고, prepare/cache와 saved F1 replay 사전 검증도 통과했다. 6개 열은 S1F/4C/G1F 통과 위치로 구성하고 finish 착순 평균은 별도 추가하지 않는다. 같은 유효 슬롯에서 평균 G1F 상대위치를 재구성할 수 있으므로 이 묶음의 성능은 순수 전술 효과나 독립적인 위치 변화 효과로 해석할 수 없다.

### Full roster 분모 독립 대조와 정정

초기 대조에서 source snapshot을 최근5 슬롯의 50,491개 참조 API ID로 먼저 좁힌 뒤 그 부분집합을 경주 편성으로 세어 4,314개 부분 경주라고 잘못 판단했다. 이 결과와 거기서 파생한 예시·연도별 수치는 모두 취소한다. 전체 `source_snapshot` 행을 참조 `race_id`별로 모은 뒤 full `race_result_rows`와 대조해야 한다. 이 정정된 방식에서는 6,269개 과거 이력 경주키의 전체 snapshot/full row가 62,709/62,709개, 같은 inherited started 규칙(착순 1..89 또는 91/92)의 starter row가 62,248/62,248개였고, source snapshot과 full table의 경주별 starter ID 집합·N이 모두 일치했다. 모든 snapshot 원행의 key, ID, horse ID·마번, 거리, finish position도 base 행과 같았다. full starter에서 ID·horse ID·마번 NULL 및 경주별 중복은 모두 0건이다. `2017-01-13_2_1`도 snapshot과 full DB 양쪽에 10 starters가 있다. 전체 DB와 snapshot의 전체 row count 차이만으로 개별 referenced race의 roster가 불완전하다고 결론내릴 수 없다. 수치와 방법은 [roster reconciliation receipt](roster_reconciliation_receipt.json)에 기록했다.

별도로 F1 `previous_start` lineage 50,209개 target row(49,464개는 `previous_finish_relative_rank` 비NULL), 5,901개 고유 과거 경주를 같은 방식으로 대조했다. 이 5,901개 source event의 snapshot/full rows는 59,089/59,089, starters는 58,648/58,648이다. 모든 full N과 snapshot N, started API ID 집합 및 비교 row fields가 일치했으며, 따라서 full N이 커져 F1 상대착순 분모가 달라지는 기존 target 노출은 0건이다. F1 현재 cohort 5,206개 경주·52,155행도 target feature ID 집합이 full started roster와 5,206/5,206 경주에서 정확히 일치했다. `field_n`은 full started N과 5,206/5,206에서 같고, full DB에서 누락된 target starter·target에 없는 추가 starter·추가 Top3 runner는 각각 0명이다. 5,206개 full target race 모두 inherited started 착순이 1..N 완결 순열이었다. 조회는 `mode=ro`, `PRAGMA query_only=ON`의 parameterized `race_result_rows` key lookup으로 수행했으며 DB는 쓰지 않았다. 이 범위에서 roster 분모 발견은 기존 F1의 이전 착순 입력이나 고정 target cohort 문제로 이어지지 않는다.

### Source audit와 cache 독립 검증

최종 source audit은 전체 DB의 1.79 GB 파일 SHA를 재계산해 기존 lock과 맞추었으며, SQLite는 `mode=ro`, `query_only=ON`으로 열었다. 전체 quality view는 반복 실행하지 않았고 해당 6,269개 이력 경주에 대해서만 API4/API303/time quality constituent를 parameterized lookup했다. 독립 검산 스크립트 [verify_source_cache.py](verify_source_cache.py)는 cache·receipt의 크기와 SHA, 모든 race-point 그룹 및 slot arithmetic을 따로 확인했다.

6,269개 source race에서 full `race_result_rows` starter 62,248명과 full source snapshot의 started ID 집합·N이 경주별로 모두 같고, NULL/경주 내 중복 API ID·horse ID·horse number는 0건이다. 18,807개 `(race, point)` 그룹에서 API4 permutation flag가 경주별 균일하고, accepted status와 순위 `1..N`의 정확한 유일 순열이 함께 성립할 때만 API4 통과로 처리한다. API303 group status는 독립 gate이며 race-point 통과는 두 gate의 conjunction이다. 정규화 rank도 `(order−1)/(N−1)`와 전수 일치했다. point 지원은 S1F 6,243 race, 4C 6,242, G1F 6,241이며 178,459 actual slots에서 valid-time S1F/ S1F→4C / 4C→G1F 관측은 각각 177,688 / 177,450 / 177,498개다. source ID·말·거리·시작 상태·T−2 cutoff, no-backfill slot 순서와 transition 차분도 전부 대조했다.

DB constituent 직접 spot check는 정상 API4 `121064/sjS1fOrd=8`, 홈페이지 정정 `180753/sjS1fOrd=7`, 미해결 개별순위 conflict `117231/sjG1fOrd=NULL`, API303 `2016-09-23_2_1/G1F` conflict를 선택했다. 각각 원천 quality-value와 cache가 일치했고 보류값은 정규화 rank가 NULL이다. 이 history cohort에서 `api_group_unavailable`, review-not-applied, source-changed 상태는 관측되지 않았다. 관측된 17개 API303 conflict race-point는 모두 API4 permutation도 실패했으므로, 실제 표본에는 group gate만으로 hold되는 사례가 없다는 점을 함께 기록한다. conflict/invalid이 아닌 허용 group 상태의 API4 정상 순위는 그대로 개별순위 기반으로 보존한다.

### 후보 preflight 코드와 결과 독립 검토

현재 source cache의 race-point roster/permutation 검사, API4와 API303 gate 분리, `valid_time` 기여조건, pair conjunction과 derived NULL lineage를 확인했다. `valid_time=False`이면 raw point rank는 진단용으로 남을 수 있지만 해당 slot의 mean contribution은 NULL이고 평균·n에 포함되지 않는다. Exact F1 last5 ID 순서, official horse ID·동일거리·실제 시작 상태와 `history_cutoff = target race date − 2 days`도 확인했다. 저장 feature table은 52,155행·5,206경주이며 모든 기존 F1 49열을 exact 비교로 보존하고 6열만 추가했다. 독립적으로 slot cache의 eligible value와 n을 groupby해 각 target의 6개 새 값을 재계산했으며 모두 일치했다. 178,459개 lineage slot 키도 cache와 일치한다.

사전 lock은 SHA `f110b33b0442e519fd3f9852098aa847af90d2228af674c39db4914142675e24`로 고정됐고, 사전 cache/feature/lineage 검증과 A의 `verify_prepared()`가 각각 PASS였다. fit 전에 후보 fit 0회·tau optimization 0회·candidate outcome metrics 미계산을 확인했다. 이후 현재 lock/코드와 prepared 입력을 변경하지 않는 조건으로 root가 세 후보 모형 fit을 승인했다. 독립 사후 검증은 후보 3 models·6 train calls·3 temperature optimizations를 완료 결과에서 확인했고, 사후 verifier의 재학습 0회·tau 재최적화 0회를 확인했다.

### 저장 F1 직접 재생

독립적으로 저장 F1 2024·2025·2026 모형을 reload했다. tree 수는 92/200/200, 각 model/meta SHA 및 24열 feature 계약이 일치했다. 고정 calibration raw scores 6,506/6,329/6,410행은 저장 점수와 각 atol 1e−12로 같았고 저장 tau를 그대로 사용했다. 17,412 test runner·1,779 race·269 race-day·10,674 canonical six-set에 대해 runner score/probability/loss, race metrics, canonical six-set 구성·확률이 저장 F1과 모두 atol 1e−12 내 일치했다. 모든 race joint set 확률 합은 1, 말별 marginal Top3 확률 합은 3이었다. 새 fit, tau 재최적화, candidate 비교는 수행하지 않았다.

### 구간 순서 근거

1300m의 `start→2C→S1F`는 사용자 제공 sequence 계약이며 독립 측정규격 검증과 구별한다. 기존 `20261009_section_time_ablation_v1/CONTRACT.md`는 G3F와 G1F를 겹치는 종반 시간으로 구분하고, G1F 시간을 누적 checkpoint 시각으로 취급하지 않는다. 그러므로 `finish_time−G1F`로 G1F 통과시각을 추정하는 검산은 기존 품질 선택 시간 계약과 맞는다. 이 값은 공식 물리거리 또는 전 거리 측정 위치를 확정하지 않으며, 새 source audit은 품질 선택 시간의 순서 일관성만 거리별로 보고해야 한다.

## 독립 post-fit 검증

별도 read-only 검증기 [verify_style6_postfit.py](verify_style6_postfit.py)를 실행했다. 저장된 F1 3개와 F1_STYLE6 3개 모델을 모두 직접 재적재했다. 각 모델 SHA·트리 수·feature contract를 확인하고 calibration/evaluation raw score를 저장 score와 `atol=1e-12`로 대조했다. STYLE6 고정 τ는 model metadata와 training completion 사이에서 정확히 같고 `[0.35,4.0]` 범위에 있었다. 해당 τ를 그대로 사용해 calibration joint NLL을 계산했으며 optimizer를 호출하지 않았다.

독립적으로 test race별 모든 3두 집합 확률을 계산해 joint 분포 합 1, 말별 Top3 marginal 합 3을 확인했다. Canonical top-6의 horse-number 정렬과 동점 순서, probability, race log loss/Brier, Top5 capture/all3, six-set hit와 mass를 저장 출력에 대조했다. Top6 subset probability mass는 전체 확률 합이 아니라 별도 `six_combo_mass`와 대조했다. 17,412 runner·1,779 race·269 date·10,674 canonical ticket에서 결과가 일치했다. Date bootstrap은 각 group·metric마다 seed `20261008`로 초기화해 2,000회를 재실행했고 CSV round-trip float 오차를 고려해 `atol=1e-12, rtol=0`으로 대조했다. 78 conditional loss rows, 467 common-race summary 및 paired rows도 일치했다.

주 gate의 STYLE6−F1 차이는 log loss `−0.0013091350` (95% CI `−0.0022447617`~`−0.0003556823`), Brier `−0.0004683843` (CI `−0.0008485216`~`−0.0000889270`)로 두 점추정이 개선되고 양쪽 CI 상한이 0 아래였다. 독립 재계산에서도 사전 gate가 PASS했다. 이는 동일한 반복 사용 역사표본에서의 후향 비교이며 독립 미래 성능 검증이나 운영 승격 근거가 아니다. Six-combo hit은 전체 표본에서 `0.562pp` 올랐으나 CI가 0을 포함한다. 연도별 2025·2026 보조 six-set 결과는 하락했다.

공통 467경주 비교에서 세 시스템은 같은 실제 Top3 결과를 사용한다. HY_R_FORM은 native PL 확률을 쓰고 F1 계열은 additive canonical six-set 확률을 쓰므로, likelihood·Brier·Top3 포함 지표 비교는 가능하지만 확률 구성을 구분해야 한다. 입력과 학습 조건도 달라 이 결과를 순수한 6개 style feature의 효과로 해석할 수 없다. HY는 log loss/Brier/six hit `0.555417/0.187645/0.308351`, F1_STYLE6은 `0.572711/0.194720/0.241970`이었다.

7개 target row에서 현재 finish outcome, finish time/valid_time, 선택된 section-time/order rows를 각각 복사본에서만 바꾸고, fixed source snapshot의 실제 시작·동일거리·T−2 window에서 target의 last5 ID를 교란 전후 다시 선택해 확인했다. 0 history, 1 history, 5 slots, 1300m, 실제 API303 conflict, `valid_time=False`이며 no-backfill된 slot, 현재 target이 T−2 cutoff보다 뒤인 사례를 포함했다. 대상 row의 24/30 input matrix, 저장 F1/STYLE6 raw score, joint/marginal probability와 canonical top6 set은 모두 불변이었다. 현재 section quality-value 복사본은 fixed-cache builder에 직접 전달되지 않으므로, 이 결과는 검증된 고정 cohort/소스창 소비 경로의 범위로 한정한다. 가능한 모든 원천-to-cohort 재생성 경로를 증명하지 않으며, 정확히 T−2일인 history source row는 이 cohort에 0건이었다.

## 검토 후 남은 판정

1. 저장 F1 2024·2025·2026 각 모형을 직접 재로딩하고 고정 입력·메타데이터·저장 점수와 대조한다. 2024년은 저장된 tree 수 92를 포함해 모든 모델의 tree 수, 카테고리 어휘, 모델/meta SHA를 확인한다.
2. 저장 모델, fixed τ, probability normalization, canonical top-six와 report outputs는 독립 reload/replay 검증을 통과했다. 더 넓은 독립 미래검증은 별도 자료와 사전 고정 절차가 필요하다.
3. 주 gate는 날짜 paired bootstrap에서 log-loss와 Brier 두 점추정치 개선 및 적어도 한 상한 0 미만 조건을 충족했다. Top5 capture, Top3 전원 포함, six-combo hit와 pick-hit은 보조 지표다. pick_hit은 최고점 말의 Top3 포함 여부이며 운영 승률·ROI가 아니다.
4. 고정 cohort에서 대상 경주의 outcome/time/section/order 교란만 바꾼 row별 불변성 검사를 한다. 이는 제한된 교란 목록의 불변성이지 가능한 모든 미래 정보·cohort 생성 변형에 대한 증명은 아니다.

## 출처 근거와 한계

검토한 기준은 `jeju/AGENTS.md`, `jeju/docs/RESTART_PLAN_20260928.md`, `jeju/review_documents/20261003/CURRENT_STATUS.md`, `jeju/review_documents/20261003/RECHECK_CHECKLIST.md`, `jeju/research/RESEARCH_PUBLICATION_POLICY.md`, `jeju/research/20261009_finish_history_ablation_v1/CONTRACT.md`, `jeju/research/20261009_section_time_ablation_v1/CONTRACT.md`, `jeju/research/20261002_section_passing_audit/README.md`, `jeju/research/20261003_unresolved_section_review/README.md`다.

로컬 SQLite는 `mode=ro`와 `PRAGMA query_only=ON`으로 열었다. Source audit은 전체 quality view를 반복 실행하지 않고 6,269개 history source race에 대해서만 API4/API303/time quality constituent를 parameterized 조회했다. 나의 postfit perturb 검증은 일곱 target ID만 직접 query했다. API4 개별 순위 선택값과 API303 group/status는 별도 view로 유지하며 원문 API 필드나 `_raw`를 이용해 보류를 우회하지 않았다.
