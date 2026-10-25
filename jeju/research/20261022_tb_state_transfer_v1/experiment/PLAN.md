# 제주 TB 상대능력 상태 전이 비교

이 계획은 `../supervisor/DESIGN_CONTRACT.md`의 고정 R/C/S 비교를 구현한다. 적합 및 실제 결과 평가는 승인 receipt가 현재 코드·입력·참조 해시에 일치하기 전까지 실행하지 않는다. 기존 연구·모델·DB·운영 파일은 읽기 전용이다. 새로 쓰는 파일은 이 `experiment/` 아래에만 둔다.

## 비교와 학습

- **R**: 저장된 F1_STYLE6 raw score를 이전 동적 능력·전개 연구가 검증한 연간 PL temperature와 결합한다. 저장된 raw 점수, 온도, 모델 provider와 source key를 해시로 검증한다.
- **C**: 원래의 동일 30개 입력을 사용한 binary Top3 LightGBM 대조군. **S**: 같은 입력과 추가한 정확히 10개의 상대순위·거리 상태 입력. S는 40개 입력이다. C/S는 나머지 모든 파라미터와 표본을 공유한다.
- 연도 Y=2024, 2025, 2026마다 초기학습 2017..Y−3, 조기종료 검증 Y−2, 선택된 반복 수로 2017..Y−2 재학습, Y−1 raw score로 보정, Y 평가. 범주 어휘는 초기학습만으로 정하고 refit에도 고정한다.
- C/S는 LightGBM binary logloss, 출전마별 `1/field_n` 가중치, seed 20261008, learning rate .04, leaves 15, `min_data_in_leaf=100`, `lambda_l2=5`, deterministic/column-wise, 4 threads, 최대 800회와 early stopping 25회를 쓴다. 각 arm은 세 개의 최종 모델, 초기+refit 6회 적합과 세 개의 PL 온도 최적화를 수행한다.
- C/S의 positive scalar temperature는 같은 arm의 Y−1 OOS 점수에서 전체 순차 PL Top3 joint NLL을 최소화하여 `[0.35,4]`에서 정한다. R의 이전 온도를 재사용하되 목적·입력 해시를 검증한다. 어느 arm에도 같은 평가연도 점수로 온도를 맞추지 않는다.

## 시점 및 입력

기존 `jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet`는 30개 F1_STYLE6 열과 키·라벨만 read-only로 읽으며 복사하지 않는다. `inputs/state_features.parquet`는 같은 52,155개 target row 키와 계약의 10개 상태열이어야 한다. 각 상태 cutoff는 해당 race date의 T−2와 일치하고 latest history date는 cutoff 이하이어야 한다. Join은 공식 `api_record_id` 및 race/date/cutoff 키로 1:1을 확인한다. State lineage는 validation 전용이며 학습 입력에 포함하지 않는다.

상태와 레이스 입력은 전원 정상 완주, 양의 유한 기록, N≥4, 정확한 `1..N` 순위인 과거 이력만 반영한다. 현재 경주·미래 경주·동일 날짜의 다른 경주 결과를 입력하지 않는다. Supervised population은 기존 5,206경주와 평가 1,779경주 / 17,412두 / 269일 그대로 둔다.

## 확률 및 판정

세 arm 모두 같은 full-field sequential Plackett–Luce ordered Top3 joint `Q`를 사용한다. 모든 풀 확률과 말별 승/정확2·3/Top2·3 주변확률은 경주별로 Q를 streaming하여 산출하며 전체 Q는 저장하지 않는다. 공식 legal minimum과 PLC 개시두수 분모는 봉인된 rules contract 그대로 적용한다. R/QNL/QPL/EXA/TLA/TRI/PLC 모두 연도별·전체 proper loss와 fixed-bin reliability를 낸다.

주 비교는 S−C, 보호 비교는 S−R이고 C−R은 학습량 설명용이다. S가 S−C 및 S−R 모두에서 기존 계약의 TRI NLL paired date bootstrap 상한 `<0`, TRI Brier `≤0`, WIN NLL/Brier `≤0` 조건을 만족할 때만 연구 후보 게이트를 통과한다. 이 자료는 반복 사용 개발 자료이며 결과는 운영 채택 근거가 아니다. WIN 축의 Top3 적중은 보조이며 기준 R의 1,023회와 상대 10% 목표 1,126회를 함께 보고한다.

QNL/QPL에서는 최대확률 1장과 주변확률 상위 3장을 동일한 수치 tie tolerance `1e-12` 및 마번 사전순으로 선택한다. QPL 세 장 중 적중한 수의 0..3 분포와 정확 합집합 적중확률은 full Q의 ordered triples를 스트리밍해 계산하고, 동일 날짜 bootstrap으로 비교한다. 이 선택 규칙은 확률 계산·정규화에 적용하지 않는다.

## 검증·보관

Synthetic checks는 TB 상태식의 쌍별 갱신·동시 commit·휴양 전파, history cutoff 및 query 불변성, PL 온도와 event-mass/marginal identities, legal minima, selected-ticket exact-union/count distribution을 검사한다. Structural preflight는 source/input/R references, exact keys/cutoffs, annual folds, fixed rule/bootstrap assets와 output confinement을 검사하되 후보 모델을 fit하거나 실제 확률/결과 metric을 만들지 않는다.

성공 run은 C/S model text, OOS raw score table, 온도·tree metadata, compact event/selection/marginal/reliability/bootstrap tables, report와 해시·실행 receipt를 보존한다. 기존 raw features, score sources, DB, full race Q는 복사하지 않는다. Study 총량은 100,000,000 bytes 이하여야 하며 기존 실험 결과는 덮어쓰지 않는다.
