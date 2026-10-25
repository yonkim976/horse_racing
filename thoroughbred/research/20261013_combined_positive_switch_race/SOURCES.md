# 출처와 재실행

[50A분류](../20261012_planned_jockey_changes_by_stable/outputs/classified_starts.parquet)159,014행과원문카드/공지의[검증](../20261012_planned_jockey_changes_by_stable/outputs/verification.json)을불변참조한다.50E의[사례정의/실제직전/검증](../20261013_all_pair_nonpodium_switch_improvement/outputs/verification.json)을참조하고입상과비입상개선을OR로합쳤다. 이전결과후보는선정조건이아니며동결213개는분모기준으로선정된기존명단이다.새원본수집/DB접근없음. 최초카드불변성미인증유지.

[계획](PLAN.md)은새통합결과조회전에세기준·분모·결측·중복·보정·기간·BH가족·지원/검증을고정했다. [입력명세](outputs/source_audit.json)는입력8개경로·크기·SHA-256과부분종료일을담는다.50E의prepare/fit/controls와50C/50의순수함수만참조하며이전main은실행하지않았다. 목표는현재한경주,능력FE는각기간사후통계다. 새로운일별주로빠르기보정을생성하지않았다.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_combined_positive_switch_race/analyze.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_combined_positive_switch_race/verify.py
MPLCONFIGDIR=/private/tmp/horse_combined_positive_mpl PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261013_combined_positive_switch_race/publish.py
```

등록은재실행하지않는다. 문서변경시중앙/공유해시를갱신하고final_review.py/record_inventory.py를실행한다.기존원본/DB/임시캐시는신규용량에서제외한다.운영예측·DB·배포를변경하지않는다.
