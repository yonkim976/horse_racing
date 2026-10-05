# 조교사·마주 연결 예외 검토 및 코어 DB 반영

> 2026-10-01 후속 처리: 심사 조교사 22행은 [말 프로필·결측 원인 검토](../20261001_trial_22_profile_absence_review_v1/README.md) 후 사용자 지시에 따라 조교사 ID·이름의 원인 미상 오류값으로 검토 종료했다. 원문 및 아래 최초 미확정 목록은 보존하고, 현재 코어 조회에는 오류 처리 분류를 표시한다.

2026-10-01, 기존 미연결 경주 조교사 60행·마주 37행과 심사 조교사 224행을 확인하고 [코어 DB](../../data/core_api_2010_20260929_v1/thoroughbred_core.duckdb)에 반영했다. 대상 사건 범위는 2010-01-01~2026-09-29이며 연구 사용 시작은 2017년이다. 조사·독립 검증 서브에이전트는 사용자 지정 `gpt-6-luna`, `xhigh`를 사용했고, 주 에이전트가 HTML 링크를 다시 파싱하고 적재를 검증했다.

## 결과

| 대상 | 검토 전 인물 ID 미연결 | 이번 보완 | 현재 남은 분류 |
|---|---:|---:|---|
| 경주 조교사 | 60 | 37 | 공식 비인물 `휴양마` 23 |
| 경주 마주 | 37 | 37 | 0 |
| 심사 조교사 | 224 | 61 | 공식 비인물 141, 미확정 22 |

- 경주 60개와 심사 221개의 공식 성적표 원문을 확보했다. 경주 보완 37행의 조교사·마주 ID는 같은 사건의 말 행에 있는 `goTrainer`·`goOwner` 링크에서 직접 확인했다. 모두 출전취소 기록이므로 실제 완주나 기승의 근거로 사용하지 않는다.
- 심사 `-` 84행 중 61행은 정확한 시행장·날짜·심사차수·마번·말 ID·기록시간이 일치하는 공식 표의 `goPage3` 조교사 ID로 보완했다. 61행은 양수 기록시간 1행과 0초 60행이다. 양수 기록시간 보완 사례는 2020-08-28 서울 5차 5번 캡틴불릿, 배휴준 `070144`, 62.8초다.
- 심사 원천 `0AAAAA`/`휴양마` 140행은 공식 표에서도 같은 표기다. 2019-04-19 서울 1차 7번 큐비트업은 API가 `-`지만 공식 표에는 `0AAAAA`/`휴양마`로 표시돼 비인물 예외에 추가했다. 이들에 인물 ID를 넣지 않았다.
- [미확정 심사 조교사 22행 목록](unresolved_trial_trainers_22.csv)은 공식 사건 페이지를 확인했지만 해당 마번의 참가자 행이 표시되지 않는다. 양수 기록시간 19행·0초 3행이다. API 원장 기록은 보존한다. 표에서 행이 빠진 이유와 API 내부 결측 원인은 공식 근거가 없어 단정하지 않는다. 일부 RPT에 조교사 이름이 있어도 이름만으로 ID를 채우지 않았다.
- 경주 성적표의 에너지셀·비바플라이 두 행에 API와 다른 마명 접두어 표기가 있었다. 말 ID·마번으로 대조하고 양쪽 이름을 보존했다. 에너지셀의 사건은 부산경남이지만 프로필 링크는 서울을 가리킨다. 프로필 링크의 지역 코드는 사건 시행장과 구분했다.

현재 경주 330,465행은 마주 ID 330,465·조교사 ID 330,442행이 연결된다. 심사 61,777행은 조교사 ID 61,614행이 연결된다. 말·기수의 기존 연결 결과와 출전·심사 원문은 유지됐다.

## 적재와 검증

- `race_trainer_owner_review` 60행, `trial_trainer_review` 224행은 적재용 정규화 원장이다. 각각의 `_evidence` 테이블에는 요청 URL·시각·원문 해시·공식 링크·API 원문 위치·RPT 보조 근거 등 전체 검토 JSON을 보존한다.
- `confirmed_runners_entity_reviewed`, `trial_participants_entity_reviewed`의 `*_entity_id_with_review`, `*_name_with_review` 열은 보완을 포함한 조회 결과다. 원문 ID·이름과 API 직접 연결 열은 변경하지 않았다.
- `role_link_exceptions_current` 186행은 확정 비인물 대체표기 164행과 실제 미확정 22행이다. 최초 원천 감사 `unresolved_entity_references` 5,548행은 원천 결측 이력이며 현재 미확정 수가 아니다.
- [주 에이전트 검증](root_verification.json): 적재 전후 `runner_results`, `trial_participants`, `race_events`, `entity_reference_roster` 전체 행을 양방향 `EXCEPT ALL`로 대조해 차이 0건을 확인했다. 기존 말·기수 연결 값도 차이 0건이며 DB 해시는 매니페스트와 일치한다.
- [독립 검증 통과](../20261001_role_independent_validation_v1/README.md): 경주 60행·심사 224행의 사건 키와 원문 해시, 공식 HTML의 같은 말 행에 있는 보완 ID, 정규화 원장과 DB의 일치를 재검증했다. [세부 검증 결과](../20261001_role_independent_validation_v1/validation.json)에 체크와 해시를 보관한다.
- 빌더 검증 **54개 전부 통과**. 사건·말 키 일치, 인물 ID 문자열·앞자리 0 보존, 공식 HTML 링크 ID 대조, 보완 ID의 기존 기준정보 존재, 행 수 유지, 비인물 표기의 인물 연결 방지를 확인했다. 적재 전 DB·매니페스트는 `thoroughbred/data/core_api_2010_20260929_v1/backups/20261001_before_trainer_owner_review/`에 보관했다.
- 원문 ID가 있는 경주 1행은 API 마주명만 없다: 2026-08-09 서울 5경주 11번 퀸즈플라잉, 마주 ID `010424`. ID 연결은 확인되며 현재 프로필 이름으로 과거 사건의 이름을 추정하지 않았다.

이 검토는 기준정보 연결 예외에 대한 보완이다. 코어 DB의 최종 동결과 후속 데이터 적재는 별도 단계다. 공식 표를 2026-10-01에 조회한 사실을 보존하며, 사건별 관계 ID를 보완한 근거를 예측 시점 이전에 수집된 피처로 간주하지 않는다.

## 원천 및 재현

- [경주 60행 공식 원문 감사](../20261001_race_role_review_v1/README.md)
- [심사 224행 공식 원문 감사](../20261001_trial_trainer_review_v1/README.md)
- [정규화 원문 해시 매니페스트](manifest.json)
- [코어 DB 매니페스트](../../data/core_api_2010_20260929_v1/manifest.json)

저장소 루트에서 실행한다.

```sh
.venv/bin/python thoroughbred/research/20260929_core_api_db_v1/normalize_role_reviews.py --race-jsonl thoroughbred/research/20261001_race_role_review_v1/race_role_review_results.jsonl --trial-jsonl thoroughbred/research/20261001_trial_trainer_review_v1/trial_trainer_gap_review.jsonl
.venv/bin/python thoroughbred/research/20260929_core_api_db_v1/build_core_db.py
```

정규화 단계에서 원문 SHA-256과 정확한 말·마번의 HTML 링크 ID·심사 기록시간을 다시 검사한다. 새 파일 경로나 공식 ID가 기존 근거와 다르면 적재를 중단한다.
