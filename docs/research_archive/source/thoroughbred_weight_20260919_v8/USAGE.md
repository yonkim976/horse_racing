# 읽기 및 재현

- 최종 결론 `REPORT.md`, 선택근거 `selection.json`, 전체 성능 `comparison.csv`, 원본 경주별 지표 `race_metrics.parquet`.
- 예상표 `UPCOMING_PREDICTIONS.md`, 기계판독 출력 `future_predictions_20260919_20/`.
- 체중 정의 `features.py`, 사전 계획 및 고정해시 `PROTOCOL.md` / `protocol_lock.json`.
- `prepare.py`는 기존 v2 보정속도 계산의 사본에 관측값 출력만 추가한다. 출력계산 패치 `speed_observation_only.patch`. 원본을 수정하지 않는다.
- 새 연구 디렉터리에 코드를 복사해 prepare → pytest → 고정해시 생성 → run_study → verify → summarize → infer → report 순서로 재현한다. 이미 봉인된 디렉터리에서 출력 생성기를 재실행하지 않는다.
- 현재 디렉터리 읽기 전용 검사: `.venv/bin/python data/research/thoroughbred_weight_20260919_v8/integrity.py verify`.
- 과거 체중은 당일 체중이 아니다. 현재 체중이 발표됐다는 가정으로 결측값을 채우지 않는다.
- A 후보는 반기, B/C 후보는 연간(H1 모델)으로 비교한다. 내부 착순은 기존 v2 연간 모델 고정. 개발 선택은2021~2024만, 참고2025~2026은 기존에 노출된 기간이다.
