# 출처와 재실행

[50A의 출전별 분류](../20261012_planned_jockey_changes_by_stable/outputs/classified_starts.parquet)159,014행을 불변 참조했다. 예정/실제/변경사유·원문위치는 [50A출처](../20261012_planned_jockey_changes_by_stable/SOURCES.md), [원시 카드·공지 독립검증](../20261012_planned_jockey_changes_by_stable/outputs/verification.json)을 따른다. 출전표의 최초 게시본 불변성 미인증 한계는 유지한다. 새 원본 수집/DB접근 없음.

[입력명세](outputs/source_audit.json)는 입력5파일의 경로·크기·SHA-256,자료종료일과범위를 담는다. 기존50의 controls/demean/cluster_ci/metrics를 순수함수로 가져와 사용했으며 기존분석의 main/prepare는 실행하지 않았다. 원본 능력·순위·시간·이전기수 정합성과 연간순위는 [연구50검증](../20261012_jockey_switch_trainer_intent/outputs/verification.json)을 참조한다. 이번 모형은 상위기수더미를 사용하지 않고 현재기수의 지역×연도 주효과와 평소 조합 주효과를 추가했다.

[설계](PLAN.md)는 결과조회 전에 작성했고 전체기준/두대조/민감도를 고정했다. 연구50A와 같은 지원37조합임을 독립 확인했다. 교체·유지의 말/경주 지원까지 충족하는20개를 공동추정했다. [분모표](outputs/pair_support.csv)에는 지원미달 모든 조합도 남겼다. 원시 전후율·같은조합 유지대비 총차·기타조합 일반교체대비 추가차를 구분한다. 지원20개 외 조합에는 별도 조합주효과/상호작용을 두지 않는 모형 가정이 있다. 코너/기수 의지 등 미관측 요인은 생성하지 않았다.

재실행은 저장된 파일만 사용한다. 등록은 재실행하지 않는다.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261012_planned_trainer_jockey_pair_effects/analyze.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261012_planned_trainer_jockey_pair_effects/verify.py
MPLCONFIGDIR=/private/tmp/horse_jockey_pair_mpl PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261012_planned_trainer_jockey_pair_effects/publish.py
```

이후 공유등록해시를 갱신하고 final_review.py/record_inventory.py로 보존·게시내용·최종 용량을 재확인해야 한다. 입력파일을 새 산출물 크기에 중복 계상하지 않는다. 운영 예측·DB·배포를 변경하는 스크립트가 아니다.
