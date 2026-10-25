# 마체중 변화 분석의 출처와 범위

2026-10-08. [성별 연구 모집단](../20261007_sex_ability_gap/outputs/population.parquet)151,074행과 [선택 원장](../20261007_sex_ability_gap/outputs/selection_ledger.parquet)158,528행,기존 보관 KRA 원문18파일을 읽기 전용 사용했다. 입력20파일의SHA-256·기간·원문체중 및 증감 검사·누락/복원 수는 [source_audit.json](outputs/source_audit.json)에 있다. 전출전 성별·체중·공식 부담중량의 원문 연결과 정상 완주 선택은 [기존 출처](../20261007_sex_ability_gap/SOURCES.md)를 계승한다. 새 API를 호출하거나 운영 DB를 조회하지 않았다.

원문 wgHr의 괄호 수치가 있으면 raw_reported_change로 보존했다. 빈 괄호는 일괄0으로 처리하지 않았다. 과거 이력 마지막 날짜와 직전 관측 날짜가 같고 두 관측 체중도 같은9,464행만 verified_zero로 복원했다.684행은 미해결 결측이다. 차이가난187행은 [불일치표](outputs/reported_vs_observed_mismatches.csv)에 있고,날짜까지 일치한1건 제외 모형을 별도 남겼다. 원문 괄호값의 기준과 자료의 직전 관측이 언제나 일치한다고 가정하지 않는다.

평소 체중의 두 정의는 전체 관측 평균과 직전5개 관측 평균(최소3개·현재 제외)이다. 전자는 후향 기술 참조이고 후자는 과거 체중만 쓰지만 발표 당시 최초 확보 시각까지 복원한 것은 아니다. 둘의 표본과 정보 범위가 다르다. 보고서의 시간순 개인곡선 반복은 미래 기록 사전예측 검증이 아니다.

체중 변화·절대체중·자기 평균 대비 편차를 따로 적합했다. 과거 부담중량 연구의 kg 계수를 체중 kg의 손실로 재사용하지 않았다. 같은 말/경주와 이력 통제·민감도·지원·BH·수치허용오차는 [보고서](README.md)와 [계획 및 실행 보충](PLAN.md)에 있다. 개인 모형은 같은 경주 다른 말 평균에 대한 상대시간의 별도 탐색이며 공동 고정효과와 구분한다. 같은 경주 평균을 관측 결과로 계산하므로 사전 능력 예측이 아니다.

원문 증감 파싱·체중 기준·개인 회귀·희소 LU/QR·군집 합과 BH는 [verify.py](verify.py)에서 독립 계산했다. [verification.json](outputs/verification.json), [개인 탐색 결과](outputs/individual_summary.json), [전체 모형](outputs/models.csv), [대비표](outputs/contrasts.csv)를 보존한다. 생물학적 최적체중·인과 손실·개별 체중 처방·채택 보정으로 일반화하지 않는다.

기존 관련150파일의 크기·해시는 [baseline_inventory.json](outputs/baseline_inventory.json), 공유파일 수정직전과 작업별 변경량은 shared_edits_baseline.json/shared_own_edits.json, 자기포함 용량은 [artifact_inventory.json](outputs/artifact_inventory.json)에 있다. code-security의 고정경로/입력보존 기준과 pages:write-page의 주장·수치 검토 기준을 적용했다. 독립 연구수를 바꾸지 않는 기존11번의11C후속으로 연결한다.
