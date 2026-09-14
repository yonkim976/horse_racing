# E3 N-vs-A 독립 검증

검증일: 2026-09-11 KST

**판정: 지정된 개발 연구 결과와 재현성을 승인한다. A의 우월성 및 운영 승격은 승인하지 않는다.**
독립 검사에서 제출 수치에 영향을 주는 차단 결함을 발견하지 않았다.

## 직접 재현한 결과

H1 validation을 독립 분모로 만들고, 저장 예측을 키로 정렬해 전수 비교했다.
제출 평가 함수의 반환값을 그대로 사용하지 않고 NumPy/수식으로 binary 손실·Brier·winner-set
손실을 계산했다. TopK는 경계 동점군에서 가능한 선택 조합을 열거해 기대 포함률을 계산했다.
경주일 bootstrap은 날짜별 손실 합과 경주 수를 함께 복원 추출하는 별도 구현으로 검증했다.

| 지표 | N | A | A−N |
|---|---:|---:|---:|
| Winner-set NLL | 1.924197523440 | 1.933863161826 | +0.009665638386 |
| Win binary NLL | 0.266067650459 | 0.266936923179 | +0.000869272721 |
| Win Brier | 0.076546729012 | 0.076429126551 | −0.000117602462 |
| Top1 | 30.613426% | 31.597222% | +0.983796%p |
| Top3 | 61.990741% | 63.541667% | +1.550926%p |
| Top5 | 82.590112% | 84.375000% | +1.784888%p |

top2/top3 binary NLL·Brier도 재현했다. 제출 지표와의 최대 오차는 6.67e-16 미만이었다.

- 경주 paired bootstrap 5,000회: **[−0.023834235424, +0.044705914727]**
- 경주일 cluster bootstrap 5,000회: **[−0.021576451975, +0.038472426332]**
- seed 20260911, 경주 288개, 경주일 묶음 28개.
- 저장 paired parquet의 모든 경주 키·날짜·N/A 손실·차이를 독립 재계산과 대조했다.

두 구간이 0을 포함하므로 우월성 근거가 부족하다. 이를 동등성이나 비열등성의 증명으로
읽으면 안 된다. bootstrap은 선택된 저장 모델에 조건부이며 재학습·후보 선택의 변동성을 포함하지 않는다.

## 학습·확률 계약

실행 코드에서 두 arm이 H1의 동일한 A 기반 feature 표에서 시작함을 확인했다.
N 필터는 train에만 적용되며 공통 validation은 3,051행·288경주다. train 및 validation 키 hash도
직접 재계산했다. fit/tune/calibration의 행 수·일자 경계는 사전 명세와 일치한다.
기존 N feature를 다시 계산하거나 과거 canonical 모델을 대조군으로 사용하지 않았다.

각 저장 bundle의 136개 feature 순서, seed, 실제 estimator parameter, iteration 및 선택 보정기를
검사했다. N win은 isotonic/142, A win은 sigmoid/110으로 일치했다. 나머지 네 head도 일치한다.
현재 trainer 및 E3 코드 hash는 protocol의 hash와 일치한다.

저장 tree와 encoder를 사용해 arm별 calibration 기간의 보정기만 메모리에서 다시 적합했다.
독립 scikit-learn 호출로 raw/sigmoid/isotonic 총 18개 후보의 binary log loss와 6개 선택 결과를
재현했다. 모든 후보의 정규화 전 값은 유한했다. tree 학습이나 새로운 후보 선택은 수행하지 않았다.

저장 예측의 누락·추가·중복, 마번 불일치, 비유한값 및 확률 범위 위반은 0이었다.
독립 계산의 경주별 확률합 최대 오차는 1.78e-15로 계약 1e-8 이내다.
원래 입력 순서로 bundle을 재로드·재추론하면 저장 예측과 최대 오차 0이다.
키 순서로 재배열한 입력으로 추론할 때에는 정규화의 합산 순서에 따라 최대 3.33e-16 차이가
생겼다. 이는 재추론 허용오차 1e-12 이내이며, 모든 입력 순서에서 bit-for-bit 같다고 확대하지 않는다.

## 보존과 검증 범위

H1 dataset·manifest, protocol의 실행 코드, 두 run의 component manifest 및 전체 artifact manifest에
기록된 총 35개 해시 대조가 모두 통과했다. 두 신규 run은 독립 연구 registry에 있으며 기본 registry에는 없다.
실행 코드도 운영 champion을 변경하지 않는다. 다만 제출 산출물에는 운영 registry/champion의
실행 전후 봉인 해시가 없어, 해당 파일 전체의 과거 불변성을 독립적으로 증명했다고 주장하지 않는다.

protocol을 학습 함수 호출 전에 쓰는 코드 순서와 파일 시각, bundle 생성 시각은 일관된다.
로컬 파일 시각과 created_before_training 플래그만으로 외부의 변경 불가능한 사전등록을
증명할 수는 없다. 이번 연구는 기존에 전달된 E3 지시서와의 일치 여부를 함께 확인했다.

- 전체 pytest 재실행: **456 passed, 2 warnings**, 25.08초.
- 관련 세 파일 Ruff check/format: 통과.
- 전체 Ruff: 기존 범위 밖 21건, 전체 format: 기존 96개 파일.
- diff-check: 기존 web/racecourse.py:347 EOF 빈 줄 한 건.
- 검증자는 실제 2026-06-01 이후 결과를 열지 않았고, tree 재학습·운영 연결을 하지 않았다.

## 연구 해석과 다음 방향

E3는 정상완주만 학습하는 N과 DNF를 포함하는 A의 학습 절차 전체를 비교했다.
fit만이 아니라 early stopping, calibration 및 그 선택 결과가 함께 달라진다.
따라서 이번 차이를 DNF 35행의 순수한 tree 학습 효과로 분해할 수는 없다.

데이터의 A 조건부 정의는 유지한다. 성능 개선 근거가 없다는 이유로 실제 출발마를 사후 제외해
평가 모집단을 되돌릴 근거는 없다. E3 N은 연구 대조군으로 보존한다.

다음 우선순위는 새 feature 추가보다 **순위 점수의 변화와 확률보정 효과를 분리하는 것**이다.
N/A의 win 보정기가 서로 다르고, isotonic의 동점과 0 확률이 보고돼 있어 TopK와 NLL의
방향 차이를 모델 능력의 차이만으로 해석할 수 없다. 이는 원인으로 확정한 것이 아니라 점검 가설이다.

저장 tree를 고정한 E4 진단 이후, 주 평가 지표인 경주 단위 확률 손실과 학습·보정 목적을
맞추는 통제 연구를 사전 설계한다. validation에서 유리한 보정기를 사후 채택하지 않는다.
실행 지시서: `docs/CONFIRMED_STARTER_E4_DIAGNOSTIC_AGENT_PROMPT_2026-09-11.md`.

독립 수치·candidate 검증·검사 source:
`data/logs/confirmed_starter_e3_independent_review_20260911.json`.
