# 제주 pair 확신 구간별 QNL/QPL 실현 수익

확신값 구간마다 고정 `jockey_id_candidate` 선택쌍의 복승(QNL) 및 복연(QPL) 적중·환급·ROI를 비교한다. 전체 해석과 결과표는 [publication/REPORT.md](publication/REPORT.md), 고정 경계는 [PLAN.md](PLAN.md)를 본다.

재현은 저장소 루트에서 `.venv/bin/python -B jeju/research/20261013_pair_confidence_returns_v1/analyze.py`를 실행한다. 결과 CSV와 입력 SHA-256은 같은 폴더에 저장한다. 저장된 2024–2026 날짜 bootstrap schedule만 읽고, SQLite·네트워크·학습은 사용하지 않았다.
