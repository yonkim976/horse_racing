# 제주 구간기록 남은 항목 검증 2026년 10월 2일

기존 구간 감사에서 남긴 항목을 공식 홈페이지 92경주, API 재조회, 부족하거나 충돌하는 범위의 공식 TXT 27경주로 대조했다. 기존 27경주 불일치 후보 중 8경주는 출처별 지점 대응 또는 말별 순위 차이로 설명됐고, 19경주는 홈페이지와 TXT 안에서도 말별 순위와 통과조 범위가 어긋난다. 정정 후보와 정답 미확정을 구분했으며 이번 점검에서 DB를 변경하지 않았다.

## 범위와 원천

- 전체 원문 감사 모집단은 경주 후보 92,513행·9,494경주다. 이 중 실제 완주 경주는 9,347개이며 취소·불성립 147경주는 별도다. 이번 홈페이지 대조는 남은 후보의 합집합 92경주로, 전체 경주의 홈페이지 검증 완료를 뜻하지 않는다.
- 말별 구간시간·통과착순은 `API4_3/raceResult_3`, 경주 전체 구간거리·누적시간·통과조는 `API6_1/raceDetailSectionRecord_1`, 코너 통과조는 `API303/corner_rank` 원문을 사용한다.
- 공식 홈페이지 92페이지의 경주 날짜·번호·제주 경마장·해시를 확인했다. 전체 출전표 기준 884행의 말 ID가 API와 일치한다. 마명은 홈페이지의 선행 `★` 표시를 제외하면 모두 같다. 말별 순위 5,304개와 구간·완주시간 7,072개를 대조했다.
- API6 2002·2025·2026년과 API303 2002년을 재조회했다. 원문은 보유한 9월 29일 수집본과 동일한 해시였다. API4는 차이가 확인된 두 경주 날짜를 재조회했고 날짜당 80행·해당 경주당 10행을 확인했다.
- 공식 TXT는 API·홈페이지 대조 후 부족 또는 충돌하는 27경주의 보완 근거로 수집했다. TXT를 경주 원장 입력으로 다시 수입하지 않았다. 원문 27파일과 대상 경주 블록 27개를 보존했다.

근거: [홈페이지 수집 원장](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/website_evidence.json>), [홈페이지 비교 요약](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/website_comparison_summary.json>), [API6·API303 재조회 경로](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/latest_api_retry_pointer.json>), [API4 재조회 경로](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/latest_api4_retry_pointer.json>), [TXT 수집 원장](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/supplemental_rpt_manifest.json>).

## 항목별 결과

| 항목 | 확인 결과 | 현재 처리 |
|---|---|---|
| 기존 순위·통과조 불일치 27경주·105관측 | 6경주·26관측은 API303 지점 대응 차이, 2경주·9관측은 API4와 홈페이지 순위 차이, 19경주·70관측은 공식 화면 자체의 불일치 | 앞의 8경주는 출처 차이를 분류했다. DB 정정 완료를 뜻하지 않는다. 뒤의 19경주는 정답 미확정 |
| 2002년 API6·API303 차이 26지점 | API6는 홈페이지와 26/26 일치, API303의 기존 지점 대응은 0/26 일치 | 연도 전체 칸 교환을 적용하지 않고 경주·지점별 근거 보존 |
| 실제 완주인데 API6 행 없는 6경주 | 최신 API에도 행 없음. 홈페이지 구간시간표와 TXT 상세 구간·누적시간 모두 공란 | 미제공 유지. 다른 말별 기록까지 없다는 뜻은 아님 |
| 말별 구간시간 전체 결측 25행·7경주 | API 7필드 모두 정수 0. 홈페이지 175칸 중 168칸 `0:00.0`, 7칸 공란 | 실제 0초로 사용하지 않음 |
| 말별 통과착순 전체 결측 1행 | 2002-11-09 1R 7번 야망의불꽃, API 6필드 0·홈페이지 경로도 전부 `-` | 결측 유지 |
| 구형 압축 통과조 10지점·6경주 | API6와 홈페이지 원문 모두 일치. 출전 마번은 한 자리지만 숫자 경계·괄호 의미의 공식 정의 미확정 | 원문 보존, 자동 숫자 분할 보류 |
| `·` 포함 통과조 162지점·47경주 | 뒤쪽 166마번 관측은 주행중지 164개·실격 2개와 전부 일치 | 특수결과 부분 분리 보관. 일반 순위로 변환하지 않음 |
| 광해청명 2026-01-17 5R G1F | API·홈페이지·TXT 모두 77.2초 | 기존 사후 분석용 NULL 유지, 정정값 추정 금지 |

25행·1행 결측은 유효 착순·양수 완주시간을 보유한 후보의 집계다. 원문 키 미제공, 필드 0, 홈페이지 공란을 같은 상태로 덮어쓰지 않는다.

## 홈페이지 기준 정정 후보와 TXT 차이

두 경주에서 실제 양수 통과착순 차이 14개를 확인했다. 기존 105개 불일치 관측을 설명하는 9개 외에 전체 출전표 비교로 5개를 더 찾은 것이다.

| 경주 | 지점 | API와 홈페이지가 다른 순위 필드 수 |
|---|---|---:|
| 2025-10-17 제주 7R | S1F 7개·G1F 3개 | 10 |
| 2026-03-06 제주 8R | G1F 4개 | 4 |

최신 API4 재조회에서도 14개 전부 기존 API와 같고 홈페이지와 다르다. 공식 TXT도 이 14개 순위와 어정적기 S1F 77.8초·시긴트 G1F 76초를 그대로 담고 있다. 홈페이지는 각각 17.8초·16초다. TXT 통과조도 두 지점에서 홈페이지와 다르다. 따라서 TXT와 API가 같다는 이유로 홈페이지 값을 되돌리지 않는다. 출처 간 수정 반영 여부 차이는 확인했지만 수정 날짜와 전달 경로는 확인하지 못했다.

최초 감사에서는 DB를 변경하지 않았다. 이후 사용자 승인에 따라 **말별 통과착순 14개를 2026-10-03 홈페이지 값으로 DB에 적용했다.** [실제 적용·독립 검증 보고서](<../20261002_section_order_website_load/README.md>)를 읽는다. TXT에서 다른 통과조 2개는 API6·API303이 이미 홈페이지와 일치하므로 이번 DB 정정 대상이 아니다. 기존 시간 정정 3건과 광해청명 2026-01-17 5R G1F 시간 NULL은 유지했다.

- [14개 순위의 원값·홈페이지 값·말 ID](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/positive_order_website_correction_candidates.json>)
- [TXT와 홈페이지의 전체 비교](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/supplemental_rpt_comparisons.json>), [TXT 검증 요약](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/supplemental_rpt_review.json>)
- API 순위 `99`와 홈페이지 공란인 19관측·5경주는 공식 주행중지 말이다. 실제 99등으로 해석하지 않는다. [특수값 목록](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/special_order_sentinel_observations.json>)

## 정답이 미확정인 19경주

홈페이지와 TXT의 같은 지점에서 말별 순위가 통과조 구성원 수로 계산한 가능한 순위 범위를 벗어나는 70관측·20지점이다. 괄호 안에서 정확한 순위를 복원하지 않는 보수적인 검사다. 어느 필드가 올바른지는 확인하지 못했으므로 경주 전체 삭제 또는 순위 추정 보정을 하지 않는다.

| 연도 | 날짜와 경주 |
|---|---|
| 2016 | 09-23 1R |
| 2017 | 07-08 4R |
| 2020 | 06-25 4R |
| 2021 | 09-03 5R |
| 2022 | 10-28 3R |
| 2023 | 02-11 6R, 03-11 3R, 03-25 2R, 07-21 2R, 12-01 5R, 12-30 5R |
| 2024 | 06-22 5R, 07-26 5R |
| 2025 | 03-29 7R, 04-18 5R, 11-01 5R |
| 2026 | 01-17 5R, 02-06 2R, 08-28 7R |

예를 들어 [2026-08-28 제주 7R 공식 성적](https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet=2&realRcDate=20260828&realRcNo=7)에서 6번 신안으뜸(3108052)의 개별 4C 순위는 1이지만 통과조 `3,(9,1),(4,2),5≡(6,8),7,10`에서는 7~8위 범위다. TXT도 같다. 해당 경주의 800m 누적시간 1:01.2와 직전 구간 9.0초 역시 원문에 존재하므로 내부 합산이 맞는 것과 실제 측정이 정확한 것을 구분한다.

[경주 목록 CSV](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/remaining_race_list.csv>), [70관측 상세](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/remaining_website_internal_order_conflicts.json>), [105관측 전체 판정](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/order_adjudications.json>).

2026-10-03 사용자 요청으로 최신 API4·공식 홈페이지를 재검토했고 충돌은 그대로였다. **후속 DB 품질 조회에서 순위 70개·통과조 20지점을 NULL·보류 상태로 반영했다.** 정답 순위를 복원한 것은 아니다. [현재 보류 반영과 독립 검증](<../20261003_unresolved_section_review/README.md>), `jeju_race_postrace_sections_quality_2026`를 사용한다. 아래 원문 판정·최초 감사 집계는 당시 관측 기록으로 보존한다.

## 2002년 지점 대응과 결측 범위

기존 26지점에 구형 표기 대상 등을 더해 18경주·108지점을 홈페이지와 대조했다. API6는 108/108 일치하고 기존 API303 필드 대응은 78/108 다르다. API303 값이 다른 코너 필드에 존재하는 사례도 있다. API303 원문 자체가 손상됐다고 단정하거나 전 기간에 동일한 칸 교환을 적용하지 않는다. [지점별 비교](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/group_website_comparisons.json>), [원문·표기 상세 보고서](<legacy_review/README.md>).

API6 결측 6경주는 2025-01-10 1R, 05-16 8R, 05-23 3R, 06-27 4R, 07-04 5R, 2026-09-11 5R다. TXT에는 거리 격자와 경주 전체 3F·4F 합계가 있지만 상세 펄롱시간·누적시간은 공란이다. 이 합계로 누락 구간을 복원하지 않는다. API4 말별 기록과 API303 통과조는 별도로 존재한다. [결측·최신 API 상세](<coverage_review/README.md>).

## 표기 해석과 모델 입력 제한

- `·` 앞 일반 통과조만 감사 목적으로 분리하여 홈페이지의 양수 순위 1,450개를 검사했으며 범위 이탈은 0건이었다. 운영 파서 변경이나 모델 입력 채택을 뜻하지 않는다. `·` 뒤 특수결과 마번을 쉼표로 붙여 순위를 늘리지 않는다. [감사용 비교](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/dot_prefix_audit_only.json>).
- S1F보다 작은 2C 시간 666관측은 기존 감사의 지점·거리 계약 미확정 항목으로 유지한다. 표시 열 순서만으로 누적시간 오류를 판단하지 않는다. 이번 92경주 대조가 이 666관측의 측정 정의를 확정한 것은 아니다.
- 경주 전체 구간시간과 개별 말 시간을 혼합하지 않는다. G3F 막판시간을 G3F 통과착순으로 만들지 않는다. 0·공란·99·특수결과를 실제 기록으로 입력하지 않는다.
- 미확정 19경주에 해당하는 충돌 필드를 정확한 순위나 확정된 정렬 라벨로 채택하지 않는다. 원문 보관과 모델 입력 허용은 별도다. 이번 점검은 DB 정정이나 모델 입력 반영을 실행하지 않았다.
- 사후 구간기록을 같은 경주의 사전 예측 피처로 사용하지 않는다. 현재 말 이름·2026년 고정 나이와 공식 말 ID 연결 정책은 기존 계약을 따른다.

## 검증과 다음 작업

GPT-6 Luna xhigh 작업자 3명이 순위, 결측, 과거 표기를 분담했고 root가 공식 원문을 직접 대조하고 판정을 확인했다. [순위 독립 검증](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_passing_audit/order_review/independent_review.json>), [결측 검증](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/coverage_review/coverage_review.json>), [과거 표기 근거](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/legacy_review/evidence/dot_suffix_website_api4_status_summary.json>)를 보존한다. 최종 기계 요약은 [summary.json](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/summary.json>)이다.

홈페이지 기준 순위 14개 정정과 미확정 19경주의 품질 조회 보류 반영은 후속 단계에서 완료했다. 남은 검토 대상은 실제 정답 확정 근거, 확인한 2002년 경주·지점별 대응, 특수결과 비교 모집단과 구형 표기의 입력 계약이다. 광해청명 G1F와 측정 정의 미확정 항목은 보류를 유지하고 확인한 결측을 추정값으로 채우지 않는다.

## 2017년부터 학습하는 경우

[기간별 품질과 학습 영향 검토](<TRAINING_FROM_2017.md>)를 함께 읽는다. 2017년 이후 후보 5,901경주·59,042행 중 유효 완주 후보가 있는 경주는 5,828개다. 내부 충돌 18경주(0.309%)와 API6 누락 6경주는 남으며, 순위 14개는 홈페이지 정정값을 DB에 반영했다. 상세 구간 누락 6경주는 홈페이지 재조회에서도 공란이었다. S1F보다 작은 2C 666관측도 모두 2024~2026년·1300m 자료다. 2017년부터 정답 학습을 시작하는 것과 과거 이력의 조회 하한은 다르다. 문제 필드를 정정·차단한 학습 자료 구성은 가능하나 모델 성능의 허용 오차는 실제 학습·시간순 비교를 실행하기 전 미확정이다.
