# 마사회 주행심사 결과: API20_1 정규화 데이터

> 2026-10-01 후속 정정: 2026-09-17 영남 주행심사 4회차·48행은 [공식 계획 및 사용자 설명 재검토](../20261001_yeongnam_trial_venue_recheck_v2/README.md)를 거쳐 코어 DB의 별도 검토 뷰에서 부산경남·1,000m로 보완했다. 아래는 최초 원천 검토 기록이며, API·RPT 원문과 이전 CSV는 변경하지 않았다.

`thoroughbred/research/20260929_calendar_api_v1/raw/trial_result`에 보관된
`API20_1/ridingTestResult_1` 응답을 정규화했습니다. 원본 파일은 읽기만 하며,
이 디렉터리에 결과와 검증 자료를 기록합니다.

## 파일

- `participants.csv`: 원본 참가자 전 행. 날짜·세션·마명 관련 정규화 필드,
  출처 정보, 전체 API 필드를 담습니다.
- `sessions.csv`: 요청 meet 코드, API `trainDate`, `trainNo`별 세션 요약과
  참가자 수·미식별 ID 수.
- `unidentified_participants.csv`: API 말 ID(`hrNo`)가 없는 행의 검토용 추출본.
  이 행들은 `participants.csv`에도 그대로 포함됩니다.
- `source_manifest.json`: 원본 경로, 요청 연도·meet 코드, 응답 상태, 행 수,
  원본 파일 SHA-256.
- `validation.json`: 원본 대조 결과와 생성 파일 해시.
- `build_dataset.py`, `validate_dataset.py`: 재생성 및 검증 스크립트.

## 정규화 기준

`trial_date`는 API `trainDate`를 ISO 형식으로 표시합니다. 원본 필드와 JSON
자료형은 `api_trainDate`와 `source_record_json`에도 보존합니다.
`trial_session_id`는 요청 meet 코드, API `trainDate`, `trainNo`로 만듭니다.
API의 meet 명칭은 `api_meet_label`에 원문 그대로 기록하고, 요청 meet 코드는
별도 `source_meet_query` 필드에 둡니다.

`horse_id`와 `horse_name`은 각각 `hrNo`, `hrName`의 값이며, 누락값을 그대로
유지합니다. `horse_id_missing`으로 ID 누락 여부를 표시하고, 신원은 추정하지
않습니다. `source_item_index`는 원본 응답 배열의 0부터 시작하는 인덱스입니다.
`participant_row_id`는 원본 파일 경로와 해당 인덱스로 구성합니다.
`source_file_sha256`으로 사용한 원본 파일을 확인할 수 있습니다.

API 응답에는 심사 등급 필드가 없어 등급이나 등급 대체값을 만들지 않았습니다.
API meet 명칭으로 실제 경주장도 추정하지 않았습니다. 특히 요청 meet `3`의
2026-09-17 기록은 원문 `영남`을 유지하고, 실제 장소는 미확정으로 둡니다.
영천을 장소로 지정하지 않았습니다.

## 범위와 검증

원본은 2010~2026년 34개 응답 파일이며, 61,777개 참가자 행, 6,199개 세션,
1,633개 meet/date 조합을 포함합니다. API meet 명칭별 행은 `서울` 37,192개,
`영남` 24,585개입니다. `hrNo`와 `hrName`이 모두 없는 104개 행을 확인했으며,
이 행들도 본 데이터와 검토용 추출본에 남겼습니다.

저장소 루트에서 실행합니다.

```sh
python3 thoroughbred/research/20260929_trial_results_api_v1/build_dataset.py
python3 thoroughbred/research/20260929_trial_results_api_v1/validate_dataset.py
```

검증 스크립트는 모든 원본 행의 보존, API 행 JSON 및 원본 해시 일치, 세션별
참가자 수 합계, 미식별 행 추출본 일치 여부를 확인합니다. 2026-09-17 meet `3`의
API 명칭 `영남`이 유지되고 실제 장소가 추가되지 않았는지도 확인합니다.
