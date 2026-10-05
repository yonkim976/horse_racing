# KRA 경주 결과 정규화 조사 데이터 v1

조사일은 2026-09-29다. 이 폴더는 `API4_3/raceResult_3` 원문을 경주 이벤트와 말별 결과 행으로 정규화한 **독립 연구 산출물**이다. 원천 응답은 [앞 단계 일정 조사](../20260929_calendar_api_v1/raw/race_execution_probe/)에 보존되어 있다. 이 작업은 operational DB를 읽거나 수정하지 않는다.

경주 계획과 시행 플래그는 앞 단계의 [race_plan.csv](../20260929_calendar_api_v1/race_plan.csv) 및 [race_execution_flags.csv](../20260929_calendar_api_v1/race_execution_flags.csv)를 키와 상태 원장으로 사용한다. 기본 결합 키는 API 요청 meet 코드, API 결과 `rcDate`, `rcNo`다. 계획의 예정일·예정시각과 결과 응답의 관측 날짜·시각 필드를 분리했다. `meet`는 API 응답 원문 표기이며, 특히 계획에 없는 결과 키는 실제 경주로 확정하지 않는다.

## 파일

| 파일 | 행 수 | 내용 |
|---|---:|---|
| [race_events.csv](race_events.csv) | 29,826 | 오류 제외 후 계획 경주별 이벤트. 예정 필드와 결과에서 관측한 날짜·경마장 표기·경주명·거리·등급·주로·날씨를 분리한다. |
| [runner_results.csv](runner_results.csv) | 331,811 | 오류 제외 후 말별 행. 착순·개별 기록·말·기수·조교사·마주·부담중량·배당·주로·날씨 필드와 원문 포인터를 제공한다. |
| [unverified_result_only_keys.csv](unverified_result_only_keys.csv) | 0 | 계획 밖 결과 키 검증용 빈 원장. 확인된 오류 72개는 활성 결과에서 제외했다. |
| [scope_exclusions.csv](scope_exclusions.csv) | 753 | 확정된 오류 경주 72개의 원천 항목 위치·사유를 기록한다. |
| [manifest.json](manifest.json) | — | 입력 응답 및 이전 키 원장의 SHA-256, 출력 SHA-256, 행 수, 검증 결과와 원천별 범위를 기록한다. |
| [build_race_results.py](build_race_results.py) | — | 원문 응답과 앞 단계 원장에서 위 파일을 재생성하고 구조·키·건수 검증을 수행한다. |

## 보존·상태 규칙

- 말별 CSV의 `source_file`과 0부터 시작하는 `source_item_index`가 압축된 원문 JSON의 원래 `items.item[]` 항목을 가리킨다. `manifest.json`의 `response_payload_sha256`은 압축을 푼 응답 바이트의 해시다. 전체 API 필드와 원래 값은 이 원문 포인터를 통해 확인할 수 있다. 선택한 정규화 열은 원문 값을 그대로 옮기며 보정·추정하지 않는다.
- `positive_finish_evidence=1`은 이전 원장의 규칙 그대로 `1 <= ord <= 89`이고 `rcTime > 0`일 때만 부여한다. 원천 `ord`, `rcTime`은 각각 `result_rank_raw`, `finish_time_seconds_raw`에 보존한다. `ord=99`, `ord=0`, `rcTime=0` 같은 행은 삭제하지 않으며 완주 시행 증거로 바꾸지 않는다.
- 원천 `name`은 말의 생산국/원산지 표기로 runner 행에 두고, `rcTime`은 말별 경주기록으로 runner 행에 둔다. 둘 다 경주 공통 속성 일치 검사에서 제외한다. `buga1`은 말별 수득상금으로 취급하지 않고 `additional_prize_1_raw`라는 원문 기반 이름으로 둔다. `prizeCond`도 성별·연령조건으로 해석하지 않고 `prize_condition_raw`에 원문을 보존한다.
- `execution_status`는 앞 단계 플래그를 그대로 연결한다. 이전 시행 경주를 복사하거나 변형한 72개 오류 키와 말별 753행은 활성 원장에서 제외하고 [판정 원장 20건](../20260929_calendar_api_v1/planless_positive_result_review.csv), [판정 원장 52건](../20260929_calendar_api_v1/result_only_nonfinish_anomaly_review.csv)과 원천 응답에 근거를 남겼다.
- `planned_no_execution_evidence`는 이 결과 원장을 생성할 당시의 **원천 대조 상태**다. 이후 116개 모두 [경주별 최종 판정 원장](../20260929_calendar_api_v1/race_nonexecution_adjudication.csv)에 `no_valid_completed_race`로 확정했다. 코어 DB의 `race_execution_adjudicated` 뷰에서 원천 상태와 최종 판정을 함께 조회할 수 있다.
- 일정의 예정 정보는 `scheduled_*`, API 결과의 관측 정보는 `actual_*` 열과 `result_event_field_distributions_json`에 있다. `actual_*` 단일 값 열은 해당 이벤트의 모든 결과 행에 같은 필드 값이 있을 때만 채운다. 값 충돌 또는 필드 누락은 빈 단일 값으로 표시하고 분포 JSON에 각각 보존한다.
- 경주별 `track`과 `weather`는 KRA API 원문 표기를 보존한다. 별도의 주로 상태 코드화나 날씨 보정은 하지 않았다.
- 계획에 없는 결과 API 키는 모두 오류로 판정해 활성 결과에서 제외했다. 원천 응답은 보존한다.

## 검증 결과

| 검사 | 결과 |
|---|---:|
| 계획 경주 키 | 29,826 |
| 원천 API 결과 항목 / 오류 제외 후 말별 행 | 332,564 / 331,811 |
| 계획 + 결과 완주 증거로 시행 확인된 키 | 29,710 |
| 계획 키에 결과 행은 있지만 양수 완주 증거가 없는 키 | 116 |
| 활성 계획 밖 결과 키 전체 | 0 |
| 오류로 제외한 경주 키 / 말별 행 | 72 / 753 |

2020-08-09 서울은 1~12경주 12개 키가 있고, 경주별 원천 결과는 9~11행이다. **12개 경주의 모든 말 행이 `ord=99`, `rcTime=0`**이므로 전 행을 보존하면서 `planned_no_execution_evidence`로 남겼고, 시행 확인 건수에는 넣지 않았다. 빌더가 이 날짜의 12개 키와 행별 상태를 다시 확인한다.

### 이벤트 속성 일치 검사

`manifest.json`의 `event_attribute_audit`은 말별 반복값 중 이벤트 수준으로 취급한 `meet`, `rcDate`, `rcDay`, `rcNo`, `rcDist`, `rcName`, `rank`, `prizeCond`, `track`, `weather`, `chaksun1`~`chaksun5`, `buga1`을 키별로 대조한다. `name`(말 생산국/원산지)과 `rcTime`(말별 기록)은 이 검사에서 제외했다.

| 결과 | 이벤트 속성 |
|---|---|
| 서로 다른 값이 한 경주 안에 나타난 이벤트: **0건** | 검사한 속성 16개 모두 |
| 원문 값이 모든 말 행에서 빠진 이벤트: **64건** | `rcDist`, `rcName`, `rank`, `track` 각 64건 |
| 원문 값이 모든 말 행에서 빠진 이벤트: **65건** | `prizeCond` |
| 검사 속성이 모든 말 행에 있고 동일한 이벤트: 나머지 전체 | 각 속성의 세부 건수는 매니페스트에 기록 |

누락은 값을 추정하거나 채우지 않고 이벤트 속성 분포에 `present=false`로 남겼다. 이 검사는 API가 해당 필드를 일관되게 반환하는지 확인하며, 응답값의 현실 세계 정확성을 독립적으로 증명하지는 않는다.

## 재현

저장소 루트에서 실행한다.

```bash
python3 thoroughbred/research/20260929_race_results_api_v1/build_race_results.py
```

입력은 앞 단계에 저장된 응답을 재사용하며, 네트워크 요청은 하지 않는다. 빌드가 선언된 건수·응답 총계·결과 키 집합·키별 결과 행 수·양수 완주 증거 수·2020-08-09 예외를 확인한 뒤 매니페스트를 쓴다.
