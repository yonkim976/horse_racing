# Daily training rider ID local inventory

이 결과는 2026-10-15 연구DB의 `daily_training_raw`와 공식 기수 프로필 스냅샷을 읽기 전용으로 대조한 로컬 조사입니다. 범위는 `prNo` 값의 원시 형태, `prGubun` 범주별 분포, 공식 기수 프로필 ID와의 **문자열 완전일치**, 그리고 이름/역할의 구분입니다.

## 핵심 결과

- 일별조교 5,173,033행 중 `rider_id_raw`(API 원필드 `prNo`)가 `-`인 행은 3,383,170개입니다. NULL 또는 빈 문자열은 없습니다. 나머지 1,789,863행에는 고유 ID 352개가 있습니다.
- 값 352개 중 숫자 6자리 316개(1,789,768행), `08A...` 형태의 영숫자 6자리 36개(95행)입니다.
- `person_reference_profile_snapshots`의 API307 기수 프로필 ID `official_id_raw_string`와 문자를 바꾸지 않고 직접 비교했을 때 282개 ID, 1,599,488행이 일치합니다(비표식 행의 89.36%). 예: `080014` ↔ 공식 프로필 이름 `김귀배`, `080411` ↔ `조창욱`. 이름은 exact ID join 후 프로필 스냅샷에서 읽었습니다.
- 일치한 프로필 ID 중 280개는 race/trial entity roster에도 직접 연결됩니다. 280개 각각의 과거 exact raw name variant는 1개이고 프로필 스냅샷 이름이 모두 일치했습니다. 이름 문자열이 여러 공식 ID에 재사용된 ID는 16개여서 이름만으로 연결하면 모호합니다.
- 동일한 공식 기수 ID가 여러 `prGubun` 원문 범주에 등장합니다. 전체 기록 범위에서 `기수+조교보` 23개, `기수+조교승인` 63개, `기수+조교사` 4개 ID가 겹칩니다. 이 집계는 서로 다른 행 사이의 누적 중복이며, 같은 날짜/같은 조교의 역할이나 당시 자격을 뜻하지 않습니다.
- API307 profile snapshot schema에는 별도의 `prNo` 또는 사번 열이 없고 `official_id_raw_string`만 있습니다. DB가 참조하는 API307 원본 JSON 파일은 로컬에 존재하지 않아, 로컬 자료만으로 `prNo`와 사번의 의미를 확인하지 못했습니다. 로컬 공식 말 프로필 JSON에서도 `"prNo"` 키 검색 결과가 없었습니다.

## 근거와 제한

`daily_training_raw`에는 `rider_id_raw`, `rider_type_raw`, `trainer_name_raw`가 있고 기승자 이름 또는 rider entity ID 열은 없습니다. 프로젝트 빌더는 원본 `prNo`를 `raw_rider_id`로, `prGubun`을 `raw_rider_type`으로 보존합니다([build_daily.py](../../20261002_training_three_v1/daily/build_daily.py:969)). DB의 `daily_training_raw` 및 프로필/roster 테이블만 읽었고, `raw_payload_json`에서 사람 이름을 가져와 연결하지 않았습니다.

결과 전체, 범주별 행/ID 수, 여러 범주에 걸친 ID, 스키마 검토 항목은 [daily_training_rider_identity_inventory.json](daily_training_rider_identity_inventory.json)에 있습니다. `prNo`가 공식 기수 ID로 쓰이는지에 관한 의미 해석과 `prGubun`의 업무상 정의는 공식 API 문서 검토 결과와 함께 판단해야 합니다. 정확한 이름 연결 가능성과 해당 조교 기록 당시 실제 역할은 서로 다른 질문입니다.
