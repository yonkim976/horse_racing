# E4 독립 검증과 차기 목적함수 준비 판정

검증일: 2026-09-12 KST

**E4 동결 진단은 통과했다. 차기 실제 경마 목적함수 학습은 아직 준비 완료가 아니다.**
E4 평가 결과와 차기 수학 함수의 결함을 구분한다. 아래 R1/R2는 E4의 여섯 출력 생성이나
평가에 사용되지 않은 실험용 함수에서 발견됐으므로 E4 수치를 무효화하지 않는다.

## 독립 재현

H1에서 공통 validation 3,051행·288경주를 만들고 여섯 parquet의 전체 키·마번·확률을 검증했다.
제출 평가 함수를 호출하지 않고 NumPy 및 동점군 조합 열거로 손실·Brier·TopK를 재계산했다.
기존 encoder/tree를 로드하고 기존 calibration 구간에서 scikit-learn 보정기를 다시 적합한 뒤,
승률을 경주별 합으로 나누는 별도 정규화로 저장 출력을 재현했다. 최대 오차는 2.23e-16 미만이다.
tree 재학습이나 새로운 후보 선택은 하지 않았다.

| 출력 | 독립 winner-set NLL |
|---|---:|
| N raw | 1.937865692372585 |
| N sigmoid | 1.938753954015444 |
| N isotonic | 1.924197523440157 |
| A raw | 1.934531213574919 |
| A sigmoid | 1.933863161825854 |
| A isotonic | 2.021841416637914 |

여섯 출력의 binary NLL·Brier·Top1/3/5도 허용오차 1e-12 이내에서 모두 일치한다.
동점 진단은 각 경주의 모든 말 쌍 및 확률 그룹 크기를 별도 집계해 저장된 경주별 parquet와 비교했다.

- 엄격 순위 역전 0, raw 정확 동점 0.
- isotonic 신규 동점: N 2,129쌍 / A 1,753쌍.
- isotonic Top1/3/5 경계 가로지름: N 61/180/168경주, A 77/122/109경주.
- 경계에서 동점군이 끝나는 경우: N 0/60/92경주, A 0/74/89경주.
- 모든 경주의 TopK 변화가 독립 기대값 계산과 일치한다.
- 경주별 N/A raw 및 final 손실, 산술 분해를 전수 대조했다. 최대 항등식 오차 0.

산술 분해의 평균은 raw A−N −0.003334478798, A 보정 효과 −0.000668051749,
N 보정 효과 −0.013668168932, 최종 A−N +0.009665638386이다.
고정된 두 tree에서 최종 차이의 방향이 보정 후 달라졌음은 확인됐다.
raw 차이는 두 tree의 fit/tune 및 iteration 차이를 포함한다. calibration 모집단은 이번처럼
tree를 고정한 raw 출력에 직접 들어가지 않지만, E3 절차에는 encoder 적합 및 보정 단계도 있으므로
전체 N/A 처리 효과를 순수 DNF 학습 효과라고 부를 수 없다.

## A isotonic 우승마 0 확률 사례

2026-03-14 서울 race_id=535, race_entry_id=5704, 1번마의 공식 win 라벨은 1이다.

| 출력 | 저장 승률 |
|---|---:|
| A raw | 0.0219699303761151 |
| A sigmoid | 0.021522386556580106 |
| A isotonic | 0 |

isotonic에서 0 확률인 출전행은 A 308행, N 305행이다. 우승마 확률이 0인 경주는 A isotonic의
위 한 경주뿐이다. 사전 epsilon 1e-15를 적용한 해당 경주의 손실은 34.538776394910684다.
epsilon 없는 -log(0)는 무한대이며, 보고된 A isotonic 평균은 사전 clipping 규칙을 적용한 값이다.
이 경주를 제외하거나 epsilon을 사후 조정해 성능을 다시 선택하지 않는다.

## 차기 수학 함수 R1: 공통 이동에 따른 손실 소실

위치: `src/horse_racing/analysis/confirmed_starter_e4.py:45`.

현재 함수는 확률 계산에는 shifted logits를 쓰지만 손실에는 큰 원래 logit을 다시 더하고 뺀다.
독립 반례:

```text
z=[0,0], q=[0.5,0.5]        -> loss=0.6931471805599453
z=[1e16,1e16], q=[0.5,0.5]  -> loss=0.0
```

두 입력은 표현 가능한 동일 점수 차이를 가지므로 확률과 CE는 같아야 한다.
현재 검사의 이동량 12345만으로는 cancellation을 발견하지 못한다.
차기 함수는 유효한 정규화 q에 대해 shifted 좌표에서 logsumexp와 CE를 끝까지 계산해야 한다.
이를 고치지 않은 함수를 objective/early-stopping/temperature 적합에 사용하지 않는다.

## 차기 수학 함수 R2: soft-label 합 검사의 상대 허용오차

위치: `src/horse_racing/analysis/confirmed_starter_e4.py:40`.

`np.isclose(..., atol=1e-12)`에 rtol이 명시되지 않아 합이 1.000001인
q=[0.5,0.500001]도 통과한다. 반환 gradient의 합은 약 −1e-6이다.
일반적인 비정규화 q의 CE 미분은 sum(q)*p−q인데, 구현은 합 1을 전제로 p−q를 반환한다.
따라서 입력 계약과 손실/미분의 일관성이 깨진다.

순수 수학 함수의 합 검사에 상대 허용오차를 명시적으로 없애고, 허용되는 미세 반올림의 처리 정책도
고정해야 한다. 별도로 LightGBM label buffer의 dtype/정밀도를 API spike에서 확인한다.
API의 float32 표현 오차를 이유로 수학 함수의 잘못된 합을 무제한 허용하지 않는다.

## 차기 초안의 미완료 사항

설치된 LightGBM 4.7.0 wrapper가 네 번째 인자로 Dataset group을 전달하는 코드 경로는 확인했다.
그러나 이것이 실제 estimator 경로의 float label 보존·callback group·reload 계약까지
통과했다는 증거는 아니다. 제출자가 API spike 미실행을 명시한 것은 정확하다.

실제 학습 전에 다음을 하나의 protocol으로 확정해야 한다.

- BINARY와 RACE_SOFTMAX의 동착 라벨을 각각 명시한다.
- early stopping을 'single-winner NLL'이라고만 쓰지 말고 동착 포함 전체 tune 모집단과
  정확한 primary metric 하나를 정한다. soft-label CE와 winner-set NLL을 혼동하지 않는다.
- temperature의 유한 탐색 범위, 적합 목적, 경계해·상수 점수·적합 실패 처리와 수치 tolerance.
- 초기 score, gradient/Hessian 스케일, Hessian 0 또는 극소값 처리, group/weight/subsampling 계약.
- 실제 두 후보의 동일한 구체적 tree 예산과 refit 절차. E3 저장 모델 자체를 새 목적 연구의
  대조군으로 쓰면 최종 확률 변환까지 달라지므로, 두 후보를 공통 새 절차로 정의한다.

## 검사와 보존

- 독립 해시 대조 49개 통과: H1/E3 입력, 현재 운영 registry, E4 출력·실행 코드·초안.
- 전체 pytest 재실행: **472 passed, 2 warnings**, 28.86초.
- E4 관련 세 파일 Ruff/format 통과.
- 전체 Ruff: 기존 범위 밖 21건. 전체 format: 기존 98개 파일.
- diff-check: 기존 web/racecourse.py:347 EOF 빈 줄 한 건.
- 검증자는 실제 2026-06-01 이후 결과를 열거나 tree를 학습하거나 운영을 변경하지 않았다.

운영 registry의 현재 해시는 제출 전후 봉인값과 일치한다. 별도 champion 경로 없음은
제출자의 발견 범위이며, 검증자가 모든 가능한 외부 포인터의 부재를 증명한 것은 아니다.

다음 에이전트 범위는 **E5-A 수학 보완·합성 LightGBM API spike·protocol 확정**이다.
새 경마 학습을 앞당기는 대신 이 세 가지를 한 작업으로 끝내고 독립 검증에 제출한다.
E4 원본과 원본 코드 hash를 보존하기 위해 수정된 수학·adapter는 새 연구 모듈에 둔다.

실행 지시서: `docs/CONFIRMED_STARTER_E5A_AGENT_PROMPT_2026-09-12.md`.
기계 판독 검증: `data/logs/confirmed_starter_e4_independent_review_20260912.json`.
