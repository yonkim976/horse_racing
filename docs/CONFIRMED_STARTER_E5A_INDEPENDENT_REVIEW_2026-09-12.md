# E5-A 독립 검증

검증일: 2026-09-12 KST

**판정: 기존 R1/R2 수학 보완과 제출된 합성 API spike는 통과. 실제 경마 학습 승인은 R3/R4 보완까지 보류한다.**
차단 사유는 예측력 부족이나 테스트 수가 아니라, 보정과 early stopping의 명세를 위반하는
구체적인 합성 반례 두 종류다. 실제 경마 데이터에서 이 결함이 발생했다고 주장하지 않는다.

## 통과한 범위

- 큰 공통 이동에서 CE=log(2) 유지, 합 1.000001인 q 거부, 허용 반올림 재정규화 확인.
- 독립 무작위 40개 사례에서 gradient 및 전체 Hessian을 중앙 유한차분으로 검증했다.
  최대 오차는 각각 7.84e-11, 1.48e-11 미만이다.
- 공개 native API spike를 임시 폴더에서 직접 재실행했다. 제출 callback_evidence.json과
  재실행 결과가 전체 일치했다. 실제 경마 tree 학습은 하지 않았다.
- group/label/weight 전달, float64 q 복원, 기본 metric 비활성화, 저장/reload 및 키 복원은
  제출한 합성 범위에서 재현됐다.
- manifest에 기록된 입력·코드·문서·출력 해시 20개가 현재 파일과 일치했다.
- 전체 pytest 재실행: **486 passed, 2 warnings**, 27.50초.
- 관련 Ruff/format 통과. 전체 Ruff는 기존 범위 밖 21건, format은 기존 98개 파일.
- diff-check는 기존 web/racecourse.py:347 EOF 빈 줄 한 건.

## R3 — temperature 경계해가 내부해로 승인됨

위치: `src/horse_racing/analysis/confirmed_starter_e5.py:353` 및 `:367`.
현재 구현은 bounded optimizer가 반환한 위치와 경계의 거리가 1e-7 이하인지로 경계해를 판정한다.
이것은 최적해가 경계인지 확인하는 충분한 조건이 아니다.

### 상한 반례

```text
group=[2], z=[0,0.01], winner=[1,0]
반환 log T=3.9999998956323135
반환 status=interior_optimum, boundary_solution=false
반환 CE=0.6932387629572305
상한 log T=4의 CE=0.6932387629476718
```

이 경우 낮은 점수의 말이 이겼다. loss는 log(1+exp(0.01/T))이므로 T가 커질수록 엄격히 감소한다.
따라서 제한 구간의 최소점은 상한인데, 반환점과 경계의 거리가 1e-7보다 조금 커서 통과한다.

### 하한 반례

```text
group=[2], z=[0,1], winner=[0,1]
반환 log T=-3.7379837504241475
반환 status=interior_optimum, objective=0
```

loss는 log(1+exp(-1/T))이며 T가 작을수록 엄격히 감소하므로 최소점은 하한이다.
작은 양의 CE가 부동소수점 계산에서 0으로 반올림되는 구간을 내부 최적점으로 오인했다.
현재 temperature 회귀 테스트의 'signal' 예제도 모든 우승마의 점수가 가장 높은 완전 분리
사례다. 그 사례를 내부해로 기대하는 assertion 자체를 수정해야 한다.

경계의 목적값·미분 및 명시적인 최적성 조건으로 확인해야 한다. 단순히 거리 tolerance를
조금 키우는 것은 하한의 넓은 수치 평탄 구간을 해결하지 못한다.
beta=1/T에서 CE가 볼록하다는 성질을 이용하는 검증도 가능하다.
진짜 평평한 목적함수와 수치 반올림 때문에 0처럼 보이는 목적함수를 구분한다.

내부해의 독립 손계산 기준은 같은 z=[1,0]인 세 경주에서 앞선 말이 두 번, 뒤진 말이 한 번
이기는 사례다. 최적 beta=log(2), T=1/log(2)=1.4426950408889634다.
이 사례는 현재도 약 1.442695054280492로 재현됐으므로 내부 최적화 전체를 부정하는 것은 아니다.

## R4 — BINARY의 probability→margin 역변환이 공통 metric을 보존하지 못함

위치: `src/horse_racing/analysis/confirmed_starter_e5.py:303`.

현재 BINARY feval은 이미 sigmoid 변환된 확률을 받고 [1e-15,1−1e-15]로 clip한 뒤 logit으로
돌린다. 원래 margin의 상대 차이는 clipping 및 확률 포화로 복원 불가능할 수 있다.
label=[1,0], group=[2]를 실제 LightGBM Dataset에 넣고 metric을 직접 호출한 독립 반례:

| 원래 margin | sigmoid 확률 | 현재 BINARY metric CE | 원래 margin의 race CE |
|---|---|---:|---:|
| [40,41] | [1,1] | 0.693147180560 | 1.313261687518 |
| [−40,−41] | [4.248e-18,1.563e-18] | 0.693147180560 | 0.313261687518 |

첫 사례는 sigmoid의 정보 소실, 둘째는 추가 clipping의 정보 소실이다.
이 상태에서는 두 후보가 같은 raw-margin softmax CE로 early stopping한다는 protocol 계약을
충족하지 못한다. 현재 합성 spike의 margin 범위에서는 발생하지 않았기 때문에 기존 증거와
테스트가 통과한 것이다.

수정은 실제 원래 raw margin을 공통 평가에 전달하는 경로여야 한다. 확률에서 잃어버린 값을
clipping epsilon 변경으로 복원할 수는 없다. native binary objective를 유지한 공개 callback
평가 경로 또는 수학적으로 동등한 검증된 raw-margin binary objective 등, 실제 구현을 선택하고
protocol을 갱신한다. 의도하지 않은 objective·가중·초기 score 변경을 함께 넣지 않는다.

## 승인 범위와 후속

E4 진단 결과는 그대로 유효하다. E5-A의 기본 수학 미분과 native API 연결도 재현됐다.
남은 작업은 R3/R4와 그에 따른 protocol v3·회귀 검증으로 한정한다.
기존 E5-A 파일과 manifest를 보존한 새 버전을 제출하고, 실제 경마 tree 학습은 아직 실행하지 않는다.

독립 검증자는 실제 2026-06-01 이후 결과를 열지 않았으며 운영 경로를 변경하지 않았다.
임시 폴더의 합성 spike 재실행은 기능 재현이며 경마 성능 연구가 아니다.

실행 지시서: `docs/CONFIRMED_STARTER_E5A_R3_R4_AGENT_PROMPT_2026-09-12.md`.
기계 판독 증거: `data/logs/confirmed_starter_e5a_independent_review_20260912.json`.
