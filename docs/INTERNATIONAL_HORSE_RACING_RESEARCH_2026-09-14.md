# 해외 경마 예측·베팅 연구 지도 (2026-09-14)

## 조사 범위와 읽는 법

홍콩·미국/캐나다·영국·일본·호주/뉴질랜드의 경주 예측, 착순 결합확률, 시장배당, 베팅 최적화에 관한 **원전 논문·저자 원고·공식 데이터 문서·공개 코드**를 골랐다. 검색은 2026-09-14 기준 `horse racing forecasting`, `rank order probability`, `pari-mutuel optimization`, `favorite–longshot bias`, `interim odds`, `walk-forward backtest`, 국가별 공식 데이터 창구를 축으로 했다. 웹 전체의 모든 자료를 망라했다는 뜻은 아니다. 학술 논문의 결과도 당시 경마장·기간·승식·수수료에 묶이고, GitHub의 ROI는 작성자 자체 보고이지 독립 재현이 아니다. `환수율 = 총환급/총구매`, `순 ROI = 환수율−100%`로 구분한다. 아래의 ‘우리에게 적용’은 논문이 입증한 사실이 아니라 이 프로젝트를 위한 연구 제안이다.

**한 줄 결론:** 데이터 시점 관리 → 경주 내 확률/착순 분포 교정 → 당시 구매 가능한 가격과 비교 → 승식별 공동확률 및 풀 영향 반영 → 새 기간 전향 검증의 순서가 중요하다. 적중률만 높이거나 켈리 금액만 바꾸는 것으로는 장기 수익을 보장하지 않는다.

## 1. 기본 예측: 각 말의 우승확률

| 원전 | 무엇을 했나 | 해석·한계 | 우리에게 적용 |
|---|---|---|---|
| [Bolton & Chapman, *Management Science* (1986)](https://pubsonline.informs.org/doi/10.1287/mnsc.32.8.1040) | 과거 경주·기수·말 특성을 조건부/다항 로짓으로 결합하여 우승확률을 산출하고 시장 대비 수익 가능성을 시험했다. | 현재의 고차원 데이터나 시간순 실전 검증을 대체하지 않는 고전적 기준선. | RaceFit의 범주별 피처가 실제 시장확률 **이상의 잔여 정보**를 만드는지 단순 로짓 기준선과 비교. |
| [Benter, *Computer Based Horse Race Handicapping and Wagering Systems* (1994)](https://gwern.net/doc/statistics/decision/1994-benter.pdf) | 홍콩 경주의 기본(fundamental) 로짓 모델과 대중의 배당 암시확률을 2단계로 결합. 예측 확률의 구간별 실제 승률, 시장에 추가하는 정보량, 마권 기대수익과 풀 규모를 따로 검증했다. 저자는 5년 실제 운영에서 양의 성과를 보고했다. | ‘모델 적중률이 높다’와 ‘시장이 모르는 정보가 있다’를 구분한 것이 핵심. 역사적 성과가 한국의 현행 시장에서 재현된다는 뜻은 아니다. | RaceFit 단독·시장 단독·RaceFit+시장 세 모델을 동일한 **구매시점** 정보로 검증. 단순 블렌딩 계수도 학습기간 밖에서 고정. |
| [White, Dattero & Flores, *International Journal of Forecasting* (1992)](https://www.sciencedirect.com/science/article/pii/016920709290069L) | 여러 개의 기초 예측을 결합하여 상대 착순을 예측했다. | 앙상블은 오류가 충분히 달라야 효과가 있다. | V5, 제주 전용, 구간속도 모델 사이의 오류 상관을 먼저 보고 가중 결합. |
| [Rosenbloom, *Omega* (2003)](https://www.sciencedirect.com/science/article/pii/S0305048303000537) | 과거 Beyer 속도지수의 변동을 바탕으로 다음 경주의 속도를 확률적으로 모의해 우승확률을 추정하고 시장 기준과 비교했다. | 속도지수 자체가 국가·주로별로 동일하지 않고, 전개/상대 상호작용도 단순화된다. | 보정 주파기록의 평균 **뿐 아니라 분산**을 말별로 추정해 몬테카를로 경주 시뮬레이터의 기준선으로 사용. |
| [Lessmann, Sung & Johnson, *Journal of Prediction Markets* (2007)](https://www.ubplj.org/index.php/jpm/article/download/427/459/1346) | LS-SVR와 조건부 로짓을 결합; 모든 착순의 균등 오차보다 **상위 입상마 순위에 중점을 둔 NDCG**로 모델을 고르는 편이 유리하다고 보고했다. | NDCG가 좋아도 확률 교정이나 베팅 수익이 자동 개선되지는 않는다. | 현재 사용자의 top3·top5 관심에 맞춰 NDCG@3/@5를 보조 지표로 추가. 단, 우승/삼복 베팅용 확률은 별도 log loss·calibration으로 평가. |
| [Lessmann, Sung & Johnson, *International Journal of Forecasting* (2010)](https://www.sciencedirect.com/science/article/pii/S0169207009002143) | 2005–06년 홍콩 **1,000경주, 출전 12,902건, 기초변수 40개**에서 경쟁마 구성까지 반영하도록 RF를 변형; 기존 통계기법 대비 예측·수익상 이점을 보고했다. | 특정 기간과 홍콩 풀에서의 결과다. 저자들의 [후속 방법론 논문](https://www.tandfonline.com/doi/full/10.1057/jors.2010.192)은 사후에는 알지만 예측 당시 모르는 정보, 점추정, 재학습 누락이 수익 평가를 낙관적으로 만들 수 있다고 경고한다. | 말 단위 독립 분류보다 **경주 단위 정규화**, 상대마 피처, walk-forward 재학습을 비교. 오래된 연구 ROI를 현재 수익 가능성으로 인용하지 않기. |
| [Nakakita & Nakatsuma, *International Journal of Computer Science in Sport* (2023)](https://sciendo.com/2/v2/download/article/10.2478/ijcss-2023-0007.pdf) | 2016–18 JRA 1,800m 자료의 4,063두·143기수를 계층 베이지안으로 분석해 말 능력과 기수 효과를 동시에 추정했다. | 특정 거리·일본 자료. 기수의 완전한 인과 효과라고 단정할 수 없다. | 기수 단순 승률 대신 말 능력·기수 효과의 축소추정, 신마/장기휴양마에는 넓은 불확실성 부여. |

**핵심 비교 실험:** 우리 모델의 전체 AUC나 top1 적중률만 보지 말고, 경주별 log loss·Brier·구간별 교정과 시장 단독 대비 추가 정보량을 같은 미래 경주에서 비교한다. 이 구분은 특히 Benter의 2단계 실험과 맞닿는다.

## 2. 착순 전체와 복승·삼복·삼쌍의 결합확률

| 원전 | 핵심 아이디어 | 중요 주의점 |
|---|---|---|
| [Harville, *Assigning Probabilities to the Outcomes of Multi-Entry Competitions* (1973; SIAM 재수록)](https://epubs.siam.org/doi/pdf/10.1137/1.9780898718386.ch30) | 우승확률 `p_i`만으로 `P(i→j)=p_i p_j/(1−p_i)` 및 3착까지의 순서 확률을 만든다. 335개 실경주를 다뤘다. 수학적으로 Plackett–Luce/순차 선택과 연결된다. | 간단하지만 ‘1위 실력’만으로 2·3착의 다른 성향을 충분히 나타낸다는 보장은 없다. |
| [Henery, *JRSS-B* (1981)](https://academic.oup.com/jrsssb/article/43/1/86/7028103) | 각 말의 잠재 주파시간/경기력을 정규분포로 놓고 순서확률을 산출한다. | 계산은 더 복잡하지만 ‘이기거나 크게 지는 말’, 선행 실패 시 급락 등의 분산 차이를 허용할 여지가 있다. |
| [Lo & Bacon-Shone, *The Statistician* (1994), HKU 기록](https://hub.hku.hk/handle/10722/60981) | Harville과 Henery의 착순확률 적합도를 비교; Harville이 항상 최선은 아니라는 점을 보였다. | 어떤 대안이 나은지는 시장·승식·기간에 따라 달라진다. |
| [Lo, Bacon-Shone & Busche, *Management Science* (1995)](https://pubsonline.informs.org/doi/10.1287/mnsc.41.6.1048) | 정교한 착순확률을 기존 place/show 시스템에 결합. 미국·홍콩 자료에서는 낮은 위험에 수익 개선을 보고했으나 일본에서는 차이가 작았다. | 논문 초록도 **최종 베팅 데이터, 계산비용 0 가정**이라고 명시한다. 사전 실행 가능한 ROI와 다르다. |
| [Ali, *Journal of Applied Statistics* (1998), 저자 원문](https://www.stat.berkeley.edu/~aldous/157/Papers/ali.pdf) | 15,000경주 이상에서 normal/gamma 기반 2·3착 확률을 실측과 비교. 여러 모형이 높은 2·3착 확률을 과대, 낮은 확률을 과소 추정하는 경향을 보고했다. | 각 승식의 결합확률을 우승확률 하나에서 자동 파생하면 교정 오류가 커질 수 있다. |
| [Armerin, Hallgren & Koski, *Applied Artificial Intelligence* (2019), KTH 저장소](https://kth.diva-portal.org/smash/record.jsf?pid=diva2%3A1294371) | 예상 착순/모멘트에서 자리별 확률분포를 복원. 마차경주(harness racing)에서 로짓·시장보다 나은 성능을 보고했다. | **경주 형태가 한국 평지경마와 다르다.** 방법론 후보이지 성능 이식 근거는 아니다. |

우리의 실험은 `V5 점수 → PL/Harville`을 기준선으로 고정하고, `말별 잠재시간 정규/로그정규 + 불확실성 + 경주 공통 페이스 충격`을 몬테카를로로 생성해 비교하는 것이다. 예를 들어 `P(복승 {i,j})=P(i→j)+P(j→i)`, `P(삼복 {i,j,k})=6개 순열 합`을 계산한다. 동시에 1·2·3착 각 자리의 확률 합, 2·3착 구간별 교정, 정확 삼복/삼쌍 log loss를 검증한다. 단순 top3 포함률은 **조합 전체가 적중할 확률**과 다르다. 공동착순·취소·최소 출전두수·승식별 정산 규칙은 별도 처리한다.

## 3. 배당시장: 어디에 ‘우위’가 있는가

| 원전 | 관찰/주장 | 실무적 함의 |
|---|---|---|
| [Hausch, Ziemba & Rubinstein, *Management Science* (1981)](https://pubsonline.informs.org/doi/abs/10.1287/mnsc.27.12.1435) | 단승/연승/입상 풀의 가격 불일치와 자신의 구매가 배당을 낮추는 효과를 포함한 비선형 최적화. 당시 두 경마장 자료에서 양의 수익을 보고했다. | 승식 간 가격이 일관적인지 비교하고, 작은 풀에 큰 금액을 넣을수록 표시 배당보다 실수령이 낮아진다. 원전은 단승의 단순 favorite–longshot 편향만으로는 수수료를 넘기 어렵다고도 설명한다. |
| [Vaughan Williams & Paton, *Economic Journal* (1997)](https://academic.oup.com/ej/article/107/440/150/5144344) | 영국의 인기마 과소/저인기마 과대 구매(favorite–longshot bias)를 수요·공급 측면에서 분석. | ‘복병마’라고 무조건 가치가 생기지 않는다. 인기 순위보다 **교정된 확률 대비 실제 가격**이 핵심. |
| [Snowberg & Wolfers, *Journal of Political Economy* (2010)](https://www.journals.uchicago.edu/doi/pdfplus/10.1086/655844) | 대규모 자료로 인기–복병 배당 편향을 단승뿐 아니라 exacta/quinella/trifecta의 선택과 연결해 검사; 확률 오인 설명에 무게를 실었다. | 승식별 인기도/배당 교정과 ‘낮은 확률 과대평가’를 동시에 점검. |
| [Smith, Paton & Vaughan Williams, *Economica* (2006)](https://onlinelibrary.wiley.com/doi/pdf/10.1111/j.1468-0335.2006.00518.x) | 영국 북메이커와 Betfair 교환시장 자료를 비교해 교환시장의 거래비용/가격 효율성을 연구했다. | 외국의 고정배당·교환시장 결과를 한국 단일총합식 배당으로 곧장 전이하면 안 된다. |
| [Brown & Yang, *Review of Finance* (2017), UEA 원고](https://ueaeprints.uea.ac.uk/id/eprint/58626/) | 영국 9,562경주의 교환시장 거래를 분석; 거래량에 결과 관련 정보가 담기나 그 효과 상당 부분은 경기 진행 중에 집중. | 거래량 신호의 **관측 시각**이 중요하며, 경주 중 정보는 출발 전 베팅 신호가 아니다. |
| [Hanyu 등, *Journal of Behavioral Economics and Finance* (2025), 원문](https://www.jstage.jst.go.jp/article/jbef/18/Special_issue/18_18.S1.pp.S1-S4/_pdf/-char/en) | JRA-VAN의 마감 전 중간배당과 최종배당을 비교; 배당의 **막판 이동 경로**가 수익과 관련되고 최종 가격만으로 정보가 다 설명되지 않는다고 보고했다. | ‘한국 마권은 최종배당으로 정산’과 ‘최종배당을 보고 베팅할 수 있다’는 서로 다르다. **최종배당은 정산값**, 의사결정은 당시 스냅샷으로만 평가. |
| [Lessmann, Sung & Johnson, *Journal of the Operational Research Society* (2011)](https://www.tandfonline.com/doi/full/10.1057/jors.2010.192) | 시장 효율성 판단에서 예측 시점 이후 정보·배당 점추정·최근 자료를 반영하지 않은 모델 때문에 과대평가될 수 있음을 홍콩 자료로 시험. | 수익 백테스트의 첫 번째 테스트는 새로운 알고리즘이 아니라 **정보 공개시각 감사**다. |

마감 전 단승 5배가 **최종 5배로 확정된다**고 가정해서 `p×5>1`을 계산하면 부정확하다. 한국식 단일총합 배당에서는 `D_final`을 분포로 취급하고, 예를 들어 구매 시각의 배당·풀·변동성으로 `E[p×D_final | 당시 정보]`와 하방 시나리오를 추정해야 한다. 자신의 구매금액이 풀에서 차지하는 비율이 크면 그 금액을 반영한 배당으로 다시 계산한다. 영국 북메이커처럼 구매 시 고정되는 배당과 구분한다.

## 4. 배팅 조합·자금관리: 예측 이후의 별도 문제

| 원전 | 내용 | 안전한 해석 |
|---|---|---|
| [Kelly, *Bell System Technical Journal* (1956)](https://onlinelibrary.wiley.com/doi/abs/10.1002/j.1538-7305.1956.tb03809.x) | 알려진 확률과 가격에서 장기 로그 자산성장률을 극대화하는 금액 배분의 출발점. | **양의 기대값과 정확한 확률**을 전제로 한다. 확률 오차가 있으면 권장액이 과격해진다. |
| [Benter (1994), 베팅·이색마권 절](https://gwern.net/doc/statistics/decision/1994-benter.pdf) | `예상 환급배수 = 결합확률 × 예상 배당`; 1배 초과 조합을 선별, 부분 켈리와 풀 영향 한도. 서로 가치 있는 두 말의 복승 조합이 각 단승보다 나은 기대값이 되는 예시를 제시했다. | ‘마권을 많이 사면 안전하다’가 아니라 **각 조합의 확률과 가격을 따로 확인**하는 방식. 부분 켈리도 음의 기대값을 양수로 바꾸지 못한다. |
| [Lo 등 (1995)](https://pubsonline.informs.org/doi/10.1287/mnsc.41.6.1048) | Harville보다 적합한 착순확률이 place/show 베팅의 위험·수익을 개선할 수 있다고 실험. | 한국 복연/삼복에 쓰려면 해당 승식 공동확률과 **그 승식의 가격**을 직접 교정·검증해야 한다. |
| [Metel, *Kelly betting on horse races with uncertainty in probability estimates* (2017), 원고](https://arxiv.org/abs/1701.02814) | 로짓 계수/확률 추정오차를 고려한 켈리 변형을 시뮬레이션. | 실경주 양의 ROI 증거가 아니라 금액 결정의 **모형 위험 관리 방법**이다. |
| [Busseti, Ryu & Boyd, *Journal of Investing* (2016), 저자 페이지](https://web.stanford.edu/~boyd/papers/kelly.html) | 특정 자산 낙폭을 초과할 확률에 제약을 건 켈리 최적화. | 수익 엣지가 검증된 뒤에야 적용할 자금관리 기술. 같은 경주 여러 마권은 손익이 강하게 연동되므로 공동 시나리오로 계산. |
| [Uhrín 등, *Optimal sports betting strategies in practice* (2021), 원고](https://arxiv.org/abs/2107.08827) | 경마 포함 3종 스포츠에서 고정액, 켈리, 분산/낙폭 제약과 변형을 동일 프로토콜로 비교; 보수적 제약이 과도한 위험을 줄이는 것을 보였다. | 자금배분 성능은 **주어진 확률·가격의 품질**에 의존한다. 한국 승식과 합계식 배당에 대한 직접 검증은 별도. |

조합을 사전 확률순으로 3장·5장·10장 더 늘리면 **경주 적중률**은 오르지만 비용도 같이 증가한다. 승식 포트폴리오의 판단식은 `E[총환급−총지출 | 구매시점 정보]`이며, 위험은 최대 손실·일별 낙폭·같은 말에 집중된 마권의 상관관계로 본다. 실측 수익이 없는 동안 ‘고확신 경주’와 ‘수익 경주’를 같은 뜻으로 쓰지 않는다.

## 5. 구간속도·주로·전개: 기초모델에 넣을 만한 해외 연구

- [Mercier & Aftalion, *PLOS ONE* (2020)](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0235024): 프랑스 경주의 속도 자료를 사용해 에너지·추진력·코너·고도에 따른 최적 페이스를 수학적으로 모형화했다. 실전 우승 예측 성적 논문은 아니다. 우리 모델에서는 `초반 페이스 압력 × 후반 감속률 × 코너 손실`의 상호작용 가설을 설계할 근거다.
- [Legg, Gibson & Rogers, *Animals* (2026)](https://www.mdpi.com/2076-2615/16/10/1433): 뉴질랜드 평지 18시즌·약 20만 출전 자료에서 거리, 주로 상태, 부담중량과 초반/마지막 600m 속도의 연관을 분석했다. 관측된 연관이 곧바로 다음 경주 예측 이득이나 인과 효과는 아니다. 거리·주로별로 후반속도를 **초반 속도/그날 주로와 함께** 보정할 가설이 된다.
- [Equibase의 GPS 결과표 발표](https://cms.equibase.com/node/172025): 일부 북미 경주에서 0.5초 간격의 위치 자료를 제공한다고 설명한다. 전개·실주행거리 측정의 장기적 방향을 보여주지만 한국 데이터에 같은 해상도가 있는지는 별도 확인이 필요하다.

‘외곽 게이트 선행마가 단독으로 여유 있게 붙는가’, ‘모래 맞은 뒤 주행이 꺾였는가’ 같은 현상은 고정 규칙보다 **실제 위치/분절기록에서 관측된 사건과 불확실성**으로 표현해야 한다. 출발 게이트·선행마 수·경주 두수·첫 코너 거리의 상호작용을 조건부로 점검하고, 데이터가 없는 사건을 확정 특징으로 채우지 않는다.

## 6. 공개 프로젝트: 재현 가능성과 경고 사항

| 프로젝트 | 가져올 만한 부분 | 검증 등급/주의 |
|---|---|---|
| [PeterLiuLiuLiu/Horse-Racing-Prediction-HKJC](https://github.com/PeterLiuLiuLiu/Horse-Racing-Prediction-HKJC) | Benter 로짓을 참고한 홍콩 데이터 수집·확률 분석의 초기 구현. | README 자체 설명이 과거 수집 경로의 변경을 경고한다. 3커밋 규모이며 독립 ROI 증거 없음. **개념 참고용**. |
| [catowabisabi/horse-racing-model-training](https://github.com/catowabisabi/horse-racing-model-training) | HKJC LightGBM/XGBoost, 무배당 기본모델, 결합·켈리·복승 시뮬레이터와 OOS 평가 코드. 자체 보고는 2017년 복승 +7.9% ROI, 2018년 상반기 452장 OOS +2.6%. | 작성자도 후자의 작은 이익과 일부 필터의 OOS 붕괴를 명시. 수집 시각·스테이크·선택 기준의 독립 감사를 거치기 전에는 **수익 사례가 아닌 재현 후보**. `max_final_odds` 필터는 실전 진입 조건으로 쓸 수 없음. |
| [tsukasaI/keiba-ai](https://github.com/tsukasaI/keiba-ai) | JRA 쌍승 중심, 확률 교정·복승/삼복 확률·walk-forward 백테스트와 테스트 코드. | README가 +19.3% ROI를 **경주 후/추정 배당**에서 얻었고 실제 조합배당 수익은 미검증이라고 명시. 수익 수치는 채택 금지, 아키텍처 참고. |
| [davidklan-png/keibamon](https://github.com/davidklan-png/keibamon) | 원본 보존, `available_at`이 있는 배당 스냅샷, 시점 위반 시 실패하는 검증, 시간순 재현 원장. | 현재는 ROI를 의도적으로 미룬다고 밝힌다. 우리 데이터 파이프라인·누수 검사에 특히 유용. |
| [gmalbert/horse-racing-predictions](https://github.com/gmalbert/horse-racing-predictions) | 영국 경주의 앙상블, 보정, 날씨, walk-forward 구조. | 실제 `market_odds` 결합 전 가치베팅 백테스트를 비활성화했다고 명시. **가격 없는 모형 환수 시뮬레이션**을 실제 ROI로 읽지 말 것. |
| [mervees/Horse-Racing-Analytics](https://github.com/mervees/Horse-Racing-Analytics) | 사전/사후 컬럼 분리, 누수 테스트, de-vig, LambdaRank, ROI 시뮬레이터 설계. | 번들 자료가 합성자료이며 README도 수익 증거가 아니라고 밝힌다. **교육용 기준 구조**. |
| [dickreuter/betfair-horse-racing](https://github.com/dickreuter/betfair-horse-racing) | 1분 간격 Betfair 가격 시계열, back/lay 수수료·손익 모델, 자동화 구조. | 현재 코드를 그대로 신뢰하기 어렵다. README 예제에 `starting_price`와 `winner`가 동일 분석 테이블에 나타나므로 입력 피처와 정산 컬럼을 구분하는 **직접 코드 감사**가 필요하다. 한국 합계식 마권과 시장 구조도 다르다. |

GitHub는 구현 아이디어의 출처로 좋지만 ‘저장소에 +ROI가 적혀 있다’는 것이 **독립적 미래 실전 수익 증명**은 아니다. 특히 다수 필터를 시험하고 가장 좋은 것만 게시하면 선택 편향이 생긴다.

## 7. 해외 공식 데이터·API 지형

| 지역 | 확인된 공식 창구 | 무엇에 쓸 수 있나/제약 |
|---|---|---|
| 홍콩 | [HKJC 공식 사이트맵](https://www.hkjc.com/en-us/sitemap) | 출전표, 결과·환급, 말/기수/조교사·조교·트라이얼·영상·실시간 배당 화면을 구분해서 제공한다. 웹 접근 가능성과 **대량 수집/재배포 권한은 별개**다. |
| 영국/호주 등의 거래소 | [Betfair Exchange API](https://developer.betfair.com/exchange-api/), [공식 시계열 데이터 안내](https://support.developer.betfair.com/hc/en-us/articles/360000402211-How-do-I-download-view-Betfair-Historical-Data), [필드 명세](https://historicdata.betfair.com/Betfair-Historical-Data-Feed-Specification.pdf) | 사전 호가/거래량/실제 시점 가격의 연구에 유리. 역사자료는 요금제별 빈도·필드가 다르며 공식 명세상 2015년 5월부터, 호주/뉴질랜드는 2016년 10월부터. 거래소 가격과 한국 최종 환급배당은 다르다. |
| 일본 | [JRA-VAN DataLab/JV-Link](https://jra-van.jp/dlb/sdv/about.html) | 과거 자료와 실시간 배당·마체중, 개발 SDK/데이터 명세를 공식 제공하는 유료 서비스. 라이선스·접근 환경을 확인해야 한다. |
| 미국 | [Equibase 결과표](https://tvg.equibase.com/static/chart/summary/), [공식 past-performance 상품 안내](https://tvg.equibase.com/newsite2/PremiumPP.cfm) | 경기 결과, 속도·페이스 지수, 불리 기록 등의 예시. 상세 데이터는 상품·계약 조건이 있을 수 있다. |
| 호주 | [Racing Australia 공식 데이터 사업 설명](https://www.racingaustralia.horse/aboutus/default.aspx) | 전국 출전·형태·결과의 공식 데이터 관리/상업 제공. 사용권 검토 필요. |

이 자료들은 **우리 한국 경마를 예측할 해외 훈련 데이터**로 바로 합치는 것보다, 방법론 검증과 데이터 시점 설계를 비교하는 데 우선 가치가 있다. 마종·거리·주로·경주 운영·승식 환급률이 달라 원자료를 섞으면 분포 이동이 커진다.

## 8. RaceFit V5에 적용할 연구 순서와 통과 기준

1. **시점 계약 고정:** 출전표·취소·마체중·주로·조교·배당 원자료에 `published_at`, `available_at`, `prediction_as_of`를 남긴다. T−30/10/5/1분 각 단계 예측과 가격을 별도 저장한다. 사후 확정배당은 정산에만 쓴다.
2. **시장 대비 예측 품질:** 서울/부경/제주를 분리해 RaceFit V5, 공개된 배당 단독, 블렌딩을 같은 기간에 비교. 기본모델은 시장 없이 학습한 버전도 유지해 독립 정보량을 측정한다. 경주 단위 log loss, Brier, top1/top3 NDCG, 1·2·3착 자리별 교정과 `시장 단독 대비 개선량`을 보고한다.
3. **착순 모형 3파전:** PL/Harville, 말별 잠재시간 분포, `경주 페이스 공통충격+말별 이분산` 모델. 2·3착 및 정확 복승/삼복/삼쌍 확률의 예측 적합도를 독립 테스트에서 비교한다. 더 복잡한 모델은 충분한 재현 개선이 있을 때만 채택한다.
4. **승식별 가격/실행:** 조합마다 원칙적으로 `E[적중지시값 × D_final | 당시정보, 해당 매수액]−1`을 공동 시나리오로 산출하고 배당·확률의 하방도 확인. 적중과 후행 배당이 조건부 독립이라는 근거가 있을 때만 이를 `p_joint × E[D_final]−1`로 분해한다. `미구매`를 반드시 선택지로 둔다. 외국의 고정배당 결과를 한국 합계식에 직접 대입하지 않는다.
5. **전향 기록:** 소수의 사전 고정한 규칙으로 새 경주를 종이마권 검증한다. 경주·일자 묶음 수익분포, 가장 큰 환급 제거 후 ROI, 다른 경마장/계절 결과, 최대 낙폭, 실시간 구매 가능성을 함께 보고한다. 탐색한 2025/2026 경주는 새 검증 표본으로 재사용하지 않는다.

**현재 프로젝트와의 대조:** [내부 2025·2026 전략 진단](BETTING_STRATEGY_2025_2026_2026-09-13.md)은 공통 4,025경주의 V3 시간순 예측에서 20개 고정 규칙·3개 확신도 필터 모두 두 해 동시 환수율 100%를 넘지 못했다고 보고했다. 이는 **현행 V5의 성능 측정이 아니고**, 해외 논문의 흑자 수치를 우리 결과로 이식할 수 없음을 일깨우는 기준선이다. 어떤 승식 조합이 실제 우위가 있는지는 가격 시점이 확보된 새 자료로 시험해야 한다.

## 우선 읽을 6편

1. [Benter 1994](https://gwern.net/doc/statistics/decision/1994-benter.pdf) — 기본모델+시장 결합과 가격/풀 제약의 원형.
2. [Lessmann 등 2010, *JORS*](https://www.tandfonline.com/doi/full/10.1057/jors.2010.192) — 과대평가되는 백테스트를 피하는 실험 설계.
3. [Lo·Bacon-Shone·Busche 1995](https://pubsonline.informs.org/doi/10.1287/mnsc.41.6.1048) — 2·3착 결합확률을 개선하는 이유와 한계.
4. [Lessmann·Sung·Johnson 2007](https://www.ubplj.org/index.php/jpm/article/download/427/459/1346) — 상위 입상 순위 목표를 별도로 평가하는 방법.
5. [Hanyu 등 2025](https://www.jstage.jst.go.jp/article/jbef/18/Special_issue/18_18.S1.pp.S1-S4/_pdf/-char/en) — 마감 전 배당과 확정배당의 차이.
6. [Hausch·Ziemba·Rubinstein 1981](https://pubsonline.informs.org/doi/abs/10.1287/mnsc.27.12.1435) — 승식 간 가격불일치와 자기 구매의 배당 영향.

**연구윤리/검증 메모:** 위 논문의 ‘수익’은 각 원전이 보고한 수치이지 여기에서 재현한 결과가 아니다. 공개 저장소는 README 및 공개 코드 구조를 확인한 범위로만 기술했으며 전체 코드·데이터의 독립 재현 감사는 하지 않았다. 한국 실전 베팅은 수수료, 최종배당 변동, 풀 깊이, 취소/공동착순 정산, 지역별 규정까지 반영해야 한다.
