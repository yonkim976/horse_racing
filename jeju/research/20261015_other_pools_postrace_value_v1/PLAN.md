# HY_R_FORM 단승·복승·쌍승·삼복승·삼쌍승 동일 경주 사후 가치 비교 계획

## 범위와 원칙

이 연구는 이전 운영 대 연구 사후 비교와 **동일한 2026-01-02~09-12 정상 complete common cohort 467경주·70일**을 사용한다. 등록부 활성 HY_R_FORM의 기존 frozen 평가 점수와 original complete Top3 ordered joint distribution에서 승식별 사건 확률을 정확히 집계한다. 새 학습·보정·승격, 운영·DB·등록부 변경, 외부 호출은 없다. 최종 표시 배당은 결과 후 관측한 가격이므로 EV와 ROI는 retrospective final-price oracle 결과다. 사전 매수 가능성이나 라이브 운영 성적의 근거가 아니다.

분석 대상은 이전 비교에서 다루지 않은 다섯 승식이다. 원 API301 코드와 사건 정의는 `WIN` 단승(우승 말), `QNL` 복승(공식 1·2위의 순서 없는 쌍), `EXA` 쌍승(공식 1위→2위 순서쌍), `TLA` 삼복승(공식 Top3 순서 없는 세트), `TRI` 삼쌍승(공식 1→2→3위 순서열)이다. API와 공식 결과의 지역 meet/race/마번 연결을 교차확인한다. 고정 이전 research model이 해당 사건 확률을 제공하지 않는 승식에는 research 확률을 만들어 붙이지 않는다. 유일한 예상 research 비교는 독립 검토에서 저장 native F1_STYLE6 삼복 확률과 support가 통과할 경우 TLA다. 그 외 research 예측은 없거나 원래 native ordered joint가 확인되지 않으면 `not_available`로 표기한다.

## 공통 코호트와 후보·가격 완전성

- QPL/PLC 비교 연구의 `cohort.csv`에서 `qpl_eligible=true`인 정확한 467 race ID를 상위 참조 코호트로 사용한다. 4,475개의 고정 operating runner ID·마번·필드 크기 및 완료 official result roster가 일치해야 한다. 공식 1·2·3위 각 1두와 Top3 동착 0건을 확인한다. 가격 완전성 기준의 primary per-pool cohort는 WIN/QNL/EXA/TLA 467경주, TRI 222경주다. API301 audited raw response에서는 TRI `9999.9` sentinel이 245경주·15,343개 후보 quote에 관측되어 그 경주의 불완전 TRI candidate set 전체를 제외한다. 동일한 222개 TRI-complete race ID를 모든 5개 풀에 적용하는 universal common-scope 표도 별도 낸다.
- 가능한 후보 전체를 runner roster에서 전산출한다: WIN `n`, QNL `C(n,2)`, EXA `n(n−1)`, TLA `C(n,3)`, TRI `n(n−1)(n−2)`. 기존 감사 API301 raw page index가 선택한 날짜별 latest-complete saved run(70일·242 pages)의 모든 raw item 및 페이지를 읽는다. 해당 date/meet run의 페이지 연속성·totalCount·item 수·원문 SHA를 검사하고, 후보별 중복·누락·비수치 값을 발견하면 fail closed 한다. API301의 `9999.9`는 프로젝트 source contract의 invalid odds sentinel로 간주한다. 이를 유효 배당으로 쓰지 않으며 값을 보정·대체하지 않는다. 어느 TRI race라도 candidate key 하나에 sentinel이 있으면 TRI의 해당 race 전체를 complete-price 기준에서 제외하고 source exclusion ledger에 표시한다.
- 당첨 quote만 저장된 `winning_quotes.csv`나 winner reference로 loser 가격을 대체하지 않는다. 모든 후보의 losing/winning final display quote 원문을 그대로 보존하고 official event hit일 때만 gross return을 발생시킨다. quote 누락·충돌을 0원으로 대체하지 않는다.
- bootstrap은 이전 비교와 동일한 2,000×269 fixed schedule을 쓰며 각 eligible cohort의 날짜를 원 schedule에 일치시킨다. 미포함 schedule date는 선택 0건이다.

## 원 운영 native 확률

각 경주의 저장 `frozen_scores.parquet`의 set rank score/beta와 order score/beta_order를 production `jeju_hybrid_evaluation.distribution`에 전달한다. 함수의 전체 ordered Top3 확률 질량을 horse-number order에 맞춰 보존하며, 각 시장의 p는 아래 사건에 해당하는 모든 ordered triple의 joint mass 합계다. All-market probability candidate tables cover 467 scores; ticket selection and payout tables use their price-complete primary cohort and the universal 222-race scope.

- WIN(h): 첫 번째 착순이 h인 모든 주문 확률 합.
- QNL({a,b}): 처음 두 순서가 {a,b}인 두 주문의 확률 합.
- EXA(a→b): 첫째 a·둘째 b인 모든 third-horse 주문의 확률 합.
- TLA({a,b,c}): 세 말이 같은 정확한 Top3 집합인 여섯 순열의 확률 합.
- TRI(a→b→c): 그 정확한 ordered triple의 확률.

각 경주에서 전체 3위 집합 확률과 모든 ordered triple 확률 합은 1, runner Top3 marginal 합은 3임을 확인한다. ordered joint는 `order_score × beta_order`를 반영한다. 승식 사건 확률을 runner 선택 rank나 사후 결과로 구성하지 않는다.

## 결과 전에 고정하는 10개 구매 정책

각 승식별 operating 후보 전체를 native p 내림차순, 숫자 tuple인 이벤트 키 오름차순으로 rank한다. 동일 확률은 이벤트 키로 결정한다. WIN의 키는 단일 숫자, QNL/TLA의 키는 정렬한 horse-number tuple, EXA/TRI의 키는 순서 보존한 horse-number tuple이다. 전략은 모델/승식별·경주당 최대 한 장이며 stake는 1,000 KRW다. 최대 EV 동률도 같은 numeric tuple 오름차순으로 해결한다. 아래 10개 정책은 모든 지원 승식과 native research TLA에도 동일하게 적용한다.

1. p rank 1, 2, 3, 4, 5 중 ticket 1장.
2. p rank 1의 post-hoc EV `p×final_odds−1 > 0`일 때 선택.
3. 전체 후보 max-EV의 post-hoc EV가 `> 0`이면 선택.
4. 확률 rank 1–3 후보 max-EV의 post-hoc EV가 `> 0`이면 선택.
5. 확률 rank 1–5 후보 max-EV의 post-hoc EV가 `> 0`이면 선택.
6. 확률 rank 1–3 후보 max-EV의 post-hoc EV가 `> 0.20`이면 선택.

상세히는 rank 규칙 5개와 threshold 규칙 5개다. p rank/EV 정책 임계값을 결과 검토 후 바꾸지 않는다. 희소 TRI 사건을 위해 다른 threshold를 임의 추가하지 않는다.

## 보고 지표·불확실성

시장·모델·정책별 eligible race, selection/no-bet, coverage, hits, hit rate, stake, gross return, net, ROI, mean selected p, mean realized odds, mean selected post-hoc EV, mean p on winning tickets 및 선택 probability rank를 보고한다. p rank 1–5의 candidate 수·mean p·hit rate·Brier score도 낸다. 적중 최다 gross 환급 1·3·5장의 ticket과 그 stake를 제거한 ROI 민감도를 제시한다. 원 schedule을 그대로 사용한 날짜-block bootstrap 95% ROI/hit-rate 구간과 zero-bet/zero-stake draw를 보고한다.

HY 단독 승식 분석과 TLA operating-vs-F1_STYLE6 비교를 구분한다. 연구 TLA의 저장된 native exact unordered Top3 probability가 동일 roster에서 생성된 공식 자료인지 별도 검토로 입증되지 않으면 TLA 연구행도 계산하지 않는다. 모델 우위나 안정적 수익을 최고 사후 ROI 하나로 정하지 않는다.

## 한계와 산출

최종배당은 경주 후 가격으로 실제 구매 시 확정되지 않을 수 있으며 공식 공표 최초 시각은 재구성하지 않는다. 자료 기간은 반복된 2026 부분연도 개발기간이라 독립 OOS 검증이 아니다. 동착·환급 계약은 지원 cohort에 관측되지 않은 이상 일반화하지 않는다. 산출물은 이 새 폴더에만 둔다: `README.md`, `REPORT.json`, 467 race candidate/selection tables, all-candidate quote/source audit, rank/bootstrap tables, `SOURCE_MANIFEST.json`, `FINAL_MANIFEST.json`, 재현 스크립트. 별도 root verifier는 REPORT freeze 후 독립 receipt를 남긴다.
