# 실행과 재현

프로젝트 루트 `/Users/kimyongjin/Desktop/horse_racing`에서 `.venv/bin/python`을 사용합니다. v5와 같은 numpy/pandas/scipy/LightGBM/DuckDB/pyarrow 환경입니다.

이 폴더의 학습 순서는 `run_study.py` → `verify.py` → `summarize.py` → `infer.py`입니다. 기존 모델/선택 파일이 있으면 학습기가 덮어쓰기를 거부합니다. 다시 학습하려면 같은 `data/research` 아래 새로운 형제 폴더에 `.py` 파일과 `PROTOCOL.md`, `protocol_lock.json`만 복사하고 실행합니다. `_initial` 파일은 무효 초기 분할의 보존본이므로 실행하지 않습니다. source hash 경로를 해석하려면 작업 디렉터리를 프로젝트 루트로 유지합니다. v2/v3/v4/v5 원천 의존성은 그대로 보존해야 합니다.

```sh
.venv/bin/python -m pytest -q data/research/thoroughbred_boundary_20260918_v6/test_core.py
.venv/bin/python data/research/thoroughbred_boundary_20260918_v6/integrity.py verify
```

`verify.py`와 `summarize.py`는 검증·집계 파일을 쓰므로 봉인 후 원본 폴더에서 재실행하지 않습니다. `integrity.py verify`는 읽기 전용입니다. 새 재현 폴더에서는 기록을 다시 생성해 수치를 대조할 수 있습니다. 시간·경로가 포함된 메타데이터는 바이트 단위로 같지 않을 수 있습니다.

이번 최종 선택은 모두 `current_*`입니다. A는 v5 `rolling_all` 2026H2, B/C는 v4 `top3_growth_strength` 2026 묶음을 사용합니다. 미래 입력은 v3 출마표와 v4의 6개 사전 변수를 키로 결합합니다. 새 자료 수집이나 당일 결과 입력을 하지 않습니다. 이 추론기는 보존된 9월 19·20일 출마표 전용이며 새로운 날짜에는 별도 시점 안전한 피처 준비가 필요합니다.
