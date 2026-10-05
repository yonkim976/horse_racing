# 더러브렛 경주 조교사·마주 ID 예외 검토

2026-10-01에 core DB의 `confirmed_runners`에서 조교사·마주 원천 필드가 비어 있는 37행과 `0AAAAA`/`휴양마` 조교사 자리표시자 23행을 KRA 공식 성적표 원문으로 대조했다. DB, builder, 기존 38행 감사 원장은 수정하지 않았다.

## 결과

- KRA `ScoretableDetailList.do` 공식 페이지 60개를 사건별로 다시 받아 원본 HTML, 응답 해시, 요청 URL, 관측 UTC 시각을 저장했다. 60개 모두 HTTP 200이었고, 각 대상은 페이지의 시행장·날짜·경주번호와 말 마번·말 ID가 일치하는 단일 행으로 확인됐다.
- 결측 37행은 모두 해당 사건의 말 행에서 `goTrainer(ID, …)`와 `goOwner(ID, …)` 링크를 확인했다. 따라서 조교사 ID·이름과 마주 ID·이름을 공식 링크 ID와 같은 행에 표시된 이름으로 보완 검토값에 기록했다. ID는 앞자리 0을 포함한 문자열로 보존했다.
- 자리표시자 23행은 모두 공식 성적표에서도 조교사 ID `0AAAAA`, 이름 `휴양마`가 확인됐다. 23행은 의미 충돌이 없으며, 실제 인물로 변환하지 않았다. 보완 조교사 ID는 계속 null이다.
- 두 행의 말 이름은 API 원문과 성적표 표기가 달랐다. 2013-04-07 부산경남 5경주 15번 말 ID `0027864`는 API `[서울]에너지셀`, 웹 `[서]에너지셀`; 2016-12-24 서울 7경주 12번 말 ID `0031896`은 API `[부산경남]비바플라이`, 웹 `★[부]비바플라이`였다. 사건 키와 말 ID로 같은 행을 연결하고 양쪽 이름을 별도 필드로 보존했다.
- 에너지셀 행의 웹 링크에는 말·조교사·마주 프로필 시행장 코드 `1`이 들어 있으나 성적표 사건은 시행장 `3`이다. 프로필 코드가 경주 시행장과 다를 수 있음을 확인해 둘 다 별도 필드에 기록했다. 이 프로필 코드로 과거 관계를 추정하지 않았다.
- 대상 60행 모두 `positive_finish_evidence=0`이며 결과 순위 코드 `95`, 경주시간 `0`이다. 성적표의 조교사·마주 링크는 취소 전 편성 행의 연결 근거로만 해석한다.

## 결과물

- [최종 60행 JSONL 원장](race_role_review_results.jsonl): 정규화된 event key, 원천값, 검증 보완값, 웹 관측값, 원문 경로·해시, API4_3 및 기존 API26 재조회 근거를 한 행씩 기록한다.
- [최종 원장 manifest](race_role_review_manifest.json): 행 수, 상태별 수, 스키마, 정책과 산출물 해시를 기록한다.
- [공식 성적표 캡처 원장](official_scoretable_capture_manifest.json): 60개 URL, 관측 시각, 캡처 상태, 원문 파일과 SHA-256을 기록한다.
- [공식 성적표 파싱 원장](official_scoretable_runner_rows.jsonl): KRA 각주 링크 인자와 원문 행 텍스트를 보존한다.
- [공식 KRA HTML 원문](raw_kra_scoretable/): 이벤트별 원문 응답이다.

최종 원장 주요 필드는 `meet`, `date`, `race_no`, `horse_program_no`, `horse_id`, `source_kind`, `review_status`, `verified_supplemental_trainer_id/name`, `verified_supplemental_owner_id/name`, `official_web_source_file/hash`, `official_web_observed_at_utc`, `official_web_request_url`이다. 전체 필드 스키마와 null 값을 포함한 상태는 manifest와 JSONL에서 확인할 수 있다.

## 근거와 판정 규칙

원래 `API4_3/raceResult_3` 원문과 37개 결측 행의 2026-09-30 `API26_2/entrySheet_2` 재조회는 이전 감사 디렉터리에 있다. 이번 결과 원장은 해당 원문 파일의 SHA-256을 함께 기재한다. 기존 재조회 응답에서 37행의 API26 조교사·마주 ID는 계속 비어 있었다. RPT의 이름만으로 ID를 연결하지 않았다.

공식 성적표 페이지는 사건 키(시행장·날짜·경주번호)로 요청했고, 페이지에서 마번과 말 ID가 일치하는 단일 행을 찾았다. 역할 ID는 그 말 행의 `goTrainer` 및 `goOwner` 링크 인자에서만 읽었다. 프로필 링크의 시행장 인자는 별도로 기록했으며, 현재 프로필 관계를 과거에 소급 적용하지 않았다.

재생성 명령:

```sh
.venv/bin/python thoroughbred/research/20261001_race_role_review_v1/collect_official_scoretables.py
.venv/bin/python thoroughbred/research/20261001_race_role_review_v1/build_review_results.py
```
