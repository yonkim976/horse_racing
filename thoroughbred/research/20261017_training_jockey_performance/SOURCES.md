# 조교 기수 기승 성적 연구의 출처

분석일2026-10-17. 인터넷 신규 수집·운영DB 조회는 하지 않았다.

- 연구DB: `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`. 읽기전용 `daily_training_rider_linked`·`training_date_coverage` 사용. 원문 API 일별조교·공식ID·캡처원장·날짜별 완전수집 상태는 DB의 provenance 열에 남아 있다. 원시 사건자료를 이번 폴더에 중복 복제하지 않았다.
- [기승자ID 연결](../20261015_daily_training_rider_links_v1/README.md): 공식ID 일치·미연결·충돌보류의 근거.2026프로필은 당시 역할의 근거로 쓰지 않는다.
- [080626 동일 사건 이름 연결](../20261015_daily_training_event_names_v1/README.md): 다비드 이름은 확인됐으나 공식ID는NULL이므로출전기수 일치로쓰지 않는다.
- [기승자 역할 검증](../20261015_training_rider_roles_followup_v1/README.md): API의미상·조교승인·조교보와 홈페이지의기수·기수트랙라이더·주로조교를 임의로같게 취급하지 않는다. 과거 API 기수표기에기수트랙라이더가포함됐을가능성을 남긴다.
- 출전입력: [신원검증159,014행 원장](../20261012_jockey_switch_trainer_intent/outputs/analysis_rows.parquet). 실제 출전기수·말·조교사·날짜·착순과과거 이력. 해당연구의기수교체전용지원제한은이번에쓰지 않았다. 원장에원문파일·항목번호·행키가 있다.
- 정제시간의근거는기존[성별연구 모집단](../20261007_sex_ability_gap/README.md)의151,074품질시간과현재출전입력의 `quality_time` 연결이다. 우승·입상은정상착순 원장으로더넓게평가한다.
- 수치방법 재사용: [기수교체 연구 코드](../20261012_jockey_switch_trainer_intent/analyze.py)의FE 투영·군집분산·BH 함수만가져왔다. 입력준비·학습·원 연구의main은실행하지 않았다.
- [최근 홈페이지 조교인력 표시](../../../docs/TRAINING_WEBSITE_RIDER_EVIDENCE_2026-10-17.md)는API 역할 한계를알리는참고다. 현재출전입력 종료일이후자료를과거노출로합치지 않았다.

입력파일·코드 SHA256와크기는[원천 감사](outputs/source_audit.json), 실제사용역할은[역할분포](outputs/source_role_audit.csv),전체날짜지원은[날짜감사](outputs/source_calendar_coverage.csv)에 보존했다. 기존DB 해시는이전연구문서의과거해시를인용하지않고이번 실행시의파일을직접 계산했다.
