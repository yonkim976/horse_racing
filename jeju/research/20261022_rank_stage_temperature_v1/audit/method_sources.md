# 순위별 temperature 가설의 1차 방법 근거

작성일: 2026-10-22. 이 메모는 구조적 방법 근거만 확인한다. 외부 경주 데이터 수집, 적합, 예측, 수익 또는 성능 비교는 하지 않았다.

## 확인한 1차 자료

1. David A. Harville, [“Assigning Probabilities to the Outcomes of Multi-Entry Competitions”](https://doi.org/10.1080/01621459.1973.10482425), *Journal of the American Statistical Association* 68(342), 1973, 312–316. [공식 저널 서지·초록](https://www.tandfonline.com/doi/abs/10.1080/01621459.1973.10482425). 저널 초록은 말 경주의 순위 확률을 win probability만으로 구성하는 가정을 소개하고 335개 경주에 적용했다고 명시한다. 이전 판본에 연결했던 `https://www.nber.org/papers/w15923.pdf`는 Harville 논문이 아니다. 해당 번호는 Erik Snowberg와 Justin Wolfers의 2010년 [*Explaining the Favorite-Longshot Bias: Is it Risk-Love or Misperceptions?*](https://users.nber.org/~jwolfers/Papers/Favorite_Longshot_Bias%28NBER%29.pdf)로 확인되어 인용에서 제거했다. Harville 원문 PDF는 이번 검토에서 서지와 대응하는 접근 가능한 링크를 검증하지 못했으므로 더 이상 PDF 사본으로 제시하지 않는다. Harville의 원 논문은 순위 분해를 정당화하는 모델 가정이지, 순위별 별도 온도에 대한 근거는 아니다.

2. R. L. Plackett, [“The Analysis of Permutations”](https://doi.org/10.2307/2346567), *Journal of the Royal Statistical Society: Series C (Applied Statistics)* 24(2), 1975, 193–202. [Oxford Academic 공식 서지·초록](https://academic.oup.com/jrsssc/article/24/2/193/6953554), [논문 스캔 사본](https://math-papers.github.io/2024/%2800285%29%20The%20Analysis%20of%20Permutations%20%281974%29.pdf). 스캔 첫 면은 `Appl. Statist. (1975), 24, No. 2, p. 193`, 저자, 제목을 명시하고 §1에 아래 식을 싣는다. 파일명에는 `(1974)`가 있으나 공식 서지의 권호는 1975년이다. 공식 article history의 received/accepted는 1974년으로 표시된다. 파일명 자체를 출판 연도의 근거로 사용하지 않는다. PDF 호스트는 공식 저널이 아닌 복제본이므로 서지 확인은 Oxford Academic 항목을 기준으로 한다.

## 현재 Q와의 관계

정규화된 점수 기반 1착 확률을 `p_i(T)=exp(s_i/T)/Σ_{h∈R}exp(s_h/T)`라 두면 Plackett의 식은

`Q_T(i,j,k) = p_i(T) · p_j(T)/(1−p_i(T)) · p_k(T)/(1−p_i(T)−p_j(T))`.

이는 기존 승인 기준선 문서의 전체 출전집합 순차 Q와 대수적으로 같다. 해당 계획은 모든 단계에 동일한 `T`를 사용한다([기준선 PLAN, 확률 정의](../../20261022_joint_wager_baseline_v1/experiment/PLAN.md#L26)). 따라서 공유 `T` Q는 Harville/Plackett형 순차 선택 구조에 raw score의 softmax 변환을 연결한 것이다. 원 논문은 이 연결의 구조를 뒷받침하지만, 제주 자료에서의 calibration 품질을 보증하지 않는다.

순위별 후보를 쓰면 각 단계에서 별도로 재정규화한다.

`Q_{T1,T2,T3}(i,j,k) = [exp(s_i/T1)/Σ_{h∈R}exp(s_h/T1)] · [exp(s_j/T2)/Σ_{h∈R\{i}}exp(s_h/T2)] · [exp(s_k/T3)/Σ_{h∈R\{i,j}}exp(s_h/T3)]`.

`T1=T2=T3`일 때만 기존 공통-temperature 식으로 환원된다. 서로 다른 `T_r`는 동일 위험집합의 남은 말 가운데 점수 비례로 한 마리씩 뽑는 순차 PL 골격을 보존하지만, 모든 단계에 공통인 하나의 worth/probability vector를 재정규화하는 원 논문 모형과는 다른 단계 의존 확장이다. 두 1차 자료 모두 단계별 temperature 분리, 그 식별성, 제주 경주에서의 이점은 제안하거나 검증하지 않는다.

## 적용 한계와 설계 경계

- 이 근거는 top-3 순서의 정규화된 full-field 공동분포 구조만 지지한다. 실제 승식 발매·정산, 동착, 취소 및 완주 관측 규칙은 별도 데이터 계약으로 다뤄야 한다.
- fixed Top3 집합 내부의 순서 모델에서는 1·2착을 고르면 3착은 남은 한 마리로 결정되므로 별도 `T3`가 식별되지 않는다. 순위별 세 온도 가설은 전체 출전집합이 매 단계 위험집합에 남아 있는 Q에만 해당한다([현재 방법 비교](README.md#L10)).
- Harville의 원문 적용 데이터나 논문에 언급된 다른 경기 결과를 본 연구의 제주 코호트, prior, 성능 기대치로 전이하지 않았다. stage-specific 확장은 새 가설이며, 검증 결과가 아니다.
- 코드·원천 점수 계약은 바꿀 필요가 없다. 입력은 기존 고정 `score`와 동일 race/runner key를 유지하고, 온도 3개는 이 점수에서 만드는 순차 분포의 후처리 적합 파라미터다. 다만 적합 기간/목표/제약은 실행 전에 별도 사전등록 및 감독 승인이 필요하다.
