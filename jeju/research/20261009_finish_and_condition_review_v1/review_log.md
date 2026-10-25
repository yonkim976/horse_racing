# 독립 연구 검토 기록

2026-10-09. 이 폴더는 `finish_history_ablation`과 `special_condition_audit`의 독립 검토 산출물만 담는다. DB, 운영 모델·등록부, 기존 실험 원본과 두 담당 에이전트의 코드는 수정하지 않는다. 중앙 결론 모음은 이 검토 범위에 포함하지 않는다.

## 사전 검토

- `jeju/AGENTS.md`, `jeju/docs/RESTART_PLAN_20260928.md`, `jeju/research/RESEARCH_PUBLICATION_POLICY.md`, code-security `SKILL.md`와 SQL injection/path traversal 관련 규칙을 읽었다.
- 기존 J0/R1 결과는 2017년 이후 학습, 평가연도별 시간 분할, 직전 연도 온도 보정, 동일한 평가 말/경주에서 재학습한 J0 재현을 갖춘 이미 사용된 후향 개발 비교다. 2024–2026을 독립 미래 검증으로 부르지 않는다.
- F1/F2의 주요 감사 경계는 `source_snapshot.parquet`의 기존 `started` 정의(정상 순위 1–89 또는 91/92), 실제 출전자 수 분모, 직전 경주 전체의 착순 완결성, 개별 말의 비정상 착순 결측 유지, 최근 5회 창 슬롯 유지, T−2 및 공식 ID 계보다.
- Root는 직전 결과 상태 열을 세 범주로 유지하는 최소 입력 설계를 승인했다. 전체 경주만 불완전한 경우에도 개별 말의 정상 착순/Top3를 직접 보존하고, 개별 착순 무효/비정상은 `previous_top3=NULL`로 구별한다. 독립 검증은 NaN을 0으로 대체하지 않는지 확인한다.
- 2026 운영 비교는 기존 공통 467경주·4,475출전으로 별도 평가해야 한다. 1,779경주 전체 연구 지표와 같은 표·분모로 합치지 않는다.
- 순차 유지 기준의 사전 해석은 사용자 권한을 받은 root 감독관이 명확화했다. F1−R1 gate가 통과한 경우에만 F2−F1 gate를 다음 단계로 평가하고, 두 gate가 모두 통과할 때만 F2를 다음 순차 연구의 후보로 삼는다. F1이 실패하면 F2−F1만으로 R1 대체나 F2 유지 주장을 하지 않는다. F2−R1은 보조 비교다. 각 모형은 설계대로 학습·보고한다. 이 결정은 원 잠금 계약을 고치지 않고 본 검토 폴더의 별도 사전결정 파일에 기록한다.
- 특별조건 S1의 공백 시퀀스는 0/93/98 불명 행에서 censor하고, 94/95/99는 기존 non-start로 유지한다. S2의 `same_starts=0`은 관측된 정확 거리 출전 이력 0으로만 해석하며 공식 첫 거리로 부르지 않는다.

## 모집단 count 정정

초기 독립 확인 메시지에서 SQLite `race_result_rows` 전체 질의의 status 빈도를 `source_snapshot.parquet` 빈도로 잘못 전달했다. 그 SQL 결과는 연구 입력 스냅샷의 집계가 아니므로 본 연구 증거로 사용하지 않는다. 직접 확인한 기존 `source_snapshot.parquet` 기준은 92,513행·9,494경주이며, 코드별 빈도는 0=20, 91=163, 92=55, 93=18, 94=313, 95=367, 98=10, 99=1,357행이다. 이 스냅샷의 `started`는 정상 순위 1–89 또는 91/92에 대해서만 true이며, 다른 코드의 의미는 임의로 재분류하지 않는다. 91/92의 한글 의미를 이 스냅샷만으로 추정하지 않는다.

## 후속 검증 상태

`finish_history_ablation_v1/verify.py final()`은 저장 확률 주변합과 6조합은 검사하지만 저장 모델 재로딩, calibration 재계산, 손실·경주 지표 및 paired 구간 재계산을 확인하지 않는다. `training_completion.json`의 모형/학습호출/보정 개수는 상수로 기록되므로 실행 사실을 단독 입증하지 않는다. 이 검증 범위의 공백은 독립 `verify_finish_history_outputs.py`에서 보완한다. 모델 출력이 생성되면 이 독립기로 입력 계보·계산 산술·9개 저장 모형(R1 3개와 F1/F2 6개)·확률/조합·지표·대표 bootstrap·운영 공통 집합을 확인한다. 별도 특별조건 출력은 데이터 계보와 기간/분모·unknown 처리·타깃 결과 교란 불변을 확인한다. 검토 결과 파일이 추가되면 이 로그에 구체적인 파일과 상태를 기록한다.

## F1 조건 보충 독립검증 중단 사항

- `jeju/research/20261009_special_condition_audit_v1/supplement_f1.py:204-213`에서 전체 기간 S2 격자는 모든 연도의 `primary_grid` 행으로 `cell_summary`를 계산한 뒤, `F1_rows`와 잔차만 해당 `period`의 F1 보충표 조회 결과로 다시 덮어쓴다. `period=all`에는 F1 보충표 셀이 없으므로 `F1_rows=0` 및 잔차 NULL로 바뀌지만, `mean_p_F1`은 전체 입력에서 최근 F1 확률을 집계한 값으로 남는다. 독립 재계산은 전체 scope 12개 중 실제 관측된 6개에서 `F1_rows=0`과 `mean_p_F1` 비NULL 불일치를 확인했다. 이 요약은 확률과 표본 분모가 불일치하므로 수리 전 보충 검증을 PASS 처리하지 않는다.
- 원본 격자 파일은 보존하고, 별도 v2를 생성해 불일치 6개 `mean_p_F1`을 NULL로 두고 수리 내역/원본 해시를 추적한다. 독립기는 v2를 같은 scope 정의로 다시 계산한 뒤에만 PASS한다. 확인한 원본 격자 SHA-256은 `fefae9d136744b9dba89634e986d49d12b9423f75eefd963e30d62813b11bdff` (62,997 bytes)이며, 수정 이전값이다.
- v2 검증 완료: [독립 receipt](f1_condition_supplement_independent_verification.json)는 F1 고정표본 17,412행·1,779경주 연결, 경주별 Top3 확률합 3, 조건 통계/날짜 구간 301행씩, S2 26 scope×12셀 312행, 원 통계 575행 불변, 200행 타깃 결과 교란 불변과 입력 해시를 독립 재계산해 PASS했다. 6셀 수정은 `mean_p_F1`만 NULL로 바뀌었고 원본 격자 SHA/바이트와 repair receipt를 일치 확인했다. 이 검사는 기존 후향 비교의 계산 독립 재현이지 독립 미래 검증이 아니다.

## 중앙 출판 전 인벤토리 대조

- 중앙 README·SOURCES·register·source_manifest의 사전 바이트 백업은 `central_backup/pre_publication_20261009/`에 보존했고 각 원 해시를 `central_prepublication_lock.json`에 기록했다.
- 이전 중앙 `source_manifest.json`의 835개 경로 중 834개는 현재 내용과 해시가 일치했다. 예외 `jeju/README.md`는 이 발행 작업 전에 이미 변경된 상태였으며(기존 등록 8,636 bytes/SHA `6fa6aea8…348907288`, 확인 파일 9,094 bytes/SHA `0620f083…1feebe3fc`), git diff에는 기존 결론 링크와 축 동반 연구 문구가 있다. 이 파일 자체는 수정하지 않고 새 source manifest에 현재 해시만 반영한다. 원 manifest 백업은 기존 등록값을 보존한다.
