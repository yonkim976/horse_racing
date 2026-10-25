# F1_STYLE6 full-field PL 제주 7승식 기준선

## 결과

F1_STYLE6 원점수 전체 출전집합에 순차 Plackett–Luce를 적용하고, 2019–2023 raw OOS 점수와 확정 1·2·3위 순서만으로 하나의 공통 temperature를 적합했다. 기준선 `T=1`과 비교한 후보는 `T=1.1837152381349905`다. 말 점수 모델은 재학습하지 않았다.

주 판정은 2024–2026-09-19 삼쌍승 전체 ordered-triple 공간의 categorical NLL이다. 후보−기준선의 race-equal 차이는 `−0.0182671075`, 고정 2,000회 date-paired bootstrap 95% CI는 `[−0.0269433365, −0.0092957929]`였다. 삼쌍승 sum-Brier 차이는 `−0.0001214193`이다. 두 사전 기준을 모두 만족해 **연구용 calibration candidate gate**를 통과했다.

다른 승식 결과는 아래처럼 별도로 해석한다. 첫 다섯 승식 중 WIN의 NLL과 Brier는 악화했다. 복승·쌍승 Brier의 전체 평균 개선은 매우 작다. 삼쌍승 pooled Brier는 개선됐으나 2025·2026 연도별 Brier는 각각 `+0.000064`와 `+0.000032` 악화했다.

| 승식 | 평가 경주 수 | 후보−T1 race-equal NLL | 후보−T1 Brier | 사건공간 |
|---|---:|---:|---:|---|
| 단승 WIN | 1,779 | +0.003477 | +0.000828 | categorical NLL, sum Brier |
| 연승 PLC | 1,743 | −0.002609 | −0.000886 | 당첨/비당첨 티켓 Bernoulli 손실의 경주 내 평균 |
| 복승 QNL | 1,779 | −0.003192 | −0.000023 | categorical NLL, sum Brier |
| 쌍승 EXA | 1,779 | −0.001857 | −0.000005 | categorical NLL, sum Brier |
| 복연승 QPL | 1,779 | −0.000767 | −0.000172 | 당첨/비당첨 티켓 Bernoulli 손실의 경주 내 평균 |
| 삼복승 TLA | 1,779 | −0.022932 | −0.001052 | categorical NLL, sum Brier |
| 삼쌍승 TRI | 1,779 | −0.018267 | −0.000121 | categorical NLL, sum Brier |

모든 비교는 동일 원점수, race 및 승식 분모를 사용했다. 로그손실은 `ε=1e−15`로 확률을 clip했고, Brier는 clip 전 확률을 사용했다. Reliability bins는 고정 구간의 ticket-event pooled count weighting으로 계산했으므로 race-equal 주 손실과 가중이 다르다. year별 sample은 2024년 637, 2025년 654, 2026년 488경주다. PLC는 발매 개시 출전두수 미관측 때문에 actual 7두 36경주를 제외해 연도별 637, 650, 456경주를 사용했다.

7승식 모두의 winner/event 정의와 분모 원칙은 [공식 규칙 계약](../rules_contract/README.md)에 있다. 실제 발매·정산 여부는 race별로 감사하지 않았으므로 이 평가는 구조적 사건확률이지 과거 풀 가용성이나 payout 재현이 아니다. 시장가격·ROI는 계산하지 않았다. 2024–2026 평가기간은 기존 개발 자료에서 반복 사용됐으므로 독립 holdout 성과로 보지 않는다. TRI gate 통과는 기존 native `q(T)`, 운영 예측, 시장 우위 또는 7승식 전체 우월성을 뜻하지 않는다.

## 선택 티켓 진단

T1과 후보 사이에 바뀐 최대확률 티켓은 승식별 합계 61개였다. [choice-change 원장](outputs/choice_change_diagnostic.parquet)의 61개 전부가 동일한 raw score multiset을 가진 티켓 사이의 수치상 동점이었다. 양 arm에서 두 티켓의 확률 차이 최대값은 `1.3877787807814457e−16`이었다. 선택 hit 수는 WIN 489→488, PLC 999→998, QNL 203→203, EXA 118→118, QPL 428→427, TLA 106→106, TRI 26→26이었다. 이 미세한 선택 차이와 hit count 변화는 모델의 선택 개선으로 해석하지 않는다.

별도 구현과 106개 race-pool-arm 선택 키가 달랐으며, 이 중 일부는 위 61건과 겹칠 수 있다. 이 선택의 최대 확률 차이는 `4.44e−16` 이내인 수치 동점으로 기록됐다. 독립 전수검산은 [supervisor/RESULT_REVIEW.json](../supervisor/RESULT_REVIEW.json)에 있다.

## 재현과 실행 기록

구조 입력 검사는 2,492 calibration race, 1,779 evaluation race, 269 evaluation date, PLC unknown 36건을 확인했다. 10개 점수 원천과 feature, metadata, rules, 고정 bootstrap schedule의 SHA-256 및 날짜 cutoff 검증은 `outputs/source_preflight.json`에 기록했다. 공식 규칙 최소두수, 발매개시 roster 미관측, `N_at_open` 하한 provenance, pool offering/official status의 미감사 상태는 [`race_contract_ledger.parquet`](outputs/race_contract_ledger.parquet)에 저장했다.

합성 검사는 PL 총질량과 주변확률, 7승식 사건 질량, 점수 상수이동 불변성, 결정적 tie-break, PLC의 5–7/8+ 규칙, QPL의 Top3 사건을 확인했다. supervisor 승인 hash를 확인한 실행은 다음이다.

```bash
.venv/bin/python jeju/research/20261022_joint_wager_baseline_v1/experiment/baseline.py --fit-evaluate
```

이 fit/evaluate 명령은 결과 파일을 덮어쓰지 않도록 이미 산출물이 있으면 실행을 거부한다. 현재 저장된 결과만 확인할 때는 다음 감독관 검산 명령을 쓴다.

```bash
.venv/bin/python jeju/research/20261022_joint_wager_baseline_v1/supervisor/verify_results.py --check-only
```

결정적 temperature optimizer는 총 2번 호출됐다. 첫 호출은 후보 적합 후 첫 경주의 선택 원장을 JSON으로 직렬화하다 NumPy 정수형 변환 오류로 중단됐으며, 파일을 저장하지 못했다. 정수형 직렬화만 고쳐서 승인 해시를 갱신했고, 두 번째 호출에서 전체 평가를 한 번 성공시켰다. 성공 실행은 14.6초였다. 이후 fit, 평가 손실 또는 선택 기준을 변경하지 않았다.

성공 결과와 진단 스크립트는 이 experiment 폴더 안에 있다. 전체 ordered Q를 저장하지 않고 race에서 집계 후 폐기했다. 보존된 runner 원장에는 `p_win`, `p_exact2`, `p_exact3`, `p_top2`, `p_top3`만 있다. `outputs/` 파일은 합계 4,286,613 bytes, 이 experiment 폴더 전체는 현재 4,496,077 bytes이며 30MB 목표 아래다.
