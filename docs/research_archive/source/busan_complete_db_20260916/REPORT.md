# 부산경남 통합 연구 DB 구축 결과

기존 운영 DB와 원문을 수정하지 않고 부경 경주·주행심사·조교·진료·체중·장구·
임시 인물 ID 근거를 하나의 격리 SQLite로 통합했다.

최종 DB는 `busan_complete.sqlite3`이며 경주 15,577개·171,064출전,
주행심사 3,400개·29,762출전, 통합 이벤트 18,977개·200,826출전을 담는다.
연구용 경주 출전은 167,960행이고 주행심사 공식 말 ID는
29,757/29,762행이 확정됐다.

경주·심사 공통 키는 `(venue_code,event_kind,event_date,event_no)`와
`(event_id,participant_no)`다. 공식 경주는 `source_meet_label=부산경남`,
주행심사 API 원문은 `source_meet_label=영남`으로 각각 보존했다. 현재 자료는
부산 Text 및 역사적 시행 근거로 `venue_code=BUSAN`이 확인됐지만, 향후
`meet=3/영남` 주행심사는 부산·영천을 별도 확인하기 전 적재하지 않는다.

초기 `trial_result_text` 5,413행은 원천 대조용이다. 전체 주행심사 분석에는
`trial_entry` 또는 확정 행만 제공하는 `analysis_trial_entry`를 사용한다.
경주 전 통합 이력은 `analysis_race_entry_history`를 사용한다. 미확정 자료는
`quarantined_*` 뷰와 `issue_summary`에 남겼다.

검증 결과 SQLite 무결성은 `ok`, 외래키 위반은 0건, 미래 주행심사 연결은
0건이다. 원천 artifact 11,890건과 비밀키가 제거된 요청 63건을 DB 안에
등록했다. 전체 스키마와 뷰는 `catalog.json`, 독립 검증은
`independent_validation.json`, 완료 판정은 `completion_audit.json`, 파일 해시는
`manifest.json`에서 확인한다.

재현 명령:

```bash
PYTHONPATH=src .venv/bin/python scripts/build_busan_complete_db.py --force
PYTHONPATH=src .venv/bin/python scripts/verify_busan_complete_db.py --full-hash
```

전체 수집·정제·연결·향후 통합 규칙은
`docs/BUSAN_COLLECTION_AND_INGESTION_PROCESS_2026-09-16.md`에 정리했다.
