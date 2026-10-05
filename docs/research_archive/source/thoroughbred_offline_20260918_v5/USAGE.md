# v5 결과 사용 및 재현

작업 디렉터리는 `/Users/kimyongjin/Desktop/horse_racing`이고 Python은 `.venv/bin/python`입니다. 원천을 다시 수집하거나 운영 DB에 쓰지 않습니다. `REPORT.md`, `selection.json`, `comparison.csv` 순서로 확인하면 채택 결과와 수치를 볼 수 있습니다.

실행 환경 버전은 `environment.json`에 있습니다. pandas 저장에는 `pyarrow==25.0.1`이 필요하며 이번 실행에서 프로젝트 가상환경에 설치했습니다.

## 기존 결과 검증

```sh
.venv/bin/python data/research/thoroughbred_offline_20260918_v5/integrity.py verify
.venv/bin/python -m pytest -q data/research/thoroughbred_offline_20260918_v5/test_selection.py data/research/thoroughbred_offline_20260918_v5/set_interaction/code/test_set_interaction.py data/research/thoroughbred_offline_20260918_v5/conditional_order/code/test_conditional_core.py data/research/thoroughbred_offline_20260918_v5/conditional_order/code/test_optimized_core.py
```

무결성 검증은 읽기 전용이고 Python/pytest 캐시는 manifest에서 제외합니다. `verify_set.py`, `verify_order.py`, `verify_windows.py`는 새 검증 JSON을 쓰므로 봉인한 폴더에서는 다시 실행하지 말고 아래의 새 재현 폴더에서 사용합니다.

## 전체 재학습

원본 폴더를 삭제하거나 덮어쓰지 않습니다. 동일한 `data/research` 아래 새 폴더에 코드와 계약만 복사한 뒤 실행합니다. 스크립트는 저장 위치를 기준으로 출력 경로를 정합니다. v2/v3/v4 원천과 모델은 읽기 전용 의존성이므로 보존해야 합니다.

```python
from pathlib import Path
import shutil
source = Path('data/research/thoroughbred_offline_20260918_v5')
dest = source.with_name('thoroughbred_offline_20260918_v5_reproduction')
dest.mkdir(exist_ok=False)
contracts = {'PROTOCOL.md', 'PROTOCOL_FROZEN.md', 'protocol.json',
             'protocol_lock.json', 'protocol_frozen.json', 'pre_result_amendment.json'}
for p in source.rglob('*'):
    if not p.is_file() or '__pycache__' in p.parts:
        continue
    if p.suffix == '.py' or p.name in contracts:
        target = dest / p.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
```

위 Python 코드를 프로젝트 루트에서 실행한 다음 새 폴더의 스크립트를 다음 순서로 실행합니다.

```sh
.venv/bin/python data/research/thoroughbred_offline_20260918_v5_reproduction/prepare_baselines.py
.venv/bin/python data/research/thoroughbred_offline_20260918_v5_reproduction/windows/run_windows.py
.venv/bin/python data/research/thoroughbred_offline_20260918_v5_reproduction/set_interaction/code/run_experiment.py
.venv/bin/python data/research/thoroughbred_offline_20260918_v5_reproduction/conditional_order/code/run_conditional_order.py
.venv/bin/python data/research/thoroughbred_offline_20260918_v5_reproduction/verify_set.py
.venv/bin/python data/research/thoroughbred_offline_20260918_v5_reproduction/verify_order.py
.venv/bin/python data/research/thoroughbred_offline_20260918_v5_reproduction/verify_windows.py
.venv/bin/python data/research/thoroughbred_offline_20260918_v5_reproduction/aggregate_study.py
.venv/bin/python data/research/thoroughbred_offline_20260918_v5_reproduction/diagnostics.py
.venv/bin/python data/research/thoroughbred_offline_20260918_v5_reproduction/infer_selected.py
```

학습은 상당한 시간이 걸립니다. 결과가 있는 폴더에서는 학습/통합 실행기가 덮어쓰기를 거부합니다. 새로 얻은 수치는 `comparison.csv`와 `selection.json`으로 대조하며, 생성 시각·경로가 포함된 메타데이터는 원본과 바이트 단위로 같지 않을 수 있습니다. 최종 보고서 작성은 무결성·단위검사 기록까지 확보한 원본에서 수행했으므로 위 재현 절차의 필수 단계가 아닙니다.

이번 원래 기간 프로세스는 48개 모델을 저장했으나 평가표 저장을 완료하지 못했습니다. `windows/recover_evaluation.py`로 저장 모델의 평가만 재생해 복구했습니다. 이 복구기는 48개 모델이 모두 존재하고 결과 파일이 없는 경우에만 실행되며 학습이나 보정을 다시 하지 않습니다. 정상적으로 완료된 재현 실행에는 사용할 필요가 없습니다.

## 추론과 평가 파일

`selection.json`의 `by_target`이 최종 연구 결정입니다. 기간 후보가 선택되면 `windows/models/2026H2/<candidate>`를 사용합니다. 유지한 A는 v3 `top3_allcore`, B/C는 v4 `top3_growth_strength`입니다. 순서 계산에는 v2 `H3_relative` 점수를 사용합니다.

`infer_selected.py`는 선택이 바뀐 경우에만 보존된 9월 19·20일 출마표를 새 폴더에 출력합니다. 유지한 목표의 확률은 이전 예상표와 대조합니다. 출마표는 27경주 전체 294두를 보존해야 하며 말 ID 문자열을 숫자로 바꾸면 안 됩니다. 이 스크립트는 새로운 날짜의 이력 피처를 생성하는 범용 운영 파이프라인이 아닙니다. 새 출마표는 별도의 시점 안전한 피처 준비와 완전성 검증이 먼저 필요합니다.

A/B/C 확률은 각각의 목표에 맞춰 보정되어 서로 다른 공동분포에서 나옵니다. A의 말별 확률을 단순 곱해 B/C 확률로 사용하지 않습니다. 한 공동분포 안에서는 A 합 3, B/C 합 1, C→B→A 주변화가 맞도록 검증했습니다. 실제 3위 경계 동착에서는 슬롯 확률과 공식 입상 사건 확률이 다를 수 있습니다.

기간 후보의 역사 결과는 `windows/race_metrics.parquet`, 확률 최고값은 같은 파일의 `top_probability`, B/C 상위 K 조합 적중은 `windows/BC_topk_race.parquet`에 있습니다. 모든 말의 역사 A 확률·B/C 상위 조합 ID를 중복 저장하지 않았으며, 저장 모델과 고정 원천으로 다시 계산할 수 있습니다. `annual_metrics_primary.csv`와 `halfyear_metrics_primary.csv`가 A 경계 동착을 제외한 일차 집계입니다. 접미사가 없는 기간 분담 집계는 원래의 경계 동착 포함 진단 자료입니다.

`conditional_order/code/*_initial.py`는 무효 초기 구현의 보존본입니다. 실행에 사용하지 않습니다. 수정 내역과 선택 동결 시점에 관한 정확한 범위는 `REVISIONS.md`와 `REPORT.md`를 참고합니다.
