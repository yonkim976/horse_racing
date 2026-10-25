# 제주 2026-10-09 산출물 ledger

새로 만든 작업 폴더와 기존 제주1 결과를 분리해 셌습니다. 기본 산출물 합계에는 ledger 두 파일을 제외하고, ledger 자체의 실제 크기를 별도로 더한 포함 합계도 함께 기록했습니다. `__pycache__`의 `.pyc`도 실제 파일 수와 byte에 포함했습니다.

| 범위 | 파일 수 | 크기(bytes) |
|---|---:|---:|
| 새 작업 폴더(ledger 제외) | 161 | 15,669,836 |
| ledger JSON | 1 | 2,681 |
| ledger Markdown | 1 | 1,496 |
| 새 작업 폴더(ledger 포함) | 163 | 15,674,013 |
| 기존 제주1 폴더 | 48 | 1,605,022 |
| 새 작업 폴더 + 기존 제주1 | 211 | 17,279,035 |

Python 소스는 5개입니다: `derive_model_probabilities.py`, `derive_race_explanations.py`, `freeze_manual_inputs.py`, `generate_reports.py`, `refresh_card_notices.py`.

모델 실행은 등록 모델 inference 1회이며, 학습·모델 수정 0회입니다. 저장된 inference의 확률 파생 1회와 말별 설명 분리 1회는 후처리입니다. native validator 1회 통과, DB/Supabase 쓰기 0회, 외부 웹 발행 0회입니다. 최신 공식 출전·게이트·변경 공지는 읽기 전용으로 재확인했고 변동은 없었습니다.

검증: 수기 고정 원본 hash 불일치 0건, HTML 로컬 링크 누락 0건, 외부 script 0개, `innerHTML` 0건, Chrome desktop/mobile viewport 수평 넘침 0건. QA 캡처는 `qa/` 아래 index와 R2의 데스크톱·모바일 4장입니다.
