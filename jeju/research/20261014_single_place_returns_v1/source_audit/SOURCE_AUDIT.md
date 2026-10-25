# 연승(PLC) 원천 감사

## 판정

**PASS — 저장된 API301 원문 가격과 고정 평가 runner 명단의 coverage·공식 말 ID·연승 순위 자격을 확인했다.** 이 감사는 확률, 모델 성과, 적중률 또는 ROI를 계산하지 않았다.

기계 판독 게이트는 `SOURCE_AUDIT_FINAL.json`이며, 가격 입력은 `PLC_PRICE_ROWS.csv`, 전체 고정 평가 roster의 공식 결과는 `OFFICIAL_RUNNER_RESULTS.csv`다. 원천별 경로와 페이지 SHA는 `SOURCE_INVENTORY.json`, `SOURCE_PAGE_INDEX.csv`, `SOURCE_PAGE_MANIFEST.csv`에 기록했다.

## API301 원문과 선택 기준

원천은 로컬에 저장된 KRA API301 `/API301/Dividend_rate_total`의 `PLC` 항목이다. 프로젝트 formatter에서 `PLC`는 연승으로 표기된다. 원문 item의 관련 필드는 `rcDate`(경주일), `rcNo`(경주번호), `meet`, `pool`, `chulNo`(단일 마번), `odds`(표시 배당)다. 연승 item은 한 마번을 나타내며 `chulNo2`, `chulNo3`는 0이다. API item에는 공식 KRA horse ID나 가격 최초 공표시각이 없으므로, 원천 키 `race_id + horse_number`를 공식 결과 roster에 연결한 뒤 `kra_horse_id`를 부여했다. cache의 `source_retrieved_at_ms`는 로컬 수집 registry 시각이며 공식 가격 공표시각으로 해석하지 않는다. 분석 join은 검증된 `race_id + kra_horse_id`를 권한다. 초안의 DB 내부 surrogate ID는 `horse_db_id`로 이름을 바꾸어 보존했다.

각 날짜·시행별로 저장된 **최신 완전 run**을 선택했다. 완전성은 페이지 연속성, `totalCount`와 페이지별 행 수의 일치, 전체 item 수 확인을 포함하는 기존 API301 감사 기준을 따랐다. 선택 페이지 목록 506개의 SHA-256은 기존 고정 index와 일치하며, 각 원문 파일의 실제 SHA를 다시 검사했다. 모두 통과했다. 선택 대상은 171개 날짜의 완전 run 171개다. 평상시 원문 페이지는 `data/raw/kra/final_dividend/YYYY/MM/DD/meet_*/run_*/`에 있고, 검증된 backfill 페이지는 `data/research/dividend_backfill_20261002_verified/`에 있다. 개별 파일 경로, page 번호, byte 수와 SHA는 `SOURCE_PAGE_MANIFEST.csv`에 있다.

이 선택은 저장된 완료 run 가운데 가장 최신인 run을 택한다. 원문을 다시 수집하거나 API에 접속하지 않았다. 동일한 raw 내용의 페이지·행을 전역 dedupe하지 않았다. 고정 가격 cohort의 원문 일치행 11,083개는 11,083개의 고유 `(race_id, horse_number)`로 확인됐다. 대상 cohort 바깥의 임시 추출행 1,089개도 `drafts/PLC_NONCOHORT_SOURCE_MATCHES.csv`에 보존했다. 최초 임시 파일도 `drafts/PLC_PRICE_ROWS.initial.csv`로 보존했다.

## Coverage와 공식 결과 연결

가격 원문이 있는 고정 cohort는 2025년 654경주와 2026-09-19까지 488경주, 총 1,142경주다. 이 1,142경주에서 실제 출주 runner별 PLC quote 11,083개를 찾았다. 고정 평가 전체 1,779경주 중 나머지 2024년 637경주는 이 로컬 원문 source에서 가격을 확인할 수 없어 가격 cohort에 포함되지 않는다.

원문 quote를 독립 기준 `ROOT_PLC_REFERENCE.csv`와 `(race_id, horse_number)`로 대조했다. 11,083개 가격 값과 원문 페이지 SHA가 모두 정확히 일치했고, 누락·불일치는 0건이다. 가격 지원 경주마다 원문 runner 수가 공식 `field_size`와 일치했다. 공식 결과 cache `OFFICIAL_RUNNER_RESULTS.csv`에는 전체 1,779경주의 17,412 runner가 있으며, root의 별도 검토에서 저장된 모델 runner roster와 공식 KRA ID·실제 field size·finish position이 일치했다. 전체 경주가 완료 상태이고 scratch, DQ, dead heat 또는 불완전 roster는 0건이었다.

가격 지원 1,142경주 중 실제 출주두수가 7두 이하인 경주는 36개, 8두 이상인 경주는 1,106개다. 공식 출주두수를 기준으로 7두 이하에는 Top2, 8두 이상에는 Top3 규칙을 적용했다. 모든 가격 지원 경주에서 raw PLC runner 수가 official field size와 일치했고, 공식 finish position 기준 qualifying runner 수가 각각 2마리 또는 3마리와 일치했다. 공식 마번과 KRA horse ID의 경주별 연결도 모두 유일했다.

## 가격·환급 의미와 한계

원문에는 runner별 `odds`가 있다. 이 값은 승자에게만 지급되는 환급 행이 아니다. 공식 순위상 연승 자격 밖인 말에도 표시 가격이 존재하므로, 미적중 말의 가격행이 없는 것으로 처리해서는 안 된다. 계산 단계에서는 공식 순위가 연승 자격 밖이면 총환급을 0으로 둔다. raw quote 자체를 지급 환급으로 해석하지 않는다.

cache의 `odds`는 원문 숫자를 변환 없이 유지한다. 기존 로컬 payout 연구는 이 표시 배당을 stake 단위당 gross return 배수로 취급했지만, API301 item 자체에는 KRW stake나 지급액 필드가 없다. 따라서 원문 표시값은 복제했고 별도 환산은 하지 않았다. 원문만으로는 경주 전 최초 가격이나 해당 가격의 공표 시각을 복원할 수 없다. 이번 cohort의 선택행에서 0, `9999.9`, null, 비수치 값은 모두 0건이다.

고정 cohort에 Top2/Top3 동착은 없어 동착 시 지급 분배, 환급 또는 기타 예외 정산 계약은 이 감사로 확인되지 않았다. 결과 계약에 이 cohort 범위를 넘어 일반화하지 않는다. 2024년은 결과 roster가 있어도 승자 quote 원문을 찾지 못했으므로 2024년의 전체 환급을 가격 자료로 검증할 수 없다.

## 산출물과 검증

`SOURCE_AUDIT_FINAL.json`은 PASS, 입력 artifact hash, quote coverage, 공식 결과 연결, field-size 자격 및 중복행 정책을 기계 판독 형식으로 기록한다. `SOURCE_INVENTORY.json`은 endpoint, 원문 키, 날짜별 최신 완전 run 선택, 페이지 목록/hash, 가격 해석, cohort coverage와 개인정보 제외 범위를 기록한다. `API301_PLC_EXAMPLES.json`에는 마번·경주·가격·순위 자격만 있는 원문 사례를 포함했으며 이름이나 인증정보는 넣지 않았다.

검증한 핵심 수치는 다음과 같다.

- 선택 원문 페이지 506개 SHA 전부 일치, 날짜별 최신 완전 run 171개.
- PLC 원문과 독립 reference 간 가격·페이지 hash 일치 11,083/11,083.
- 가격 원문 coverage 1,142경주, official runner 11,083/11,083.
- 전체 결과 cache 1,779경주, 17,412 runner.
- 0, `9999.9`, null/non-numeric quote 0건; duplicate race-runner key 0건.
- 확률·성과·ROI 계산 없음.
