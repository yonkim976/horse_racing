# API 우선 재수집·원장 구축 결과

기준일: 2026-09-29

## 현재 산출물과 원천 이름

- **신규 DB:** [`jeju/data/jeju_native_core.sqlite3`](</Users/kimyongjin/Desktop/horse_racing/jeju/data/jeju_native_core.sqlite3>). KRA API 원문을 보존하고 결과·주행심사 관측, 마종 근거, 보완 출처, 충돌을 연결한 **API 우선 근거 원장**이다. 제주마 확정 행만 담은 최종 DB는 아니다. 결과 API에는 개별 마종 필드가 없고, 후보 행도 과거 시점의 마종이 확정되지 않았으므로 결과행에 `native_confirmed`를 부여하지 않았다.
- **경주결과 1차 원천:** 공공데이터포털 15058305 **한국마사회 경주기록 정보**, `B551015/API4_3/raceResult_3` (`meet=2`, 연도별 `rc_year`). 제주 경마장 전체 결과 응답을 원문 바이트로 보존했다.
- **주행심사 1차 원천:** 공공데이터포털 15056974 **한국마사회 주행심사 상세결과**, `B551015/API20_1/ridingTestResult_1` (`meet=2`, 연도별 `tr_year`). 응답의 `majong` 원문 라벨과 공식 말 ID·심사일을 관측 근거로 보존했다.
- **현재 말 프로필 보조 검토:** 공공데이터포털 15057985 **한국마사회 마필종합 상세정보**, `B551015/API42_1/totalHorseInfo_1`. 수집 가능성·제한은 [API42_1 조사](<../20260929_horse_breed_profile_api/API42_1_FEASIBILITY.md>)에 있다. `breed`는 응답 시점의 프로필 관측이며 역사적 경주일의 품종을 소급 입증하지 않는다.

모든 원문·coverage·정규화 관측은 신규 DB와 아래 raw 경로에 있다. 서비스 키는 manifest나 로그에 남기지 않았다. 기존 운영 DB와 phase2 연구 DB를 읽기 전용으로만 확인했고 신규 DB의 입력으로 복사하지 않았다.

## 적재 범위와 검증

| 자료 | API 응답 범위 | 행·이벤트 수 | 판정 |
|---|---:|---:|---|
| API4_3 경주결과 | 2002~2026, 2002-01-12~2026-09-19 | 191,786 출전·결과행 | 제주 경마장 전체 원행 보존 |
| API20_1 주행심사 | 2000~2026, 2000-01-05~2026-09-16 | 34,377행 | 전체 마종 라벨 보존 |
| API20_1 `majong=제주` | 2002-06-12~2026-09-16 | 15,738행·1,967심사 | API 명시 라벨 관측; 2000·2001에는 제주 라벨 0행 |
| 원문 응답 | 두 API 전체 | 80개 source artifact·226,163개 API raw record | raw SHA 80/80 일치 |

DB build manifest는 [`jeju_native_core.build_manifest.json`](</Users/kimyongjin/Desktop/horse_racing/jeju/data/jeju_native_core.build_manifest.json>)이다. `PRAGMA integrity_check=ok`, 외래키 위반 0건이며 manifest가 추적하는 원문 80개의 SHA-256 불일치도 0건이다. DB SHA-256은 `6196f332981f8fbc5008fe0e538ad75ae0189cf348246e81b6674fd772e408aa`다. 연도별 상세 coverage는 manifest와 `collection_coverage` 테이블에서 확인한다.

주요 원문 위치:

- 경주결과 2002~2025: [`20260929_api4_3_history_backfill/attempts/20260929T132522.134266Z/`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_api4_3_history_backfill/attempts/20260929T132522.134266Z>)
- 경주결과 2026: [`2026 API4_3 시도`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_core_collection_inventory/raw/2026/attempts/20260929T132618.518555Z>), 페이지 SHA-256 `8f60ee195eff36cb2f4bd0620fd4db0e30ac2b17618c0b7bbfc1b144a2eb4006`
- 주행심사 2000~2025: [`trial API inventory`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_trial_api_backfill_2003_2025/collection_inventory.json>)의 연도별 attempt 경로
- 주행심사 2026: [`2026 API20_1 시도`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_core_collection_inventory/raw/trials/2026/attempts/20260929T132644.423798Z>), 페이지 SHA-256 `248b26df1494c23f3a8c5cfdfe383df997e0af0109e0a761b180eb4b52ce33f6`

2026년 9월 최신 응답은 후보 원천과 다음처럼 비교했다.

- 9/17~19 경주: API4_3 206행과 기존 후보 206행의 날짜·경주·출주번호·공식 말 ID·착순 등 식별·결과 키가 모두 일치했다. 주파기록은 204/206 일치한다. 나머지 두 행은 9/19 4R의 말 ID `3103453`, `3103835`; API `rcTime=0`인 비주행행이며 후보 기록은 NULL이다. 상세는 해당 attempt의 `api_validation_20260917_19.json`이다.
- 9/16 주행심사: API20_1에 20행, 말 ID 20개, `majong=제주` 20행이 있다. 심사번호별 7/7/6행, 판정은 합격 13·불합격 6·출전취소 1이다. RPT 비교표는 검증용이며 API 원문을 대체하지 않는다.

## 결과행의 품종 후보와 한계

API4_3 원문에는 개별 말의 품종 필드가 없다. 따라서 결과행의 `breed_label_raw`는 전부 NULL이고 원문 `rank`는 `rank_class_raw`로 따로 보존한다. `rank`가 `제`로 시작한다는 이유만으로 품종을 확정하지 않는다.

- `rank_class_raw` 접두가 `제`인 결과는 **후보** 92,414행·9,445경주·4,006개 말 ID다. 이 4,006개 ID는 API20_1에서 같은 공식 말 ID의 `majong=제주` 관측이 있으며, 후보 행 전체에서 관측일은 경주일 이전 또는 당일이다. 이는 시간 관계를 가진 교차 후보 근거이지 품종 유효기간을 입증하는 자료는 아니다.
- `rank`가 `제`로 시작하지 않지만 동일 말 ID의 API20_1 `majong=제주`가 그 경주일 이전 또는 당일에 관측된 추가 결과 후보는 281행·197개 말 ID·68경주다. 연도별 행 수는 2002년 21, 2003년 36, 2004년 8, 2006년 26, 2007년 17, 2008년 30, 2009년 57, 2010년 28, 2012년 58이다.
- 추가 281행 중 229행은 API4_3 원문의 `rank`가 빈 문자열이며 거리와 주로상태도 비어 있다. 나머지 52행은 `래2` 또는 `래3`이다. 추가 후보의 조건 필드 결측을 기존 `제` 후보의 완전성과 혼동하지 않는다.
- [`jeju_race_population_candidates` 뷰](</Users/kimyongjin/Desktop/horse_racing/jeju/data/jeju_native_core.sqlite3>)의 합계는 92,695행·9,513경주·4,006개 ID다. 추가 68경주에는 API4_3 전체 출전행 609개가 있고, 그중 추가 후보는 281행이다. 68경주 중 전 출전행이 이 추가 후보인 경주는 24개뿐이다. 따라서 68경주를 제주마 전용 경주로 부르지 않는다.
- 후보 뷰 안에서 비제주 `API20_1 majong` 관측과 연결된 결과행/ID는 0, 같은 ID의 API20_1 다중 마종 라벨 관측도 0이다. 이는 현재 수집 원문에서의 관측 결과이며 모든 역사 기간의 품종 이력을 뜻하지 않는다.

API20_1 주행심사 행은 API가 표시한 당시 심사 라벨로 그대로 남긴다. `breed_evidence`는 말 ID와 심사일의 직접 API 관측을 연결한다. 서로 다른 날의 프로필 값은 과거로 소급하지 않으며, 경주 당시 유효 품종 근거가 없으면 결과는 확정하지 않는다. 2023년 이후의 제주마 전용 시행 규칙은 경주 모집단 차원의 후보 근거로 별도 표시하고 API의 말별 필드처럼 취급하지 않는다.

## RPT/TXT 보완과 충돌

- **2026-09-16 거리:** API20_1 응답에 심사 거리가 없어 RPT의 1~3차 `800m` 표기 3건을 `supplement` 역할로 적재했다. API 관측 값은 변경하지 않았다.
- **2021-10-21 자수정(ID `1019026`):** API20_1 원문 `majong=한라`와 RPT 13행 문자 `제`가 다르다. RPT는 `validation_only`이며 두 관측을 모두 보존하고 해당 주행심사 행을 격리했다. RPT SHA-256 `d1901d3ce1c1d0d4d9e2956cc343f5c36cd78e01023caba9377b05628a022a5f`.

이 예외 외에는 TXT/RPT를 기본 수집원으로 쓰거나 기존 Text 기반 phase2 행을 API 사실로 복사하지 않았다.

## 재현 및 다음 연결

새 DB는 다음 명령으로 보유한 검증된 API raw에서 별도 scratch DB로 재생성한다. 기본 DB 경로가 이미 존재하면 로더가 덮어쓰기를 거부한다.

```bash
python3 jeju/scripts/build_native_core_from_api_raw.py --database /tmp/jeju_native_core_rebuild.sqlite3
```

DDL은 [`jeju_native_core.sql`](</Users/kimyongjin/Desktop/horse_racing/jeju/data/schema/jeju_native_core.sql>), 로더는 [`build_native_core_from_api_raw.py`](</Users/kimyongjin/Desktop/horse_racing/jeju/scripts/build_native_core_from_api_raw.py>)다. DB에는 모든 meet=2 경주결과 원행과 모든 마종의 주행심사 원행이 들어 있다. 다음 단계는 품종 유효시점이 확인되는 공식 이력을 확보하거나 미확정 후보를 격리하는 것이며, API42_1 현재 프로필 전체 수집만으로 과거 결과를 확정하지 않는다.
