# 2010~2026 경마·주행심사 날짜 원장 v1

> 2026-10-01 휴장·미시행 유형 보완: [현재 코어 반영 원장](../20261001_closure_gap_followup_v4/README.md)은 휴장·중단 81구간·경주장별 날짜 552개(공식 시작일/API 재개일로 경계를 정한 2구간 및 사용자 제공 KRA 연간계획 근거 4구간 포함)와 종전 29경주의 취소 확정을 반영한다. 세부 유형 미확정은 0건이며, 역사적 휴장 자료의 완전성은 부분이다. 이 디렉터리의 이전 CSV는 그대로 보존한다.

> 2026-10-01 후속 정정: 2026-09-17 영남 주행심사 4회차·48행은 [공식 계획 및 사용자 설명 재검토](../20261001_yeongnam_trial_venue_recheck_v2/README.md)를 거쳐 코어 DB의 별도 검토 뷰에서 부산경남·1,000m로 보완했다. 아래는 최초 원천 검토 기록이며, API·RPT 원문과 이전 CSV는 변경하지 않았다.

초기 조사일 2026-09-29, 마사회 성적표 직접 재검증일 2026-09-30. 범위는 **2010-01-01~2026-09-29**, 서울(1)·부산경남(3)·영천(4)의 정식 경주와 주행심사다. 제주 경주는 제외했다. 이 산출물은 **일정·시행일 단계**이며 말별 결과, 착순, 기록, 관계자 정보의 연구 DB 적재는 아직 하지 않았다. 2017년 이후만 향후 학습·평가 대상으로 사용하고 2010~2016년은 이력 계산용이다.

## 우선 원천과 상태 의미

- [한국마사회 경주계획표](https://www.data.go.kr/data/15056499/openapi.do) `API72_2/racePlan_2`: `meet + rc_year`로 2010~2026년을 전수 조회했다. 2026년 영천은 `meet=4`다. 계획표의 행은 **편성/예정 경주**이며 시행 증거가 아니다.
- [한국마사회 주행심사 상세결과](https://www.data.go.kr/data/15056974/openapi.do) `API20_1/ridingTestResult_1`: `meet + tr_year`로 조회하고 응답의 `trainDate`와 `trainNo`로 실제 심사 날짜·회차를 집계했다. `meet=3` 응답의 장소 표기는 `영남`이며 영천 시행 후 부산경남과 영천을 API 코드만으로 분리할 수 없다.
- 한국마사회 `API4_3/raceResult_3`: 경주 **시행 여부 확인에 필요한 날짜·경주번호와 양수 완주기록 존재 여부만** 추출했다. 상세 결과는 다음 단계에서 판정한다. API가 과거 경주처럼 보이는 값을 잘못된 날짜·경마장으로 반환하는 경우가 있어, `경주계획에도 있고 양수 완주기록도 있는` 키만 우선 시행 확인으로 표시한다.
- KRA `dacom11` 경주 RPT와 `dacom23` 주행심사 RPT는 **보조 검증**에만 사용했다. 공식 시행계획 PDF와 연감에서 명시한 휴장·취소는 별도 근거 열로 표시했다.
- [KRA 경주성적표 기간조회](https://race.kra.co.kr/raceScore/scoretablePeriodSearch.do)는 2026-09-30에 경마장·날짜를 선택하고 해당 경주번호의 설명을 펼쳐 직접 읽었다. 동적 화면의 문구를 CSV에 전사했으며 페이지 원문 파일은 보관하지 못했다.

136개 연도×API×경마장 요청의 응답 원문은 `raw/`에 보존했다. 경주기록 API 원문은 `.json.gz`로 압축했다. 각 요청의 원문 SHA-256, 응답 건수, 파일 경로는 [manifest.json](manifest.json)에 있다. 서비스키와 인증 URL은 저장하지 않았다. 모든 응답의 `totalCount`와 실제 행 수, 요청 연도와 응답 날짜의 일치를 확인했다.

## 생성된 원장과 수량

| 파일 | 의미 |
|---|---|
| [race_plan.csv](race_plan.csv) | 계획표 경주별 29,826행. 경주장·일자·번호·거리·등급 원문 등 |
| [race_execution_flags.csv](race_execution_flags.csv) | 계획 키와 공식 경주기록의 완주 증거 대조. 착순·기록 값은 쓰지 않음 |
| [race_nonexecution_adjudication.csv](race_nonexecution_adjudication.csv) | 양수 완주 증거가 없는 계획 116경주의 최종 `no_valid_completed_race` 판정과 세부 상태·근거 |
| [trial_sessions.csv](trial_sessions.csv) | 공식 API의 주행심사 날짜·회차 6,199행. 참가행 61,777개를 회차로 묶음 |
| [event_days.csv](event_days.csv) | 경주/심사 날짜가 있는 API 원장 |
| [daily_calendar.csv](daily_calendar.csv) | 2010-01-01~2026-09-29의 **모든 날짜×3경마장 18,348행**. 계획·시행·심사·공식 휴장·당일 전 경주 취소 여부를 분리 |
| [annual_summary.csv](annual_summary.csv) | 연도×경마장별 계획·시행 확인·심사·문서화된 휴장/취소 수 |
| [official_annual_stats_crosscheck.csv](official_annual_stats_crosscheck.csv) | [KRA 공식 연간 통계](https://race.kra.co.kr/globalEn/racingStatistic.do)의 2021~2025년 서울·부산경남 시행일·경주 수와 API 원장 비교 |
| [long_execution_gaps.csv](long_execution_gaps.csv) | 시행일 사이 7일 이상 공백의 **검토 후보**. 이 공백을 자동으로 휴장이라 판정하지 않음 |
| [reported_race_cancellations.csv](reported_race_cancellations.csv) | 사용자가 마사회 결과 화면 등을 대조해 확인한 취소 33경주와 사유. 직접 화면 원문 보관 상태를 별도 표시 |
| [partial_day_cancellation_evidence.csv](partial_day_cancellation_evidence.csv) | 일부 시행일의 미시행 10경주에 대한 KRA 연감 8건과 당시 보도 2건 |
| [kra_scoretable_nonfinish_reasons.csv](kra_scoretable_nonfinish_reasons.csv) | [KRA 경주성적표 기간조회](https://race.kra.co.kr/raceScore/scoretablePeriodSearch.do)에서 경주번호를 펼쳐 직접 확인한 완주 결과 없는 64경주의 화면 문구 |
| [remaining_partial_day_review.csv](remaining_partial_day_review.csv) | 이전에 사유 미확정이었던 9개 날짜·21경주의 KRA 직접 조회 결과 |
| [planless_positive_result_review.csv](planless_positive_result_review.csv) | 활성 원장에서 제외한 API 오류 경주 20개의 판정 근거. KRA 성적표에는 해당 날짜 자료가 없고, 모두 이전 시행 경주와 출전마 집합이 정확히 일치함 |
| [result_only_nonfinish_anomaly_review.csv](result_only_nonfinish_anomaly_review.csv) | 추가로 제외한 결과 API 전용 52키의 판정 근거. 8개 경마장·날짜의 KRA 성적표에 자료가 없고, 모두 이전 시행 경주와 출전마 집합이 정확히 일치함 |

| 경마장/원천 지역 | 계획 경주 | 계획 날짜 | 계획+완주 증거 경주 | 해당 시행일 | 심사 회차 | 심사 실행일 |
|---|---:|---:|---:|---:|---:|---:|
| 서울 | 17,403 | 1,562 | 17,322 | 1,558 | 3,483 | 825 |
| 부산경남 경주 / 영남 심사 | 12,411 | 1,553 | 12,376 | 1,549 | 2,716 | 808 |
| 영천 경주 | 12 | 2 | 12 | 2 | API 단독 분리 불가 | API 단독 분리 불가 |
| **합계** | **29,826** | **3,117** | **29,710** | **3,109** | **6,199** | **1,633** |

시행일은 **경마장별 날짜 수**이며, 서울과 부산경남이 같은 날 경주하면 2일로 센다. API 경주계획 116경주는 양수 완주 증거가 없고, 그중 75경주는 해당 경마장 하루 전체에 완주 증거가 없다. `race_execution_flags.csv`는 이 원천 대조를 보존하고, 날짜 원장은 KRA 성적표 직접 확인 근거를 별도 열과 상태로 기록한다. 계획에 없는 결과 API 키 **72개**는 모두 오류로 판정해 활성 경주·결과 원장에서 제외했다. 앞서 양수 완주 형태의 20개는 [첫 판정 원장](planless_positive_result_review.csv)에, 추가 52개는 [두 번째 판정 원장](result_only_nonfinish_anomaly_review.csv)에 남겼다. 72개 모두 이전 시행 경주와 출전마 집합이 정확히 같으며, 해당 경마장·날짜의 [KRA 성적표](https://race.kra.co.kr/raceScore/scoretablePeriodSearch.do)는 `자료가 없습니다`로 표시됐다. 오류 원천 응답과 판정 근거는 감사용으로 보존한다. 2026년 [공식 시행계획](https://race.kra.co.kr/down/raceplan2026_20260516.pdf)에 적힌 월요 공휴일 경마일은 3월 2일·8월 17일·10월 5일이다.

**양수 완주 증거가 없는 계획 경주 116건 모두** 최종 판정 원장에 `no_valid_completed_race`로 기록했다. 이 값은 유효한 완주 결과가 확인되지 않았다는 판정이며, 출발 시도 여부를 뜻하지 않는다. 원장의 `adjudication_status`는 근거가 지지하는 범위에서 취소·무효·공식 일정 중단을 구분한다.

| 세부 상태 | 경주 수 | 해석 |
|---|---:|---|
| `official_day_cancelled` | 35 | KRA 연감이 당일 전 경주 취소/미시행으로 기록 |
| `reported_day_cancelled` | 11 | 2019-11-29 부산경남 전 경주. KRA 성적표 사유와 당시 보도에서 인용한 KRA 추모 공지를 함께 보존 |
| `official_closure_nonexecution` | 17 | 2020-02-23 서울·부산경남. 변경 시행계획의 코로나19 경마 중단 기간에 포함 |
| `race_cancelled` | 22 | 12건은 KRA 화면에 경주취소가 명시되고, 10건은 연감 또는 당시 보도가 경주 취소를 확인 |
| `race_invalid` | 2 | 서울 2023-01-15 9경주와 부산경남 2025-12-26 6경주. KRA 화면에 경주불성립으로 표시 |
| `reason_recorded_outcome_unclassified` | 29 | KRA 화면에 사유 문구는 있으나 취소·경주불성립을 명시하지 않아 그 세부 유형은 확정하지 않음 |

최종 verdict는 116건 모두 `no_valid_completed_race`이며, 위 상태 수는 116건을 빠짐없이 나눈다. 특히 29건의 사유 문구는 KRA 화면에서 확인한 원문 그대로 기록했지만, 그 문구만으로 취소나 무효를 추론하지 않았다. 64건은 KRA 성적표 기간조회에서 개별 경주 설명까지 확인했고 정확한 문구는 [경주별 원장](kra_scoretable_nonfinish_reasons.csv)에 보존했다. 동적 화면 원문 파일은 보관하지 않았다. `build_daily_calendar.py`가 상세 판정 원장과 날짜별 상태 집계를 함께 재생성한다.

[마사회 공식 경마 통계](https://race.kra.co.kr/globalEn/racingStatistic.do)의 2021~2025년 서울·부산경남 `NUMBER OF FIXTURES` 및 `NUMBER OF RACES` 10개 연도×경마장 조합은 API의 시행 확인일·경주 수와 **모두 일치**한다. [독립 대조 파일](official_annual_stats_crosscheck.csv)과 [검증 스크립트](check_official_annual_stats.py)에 수치를 보존했다. 이는 연간 총량 검증이며, 개별 날짜의 공식 취소 사유까지 증명하지는 않는다.

## 휴장과 취소

[KRA 공식 시행계획을 근거로 문서화한 기존 구간](../20260929_closure_inventory_v1/closures.csv) 50개에, [2026년 시행계획](https://race.kra.co.kr/down/raceplan2026_20260516.pdf)의 **9월 25~27일 서울·부산경남·영천 추석 휴장**을 [추가 원장](closure_addendum.csv)으로 합쳤다. 현재 공식 휴장 근거가 달린 날짜×경마장 행은 **389개**이고, 그 안에서 시행 확인 경주는 **0개**다. 2020년 2월 23일 서울 11·부산경남 6경주는 이전 계획에는 남아 있지만 [KRA의 2020년 조정 계획](https://race.kra.co.kr/down/raceplan_2020.pdf)이 2월 23일~6월 18일을 공식 미시행 기간으로 명시한다. 이 17건은 개별 취소가 아니라 `official_closure_nonexecution`으로 판정했다.

이 **휴장 목록은 아직 2010~2026년 완전한 목록이 아니다.** 공식 구간이 없는 연도의 무경주일을 휴장이라고 채우지 않았다. 계획은 있으나 해당 경마장 하루 전체에 완주 증거가 없는 날짜는 서울 2012-06-30·2014-04-20·2020-02-23·2020-08-09, 부산경남 2010-03-14·2014-04-20·2019-11-29·2020-02-23, 모두 **8개 경마장·날짜**다. 이 중 2020-02-23 두 곳은 공식 미시행 구간이다. [KRA 2014년 마사연감](https://board.kra.co.kr/board/downloadFile.do?boardNo=215&fileNm=20151224182414435799.pdf&fileRnm=2014%EB%85%84_%EB%A7%88%EC%82%AC%EC%97%B0%EA%B0%90.pdf)은 부산경남 2010-03-14(기수 추모), 서울 2012-06-30(폭우), 서울·부산경남 2014-04-20(세월호 추모) **4개 경마장·날짜의 전 경주 취소/미시행**을 기록한다. 이를 [별도 원장](official_nonexecution_addendum.csv)에 넣었다. 예정된 휴장과 당일 취소는 별도 상태로 유지한다. 부산경남 2019-11-29의 11경주는 KRA 성적표에서 모두 `문중원 기수 사망`, 서울 2020-08-09의 12경주는 모두 `경주로 불량(우천)으로 경주취소`로 표시돼 [직접 조회 원장](kra_scoretable_nonfinish_reasons.csv)에 기록했다. `race_nonexecution_adjudication.csv`는 이 날짜를 각각 전일 미시행 보고와 명시적인 경주취소로 구분한다.

## RPT 보조 검증

[경주 RPT 본문 대조](race_rpt_crosscheck.json): 보관된 `dacom11`의 본문 날짜·경마장으로 1,827개 경마장·시행일을 읽었고 API 시행 확인일과 불일치하는 RPT 날짜는 **0개**, 파싱 실패도 **0개**다. 보관 범위가 온전한 **2015~2024년은 연도별 API 시행일과 RPT 시행일이 모두 일치**한다. 2010~2014년, 2025년은 이 RPT가 보관되지 않았고 2026년은 일부만 있다. 2026-09-13 RPT는 `meet=3` 폴더에 있지만 **본문 경마장은 영천**이다. 따라서 RPT 경로를 경마장 확정 근거로 쓰지 않았다.

[대조 결과](trial_rpt_crosscheck.json): API 주행심사 실행일 1,633개 중 보관 RPT 본문에도 날짜가 있는 것은 1,628개, **API에만 있는 5개**는 서울 2013-01-25·2020-12-24·2021-01-28·2022-01-21, 영남 2019-11-30이다. RPT 본문에만 있는 실행일은 0개이며 파싱 실패도 0개다. 영남의 `20120519dacom23.rpt`는 **파일명은 5월 19일이나 본문은 5월 17일**로 API `trainDate=20120517`과 일치한다. 파일명만으로 심사일을 정하면 오류가 생긴다.

2026-09-17 영남 주행심사 4회차·48참가행은 API와 RPT 모두 날짜·회차를 확인하지만 RPT에는 시행장 표기가 없어 부산경남/영천 장소를 아직 확정하지 않았다.

## 남은 검증과 다음 단계

1. 공식 연간 시행계획·변경 공지·연감을 2010~2017년 및 2021년까지 확보하고, 2020년 추가 중단기와 이미 확보한 연도의 임시 변경 공지도 점검해 휴장 날짜의 문서 근거를 보완한다. 긴 시행 공백은 후보일 뿐 공식 휴장이 아니다.
2. 계획에 없는 결과 API 키 72개는 이전 시행 경주의 출전마 집합을 재사용하거나 기록을 변형한 행으로 확인돼 활성 산출물에서 제외했다. API 생성·정정 경위는 아직 확인하지 못했다. 2026-09-17 영남 심사 장소도 원문으로 판정한다. 완주 증거가 없는 116건은 현재 확인한 근거에 따라 모두 최종 분류했으며, 29건은 KRA 화면에 사유 문구가 있지만 취소·무효 여부를 특정할 수 없어 그 불확실성을 상태로 유지한다.
3. 날짜·시행·장소 원장이 검증된 뒤 경주/심사 결과와 경주 종류·거리·주로 등 상세정보를 적재한다. 미확정 행은 버리지 않고 분리한다.

재현: `.venv/bin/python thoroughbred/research/20260929_calendar_api_v1/collect.py --fetch` (기존 응답 재사용), 이어서 `check_trial_rpt.py`, `build_daily_calendar.py`, `check_race_rpt.py`, `check_official_annual_stats.py`, [check_scoretable_evidence.py](check_scoretable_evidence.py), [match_planless_result_sources.py](match_planless_result_sources.py)를 실행한다. API 원문을 다시 받지 않으려면 `collect.py`에서 `--fetch`를 생략한다. 성적표 화면 문구 CSV는 수동 조회 전사 자료이므로 자동 재수집되지 않는다.
