# 확률 조합 gap 진단: 원천·연구설계 감사

검토일: 2026-10-10. 상태: 읽기 전용 설계 감사. 이 폴더는 저장된 F1/`F1_STYLE6` raw score 및 기존 연구계약을 검토해 조합 gap 진단의 범위·비교 가능성·한계를 기록한다. 새 성능 통계, 조합 적중 분해, bootstrap은 계산하지 않았다.

## 판단

저장된 점수의 출처와 확률 구조는 후속 진단의 근거로 사용할 수 있다. 점수는 평가연도별 LightGBM raw logit이다. F1 계열은 경주 안의 모든 무순위 Top3 집합에 세 말 점수 합을 매기고 저장된 양의 τ로 softmax 정규화한다. 말별 Top3 확률은 해당 분포의 inclusion marginal이다. 따라서 저장 확률로 설명할 수 있는 것은 무순위 Top3 집합과 말별 Top3 포함 사건이다. 정확한 착순 순서, 정확한 2·3착 확률, 순서가 있는 승식 확률은 이 구조에서 나오지 않는다.

앞서 확인된 대상은 1,779경주·17,412 출전·269 경주일이며 2026년은 9월 19일까지다. style-history 보고서는 Top3 log loss/Brier 개선과 함께 canonical 최대 6조합 hit의 불확실성, 2025·2026 점추정 하락을 이미 기록했다. 새 진단은 이 저장 점수에서 **모형이 제안한 상위 k joint ticket들의 말 union이 실현 Top3를 덮지 못한 경우**와 **union 안에는 실현 Top3가 있으나 그 조합을 티켓으로 선택하지 않은 경우**를 나누는 분석으로 설계할 수 있다. 이 구조 분석은 말별 확률의 개선·악화와 다른 결과 층위다.

선행 axis-companion 연구도 후보군 포괄 상한과 신규 적중/기존 적중 손실을 이미 다뤘다. 따라서 실패를 후보 miss와 allocation miss로 나누는 일반 아이디어 자체를 새롭다고 주장하지 않는다. 새 진단의 차이는 축을 고정하지 않는 전체 Top3 집합 Q, top-k joint-ticket union, 그리고 F1 대 STYLE6 같은 평가 코호트에서 비교하는 범위다. 자세한 검토와 수학적 귀결은 [1차 검토 메모](REVIEW_MEMO.md)에 남겼다.

## 해석상 꼭 지킬 경계

- raw score와 확률을 혼동하지 않는다. 모델·연도별 τ를 적용한 Q 및 주변확률로 확률 차이를 말한다. 서로 다른 모델의 raw score 크기는 직접 비교하지 않는다.
- 같은 모델·경주 안에서 τ가 양수이면 horse 순위와 canonical set 순위가 유지된다. 보정 전후 선택 조합이 달라졌다는 결과는 동점 순서와 구현을 점검해야 한다.
- 동점 재현은 원 구현을 따른다: horse 행 마번 오름차순, 삼두 score 정렬 후 `(z₁+z₂)+z₃`, set 에너지 내림차순 stable 정렬, 조합 열거 순서 tie-break.
- 진단 k는 사전에 `{1,3,6,10,20}`으로 고정한다. 같은 경주에서 같은 k장의 unordered 조합을 고르는 경우 각 모델이 자기 Q에서 고른 상위 k장은 **그 모델이 부여한** 기대 hit 확률을 최대화한다. 실제 hit 보장은 아니다. 후보 horse union은 모델별로 따로 만들고 pooled union은 쓰지 않는다. k가 다른 hit율은 티켓 수가 달라 직접 모델 우열로 비교하지 않는다. k>6은 이번 진단에서 사전에 고정한 추가 민감도 진단이다.
- Top5 capture 또는 Top5 all-three는 canonical 6 ticket의 상한이 아니다.
- Additive set Q에는 명시적 pair-specific joint interaction이 없다. 같은 경주에서 `Q({i,j,k})/Q({i,j,l}) = exp((z_k−z_l)/τ)`로 제3말 교체 odds는 이미 포함된 i,j에 따라 달라지지 않는다. 말 점수는 경주 맥락을 반영할 수 있고 고정 3두 집합 사건은 의존적이므로 이를 독립 말 확률의 곱이라고 해석하지 않는다. pair 학습은 후속 가설일 뿐 이번 진단의 개선 결과가 아니다.
- HY_R_FORM native Plackett–Luce와 F1 additive set model은 점수가 있는 동일 roster/label에서 Top3 주변확률 손실, 무순위 Top3 집합 NLL, 같은 k 조합 hit로 비교할 수 있다. 현재 저장 운영 직접대조는 공통 467경주에 한정된다. 같은 입력·학습 조건을 통제하지 않으므로 구조 하나의 인과효과를 식별하지 않는다. additive Q는 order probability를 제공하지 않는다.
- 과거 코호트의 선택은 사후 정상 완주와 완전 roster에 의존한다. 실제 당시 출마표 및 원천 공개 시각을 확인할 수 없다. 반복 분석된 라벨은 새 라벨이나 독립 미래 holdout이 아니다.
- 조건부 pair 모델 학습은 이번 진단의 귀결로 자동 실행하지 않는다. 후속 제안에는 새 시간순 OOF, 같은 roster·label·기간의 공정 대조, 6조합 동일 예산 계약이 필요하다.

## 원천·연구설계 검토 범위

`source_manifest.json`에 current SHA-256, 파일 크기, 사용 범위, hash basis를 기록했다. 주요 소형 문서·코드·saved score 파일은 현재 바이트를 해시했고, style-history의 기존 `prepared_lock.json`과 `source_audit_reference.json`, axis-companion의 `source_lock.json`을 읽었다. source cache와 DB 전체는 다시 해시하지 않았다. cache hash는 기존 source-audit lock에 선언된 값이다.

| 원천 | 사용 범위 | SHA-256 |
|---|---|---|
| [`jeju/AGENTS.md`](../../AGENTS.md) | 제주 연구 범위, DB 읽기 전용·신원/시점 정책 | `8f765820ea187e85aabe53f079400f4553bccb4c32a66e67bd17e47d192dd094` |
| [`RESTART_PLAN_20260928.md`](../../docs/RESTART_PLAN_20260928.md) | 확률 목표, 시간분할, 후향 결과와 독립 검증 구분 | `834190c608ebc87f8b2ac5467430390b85610663b01c88d345b592328023c848` |
| [`JEJU_PREDICTION_OBJECTIVES_2026-09-28.md`](../../docs/JEJU_PREDICTION_OBJECTIVES_2026-09-28.md) | 무순위/순서 조합 목표, 고정 조합 수와 승식 정의 | `429427c8e41181c1daab83c75f586138a5188d30218051c2acde493814d53217` |
| [`review_documents/README.md`](../../review_documents/README.md) | 검토용 문서함이 원천/DB 대체물이 아님을 확인 | `3db59f4dd11baafd7fe4672931d3610213a9afd7bbc5d074078794126ffa9a04` |
| [`12_AXIS_COMPANION_PAIRS.md`](../conclusions/12_AXIS_COMPANION_PAIRS.md) | 동반쌍 연구의 축 조건, 15쌍 중 6개, 후보군 coverage 선행 범위 | `a856291d3a92e2cd1a824add2d2c01bc9a52b6011f36078e05716bde9e1d7808` |
| [`17_STYLE_HISTORY_ABLATION.md`](../conclusions/17_STYLE_HISTORY_ABLATION.md) | STYLE6 기존 성능 판정, native PL과 additive set 비교 한계 | `fa48bff22da3a52003f81382a1ae452c6f715724dd1b607ae63aeef492f4afd4` |
| [`style-history FINAL_RESULTS.md`](../20261010_style_history_ablation_v1/FINAL_RESULTS.md) | 저장 결과의 기존 판정·표본 범위·2025/26 hit 하락 | `00507fdf1fff74e19498b605501a4d9351c37928f30afb4c6e96761631895607` |
| [`style-history CONTRACT.md`](../20261010_style_history_ablation_v1/CONTRACT.md) | 고정 입력·fold·τ·정책·평가 계약 | `c10aac8f6faa6e841afd9ef829bfa0b29ada2dceabcbb5405fdfad9c12536bf9` |
| [`style-history run.py`](../20261010_style_history_ablation_v1/run.py) | raw evaluation score 저장 경로, fit 승인 게이트 | `313ccf5ea1c48911787749e4db16d93f47cbb07a16136601236b58a48199c396` |
| [`style-history report.py`](../20261010_style_history_ablation_v1/report.py) | saved score를 F1 set-model 평가로 변환하는 호출 경로 | `3c90a13a2906ae3eb0ad0fe489da5c68197141375fb07343155818632f101da6` |
| [`F1 set-model run.py`](../20261008_horse_profile_baseline_v1/run.py) | 모든 무순위 3두 set의 additive energy·τ·marginal 및 ticket 선택식 | `40fcb2875c06beedd56044f8fe94cdedf6fc0e2c2db38a87a326234999255e68` |
| [`F1 history prepare.py`](../20261009_finish_history_ablation_v1/prepare.py) | F1/F1_STYLE6 고정 평가 roster·source lineage 준비 경로 | `dbfe79bd6bc6339f9d029f06437ea05cca69ddb80cdac812d4c318eeab216a40` |
| [`baseline replay predictions`](../20261010_style_history_ablation_v1/outputs/f1_reproduced_runner_predictions.parquet) | 저장 F1 raw score와 calibrated pTop3, 평가 출전 17,412행의 replay artifact | `04fc9f9a5ce45e8aee76028f10663d6d3c69646e120627f8fca3d545be49914f` |
| [`F1_STYLE6 2024 evaluation scores`](../20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/evaluation_scores.parquet) | 2024 raw score, 6,329 출전·637경주 | `b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60` |
| [`F1_STYLE6 2025 evaluation scores`](../20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/evaluation_scores.parquet) | 2025 raw score, 6,410 출전·654경주 | `45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12` |
| [`F1_STYLE6 2026 evaluation scores`](../20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/evaluation_scores.parquet) | 2026-01-02~09-19 raw score, 4,673 출전·488경주 | `0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a` |
| [`style-history prepared_lock.json`](../20261010_style_history_ablation_v1/outputs/prepared_lock.json) | 선언된 58개 references, 보호 입력 4개, prepared artifacts의 lock | `f110b33b0442e519fd3f9852098aa847af90d2228af674c39db4914142675e24` |
| [`source_audit_reference.json`](../20261010_style_history_ablation_v1/outputs/source_audit_reference.json) | source audit JSON 및 두 cache SHA, 실제 history slot 178,459행 | `8bc61badf6913b3e23ef01607511b574f6216c93d476125c3d033fede4e6d857` |
| [`axis-companion README`](../20261009_axis_companion_pairs_v1/README.md) | 기존 target/policy/후향 코호트와 후보 pool 포괄 상한 | `515481e867edac008b314c77d50d7e6b0554324a47b79be287e985f0e8874952` |
| [`axis-companion PLAN.md`](../20261009_axis_companion_pairs_v1/PLAN.md) | 고정 축·15쌍에서 6개, 시간분할과 비교 계약 | `2de1c839b666d357a7bdfd8e12b0305aaeed8dc08e7ea991c3c43177e553e639` |
| [`axis-companion source_lock.json`](../20261009_axis_companion_pairs_v1/outputs/source_lock.json) | 기존 model, inputs, outputs 및 protected paths를 선언한 25-file lock | `89df37d49131153afa047128b807c7ae85c5bc7b39a2576e9620b8fec3ddc56a` |

두 style-history 모델의 정확한 τ와 evaluation score hash는 기존 `F1_*` 및 `F1_STYLE6_*` `meta.json`에 기록되어 있다. τ 값은 [검토 메모](REVIEW_MEMO.md)에 표시했고 세 STYLE6 evaluation file SHA는 현재 다시 계산해 기존 metadata의 hash와 일치함을 확인했다. F1 replay output은 기존 prepared lock hash와 현재 hash가 일치한다.

보호된 DB·운영 등록부·모델 파일의 전체 SHA를 이번에 다시 계산하지 않았다. SQL이나 네트워크 요청, model fit, tauopt, metric·bootstrap·새 label 통계는 실행하지 않았다. 이 폴더에만 문서를 추가했다.
