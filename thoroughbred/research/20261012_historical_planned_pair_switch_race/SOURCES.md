# 출처와 재실행

[50A의 출전별 분류](../20261012_planned_jockey_changes_by_stable/outputs/classified_starts.parquet)159,014행을 불변 참조한다. 예정/실제 기수와 카드·공지 원문 위치는 [50A출처](../20261012_planned_jockey_changes_by_stable/SOURCES.md)와 [원시독립검증](../20261012_planned_jockey_changes_by_stable/outputs/verification.json)을 따른다.2018은 이력과 연간 기수지원 참고기간이고 주분석은2019~2025년이다.2026부분기간은 제외했다. 새 원본 수집/DB 접근 없음. 최초 카드 게시본의 불변성은 인증하지 못했다.

[입력명세](outputs/source_audit.json)는 입력5파일의 경로·크기·SHA-256과 현재 한경주 목표를 담는다. 연구50 controls/demean/bh를 순수함수로 재사용하고 기존 main은 실행하지 않았다. 이전50B의 [지원표](../20261012_planned_trainer_jockey_pair_effects/outputs/pair_support.csv)37조합을 전수 재검토했다. [사전계획](PLAN.md)의 출전/말/경주 지원기준을 동일하게 적용하고213명단을 민감도에도 고정했다.

[변경이벤트](outputs/switch_race_events.parquet)는 현재행키·직전행키·현재결과와 출처만 보관한다. 다음 출전이나 이후 평균결과는 생성하지 않았다. 다만 사후 말 고정효과의 추정에는 분석기간 전체 관측을 쓰므로 능력통제까지 경주 이전 정보만 쓴 예측검증이라고 해석하지 않는다. 원시율과 보정차의 비교기준도 다르다.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261012_historical_planned_pair_switch_race/analyze.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261012_historical_planned_pair_switch_race/verify.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261012_historical_planned_pair_switch_race/verify_recent.py
MPLCONFIGDIR=/private/tmp/horse_historical_pair_mpl PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261012_historical_planned_pair_switch_race/publish.py
```

등록스크립트는 재실행하지 않는다. 보고서를 바꿨다면 중앙 결론과 등록해시를 갱신하고 final_review.py/record_inventory.py를 실행한다. 입력은 새 산출물 크기에 중복 계상하지 않는다. 운영 예측·DB·배포를 바꾸는 스크립트가 아니다.
