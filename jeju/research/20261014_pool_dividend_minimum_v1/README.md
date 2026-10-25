# 제주 실제 당첨배당의 경주별 최저 배당 분류

2026-10-14 사용자 정정에 따라 PLC(연승)·QPL(복연승)은 경주별 실제 당첨 quote 중 **최솟값**으로 분류했다. 나머지 다섯 승식은 경주당 quote 하나여서 이전 분류가 그대로 유지된다. 구간은 저 `<5배`, 중 `5≤배당<20배`, 고 `≥20배`다. 이 결과는 실제 당첨배당의 기술 빈도이며 사전 확률·수익률·베팅 기준이 아니다.

원천은 `jeju/research/20261014_pool_dividend_frequency_v1/winning_quotes.csv`의 13,560개 동결 quote다. 입력 파일, 기존 `race_pool_summary.csv`, 원천 `SOURCE_HASHES.json`, `ROOT_FINAL_REVIEW.json`의 SHA-256은 `SOURCE_HASHES.json`에 기록했다. 원천 최종 독립 검토 해시는 `2d254793bbe5d0b919dfd4f408e3e1380f824cac148a30333deff2da773495c8`이고 당첨 quote 파일 해시는 `6a208e23ebe175ea20f7a9bfcc86f24245e5dfc675eba0cec22be93eb1dcdca4`다.

`race_classification.csv`에는 경주×승식별 원 quote 수, 최솟값·최댓값, 구 max 기준과 새 min 기준이 있다. `summary.csv`는 전체·2025·2026의 경주 수와 분류 비율을, `oldmax_to_newmin_crosswalk.csv`는 이전 max 분류에서 새 min 분류로 이동한 경주 수를 제공한다. 전체/2025/2026 경주 분모는 각각 1,237/707/530이다.

재현: 프로젝트 루트에서 `.venv/bin/python -B jeju/research/20261014_pool_dividend_minimum_v1/analyze_minimum.py`. 스크립트는 동결 파일 해시와 입력 표의 완전성을 확인하고 새 연구 폴더에만 결과를 쓴다. DB나 네트워크를 열지 않는다. 출력 SHA-256은 `SOURCE_HASHES.json`에 기록하며, 그 파일 자체의 해시는 자기참조를 피하기 위해 목록에서 제외한다. 이 후속 계산은 기존 연구·원천·중앙 결론 등록부를 수정하지 않는다.
