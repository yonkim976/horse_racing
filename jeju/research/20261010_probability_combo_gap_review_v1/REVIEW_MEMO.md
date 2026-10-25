# F1_STYLE6 주변 확률과 최대 6조합 적중 간격: 사전 독립 검토

검토일: 2026-10-10  
상태: 기존 보고서·계약·평가 코드를 읽은 사전 검토. 새 결과 통계는 계산하지 않았다.

## 질문과 범위

검토 질문은 F1_STYLE6의 Top3 말별 확률 손실이 F1보다 좋아졌다는 기존 보고가 canonical 최대 6조합 적중으로 같은 폭만큼 이어지지 않은 이유를 저장된 점수에서 분해할 수 있는가이다. 입력은 `20261010_style_history_ablation_v1`의 잠긴 F1 재현 점수와 F1_STYLE6 점수, 각 연도 메타의 저장 tau, 해당 연구의 입력·출처 잠금이다. 대상 코호트는 기존 계약의 2024~2026-09-19 후향 코호트 1,779경주·17,412출전·269경주일이다.

이 메모는 기존 산출물의 재산출물이 아니다. FINAL_RESULTS.md의 수치는 기존 보고가 제시한 값으로만 인용하며 독립 확인한 통계로 제시하지 않는다. 모델 재학습, tau 재최적화, 외부 수집, DB·운영 모델·등록부 변경은 범위에 넣지 않는다.

## 기존 코드에서 확인한 평가 계약

1. 평가 경주마다 말별 raw score를 사용해 가능한 무순서 3두 조합 `C(N,3)` 전체를 만들고 조합 에너지를 세 score의 합으로 계산한다. 연도별 저장 tau를 적용해 전체 조합에 걸쳐 `q(S) = exp(E(S)/tau) / sum_T exp(E(T)/tau)`로 정규화한다. 따라서 정규화 범위는 여섯 장이나 상위 일부가 아니라 그 경주의 전체 가능한 조합이다.
2. 말별 `p_top3`는 전체 조합 분포의 포함 주변확률 `p_i = sum_{S: i in S} q(S)`다. 한 경주에서 주변확률 합은 3이고 조합확률 합은 1이다. 기존 log loss와 Brier는 말별 Top3 포함 표지에 대한 경주 내 평균 손실이다.
3. 정답은 최종순위 1~3위의 무순서 집합이다. canonical six는 `E(S)`가 큰 조합 여섯 개다. tau가 양수이므로 `E` 순서와 `q` 순서는 같다. 저장된 기존 정의상 최대6 적중은 정답 집합이 이 여섯 조합 가운데 하나인지 나타낸다.
4. 입력 행은 마번 오름차순으로 정렬된다. 조합 생성은 이 행 순서의 `itertools.combinations`이고, 에너지 동점은 stable 내림차순 정렬로 원래 조합 순서를 보존한다. 따라서 완전 동점에서는 마번 오름차순 조합 열거 순서가 우선한다. 최고점 말 동점도 stable sort에 따라 마번 오름차순 행을 보존한다.
5. 저장 tau는 calibration 기간의 전체 3두 집합 NLL을 최소화하도록 연도별로 정해진다. report 단계는 저장 점수와 tau를 평가기에 전달하고 재학습·재보정을 하지 않는다. 기존 report는 모델별 score와 p_top3를 함께 보관한다.

가산 3두 분포에서 양수 tau는 점수에 대한 양의 단조 변환을 조합 에너지에 적용하므로 canonical six의 순위와 hit를 바꾸지 않는다. 또한 `w_i = exp(score_i/tau)`라 놓으면 고정 크기 3두 부분집합 분포의 주변확률은 `p_i = w_i e_2(w_{-i}) / e_3(w)`다. 임의의 두 말 i,j에 대해

`p_i - p_j = (w_i - w_j) e_2(w_{-{i,j}}) / e_3(w)`

이므로 필드가 4두 이상일 때 주변확률 순서는 score 순서와 같다. 3두만 있는 경주에서는 모두가 Top3이므로 주변확률이 전부 1이다. 같은 점수 동점은 같은 주변확률이어야 하며, 계산 정밀도 때문에 생기는 표시상의 미세 차이는 별도 확인 대상이다. 따라서 tau 변화는 확률의 크기와 공동 손실·여섯 조합 질량에는 영향을 주지만 조합 순위나 이론상 runner 순위는 바꾸지 않는다.

## 독립 검토에서 확인된 제한

기본 `20261010_style_history_ablation_v1/verify.py`는 후보 점수를 모델에서 다시 계산해 저장 점수와 대조하지만, 후보·기준선 확률 및 canonical 조합을 재생성할 때 `OLD.evaluate`를 다시 호출한다. 다만 독립 검증이 없었다고 결론 내리면 안 된다. 별도 `20261010_style_history_review_v1/verify_style6_postfit.py`는 F1/F1_STYLE6 저장 모델 6개를 재로딩하고 `eval_race()`를 자체 구현해 full joint, 주변확률, canonical six, race metric 및 날짜 bootstrap을 다시 계산했다. 그 독립 검증 receipt는 PASS이며 17,412 출전·1,779경주·269일, 확률 합, 보고서 대조, CI 일치를 기록한다. 이는 이전 F1_STYLE6 결과의 독립 확인 근거다. 이번 gap 연구에서는 새로운 원인분해 표가 추가되므로 해당 script나 `OLD.evaluate` 또는 A 작업 helper에 의존하지 않고 잠긴 저장 raw score에서 진단을 새로 계산해 서로 대조한다.

기존 평가기 `parts()`와 이전 별도 검증기 `eval_race()` 모두 정렬된 세 점수에 `sum(axis=1)`을 적용한다. 이 둘은 별도 구현이지만 동일한 NumPy reduction 표현을 사용한다. 이전 계약 및 verifier의 일부 코드 경로는 `(s0+s1)+s2`를 명시한다. 길이 3의 합은 통상 같은 결과여도 정확한 부동소수점 동점과 cutoff 경계 조합의 선택은 결과에 직접 영향을 준다. 독립 산출은 계약상 덧셈 순서를 고정하고, 이전 independent receipt 및 원 evaluator의 저장 조합과 차이를 대조하되 근접 동점도 진단 표에 남겨야 한다. 재계산에서 달라지는 표가 있으면 성능 해석 전에 먼저 해결한다.

기존 주 log loss/Brier는 출전마별 Top3 포함 주변사건을 평가한다. 정확한 세두 집합이 얼마나 좋은지는 해당 조합의 full-joint 확률을 평가하는 NLL 및 categorical Brier가 직접 다룬다. 주변 손실 개선만으로 exact-set 순위 또는 여섯 장에 든 정답 수의 개선을 보장하지 않는다. 이는 현재 자료에서 확인된 원인 판정이 아니라 평가목표 간 수학적 차이다.

## 승인 후 독립 재산출 제안

PLAN이 승인되면 같은 저장 파일을 입력으로 아래 절차를 고정한다.

1. F1과 F1_STYLE6 저장 점수를 `year, api_record_id` 키로 결합한다. race·horse 키, 마번 정렬, 저장된 연도별 tau, 정답 세두 집합, 17,412개 출전·1,779개 경주·269개 경주일 커버리지를 확인한다. score와 tau를 새로 맞추지 않는다.
2. 각각의 경주에 대해 전체 `C(N,3)` 에너지와 정규화 `q`, `p_top3`, true-set rank/NLL, canonical top6와 top6 mass를 독립 계산한다. 확률합·주변합·점수/주변 순서·score/tau=1일 때 순위 불변을 검증하고 저장된 report 파일과 비교한다.
3. F1/F1_STYLE6의 true-set 전체 joint NLL 및 정의를 명시한 categorical Brier, 주변 Top3 손실, top6 mass와 hit indicator의 신뢰도·Brier를 나란히 비교한다. 여섯 장의 적중률과 선택된 여섯 조합 확률질량은 별도 항목으로 보고한다.
4. 경주별 top6 조합 집합이 동일한지, 들어오고 빠진 ticket이 있는지, 정답이 F1 전용·STYLE6 전용·둘 다 적중·둘 다 실패 어느 경우인지 나눈다. 각 모델별 선택 여섯 ticket에 등장한 말 ID의 합집합 `U6`도 만든다. 실제 상위 세두가 `U6`에 모두 있지 않으면 `outside-U6 miss`, 모두 있지만 해당 세두 조합이 선택 여섯 ticket에 없으면 `inside-U6 allocation miss`, 해당 조합이 선택됐으면 `hit`으로 분류한다. 이 3범주는 모델별로 모든 경주를 분할한다. 여섯 번째/일곱 번째 조합 에너지 차이와 정답 조합 에너지 순위를 보존한다.
5. 주변 손실 변화와 ticket 변화를 교차한다. paired race의 log loss 및 Brier 각각에서 `delta = STYLE6 − F1`를 계산하고 `delta < -1e-12`는 개선, `|delta| <= 1e-12`는 동률, `delta > 1e-12`는 악화로 고정 분류한다. 각 구간에서 top6 집합 불변·교체, 두 모델의 적중 방향, 모델별 `U6` 분해를 집계한다. 신뢰구간은 날짜 단위 paired bootstrap으로 계산한다.
6. 저장 tau와 고정 tau=1을 분리 비교한다. tau=1에서는 확률 크기, joint NLL/Brier 및 top6 mass만 재평가하고, top6 구성·hit이 저장 tau와 같음을 확인한다. tau의 사후 최적화는 하지 않는다.

`top5_all3`는 고정된 top5 안에 정답 세 마리가 모두 있는 사건이다. top6 ticket은 top5 말만으로 구성된 조합으로 제한되지 않으므로 이 값은 canonical six-hit의 엄밀한 상한이 아니다. 특정 새 조합 선택 정책도 저장 분포에서 선택한 여섯 장보다 그 분포의 기대 hit을 자동으로 높일 수는 없다. 정책을 바꾸는 비교가 필요하면 별도 학습·다중비교·사전등록 문제가 되므로 이번 저장점수 진단과 혼합하지 않는다.

## 입력 무결성과 수행 경계

기존 `prepared_lock.json`은 연구 코드·입력·출처 cache·결과 artifact 해시를 기록하고, DB·운영 등록부·현재 모델 해시를 보호 대상으로 잠근다. 기존 report와 final verification은 이 잠금 검사를 포함한다. 새 검토 스크립트는 동일한 잠금 파일을 읽기 전용으로 검증하고, 결과는 이 독립 검토 디렉터리에만 쓴다. score는 불투명한 저장값으로 취급하고 네트워크나 DB를 조회하지 않는다.

코드 보안 지침의 파일 경로 규칙을 확인했다. 검토한 report/run 경로는 작업 디렉터리와 계약으로 정한 상수 경로를 사용하고 사용자 제공 경로를 파일명에 결합하지 않는다. 이번 검토에서는 파일 입출력 취약점 징후를 찾지 못했다. 본 검토의 핵심은 성능평가 정확성과 분포 정의다.

## 근거 파일

- `jeju/research/20261010_style_history_ablation_v1/FINAL_RESULTS.md`
- `jeju/research/20261010_style_history_ablation_v1/CONTRACT.md`
- `jeju/research/20261010_style_history_ablation_v1/README.md`
- `jeju/research/20261010_style_history_ablation_v1/outputs/report/report_receipt.json`
- `jeju/research/20261010_style_history_ablation_v1/outputs/final_verification.json`
- `jeju/research/20261010_style_history_ablation_v1/outputs/prepared_lock.json`
- `jeju/research/20261010_style_history_ablation_v1/report.py`, `run.py`, `verify.py`
- `jeju/research/20261010_style_history_review_v1/verify_style6_postfit.py`, `style6_postfit_independent_receipt.json`
- `jeju/research/20261009_finish_history_ablation_v1/verify.py`
- `jeju/research/20261008_horse_profile_baseline_v1/run.py`
