# 제주 일별조교 기승자 사번·이름 연결 — 2026-10-15

제주 로컬 DB `jeju/data/jeju_native_core.sqlite3`에 사번별 이름 참조와 홈페이지의 동일 조교행 확인 근거를 추가했다. **908,316행 중 743,584행(81.86%)에서 사번 기준 이름을 조회할 수 있고, 164,732행은 미연결로 남는다.** 원래 조교행·사번·기승자 구분·담당 조교사명은 유지한다.

이름은 공식 번호에 연결한 참조명이다. 과거 모든 조교행의 실명을 개별 홈페이지에서 검증한 것은 아니다. 이번 홈페이지에서 해당 말·날짜·시각까지 직접 확인한 이름은 별도 필드로 제공한다.

## 저장과 조회

| 객체 | 내용 |
|---|---|
| `training_rider_identity_reviews` | 기승자 구분×원문 사번 303개 검토행, 참조 이름·상태·공식 근거 |
| `training_rider_website_observations` | 홈페이지와 정확히 일치한 1,259개 조교행. 실명 1,236개, 이름 없는 `외` 표기 23개 |
| `daily_training_riders` | 기존 일별조교 908,316행에 이름과 상태를 연결한 조회 |
| `daily_training_riders_analysis_2026` | 분석 상한 2026-09-19까지 907,389행. 최신 말 이름·2026년 나이 정책 유지 |

주요 필드:

- `rider_name`: 사번에 연결한 참조 이름. 근거 없으면 NULL이다.
- `prGubun_raw`, `prNo_raw`: API18 기승자 구분과 사번. 선행 0과 원문 `-`를 유지한다.
- `rider_reference_person_kind`: 이름을 찾은 참조의 종류다. 원문 구분 `-`인 과거 조교의 직책을 소급 확정하지 않는다.
- `rider_identity_status`, `rider_identity_evidence_json`: 연결 판정과 원문·ID·해시 근거다.
- `rider_name_on_website`, `rider_label_on_website_raw`: 같은 조교행에서 직접 확인한 실명과 홈페이지 원표기다. `한태경(관)`처럼 원표기도 보존한다. `외`는 원표기만 있고 실명은 NULL이다.
- `rider_name_same_event_website_verified`: 이번 수집에서 실명·말·날짜·입퇴장·조교 분이 직접 일치하면 1이다. 0은 이번 관측표에서 실명을 확인하지 않았다는 뜻이며 다른 과거 확인 근거가 없었다는 뜻은 아니다.
- `trName_raw`: 담당 조교사 원문명이며 기승자 이름으로 대입하지 않는다. `prGubun_raw='조교사'`인 행은 기승자의 사번을 공식 조교사 ID에 연결한다.

```sql
SELECT training_date, horse_id, current_horse_name,
       prGubun_raw, prNo_raw, rider_name, rider_identity_status,
       rider_name_on_website, rider_label_on_website_raw,
       rider_name_same_event_website_verified,
       trName_raw AS responsible_trainer_name_raw,
       start_time_local, end_time_local, duration_minutes
FROM daily_training_riders_analysis_2026
WHERE horse_id = '3107491'
ORDER BY training_date DESC;
```

백두명성 2026-09-16은 `003086`→이동준, 담당 조교사 원문은 문성호다. 녹색왕자 2026-09-28은 `005003`→한태경이며 홈페이지 `한태경(관)`·06:41~06:47·6분까지 직접 일치한다. 후자는 분석 상한 이후라 전체 조회에만 있다. [실제 조회 예시](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_identity/root/query_examples.json>).

## 연결 결과

| 근거 | 조교 원행 수 |
|---|---:|
| 기수 구분 + 공식 기수 ID 단일 이름 | 315,599 |
| 조교사 구분 + 공식 조교사 ID 단일 이름 | 111,648 |
| 구분 미제공 + 단일 종류의 공식 ID 이름 참조 | 66,818 |
| 기수후보생 구분 + 공식 기수 ID 참조, 후보생 구분 유지 | 1 |
| 홈페이지에서 확인한 직원 사번 50개의 실명 참조 | 249,518 |
| **합계** | **743,584** |

유효 기수·조교사 번호의 교집합과 참조 이름 충돌은 0건이었다. 원문 `-`를 번호로 비교하면 거짓 일치가 생기므로 사번 없는 행은 이름을 연결하지 않는다. 이름 유사도·번호 접두 추정·현재 담당 조교사명으로 연결하지 않았다.

직원 50개 사번은 각각 2개 이상의 서로 다른 말·날짜에서 같은 실명이 나왔다. 같은 사번의 과거 행에도 참조 이름을 붙였지만, 과거 날짜의 실명·직책이나 사번의 역사적 재사용 가능성을 전수 확정한 것은 아니다. 같은 사건의 직접 확인은 이벤트별 필드로 구분한다.

## 미연결 기록

| 원인 | 행 수 | 처리 |
|---|---:|---|
| 사번 자체가 `-` | 92,165 | 이름 NULL·`missing_employee_number`. 미기승이라는 뜻은 아님 |
| 사번은 있으나 확보한 명부·홈페이지에 실명 근거가 없음 | 71,748 | 이름 NULL·`unresolved_employee_number` |
| 홈페이지 정확 일치행도 실명 없이 `외`만 표시 | 819 | 사번 5개 전체 이력의 참조명 NULL·`website_person_name_not_provided`. 직접 본 원문은 23행 |
| **합계** | **164,732** | 추정 이름을 넣지 않음 |

미연결은 기승자 구분×사번 76그룹이고 유효 사번은 중복을 제외하면 53개다. 실명 근거 없는 71,748행은 48개 사번에 해당한다. 47개는 최근 홈페이지 조회 범위 밖의 과거 기록이며, `005319`는 범위 경계 2026-04-15의 단일 후보행을 홈페이지에서 찾지 못했다. 마지막 시행일만으로 퇴사·은퇴를 확정하지 않는다.

`외`만 확인한 번호는 `006045`, `006077`, `006078`, `006079`, `006080`이다. 이 한 글자를 사람 이름이나 공식 신분으로 확장하지 않는다.

[전체 사번 목록](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_identity/rider_identity_register.csv>), [미연결 사번·사유·행 수·기간](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_identity/unresolved_rider_numbers.csv>), [최근 홈페이지 후보 56개 사번 판정](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_identity/source_review/staff_website_identity_evidence.json>)을 보존한다. CSV의 사번도 텍스트로 읽어 선행 0을 유지한다.

## 원천과 검증 범위

1. 보유 API18 원문·기존 정규행을 사용했다. API4 경주결과·API20 주행심사의 공식 인물 ID와 이름을 대조했고, 근거 218개 관측의 payload와 36개 원문 페이지 SHA·item 위치를 확인했다.
2. 2026-10-08 수집한 [API307 기수 상세정보](https://www.data.go.kr/data/15056828/openapi.do) 전 지역 838개 응답을 참조했다. 이번에 새 API307 호출을 한 것은 아니다. API308 보유 원문은 홈페이지 수집 대상의 번호 범위 검토에 사용했다.
3. 명부로 연결되지 않는 최근 사번 56개를 포함하도록 공식 [말별 조교현황](https://race.kra.co.kr/racehorse/profileTrainState.do?Act=02&Sub=1&hrNo=3104703&meet=2) 32페이지를 받았다. 모두 HTTP 200이며 원문 바이트·SHA·말 ID를 보존했다. 홈페이지는 최근 6개월 자료라고 안내하며 과거 전체 기간 조회가 아니다.
4. 말 ID·날짜·입장·퇴장·조교 분이 함께 일치한 1,259개 관측을 별도 파서로 대조했다. 이름·역할 충돌이나 여러 사번이 같은 사건키에 겹친 경우는 없었다. 경주일 안내행은 조교행으로 만들지 않았다.
5. `금주출전예정`·`차주출전예정` 상태도 시간값이 있는 조교행이면 포함했다. 출발조교 기승자는 일별조교와 다를 수 있어 이름 대체 근거로 쓰지 않았다.

## 적용·복구·재현

- [실제 적용](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_identity/root/production_apply.json>), [시험 적용](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_identity/root/staging_apply.json>), [시험 재실행](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_identity/root/staging_replay.json>), [빈 검토표를 포함한 스키마 재구축 후 적재 검증](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_identity/root/schema_bootstrap_verification.json>), [집계](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_identity/summary.json>).
- [실제 DB 독립 검증](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_identity/verification/production_verification_report.json>), [참조 변경·미적용 차단 검증](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_identity/root/guard_verification.json>). 적용 전후 기존 34개 테이블의 모든 행 지문과 기존 SQL 객체 115개가 같았고 신규 조회의 중복·누락·원문 변경은 0건이었다.
- 적용 전 DB 사본은 `root/before_rider_identity.sqlite3`, 당시 모든 테이블 수·스키마는 [before_state.json](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_identity/root/before_state.json>)에 있다. 전체 DB 복원은 이후 다른 변경도 되돌릴 수 있으므로 범위를 먼저 확인한다.
- [신규 스키마](</Users/kimyongjin/Desktop/horse_racing/jeju/data/schema/migrations/20261015_add_daily_training_rider_identity.sql>), [로더](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261015_training_rider_identity/link_training_riders.py>), [공식 웹 보완](<source_review/README.md>), [ID 전수 감사](<audit/README.md>).

기본 실행은 근거를 재검증하고 새 계획 보고서만 쓴다. 출력은 이 작업 폴더 안의 새 경로로 지정한다.

```sh
.venv/bin/python jeju/research/20261015_training_rider_identity/link_training_riders.py \
  --output jeju/research/20261015_training_rider_identity/root/new_review_plan.json
```

적용은 `--apply --expected-db-sha256 <현재 대상 DB SHA>`를 추가한다. 시험 DB는 `--db`로 이 작업 폴더 안의 경로를 지정한다. 기존 검토행과 다르면 덮어쓰지 않고 중단한다. 참조 API payload SHA가 달라지거나 검토행이 없으면 이름은 NULL과 재검토 상태로 제공한다. 홈페이지 관측은 고정 SHA에 연결하며 원문 변경 시 새 버전으로 재검토한다.

인물 이름 연결로 사건 당시 직책·공개시각, 조교 강도·시행 횟수 또는 모델 성능 개선을 확정하지 않는다. 기존 모델 입력과 가중치는 자동 갱신하지 않았다.
