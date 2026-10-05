# 제주마 월별 API18_1·API25_1 원문 이력

기준일은 2026-09-30이다. `meet=2`로 2002-01부터 2026-09까지 297개 월 partition씩, 총 594개를 조사했다. 원문 상세 데이터는 core DB에 적재하지 않았다.

2026-10-01 후속 전수 확인: 일별조교의 실제 기록 범위·시간 0값·횟수 항목 전 기간 0값·말 ID 형식과 연결은 [조교 원문 감사](<../20261001_training_audit/README.md>)에 기록했다. 모델 입력·집계·중복·시점 처리 기준은 [조교 API 입력 기준](<../../docs/JEJU_TRAINING_API_INPUT_CONTRACT_2026-10-01.md>)을 따른다.

## API와 페이지 설정

| 자료 | 공식 endpoint | 기간 필터 | 날짜 필드 | 기본 페이지 크기 |
|---|---|---|---|---:|
| 일별조교 API18_1 | `/API18_1/dailyTraining_1` | `tr_month=YYYYMM` | `trDate` | 20,000 (2016-09 probe 검증 뒤) |
| 출전마 체중 API25_1 | `/API25_1/entryHorseWeightInfo_1` | `rc_month=YYYYMM` | `rcDate` | 1,000 |

API18_1에는 `tr_year`를 보내지 않았다. 기존 조사에서 이 필터가 연도를 제대로 제한하지 않는 것을 확인했다. API18_1 2002-01–2007-10은 probe 이전의 `numOfRows=1,000` 응답이며, 2007-11–2026-08은 20,000행 설정이다. API25_1 월 요청은 1,000행이다. API18_1의 2026-09는 이전에 수집·검증된 공식 1,000행 페이지를 참조한다. 2016-09의 API18_1 20,000행 probe는 5,357행·1페이지를 반환했고, SHA-256은 `ec911d2658d3b0f4c5f336b90ac08ae50a236f6ecb269b7d14d158fb3cc86bf5`다.

## 최종 coverage

| 자료 | 월 partition | 양성 coverage | 빈 응답 | 공식 원문 페이지 | 양성 행 수 |
|---|---:|---:|---:|---:|---:|
| API18_1 일별조교 | 297 | 228 (월 필터 227, `tr_date` fallback 1) | 69 | 337 | 1,444,319 |
| API25_1 출전마 체중 | 297 | 291 | 6 | 298 | 190,305 |

API18_1의 69개 빈 응답은 2002-01–2007-09다. 빈 응답은 원문 JSON과 함께 기록했으며 양성 coverage 행으로 세지 않았다. `monthly_coverage.csv`와 `coverage_summary.json`은 dataset별 연도·월 상태를 나눠 담는다.

### 해결 기록이 필요한 월

- **API18_1 2015-06:** 공식 월 필터 `tr_month=201506`은 `numOfRows=20,000`에서 4회, 1,000행 fallback에서 4회 모두 `ReadTimeout`이었다. 이 8개 실패 시도는 ledger에 보존되어 있고 월 요청 `api_total_count`는 미확정으로 남겼다. `tr_date=20150615`는 정확히 233행을, `tr_date=20150630`은 정확한 빈 응답을 반환해 날짜 필터를 검증했다. 이후 30일을 각각 페이지 끝까지 수집해 25일 양성·5일 빈 응답, 30페이지, 날짜별 `totalCount` 합과 실제 행 합계 5,970을 확인했다. 모든 행이 요청한 날짜에 속하고 중복 행과 `(trDate, hrNo)` 중복 초과가 각각 0이다. 이 월의 상태는 월 API 직접 완료가 아니라 `complete_positive_coverage_via_daily_tr_date`로 표시한다.
- **API18_1 2026-09:** 이번 월 요청에서 4회 `ReadTimeout`이 발생했다. 기존 공식 API archive의 6페이지 원문을 SHA·페이지 행 수·totalCount로 검증한 뒤 원문을 복사하지 않고 상대경로 provenance로 연결했다. 5,370행 모두 `trDate`가 202609이며 범위는 20260902–20260928이다. 2026-09-20 이후 1,039행은 별도 cutoff 파일에 분리했다.
- **API25_1 2026-09:** 이번 월 요청에서 4회 `ReadTimeout`이 발생했다. 기존 공식 archive의 검증된 1페이지(514행, totalCount 514)를 상대경로 provenance로 연결했다. 날짜 범위는 20260904–20260919이고 cutoff 초과 행은 0이다.

따라서 첫 월간 pass manifest의 `complete_with_partition_failures`는 이후 해결 결과를 반영하도록 `completed_with_partition_failures_then_resolved`로 조정했다. 최종 범위 상태는 `api_first_month_range_complete_with_provenance_recovery`다. 월 요청 실패 이력은 삭제하지 않았다.

## Cutoff와 요청량

`2026-09-19`는 cutoff에 포함한다. API18_1의 2026-09 원문 페이지에는 9월 20일 이후 행도 포함되어 있으나, 1,039행을 [`cutoff_exceeding/`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_api_monthly_history/cutoff_exceeding>)에 별도 JSON 및 SHA로 기록했다. API25_1은 cutoff 초과 행이 없다. 원본 페이지는 감사용으로 보존한다.

이 collector가 ledger에서 집계한 요청 시도는 KST 2026-09-30 기준 654회다. 공유 개발계정의 3,000회/일 한도 중 다른 agent 요청량은 알 수 없으며 quota 응답은 관찰되지 않았다. transient/ReadTimeout은 페이지별 최대 3회 지수 backoff 후 중단하고, quota 신호는 즉시 중단한다. 오류 유형, 페이지, 시도 번호, in-flight 중단/재개 정보는 ledger와 실행 manifest에 남긴다.

## 재현과 산출물

```sh
PYTHONPATH=src .venv/bin/python jeju/research/20260929_api_monthly_history/collect_monthly_history.py
```

- `collect_monthly_history.py`: 월별 수집, 페이지 검증, raw SHA, 월·연 coverage 집계
- `probe_daily_training_page_size.py`: API18_1 20,000행 page-size probe
- `probe_daily_training_date_param.py`: 2015-06 `tr_date` 유효성 probe
- `collect_daily_training_tr_date_month_fallback.py`: 2015-06의 30개 정확 날짜 partition fallback
- `ledger.json`: 월별 상태, 페이지·SHA·오류, quota 요청량, prior archive provenance, 날짜 fallback 및 재개 이력
- `runs/*.json`: 실행별 상태와 페이지·시도 정보
- `raw/<dataset>/<YYYYMM>/<run-id>/`: 월 필터의 공식 응답 페이지
- `raw/tr_date_fallback/201506/`: fallback에서 새로 받은 날짜별 응답 페이지
- `raw/date_probes/`: 2015-06 필터 probe 원문
- `monthly_coverage.csv`, `coverage_summary.json`: 월·연·dataset별 결과
- `cutoff_exceeding/daily_training/202609/`: cutoff 뒤 API18_1 행과 별도 SHA

API18_1·API25_1의 2026-09 prior archive raw는 `../20260929_api_detail_sources/raw/samples/20260929T142137.341471Z/`에 있다. 이 run은 원문 페이지를 복사하지 않고 `ledger.json`의 `prior_official_api_archive` provenance에 SHA·경로를 연결한다. 서비스키는 설정에서 메모리로만 읽고 파일, manifest, URL 기록, stdout에 저장하지 않는다. `.env` 내용을 출력하지 않았다.
