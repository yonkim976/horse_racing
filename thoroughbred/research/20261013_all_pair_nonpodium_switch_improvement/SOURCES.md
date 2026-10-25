# 출처와 재실행

[50A분류](../20261012_planned_jockey_changes_by_stable/outputs/classified_starts.parquet)159,014행과원문카드/변경공지의[검증](../20261012_planned_jockey_changes_by_stable/outputs/verification.json)을불변참조한다. [50C지원표](../20261012_historical_planned_pair_switch_race/outputs/pair_support.csv)의결과와무관한213조합을동결하고나머지조합도전수원시집계했다.이전입상률4후보는선정조건에쓰지않았다.새원본수집/DB접근없음.최초게시본불변성미인증유지.

[계획](PLAN.md)은개선정의/주사건/조건부보조/연도/최근/검정가족/지원/검증을사전에고정했다. 보조모형의연도별완결성을위한16모형추가는주사건결과확인뒤전수명단으로범위를넓힌탐색이며별도기록했다.주사건검정과후보명단을바꾸지않았다.

[입력명세](outputs/source_audit.json)는입력6개경로·크기·SHA-256과부분종료일을담는다.50C의prepare/design과50의controls/demean순수함수만참조하고이전main은실행하지않았다.추가직전시간차/함수율/출전두수는실제직전행키로조회하고SQLlag로대조했다.기록비교는지역/거리/등급·품질기록유효성을확인했다.일별주로빠르기보정은생성하지않았다.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_all_pair_nonpodium_switch_improvement/analyze.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_all_pair_nonpodium_switch_improvement/verify.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_all_pair_nonpodium_switch_improvement/extend_conditional_annual.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_all_pair_nonpodium_switch_improvement/verify_conditional_annual.py
MPLCONFIGDIR=/private/tmp/horse_nonpodium_mpl PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_all_pair_nonpodium_switch_improvement/publish.py
```

등록은재실행하지않는다. 문서변경시중앙/공유해시를갱신하고final_review.py/record_inventory.py를실행한다.기존원본/DB/임시캐시는신규용량에계상하지않는다.운영예측·DB·배포를변경하지않는다.
