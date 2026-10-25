# 출처와 재실행

[50A의 출전별 분류](../20261012_planned_jockey_changes_by_stable/outputs/classified_starts.parquet)159,014행을 불변 참조한다. 원문 카드·공지 분류와 최초 게시본 불변성 미인증 한계는 [50A 출처](../20261012_planned_jockey_changes_by_stable/SOURCES.md)와 [검증](../20261012_planned_jockey_changes_by_stable/outputs/verification.json)을 따른다. [50C 후보표](../20261012_historical_planned_pair_switch_race/outputs/nominal_top3_candidates.csv)에서 양수인 네 조합을 고정했다. 원래213조합 BH를 통과한 후보는 없었다.

[사전계획](PLAN.md)은 연도별 결과를 보기 전에 연도/두기간/2026부분,고정분모BH,표본지원,검증을 정했다. 연도별 분모만 먼저 확인해 최근 표본 부재를 표시했다. 네 후보의 평소조합/변경항을 연도별 또는 기간별로 허용해 평소 조합의 수준 변화까지 고려했다. 해당기간에 새로 후보를 고르지 않았다.

[입력명세](outputs/source_audit.json)는 입력8개 경로·크기·SHA-256과 부분기간 종료일을 기록한다.50C의 순수 prepare/aggregate/fit과50의 controls/demean을 참조하고 이전 main은 실행하지 않았다. 새 원본 수집·DB 접근 없음. 결과 확인 뒤 별도의 조건별 분모 진단으로 연간100회 제한/다른 조건에 따른 범위 차이와 모든 원본 조합행의 부재도 확인했다. 이 진단은 추가 보정모형이 아니며 [범위검증](outputs/coverage_verification.json)에 사후 점검임을 표시했다. [이벤트](outputs/four_pair_switch_events.parquet)는 변경한 현재행과 직전행 키/현재결과·원문출처만 담으며 이후성과는 생성하지 않는다. 사후 말능력FE는 전체기간 관측으로 추정하므로 경주전 예측모형은 아니다.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_four_pair_annual_switch_race/analyze.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_four_pair_annual_switch_race/verify.py
OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_four_pair_annual_switch_race/coverage_audit.py
MPLCONFIGDIR=/private/tmp/horse_four_annual_mpl PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_four_pair_annual_switch_race/publish.py
```

등록은 재실행하지 않는다. 문서 변경 시 중앙/공유해시를 갱신하고 final_review.py/record_inventory.py로 확인한다. 원본참조·DB·임시캐시는 산출물 용량에서 제외한다. 운영 예측·DB·배포를 바꾸는 스크립트가 아니다.
