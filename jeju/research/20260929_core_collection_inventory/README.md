# 제주마 API 우선 기본 원천 인벤토리

기준일: 2026-09-29

## 최신 상태

API 재시도와 신규 core DB 적재가 완료됐다. 초기 DNS 실패 기록은 그 시점의 실패 시도이며 현재 상태가 아니다. 최신 수집·대조·품종 후보·제한은 [API 우선 재수집 보고서](API_FIRST_RERUN_20260929.md)를 기준으로 본다.

- 경주결과는 공공데이터포털 **한국마사회 경주기록 정보**(15058305, `API4_3/raceResult_3`)에서 2002~2026 응답 191,786행을 받았다. 2026 최신 결과일은 9/19다.
- 주행심사는 **한국마사회 주행심사 상세결과**(15056974, `API20_1/ridingTestResult_1`)에서 2000~2026 응답 34,377행을 받았다. 정확한 `majong=제주`는 15,738행이며 최초 관측일은 2002-06-12, 최신은 2026-09-16이다. 2000·2001년 응답에는 제주 라벨이 없다.
- 신규 원장은 [`jeju/data/jeju_native_core.sqlite3`](../../data/jeju_native_core.sqlite3)다. API 응답 원문과 정규화 관측·coverage·출처/이슈를 연결한 DB이지 확정 품종만 담은 DB는 아니다.
- API 원문 결과행에 말별 품종 필드는 없어 `breed_label_raw=NULL`로 둔다. `rank` 접두 `제`는 후보 선택에만 사용한다. 이 후보 92,414행·9,445경주 외에, 경주일 이전 또는 당일의 동일 ID `API20_1 majong=제주` 교차근거로 추가된 281행·68개 경주가 있다. 추가 68경주 중 모든 API4_3 출전행이 후보인 경우는 24개뿐이라 혼합/부분 후보 경주로 별도 설명한다.
- 2026-09-17~19 경주 206행은 API 결과와 출전 키·말 ID·착순이 206/206 일치하고 주파기록이 204/206 일치한다. 9/16 API 주행심사 20행은 `majong=제주`, 말 ID가 전부 고유하다.
- RPT/TXT는 API가 주지 않는 9/16 심사거리 800m 세 건을 `supplement`로 보완하고, 2021 자수정의 API/RPT 마종 불일치 한 건을 `validation_only`로 격리하는 데에만 썼다.

DB 적재 결과와 원문 SHA/무결성은 [`jeju/data/jeju_native_core.build_manifest.json`](../../data/jeju_native_core.build_manifest.json)에서 확인한다. 품종 기준시점이 확인되지 않은 결과를 제주마로 확정하지 않았다. API42_1 현재 프로필은 별도 [실현 가능성 조사](../20260929_horse_breed_profile_api/API42_1_FEASIBILITY.md)를 참조한다.

## 주요 산출물

- [API-first 재수집 결과와 검증](API_FIRST_RERUN_20260929.md)
- [연도별 결과 API 원문](../20260929_api4_3_history_backfill/attempts/20260929T132522.134266Z/)
- [연도별 주행심사 API 원문 inventory](../20260929_trial_api_backfill_2003_2025/collection_inventory.json)
- [신규 DB DDL](../../data/schema/jeju_native_core.sql)
- [API raw 기반 DB 로더](../../scripts/build_native_core_from_api_raw.py)

이 폴더의 `FOLLOWUP_20260929.md`와 첫 `raw/2026/attempts/20260929T070858.176641Z/` 시도 manifest는 최초 조사 당시의 DNS 실패·미대조 상태를 기록한 **역사적 기록**으로 보존했다. 이후 성공한 API 수집과 대조 결과는 위 최신 보고서가 대체한다. 해당 파일들의 현재형 결론을 최신 상태로 인용하지 않는다.
