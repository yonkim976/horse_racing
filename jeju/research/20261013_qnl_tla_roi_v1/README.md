# 복승·삼복승 동일 예산 수익률

2025-01-03~2026-09-19의 동일 1,142경주에서, 매경주 총 6,000원씩 투입했다고 계산했다. 한 조합은 6,000원, 삼복승 6조합은 각 1,000원이다. 방식당 총투입은 6,852,000원이다. 2024년 637경주는 배당 미보유로 제외했다.

| 승식·연구 방식 | 구매 조합 수 | 적중 경주 | 순수익률 |
|---|---:|---:|---:|
| 복승 현재 기수 ID 선택 쌍 | 1 | 145 | −23.57% |
| 복승 직전 기수 기본 선택 쌍 | 1 | 141 | −25.14% |
| 복승 말 점수 Top2 | 1 | 138 | −26.37% |
| 삼복승 이전 F1 | 1 | 80 | −16.71% |
| 삼복승 이전 F1 | 6 | 260 | −36.42% |
| 삼복승 F1_STYLE6 | 1 | 74 | −20.75% |
| 삼복승 F1_STYLE6 | 6 | 257 | −34.18% |
| 삼복승 공동 관계 후보 | 1 | 69 | −30.00% |
| 삼복승 공동 관계 후보 | 6 | 276 | −29.77% |

현재 선택 쌍의 복승은 총환급 5,236,800원·순손실 1,615,200원이었다. 복승은 두 말이 실제 1·2착인 경우만 적중이다. 삼복승은 실제 Top3 세 말과 정확히 일치하는 저장 티켓만 지급하며, 6조합의 투입금을 여섯 배로 중복 비교하지 않았다.

현재 기수 ID pair 후보에는 삼복승의 세 번째 말을 고르는 정책이 없다. 삼복승 결과는 별도로 저장된 F1/F1_STYLE6 및 공동 관계 모델 티켓의 결과다. 사후 결과로 세 번째 말을 추가하거나 새 조합을 만들지 않았다. 매칭 기준선의 삼복승 집계는 F1_STYLE6과 같지만 별도 방식으로 보존했다. 이번 18개 방식(복연 참고 포함)은 모두 표본 내 순손실이다. 운영 HY_R_FORM과의 비교·미래 수익 검증·모델 승격은 아니다.

This retrospective accounting uses the same 1,142 payout-supported races as the QPL study: 654 in 2025 and 488 through 2026-09-19. It applies 6,000 KRW per race to every method. QNL buys one selected pair at 6,000 KRW and counts a win only when that unordered pair is exactly the official Top2. TLA compares the saved rank-1 ticket at 6,000 KRW with six saved tickets at 1,000 KRW each.

TLA selections come from saved F1, F1_STYLE6, and the joint candidate/matched-baseline outputs. The joint rank order was checked against `all_triples.parquet` and `report.py`; the pair-axis `unrestricted_top_k` K6 arrays match those joint arrays exactly, so they are recorded as parity evidence rather than a duplicate method. No third horse is inferred from pair-only selectors. The current jockey-ID QPL result is included as a 6,000 KRW scaled reference.

`race_returns.csv` contains each ticket, exact-hit result, stake, payout multiple, return, and net. `summary.csv` reports ticket and race hit rates, full and year-split return, recovery, and ROI. All payout-supported official winning QNL/TLA values were compared between the shared read-only DB and verified local API301 source rows.

This is a repeated retrospective development period, not independent future validation or an operating/betting policy. It used no network access, model fitting, or shared-data writes.

Luna xhigh 계산 후 감독은 저장 원본에서 티켓을 별도로 읽어 43,396개 티켓과 54개 집계를 독립 재계산했고 모두 일치했다. 사용된 당첨배당 원문 221페이지를 별도 파싱·해시 검증했다. [공식 보고서](REPORT.json), [전체·연도별 표](summary.csv), [경주·티켓별 환급](race_returns.csv), [독립 검산 코드](root_verify.py), [검토 결과](ROOT_REVIEW.json), [원문 페이지 ID·경로·해시](SOURCE_PAGE_INDEX.json)에 보존했다.
