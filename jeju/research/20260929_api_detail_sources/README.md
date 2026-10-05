# KRA 상세자료 API 확인 결과

기준일: 2026-09-30 · 대상: 제주 경주장(`meet=2`) · 수집 루트: KRA 공공데이터포털 API

2026-10-01 조교 후속 확인: 출발조교의 완전 동일 추가 반복 4,205행과 내용이 다른 말·날짜 조합을 [원문 감사 보고서](../20261001_training_audit/README.md)에 기록했다. 일별조교 월별 전기간 수집의 현재 결과는 [월별 수집 보고서](../20260929_api_monthly_history/README.md)를 따른다. 조교의 모델 입력에는 [조교 API 입력 기준](../../docs/JEJU_TRAINING_API_INPUT_CONTRACT_2026-10-01.md)을 적용한다.

## 완료 범위

| 자료 | 공식 endpoint / 확인한 기간 필터 | 이번 작업의 완료 범위 |
|---|---|---|
| 구간통과 상세 [API6_1](https://www.data.go.kr/data/15057847/openapi.do) | `/API6_1/raceDetailSectionRecord_1`; `meet`, `rc_year` 또는 `rc_date` | **2002–2026 전 연도 완료:** 25/25년, 19,651행, 25페이지. 모든 응답의 `totalCount`, 페이지 수, 행의 `rcDate` 연도가 일치. 날짜 표본은 2016-01-08 9행, 2026-09-19 7행. 구간별 거리·시간·통과순위가 있고 horse ID 필드는 없음. |
| 코너 통과 [API303](https://www.data.go.kr/data/15119851/openapi.do) | `/API303/corner_rank`; `meet`, `rc_year` 또는 `rc_date` | **2002–2026 전 연도 완료:** 25/25년, 19,933행, 25페이지. `totalCount`, 페이지 수, 모든 행의 `rcDate` 연도 일치. 같은 날짜 표본은 2016년 9행, 2026년 7행. 코너 순위·3F/4F 통과시간·tempo가 있고 horse ID 필드는 없음. |
| 진료 [API16_1](https://www.data.go.kr/data/15057799/openapi.do) | `/API16_1/raceHorseClinic_1`; `clinic_year`, `clinic_month`, `clinic_date` | **2002–2026 연간 요청 완료:** 25/25 partition, 12,030행/32페이지. `clinicDate` 연도가 요청 연도와 일치. 빈 응답 9개 연도는 요청 완료로만 기록하며 자료 존재의 증거로 세지 않음. 2026 응답 중 cutoff(2026-09-19) 뒤 날짜 39행을 별도 집계. |
| 심판 [API215](https://www.data.go.kr/data/15063980/openapi.do) | `/API215/JudgeReport`; `rc_year`, `rc_month`, `rc_date` | **2002–2026 연간 요청 완료:** 25/25 partition, 6,152행/25페이지. `rcDate` 연도가 요청 연도와 일치. 빈 응답 15개 연도는 양성 자료 coverage로 세지 않음. 기존에 확인한 심판·기수변경·재결 관련 텍스트 필드도 보존됨. |
| 일별조교 [API18_1](https://www.data.go.kr/data/15058782/openapi.do) | `/API18_1/dailyTraining_1`; `tr_month` (문서에는 `hr_name`, `hr_no`, `tr_date`도 있음) | 2026-09 5,370행/6페이지, 2016-09 5,357행/6페이지. `trDate` 월 일치. **`tr_year`는 유효한 연도 필터로 확인되지 않음:** 2016 입력이 2026 자료를 반환한 잘못된 호출이 있어 무효 표본으로 제외함. 전기간 backfill 아님. |
| 출발조교 [API22_1](https://www.data.go.kr/data/15059043/openapi.do) | `/API22_1/startingTranning_1`; `tr_year`, `tr_month`, `tr_date` | **2002–2026 연간 요청 완료:** 25/25 partition, 295,471행/311페이지. `trDate` 연도가 요청 연도와 일치. 빈 응답은 2002–2006년 5개 partition. 2016년 23,524행/24페이지의 모든 페이지를 검증했고, 2026 응답 중 cutoff 뒤 날짜 80행을 별도 집계. |
| 체중 [API25_1](https://www.data.go.kr/data/15057498/openapi.do) | `/API25_1/entryHorseWeightInfo_1`; `rc_month`, `rc_date` | 2026-09 514행, 2016-09 612행; 각각 한 페이지 전체이고 월 일치. 전기간 backfill 아님. 이 endpoint에서 `rc_year`는 기간 필터로 사용하지 않음. |
| 체중·장구/출혈 [API24_1](https://www.data.go.kr/data/15058040/openapi.do) | `/API24_1/horseMedicalAndEquipment_1`; `rc_date` | 요청일 표본만 완료: 2026-09-19 63행, 2016-01-08 92행; 모두 한 페이지이며 날짜 일치. `toolName`, `bleedingCnt`, `bleedingDate`, `illName` 필드 확인. API 문서의 날짜 필터로 2002–2026 수집 시 API4_3의 2,304개 고유 경주일 기준 **최소 2,304회 날짜 partition 요청**이 예상됨(페이지 추가분 제외). 전체 backfill은 하지 않음. |

샘플 실행은 18요청, HTTP 성공 18건, 요청 기간과 행 날짜 일치 18건이었다. 그중 첫 페이지 자체로 partition 전체가 끝난 것은 13개다. 위 표의 5개 긴 대표 partition은 페이지를 끝까지 이어받아 완결했다. 표본·대표 partition 응답은 **59개 고유 페이지**로 보존했으며 각 페이지에 바이트 크기와 SHA-256 manifest가 있다. 별도로 API6_1/API303 연간 응답 50페이지를 보존했다. HTTP 200만으로 coverage로 세지 않았으며, 0행 응답은 양성 coverage로 인정하지 않는 검증 규칙을 수집 코드에 적용했다.

## 2026-09-30 연간 수집 결과

API16_1, API215, API22_1을 각각 `clinic_year`, `rc_year`, `tr_year`로 2002–2026 연간 partition 수집했다. 최종 run은 **75/75 연간 partition 완료**, 368개 페이지 응답 보존이며, 응답 JSON의 페이지 번호·행 수·`totalCount` 및 행 날짜 연도를 독립 검증했다. 원문 파일 SHA-256·byte size도 manifest와 대조해 오류 0건이다.

| API | 연도 partition | 행 / 페이지 | 0행 partition | cutoff 뒤 응답행 |
|---|---:|---:|---|---:|
| API16_1 진료 | 25/25 | 12,030 / 32 | 2002–2007, 2009–2011 (9년) | 39 |
| API215 심판 | 25/25 | 6,152 / 25 | 2002–2016 (15년) | 0 |
| API22_1 출발조교 | 25/25 | 295,471 / 311 | 2002–2006 (5년) | 80 |

0행 partition은 HTTP/API 정상 응답(`resultCode=00`, `totalCount=0`)과 원문 페이지가 확인된 **질의 완료**다. 해당 연도에 자료가 존재한다는 양성 증거가 아니며, 최초 제공연도나 과거 기록의 부재 원인을 확정하지 않는다. 2026-09-19 이후 119행(진료 39, 출발조교 80)은 원문 보존 후 cutoff 기준 분석에서 별도 제외할 수 있도록 표시했다.

연도별 응답은 `raw/full_year_clinic_judgement_start_training/20260929T150517.740550Z/`에 있다. `run_manifest.json`은 요약과 각 연도·페이지 메타데이터, `attempt_ledger.jsonl`은 실패·재시도·페이지 보존 이력을 기록한다. 각 페이지 원문은 데이터셋/연도별 `source_pages/` 아래에 있고 SHA-256과 byte size가 manifest에 포함된다. 2016 출발조교는 24페이지를 모두 받아 23,524행과 대조했다. 전체 run의 기대 페이지는 API별 `ceil(totalCount/1000)` 합계로 산정하며, **API22_1 311페이지**와 **전체 368페이지(진료 32 + 심판 25 + 출발조교 311)**를 구분한다.

수집 도중 API16_1 2002 첫 요청에서 두 차례 transport 실패가 남아 있으나, 재개 후 해당 연도의 성공 응답(0행)을 포함해 25개 연도가 모두 완료됐다. API22_1은 2019년 16페이지, 2023년 8·9페이지에서 transient timeout 재시도 후 원문 저장에 성공했다. 모두 ledger에 남겼고 미완료 partition은 없다. 저장된 페이지 응답은 368개이며, 별도 retry/failure 기록도 보존되어 있으므로 응답 페이지 수와 실제 HTTP 시도 수를 같은 수치로 취급하지 않는다.

## 경주 결과 키와의 대조

API4_3의 기존 2002–2026 기준 집합 20,117개 고유 경주키와 API6_1/API303을 독립 대조한 결과:

| API | API 행/고유키 | API4_3 대비 누락 | 추가·중복 키 |
|---|---:|---:|---:|
| API6_1 | 19,651 | 466 | 0 |
| API303 | 19,933 | 184 | 0 |

누락은 원인 미확정이며 API 지연·경주 취소 등으로 단정하지 않는다. API6_1 공백은 여러 연도에 분포하고 2026년에 40개다. API303 공백은 2002년 37, 2003년 49, 2004년 45, 2005년 8, 2006년 26, 2026년 19개다. `rank='제'`인 경주 9,445개만 별도로 보면 API6_1 누락 145개, API303 누락 25개다. `meet=2`는 제주 경주장 필터이며 품종 증거가 아니다. 공백 경주키의 날짜·원인을 추가 감사한 뒤 TXT/RPT는 API에서 비는 필드 보완 및 검증에만 사용할 후보로 남긴다.

## 전기간 수집량 산정과 역사 coverage의 한계

API6_1, API303, API16_1, API215, API22_1은 2002–2026 연간 요청을 완료했다. API18_1과 API25_1의 후속 월별 요청도 완료됐으며 최신 범위는 별도 원장을 따른다. partition 수는 전체 페이지·행 수를 뜻하지 않는다. API24_1의 날짜별 수집 현황은 [전용 원장](../20260929_api_equipment_recent/README.md)을 따른다.

| 자료 | 2002–2026 계획 partition | 근거와 상태 |
|---|---:|---|
| API16_1 진료 | 연 25개 | 전기간 요청 완료: 32페이지, 12,030행. 9개 연도는 정상 0행 응답이며 양성 자료 coverage는 아님. |
| API18_1 일별조교 | 월 297개 (2002-01–2026-09) | 후속 월별 요청 완료: 337페이지·1,444,319행, 정상 0행 69개월. 2015-06은 같은 API 날짜별 요청, 2026-09는 기존 공식 원문 검증·연결로 회복했다. 실제 관측은 2007-10-01–2026-09-28이며 공식 최초 제공일을 확정한 것은 아님. [월별 원장](../20260929_api_monthly_history/README.md), [입력 기준](../../docs/JEJU_TRAINING_API_INPUT_CONTRACT_2026-10-01.md). |
| API22_1 출발조교 | 연 25개 | 전기간 요청 완료: 311페이지, 295,471행. 5개 연도는 정상 0행 응답이며 양성 자료 coverage는 아님. 2016년의 24페이지 포함. |
| API215 심판 | 연 25개 | 전기간 요청 완료: 25페이지, 6,152행. 15개 연도는 정상 0행 응답이며 양성 자료 coverage는 아님. |
| API25_1 체중 | 월 297개 | 후속 월별 요청 완료: 298페이지·190,305행, 정상 0행 6개월. 2026-09는 기존 공식 원문 검증·연결로 회복했다. 기존 별도 연구의 유효 체중 행 수와 이번 전체 원문 행 수를 구분한다. [월별 원장](../20260929_api_monthly_history/README.md). |
| API24_1 장구/출혈 | 최소 날짜 partition 2,304개 | API4_3의 2002–2025 고유 경주일 2,225개와 2026-09-19까지 79개를 합산한 호출량 추정. API24_1은 날짜 표본 두 건뿐이고 2016 표본은 양성이나 2002–2015 전체 가용성은 미검증. |

API16_1 연간 응답에서는 2008년부터 양성 행이 있었고, 이전 조사에는 2012-10-21 진단 텍스트 단서가 기록되어 있다. 정상 0행 연도는 이 endpoint의 요청 결과만 나타내며, 원천 시스템의 역사적 미제공이나 모든 자료의 부재를 뜻한다고 단정하지 않는다. API24_1 포털 등록일(2019-06-21)은 API의 실제 최초 관측일로 간주하지 않는다. API4_3도 본 작업에서 날짜 표본만 호출했으며, 기준 집합은 기존 연구 archive를 사용했다.

## 산출물

- 연간 전기간 수집기: [`collect_sections_and_passing_years.py`](collect_sections_and_passing_years.py)
- 추가 연간 수집기 및 재개 옵션: [`collect_annual_clinic_judgement_start_training.py`](collect_annual_clinic_judgement_start_training.py)
- 표본 수집기: [`collect_api_samples.py`](collect_api_samples.py)
- 대표 partition pagination 수집기: [`complete_representative_partitions.py`](complete_representative_partitions.py)
- 연도 필터 probe: [`probe_annual_filters.py`](probe_annual_filters.py)
- API16_1/API215/API22_1 전기간 수집기: [`collect_annual_clinic_judgement_start_training.py`](collect_annual_clinic_judgement_start_training.py)
- API6_1/API303 전기간 원문·manifest: [`raw/full_year_sections_passing/20260929T143902.196014Z/`](raw/full_year_sections_passing/20260929T143902.196014Z/)
- 18요청 표본 manifest: [`raw/samples/20260929T142137.341471Z/sample_manifest.json`](raw/samples/20260929T142137.341471Z/sample_manifest.json)
- 5개 대표 pagination 완료 manifest: [`raw/samples/20260929T142137.341471Z/representative_partition_completion.json`](raw/samples/20260929T142137.341471Z/representative_partition_completion.json)
- API16_1/API215/API22_1 2002–2026 원문·SHA·재개 ledger: [`raw/full_year_clinic_judgement_start_training/20260929T150517.740550Z/`](raw/full_year_clinic_judgement_start_training/20260929T150517.740550Z/)
- 기존 역사 availability 조사: [`JEJU_NATIVE_SOURCE_COLLECTION_AVAILABILITY_2026-09-14.md`](../../../docs/JEJU_NATIVE_SOURCE_COLLECTION_AVAILABILITY_2026-09-14.md)

요청은 공식 OpenAPI의 JSON 응답을 사용했다. 서비스 키는 실행환경 설정에서 메모리로만 읽었고 manifest에 저장하지 않았다. `.env` 내용은 출력하지 않았다. API6_1/API303/API16_1/API215/API22_1의 연도 요청과 API18_1/API25_1의 월별 요청은 완료됐다. **전체 상세자료의 적재·필드·공백 검증은 완료 상태가 아니다.** API24_1 날짜별 수집의 현재 상태는 전용 원장을 따른다. 정상 0행 기간은 자료가 있는 coverage로 해석할 수 없으며, API6_1/API303의 누락 경주키는 원인 감사 및 필요한 TXT/RPT 보완을 남긴다. 조교 원문의 수집 완료와 모델 입력 검증 완료를 구분한다.
