# 통합 목록 사전 해시 차이의 처리

첫 `publish.py` 실행은 통합 manifest가 기록한 이전 `jeju/AGENTS.md` 해시와 현재 파일이 다름을 발견해 **어떤 게시 파일도 수정하기 전에 종료**했다. 연구 계산/검증은 통과 상태이며 결과를 재추정하지 않았다.

`prepublication_audit01.json`에서 기존1,964항목을 전수 확인했다. 작업 시작 전부터 바뀐 것은 `jeju/AGENTS.md`, `jeju/README.md`, `jeju/review_documents/README.md`, `jeju/data/jeju_native_core.sqlite3` 네 경로다. 최신 지침과 문서가 연결한2026-10-15 조교 기승자 실명/종류 적용 이력이며 이번 출전간격 연구가 수정한 파일이 아니다.

종류 적용의 `application_manifest.json`은 applied_and_independently_verified, 독립 전수검증은passed이며 DB SHA c52d2ab941ec9b53829891b59db660fbd789cd5e5e27192f9401c1f1f83d158d가 이번 읽기 전후 해시와 일치한다. 적용 manifest가 나열한 근거 파일 해시도 재확인한다. 네 현재 파일은 수정하지 않는다.

후속 `publish_v2.py`는 위 네 경로만 예외로 허용하고 관측된 현재 해시가 재변경되지 않았는지 검사한다. 이전 manifest의 해시는 snapshot과 사전차이 원장에 보존하며 통합현재목록의관측메타데이터만갱신한다. 기존 연구 산출물의불변과운영/DB미수정상태는별도로검증한다. 이전 DB 파일이나지침이불변이었다는주장은하지않는다. 나머지1,960기존항목은변경없이검증하고,기존27주제객체는그대로보존한다.
