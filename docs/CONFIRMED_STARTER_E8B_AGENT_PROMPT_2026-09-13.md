# E8-B: 실제 공식 출전표 일회성 capture-only pilot

작업 디렉터리: `/Users/kimyongjin/Desktop/horse_racing`.

E8-A H1/H2 독립 검증이 통과했다. 이 지시문을 사용자가 전달하면 **격리된 실제 일정·출전표의 제한적 읽기 수집**을 수행한다. 합성 계약 보완은 종료하고 실제 원천 접근·원문 보존·응답 완전성을 실측하는 것이 이번 목적이다. 자동 수집이나 모델 발행을 시작하는 지시가 아니다.

## 완료 목표와 예산

- 서울의 가까운 예정 경주일 하나에서 출전표 응답을 수집한다. 일자별 응답 전체를 pagination 검증에 사용하되, 미래 경주 1개를 사례로 선정해 키와 관측 시각을 설명한다.
- 총 HTTP 요청은 **최대 12회**다. 페이지, 재시도, redirect 등 실제 요청을 포함해 transport 수준에서 예산을 지킨다. 예산 내에서 같은 일자의 출전표를 최대 2회 완전 수집하여 응답 변화를 대조할 수 있다. 장시간 대기하지 않는다.
- 날짜·원천 파라미터는 첫 호출 전에 기록한다. 빈 응답을 성공으로 만들기 위해 날짜 범위를 계속 넓히지 않는다. 서울 외 경마장, 여러 주의 대량 수집으로 확대하지 않는다.
- 자료 없음·인증/통신/쿼터 오류·예산 부족도 정식 결과다. 원문과 실패 원인을 보존하고 실제 수집 성공을 주장하지 않는다. credentials가 없으면 offline adapter·검사까지 끝내고 한계를 제출한다.

## 먼저 확인할 기존 코드

- `docs/CONFIRMED_STARTER_E8A_V2_H1_H2_INDEPENDENT_REVIEW_2026-09-13.md`
- `src/horse_racing/collectors/kra_api.py`: `FetchedPage`, `KraApiClient.iter_entry_sheet_pages`, `iter_pages`, `ENTRY_SHEET_ENDPOINT`, `RACE_PLAN_ENDPOINT`
- `src/horse_racing/parsers/entry_sheet.py`: `parse_entry_sheet_page`
- 기존 race-plan parser 및 수집 파라미터, settings의 기존 service key
- 승인된 E8-A의 CAS·시각 검증·append journal 개념

기존 client는 `_fetch_json`에 최대 6회 retry가 있고, parser/iterator에는 누락된 count를 대체하는 기본값이 있다. 그대로 호출한 횟수를 실제 HTTP 횟수로 세거나 parser 반환 count를 원문에 명시된 count라고 해석하지 않는다. 기존 운영 코드 수정 없이 pilot용 wrapper/adapter에서 요청 예산과 원문 검증을 추가한다.

## 허용·금지 범위

허용 원천은 기존 코드에 정의된 **공식 race-plan과 API26_2 출전표**뿐이다. 현재 실행 시각을 실제 시스템 시계로 기록하고, 오늘 이후 가까운 서울 예정일을 선택한다. 오늘 자료에 이미 끝난 경주가 함께 포함되면 원문 응답은 보존하되 사례는 아직 cutoff가 지나지 않은 경주만 선정한다. 그런 경주가 없으면 prospective 사례 없음으로 보고한다. 결과를 보고 사례를 고르지 않는다.

2026-06-01 이후 실제 결과·구간·확정배당·심판 결과 보고서 및 미사용 holdout은 열지 않는다. 이번 새 사전 일정·출전표 관측은 과거 결과 조회 제한과 구분한다. 결과 endpoint로 일정이나 말 정보를 보충하지 않는다.

운영 DB·schema·registry·공개 원장·scheduler·UI·기존 봉인 코드/산출물을 수정하지 않는다. `ingest_entry_sheet` 같은 운영 upsert 함수를 호출하지 않는다. 실제 학습·추론·확률 발행·성능 평가·배팅은 0회다. 자동화 등록이나 백그라운드 지속 수집도 하지 않는다.

## 격리 adapter와 원문 보존

1. 먼저 기존 parser를 쓰는 작은 capture-only adapter와 mocked transport 검사를 만든다. 저장 대상은 새 실험 폴더이며 기존 SQLite를 열어 쓰지 않는다. 실제 API 응답을 `synthetic_entry_sheet_v1`로 변환해 합성 적격 gate를 통과시키지 않는다.
2. 원문 바이트, SHA256, endpoint, 공개 파라미터, HTTP 상태, 요청/수신/파싱/commit 완료 시각, parser 코드 hash, capture batch ID, 페이지 번호와 실패 상태를 기록한다. API 공개/적용 시각이 없으면 null로 남긴다. body를 수신한 뒤 파싱 실패하더라도 원문·실패를 남긴다.
3. 기존 service key는 설정에서 사용하되 값, 인증 포함 URL, exception의 비밀 값을 출력하거나 manifest에 넣지 않는다. 응답에 인증값이 반사되어 있으면 비밀을 포함한 artifact를 사용자 문서에 노출하지 않도록 별도 보존/마스킹 정책을 명시한다.
4. request/response 시각을 caller가 과거로 꾸며 넣지 않는다. 실제 응답·파싱·저장 단계의 시각을 분리한다. 실패 후 복구·재시도는 새로운 관측으로 기록하고 이전 시각을 소급 부여하지 않는다.
5. 원문에서 온 식별자는 `(meet, rcDate, rcNo, chulNo, hrNo)`로 보존한다. 운영 DB의 현재 entry ID가 없어도 synthetic/임의 정수를 실제 DB ID로 가장하지 않는다. 필요하면 명시적인 source key를 사용한다.

## 완전성·시간 검증

- 원문 header 성공 코드, 명시적 `totalCount`, `pageNo`, `numOfRows`, 실제 item 수를 대조한다. 누락/잘못된 메타데이터를 parser 기본값으로 보완해서 complete로 표시하지 않는다.
- page 중복·누락·중간 빈 페이지·서로 다른 totalCount·키 중복·다른 날짜/경마장 혼입을 검사한다. 모든 페이지의 합집합 unique item 수와 원문 totalCount를 대조한다.
- 일자별 전체 item 수와 경주별 출전마 수를 구분한다. totalCount를 경주별 독립 출전두수라고 쓰지 않는다.
- 두 차례 complete 응답을 확보하면 raw/page/key/value 변화를 기록한다. 같은 결과 두 번은 그 관측 구간에서 같았다는 증거이며 원천 전체의 원자적 snapshot이나 취소 반영 완전성을 증명하지 않는다.
- 일정은 실제 원문에서 받은 값과 근거를 보존한다. 임의 출발시각·`scheduled+20분` 같은 가정으로 적격을 만들지 않는다. 선정 경주의 관측 완료가 해당 일정의 T−30 전인지 수치로 보고하되 실제 최종 출발시각을 결과에서 가져오지 않는다.
- API26_2에 취소/정정 완전성을 입증할 정보가 없으면 그 상태를 분명히 적는다. **응답 페이지 완전성 통과와 F_t 출전집합 적격은 별개**다. 이번에는 실제 F_t 봉인 또는 실제 feature snapshot/예측 admission을 생성하지 않는다.

mock 검사는 페이지 누락/중복, 누락된 totalCount, parsing 실패 원문 보존, 요청 예산과 retry, 시각 역행·정상 수집, key 식별 충돌에 한정한다. 합성 저장기의 기능을 다시 전면 재구현하지 않는다.

## 제출과 종료

`docs/CONFIRMED_STARTER_E8B_2026-09-13.md`, 새 adapter/runner/테스트, 원문 CAS·capture 원장, 페이지/키/시각 감사 JSON, 보존·신규 source·출력 manifest를 제출한다. 보고서에는 실제 HTTP 횟수, 대상 일자/경주, 완전 수집 횟수, 마지막 관측 완료시각, T−30까지의 차이, 실패·불확실 항목을 기재한다.

상태는 실제 결과에 맞춰 `capture_only_completed` 또는 `capture_only_incomplete`로 기록하고, 모델/운영 활성화는 `not_activated`, F_t 적격은 `unverified`로 유지한다. 관련 Ruff check/format과 전체 pytest를 수행하며 기존 범위 밖 오류를 수정하지 않는다.

실제 원천의 제약을 확인한 뒤 수집 주기·취소 원천·보존 운영을 결정할 수 있게 보고하고 종료한다. 동일 turn에서 자동화·대량 수집·새 모델 연구·실전 발행으로 확장하지 않는다.
