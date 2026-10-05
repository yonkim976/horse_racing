# 이전 연구 스냅샷의 장구 보관 방식

## 범위와 방법

`thoroughbred/data/dataset_20260929_v1/thoroughbred.duckdb`를 DuckDB `read_only=True`로 열어 `equipment_event`의 스키마·날짜·출처·연결상태·원문 텍스트를 집계했다. 보조로 2026-09-18 통합 연구 DB와 빌더·README를 읽었다. DB와 원천은 수정하지 않았고, 네트워크 수집도 하지 않았다. 원문 예시는 질병 표현이 포함됨을 확인하는 데만 썼으며, 이 보고서에는 말 이름, 요청 URL, 비밀값, 개별 원문을 싣지 않았다.

## 저장 형태와 범위

`equipment_event`는 장구 사전을 정규화한 테이블이 아니라 출전별 원문 이벤트 테이블이다. v1에는 329,297행과 아래 19개 열이 있다.

| 묶음 | 열 |
|---|---|
| 출전·개체 키 | `equipment_event_id`, `race_id`, `venue_code`, `canonical_meet`, `race_date`, `race_no`, `chul_no`, `hr_no` |
| 원문 | `horse_name_raw`, `horse_name_normalized`, `detail_raw` |
| 별도 진료 보조값 | `bleeding_count`, `bleeding_date_raw`, `illness_note` |
| 연결·출처 상태 | `link_status`, `availability_status`, `source_dataset`, `source_path`, `source_row` |

v1에 실제 보존된 범위는 경주장별로 다음과 같다.

| `venue_code` | 행 수 | 날짜 | `source_dataset` | 연결 상태 |
|---|---:|---|---|---|
| SEOUL | 193,918 | 2010-01-09–2026-09-13 | `seoul_backfill_20260915_v1` | 전 행 `confirmed_canonical_race_key` |
| BUSAN | 135,325 | 2010-01-08–2026-09-11 | `busan_complete_db_20260916` | 전 행 `confirmed_canonical_race_key` |
| YEONGCHEON | 54 | 2026-09-13 | `operating_db_meet4_confirmed` | 전 행 `confirmed_official_id` |
| 합계 | 329,297 | 2010-01-08–2026-09-13 | 세 출처 | 전 행에 `race_id`와 `hr_no` 존재 |

제주 행은 없다. `availability_status`는 329,297행 모두 `availability_unverified`다. 말/경주 연결 성공은 원문의 공개 시각이나 장구 의미가 확인되었다는 뜻이 아니다.

이 2010+ 범위는 2026-09-18 통합 DB의 `equipment_event`를 날짜로 잘라 만든 결과다. 원 통합본은 441,918행(서울 271,536, 부산 170,328, 영천 54)이며 서울 77,618행과 부산 35,003행은 2010년 이전이다. v1 빌더가 `race_date >= 2010-01-01`만 복사했다.

## `detail_raw`의 실제 성격

`detail_raw`에는 파싱된 장구 코드나 장구 변경 전·후 값이 없다. 전체 329,297행 중 공백 원문은 4,601행이다. 의미 판정이 아닌 간단한 단어 패턴 점검에서는 의료 표현만 매치한 행 81,625개, 장구 표현만 매치한 행 62,225개, 두 종류가 함께 매치된 행 146,746개, 어느 패턴에도 매치되지 않은 비공백 행 34,100개가 나왔다. 패턴은 한국어 표현 일부만 검사하므로 분류 정답이나 장구 목록으로 해석하면 안 된다.

특히 가장 이른 부산 출전일의 원문에는 운동기 질환, 피로 회복, 골막염, 감기, 예방접종, 치과 처치 같은 의료 기록만 있는 행과 장구 표현에 진료 문장이 붙은 행이 함께 있다. 서울·부산 파서는 `dacom71` 보고서의 출전마 줄을 `detail_raw`로 저장한 다음, 뒤따르는 날짜 형식 줄도 같은 필드에 개행으로 덧붙인다. 그래서 이 저장 관행 자체가 장구와 의료 텍스트가 한 칸에 섞일 수 있음을 코드로 확인해 준다.

따라서 이 테이블은 과거 출전 관련 원문 및 출처 흔적을 보존한 자료로는 쓸 수 있지만, 원문을 바로 고유 장구명 목록으로 집계하거나 `detail_raw` 행을 장구 변경 사건으로 간주할 근거는 없다. 2010+의 서울·부산 `bleeding_count`, `bleeding_date_raw`, `illness_note`는 변환 코드가 전부 `NULL`로 채웠다. 원문 문자열이 해당 정보를 별도 열로 완전히 구조화했다는 의미도 아니다.

## 로컬 빌더 경로

1. `scripts/build_seoul_backfill.py`와 `scripts/build_busan_history.py`는 지역별 `entry_equipment` SQLite 표를 정의한다. `dacom71` 텍스트에서 경주일·경주번호·출전번호·말 이름이 기존 공식 출전 행과 맞으면 원문을 저장한다. 원문에 날짜 형식 줄이 이어지면 같은 `detail_raw`에 개행으로 추가한다.
2. `scripts/build_unified_thoroughbred_dataset.py`는 서울·부산 stage DB를 읽기 전용으로 열어 `entry_equipment`를 통합 `equipment_event`에 복사한다. 경주일·경주번호·출전번호와 정규화 이름으로 출전표를 대조해 연결 상태를 설정하고, ID에는 출처 dataset·날짜·경주·출전번호·원천 경로를 포함한다. 영천 54행은 운영 DB의 `entry_equipment.equipment_raw`를 `detail_raw`로 옮긴다.
3. `thoroughbred/research/20260929_dataset_v1/build.py`는 2026-09-18 통합 DB를 `READ_ONLY`로 attach해 2010년 이후 표를 복사한다. 보고서 범위의 장구 행은 이 단계에서 제외된 오류 경주 행이 0개다. README는 원래 서울·부산 stage SQLite가 현재 저장소에 없어 이전 통합 DuckDB를 이 버전의 고정 과거 원천으로 삼았다고 명시한다.

관련 코드 위치:

- [지역별 원문 테이블 및 서울 파서](../../../../scripts/build_seoul_backfill.py#L105)
- [부산 파서의 원문 저장·날짜 줄 append](../../../../scripts/build_busan_history.py#L258)
- [통합 스키마와 출처 변환](../../../../scripts/build_unified_thoroughbred_dataset.py#L198)
- [v1 복사 날짜와 source DB 설정](../../20260929_dataset_v1/build.py#L23)
- [원 통합본에서 2010+ 복사하는 README 설명](../../20260929_dataset_v1/README.md#L51)

## 해석 제한

이전 `equipment_event`의 출전·말 링크 상태가 모두 확정이어도, 이는 출전 키 연결을 확인한 것이다. `detail_raw`를 장구 개념으로 분리·검증했다거나 해당 자료가 경주 전 이용 가능했음을 증명하지 않는다. 새 연구 코어의 장구 설계나 정답 목록을 이 이전 연구 스냅샷에서 그대로 승계하지 않는 것이 맞다.
