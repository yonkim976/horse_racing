# API42_1 제주마 후보 마필정보 수집

한국마사회 마필종합 상세정보 `B551015/API42_1/totalHorseInfo_1`를 말 ID별로 조회해 현재 프로필의 `breed`와 원문 날짜 필드를 보존한다. 현재 프로필 조회 시점은 기록하지만, 원문 날짜 필드나 현재 품종을 과거 경주일에 소급 적용하지 않는다. API20_1 `majong`은 주행심사일 관측으로 별도 교차표에 보존한다.

## 동결된 대상

- 우선 조회: `jeju_race_population_candidates`의 경주결과 후보 4,006 고유 `horse_id`.
- 최종 전체 대상: 위 후보와 API20_1 `majong=제주` 전체 4,617 ID의 합집합. 경주 후보 밖의 API20_1 보조 ID는 611개다.
- 대상 ID 및 API20 교차표는 첫 실행 시 SQLite 읽기 전용 연결로 만들어 SHA-256을 기록한다. 이후 재개에서는 동결 파일 해시를 확인한다.

## 실행 및 재개

저장소 루트에서 다음을 실행한다.

```sh
./.venv/bin/python3 jeju/research/20260930_api42_horse_breed_collection/collect_api42_profiles.py
```

공공데이터포털의 [마필종합 상세정보 API 신청 페이지](https://www.data.go.kr/data/15057985/openapi.do)는 개발계정 트래픽을 이 API 서비스당 3,000회로 표시하고, 에러코드 22를 해당 서비스의 일일 허용량 초과, 코드 23을 초당 호출 허용량 초과로 정의한다. 수집기는 이 API42_1 서비스만 하루 최대 3,000회 시작하도록 제한한다. 다른 한국마사회 API의 호출은 이 API42_1 서비스 한도에 합산하지 않는다. 각 API 요청 시작 간격은 최소 1.05초다. HTTP 429, 에러코드 22/23, 권한/키 오류에서 즉시 중단한다. 요청 실패는 ledger와 격리 원장에 남긴다. 다음 실행에서는 미요청 ID와 timeout/transport/5xx 실패만 말별 최대 2회까지 재시도하고, 0건·ID 불일치 등 나머지 실패는 자동 재요청 없이 격리에 둔다. 2026-09-30에는 이전 600회와 이어서 총 3,000회를 시작해 일일 수집기 상한에서 멈췄다. 공개 페이지에서는 계정의 실시간 잔여량을 볼 수 없으므로 이 계산은 이 수집기가 기록한 호출 시작 수에 근거한다.

각 KST 날짜의 수집은 같은 날짜를 `checked_on_kst`로 기록한 `quota_checkpoint_YYYYMMDD.json`을 요구한다. 실행 상태에는 당일 checkpoint만 저장해 전날의 호출 수와 잔여 한도가 복사되지 않게 한다. 2026-10-01 checkpoint는 `quota_checkpoint_20261001.json`이다. 이후 날짜에 재개하려면 공식 포털 한도를 그 날짜에 확인해 새 checkpoint를 만들고, `collector_requests_started_before_resume`와 `maximum_additional_collector_requests_today`를 그날 ledger 및 state의 시작 수에 맞춰 기록한다. 날짜가 맞는 checkpoint가 없으면 수집기는 네트워크 요청 전에 중단한다.

서비스키는 프로젝트 설정에서 메모리로만 읽으며 파일, 로그, URL, manifest에 기록하지 않는다.

2026-09-30 마감 결과는 [`RESULTS.md`](<RESULTS.md>)에 보존했다. 최신 결과인 [`RESULTS_20261001.md`](<RESULTS_20261001.md>) 기준으로 동결 대상 4,617마리의 수집이 완료됐고 남은 ID는 0이다. 새 대상이나 재시도할 미완료 프로필이 생기면 다음 KST 날짜의 공식 한도 확인과 날짜별 quota checkpoint를 준비한 뒤 같은 명령을 수동 실행한다. 예약 작업이나 cron은 만들지 않았다.

## 산출물

- `target_ids.jsonl`, `api20_crosswalk.jsonl`, `target_manifest.json`: 동결된 대상·교차 근거와 SHA-256.
- `raw/<hrNo>/attempt_*.json`: HTTP 응답 본문 바이트 원문. 파일별 SHA-256은 `request_ledger.jsonl`에 기록하고 저장 후 재검증한다.
- `request_ledger.jsonl`: 요청별 HTTP/API 상태, `totalCount`, 실제 행 수, 요청 ID와 반환 ID, 품종, 프로필 날짜 필드, 응답 SHA-256을 기록하는 재개 원장.
- `quarantine_ledger.jsonl`: 0건, 다건, ID 불일치, 날짜 형식/응답 오류, 타임아웃 등 검토·재시도 대상과 원문 경로를 기록.
- `collection_state.json`, `collection_summary.json`: 마지막 실행 상태와 현재 누적 집계.
- `quota_checkpoint_YYYYMMDD.json`: 날짜별 공개 API 한도 확인과 당일 시작 수 기준.

## 해석 제한

API42_1의 `breed`는 조회 당시 현재 프로필 값이다. `chgDt`, `birthDt` 등의 반환값은 공식 정의와 유효기간을 별도로 확인하기 전까지 원문 필드로만 취급한다. API42_1 현재 값과 API20_1 심사일 `majong`이 다르면 충돌로 집계하고 어느 쪽도 과거 전체 기간의 품종으로 단정하지 않는다.

빈 값과 `-`, `0`, `N/A`, `unknown`, `미상` 같은 placeholder는 품종 검증 완료로 세지 않는다. 응답 원문과 반환 label은 보존하고 검토 대상으로 격리한다.
