# KRA 질병 용어 조사 문서·산출물 등록부 · 2026-10-01

이 등록부는 질병 설명 대조 작업의 문서를 최신 보고서, 재현용 중간 증거, 역사적 스냅샷, 정리 후보로 나눈다. 이 점검에서 기존 연구 파일은 삭제하지 않았다.

## 최신 기준 문서

| 문서 | 역할 | 현재 상태 |
|---|---|---|
| [질병 용어·설명 대조 현황](KRA_DISEASE_GLOSSARY_COVERAGE_2026-09-30.md) | 상위 DB 담당자에게 넘길 현재 요약. 표제 판정과 설명 확보량을 분리 | 현재 기준 문서. API33 수집, 완전 중복 12행 처리, 사용자 판정, 설명 추가 수집분을 반영 |
| [2026-10-01 프로필 설명 추가 수집 보고서](../data/research/kra_disease_glossary_api33_20260930/profile_hover_expansion_20261001/coverage_report_20261001.md) | 실제 수집 설명과 업데이트된 설명 커버리지 | 현재 설명 분류의 기준. 10마리 프로필 288행에서 38개 조합, 신규 설명 34개. 사용 빈도는 최신 DB 스냅샷 반영 |
| [최신 진료 DB 재대조 보고서](../data/research/kra_disease_glossary_api33_20260930/profile_hover_expansion_20261001/db_refresh_comparison_20261001.md) | 최신 진료일, 빈도 갱신, 로컬·Supabase 동일성 | 2026-09-30까지 대조. 고유 문구 추가 없음, 기존 117개 빈도 +1,172건. 전체 이력 277개월 내용 해시 일치 |
| [API 사용 인벤토리](KRA_API_USAGE_INVENTORY_2026-09-30.md) | 프로젝트가 신청·조회한 KRA API와 실제 제공 데이터 구분 | API33의 `illDesc`가 전부 `-`라는 제한을 반영 |
| [데이터 원천 카탈로그](DATA_SOURCE_CATALOG.md) | 등록된 원천과 사용 목적 | API33을 표제 대조용으로, 설명은 KRA 웹 출처 별도 확인 대상으로 표시 |

## 보존할 원본·중간 증거

이 파일들은 최종 결론을 재현하거나 출처를 감사하는 근거다. 중간 산출물이라는 이유로 삭제하지 않는다.

| 파일/폴더 | 보존 이유 |
|---|---|
| `data/research/kra_disease_glossary_api33_20260930/api33_glossary.json`, `raw/api33_page_*.xml`, `manifest.json` | API33 원응답, 페이지별 `totalCount`/건수/응답 코드/원문 해시. 12개 완전 중복도 원본에는 유지 |
| `api33_glossary_deduplicated_exact.json`, `exact_duplicate_rows_removed.csv`, `deduplicate_exact_rows.py`, `exact_deduplication_report.md` | 완전 동일 12행만 뺀 파생 사전과 재현·감사 근거. 영문명이 다른 같은 한글명 행은 보존 |
| `data/research/kra_disease_glossary_20260930/raw/`, `glossary.json`, `web_vs_api33.csv` | KRA 질병용어 웹 50개 항목 원문, 추출 설명, API33 비교 |
| `profile_hover_review_20260930/`, `final_review_20260930/phrase_recheck_20261001/` | 이전 KRA 프로필 확인, 사용자 직접 확인, 대표 원문·날짜 대조와 판정 기록 |
| `api16_recheck_20260930/`, `dacom72_recheck_20260930/`, `final_review_20260930/*source_check*/` | API16/RPT 원문 검증과 행·원문 해시 |
| `manual_review_decisions_20260930.csv`, `manual_review_body_laterality_20260930.md`, `composite_review_20260930/` | 사용자가 승인한 용어 대응 규칙과 복합 구성요소 검토 이력 |
| `profile_hover_expansion_20261001/` 전체 | 38개 표제·영문명·설명 조합의 원문, 출처/시각/해시, 최신 DB 빈도 스냅샷, 갱신된 검토 CSV와 재현 스크립트. 프로필 전체 확인 288행과 선택 표제 관측 136건을 구분 |

## 이전 보고서: 남겨두되 현재 집계에는 사용하지 않는 스냅샷

| 파일 | 상태 | 조치 |
|---|---|---|
| `data/research/kra_disease_glossary_api33_20260930/coverage_report.md` | API33 연결/최종 표제 adjudication 이전 초기 수집 보고서. 당시 API33 인증 오류와 50건 웹 용어집 기준 | 삭제하지 않고 초기 조사 이력으로 보존. 현재 숫자를 인용할 때는 상위 현황 문서와 추가 수집 보고서를 사용 |
| `profile_hover_review_20260930/coverage_report.md` | 미확정 32개 검토 시점의 행 단위 기록. 이후 사용자 지시와 최종 대조로 보류 상태가 닫힘 | 과거 조사 근거로 보존. “32개 미확정”을 현재 상태로 읽지 않음 |
| `final_review_20260930/coverage_report.md` | 2026-10-01 프로필 추가 수집 전 설명 커버리지(443/1,518/3,431)와 최신 표제 판정 | 표제 판정 이력에는 유효하나 설명 숫자는 새 보고서로 대체 |
| `manual_review_held_terms_20260930.md` | 사용자가 용어·설명을 직접 확인하기 전의 보류 3건 메모 | 현재 보류 목록이 아니다. 확인 당시 기록으로만 보존 |
| `description_collection_plan_20261001.md` | 추가 수집 전 조사 경로 설계 | 실제 프로필 수집이 시작됐으므로 본문의 상태 안내를 현황에 맞게 갱신. 절차와 공식 출처는 계속 참고 |

## 삭제 판단

- **이번 정리에서 삭제 후보 파일은 확인하지 않았다.** 오래된 문서 중 일부 숫자와 보류 상태는 현재와 다르지만, 원문 해시·사용자 판정·검색 한계가 포함돼 감사 가치가 있다. 위처럼 스냅샷 또는 역사적 메모로 표시하고 최신 현황에서 분리한다.
- API16 날짜별 재조회 `raw/`에 바이트가 동일한 0건 응답 파일 5개가 있지만, 각각 다른 meet·진료일 요청의 근거다. 매니페스트가 해당 경로를 가리키고 재현 스크립트도 날짜별 파일을 요구하므로 중복 보존한다.
- “12개 제거”는 API33 **파생 사전**에서 동일한 `illName+illEngName+illDesc` 중복행을 제외한 뜻이다. 원본 JSON/XML이나 제거 내역 CSV의 12행은 삭제하지 않았다. 한글명이 같더라도 영문명이 다른 나머지 행은 그대로 남겼다.
- 다른 주제의 프로젝트 문서나 코드 정리는 이 등록부의 범위 밖이며 변경하지 않았다.

## 요청 기준으로 나눈 현재 파일 정리

| 구분 | 파일/폴더 | 조치 |
|---|---|---|
| 지금까지의 결론을 모은 최신 문서 | `docs/KRA_DISEASE_GLOSSARY_COVERAGE_2026-09-30.md` | 상위 인수인계 요약으로 유지. 2026-10-01 설명 수집 결과와 최신 집계를 반영 |
| 최신 상세 보고·계속 갱신할 연구 자료 | `profile_hover_expansion_20261001/coverage_report_20261001.md`, 원문 CSV 2개, `source_manifest.json`, `full_term_review_20261001.csv`, `apply_profile_expansion.py` | 원문·출처·시각·해시·재현 절차이므로 보존. 문구별 보고는 생성 CSV를 기준으로 함 |
| 계속 참고할 수집 계획 | `description_collection_plan_20261001.md` | 실행 현황과 수치를 최신 결과에 맞춰 갱신. 수집 순서·검증 기준은 유지 |
| 중간 산출물·과거 시점 스냅샷 | 이 등록부의 “이전 보고서” 및 `data/research/kra_disease_glossary_api33_20260930/` 안의 이전 점검 폴더 | 현재 수치로 덮어쓰지 않고 당시 근거로 보존. 최신 여부가 혼동되지 않도록 이 등록부에서 구분 |
| 삭제해도 되는 파일 | 현재 확인된 안전한 파일 후보 없음 | 이번 요청에서도 삭제할 파일이 없어 파일 삭제는 하지 않음. 원문, 해시, 사용자 판정 또는 절차 재현 근거가 있는 스냅샷은 보존 |

현재 통합 수치는 5,397개 고유 문구·677,219건 중 모든 구성 설명 확보 1,141개·531,777건, 일부 확보 1,812개·5,592건, 표제는 있으나 설명 미확보 2,439개·139,805건, 제외/비대상 5개·45건이다. 로컬 SQLite 읽기 전용 스냅샷과 Supabase `SELECT` 비교로 확인했으며 운영 DB와 Supabase에는 쓰지 않았다.

## 계속 갱신할 때

새 프로필 설명을 얻으면 먼저 `profile_hover_expansion_YYYYMMDD/`에 표제·영문명·설명 원문, 말 마번·meet·날짜·출처·시각·해시를 저장한다. 다음으로 갱신 검토표와 추가 수집 보고서를 다시 만든다. 최종 표제 판정, 사용자 제공 설명, KRA 공식 설명의 출처를 서로 혼합하지 않는다. 현재 종합 숫자는 상위 현황 문서를 기준으로 하고, 과거 스냅샷은 당시 상태로 보존한다.
