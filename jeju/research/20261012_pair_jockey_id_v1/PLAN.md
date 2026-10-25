# 제주 pair jockey-ID categorical main-effect 단일 비교

상태: 사전 설계와 label-free source preflight 완료, root의 구체적 fit 승인을 대기한다. 후보 적합·평가 예측·성과값은 승인 전 생성하지 않는다.

## 질문과 고정 범위

저장 F1_STYLE6 말 점수, 20개 style pair basis, 최근 365일 기수 rolling feature, pair labels·코호트·평가 분할을 고정한다. 기존 `20261012_pair_jockey_basic_v1`의 저장 rolling candidate를 기준 비교로 재사용하며 그 계수를 다시 적합하지 않는다. 한 arm에서 rolling feature까지 포함한 기존 21개 β/γ와 H1-only 공식 기수 ID categorical main effect를 joint BCE fit한다.

각 무순서 pair의 선형예측자는 다음과 같다.

```text
eta_ij = logit(p0_ij) + z_style20·beta + z_rolling·gamma + W_jockey(i,j)·theta
```

기수 ID는 공식 event ID만 사용한다. ID 숫자 값이나 이름은 수치 입력으로 사용하지 않는다. 각 평가 fold에서 ID vocabulary는 그 fold의 H1 event ID 집합만으로 만들며 정렬된 39개 ID를 유지한다. H1에서 본 적 없는 H2/evaluation ID는 categorical runner basis 0으로 처리한다. 과거 기수 효과 연구의 계수, 전체기간 vocabulary나 미래 ID 정보를 복사하지 않는다.

## 범주형 basis와 사전 고정 처리

무순서 pair `(i,j)`와 H1 ID `r`에 대해 `u_r=I(ID_i=r)+I(ID_j=r)`, `K=I(ID_i∈H1 vocab)+I(ID_j∈H1 vocab)`로 둔다. H1의 경주 균등(pair 내 평균 후 경주 평균)으로 `mu_r=E_H1[u_r]`, `pi_r=mu_r/2`, `sigma_r=sqrt(E_H1[(u_r-mu_r)^2])`를 구하고 다음 열을 만든다.

```text
W_r = (u_r - K*pi_r) / sigma_r
```

H1에서는 모든 ID가 known이므로 `K=2`, 각 열이 경주 균등 평균 0·표준편차 1이다. 이 효과 코딩은 각 known runner의 중심화 효과를 pair 합으로 표현한다. unknown runner는 모든 categorical 열에서 정확히 0이고, mixed known/unknown pair에는 known runner의 중심화 효과만 들어간다. `sigma<=1e-12`인 열은 효과 0으로 제외한다. 사전 source census에서는 각 fold 39개 열이 모두 유효하다.

H1에서 관측된 모든 ID를 사용하며 희귀 ID pooling, 계수 탐색·별도 shrinkage tuning은 하지 않는다. H1 최소 관측 출전은 52회다. 저장 21개 moments는 그대로 재사용한다. 21개 기존 계수와 모든 categorical 계수를 `lambda=1` race-equal pair BCE, no explicit intercept, 동일 L-BFGS-B 옵션으로 함께 적합한다. ridge는 표준화 basis 계수에 적용된다. 따라서 원시 per-ID 효과 `alpha_r=theta_r/sigma_r - sum_k(pi_k*theta_k/sigma_k)`의 유효 penalty는 `sigma`와 support에 따라 다르며, raw effect가 ID별 동일 강도로 shrink된다고 해석하지 않는다. `alpha`는 weighted-centered 관측 연관성이지 인과효과가 아니다.

## 분할·fit 예산·평가

기존 확장 pair 연구의 고정 fold를 사용한다. H1 2,147/2,818/3,458경주, H2 336/311/325경주, evaluation 637/654/488경주다. H1의 과거 score provider 역할과 연도별 계보, 2일 purge, 2019 시작·직전연도 1–6월 범위를 유지한다. 승인 뒤 H1 3회와 candidate H2 positive-slope Platt map 3회만 수행한다. saved baseline·F1_STYLE6·기타 comparator는 fit 0회다.

Primary 비교는 새 candidate에서 저장 rolling candidate의 429/1,779를 뺀 값이다. Secondary gate는 raw F1_STYLE6 score Top2 429/1,779 대비다. 두 비교 모두 점추정과 기존 2,000회 경주일 bootstrap 95% CI 하한이 양수여야 gate 통과로 표시한다. expanded 427, old direct 426, joint marginal 434, maximum joint 422, matched maximum joint 429 등 기존 저장 comparator도 보존한다. report에는 확률 Brier/log loss와 calibration, 선택확률 `>=0.20` 진단, 연도·거리 결과, 선택 변경 경주의 gains/losses/ties 및 date CI를 포함한다. 성과 확인 뒤 설정을 변경하거나 추가 arm을 만들지 않는다.

원천은 2026-09-19까지 정상완주 완전 편성 캐시다. H1 feature 결과로부터 같은 경주 label을 기수 category vocabulary나 moments 계산에 쓰지 않는다. 하지만 과거 결과 게시시각이 없고 현행 event jockey snapshot을 후향 연결하므로 timestamp 가용성은 보장하지 않는다. 평가기간은 반복 개발자료이며 독립 미래 holdout이 아니다. 원천·분할·결과 저장은 이 폴더에 한정한다. 운영·DB·중앙 publication files는 수정하지 않는다.

