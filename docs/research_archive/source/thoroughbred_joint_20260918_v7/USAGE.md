# v7 재현 및 검증

작업 디렉터리는 `/Users/kimyongjin/Desktop/horse_racing`이고 Python은 `.venv/bin/python`입니다. 패키지 환경은 동봉 `environment.json`과 같습니다. 새 자료 수집은 필요 없습니다.

학습과 평가 순서는 `run_study.py` → `verify.py` → `summarize.py` → `confidence_audit.py`입니다. `models` 또는 `selection.json`이 이미 있으면 학습기가 덮어쓰기를 거부합니다. 재학습하려면 같은 `data/research` 아래 새 형제 폴더에 `.py` 파일, `PROTOCOL.md`, `protocol_lock.json`을 복사하고 그곳의 스크립트를 실행합니다. v2/v3/v4/v5와 확률 진단에 사용하는 v6 원천 의존성은 그대로 보존합니다. 프로토콜 해시와 경로 검사를 위해 프로젝트 루트에서 실행합니다.

```sh
.venv/bin/python -m pytest -q data/research/thoroughbred_joint_20260918_v7/test_objective.py
.venv/bin/python data/research/thoroughbred_joint_20260918_v7/integrity.py verify
```

`integrity.py verify`는 읽기 전용입니다. 나머지 검증·집계기는 결과 파일을 쓰므로 봉인된 원본에서 재실행하지 말고 새 재현 폴더에서 사용합니다. 값은 같아야 하지만 생성 시각이나 경로를 포함한 메타데이터는 바이트 단위로 다를 수 있습니다.

학습된 후보는 `models/<year>/direct_joint110`에 있습니다. `metadata.json`에는 FIT 행/경주 수·기간·범주 사전·변수·선택한 회수·목표별 보정 온도가 있습니다. 추론은 기존 `targets_core.load_bundle`, `raw_scores`, `top3_set_joint`와 호환됩니다. C 내부 순서는 해당 연도의 v2 H3_relative 점수와 기존 개최지별 온도를 사용합니다. 미등록 개최지 우승 온도는 1.0입니다.

후보가 채택되지 않았으므로 새 후보의 미래 예상으로 기존 표를 바꾸지 않았습니다. 현재 예상표는 v6의 `UPCOMING_PREDICTIONS.md`이며 모든 확률·최고 선택이 v5와 같습니다. 신규 경주의 피처 생성이나 운영 배포를 수행하는 코드는 이번 범위에 포함하지 않습니다.
