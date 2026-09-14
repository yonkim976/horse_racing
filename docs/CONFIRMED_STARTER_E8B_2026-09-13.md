# E8-B: 공식 일정·출전표 제한 수집 결과 (2026-09-13)

## 결론

`capture_only_incomplete`. 2026-09-13 18:05–18:06 KST에 서울 **2026-09-19** 한 날짜만 대상으로 공식 `/API154/racePlan`과 `/API26_2/entrySheet_2`를 조회했다. 첫 격리 시도에서 일정 전송 2회가 `ConnectError`였고, 실패 감사 코드의 null 처리 결함으로 실행이 중단됐다. 이 시도의 원장과 사전 프로토콜은 그대로 보존했다. 결함을 고친 두 번째 격리 시도에서 실제 전송 3회 모두 HTTP 200 응답을 받았지만 일정 1회·출전표 2회가 모두 명시적 `totalCount=0`, 실제 item 0이었다. 합계 **실제 transport 전송 5/12회**다. 다른 날짜·경마장으로 확대하지 않았다.

따라서 *빈 응답의 페이지 envelope 완전성*은 검사되었지만, **실제 비어 있지 않은 출전표의 완전 수집은 0회**이고 대상 경주도 없다. 마지막 원문 관측 commit 완료는 `2026-09-13 18:06:26.132 KST`다. 원천 일정의 출발시각이 하나도 없으므로 T−30 차이는 계산 불가(`null`)이며 prospective 사례는 없다. 운영/모델은 `not_activated`, 실제 `F_t` 적격은 `unverified`다.

## 구현·재현

- 격리 adapter는 공식 두 endpoint만 허용하고, redirect 자동 추적을 끄며, 실제 transport send를 세어 최대 12회에서 차단한다. 페이지당 최대 2회 시도하며 재시도도 독립 관측으로 기록한다. 운영 `KraApiClient`, DB, schema, registry, scheduler, UI, 합성 봉인 경로는 건드리지 않았다.
- 응답 바이트를 SHA256 CAS에 먼저 보존한다. 원장에는 endpoint, 공개 파라미터, HTTP 상태, 요청/수신/파싱/commit 완료 시각, parser 코드 해시, batch/page/attempt, 실패 종류, 원문 해시를 append한다. API 공개·적용 시각은 원천에 없으므로 `null`이다. 실제 시각은 시스템 시계에서 단계별로 취득하며 역행을 거절한다.
- 원문 header 성공 코드와 명시적 `totalCount/pageNo/numOfRows`를 parser 기본값과 독립 검증한다. page 연속성·중복·중간 빈 페이지·count 일치·날짜/서울 혼입·source key 및 출전번호/말 ID 충돌을 검사한다. 전체 일자 count와 경주별 count를 분리한다. source key는 `(meet, rcDate, rcNo, chulNo, hrNo)`이며 운영 entry ID를 합성하지 않는다.
- 원문 CAS는 권한 `0700` 폴더의 `0600` 파일에 둔다. 인증값과 인증 포함 URL은 원장·보고서에 쓰지 않는다. 응답에 credential이 반사되면 공개 감사의 source key와 사례를 억제한다. 실제 응답에서 반사는 검출되지 않았다. 원문 자체는 비공개 CAS에 그대로 보존한다.
- 모의 transport 회귀 7개가 성공했다: 완전 페이지/source key, 누락된 `totalCount`와 parser 실패 시 원문 보존, transport 예산·retry·redirect 비추적, 정상/역행 시각, 페이지 누락·중복/식별 충돌, 통신 실패의 null metadata 감사. 최초 실제 실패가 발견한 null 감사 반례를 별도 테스트로 고정했다.

실행된 검증: 관련 Ruff `format --check` 및 `check` 통과, 전체 `pytest -q` **618 passed, 2 warnings**. 두 경고는 기존 Starlette deprecation과 Polars PIT sortedness 경고다.

## 산출물과 해석

첫 중단 시도는 `data/experiments/confirmed_starter_e8b_20260913/`의 사전 프로토콜·append 원장·중단 평가에 남아 있다. 두 번째는 `data/experiments/confirmed_starter_e8b_20260913_attempt2/`의 `preflight_protocol.json`, `capture_journal.jsonl`, `raw_private/`, `page_key_time_audit.json`, `manifest.json`, `post_capture_assessment.json`에 남아 있다. 사전 프로토콜은 최초 HTTP 전에 날짜와 파라미터를 기록했다. 실제 원문 3개는 같은 136-byte 응답으로 SHA256 `640c1da4ea90e6ffd55e7d69b9fec7afe03bdbd1b82b8ed662db4442fd6e2e5d`의 CAS 객체 1개다. 두 출전표 관측은 약 110ms 간격으로 raw/key/value가 같지만 **빈 응답**이므로 출전집합 안정성이나 취소 반영을 입증하지 않는다.

원 수집 감사/manifest는 덮어쓰지 않았다. 수집 뒤 “빈 출전표는 재조회하지 않기”와 실패 감사의 null 경로를 보완한 최종 코드 해시 및 첫 실패를 포함한 총 요청 수는 append 성격의 `post_capture_assessment.json`에 기록했다. 수집 시점 코드 해시와 최종 코드 해시가 다른 이유도 그 파일에 명시했다.

## 남은 한계와 독립 검증 포인트

9월 19일 일정·출전표가 이 관측 시점에 빈 것은 확인됐지만, 향후 공개 시각·자료 변경 주기·취소/정정 완전성은 알 수 없다. 빈 페이지의 `totalCount=0` 검사는 비어 있지 않은 여러 페이지의 실전 pagination 검증이 아니다. 실제 source key 사례, 경주별 출전두수, T−30 margin은 얻지 못했다. 검증 담당자는 두 시도의 전송 원장 총 5회, preflight의 날짜/endpoint, raw CAS 해시·권한, empty-envelope과 capture status의 구분, 최초 실패가 회귀 테스트로 고정됐는지 확인하면 된다. 이 결과로 실제 `F_t` 봉인, feature snapshot, 예측, 평가, 운영 승격, 자동 수집을 시작해서는 안 된다.
