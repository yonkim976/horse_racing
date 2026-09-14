# Canonical 구간 연구 독립 검증

검증일: 2026-09-11 KST. 역할: 구현 결과 검토. 운영 코드·DB·학습 artifact는 수정하지 않았다.

**판정: 기본 변환과 현재 NLL 비교는 확인. 운영 승격 보류에 동의. 평가 코드와 경계 검증 보완 전까지 단계 완료 승인은 유보한다.**

기계 판독 근거: [검증 JSON](../data/logs/canonical_section_review_20260911.json).
원 구현 보고서: [연구 인수인계](CANONICAL_SECTION_RESEARCH_2026-09-11.md).

## 1. 직접 재검증한 통과 항목

- `audit_canonical_sections.py`를 별도 `/tmp` 출력으로 재실행: 원문 표본 48건 모두 저장값과 일치. 기존 감사의 표본·basis 집계·서울 사례와 동일.
- 서울 race_id=1681, 6번 last200=12,800ms, 상대지수 +12.124924 재현.
- 기존 V5 artifact를 고정 validation 입력 6,969행으로 다시 추론: 저장된 예측과 exact equal.
- A/B 데이터 파일 SHA-256, canonical 코드 5개 파일 hash, 원천 감사 hash 일치.
- A/B 출전 식별키가 동일. 양쪽 모델에서 공통으로 실제 선택한 feature 값은 전부 동일.
- 전체 dataset 공통 열 중 early gate 4개 값은 차이가 있었으나 이번 두 모델에서 모두 제외된 열이다. 이를 이번 A/B의 사용 입력 차이로 오인하지 않는다.
- 288경주 NLL, 이진 LL, Brier와 5,000회 race/day-block bootstrap을 기존 스크립트로 재현: 기존 JSON과 동일.
- 합성 DB에서 실제 `build_prediction_frame`을 canonical run의 136-feature 계약으로 실행: 5두 모두 canonical last200 이력 생성, profile count=1, 결과 label 없음.
- 전체 pytest 재실행: 387 passed, 경고 2개. 관련 파일 Ruff PASS.
- 전체 Ruff 21건 재확인: `scripts/analysis_finish_time_quality.py` 18건, `analysis/baselines.py`, `features/ability.py`, `tests/test_segment_correction.py` 각 1건. 이번 canonical 파일의 오류가 아니며 별도 범위로 둔다.

신규 실제 결과·원천 분석은 2026-05-31까지로 제한했다. 합성 DB의 미래 날짜는 가상 fixture다. 미사용 실제 holdout은 평가하지 않았다.

## 2. 보완 요구

### R1 / P2 — 확률 동점에서 입력 행 순서가 적중률을 바꾼다

위치: [compare_canonical_section_runs.py](../scripts/compare_canonical_section_runs.py), `_race_metrics`, 37~45행.

두 모델 모두 win 보정이 isotonic이며 같은 확률이 반복된다. `np.argsort(..., kind='stable')` 후 앞 K개를 선택하므로 입력 행 순서가 임의의 동점 우선순위가 된다. 이것은 실제 착순 동착과 별개의 문제다. 보고서의 `tie_races=0`은 확률 동점이 없다는 뜻이 아니다.

| 결과 | Legacy | Canonical |
|---|---:|---:|
| 기존 보고 Top1 | 33.3333% | 30.5556% |
| 입력 행을 뒤집었을 때 Top1 | 30.9028% | 31.9444% |
| 1순위 경계에 확률 동점이 있는 경주 | 51 | 83 |

행 순서만 바꾸어도 어느 쪽 Top1이 높은지가 뒤집힌다. 기존 프로젝트의 동점 기대값 정책으로 독립 계산한 값은 다음과 같다.

| 지표 | Legacy | Canonical | Canonical−Legacy |
|---|---:|---:|---:|
| Top1 | 31.712963% | 31.695602% | −0.017361%p |
| 우승마 Top3 | 62.320602% | 63.605324% | +1.284722%p |
| 우승마 Top5 | 83.819444% | 83.663194% | −0.156250%p |

단독 우승 경주에서 우승마보다 높은 확률의 말이 g두, 같은 확률 말이 t두이면 `clip((K−g)/t, 0, 1)`을 기여도로 사용했다. 이는 사전 고정된 무작위 동점해소의 기대값이며 실제 구매 적중횟수가 아니다. 실제 운영에 별도 tie-breaker를 쓰려면 결과와 무관하게 먼저 정의하고 별도로 평가한다.

요구: 공통 평가 정책 재사용 또는 일관된 확장, Top1/3/5 재계산, 역순·무작위 행 재배열 불변 테스트. 실제 동착 처리는 별도 계약으로 유지한다.

### R2 / P2 — 예측 누락을 coverage로 검출할 수 없다

위치: 같은 파일 `_joined` 24~28행, coverage 63행, main의 paired join.

현재 coverage는 join된 행 수를 그 안의 고유 출전 수로 나눈다. 중복 없는 한 항상 1이다. 실제 예측 행을 한 개 제거한 입력에서도 1.0이 나왔다. inner join은 누락·범위 불일치를 조용히 감출 수 있고, 고정 데이터셋 경로와 넘겨받은 run ID의 연결도 검증하지 않는다.

이번 실제 artifact에서는 양쪽 3,038행·288경주 식별키가 같아 누락에 의한 현재 NLL 왜곡은 발견하지 못했다. 그러나 재사용 가능한 비교기로 승인하려면 보완해야 한다.

요구: 원장에서 run의 실제 dataset·기간·feature 계약을 읽고 검증. 사전 정의한 validation 전체 출전집합을 분모로 coverage 계산. 고유키·범위·누락·추가·말별/경주별 완전성·확률 유한성과 합을 확인하고, A/B 불일치 시 비교를 중단한다. 명시적 제외 정책 없이 일부 말만 제거해 정규화하거나 교집합만 평가하지 않는다. 검증 전 결과를 가정한 `post_2026_06_used=False` 같은 메타데이터를 하드코딩하지 않는다.

### R3 / P2 — 물리적 구간 순서·거리 검증이 완전하지 않다

위치: [canonical_sections.py](../src/horse_racing/analysis/features/canonical_sections.py), 88~105행 및 profile_available 126~127행.

G3F와 G1F 사이 순서는 검사하지만 S1F와 다른 지점의 관계 및 경주거리와 600m 구간의 양립 가능성을 검사하지 않는다. 합성 반례를 직접 실행했다.

- 1,200m, FIN=76.6초, S1F=70초, G3F 누적=38초, G1F 누적=63.8초여도 `profile_available=1`.
- 400m 경주에 잘못된 G3F 값을 넣어도 `last600=38.6초`, `profile_available=1`.

서울에서 명시적 cumulative S1F≥G1F인 실측 행은 조회 범위 내 0건이었다. 그러므로 위 반례를 현재 서울 성능 왜곡이 입증된 것으로 표현하지 않는다. 다만 인수인계의 엄격한 순서·거리 방어가 완성됐다는 설명은 수정해야 한다.

요구: 확인된 물리적 측정거리와 시간 순서를 함께 검증한다. S1F, G3F, G1F는 경주거리에 따라 같은 위치일 수 있으므로 일률적인 엄격 부등식을 적용하지 않는다. 800m의 S1F/G3F 등 동일지점은 공식 계약에 따라 처리하고, 허용 시간 오차도 원천 정밀도에 근거해 명시한다. 불가능한 구간·미확정 거리는 unavailable로 남기고 관련 profile flag를 일관되게 만든다.

### R4 / P2 — 날짜 상한이 모든 시간가변 원천에 적용되지는 않는다

위치: [base.py](../src/horse_racing/analysis/features/base.py), `load_source_frames`, 219~235행.

`race_date_max`는 past_results와 sections에만 적용된다. training, medical, running_trials의 결과, steward_reports 등은 여전히 전체 날짜를 조회한다. 같은 함수의 조회 상한이 모든 원천에 적용된다고 이해하면 안 된다.

이것은 **후속 날짜 자료를 읽는 범위의 문제**다. 현재 canonical A/B feature에 미래 결과가 유입됐다고 입증한 것은 아니다. 경주 뒤 정보를 읽는 것과 그것이 예측에 영향을 주는 것은 구분한다.

요구: 명시적 상한을 준 연구 경로에서는 필요한 시간가변 테이블 모두에 해당 event date 상한을 전달하거나, 사용하지 않는 원천을 읽지 않는다. 기본 legacy 정책은 유지한다. synthetic 미래 행을 각 원천에 넣고 반환 source frame에 포함되지 않는지 테스트한다. 현재 성별 snapshot 같은 별도 기존 PIT 이슈를 이번 수정에서 임의로 재설계하지 않는다.

## 3. 성능 결론의 정확한 범위

NLL canonical−legacy = +0.0029380344740913954. race bootstrap 95% CI는 [-0.030748699238871805, +0.03673950183429222], day-block CI는 [-0.027582923073068907, +0.03455628425792916]. 따라서 개선 근거가 없다는 판단은 그대로다. Top1 큰 하락이나 Top5 개선이라는 해석은 동점 처리 수정 후 철회·정정해야 한다.

이번 비교는 **서울 history feature의 LightGBM binary 단일 seed 42** 실험이다. 실제 주력 V5의 LambdaRank＋177개 상세 feature를 그대로 교체한 결과가 아니다. canonical 9개 대응축 외에 middle400 1개가 추가된 feature 묶음 비교이므로 순수 변환식 하나의 효과로만 읽지 않는다.

auto calibration 후보는 기존 학습 코드에서 development validation으로 선택됐다. 이미 사용한 개발 구간이라고 명시한 것은 맞다. 이 신뢰구간은 선택된 후보의 해당 개발 표본 손실차를 요약하며, 후보 선택 불확실성 전체나 미래 일반화·동등성 증거가 아니다. bootstrap에서 차이<0인 비율을 ‘모델이 실제로 더 좋을 확률’이라는 사후확률로 표현하지 않는다.

## 4. 다음 담당자에게 요청할 작업

먼저 R1~R4의 제한된 보완을 한다. 모델 개선 실험·새 seed 탐색·C 혼합모델·제주/부경 provenance 복원·DNF 라벨 개편은 동시에 진행하지 않는다.

- 기존 모델·데이터·비교 JSON을 보존한다. 수정된 평가 결과는 새 버전 경로에 기록한다.
- R1/R2는 현재 고정 예측으로 재평가하면 된다. 재학습이 필요하지 않다.
- R3/R4 변경 후 새 dataset으로 값·coverage를 비교한다. 학습 입력이 실제로 달라진 경우에만 동일 설정으로 새 run을 만든다. 달라지지 않았다면 해시·키·값 대조 근거를 남기고 불필요한 재학습을 하지 않는다.
- 관련 회귀검증과 전체 테스트를 실행하고, 보고서의 TopK·완료 범위·같은 날 source 보존 설명을 정정한다. 현재 prediction_frame는 여전히 해당 날짜 이전으로 과거 결과·sections를 필터링하므로 당일편향 live 지원 완료로 읽히면 안 된다.
- 보완 결과를 검증 담당자에게 제출한 뒤 사전 출전집합/DNF 계약 단계로 넘어간다. 이번 검토는 코드 수정이나 운영 승격을 수행하지 않았다.

## 5. 재현 명령

```bash
.venv/bin/pytest -q
.venv/bin/python scripts/audit_canonical_sections.py --output /tmp/canonical_source_reviewer.json
.venv/bin/python scripts/compare_canonical_section_runs.py \
  --legacy-run 8eed3487-3ea1-4900-ad00-7d14cf6949cc \
  --canonical-run 55456a89-f784-47b0-a704-0fe30562288e \
  --iterations 5000 --output /tmp/canonical_comparison_reviewer.json
```

마지막 명령은 원래 결과의 재현이며 R1/R2가 수정된 비교기는 아니다. 동점 기대값과 반례 결과는 검증 JSON에 별도로 기록했다.
