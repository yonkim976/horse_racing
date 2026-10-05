# 제주 조교 API 원문과 동일 중복 점검

확인일: 2026-10-01

후속 판정: 사용자 제공 백두명성 홈페이지 화면에도 출발조교의 동일 내용 두 행이 표시돼 [화면 대조](<../20261001_training_website_crosscheck/README.md>)를 기록했다. 이 보고서의 동일 그룹은 내용 일치 집계이며 오류나 실제 사건 중복의 확정 수치가 아니다. **같은 내용의 원문 행을 한 행으로 줄이는 정제를 적용하지 않는다.** 아래 전수 집계는 관측 사실로 보존한다.

일별조교 API18_1과 출발조교 API22_1의 보유 원문을 전수 확인했다. **출발조교에는 전체 item이 같은 4,205그룹이 있고, 모두 두 번씩 나타난다.** 보유 제주마 ID에 연결되는 추가 반복은 3,299행이다. 이번 작업은 확인과 문서화이며 원문 삭제·DB 적재·중복 제거·새 API 호출·모델 변경은 하지 않았다.

모델 입력 기준의 정본은 [조교 API 자료와 모델 입력 기준](<../../docs/JEJU_TRAINING_API_INPUT_CONTRACT_2026-10-01.md>)이다. 이 폴더의 JSON·JSONL은 감사 원장으로, 모델 입력 파일이 아니다.

## 원문 범위와 연결

| 구분 | 일별조교 | 출발조교 |
|---|---:|---:|
| 원문 페이지 | 337 | 311 |
| 원문 행 | 1,444,319 | 295,471 |
| 보유 제주마 4,617두에 연결되는 원문 행 | 908,316 | 190,842 |
| 그중 2026-09-19까지의 행 | 907,389 | 190,790 |
| 연결 제주마 수 | 4,545 | 4,476 |
| 원문 최초 관측일 | 2007-10-01 | 2007-10-17 |
| 원문 최종 관측일 | 2026-09-28 | 2026-09-27 |
| 완전 동일 추가 반복 | 0 | 4,205 |

전체 원문 행은 제주 경주장 전체이고, 보유 제주마 연결 행은 공식 말 ID를 원문 문자열과 정확히 일치시킨 결과다. 반복 내용도 모두 포함한 집계다. **2026-09-19까지 보유 제주마 연결 출발조교는 190,790행을 보존한다.** 이전에 제시한 내용 유일화 가정의 187,491행은 현재 정제 계획이나 입력 모집단 수로 사용하지 않는다. 실제 조교 시행 횟수는 별도 확인이 필요하다.

## 완전 동일 판정 결과

하나의 원문 item에 존재하는 모든 키와 JSON 값의 형식·값이 같을 때만 동일 그룹으로 묶었다. 객체 키 순서는 무시했지만 문자열 공백, 이름, ID, 비고는 정리하지 않았다. 각 그룹에는 내용 SHA-256과 원문 파일 SHA-256, 요청 연도, 페이지 번호, item의 1부터 시작하는 순번을 기록했다.

| 항목 | 결과 |
|---|---:|
| 동일 그룹 | 4,205개 |
| 각 그룹 출현 횟수 | 전부 2회 |
| 동일 그룹에 속한 원문 출현 행 | 8,410행 |
| 대표 한 행을 남길 경우 추가 반복 | 4,205행 |
| 전체 원문 중 서로 다른 내용 | 291,266개 |
| 같은 페이지 안의 그룹 | 4,199개 |
| 서로 다른 페이지에 걸친 그룹 | 6개 |
| 양성 응답 페이지 전체 SHA-256 반복 | 0건 |
| 중복에 연결된 전체 말 ID | 2,079개 |
| 보유 제주마 ID에 연결된 동일 그룹·추가 반복 | 3,299개·3,299행 |
| 중복에 연결된 보유 제주마 | 1,536두 |

같은 페이지 안의 4,199그룹 중 4,179그룹은 item 순번이 연속된다. 나머지는 2·3·4·5·32칸 떨어져 있다. 양성 응답 페이지 전체의 반복은 없고 원문 item 안에 반복이 존재한다. 원천 시스템이 왜 반복 item을 반환했는지, 실제 동일 이벤트의 중복인지에 관한 내부 원인은 이 자료만으로 확정하지 않았다.

### 연도별 추가 반복

| 연도 | 제주 경주장 전체 | 보유 제주마 ID 연결분 |
|---|---:|---:|
| 2007부터 2013 | 0 | 0 |
| 2014 | 8 | 2 |
| 2015 | 357 | 153 |
| 2016 | 287 | 138 |
| 2017 | 300 | 197 |
| 2018 | 238 | 166 |
| 2019 | 279 | 211 |
| 2020 | 381 | 277 |
| 2021 | 692 | 542 |
| 2022 | 571 | 521 |
| 2023 | 486 | 486 |
| 2024 | 250 | 250 |
| 2025 | 217 | 217 |
| 2026 | 139 | 139 |
| 합계 | **4,205** | **3,299** |

차이 906행은 보유 4,617두 명단 밖의 말에 해당한다. 이번 감사만으로 이들을 한라마나 비제주마로 판정하지 않았다.

### 대표 원문 사례

- **해파랑 ID 3014942, 2014-12-24:** [2014년 1페이지](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_api_detail_sources/raw/full_year_clinic_judgement_start_training/20260929T150517.740550Z/starting_training/2014/source_pages/page_0001.json>)의 item 109·110이 일치한다. `part=12`, `partNo=24`, `prName=이병석`, `remark='-'`이며 전체 8개 필드가 동일하다.
- **천문조 ID 3016391, 2016-12-14:** [1페이지](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_api_detail_sources/raw/full_year_clinic_judgement_start_training/20260929T150517.740550Z/starting_training/2016/source_pages/page_0001.json>)의 마지막 item 1,000과 [2페이지](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_api_detail_sources/raw/full_year_clinic_judgement_start_training/20260929T150517.740550Z/starting_training/2016/source_pages/page_0002.json>)의 첫 item 1이 일치한다. `part=12`, `partNo=9`, `prName=이병석`, `remark=양호`이며 전체 8개 필드가 동일하다.

모든 그룹의 양쪽 원문 위치는 [완전 동일 중복 원장](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_training_audit/starting_exact_duplicate_groups.jsonl>)에 보존했다. 마명은 해당 원문 표기다.

## 같은 말과 날짜지만 다른 내용

말 ID와 날짜만으로 보면 추가 반복은 7,297행이다. 완전 동일 추가 반복 4,205행을 빼도 내용이 다른 3,092개 조합이 남는다. 각 조합의 서로 다른 내용은 두 개씩이다.

| 서로 다른 필드 | 말과 날짜 조합 수 |
|---|---:|
| 기승자명 prName | 2,678 |
| 기승자명과 비고 prName 및 remark | 159 |
| 비고 remark | 230 |
| 조와 순번 part 및 partNo | 24 |
| 조 part | 1 |
| 합계 | **3,092** |

서로 다른 실제 훈련인지, 정정·재노출인지 원인은 미확정이다. 말 ID와 날짜만으로 한 행을 남기면 서로 다른 관측을 잃으므로 그런 중복 제거를 적용하지 않는다. [다른 내용 원장](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_training_audit/starting_same_horse_day_different_records.jsonl>)에 필드 차이와 최초 원문 위치를 보존했다.

## 일별조교의 공백과 ID 형식

- `run1Cnt`, `run2Cnt`: 각각 1,444,319행 모두 0. 실제 미조교나 횟수 0으로 입력하지 않는다.
- `trTerm`: 79,528행이 0이다. 처음 0이 아닌 값이 나타나는 날짜는 2008-11-10이고 마지막 0값은 2009-04-24다. 초기 0값을 휴식으로 바꾸지 않는다.
- 일별조교 원문이 없는 경주 연결 57두는 모두 마지막 보유 경주가 첫 관측일 2007-10-01 이전이다. [명단과 경주 기간](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_training_audit/missing_daily_race_horses.jsonl>).
- `hrNo='018570 '`인 3행은 ID 끝에 공백이 있고 마명 필드도 없다. 날짜는 2020-08-08·09·13이며 현재 보유 제주마 ID와 정확히 연결되지 않는다. 임의 변환 없이 [ID 형식 점검 원장](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_training_audit/invalid_raw_training_ids.jsonl>)에 보존했다. 908,316행의 제주마 연결 수에는 포함되지 않는다.

## 검증과 재현

[감사 코드](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_training_audit/audit_training_sources.py>)는 원문 파일 해시, API 정상 응답, 페이지 번호·행 수, 요청 기간과 행 날짜, 제주 경주장 값을 확인하고 모든 행을 순회했다. 648개 원문 페이지의 검증을 통과했다. DB는 읽기 전용으로 열었고 감사 전후 SHA-256은 모두 다음 값으로 같았다.

`34a491aaf8d9dd878315acd090c2af1719a2bbfda27a5309f631a3201acb7de0`

기존 원문은 모두 읽기만 했고 산출물은 이 폴더에 새로 저장했다. DB에는 조교 레코드가 적재되지 않은 상태다. 산출물 해시와 전체 항목·연도·월별 집계는 [audit_summary.json](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_training_audit/audit_summary.json>)에 있다.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 jeju/research/20261001_training_audit/audit_training_sources.py
```

코드는 산출물 존재 시 덮어쓰지 않고 중단한다. 재검증은 기존 원장과 코드 버전을 보존한 새 감사 경로에서 수행한다. 수집 재시도와 같은 API의 원문 회복 경위는 [월별 원장](<../20260929_api_monthly_history/README.md>), [연도별 원장](<../20260929_api_detail_sources/README.md>)을 따른다.

[GPT-6 Luna xhigh의 독립 재검산](<independent_review.md>)에서도 원문 행 수, 동일 그룹·다중도, 페이지 내부·경계 반복, 제주마 연결 중복과 내용이 다른 말·날짜 조합 수가 일치했다.
