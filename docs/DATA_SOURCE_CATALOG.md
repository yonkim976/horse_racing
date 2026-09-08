# KRA 데이터 소스 카탈로그와 수집 인수인계서

최종 확인: 2026-08-28 (Asia/Seoul)

이 문서는 다른 에이전트가 별도의 대화 맥락 없이 한국마사회(KRA) 원천을 확인하고 데이터를
다운로드할 수 있도록 만든 인수인계 문서다. 프로젝트의 소스 전략은 다음과 같다.

```text
과거 대량 적재       KRA 경마정보 Text 자료실
현재·신규 증분 적재  공공데이터포털 OpenAPI
원본 보존             data/raw 아래에 응답/파일 + 요청 메타데이터 + SHA-256
분석용 정규화         SQLite → 추후 Parquet/DuckDB/Polars
```

## 1. 상태 표기와 중요한 원칙

| 표기 | 의미 |
|---|---|
| `LIVE` | 현재 저장소 코드로 실제 정상 응답과 적재를 확인함 |
| `VERIFIED` | 2026-08-23 공식 상세 페이지에서 서비스 존재·설명을 확인함 |
| `INDEXED` | KRA 전체 공식 서비스 목록에서 존재를 확인했으나 개별 호출 명세 재확인이 필요함 |

- `VERIFIED`는 수집기 구현 완료를 뜻하지 않는다. 활용신청 후 Swagger/참고문서의 요청주소,
  operation, 파라미터 대소문자와 응답을 다시 확인해야 한다.
- 서비스는 대부분 각각 별도의 활용신청이 필요하다. 공통 서비스키가 있어도 미신청 API는
  `SERVICE_ACCESS_DENIED_ERROR`가 발생할 수 있다.
- 공공데이터포털 개발계정의 일반적인 표시 한도는 API별 일 3,000건이다. 일부 API는 다르므로
  각 상세 페이지의 현재 값을 우선한다.
- 기준 Base URL은 `https://apis.data.go.kr/B551015`다. 인증키 환경변수는
  `HORSE_RACING_DATA_GO_KR_SERVICE_KEY`이며 `.env`와 원본 요청 로그에 키를 노출하지 않는다.
- 경마장 코드는 `1=서울`, `2=제주`, `3=부산경남`, 향후 지원되는 API에서는 `4=영천`이다.
- 마번·기수번호·조교사번호·마주번호는 앞자리 0이 있는 문자열 ID로 보존한다.
- 공식 전체 서비스 교차확인용 기준은 [2026년 KRA OpenAPI 서비스 목록](https://www.data.go.kr/bbs/ntc/selectNotice.do?originId=NOTICE_0000000004487)이다.

## 2. 현재 코드에 통합되어 실제 사용한 API

아래 API는 `src/horse_racing/collectors/kra_api.py`에 구현되어 있고, 일정·결과·구간·말 이력
수집에 사용한다. Base URL 뒤에 Endpoint를 붙인다.

| 상태 | 공식 데이터 | 데이터 ID | Endpoint / operation | 주요 조건 | 핵심 용도 |
|---|---|---:|---|---|---|
| `LIVE` | [AI학습용 경주계획](https://www.data.go.kr/data/15143802/openapi.do) | 15143802 | `/API154/racePlan` / `racePlan` | `rccrs_cd`, `race_dt` | 일정, 조건, 예정·실제 출발시각, 날씨·주로 |
| `LIVE` | [출전표 상세정보](https://www.data.go.kr/data/15058677/openapi.do) | 15058677 | `/API26_2/entrySheet_2` / `entrySheet_2` | `meet`, `rc_date` | 출전마와 말·기수·조교사·마주 ID, 체중, 레이팅 |
| `LIVE` | [출전표정보](https://www.data.go.kr/data/15160316/openapi.do) | 15160316 | `/API78/chulmainfo` / `chulmainfo` | `rccrs_cd`, `race_dt` | 공식 출발번호 `gtno` 수집·기존 출주번호 검증 |
| `LIVE` | [AI학습용 경주결과](https://www.data.go.kr/data/15143803/openapi.do) | 15143803 | `/API155/raceResult` / `raceResult` | `rccrs_cd`, `race_dt` | 결과 존재 확인과 기본 결과 |
| `LIVE` | [AI기반연구용 경주결과상세](https://www.data.go.kr/data/15150068/openapi.do) | 15150068 | `/API156/raceRsutDtl` / `raceRsutDtl` | `rccrs_cd`, `race_dt` | 순위·기록·상금·장구 등 상세 결과 |
| `LIVE` | [확정배당율 통합 정보](https://www.data.go.kr/data/15058559/openapi.do) | 15058559 | `/API301/Dividend_rate_total` / `Dividend_rate_total` | `meet`, `rc_date` | 승식별 선택 조합과 최종 배당 |
| `LIVE` | [경주기록 정보](https://www.data.go.kr/data/15058305/openapi.do) | 15058305 | `/API4_3/raceResult_3` / `raceResult_3` | `meet`, `rc_date` | 말별 구간기록 |
| `LIVE` | [경주마 레이팅 정보](https://www.data.go.kr/data/15057323/openapi.do) | 15057323 | `/API77/raceHorseRating` / `raceHorseRating` | (전체) | 레이팅 스냅샷 |
| `LIVE` | [출전마 체중 정보](https://www.data.go.kr/data/15057498/openapi.do) | 15057498 | `/API25_1/entryHorseWeightInfo_1` / `entryHorseWeightInfo_1` | `meet`, `rc_date` | 체중 이력 |
| `LIVE` | [일별훈련 상세정보](https://www.data.go.kr/data/15058782/openapi.do) | 15058782 | `/API18_1/dailyTraining_1` / `dailyTraining_1` | `meet`, `tr_date` | 일별 훈련 |
| `LIVE` | [마필진료 정보](https://www.data.go.kr/data/15057799/openapi.do) | 15057799 | `/API16_1/raceHorseClinic_1` / `raceHorseClinic_1` | `meet`, `clinic_date` | 진료 이력 |
| `LIVE` | [경주마 상세정보](https://www.data.go.kr/data/15058115/openapi.do) | 15058115 | `/API8_2/raceHorseInfo_2` / `raceHorseInfo_2` | `meet`, `act_gubun` | 말 프로필·혈통·통산 성적 스냅샷 |
| `LIVE` | [기수변경 정보](https://www.data.go.kr/data/15057181/openapi.do) | 15057181 | `/API10_1/jockeyChangeInfo_1` / `jockeyChangeInfo_1` | `meet`, `rc_date` | 경주별 기수변경 |
| `LIVE` | [경주마 출전취소 정보](https://www.data.go.kr/data/15056779/openapi.do) | 15056779 | `/API9_1/raceHorseCancelInfo_1` / `raceHorseCancelInfo_1` | `meet`, `rc_date` | 출전취소 |
| `LIVE` | [출전마 장구사용 및 폐출혈 정보](https://www.data.go.kr/data/15058040/openapi.do) | 15058040 | `/API24_1/horseMedicalAndEquipment_1` / `horseMedicalAndEquipment_1` | `meet`, `rc_date` | 장구·폐출혈·이상 |
| `LIVE` | [경주마 등급변동 정보](https://www.data.go.kr/data/15058076/openapi.do) | 15058076 | `/raceHorseRatingChangeInfo_2/raceHorseRatingChangeInfo_2` | `meet`(선택) | 등급 적용·종료 이력 |
| `LIVE` | [출발훈련 정보](https://www.data.go.kr/data/15059043/openapi.do) | 15059043 | `/API22_1/startingTranning_1` / `startingTranning_1` | `meet`, `tr_date` | 출발대 훈련 |
| `LIVE` | [심판리포트정보](https://www.data.go.kr/data/15063980/openapi.do) | 15063980 | `/API215/JudgeReport` / `JudgeReport` | `meet`, `rc_date` | 심판 판정·제재 |

공통 pagination은 `pageNo`, `numOfRows`다. JSON이 지원되는 API에는 `_type=json`을 붙인다.
현재 구현상 API26 출전표의 키 이름은 `ServiceKey`, API78을 포함한 나머지는
`serviceKey`로 호출한다.

API78은 2026-08-28 승인 후 실호출을 확인했다. 2025-01-04 서울, 2026-08-28 제주,
2026-08-29 서울에서 기존 출전표와 대조한 300행 모두 `gtno = horse_number`였고 마명도
일치했다. 수집기는 번호나 마명이 다르면 저장하지 않고 실패 처리한다. 공식 안내상 출전표
갱신 시각은 서울 목요일 17:00, 제주 목요일 15:00, 부산경남 수요일 15:00이 기준이다.

```bash
cp .env.example .env
# .env 안에 HORSE_RACING_DATA_GO_KR_SERVICE_KEY=Decoding_인증키 설정

uv run horse-racing collect-race-day --date 20260822 --meet 1
uv run horse-racing backfill-results \
  --start 20250101 --end 20251231 --meets 1 2 3 --skip-dividends
uv run horse-racing backfill-dividends \
  --start 20250101 --end 20251231 --meets 1 2 3 --page-size 10000

uv run horse-racing collect-gate-numbers --date 20260829 --meet 1
uv run horse-racing backfill-gates \
  --start 20250101 --end 20260831 --meets 1 2 3
```

## 3. 경주·결과·전개 원천

| 우선 | 상태 | 공식 데이터 / ID | 공식 확인 내용과 검색 조건 | 프로젝트 활용 |
|---|---|---|---|---|
| S | `LIVE` | [경주기록 정보](https://www.data.go.kr/data/15058305/openapi.do) / 15058305 | `/API4_3/raceResult_3`; `meet`, `rc_date`; `collect-race-sections`, `backfill-sections`, `sync-daily`가 말별 S1F·코너·G3F·G1F를 `race_section_results`에 적재 | 일반 결과 원천과 AI API 스키마 대조, 구간기록 수집 |
| S | `VERIFIED` | [경주별상세성적표](https://www.data.go.kr/data/15089492/openapi.do) / 15089492 | `/racedetailresult/getracedetailresult`; `meet`, `rc_date`, `rc_no`; XML. 순위, 출주번호, ID, 착차, 체중증감, 단·연승배당, 기록, 장구, 출주 여부 | API156 대조 및 누락 보완 |
| S | `VERIFIED` | [경주 구간별 성적 정보](https://www.data.go.kr/data/15057847/openapi.do) / 15057847 | `/API6_1/raceDetailSectionRecord_1`; 경주 단위 1F~12F·S1F/G3F/G1F group notation | 경주 전개 보강(미구현), API4_3와 coverage 비교 |
| S | `VERIFIED` | [마필 구간별 경주기록](https://www.data.go.kr/tcs/dss/selectApiDataDetailView.do?publicDataPk=15057859) / 15057859 | `hr_name`, `hr_no`, `meet`, `rc_date`, `rc_year`, `rc_month`; 말·거리별 과거 최고/최저/평균 S1F·코너·G3F·G1F | 예측일 기준 과거 요약값, API37 참고문서 확인 |
| S | `VERIFIED` | [경마코너별통과순위·주로빠르기](https://www.data.go.kr/data/15119851/openapi.do) / 15119851 | 경주 코너 통과순위와 주로 빠르기 | 경주 전개 보강, 구간 API와 coverage 비교 |
| S | `VERIFIED` | [경주 요약성적표](https://www.data.go.kr/data/15057579/openapi.do) / 15057579 | `/API34_1/raceSummaryResult_1`; 경주별 적중 조합과 승식별 확정배당 | 결과·배당 QA |
| A | `VERIFIED` | [출전 등록말 정보](https://www.data.go.kr/data/15056699/openapi.do) / 15056699 | 계획 경주와 등록마, 말·조교사·마주 ID, 상금 | 출전표 확정 전 후보군과 편성 변화 |
| A | `VERIFIED` | [대상경주 연간계획](https://www.data.go.kr/data/15059482/openapi.do) / 15059482 | `/API40/raceAnnualPlan`; `meet`, `rc_year`; XML | 장기 일정과 대상·특별경주 태그 |
| A | `VERIFIED` | [경마시행당일 경주결과종합](https://www.data.go.kr/data/15119524/openapi.do) / 15119524 | 당일 경주 결과 종합 | 당일 빠른 동기화의 보조 원천 |

구간 API가 제공하는 값은 연속 GPS 좌표가 아니다. Furlong 기록과 코너 통과순위로 레이스
전개를 근사하는 데이터다. 연속 위치를 얻으려면 별도의 KRA 제공 협의나 영상 추적이 필요하다.

## 4. 말·레이팅·체중 원천

| 우선 | 상태 | 공식 데이터 / ID | 주요 내용과 조건 | 프로젝트 활용 / 주의 |
|---|---|---|---|---|
| S | `LIVE` | [경주마 상세정보](https://www.data.go.kr/data/15058115/openapi.do) / 15058115 | `/API8_2/raceHorseInfo_2`; `meet`, `act_gubun`; 생년월일·산지·등급·혈통·통산/올해 성적 | `collect-horse-profiles` → `horses` + `horse_profile_snapshots`. 현역/비현역은 아래 `act_gubun` 참고 |
| S | `VERIFIED` | [경주마 성적 정보](https://www.data.go.kr/data/15058779/openapi.do) / 15058779 | 최근 경주와 통산·최근1년·최근6개월 기록·상금 | 결과 대조와 현재 프로필; 과거 시점 누수 주의 |
| S | `LIVE` | [경주마 레이팅 정보](https://www.data.go.kr/data/15057323/openapi.do) / 15057323 | `/API77/raceHorseRating`; `pageNo`, `numOfRows`; JSON; 마번과 rating1~4 | `collect-ratings` → `horse_rating_snapshots`. `observed_at_ms` 필수 |
| S | `LIVE` | [경주마 등급변동 정보](https://www.data.go.kr/data/15058076/openapi.do) / 15058076 | `/raceHorseRatingChangeInfo_2/...`; 마번, 적용·종료일, 이전·신규 등급 | `collect-grade-changes` → `horse_grade_changes` |
| S | `LIVE` | [출전마 체중 정보](https://www.data.go.kr/data/15057498/openapi.do) / 15057498 | `/API25_1/entryHorseWeightInfo_1`; `meet`, `rc_date`; 경주별 체중과 증감 | `collect-weights` / `backfill-weights` → `horse_weight_history` |
| A | `VERIFIED` | [마필종합 상세정보](https://www.data.go.kr/dataset/15033301/openapi.do?lang=ko) / 묶음 카탈로그 | 혈통·등록·소유·소재·경주경력 등 풍부한 마필 프로필 | pedigree와 식별 보강. 묶음 안 개별 API를 선택해 활용신청 |
| A | `INDEXED` | 경주마명 변경 정보 | 마번, 변경 전·후 마명, 변경일·사유 | 이름 alias 이력. 공식 마번 JOIN은 유지 |

### 4.1 현역 / 비현역 구분 (`act_gubun`)

경주마 상세 API는 응답 필드에 현역 여부가 없고, **요청 파라미터 `act_gubun`으로 목록을 나눈다.**

| `act_gubun` | 의미 | CLI | 2026-08-25 확인 totalCount (대략) |
|---|---|---|---|
| `y` (기본) | 현역 | `collect-horse-profiles` | 서울 1,777 / 제주 999 / 부산경남 1,279 |
| `n` | 비현역 | `collect-horse-profiles --include-inactive` | 서울 ~28,310 / 제주 ~20,946 / 부산경남 ~12,230 |
| (생략) | 현역과 동일하게 동작 | — | `y`와 같은 건수 |

```bash
# 현역만 (기본, act_gubun=y)
uv run horse-racing collect-horse-profiles --meets 1 2 3

# 비현역 (act_gubun=n)
uv run horse-racing collect-horse-profiles --meets 1 2 3 --include-inactive
```

현재 DB의 `horses` / `horse_profile_snapshots`에는 `is_active` 같은 플래그가 **없다**.
기본 수집은 현역만 적재하므로, 비현역을 구분·유지하려면 이후 `is_active` 컬럼을 두고
현역 목록을 주기적으로 갱신하는 설계가 필요하다. 통산·올해 성적은 수집 시점 스냅샷이므로
과거 경주 feature로 그대로 JOIN하지 않는다.

## 5. 훈련·건강 원천

| 우선 | 상태 | 공식 데이터 / ID | 주요 내용과 조건 | 프로젝트 활용 |
|---|---|---|---|---|
| S | `LIVE` | [일별훈련 상세정보](https://www.data.go.kr/data/15058782/openapi.do) / 15058782 | `/API18_1/dailyTraining_1`; `meet`, `tr_date`; 기승자·시작/종료·훈련초·구보·습보·출전예정 | `collect-training` / `backfill-training` → `horse_training` |
| A | `LIVE` | [출발훈련 정보](https://www.data.go.kr/data/15059043/openapi.do) / 15059043 | `/API22_1/startingTranning_1`; `meet`, `tr_date` | `collect-start-training` / `backfill-start-training` → `horse_start_training` |
| A | `VERIFIED` | [경주마 수영조교정보](https://www.data.go.kr/data/15144291/openapi.do) / 15144291 | `/API144/swimExerInfo`; `rccrs_cd`, 훈련일, `hr_no`, `hr_name`; JSON+XML | **403 PENDING** 활용신청 후 수집 |
| B | `VERIFIED` | [수영훈련정보](https://www.data.go.kr/data/15063981/openapi.do) / 15063981 | 기존 `/API216/SwimTr`; 말·조교사·훈련일·횟수 | API144와 범위 비교 후 중복 수집 여부 결정 |
| A | `VERIFIED` | [언덕주로 훈련정보](https://www.data.go.kr/data/15086327/openapi.do) / 15086327 | API224 참고문서; 언덕주로 조교 기록 | **PENDING** 활용신청·endpoint 재확인 |
| A | `LIVE` | [마필진료 정보](https://www.data.go.kr/data/15057799/openapi.do) / 15057799 | `/API16_1/raceHorseClinic_1`; `meet`, `clinic_date`; 진료일·병원·진단 | `collect-medical` / `backfill-medical` → `horse_medical` |
| A | `LIVE` | [출전마 장구사용 및 폐출혈 정보](https://www.data.go.kr/data/15058040/openapi.do) / 15058040 | `/API24_1/horseMedicalAndEquipment_1`; `meet`, `rc_date` | `collect-equipment` / `backfill-equipment` → `entry_equipment` |
| B | `VERIFIED` | [마필 질병 정보](https://www.data.go.kr/data/15036577/openapi.do) / 15036577 | `/API33/horseDiseaseInfo`; 한·영 질병명과 설명 | 진료 코드/용어 사전 |
| A | `VERIFIED` | [조교사 월별 조교시간](https://www.data.go.kr/data/15089715/openapi.do) / 15089715 | 경마장·월별 조교사 훈련시간 | 조교사 훈련량 snapshot |
| A | `VERIFIED` | [조교사 월별 조교비율](https://www.data.go.kr/data/15089716/openapi.do) / 15089716 | 경마장·월별 조교 비율 | 조교 패턴 feature |
| A | `VERIFIED` | [조교사 월별 조교강도](https://www.data.go.kr/data/15089717/openapi.do) / 15089717 | `/trmmtrainstr/gettrmmtrainstr`; `meet`, `tr_month` | 월별 강도·순위 feature |

## 6. 기수·조교사·마주 원천

| 우선 | 상태 | 공식 데이터 / ID | 주요 내용과 조건 | 프로젝트 활용 / 주의 |
|---|---|---|---|---|
| S | `VERIFIED` | [기수 상세정보](https://www.data.go.kr/data/15056828/openapi.do) / 15056828 | 기수번호, 생년월일·데뷔일·소속, 통산·최근 성적 | 기수 기준정보. 누적 성적은 snapshot으로 저장 |
| S | `VERIFIED` | [조교사 상세정보](https://www.data.go.kr/data/15057915/openapi.do) / 15057915 | `meet`, `tr_name`, `tr_no`; 조교사번호, 데뷔·통산·연도 성적 | 조교사 기준정보·snapshot |
| S | `VERIFIED` | [마필·기수·조교사 통산경주기록](https://www.data.go.kr/data/15058399/openapi.do) / 15058399 | `meet`, `pr_gubun`(0 말/1 마주/2 조교사/3 기수), 이름·번호; 통산·연간·6개월 | 공통 ID 대조와 현재 통계 |
| A | `VERIFIED` | [기수 통산성적비교](https://www.data.go.kr/data/15089658/openapi.do) / 15089658 | 기수별 통산 출주·순위·승률 등 | 기준 통계, 과거 예측에는 관측시점 제한 |
| A | `INDEXED` | 기수 최근1년·기간별성적비교 | 최근1년 또는 지정기간의 기수 성적 | 30/90/365일 rolling feature 후보; 개별 Swagger 재확인 |
| A | `VERIFIED` | [조교사 기간별전적비교](https://www.data.go.kr/data/15089711/openapi.do) / 15089711 | 경마장·기간별 조교사 성적 | 조교사 rolling feature |
| A | `VERIFIED` | [마주 기간별성적비교](https://www.data.go.kr/data/15089719/openapi.do) / 15089719 | `/owpresult/getowpresult`; `meet`, `rc_date_fr`, `rc_date_to` | 마주 기간별 출주·1/2/3착·승률·복승률 |

현재 DB의 `horses`, `jockeys`, `trainers`, `owners`는 각각 공식 ID로 유니크하게 관리한다.
이름은 표시와 검색용이며 JOIN 키로 사용하지 않는다.

## 7. 변경·심판·시장 원천

| 우선 | 상태 | 공식 데이터 / ID | 주요 내용 | 프로젝트 활용 / 주의 |
|---|---|---|---|---|
| A | `LIVE` | [기수변경 정보](https://www.data.go.kr/data/15057181/openapi.do) / 15057181 | `/API10_1/jockeyChangeInfo_1`; 경주일·경주·말과 변경 전후 기수·사유 | `collect-jockey-changes` → `jockey_changes` |
| A | `LIVE` | [경주마 출전취소 정보](https://www.data.go.kr/data/15056779/openapi.do) / 15056779 | `/API9_1/raceHorseCancelInfo_1`; 경주일·경주·말·취소사유 | `collect-scratches` → `race_scratches` |
| A | `LIVE` | [심판리포트정보](https://www.data.go.kr/data/15063980/openapi.do) / 15063980 | `/API215/JudgeReport`; 경주·날씨·위원·심판사항 | `collect-steward-reports` → `race_steward_reports` |
| A | `VERIFIED` | [경마 매출액 및 확정배당율](https://www.data.go.kr/data/15057896/openapi.do) / 15057896 | `/API179_1/salesAndDividendRate_1`; 경주·승식별 매출과 최종 배당 | 시장 규모와 사후 backtest |
| B | `VERIFIED` | [복승식 확정배당율 정보](https://www.data.go.kr/data/15057090/openapi.do) / 15057090 | `/API5/quinellaOddsInfo`; 복승 조합별 최종 배당 | API301 누락 대조용 |

[KRA 경마속보](https://race.kra.co.kr/raceFastreport/ChulmapyoChange.do?Act=03&Sub=1&meet=1)는
웹에서 당일 기수변경·말취소·주로상태를 빠르게 확인하는 보조 원천이다. 자동수집은 이용조건과
페이지 구조를 확인한 뒤 진행한다.

확정배당은 경주 종료 후 알게 되는 값이다. `observed_at`이 있어도 경주 전 실시간 시세가
아니므로 학습 feature로 넣지 않고 시장 비교·사후 평가에만 사용한다.

## 8. KRA Text 자료실

### 8.1 공식 진입점과 경마장

| 경마장 | `meet` | Text 자료 | 갱신주기 |
|---|---:|---|---|
| 서울 | 1 | [자료실](https://race.kra.co.kr/dbdata/textData.do?Act=12&Sub=1&meet=1) | [갱신주기](https://race.kra.co.kr/dbdata/renewDBDate.do?Act=12&Sub=2&meet=1) |
| 제주 | 2 | [자료실](https://race.kra.co.kr/dbdata/textData.do?Act=12&Sub=1&meet=2) | [갱신주기](https://race.kra.co.kr/dbdata/renewDBDate.do?Act=12&Sub=2&meet=2) |
| 부산경남 | 3 | [자료실](https://race.kra.co.kr/dbdata/textData.do?Act=12&Sub=1&meet=3) | [갱신주기](https://race.kra.co.kr/dbdata/renewDBDate.do?Act=12&Sub=2&meet=3) |

### 8.2 파일 분류 코드

2026-08-23 서울 자료실 HTML의 실제 `goPage1(fileType, codeName)` 값을 확인했다. 세 경마장
페이지에 같은 분류가 보이더라도 파일 보유 기간은 각각 확인한다.

| 구분 | `fileType` | 화면명 | 우선 사용처 |
|---|---|---|---|
| 개최 | `dacom01` | 출전표 | 과거 출전 편성 |
| 개최 | `dacom71` | 출전마진료및장구현황 | 경주 전 건강·장구 |
| 개최 | `dacom12` | 출전마체중안내 | 과거 체중 snapshot |
| 개최 | `dacom13` | 기수변경말취소주로상태 | 변경·취소·주로 |
| 개최 | `dacom07` | 출전등록말현황 | 출전 등록 후보군 |
| 기록 | `dacom23` | 주행심사결과 | `collect-running-trials` → `running_trials`, `running_trial_results` |
| 기록 | `dacom55` | 일별조교현황 | 과거 훈련 |
| 기록 | `dacom52` | 승급말현황 | 등급 변화 보조 |
| 기록 | `dacom11` | 경마성적표 | 과거 결과 backfill 핵심 |
| 기록 | `dacom21` | 말성적조회 | 말별 누적·최근 성적 |
| 기록 | `dacom22` | 기수성적조회 | 기수 성적 |
| 기록 | `dacom72` | 말진료현황 | 진료 이력 |
| 기록 | `db4` | 출발심사결과 | 출발 심사 |
| 기록 | `db5` | 출발조교현황 | 출발 조교 |
| 기록 | `db7` | 마명변경내역 | 말 이름 alias 이력 |
| 기본 | `db1` | 경주마정보 | 말 기준정보 |
| 기본 | `db2` | 기수정보 | 기수 기준정보 |
| 기본 | `db3` | 조교사정보 | 조교사 기준정보 |
| 기본 | `db6` | 마주정보 | 마주 기준정보 |

### 8.3 목록 조회와 파일 다운로드 절차

목록은 `POST https://race.kra.co.kr/dbdata/textDataList.do`로 조회한다. 필수 실사용 값은
`meet`, `fileType`, `codeName`, `pageIndex`이며 한 페이지에 파일 10개가 표시된다.

```bash
curl --fail --silent --show-error \
  --request POST 'https://race.kra.co.kr/dbdata/textDataList.do' \
  --data-urlencode 'Act=12' \
  --data-urlencode 'Sub=1' \
  --data-urlencode 'meet=1' \
  --data-urlencode 'fileType=dacom11' \
  --data-urlencode 'codeName=경마성적표' \
  --data-urlencode 'pageIndex=1' \
  --output /tmp/kra-text-list.html
```

목록 HTML은 EUC-KR이므로 링크를 추출할 때 변환한다.

```bash
iconv -f euc-kr -t utf-8 /tmp/kra-text-list.html \
  | rg -o '/dbdata/fileDownLoad\.do\?fn=[^" ]+&meet=[123]'
```

목록에서 얻은 `fn`과 `meet`을 그대로 다운로드 URL에 사용한다.

```bash
curl --fail --location --retry 5 \
  'https://race.kra.co.kr/dbdata/fileDownLoad.do?fn=chollian/seoul/jungbo/rcresult/20260822dacom11.rpt&meet=1' \
  --output data/raw/kra_text/dacom11/meet=1/20260822dacom11.rpt
```

실제 `20260822dacom11.rpt`를 내려받아 확인한 결과 76,233 bytes, EUC-KR 한글, CRLF 줄바꿈의
고정폭 보고서였다. `dacom11` 서울 목록은 마지막 217페이지의 `20030712dacom11.rpt`까지
실제 노출됐다. 이는 **경마성적표·서울 한 종류에 대한 확인값**이며 다른 분류·경마장 최초일을
같다고 가정하지 않는다.

원본 `.rpt`는 변환하지 않은 채 보존하고 파서 입력에서만 UTF-8로 변환한다.

```bash
iconv -f euc-kr -t utf-8 \
  data/raw/kra_text/dacom11/meet=1/20260822dacom11.rpt \
  > /tmp/20260822dacom11.utf8.rpt
```

### 8.4 Text downloader 구현 요구사항

1. `meet × fileType × pageIndex` 목록을 끝까지 순회한다.
2. 파일 URL, 원격 파일명, 크기, 목록 페이지, 발견시각을 manifest에 먼저 기록한다.
3. 이미 같은 SHA-256이 있으면 재다운로드하지 않는다.
4. 다운로드 도중 종료돼도 `.part`를 최종 파일로 오인하지 않도록 원자적으로 rename한다.
5. 원본 bytes, HTTP 상태·헤더, `retrieved_at`, SHA-256을 보존한다.
6. 서버 부하를 피하도록 직렬 또는 낮은 동시성, 요청 간 지연, 429/5xx backoff를 사용한다.
7. 분류별 인코딩·고정폭/구분자·최초일·누락기간을 표본 검사한 뒤 별도 parser를 만든다.
8. API와 겹치는 기간을 표본 대조해 ID, 건수, 정정자료 우선순위를 정한다.

1~6의 공통 Downloader는 `download-text-archive`로 구현됐다. manifest는 다운로드 전에
`discovered` 이벤트를 기록하고 `downloaded`, `skipped_existing`,
`skipped_duplicate_sha256`, `failed` 상태를 append-only로 남긴다. 예:

```bash
uv run horse-racing download-text-archive \
  --file-type dacom11 --start 20150101 --end 20241231 --meets 1 2 3
```

`dacom11`은 분류별 parser의 첫 구현 대상이다. 2026-08-28에 서울·제주·부산경남
2015~2024 원본 2,717파일을 확보하고 24,586경주·260,066출전/결과를 정규화 DB에
적재했다. 2026-08-23 서울 API 중복 표본 10경주·97두의 착순/기록 불일치는 0건이었다.
다운로드 재실행은 기존 파일을 건너뛰며, 파일 저장 뒤 DB 기록 전에 중단된 경우에도
`SourceDocument` 메타데이터를 복구한다.

정규화 전 감사와 적재 명령은 다음과 같다.

```bash
uv run horse-racing ingest-text-results \
  --start 20150101 --end 20241231 --meets 1 2 3 --validate-only
uv run horse-racing ingest-text-results \
  --start 20150101 --end 20241231 --meets 1 2 3 --allow-synthetic-horses
```

공식 마번은 260,057/260,066건이 연결됐고, `마이공주` 9회 출전만 하나의 결정적
`text:` ID를 사용했다. 성적표에는 예정 출발시각이 없으므로 `scheduled_at_ms`는
`dacom01` 보강 전까지 결측이다.

## 9. 새 에이전트용 OpenAPI 다운로드 순서

### 9.1 활용신청 확인

1. 위 공식 링크에서 API마다 `활용신청` 상태를 확인한다.
2. 상세 페이지의 수정일, 데이터 포맷, 일일 트래픽, 참고문서, 요청주소를 manifest에 기록한다.
3. Swagger에서 요청 변수와 날짜 기본값을 확인한다. 날짜를 생략하면 “최근 한 달”만 반환하는
   API가 있으므로 backfill에서 검색기간을 절대 암묵값으로 두지 않는다.
4. 표본은 `meet=1`, 실제 경주일 하루, `pageNo=1`, 작은 `numOfRows`로 호출한다.
5. 응답의 `resultCode`, `totalCount`, item 경로와 실제 필드 타입을 저장한 뒤 수집기를 구현한다.

### 9.2 안전한 표본 호출 템플릿

셸 히스토리와 프로세스 목록에 인증키가 보일 수 있으므로 로컬 개발에서는 기존 Python 설정을
사용하는 편이 낫다. curl이 필요하다면 키를 출력하거나 문서에 붙여 넣지 않는다.

```bash
set -a
source .env
set +a

curl --fail --silent --show-error --get \
  'https://apis.data.go.kr/B551015/API4_3/raceResult_3' \
  --data-urlencode "ServiceKey=${HORSE_RACING_DATA_GO_KR_SERVICE_KEY}" \
  --data-urlencode 'pageNo=1' \
  --data-urlencode 'numOfRows=10' \
  --data-urlencode 'meet=1' \
  --data-urlencode 'rc_date=20260822' \
  --data-urlencode '_type=json'
```

인증키가 이미 URL-encoding된 키인지 Decoding 키인지에 따라 중복 인코딩 오류가 생길 수 있다.
이 프로젝트에서는 `.env`에 공공데이터포털의 **Decoding 인증키**를 저장하고 HTTP client가
query encoding을 하게 한다.

### 9.3 권장 구현 순서

```text
1. 경주 구간별 성적 → `API4_3/raceResult_3`로 `race_section_results` 적재 완료 (`collect-race-sections`, `backfill-sections`)
2. 말 레이팅·등급변동·체중 → point-in-time 말 이력
3. 일별·수영·출발·언덕 훈련 → 최근 훈련 feature
4. 진료·장구·폐출혈 → 건강 이력
5. 기수·조교사 기간별 성적 → 사람 snapshot
6. 기수변경·출전취소·심판리포트 → 경주 변경 사건
7. Text downloader → 장기 과거 원본 확보
8. API/Text 중복기간 대조 → parser와 정정 우선순위 확정
```

## 10. Raw 저장 계약

권장 경로 예시는 다음과 같다.

```text
data/raw/
├── kra_api/
│   └── {source_name}/year=YYYY/month=MM/day=DD/meet=N/{run_id}/page=0001.json
└── kra_text/
    └── {file_type}/meet=N/{remote_filename}
```

각 원본에 대응하는 수집 메타데이터에는 최소 다음 값을 남긴다.

```text
source_name, official_data_id, portal_url
endpoint, operation, public_request_params
requested_at, retrieved_at, observed_at, effective_at
http_status, content_type, encoding
remote_filename, local_path, byte_size, sha256
parser_version, ingestion_run_id
```

서비스키는 `public_request_params`, URL, 파일명, 로그 어디에도 넣지 않는다. Git에는 문서와
코드만 올리고 `data/`의 실제 DB·원본·로그는 올리지 않는다.

## 11. 시점 누수 체크리스트

- 현재 레이팅·현재 통산 성적·현재 상금을 과거 경주에 그대로 JOIN하지 않는다.
- 체중, 기수변경, 취소, 주로상태는 “경주일 데이터”만으로 충분하지 않고 실제 공개시각을
  보존해야 한다.
- 결과, 착순, 경주기록, 확정배당, 실제 출발시각은 경주 전 feature가 아니다.
- AI학습용이라는 명칭은 feature-ready 또는 leakage-free를 보증하지 않는다.
- 모든 snapshot에 가능한 한 `effective_at`, `observed_at`, `ingested_at`을 둔다.
- 모델 데이터셋 생성 시 명시적 `prediction_at` 이전에 공개된 행만 point-in-time join한다.

## 12. 완료 판정

새 소스를 추가했다면 다음을 모두 충족해야 “수집 완료”로 표시한다.

- 공식 데이터 ID와 링크, 확인일, endpoint/operation, 포맷, 한도를 기록함
- 활용승인이 실제 표본 호출에서 확인됨
- 전체 pagination과 빈 결과를 처리함
- 원본 bytes와 SHA-256, 공개 요청 파라미터를 보존함
- 동일 명령 재실행이 중복 행을 만들지 않음
- 경마장·날짜별 기대 건수와 ID 결측/중복을 검사함
- 응답의 의미와 공개시점, 누수 위험을 문서화함
- API/Text 중복 데이터라면 표본 대조 결과와 우선 원천을 결정함

이 문서의 공식 링크와 메타데이터는 2026-08-23 기준이다. KRA와 공공데이터포털은 API 명세를
수정할 수 있으므로 구현 직전과 운영 장애 시 개별 상세 페이지를 다시 확인한다.
