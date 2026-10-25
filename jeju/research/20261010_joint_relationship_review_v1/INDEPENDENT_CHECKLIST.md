# 공동입상 관계 후보 독립검증 체크리스트

이 체크리스트는 구현 산출물에 대해 별도 코드·데이터 경로로 재산출할 항목이다. 구현 agent의 helper를 import해 그 helper를 검증했다고 주장하지 않는다. 임계값·허용오차·날짜 경계는 결과를 보기 전에 계약에 고정한다. 현재 outcome 기반 실험은 수행하지 않았다.

## 1. 불변 입력 및 코호트

- [ ] 연구 PLAN, data contract, 구현 코드, source lock, 기존 probability combo gap manifest, STYLE6 artifact manifest/prepared lock의 SHA-256을 새 검증 lock에 기록하고 기존 잠금값과 대조한다.
- [ ] 2024-01-05~2026-09-19, 1,779 race, 17,412 runner, 269 race day를 race ID 및 `api_record_id`로 재구성한다. 각 경주는 전체 started roster와 기존 F1 replay 키·순서·라벨에 일대일 일치해야 한다.
- [ ] 2024/2025/2026의 F1_STYLE6 `evaluation_scores.parquet`, `top3.txt`, `meta.json`과 τ SHA를 각각 독립 대조한다. 17,412개의 고정 eval raw score가 기존 파일과 bitwise 동일한지 확인한다.
- [ ] calibration raw score 3개는 STYLE6 `ARTIFACT_MANIFEST.json` 및 연도별 meta의 checksum과 비교한다. 새 연구 source lock에 직접 넣었는지 확인한다.
- [ ] 기준선의 F1 raw score, 기존 F1_STYLE6 raw score, frozen canonical six, F1_STYLE6 canonical six, roster, Top3 truth, 기존 τ 및 결과표는 새 후보 산출 전후 동일한지 확인한다.
- [ ] 공유 DB, 운영 등록부, 현행 `HY_R_FORM` 및 기존 F1/F1_STYLE6 산출물의 보호 SHA·크기가 전후 동일함을 검사한다. 새 파일은 이 리뷰/구현의 새 하위 폴더에만 생겨야 한다.

## 2. 달력 시간 순서, OOF, 누수

- [ ] 연도별 calibration raw score가 해당 점수 생성 모델의 train/refit race와 겹치지 않음을 meta와 race key로 확인한다. 학습기간 내부의 같은 모델 in-sample score를 관계 learner 학습에서 쓰지 않았는지 확인한다.
- [ ] calibration-year race date를 사전 고정 규칙으로 정렬해 연속 H1/H2 구간으로 나눈다. 경계 기준, race day 수, race 수, 최소·최대 날짜와 purge된 race 수를 보존한다. 같은 race date를 둘로 쪼개지 않는다.
- [ ] 각 연도마다 `F1 refit max <= H1 min - 2 days`, `H1 fit max <= H2 calibration min - 2 days`, `H2 calibration max <= next evaluation min - 2 days`를 실제 날짜 계산으로 검증한다. 범위가 비면 fail closed다.
- [ ] 각 H1/H2/evaluation 내 한 경주의 출전 행은 전부 같은 분할에 있다. race ID 중복, runner 키 중복, 날짜 역전은 0건이어야 한다.
- [ ] pair 입력과 baseline score는 예측대상 경주에 대해 저장 F1_STYLE6 점수 및 사전 가용 feature만으로 생성됐는지 확인한다. 현재 경주의 finish/result/Top3 label, 사후 section, 순위나 다른 사후 필드가 pair feature에 들어오지 않는다.
- [ ] saved full-year STYLE6 τ는 H1 관계 fit에 사용되지 않는다. 후보 Jτ와 비교용 matched baseline τ는 H2 라벨만으로 계산한다. H2 라벨은 H1 계수 선택에 영향을 주지 않는다.
- [ ] evaluation-year label을 임의로 변경한 복사 입력으로 독립 확인한다. H1 계수, H2 τ, eval raw score, joint probability, canonical six 선택 순서는 바뀌지 않아야 한다. outcome metric만 바뀔 수 있다.
- [ ] 뒤 연도 라벨/입력을 바꿔도 앞 연도 모델·예측이 바뀌지 않는다. 이전 연도 eval 결과가 이후 연도 관계 학습에 쓰이는 경우에만 이후 연도 산출에 영향을 줄 수 있다.

## 3. 말 점수 고정 및 pair 상호작용

- [ ] 각 race의 기존 F1_STYLE6 runner raw score 배열과 stable runner key·horse number 순서가 후보 전후 bitwise 동일하다. candidate가 새로운 unary 점수, 말별 intercept, 점수 재학습, tau로 변형된 점수를 별도 점수처럼 저장하지 않았는지 확인한다.
- [ ] 후보 triple energy를 독립적으로 `고정 raw score의 합 + 학습된 unordered pair correction`으로 다시 계산한다. pair correction은 symmetric이고 runner 입력 순서에 불변이어야 한다.
- [ ] pair term의 학습 입력·계수·정규화·support threshold·정규화 상수·regularization이 계약과 일치한다. 모든 선택은 H1 내부에서 끝나고 H2/eval 결과를 본 뒤 조정되지 않아야 한다.
- [ ] H1 scaler를 독립 재산출한다. `w_ri=1/N_r`로 runner weight를 두고 각 열에 `mu=sum_valid(w*x)/sum_valid(w)`, `sd=sqrt(sum_valid(w*(x-mu)^2)/sum_valid(w))`를 적용한다. 세 mean열은 대응 `n>0` 및 finite인 행만 valid로 센다. 따라서 mean열의 race 총 weight는 유효 runner 비율에 비례하며 strict race-equal mean이 아니다. Count와 score는 유효 finite 행 전체를 쓴다. 구현 scaler helper를 import하지 않는다.
- [ ] 후보 pair correction을 모든 가능한 triple에서 `X_{T,i}=1[i∈T]` unary incidence matrix의 열공간에 투영한다. residual interaction norm이 사전 임계값보다 크고, 비영 pair correction이 단순 말별 unary 재표현으로 설명되지 않아야 한다.
- [ ] pair 계수 또는 correction이 0인 합성 입력에서 matched-baseline joint probability와 six selection parity가 맞는지 확인한다. 별도로 기존 full-year τ를 쓴 고정 F1_STYLE6 결과와의 parity도 확인한다. 두 τ 비교기준을 섞지 않는다.
- [ ] 한 race의 출전 행 순서를 여러 순열로 바꿔 독립 재산출한다. 말 ID로 복원한 triple probabilities와 선택 6장이 변하지 않아야 한다.

## 4. 공동 분포와 최대 6조합

- [ ] 각 race에서 출전마의 무순서 3두 조합 `C(n,3)` 전부 한 번씩 열거한다. triple key가 중복·누락되지 않으며 truth가 정확히 한 triple이다.
- [ ] 후보 joint logits를 전체 triple에 대해 안정적인 softmax로 정규화한다. 확률은 finite이고 0 이상이며 경주별 합은 허용오차 내 1이다.
- [ ] 각 runner marginal을 모든 그 runner 포함 triple 확률 합으로 독립 계산한다. 출전 전체 marginal 합은 경주별 3이며, 모든 marginal은 [0,1] 범위다.
- [ ] canonical six는 triple energy 내림차순, 완전 동점은 고정된 말 번호 오름차순 조합 열거의 stable 순서를 따른다. 필드 3두 이상인 각 race에서 서로 다른 조합을 정확히 6개 선택하고 순서·키 중복이 없다.
- [ ] 0 pair residual은 해당 기준τ 아래 기존 canonical six와 일치해야 한다. 후보 및 null baseline 결과에 저장된 선택 순위·확률과 parity를 별도로 대조한다.
- [ ] `hit`은 선택 6장 안에 실제 무순서 Top3 set이 있는 경우로 계산한다. exact 2착·3착이나 순서 적중으로 보고하지 않는다.

## 5. 독립 결과 대조

- [ ] 구현 출력의 모든 race별 joint probability, runner marginal, true-set probability, canonical six, six mass, hit를 독립 산식으로 재계산한다. 구현 helper를 호출하지 않는다.
- [ ] 전체 triple 수와 race 수가 각 race roster에서 직접 합산한 값과 맞고, joint loss/runner loss/선택 ticket 집계가 원자료와 일치한다.
- [ ] 전체 및 연도별 paired date bootstrap을 날짜 단위로 2,000회 수행하고, 지표마다 seed 20261008을 재설정한다. race 단위 bootstrap으로 바꾸지 않는다.
- [ ] loss delta 부호가 `관계 후보 - F1_STYLE6`이고, 음수 개선 해석을 모든 표·요약에서 동일하게 쓴다. fixed original baseline과 matched-τ null baseline의 대상·τ를 표기한다.
- [ ] 전체, 연도별, 기존 고정 거리별 표본 race 수와 race-day 수를 함께 대조한다. 2026은 2026-09-19까지 부분 연도라고 표시한다.
- [ ] 구현 산출물과 독립 재산출물의 row key·정렬·수치 차이 및 허용오차를 기계 판독 receipt로 남긴다. 차이가 있으면 해당 지표 전체의 통과를 보류한다.

## 6. 저장된 계수·온도 독립 stationarity 검사 (root 학습 승인 후)

- [ ] 저장된 fold별 beta만 읽는다. H1의 고정 raw-score offset과 계약 피처로 objective 및 analytic gradient를 독립 재산출하고 L2 `lambda=1.0` penalty를 포함한다. 저장 receipt의 objective, gradient, optimizer termination reason과 대조한다. L-BFGS-B의 사전 고정 `gtol=1e-8`, `ftol=1e-12` 중 실제 종료 조건이 충족됐는지 검사한다. 계수 재최적화나 대체 계수 선택은 금지한다.
- [ ] 저장된 H2 candidate tau와 matched-baseline tau만 읽는다. 각 tau에서 race-equal exact-set NLL과 `dL/dtau=(E_true-E_p[E])/tau^2`를 독립 계산한다. `[0.35, 4.0]` 안의 내부해는 derivative가 0에 가까워야 하며, 하한해는 derivative `>= 0`, 상한해는 derivative `<= 0`인 KKT 부호를 검사한다. 경계 안쪽에서 absolute step `1e-4` 및 `1e-3` perturbation의 objective도 평가해 국소 최소를 확인한다. `minimize`·grid search·다른 tau 선택은 금지한다.
- [ ] 예상 적합 횟수는 fold별 beta 3회와 H2 candidate/matched-baseline temperature 최적화 6회다. 독립 objective/gradient/derivative 재산출은 적합 횟수에 포함하지 않으며 새 후보를 fit하지 않는다.
- [ ] 분석·적합 artifact와 별도 독립 재산출 receipt의 beta, tau, objective, gradient/derivative, termination/KKT 판정을 저장 key별로 기계 대조한다.

## 7. 종료 게이트

- [ ] 후보 training/model hash, 계수, H1/H2 split, matched τ, scoring contract, source hash를 산출물 manifest에 잠근다.
- [ ] 독립 검증 결과를 새 review 폴더에만 저장하고 root에게 PASS/FAIL, 구체 증거, 남은 제한을 보고한다.
- [ ] 사용자가 허가한 최초 범위 안에서 연구 산출물을 마친다. 중앙 `conclusions/`, registry, DB, 운영 반영은 root의 별도 후속 승인 전 수정하지 않는다.
