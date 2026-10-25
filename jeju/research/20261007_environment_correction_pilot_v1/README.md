# 제주 환경 보정 파일럿 v1

2026-10-07. **원기록 R0 유지. 함수율·월·번호 선택률은 모두0%.** 환경의 조정 관찰 차이는 있지만 Top3 예측 개선 기준은 통과하지 못했다. DB·HY_R_FORM·등록부·더러브렛 자산은 보존했다.

- [핵심 결과표와 해석](RESULTS.md)
- [학습 전 고정한 연구 계약](RESEARCH_CONTRACT.md)
- [원천·집계 재확인](audit/summary.json)
- [시간순 적용률 선택](comparison_01/selection_locked_before_evaluation.json)
- [최종 판단](comparison_01/decision.json)
- [계산·누수·원천 보존 검증](verification_02/verification.json)
- [함수율·월 관찰 그림](report_01/environment_effects.png)

새 결과만 이 폴더 아래 보존했다. 2019~2026은 후향 개발자료이며 독립 미래 검증이나 운영 적용 완료가 아니다. 효과 추정값과 실제 적용초/NULL 지원 상태를 구분한다.

재현 환경은 프로젝트 `.venv`의 Python3.12이며 numpy2.5.2/pandas3.0.5/scipy1.18.1/sklearn1.9.0을 사용했다. 분석 실행에는 `--output analysis_02`를 명시한다. compare 기본 입력 `analysis_02`/출력 `comparison_01`, verify `verification_02`다. 각 산출물 폴더가 없는 새 연구 복사본에서만 실행한다. 출력 폴더가 있으면 덮어쓰지 않고 중단한다. 단일 실행 예시는 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -u jeju/research/새연구폴더/analyze.py --output analysis_02`다. `modeling.py` 등은 동일 새 폴더에서 자동 참조한다. 원천 감사와 계약 해시는 재현 전에 확인한다.
