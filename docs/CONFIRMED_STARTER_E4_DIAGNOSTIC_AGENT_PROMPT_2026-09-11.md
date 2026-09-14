# E4 실행 지시: 순위·확률보정 분리 진단과 다음 목적함수 연구 설계

작업 경로: `/Users/kimyongjin/Desktop/horse_racing`

E3 독립 검증은 통과했다. A−N winner-set NLL은 +0.009665638이며 두 paired CI는 0을 포함했다.
새로운 tree 모델을 학습하기 전에, 저장 점수와 보정의 영향을 분리해 다음 실험을 명확히 하라.
이번 단계는 기존 모델을 고정한 진단과 후속 사전 설계까지다. 사용자에게 결과를 제출하고 멈춰라.

먼저 E3 독립 검증 보고서와 E3 protocol·comparison·실행 코드를 읽어라.
`docs/CONFIRMED_STARTER_E3_INDEPENDENT_REVIEW_2026-09-11.md`

## 1. 범위 동결

- H1 dataset·manifest와 E3 protocol·두 bundle·predictions의 hash를 확인하고 원본을 보존한다.
- H1 A 조건부 표, 136개 feature, 기존 두 encoder·tree·iteration을 고정한다.
- N run: `d2ee0d24-60d0-4194-aa8b-390c00505586`.
- A run: `32d7ade9-e896-450c-bbcc-52eaf0a4764c`.
- 공통 validation은 2026-03-01~2026-05-31, 3,051행·288경주다.
- 실제 2026-06-01 이후 행을 조회·탐색·평가하지 않는다.
- 새로운 tree 학습, feature 변경, seed 탐색, calibration 후보 추가, 모델 승격은 하지 않는다.
- 기존 N/A의 calibration split에서 기존 sigmoid/isotonic을 재구성하는 것은 재현 목적으로 허용한다.
  tree 재학습과 보정기 재적합을 보고서에서 구분한다.

## 2. 승률 head만 분리 진단

예측 결과를 보기 전에 이 진단의 입력·출력·산식을 새 E4 protocol에 저장하라.
두 arm 각각에서 다음 세 출력을 재구성한다.

1. 저장 tree의 raw binary 확률을 기존 방식으로 경주 합 1로 정규화.
2. 기존 sigmoid 보정 후 같은 정규화.
3. 기존 isotonic 보정 후 같은 정규화.

보정기는 해당 arm의 2025-12-28~2026-02-28 calibration 행에서만 적합한다.
각 후보의 E3 기록 binary log loss와 선택된 최종 예측이 재현되는지 확인한다.
6개 출력 모두 누락·추가·중복·유한값·[0,1]·경주합 계약을 검사하고 키별로 저장한다.
validation 결과를 보고 후보를 새로 선택하거나 E3 결과를 수정하지 마라.

각 출력에 대해 winner-set NLL, win binary NLL/Brier, 동점 기대 Top1/Top3/Top5를 계산한다.
raw tree 순위와 보정 후 순위에서 다음을 구분한다.

- 엄격한 순위 역전과 보정으로 새로 생긴 동점.
- 실제 선택 경계가 동점군을 가로지르는 경주와 경계가 동점군 끝인 경주.
- 0/1 확률 행 수, 우승마 0 확률 경주 수, epsilon clipping 수.
- 원래 raw 확률부터 있던 동점과 isotonic으로 합쳐진 동점.

동점의 기대 포함률은 결과와 무관한 균등 무작위 선택으로 계산한다.
단조 보정은 점수 순위를 반드시 엄격하게 보존하는 것은 아니며 동점을 만들 수 있다.
isotonic 후 TopK 변화가 있다면 경주별 기여를 동점 변화로 설명할 수 있는지 확인하라.
불일치가 있으면 원인을 찾되 raw 동점과 부동소수점 합산 차이를 숨기지 마라.

## 3. E3 차이의 산술 분해

경주별로 다음 항등식을 확인하라.

```text
최종 A NLL − 최종 N NLL
= (raw A NLL − raw N NLL)
  + (최종 A NLL − raw A NLL)
  − (최종 N NLL − raw N NLL)
```

전체 평균과 경주별 오차를 저장하라. 이는 선택된 tree를 고정한 산술 분해이며
DNF 포함의 인과효과를 식별하는 분석은 아니다. fit/tune 포함 정책이 달라진 영향도 raw 차이에 섞인다.
동일 보정 방식끼리 N/A를 비교한 세 행과 원래 E3 최종 조합을 모두 보고한다.
좋은 행만 골라 새 winner를 선언하지 마라. 진단 후보에서 가장 낮은 validation NLL을
찾더라도 채택하지 말고 탐색 결과로만 표시한다.

전체 288경주를 주 대상으로 유지한다. 이미 사전 고정된 특수 상태 포함 12경주/나머지 276경주
진단은 허용하지만 새로운 유리한 subset 탐색은 하지 않는다.
E3의 paired bootstrap은 원래 최종 출력의 확인용으로 유지한다. 6개 진단 후보에 대한 수많은
유의성 검정이나 재선택은 필요 없다.

## 4. 다음 연구 protocol 초안

위 진단과 별도로, 동일 A 학습 대상·136개 feature에서 binary 학습과 경주 단위 확률 목적을
비교하는 다음 연구를 설계하라. 이번에는 그 모델을 학습하지 않는다.

초안은 실제 설치된 trainer/API를 확인해 다음 사항을 구체화해야 한다.

- 같은 정보·분할·encoder 정책·학습 예산으로 목적함수 차이를 비교하는 대조군과 후보.
- 말별 binary loss, 경주 단위 softmax 확률 손실, winner-set 평가 지표 사이의 정확한 관계.
- 공식 동착 학습 라벨 정책. 동착 승자 균등 soft label CE와 -log(sum winner probability)는
  같은 목적이 아니므로 구분한다. DNF/실격에는 0 라벨을 유지한다.
- 안정적인 softmax/logsumexp, 경주 그룹 경계, 목적함수 gradient/Hessian 또는 근사,
  사용 라이브러리와의 호환성. 근사와 정확 미분을 구분한다.
- 순열·공통 점수 이동 불변성, 확률합, 극단 logit, 유한차분 미분 점검을 합성 예제로 명세한다.
- early stopping 지표와 별도 calibration 목적을 경주 단위로 맞추는 방안.
- 보정 선택·적합을 train 내부에서 끝내고 development validation을 새 후보 선택에
  재사용하지 않는 절차. 이미 반복 사용한 development를 새로운 독립 test로 부르지 않는다.
- 두 후보를 넘지 않는 실험 예산, 단일 seed의 탐색 한계, 후속 시간 분할 검증 계획.
- 새 모델의 운영 연동 없이 연구 artifact로 격리하는 방식.

설계 근거는 로컬 코드 또는 공식 문서·원 논문으로 확인한다. 수치가 좋아질 것이라고 약속하지 마라.
필요하면 합성 예제용 수학 검증 함수를 만들 수 있지만 실제 경마 tree 학습은 하지 않는다.

## 5. 제출

새 `data/experiments/confirmed_starter_e4_diagnostic_20260911/`에 protocol, 6개 승률 출력,
진단 JSON, 경주별 분해 parquet, 입력·출력·실행 코드 hash manifest, 보고서를 저장하라.
다음 목적함수 연구 초안은 별도 문서로 저장한다. 이번 E4는 성능 승격 실험이 아님을 표기하라.

정규화 전 비유한값·키 계약·동점 분해·산술 항등식·원래 E3 재현의 의미 있는 검사를 수행한다.
관련 Ruff/format, 전체 pytest와 diff-check를 실행하고 기존 범위 밖 오류를 구분한다.
원본 보존을 실제 전후 해시로 기록한다. 운영 registry/champion 관련 파일은 경로를 확인해
읽기 전용 해시로 봉인하고 비교한다. 기존 dirty work를 수정하지 않는다.

핵심 결과는 'raw 점수 차이', '보정이 만든 차이', '분리되지 않은 요인', '다음 실험의 정확한 변경점'으로
정리해 제출하라. 독립 검증 전에 후속 목적함수 학습이나 운영 승격으로 진행하지 마라.
