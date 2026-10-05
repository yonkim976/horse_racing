# 제주 구간 순위·통과조 공식 페이지 재조회

2026-10-03에 기존 미해결 19경주의 KRA 공식 경주성적 상세페이지를 HTTPS로 다시 조회했다. 응답 본문 원바이트와 EUC-KR 인코딩을 보존했다. 19페이지 모두 HTTP 200이며 날짜·경주번호·제주 식별이 확인됐다.

## 결과

- 페이지 원문 SHA-256은 2026-10-02 보관본 19개와 모두 같다. 출전마별 표시 순위, 6지점 순위 경로, 통과조도 기존 페이지와 바뀐 항목이 없다.
- 전체 184개 출전마의 공식 말 ID와 S1F·1C·2C·3C·4C·G1F 순위 경로를 보존했다. 충돌 70관측은 모두 공식 말 ID가 기존 대상과 일치하고, 최신 개별 순위도 기존 페이지 값과 같다.
- 괄호 묶음 안의 순서를 복원하지 않는 보수적 범위 검사를 다시 적용했다. 70개 관측·20개 지점·19경주 전부에서 개별 순위가 같은 페이지 통과조의 가능한 순위 범위 밖에 남는다. 누락 또는 파싱 실패는 0건이다.
- 같은 날의 API4 공식 재조회에서도 19일자·70개 순위 값은 바뀌지 않았다. 부모 검증 원장은 [독립 대조](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/root_fresh_evidence_check.json>), API4 원문 원장은 [API4 재조회 manifest](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/api4_recheck/20261002T155808.237358Z/manifest.json>)다.
- 19페이지 중 17페이지에 심판 설명이 있고, 2016-09-23 1R과 2017-07-08 4R 페이지에는 Report 본문이 없다. 확인한 설명에서 구간기록 정정, 계측 이상, 통과순위·통과조 표기 정정 근거는 찾지 못했다.
- 2023-03-11 3R에는 결승선 직전 방해를 심의한 뒤 도착순위대로 확정했다는 설명이 있다. 이는 결승선 도착 순위 판정이며 구간별 통과순위·통과조 판정은 아니다. 2025-11-01 5R의 추가심판사항은 기승 전개와 처분에 관한 설명이다. 2023-07-21 2R의 1:13.6 기록은 주행심사 사유로 언급됐고 계측 이상이나 기록 정정은 기재되지 않았다.
- 이 홈페이지 재조회 작업자는 DB를 변경하지 않았다. 이후 root가 진행한 실제 DB 보류 반영은 [상위 적용·검증 보고서](<../README.md>)를 따른다. 통과조 원문과 개별 순위를 다수결로 판정하지 않았고 괄호 안의 정확한 순위도 추정하지 않았다.

## 산출물

| 파일 | 내용 |
|---|---|
| [`raw_pages/`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/official_recheck/raw_pages>) | KRA가 응답한 19개 원문 HTML 바이트. 응답 `Content-Encoding`은 없고 문자셋은 EUC-KR이다. |
| [`manifest.json`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/official_recheck/manifest.json>) | 기존 `website_evidence` 핵심 필드와 HTTP 상태·SHA·전체 표·출전마 ID·6지점 경로·통과조·심판 설명 전문 및 전일 페이지 비교. |
| [`flagged_observations_recheck.json`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/official_recheck/flagged_observations_recheck.json>) | 70관측별 최신 개별 순위와 통과조 원문, 말 ID, 가능한 순위 범위, 재검산 결과. |
| [`official_report_review.json`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/official_recheck/official_report_review.json>) | 19개 페이지의 심판 설명 전문과 키워드 검토용 행. |
| [`race_report_assessment.json`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/official_recheck/race_report_assessment.json>) | 심판 설명의 경주별 수동 판정. |
| [`summary.json`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/official_recheck/summary.json>) | 경주·관측·변경 여부 집계. |
| [`collect_recheck.py`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/official_recheck/collect_recheck.py>) | 지정 경주 페이지의 읽기 전용 HTTPS 수집기. 원문 파일은 전용 새 폴더에만 배타 생성한다. |
| [`rebuild_manifest.py`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/official_recheck/rebuild_manifest.py>) | 보존 원문에서 표·말 ID·6지점 경로·통과조·심판 설명을 추출하고 충돌 범위를 재계산한다. |

`official_pages_manifest.json`은 최초 다운로드 단계의 임시 수집 원장이다. 최종 대조와 올바른 다열 통과조 추출에는 `manifest.json`을 사용한다.

## 기준 자료

대상 70관측과 종전 범위 판정은 [2026-10-02 검토 보고서](<../../20261002_section_remaining_review/README.md>) 및 [충돌 관측 목록](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/remaining_website_internal_order_conflicts.json>)에 있다. 과거 보관 페이지 원문은 해당 검토 폴더의 `website_html/`에서 참조했다.
