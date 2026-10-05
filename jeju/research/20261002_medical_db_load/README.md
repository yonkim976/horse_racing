# 제주마 진료 API 적재·독립 검증 보고서 — 2026-10-02

## 완료 결과

실제 적재 DB는 `jeju/data/jeju_native_core.sqlite3`이다. 이번 수집·적재는 API16 진료 원문과 API42 현재 마필정보를 사용했다.

| 항목 | 결과 |
|---|---:|
| 진료 원문 연결 `medical_api_rows` | 12,030행·944두 |
| 원문 진료일 범위 | 2008-04-02~2026-09-27 |
| 분석 조회 `medical_api_rows_analysis_2026` | 2026-09-19까지 11,991행·939두 |
| 기준일 이후 보존 원문 | 39행 |
| 추가 조회·검증한 현재 제주마 프로필 | 81두 |
| 전체 최신 프로필 | 4,718두 |
| 두 원문 진료 슬롯 | 24,060개 |
| 비어 있지 않은 원문 문구 / 등장 슬롯 | 168종 / 11,344개 |
| 원문 `-` 슬롯 | 12,716개 |
| 완전히 동일한 원문 반복 | 18그룹·38행, 유지 |

81두는 기존 프로필에 연결되지 않던 진료 156행의 공식 말 ID를 기준으로 조회했다. 모두 HTTP 200, API 정상 코드, 1건 응답, 요청·응답 ID 일치, 현재 품종 제주마를 확인했다. 진료 원문은 32개 응답 페이지의 모든 item 위치·필드·JSON 타입·해시를 DB와 독립 대조했다. 현재 프로필은 과거 진료일의 품종 증명이 아니다.

## 수집원천과 연결 이름

- **마필진료 정보**: API16_1 `raceHorseClinic_1`, 공공데이터포털 자료번호 `15057799`. 기존 API 원문 수집 실행 `20260929T150517.740550Z`, 2002~2026년 25개 연도 조회 결과를 사용했다. 진료일·말 ID·당시 마명·병원명·`illName1`·`illName2`·`meet`·`part` 및 전체 원문을 보존한다. `part` 의미는 미확정이다.
- **마필종합 상세정보**: API42_1 `totalHorseInfo_1`, 자료번호 `15057985`. 신규 81두의 응답은 `profile_collection/`에 보존했다. 수집 실패 기록도 남기고 성공 응답의 실제 실행 ID·수집시각·원문 경로를 사용했다.
- **질병 연구 사전**: `thoroughbred/research/20261002_medical_v1/dictionary/`의 고정된 6개 Parquet와 원문 해시를 그대로 재사용했다. API33 원문 3,523행, 용어 3,511행, 문구 검토 5,397행, 검토 구성요소 9,113행, 설명 출처 145행, 설명 용어 119행이다.

더러브렛 사전 README의 서울·부경 사건 범위는 그쪽 진료 적재기의 기준이다. 이번 제주 진료는 사용자 승인에 따른 별도 사건 범위이며, 건수는 제주 API16 원문에서 독립 계산했다. 더러브렛 진료 사건·기존 사용 빈도는 복사하지 않았다. 공유 사전은 정확한 원문 문구와 해시가 일치하는 검토 메타데이터 조회에만 사용하며, 말의 진단을 자동 확정하지 않는다. 사전 원본 파일은 변경하지 않았다.

## 모델 입력 기준

분석의 기본 행 단위는 **원래 API item 1개**다. 말 이름으로 연결하지 않고 공식 말 ID로 연결한다. 최신 이름·2026년 고정 나이는 기존 `horse_analysis_2026` 정책을 적용하며, 진료 당시 마명은 원문에 남긴다.

- 원문 반복과 동일 말·동일 날짜 복수행을 유지했다. 원행 수를 실제 진료 방문 횟수로 단정하지 않는다. 재적재 중복은 원문 파일과 1부터 시작하는 item 위치로 막는다.
- `medical_api_diagnosis_slots`에는 두 슬롯을 그대로 저장했다. `-`는 원문 보존 + 정규값 NULL이며 건강함·미진료를 뜻하지 않는다. 키 미제공·명시적 null·빈 문자열·원문 문자열은 구분해 보존한다.
- 문구 검토·구성요소·설명은 각각 `medical_api_diagnosis_slot_review`, `medical_api_diagnosis_components`, `medical_api_diagnosis_explanation_terms` 등으로 분리했다. 설명의 1:N 조인으로 진료 원행이나 출전행을 늘리지 않는다.
- 이번 API 문구 168종은 모두 정확한 문구 검토 조건에 연결된다. 연결된 표제어 168종 중 40종은 확보한 공식 설명이 있고 128종은 제목만 있다. API33 `illDesc`는 전부 `-`이므로 설명으로 사용하지 않는다. 접두어 파서 의존 356개·사건 조건부 8개 규칙은 일반 연결에서 적용하지 않는다.
- 재료판매·검사·장제·예방·처치 문구를 질병으로 자동 분류하지 않는다. 중증도·회복·성적 영향 등을 설명 제목으로 추정하지 않는다.
- `clinicDate`는 진료 사건 날짜이며 과거 공개시각은 미확정이다. 경주 전 분석에 연결할 때 최소 `clinic_date < race_date`와 공개시각 미확정을 반영해야 한다. 이번 적재를 기존 예측 모델 입력에 자동 채택하지 않았다.
- 제외된 작은곰 `3005648`은 재편입하지 않았다.

상세 규칙은 [MODEL_INPUT_CONTRACT.md](MODEL_INPUT_CONTRACT.md)에 있다.

## 과거 공백 재확인

2002~2007년·2009~2011년의 9개 연도를 API로 재조회했다. 모두 HTTP 200·정상 코드·`totalCount=0`이었다. 이는 해당 요청의 응답이 0행이라는 뜻이며 과거 진료가 없었다는 증거는 아니다.

기존 제주 `dacom72` TXT 1,150파일·53,185행도 확인했다. 2005~2007년·2009~2011년 진료일 자료는 있지만 공식 7자리 말 ID가 없어 이름만으로 제주마 진료에 연결할 수 없다. 이번 TXT 진료 적재는 0행이며 보완 후보로 보존했다. 2002~2004년 TXT도 확보되지 않았다. 상세 결과는 [history_gap_review/README.md](history_gap_review/README.md)에 있다.

## 검증·복구 근거

- 시험 사본에 적재한 뒤 재실행하여 신규 삽입 0건을 확인했다.
- root가 API16 32페이지·12,030개 원문 위치와 필드, API42 81개 응답, 사전 6개 파일의 모든 행을 독립 대조했다.
- 실제 적재 후 기존 16개 테이블의 모든 기존 행 값과 기존 SQL 스키마가 유지되는지 대조했다. 외래키 오류 0건, SQLite 검사 정상이다.
- 적재 전 SQLite 백업과 그 시점의 build manifest를 `root/before_load.sqlite3`, `root/before_load.build_manifest.json`에 함께 보존했다. 백업 SHA와 적재 전 실제 파일 SHA는 SQLite 백업 방식에 따라 다르며 각각 별도 기록했다.

최종 집계·해시는 [summary.json](summary.json), 실제 적재 기록은 [production/apply_report.json](production/apply_report.json), 독립 검증은 `root/root_production_*_verification.json`, 시험 재실행은 [staging_replay_report.json](staging_replay_report.json)에 있다.

## 재적재 실행

기존 DB 사본 또는 제주 native DB에 명시적 경로·현재 SHA를 전달한다. 기본은 읽기 전용 계획 점검이며 `--apply`에서 트랜잭션 적재한다.

```sh
.venv/bin/python jeju/research/20261002_medical_db_load/load_medical_api16.py \
  --project-root /Users/kimyongjin/Desktop/horse_racing \
  --db /absolute/path/to/database.sqlite3 \
  --output-dir /absolute/path/to/new-report-directory \
  --profile-collection-dir /Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_medical_db_load/profile_collection \
  --expected-db-sha256 <current-database-sha256>
```

최초 적재용 입력 파일과 메타데이터의 해시가 다르면 중단한다. 기존 시험 보고서를 덮어쓰지 않도록 새로운 출력 폴더를 사용한다.
