# F1_STYLE6 결과

## 판정

사전 지정한 주 gate를 통과했다. F1_STYLE6은 다음 연구에서 사용할 기준선 후보로 유지한다. 운영 모형 승격이나 독립 미래 검증으로 해석하지 않으며 기존 F1도 보존한다.

평가 코호트는 2024~2026년 1,779경주, 269경주일이다. 모든 차이는 F1_STYLE6−F1이다. 경주 균등 Top3 log loss는 0.569469에서 0.568159로 낮아졌고, Brier는 0.192724에서 0.192256으로 낮아졌다. 2,000회 날짜 paired bootstrap(지표별 seed 20261008)의 차이는 다음과 같다.

| 지표 | 차이 | 95% 구간 |
|---|---:|---:|
| Top3 log loss | −0.001309 | [−0.002245, −0.000356] |
| Top3 Brier | −0.000468 | [−0.000849, −0.000089] |
| canonical 최대 6 조합 hit | +0.562%p | [−0.507, +1.639]%p |
| 최고점 말 Top3 포함 (`pick_hit`) | −0.506%p | [−1.594, +0.623]%p |

사전 주 gate는 log loss와 Brier 두 지표다. 두 점추정치가 모두 개선됐고, 두 구간의 상한도 0 아래다. 2024·2025·2026 각 연도에서 log loss와 Brier 차이는 모두 음수였다. 이 방향 일치는 연도별 독립 유의성이나 미래 성능 검증을 뜻하지 않는다. 2026년은 9월 19일까지의 부분연도다.

보조 지표는 불확실성을 함께 본다. canonical 최대 6 조합 hit는 22.316%에서 22.878%로 +0.562%p였지만, 95% 날짜 paired 구간은 [−0.507, +1.639]%p로 0을 포함한다. 이 지표는 사전 주 gate가 아니며 증거는 불확실하다. Top5 capture는 +0.037%p, Top5 전원 포함은 +0.056%p였다. 최고점 말의 Top3 포함(`pick_hit`)은 58.010%에서 57.504%로 −0.506%p였다. 이는 우승 적중률이 아니다.

연도별 주 손실 변화도 같은 방향이었다. 반면 보조 six-hit은 2025년 21.407%→21.101%, 2026년 24.590%→24.385%로 하락했다.

| 평가연도 | log loss F1 → STYLE6 | 차이 | Brier F1 → STYLE6 | 차이 |
|---|---:|---:|---:|---:|
| 2024 | 0.568598 → 0.566793 | −0.001805 | 0.191952 → 0.191229 | −0.000723 |
| 2025 | 0.567216 → 0.566143 | −0.001073 | 0.191741 → 0.191392 | −0.000349 |
| 2026 | 0.573624 → 0.572646 | −0.000978 | 0.195050 → 0.194754 | −0.000296 |

공통 운영 비교 467경주·70일에서 F1의 log loss/Brier는 0.573442/0.194940, Top5 capture/six-hit은 69.522%/24.411%였다. F1_STYLE6은 0.572711/0.194720, 69.665%/24.197%였다. HY_R_FORM의 native PL은 log loss 0.555417, Brier 0.187645, Top5 capture 75.018%, six-hit 30.835%였다. 같은 Top3 결과를 대상으로 공통 경주 성능을 직접 비교할 수 있지만, 확률 구성 방식(native PL/additive 3-set), 입력, 학습 조건이 다르므로 F1_STYLE6의 여섯 추가 입력만의 효과를 분리한 대조는 아니다.

## 해석 범위

후보는 초반 상대위치, 두 구간의 상대 위치 변화, 각 관측 수를 묶은 6열 패키지다. 개선은 순수 전술·선행 유지·추입의 독립 효과를 식별하지 않는다. 같은 유효 슬롯 집합에서 평균 S1F 위치와 두 평균 변화를 조합하면 G1F 상대 위치 평균을 재구성할 수 있어 최근 G1F 위치 수준과도 분리되지 않는다.

결과는 같은 과거 자료를 반복 사용한 후향 개발 비교다. 평가는 사후 정상 완주·완전 편성 선택 코호트이며, 당시 예측 대상 편성과 원천 발행 시각은 역사적으로 복원하지 못했다. source audit는 지정된 history-source cohort를 확인했으며 전체 DB의 point 가용성을 주장하지 않는다. 운영 승격 또는 인과효과 주장은 하지 않는다.

상세 수치와 재검증 결과는 [`outputs/report/report_receipt.json`](outputs/report/report_receipt.json), [`outputs/final_verification.json`](outputs/final_verification.json), [`outputs/postfit_verify_recovery_receipt.json`](outputs/postfit_verify_recovery_receipt.json)에 있다.

## 재현과 검증

고정 후보 학습은 다음 명령으로 수행했다. 이는 저장된 root 승인 receipt를 확인하고 한 번만 3개 연도 모델·6회 LightGBM 학습·3회 온도 보정을 실행한다.

```bash
.venv/bin/python jeju/research/20261010_style_history_ablation_v1/run.py fit
.venv/bin/python jeju/research/20261010_style_history_ablation_v1/report.py report
```

학습 후 [`outputs/postfit_verify_recovery.py`](outputs/postfit_verify_recovery.py)는 저장된 세 모델을 다시 불러 raw calibration/evaluation score, 고정 tau, race/runner/canonical-six 출력, paired/support/conditional/467 표를 no-fit으로 검증했다. 원 verifier의 `report_receipt.primary_gate` Python dict 완전일치 비교만 JSON 재로드·부동소수점 재계산 차이 최대 `3.6808663755882876e-17` 때문에 실패했다. Boolean과 key는 정확히 일치했고, 두 numeric map은 `rtol=0`, `atol=1e-12`로 재비교했으며 saved-score parity, 보고표 검증은 모두 통과했다. 최종 결과는 [`outputs/postfit_verify_recovery_receipt.json`](outputs/postfit_verify_recovery_receipt.json)에 기록했다. 사전 feature 검증 `verify.verify_prepared()`도 fit 전에 read-only PASS했고, 이 결과는 finalizer에서 재사용했다.
