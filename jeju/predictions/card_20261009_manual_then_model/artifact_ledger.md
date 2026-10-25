# 제주 2026-10-09 산출물 ledger

최종 승식 조합 안내를 추가했습니다. 기존 등록모델의 저장된 공동분포만 사용했으며 새 모델 추론·DB 쓰기·웹 발행은 없습니다.

| 범위 | 파일 수 | 크기(bytes) |
|---|---:|---:|
| 최종 judgment 개정 전 기준 | 163 | 15,674,013 |
| 현재 작업 폴더(기존 root ledger pair 제외) | 197 | 20,216,511 |
| 현재 작업 폴더(모든 ledger 포함) | 199 | 20,225,188 |
| final_judgment_v1 하위(자체 ledger 제외) | 34 | 4,393,448 |
| final_judgment_v1 하위(자체 ledger 포함) | 36 | 4,398,471 |
| 기존 제주1 폴더 | 48 | 1,605,022 |
| 현재 작업 폴더 + 기존 제주1 | 247 | 21,830,210 |

개정 하위 신규 36개 파일에는 백업 사본 11개, 조합 catalog 7개, 최종 판단 JSON 7개, QA 캡처 4장 등이 포함됩니다. 최종 HTML 8개는 기존 작업 폴더 위치에서 갱신했습니다. 기존 백업 manifest에 명시된 파일 11개(generator 1, HTML 8, 기존 ledger 2)를 백업 후 갱신했습니다.

새 소스는 2개(`final_judgment_v1/build_combination_catalogs.py`, `final_judgment_v1/capture_final_judgment_qa.cjs`)이며 `generate_reports.py` 기존 소스 1개를 수정했습니다. 비교용 백업 Python 사본 1개도 실제 파일 수·용량에 포함했습니다. 새 revision 하위 `__pycache__`는 0개입니다.

모델 추론은 카드 전체 기준 1회였고 이번 개정의 추가 추론 0회입니다. 학습·모델 변경 0회, DB/Supabase 쓰기 0회, 웹 발행 0회입니다. 조합 확률은 저장된 `joint_outcomes`에서 계산했습니다.

검증: 수기 고정 원본 40개 해시 일치, 판단 근거와 모델확률 catalog 원천 해시 불일치 0건, 8개 HTML 로컬 링크 376개 점검·누락 0건, 외부 script 0개, `innerHTML` 0건, viewport 넘침 0건입니다. QA 캡처는 390×844 모바일 및 1440×1100 데스크톱에서 index와 R2 대표 상세를 CDP로 생성했습니다.

ledger 실제 크기: root JSON 6,577B, root Markdown 2,100B, revision JSON 2,927B, revision Markdown 2,096B.
