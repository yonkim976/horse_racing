# 제주마 경주 당시 공식 ID 미해결 29행 (2026-09-14)

범위는 2002-07-28~2026-09-12에 공식 결과가 `제`로 명시되고, 해당 경주에 정상 숫자 착순과 양수 완주시간이 최소 1행 있는 경주다. 확인된 9,288경주·90,892행 중 세 공식 ID를 연결한 90,863행은 [별도 연구 원장](../data/research/jeju_confirmed_race_time_ids_20260914/linked_official_ids.jsonl)에 있다. 아래 **29행만 미해결**이다. 기존 DB·원문·모델은 수정하지 않았다.

- **조교사 25행:** 공식 결과의 `trNo=0BBBBB`, `trName=외부마`는 개별 조교사 ID가 아니다. 말과 마주 공식 번호는 연결됐지만 조교사 번호는 공란으로 남겼다.
- **말 ID 4행:** 2019년 네 경주에서 같은 출주번호의 공식 API는 `푸른장군/3017931`, 기존 Text·DB는 `푸른대왕/3018834`다. 경주행의 말 ID 자체가 달라 세 번호를 DB 출전행에 연결하지 않았다.

| 경주일 | 경주 | 출주 | API 말명 / `hrNo` | 미해결 사유 | DB 대조 | 원천 행 |
| --- | ---: | ---: | --- | --- | --- | --- |
| 2017-09-09 | 5 | 7 | 최대공약수 / `3016290` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2017.jsonl:1733](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2017.jsonl) |
| 2019-05-03 | 8 | 10 | 푸른장군 / `3017931` | 말 ID·마명 충돌 | `푸른대왕/3018834` | [원천 official_native_results_2019.jsonl:4355](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2019.jsonl) |
| 2019-05-25 | 9 | 10 | 푸른장군 / `3017931` | 말 ID·마명 충돌 | `푸른대왕/3018834` | [원천 official_native_results_2019.jsonl:3886](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2019.jsonl) |
| 2019-06-08 | 8 | 3 | 푸른장군 / `3017931` | 말 ID·마명 충돌 | `푸른대왕/3018834` | [원천 official_native_results_2019.jsonl:3626](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2019.jsonl) |
| 2019-07-12 | 9 | 7 | 푸른장군 / `3017931` | 말 ID·마명 충돌 | `푸른대왕/3018834` | [원천 official_native_results_2019.jsonl:3049](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2019.jsonl) |
| 2022-03-11 | 5 | 5 | 검은맹주 / `3102504` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2022.jsonl:5230](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2022.jsonl) |
| 2022-10-21 | 2 | 3 | 중문보스 / `3102843` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2022.jsonl:1351](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2022.jsonl) |
| 2023-05-27 | 6 | 8 | 광명성호 / `3016266` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2023.jsonl:4314](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2023.jsonl) |
| 2026-07-07 | 1 | 9 | 민강불패 / `3104267` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1547](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 1 | 6 | 금지게 / `3104615` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1544](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 1 | 5 | 주마녀 / `3107428` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1542](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 1 | 8 | 대지사랑 / `3107485` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1541](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 1 | 7 | 이글킹 / `3107842` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1548](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 1 | 2 | 일품히트 / `3109274` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1546](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 2 | 8 | 비룡신공 / `3102610` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1556](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 2 | 10 | 불생불사 / `3103344` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1557](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 2 | 9 | 서산히어로 / `3103597` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1551](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 2 | 3 | 무림왕자 / `3105495` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1549](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 3 | 4 | 라이덴 / `3101444` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1561](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 3 | 7 | 월드프린스 / `3104199` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1567](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 3 | 1 | 동백천하 / `3104260` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1562](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 3 | 9 | 지구 / `3104630` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1566](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 3 | 5 | 새벽전설 / `3107541` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1559](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 3 | 8 | 파워스타 / `3107868` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1560](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 4 | 7 | 영웅퀸 / `3103305` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1575](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 4 | 2 | 진한파도 / `3103315` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1573](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 4 | 9 | 용트림 / `3103398` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1577](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 4 | 1 | 명성만리 / `3104094` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1569](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |
| 2026-07-07 | 4 | 5 | 일품걸 / `3104649` | 조교사 `0BBBBB` (`외부마`) | DB 조교사도 `0BBBBB` | [원천 official_native_results_2026.jsonl:1572](../data/research/jeju_race_time_official_ids_20260914/official_native_results_2026.jsonl) |

[미해결 29행 기계 판독 원장](../data/research/jeju_confirmed_race_time_ids_20260914/unresolved_29.jsonl)은 각 행의 공식 API 응답 SHA-256, 필터링 원문 파일 SHA-256·행 번호, DB 값, 마주번호 후속 대조 근거를 보존한다. 2019년 말 ID 충돌은 같은 출주번호의 DB측 행도 `same_number_db_candidates`에 붙였다. 마주번호가 충돌했던 2022-03-11 `검은맹주`는 [두 공식 경주별 API 대조](../data/research/jeju_owner_boundary_entry_sheets_20260914/five_native_entry_sheet_rows.json)로 `owNo=001105`를 연결했지만 `trNo`는 여전히 미해결이다.

[재현 코드](../scripts/materialize_jeju_confirmed_race_ids.py) · [독립 검증 코드](../scripts/verify_jeju_confirmed_race_ids.py) · [검증 결과](../data/research/jeju_confirmed_race_time_ids_20260914/verification.json). 이 원장은 경주 당시 결과의 ID 근거만 다루며, 과거 경주 전 공개 시각·조교/진료 사건의 사람 귀속·예측 성능을 증명하지 않는다.
