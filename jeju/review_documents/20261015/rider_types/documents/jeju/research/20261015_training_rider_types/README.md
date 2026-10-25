# 제주 일별조교 기승자 종류 저장 — 2026-10-15

제주 로컬 DB `jeju/data/jeju_native_core.sqlite3`에 일별조교 908,316행의 종류를 저장했다. 확인된 종류만 분류하고 근거 없는 298,875행은 **미분류**로 남겼다. 새 분석 조회의 이름 필드 `jockey_name`은 종류가 **기수**인 경우에만 제공한다.

## 종류별 조교 기록 행 수

| 종류 | 전체 저장 범위 | 분석 상한 2026-09-19까지 |
|---|---:|---:|
| 기수 | 315,601 | 315,295 |
| 조교사 | 111,648 | 111,527 |
| 조교보 | 71,889 | 71,889 |
| 조교승인 | 107,371 | 107,371 |
| 기수후보생 | 1,696 | 1,696 |
| 주로조교 | 1,236 | 1,185 |
| 교육생 | 0 | 0 |
| 기수 트랙라이더 | 0 | 0 |
| 미분류 | 298,875 | 298,426 |
| **합계** | **908,316** | **907,389** |

전체 원문 범위는 2007-10-01~2026-09-28이다. 수량은 원문 조교 기록 행 수이며 실제 시행 횟수나 인원 수로 단정하지 않는다. 교육생·트랙라이더 0행은 현재 확보한 표기로 확인된 행이 없다는 뜻이다. 제주에 해당 인력이 없었다는 뜻이 아니다. API의 기수후보생과 홈페이지의 교육생은 원표기의 구체성을 보존해 별도 종류로 뒀다.

[종류별 집계 CSV](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_types/rider_type_counts.csv>), [적용·기간별 집계](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_types/production_apply.json>), [독립 원천 감사](<audit/README.md>).

## 분류 근거와 미분류

- API18 `prGubun_raw`의 기수·조교사·조교보·조교승인·기수후보생을 기본 종류로 사용한다. 원문은 수정하지 않는다.
- API 종류가 `-`여도 **같은 말·날짜·입장·퇴장·조교 분**이 일치하는 공식 홈페이지 표기가 있으면 그 조교행만 보완한다. `(관)` 1,236행은 공식 범례의 **주로조교**로 저장한다. 이를 관리사라는 직책과 자동으로 동일시하지 않는다.
- 범례 `조`/`(조)`는 조교사, `생`/`(생)`은 교육생, `이름(트)`는 기수 트랙라이더다. 표식 없는 이름은 보유 현역·은퇴 기수 API307 명부와 이름이 일치할 때 기수로 해석한다. 모호한 표기는 미분류다.
- API의 넓은 구분과 같은 사건 웹의 더 구체적인 표기가 있으면 원문을 유지하고 정규 종류를 세분화한다. 기수→기수 트랙라이더가 그 예지만 이번 자료에는 해당 사례가 없다. 후보생/교육생, 조교보·조교승인/주로조교는 원문 구체성을 유지한다. 다른 명시적 충돌은 미분류·`api_website_type_conflict`로 둔다. 이번 충돌은 0행이다.
- 같은 사번의 다른 날짜, 현재 등록 직책 또는 이전 작업에서 연결한 실명으로 과거 종류를 소급 추정하지 않는다. 이름 참조가 있어도 종류는 미분류일 수 있다.

미분류 298,875행은 **당시 종류 근거가 없는 298,852행**과 **홈페이지에도 `외`만 표시된 23행**이다. `외`의 뜻을 사람 이름이나 직책으로 확장하지 않는다. 이전 이름 연결의 미연결 164,732행과는 판정 기준이 다르다.

이번 작업은 기존 보유 API와 홈페이지 32페이지만 사용했으며 네트워크 재수집을 하지 않았다. 별도 파서로 재검토한 동일 사건은 1,691개다. 홈페이지 주로조교 1,236개·기수 311개·조교사 121개·미분류 23개이고, API에 이미 종류가 있던 432개는 원문 구분과 일치했다.

## DB 객체와 사용법

| 객체 | 내용 |
|---|---|
| `daily_training_rider_type_assignments` | 원 조교행당 1개, 908,316개의 저장된 종류·판정·원문 연결키·웹 근거 |
| `daily_training_rider_type_values` | 현재 원문 연결키와 저장된 판정을 비교한 종류·상태 조회 |
| `daily_training_rider_types` | 전체 일별조교 + 종류·기수 이름 |
| `daily_training_rider_types_analysis_2026` | 기존 분석 상한까지 907,389행 + 최신 말 이름·2026년 나이 |

새 분석은 `rider_type`, `rider_type_status`, `jockey_name`, `jockey_name_status`를 사용한다. 기수가 아닌 종류와 미분류의 `jockey_name`은 모두 NULL이다. 전체 기수 315,601행 중 이름은 315,599행에서 제공하고, 원문 사번이 없는 [2행](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_types/unresolved_jockey_names.csv>)은 종류를 유지하며 이름은 NULL로 둔다.

```sql
SELECT training_date, horse_id, current_horse_name,
       rider_type, rider_type_status, jockey_name, jockey_name_status,
       duration_minutes, prGubun_raw, prNo_raw
FROM daily_training_rider_types_analysis_2026
WHERE horse_id = '3107491'
ORDER BY training_date DESC;
```

`prGubun_raw`·`prNo_raw`·`trName_raw`와 이전 실명 참조 테이블·뷰는 추적용으로 보존했다. 담당 조교사명 `trName_raw`를 기승자명으로 대입하지 않는다. 기수 외 이름을 새 분석용 인물 변수에 넣지 않는다. 출발조교는 별도 자료이며 이번 집계와 합산하지 않는다.

검토행이 없거나 말·날짜·시각·기간·기승자 원문 구분·사번·원문 artifact 연결키가 바뀌면 조회 종류는 미분류이며 기수 이름도 NULL로 차단한다. 판정 상태는 각각 `type_review_not_applied`, `type_source_fields_changed`다.

## 실제 적용과 검증

- [실제 적용](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_types/production_apply.json>), [시험 적용](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_types/staging_apply.json>), [재실행 추가·수정 없음](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_types/staging_replay.json>), [메모리 차단 규칙 검증](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_types/guard_verification.json>).
- [실제 DB 독립 전수 검증](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_types/verification/production_full_html_verification.json>), [검증 사용법](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_types/verification/README.md>), [적용 전 백업](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_types/before_types.sqlite3>), [신규 스키마](</Users/kimyongjin/Desktop/horse_racing/jeju/data/schema/migrations/20261015_add_training_rider_types.sql>).
- 기존 사용자 테이블 34개의 1,845,196행 지문과 기존 SQL 정의가 모두 유지됐다. [SQLite 내부 통계 테이블 2개의 보존](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_types/sqlite_statistics_preservation.json>)도 별도 확인했다. 신규 조회의 중복·누락·원문 변경과 기수 외 이름 노출은 0건이다. 검증기 초기 시각 파싱 오류는 읽기 전용 실패 원장에 보존하며 최종 통과 보고서를 기준으로 판단한다.
- 기존 원문과 이름 연결 원장을 유지하고 신규 종류 테이블·조회만 추가했다. 기존 모델 입력과 가중치는 자동 갱신하지 않았다.

기본 명령은 원문 근거를 확인하고 새 계획만 출력한다. 보고서와 웹 대조 sidecar가 이미 있으면 덮어쓰지 않는다.

```sh
.venv/bin/python jeju/research/20261015_training_rider_types/classify_riders.py \
  --output jeju/research/20261015_training_rider_types/new_plan.json
```

실제 적재는 `--apply --expected-db-sha256 <현재 DB SHA>`를 추가한다. `--db`는 이 작업 폴더 안 시험 DB 경로 또는 제주 로컬 DB만 허용한다. 원문 기승자 구분 집합이나 기존 저장 판정이 바뀌면 재검토하며 자동 덮어쓰지 않는다. 재구축 시 기본 스키마·일별조교·이름 참조 적재 후 이 분류기를 적용한다. 사건 날짜와 과거 공개시각은 구분하며 같은 경주의 사후 자료를 사전 입력으로 사용하지 않는다.
