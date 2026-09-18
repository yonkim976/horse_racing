# 제주마 경주·주행심사 연구 DB 적재 보고서 (2026-09-15)

## 적재 결과

합의한 웹사이트식 구간 분석 기준으로 별도 연구 SQLite를 생성했다. 기존 `data/horse_racing.sqlite3`, 원문, 모델, 데이터셋, registry는 수정하지 않았다. 새 DB는 [jeju_native_analysis.sqlite3](../data/research/jeju_native_analysis_db_20260915/jeju_native_analysis.sqlite3)이며 SHA-256은 `b7f05ac07f0a08bb1fdfcf4983b06e8b964e8e1a17853f6a9787ae69de35844e`다.

| 구분 | 이벤트 | 적재 출전행 | 웹사이트식 구간 사용 가능 | 엄격 분석 뷰 포함 |
| --- | ---: | ---: | ---: | ---: |
| 제주마 경주 | 9,423 | 92,208 | 90,086 | **90,082** |
| 제주마 주행심사 후보 | 1,945 | 15,688 | 11,671 | **11,671** |
| 합계 | 11,368 | 107,896 | 101,757 | 101,753 |

경주의 사용 가능 90,086행 중 4행은 공식 API와 기존 DB 말 ID가 충돌한 미해결행이다. 원 체크포인트와 구간은 보존하되, 세 공식 ID가 완결된 `analysis_race_segments` 뷰에서는 제외했다. 따라서 일반 분석의 기본 분모는 **90,082출전행·407,327파생 구간**이다. 주행심사는 공식 `hrNo`와 당시 심사표의 `trNo`가 연결된 **11,671출전행·46,685파생 구간**을 `analysis_trial_segments` 뷰로 제공한다. 주행심사 공식 원천에는 당시 마주 ID가 없어 `ow_no`는 비워 두었다.

## 저장 구조와 구간 산식

`source_artifact`에는 실제 사용한 원천·연결 원장 1,108개의 경로와 SHA-256을, `source_request`에는 비밀키를 제거한 공식 요청 2,624건의 요청·응답 해시를 저장했다. `source_row`는 제주마 적재행의 정규화 JSON과 행 해시를 보존한다. `event`와 `entry`는 경주/심사 키, 출주번호, 말 이름, `hr_no/tr_no/ow_no`, 마종 근거, 공식 ID 상태, 완주기록, 분석 상태를 저장한다. 공식 ID는 모두 앞자리 0을 보존하는 TEXT로 검증했다.

`section_checkpoint`에는 S1F·1C·2C·3C·G3F·4C·G1F·FIN 원 값을 599,658행 저장했다. 종반 G3F/G1F는 원래 `closing` 값과 완주시간에서 변환한 출발 후 누적시간을 함께 구분한다. 코너 위치에는 `distance_is_approximate=1`을 둔다. `derived_segment` 454,028행은 같은 말의 인접 체크포인트 누적시간 차이다. `distance_m`은 두 지점 사이의 약 거리, `elapsed_ms`는 소요시간이다. 같은 위치의 S1F/3C/G3F처럼 공개값이 반올림 범위에서 맞는 지점은 한 위치로 묶는다. 결측 또는 시간 역전이 있으면 파생 구간을 만들지 않는다.

파생 구간 거리 분포는 100m 19,492행, 200m 402,889행, 210m 12,233행, 300m 12,157행, 400m 5,565행, 500m 665행, 600m 1,027행이다. 따라서 대부분은 사용자가 의도한 약 200m 단위이고, 장거리 경주의 공식 계측점 공백은 실제 300~600m 구간으로 유지했다. 값을 임의 보간하지 않았다.

## 제외와 격리

분석 소비자는 `analysis_race_segments`와 `analysis_trial_segments`를 사용하면 미해결·결측·모순행이 자동 제외된다. 원인을 조사할 때는 `quarantined_entries`, `resolution_issue`, `exclusion_summary`를 사용한다.

- `제` 표시지만 양수 정상 결과가 없는 135경주·1,316행은 `explicit_je_no_positive_result`로 보존하고 구간 분석에서 제외했다.
- 정상 경주 안의 비양수 완주행 744행과 구간 결측 57행, 구간 모순 5행은 상태를 분리했다.
- 경주 공식 ID 미해결 29행은 `missing_official_trNo` 25행, `official_row_absent_from_db` 4행이다.
- 주행심사 공식 ID 미해결 55행은 마명 충돌 34, 연령 충돌 14, 성별 충돌 6, 공식행 누락 1이다.
- 주행심사는 구간 결측 3,539행, 구간 모순 1행, 비양수 완주 422행, ID 미해결 55행을 분석 뷰에서 제외했다.
- 혼합 Text의 `한` 7,338행·`래` 818행·공식 프로필로 확인한 `검` 29행은 새 제주마 출전 테이블에 저장하지 않았다. `산` 6,016행은 제주마 근거가 없어 `excluded_from_native_breed_unconfirmed` 집계로만 남겼다.

2015~2018년 주행심사 Text에 없던 공식 상세표 구간값은 **2,981행**에 반영했다. `section_checkpoint.source_kind='trial_official_web_supplement'`로 표시해 Text 구간과 구분했다. 2003~2014년은 현재 확인된 말별 구간시간이 없으므로 완주기록과 신원 근거는 보존하지만 구간 뷰에는 포함하지 않는다.

## 분석 사용법

경주 구간 분석의 기본 조회는 다음과 같다.

```sql
SELECT event_date, event_number, distance_m,
       horse_number, horse_name, hr_no, tr_no, ow_no,
       segment_sequence, from_codes, to_codes,
       segment_distance_m, distance_is_approximate, elapsed_ms
FROM analysis_race_segments
ORDER BY event_date, event_number, horse_number, segment_sequence;
```

주행심사는 `analysis_trial_segments`를 같은 방식으로 조회한다. 특정 말의 경주와 심사를 함께 분석하려면 `hr_no`를 사용한다. `distance_is_approximate=1`은 구간 양 끝 중 하나 이상이 코너 기준이라는 뜻이다. 엄격한 공식 ID 완결성과 무관하게 시간 자체가 유효한 4개 경주행을 조사하려면 `entry.segment_quality='usable'`와 `identity_status='official_race_id_unresolved'`를 함께 조회한다.

재현 코드는 [build_jeju_native_analysis_db.py](../scripts/build_jeju_native_analysis_db.py), 독립 검증 코드는 [verify_jeju_native_analysis_db.py](../scripts/verify_jeju_native_analysis_db.py)다.

```bash
python3 scripts/build_jeju_native_analysis_db.py
python3 scripts/verify_jeju_native_analysis_db.py
```

빌더 검증과 독립 검증은 DB 무결성, 외래키, 1,108개 입력 원천 해시, 공식 ID 문자열 형식, 경주·심사 분모, 미해결 수, 보완 심사 2,981행, 사용 가능 101,757행, 파생 구간 454,028행의 전수 재계산을 통과했다. 결과는 [validation.json](../data/research/jeju_native_analysis_db_20260915/validation.json)과 [independent_validation.json](../data/research/jeju_native_analysis_db_20260915/independent_validation.json)에 있다. 이 적재는 과거 경주 전 공개 시각이나 예측 성능을 검증하지 않는다.
