# 서울 `text:` 임시 ID와 공식 API ID 연결

`text:`는 KRA가 발급한 ID가 아니다. 운영 DB의 `dacom11` Text 적재기가 공식 번호를
찾지 못할 때 만든 **이름 기반 임시 해시**다. 기수·마주 해시는
`SHA256(0|정규화이름||)`의 앞 24자리, 조교사는 경마장 번호 1을 사용한다.
말은 `SHA256(경마장|정규화마명|추정 출생연도|성별)` 앞 24자리다.
예를 들어 `text:jockey:8d925be0e094ce96a3a2abfe`는 `김영진`이라는
이름의 임시 키다. 같은 이름이 같은 공식 인물임을 증명하지 않는다.

완료된 서울 운영 DB의 출전행 **67,709개**에서 임시 ID 사용
**102,205건**을 찾았다. 공식 결과의 경주일·경주번호·공식 말 ID 또는
출전번호와 마명을 확인하고, 해당 API 원문 행의 공식 인물 번호를 재검증했다.
그 결과 경주 당시 인물 관계 **102,194건**을 확인했다. 이 관계는
`entry_linkage.csv`에서 경주행마다 조회한다. 이름 불일치가 있어도 당시 공식
결과의 인물 번호는 보존하되, 임시 ID의 전역적 인물 동일성은 승인하지 않았다.

임시 ID **961개** 중 공식 ID가 관측 범위에서 하나이고 매 경주의
이름·출전관계가 모두 맞는 **636개**만
`confirmed_single_official_id`다. 나머지 **325개**는 다중
공식 ID 21개, 이름 충돌 302개,
말 출전관계 미확정 2개다. `temporary_id_link.csv`와
`unresolved_identity.csv`에 후보·근거행 수·기간을 남겼다. 이름만으로
모든 과거 이력을 일괄 치환하지 않는다.

특히 운영 DB의 `text:a6eb38321c4ca2ebb9dc9366`은 **마이공주**다.
2022-03-27~2023-02-19의 9개 보존 `dacom11` Text도 마이공주라고 쓰지만,
같은 경주·출전번호의 공식 결과는 9개 모두 **마이왕자 (`0044830`)**다.
`horse_name_conflicts.csv`에 두 원문 경로·해시와 공식 행 번호를 남겼다.
이것은 동일 말이라고 승인할 근거가 없으므로 미해결로 유지한다.

`entry_linkage.csv`는 임시 ID가 쓰인 **출전행별 관계**, `temporary_id_link.csv`는
임시 ID별 **전역 동일성 판정**, `candidate_evidence.csv`는 후보 공식 ID별
근거 건수·표본 원문 위치다. `relationship_status`가
`confirmed_race_time_relation`이어도 `identity_status`가 미해결일 수 있다.
기존 운영 DB와 서울 백필 DB는 읽기 전용으로 열었고 변경하지 않았다.

프로젝트 루트에서 `.venv/bin/python scripts/link_seoul_text_ids.py`로 재현한다.
`sha256_manifest.csv`는 입력 DB, 사용한 공식/Text 원문, 출력 CSV·JSON,
실행 코드의 SHA256을 기록한다. DB에 WAL이 있을 수 있으므로
`summary.json`에는 실제 읽은 운영 출전행의 순서 있는 SHA256도 기록했다.
