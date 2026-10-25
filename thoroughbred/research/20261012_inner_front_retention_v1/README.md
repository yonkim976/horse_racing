# 내측 초반 경쟁·앞선 진입 확률·종반 유지력을 결합한 모델

2026-10-12. **선택22입력 모델보다 입상확률 오차와 축복승3조합은 개선됐다. 축마 입상률도 세 연도에서 올랐지만, 합산 축마·복승1조합 개선은 불확실하다. 이전103입력 연구모델을 전반적으로 넘지는 못했다.** 새55입력은 연구 후보로 보존하고 운영·선택22·미래검증계약은 유지한다.

## 비교 대상과 지표

서울·부산 같은4,799경주/50,754출전이다.2024년1,761경주,2025년1,750경주,2026-09-20까지1,288경주. 관측연구45의4,827경주와는 능력모형의 유효결과/카드 필터가 다르다. 신마·구간기록결측도 이번 평가에서 제외하지 않았다. 연구의 기존 기준은 사용자가 선택한 **월·게이트·부담중량22입력**이고 운영모델 자체의 교체 시험으로 해석하지 않는다.

- axis_top3:예측1위 축마가 실제3위이내. axis_top2:같은축마가2위이내.
- quinella_one:예측상위2두가 실제1·2착을 순서무관 모두 차지한 복승1조합.
- axis_next3:축마1두를 고정하고 예측2~4위와 짝지은 **복승3조합 중 적중**. 삼복3조합이나 3두가 함께 입상한 비율이 아니다.
- top5_all:예측상위5두 안에 실제입상3두 모두 포함. trio6:전체삼복조합의 말점수합 상위6조합 중 실제삼복 적중.6두선정과다르며 배당/수익률평가가아니다.
- Brier:예측입상확률과 실제입상여부의 제곱오차 평균, 작을수록좋다. 입상라벨 모형에서 말별 입상확률합은경주당3,상위2착라벨은합2다. 축우승확률을직접학습한모형이아니다.

## 추가 입력과 시점

22→37→39→55의 고정 세 단계다. [전체열계약](outputs/feature_contract.json)에55개를보존했다.

**초반 경쟁15개:** 최근실제3슬롯 보정초반평균과최근5지원수,게이트상대위치,내측두수/초반지원수,내측최고및평균시간−자기시간,내측더빠른말수/±0.15초근접수,동일거리최근5슬롯초반평균/지원수/내측최고대비차이/내측지원수,과거첫조율/지원수. 동일거리평균은기록2개이상,내측차이는내측3두·80%지원조건이며 일반최근3채널은관측수가작아도차이를계산하고지원수를함께둔다. 게이트번호결번유지,실제내·외측주행경로아님.

**앞선 확률2개:** 첫통과조진입확률과지원표시. 첫조여러두가능,단독선행확률과다르고합1을강제하지않는다.37입력으로2020~2026각년도이전자료만보조모형7개학습했다.2017~2019는이확률결측보존. 현재실제초반이나현재통과조를입력하지않는다.

**종반 유지12개:** 같은과거출전의초반/G3F/G1F를짝지어,첫조진입시G3F·G1F상대우위/관측수/동시유지율4개,상대평균보다초반이빨랐을때같은4개,외측이면서초반빨랐을때G3F·G1F상대우위/관측수3개,전체유효짝수1개다. 각구간상대5두·80%관측과정상결과요구. 평균n/(n+3)수축,유지율(유지+1)/(n+2),사건0회면평균/비율결측이다. 첫조는공식통과조,빠른초반은상대시간기준으로구분한다. 생리적힘사용이나'무리했다'는의도는관측하지못한다.

**관계4개:** 앞선확률×첫조G3F/G1F우위2개,앞선확률×내측빠른상대관측비율×빠른초반G3F/G1F우위2개. G1F는G3F에포함되므로두초손실을더해감점하지않는다. 외측일괄감점도없다.

기록은기존section_style의연도이전자료로적합한함수율·월·게이트보정값을동결재사용했고미지원은원시초를유지했다. 게이트보정이후의추가전개설명력을시험한것이다. 별도서울구간후속02C의새보정은동시에반영하지않았다. 현재기수/조교사/배당/실측전개/실측함수율은새입력에없다. 과거는T−2/730일/실제최근5전,결측을건너뛰어5개를채우지않는다.

입력관측범위:

| year | rows | races | early | same_inner_gap | front_keep | fast_keep | outerfast_keep |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2024 | 18459 | 1761 | 17291 | 1156 | 9338 | 14588 | 9515 |
| 2025 | 18657 | 1750 | 17548 | 1224 | 9209 | 14798 | 9508 |
| 2026 | 13638 | 1288 | 12838 | 884 | 6625 | 10704 | 6944 |

동일거리내측차이는지원이엄격해전체의약6%뿐이다. 일반초반채널/결측표시로나머지말도남겼다. 앞선후유지경험과빠른초반유지경험은서로다른조건이다.

## 학습 방법

능력학습은2017년부터,이전2010~2016은기존이력워밍업이다. 연도Y의모형은Y−3까지최초학습,Y−2조기종료선택후재학습,Y−1조합온도교정,Y시험. LightGBM이진/learning_rate0.04/leaves15/minleaf150/L2=5/max200/earlystop25/seed20261004/1두수가중을기존과동일하게고정했다. 앞선보조는각자기연도이전2017년이후자료/180회/L2=10/seed42다. 자기연도정답으로만든앞선확률을능력훈련행에넣지않았다.

입상라벨3후보×서울·부산×3연도=18능력모형. 상위2착라벨55입력도6개추가,최종저장능력24개+앞선7개다. 기존baseline22와previous_full103은동결예측재사용. 결과후열선별/임계값검색/최적후보선택은하지않았다.

## 입상라벨 주 후보: 연도별 기존22 → 결합55

| period | n | axis_top3 | axis_top2 | quinella_one | axis_next3 | Brier |
| --- | --- | --- | --- | --- | --- | --- |
| 2024 | 1761 | 58.77% → 60.99% | 45.77% → 47.36% | 11.58% → 12.55% | 25.44% → 27.20% | 0.178801 → 0.178152 |
| 2025 | 1750 | 59.03% → 59.37% | 47.66% → 47.26% | 11.26% → 11.31% | 25.43% → 26.80% | 0.177391 → 0.176314 |
| 2026 | 1288 | 61.65% → 61.96% | 49.22% → 49.61% | 13.59% → 13.66% | 28.34% → 29.11% | 0.176177 → 0.173244 |
| all | 4799 | 59.64% → 60.66% | 47.38% → 47.93% | 12.00% → 12.40% | 26.21% → 27.57% | 0.177583 → 0.176165 |

전체축3위이내2,862→2,911경주로49경주증가,축2위이내2,274→2,300으로26증가,복승1조합576→595로19증가,축복승3조합1,258→1,323으로65증가했다. 축3위추가적중419경주와기존적중상실370경주가함께발생했다.2024순증39경주,2025는6경주,2026은4경주로효과크기는일정하지않다.

같은경주차이의경주일군집bootstrap2,000회/seed20261012/95%CI다. 적중지표는%p,오차는원단위이며음수Brier가개선이다.

| variant | reference | period | metric | n | difference | lo | hi | units |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| combined55 | baseline22 | all | axis_top3 | 4799 | 1.021046 | -0.162934 | 2.265617 | percentage_points |
| combined55 | baseline22 | all | axis_top2 | 4799 | 0.541780 | -0.683973 | 1.749619 | percentage_points |
| combined55 | baseline22 | all | axis_win | 4799 | 1.208585 | 0.184422 | 2.264768 | percentage_points |
| combined55 | baseline22 | all | quinella_one | 4799 | 0.395916 | -0.416630 | 1.204883 | percentage_points |
| combined55 | baseline22 | all | axis_next3 | 4799 | 1.354449 | 0.408089 | 2.347323 | percentage_points |
| combined55 | baseline22 | all | top5_all | 4799 | 0.645968 | -0.385210 | 1.693072 | percentage_points |
| combined55 | baseline22 | all | top3_all | 4799 | 0.333403 | -0.332611 | 1.004127 | percentage_points |
| combined55 | baseline22 | all | trio6 | 4799 | 0.770994 | -0.126656 | 1.654809 | percentage_points |
| combined55 | baseline22 | all | target_brier | 4799 | -0.001418 | -0.001951 | -0.000893 | loss |
| combined55 | baseline22 | all | set_logloss | 4799 | -0.029884 | -0.041832 | -0.017634 | loss |
| combined55 | baseline22 | 2024 | axis_top3 | 1761 | 2.214651 | 0.057137 | 4.297248 | percentage_points |
| combined55 | baseline22 | 2024 | axis_top2 | 1761 | 1.590006 | -0.467947 | 3.727171 | percentage_points |
| combined55 | baseline22 | 2024 | axis_win | 1761 | 1.192504 | -0.712687 | 3.121500 | percentage_points |
| combined55 | baseline22 | 2024 | quinella_one | 1761 | 0.965361 | -0.441244 | 2.426561 | percentage_points |
| combined55 | baseline22 | 2024 | axis_next3 | 1761 | 1.760363 | 0.164647 | 3.412412 | percentage_points |
| combined55 | baseline22 | 2024 | top5_all | 1761 | -0.454287 | -2.242687 | 1.214628 | percentage_points |
| combined55 | baseline22 | 2024 | top3_all | 1761 | 0.227144 | -0.696815 | 1.184901 | percentage_points |
| combined55 | baseline22 | 2024 | trio6 | 1761 | -0.511073 | -1.912601 | 0.968772 | percentage_points |
| combined55 | baseline22 | 2024 | target_brier | 1761 | -0.000649 | -0.001523 | 0.000213 | loss |
| combined55 | baseline22 | 2024 | set_logloss | 1761 | -0.006522 | -0.025892 | 0.012063 | loss |
| combined55 | baseline22 | 2025 | axis_top3 | 1750 | 0.342857 | -1.756474 | 2.335029 | percentage_points |
| combined55 | baseline22 | 2025 | axis_top2 | 1750 | -0.400000 | -2.340651 | 1.528026 | percentage_points |
| combined55 | baseline22 | 2025 | axis_win | 1750 | 0.742857 | -0.904096 | 2.380013 | percentage_points |
| combined55 | baseline22 | 2025 | quinella_one | 1750 | 0.057143 | -1.336862 | 1.471578 | percentage_points |
| combined55 | baseline22 | 2025 | axis_next3 | 1750 | 1.371429 | -0.277461 | 2.921869 | percentage_points |
| combined55 | baseline22 | 2025 | top5_all | 1750 | 1.257143 | -0.398260 | 2.847825 | percentage_points |
| combined55 | baseline22 | 2025 | top3_all | 1750 | -0.114286 | -1.187986 | 0.932415 | percentage_points |
| combined55 | baseline22 | 2025 | trio6 | 1750 | 1.142857 | -0.240260 | 2.618397 | percentage_points |
| combined55 | baseline22 | 2025 | target_brier | 1750 | -0.001076 | -0.001997 | -0.000217 | loss |
| combined55 | baseline22 | 2025 | set_logloss | 1750 | -0.026063 | -0.047227 | -0.004689 | loss |
| combined55 | baseline22 | 2026 | axis_top3 | 1288 | 0.310559 | -1.761435 | 2.416931 | percentage_points |
| combined55 | baseline22 | 2026 | axis_top2 | 1288 | 0.388199 | -1.644597 | 2.541732 | percentage_points |
| combined55 | baseline22 | 2026 | axis_win | 1288 | 1.863354 | -0.158611 | 3.950470 | percentage_points |
| combined55 | baseline22 | 2026 | quinella_one | 1288 | 0.077640 | -1.388943 | 1.515324 | percentage_points |
| combined55 | baseline22 | 2026 | axis_next3 | 1288 | 0.776398 | -0.988204 | 2.548755 | percentage_points |
| combined55 | baseline22 | 2026 | top5_all | 1288 | 1.319876 | -0.728456 | 3.141811 | percentage_points |
| combined55 | baseline22 | 2026 | top3_all | 1288 | 1.086957 | -0.327994 | 2.523324 | percentage_points |
| combined55 | baseline22 | 2026 | trio6 | 1288 | 2.018634 | 0.247709 | 3.712607 | percentage_points |
| combined55 | baseline22 | 2026 | target_brier | 1288 | -0.002932 | -0.003884 | -0.002035 | loss |
| combined55 | baseline22 | 2026 | set_logloss | 1288 | -0.067017 | -0.087579 | -0.048731 | loss |

전체축3위+1.021%p구간[-0.163,+2.266]과복승1조합+0.396%p[-0.417,+1.205]는0을포함한다. 축복승3조합+1.354%p[+0.408,+2.347]와Brier−0.001418[-0.001951,-0.000893]는이번표본에서개선신호다.2025/2026Brier도개선했지만2024는불확실하다.2025축2위는47.66→47.26%로소폭하락했다. 여러지표·연도를탐색한반복후향검증이므로독립미래재현을대신하지않는다.

삼복6조합은전체25.59→26.36%,2024는25.21→24.70%로하락,2025는24.17→25.31%,2026은28.03→30.05%다. 삼복을주목표로이후후보를고른것이아니다.

## 어느 묶음에서 달라졌는가

아래비율은0~1이다.

| variant | n | axis_top3 | axis_top2 | quinella_one | axis_next3 | top5_all | trio6 | target_brier |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline22 | 4799 | 0.596374 | 0.473849 | 0.120025 | 0.262138 | 0.307147 | 0.255887 | 0.177583 |
| combined55 | 4799 | 0.606585 | 0.479267 | 0.123984 | 0.275682 | 0.313607 | 0.263597 | 0.176165 |
| front39 | 4799 | 0.600750 | 0.478016 | 0.118983 | 0.273182 | 0.306939 | 0.259846 | 0.176891 |
| inner37 | 4799 | 0.602209 | 0.477808 | 0.120859 | 0.270056 | 0.307981 | 0.259429 | 0.176843 |
| previous_full103 | 4799 | 0.604709 | 0.475099 | 0.123984 | 0.280683 | 0.328610 | 0.271307 | 0.174657 |

37입력초반경쟁만으로축입상59.64→60.22%,39입력앞선확률까지는60.08%,55입력종반까지60.66%였다. 앞선확률을넣으면모든지표가단조롭게좋아지는구조는아니다. 최종55−39의Brier는−0.000726[-0.001094,-0.000362]로개선됐지만축입상+0.583%p[-0.378,+1.655],축복승3조합+0.250%p[-0.624,+1.153]는불확실했다. 즉 **종반묶음의추가효과는확률오차에서더명확하며적중률에서는미확정**이다.

| variant | reference | period | metric | n | difference | lo | hi | units |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| combined55 | front39 | all | axis_top3 | 4799 | 0.583455 | -0.377515 | 1.655407 | percentage_points |
| combined55 | front39 | all | axis_top2 | 4799 | 0.125026 | -0.871288 | 1.109750 | percentage_points |
| combined55 | front39 | all | axis_win | 4799 | 0.166701 | -0.734135 | 1.068673 | percentage_points |
| combined55 | front39 | all | quinella_one | 4799 | 0.500104 | -0.163210 | 1.175267 | percentage_points |
| combined55 | front39 | all | axis_next3 | 4799 | 0.250052 | -0.624233 | 1.152611 | percentage_points |
| combined55 | front39 | all | top5_all | 4799 | 0.666806 | -0.267322 | 1.557771 | percentage_points |
| combined55 | front39 | all | top3_all | 4799 | -0.083351 | -0.642391 | 0.483361 | percentage_points |
| combined55 | front39 | all | trio6 | 4799 | 0.375078 | -0.338757 | 1.074665 | percentage_points |
| combined55 | front39 | all | target_brier | 4799 | -0.000726 | -0.001094 | -0.000362 | loss |
| combined55 | front39 | all | set_logloss | 4799 | -0.013051 | -0.021472 | -0.005118 | loss |

보조앞선모형의최고확률말첫조진입은2024년67.13%,2025년67.48%,2026년68.44%다. 전원통과조관측경주1,725/1,719/1,258에서계산했다. 이지표는입상/우승확률정확도와다르며이번표에앞선보조의동일입력기준모형대비개선검증을추가하지않았다. 모델이사용한묶음별gain은[중요도](outputs/bundle_importance.csv)에보존했고인과효과로해석하지않는다.

## 상위2착 목표로 별도 학습한 보조 시험

기존상위2착22입력 → 상위2착55입력이다. 입상라벨표와Brier수준을직접비교하면안된다.

| period | n | axis_top3 | axis_top2 | quinella_one | axis_next3 | Brier |
| --- | --- | --- | --- | --- | --- | --- |
| 2024 | 1761 | 58.89% → 59.97% | 46.39% → 47.59% | 12.04% → 12.21% | 26.06% → 25.95% | 0.137604 → 0.136736 |
| 2025 | 1750 | 58.97% → 59.03% | 47.09% → 47.31% | 11.77% → 11.43% | 25.03% → 25.94% | 0.136353 → 0.135386 |
| 2026 | 1288 | 62.11% → 60.48% | 49.30% → 48.68% | 13.66% → 14.05% | 28.42% → 29.27% | 0.135084 → 0.133139 |
| all | 4799 | 59.78% → 59.76% | 47.43% → 47.78% | 12.38% → 12.42% | 26.32% → 26.84% | 0.136472 → 0.135278 |

복승1조합전체12.38→12.42%,축2위47.43→47.78%로매우작은변화다. 두지표와축복승3조합의합산차이95%구간은모두0을포함한다.2026축2위는49.30→48.68%로하락했다. 확률Brier는세연도및합산에서개선됐지만복승적중문제를해결했다는근거는없다.

| variant | reference | period | metric | n | difference | lo | hi | units |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| combined55_top2 | baseline22_top2 | all | axis_top2 | 4799 | 0.354240 | -0.876136 | 1.574522 | percentage_points |
| combined55_top2 | baseline22_top2 | all | quinella_one | 4799 | 0.041675 | -0.749301 | 0.911982 | percentage_points |
| combined55_top2 | baseline22_top2 | all | axis_next3 | 4799 | 0.520942 | -0.437434 | 1.505934 | percentage_points |
| combined55_top2 | baseline22_top2 | all | target_brier | 4799 | -0.001193 | -0.001628 | -0.000743 | loss |
| combined55_top2 | baseline22_top2 | 2024 | axis_top2 | 1761 | 1.192504 | -1.154123 | 3.442683 | percentage_points |
| combined55_top2 | baseline22_top2 | 2024 | quinella_one | 1761 | 0.170358 | -1.269506 | 1.556056 | percentage_points |
| combined55_top2 | baseline22_top2 | 2024 | axis_next3 | 1761 | -0.113572 | -1.702066 | 1.546824 | percentage_points |
| combined55_top2 | baseline22_top2 | 2024 | target_brier | 1761 | -0.000868 | -0.001699 | -0.000089 | loss |
| combined55_top2 | baseline22_top2 | 2025 | axis_top2 | 1750 | 0.228571 | -1.683695 | 2.273413 | percentage_points |
| combined55_top2 | baseline22_top2 | 2025 | quinella_one | 1750 | -0.342857 | -1.608870 | 0.963989 | percentage_points |
| combined55_top2 | baseline22_top2 | 2025 | axis_next3 | 1750 | 0.914286 | -0.680291 | 2.542545 | percentage_points |
| combined55_top2 | baseline22_top2 | 2025 | target_brier | 1750 | -0.000967 | -0.001737 | -0.000242 | loss |
| combined55_top2 | baseline22_top2 | 2026 | axis_top2 | 1288 | -0.621118 | -2.636126 | 1.362190 | percentage_points |
| combined55_top2 | baseline22_top2 | 2026 | quinella_one | 1288 | 0.388199 | -1.022179 | 1.864947 | percentage_points |
| combined55_top2 | baseline22_top2 | 2026 | axis_next3 | 1288 | 0.854037 | -1.001062 | 2.809213 | percentage_points |
| combined55_top2 | baseline22_top2 | 2026 | target_brier | 1288 | -0.001945 | -0.002680 | -0.001206 | loss |

## 이전103입력 연구와 비교하면

이번55입력은선택22모델을기준으로새로쌓은작은입력구성이며이전103입력에추가한159입력모형이아니다. 이전full103은다양한구간·각질·비선행추월관계까지포함했다. 축입상60.47→60.66%차이는불확실하고,복승1조합은둘다595/4,799로같다. 축복승3조합은28.07→27.57%,상위5두입상전체포착32.86→31.36%로낮았다. Brier도0.174657→0.176165로악화됐다. 따라서새후보가전체연구중최선이라고말할수없다.

| variant | reference | period | metric | n | difference | lo | hi | units |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| combined55 | previous_full103 | all | axis_top3 | 4799 | 0.187539 | -0.872923 | 1.287656 | percentage_points |
| combined55 | previous_full103 | all | axis_top2 | 4799 | 0.416753 | -0.639626 | 1.498533 | percentage_points |
| combined55 | previous_full103 | all | axis_win | 4799 | 0.354240 | -0.590471 | 1.296824 | percentage_points |
| combined55 | previous_full103 | all | quinella_one | 4799 | 0.000000 | -0.739760 | 0.781250 | percentage_points |
| combined55 | previous_full103 | all | axis_next3 | 4799 | -0.500104 | -1.575284 | 0.521749 | percentage_points |
| combined55 | previous_full103 | all | top5_all | 4799 | -1.500313 | -2.626669 | -0.366149 | percentage_points |
| combined55 | previous_full103 | all | top3_all | 4799 | -0.500104 | -1.141671 | 0.148463 | percentage_points |
| combined55 | previous_full103 | all | trio6 | 4799 | -0.770994 | -1.681696 | 0.145995 | percentage_points |
| combined55 | previous_full103 | all | target_brier | 4799 | 0.001508 | 0.001045 | 0.001982 | loss |
| combined55 | previous_full103 | all | set_logloss | 4799 | 0.040010 | 0.028747 | 0.050941 | loss |

## 판단과 검증

내측초반차이·앞선확률·과거종반유지를연결하는정보에는추가가치의신호가있다. 특히22입력대비확률오차와축복승3조합개선은후속검증후보로남길만하다. 하지만축단독/복승1조합향상확정및103입력대체근거는부족하다. 이번결과로선택22·운영모형·미래계약을변경하지않았다. 기존동결계약은그대로보존하며새55후보의별도미래검증설계가필요하다.

24저장능력모형과7앞선모형재추론,19,196개모형·경주지표,확률합/축/복승/상위5/삼복조합/Brier를확인했다. 최대점수재현오차0,기준22입력/예측불변.250개실제과거슬롯과180개원시관측의같은출전유지사건을독립재계산했고80개전체편성의현재정답변조에도입력불변이었다. 앞선/능력학습·교정시점및730일을검증했다.

한계는반복후향표본/다중비교미보정/2026부분연도/2018이전구간자료결측/같은거리지원부족/보정미지원원시초/과거와현재편성변화다. 기수의도·실제주행경로·생리적소모는추정하지않았다. 기존22입력의당일부담중량시점은상속된검증범위이며원선택문서의`current_weight_pit_verified=false`를이번작업이해결한것은아니다. 로컬자료만사용했고DB쓰기/외부수집/제주변경은없다.

재현순서: `run.py prepare`→`run.py train`→`run.py analyse`→`verify.py`→`diagnostics.py`→`report.py`→`finalize_inventory.py`.

[연도별전체지표](outputs/metrics.csv) · [짝비교와95%구간](outputs/paired_differences.csv) · [적중획득·상실](outputs/gain_loss.csv) · [검증](outputs/verification.json) · [용량명세](outputs/artifact_inventory.json)
